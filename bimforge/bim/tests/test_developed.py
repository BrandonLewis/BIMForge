"""bimforge.bim.developed: developed elevations along an IfcAlignment."""
from __future__ import annotations

import math
import uuid

import pytest
import yaml

ifcopenshell = pytest.importorskip("ifcopenshell")
pytest.importorskip("shapely")

from bimforge.author.alignment import Alignment  # noqa: E402
from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402
from bimforge.author.sweep import SweptSection  # noqa: E402
from bimforge.author.tests.test_emit_alignment import POB, RUN  # noqa: E402
from bimforge.bim.developed import (ElevationView, SectionView,  # noqa: E402
                                    cross_section, develop, load_set,
                                    parse_station, write_dxf)


def _ctx():
    return ProjectContext(name="dev", schema="IFC4X3_ADD2", epsg=2226,
                          base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                          guid_ns=uuid.UUID(int=91))


def _wall(al, ctx, name, x0, x1, h, s0=1010.0, s1=1100.0, ifc="IfcWall"):
    """A level box swept along the line: x0..x1 ft LEFT of it, El 0 to h."""
    sw = SweptSection(name, [(x0, 0.0), (x1, 0.0), (x1, h), (x0, h)], al, s0, s1,
                      origin=ctx, ifc=ifc)
    return Element.from_geometry(name, sw, ifc_class=ifc,
                                 quantities={"volume_cf": sw.volume_cf})


@pytest.fixture(scope="module")
def ifc(tmp_path_factory):
    """On the fixture line's 120 ft tangent (1000 -> 1120): a wall 10 ft
    tall 9-11 ft Lt, a 3 ft box 4-6 ft Lt beyond it (seen from the left),
    and a curved wall 2 ft tall 19-21 ft Lt over the two curves."""
    ctx = _ctx()
    al = Alignment(POB, RUN, name="ML")
    m = StructureModel("dev", ctx)
    m.add(_wall(al, ctx, "tall wall", 9.0, 11.0, 10.0))
    m.add(_wall(al, ctx, "low box", 4.0, 6.0, 3.0, 1030.0, 1080.0, "IfcFooting"))
    m.add(_wall(al, ctx, "curved wall", 19.0, 21.0, 2.0, 1130.0, 1360.0))
    m.alignments.append((al, None))
    out = tmp_path_factory.mktemp("dev") / "dev.ifc"
    emit_ifc(m, str(out))
    return ifcopenshell.open(str(out)), al


def test_parse_station():
    assert parse_station("547+62.90") == pytest.approx(54762.90)
    assert parse_station("1+234.5", "m") == pytest.approx(1234.5)
    assert parse_station(-12.5) == -12.5 and parse_station("-0+12.50") == -12.5


def test_the_cut_is_the_wall_unrolled_along_its_offset_line(ifc):
    from shapely.geometry import Polygon
    from bimforge.author.barrier_template import offset_length
    f, al = ifc
    dr = develop(f, ElevationView("C", 1140.0, 1350.0, offset=20.0, side="Lt",
                                  look_from="left", depth=5.0))
    # true length along 20 ft Lt over a right then a left curve, not 210 ft
    want = offset_length(al, 1140.0, 1350.0, 20.0)
    assert dr.length == pytest.approx(want, abs=0.02) and abs(want - 210.0) > 1.0
    (layer, _rgb, polys), = dr.cut
    area = sum(Polygon(p[0], p[1:]).area for p in polys)
    assert area == pytest.approx(2.0 * want, rel=2e-3)          # 2 ft tall all along
    ys = [pt[1] for p in polys for pt in p[0]]
    # the section's z are elevations: the wall stands El 0 to 2
    assert (min(ys), max(ys)) == (pytest.approx(0.0, abs=1e-3), pytest.approx(2.0, abs=1e-3))


def test_true_view_runs_stations_by_the_viewers_side(ifc):
    f, _al = ifc
    kw = dict(offset=12.0, side="Lt", depth=15.0)
    left = develop(f, ElevationView("L", 1010.0, 1100.0, look_from="left", **kw))
    right = develop(f, ElevationView("R", 1010.0, 1100.0, offset=0.0, side="Lt",
                                     look_from="right", depth=15.0))
    mirrored = develop(f, ElevationView("M", 1010.0, 1100.0, look_from="left",
                                        true_view=False, **kw))
    at = lambda dr, s: next(x for x, st in dr.ticks if st == s)  # noqa: E731
    assert at(left, 1010.0) == pytest.approx(90.0) and at(left, 1100.0) == pytest.approx(0.0)
    assert at(right, 1010.0) == pytest.approx(0.0) and at(right, 1100.0) == pytest.approx(90.0)
    assert at(mirrored, 1010.0) == pytest.approx(0.0)


def test_what_is_behind_is_hidden(ifc):
    f, _al = ifc
    def tops(dr):
        """Elevations of the long level lines seen."""
        return {round(a[1], 2) for ln in dr.beyond for a, b in zip(ln, ln[1:])
                if abs(a[1] - b[1]) < 1e-6 and abs(b[0] - a[0]) > 5.0}
    # from the left (12 ft Lt): the tall wall stands in front of the low box
    left = develop(f, ElevationView("L", 1010.0, 1100.0, offset=12.0, side="Lt",
                                    look_from="left", depth=15.0))
    assert 10.0 in tops(left) and 3.0 not in tops(left)
    assert not left.cut                                    # the cut is in the air
    # from the right (on the line): the low box is in front, its top seen,
    # and the tall wall's top above it
    right = develop(f, ElevationView("R", 1010.0, 1100.0, offset=0.0, side="Lt",
                                     look_from="right", depth=15.0))
    assert {3.0, 10.0} <= tops(right)


def test_a_sheet_set_to_dxf(ifc, tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    f, _al = ifc
    views = [ElevationView("OVERALL", 1010.0, 1100.0, offset=10.0, side="Lt",
                           look_from="right", depth=5.0),
             ElevationView("DETAIL", 1040.0, 1060.0, offset=10.0, side="Lt",
                           look_from="right", depth=5.0, scale=2)]
    out = tmp_path / "set.dxf"
    rep = write_dxf([develop(f, v) for v in views], str(out))
    assert rep[0].startswith("01 OVERALL: 1010.00 to 1100.00")
    assert '1" = 2' in rep[1]
    doc = ezdxf.readfile(str(out))
    assert [lay.name for lay in doc.layouts if lay.name != "Model"] == ["01 OVERALL", "02 DETAIL"]
    vp = [e for e in doc.layouts.get("02 DETAIL") if e.dxftype() == "VIEWPORT"]
    assert any(abs(v.dxf.view_height / v.dxf.height - 2.0) < 1e-9 for v in vp)
    layers = {e.dxf.layer for e in doc.modelspace()}
    assert "E-BEYOND" in layers and any(n.startswith("E-CUT-") for n in layers)


def test_a_set_file_makes_the_segments(tmp_path):
    p = tmp_path / "set.yaml"
    p.write_text(yaml.safe_dump({
        "ifc": "m.ifc", "offset": 10, "side": "Rt", "look_from": "left", "depth": 8,
        "views": [{"name": "OVERALL", "from": "0+00", "to": "95+00.23"}],
        "segments": {"from": "0+00", "to": "95+00.23", "length": 1000, "overlap": 20,
                     "scale": 10}}), encoding="utf-8")
    ifc, views, _sheet, out = load_set(p)
    assert ifc.endswith("m.ifc") and out.endswith("set.dxf")
    segs = views[1:]
    assert len(segs) == 10
    assert segs[0].from_station == 0.0 and segs[1].from_station == 980.0
    assert segs[-1].to_station == pytest.approx(9500.23)
    assert all(v.offset == 10 and v.side == "Rt" and v.depth == 8 for v in views)


def _cut_spans(dr):
    """{layer-ish: (xmin, xmax, ymin, ymax, area)} of the section's cut."""
    from shapely.geometry import Polygon
    out = []
    for _layer, _rgb, polys in dr.cut:
        for p in polys:
            poly = Polygon(p[0], p[1:])
            x0, y0, x1, y1 = poly.bounds
            out.append((round(x0, 3), round(x1, 3), round(y0, 3), round(y1, 3),
                        round(poly.area, 2)))
    return sorted(out)


def test_a_cross_section_is_what_the_section_camera_sees(ifc):
    """At 1050, 30 ft wide, looking ahead: Lt is on the viewer's left, so
    the tall wall (9-11 Lt) cuts at x 4-6 and the low box (4-6 Lt) at 9-11,
    with CL at x 15. Looking back mirrors it."""
    f, _al = ifc
    ahead = cross_section(f, SectionView("A", 1050.0, width=30.0, depth=10.0))
    assert ahead.length == pytest.approx(30.0) and ahead.tick_kind == "offset"
    assert _cut_spans(ahead) == [(4.0, 6.0, 0.0, 10.0, 20.0), (9.0, 11.0, 0.0, 3.0, 6.0)]
    ticks = dict((o, x) for x, o in ahead.ticks)
    assert (ticks[0.0], ticks[10.0], ticks[-10.0]) == (15.0, 5.0, 25.0)
    back = cross_section(f, SectionView("B", 1050.0, width=30.0, depth=10.0,
                                        look_back=True))
    assert _cut_spans(back) == [(19.0, 21.0, 0.0, 3.0, 6.0), (24.0, 26.0, 0.0, 10.0, 20.0)]
    # nothing is cut where nothing stands, but what lies beyond is drawn
    gap = cross_section(f, SectionView("G", 1005.0, width=30.0, depth=10.0))
    assert not gap.cut and gap.beyond
    with pytest.raises(ValueError, match="not along"):
        cross_section(f, SectionView("X", 5000.0))


def test_a_cross_section_to_dxf(ifc, tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    f, _al = ifc
    out = tmp_path / "sec.dxf"
    rep = write_dxf([cross_section(f, SectionView("S", 1050.0, width=30.0,
                                                  depth=10.0))], str(out))
    assert rep[0].startswith("01 S: section at 10+50.00, 30.00 wide")
    doc = ezdxf.readfile(str(out))
    texts = {e.dxf.text for e in doc.modelspace() if e.dxftype() == "TEXT"}
    assert {"CL", "10 Lt", "10 Rt"} <= texts
    lay = doc.layouts.get("01 S")
    titles = [e.dxf.text for e in lay if e.dxftype() == "TEXT"]
    assert any("SECTION AT STA 10+50.00, LOOKING AHEAD" in t for t in titles)


@pytest.fixture(scope="module")
def wall_section(tmp_path_factory):
    """A wall in a trench at 1010-1100: native ground wider than any view,
    compacted fill, a stem, one bar, and an unstyled 'drain rock' body."""
    ctx = _ctx()
    al = Alignment(POB, RUN, name="ML")
    m = StructureModel("sec", ctx)

    def body(name, ring, ifc):
        sw = SweptSection(name, ring, al, 1010.0, 1100.0, origin=ctx, ifc=ifc)
        m.add(Element.from_geometry(name, sw, ifc_class=ifc,
                                    quantities={"volume_cf": sw.volume_cf}))
    box = lambda x0, x1, z0, z1: [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]  # noqa: E731
    body("existing ground", [(-40, -12), (40, -12), (40, 0), (6, 0), (6, -6),
                             (-6, -6), (-6, 0), (-40, 0)], "IfcGeographicElement")
    body("backfill", box(-6, -1, -6, 0), "IfcEarthworksFill")
    body("stem", box(-1, 1, -6, 8), "IfcWall")
    body("drain rock", box(1, 6, -6, 0), "IfcBuildingElementProxy")
    body("bar", box(0.5, 0.6, -3.0, -2.9), "IfcReinforcingBar")
    m.alignments.append((al, None))
    out = tmp_path_factory.mktemp("sec") / "sec.ifc"
    emit_ifc(m, str(out))
    return ifcopenshell.open(str(out))


def test_section_fills_read_as_what_they_are(wall_section):
    from bimforge.author import ifc_styles as S
    dr = cross_section(wall_section, SectionView("S", 1050.0, width=30.0, depth=1.0))
    layers = {layer: rgb for layer, rgb, _rings in dr.cut}
    assert set(layers) == {"E-CUT-Earthwork", "E-CUT-Compacted-Fill", "E-CUT-Concrete",
                           "E-CUT-Gravel", "E-CUT-Reinforcing-Steel"}
    # the see-through earth style still fills in its own colour, not half dark
    assert layers["E-CUT-Earthwork"] == pytest.approx(tuple(S._EARTH["rgb"]), abs=0.01)
    # unstyled: what its name says (as the Blender add-on reads it)
    from bimforge.bim.section_style import by_kind
    assert layers["E-CUT-Gravel"] == pytest.approx(by_kind("Gravel").rgb)
    # the ground is wider than the view, yet closes and fills to its edges
    (_l, _r, rings), = [c for c in dr.cut if c[0] == "E-CUT-Earthwork"]
    xs = [p[0] for ring in rings for p in ring[0]]
    assert (min(xs), max(xs)) == (pytest.approx(0.0), pytest.approx(30.0))


def test_the_dxf_hatches_each_kind_and_dots_the_rebar(wall_section, tmp_path):
    ezdxf = pytest.importorskip("ezdxf")
    from bimforge.bim.section_style import MIN_DOT_IN, by_kind, hatch_scale
    out = tmp_path / "sec.dxf"
    write_dxf([cross_section(wall_section, SectionView("S", 1050.0, width=30.0,
                                                       depth=1.0, scale=4))], str(out))
    doc = ezdxf.readfile(str(out))
    pats = {h.dxf.layer: h for h in doc.modelspace().query("HATCH")
            if h.dxf.layer.endswith("-PATT")}
    assert pats["E-CUT-Concrete-PATT"].dxf.pattern_name == "CONCRETE1"
    assert pats["E-CUT-Earthwork-PATT"].dxf.pattern_name == "EARTH"
    assert pats["E-CUT-Compacted-Fill-PATT"].dxf.pattern_name == "AR-SAND"
    assert pats["E-CUT-Gravel-PATT"].dxf.pattern_name == "GRAVEL"
    assert pats["E-CUT-Concrete-PATT"].dxf.pattern_scale == pytest.approx(
        hatch_scale(by_kind("Concrete"), 4))
    # the 0.1 ft bar is smaller than the minimum dot: a solid disc that size
    bar = pats["E-CUT-Reinforcing-Steel-PATT"]
    assert bar.dxf.solid_fill == 1
    (arc,) = bar.paths[0].edges
    assert arc.radius == pytest.approx(MIN_DOT_IN / 2 * 4)
    # the colour fill stays on its own layer (freeze it for black and white)
    assert any(h.dxf.layer == "E-CUT-Concrete" for h in doc.modelspace().query("HATCH"))


def test_the_style_table():
    from bimforge.author import ifc_styles as S
    from bimforge.bim.section_style import KINDS, classify, hatch_scale, style_of
    import ezdxf.tools.pattern as P
    names = set(P.ISO_PATTERN)
    assert all(k.dxf == "SOLID" or k.dxf in names for k in KINDS)
    assert classify("S-EW-FILL")[0] == "Compacted Fill"
    assert classify("S-BACKFILL-LEAN")[0] == "Lean Concrete"
    assert classify("S-BACKFILL-CONC")[0] == "Concrete Backfill"
    assert classify("Structure backfill")[0] == "Compacted Fill"
    assert classify("existing ground (remaining)")[0] == "Earthwork"
    assert S.resolve_surface("S-EW-FILL", None)["rgb"] == S._FILL["rgb"]
    assert hatch_scale(style_of("concrete"), 25.4) == pytest.approx(0.8)
    # neighbours in a wall section are told apart by colour alone
    rgb = {k.kind: k.rgb for k in KINDS}
    for a, b in [("Concrete", "Concrete Backfill"), ("Concrete", "Lean Concrete"),
                 ("Earthwork", "Compacted Fill"), ("Compacted Fill", "Lean Concrete")]:
        assert sum(abs(x - y) for x, y in zip(rgb[a], rgb[b])) > 0.25, (a, b)


def test_review_round_trips_and_edges(wall_section, tmp_path):
    """PR #3 review: a bar outside the view is not an empty cut, outlines
    live on the ink layer, kind labels re-classify, layer spellings
    normalise, and an unnamed alignment resolves by its '#id' label."""
    ezdxf = pytest.importorskip("ezdxf")
    from types import SimpleNamespace as NS
    from bimforge.bim import developed as D
    from bimforge.bim.section_style import KINDS, style_of
    # 30 ft wide misses nothing; 0.5 ft wide at CL leaves the bar (0.5 Lt) out
    narrow = cross_section(wall_section, SectionView("N", 1050.0, width=0.6, depth=1.0))
    assert all(ring and len(ring[0]) >= 3 for _l, _r, rings in narrow.cut for ring in rings)
    assert "E-CUT-Reinforcing-Steel" not in {c[0] for c in narrow.cut}
    out = tmp_path / "n.dxf"
    write_dxf([narrow], str(out))                         # no crash
    # cut outlines on the -PATT (ink) layer, so a frozen colour layer keeps them
    write_dxf([cross_section(wall_section, SectionView("S", 1050.0, width=30.0))],
              str(out))
    doc = ezdxf.readfile(str(out))
    heavy = [e for e in doc.modelspace().query("LWPOLYLINE") if e.dxf.lineweight == 50]
    assert heavy and all(e.dxf.layer.endswith("-PATT") for e in heavy)
    # every kind's own label, and its DXF layer spelling, classify as itself
    for k in KINDS:
        assert style_of(k.kind) is k, k.kind
        assert style_of(D._layer_name(k.kind).replace("E-CUT-", "")) is k, k.kind
    # a named style with no IfcMaterial: its style name says what it is
    el = NS(Name="W1", is_a=lambda *a: "IfcWall")
    styled = NS(name="Lean Concrete", surface=NS(components=(0.9, 0.85, 0.62)), diffuse=None)
    layer, _ = D._cut_layer(el, None, [styled], [(0.9, 0.85, 0.62)], [(0.9, 0.85, 0.62)])
    assert layer == "E-CUT-Lean-Concrete"
    # a generic material name: the element name says it, colour kept
    rock = NS(Name="drain rock", is_a=lambda *a: "IfcBuildingElementProxy")
    layer, tri = D._cut_layer(rock, NS(Name="Material"), [], [(0.3, 0.3, 0.3)], [(0.3, 0.3, 0.3)])
    assert layer == "E-CUT-Gravel" and tri == [(0.3, 0.3, 0.3)]


def test_an_unnamed_alignment_resolves_by_its_label(wall_section):
    from bimforge.bim.alignment_station import AlignmentStationer, alignments
    from bimforge.bim.developed import _stationer_for
    al = alignments(wall_section)[0]
    name, al.Name = al.Name, None
    try:
        label = AlignmentStationer(wall_section, al).name
        assert label == f"#{al.id()}"
        assert _stationer_for(wall_section, label).alignment == al
    finally:
        al.Name = name


def test_review_two_names_before_class_and_long_bars_keep_their_length(tmp_path):
    """PR #3 second review: an unstyled element's name beats its class; a
    long thin bar is not shrunk to a dot."""
    ezdxf = pytest.importorskip("ezdxf")
    from types import SimpleNamespace as NS
    from bimforge.bim import developed as D
    el = NS(Name="Lean Concrete", is_a=lambda *a: "IfcWall")
    layer, tri = D._cut_layer(el, None, [], [(0.6, 0.6, 0.6)], [(0.6, 0.6, 0.6)])
    assert layer == "E-CUT-Lean-Concrete" and tri == [(0.90, 0.85, 0.62)]
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    bar = [[(0.0, 0.0), (20.0, 0.0), (20.0, 0.05), (0.0, 0.05), (0.0, 0.0)]]
    D._cut_to_dxf(doc, msp, "E-CUT-Reinforcing-Steel", (0.75, 0.15, 0.12), [bar],
                  lambda p: p, 50.0)
    ink = [h for h in msp.query("HATCH") if h.dxf.layer.endswith("-PATT")]
    assert ink and all(type(p).__name__ == "PolylinePath" for h in ink for p in h.paths)
    assert any(e.dxf.layer.endswith("-PATT") for e in msp.query("LWPOLYLINE"))


def test_review_three_classification_materials_and_occlusion(wall_section):
    """PR #3 third review: the kind survives the 40-character layer name;
    reinforced concrete is concrete; a multi-material product cuts per
    material; a cut face hides what lies behind it."""
    import numpy as np
    from types import SimpleNamespace as NS
    from bimforge.bim import developed as D
    from bimforge.bim.section_style import style_of
    # 1. classified on the layer as written, not the full name
    long = "Existing reinforced concrete (Br 12-3456), to be removed"
    el = NS(Name="E1", is_a=lambda *a: "IfcWall")
    layer, _ = D._cut_layer(el, NS(Name=long), [], [(0.6, 0.6, 0.6)], [(0.6, 0.6, 0.6)])
    assert style_of(layer.replace("E-CUT-", "")).kind == "Existing (to remove)"
    # 4. reinforced concrete is concrete; reinforcing steel is rebar
    assert style_of("Reinforced Concrete").kind == "Concrete"
    assert style_of("Reinforcing Steel").kind == "Reinforcing Steel"
    assert style_of("Reinforcement").kind == "Reinforcing Steel"
    # 2. the bar's solid added into the stem: the stem cuts as concrete AND rebar
    f = ifcopenshell.file.from_string(wall_section.to_string())
    stem = next(e for e in f.by_type("IfcWall") if e.Name == "stem")
    bar = next(e for e in f.by_type("IfcReinforcingBar"))
    s_rep = stem.Representation.Representations[0]
    b_item = bar.Representation.Representations[0].Items[0]
    s_rep.Items = list(s_rep.Items) + [b_item]
    D._BODY_CACHE.clear()
    layers = {layer for name, layer, *_ in D._all_bodies(f, None) if name == "stem"}
    assert layers == {"E-CUT-Concrete", "E-CUT-Reinforcing-Steel"}
    D._BODY_CACHE.clear()
    # 3. a cut face at depth 0 in the buffer, its hole left open
    zbuf = np.full((10, 10), np.inf)
    ring = [[(1, 1), (9, 1), (9, 9), (1, 9), (1, 1)],
            [(4, 4), (6, 4), (6, 6), (4, 6), (4, 4)]]
    D._raster_cut(zbuf, [("E-CUT-Concrete", (0.7, 0.7, 0.7), [ring])], 1.0, 0.0)
    assert zbuf[2, 2] == 0.0 and np.isinf(zbuf[5, 5]) and np.isinf(zbuf[0, 0])


@pytest.fixture(scope="module")
def dug(tmp_path_factory):
    """Ground 20 ft Lt to 20 ft Rt, El -12 to 0, with a 12 ft wide 6 ft deep
    excavation that VOIDS it (IfcEarthworksCut) and a footing in the hole."""
    ctx = _ctx()
    al = Alignment(POB, RUN, name="ML")
    m = StructureModel("dug", ctx)

    def body(name, ring, ifc, **kw):
        sw = SweptSection(name, ring, al, 1010.0, 1100.0, origin=ctx, ifc=ifc)
        m.add(Element.from_geometry(name, sw, ifc_class=ifc,
                                    quantities={"volume_cf": sw.volume_cf}, **kw))
    box = lambda x0, x1, z0, z1: [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]  # noqa: E731
    body("existing ground", box(-20, 20, -12, 0), "IfcGeographicElement")
    body("structure excavation", box(-6, 6, -6, 0), "IfcEarthworksCut")
    m.element("structure excavation").voids = "existing ground"
    body("footing", box(-4, 4, -6, -4), "IfcFooting")
    m.alignments.append((al, None))
    out = tmp_path_factory.mktemp("dug") / "dug.ifc"
    emit_ifc(m, str(out))
    return ifcopenshell.open(str(out))


def test_excavation_is_ground_removed_in_a_section(dug, tmp_path, monkeypatch):
    """The cut is never a fill: the ground shows the hole, the cut's outline
    is the dashed limit of excavation, and before its dig date (4D) it is
    still ground."""
    from shapely.geometry import Polygon
    from bimforge.bim import developed as D
    from bimforge.bim import schedule_state as SS

    def area(dr, layer):
        return sum(Polygon(p[0], p[1:]).area for lay, _r, ps in dr.cut if lay == layer
                   for p in ps)
    D._BODY_CACHE.clear()
    dr = cross_section(dug, SectionView("S", 1050.0, width=50.0, depth=1.0))
    layers = {lay for lay, _r, _p in dr.cut}
    assert D.LIMIT_LAYER not in layers and "E-CUT-Excavation" not in layers
    assert area(dr, "E-CUT-Earthwork") == pytest.approx(40 * 12 - 12 * 6, rel=1e-3)
    # the limit of excavation: the cut's outline, 6 + 12 + 6 ft of it
    total = sum(sum(math.dist(a, b) for a, b in zip(ln, ln[1:])) for ln in dr.limits)
    assert total == pytest.approx(6 + 12 + 6 + 12, abs=0.05)   # the top edge too
    out = tmp_path / "s.dxf"
    write_dxf([dr], str(out))
    import ezdxf
    doc = ezdxf.readfile(str(out))
    lims = [e for e in doc.modelspace().query("LWPOLYLINE") if e.dxf.layer == D.LIMIT_LAYER]
    assert lims and all(e.dxf.linetype == "DASHED" for e in lims)
    # 4D: dug on 2027-01-10; on 2027-01-05 the hole is still ground
    cut = dug.by_type("IfcEarthworksCut")[0]
    monkeypatch.setattr(SS, "element_spans",
                        lambda f: {cut.GlobalId: SS.Span("2027-01-10", None, ("dig",))})
    D._BODY_CACHE.clear()
    before = cross_section(dug, SectionView("B", 1050.0, width=50.0, depth=1.0,
                                            date="2027-01-05"))
    after = cross_section(dug, SectionView("A", 1050.0, width=50.0, depth=1.0,
                                           date="2027-01-12"))
    assert area(before, "E-CUT-Earthwork") == pytest.approx(40 * 12, rel=1e-3)
    assert area(after, "E-CUT-Earthwork") == pytest.approx(40 * 12 - 12 * 6, rel=1e-3)
    D._BODY_CACHE.clear()


def test_a_pay_item_excavation_body_is_ground_removed_too(tmp_path, monkeypatch):
    """The usual earthwork model: the ground already less the dig, the excavation an
    unhosted body (IfcEarthworksElement EXCAVATION, #364). It is drawn as the
    limit of excavation, never a block in the hole; before its dig, ground."""
    from shapely.geometry import Polygon
    from bimforge.bim import developed as D
    from bimforge.bim import schedule_state as SS
    ctx = _ctx()
    al = Alignment(POB, RUN, name="ML")
    m = StructureModel("holed", ctx)

    def body(name, ring, ifc):
        sw = SweptSection(name, ring, al, 1010.0, 1100.0, origin=ctx, ifc=ifc)
        m.add(Element.from_geometry(name, sw, ifc_class=ifc,
                                    quantities={"volume_cf": sw.volume_cf}))
    body("existing ground (remaining)", [(-20, -12), (20, -12), (20, 0), (6, 0), (6, -6),
                                         (-6, -6), (-6, 0), (-20, 0)], "IfcGeographicElement")
    body("structure excavation", [(-6, -6), (6, -6), (6, 0), (-6, 0)], "IfcEarthworksCut")
    m.alignments.append((al, None))
    out = tmp_path / "holed.ifc"
    emit_ifc(m, str(out))
    f = ifcopenshell.open(str(out))
    (exc,) = [e for e in f.by_type("IfcEarthworksElement") if D.is_excavation(e)]

    def area(dr):
        return sum(Polygon(p[0], p[1:]).area for lay, _r, ps in dr.cut for p in ps)
    D._BODY_CACHE.clear()
    dr = cross_section(f, SectionView("S", 1050.0, width=50.0, depth=1.0))
    assert area(dr) == pytest.approx(40 * 12 - 12 * 6, rel=1e-3)      # the hole, no block
    assert dr.limits
    monkeypatch.setattr(SS, "element_spans",
                        lambda f: {exc.GlobalId: SS.Span("2027-01-10", None, ("dig",))})
    D._BODY_CACHE.clear()
    before = cross_section(f, SectionView("B", 1050.0, width=50.0, depth=1.0,
                                          date="2027-01-05"))
    assert area(before) == pytest.approx(40 * 12, rel=1e-3)
    D._BODY_CACHE.clear()


def test_an_enclosed_cavity_stays_a_hole():
    """A body with a cavity wholly inside it (ground around a backfilled
    overexcavation) cuts as an outline with a hole, not a solid: polygonize
    returns the cavity as a face too."""
    from shapely.geometry import Polygon
    from bimforge.bim.developed import _polygons
    def ring(x0, x1, y0, y1):
        p = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
        return list(zip(p, p[1:] + p[:1]))
    rings = _polygons(ring(0, 10, 0, 10) + ring(4, 6, 4, 6), 0.0, 10.0)
    assert sum(Polygon(r[0], r[1:]).area for r in rings) == pytest.approx(100 - 4)
    # two separate bodies side by side both stay solid
    rings = _polygons(ring(0, 4, 0, 4) + ring(5, 9, 0, 4), 0.0, 10.0)
    assert sum(Polygon(r[0], r[1:]).area for r in rings) == pytest.approx(32)
