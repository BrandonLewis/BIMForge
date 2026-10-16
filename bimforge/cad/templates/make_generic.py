"""Generate templates/generic-title-blocks.dxf — bimforge's neutral border library.

Defines the same block names the engine's SHEET_SIZES expect
("border_ARCH D TITLE", "border_11X17 TITLE") so any conforming library —
this one or an org style pack's — drops in without code changes: a plain
double border rectangle, a title strip, and one ATTDEF per TitleBlockFields
field (upper-cased tags) so ``add_auto_attribs`` stamps every field.

Regeneration is not byte-reproducible: ezdxf stamps $TDCREATE/$TDUPDATE,
$FINGERPRINTGUID/$VERSIONGUID, and a versioned comment on every run. When
reviewing a regenerated file, diff the geometry and ATTDEFs, not raw bytes.

Usage:  python packages/bimforge/bimforge/cad/templates/make_generic.py
"""
from __future__ import annotations

from pathlib import Path

import ezdxf

#: (block name, paper (w, h) in inches) — must match titleblock.SHEET_SIZES.
BLOCKS = (
    ("border_ARCH D TITLE", (36.0, 24.0)),
    ("border_11X17 TITLE", (11.0, 17.0)),
)

#: TitleBlockFields attribute tags (upper-cased dataclass field names).
TAGS = (
    "PROJECT", "CONTRACT", "BRIDGE", "JOB_NO", "PROJECT_NAME", "SUBTITLE",
    "SHEET_TITLE", "CITY", "COUNTY", "DATE", "SCALE", "DRAFTER", "DESIGNER",
    "CHECKED", "SHT", "SHT_TOTAL",
)

MARGIN = 0.5   # border inset from the paper edge, inches
STRIP_H = 2.0  # title strip height, inches
TEXT_H = 0.09  # attdef text height, inches


def build(path: Path) -> Path:
    doc = ezdxf.new("R2018", setup=True)
    for name, (w, h) in BLOCKS:
        blk = doc.blocks.new(name=name)
        blk.add_lwpolyline([(0, 0), (w, 0), (w, h), (0, h)], close=True)
        blk.add_lwpolyline(
            [(MARGIN, MARGIN), (w - MARGIN, MARGIN),
             (w - MARGIN, h - MARGIN), (MARGIN, h - MARGIN)], close=True)
        blk.add_lwpolyline(
            [(MARGIN, MARGIN), (w - MARGIN, MARGIN),
             (w - MARGIN, MARGIN + STRIP_H), (MARGIN, MARGIN + STRIP_H)],
            close=True)
        cols = 4
        cell_w = (w - 2 * MARGIN) / cols
        cell_h = STRIP_H / 4
        for i, tag in enumerate(TAGS):
            cx = MARGIN + (i % cols) * cell_w + 0.1
            cy = MARGIN + STRIP_H - (i // cols + 1) * cell_h + 0.05
            blk.add_attdef(tag, insert=(cx, cy), dxfattribs={"height": TEXT_H})
    doc.saveas(path)
    return path


if __name__ == "__main__":
    print(build(Path(__file__).parent / "generic-title-blocks.dxf"))
