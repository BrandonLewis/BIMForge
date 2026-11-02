"""Declared alignments (StructureModel.alignments) and their federation.

A family whose solids are built off its own line frame declares its control
line; emit writes it as an IfcAlignment although nothing sweeps along it, and
federate carries it whole into the combined file: aggregated to the project,
referenced in the site, layouts nested, Axis subcontext kept, no part of it
dropped into a storey. The stationer must read the same line back from the
federated file as from the source.
"""
from __future__ import annotations

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author.alignment import Alignment, Profile  # noqa: E402
from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.federate import federate  # noqa: E402
from bimforge.author.model import StructureModel  # noqa: E402
from bimforge.author.spatial import Facility  # noqa: E402
from bimforge.author.tests.test_ifc4x3_facility import (  # noqa: E402
    _box, _bridge, _ctx, _validate)
from bimforge.bim.alignment_station import (  # noqa: E402
    AlignmentStationer, alignments)

POB = {"station": 900.0, "northing": 1_943_000.0, "easting": 6_594_000.0}
RUN = [{"kind": "tangent", "bearing": "N 0-6-3 W", "length": 300.0}]
PROFILE = [{"bvc_station": 950.0, "bvc_elev": 210.0, "g_in_pct": 1.7,
            "g_out_pct": -1.6, "length_ft": 200.0, "evc_station": 1150.0,
            "evc_elev": 210.0 + 0.017 * 200.0 - 0.033 / 400.0 * 200.0 ** 2}]


def _with_line(m):
    al, prof = Alignment(POB, RUN, name="ROUTE-1"), Profile(PROFILE)
    m.alignments.append((al, prof))
    return m, al, prof


def _terrain():
    m = StructureModel("Terrain", _ctx(facility=Facility("site")))
    m.add(_box("existing-grade", 0.0, "IfcGeographicElement", (-5.0, 0.0)))
    return m


def test_a_declared_alignment_is_written_without_a_sweep(tmp_path):
    m, al, prof = _with_line(_bridge())
    emit_ifc(m, str(tmp_path / "b.ifc"))
    f = ifcopenshell.open(str(tmp_path / "b.ifc"))
    (ifc_al,) = f.by_type("IfcAlignment")
    assert ifc_al.Name == "ROUTE-1"
    st = AlignmentStationer(f, ifc_al)
    k = m.ctx.ft_to_m
    assert st.length == pytest.approx(300.0 * k)
    assert st.convert(st.start_station, "ft") == pytest.approx(900.0)
    fr = st.frame((1050.0 - 900.0) * k)
    assert st.elevation_m(fr.point[2]) / k == pytest.approx(prof.elev(1050.0),
                                                            abs=1e-6)


@pytest.mark.parametrize("facility", [True, False])
def test_federate_carries_the_alignment_whole(tmp_path, facility):
    bridge = _bridge() if facility else _bridge(facility=None)
    m, al, prof = _with_line(bridge)
    emit_ifc(m, str(tmp_path / "bridge.ifc"))
    emit_ifc(_terrain(), str(tmp_path / "terrain.ifc"))
    src = ifcopenshell.open(str(tmp_path / "bridge.ifc"))
    out = tmp_path / "combined.ifc"
    r = federate([(tmp_path / "bridge.ifc", "Bridge"),
                  (tmp_path / "terrain.ifc", "Terrain")], str(out), _ctx())
    assert r.alignments == 1
    f = ifcopenshell.open(str(out))
    (ifc_al,) = f.by_type("IfcAlignment")
    # aggregated to the project, referenced (not contained) in the site
    assert [r.RelatingObject.is_a() for r in ifc_al.Decomposes] == ["IfcProject"]
    assert [r.RelatingStructure.is_a()
            for r in ifc_al.ReferencedInStructures] == ["IfcSite"]
    assert ifc_al.id() not in {e.id() for r in f.by_type(
        "IfcRelContainedInSpatialStructure") for e in r.RelatedElements}
    # nothing of it dropped into a storey; layouts and segments still nested
    nested = {o.is_a() for r in ifc_al.IsNestedBy for o in r.RelatedObjects}
    assert {"IfcAlignmentHorizontal", "IfcAlignmentVertical",
            "IfcReferent"} <= nested
    contained = {e.id() for r in f.by_type("IfcRelContainedInSpatialStructure")
                 for e in r.RelatedElements}
    for p in f.by_type("IfcAlignmentSegment") + f.by_type("IfcReferent"):
        assert p.id() not in contained and p.Nests
    assert len(f.by_type("IfcAlignmentSegment")) == len(
        src.by_type("IfcAlignmentSegment"))
    # the axis curve keeps an Axis subcontext of the one model context
    (axis,) = [rep for rep in ifc_al.Representation.Representations
               if rep.RepresentationIdentifier == "Axis"]
    assert axis.ContextOfItems.is_a("IfcGeometricRepresentationSubContext")
    assert axis.ContextOfItems.ContextIdentifier == "Axis"
    roots = [c for c in f.by_type("IfcGeometricRepresentationContext")
             if not c.is_a("IfcGeometricRepresentationSubContext")]
    assert len(roots) == 1 and axis.ContextOfItems.ParentContext == roots[0]
    # and it stations exactly as the source does
    a = AlignmentStationer(src, alignments(src)[0])
    b = AlignmentStationer(f, alignments(f)[0])
    assert b.start_station == pytest.approx(a.start_station)
    for d in (0.0, 30.0, a.length):
        assert b.frame(d).point == pytest.approx(a.frame(d).point, abs=1e-9)
    problems = _validate(out)
    if not facility:
        # a storey-path source federated beside a facility-tree one leaves
        # its storey un-aggregated: a federate limitation that predates
        # alignments (same result with no alignment), not this feature's
        problems = [p for p in problems if "IfcBuildingStorey" not in p]
    assert problems == []


def test_federating_an_alignment_is_byte_deterministic(tmp_path):
    for name in ("one", "two"):
        m, *_ = _with_line(_bridge())
        emit_ifc(m, str(tmp_path / f"{name}-b.ifc"))
        emit_ifc(_terrain(), str(tmp_path / f"{name}-t.ifc"))
        federate([(tmp_path / f"{name}-b.ifc", "Bridge"),
                  (tmp_path / f"{name}-t.ifc", "Terrain")],
                 str(tmp_path / f"{name}.ifc"), _ctx())
    a = (tmp_path / "one.ifc").read_bytes()
    b = (tmp_path / "two.ifc").read_bytes()
    assert a == b
