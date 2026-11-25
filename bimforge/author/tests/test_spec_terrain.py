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


def plane_tiff(url, plane):
    """The DEM the request asks for, its pixel centres on `plane(e, n)`
    (metres, the request's CRS units in plan)."""
    Image = pytest.importorskip("PIL.Image")
    from urllib.parse import parse_qs, urlparse
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    x0, y0, x1, y1 = (float(v) for v in q["bbox"].split(","))
    cols, rows = (int(v) for v in q["size"].split(","))
    es = x0 + (np.arange(cols) + 0.5) * (x1 - x0) / cols
    ns = y1 - (np.arange(rows) + 0.5) * (y1 - y0) / rows      # row 0 north
    z = np.array([[plane(e, n) for e in es] for n in ns], dtype="float32")
    buf = io.BytesIO()
    Image.fromarray(z, mode="F").save(buf, format="TIFF")
    return buf.getvalue()


def offline(monkeypatch, calls=None, plane=None):
    """3DEP answered locally: the DEM a flat 30.48 m, or `plane` over the
    requested bbox; the work-unit index one feature."""
    def fake(url, timeout):
        if calls is not None:
            calls.append(url)
        if "exportImage" in url:
            return _Resp(tiff() if plane is None else plane_tiff(url, plane))
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


US_FT = 1200.0 / 3937.0


def example_plane(e, n):
    """The shipped corridor's ground: {source: plane} (300 ft at its point of
    beginning, rising 0.02 north and 0.04 east), in metres. Flat ground
    puts its fills and walls where the example lists a wall gap."""
    return (300.0 + 0.02 * (n - 1943000.0) + 0.04 * (e - 6594000.0)) * US_FT


def corridor_spec(tmp_path, ground, terrain=None, name="rc.spec.yaml"):
    s = yaml.safe_load((EX / "road-corridor.spec.yaml").read_text())
    s["paycodes"] = str(EX / "road-corridor.paycodes.yaml")
    s["outputs"] = {"ifc": str(tmp_path / "out" / (name + ".ifc"))}
    s["project"]["vertical_datum"] = "NAVD88"
    s["params"]["ground"] = ground
    if terrain is not None:
        s["terrain"] = terrain
    p = tmp_path / name
    p.write_text(yaml.safe_dump(s), encoding="utf-8")
    return p


def test_the_0_1_132_ground_builds_the_same_ifc(tmp_path, monkeypatch, capsys):
    offline(monkeypatch, plane=example_plane)
    # 15 m cells, about the plane's own 50 ft: the corridor voids its cuts
    # out of the mesh, and 3 m cells take minutes per build
    cache = str(tmp_path / "t" / "ml")
    old = corridor_spec(tmp_path, {"source": "3dep", "cache": cache,
                                   "spacing_m": 15.0}, name="old.yaml")
    new = corridor_spec(tmp_path, {"source": "terrain"},
                        {"cache": cache, "spacing_m": 15.0}, name="new.yaml")
    assert R.build_from_spec(old) == 0
    assert "ground: source 3dep is now terrain:" in capsys.readouterr().err
    assert R.build_from_spec(new) == 0
    a = (tmp_path / "out" / "old.yaml.ifc").read_text().splitlines()
    b = (tmp_path / "out" / "new.yaml.ifc").read_text().splitlines()

    def strip(lines, name):
        # only what names the spec: the BIMForge_Model set's BuildId (the
        # spec source's hash) and Source (its file name). The header's
        # timestamp is fixed, so it stays in.
        return [line for line in lines
                if "'BuildId'" not in line and f"IFCLABEL('{name}')" not in line]
    assert len(strip(a, "old.yaml")) == len(a) - 2
    assert strip(a, "old.yaml") == strip(b, "new.yaml")


def test_the_old_ground_and_a_terrain_block_are_refused(tmp_path):
    p = corridor_spec(tmp_path, {"source": "3dep", "cache": "x"}, {"cache": "x"})
    with pytest.raises(ValueError, match="both name the ground"):
        R.load_spec(p)


def test_a_plane_corridor_with_terrain_carries_one_ground(tmp_path, monkeypatch):
    import ifcopenshell
    offline(monkeypatch, plane=example_plane)
    s = yaml.safe_load((EX / "road-corridor.spec.yaml").read_text())
    p = corridor_spec(tmp_path, s["params"]["ground"],
                      {"cache": str(tmp_path / "t" / "ml"), "spacing_m": 15.0})
    assert R.build_from_spec(p) == 0
    f = ifcopenshell.open(str(tmp_path / "out" / "rc.spec.yaml.ifc"))
    grounds = [e for e in f.by_type("IfcGeographicElement")
               if e.PredefinedType == "TERRAIN"]
    assert len(grounds) == 1 and "3DEP" in grounds[0].Name


def test_the_old_ground_without_cache_names_the_file_and_the_form(tmp_path):
    p = corridor_spec(tmp_path, {"source": "3dep"})
    with pytest.raises(ValueError,
                       match=r"rc\.spec\.yaml: ground: source 3dep: needs `cache`"):
        R.load_spec(p)


def test_the_old_ground_without_epsg_names_the_old_form(tmp_path):
    p = corridor_spec(tmp_path, {"source": "3dep", "cache": "x"})
    s = yaml.safe_load(p.read_text())
    s["project"]["epsg"] = None
    p.write_text(yaml.safe_dump(s), encoding="utf-8")
    with pytest.raises(ValueError, match="ground: source 3dep needs project.epsg"):
        R.load_spec(p)


def test_params_terrain_is_reserved(tmp_path):
    p = b3_spec(tmp_path)
    s = yaml.safe_load(p.read_text())
    s["params"]["terrain"] = {"cache": "x"}
    p.write_text(yaml.safe_dump(s), encoding="utf-8")
    with pytest.raises(ValueError, match="params.terrain is reserved.*top-level "
                                         "`terrain:` block"):
        R.load_spec(p)


def test_a_wall_with_terrain_passes_the_validators(tmp_path, monkeypatch):
    import ifcopenshell
    import ifcopenshell.validate as V
    offline(monkeypatch)
    p = b3_spec(tmp_path, {"cache": "terrain/site", "spacing_m": 3.0})
    assert R.build_from_spec(p) == 0
    f = ifcopenshell.open(str(tmp_path / "out" / "b3.ifc"))
    log = V.json_logger()
    V.validate(f, log)
    assert not log.statements, log.statements[:3]
