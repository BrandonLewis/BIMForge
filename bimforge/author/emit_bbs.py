"""Bar-bending schedule (BBS) xlsx from a model's IfcReinforcingBar elements.
openpyxl is NOT a bimforge dependency: lazy import, friendly error (mirrors
emit_qto)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

#: pinned docProps created/modified timestamp -- openpyxl otherwise stamps
#: wall-clock time, breaking byte-determinism for a rebuild of an unchanged
#: model at a different time (mirrors emit_qto's QTO_BUILD_STAMP).
BBS_BUILD_STAMP = datetime(2026, 8, 15, 12, 0, 0)


def emit_bbs(model, path: str) -> str:
    try:
        from openpyxl import Workbook
    except ImportError:
        raise RuntimeError(
            "emit_bbs needs openpyxl, which bimforge does not bundle: "
            "pip install openpyxl") from None
    wb = Workbook()
    wb.properties.created = wb.properties.modified = BBS_BUILD_STAMP
    ws = wb.active
    ws.title = "Bar Schedule"
    ws.append(["Mark", "Size", "Count", "Length (ft)", "Weight (lb)"])
    total = 0.0
    for el in model.elements:
        if el.ifc_class != "IfcReinforcingBar":
            continue
        q = el.quantities
        w = q.get("weight_lb", 0.0)
        total += w
        ws.append([el.name, el.description or "", q.get("count"),
                   q.get("length_ft"), w])
    ws.append(["TOTAL", "", "", "", total])
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    wb.save(str(p))
    return f"BBS written to {p}"
