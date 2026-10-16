"""est-sheets — sheet-production CLI: control / layout / structure.

Deterministic file operations wrapping the `bimforge.sheets` renderers
(the sheet engine ships inside bimforge as `bimforge.cad`; only PDF/PNG
rendering needs the optional `draw` extra). Every anticipated failure
(missing file, bad CSV/YAML/JSON shape, invalid scale, unmapped layers,
the `sheets` extra not installed) prints one clean line and returns 1,
mirroring `estimating_tools.intake.cli`'s house style.

Outputs land in `--out-dir` (created if missing), named from a slug of
`--title`: `<slug>.dxf` (control/layout), `<slug>.sheet.dxf` (structure),
plus `<slug>.pdf` / `<slug>.png` / `qc-<slug>.md` always, and `<slug>.kml`
for control/layout when a CRS is derivable (structure sheets have no `--kml`
flag — they rarely have a derivable CRS). PDF/PNG rendering
(`bimforge.cad.plot.render_layout`) is best-effort: if matplotlib (the `draw`
extra) is unavailable, or the rendering step itself fails, a note is printed
and the sheet DXF is left as the product — that failure alone does not fail
the command.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

from bimforge.sheets.control import (
    _layout_name, control_kml, draw_control_sheet, qc_report,
)
from bimforge.sheets.layout import draw_layout_sheet, layout_kml, layout_qc
from bimforge.sheets.model import (
    Alignment, SheetMeta, VALID_GRADES, load_control_csv, scale_from_engineering,
)
from bimforge.sheets.structure import frame_structure_sheet, structure_qc

_SHEETS_EXTRA_MSG = (
    'install the draw extra: pip install "bimforge[draw]" '
    "(matplotlib, for PDF/PNG rendering)")

_SLUG_RE = re.compile(r"[^a-z0-9]+")

_LAYOUT_EXCLUDE = ("Model", "Layout1")


def _slugify(title: str) -> str:
    return _SLUG_RE.sub("-", title.lower()).strip("-") or "sheet"


def _find_sheet_layout(doc, expected: str) -> str:
    """Name of the paperspace layout `compose_sheet` created.

    Tries the sanitized `expected` name (what the renderer actually asked
    `compose_sheet` for) first — exact match wins even when other, unrelated
    layouts are present (e.g. a pre-existing layout in a source DXF handed to
    `structure`). Falls back to the single-candidate heuristic (robust to
    truncation/formatting differences) only when there's exactly one
    non-default layout to fall back to.
    """
    names = [lay.name for lay in doc.layouts if lay.name not in _LAYOUT_EXCLUDE]
    if expected in names:
        return expected
    if len(names) == 1:
        return names[0]
    raise ValueError(
        f"expected sheet layout {expected!r} in the saved DXF, found {names}")


def _emit_pdf_png(dxf_path: Path, slug: str, out_dir: Path, args, expected_layout: str) -> None:
    """Best-effort PDF/PNG rendering — never fails the command."""
    if not args.pdf and not args.png:
        return
    try:
        import ezdxf
        from bimforge.cad.plot import render_layout
    except ImportError:
        print(f"skipping PDF/PNG rendering — {_SHEETS_EXTRA_MSG}")
        return
    try:
        doc = ezdxf.readfile(dxf_path)
        layout_name = _find_sheet_layout(doc, expected_layout)
        if args.pdf:
            render_layout(doc, layout_name, out_dir / f"{slug}.pdf")
        if args.png:
            render_layout(doc, layout_name, out_dir / f"{slug}.png")
    except Exception as exc:
        print(f"skipping PDF/PNG rendering: {exc}")


def _parse_scale(text: str | None) -> tuple[float | None, int]:
    """(scale, rc) — rc is 1 (with a message already printed) on bad input."""
    if not text:
        return None, 0
    try:
        return scale_from_engineering(text), 0
    except ValueError as exc:
        print(exc)
        return None, 1


def cmd_control(args) -> int:
    try:
        points = load_control_csv(args.csv_path)
    except FileNotFoundError:
        print(f"no such file: {args.csv_path}")
        return 1
    except ValueError as exc:
        print(exc)
        return 1

    scale_val, rc = _parse_scale(args.scale)
    if rc:
        return rc

    try:
        meta = SheetMeta(project=args.project, sheet_title=args.title, grade=args.grade,
                         crs_epsg=args.crs_epsg, basis_note=args.basis or "",
                         combined_factor=args.combined_factor, bid_number=args.bid_number,
                         date=args.date or "", scale_text=args.scale or "")
    except ValueError as exc:
        print(exc)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(args.title)
    dxf_path = out_dir / f"{slug}.dxf"

    try:
        draw_control_sheet(points, meta, dxf_path, size=args.size, scale=scale_val)
    except ImportError:
        print(_SHEETS_EXTRA_MSG)
        return 1
    except (ValueError, KeyError, TypeError) as exc:
        print(exc)
        return 1

    (out_dir / f"qc-{slug}.md").write_text(qc_report(points, meta), encoding="utf-8")

    if args.kml:
        kml_text = control_kml(points, meta)
        if kml_text:
            (out_dir / f"{slug}.kml").write_text(kml_text, encoding="utf-8")

    _emit_pdf_png(dxf_path, slug, out_dir, args, _layout_name(args.title, "CONTROL"))
    print(f"control sheet: {dxf_path}")
    return 0


def cmd_layout(args) -> int:
    try:
        raw = yaml.safe_load(Path(args.alignment_yaml).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"no such file: {args.alignment_yaml}")
        return 1
    except yaml.YAMLError as exc:
        print(f"invalid YAML in {args.alignment_yaml}: {exc}")
        return 1
    if not isinstance(raw, dict) or not isinstance(raw.get("points"), list):
        print("alignment YAML must be a mapping with a 'points' list "
              "(each {station, northing, easting})")
        return 1

    try:
        points = [{"station": float(p["station"]), "northing": float(p["northing"]),
                  "easting": float(p["easting"])} for p in raw["points"]]
    except (TypeError, KeyError, ValueError) as exc:
        print(f"invalid alignment points in {args.alignment_yaml}: {exc}")
        return 1

    grade = args.grade or raw.get("grade")
    if not grade:
        print("grade is required: pass --grade or set 'grade' in the alignment YAML")
        return 1

    crs_epsg = args.crs_epsg if args.crs_epsg is not None else raw.get("crs_epsg")

    scale_val, rc = _parse_scale(args.scale)
    if rc:
        return rc

    try:
        alignment = Alignment(name=raw.get("name") or args.title, points=points)
    except ValueError as exc:
        print(exc)
        return 1

    try:
        meta = SheetMeta(project=args.project, sheet_title=args.title, grade=grade,
                         crs_epsg=crs_epsg, bid_number=args.bid_number,
                         date=args.date or "", scale_text=args.scale or "")
    except ValueError as exc:
        print(exc)
        return 1

    structures = None
    if args.structures:
        try:
            structures = json.loads(Path(args.structures).read_text(encoding="utf-8"))
        except FileNotFoundError:
            print(f"no such file: {args.structures}")
            return 1
        except json.JSONDecodeError as exc:
            print(f"invalid JSON in {args.structures}: {exc}")
            return 1
        if not isinstance(structures, list):
            print(f"structures JSON must be a list, got {type(structures).__name__}")
            return 1
        if not all(isinstance(s, dict) and "structure_id" in s and "station" in s
                   for s in structures):
            print("structures entries must be objects with structure_id and station")
            return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(args.title)
    dxf_path = out_dir / f"{slug}.dxf"

    try:
        draw_layout_sheet(alignment, meta, dxf_path, structures=structures,
                          tick_interval=args.tick_interval, size=args.size, scale=scale_val)
    except ImportError:
        print(_SHEETS_EXTRA_MSG)
        return 1
    except (ValueError, KeyError, TypeError) as exc:
        print(exc)
        return 1

    (out_dir / f"qc-{slug}.md").write_text(
        layout_qc(alignment, meta, structures), encoding="utf-8")

    if args.kml:
        kml_text = layout_kml(alignment, meta, structures)
        if kml_text:
            (out_dir / f"{slug}.kml").write_text(kml_text, encoding="utf-8")

    _emit_pdf_png(dxf_path, slug, out_dir, args, _layout_name(args.title, "LAYOUT"))
    print(f"layout sheet: {dxf_path}")
    return 0


def cmd_structure(args) -> int:
    scale_val, rc = _parse_scale(args.scale)
    if rc:
        return rc

    try:
        meta = SheetMeta(project=args.project, sheet_title=args.title, grade=args.grade,
                         crs_epsg=args.crs_epsg, bid_number=args.bid_number,
                         date=args.date or "", scale_text=args.scale or "")
    except ValueError as exc:
        print(exc)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slugify(args.title)
    out_path = out_dir / f"{slug}.sheet.dxf"

    try:
        import ezdxf
        frame_structure_sheet(args.dxf_path, args.layer_map, meta, out_path,
                              size=args.size, scale=scale_val)
    except FileNotFoundError as exc:
        print(exc)
        return 1
    except yaml.YAMLError as exc:
        print(f"invalid YAML in {args.layer_map}: {exc}")
        return 1
    except ImportError:
        print(_SHEETS_EXTRA_MSG)
        return 1
    except ezdxf.DXFError as exc:
        print(f"corrupt or invalid DXF: {exc}")
        return 1
    except (ValueError, KeyError, TypeError) as exc:
        print(exc)
        return 1

    (out_dir / f"qc-{slug}.md").write_text(
        structure_qc(args.dxf_path, meta), encoding="utf-8")

    _emit_pdf_png(out_path, slug, out_dir, args, _layout_name(args.title, "STRUCTURE"))
    print(f"structure sheet: {out_path}")
    return 0


def _add_shared_args(p: argparse.ArgumentParser, *, grade_required: bool,
                     add_kml: bool = True) -> None:
    p.add_argument("--project", required=True)
    p.add_argument("--grade", choices=list(VALID_GRADES), default=None,
                   required=grade_required,
                   help="survey | approximate" + ("" if grade_required else
                        " (optional here — falls back to the alignment YAML's 'grade')"))
    p.add_argument("--title", required=True)
    p.add_argument("--out-dir", required=True)
    p.add_argument("--size", choices=["ARCH_D", "11x17"], default="ARCH_D")
    p.add_argument("--scale", default=None, help="engineering scale text, e.g. 1\"=30'")
    p.add_argument("--crs-epsg", type=int, default=None)
    p.add_argument("--bid-number", default=None)
    p.add_argument("--date", default=None)
    p.add_argument("--pdf", action=argparse.BooleanOptionalAction, default=True,
                   help="Render a PDF alongside the DXF (default: attempt it; "
                        "skipped with a note if the sheets/draw extra is missing).")
    p.add_argument("--png", action="store_true", help="Also render a PNG preview.")
    if add_kml:
        p.add_argument("--kml", action=argparse.BooleanOptionalAction, default=True,
                       help="Write a KML alongside the DXF when derivable "
                            "(control, layout).")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="est-sheets",
        description="Sheet production: control / layout / structure sheets "
                    "(DXF + PDF + KML + QC) from Phase-1 project data.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("control", help="Draw a survey-control sheet from a control-points CSV.")
    p.add_argument("csv_path")
    p.add_argument("--basis", default=None, help="Basis-of-bearing/coordinates prose.")
    p.add_argument("--combined-factor", type=float, default=None,
                   help="Grid-to-ground combined scale factor.")
    _add_shared_args(p, grade_required=True)
    p.set_defaults(func=cmd_control)

    p = sub.add_parser("layout", help="Draw a layout sheet from an alignment YAML.")
    p.add_argument("alignment_yaml")
    p.add_argument("--structures", default=None,
                   help="JSON file: list of {structure_id, station, offset_ft, side}.")
    p.add_argument("--tick-interval", type=float, default=100.0)
    _add_shared_args(p, grade_required=False)
    p.set_defaults(func=cmd_layout)

    p = sub.add_parser("structure", help="Frame a takeoff DXF into a structure sheet.")
    p.add_argument("dxf_path")
    p.add_argument("--layer-map", required=True)
    _add_shared_args(p, grade_required=True, add_kml=False)
    p.set_defaults(func=cmd_structure)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
