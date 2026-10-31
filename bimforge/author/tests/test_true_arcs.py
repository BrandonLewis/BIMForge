"""True arcs: circles reach IFC and STEP as circles, not polygons.

A CircleRing is the polygon every mesh/volume consumer reads (sized to the
circle's area) that remembers its circle; exact writers draw the arc. Revit
and Tekla turn an IfcCircleProfileDef extrusion into a native round member;
a faceted polygon stays dumb geometry.
"""
from __future__ import annotations

import math
import uuid

import pytest

from bimforge.author.primitives import (CircleRing, CircularColumn,
                                        SectionPrism, circle_poly, exact_of,
                                        poly_area, ring_circle)
from bimforge.bim.ifc_mesh import mesh_topology

FT = 1200.0 / 3937.0


def test_a_circle_ring_is_its_polygon_and_remembers_the_circle():
    ring = circle_poly(1.5, 32, cx=2.0, cy=3.0)
    assert isinstance(ring, CircleRing) and ring_circle(ring) == (2.0, 3.0, 1.5)
    assert poly_area(ring) == pytest.approx(math.pi * 1.5 ** 2)   # equal-area
    assert ring_circle([tuple(p) for p in ring]) is None           # rebuilt: forgotten


def test_circular_column_mesh_volume_and_exact_agree():
    pile = CircularColumn("pile", (0, 0, -40), (4, 0, 0), r=1.0, segments=32)
    (d,) = pile.body_solids()
    t = mesh_topology(d["verts"], d["tris"])
    assert t["closed"] and t["components"] == 1
    assert pile.volume_cf == pytest.approx(math.pi * 40.0)        # area x vertical H
    assert exact_of(d) is d["exact"]
    assert d["exact"]["circles"]["profile"] == (0.0, 0.0, 1.0)
    tube = CircularColumn("pipe", (0, 0, 0), (0, 0, 10), r=1.0, r_inner=0.9)
    (d2,) = tube.body_solids()
    assert mesh_topology(d2["verts"], d2["tris"])["closed"]
    assert tube.volume_cf == pytest.approx(math.pi * (1 - 0.81) * 10)
    with pytest.raises(ValueError):
        CircularColumn("flat", (0, 0, 0), (1, 0, 0), r=1.0)


ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.gate import run_post  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402


def _model():
    ctx = ProjectContext(name="Arcs", schema="IFC4X3_ADD2", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0, base_h=0.0,
                         guid_ns=uuid.UUID(int=314))
    m = StructureModel("arcs", ctx)
    m.solid_body_gate = "error"
    for name, geo, cls in (
            ("plumb pile", CircularColumn("plumb pile", (0, 0, -40), (0, 0, 0),
                                          r=0.75), "IfcPile"),
            ("battered pile", CircularColumn("battered pile", (10, 0, -40),
                                             (23.33, 0, 0), r=0.75), "IfcPile"),
            ("pipe sleeve", CircularColumn("pipe sleeve", (20, 5, 0),
                                           (20, 5, 3), r=0.5, r_inner=0.45),
             "IfcPipeSegment"),
            ("stem", SectionPrism("stem", [(0, 0), (10, 0), (10, 6), (0, 6)],
                                  1.0, y0=20.0,
                                  voids=[circle_poly(1.5, 32, 5.0, 2.0)]),
             "IfcWall")):
        m.add(Element(name, cls, geometry=geo,
                      quantities={"volume_cf": geo.volume_cf}))
    return m


def test_ifc_writes_true_circles(tmp_path):
    m = _model()
    out = tmp_path / "arcs.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    prof = {}
    for p in f.by_type("IfcElement"):
        (item,) = [i for r in p.Representation.Representations for i in r.Items]
        assert item.is_a("IfcExtrudedAreaSolid"), p.Name
        prof[p.Name] = item
    assert prof["plumb pile"].SweptArea.is_a("IfcCircleProfileDef")
    assert prof["plumb pile"].SweptArea.Radius == pytest.approx(0.75 * FT)
    bat = prof["battered pile"]
    assert bat.SweptArea.is_a("IfcCircleProfileDef")
    dx, dy, dz = bat.ExtrudedDirection.DirectionRatios
    assert dx / dz == pytest.approx(13.33 / 40, abs=1e-3)          # 3:1 batter
    hollow = prof["pipe sleeve"].SweptArea
    assert hollow.is_a("IfcCircleHollowProfileDef")
    assert hollow.WallThickness == pytest.approx(0.05 * FT)
    stem = prof["stem"].SweptArea
    assert stem.is_a("IfcArbitraryProfileDefWithVoids")
    (hole,) = stem.InnerCurves
    assert hole.is_a("IfcCircle") and hole.Radius == pytest.approx(1.5 * FT)
    rep = run_post(m, {"ifc": str(out)})
    assert rep.passed, rep.failures                # true volumes, solid bodies


def test_step_writes_true_cylinders(tmp_path):
    b3d = pytest.importorskip("build123d")
    from bimforge.author.emit_step import build_solids
    m = _model()
    for el, parts in build_solids(m):
        (part,) = parts
        kinds = {f.geom_type.name for f in part.faces()}
        assert "CYLINDER" in kinds or el.name == "battered pile", (el.name, kinds)
        assert part.is_valid
        assert part.volume == pytest.approx(el.quantities["volume_cf"],
                                            rel=1e-6), el.name
    bat = [p for el, ps in build_solids(m) if el.name == "battered pile"
           for p in ps][0]
    # an oblique circular extrusion: its side is a true elliptic-cylinder
    # surface (a B-spline/extrusion surface), not facets
    assert len(bat.faces()) == 3
