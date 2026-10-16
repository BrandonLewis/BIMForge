"""Caltrans B9 structure-approach-slab section: a constant-thickness skewed RC
slab keyed by type (N/R/EQ). The type key encodes the slab length in feet
(`*_30` -> 30 ft, `*_10` -> 10 ft); the row carries the transcribed thickness,
design span, and bar schedule. Real agency dimensions live bid-side via
`params.tables_file` -- nothing bakes into the package (public-mirror gate).

    tables:
      type_n_30:
        length_ft: 30.0
        thickness_ft: 1.25
        design_span_ft: 24.5
        bars: {bottom_main: "#10@6", bottom_transverse: "#6@12",
               top_mat: "#5@18", edge_cont: {size: 5, count: 4}}
        dowels: {seat: "#5@12", seat_len_ft: 2.0,
                 diaphragm: "#5@9", diaphragm_len_ft: 2.667}
"""
from __future__ import annotations

import re

# Integer feet only: N/R/EQ approach-slab keys are all integer-foot lengths.
_LEN_FROM_KEY = re.compile(r"_(\d+)$")


def length_from_type_key(key: str) -> float:
    """Slab length (ft) encoded in a type key: `type_n_30` -> 30.0."""
    m = _LEN_FROM_KEY.search(str(key))
    if not m:
        raise ValueError(
            f"approach-slab type key {key!r} must end in _<length_ft>, "
            f"e.g. type_n_30 / type_eq_10")
    return float(m.group(1))


class ApproachSlabSection:
    """One transcribed approach-slab type row, keyed by type name."""

    def __init__(self, type_key: str, table: dict) -> None:
        if type_key not in table:
            raise ValueError(
                f"no approach-slab table row for {type_key!r} "
                f"(have {sorted(table)})")
        row = table[type_key]
        if "length_ft" not in row or "thickness_ft" not in row:
            raise ValueError(
                f"{type_key}: length_ft and thickness_ft are required")
        self.type_key = type_key
        # Parse the key-encoded length now (fail loud at construction) and
        # memoize it, so key_length_ft can't raise later inside a model.checks
        # closure -- gate.run_pre does not catch check exceptions.
        self._key_length_ft = length_from_type_key(type_key)
        self.length_ft = float(row["length_ft"])
        self.thickness_ft = float(row["thickness_ft"])
        self.design_span_ft = float(row.get("design_span_ft", 0.0))
        if self.length_ft <= 0.0 or self.thickness_ft <= 0.0:
            raise ValueError(
                f"{type_key}: length_ft and thickness_ft must be positive")
        self.bars = dict(row.get("bars") or {})
        if not self.bars:
            raise ValueError(
                f"{type_key}: bar schedule 'bars' is required and non-empty")
        self.dowels = dict(row.get("dowels") or {})

    @property
    def key_length_ft(self) -> float:
        """Length encoded in the type key (independent of the row's length_ft
        -- the two are cross-checked by the family's gate check). Parsed and
        validated at construction, so this never raises."""
        return self._key_length_ft
