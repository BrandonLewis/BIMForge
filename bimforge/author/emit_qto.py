"""QTO workbook emitter: Summary (per pay code) + Elements (every product),
from the MODEL's analytic quantities — the emitted IFC is verified separately
by the gate; this workbook is the estimator-facing reconciliation surface.

openpyxl is NOT a bimforge dependency: lazy import, friendly error.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

#: pinned docProps created/modified timestamps — openpyxl otherwise stamps
#: wall-clock time, which breaks byte-determinism for a rebuild of an
#: unchanged model/paycodes at a different time (mirrors emit_ifc's
#: BUILD_STAMP / emit_step's STEP_BUILD_STAMP).
QTO_BUILD_STAMP = datetime(2026, 8, 15, 12, 0, 0)

#: measure -> (element quantity key, SI->pay-unit is NOT applied here: the
#: workbook stays in the model's own feet/pounds domain).
_MEASURE_KEY = {"GrossVolume": "volume_cf", "GrossArea": "area_sf",
                "Length": "length_ft", "Count": "count",
                "GrossWeight": "weight_lb"}
_UNIT_FACTOR = {("volume_cf", "CY"): 1 / 27.0, ("volume_cf", "CF"): 1.0,
                ("area_sf", "SF"): 1.0, ("area_sf", "SY"): 1 / 9.0,
                ("length_ft", "LF"): 1.0, ("count", "EA"): 1.0,
                ("weight_lb", "LBS"): 1.0, ("weight_lb", "TON"): 1 / 2000.0}


def emit_qto(model, path, paycodes) -> str:
    try:
        from openpyxl import Workbook
    except ImportError:
        raise RuntimeError(
            "emit_qto needs openpyxl, which bimforge does not bundle: "
            "pip install openpyxl") from None
    wb = Workbook()
    wb.properties.created = wb.properties.modified = QTO_BUILD_STAMP
    ws = wb.active
    ws.title = "Summary"
    ws.append(["Pay code", "Description", "Measure", "Modelled", "Unit"])
    for code in model.codes_used():
        cfg = paycodes.codes[code]
        key = _MEASURE_KEY.get(cfg["measure"])
        total = model.total(code, key) if key else 0.0
        factor = _UNIT_FACTOR.get((key, cfg["unit"].upper()), 1.0)
        ws.append([code, cfg.get("description", ""), cfg["measure"],
                   round(total * factor, 4), cfg["unit"]])
    we = wb.create_sheet("Elements")
    we.append(["Element", "IFC class", "Codes", "Count", "Volume CF",
               "Weight LB", "Area SF", "Length FT"])
    for el in model.elements:
        q = el.quantities
        we.append([el.name, el.ifc_class, ", ".join(el.classifications) or
                   "(reference)", q.get("count", 1), q.get("volume_cf"),
                   el.weight_lb, q.get("area_sf"), q.get("length_ft")])
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return f"QTO workbook written to {path}"
