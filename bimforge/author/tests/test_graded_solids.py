"""Promoted graded solids: Prismatoid / MirrorX / ShearedZ (#195, solids half)."""
from __future__ import annotations

import math
import uuid

import pytest

from bimforge.author.primitives import MirrorX, Prism, Prismatoid, ShearedZ


def _deck():
    # a 10 x 5 plan slab on a sloped bottom, constant 2 ft vertical thickness
    bottom = [(0, 0, 0.0), (10, 0, 1.0), (10, 5, 1.0), (0, 5, 0.0)]
    top = [(x, y, z + 2.0) for x, y, z in bottom]
    return Prismatoid("deck bay", bottom, top, ifc="IfcSlab")


def test_prismatoid_area_volume_height():
    d = _deck()
    assert math.isclose(d.area_sf, 50.0)                 # plan area of bottom
    assert math.isclose(d.volume_cf, 100.0, rel_tol=1e-9)  # 50 * 2 ft
    assert math.isclose(d.height_ft, 2.0, rel_tol=1e-9)
    (s,) = d.body_solids()
    assert s["kind"] == "mesh" and s["plan"]             # rides the mesh kind


def test_prismatoid_rejects_mismatched_rings():
    with pytest.raises(ValueError, match="points"):
        Prismatoid("x", [(0, 0, 0), (1, 0, 0), (1, 1, 0)],
                   [(0, 0, 1), (1, 0, 1)])


def test_mirrorx_negates_x_and_passes_quantities_through():
    d = _deck()
    m = MirrorX(d)
    assert m.area_sf == d.area_sf and m.volume_cf == d.volume_cf  # isometry
    (orig,), (refl,) = d.body_solids(), m.body_solids()
    assert refl["verts"] == [(-x, y, z) for x, y, z in orig["verts"]]
    # winding flipped so the shell still faces outward
    assert refl["tris"] == [(a, c, b) for a, b, c in orig["tris"]]


def test_shearedz_is_volume_preserving_and_tilts_z():
    d = _deck()
    sh = ShearedZ(d, slope=0.05, y_ref=0.0)
    assert sh.volume_cf == d.volume_cf                   # Cavalieri: exact
    (orig,), (out,) = d.body_solids(), sh.body_solids()
    assert out["verts"] == [(x, y, z + 0.05 * y)
                            for x, y, z in orig["verts"]]


def test_mirrorx_and_shearedz_reject_non_mesh():
    p = Prism("ftg", [(0, 0), (2, 0), (2, 2), (0, 2)], z_bot=0, z_top=1)
    with pytest.raises(TypeError, match="mesh"):
        MirrorX(p).body_solids()
    with pytest.raises(TypeError, match="mesh"):
        ShearedZ(p, 0.1).body_solids()


# --------------------------------------------------------------------------
# emitter integration
# --------------------------------------------------------------------------

pytest.importorskip("ifcopenshell")

from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402


def test_prismatoid_emits_a_faceted_brep(tmp_path):
    import ifcopenshell
    ctx = ProjectContext(name="Deck Fixture", epsg=2226, base_e=6_594_000.0,
                         base_n=1_943_000.0, base_h=200.0,
                         guid_ns=uuid.UUID(int=195))
    m = StructureModel("deck", ctx)
    m.add(Element.from_geometry("deck bay", _deck(), ifc_class="IfcSlab"))
    out = tmp_path / "deck.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    assert len(f.by_type("IfcFacetedBrep")) == 1         # existing mesh path
