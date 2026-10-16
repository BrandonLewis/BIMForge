"""IFC -> CanonicalTakeoff: group elements by cost code, sum pay quantities.

Reads ANY IFC conforming to the takeoff contract (classification references
keyed by pay code + Qto quantities in the file's DECLARED units, scaled to
SI here per issue #109 — the full contract, with the recognized quantity
names and a producer checklist, is documented in
docs/ifc-takeoff-contract.md; `bimforge.bim.dxf2bim` is one
producer, not the only one), groups elements by their classification code,
sums the chosen pay quantity, converts SI -> the commercial pay unit, and
emits the open CanonicalTakeoff shape
(`estimating_tools.takeoff.model.CanonicalTakeoff`):

    {organization_id, project_ref, rows: [...]}

A quantity row is:
    {description, kind: "quantity", quantity, unit, item_number?, cost_code?, schedule?,
     elements: [...]}

`elements` is the per-element breakdown behind the summed quantity — one entry
per IFC element with a section_type derived from the IFC class/predefined type
(and the source layer name dxf2bim embeds in the element name, for wing walls)
plus length/width/height in FEET recovered from the Qto quantities (null where
not derivable). It feeds the estimate-structures push plan
(`estimating_tools.takeoff.push`), where each element becomes a structure
section.

Pay quantity & unit per cost code come from an optional takeoff map (see
`bimforge/bim/examples/takeoff_map.example.yaml`). Without one, each
code falls back to its natural SI measure (count->EA, volume->M3, area->M2,
linear->M). The map is where you assign commercial pay units
(CY / SF / SY / LF / EA), item numbers, and schedules.
"""
from __future__ import annotations

import csv
import sys
from collections import defaultdict
from typing import Optional

import ifcopenshell
import ifcopenshell.util.element as ue
import ifcopenshell.util.unit as unit_util

# ----------------------------------------------------------------------------
# Measure -> physical dimension, and SI -> pay-unit conversion
# ----------------------------------------------------------------------------
MEASURE_DIM = {
    "GrossArea": "area", "NetArea": "area",
    "GrossVolume": "volume", "NetVolume": "volume",
    "Length": "length", "Perimeter": "length", "Width": "length", "Height": "length",
    "Count": "count",
    # weight-paid metal (issue #108): rebar and fabricated steel pay by
    # LB/CWT/TON off IfcQuantityWeight. Deliberately NOT in pick_measure's
    # natural-preference order — weight is opt-in via a declared measure.
    # Plain "Weight" is Qto_ReinforcingElementBaseQuantities' name for it
    # (the naming exception; plates/beams use Gross/NetWeight).
    "GrossWeight": "mass", "NetWeight": "mass", "Weight": "mass",
}

# factor to multiply the SI value (m2 / m3 / m / kg / each) by, per pay unit
CONVERT = {
    "area":   {"M2": 1.0, "SM": 1.0, "SF": 10.76391041671, "SY": 1.19599004630},
    "volume": {"M3": 1.0, "CM": 1.0, "CY": 1.30795061931, "CF": 35.3146667215},
    "length": {"M": 1.0, "LM": 1.0, "LF": 3.28083989501, "FT": 3.28083989501,
               "YD": 1.09361329834},
    "count":  {"EA": 1.0, "EACH": 1.0, "LS": 1.0},
    "mass":   {"KG": 1.0, "LB": 2.20462262185, "LBS": 2.20462262185,
               "CWT": 0.0220462262185,          # US hundredweight, 100 lb
               "TON": 0.00110231131092},        # US short ton, 2000 lb
}

# natural default unit when no map entry exists
DEFAULT_UNIT = {"area": "M2", "volume": "M3", "length": "M", "count": "EA",
                "mass": "KG"}

M_TO_FT = 3.28083989501

# IFC class -> BidSheet.ai concrete_section_type (Structures grid).
# IfcSlab covers the FLOOR (deck) case dxf2bim authors; wing walls are split
# off IfcWall by name below.
_SECTION_TYPE = {
    "IfcSlab": "decks",
    "IfcWall": "walls",
    "IfcFooting": "footing",
    "IfcPile": "pile",
}


def section_type_of(element) -> str:
    """BidSheet.ai section type for an IFC element.

    dxf2bim embeds the source DXF layer in the element name
    (`<layer>-<handle>`; count elements carry the block name), and no separate
    layer attribute survives into the IFC — so wall elements whose name/layer
    suggests a wing wall are matched on the name. Everything else falls back
    to the IFC class mapping, then to the lowercased class name.
    """
    cls = element.is_a()
    if cls == "IfcWall" and "wing" in (element.Name or "").lower():
        return "wing_wall"
    return _SECTION_TYPE.get(cls, cls[3:].lower() if cls.startswith("Ifc") else cls.lower())


def _ft(qtys: dict[str, float], name: str) -> Optional[float]:
    """A Qto length quantity (SI metres) in feet, or None when not derivable."""
    if name not in qtys:
        return None
    return round(qtys[name] * M_TO_FT, 4)


def element_entry(element, qtys: dict[str, float], measure: str | None) -> dict:
    """One CanonicalTakeoff row `elements` entry for an IFC element.

    `measure` is the Qto name the row summed for this element; `value_si` is
    that quantity in SI — the audit compares element-level values in SI, so
    no unit table is needed downstream.
    """
    value_si = qtys.get(measure) if measure else None
    entry = {
        "name": element.Name or f"{element.is_a()}-{element.GlobalId[:6]}",
        "global_id": element.GlobalId,
        "section_type": section_type_of(element),
        "count": int(qtys.get("Count", 1)) or 1,
        "length_ft": _ft(qtys, "Length"),
        "width_ft": _ft(qtys, "Width"),
        "height_ft": _ft(qtys, "Height"),
        "measure": measure,
        "value_si": value_si,
    }
    # A volume element carries its cubic yards directly, so the estimate-
    # structures planner need not recover a full L×W×H box from the Qto — it
    # usually can't (a swept solid records only its GrossVolume + a height).
    # value_si is SI (m³); the CONVERT volume table takes it to CY (issue #210).
    if value_si is not None and MEASURE_DIM.get(measure) == "volume":
        entry["cy"] = round(convert(value_si, "volume", "CY"), 4)
    return entry


def convert(value: float, dim: str, unit: str) -> float:
    table = CONVERT.get(dim, {})
    if unit.upper() not in table:
        raise ValueError(f"unit '{unit}' is not valid for a {dim} quantity "
                         f"(choices: {sorted(table)})")
    return value * table[unit.upper()]


# ----------------------------------------------------------------------------
# Read IFC
# ----------------------------------------------------------------------------
def classifications_of(element) -> list[dict]:
    """EVERY {system, code, name} classification on the element, in
    association order. IFC permits more than one, and heavy-civil pay
    structures require it — furnish by the foot AND drive by the each off
    one physical pile (issue #106). Truncating to the first silently drops
    pay items."""
    out = []
    for rel in getattr(element, "HasAssociations", []) or []:
        if not rel.is_a("IfcRelAssociatesClassification"):
            continue
        ref = rel.RelatingClassification
        if not (ref and ref.is_a("IfcClassificationReference")):
            continue
        src = ref.ReferencedSource
        system = None
        if src and (src.is_a("IfcClassification")
                    or src.is_a("IfcClassificationReference")):
            system = src.Name
        out.append({"system": system,
                    "code": ref.Identification or "",
                    "name": ref.Name or ""})
    return out


def classification_of(element) -> Optional[dict]:
    """The FIRST classification only — kept for single-code callers; anything
    keying pay items must use classifications_of()."""
    got = classifications_of(element)
    return got[0] if got else None


def _mass_scale(model) -> float:
    """Native mass -> KILOGRAMS. IFC's SI mass unit is the GRAM (kg is the
    KILO prefix), so ifcopenshell's prefix-based scale is gram-based and
    returns 1 for both "GRAM declared" and "no MASSUNIT at all" — the two
    need opposite handling (grams: ÷1000; undeclared: assume kg). Detect
    the declaration ourselves (issue #108's grams caveat)."""
    projects = model.by_type("IfcProject")
    units = projects[0].UnitsInContext if projects else None
    declared = any(getattr(u, "UnitType", None) == "MASSUNIT"
                   for u in (units.Units if units else []))
    if not declared:
        return 1.0
    return unit_util.calculate_unit_scale(model, "MASSUNIT") / 1000.0


def _unit_scales(model) -> dict[str, float]:
    """Per-dimension multipliers taking the file's NATIVE Qto values to SI
    base (m / m² / m³ / kg). Foreign files commonly declare millimetre
    lengths and gram masses (issue #109) — raw values must never be assumed
    SI. Missing declarations scale by 1."""
    s = unit_util.calculate_unit_scale(model)                  # LENGTHUNIT
    return {"length": s, "area": s * s, "volume": s ** 3,
            "mass": _mass_scale(model), "count": 1.0}


def quantities_of(element, scales: dict | None = None) -> dict[str, float]:
    """Flatten all Qto sets into {quantity_name: value}.

    Pass the model's `_unit_scales()` dict as `scales` to get SI base
    values: quantity names with a known dimension (MEASURE_DIM) are scaled
    from the file's declared units, unknown names pass through raw (they
    are unmappable anyway). With `scales=None` (the default) values come
    back NATIVE/unscaled — only for callers that guarantee an SI-authored
    file."""
    flat: dict[str, float] = {}
    for qset in ue.get_psets(element, qtos_only=True).values():
        for k, v in qset.items():
            if k == "id":
                continue
            if isinstance(v, (int, float)):
                factor = (scales or {}).get(MEASURE_DIM.get(k), 1.0)
                flat[k] = float(v) * factor
    return flat


def ifc_leg(ifc_path: str) -> dict:
    """The audit's IFC leg: {GlobalId: {name, ifc_class, qtys}} for every
    IfcElement, qtys in SI (the same quantities_of + unit scaling the
    takeoff itself sums — audit and takeoff read the model identically by
    construction)."""
    model = ifcopenshell.open(ifc_path)
    scales = _unit_scales(model)
    return {el.GlobalId: {
                "name": el.Name or f"{el.is_a()}-{el.GlobalId[:6]}",
                "ifc_class": el.is_a(),
                "qtys": quantities_of(el, scales)}
            for el in model.by_type("IfcElement")}


# ----------------------------------------------------------------------------
# Build the CanonicalTakeoff
# ----------------------------------------------------------------------------
def pick_measure(qtys: dict[str, float], preferred: Optional[str]) -> Optional[str]:
    if preferred and preferred in qtys:
        return preferred
    # natural preference order: count, then volume, then area, then length
    for name in ("Count", "GrossVolume", "NetVolume", "GrossArea", "NetArea",
                 "Length"):
        if name in qtys:
            return name
    return None


def measure_entries(code: str, cfg: dict):
    """The code's explicit `measures:` entries, or None for the singular path.

    Explicit entries are validated up front (fail loud, before any element
    is read): a non-empty list of dicts, each naming a known measure.
    """
    if "measures" not in cfg:
        return None
    if "measure" in cfg:
        raise ValueError(f"code {code}: use either 'measure' or 'measures', "
                         f"not both")
    entries = cfg["measures"]
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"code {code}: 'measures' must be a non-empty list")
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict) or not entry.get("measure"):
            raise ValueError(f"code {code}: measures[{i}] must set 'measure'")
        if entry["measure"] not in MEASURE_DIM:
            raise ValueError(f"code {code}: unknown measure "
                             f"'{entry['measure']}' (choices: {sorted(MEASURE_DIM)})")
    return entries


def normalize_map(tmap: dict):
    """Validate the takeoff map and return (codes_cfg, defaults, entries_by_code).

    Shared by build_takeoff and estimate5d — the two consumers of the map
    must accept and reject exactly the same files. entries_by_code maps each
    code to its explicit `measures:` list, or None on the singular path.
    Raises ValueError on: non-mapping codes/entries, unknown singular
    measure, and everything measure_entries rejects.
    """
    codes_cfg = tmap.get("codes", {}) or {}
    if not isinstance(codes_cfg, dict):
        raise ValueError(f"takeoff map: 'codes' must be a mapping of code -> "
                         f"config, got {type(codes_cfg).__name__}")
    for code, cfg in codes_cfg.items():
        if cfg is not None and not isinstance(cfg, dict):
            raise ValueError(f"code {code}: map entry must be a mapping "
                             f"(measure/unit/item_number/...), got "
                             f"{type(cfg).__name__}")
        # the singular path must fail as loudly as measure_entries does for
        # the plural one — never a bare KeyError or a silent natural-measure
        # fallback on a typo'd measure (issue #108)
        m = (cfg or {}).get("measure")
        if m is not None and m not in MEASURE_DIM:
            raise ValueError(f"code {code}: unknown measure {m!r} "
                             f"(choices: {sorted(MEASURE_DIM)})")
    defaults = tmap.get("defaults", {}) or {}
    entries_by_code = {code: measure_entries(code, cfg or {})
                       for code, cfg in codes_cfg.items()}
    return codes_cfg, defaults, entries_by_code


def build_takeoff(ifc_path: str, tmap: dict) -> tuple[dict, list[str]]:
    """Return (CanonicalTakeoff dict, review warnings).

    The dict is the exact shape `CanonicalTakeoff.from_json` loads:
    `organization_id` (the BidSheet.ai org id — an integer; 0 when the map
    doesn't set one), optional `project_ref`, and quantity `rows`.

    A map code with `measures:` (plural) emits one row per entry — the same
    elements pay multiple bid items (e.g. CISS piling furnished by Length
    and driven by Count). Explicit entries are strict: only the named
    measure is summed, and an element lacking it is warned and skipped from
    that row only. The singular `measure:` path keeps its natural-preference
    fallback (`pick_measure`) unchanged.
    """
    return _build_takeoff(ifcopenshell.open(ifc_path), tmap)


def _build_takeoff(model, tmap: dict) -> tuple[dict, list[str]]:
    scales = _unit_scales(model)
    codes_cfg, defaults, entries_by_code = normalize_map(tmap)

    # accumulate per (code, entry index) -> running total in SI + metadata
    # (index 0 is the only entry on the singular path)
    acc: dict[tuple, dict] = defaultdict(lambda: {
        "si_total": 0.0, "dim": None, "description": "", "system": None,
        "measure": None, "n": 0, "elements": []})
    warnings: list[str] = []
    unclassified = 0

    # issue #106 addendum: downstream layers (estimate-spec apply, the audit,
    # BM push) key rows on (schedule, item_number). Two codes sharing one
    # under DIFFERENT measures/units collide there (2 EA + 416.75 LBS ->
    # 418.75 EA in the reporter's consumer); same measure+unit is a
    # legitimate rollup and stays silent.
    by_item: dict[tuple, list] = defaultdict(list)
    for code, cfg in codes_cfg.items():
        cfg = cfg or {}
        ents = entries_by_code.get(code) or [cfg]
        for e in ents:
            item_number = str(e.get("item_number", "") or "")
            if not item_number:
                continue
            sched = e.get("schedule", cfg.get("schedule",
                                              defaults.get("schedule")))
            by_item[(sched, item_number)].append(
                (code, e.get("measure") or cfg.get("measure"),
                 e.get("unit") or cfg.get("unit")))
    for (_sched, item_number), owners in sorted(by_item.items()):
        if len({(m, u) for _, m, u in owners}) > 1:
            codes_str = ", ".join(sorted({c for c, _, _ in owners}))
            warnings.append(f"codes {codes_str} share item_number "
                            f"{item_number} but differ in measure/unit — "
                            f"downstream layers keying on the item number "
                            f"will collide (see issue #106)")

    for el in model.by_type("IfcElement"):
        # EVERY classification participates (issue #106) — furnish-and-drive
        # piling pays two codes off one element, each summing its own
        # measure. Deduped so the same code associated twice counts once.
        clss = []
        seen_codes: set[str] = set()
        for c in classifications_of(el):
            if c["code"] and c["code"] not in seen_codes:
                seen_codes.add(c["code"])
                clss.append(c)
        qtys = quantities_of(el, scales)
        if not clss:
            unclassified += 1
            continue
        for cls in clss:
            code = cls["code"]
            cfg = codes_cfg.get(code, {}) or {}
            entries = entries_by_code.get(code)
            if entries is None:
                measure = pick_measure(qtys, cfg.get("measure"))
                if measure is None:
                    warnings.append(f"{el.is_a()} '{el.Name}' (code {code}) "
                                    f"has no usable quantity — skipped")
                    continue
                dim = MEASURE_DIM[measure]
                a = acc[(code, 0)]
                if a["dim"] and a["dim"] != dim:
                    warnings.append(f"code {code}: mixing {a['dim']} and "
                                    f"{dim} measures — check the map")
                a["si_total"] += qtys[measure]
                a["dim"] = dim
                a["measure"] = measure
                a["system"] = cls["system"]
                a["description"] = a["description"] or cls["name"] or code
                a["n"] += 1
                a["elements"].append(element_entry(el, qtys, measure))
                continue
            for i, entry in enumerate(entries):
                measure = entry["measure"]
                if measure not in qtys:
                    warnings.append(f"{el.is_a()} '{el.Name}' (code {code}) "
                                    f"lacks {measure} — skipped from that row")
                    continue
                a = acc[(code, i)]
                a["si_total"] += qtys[measure]
                a["dim"] = MEASURE_DIM[measure]
                a["measure"] = measure
                a["system"] = cls["system"]
                a["description"] = (a["description"]
                                    or entry.get("description")
                                    or cls["name"] or code)
                a["n"] += 1
                a["elements"].append(element_entry(el, qtys, measure))

    if unclassified:
        warnings.append(f"{unclassified} element(s) had no classification code — "
                        f"add one in the layer map to include them")

    rows = []
    for (code, idx), a in sorted(acc.items()):
        cfg = codes_cfg.get(code, {}) or {}
        entries = entries_by_code.get(code)
        entry = entries[idx] if entries else cfg
        unit = entry.get("unit") or DEFAULT_UNIT[a["dim"]]
        if code not in codes_cfg:
            warnings.append(f"code {code}: no map entry — used natural unit "
                            f"'{unit}' and no item number")
        qty = round(convert(a["si_total"], a["dim"], unit), 4)
        rows.append({
            "description": a["description"],
            "kind": "quantity",
            "quantity": qty,
            "unit": unit,
            "item_number": str(entry.get("item_number", "")) or None,
            "cost_code": code,
            "schedule": entry.get("schedule",
                                  cfg.get("schedule", defaults.get("schedule"))),
            "elements": a["elements"],
        })

    # a declared code with no rows is a silent pay-item gap — the exact
    # failure mode of issue #106; make it a review line, never silence
    produced = {r["cost_code"] for r in rows}
    for code in codes_cfg:
        if code not in produced:
            warnings.append(f"code {code}: declared in the takeoff map but "
                            f"produced no rows — no classified element "
                            f"carries it (or none had a usable quantity)")

    takeoff = {
        # CanonicalTakeoff.organization_id is the integer BidSheet.ai org id;
        # default to 0 (placeholder) rather than a string so the JSON always
        # loads into the takeoff model.
        "organization_id": tmap.get("organization_id", 0),
        "project_ref": tmap.get("project_ref"),
        "rows": rows,
    }
    return takeoff, warnings


def takeoff_by_task(ifc_path: str, tmap: dict, schedule=None
                    ) -> tuple[dict, list[str]]:
    """`build_takeoff`, with each row split across the schedule's tasks (#335).

    Every row gains `tasks` ({task id: quantity in the row's unit}) and
    `unassigned` (the quantity no task claims), with
    `sum(tasks.values()) + unassigned == quantity` to the row's rounding.
    A pile item thus splits between its stage 1 and stage 2 piling tasks.

    Only a constructive task claims an element — type CONSTRUCTION,
    INSTALLATION, NOTDEFINED or none (`schedule_read.CONSTRUCTIVE_TYPES`);
    a removal or demolition task never takes the quantity of what it
    removes. An element two constructive tasks link to goes to the
    earliest-starting one (schedule order breaks a tie), with a warning.

    `schedule` is a CanonicalSchedule whose task ids match the IFC's (a
    consumer's re-plan of what `read_schedule` returned); None reads the
    IFC's only work schedule. Links in both directions count
    (`schedule_read.task_elements`).
    """
    from bimforge.bim.schedule_read import (
        CONSTRUCTIVE_TYPES, read_schedule, schedule_links)

    model = ifcopenshell.open(ifc_path)
    takeoff, warnings = _build_takeoff(model, tmap)
    if schedule is None:
        schedule = read_schedule(model)
    links = schedule_links(model, schedule)

    order = {t.id: i for i, t in enumerate(schedule.tasks)}
    candidates: dict[str, list] = defaultdict(list)
    for t in schedule.tasks:
        if (t.task_type or "NOTDEFINED").upper() not in CONSTRUCTIVE_TYPES:
            continue
        for link in links.get(t.id, []):
            if t not in candidates[link["global_id"]]:
                candidates[link["global_id"]].append(t)
    claim: dict[str, str] = {}
    for gid, tasks in candidates.items():
        tasks.sort(key=lambda t: (t.start is None, t.start or "", order[t.id]))
        claim[gid] = tasks[0].id
        if len(tasks) > 1:
            warnings.append(
                f"element {gid} is linked to {len(tasks)} construction tasks "
                f"({', '.join(t.id for t in tasks)}) — claimed by the "
                f"earliest-starting, {tasks[0].id}")

    for row in takeoff["rows"]:
        unit = row["unit"]
        split: dict[str, float] = defaultdict(float)
        for el in row["elements"]:
            owner = claim.get(el["global_id"])
            if owner is not None and el["value_si"] is not None:
                split[owner] += convert(el["value_si"],
                                        MEASURE_DIM[el["measure"]], unit)
        row["tasks"], row["unassigned"] = _apportion(
            row["quantity"],
            sorted(split.items(), key=lambda kv: order[kv[0]]))
    return takeoff, warnings


def _apportion(quantity: float, shares: list[tuple[str, float]]
               ) -> tuple[dict[str, float], float]:
    """Round task shares to the row's 4 decimals so they and `unassigned`
    sum to `quantity` exactly, with `unassigned` never negative.

    Rounding each share on its own does not: two 0.00006 shares of a
    0.0001 row both round up, leaving -0.0001 unassigned. Work in
    ten-thousandths: the claimed total is rounded once (and capped at the
    row), each share takes its floor, and the units left over go to the
    largest remainders (schedule order breaks a tie).
    """
    total = round(quantity * 10_000)
    exact = [(tid, q * 10_000) for tid, q in shares]
    claimed = min(total, round(sum(q for _, q in exact)))
    units = {tid: int(q // 1) for tid, q in exact}
    # floors <= claimed: they sum below the exact total, which rounds to
    # at least their (integer) sum, and the row was rounded from that total
    spare = claimed - sum(units.values())
    by_remainder = sorted(range(len(exact)),
                          key=lambda i: -(exact[i][1] - units[exact[i][0]]))
    for i in by_remainder[:spare]:
        units[exact[i][0]] += 1
    tasks = {tid: round(u / 10_000, 4) for tid, u in units.items()}
    return tasks, round((total - sum(units.values())) / 10_000, 4)


# ----------------------------------------------------------------------------
# Output
# ----------------------------------------------------------------------------
def print_summary(takeoff: dict):
    rows = takeoff["rows"]
    print(f"\nCanonicalTakeoff — {len(rows)} bid-item rows "
          f"(org={takeoff['organization_id'] or '<unset>'}, "
          f"project={takeoff['project_ref'] or '<unset>'})\n")
    hdr = f"{'Item':6} {'Cost code':12} {'Description':26} {'Qty':>12} {'Unit':5} {'Sched':6}"
    print(hdr)
    print("-" * len(hdr))
    for r in rows:
        print(f"{(r['item_number'] or '-'):6} {r['cost_code']:12} "
              f"{r['description'][:26]:26} {r['quantity']:>12,.2f} {r['unit']:5} "
              f"{str(r['schedule'] or '-'):6}")
    print()


def write_csv(takeoff: dict, csv_path: str):
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["item_number", "cost_code",
                           "description", "quantity", "unit", "schedule"])
        w.writeheader()
        for r in takeoff["rows"]:
            w.writerow({k: r.get(k) for k in w.fieldnames})


def print_warnings(warnings: list[str]):
    if warnings:
        print("\nReview:", file=sys.stderr)
        for wmsg in warnings:
            print(f"  ! {wmsg}", file=sys.stderr)
