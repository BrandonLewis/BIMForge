"""est-bim contours / contour-surface / terrain-diff CLI wiring.

Drives arg parsing + the Task 1-3 library cores through tiny synthetic
fixtures — fake sheet vectors and calibrations (no PDFs), in-test JSON
manifests and npz grids (no network). scipy-dependent paths importorskip;
the matplotlib PNG path is exercised through its import seam.
"""
import json
import math
import sys
import types

import numpy as np
import pytest
import yaml

from bimforge.bim import cli


# ------------------------------------------------------------------ fixtures
class _Seg:
    """Duck-typed plansheet segment (x1/y1/x2/y2/width/color/length)."""

    def __init__(self, x1, y1, x2, y2, width=0.72, color=(0.5, 0.5, 0.5),
                 layer=None):
        self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2
        self.width = width
        self.color = color
        self.layer = layer
        self.length = math.dist((x1, y1), (x2, y2))


class _Zone:
    """Zone-like calibration: 2 ft per page point, identity-ish frame."""

    name = "full"
    ft_per_pt = 2.0
    method = "synthetic"

    @staticmethod
    def to_world(x, y):
        return (x * 2.0, -y * 2.0)


class _Calib:
    sheet = 7

    def zone(self, name=None):
        return _Zone()


def _fake_sheet():
    segs = [
        _Seg(0.0, 0.0, 50.0, 0.0),                     # contour pen, part 1
        _Seg(50.0, 0.0, 100.0, 0.0),                   # contour pen, part 2
        _Seg(0.0, 10.0, 100.0, 10.0, color=(1.0, 0.0, 0.0)),  # coloured noise
        _Seg(0.0, 20.0, 100.0, 20.0, color=(0.0, 0.0, 0.0)),  # other pen
    ]
    return types.SimpleNamespace(segments=segs, texts=[], rotation=0)


@pytest.fixture
def contours_env(monkeypatch):
    """Swap the PDF extractor + calibration loader for synthetic doubles.

    Fake modules go into sys.modules so the handler's direct submodule
    imports hit them — the real modules need pymupdf, which the pure CLI
    wiring under test does not.
    """
    sv = _fake_sheet()
    fake_vectors = types.ModuleType("bimforge.bim.plansheet.vectors")
    fake_vectors.extract_sheet = lambda pdf, page, min_path_pt=2.0: sv
    fake_calibrate = types.ModuleType("bimforge.bim.plansheet.calibrate")
    fake_calibrate.load_calibration = lambda path: _Calib()
    monkeypatch.setitem(
        sys.modules, "bimforge.bim.plansheet.vectors", fake_vectors)
    monkeypatch.setitem(
        sys.modules, "bimforge.bim.plansheet.calibrate", fake_calibrate)

    from bimforge.bim.plansheet import geopdf, triage
    state = {"viewports": [], "kind": "vector"}
    monkeypatch.setattr(geopdf, "read_viewports",
                        lambda pdf, page, bbox_mode="viewport":
                        list(state["viewports"]))
    monkeypatch.setattr(triage, "sheet_triage",
                        lambda pdf, page: triage.SheetTriage(
                            state["kind"], 0.97 if state["kind"] == "raster"
                            else 0.0, 1224.0, list(state["viewports"])))
    sv.geo_state = state
    return sv


def _viewport(transform=(2.0, 0.0, 1000.0, 0.0, -2.0, 5000.0),
              bbox=(-1.0, -1.0, 60.0, 5.0), unit="US survey foot", index=0):
    from bimforge.bim.plansheet.geopdf import Viewport
    return Viewport(index, bbox, 2226, unit, transform, [0.01], "viewport")


# ------------------------------------------------------------- est-bim contours
def test_contours_profile_prints_pen_table(contours_env, capsys):
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7", "--profile"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "grey" in out and "width" in out
    assert "0.5" in out                     # the contour pen shows up


def test_contours_profile_prints_triage_and_ocg_table(contours_env, capsys):
    contours_env.segments.append(_Seg(0.0, 40.0, 80.0, 40.0, layer="Topo|CONT_MNR"))
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7", "--profile"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "sheet 7: vector" in out
    assert "GeoPDF viewports: 0" in out
    assert "layers (OCGs): 1" in out and "Topo|CONT_MNR" in out
    assert "grey" in out and "width" in out            # pen table still there


def test_contours_profile_flags_a_bad_geopdf_scale(contours_env, capsys):
    contours_env.geo_state["viewports"] = [
        _viewport(transform=(2.0, 0.0, 1000.0, 0.0, -3.0, 5000.0))]
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7", "--profile"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "GeoPDF viewport 0: EPSG:2226" in out
    assert "--geopdf-bbox page" in out


def test_contours_profile_labels_a_metre_crs_viewport(contours_env, capsys):
    contours_env.geo_state["viewports"] = [_viewport(unit="metre")]
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7", "--profile"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "m/pt" in out
    assert "ft/pt" not in out
    assert "v1 needs a foot-unit CRS" in out


def test_contours_profile_says_raster(contours_env, capsys):
    contours_env.geo_state["kind"] = "raster"
    cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7", "--profile"])
    assert "raster" in capsys.readouterr().out


def test_contours_min_path_pt_defaults_to_zero(contours_env, capsys):
    # #398: a nonzero --min-path-pt drops the short connector paths that
    # contour runs are built from, fragmenting them — so contours must keep
    # every path by default (min_path_pt == 0), unlike calibrate/vectors.
    fake_vectors = sys.modules["bimforge.bim.plansheet.vectors"]
    orig = fake_vectors.extract_sheet
    calls = []

    def spy(pdf, page, min_path_pt=2.0):
        calls.append(min_path_pt)
        return orig(pdf, page, min_path_pt=min_path_pt)

    fake_vectors.extract_sheet = spy
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7", "--profile"])
    assert rc == 0
    assert calls == [0.0]
    assert "--min-path-pt" not in capsys.readouterr().err


def test_contours_nonzero_min_path_pt_warns(contours_env, capsys):
    # #398: raising --min-path-pt above 0 can silently fragment/lose line
    # work, so the CLI must warn on stderr when the operator sets it.
    fake_vectors = sys.modules["bimforge.bim.plansheet.vectors"]
    orig = fake_vectors.extract_sheet
    calls = []

    def spy(pdf, page, min_path_pt=2.0):
        calls.append(min_path_pt)
        return orig(pdf, page, min_path_pt=min_path_pt)

    fake_vectors.extract_sheet = spy
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7", "--profile",
                   "--min-path-pt", "2"])
    assert rc == 0
    assert calls == [2.0]
    err = capsys.readouterr().err
    assert "--min-path-pt 2" in err
    assert "fragment" in err or "connector" in err


def test_calibrate_and_vectors_still_default_min_path_pt_to_2(monkeypatch):
    # #398 narrowed the fragmenting default to `contours` only; calibrate
    # and vectors keep the hatch-noise filter on by default.
    import argparse

    class _Stop(Exception):
        pass

    def capture(self, *a, **kw):
        raise _Stop(self)

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture)
    with pytest.raises(_Stop) as stop:
        cli.main([])
    parser = stop.value.args[0]
    sub = next(a for a in parser._actions
               if isinstance(a, argparse._SubParsersAction))
    assert sub.choices["calibrate"].get_default("min_path_pt") == 2.0
    assert sub.choices["vectors"].get_default("min_path_pt") == 2.0
    assert sub.choices["contours"].get_default("min_path_pt") == 0.0


def test_contours_writes_dxf_and_manifest(contours_env, tmp_path, capsys):
    ezdxf = pytest.importorskip("ezdxf")
    dxf = tmp_path / "c.dxf"
    manifest = tmp_path / "c.json"
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7",
                   "--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                   "--out", str(dxf), "--json", str(manifest)])
    assert rc == 0
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert m["sheet"] == 7
    assert m["frame"] == "sheet_local_ft"
    rec = m["layers"]["EXIST"]
    assert rec["segments"] == 2             # only the grey 0.72 pen matched
    assert rec["polylines"] == 1            # collinear parts chained into one
    assert rec["lines"][0]["length_ft"] == pytest.approx(200.0)
    doc = ezdxf.readfile(str(dxf))
    polys = [e for e in doc.modelspace() if e.dxftype() == "LWPOLYLINE"]
    assert len(polys) == 1
    assert polys[0].dxf.layer == "C-EXIST"


def test_contours_ties_switch_frame_to_state_plane(contours_env, tmp_path):
    manifest = tmp_path / "c.json"
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7",
                   "--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                   "--tie", "0,0=0,0", "--tie", "100,0=0,200",
                   "--json", str(manifest)])
    assert rc == 0
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert m["frame"] == "state_plane_ft"
    rec = m["layers"]["EXIST"]
    assert rec["georef"]["ties"] == 2
    assert rec["lines"][0]["length_ft"] == pytest.approx(200.0)


def test_contours_requires_calib_and_layer(contours_env, capsys):
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7"])
    assert rc == 1
    assert "--calib" in capsys.readouterr().err


def test_contours_bad_layer_spec_is_exit_1(contours_env, capsys):
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7",
                   "--calib", "calib.yaml", "--layer", "EXIST=notagrey"])
    assert rc == 1
    assert "bad" in capsys.readouterr().err


def test_contours_calibration_sheet_mismatch(contours_env, capsys):
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "9",
                   "--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72"])
    assert rc == 1
    assert "sheet" in capsys.readouterr().err


def _contours(*extra):
    return cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7", *extra])


def test_contours_ocg_selector_writes_manifest_v2(contours_env, tmp_path):
    contours_env.segments += [_Seg(0.0, 40.0, 50.0, 40.0, layer="Topo|CONT_MNR"),
                              _Seg(50.0, 40.0, 100.0, 40.0, layer="Topo|CONT_MNR")]
    manifest = tmp_path / "c.json"
    rc = _contours("--calib", "calib.yaml", "--layer", "EG=ocg:Topo|CONT_*",
                   "--surface", "EG=existing", "--role", "EG=intermediate",
                   "--json", str(manifest))
    assert rc == 0
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert (m["manifest_version"], m["source_kind"]) == (2, "vector")
    assert m["georef"]["method"] == "calibration"
    assert len(m["georef"]["transform"]) == 6
    assert m["ft_per_pt"] == 2.0 and m["calibration_method"] == "synthetic"
    rec = m["layers"]["EG"]
    assert (rec["surface"], rec["role"]) == ("existing", "intermediate")
    assert rec["polylines"] == 1
    assert rec["lines"][0]["source"] == {"kind": "vector-ocg", "ocg": "Topo|CONT_MNR"}


def test_contours_tag_for_unknown_layer_is_exit_1(contours_env, capsys):
    rc = _contours("--calib", "calib.yaml", "--layer", "EG=0.5@0.72",
                   "--surface", "FG=proposed")
    assert rc == 1 and "no --layer" in capsys.readouterr().err


def test_contours_bad_surface_value_is_exit_1(contours_env, capsys):
    rc = _contours("--calib", "calib.yaml", "--layer", "EG=0.5@0.72",
                   "--surface", "EG=maybe")
    assert rc == 1 and "bad --surface" in capsys.readouterr().err


def test_contours_geopdf_georeferences_without_calib(contours_env, tmp_path):
    contours_env.geo_state["viewports"] = [_viewport()]
    manifest = tmp_path / "c.json"
    rc = _contours("--layer", "EXIST=0.5@0.72", "--json", str(manifest))
    assert rc == 0
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert m["frame"] == "state_plane_ft"
    assert (m["georef"]["method"], m["georef"]["crs_epsg"]) == ("geopdf", 2226)
    # no calibration was given: the v1 top-level key keeps its v1 meaning
    # (the CALIBRATION's method) rather than aliasing georef.method
    assert m["calibration_method"] == ""
    rec = m["layers"]["EXIST"]
    assert rec["outside_bounds"] == 1          # (50,0)-(100,0) leaves the box
    assert rec["lines"][0]["points"][0] == pytest.approx([1000.0, 5000.0])


def test_contours_geopdf_scale_gate_is_exit_2(contours_env, capsys):
    contours_env.geo_state["viewports"] = [
        _viewport(transform=(2.0, 0.0, 1000.0, 0.0, -3.0, 5000.0))]
    rc = _contours("--layer", "EXIST=0.5@0.72")
    err = capsys.readouterr().err
    assert rc == 2 and "--geopdf-bbox page" in err
    assert "--no-geopdf" in err


def test_contours_ties_win_over_geopdf(contours_env, tmp_path):
    contours_env.geo_state["viewports"] = [_viewport()]
    manifest = tmp_path / "c.json"
    rc = _contours("--layer", "EXIST=0.5@0.72", "--tie", "0,0=0,0",
                   "--tie", "100,0=0,200", "--json", str(manifest))
    assert rc == 0
    assert json.loads(manifest.read_text())["georef"]["method"] == "ties"


def test_contours_geopdf_wins_over_calibration_and_logs_the_frame(
        contours_env, tmp_path, capsys):
    # --calib given AND a good viewport present, no ties: GeoPDF wins, and
    # the operator is told the output frame changed (not the calibration's
    # sheet_local_ft) plus how to opt back out.
    contours_env.geo_state["viewports"] = [_viewport()]
    manifest = tmp_path / "c.json"
    rc = _contours("--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                   "--json", str(manifest))
    assert rc == 0
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert m["georef"]["method"] == "geopdf"
    err = capsys.readouterr().err
    assert "scale vs calibration" in err               # drift vs calibration
    assert "state_plane_ft" in err and "sheet_local_ft" in err
    assert "--no-geopdf" in err


def test_contours_no_geopdf_falls_back_to_calibration(contours_env, tmp_path):
    contours_env.geo_state["viewports"] = [_viewport()]
    manifest = tmp_path / "c.json"
    rc = _contours("--calib", "calib.yaml", "--no-geopdf",
                   "--layer", "EXIST=0.5@0.72", "--json", str(manifest))
    assert rc == 0
    assert json.loads(manifest.read_text())["georef"]["method"] == "calibration"


def test_contours_metre_geopdf_is_exit_1(contours_env, capsys):
    contours_env.geo_state["viewports"] = [_viewport(unit="metre")]
    rc = _contours("--layer", "EXIST=0.5@0.72")
    err = capsys.readouterr().err
    assert rc == 1 and "foot-unit" in err
    assert "--no-geopdf" in err


def test_contours_several_viewports_need_a_choice(contours_env, capsys):
    contours_env.geo_state["viewports"] = [_viewport(index=0), _viewport(index=1)]
    assert _contours("--layer", "EXIST=0.5@0.72") == 1
    err = capsys.readouterr().err
    assert "--viewport" in err
    assert "--no-geopdf" in err
    assert _contours("--layer", "EXIST=0.5@0.72", "--viewport", "1") == 0


def test_contours_explicit_viewport_with_no_geopdf_viewport_is_exit_1(
        contours_env, capsys):
    # --viewport 3 on a page with NO GeoPDF viewport at all must not be
    # silently ignored and fall through to the calibration.
    rc = _contours("--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                   "--viewport", "3")
    assert rc == 1
    err = capsys.readouterr().err
    assert "--viewport 3" in err
    assert "no GeoPDF viewport" in err


def test_contours_explicit_viewport_does_not_silently_fall_back_on_a_read_error(
        contours_env, capsys, monkeypatch):
    from bimforge.bim.plansheet import geopdf

    def boom(pdf, page, bbox_mode="viewport"):
        raise ValueError("GeoPDF /VP is not an array or dictionary")

    monkeypatch.setattr(geopdf, "read_viewports", boom)
    rc = _contours("--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                   "--viewport", "0")
    assert rc == 1
    err = capsys.readouterr().err
    assert "--viewport 0" in err
    assert "GeoPDF viewport unreadable" in err
    assert "not an array or dictionary" in err


def test_contours_needs_a_georeference(contours_env, capsys):
    rc = _contours("--layer", "EXIST=0.5@0.72")
    assert rc == 1 and "no georeference" in capsys.readouterr().err


def test_contours_max_residual_gate_is_exit_2(contours_env, capsys):
    rc = _contours("--layer", "EXIST=0.5@0.72", "--tie-model", "affine",
                   "--tie", "0,0=0,0", "--tie", "100,0=0,200",
                   "--tie", "0,100=-200,0", "--tie", "100,100=-150,210",
                   "--max-residual-ft", "0.5")
    assert rc == 2 and "--max-residual-ft" in capsys.readouterr().err


def test_contours_max_residual_gate_also_applies_to_calibration(
        contours_env, capsys, monkeypatch):
    # a calibration-backed run carries the zone's own residual_ft, and
    # --max-residual-ft must gate it too (previously georef_from_zone
    # dropped it, so this gate was a no-op for --calib runs).
    class _ZoneWithResidual(_Zone):
        residual_ft = 5.0

    class _CalibWithResidual:
        sheet = 7

        def zone(self, name=None):
            return _ZoneWithResidual()

    monkeypatch.setattr(sys.modules["bimforge.bim.plansheet.calibrate"],
                        "load_calibration", lambda path: _CalibWithResidual())
    rc = _contours("--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                   "--max-residual-ft", "1.0")
    assert rc == 2
    assert "--max-residual-ft" in capsys.readouterr().err


def test_contour_surface_accepts_a_v2_manifest_from_contours_unchanged(
        contours_env, tmp_path):
    """A v2 manifest written by `est-bim contours` feeds `contour-surface`
    with no adaptor — pins the "contour-surface reads v2 unchanged" exit
    criterion."""
    pytest.importorskip("scipy")

    def pen_line(y, n=21, dx=10.0):
        return [_Seg(i * dx, y, (i + 1) * dx, y) for i in range(n - 1)]

    # three parallel contour-pen lines at page y = 0, -10, -20; the fixture's
    # _Zone.to_world(x, y) = (2x, -2y) puts them at world y = 0, 20, 40 ft
    contours_env.segments = (pen_line(0.0) + pen_line(-10.0)
                             + pen_line(-20.0))
    manifest = tmp_path / "c.json"
    rc = _contours("--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                   "--json", str(manifest))
    assert rc == 0
    m = json.loads(manifest.read_text(encoding="utf-8"))
    assert m["manifest_version"] == 2
    assert len(m["layers"]["EXIST"]["lines"]) == 3

    anchors = tmp_path / "anchors.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88", "contours": [
        {"elev": 100.0, "xy": [100.0, 0.0]},
        {"elev": 110.0, "xy": [100.0, 20.0]},
        {"elev": 120.0, "xy": [100.0, 40.0]}]})
    out = tmp_path / "tin.npz"
    rc2 = cli.main(["contour-surface", "--contours", str(manifest),
                    "--anchors", str(anchors), "--out", str(out)])
    assert rc2 == 0
    d = np.load(out, allow_pickle=False)
    info = json.loads(str(d["info"]))
    assert info["tiers"] == {"lettered": 3, "inferred": 0}


# ----------------------------------------------------- est-bim contour-surface
def _line(y, n=21, dx=10.0):
    return [[i * dx, y] for i in range(n)]


def _write_manifest(path, ys=(0.0, 20.0, 40.0)):
    m = {"sheet": 1,
         "layers": {"EXIST": {"lines": [{"points": _line(y)} for y in ys]}}}
    path.write_text(json.dumps(m), encoding="utf-8")


def _write_yaml(path, obj):
    path.write_text(yaml.safe_dump(obj), encoding="utf-8")


def test_contour_surface_lettered_tin_and_score(tmp_path, capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_manifest(man)
    anchors = tmp_path / "anchors.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88", "contours": [
        {"elev": 100.0, "xy": [100.0, 0.0]},
        {"elev": 110.0, "xy": [100.0, 20.0]},
        {"elev": 120.0, "xy": [100.0, 40.0]}]})
    spots = tmp_path / "spots.yaml"
    _write_yaml(spots, {"spots": [{"elev": 105.0, "xy": [55.0, 10.0]}]})
    out = tmp_path / "tin.npz"
    report = tmp_path / "surface.md"
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors), "--spots", str(spots),
                   "--out", str(out), "--report", str(report)])
    assert rc == 0
    d = np.load(out, allow_pickle=False)     # npz holds no pickle, ever
    assert d["points"].shape[1] == 3
    assert len(d["simplices"]) > 0
    info = json.loads(str(d["info"]))
    assert info["tiers"] == {"lettered": 3, "inferred": 0}
    assert info["score"]["rmse"] == pytest.approx(0.0, abs=1e-6)
    assert info["provenance"]["Source"] == "plan-sheet contours"
    assert info["provenance"]["SurveyGrade"] is False
    text = report.read_text(encoding="utf-8")
    assert "Scorecard" in text and "held-out" in text
    assert "RMSE" in capsys.readouterr().err


def test_contour_surface_spot_pins_pin_contours_and_score_leave_one_out(tmp_path):
    pytest.importorskip("scipy")
    # two lettered 20s with a rise or a dip between them — the labels cannot
    # say which; one spot can
    man = tmp_path / "m.json"
    _write_manifest(man, ys=(0.0, 20.0, 40.0, 60.0, 80.0, 100.0))
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88", "interval_ft": 1.0,
                          "contours": [{"elev": 20.0, "xy": [100.0, 0.0]},
                                       {"elev": 20.0, "xy": [100.0, 100.0]}],
                          "spots": [{"elev": 22.4, "xy": [100.0, 52.0]}]})
    base = ["contour-surface", "--contours", str(man), "--anchors", str(anchors)]
    out0, out1, report = tmp_path / "a.npz", tmp_path / "b.npz", tmp_path / "r.md"
    assert cli.main(base + ["--out", str(out0)]) == 0
    assert cli.main(base + ["--spot-pins", "--propagate", "--out", str(out1),
                            "--report", str(report)]) == 0
    i0 = json.loads(str(np.load(out0, allow_pickle=False)["info"]))
    i1 = json.loads(str(np.load(out1, allow_pickle=False)["info"]))
    assert i0["reconcile"]["pinned"] == 0 and i1["reconcile"]["pinned"] == 2
    assert i0["spot_scoring"] == "held-out"
    assert i1["spot_scoring"] == "leave-one-out" and i1["score"]["n"] == 1
    assert "## Scorecard — leave-one-out spot elevations" in report.read_text(
        encoding="utf-8")
    # without --propagate the pins cannot change the surface: held out
    out2 = tmp_path / "c.npz"
    assert cli.main(base + ["--spot-pins", "--out", str(out2)]) == 0
    i2 = json.loads(str(np.load(out2, allow_pickle=False)["info"]))
    assert i2["reconcile"]["pinned"] == 2 and i2["spot_scoring"] == "held-out"


def test_contour_surface_spot_pins_pin_lines_they_never_assign(tmp_path):
    pytest.importorskip("scipy")
    # the labels (20 ... 20) leave the lines between them open; a 22.4 spot
    # pins two of them, but no pair of lettered lines brackets a value, so
    # --propagate assigns none: spot pins never make a line assignable
    # (final review I-3). A change that let them would fail here.
    man = tmp_path / "m.json"
    _write_manifest(man, ys=(0.0, 20.0, 40.0, 60.0, 80.0, 100.0))
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88", "interval_ft": 1.0,
                          "contours": [{"elev": 20.0, "xy": [100.0, 0.0]},
                                       {"elev": 20.0, "xy": [100.0, 100.0]}],
                          "spots": [{"elev": 22.4, "xy": [100.0, 52.0]}]})
    out = tmp_path / "t.npz"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--propagate", "--spot-pins",
                     "--out", str(out)]) == 0
    info = json.loads(str(np.load(out, allow_pickle=False)["info"]))
    assert info["reconcile"]["pinned"] == 2
    assert info["tiers"]["inferred"] == 0


@pytest.mark.parametrize("line", [[[0.0, 0.0], [100.0, 0.0]],          # 2 points
                                  [[x, 0.0] for x in range(0, 101, 10)]])  # collinear
def test_leave_one_out_leaves_a_spot_unscored_without_a_surface(line):
    pytest.importorskip("scipy")
    from bimforge.terrain.reconcile import neighbour_graph
    polys = [(np.array(line, dtype=float), "sheet 1", "EG")]
    got = cli._leave_one_out(polys, neighbour_graph(polys), {0: 10.0}, 1.0,
                             [{"elev": 10.0, "xy": (50.0, 1.0)}], roles={},
                             index_interval=None, snap_tol=0.35, thin=8.0,
                             max_edge=250.0)
    assert got["rows"] == [{"elev": 10.0, "tin": None, "err": None}]
    assert got["stats"]["n"] == 0


def test_contour_surface_spot_pins_never_add_an_assigned_contour(tmp_path):
    pytest.importorskip("scipy")
    from bimforge.terrain.contours import _TIERS
    # six parallel lines 20 ft apart lettered 20 and 25 at the ends: the
    # labels alone assign lines 1-4 (21-24). Spot pins only add limits, so
    # the lines assigned with them are a subset of those without (final
    # review I-3): a spot that agrees changes nothing; one that contradicts
    # line 3 (23) withdraws the lines it conflicts with
    ys = (0.0, 20.0, 40.0, 60.0, 80.0, 100.0)
    man = tmp_path / "m.json"
    _write_manifest(man, ys=ys)

    def assigned(spots, *flags):
        anchors, out = tmp_path / "a.yaml", tmp_path / "t.npz"
        _write_yaml(anchors, {"vertical_datum": "NAVD88", "interval_ft": 1.0,
                              "contours": [{"elev": 20.0, "xy": [100.0, 0.0]},
                                           {"elev": 25.0, "xy": [100.0, 100.0]}],
                              "spots": spots})
        assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                         str(anchors), "--propagate", *flags,
                         "--out", str(out)]) == 0
        d = np.load(out, allow_pickle=False)
        offs, pts = d["line_offsets"], d["line_points"]
        return {ys.index(float(pts[offs[k], 1])) for k in range(len(offs) - 1)
                if d["line_tier"][k] == _TIERS.index("inferred")}

    agrees = [{"elev": 23.2, "xy": [100.0, 61.0]}]
    contradicts = [{"elev": 21.0, "xy": [100.0, 61.0]}]
    for spots in (agrees, contradicts):
        without, with_pins = assigned(spots), assigned(spots, "--spot-pins")
        assert without == {1, 2, 3, 4}
        assert with_pins <= without
    assert assigned(agrees, "--spot-pins") == {1, 2, 3, 4}
    assert assigned(contradicts, "--spot-pins") == {1, 2}


def test_contour_surface_spot_pins_need_an_interval(tmp_path, capsys):
    man = tmp_path / "m.json"
    _write_manifest(man)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88", "contours": [
        {"elev": 100.0, "xy": [100.0, 0.0]}]})
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--spot-pins",
                     "--out", str(tmp_path / "t.npz")]) == 1
    assert "--spot-pins needs a contour interval" in capsys.readouterr().err


def test_contour_surface_propagate_marks_inferred_tier(tmp_path):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_manifest(man)
    anchors = tmp_path / "anchors.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88", "contours": [
        {"elev": 100.0, "xy": [100.0, 0.0]},
        {"elev": 120.0, "xy": [100.0, 40.0]}]})
    out = tmp_path / "tin.npz"
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors), "--propagate",
                   "--interval", "10", "--out", str(out)])
    assert rc == 0
    d = np.load(out, allow_pickle=False)
    info = json.loads(str(d["info"]))
    assert info["tiers"] == {"lettered": 2, "inferred": 1}
    # the middle contour landed at 110 ft
    assert 110.0 in set(np.asarray(d["points"])[:, 2].tolist())


def test_contour_surface_propagate_honours_layer_roles(tmp_path, capsys):
    pytest.importorskip("scipy")
    # 1 ft contours at y = 0..50, lettered 20 and 25. The y=30 line (the
    # hop count says 23) sits on the index-role layer, so it is refused;
    # the intermediate-role lines are inferred.
    man = tmp_path / "m.json"
    man.write_text(json.dumps({"sheet": 1, "layers": {
        "MJR": {"role": "index",
                "lines": [{"points": _line(y)} for y in (0.0, 30.0, 50.0)]},
        "MNR": {"role": "intermediate",
                "lines": [{"points": _line(y)} for y in (10.0, 20.0, 40.0)]}}}),
        encoding="utf-8")
    anchors = tmp_path / "anchors.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88", "interval_ft": 1.0,
                          "index_interval_ft": 5.0, "contours": [
                              {"elev": 20.0, "xy": [100.0, 0.0]},
                              {"elev": 25.0, "xy": [100.0, 50.0]}]})
    out = tmp_path / "tin.npz"
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors), "--propagate", "--out", str(out)])
    assert rc == 0
    info = json.loads(str(np.load(out, allow_pickle=False)["info"]))
    assert info["tiers"] == {"lettered": 2, "inferred": 3}
    assert "conflict" in capsys.readouterr().err


def test_contour_surface_max_rmse_gate_is_exit_2(tmp_path, capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_manifest(man)
    anchors = tmp_path / "anchors.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88", "contours": [
        {"elev": 100.0, "xy": [100.0, 0.0]},
        {"elev": 110.0, "xy": [100.0, 20.0]},
        {"elev": 120.0, "xy": [100.0, 40.0]}]})
    spots = tmp_path / "spots.yaml"
    _write_yaml(spots, {"spots": [{"elev": 200.0, "xy": [55.0, 10.0]}]})
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors), "--spots", str(spots),
                   "--max-rmse", "1.0", "--out", str(tmp_path / "t.npz")])
    assert rc == 2
    assert "RMSE" in capsys.readouterr().err


def test_contour_surface_unscored_fails_the_rmse_gate(tmp_path, capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_manifest(man)
    anchors = tmp_path / "anchors.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88", "contours": [
        {"elev": 100.0, "xy": [100.0, 0.0]},
        {"elev": 110.0, "xy": [100.0, 20.0]},
        {"elev": 120.0, "xy": [100.0, 40.0]}]})
    spots = tmp_path / "spots.yaml"
    _write_yaml(spots, {"spots": [{"elev": 100.0, "xy": [9000.0, 9000.0]}]})
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors), "--spots", str(spots),
                   "--max-rmse", "1.0", "--out", str(tmp_path / "t.npz")])
    assert rc == 2
    assert "unscored" in capsys.readouterr().err


def test_contour_surface_page_anchor_without_ties_is_exit_1(tmp_path, capsys):
    man = tmp_path / "m.json"
    _write_manifest(man)
    anchors = tmp_path / "anchors.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88",
                          "contours": [{"elev": 100.0, "page": [10.0, 10.0]}]})
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors),
                   "--out", str(tmp_path / "t.npz")])
    assert rc == 1
    assert "--tie" in capsys.readouterr().err


def test_contour_surface_scipy_runtimeerror_is_actionable(
        tmp_path, monkeypatch, capsys):
    man = tmp_path / "m.json"
    _write_manifest(man)
    anchors = tmp_path / "anchors.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88", "contours": [
        {"elev": 100.0, "xy": [100.0, 0.0]},
        {"elev": 110.0, "xy": [100.0, 20.0]},
        {"elev": 120.0, "xy": [100.0, 40.0]}]})

    def boom(points, max_edge):
        raise RuntimeError(
            "scipy is required for the contour-TIN terrain source — "
            'pip install "bimforge[terrain]"')

    monkeypatch.setattr("bimforge.terrain.contours.build_tin", boom)
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors),
                   "--out", str(tmp_path / "t.npz")])
    assert rc == 1
    assert "bimforge[terrain]" in capsys.readouterr().err


def _write_v2_manifest(path, ys=(0.0, 20.0, 40.0), *, surface=None,
                       extra_layers=None):
    """A v2 manifest whose georef maps page (x, y) -> world (2x, -2y)."""
    layer = {"lines": [{"points": _line(y)} for y in ys]}
    if surface:
        layer["surface"] = surface
    layers = {"EXIST": layer, **(extra_layers or {})}
    m = {"manifest_version": 2, "sheet": 1, "source_kind": "vector",
         "georef": {"method": "calibration", "model": "similarity",
                    "frame": "sheet_local_ft", "ft_per_pt": 2.0,
                    "transform": [2.0, 0.0, 0.0, 0.0, -2.0, 0.0],
                    "residuals_ft": []},
         "layers": layers}
    path.write_text(json.dumps(m), encoding="utf-8")


# world (100, 0 / 20 / 40) ft  <->  page (50, 0 / -10 / -20) pt
_PAGE_ANCHORS = [{"elev": 100.0, "page": [50.0, 0.0]},
                 {"elev": 110.0, "page": [50.0, -10.0]},
                 {"elev": 120.0, "page": [50.0, -20.0]}]


def test_contour_surface_places_page_anchors_through_the_v2_georef(
        tmp_path, capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"sheet": 1, "vertical_datum": "NGVD29",
                          "contours": _PAGE_ANCHORS})
    out = tmp_path / "tin.npz"
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors), "--out", str(out)])
    assert rc == 0
    info = json.loads(str(np.load(out, allow_pickle=False)["info"]))
    assert info["tiers"] == {"lettered": 3, "inferred": 0}
    assert info["vertical_datum"] == "NGVD29" and info["surface"] == "existing"
    assert "placed by the manifest sheet 1 georef" in capsys.readouterr().err


def test_contour_surface_ties_override_the_manifest_georef(tmp_path, capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29",
                          "contours": _PAGE_ANCHORS})
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors), "--tie", "0,0=0,0",
                   "--tie", "50,0=0,100", "--out", str(tmp_path / "t.npz")])
    assert rc == 0
    assert "--tie" in capsys.readouterr().err


def test_contour_surface_requires_vertical_datum(tmp_path, capsys):
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"contours": _PAGE_ANCHORS})
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors), "--out", str(tmp_path / "t.npz")])
    assert rc == 1 and "vertical_datum" in capsys.readouterr().err


def test_contour_surface_skips_unread_anchor_records(tmp_path, capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors = tmp_path / "a.yaml"
    recs = [dict(r) for r in _PAGE_ANCHORS]
    recs[1]["elev"] = None
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "contours": recs})
    out = tmp_path / "t.npz"
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors), "--out", str(out)])
    assert rc == 0
    info = json.loads(str(np.load(out, allow_pickle=False)["info"]))
    assert info["tiers"]["lettered"] == 2 and info["unread_anchors"] == 1
    assert "unread" in capsys.readouterr().err


def test_contour_surface_proposed_surface_writes_fg_layers(tmp_path):
    pytest.importorskip("scipy")
    ezdxf = pytest.importorskip("ezdxf")
    man = tmp_path / "m.json"
    _write_v2_manifest(man, surface="proposed")
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29",
                          "contours": _PAGE_ANCHORS})
    out, dxf = tmp_path / "t.npz", tmp_path / "s.dxf"
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors), "--out", str(out),
                   "--dxf", str(dxf)])
    assert rc == 0
    assert json.loads(str(np.load(out, allow_pickle=False)["info"]))[
        "surface"] == "proposed"
    names = {layer.dxf.name for layer in ezdxf.readfile(str(dxf)).layers}
    assert "FG-CONTOUR-LETTERED" in names and "EG-CONTOUR-LETTERED" not in names


def test_contour_surface_mixed_surfaces_is_exit_1(tmp_path, capsys):
    man = tmp_path / "m.json"
    _write_v2_manifest(man, surface="existing", extra_layers={
        "PROP": {"surface": "proposed", "lines": [{"points": _line(60.0)}]}})
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29",
                          "contours": _PAGE_ANCHORS})
    rc = cli.main(["contour-surface", "--contours", str(man),
                   "--anchors", str(anchors), "--out", str(tmp_path / "t.npz")])
    assert rc == 1 and "mix" in capsys.readouterr().err


def test_contour_surface_skips_the_review_layer_unless_included(
        tmp_path, capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man, extra_layers={
        "REVIEW": {"lines": [{"points": _line(60.0)}]}})
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29",
                          "contours": _PAGE_ANCHORS})
    args = ["contour-surface", "--contours", str(man), "--anchors",
            str(anchors), "--out", str(tmp_path / "t.npz")]
    assert cli.main(args) == 0
    assert "skipped 1 REVIEW line" in capsys.readouterr().err
    assert cli.main(args + ["--include-review"]) == 0
    assert "REVIEW" not in capsys.readouterr().err


_FIVE = (0.0, 20.0, 40.0, 60.0, 80.0)


def _five_page_anchors(values):
    return [{"elev": v, "page": [50.0, -y / 2.0]} for v, y in zip(values, _FIVE)]


def test_contour_surface_reports_conflicting_labels_and_keeps_them(tmp_path, capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man, ys=_FIVE)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "interval_ft": 10.0,
                          "contours": _five_page_anchors(
                              [100.0, 110.0, 150.0, 130.0, 140.0])})
    out, report = tmp_path / "t.npz", tmp_path / "r.md"
    rc = cli.main(["contour-surface", "--contours", str(man), "--anchors",
                   str(anchors), "--out", str(out), "--report", str(report)])
    assert rc == 0
    info = json.loads(str(np.load(out, allow_pickle=False)["info"]))
    assert info["tiers"]["lettered"] == 5      # kept: which one is wrong is a person's call
    assert info["label_checks"] == {"index_multiple": 0, "label_conflicts": 4}
    assert info["findings"] == 1
    assert "findings: 1 (1 conflict)" in capsys.readouterr().err
    text = report.read_text(encoding="utf-8")
    assert "## Findings" in text and "| F01 | conflict |" in text
    assert "without the 150 label on line 2" in text


_SEVEN = tuple(20.0 * k for k in range(7))
# lines 1 and 5 unlabelled; line 3 = 170 conflicts with its neighbours
_UNFAITHFUL = {0: 200.0, 2: 120.0, 3: 170.0, 4: 140.0, 6: 200.0}


def test_contour_surface_findings_name_the_anchor_ids(tmp_path, capsys):
    pytest.importorskip("scipy")
    from bimforge.terrain.contours import load_tin_npz
    man = tmp_path / "m.json"
    _write_v2_manifest(man, ys=_SEVEN)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "interval_ft": 10.0,
                          "contours": [
                              {"id": f"L{k:03d}", "elev": v,
                               "page": [50.0, -_SEVEN[k] / 2.0]}
                              for k, v in _UNFAITHFUL.items()]})
    out, report = tmp_path / "t.npz", tmp_path / "r.md"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(out),
                     "--report", str(report)]) == 0
    t = load_tin_npz(out)
    assert t.info["tiers"]["lettered"] == 5
    assert 170.0 in [ln["elev"] for ln in t.lines]       # kept, in the TIN
    assert t.info["label_checks"]["label_conflicts"] >= 1
    text = report.read_text(encoding="utf-8")
    assert "170 (L003)" in text                          # the finding names the anchor
    assert "| L003 | 170 | 3 | 0.00 |" in text           # label matching unchanged


def test_contour_surface_says_when_the_label_checks_are_off(tmp_path, capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29",
                          "contours": _PAGE_ANCHORS})
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(tmp_path / "t.npz")]) == 0
    err = capsys.readouterr().err
    assert ("index check off (no role: index layer / no index_interval_ft)"
            in err)
    assert "reconciliation off (no interval_ft)" in err
    assert "0 off the index interval" not in err


def test_contour_surface_strict_exits_2_on_findings(tmp_path, capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man, ys=_FIVE)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "interval_ft": 10.0,
                          "contours": _five_page_anchors(
                              [100.0, 110.0, 150.0, 130.0, 140.0])})
    out = tmp_path / "t.npz"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(out), "--strict"]) == 2
    assert out.exists()                                  # every output written first
    assert "--strict: 1 finding(s)" in capsys.readouterr().err


def test_contour_surface_strict_points_to_the_report_or_asks_for_one(tmp_path,
                                                                     capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man, ys=_FIVE)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "interval_ft": 10.0,
                          "contours": _five_page_anchors(
                              [100.0, 110.0, 150.0, 130.0, 140.0])})
    base = ["contour-surface", "--contours", str(man), "--anchors",
            str(anchors), "--out", str(tmp_path / "t.npz"), "--strict"]
    assert cli.main(base) == 2
    assert "rerun with --report for the details" in capsys.readouterr().err
    report = tmp_path / "r.md"
    assert cli.main(base + ["--report", str(report)]) == 2
    assert f"see {report}" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["-1", "0", "nan", "inf"])
def test_contour_surface_rejects_a_bad_interval(tmp_path, capsys, bad):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29",
                          "contours": _PAGE_ANCHORS})
    out = tmp_path / "t.npz"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--interval", bad, "--out", str(out)]) == 1
    assert "error: --interval must be a finite number > 0" in capsys.readouterr().err
    assert not out.exists()


def test_contour_surface_strict_passes_a_clean_sheet(tmp_path):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "interval_ft": 10.0,
                          "contours": _PAGE_ANCHORS})
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(tmp_path / "t.npz"),
                     "--strict"]) == 0


def test_contour_surface_records_the_reconciliation_in_the_npz(tmp_path):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "interval_ft": 10.0,
                          "contours": _PAGE_ANCHORS})
    out = tmp_path / "t.npz"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(out),
                     "--contact-ft", "0.25"]) == 0
    info = json.loads(str(np.load(out, allow_pickle=False)["info"]))
    assert info["reconcile"]["label_conflicts"] == 0 and info["findings"] == 0
    assert info["spot_scoring"] == "held-out"
    assert info["graph"]["contact_ft"] == 0.25
    assert info["graph"]["refused_merges"] == 0


def test_contour_surface_logs_refused_merge_joins(tmp_path, capsys):
    pytest.importorskip("scipy")
    # the y=20 contour is in two pieces with a line on another layer across
    # the gap: the merge must not draw the contour across it
    man = tmp_path / "m.json"
    man.write_text(json.dumps({"sheet": 1, "layers": {
        "EXIST": {"lines": [{"points": _line(0.0)}, {"points": _line(40.0)},
                            {"points": [[0.0, 20.0], [90.0, 20.0]]},
                            {"points": [[98.0, 20.0], [200.0, 20.0]]}]},
        "X": {"lines": [{"points": [[94.0, 15.0], [94.0, 25.0]]}]}}}),
        encoding="utf-8")
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NAVD88", "contours": [
        {"elev": 100.0, "xy": [100.0, 0.0]}, {"elev": 120.0, "xy": [100.0, 40.0]}]})
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--merge-gap", "10",
                     "--out", str(tmp_path / "t.npz")]) == 0
    assert "1 join(s) refused" in capsys.readouterr().err


def test_contour_surface_reads_a_string_sheet_as_a_page_number(tmp_path, capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors = tmp_path / "a.yaml"
    anchors.write_text('sheet: "1"\nvertical_datum: NGVD29\n'
                       + yaml.safe_dump({"contours": _PAGE_ANCHORS}),
                       encoding="utf-8")
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(tmp_path / "t.npz")]) == 0
    assert "placed by the manifest sheet 1 georef" in capsys.readouterr().err


def test_contour_surface_names_the_sheet_no_manifest_is_for(tmp_path, capsys):
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"sheet": 2, "vertical_datum": "NGVD29",
                          "contours": _PAGE_ANCHORS})
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(tmp_path / "t.npz")]) == 1
    assert "no v2 manifest is for sheet 2" in capsys.readouterr().err


@pytest.mark.parametrize("text, match", [
    ("- 1\n- 2\n", "expected a mapping"),
    ("5\n", "expected a mapping"),
    ("vertical_datum: X\ncontours: [5]\n", r"contours\[0\]"),
    ("vertical_datum: X\ncontours: [{elev: 1, page: [1, 2, 3]}]\n",
     "page must be 2 numbers"),
    ("vertical_datum: X\ncontours: [{elev: [1], xy: [0, 0]}]\n",
     "elev must be a number"),
    ("vertical_datum: X\ninterval_ft: -1\n", "interval_ft: must be > 0"),
    ("vertical_datum: X\ninterval_ft: 0\n", "interval_ft: must be > 0"),
    ("vertical_datum: X\nindex_interval_ft: 0\n",
     "index_interval_ft: must be > 0"),
    ("vertical_datum: X\ncontours: [{elev: 1\n", "not valid YAML"),
])
def test_contour_surface_bad_anchors_are_exit_1_not_a_traceback(
        tmp_path, capsys, text, match):
    import re
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors = tmp_path / "a.yaml"
    anchors.write_text(text, encoding="utf-8")
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(tmp_path / "t.npz")]) == 1
    err = capsys.readouterr().err
    assert err.startswith("error: ") and re.search(match, err)


def test_contour_surface_a_scalar_spots_file_is_exit_1(tmp_path, capsys):
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    anchors, spots = tmp_path / "a.yaml", tmp_path / "s.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29",
                          "contours": _PAGE_ANCHORS})
    spots.write_text("5\n", encoding="utf-8")
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--spots", str(spots),
                     "--out", str(tmp_path / "t.npz")]) == 1
    assert "--spots file" in capsys.readouterr().err


def test_contour_surface_drops_an_index_label_off_the_index_interval(tmp_path):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man, ys=_FIVE)
    m = json.loads(man.read_text())
    m["layers"]["EXIST"]["role"] = "index"
    man.write_text(json.dumps(m))
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "index_interval_ft": 50.0,
                          "contours": _five_page_anchors(
                              [100.0, 150.0, 200.0, 250.0, 305.0])})
    out = tmp_path / "t.npz"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(out)]) == 0
    info = json.loads(str(np.load(out, allow_pickle=False)["info"]))
    assert info["label_checks"]["index_multiple"] == 1
    assert info["tiers"]["lettered"] == 4


def test_contour_surface_writes_a_v2_tin_with_its_contours(tmp_path, capsys):
    pytest.importorskip("scipy")
    from bimforge.terrain.contours import load_tin_npz
    man = tmp_path / "m.json"
    _write_v2_manifest(man)
    m = json.loads(man.read_text())
    m["georef"]["crs_epsg"] = 2226
    man.write_text(json.dumps(m))
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29",
                          "contours": _PAGE_ANCHORS})
    out, report = tmp_path / "t.npz", tmp_path / "r.md"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(out),
                     "--report", str(report)]) == 0
    t = load_tin_npz(out)
    assert t.info["npz_version"] == 2 and t.info["crs_epsg"] == 2226
    assert len(t.lines) == 3 and {ln["tier"] for ln in t.lines} == {"lettered"}
    assert sorted(ln["elev"] for ln in t.lines) == [100.0, 110.0, 120.0]
    assert len(t.point_line) == len(t.points)
    assert 0.0 <= t.info["flat_triangle_share"] <= 1.0
    assert "flat-triangle share" in report.read_text(encoding="utf-8")
    assert "flat-triangle share" in capsys.readouterr().err


def test_contour_surface_refuses_manifests_in_different_crss(tmp_path, capsys):
    pytest.importorskip("scipy")
    mans = []
    for sheet, crs in ((1, 2226), (2, 2227)):
        man = tmp_path / f"m{crs}.json"
        _write_v2_manifest(man)
        m = json.loads(man.read_text())
        m["sheet"], m["georef"]["crs_epsg"] = sheet, crs
        man.write_text(json.dumps(m))
        mans.append(str(man))
    anchors = tmp_path / "a.yaml"       # sheet 1's georef places the anchors
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "sheet": 1,
                          "contours": _PAGE_ANCHORS})
    out = tmp_path / "t.npz"
    assert cli.main(["contour-surface", "--contours", *mans, "--anchors",
                     str(anchors), "--out", str(out)]) == 1
    assert "EPSG 2226, 2227" in capsys.readouterr().err
    assert not out.exists()


def _conflicting_five(tmp_path):
    man = tmp_path / "m.json"
    _write_v2_manifest(man, ys=_FIVE)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "interval_ft": 10.0,
                          "contours": _five_page_anchors(
                              [100.0, 110.0, 150.0, 130.0, 140.0])})
    return man, anchors


def test_contour_surface_review_dir_without_a_pdf(tmp_path):
    pytest.importorskip("scipy")
    man, anchors = _conflicting_five(tmp_path)
    rd = tmp_path / "review"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(tmp_path / "t.npz"),
                     "--review-dir", str(rd)]) == 0
    assert {p.name for p in rd.iterdir()} == {"review.md", "findings.json",
                                              "lines.csv", ".contour-review"}
    (f,) = json.loads((rd / "findings.json").read_text(encoding="utf-8"))["findings"]
    # the conflict's lines are y = 0..60 at x 0..200: centre world (100, 30),
    # which the georef (page -> world (2x, -2y)) puts at page (50, -15)
    assert f["kind"] == "conflict" and f["page"] == pytest.approx([50.0, -15.0])


def test_contour_surface_refuses_a_review_dir_it_did_not_write(tmp_path, capsys):
    man, anchors = _conflicting_five(tmp_path)
    rd = tmp_path / "work"
    rd.mkdir()
    (rd / "review.md").write_text("my own notes", encoding="utf-8")
    out = tmp_path / "t.npz"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(out), "--review-dir", str(rd)]) == 1
    assert "not a review directory" in capsys.readouterr().err
    assert (rd / "review.md").read_text(encoding="utf-8") == "my own notes"
    assert not out.exists()


def test_contour_surface_pdf_needs_a_review_dir(tmp_path, capsys):
    man, anchors = _conflicting_five(tmp_path)
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(tmp_path / "t.npz"),
                     "--pdf", str(tmp_path / "plans.pdf")]) == 1
    assert "--pdf needs --review-dir" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["0", "-5", "nan", "inf"])
def test_contour_surface_review_crop_ft_must_be_positive(tmp_path, capsys, bad):
    man, anchors = _conflicting_five(tmp_path)
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(tmp_path / "t.npz"),
                     "--review-dir", str(tmp_path / "review"),
                     "--review-crop-ft", bad]) == 1
    assert ("--review-crop-ft must be a finite number > 0"
            in capsys.readouterr().err)


def test_contour_surface_dpi_must_be_positive(tmp_path, capsys):
    man, anchors = _conflicting_five(tmp_path)
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(tmp_path / "t.npz"),
                     "--review-dir", str(tmp_path / "review"),
                     "--dpi", "0"]) == 1
    assert "--dpi" in capsys.readouterr().err


def test_contour_surface_singular_page_placement_is_an_input_error(tmp_path,
                                                                   capsys):
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man, ys=_FIVE)
    m = json.loads(man.read_text(encoding="utf-8"))
    m["georef"]["transform"] = [2.0, 0.0, 0.0, 4.0, 0.0, 0.0]      # det 0
    man.write_text(json.dumps(m), encoding="utf-8")
    anchors = tmp_path / "a.yaml"
    # world anchors need no page placement, so the run reaches the findings
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "interval_ft": 10.0,
                          "contours": [{"elev": v, "xy": [100.0, y]} for v, y in
                                       zip([100.0, 110.0, 150.0, 130.0, 140.0],
                                           _FIVE)]})
    out = tmp_path / "t.npz"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(out)]) == 1
    assert "singular" in capsys.readouterr().err
    assert not out.exists()


def test_contour_surface_review_crops_every_finding(tmp_path):
    pytest.importorskip("fitz")
    pytest.importorskip("scipy")
    from bimforge.bim.tests._pdf_fixtures import write_label_sheet
    pdf = write_label_sheet(tmp_path / "s.pdf")
    man = tmp_path / "c.json"
    assert cli.main(["contours", "--pdf", pdf, "--sheet", "1",
                     "--tie", "100,200=5000,1000", "--tie", "1100,200=5000,2000",
                     "--layer", "C=ocg:Topo|CONT_MJR", "--min-length", "2",
                     "--json", str(man)]) == 0
    anchors = tmp_path / "a.yaml"
    # 100 and 130 two contours apart on a 10 ft interval: a conflict
    _write_yaml(anchors, {"sheet": 1, "vertical_datum": "NGVD29",
                          "interval_ft": 10.0, "contours": [
                              {"elev": 100.0, "page": [600.0, 200.0]},
                              {"elev": 130.0, "page": [600.0, 400.0]}]})
    rd = tmp_path / "review"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--pdf", pdf, "--review-dir", str(rd),
                     "--dpi", "72", "--out", str(tmp_path / "t.npz")]) == 0
    names = {p.name for p in rd.iterdir()}
    assert {"F01.png", "contact-sheet.pdf", "contact-sheet-01.png",
            "review.md", "findings.json", "lines.csv"} <= names
    assert "![F01](F01.png)" in (rd / "review.md").read_text(encoding="utf-8")


# -------------------------------------------------------- est-bim terrain-diff
def _write_grid(path, z_val=10.0):
    z = np.full((10, 10), float(z_val))
    np.savez_compressed(path, z=z, xmin=0.0, ymin=0.0, xmax=10.0, ymax=10.0,
                        info=json.dumps({"project": "TESTGRID",
                                         "publication": "2020-01-01"}))


def test_terrain_diff_metric_surface_with_vshift(tmp_path, capsys):
    grid = tmp_path / "grid.npz"
    _write_grid(grid)
    surface = tmp_path / "surface.csv"
    surface.write_text("e,n,z\n5.0,5.0,10.2\n", encoding="utf-8")
    vshift = tmp_path / "vshift.json"
    vshift.write_text(json.dumps({"shift_m": 0.3, "source": "test pin",
                                  "lat": 0.0, "lon": 0.0}), encoding="utf-8")
    csv_out = tmp_path / "diff.csv"
    rc = cli.main(["terrain-diff", "--surface", str(surface),
                   "--grid", str(grid), "--vshift-json", str(vshift),
                   "--units", "m", "--csv", str(csv_out)])
    assert rc == 0
    lines = csv_out.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0].startswith("easting_m,")
    vals = [float(v) for v in lines[1].split(",")]
    # plan 10.2 + 0.3 shift = 10.5 NAVD88 m vs terrain 10.0 -> +0.5 (plan above)
    assert vals[4] == pytest.approx(0.5, abs=1e-6)


def test_terrain_diff_ftus_surface(tmp_path):
    from bimforge.terrain.diff import M_PER_FT
    grid = tmp_path / "grid.npz"
    _write_grid(grid)
    surface = tmp_path / "surface.xyz"
    ft = 5.0 / M_PER_FT
    surface.write_text(f"{ft:.9f} {ft:.9f} {10.0 / M_PER_FT:.9f}\n",
                       encoding="utf-8")
    csv_out = tmp_path / "diff.csv"
    rc = cli.main(["terrain-diff", "--surface", str(surface),
                   "--grid", str(grid), "--csv", str(csv_out)])
    assert rc == 0
    lines = csv_out.read_text(encoding="utf-8").strip().splitlines()
    vals = [float(v) for v in lines[1].split(",")]
    assert vals[0] == pytest.approx(5.0, abs=1e-6)
    assert vals[4] == pytest.approx(0.0, abs=1e-6)


def test_terrain_diff_no_overlap_is_exit_1(tmp_path, capsys):
    grid = tmp_path / "grid.npz"
    _write_grid(grid)
    surface = tmp_path / "surface.csv"
    surface.write_text("500.0,500.0,10.0\n", encoding="utf-8")
    rc = cli.main(["terrain-diff", "--surface", str(surface),
                   "--grid", str(grid), "--units", "m"])
    assert rc == 1
    assert "no overlap" in capsys.readouterr().err


def test_terrain_diff_png_degrades_without_matplotlib(
        tmp_path, monkeypatch, capsys):
    grid = tmp_path / "grid.npz"
    _write_grid(grid)
    surface = tmp_path / "surface.csv"
    surface.write_text("5.0,5.0,10.0\n", encoding="utf-8")

    def no_pyplot():
        raise ImportError("matplotlib blocked for test")

    monkeypatch.setattr("bimforge.terrain.diff._import_pyplot", no_pyplot)
    rc = cli.main(["terrain-diff", "--surface", str(surface),
                   "--grid", str(grid), "--units", "m",
                   "--png", str(tmp_path / "diff.png")])
    assert rc == 0                          # the PNG is optional; no raise
    assert "matplotlib" in capsys.readouterr().err
    assert not (tmp_path / "diff.png").exists()


def _save_square(path, z0, datum="NGVD29", crs=None):
    from bimforge.terrain.contours import save_tin_npz
    xy = np.array([[0, 0], [100, 0], [100, 100], [0, 100]], float)
    pts = np.column_stack([xy, z0 + 0.1 * xy[:, 0]])
    return save_tin_npz(path, pts, [[0, 1, 2], [0, 2, 3]],
                        {"vertical_datum": datum, "crs_epsg": crs}, [],
                        [-1, -1, -1, -1])


def test_terrain_diff_one_stated_datum_is_not_asserted(tmp_path, capsys):
    a = _save_square(tmp_path / "fg.npz", 102.0, datum="NGVD29")
    b = _save_square(tmp_path / "eg.npz", 100.0, datum=None)
    report = tmp_path / "r.md"
    assert cli.main(["terrain-diff", "--surface", a, "--against", b,
                     "--step", "10", "--report", str(report)]) == 0
    assert ("warning: eg.npz records no vertical datum; comparing as if it "
            "were NGVD29") in capsys.readouterr().err
    assert ("- vertical datum: NGVD29 (against: unstated)"
            in report.read_text(encoding="utf-8"))


def test_terrain_diff_refuses_two_horizontal_crss(tmp_path, capsys):
    a = _save_square(tmp_path / "a.npz", 102.0, crs=2226)
    b = _save_square(tmp_path / "b.npz", 100.0, crs=2227)
    assert cli.main(["terrain-diff", "--surface", a, "--against", b]) == 1
    assert "different horizontal CRSs" in capsys.readouterr().err


def test_terrain_diff_same_crs_and_datum_compare(tmp_path):
    a = _save_square(tmp_path / "a.npz", 102.0, crs=2226)
    b = _save_square(tmp_path / "b.npz", 100.0, crs=2226)
    assert cli.main(["terrain-diff", "--surface", a, "--against", b,
                     "--step", "10"]) == 0


@pytest.mark.parametrize("text", ["zones: 5\n", "- a\n- b\n", "zones:\n"])
def test_terrain_diff_a_malformed_zones_file_is_exit_1(tmp_path, capsys, text):
    a = _save_square(tmp_path / "fg.npz", 102.0)
    b = _save_square(tmp_path / "eg.npz", 100.0)
    zones = tmp_path / "zones.yaml"
    zones.write_text(text, encoding="utf-8")
    assert cli.main(["terrain-diff", "--surface", a, "--against", b,
                     "--zones", str(zones)]) == 1
    assert "error: zones file:" in capsys.readouterr().err


@pytest.mark.parametrize("flag, value", [("--step", "0"), ("--step", "-5"),
                                         ("--tie-tol", "0"),
                                         ("--tie-tol", "nan")])
def test_terrain_diff_step_and_tie_tol_must_be_positive(tmp_path, capsys,
                                                        flag, value):
    a = _save_square(tmp_path / "fg.npz", 102.0)
    b = _save_square(tmp_path / "eg.npz", 100.0)
    with pytest.raises(SystemExit) as exc:
        cli.main(["terrain-diff", "--surface", a, "--against", b, flag, value])
    assert exc.value.code != 0
    assert "must be > 0" in capsys.readouterr().err


def test_terrain_diff_tin_against_tin(tmp_path, capsys):
    a = _save_square(tmp_path / "fg.npz", 102.0)
    b = _save_square(tmp_path / "eg.npz", 100.0)
    csv_out, report = tmp_path / "d.csv", tmp_path / "r.md"
    rc = cli.main(["terrain-diff", "--surface", a, "--against", b,
                   "--step", "10", "--csv", str(csv_out),
                   "--report", str(report)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "not a pay quantity" in out.lower() and "median +2.000" in out
    assert csv_out.read_text().splitlines()[0] == "x,y,z_surface,z_against,delta"
    assert "not a pay quantity" in report.read_text(encoding="utf-8").lower()


def test_terrain_diff_refuses_two_vertical_datums(tmp_path, capsys):
    a = _save_square(tmp_path / "a.npz", 102.0, datum="NGVD29")
    b = _save_square(tmp_path / "b.npz", 100.0, datum="NAVD88")
    rc = cli.main(["terrain-diff", "--surface", a, "--against", b])
    assert rc == 1 and "vertical datum" in capsys.readouterr().err


def test_terrain_diff_against_needs_tin_files(tmp_path, capsys):
    b = _save_square(tmp_path / "b.npz", 100.0)
    xyz = tmp_path / "s.xyz"
    xyz.write_text("1 2 3\n", encoding="utf-8")
    rc = cli.main(["terrain-diff", "--surface", str(xyz), "--against", b])
    assert rc == 1 and ".npz" in capsys.readouterr().err


def test_terrain_diff_rejects_a_malformed_zone_without_a_traceback(
        tmp_path, capsys):
    a = _save_square(tmp_path / "fg.npz", 102.0)
    b = _save_square(tmp_path / "eg.npz", 100.0)
    zones = tmp_path / "zones.yaml"
    zones.write_text(yaml.safe_dump({"zones": [{"name": "west"}]}),
                     encoding="utf-8")
    rc = cli.main(["terrain-diff", "--surface", a, "--against", b,
                   "--zones", str(zones)])
    assert rc == 1 and "--zones" in capsys.readouterr().err


def test_terrain_diff_rejects_a_degenerate_zone_polygon(tmp_path, capsys):
    a = _save_square(tmp_path / "fg.npz", 102.0)
    b = _save_square(tmp_path / "eg.npz", 100.0)
    zones = tmp_path / "zones.yaml"
    zones.write_text(yaml.safe_dump(
        {"zones": [{"name": "west", "polygon": [[0, 0], [10, 0]]}]}),
        encoding="utf-8")
    rc = cli.main(["terrain-diff", "--surface", a, "--against", b,
                   "--zones", str(zones)])
    assert rc == 1 and "--zones" in capsys.readouterr().err


def test_terrain_diff_rejects_a_non_list_zone_polygon(tmp_path, capsys):
    a = _save_square(tmp_path / "fg.npz", 102.0)
    b = _save_square(tmp_path / "eg.npz", 100.0)
    zones = tmp_path / "zones.yaml"
    zones.write_text(yaml.safe_dump(
        {"zones": [{"name": "west", "polygon": 5}]}), encoding="utf-8")
    rc = cli.main(["terrain-diff", "--surface", a, "--against", b,
                   "--zones", str(zones)])
    assert rc == 1 and "--zones" in capsys.readouterr().err


def test_terrain_diff_grid_and_against_are_exclusive(tmp_path):
    with pytest.raises(SystemExit):
        cli.main(["terrain-diff", "--surface", "a.npz", "--grid", "g.npz",
                  "--against", "b.npz"])


def test_terrain_diff_grid_mode_accepts_a_tin_surface(tmp_path):
    from bimforge.terrain.diff import M_PER_FT
    grid = tmp_path / "grid.npz"
    _write_grid(grid)
    from bimforge.terrain.contours import save_tin_npz
    ft = 5.0 / M_PER_FT
    pts = np.array([[ft, ft, 10.0 / M_PER_FT]] * 3)
    tin = save_tin_npz(tmp_path / "s", pts, [[0, 1, 2]],
                       {"vertical_datum": "NAVD88"}, [], [-1, -1, -1])
    csv_out = tmp_path / "d.csv"
    assert cli.main(["terrain-diff", "--surface", tin, "--grid", str(grid),
                     "--csv", str(csv_out)]) == 0
    assert csv_out.read_text().splitlines()[0].startswith("easting_m,")


def test_terrain_diff_grid_mode_logs_the_tin_vertical_datum(tmp_path, capsys):
    grid = tmp_path / "grid.npz"
    _write_grid(grid)
    from bimforge.terrain.contours import save_tin_npz
    from bimforge.terrain.diff import M_PER_FT
    ft = 5.0 / M_PER_FT
    tin = save_tin_npz(tmp_path / "s", np.array([[ft, ft, 30.0]] * 3),
                       [[0, 1, 2]], {"vertical_datum": "NGVD29"}, [],
                       [-1, -1, -1])
    assert cli.main(["terrain-diff", "--surface", tin, "--grid",
                     str(grid)]) == 0
    line = next(ln for ln in capsys.readouterr().err.splitlines()
                if ln.startswith("vertical:"))
    assert "the surface TIN records vertical datum NGVD29" in line


# ------------------------- --crs-epsg on ties (#232) -------------------------
def _ties_run(*extra, manifest):
    return cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7",
                     "--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                     "--tie", "0,0=0,0", "--tie", "100,0=0,200",
                     "--json", str(manifest), *extra])


def test_crs_epsg_is_recorded_on_a_ties_manifest(contours_env, tmp_path):
    m = tmp_path / "c.json"
    rc = _ties_run("--crs-epsg", "2226", manifest=m)
    assert rc == 0
    g = json.loads(m.read_text(encoding="utf-8"))["georef"]
    assert g["method"] == "ties" and g["crs_epsg"] == 2226


def test_ties_without_crs_warns_it_wont_reach_a_model(contours_env, tmp_path, capsys):
    m = tmp_path / "c.json"
    rc = _ties_run(manifest=m)
    assert rc == 0
    assert "crs_epsg" not in json.loads(m.read_text(encoding="utf-8"))["georef"]
    err = capsys.readouterr().err
    assert "no CRS" in err and "--crs-epsg" in err


def test_ties_inherit_crs_from_an_agreeing_viewport(contours_env, tmp_path, capsys):
    contours_env.geo_state["viewports"] = [
        _viewport(transform=(2.0, 0.0, 0.0, 0.0, -2.0, 0.0),
                  bbox=(-5.0, -5.0, 105.0, 5.0))]
    m = tmp_path / "c.json"
    rc = _ties_run(manifest=m)                          # no --crs-epsg
    assert rc == 0
    g = json.loads(m.read_text(encoding="utf-8"))["georef"]
    assert g["crs_epsg"] == 2226
    assert "inherited from GeoPDF viewport" in capsys.readouterr().err


def test_ties_explicit_viewport_with_no_geopdf_viewport_is_exit_1(
        contours_env, tmp_path, capsys):
    m = tmp_path / "c.json"
    rc = _ties_run("--viewport", "3", manifest=m)
    assert rc == 1
    assert "no GeoPDF viewport" in capsys.readouterr().err


def test_ties_disagreeing_with_viewport_warns_but_ties_still_win(
        contours_env, tmp_path, capsys):
    # the default viewport maps the tie page points ~5000 ft away
    contours_env.geo_state["viewports"] = [_viewport()]
    m = tmp_path / "c.json"
    rc = _ties_run(manifest=m)
    assert rc == 0
    g = json.loads(m.read_text(encoding="utf-8"))["georef"]
    assert g["method"] == "ties"                        # ties still win
    assert "crs_epsg" not in g                          # not inherited on disagreement
    err = capsys.readouterr().err
    assert "WARNING" in err and "GeoPDF" in err


def test_ties_scale_drift_blocks_crs_inheritance_but_is_not_fatal(
        contours_env, tmp_path, capsys):
    contours_env.geo_state["viewports"] = [
        _viewport(transform=(2.04, 0.0, 0.0, 0.0, -2.04, 0.0),
                  bbox=(-5.0, -5.0, 105.0, 5.0))]
    m = tmp_path / "c.json"
    rc = _ties_run(manifest=m)
    assert rc == 0
    g = json.loads(m.read_text(encoding="utf-8"))["georef"]
    assert "crs_epsg" not in g
    assert "not inheriting its CRS" in capsys.readouterr().err


def test_crs_epsg_conflicting_with_a_geopdf_viewport_is_exit_1(
        contours_env, capsys):
    contours_env.geo_state["viewports"] = [_viewport()]
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7",
                   "--layer", "EXIST=0.5@0.72", "--crs-epsg", "9999"])
    assert rc == 1
    assert "conflicts with the GeoPDF viewport" in capsys.readouterr().err


def test_ties_crs_epsg_conflicting_with_an_agreeing_viewport_is_exit_1(
        contours_env, tmp_path, capsys):
    contours_env.geo_state["viewports"] = [
        _viewport(transform=(2.0, 0.0, 0.0, 0.0, -2.0, 0.0),
                  bbox=(-5.0, -5.0, 105.0, 5.0))]
    m = tmp_path / "c.json"
    rc = _ties_run("--crs-epsg", "9999", manifest=m)
    assert rc == 1
    assert "conflicts with the GeoPDF viewport" in capsys.readouterr().err


def test_crs_epsg_on_calibration_only_is_exit_1(contours_env, capsys):
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7",
                   "--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                   "--crs-epsg", "2226"])
    assert rc == 1
    assert "--crs-epsg" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["0", "-5"])
def test_crs_epsg_must_be_positive(tmp_path, capsys, value):
    with pytest.raises(SystemExit) as exc:
        _ties_run("--crs-epsg", value, manifest=tmp_path / "c.json")
    assert exc.value.code != 0
    assert "must be > 0" in capsys.readouterr().err


# --------------------------- --clip to the plan viewport (#243) --------------
def test_contours_clip_drops_out_of_viewport_paths(contours_env, tmp_path):
    # a title-block glyph stroke far outside the plan area
    contours_env.segments.append(_Seg(500.0, 500.0, 503.0, 500.0))
    m = tmp_path / "c.json"
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7",
                   "--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                   "--clip", "0,0,200,200", "--json", str(m)])
    assert rc == 0
    man = json.loads(m.read_text(encoding="utf-8"))
    assert man["clip"] == [0.0, 0.0, 200.0, 200.0]
    rec = man["layers"]["EXIST"]
    assert rec["polylines"] == 1                     # the real contour survived
    assert rec["clipped"] == 1                       # the title-block glyph gone


def test_contours_bad_clip_is_exit_1(contours_env, capsys):
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7",
                   "--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                   "--clip", "1,2,3"])
    assert rc == 1
    assert "clip" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["nan,0,1,2", "0,0,inf,2", "0,0,1,-inf"])
def test_contours_non_finite_clip_is_exit_1(contours_env, capsys, value):
    rc = cli.main(["contours", "--pdf", "x.pdf", "--sheet", "7",
                   "--calib", "calib.yaml", "--layer", "EXIST=0.5@0.72",
                   "--clip", value])
    assert rc == 1
    assert "finite" in capsys.readouterr().err


def test_contour_surface_report_shows_each_conflict_chain_ft_per_hop(tmp_path):
    # #397: a conflict says how many feet per hop its chain implies, so a
    # faces edge across a gap can be found without tracing the lines by hand
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man, ys=_FIVE)
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "interval_ft": 10.0,
                          "contours": _five_page_anchors(
                              [100.0, 110.0, 150.0, 130.0, 140.0])})
    out, report = tmp_path / "t.npz", tmp_path / "r.md"
    assert cli.main(["contour-surface", "--contours", str(man), "--anchors",
                     str(anchors), "--out", str(out),
                     "--report", str(report)]) == 0
    text = report.read_text(encoding="utf-8")
    assert ("- chain 2(150) – 1(110): 1 hop for 40 ft = 40.00 ft/hop against "
            "the 10 ft interval — more than one interval per hop") in text


def test_contour_surface_min_facing_ft_sets_the_neighbour_graph(tmp_path, capsys):
    # #397: --min-facing-ft is exposed; a facing run shorter than it is no hop
    pytest.importorskip("scipy")
    man = tmp_path / "m.json"
    _write_v2_manifest(man)                    # three 400-ft lines, 40 ft apart
    anchors = tmp_path / "a.yaml"
    _write_yaml(anchors, {"vertical_datum": "NGVD29", "interval_ft": 10.0,
                          "contours": [_PAGE_ANCHORS[0], _PAGE_ANCHORS[2]]})
    base = ["contour-surface", "--contours", str(man), "--anchors",
            str(anchors)]
    out = tmp_path / "t.npz"
    assert cli.main(base + ["--out", str(out)]) == 0
    info = json.loads(str(np.load(out, allow_pickle=False)["info"]))
    assert info["graph"]["min_facing_ft"] == 4.0
    assert info["reconcile"]["pinned"] == 1            # the middle line: 110
    capsys.readouterr()
    out2 = tmp_path / "t2.npz"
    assert cli.main(base + ["--out", str(out2), "--min-facing-ft", "1000"]) == 0
    info = json.loads(str(np.load(out2, allow_pickle=False)["info"]))
    assert info["graph"]["min_facing_ft"] == 1000.0
    assert info["reconcile"]["pinned"] == 0 and info["reconcile"]["unreached"] == 1


# ------------------------------------- barriers across a gap (#397 part b)
# contours 100..110; the 103..107 bank stops at x = 100 (a roadway cut took
# the rest), so past it 102 and 108 face across empty ground: one hop for 6 ft
_GAP_Y = {100: 0.0, 101: 20.0, 102: 40.0, 103: 44.0, 104: 46.0, 105: 48.0,
          106: 50.0, 107: 52.0, 108: 56.0, 109: 76.0, 110: 96.0}
_GAP_PROP = [[105.0, 48.0], [150.0, 48.0], [200.0, 48.0]]   # through the gap


def _gap_manifest(path, *, prop=True):
    lines = [{"points": [[float(x), y] for x in
                         (range(0, 101, 10) if 103 <= z <= 107
                          else range(0, 201, 10))]}
             for z, y in _GAP_Y.items()]
    extra = {"PROP": {"lines": [{"points": _GAP_PROP}]}} if prop else {}
    m = {"manifest_version": 2, "sheet": 1, "source_kind": "vector",
         "georef": {"method": "calibration", "model": "similarity",
                    "frame": "sheet_local_ft", "ft_per_pt": 2.0,
                    "transform": [2.0, 0.0, 0.0, 0.0, -2.0, 0.0],
                    "residuals_ft": []},
         "layers": {"EXIST": {"lines": lines}, **extra}}
    path.write_text(json.dumps(m), encoding="utf-8")


def _gap_anchors(path, **extra):
    # labels 100, 105, 110 at world x = 50 -> page (25, -y / 2)
    _write_yaml(path, {"sheet": 1, "vertical_datum": "NGVD29",
                       "interval_ft": 1.0, **extra,
                       "contours": [{"id": f"L{z}", "elev": float(z),
                                     "page": [25.0, -_GAP_Y[z] / 2.0]}
                                    for z in (100, 105, 110)]})


def _gap_run(tmp_path, *extra, anchors_extra=None, prop=True):
    man, anchors = tmp_path / "m.json", tmp_path / "a.yaml"
    _gap_manifest(man, prop=prop)
    _gap_anchors(anchors, **(anchors_extra or {}))
    out, report = tmp_path / "t.npz", tmp_path / "r.md"
    rc = cli.main(["contour-surface", "--contours", str(man), "--anchors",
                   str(anchors), "--out", str(out), "--report", str(report),
                   *extra])
    return rc, out, report


def _info(out):
    return json.loads(str(np.load(out, allow_pickle=False)["info"]))


def test_contour_surface_a_gap_conflicts_without_a_barrier(tmp_path):
    # the counterfactual: the same sheet, nothing in the gap
    pytest.importorskip("scipy")
    rc, out, report = _gap_run(tmp_path, "--layers", "EXIST")
    assert rc == 0
    assert _info(out)["reconcile"]["label_conflicts"] == 2
    findings = report.read_text(encoding="utf-8").split("## Findings")[1]
    assert "| F01 | conflict |" in findings


def test_contour_surface_barrier_layers_set_the_gap_aside(tmp_path, capsys):
    pytest.importorskip("scipy")
    from bimforge.terrain.contours import load_tin_npz
    rc, out, report = _gap_run(tmp_path, "--barrier-layers", "PROP")
    assert rc == 0
    err = capsys.readouterr().err
    assert "11 polylines from 1 manifest(s)" in err       # PROP is no contour
    assert "barriers: 1 faces pair(s) set aside (layer PROP: 1)" in err
    info = _info(out)
    assert info["reconcile"]["label_conflicts"] == 0
    assert info["reconcile"]["conflict"] == 0 and info["reconcile"]["pinned"] == 8
    assert info["graph"]["barriers"] == {"layer PROP": 1}
    assert info["graph"]["barred"] == 1
    t = load_tin_npz(out)
    # the TIN is the lettered contours only: the PROP line is no contour
    assert sorted(ln["elev"] for ln in t.lines) == [100.0, 105.0, 110.0]
    assert {ln["source"] for ln in t.lines} == {"sheet 1 / EXIST"}
    text = report.read_text(encoding="utf-8")
    findings = text.split("## Findings")[1]
    assert "| conflict |" not in findings                 # the only finding:
    assert "| F01 | barrier | 2, 8 |" in findings         # the gap, set aside
    assert "| F02 |" not in findings
    assert "lines 2 and 8:" in text and "set aside by layer PROP" in text
    assert "barriers: layer PROP (1 line)" in text


def test_contour_surface_barrier_layers_with_layers_keeps_both_apart(tmp_path):
    pytest.importorskip("scipy")
    rc, out, _ = _gap_run(tmp_path, "--layers", "EXIST",
                          "--barrier-layers", "PROP")
    assert rc == 0
    assert _info(out)["reconcile"]["label_conflicts"] == 0


def test_contour_surface_unknown_barrier_layer_is_exit_1(tmp_path, capsys):
    rc, _, _ = _gap_run(tmp_path, "--barrier-layers", "PROPMIN")
    assert rc == 1
    assert "--barrier-layers PROPMIN: no such layer" in capsys.readouterr().err


def test_contour_surface_a_layer_cannot_be_contour_and_barrier(tmp_path, capsys):
    rc, _, _ = _gap_run(tmp_path, "--layers", "EXIST", "PROP",
                        "--barrier-layers", "PROP")
    assert rc == 1
    assert ("PROP is in both --layers and --barrier-layers"
            in capsys.readouterr().err)


def test_contour_surface_anchors_break_lines_are_barriers(tmp_path, capsys):
    pytest.importorskip("scipy")
    # the same polyline as PROP, drawn in page points: world (2x, -2y)
    brk = {"breaks": [{"page": [[x / 2.0, -y / 2.0] for x, y in _GAP_PROP],
                       "note": "roadway cut"}]}
    rc, out, report = _gap_run(tmp_path, "--review-dir",
                               str(tmp_path / "review"),
                               anchors_extra=brk, prop=False)
    assert rc == 0
    assert ("barriers: 1 faces pair(s) set aside (break lines: 1)"
            in capsys.readouterr().err)
    info = _info(out)
    assert info["reconcile"]["label_conflicts"] == 0
    assert info["reconcile"]["pinned"] == 8
    assert info["graph"]["barriers"] == {"break 1 (roadway cut)": 1}
    text = report.read_text(encoding="utf-8")
    assert "set aside by break 1 (roadway cut)" in text
    review = (tmp_path / "review" / "review.md").read_text(encoding="utf-8")
    assert "## F01 · barrier" in review
    assert "set aside by break 1 (roadway cut)" in review
    (f,) = json.loads((tmp_path / "review" / "findings.json")
                      .read_text(encoding="utf-8"))["findings"]
    assert f["kind"] == "barrier" and f["lines"] == [2, 8]
    assert f["page"] is not None and 50.0 < f["page"][0] < 100.0


def test_contour_surface_no_face_sets_one_pair_aside(tmp_path, capsys):
    pytest.importorskip("scipy")
    rc, out, report = _gap_run(tmp_path, "--layers", "EXIST",
                               "--no-face", "2,8")
    assert rc == 0
    assert ("barriers: 1 faces pair(s) set aside (--no-face: 1)"
            in capsys.readouterr().err)
    info = _info(out)
    assert info["reconcile"]["label_conflicts"] == 0
    assert info["reconcile"]["pinned"] == 8
    assert info["graph"]["no_face"] == [[2, 8]]
    assert "set aside by --no-face" in report.read_text(encoding="utf-8")


def test_contour_surface_no_face_warns_on_a_pair_that_does_not_face(
        tmp_path, capsys):
    pytest.importorskip("scipy")
    rc, out, _ = _gap_run(tmp_path, "--layers", "EXIST", "--no-face", "0,5")
    assert rc == 0
    assert "warning: --no-face 0,5: not a faces pair" in capsys.readouterr().err
    assert _info(out)["reconcile"]["label_conflicts"] == 2


def test_contour_surface_no_face_out_of_range_is_exit_1(tmp_path, capsys):
    pytest.importorskip("scipy")
    rc, _, _ = _gap_run(tmp_path, "--layers", "EXIST", "--no-face", "2,11")
    assert rc == 1
    assert "line 11 is out of range (0..10)" in capsys.readouterr().err


@pytest.mark.parametrize("bad", ["2", "a,b", "1,2,3"])
def test_contour_surface_malformed_no_face_is_a_usage_error(tmp_path, capsys,
                                                            bad):
    with pytest.raises(SystemExit) as exc:
        _gap_run(tmp_path, "--layers", "EXIST", "--no-face", bad)
    assert exc.value.code == 2
    assert "expected A,B" in capsys.readouterr().err


def test_contour_surface_without_barriers_reports_no_barrier_line(tmp_path,
                                                                  capsys):
    pytest.importorskip("scipy")
    rc, out, report = _gap_run(tmp_path, "--layers", "EXIST")
    assert rc == 0
    assert "barriers:" not in capsys.readouterr().err
    info = _info(out)
    assert "barriers" not in info["graph"] and "barred" not in info["graph"]
    assert "barrier" not in report.read_text(encoding="utf-8")


# ------------------------------------------- review of #397 b (round 2)
_GAP_PROP_SHORT = [[130.0, 48.0], [200.0, 48.0]]     # stops short: leaks


def _gap_run_with(tmp_path, prop_points, *extra):
    man, anchors = tmp_path / "m.json", tmp_path / "a.yaml"
    _gap_manifest(man)
    m = json.loads(man.read_text(encoding="utf-8"))
    m["layers"]["PROP"]["lines"] = ([{"points": prop_points}]
                                    if prop_points else [])
    man.write_text(json.dumps(m), encoding="utf-8")
    _gap_anchors(anchors)
    out, report = tmp_path / "t.npz", tmp_path / "r.md"
    rc = cli.main(["contour-surface", "--contours", str(man), "--anchors",
                   str(anchors), "--out", str(out), "--report", str(report),
                   *extra])
    return rc, out, report


def test_contour_surface_strict_ignores_a_barrier_the_user_asked_for(
        tmp_path, capsys):
    pytest.importorskip("scipy")
    rc, out, report = _gap_run(tmp_path, "--barrier-layers", "PROP",
                               "--strict")
    assert rc == 0                         # the set-aside was asked for
    assert "findings: 1 (1 barrier)" in capsys.readouterr().err
    assert _info(out)["findings"] == 1     # still reported everywhere
    assert "| F01 | barrier | 2, 8 |" in report.read_text(encoding="utf-8")


def test_contour_surface_a_leaky_barrier_is_reported_and_fails_strict(
        tmp_path, capsys):
    pytest.importorskip("scipy")
    rc, out, report = _gap_run_with(tmp_path, _GAP_PROP_SHORT,
                                    "--barrier-layers", "PROP", "--strict")
    assert rc == 2
    err = capsys.readouterr().err
    assert ("barriers: 0 faces pair(s) set aside; 1 pair(s) kept though "
            "partly blocked — extend the barrier (layer PROP: 1)") in err
    assert "error: --strict" in err
    info = _info(out)
    assert info["graph"]["barred"] == 0 and info["graph"]["partly_barred"] == 1
    assert info["reconcile"]["label_conflicts"] == 2     # the gap still hops
    text = report.read_text(encoding="utf-8")
    assert "still faces — the pair is kept; extend the barrier/break line" in text


def test_contour_surface_warns_on_an_empty_barrier_layer(tmp_path, capsys):
    pytest.importorskip("scipy")
    rc, out, _ = _gap_run_with(tmp_path, None, "--barrier-layers", "PROP")
    assert rc == 0
    assert ("warning: --barrier-layers PROP: layer has no lines"
            in capsys.readouterr().err)


def test_contour_surface_no_face_on_a_barred_pair_names_the_barrier(
        tmp_path, capsys):
    pytest.importorskip("scipy")
    rc, out, _ = _gap_run(tmp_path, "--barrier-layers", "PROP",
                          "--no-face", "2,8")
    assert rc == 0
    assert ("warning: --no-face 2,8: already set aside by layer PROP"
            in capsys.readouterr().err)


def test_contour_surface_help_explains_barriers_and_strict(capsys):
    with pytest.raises(SystemExit):
        cli.main(["contour-surface", "--help"])
    out = " ".join(capsys.readouterr().out.split())
    assert "must reach the ends of the interrupted contours" in out
    assert "barrier findings you asked for do not count" in out
