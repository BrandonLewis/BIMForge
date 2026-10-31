"""Build the Blender alignment-section add-on zip.

Examples:
    python -m bimforge.blender
    python -m bimforge.blender --out dist/bimforge_alignment_section.zip
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from bimforge.blender import ADDON, build_addon


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m bimforge.blender",
                                 description=__doc__.splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(f"{ADDON}.zip"),
                    help="zip to write (default: ./%(default)s)")
    args = ap.parse_args(argv)
    out = build_addon(args.out)
    print(f"wrote {out} — install it in Blender: Edit > Preferences > "
          f"Add-ons > Install from Disk", file=sys.stderr)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
