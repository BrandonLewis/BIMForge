"""Earthwork for 4D (#59): one hosted cut per pit, the backfill derived from
it, and the two grouped by location.

The pit is an IfcEarthworksCut voiding the existing ground. The backfill is
the pit clipped at the backfill's top, less every element standing in it: a
stem that rises above the backfill takes away only its buried part. A 4D
viewer drains or fills each single solid by volume over its task, so there
are no lifts.
"""
from __future__ import annotations

import uuid

import pytest

pytest.importorskip("manifold3d")
ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author.backfill import derive_backfill  # noqa: E402
from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402

FT3 = (1200.0 / 3937.0) ** 3
PIT, FILL, GROUP = "Abut 1 excavation", "Abut 1 backfill", "Abut 1 earthwork"


def _prism(x0, x1, y0, y1, z0, z1):
    return {"kind": "prism", "units": "ft",
            "base": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)],
            "z_bot": z0, "z_top": z1}


def _abutment(voids="existing ground"):
    """A 40 x 20 x 8 ft pit (6400 cf) holding a 30 x 12 x 3 ft footing
    (1080 cf) and a 20 x 4 ft stem from the footing to El +10."""
    ctx = ProjectContext(name="abut", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, guid_ns=uuid.UUID(int=59))
    m = StructureModel("abut", ctx)
    m.add(Element("existing ground", ifc_class="IfcGeographicElement",
                  predefined_type="TERRAIN", geometry=_prism(0, 60, 0, 40, -20, 0),
                  quantities={"volume_cf": 60 * 40 * 20}))
    m.add(Element(PIT, ifc_class="IfcEarthworksCut", predefined_type="EXCAVATION",
                  geometry=_prism(10, 50, 10, 30, -8, 0), voids=voids,
                  quantities={"volume_cf": 40 * 20 * 8}))
    m.add(Element("Abut 1 footing", ifc_class="IfcFooting",
                  geometry=_prism(15, 45, 14, 26, -8, -5),
                  quantities={"volume_cf": 30 * 12 * 3}))
    m.add(Element("Abut 1 stem", ifc_class="IfcWall",
                  geometry=_prism(20, 40, 18, 22, -5, 10),
                  quantities={"volume_cf": 20 * 4 * 15}))
    return m


# the pit clipped at -1 (40 x 20 x 7 = 5600), less the footing (1080) and
# the stem's buried part from -5 to -1 (20 x 4 x 4 = 320)
NET = 5600 - 1080 - 320


def _mesh_volume(f, name):
    import ifcopenshell.geom as geom
    import numpy as np
    s = geom.settings()
    s.set("use-world-coords", True)
    el = next(e for e in f.by_type("IfcProduct") if e.Name == name)
    sh = geom.create_shape(s, el)
    v = np.asarray(sh.geometry.verts).reshape(-1, 3)
    t = np.asarray(sh.geometry.faces).reshape(-1, 3)
    a, b, c = v[t[:, 0]], v[t[:, 1]], v[t[:, 2]]
    return abs(np.einsum("ij,ij->i", a, np.cross(b, c)).sum()) / 6 / FT3


def test_the_backfill_is_the_pit_less_what_stands_in_it():
    m = _abutment()
    el = derive_backfill(m, PIT, FILL, top=-1.0, group=GROUP)
    assert (el.ifc_class, el.predefined_type) == ("IfcEarthworksFill", "BACKFILL")
    assert el.quantities["volume_cf"] == pytest.approx(NET, abs=0.1)
    assert m.element(FILL) is el
    # the solid and its stated quantity agree, and the gate holds it to the
    # pit less what stands in it
    label, got, want, tol = m.stated_quantities[-1]
    assert FILL in label and got == pytest.approx(want, abs=tol)
    assert m.groups[GROUP] == [PIT, FILL]


def test_the_written_backfill_is_one_solid_with_its_volume(tmp_path):
    m = _abutment()
    derive_backfill(m, PIT, FILL, top=-1.0, group=GROUP)
    out = tmp_path / "abut.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    assert _mesh_volume(f, FILL) == pytest.approx(NET, rel=1e-6)
    fill = next(e for e in f.by_type("IfcEarthworksFill") if e.Name == FILL)
    assert fill.PredefinedType == "BACKFILL"
    import ifcopenshell.util.element as ue
    qto = {k: v for ps in ue.get_psets(fill, qtos_only=True).values()
           for k, v in ps.items() if isinstance(v, float)}
    assert any(v == pytest.approx(NET * FT3, rel=1e-6) for v in qto.values())


def test_the_cut_and_its_backfill_are_grouped_by_location(tmp_path):
    m = _abutment()
    derive_backfill(m, PIT, FILL, top=-1.0, group=GROUP)
    out = tmp_path / "abut.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    (grp,) = f.by_type("IfcGroup")
    assert grp.Name == GROUP
    (rel,) = grp.IsGroupedBy
    members = {o.Name: o for o in rel.RelatedObjects}
    assert set(members) == {PIT, FILL}
    # the cut hangs off the ground it voids, not off the group or the tree:
    # a group is an assignment, not a parent
    cut = members[PIT]
    assert cut.is_a("IfcEarthworksCut")
    assert cut.VoidsElements[0].RelatingBuildingElement.Name == "existing ground"
    assert not cut.ContainedInStructure
    assert not getattr(cut, "Decomposes", None)


def test_a_group_naming_a_missing_element_is_refused(tmp_path):
    m = _abutment()
    m.groups["Abut 2 earthwork"] = [PIT, "Abut 2 backfill"]
    with pytest.raises(ValueError, match="Abut 2 backfill"):
        emit_ifc(m, str(tmp_path / "bad.ifc"))


def test_a_body_that_is_not_closed_is_refused():
    m = _abutment()
    # a box with its top face missing: not a solid, so no volume to take away
    v = [(20, 12, -7), (24, 12, -7), (24, 13, -7), (20, 13, -7),
         (20, 12, -6), (24, 12, -6), (24, 13, -6), (20, 13, -6)]
    t = [(0, 2, 1), (0, 3, 2), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
         (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    m.add(Element("drain pipe", ifc_class="IfcPipeSegment",
                  geometry={"kind": "mesh", "units": "ft", "verts": v, "tris": t}))
    with pytest.raises(ValueError, match="drain pipe"):
        derive_backfill(m, PIT, FILL, top=-1.0)


def test_a_backfill_in_pieces_is_refused_unless_expected():
    m = _abutment()
    # a cutoff wall across the whole pit splits the backfill in two
    m.add(Element("cutoff wall", ifc_class="IfcWall",
                  geometry=_prism(46, 48, 10, 30, -8, 2)))
    with pytest.raises(ValueError, match="2 pieces"):
        derive_backfill(m, PIT, FILL, top=-1.0)
    el = derive_backfill(m, PIT, FILL, top=-1.0, pieces=2)
    assert el.quantities["volume_cf"] == pytest.approx(NET - 2 * 20 * 7, abs=0.1)


def test_nothing_left_to_backfill_is_refused():
    m = _abutment()
    with pytest.raises(ValueError, match="nothing"):
        derive_backfill(m, PIT, FILL, top=-8.0)


def test_excluded_elements_are_not_taken_away():
    m = _abutment()
    el = derive_backfill(m, PIT, FILL, top=-1.0, exclude=["Abut 1 stem"])
    assert el.quantities["volume_cf"] == pytest.approx(NET + 320, abs=0.1)


def test_a_surface_top_clips_the_pit():
    # a backfill finished to a plane sloping from -2 at x = 0 to 0 at x = 60,
    # given as a two-triangle surface over the pit
    m = _abutment()
    surf = {"verts": [(0, 0, -2), (60, 0, 0), (60, 40, 0), (0, 40, -2)],
            "tris": [(0, 1, 2), (0, 2, 3)]}
    el = derive_backfill(m, PIT, FILL, top=surf, exclude=["Abut 1 stem"])
    # mean top over the pit (x 10..50) is -2 + 2 * 30 / 60 = -1: the same
    # clipped volume as a level -1 top
    assert el.quantities["volume_cf"] == pytest.approx(5600 - 1080, abs=0.5)


def test_an_unhosted_excavation_next_to_ground_is_warned(tmp_path):
    m = _abutment(voids=None)
    with pytest.warns(UserWarning, match="voids"):
        emit_ifc(m, str(tmp_path / "unhosted.ifc"))
