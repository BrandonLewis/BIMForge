"""IFC -> BidSheet.ai modelled elements (the import half of the IFC round trip).

`plan_modelled_elements` turns an IFC's elements into the `elements` payload
BidSheet.ai's `upsert_modelled_elements` MCP tool takes (BidSheet.ai #1486
slice 6; the contract is its spec 2026-10-17-ifc-round-trip-design.md):

    {"global_id": "<22-char IFC GlobalId>", "name": ..., "ifc_class": ...,
     "element_type": ..., "structure_id"?: ...,
     "quantities": {key: {"value": n, "unit": "CY",
                          "source": "Qto_FootingBaseQuantities.NetVolume"}},
     "pay_items"?: {key: estimate item id}}

BidSheet.ai never parses IFC, so every unit conversion happens here: values
are sent IN THE KEY'S UNIT (`concrete_cy` in CY, never the model's m3), with
`unit` set so BidSheet.ai can refuse a mismatch.

Which elements are sent. The upsert is all-or-nothing and a sent element's
volume is stored as concrete unless its type says earth, so the default is
conservative:

- the classes BidSheet.ai types (footing, wall, slab, column, pile,
  earthworks cut and fill) and any element carrying a classification
  reference (a pay code) are sent; anything else is skipped and reported
  with its class. `all_elements=True` sends the rest as generic.
- beams, members, plates (steel, usually), courses and pavements are
  skipped even when classified — their volume is not structural concrete
  — unless `all_elements=True`. Reinforcement, terrain
  (IfcGeographicElement, terrain proxies), openings and virtual elements
  are never sent.
- an element that aggregates parts which are themselves sent is skipped:
  the parts carry the quantities, and sending both would count them twice.
- an element whose GlobalId is not IFC-shaped, or repeats one already
  planned (the first is kept), is skipped: either would make BidSheet.ai
  refuse the whole call.

Quantity keys, by element type (subtype-aware, so IfcWallStandardCase is a
wall — BidSheet.ai's own IfcClass lookup is exact, hence `element_type` is
always sent explicitly):

- volume -> `excavation_cy` (IfcEarthworksCut: UndisturbedVolume, else
  Net/GrossVolume), `backfill_cy` (IfcEarthworksFill: CompactedVolume, else
  Net/GrossVolume), otherwise `concrete_cy` (NetVolume, else GrossVolume).
  A loose (swelled) volume is never the in-place measure and is not used.
- `pile_lf` (IfcPile only) from the pile's Length.
- `form_contact_sf` only when the caller names the quantity that holds the
  formed area (`form_area="Qto_Set.Name"` or a bare quantity name), and only
  for concrete types. No IFC base quantity set carries a formwork area — a
  wall's NetSideArea is one elevation face and excludes the ends — so the
  planner never guesses one.

An element that is sent but has none of these quantities goes with
`quantities: {}`: on a re-import that clears the model values BidSheet.ai
stored from an earlier export whose Qto has since gone. A NaN or infinite
quantity skips the element instead, so a broken export never clears good
values.

Values are scaled to SI by each quantity's own Unit, else the file's
declared unit of that dimension (`ifc_takeoff.quantity_scale`), then m3 ->
CY (/ 0.764554857984), m2 -> SF (/ 0.09290304), m -> LF (/ 0.3048), rounded
to the 4 places BidSheet.ai stores; a nonzero value that rounds to zero is
warned (a unit declaration is probably wrong).

Pay items: an element's classification code (the takeoff's pay-code spine)
is looked up in `items` — {code: item id}, {code: {"id", "unit"}}, or a
`get_estimate_model` document (its `items[].item_code`, else
`item_number`; a code or number several items share is ambiguous and maps
to none; `schedule=` limits the items to one schedule label first). The item
pays the key whose unit is the item's unit; with no unit known it pays the
volume key. Pure: reads the IFC, writes nothing.
"""
from __future__ import annotations

import math
import re
from typing import Optional

import ifcopenshell

from bimforge.bim.ifc_takeoff import (
    QUANTITY_DIM, classifications_of, quantity_scale, quantity_sets,
    _unit_scales)

CY_M3 = 0.764554857984         # one cubic yard in m3
SF_M2 = 0.09290304             # one square foot in m2
LF_M = 0.3048                  # one foot in m

# BidSheet.ai's Element column limits
NAME_MAX = 200
STRUCTURE_ID_MAX = 100

# BidSheet.ai's GlobalId rule (Projects/services/ifc_guid.is_global_id):
# 22 characters of IFC's base64 alphabet, the first carrying two bits.
GLOBAL_ID_RE = re.compile(r"^[0-3][0-9A-Za-z_$]{21}$")

# IFC class -> BidSheet.ai element type, checked in order with is_a (subtype
# aware). Mirrors BidSheet.ai's ELEMENT_TYPES; anything else is generic.
ELEMENT_TYPES = (
    ("IfcFooting", "footing"),
    ("IfcWall", "wall"),
    ("IfcSlab", "slab"),
    ("IfcColumn", "column"),
    ("IfcPile", "pile"),
    ("IfcEarthworksCut", "excavation"),
    ("IfcEarthworksFill", "backfill"),
)

# Never sent: not concrete or earthwork in any reading, or not built work.
NEVER_SENT = ("IfcReinforcingElement", "IfcGeographicElement",
              "IfcVirtualElement")
# Skipped by default even when classified (steel, or paving courses), sent
# as generic only with all_elements.
NOT_CONCRETE = ("IfcBeam", "IfcMember", "IfcPlate", "IfcCourse",
                "IfcPavement")

# The volume key per element type (BidSheet.ai's volume_key) and the Qto
# names that measure it, most-preferred first.
VOLUME_KEY = {"excavation": "excavation_cy", "backfill": "backfill_cy"}
VOLUME_NAMES = {
    "excavation_cy": ("UndisturbedVolume", "NetVolume", "GrossVolume"),
    "backfill_cy": ("CompactedVolume", "NetVolume", "GrossVolume"),
    "concrete_cy": ("NetVolume", "GrossVolume"),
}

KEY_UNITS = {"concrete_cy": "CY", "excavation_cy": "CY", "backfill_cy": "CY",
             "form_contact_sf": "SFCA", "pile_lf": "LF"}


def _is_a(element, cls: str) -> bool:
    try:
        return element.is_a(cls)
    except Exception:          # noqa: BLE001 — a class the schema lacks
        return False


def element_type_of(element) -> str:
    """The BidSheet.ai element type an IFC element reads as."""
    for cls, element_type in ELEMENT_TYPES:
        if _is_a(element, cls):
            return element_type
    return "generic"


def volume_key(element_type: str) -> str:
    return VOLUME_KEY.get(element_type, "concrete_cy")


def is_global_id(value) -> bool:
    return isinstance(value, str) and bool(GLOBAL_ID_RE.match(value))


def element_name(element) -> str:
    """The element's Name, else its class and GlobalId tail (a blank or
    whitespace-only Name is missing)."""
    name = (element.Name or "").strip()
    return name or f"{element.is_a()}-{(element.GlobalId or '')[-6:]}"


def _is_terrain(element) -> bool:
    if not _is_a(element, "IfcBuildingElementProxy"):
        return False
    text = " ".join(str(getattr(element, a, None) or "")
                    for a in ("Name", "ObjectType", "PredefinedType"))
    return "terrain" in text.lower()


def _qto_values(element, scales: dict):
    """(values, bad): every volume/area/length Qto member as (set, name,
    SI value, dim), and the "Set.Name"s whose value is NaN or infinite."""
    found: dict[tuple[str, str], tuple[float, str]] = {}
    bad = []
    for qto in quantity_sets(element):
        for q in qto.Quantities or []:
            dim = QUANTITY_DIM.get(q.is_a())
            if dim not in ("volume", "area", "length"):
                continue
            value = q[3]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if not math.isfinite(value):
                bad.append(f"{qto.Name}.{q.Name}")
                continue
            found[(qto.Name or "", q.Name)] = (
                float(value) * quantity_scale(q, scales, dim), dim)
    return [(s, n, v, d) for (s, n), (v, d) in found.items()], bad


def _pick(values, names: tuple[str, ...], dim: str):
    """The (set, name, value) of the most-preferred name, a standard
    `Qto_` set first when several sets carry it."""
    hits = [(names.index(n), not s.startswith("Qto_"), s, n, v)
            for s, n, v, d in values if d == dim and n in names]
    if not hits:
        return None
    _, _, s, n, v = min(hits)
    return s, n, v


def _form_pick(values, form_area: str):
    """The caller-named formed-area quantity: `Set.Name`, or a bare name in
    any set (a standard Qto_ set first)."""
    if "." in form_area:
        want_set, want = form_area.split(".", 1)
        hits = [(s, n, v) for s, n, v, d in values
                if s == want_set and n == want and d == "area"]
        return hits[0] if hits else None
    return _pick(values, (form_area,), "area")


def _item_index(items, schedule: str | None = None):
    """({code: {"id", "unit"}}, ambiguous codes) — see `item_index`."""
    if not items:
        return {}, set()
    if isinstance(items, dict) and isinstance(items.get("items"), list):
        items = items["items"]
    if isinstance(items, list):
        if schedule is not None:
            items = [it for it in items
                     if str(it.get("schedule") or "") == schedule]
        by_code: dict[str, list] = {}
        by_number: dict[str, list] = {}
        for it in items:
            code = str(it.get("item_code") or "")
            if code:
                by_code.setdefault(code, []).append(it)
            num = str(it.get("item_number") or "")
            if num:
                by_number.setdefault(num, []).append(it)
        out, ambiguous = {}, set()
        for code, hits in by_code.items():
            if len(hits) == 1:
                out[code] = {"id": hits[0]["id"],
                             "unit": hits[0].get("unit") or None}
            else:
                ambiguous.add(code)
        for num, hits in by_number.items():
            if num in out or num in ambiguous:
                continue          # a code claims the string
            if len(hits) == 1:
                out[num] = {"id": hits[0]["id"],
                            "unit": hits[0].get("unit") or None}
            else:
                ambiguous.add(num)
        return out, ambiguous
    out = {}
    for code, val in items.items():
        if isinstance(val, dict):
            out[str(code)] = {"id": val.get("id"),
                              "unit": val.get("unit") or None}
        else:
            out[str(code)] = {"id": val, "unit": None}
    for code, rec in out.items():
        if isinstance(rec["id"], bool) or not isinstance(rec["id"], int):
            raise ValueError(f"items: {code!r} must map to an estimate item "
                             f"id (an integer), got {rec['id']!r}")
    return out, set()


def item_index(items, schedule: str | None = None) -> dict[str, dict]:
    """Normalise the `items` input to {code: {"id": int, "unit": str|None}}.

    Accepts {code: id}, {code: {"id", "unit"?}}, a list of item dicts, or a
    whole `get_estimate_model` document. Item dicts key on `item_code`, and
    on `item_number` where no item claims that string as its code. A code
    (or number) several items share is ambiguous and left out — guessing
    one would pay the wrong item; `schedule` (an item's `schedule` label)
    narrows the items first, which usually resolves it.
    """
    return _item_index(items, schedule)[0]


def _pay_key(quantities: dict, unit: Optional[str], vkey: str) -> Optional[str]:
    """The quantity key an item of `unit` pays."""
    if unit:
        u = unit.strip().upper()
        for key in quantities:
            ku = KEY_UNITS[key]
            if u == ku or (ku == "SFCA" and u == "SF"):
                return key
        return None
    return vkey if vkey in quantities else (
        next(iter(quantities)) if len(quantities) == 1 else None)


def _quantity(value: float, unit: str, set_name: str, name: str,
              warnings: list, label: str) -> dict:
    rounded = round(value, 4)
    if value and not rounded:
        warnings.append(f"{label}: {set_name}.{name} is {value:.3g} {unit} — "
                        f"rounds to 0 at 4 places; check the file's unit "
                        f"declarations")
    return {"value": rounded, "unit": unit, "source": f"{set_name}.{name}"}


def _parts(element) -> list:
    return [o for rel in getattr(element, "IsDecomposedBy", None) or []
            if rel.is_a("IfcRelAggregates")
            for o in rel.RelatedObjects or [] if o.is_a("IfcElement")]


def plan_modelled_elements(ifc, items=None, *, structure_id: str | None = None,
                           structure_ids: dict | None = None,
                           form_area: str | None = None,
                           all_elements: bool = False,
                           schedule: str | None = None) -> dict:
    """Plan the `upsert_modelled_elements` payload for an IFC.

    `ifc` is a path or an open model. `items` maps classification (bid
    item) codes to estimate item ids (see `item_index`; `schedule` limits a
    model's items to one schedule label). `structure_ids` maps a
    classification code to a BidSheet.ai structure id; `structure_id` is the
    default for elements whose codes name none. `form_area` names the
    quantity holding the formed (form contact) area — never inferred.
    `all_elements` also sends unclassified, untyped elements and
    beams/members/plates/courses/pavements, as generic. See the module
    docstring for which elements are sent.

    Returns {"elements": [...], "skipped": [{global_id, name, ifc_class,
    reason}], "without_quantities": [{global_id, name}], "warnings": [...]}.
    """
    model = ifcopenshell.open(ifc) if isinstance(ifc, str) else ifc
    scales = _unit_scales(model)
    index, ambiguous = _item_index(items, schedule)
    structure_ids = {str(k): v for k, v in (structure_ids or {}).items()}
    skipped, warnings = [], []

    def skip(el, reason):
        skipped.append({"global_id": el.GlobalId, "name": element_name(el),
                        "ifc_class": el.is_a(), "reason": reason})

    # -- pass 1: which elements are candidates ----------------------------
    candidates = []
    for el in model.by_type("IfcElement"):
        if _is_a(el, "IfcFeatureElement") and \
                not _is_a(el, "IfcEarthworksCut"):
            continue                      # openings, voids, projections
        if any(_is_a(el, c) for c in NEVER_SENT) or _is_terrain(el):
            if not _is_a(el, "IfcVirtualElement"):
                skip(el, f"{el.is_a()} is not concrete or earthwork — "
                         f"never sent")
            continue
        etype = element_type_of(el)
        codes = list(dict.fromkeys(c["code"] for c in classifications_of(el)
                                   if c["code"]))
        if not all_elements:
            if any(_is_a(el, c) for c in NOT_CONCRETE):
                skip(el, f"{el.is_a()} is not structural concrete — "
                         f"pass all_elements (--all-elements) to send it "
                         f"as generic")
                continue
            if etype == "generic" and not codes:
                skip(el, f"{el.is_a()} is neither a typed class nor "
                         f"classified — pass all_elements (--all-elements) "
                         f"to send it as generic")
                continue
        candidates.append((el, etype, codes))

    # an aggregate whose own parts are sent would double their quantities
    sent_ids = {el.id() for el, _, _ in candidates}
    kept = []
    for el, etype, codes in candidates:
        if any(p.id() in sent_ids for p in _parts(el)):
            skip(el, "aggregates parts that are sent themselves — the parts "
                     "carry the quantities")
            continue
        kept.append((el, etype, codes))

    # -- pass 2: entries ----------------------------------------------------
    elements, without, seen_gids = [], [], {}
    unmapped_codes: set[str] = set()
    ambiguous_hit: set[str] = set()
    no_form = 0
    for el, etype, codes in kept:
        name = element_name(el)
        gid = el.GlobalId
        if not is_global_id(gid):
            skip(el, f"GlobalId {gid!r} is not a 22-character IFC GlobalId "
                     f"— BidSheet.ai would refuse the whole call")
            continue
        if gid in seen_gids:
            skip(el, f"GlobalId {gid} repeats {seen_gids[gid]!r} (the first "
                     f"is kept) — BidSheet.ai would refuse the whole call")
            continue
        values, bad = _qto_values(el, scales)
        if bad:
            skip(el, f"non-finite quantity {', '.join(bad)} — a broken "
                     f"export; not sent, so stored values are kept")
            continue
        seen_gids[gid] = name
        label = f"{name} ({gid})"
        vkey = volume_key(etype)

        quantities: dict[str, dict] = {}
        vol = _pick(values, VOLUME_NAMES[vkey], "volume")
        if vol is not None:
            s, n, v = vol
            quantities[vkey] = _quantity(v / CY_M3, "CY", s, n, warnings,
                                         label)
        if etype == "pile":
            length = _pick(values, ("Length",), "length")
            if length is not None:
                s, n, v = length
                quantities["pile_lf"] = _quantity(v / LF_M, "LF", s, n,
                                                  warnings, label)
        if form_area and vkey == "concrete_cy":
            form = _form_pick(values, form_area)
            if form is not None:
                s, n, v = form
                quantities["form_contact_sf"] = _quantity(
                    v / SF_M2, "SFCA", s, n, warnings, label)
            else:
                no_form += 1

        entry = {"global_id": gid, "name": name[:NAME_MAX],
                 "ifc_class": el.is_a(), "element_type": etype}
        sid = next((structure_ids[c] for c in codes if c in structure_ids),
                   structure_id)
        if sid:
            entry["structure_id"] = str(sid)[:STRUCTURE_ID_MAX]
        entry["quantities"] = quantities
        if not quantities:
            without.append({"global_id": gid, "name": name})

        pay_items: dict[str, int] = {}
        for code in codes if quantities else ():
            rec = index.get(code)
            if rec is None:
                if code in ambiguous:
                    ambiguous_hit.add(code)
                elif index:
                    unmapped_codes.add(code)
                continue
            key = _pay_key(quantities, rec["unit"], vkey)
            if key is None:
                warnings.append(
                    f"{label}: code {code} pays item {rec['id']} in "
                    f"{rec['unit'] or '?'}, which no quantity of this "
                    f"element is measured in — no pay item set")
                continue
            if key in pay_items and pay_items[key] != rec["id"]:
                warnings.append(
                    f"{label}: {key} is claimed by several codes — kept item "
                    f"{pay_items[key]}, not {rec['id']} (code {code})")
                continue
            pay_items[key] = rec["id"]
        if pay_items:
            entry["pay_items"] = pay_items
        elements.append(entry)

    if ambiguous_hit:
        warnings.append(f"classification code(s) {', '.join(sorted(ambiguous_hit))} "
                        f"match several estimate items — no pay item set "
                        f"(pass the schedule, or map them by item id)")
    if unmapped_codes:
        warnings.append(f"classification code(s) with no estimate item: "
                        f"{', '.join(sorted(unmapped_codes))} — their "
                        f"elements import without a pay item")
    if no_form:
        warnings.append(f"{no_form} concrete element(s) lack the form area "
                        f"quantity {form_area!r} — no form_contact_sf sent")
    if without:
        warnings.append(f"{len(without)} element(s) are sent with no "
                        f"quantities (no Qto BidSheet.ai stores): a re-import "
                        f"clears the model values an earlier one stored")
    return {"elements": elements, "skipped": skipped,
            "without_quantities": without, "warnings": warnings}
