"""Excavation as ground REMOVED: an IfcEarthworksCut that voids the ground.

`Element.voids` names the host. The cut is emitted as itself, related by
IfcRelVoidsElement, kept out of the spatial tree (a feature hangs off its
host), and keeps its quantities; the ground draws with the hole.
"""
from __future__ import annotations

import uuid

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402

FT3 = (1200.0 / 3937.0) ** 3


def _prism(x0, x1, y0, y1, z0, z1):
    return {"kind": "prism", "units": "ft",
            "base": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            "z_bot": z0, "z_top": z1}


def _model(voids="existing ground"):
    ctx = ProjectContext(name="dig", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, guid_ns=uuid.UUID(int=364))
    m = StructureModel("dig", ctx)
    m.add(Element("existing ground", ifc_class="IfcGeographicElement",
                  predefined_type="TERRAIN", geometry=_prism(0, 40, 0, 40, -20, 0),
                  quantities={"volume_cf": 40 * 40 * 20}))
    m.add(Element("structure excavation", ifc_class="IfcEarthworksCut",
                  geometry=_prism(10, 30, 10, 20, -6, 0), voids=voids,
                  quantities={"volume_cf": 20 * 10 * 6}))
    m.add(Element("footing", ifc_class="IfcFooting", geometry=_prism(12, 28, 12, 18, -6, -4),
                  quantities={"volume_cf": 16 * 6 * 2}))
    return m


def _volumes(f):
    import ifcopenshell.geom as geom
    import numpy as np
    s = geom.settings()
    s.set("use-world-coords", True)
    out = {}
    it = geom.iterator(s, f)
    assert it.initialize()
    while True:
        sh = it.get()
        v = np.asarray(sh.geometry.verts).reshape(-1, 3)
        t = np.asarray(sh.geometry.faces).reshape(-1, 3)
        a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
        out[f.by_id(sh.id).Name] = abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6 / FT3
        if not it.next():
            break
    return out


def test_a_hosted_cut_voids_the_ground_and_keeps_its_quantity(tmp_path):
    import ifcopenshell.util.element as ue
    import ifcopenshell.validate as V
    path = tmp_path / "dig.ifc"
    emit_ifc(_model(), str(path))
    f = ifcopenshell.open(str(path))
    (cut,) = f.by_type("IfcEarthworksCut")          # itself, not rewritten (#364)
    assert cut.ObjectType is None
    (rel,) = cut.VoidsElements
    assert rel.RelatingBuildingElement.Name == "existing ground"
    assert not cut.ContainedInStructure              # hangs off its host
    # the ground draws with the hole; the cut keeps its own body and quantity
    vol = _volumes(f)
    assert vol["existing ground"] == pytest.approx(40 * 40 * 20 - 20 * 10 * 6, rel=1e-6)
    assert vol["structure excavation"] == pytest.approx(1200.0, rel=1e-6)
    qto = {k: v for ps in ue.get_psets(cut, qtos_only=True).values() for k, v in ps.items()}
    assert any(abs(v - 1200.0 * FT3) < 1e-6 for v in qto.values() if isinstance(v, float))
    log = V.json_logger()
    V.validate(f, log)
    assert not log.statements, log.statements[:3]


def test_takeoff_counts_the_hosted_cut_as_excavation(tmp_path):
    from bimforge.bim.model_elements import plan_modelled_elements
    path = tmp_path / "dig.ifc"
    emit_ifc(_model(), str(path))
    plan = plan_modelled_elements(str(path), all_elements=True, takeoff=True)
    cut = next(e for e in plan["elements"] if e["name"] == "structure excavation")
    assert cut["element_type"] == "excavation"
    assert cut["quantities"]["excavation_cy"]["value"] == pytest.approx(1200.0 / 27.0, rel=1e-3)
    # the ground it voids is never a pay quantity
    assert any(s["name"] == "existing ground" for s in plan["skipped"])


def test_voids_must_name_another_element_and_only_a_cut_voids():
    m = _model(voids="no such thing")
    with pytest.raises(ValueError, match="not another element"):
        emit_ifc(m, "/dev/null")
    m = _model()
    m.elements[2].voids = "existing ground"          # a footing cannot
    with pytest.raises(ValueError, match="only an IfcEarthworksCut"):
        emit_ifc(m, "/dev/null")
