"""Plan-sheet contour extraction core (`bim.plansheet.contours`) — pure parts.

Everything here runs on synthetic segment lists — no PDFs, no pymupdf. The
segment stand-in duck-types the plansheet extractor's ``Segment`` (x1/y1/x2/
y2/width/color/length); the calibration stand-in duck-types a ``Zone``
(ft_per_pt/method/to_world). The PDF-dependent path (extract_sheet → real
Segment objects) is exercised by the CLI/e2e level, not here.
"""
from __future__ import annotations

import math
import types
from dataclasses import dataclass

import pytest

from bimforge.bim.plansheet.contours import (
    CHAIN_TOL_PT, LayerSpec, affine_coeffs, bridge, chain, extract_contours,
    georef_from_ties, georef_from_zone, is_closed, matches, ocg_table,
    parse_layer, parse_layer_spec, parse_selector, parse_tie, pen_table,
    polyline_length, select_segments, solve_georef, solve_georef_affine,
)


@dataclass(frozen=True)
class Seg:
    """Duck-typed stand-in for plansheet.vectors.Segment."""

    x1: float
    y1: float
    x2: float
    y2: float
    width: float = 0.72
    color: tuple | None = (0.5, 0.5, 0.5)
    layer: str | None = None

    @property
    def length(self) -> float:
        return math.hypot(self.x2 - self.x1, self.y2 - self.y1)


def grey_seg(a, b, grey=0.5, width=0.72):
    return Seg(a[0], a[1], b[0], b[1], width=width, color=(grey, grey, grey))


# ----------------------------------------------------------------- selectors
class TestParseLayer:
    def test_full_spec(self):
        assert parse_layer("EXIST=0.753@0.72") == ("EXIST", 0.753, 0.72)

    def test_width_omitted_means_any(self):
        assert parse_layer("PROP=0") == ("PROP", 0.0, None)

    def test_name_stripped(self):
        assert parse_layer(" EXIST =0.5@1.0")[0] == "EXIST"

    @pytest.mark.parametrize("spec", ["0.753@0.72", "A=x@y", "A=@", "A="])
    def test_bad_spec_raises(self, spec):
        with pytest.raises(ValueError):
            parse_layer(spec)


class TestParseSelector:
    def test_grey_and_width(self):
        assert parse_selector("0.753@0.72") == (0.753, 0.72)

    def test_grey_only(self):
        assert parse_selector("0.753") == (0.753, None)

    def test_bad_raises(self):
        with pytest.raises(ValueError):
            parse_selector("grey@wide")


class TestMatches:
    def test_grey_and_width_match(self):
        assert matches(grey_seg((0, 0), (1, 0), grey=0.753), 0.753, 0.72)

    def test_any_width_when_none(self):
        assert matches(grey_seg((0, 0), (1, 0), width=1.4), 0.5, None)

    def test_width_mismatch_rejected(self):
        assert not matches(grey_seg((0, 0), (1, 0), width=0.5), 0.5, 0.72)

    def test_grey_mismatch_rejected(self):
        assert not matches(grey_seg((0, 0), (1, 0), grey=0.7), 0.753, 0.72)

    def test_coloured_stroke_never_a_contour(self):
        s = Seg(0, 0, 1, 0, color=(0.8, 0.2, 0.2))
        assert not matches(s, 0.8, 0.72)

    def test_unstroked_rejected(self):
        assert not matches(Seg(0, 0, 1, 0, color=None), 0.5, 0.72)


# ------------------------------------------------------------------ chaining
class TestChain:
    def test_collinear_run_joins(self):
        segs = [grey_seg((0, 0), (1, 0)), grey_seg((1, 0), (2, 0)),
                grey_seg((2, 0), (3, 0))]
        out = chain(segs)
        assert len(out) == 1
        assert len(out[0]) == 4
        assert {out[0][0], out[0][-1]} == {(0.0, 0.0), (3.0, 0.0)}

    def test_reversed_segment_still_chains(self):
        segs = [grey_seg((0, 0), (1, 0)), grey_seg((2, 0), (1, 0))]
        out = chain(segs)
        assert len(out) == 1
        assert len(out[0]) == 3

    def test_tol_respected(self):
        segs = [grey_seg((0, 0), (1, 0)), grey_seg((1.2, 0), (2, 0))]
        assert len(chain(segs, tol=0.05)) == 2      # 0.2 pt gap stays a gap
        assert len(chain(segs, tol=0.5)) == 1       # coarser tol absorbs it

    def test_branch_stops_the_walk(self):
        # three segments share (1, 0): never guess a branch — a contour that
        # breaks in two is recoverable, one that jumps contours is not
        segs = [grey_seg((0, 0), (1, 0)), grey_seg((1, 0), (2, 0)),
                grey_seg((1, 0), (1, 1))]
        out = chain(segs)
        assert len(out) == 3
        assert all(len(c) == 2 for c in out)

    def test_degenerate_segment_dropped(self):
        assert chain([grey_seg((1, 1), (1, 1))]) == []

    def test_default_tol_is_chain_tol_pt(self):
        assert CHAIN_TOL_PT == 0.05


# ------------------------------------------------------------------ bridging
class TestBridge:
    def test_joins_across_gap_when_ends_point_at_each_other(self):
        chains = [[(0.0, 0.0), (10.0, 0.0)], [(15.0, 0.0), (25.0, 0.0)]]
        out = bridge(chains, gap_pt=6.0, max_turn_deg=25.0)
        assert len(out) == 1
        assert len(out[0]) == 4
        assert polyline_length(out[0]) == pytest.approx(25.0)

    def test_refuses_a_sharp_turn(self):
        # the jump is short but the second run heads off perpendicular —
        # the direction test is what stops hops onto a neighbouring contour
        chains = [[(0.0, 0.0), (10.0, 0.0)], [(12.0, 2.0), (12.0, 12.0)]]
        out = bridge(chains, gap_pt=6.0, max_turn_deg=25.0)
        assert len(out) == 2

    def test_refuses_a_gap_beyond_limit(self):
        chains = [[(0.0, 0.0), (10.0, 0.0)], [(20.0, 0.0), (30.0, 0.0)]]
        out = bridge(chains, gap_pt=6.0, max_turn_deg=25.0)
        assert len(out) == 2

    def test_dashed_run_restitches_in_order(self):
        # four dashes of one contour: 6 pt on, 3 pt off
        chains = [[(x, 0.0), (x + 6.0, 0.0)] for x in (0.0, 9.0, 18.0, 27.0)]
        out = bridge(chains, gap_pt=4.0, max_turn_deg=25.0)
        assert len(out) == 1
        xs = [p[0] for p in out[0]]
        assert xs == sorted(xs) or xs == sorted(xs, reverse=True)


# -------------------------------------------------------------------- georef
class TestParseTie:
    def test_roundtrip(self):
        assert parse_tie("100,200=5000.5,3000") == ((100.0, 200.0),
                                                    (5000.5, 3000.0))

    @pytest.mark.parametrize("spec", ["100,200", "a,b=1,2", "1=2", "1,2=3"])
    def test_bad_spec_raises(self, spec):
        with pytest.raises(ValueError):
            parse_tie(spec)


class TestSolveGeoref:
    #: known similarity: w = a*z + b, z = px + i*(-py), w = E + i*N
    A = 2.0 * complex(math.cos(math.radians(30)), math.sin(math.radians(30)))
    B = complex(1000.0, 500.0)

    def tie(self, px, py):
        w = self.A * complex(px, -py) + self.B
        return ((px, py), (w.imag, w.real))          # world spec is (N, E)

    def test_recovers_known_transform_from_two_ties(self):
        fn, scale, res = solve_georef([self.tie(100, 100), self.tie(400, 150)])
        assert scale == pytest.approx(2.0)
        assert all(r == pytest.approx(0.0, abs=1e-9) for r in res)
        w = self.A * complex(313.0, -77.0) + self.B
        e, n = fn(313.0, 77.0)
        assert e == pytest.approx(w.real)
        assert n == pytest.approx(w.imag)

    def test_three_ties_average_with_residuals(self):
        ties = [self.tie(100, 100), self.tie(400, 150), self.tie(250, 300)]
        fn, scale, res = solve_georef(ties)
        assert len(res) == 3
        assert scale == pytest.approx(2.0)

    def test_fewer_than_two_ties_raises(self):
        with pytest.raises(ValueError):
            solve_georef([self.tie(100, 100)])

    def test_coincident_ties_give_zero_scale(self):
        # both ties land on the same page point: the fit is degenerate, not
        # a real (if odd) similarity transform.
        fn, scale, res = solve_georef([((5.0, 5.0), (0.0, 0.0)),
                                       ((5.0, 5.0), (10.0, 10.0))])
        assert scale == 0.0


# ------------------------------------------------------------------ geometry
class TestGeometryHelpers:
    def test_polyline_length(self):
        assert polyline_length([(0, 0), (3, 0), (3, 4)]) == pytest.approx(7.0)

    def test_is_closed_square(self):
        square = [(0, 0), (1, 0), (1, 1), (0, 1), (0.001, 0.0)]
        assert is_closed(square, tol=0.01)
        assert not is_closed(square, tol=0.0001)

    def test_open_polyline_not_closed(self):
        assert not is_closed([(0, 0), (1, 0), (1, 1)], tol=0.01)

    def test_two_points_never_closed(self):
        assert not is_closed([(0, 0), (0, 0)], tol=1.0)


# ----------------------------------------------------------------- pen table
class TestPenTable:
    def test_groups_by_grey_width_and_chroma(self):
        segs = [grey_seg((0, 0), (10, 0), grey=0.753),
                grey_seg((0, 1), (10, 1), grey=0.753),
                grey_seg((0, 2), (5, 2), grey=0.0),
                Seg(0, 3, 5, 3, color=(0.9, 0.1, 0.1))]
        rows = pen_table(segs)
        assert rows[0] == {"grey": 0.753, "width": 0.72, "coloured": False,
                           "segments": 2, "length_pt": 20.0}
        coloured = [r for r in rows if r["coloured"]]
        assert len(coloured) == 1 and coloured[0]["segments"] == 1


# -------------------------------------------------------------- orchestrator
class FakeZone:
    """Duck-typed calibration zone: 2 ft/pt, y flipped (page y is down)."""

    ft_per_pt = 2.0
    method = "manual"

    def to_world(self, x, y):
        return (x * 2.0, -y * 2.0)


class FakeSheet:
    def __init__(self, segments):
        self.segments = segments


class TestExtractContours:
    def sheet(self):
        return FakeSheet([
            grey_seg((0, 0), (10, 0)),               # ┐ one 30 pt = 60 ft
            grey_seg((10, 0), (20, 0)),              # │ contour in three
            grey_seg((20, 0), (30, 0)),              # ┘ strokes
            grey_seg((0, 50), (5, 50)),              # 10 ft of leader junk
            grey_seg((0, 60), (30, 60), grey=0.0),   # wrong pen
        ])

    def test_selects_chains_filters_and_transforms(self):
        rec = extract_contours(self.sheet(), "0.5@0.72", FakeZone(),
                               min_length_ft=20.0)
        assert rec["frame"] == "sheet_local_ft"
        assert rec["segments"] == 4                  # both grey-0.5 features
        assert rec["polylines"] == 1                 # junk dropped at 20 ft
        (line,) = rec["lines"]
        assert line["length_ft"] == pytest.approx(60.0)
        assert line["points"][0] == [0.0, 0.0] or line["points"][-1] == [0.0, 0.0]
        assert line["closed"] is False
        assert line["elevation"] is None             # read visually, never here
        assert rec["ft_per_pt"] == 2.0

    def test_selector_tuple_accepted(self):
        rec = extract_contours(self.sheet(), (0.5, None), FakeZone(),
                               min_length_ft=20.0)
        assert rec["polylines"] == 1
        assert rec["selector"] == "0.5"

    def test_ties_switch_frame_to_state_plane(self):
        # world = (E, N) = (2*px, -2*py): a = 2, b = 0 in the tie model
        ties = [parse_tie("0,0=0,0"), parse_tie("10,0=0,20")]
        rec = extract_contours(self.sheet(), "0.5@0.72", FakeZone(),
                               min_length_ft=20.0, ties=ties)
        assert rec["frame"] == "state_plane_ft"
        assert rec["georef"]["scale_ft_per_pt"] == pytest.approx(2.0)
        assert rec["georef"]["ties"] == 2


class TestTieScaleConsistency:
    def test_tie_derived_scale_governs_tolerance_and_report(self):
        # Zone says 2 ft/pt but the ties georeference at 3 ft/pt: the record's
        # ft_per_pt (and the closure tolerance) must follow the tie-derived
        # frame the points are actually in (Copilot, PR #125).
        sheet = FakeSheet([grey_seg((0, 0), (10, 0)),
                           grey_seg((10, 0), (20, 0))])
        ties = [parse_tie("0,0=0,0"), parse_tie("10,0=0,30")]
        rec = extract_contours(sheet, "0.5@0.72", FakeZone(),
                               min_length_ft=1.0, ties=ties)
        assert rec["frame"] == "state_plane_ft"
        assert rec["ft_per_pt"] == pytest.approx(3.0)
        assert rec["georef"]["scale_ft_per_pt"] == pytest.approx(3.0)


# ------------------------------------------------------------- OCG selectors
class _ZoneStub:
    """Zone-like calibration: 1 ft per page point, y flipped."""

    ft_per_pt = 1.0
    method = "stub"

    @staticmethod
    def to_world(x, y):
        return (x, -y)


def ocg_seg(a, b, layer, grey=0.75, width=0.72):
    return Seg(a[0], a[1], b[0], b[1], width=width, color=(grey, grey, grey),
               layer=layer)


class TestParseLayerSpec:
    def test_pen_spec(self):
        assert parse_layer_spec("EXIST=0.753@0.72") == LayerSpec(
            "EXIST", "pen", grey=0.753, width=0.72)

    def test_ocg_spec_keeps_the_glob_verbatim(self):
        spec = parse_layer_spec("EXIST=ocg:*|C-TOPO-M*R-N")
        assert spec == LayerSpec("EXIST", "ocg", glob="*|C-TOPO-M*R-N")
        assert spec.selector == "ocg:*|C-TOPO-M*R-N"

    @pytest.mark.parametrize("spec", ["ocg:*", "A=ocg:", "=0.5", "A=x@y", "A"])
    def test_bad_specs_raise(self, spec):
        with pytest.raises(ValueError):
            parse_layer_spec(spec)


class TestSelectAndTable:
    def segs(self):
        return [ocg_seg((0, 0), (50, 0), "Topo|CONT_MNR"),
                ocg_seg((0, 10), (50, 10), "Topo|CONT_MJR", width=1.02),
                ocg_seg((0, 20), (50, 20), "Topo|E_TREE"),
                grey_seg((0, 30), (50, 30))]                 # untagged

    def test_ocg_glob_selects_by_name_case_sensitively(self):
        got = select_segments(self.segs(), parse_layer_spec("C=ocg:Topo|CONT_M*"))
        assert sorted(s.layer for s in got) == ["Topo|CONT_MJR", "Topo|CONT_MNR"]
        assert select_segments(self.segs(), parse_layer_spec("C=ocg:topo|*")) == []

    def test_pen_spec_still_selects_by_pen(self):
        got = select_segments(self.segs(), parse_layer_spec("P=0.5@0.72"))
        assert len(got) == 1 and got[0].layer is None

    def test_ocg_table_rows(self):
        rows = {r["layer"]: r for r in ocg_table(self.segs())}
        assert set(rows) == {"Topo|CONT_MNR", "Topo|CONT_MJR", "Topo|E_TREE", None}
        assert rows["Topo|CONT_MJR"]["pens"] == ["0.75@1.02"]
        assert rows["Topo|CONT_MNR"]["length_pt"] == pytest.approx(50.0)

    def test_ocg_table_empty_on_a_layer_flattened_sheet(self):
        assert ocg_table([grey_seg((0, 0), (50, 0))]) == []


class TestExtractContoursOcg:
    def sheet(self):
        # A and B meet end-to-end at x=100, but sit on different OCGs.
        return types.SimpleNamespace(segments=[
            ocg_seg((0, 0), (50, 0), "Topo|CONT_MNR"),
            ocg_seg((50, 0), (100, 0), "Topo|CONT_MNR"),
            ocg_seg((100, 0), (150, 0), "Topo|CONT_MJR"),
        ])

    def test_chains_per_layer_and_records_the_source(self):
        rec = extract_contours(self.sheet(), "ocg:Topo|CONT_M*", _ZoneStub(),
                               min_length_ft=1.0)
        by_ocg = {ln["source"]["ocg"]: ln for ln in rec["lines"]}
        assert set(by_ocg) == {"Topo|CONT_MNR", "Topo|CONT_MJR"}
        assert by_ocg["Topo|CONT_MNR"]["length_ft"] == pytest.approx(100.0)
        assert by_ocg["Topo|CONT_MJR"]["length_ft"] == pytest.approx(50.0)
        assert all(ln["source"]["kind"] == "vector-ocg" for ln in rec["lines"])
        assert rec["selector"] == "ocg:Topo|CONT_M*"

    def test_layerspec_selector_is_accepted(self):
        spec = parse_layer_spec("C=ocg:Topo|CONT_MNR")
        rec = extract_contours(self.sheet(), spec, _ZoneStub(), min_length_ft=1.0)
        assert rec["polylines"] == 1

    def test_pen_lines_record_their_selector(self):
        sheet = types.SimpleNamespace(segments=[grey_seg((0, 0), (40, 0))])
        rec = extract_contours(sheet, "0.5@0.72", _ZoneStub(), min_length_ft=1.0)
        assert rec["lines"][0]["source"] == {"kind": "vector-pen",
                                             "selector": "0.5@0.72"}

    def test_bare_ocg_selector_with_empty_glob_raises(self):
        # consistent with parse_layer_spec("A=ocg:") raising on an empty glob
        with pytest.raises(ValueError):
            extract_contours(self.sheet(), "ocg:", _ZoneStub(), min_length_ft=1.0)


# ------------------------------------------------------------------- Georef
def _stretch(x, y):
    """An anisotropic page->world map (paper stretch): (E, N)."""
    return (1000.0 + 2.0 * x + 0.1 * y, 5000.0 + 0.05 * x - 2.2 * y)


def _ties(fn, pts):
    return [((x, y), (fn(x, y)[1], fn(x, y)[0])) for x, y in pts]


class TestAffineGeoref:
    PTS = [(0.0, 0.0), (800.0, 0.0), (800.0, 500.0), (0.0, 500.0)]

    def test_recovers_an_anisotropic_stretch_exactly(self):
        fn, (sx, sy), res = solve_georef_affine(_ties(_stretch, self.PTS))
        assert fn(123.0, 45.0) == pytest.approx(_stretch(123.0, 45.0), abs=1e-6)
        assert max(res) < 1e-6
        assert sx == pytest.approx(math.hypot(2.0, 0.05))
        assert sy == pytest.approx(math.hypot(0.1, 2.2))

    def test_needs_three_ties(self):
        with pytest.raises(ValueError, match="three"):
            solve_georef_affine(_ties(_stretch, self.PTS[:2]))

    def test_rejects_collinear_ties(self):
        with pytest.raises(ValueError, match="collinear"):
            solve_georef_affine(_ties(_stretch, [(0, 0), (1, 1), (2, 2)]))

    def test_affine_coeffs_reproduce_the_map(self):
        a, b, c, d, e, f = affine_coeffs(_stretch)
        assert (a * 7 + b * 9 + c, d * 7 + e * 9 + f) == pytest.approx(_stretch(7, 9))


class TestGeorefBuilders:
    def test_similarity_ties_match_solve_georef(self):
        ties = [((0.0, 0.0), (0.0, 0.0)), ((100.0, 0.0), (0.0, 200.0))]
        g = georef_from_ties(ties)
        fn, scale, _ = solve_georef(ties)
        assert g.to_world(30.0, 40.0) == pytest.approx(fn(30.0, 40.0))
        assert (g.method, g.model, g.frame, g.n_ties) == ("ties", "similarity",
                                                          "state_plane_ft", 2)
        assert g.ft_per_pt == pytest.approx(scale)

    def test_affine_ties_average_the_two_scales(self):
        g = georef_from_ties(_ties(_stretch, TestAffineGeoref.PTS), "affine")
        assert g.ft_per_pt == pytest.approx(
            (math.hypot(2.0, 0.05) + math.hypot(0.1, 2.2)) / 2)

    def test_unknown_model_raises(self):
        with pytest.raises(ValueError, match="tie model"):
            georef_from_ties(_ties(_stretch, TestAffineGeoref.PTS), "bilinear")

    def test_coincident_ties_raise_instead_of_a_zero_scale_georef(self):
        # two ties at the same page point: the similarity fit is degenerate
        # (scale 0), which must not silently become a usable Georef.
        ties = [((5.0, 5.0), (0.0, 0.0)), ((5.0, 5.0), (10.0, 10.0))]
        with pytest.raises(ValueError, match="degenerate"):
            georef_from_ties(ties)

    def test_zero_affine_scale_raises(self, monkeypatch):
        # solve_georef_affine itself only guards collinearity; a fit that is
        # non-collinear but whose x-scale comes back zero (or non-finite)
        # must still be refused by georef_from_ties.
        import bimforge.bim.plansheet.contours as contours_mod

        def fake_solve(ties):
            return (lambda px, py: (0.0, 0.0)), (0.0, 2.0), [0.0, 0.0, 0.0]

        monkeypatch.setattr(contours_mod, "solve_georef_affine", fake_solve)
        ties = _ties(_stretch, TestAffineGeoref.PTS)
        with pytest.raises(ValueError, match="degenerate"):
            georef_from_ties(ties, "affine")

    def test_zone_georef_and_record_shape(self):
        g = georef_from_zone(_ZoneStub())
        rec = g.record()
        assert rec["method"] == "calibration" and rec["frame"] == "sheet_local_ft"
        assert rec["transform"] == pytest.approx([1.0, 0.0, 0.0, 0.0, -1.0, 0.0])
        assert "crs_epsg" not in rec
        assert rec["residuals_ft"] == []            # no residual_ft on the stub

    def test_zone_georef_carries_the_calibration_residual(self):
        zone = types.SimpleNamespace(to_world=_ZoneStub.to_world,
                                     ft_per_pt=1.0, residual_ft=0.8)
        g = georef_from_zone(zone)
        assert g.residuals_ft == (0.8,)
        assert g.record()["residuals_ft"] == [0.8]


class TestExtractContoursGeoref:
    def sheet(self):
        return types.SimpleNamespace(segments=[
            grey_seg((0, 0), (40, 0)),          # inside the bounds
            grey_seg((0, 90), (40, 90)),        # outside
        ])

    def test_explicit_georef_and_bounds(self):
        g = georef_from_ties([((0.0, 0.0), (0.0, 0.0)),
                              ((100.0, 0.0), (0.0, 200.0))])
        rec = extract_contours(self.sheet(), "0.5@0.72", georef=g,
                               bounds=(-1.0, -1.0, 50.0, 10.0), min_length_ft=1.0)
        assert rec["frame"] == "state_plane_ft"
        assert rec["outside_bounds"] == 1
        assert rec["polylines"] == 1
        assert rec["lines"][0]["length_ft"] == pytest.approx(80.0)
        assert rec["georef"]["ties"] == 2            # legacy per-layer block

    def test_needs_some_georeference(self):
        with pytest.raises(ValueError, match="georef"):
            extract_contours(self.sheet(), "0.5@0.72")


# --------------------------- ties vs GeoPDF cross-check (#231) ---------------
def _vp(transform, bbox=(-5.0, -5.0, 105.0, 5.0)):
    from bimforge.bim.plansheet.geopdf import Viewport
    return Viewport(0, bbox, 2226, "US survey foot", transform, [0.01], "viewport")


# two ties: page (0,0)->survey (E0,N0), page (100,0)->survey (E200,N0)
_TIES = [((0.0, 0.0), (0.0, 0.0)), ((100.0, 0.0), (0.0, 200.0))]


def test_crosscheck_agrees_when_viewport_matches_ties():
    from bimforge.bim.plansheet.contours import crosscheck_ties_vs_viewport
    vp = _vp((2.0, 0.0, 0.0, 0.0, -2.0, 0.0))          # E=2x, N=-2y
    drift, max_off, inside = crosscheck_ties_vs_viewport(_TIES, 2.0, vp)
    assert abs(drift) < 1e-6
    assert max_off < 1e-6
    assert inside


def test_crosscheck_flags_a_uniform_offset_a_residual_fit_would_hide():
    from bimforge.bim.plansheet.contours import crosscheck_ties_vs_viewport
    vp = _vp((2.0, 0.0, 30.0, 0.0, -2.0, 40.0))        # +30 E, +40 N shift
    drift, max_off, inside = crosscheck_ties_vs_viewport(_TIES, 2.0, vp)
    assert abs(drift) < 1e-6                            # scale is still right
    assert max_off == pytest.approx(50.0)              # hypot(30, 40)
    assert inside


def test_crosscheck_reports_scale_drift():
    from bimforge.bim.plansheet.contours import crosscheck_ties_vs_viewport
    vp = _vp((2.04, 0.0, 0.0, 0.0, -2.04, 0.0))        # 2% larger scale
    drift, _off, _inside = crosscheck_ties_vs_viewport(_TIES, 2.0, vp)
    assert drift == pytest.approx(100 * (2.0 / 2.04 - 1.0))
    assert abs(drift) > 1.0


def test_crosscheck_inside_is_false_when_a_tie_leaves_the_bbox():
    from bimforge.bim.plansheet.contours import crosscheck_ties_vs_viewport
    vp = _vp((2.0, 0.0, 0.0, 0.0, -2.0, 0.0), bbox=(-1.0, -1.0, 60.0, 5.0))
    _drift, _off, inside = crosscheck_ties_vs_viewport(_TIES, 2.0, vp)
    assert not inside                                  # tie at px=100 is outside


class TestClip:
    """Clip picked segments to a page rectangle (#243): fully-inside kept,
    fully-outside dropped, a crossing segment CUT at the boundary."""

    def test_fully_inside_is_unchanged(self):
        from bimforge.bim.plansheet.contours import clip_segment
        c = clip_segment(grey_seg((5, 5), (15, 15)), (0, 0, 20, 20))
        assert (c.x1, c.y1, c.x2, c.y2) == (5, 5, 15, 15)

    def test_fully_outside_is_dropped(self):
        from bimforge.bim.plansheet.contours import clip_segment
        assert clip_segment(grey_seg((30, 30), (40, 40)), (0, 0, 20, 20)) is None

    def test_crossing_is_cut_at_the_boundary(self):
        from bimforge.bim.plansheet.contours import clip_segment
        c = clip_segment(grey_seg((-10, 5), (10, 5)), (0, 0, 20, 20))
        assert (round(c.x1, 6), round(c.y1, 6)) == (0.0, 5.0)   # cut at x=0
        assert (round(c.x2, 6), round(c.y2, 6)) == (10.0, 5.0)

    def test_preserves_layer_and_pen(self):
        from bimforge.bim.plansheet.contours import clip_segment
        s = Seg(-5, 5, 10, 5, layer="Topo|CONT_MJR_DEP")
        c = clip_segment(s, (0, 0, 20, 20))
        assert c.layer == "Topo|CONT_MJR_DEP" and c.color == (0.5, 0.5, 0.5)

    def test_reversed_rect_is_normalized(self):
        from bimforge.bim.plansheet.contours import clip_segment
        c = clip_segment(grey_seg((5, 5), (15, 15)), (20, 20, 0, 0))
        assert c is not None

    def test_extract_contours_clip_drops_outside_and_counts(self):
        sheet = FakeSheet([
            grey_seg((0, 0), (30, 0)),            # a real 60 ft contour, inside
            grey_seg((100, 100), (103, 100)),     # title-block glyph, outside
        ])
        rec = extract_contours(sheet, "0.5@0.72", FakeZone(),
                               min_length_ft=20.0, clip=(-1, -1, 60, 5))
        assert rec["polylines"] == 1
        assert rec["clipped"] == 1
