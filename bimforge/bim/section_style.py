"""What a cut reads as: the section fill colour and hatch for each kind of
material, for the DXF sheets (the IfcSection Blender add-on carries its own
copy and paints the same hatches live).

A cut is classified by its material name (the IfcSurfaceStyle / IfcMaterial
name, e.g. "Compacted Fill"), else its object name ("IfcReinforcingBar/B1",
"S-EW-FILL"). The first kind whose pattern matches wins, so rebar is tried
before steel, lean concrete before concrete, compacted fill before native
earth. The rgb of the kinds BIMForge styles itself are
bimforge.author.ifc_styles' (a test holds them equal).

Each kind carries two hatches:

* `dxf`: an ezdxf/AutoCAD pattern and its density. Patterns are defined in
  millimetres, so the hatch scale is (sheet scale / 25.4) x density: the
  pattern plots at its nominal size on paper at any drawing scale.
* `paint`: the procedural hatch the Blender add-on paints in the section
  materials (Material Preview / Rendered): "stipple", "sand", "earth",
  "lines", "cross", "gravel", "solid", or "" for a flat fill.

    from bimforge.bim.section_style import classify, style_of
    classify("Compacted Fill")          # ('Compacted Fill', (0.80, 0.69, 0.46))
    style_of("IfcReinforcingBar/B1").dxf  # 'SOLID'
"""
from __future__ import annotations

import re
from typing import NamedTuple


class Kind(NamedTuple):
    kind: str
    pattern: str                 # regex on the lower-cased name, "_" -> " "
    rgb: tuple
    dxf: str                     # hatch pattern name ("SOLID": a solid fill)
    density: float               # x the pattern's nominal size
    paint: str                   # Blender procedural hatch


KINDS: list[Kind] = [
    # existing work to be removed reads apart from new work of any kind
    Kind("Existing (to remove)", r"to (be )?remove|\bdemo(lish|lition)?\b|"
         r"^existing \d", (0.86, 0.62, 0.55), "CONC_DEMOLITION", 1.0, "cross"),
    Kind("Reinforcing Steel", r"rebar|reinforc(ing|ement)|\brebr\b|\brein\b|ifcreinforcing",
         (0.75, 0.15, 0.12), "SOLID", 1.0, "solid"),
    Kind("Asphalt", r"asphalt|\bhma\b|\bac\b|bitum|\bpave(ment)?\b|\bpaving\b",
         (0.16, 0.16, 0.17), "ASPHALT", 1.0, "sand"),
    Kind("Gravel", r"gravel|aggregate|\bagg\b|\bab\b|base course|class 2|"
         r"\bbase\b|crushed|rock|riprap|\brsp\b|ballast|drain rock",
         (0.62, 0.55, 0.42), "GRAVEL", 0.8, "gravel"),
    Kind("Structural Steel", r"steel|\bstl\b|metal|\bmetl\b|girder|"
         r"ifcrailing|ifcmember|ifcplate", (0.55, 0.60, 0.66), "ANSI32", 1.0, "lines"),
    Kind("Timber", r"timber|wood|lagging", (0.55, 0.40, 0.24), "WOOD1", 1.0, "lines"),
    # cementitious fills before concrete: they ARE concrete by name
    Kind("Lean Concrete", r"lean concrete|\bcdf\b|controlled density|slurry|"
         r"flowable fill|backfill.lean", (0.90, 0.85, 0.62), "SACNCR", 1.5, "sand"),
    Kind("Concrete Backfill", r"concrete backfill|backfill.conc",
         (0.58, 0.64, 0.70), "AR-CONC", 0.5, "stipple"),
    # placed earth before native earth
    Kind("Compacted Fill", r"compacted|\bfill\b|(?<!concrete )backfill|embank|"
         r"refill|ifcearthworksfill", (0.80, 0.69, 0.46), "AR-SAND", 0.2, "sand"),
    Kind("Earthwork", r"earth|soil|excav|terrain|\bgrade\b|\bground\b|\bew\b|"
         r"ifcgeographic|ifcearthworks", (0.56, 0.44, 0.30), "EARTH", 2.5, "earth"),
    Kind("Concrete", r"concrete|\bconc\b|\bpcc\b|\bcip\b|precast|grout|"
         r"ifcslab|ifcwall|ifcfooting|ifcbeam|ifccolumn|ifcpile|deck|barrier|"
         r"headwall|culvert|abutment", (0.75, 0.73, 0.68), "CONCRETE1", 0.8, "stipple"),
]
UNSTYLED = ("Unstyled", (0.60, 0.60, 0.60))
#: rebar smaller than this on paper (inches) plots as a dot this size
MIN_DOT_IN = 0.04

_BY_NAME = {k.kind: k for k in KINDS}


def style_of(*names) -> Kind | None:
    """The first kind any of `names` matches (each name in turn)."""
    for name in names:
        # "_" and "-" read as spaces: a DXF / Blender layer ("Lean-Concrete",
        # "S-BACKFILL-LEAN") classifies as its name does
        low = re.sub(r"[_-]+", " ", (name or "").lower())
        for k in KINDS:
            if re.search(k.pattern, low):
                return k
    return None


def classify(*names) -> tuple[str, tuple] | None:
    """(kind, rgb) of the first kind any of `names` matches."""
    k = style_of(*names)
    return (k.kind, k.rgb) if k else None


def by_kind(kind: str) -> Kind | None:
    return _BY_NAME.get(kind)


def hatch_scale(kind: Kind, sheet_scale: float) -> float:
    """The DXF hatch scale for `kind` at 1" = `sheet_scale` drawing units."""
    return sheet_scale / 25.4 * kind.density
