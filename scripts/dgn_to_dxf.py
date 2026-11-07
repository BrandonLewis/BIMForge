#!/usr/bin/env python3
"""Batch-convert Caltrans DGN (MicroStation V8) to DXF.

The free ODA File Converter only reads DWG/DXF, NOT DGN. So conversion is a
two-stage chain:

    1. DGN -> DWG   via the ODA Toolkit sample ``ExDgnImport`` (per file). The
       sample prints "Press ENTER to continue..." and blocks on stdin, so we
       feed it a newline. It also needs its own DLL directory on PATH.
    2. DWG -> DXF   via ``ODAFileConverter`` (batch; it handles DWG<->DXF fine).

    python scripts/dgn_to_dxf.py                         # data/caltrans-2025/{dgn->dxf}
    python scripts/dgn_to_dxf.py --filter "2025__b03*.dgn"   # just the B3 sheets
    python scripts/dgn_to_dxf.py --dry-run

ExDgnImport ships with the ODA Toolkit, which has no standard install
location: pass ``--dgn-importer`` or set ``ODA_DGN_IMPORTER``.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

DEFAULT_ODA = r"C:\Program Files\ODA\ODAFileConverter 27.1.0\ODAFileConverter.exe"
DEFAULT_DGN_IMPORTER = os.environ.get("ODA_DGN_IMPORTER", "")
DEFAULT_IN = Path("data/caltrans-2025/dgn")
DEFAULT_OUT = Path("data/caltrans-2025/dxf")


def exdgnimport_command(exe: str, src_dgn: str | Path,
                        dst_dwg: str | Path) -> list[str]:
    """The ExDgnImport argv for a single DGN->DWG import."""
    return [exe, str(src_dgn), str(dst_dwg)]


def oda_command(exe: str, in_dir: str | Path, out_dir: str | Path,
                dwg_filter: str = "*.DWG") -> list[str]:
    """The ODA File Converter argv for a DWG->DXF (ACAD2018) batch."""
    return [exe, str(in_dir), str(out_dir), "ACAD2018", "DXF", "0", "1",
            dwg_filter]


def _dgn_to_dwg(importer: str, src_dgn: Path, dst_dwg: Path) -> None:
    """Run one ExDgnImport, feeding the newline its "Press ENTER" prompt wants.
    ExDgnImport needs its own directory on PATH so its ODA DLLs resolve."""
    env = dict(os.environ)
    env["PATH"] = str(Path(importer).parent) + os.pathsep + env.get("PATH", "")
    subprocess.run(exdgnimport_command(importer, src_dgn, dst_dwg),
                   input=b"\n", env=env)


def convert(oda_exe: str, importer: str, in_dir: Path, out_dir: Path,
            dgn_filter: str, dry_run: bool) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    dgns = sorted(in_dir.glob(dgn_filter))
    print(f"stage 1 (ExDgnImport): {len(dgns)} DGN -> DWG  [{importer}]")
    print(f"stage 2 (ODAFileConverter): DWG -> DXF -> {out_dir}  [{oda_exe}]")
    if dry_run:
        for d in dgns:
            print(f"  {d.name}")
        return 0
    if not importer:
        # Path("") is the current directory, which exists
        print("no ExDgnImport: pass --dgn-importer or set ODA_DGN_IMPORTER",
              file=sys.stderr)
        return 2
    for exe in (importer, oda_exe):
        if not Path(exe).exists():
            print(f"converter not found: {exe}", file=sys.stderr)
            return 2
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        for d in dgns:
            _dgn_to_dwg(importer, d, tmp_dir / (d.stem + ".dwg"))
        made_dwg = len(list(tmp_dir.glob("*.dwg")))
        print(f"  {made_dwg}/{len(dgns)} DWG produced")
        subprocess.run(oda_command(oda_exe, tmp_dir, out_dir))
    n = len(list(out_dir.glob("*.dxf")))
    print(f"{n} DXF in {out_dir}")
    return 0 if n else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--oda", default=DEFAULT_ODA, help="ODAFileConverter.exe")
    ap.add_argument("--dgn-importer", default=DEFAULT_DGN_IMPORTER,
                    help="ODA Toolkit ExDgnImport.exe")
    ap.add_argument("--in-dir", type=Path, default=DEFAULT_IN)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--filter", dest="dgn_filter", default="*.dgn",
                    help="glob over --in-dir (e.g. '2025__b03*.dgn')")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    return convert(a.oda, a.dgn_importer, a.in_dir, a.out_dir,
                   a.dgn_filter, a.dry_run)


if __name__ == "__main__":
    raise SystemExit(main())
