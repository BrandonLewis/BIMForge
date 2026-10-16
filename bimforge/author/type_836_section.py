"""Caltrans Type 836 / Type-C barrier cross-section (B11-80). The single
construction point for the 836 BarrierSection, built from a d90.type_c_barrier
row (explicit `profile` or parametric dims). Per-row dims flow straight into
BarrierSection, so a Mod item (an altered sheet dimension) is a per-row override.
The 836 barrier is swept along a 3D rail in `culvert_headwall` (path-swept, not a
straight run); this module owns only its section, the layer 836 shares with the
straight-run barrier families (732sw/842)."""
from __future__ import annotations

from bimforge.author.barrier_section import BarrierSection


def type_836_section(row: dict) -> BarrierSection:
    if not row.get("shape"):
        raise ValueError("Type 836 barrier section requires 'shape' "
                         "(supply a d90.type_c_barrier with shape + profile/dims)")
    bt = str(row.get("barrier_type", "836"))
    # treat an explicit None (e.g. `h_ft: null` in yaml) as absent so height_ft
    # still serves as the fallback -- dict.get short-circuits only on a MISSING
    # key, not a present-but-None value.
    h = row.get("h_ft")
    if h is None:
        h = row.get("height_ft")
    hkey = str(h)
    return BarrierSection(bt, hkey, {"barriers": {bt: {
        "shape": row["shape"], "variants": {hkey: row}}}})
