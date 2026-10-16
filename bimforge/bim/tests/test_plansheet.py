"""PDF plan-sheet measurement path: calibrate → vectors/regions → measure+snap → QC.

Two tiers:

* A synthetic vector PDF authored in-test with fitz — a 45 ft x 30 ft deck
  rectangle at a known scale (0.9 pt/ft), interior lines, hatch micro-noise,
  a long carrier line with station ticks at 9.0 pt (= 10 ft), a graphic
  scale bar (4 x 9.0 pt subdivisions + half block), and (optionally) REAL
  lettered dimension strings beside the deck edges. Toggling the lettering
  off reproduces the flattened-signed-set case; the vision-hints handshake
  is exercised against it. Runs everywhere pymupdf is installed (CI).
* Local-only regressions against the signed Pioneer Ave plan set (all 21
  pages text-flattened; every sheet plots at HALF its lettered scale):
  sheet 4 auto-calibrates from station ticks + fixture-captured vision
  hints; sheet 13 is the documented no-geometric-source exit-2 case; the
  deck re-measures at 45.00 x 30.00 ft. Skipped unless the plan PDF exists
  (set EST_PIONEER_PDF to point at it).
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path

import pytest

fitz = pytest.importorskip("fitz")
ezdxf = pytest.importorskip("ezdxf")

from bimforge.bim import cli  # noqa: E402
from bimforge.bim.plansheet import detect  # noqa: E402
from bimforge.bim.plansheet.calibrate import (  # noqa: E402
    CalibrationError, CalibrationInsufficient, build_calibration,
    calibrate_zone_from_dimensions, load_calibration, parse_dimension,
    parse_scale, save_calibration,
)
from bimforge.bim.plansheet.crosscheck import (  # noqa: E402
    collect_lettered, cross_check, render_report,
)
from bimforge.bim.plansheet.hints import (  # noqa: E402
    HintsError, load_hints, parse_station,
)
from bimforge.bim.plansheet.measure import (  # noqa: E402
    measure_traces, world_segments, write_vectors_dxf,
)
from bimforge.bim.plansheet.regions import find_regions  # noqa: E402
from bimforge.bim.plansheet.snap import snap_point, snap_polyline  # noqa: E402
from bimforge.bim.plansheet.vectors import (  # noqa: E402
    extract_sheet, load_classes, normalize_dashes, rotate_to_visual,
    style_layer, visual_to_unrotated,
)

FIXTURES = Path(__file__).parent / "fixtures"

# ---------------------------------------------------------------------------
# Synthetic fixture: 45 ft x 30 ft deck at 0.9 pt/ft on a 612x792 page
# ---------------------------------------------------------------------------
PT_PER_FT = 0.9
FT_PER_PT = 1.0 / PT_PER_FT          # 1.111111...
RX0, RY0 = 100.0, 100.0              # deck rectangle, page points (y down)
RW_PT, RH_PT = 45.0 * PT_PER_FT, 30.0 * PT_PER_FT   # 40.5 x 27.0 pt
RX1, RY1 = RX0 + RW_PT, RY0 + RH_PT
PAGE_W, PAGE_H = 612.0, 792.0

# geometric calibration features (v2): both spacings are 9.0 pt = 10 ft
CARRIER_Y = 187.0
TICK_X0, TICK_SPACING_PT, N_TICKS = 200.0, 9.0, 6
BAR_X0, BAR_Y, BAR_SUBDIV_PT = 300.0, 700.0, 9.0

#: segments the extractor keeps: 4 deck edges + midspan + dashed centerline
#: + 4 legacy marks + 1 carrier + 6 ticks + 5 scale-bar strokes
N_SEGMENTS = 4 + 2 + 4 + 1 + N_TICKS + 5


def _write_sheet(path, rotate: int = 0, with_text: bool = True) -> str:
    """The synthetic plan sheet; ``with_text=False`` = flattened signed set."""
    doc = fitz.open()
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    # deck rectangle (four explicit edges, like plotted CAD linework)
    for a, b in (((RX0, RY0), (RX1, RY0)), ((RX1, RY0), (RX1, RY1)),
                 ((RX1, RY1), (RX0, RY1)), ((RX0, RY1), (RX0, RY0))):
        page.draw_line(a, b)
    # interior lines: a mid-span horizontal and a dashed centerline
    page.draw_line((RX0, (RY0 + RY1) / 2), (RX1, (RY0 + RY1) / 2))
    page.draw_line((RX0 - 9, RY0 + RH_PT / 2), (RX1 + 9, RY0 + RH_PT / 2),
                   dashes="[2 2] 0")
    # legacy short marks along the bottom edge (uneven family, stays noise)
    for i in range(4):
        x = RX0 + (i + 1) * RW_PT / 5.0
        page.draw_line((x, RY1 - 2.0), (x, RY1 + 2.0))
    # v2: station-tick carrier — a long line with 6 ticks at 9.0 pt (10 ft)
    page.draw_line((60.0, CARRIER_Y), (560.0, CARRIER_Y))
    for i in range(N_TICKS):
        x = TICK_X0 + i * TICK_SPACING_PT
        page.draw_line((x, CARRIER_Y - 3.0), (x, CARRIER_Y + 3.0))
    # v2: graphic scale bar — half block + 4 subdivisions, drawn end-to-end
    xs = [BAR_X0 - BAR_SUBDIV_PT / 2] + [BAR_X0 + i * BAR_SUBDIV_PT
                                         for i in range(5)]
    for a, b in zip(xs, xs[1:]):
        page.draw_line((a, BAR_Y), (b, BAR_Y))
    # hatch noise: sub-2pt micro strokes that the min_path_pt filter must drop
    for i in range(30):
        x = 300.0 + (i % 6) * 3.0
        y = 300.0 + (i // 6) * 3.0
        page.draw_line((x, y), (x + 1.0, y + 1.0))
    if with_text:
        # lettered dimensions beside their edges (the calibration evidence)
        page.insert_text((RX0 + RW_PT / 2 - 12, RY1 + 9), '45\'-0"', fontsize=6)
        page.insert_text((RX1 + 8, RY0 + RH_PT / 2 + 12), '30\'-0"', fontsize=6,
                         rotate=90)
    if rotate:
        page.set_rotation(rotate)
    doc.save(str(path))
    doc.close()
    return str(path)


def _calibrated(pdf) -> tuple:
    sv = extract_sheet(pdf, 0)
    calib = build_calibration(sv, 1)
    return sv, calib


def _corners_world(zone) -> list[tuple[float, float]]:
    return [zone.to_world(x, y)
            for x, y in ((RX0, RY1), (RX1, RY1), (RX1, RY0), (RX0, RY0))]


def _write_hints(path, entries, frame: str = "visual") -> str:
    import yaml
    Path(path).write_text(
        yaml.safe_dump({"frame": frame, "zone_hints": entries}),
        encoding="utf-8")
    return str(path)


# ---------------------------------------------------------------------------
# unit-level: parsing + frames
# ---------------------------------------------------------------------------
def test_parse_dimension_feet_inches_and_fractions():
    assert parse_dimension('45\'-0"') == [45.0]
    assert parse_dimension('BB TO EB 45\'-0" ALONG "P" LINE')[0] == 45.0
    assert parse_dimension('1\'-6"') == [1.5]
    assert parse_dimension('2\'-4 1/2"') == [2.375]
    assert parse_dimension('45\'-0" x 30\'-0"') == [45.0, 30.0]
    assert parse_dimension("no dims here 45 ft") == []


def test_parse_scale_forms():
    assert parse_scale("1in=40ft") == pytest.approx(40.0 / 72.0)
    assert parse_scale('1/4in=1ft') == pytest.approx(1.0 / 18.0)
    # lettered title-block forms (feet-inches right-hand side)
    assert parse_scale('1/8" = 1\'-0"') == pytest.approx(1.0 / 9.0)
    assert parse_scale('3/16" = 1\'-0"') == pytest.approx(1.0 / 13.5)
    with pytest.raises(CalibrationError):
        parse_scale("forty to one")


def test_parse_station():
    assert parse_station("106+00") == 10600.0
    assert parse_station("BB 105+97.90") == pytest.approx(10597.90)
    assert parse_station("no station") is None


def test_visual_round_trip():
    for rot in (0, 90, 180, 270):
        vx, vy = rotate_to_visual(123.4, 567.8, rot, PAGE_W, PAGE_H)
        assert visual_to_unrotated(vx, vy, rot, PAGE_W, PAGE_H) == \
            pytest.approx((123.4, 567.8))


def test_normalize_dashes():
    assert normalize_dashes("") == ""
    assert normalize_dashes("[] 0") == ""
    assert normalize_dashes("[ 7.92 3 1.98 3 ] 0") == "7.92,3,1.98,3"
    assert normalize_dashes([7.92, 3.0, 1.98, 3.0]) == "7.92,3,1.98,3"
    # phase is ignored
    assert normalize_dashes("[ 2 2 ] 1") == normalize_dashes("[2 2] 0")


# ---------------------------------------------------------------------------
# detect: ticks, scale bar (pure vector, flattening-immune)
# ---------------------------------------------------------------------------
def test_detect_ticks_and_scale_bar(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf", with_text=False)
    sv = extract_sheet(pdf, 0)
    fams = detect.detect_station_ticks(sv.segments)
    best = next(f for f in fams if f.count == N_TICKS)
    assert best.spacing_pt == pytest.approx(TICK_SPACING_PT, abs=0.05)
    assert best.spread_pct < 1.0
    bars = detect.detect_scale_bars(sv.segments)
    bar = next(b for b in bars if b.n_subdivs == 4)
    assert bar.subdiv_pt == pytest.approx(BAR_SUBDIV_PT, abs=0.05)
    assert bar.has_half
    # each spacing hypothesizes the standard world spacings
    hyps = dict(detect.spacing_candidates(best.spacing_pt))
    assert hyps[10.0] == pytest.approx(FT_PER_PT, rel=0.005)


# ---------------------------------------------------------------------------
# calibrate: pooled consensus on the synthetic sheet
# ---------------------------------------------------------------------------
def test_calibrate_consensus_text_plus_geometry(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    sv, calib = _calibrated(pdf)
    zone = calib.zones[0]
    assert zone.method.startswith("consensus:")
    assert "text_dims" in zone.method and "ticks" in zone.method
    assert zone.ft_per_pt == pytest.approx(FT_PER_PT, rel=0.001)   # within 0.1%
    assert zone.residual_ft is not None and zone.residual_ft < 0.05
    assert "consensus" in zone.evidence
    assert not calib.warnings
    assert calib.evidence_reports and calib.evidence_reports[0]["accepted"]


def test_calibrate_flattened_hints_auto_accept(tmp_path):
    """The vision handshake: no text layer, agent-read hints + geometry."""
    pdf = _write_sheet(tmp_path / "flat.pdf", with_text=False)
    sv = extract_sheet(pdf, 0)
    assert sv.texts == []
    hints_file = _write_hints(tmp_path / "hints.yaml", [
        {"kind": "dimension", "text": '45\'-0"',
         "near_pt": [RX0 + RW_PT / 2, RY1 + 9]},   # below the bottom edge
    ])
    hints = load_hints(hints_file, sv)
    calib = build_calibration(sv, 1, hints=hints)
    zone = calib.zones[0]
    assert zone.method.startswith("consensus:")
    assert "hints" in zone.method
    assert zone.ft_per_pt == pytest.approx(FT_PER_PT, rel=0.001)


def test_calibrate_flattened_no_hints_insufficient(tmp_path):
    pdf = _write_sheet(tmp_path / "flat.pdf", with_text=False)
    sv = extract_sheet(pdf, 0)
    with pytest.raises(CalibrationInsufficient) as ei:
        build_calibration(sv, 1)
    report = ei.value.reports[0]
    assert report["accepted"] is None
    assert report["candidates"]                     # geometry proposed values
    assert "hints" in report["note"]
    # the true scale IS among the hypothesis candidates, awaiting confirmation
    assert any(abs(c["ft_per_pt"] - FT_PER_PT) < 0.005 * FT_PER_PT
               for c in report["candidates"])


def test_scale_note_never_accepts_alone_and_is_contradicted(tmp_path):
    """Title blocks lie: a scale note agreeing with a geometric hypothesis
    still cannot auto-accept (no measured member); once real evidence wins,
    the lying note is reported CONTRADICTED, not dropped."""
    pdf = _write_sheet(tmp_path / "flat.pdf", with_text=False)
    sv = extract_sheet(pdf, 0)
    # "1in=40ft" = 0.5556 ft/pt — exactly the ticks' 5 ft hypothesis
    # (9.0 pt spacing), the half-size-plot trap
    note_only = load_hints(_write_hints(tmp_path / "h1.yaml", [
        {"kind": "scale_note", "text": "1in=40ft", "near_pt": [500.0, 80.0]},
    ]), sv)
    with pytest.raises(CalibrationInsufficient):
        build_calibration(sv, 1, hints=note_only)

    both = load_hints(_write_hints(tmp_path / "h2.yaml", [
        {"kind": "scale_note", "text": "1in=40ft", "near_pt": [500.0, 80.0]},
        {"kind": "dimension", "text": '45\'-0"',
         "near_pt": [RX0 + RW_PT / 2, RY1 + 9]},
    ]), sv)
    calib = build_calibration(sv, 1, hints=both)
    assert calib.zones[0].ft_per_pt == pytest.approx(FT_PER_PT, rel=0.001)
    assert any("CONTRADICTED" in w and "1in=40ft" in w for w in calib.warnings)


def test_contradicted_wrong_dimension_hint_is_flagged(tmp_path):
    """A misread dimension: consensus still lands on the evidence, and the
    disagreeing hint is listed."""
    pdf = _write_sheet(tmp_path / "sheet.pdf")            # live text present
    sv = extract_sheet(pdf, 0)
    bad = load_hints(_write_hints(tmp_path / "h.yaml", [
        {"kind": "dimension", "text": '48\'-0"',          # misread 45 as 48
         "near_pt": [RX0 + RW_PT / 2, RY1 + 9]},
    ]), sv)
    calib = build_calibration(sv, 1, hints=bad)
    assert calib.zones[0].ft_per_pt == pytest.approx(FT_PER_PT, rel=0.001)
    assert any("CONTRADICTED" in w for w in calib.warnings)


def _harmonic_candidates():
    """Two eligible clusters at an exact 2x ratio — the #249 field failure. The
    doubled value (a half-inch segment read as the note's inch) out-weighs the
    true one, so plain weight-ranked consensus accepts 2x the scale (areas 4x)
    with a confident three-source label. Values are the reporter's sheet A."""
    from bimforge.bim.plansheet.calibrate import Candidate
    doubled, true = 0.555715, 0.277903            # ratio 0.50008 ~ exactly 1/2
    return [
        # doubled cluster (winner by weight): text_dims measured + bar + 2 ticks
        Candidate(source="text_dims", kind="dimension_string", ft_per_pt=doubled,
                  measured=True, length_pt=36.0, world_ft=20.0,
                  detail="'1\" = 20'-0\"' vs 36.00 pt segment"),
        Candidate(source="scale_bar", kind="scale_bar@10ft", ft_per_pt=doubled),
        Candidate(source="ticks", kind="tick_family@50ft", ft_per_pt=doubled),
        Candidate(source="ticks", kind="tick_family@50ft", ft_per_pt=doubled),
        # true cluster: a POPULATED measured sibling at exactly half
        Candidate(source="text_dims", kind="dimension_string", ft_per_pt=true,
                  measured=True, length_pt=72.0, world_ft=20.0,
                  detail="'1\" = 20'-0\"' vs 72.00 pt segment"),
        Candidate(source="ticks", kind="tick_family@100ft", ft_per_pt=true),
    ]


def test_consensus_refuses_harmonic_double_scale():
    """#249: when the winning cluster sits at exactly 2x (or 1/2x) another
    POPULATED, measured cluster, the scale is harmonically ambiguous — geometry
    alone cannot tell inch from half-inch. Refuse to auto-accept (return None)
    so the agent disambiguates with an independent measured source, rather than
    silently shipping a 2x scale / 4x areas."""
    from bimforge.bim.plansheet.calibrate import consensus
    value, clusters = consensus(_harmonic_candidates())
    assert value is None
    # the conflict is recorded on both clusters so the evidence report explains it
    conflicted = [c for c in clusters if c.get("harmonic_conflict") is not None]
    assert len(conflicted) == 2
    vals = sorted(round(c["ft_per_pt"], 6) for c in conflicted)
    assert vals == [0.277903, 0.555715]


def test_consensus_accepts_when_no_harmonic_sibling():
    """Control: the SAME winning cluster auto-accepts normally once the doubled
    sibling is absent — the guard is specific to the harmonic conflict, not a
    blanket refusal of a weight-ranked winner."""
    from bimforge.bim.plansheet.calibrate import consensus
    cands = [c for c in _harmonic_candidates() if c.ft_per_pt > 0.4]
    value, clusters = consensus(cands)
    assert value == pytest.approx(0.555715)
    assert all(c.get("harmonic_conflict") is None for c in clusters)


def test_harmonic_double_scale_reports_insufficient_with_note(tmp_path):
    """End-to-end shape: a harmonic conflict must surface as the evidence
    report an agent reads — accepted None, a note that names the conflict and
    points at an independent measured source (the /Annots station chain)."""
    from bimforge.bim.plansheet.calibrate import _zone_report, consensus
    cands = _harmonic_candidates()
    value, clusters = consensus(cands)
    report = _zone_report("full", (0.0, 0.0, 100.0, 100.0), cands, clusters, None)
    assert report["accepted"] is None
    assert "harmonic" in report["note"].lower()
    assert "2x" in report["note"] or "half" in report["note"].lower()


def test_calibration_yaml_round_trip(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    _sv, calib = _calibrated(pdf)
    out = tmp_path / "calib.yaml"
    save_calibration(calib, out)
    back = load_calibration(out)
    assert back.sheet == 1 and back.page_index == 0
    z0, z1 = calib.zones[0], back.zones[0]
    assert z1.ft_per_pt == pytest.approx(z0.ft_per_pt)
    assert z1.method == z0.method and z1.method.startswith("consensus:")
    assert z1.page_size_pt == (PAGE_W, PAGE_H)
    assert z1.to_world(RX0, RY1) == pytest.approx(z0.to_world(RX0, RY1))


def test_manual_override_warns_single_evidence(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    sv = extract_sheet(pdf, 0)
    calib = build_calibration(sv, 1, scale="1in=40ft")
    assert calib.zones[0].method == "manual"
    assert calib.zones[0].ft_per_pt == pytest.approx(40.0 / 72.0)
    assert any("single evidence" in w or ">=2" in w for w in calib.warnings)


def test_calibrate_no_evidence_raises(tmp_path):
    doc = fitz.open()
    doc.new_page(width=200, height=200)          # blank page: nothing at all
    pdf = tmp_path / "blank.pdf"
    doc.save(str(pdf))
    doc.close()
    sv = extract_sheet(pdf, 0)
    with pytest.raises(CalibrationInsufficient):
        build_calibration(sv, 1)
    # the v1 single-method API still reports its own absence of evidence
    with pytest.raises(CalibrationError, match="no dimension-string evidence"):
        calibrate_zone_from_dimensions(sv, "full", (0, 0, 200, 200))


def test_alignment_passthrough(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    sv = extract_sheet(pdf, 0)
    alignment = {"bearing_dms": [1, 13, 24],
                 "ties": [[10407.90, 2121065.09, 6441894.16]],
                 "crs_epsg": 2227}
    calib = build_calibration(sv, 1, alignment=alignment)
    out = tmp_path / "calib.yaml"
    save_calibration(calib, out)
    back = load_calibration(out)
    assert back.alignment == alignment
    assert back.zones[0].world == "station_offset"


def test_hints_validation_errors(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    sv = extract_sheet(pdf, 0)
    with pytest.raises(HintsError, match="kind"):
        load_hints(_write_hints(tmp_path / "h1.yaml", [
            {"kind": "guess", "text": "x", "near_pt": [1, 2]}]), sv)
    with pytest.raises(HintsError, match="feet-inches"):
        load_hints(_write_hints(tmp_path / "h2.yaml", [
            {"kind": "dimension", "text": "45 ft", "near_pt": [1, 2]}]), sv)
    with pytest.raises(HintsError, match="near_pt"):
        load_hints(_write_hints(tmp_path / "h3.yaml", [
            {"kind": "dimension", "text": '45\'-0"', "near_pt": [1]}]), sv)
    with pytest.raises(HintsError, match="station"):
        load_hints(_write_hints(tmp_path / "h4.yaml", [
            {"kind": "station_label", "text": "BB", "near_pt": [1, 2]}]), sv)


# ---------------------------------------------------------------------------
# vectors: extraction, micro filter, world lengths, /Rotate, classes
# ---------------------------------------------------------------------------
def test_vectors_lengths_and_micro_filter(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    sv, calib = _calibrated(pdf)
    zone = calib.zones[0]
    # hatch noise (1.4 pt strokes) filtered; ticks and linework kept
    assert len(sv.segments) == N_SEGMENTS
    lengths = sorted(round(math.dist(*seg), 2) for seg in world_segments(sv, zone))
    assert lengths.count(45.0) == 3            # top + bottom edges + mid-span line
    assert lengths.count(30.0) == 2            # left + right edges
    dashed = [s for s in sv.segments if s.dashes]
    assert len(dashed) == 1
    assert style_layer(dashed[0]).startswith("V-DASH-")
    assert style_layer(sv.segments[0]) == "V-SOLID"


def test_classes_map_layers(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    sv = extract_sheet(pdf, 0)
    cpath = tmp_path / "classes.yaml"
    cpath.write_text("classes:\n  CL: \"[2 2] 0\"\n", encoding="utf-8")
    classes = load_classes(cpath)
    dashed = next(s for s in sv.segments if s.dashes)
    assert style_layer(dashed, classes) == "V-CL"
    assert style_layer(dashed) .startswith("V-DASH-")
    with pytest.raises(ValueError, match="classes"):
        bad = tmp_path / "bad.yaml"
        bad.write_text("nope: 1\n", encoding="utf-8")
        load_classes(bad)


def test_vectors_dxf_layers_by_style(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    sv, calib = _calibrated(pdf)
    out = tmp_path / "vectors.dxf"
    info = write_vectors_dxf(sv, calib.zones[0], out)
    assert info["segments"] == N_SEGMENTS
    assert info["layers"]["V-SOLID"] == N_SEGMENTS - 1
    assert sum(v for k, v in info["layers"].items() if k.startswith("V-DASH-")) == 1
    doc = ezdxf.readfile(str(out))
    from ezdxf import units as _u
    assert doc.header["$INSUNITS"] == _u.FT    # feet
    assert len(doc.modelspace().query("LINE")) == N_SEGMENTS


def test_rotated_page_measures_identically(tmp_path):
    pdf = _write_sheet(tmp_path / "rot.pdf", rotate=90)
    sv, calib = _calibrated(pdf)
    zone = calib.zones[0]
    assert sv.rotation == 90 and zone.rotation_deg == 90
    assert zone.ft_per_pt == pytest.approx(FT_PER_PT, rel=0.001)
    lengths = sorted(round(math.dist(*seg), 2) for seg in world_segments(sv, zone))
    assert lengths.count(45.0) == 3 and lengths.count(30.0) == 2
    # world edges stay axis-aligned after the /Rotate mapping
    (ax, ay), (bx, by) = world_segments(sv, zone)[0]
    assert min(abs(ax - bx), abs(ay - by)) < 1e-6


# ---------------------------------------------------------------------------
# regions: closed loops from the vector soup
# ---------------------------------------------------------------------------
def test_regions_find_deck_faces(tmp_path):
    """The deck closes into faces of the planar arrangement: the mid-span
    line splits the 45x30 rectangle into two 45x15 halves whose areas sum
    to the footprint (regions are faces — pick and sum)."""
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    sv, calib = _calibrated(pdf)
    regions = find_regions(sv.segments)
    assert len(regions) == 2
    for r in regions:
        assert r.area_pt2 == pytest.approx(RW_PT * RH_PT / 2, rel=0.001)
        assert r.feature_class == "SOLID"
        assert r.layer == "V-REGION-SOLID"
    total_ft2 = sum(r.area_pt2 for r in regions) * calib.zones[0].ft_per_pt ** 2
    assert total_ft2 == pytest.approx(45.0 * 30.0, rel=0.002)


def test_cli_vectors_regions_json(tmp_path, capsys):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    assert cli.main(["calibrate", "--pdf", pdf, "--sheet", "1",
                     "--out", str(tmp_path / "calib.yaml")]) == 0
    rj = tmp_path / "regions.json"
    assert cli.main(["vectors", "--pdf", pdf, "--sheet", "1",
                     "--calib", str(tmp_path / "calib.yaml"),
                     "--regions", "--regions-json", str(rj),
                     "--out", str(tmp_path / "vectors.dxf")]) == 0
    out = capsys.readouterr().out
    assert "closed regions" in out
    data = json.loads(rj.read_text(encoding="utf-8"))
    assert len(data["regions"]) == 2               # two 45x15 deck halves
    for row in data["regions"]:
        assert row["layer"] == "V-REGION-SOLID"
        assert row["area_ft2"] == pytest.approx(675.0, rel=0.002)
        assert row["area_sy"] == pytest.approx(75.0, rel=0.002)
    doc = ezdxf.readfile(str(tmp_path / "vectors.dxf"))
    polys = doc.modelspace().query('LWPOLYLINE[layer=="V-REGION-SOLID"]')
    assert len(polys) == 2 and all(p.closed for p in polys)


# ---------------------------------------------------------------------------
# snap
# ---------------------------------------------------------------------------
def test_snap_prefers_endpoint_over_projection():
    segs = [((0.0, 0.0), (10.0, 0.0))]
    r = snap_point((0.05, 0.05), segs, tol=0.15)
    assert r.snapped and r.point == (0.0, 0.0)          # corner, not (0.05, 0)
    r = snap_point((5.0, 0.1), segs, tol=0.15)
    assert r.snapped and r.point == (5.0, 0.0)          # mid-edge projection
    r = snap_point((5.0, 5.0), segs, tol=0.15)
    assert not r.snapped and r.point == (5.0, 5.0)
    assert r.distance == pytest.approx(5.0)


def test_snap_polyline_flags_per_vertex():
    segs = [((0.0, 0.0), (10.0, 0.0))]
    rs = snap_polyline([(0.1, 0.0), (99.0, 99.0)], segs, tol=0.15)
    assert [r.snapped for r in rs] == [True, False]


# ---------------------------------------------------------------------------
# measure: end-to-end through the CLI (+ QC cross-check)
# ---------------------------------------------------------------------------
def _layer_map(tmp_path) -> Path:
    import yaml
    p = tmp_path / "layer_map.yaml"
    p.write_text(yaml.safe_dump({
        "project": {"name": "plansheet test"},
        "units": {"dxf_length_unit": "ft"},
        "layers": {
            "S-DECK": {"ifc_class": "IfcSlab", "feature": "area", "height": 0.5},
            "S-PILE": {"ifc_class": "IfcPile", "feature": "count", "height": 10.0},
        },
    }), encoding="utf-8")
    return p


def _measure_setup(tmp_path, trace_pts, *, extra_layers=None) -> dict:
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    rc = cli.main(["calibrate", "--pdf", pdf, "--sheet", "1",
                   "--out", str(tmp_path / "calib.yaml")])
    assert rc == 0
    layers = {"S-DECK": [{"closed": True, "points": [list(p) for p in trace_pts]}]}
    layers.update(extra_layers or {})
    (tmp_path / "traces.json").write_text(json.dumps({"layers": layers}),
                                          encoding="utf-8")
    return {"pdf": pdf, "calib": str(tmp_path / "calib.yaml"),
            "traces": str(tmp_path / "traces.json"),
            "layer_map": str(_layer_map(tmp_path)),
            "out": str(tmp_path / "takeoff.dxf"),
            "sidecar": str(tmp_path / "prov.json"),
            "report": str(tmp_path / "qc.md")}


def _shoelace(pts) -> float:
    a = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


def test_measure_snaps_perturbed_trace_to_cad_precision(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    _sv, calib = _calibrated(pdf)
    zone = calib.zones[0]
    jitter = [(0.05, -0.04), (-0.05, 0.05), (0.04, 0.05), (-0.03, -0.05)]
    trace = [(x + dx, y + dy)
             for (x, y), (dx, dy) in zip(_corners_world(zone), jitter)]
    # a mid-mark pile point, also perturbed
    tick_x = RX0 + RW_PT / 5.0
    px, py = zone.to_world(tick_x, RY1)
    args = _measure_setup(
        tmp_path, trace,
        extra_layers={"S-PILE": [{"points": [[px + 0.04, py - 0.03]]}]})
    rc = cli.main(["measure", "--pdf", args["pdf"], "--sheet", "1",
                   "--calib", args["calib"], "--traces", args["traces"],
                   "--layer-map", args["layer_map"], "--out", args["out"],
                   "--sidecar", args["sidecar"], "--report", args["report"]])
    assert rc == 0

    doc = ezdxf.readfile(args["out"])
    msp = doc.modelspace()
    polys = msp.query('LWPOLYLINE[layer=="S-DECK"]')
    assert len(polys) == 1 and polys[0].closed
    pts = [(p[0], p[1]) for p in polys[0].get_points("xy")]
    area = _shoelace(pts)
    assert area == pytest.approx(45.0 * 30.0, rel=0.002)     # within 0.2%
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    assert max(xs) - min(xs) == pytest.approx(45.0, abs=0.01)
    assert max(ys) - min(ys) == pytest.approx(30.0, abs=0.01)

    inserts = msp.query('INSERT[layer=="S-PILE"]')            # dxf2bim count path
    assert len(inserts) == 1
    ip = inserts[0].dxf.insert
    # snapped onto the mark/edge linework near the proposed point (mid-segment
    # projection, so one coordinate keeps a sub-tolerance offset)
    assert (ip.x, ip.y) == pytest.approx((px, py), abs=0.06)

    prov = json.loads(Path(args["sidecar"]).read_text(encoding="utf-8"))
    assert prov["unsnapped_vertices"] == 0
    ent = {e["layer"]: e for e in prov["entities"]}
    assert all(not f for f in ent["S-DECK"]["unsnapped"])
    assert all(d <= 0.15 for d in ent["S-DECK"]["snap_dist_ft"])
    assert prov["zones"]["full"]["method"].startswith("consensus:")

    # QC cross-check: live 45'-0"/30'-0" spans verify the deck; the pile
    # (a count entity, nothing lettered) is UNVERIFIED — listed, not omitted
    assert ent["S-DECK"]["confidence"] == "ok"
    checked = {r["lettered_ft"] for r in ent["S-DECK"]["crosscheck"]}
    assert checked == {45.0, 30.0}
    assert all(r["status"] == "OK" and r["delta_pct"] <= 0.5
               for r in ent["S-DECK"]["crosscheck"])
    assert ent["S-PILE"]["confidence"] == "unverified"
    report = Path(args["report"]).read_text(encoding="utf-8")
    assert "| S-DECK[0] |" in report and "OK" in report
    assert "UNVERIFIED" in report


def test_crosscheck_review_flag_from_wrong_hint(tmp_path):
    """A lettered value disagreeing >0.5% with the vector measurement flags
    REVIEW (flattened sheet: the lettering arrives as a dimension hint)."""
    pdf = _write_sheet(tmp_path / "flat.pdf", with_text=False)
    sv = extract_sheet(pdf, 0)
    calib = build_calibration(sv, 1, ft_per_pt=FT_PER_PT)
    zone = calib.zones[0]
    traces = {"layers": {"S-DECK": [{"closed": True,
                                     "points": [list(p) for p in _corners_world(zone)]}]}}
    import yaml
    lm = yaml.safe_load(_layer_map(tmp_path).read_text(encoding="utf-8"))
    res = measure_traces(sv, calib, traces, lm, tmp_path / "t.dxf")
    hints = load_hints(_write_hints(tmp_path / "h.yaml", [
        {"kind": "dimension", "text": '46\'-0"',        # letters say 46
         "near_pt": [RX0 + RW_PT / 2, RY1 + 9]},
    ]), sv)
    rows = cross_check(res.sidecar, collect_lettered(sv, calib, hints))
    assert any(r.status == "REVIEW" for r in rows)
    assert res.sidecar[0]["confidence"] == "review"
    md = render_report(rows)
    assert "REVIEW" in md


def test_crosscheck_zero_dimension_lettering_ignored(tmp_path):
    """A lettered 0'-0\" must not reach cross_check (division by lettered
    feet) — non-positive parses are dropped at collection."""
    pdf = _write_sheet(tmp_path / "flat.pdf", with_text=False)
    sv = extract_sheet(pdf, 0)
    calib = build_calibration(sv, 1, ft_per_pt=FT_PER_PT)
    zone = calib.zones[0]
    traces = {"layers": {"S-DECK": [{"closed": True,
                                     "points": [list(p) for p in _corners_world(zone)]}]}}
    import yaml
    lm = yaml.safe_load(_layer_map(tmp_path).read_text(encoding="utf-8"))
    res = measure_traces(sv, calib, traces, lm, tmp_path / "t.dxf")
    hints = load_hints(_write_hints(tmp_path / "h.yaml", [
        {"kind": "dimension", "text": '0\'-0"',
         "near_pt": [RX0 + RW_PT / 2, RY1 + 9]},
    ]), sv)
    lettered = collect_lettered(sv, calib, hints)
    assert lettered == []                       # dropped, not carried as 0.0
    rows = cross_check(res.sidecar, lettered)   # must not raise
    assert res.sidecar[0]["confidence"] == "unverified"
    assert all(r.status == "UNVERIFIED" for r in rows)


def test_entity_gate_dist_open_polyline_has_no_closing_edge():
    """Open polylines must not synthesize a closing edge — it would shrink
    the gate distance and adopt unrelated lettering (closed ones keep it)."""
    from bimforge.bim.plansheet.crosscheck import _entity_gate_dist
    pts = [(0.0, 0.0), (100.0, 0.0), (100.0, 50.0)]
    probe = (50.0, 25.0)   # on the would-be closing edge, 25 ft off real edges
    assert _entity_gate_dist(pts, *probe, closed=False) == pytest.approx(25.0)
    assert _entity_gate_dist(pts, *probe, closed=True) == pytest.approx(0.0, abs=1e-9)


def test_measure_far_point_flags_unsnapped_and_fails(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    _sv, calib = _calibrated(pdf)
    corners = _corners_world(calib.zones[0])
    bad = corners[:3] + [(corners[3][0] + 5.0, corners[3][1] + 5.0)]   # 5 ft off
    args = _measure_setup(tmp_path, bad)
    base = ["measure", "--pdf", args["pdf"], "--calib", args["calib"],
            "--traces", args["traces"], "--layer-map", args["layer_map"],
            "--out", args["out"], "--sidecar", args["sidecar"]]
    assert cli.main(base) != 0                                # blocked
    assert cli.main(base + ["--allow-unsnapped"]) == 0        # explicit override
    prov = json.loads(Path(args["sidecar"]).read_text(encoding="utf-8"))
    assert prov["unsnapped_vertices"] == 1
    assert prov["entities"][0]["unsnapped"] == [False, False, False, True]


def test_measure_rejects_unmapped_layer(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    _sv, calib = _calibrated(pdf)
    args = _measure_setup(tmp_path, _corners_world(calib.zones[0]))
    Path(args["traces"]).write_text(json.dumps(
        {"layers": {"S-NOPE": [{"closed": True, "points": [[0, 0], [1, 0], [1, 1]]}]}}),
        encoding="utf-8")
    rc = cli.main(["measure", "--pdf", args["pdf"], "--calib", args["calib"],
                   "--traces", args["traces"], "--layer-map", args["layer_map"],
                   "--out", args["out"]])
    assert rc == 1


# ---------------------------------------------------------------------------
# CLI: vectors, render, exit-2 evidence report
# ---------------------------------------------------------------------------
def test_cli_vectors_subcommand(tmp_path, capsys):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    assert cli.main(["calibrate", "--pdf", pdf, "--sheet", "1",
                     "--out", str(tmp_path / "calib.yaml")]) == 0
    assert cli.main(["vectors", "--pdf", pdf, "--sheet", "1",
                     "--calib", str(tmp_path / "calib.yaml"),
                     "--out", str(tmp_path / "vectors.dxf")]) == 0
    out = capsys.readouterr().out
    assert "V-SOLID" in out
    assert (tmp_path / "vectors.dxf").is_file()


def test_cli_sheet_mismatch_errors(tmp_path):
    pdf = _write_sheet(tmp_path / "sheet.pdf")
    assert cli.main(["calibrate", "--pdf", pdf, "--sheet", "1",
                     "--out", str(tmp_path / "calib.yaml")]) == 0
    rc = cli.main(["vectors", "--pdf", pdf, "--sheet", "2",
                   "--calib", str(tmp_path / "calib.yaml"),
                   "--out", str(tmp_path / "v.dxf")])
    assert rc == 1


def test_cli_render_and_exit2_evidence(tmp_path, capsys):
    pdf = _write_sheet(tmp_path / "flat.pdf", with_text=False)
    png = tmp_path / "sheet.png"
    ev = tmp_path / "evidence.json"
    rc = cli.main(["calibrate", "--pdf", pdf, "--sheet", "1",
                   "--render", str(png), "--dpi", "96",
                   "--evidence", str(ev),
                   "--out", str(tmp_path / "calib.yaml")])
    assert rc == 2                                   # insufficient evidence
    out = capsys.readouterr().out
    assert png.is_file()                             # rendered before failing
    assert "1 px = 0.750000 pt" in out               # 72/96
    data = json.loads(ev.read_text(encoding="utf-8"))
    assert data["zones"][0]["accepted"] is None
    assert data["zones"][0]["candidates"]
    assert not (tmp_path / "calib.yaml").exists()    # nothing half-written
    # the printed JSON matches the file (agents may parse stdout)
    assert '"accepted": null' in out


def test_cli_hints_flattened_full_loop(tmp_path, capsys):
    """flattened sheet: render → (vision) → hints.yaml → auto-accept."""
    pdf = _write_sheet(tmp_path / "flat.pdf", with_text=False)
    hints = _write_hints(tmp_path / "hints.yaml", [
        {"kind": "dimension", "text": '45\'-0"',
         "near_pt": [RX0 + RW_PT / 2, RY1 + 9]},
    ])
    rc = cli.main(["calibrate", "--pdf", pdf, "--sheet", "1",
                   "--hints", hints, "--out", str(tmp_path / "calib.yaml")])
    assert rc == 0
    calib = load_calibration(tmp_path / "calib.yaml")
    assert calib.zones[0].ft_per_pt == pytest.approx(FT_PER_PT, rel=0.001)
    assert "hints" in calib.zones[0].method


# ---------------------------------------------------------------------------
# Pioneer Ave local regression (skipped when the plan set is absent)
# ---------------------------------------------------------------------------
def _pioneer_pdf() -> Path:
    env = os.environ.get("EST_PIONEER_PDF")
    if env:
        return Path(env)
    return (Path.home() / "PycharmProjects" / "Work"
            / "Pioneer-Ave-over-Lone-Tree-Creek-Bridge" / "Plans"
            / "Pioneer-Ave-Plans-12x18-signed.pdf")


pioneer = pytest.mark.skipif(
    not _pioneer_pdf().is_file(),
    reason="Pioneer plan set not present (local-only regression; "
           "set EST_PIONEER_PDF)")


@pioneer
def test_pioneer_signed_set_has_no_text_layer():
    """The signed 12x18 set is flattened: every sheet's lettering is vector
    outlines, so live-text dimension_strings cannot run on ANY sheet of this
    PDF — the v1 finding that drove the v2 rephase. Calibration evidence
    must come from geometry + vision hints."""
    sv = extract_sheet(str(_pioneer_pdf()), 12)
    assert sv.texts == []
    with pytest.raises(CalibrationError, match="no dimension-string evidence"):
        calibrate_zone_from_dimensions(sv, "plan", (0, 0, sv.width, sv.height))


@pioneer
def test_pioneer_sheet4_auto_calibrates_from_ticks_and_hints():
    """Exit criterion (a): a sheet of the flattened signed set calibrates
    automatically — no --ft-per-pt — catching the half-size-plot scale.

    Sheet 4 (PROJECT CONTROL) is the sheet that offers a geometric source:
    the "P" line carries twelve station ticks at exactly 90.00 pt. The
    committed hints fixture is fixture-captured vision (station labels
    "105"/"106"/"107" read off the render, plus the lettered scale note).
    Consensus: ticks (100 ft hypothesis) + station-label pairs = accepted
    1.1111 ft/pt (true 1"=80', HALF the lettered 1"=40' — the note is
    reported CONTRADICTED). The world anchor lands on the 105+00 tick."""
    sv = extract_sheet(str(_pioneer_pdf()), 3)
    hints = load_hints(FIXTURES / "pioneer-sheet4-hints.yaml", sv)
    calib = build_calibration(sv, 4, hints=hints)
    zone = calib.zones[0]
    true_ft_per_pt = 100.0 / 90.0                   # 1"=80' on the half plot
    assert zone.ft_per_pt == pytest.approx(true_ft_per_pt, rel=0.0005)
    assert zone.method == "consensus:hints+ticks"
    assert zone.world == "station_offset"
    assert zone.anchor is not None
    assert zone.anchor["world"] == [10500.0, 0.0]
    # the control script's independently-derived tick position (sheet-4
    # ground truth: station 105+00 at unrotated y 771.90)
    assert zone.anchor["page"][1] == pytest.approx(771.90, abs=0.5)
    assert any("CONTRADICTED" in w and "40" in w for w in calib.warnings)
    # the lettered scale would have been 51% wrong
    assert parse_scale('1"=40\'') == pytest.approx(0.5556, rel=0.001)


@pioneer
def test_pioneer_sheet13_exhausted_no_geometric_source():
    """Sheet 13 (GENERAL PLAN) is the documented no-geometric-source case:
    the PLAN "P" line carries a single station tick (106+00) — no evenly
    spaced family — and the PROFILE GRADE view is lettered NO SCALE with no
    ruled grid. All calibration value on this sheet is flattened lettering:
    ONE independent source type, so v2 correctly refuses to auto-accept
    (exit 2) even with dimension hints supplied — and the evidence report
    hands the agent the hint-confirmed value (~0.2222 ft/pt, HALF the
    lettered 1/8"=1'-0") for a deliberate manual override."""
    sv = extract_sheet(str(_pioneer_pdf()), 12)
    hints = load_hints(FIXTURES / "pioneer-sheet13-hints.yaml", sv)
    # plan bbox widened to include the right-side dimension chain the
    # fixture hints reference (the deck test's bbox predates the chain)
    zones = [("plan", (450.0, 540.0, 800.0, 1100.0)),
             ("elevation", PIONEER_SHEET13_ELEV_BBOX)]
    with pytest.raises(CalibrationInsufficient) as ei:
        build_calibration(sv, 13, zones=zones, hints=hints)
    true_ft_per_pt = 1.0 / 4.5
    for report in ei.value.reports:
        assert report["accepted"] is None
        hint_clusters = [
            c for c in report["clusters"]
            if any(m["source"] == "hints" and m.get("measured")
                   for m in c["members"])]
        assert any(abs(c["ft_per_pt"] - true_ft_per_pt) < 0.005 * true_ft_per_pt
                   for c in hint_clusters), report["zone"]
        assert all(not c["eligible"] for c in report["clusters"])


@pioneer
def test_pioneer_sheet13_deck_dims():
    """Sheet 13 GENERAL PLAN, PLAN view: re-measure the deck (lettered
    45'-0" BB to EB along the "P" line x 30'-0" out to out) from approximate
    hand-picked trace points, letting snap supply the precision — mirroring
    real agent usage.

    Calibration is MANUAL here (see the exhaustion test above): the view is
    lettered 1/8" = 1'-0" but the signed set is a half-size 12x18 plot, so
    the true scale is 1/16" = 1 ft (4.5 pt/ft) — the exact "title block lies
    on half-size plots" hazard the spec warns about. The 45'/30' assertions
    below are what validate the manual scale against the engineer's own
    linework.
    """
    pdf = str(_pioneer_pdf())
    sv = extract_sheet(pdf, 12)                     # sheet 13, 1-based
    assert sv.rotation == 90                        # 12x18 sheets carry /Rotate 90

    calib = build_calibration(
        sv, 13, zones=[("plan", PIONEER_SHEET13_PLAN_BBOX)], scale="1/16in=1ft")
    zone = calib.zones[0]
    assert zone.ft_per_pt == pytest.approx(1.0 / 4.5)
    segs = world_segments(sv, zone)
    assert len(segs) > 1000                         # real vector soup

    # Length along the bridge: probe points near mid-deck on the BB and EB
    # lines; snap projects them onto the extracted linework.
    snaps = snap_polyline(PIONEER_SHEET13_LENGTH_TRACE, segs, tol=0.3)
    assert all(s.snapped for s in snaps), [s.distance for s in snaps]
    length = abs(snaps[0].point[0] - snaps[1].point[0])
    # Width out to out: probe points on the two outer deck edges.
    snaps = snap_polyline(PIONEER_SHEET13_WIDTH_TRACE, segs, tol=0.3)
    assert all(s.snapped for s in snaps), [s.distance for s in snaps]
    width = abs(snaps[0].point[1] - snaps[1].point[1])

    # engineer's lettering: 45'-0" x 30'-0"
    assert length == pytest.approx(45.0, abs=0.2)
    assert width == pytest.approx(30.0, abs=0.2)


@pioneer
def test_pioneer_sheet20_rsp_footprint_and_fabric(tmp_path):
    """Exit criterion (b): sheet 20 (ROCK SLOPE PROTECTION DETAILS) yields
    the RSP stone footprint and the fabric extent with the slope-face
    correction the details imply.

    Calibration: like sheet 13, sheet 20 offers no geometric spacing family
    at the true scale (single 106+00 / 106+50 ticks), so hints-only evidence
    exits 2 with ~0.1481 ft/pt confirmed in the report — HALF the lettered
    3/16" = 1'-0" — and the manual override takes it deliberately.

    Measurement: both plan polygons (stone limits = outer thick line, fabric
    limit = inner line 2'-6" inside, per the "2'-6", Typ" band and the toe
    detail) are traced at their corner coordinates and snapped to the
    vectors. The engineer's own lettering verifies the result (QC table):
    bottom edge 12'-6", LIMITS 59'-10", toe width 2'-6". Fabric follows the
    2:1 slope face (sec(atan(1/2)) = 1.118) plus the toe wrap the ELEVATION
    detail shows (7'-0" back face + 2'-6" bottom; upslope edge key 2'-6" +
    2'-6")."""
    pdf = str(_pioneer_pdf())
    sv = extract_sheet(pdf, 19)                     # sheet 20, 1-based
    hints = load_hints(FIXTURES / "pioneer-sheet20-hints.yaml", sv)

    # (1) hints alone cannot auto-accept: one independent source type
    true_ft_per_pt = 2.0 / 13.5                     # 6.75 pt/ft
    with pytest.raises(CalibrationInsufficient) as ei:
        build_calibration(sv, 20, hints=hints)
    clusters = ei.value.reports[0]["clusters"]
    top_hint = max(
        (c for c in clusters
         if any(m["source"] == "hints" and m.get("measured")
                for m in c["members"])),
        key=lambda c: c["weight"])
    assert top_hint["ft_per_pt"] == pytest.approx(true_ft_per_pt, rel=0.005)
    assert not top_hint["eligible"]

    # (2) manual override with the hint-confirmed value
    calib = build_calibration(sv, 20, ft_per_pt=true_ft_per_pt)
    zone = calib.zones[0]

    def to_world(x, y):
        return zone.to_world(x, y)

    traces = {"layers": {
        "S-RSP": [
            {"closed": True, "points": [list(to_world(x, y))
                                        for x, y in PIONEER_SHEET20_LEFT_STONE]},
            {"closed": True, "points": [list(to_world(x, y))
                                        for x, y in PIONEER_SHEET20_RIGHT_STONE]},
        ],
        "S-RSP-FABRIC": [
            {"closed": True, "points": [list(to_world(x, y))
                                        for x, y in PIONEER_SHEET20_LEFT_FABRIC]},
            {"closed": True, "points": [list(to_world(x, y))
                                        for x, y in PIONEER_SHEET20_RIGHT_FABRIC]},
        ],
    }}
    layer_map = {
        "units": {"dxf_length_unit": "ft"},
        "layers": {"S-RSP": {"feature": "area"},
                   "S-RSP-FABRIC": {"feature": "area"}},
    }
    res = measure_traces(sv, calib, traces, layer_map, tmp_path / "rsp.dxf")
    assert res.unsnapped == 0
    assert res.max_snap_ft < 0.15

    areas = {}
    for e in res.sidecar:
        areas[f"{e['layer']}[{e['index']}]"] = _shoelace(
            [tuple(p) for p in e["points"]])
    stone = areas["S-RSP[0]"] + areas["S-RSP[1]"]
    fabric_plan = areas["S-RSP-FABRIC[0]"] + areas["S-RSP-FABRIC[1]"]
    # vector-measured plan footprints (ft2): the numbers behind the report
    assert stone == pytest.approx(1772.0, rel=0.005)        # 196.9 SY
    assert fabric_plan == pytest.approx(1236.7, rel=0.005)  # 137.4 SY

    # (3) QC cross-check against the engineer's lettering
    rows = cross_check(res.sidecar, collect_lettered(sv, calib, hints))
    ok = {(r.entity, r.lettered_ft) for r in rows if r.status == "OK"}
    assert ("S-RSP[0]", 12.5) in ok                 # bottom edge 12'-6"
    assert ("S-RSP[0]", 59.0 + 10 / 12.0) in ok     # LIMITS = 59'-10"
    assert ("S-RSP[1]", 2.5) in ok                  # toe key width 2'-6"
    assert any(r.entity == "S-RSP-FABRIC[1]" and r.status == "UNVERIFIED"
               for r in rows)                       # listed, not omitted

    # (4) fabric extent with the slope-face correction the details show
    slope = math.sqrt(5.0) / 2.0                    # sec(atan(1/2)), 2:1
    toe_run = (255.91 + 115.83 + 84.36 + 181.87 + 16.92 + 253.68) * true_ft_per_pt
    top_run = (149.04 + 67.47 + 108.60 + 268.80) * true_ft_per_pt
    fabric_total_sy = (fabric_plan * slope
                       + toe_run * (7.0 + 2.5)      # toe: 7' face + 2'-6" bottom
                       + top_run * (2.5 + 2.5)) / 9.0   # upslope edge key
    assert fabric_total_sy == pytest.approx(344.6, abs=2.0)
    # the exit-(b) comparison: geometry-aware fabric vs the flat-plan miss
    assert fabric_total_sy > 287.78 * 1.15          # well beyond the old model


# Sheet 20 RSP polygon corners in unrotated page points, read from the
# sheet's own vector segments (outer thick chain = stone limits, inner
# chain = fabric limit; roadway-side notch from the thin abutment edges)
# and verified against the lettering: top 6'-4"+15'-9" = 22.08 ft, bottom
# 12'-6", LIMITS 59'-10" / 58'-7", abutment face 30.0 ft.
PIONEER_SHEET20_LEFT_STONE = [
    (346.74, 925.02), (346.74, 775.98), (413.10, 763.80), (662.28, 849.54),
    (750.60, 924.48), (750.60, 1008.84), (643.68, 1008.84), (643.68, 873.84),
    (441.24, 873.84), (441.24, 925.02)]
PIONEER_SHEET20_LEFT_FABRIC = [
    (363.60, 925.02), (363.60, 790.02), (411.78, 781.20), (653.76, 864.48),
    (733.68, 932.28), (733.68, 1008.84), (643.68, 1008.84), (643.68, 873.84),
    (441.24, 873.84), (441.24, 925.02)]
PIONEER_SHEET20_RIGHT_STONE = [
    (355.20, 285.60), (355.20, 394.20), (624.00, 394.20), (733.68, 539.28),
    (750.60, 539.28), (750.60, 285.60), (643.68, 285.60), (643.68, 356.52),
    (441.24, 356.52), (441.24, 285.60)]
PIONEER_SHEET20_RIGHT_FABRIC = [
    (372.00, 285.60), (372.00, 377.34), (632.40, 377.28), (733.68, 511.26),
    (733.68, 285.60), (643.68, 285.60), (643.68, 356.52), (441.24, 356.52),
    (441.24, 285.60)]


# Established once by inspecting the rendered sheet (see the test docstrings):
# unrotated page points on the /Rotate 90 page. The traces are world feet
# (zone frame: +x along the bridge toward BB, +y across the deck),
# hand-picked off the render to about a tenth of a foot.
PIONEER_SHEET13_PLAN_BBOX = (450.0, 600.0, 800.0, 1100.0)
PIONEER_SHEET13_ELEV_BBOX = (150.0, 600.0, 430.0, 1120.0)
PIONEER_SHEET13_LENGTH_TRACE = [(83.7, 39.1), (38.8, 39.1)]   # BB line, EB line
PIONEER_SHEET13_WIDTH_TRACE = [(61.0, 54.1), (61.0, 24.0)]    # LT edge, RT edge


def test_extract_sheet_carries_ocg_layer_names(tmp_path):
    """Issue #200: a Civil-3D-plotted set keeps its CAD layers as PDF optional-
    content groups; pymupdf reports each drawing group's OCG under
    grp['layer']. extract_sheet dropped it, so contour/vector selection could
    only go by pen style. Segments now carry the OCG name (None when the path
    is on no OCG), so downstream can select by layer."""
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    minor = doc.add_ocg("Topo|CONT_MNR")
    major = doc.add_ocg("Topo|CONT_MJR")
    page.draw_line((10, 10), (150, 10), color=(0, 0, 0), width=0.75, oc=minor)
    page.draw_line((10, 30), (150, 30), color=(0, 0, 0), width=1.5, oc=major)
    page.draw_line((10, 50), (150, 50), color=(0, 0, 0), width=0.5)  # no OCG
    pdf = tmp_path / "ocg.pdf"
    doc.save(str(pdf))

    sv = extract_sheet(str(pdf), 0)
    by_layer: dict = {}
    for s in sv.segments:
        by_layer.setdefault(s.layer, 0)
        by_layer[s.layer] += 1
    assert by_layer.get("Topo|CONT_MNR"), "minor-contour OCG name was dropped"
    assert by_layer.get("Topo|CONT_MJR"), "major-contour OCG name was dropped"
    # an untagged path carries None, not "" — so `is None` cleanly means
    # "no layer" and layer selectors don't match the empty string
    assert None in by_layer, "an untagged path should carry layer=None"
