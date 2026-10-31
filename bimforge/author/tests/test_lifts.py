"""bimforge.author.lifts: fill bodies cut into compacted lifts."""
from __future__ import annotations

import uuid

import pytest

pytest.importorskip("manifold3d")

from bimforge.author.lifts import (cut_lifts, lift_dates,  # noqa: E402
                                   solid_of, split_into_lifts)
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402
from bimforge.bim.ifc_mesh import mesh_topology  # noqa: E402

SQ = [(0.0, 0.0), (20.0, 0.0), (20.0, 10.0), (0.0, 10.0)]
FOOTING = [(5.0, 3.0), (15.0, 3.0), (15.0, 7.0), (5.0, 7.0)]


def _backfill():
    """The shipped `fill` kind: a 20 x 10 x 4 ft pit refilled around a
    10 x 4 ft footing that stands 2.5 ft tall in it."""
    return {"kind": "fill", "units": "ft", "base": SQ, "z_bot": 0.0,
            "z_top": 4.0,
            "cuts": [{"base": FOOTING, "z_bot": 0.0, "z_top": 2.5}]}


def _model(geom, base_h=140.0):
    ctx = ProjectContext(name="Lifts", schema="IFC4X3_ADD2", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         base_h=base_h, guid_ns=uuid.UUID(int=19))
    m = StructureModel("lifts", ctx)
    m.add(Element("Abut 1 structure backfill", "IfcEarthworksFill",
                  geometry=geom, predefined_type="BACKFILL",
                  material="Structure backfill", classifications=["41"],
                  quantities={"volume_cf": 20 * 10 * 4 - 10 * 4 * 2.5}))
    return m


def test_fill_is_cut_into_closed_compacted_lifts():
    lifts = cut_lifts(solid_of([_backfill()]), 0.67)
    # 4.0 ft / 0.67: five full lifts and 0.65 ft on top (a full-ish lift)
    assert [round(l.thickness_ft, 2) for l in lifts] == [0.67] * 5 + [0.65]
    assert sum(l.volume_cf for l in lifts) == pytest.approx(700.0)
    # lifts below the footing top go round it; above it they are full
    assert lifts[0].volume_cf == pytest.approx((200 - 40) * 0.67)
    assert lifts[-1].volume_cf == pytest.approx(200 * 0.65)
    for lf in lifts:
        t = mesh_topology(lf.verts, lf.tris)
        assert t["closed"] and t["components"] == 1, lf.index


def test_a_thin_top_remainder_joins_the_lift_below():
    lifts = cut_lifts(solid_of([dict(_backfill(), z_top=3.45)]), 0.67)
    # 3.45 = 5 x 0.67 + 0.10: the 0.10 sliver rides on lift 5 (0.77 ft)
    assert len(lifts) == 5
    assert lifts[-1].thickness_ft == pytest.approx(0.77)


def test_touching_cells_become_one_solid_before_cutting():
    cells = []
    for i in range(4):                       # 4 boxes side by side
        x0 = 5.0 * i
        v = [(x0, 0, 0), (x0 + 5, 0, 0), (x0 + 5, 10, 0), (x0, 10, 0),
             (x0, 0, 2), (x0 + 5, 0, 2), (x0 + 5, 10, 2), (x0, 10, 2)]
        f = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
             (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
        cells.append({"kind": "mesh", "units": "ft", "verts": v, "tris": f})
    lifts = cut_lifts(solid_of(cells), 1.0)
    assert len(lifts) == 2
    for lf in lifts:
        t = mesh_topology(lf.verts, lf.tris)
        assert t["closed"] and t["components"] == 1   # no internal walls
        assert lf.volume_cf == pytest.approx(200.0)


def test_split_replaces_the_element_with_its_lifts():
    m = _model(_backfill())
    els = split_into_lifts(m, "Abut 1 structure backfill", 0.67,
                           base_elev=140.0)
    names = [e.name for e in m.elements]
    assert "Abut 1 structure backfill" not in names
    assert els[0].name == ("Abut 1 structure backfill lift 01 "
                           "(El 140.00-140.67)")
    assert m.assemblies["Abut 1 structure backfill"] == [e.name for e in els]
    for e in els:
        assert e.ifc_class == "IfcEarthworksFill"
        assert e.predefined_type == "BACKFILL" and e.classifications == ["41"]
    assert els[2].lift == {"index": 3, "of": 6,
                           "parent": "Abut 1 structure backfill",
                           "bottom_elev": pytest.approx(141.34),
                           "top_elev": pytest.approx(142.01),
                           "thickness_ft": pytest.approx(0.67)}
    (label, got, want, tol), = [q for q in m.stated_quantities
                                if "lifts sum" in q[0]]
    assert got == pytest.approx(want)


def test_lifts_emit_and_pass_the_solid_body_check(tmp_path):
    pytest.importorskip("ifcopenshell")
    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.gate import _ifc_solid_body_check, run_pre
    m = _model(_backfill())
    split_into_lifts(m, "Abut 1 structure backfill", 0.67)
    assert run_pre(m).passed
    out = tmp_path / "lifts.ifc"
    emit_ifc(m, str(out))
    assert _ifc_solid_body_check(m, str(out)) == []
    import ifcopenshell
    f = ifcopenshell.open(str(out))
    (asm,) = f.by_type("IfcElementAssembly")
    parts = [o for r in asm.IsDecomposedBy for o in r.RelatedObjects]
    assert len(parts) == 6 and all(p.is_a("IfcEarthworksFill") for p in parts)


def test_lift_dates_share_the_task_by_volume():
    m = _model(_backfill())
    els = split_into_lifts(m, "Abut 1 structure backfill", 0.67)
    # 2027-09-15 (Wed) .. 2027-09-20 (Mon): 4 working days for 6 lifts
    d = lift_dates(els, "2027-09-15", "2027-09-20")
    assert d[0][0] == "2027-09-15" and d[-1][1] == "2027-09-20"
    assert all(a <= b for a, b in d)
    assert [a for a, _ in d] == sorted(a for a, _ in d)
    assert "2027-09-18" not in {x for p in d for x in p}       # Saturday
