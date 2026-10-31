"""Blender add-ons that ship with bimforge.

`alignment_section` — a station slider that cuts a section along an IFC
alignment (View3D > Sidebar > Section). Blender installs an add-on from a
zip, and the add-on must carry the stationing module it uses (Bonsai's
Python has ifcopenshell but not bimforge), so :func:`build_addon` zips the
add-on together with its own copy of bimforge.bim.alignment_station.

Examples:
    python -m bimforge.blender                      # -> ./bimforge_alignment_section.zip
    python -m bimforge.blender --out dist/section.zip
    # Blender: Edit > Preferences > Add-ons > Install from Disk... > the zip
"""
from __future__ import annotations

import zipfile
from pathlib import Path

ADDON = "bimforge_alignment_section"


def build_addon(out: str | Path) -> Path:
    """Write the installable add-on zip to `out`; returns the path."""
    here = Path(__file__).resolve().parent
    src = here / "alignment_section" / "__init__.py"
    station = here.parent / "bim" / "alignment_station.py"
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(src, f"{ADDON}/__init__.py")
        z.write(station, f"{ADDON}/alignment_station.py")
    return out
