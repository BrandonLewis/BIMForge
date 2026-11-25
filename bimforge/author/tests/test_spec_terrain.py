"""A spec's terrain: block (G.9): parsed, translated, added once.

Offline: 3DEP's transport is replaced; the DEM is a flat float32 TIFF."""
import io
import json
from pathlib import Path

import numpy as np
import pytest
import yaml

from bimforge.author.families import registry as R
from bimforge.terrain import fetch as F

EX = Path(R.__file__).resolve().parents[1] / "examples"


def tiff(rows=40, cols=40, z_m=30.48):
    Image = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    Image.fromarray(np.full((rows, cols), z_m, dtype="float32"), mode="F").save(
        buf, format="TIFF")
    return buf.getvalue()


class _Resp:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


def offline(monkeypatch, calls=None, z_m=30.48):
    """3DEP answered locally: the DEM a flat `z_m` metres, the work-unit
    index one feature."""
    def fake(url, timeout):
        if calls is not None:
            calls.append(url)
        if "exportImage" in url:
            return _Resp(tiff(z_m=z_m))
        return _Resp(json.dumps({"features": [{"attributes": {
            "project": "CA_Test", "workunit": "W1", "collect_start": 0,
            "collect_end": 0, "ql": "QL2"}}]}).encode())
    monkeypatch.setattr(F, "_urlopen", fake)


def b3_spec(tmp_path, terrain=None, vertical_datum="NAVD88", **extra):
    s = yaml.safe_load((EX / "caltrans-b3-retaining-wall.spec.yaml").read_text())
    s["params"]["tables_file"] = str(EX / "caltrans-b3-tables.example.yaml")
    s["paycodes"] = str(EX / "caltrans-b3-retaining-wall.paycodes.yaml")
    s["outputs"] = {"ifc": str(tmp_path / "out" / "b3.ifc")}
    s["project"]["vertical_datum"] = vertical_datum
    if terrain is not None:
        s["terrain"] = terrain
    s.update(extra)
    p = tmp_path / "b3.spec.yaml"
    p.write_text(yaml.safe_dump(s), encoding="utf-8")
    return p


def test_load_spec_parses_the_block(tmp_path):
    spec = R.load_spec(b3_spec(tmp_path, {"cache": "terrain/site"}))
    ts = spec["_terrain"]
    assert ts.cache == str((tmp_path / "terrain" / "site").resolve())
    assert "terrain" not in spec["params"]


@pytest.mark.parametrize("terrain, project, match", [
    ({"source": "srtm", "cache": "x"}, {}, "not dem or lpc"),
    ({"cache": "x"}, {"epsg": None}, "terrain: needs project.epsg"),
])
def test_load_spec_refuses(tmp_path, terrain, project, match):
    p = b3_spec(tmp_path, terrain)
    s = yaml.safe_load(p.read_text())
    s["project"].update(project)
    p.write_text(yaml.safe_dump(s), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        R.load_spec(p)


def _terrain_pset(element):
    for rel in element.IsDefinedBy:
        if not rel.is_a("IfcRelDefinesByProperties"):
            continue
        pd = rel.RelatingPropertyDefinition
        if pd.Name == "Pset_BimforgeTerrain":
            return {p.Name: p.NominalValue.wrappedValue
                    for p in pd.HasProperties}
    raise AssertionError("no Pset_BimforgeTerrain")


def test_a_b3_wall_gets_one_ground_around_it(tmp_path, monkeypatch, capsys):
    import ifcopenshell
    offline(monkeypatch)
    p = b3_spec(tmp_path, {"cache": "terrain/site", "margin_ft": 30.0,
                           "spacing_m": 3.0})
    assert R.build_from_spec(p) == 0
    f = ifcopenshell.open(str(tmp_path / "out" / "b3.ifc"))
    (g,) = [e for e in f.by_type("IfcGeographicElement")
            if e.PredefinedType == "TERRAIN"]
    # contained where the model's every element is (emit_ifc's default
    # container: the storey on the IFC4 building path), as the corridor's
    # TERRAIN is
    container = g.ContainedInStructure[0].RelatingStructure
    (wall,) = [e for e in f.by_type("IfcWall")][:1]
    assert container == wall.ContainedInStructure[0].RelatingStructure
    prov = _terrain_pset(g)
    assert prov["Source"] == "USGS 3DEP 1m DEM"
    assert prov["VerticalShiftSource"] == "NAVD88: none"
    assert prov["QualityLevel"] == "QL2"
    assert (tmp_path / "terrain" / "site-3DEP-DEM.tif").exists()


def test_the_build_needs_a_datum_rule(tmp_path, monkeypatch, capsys):
    offline(monkeypatch)
    p = b3_spec(tmp_path, {"cache": "terrain/site"}, vertical_datum=None)
    with pytest.raises(ValueError, match="has no rule"):
        R.build_from_spec(p)


def test_a_spec_without_terrain_is_unchanged(tmp_path, monkeypatch):
    def never(url, timeout):
        raise AssertionError(url)
    monkeypatch.setattr(F, "_urlopen", never)
    assert R.build_from_spec(b3_spec(tmp_path)) == 0
