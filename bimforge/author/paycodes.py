"""Pay codes as bid data (spec §3): loader/validator for per-bid paycodes.yaml,
`classify(element)`, and takeoff-map generation.

The schema (the machinery ships; the TABLES are per-bid data):

    rules:                 # ordered, first-match per element
      - match: "(?i)footing"
        ifc_class: IfcFooting     # optional narrowing
        group: ps_footing
        sign: 1                   # -1 => void deduction
    groups:
      ps_footing: {measure: GrossVolume}
      ps_steel:   {measure: GrossWeight, density_pcf: 490}
    codes:
      PS-FTG-CONC:   {group: ps_footing, measure: GrossVolume, unit: CY,
                      item_number: "Item # 2", description: "..."}
      PS-SADDLE-STL: {group: ps_steel, measure: GrossWeight, unit: LBS}
    spatial_parts:         # optional, IFC4X3 facility parts (#318); first match
      - {match: "(?i)abut", part: ABUTMENT}
      - {match: "(?i)deck", part: {name: Deck, predefined_type: DECK}}

Lessons encoded (ifc_qto lesson d + sample-bridge gap #1): ONE mapping table, never
restated — the IFC classification and the generated takeoff map both come
from here, so they cannot drift apart. A group may carry SEVERAL codes (one
code per PAY ITEM: furnish by the foot AND drive by the each off one
element); each code sums its own measure to its own item, so nothing
double-counts. Weight (GrossWeight/LBS + density) is first-class; a weight
code whose group has no density is a validation error unless elements carry
explicit weights.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from bimforge.author.spatial import (SpatialPartRule, apply_spatial_parts,
                                     parse_rules)

#: The measures a code may sum — the ifc_takeoff contract's quantity names.
KNOWN_MEASURES = ("GrossVolume", "NetVolume", "GrossArea", "NetArea",
                  "Length", "Perimeter", "Width", "Height", "Count",
                  "GrossWeight", "NetWeight", "Weight")
WEIGHT_MEASURES = ("GrossWeight", "NetWeight", "Weight")
#: Spellings normalised at load (#363): emit_ifc writes the weight Qto as
#: GrossWeight, so a map saying plain `Weight` (the reinforcing-Qto name)
#: must come out as GrossWeight or the takeoff never finds it.
MEASURE_ALIASES = {"Weight": "GrossWeight"}


@dataclass(frozen=True)
class Rule:
    pattern: str
    group: str
    ifc_class: str | None = None
    sign: int = 1

    def matches(self, name: str, ifc_class: str) -> bool:
        if self.ifc_class and self.ifc_class != ifc_class:
            return False
        return bool(re.search(self.pattern, name, re.I))


@dataclass
class PayCodes:
    rules: list[Rule]
    groups: dict[str, dict]
    codes: dict[str, dict]
    project_ref: str | None = None
    organization_id: int = 0
    defaults: dict = field(default_factory=dict)
    # Cost-code system IFC identity (spec §5.4): source_system -> IfcClassification.Name,
    # edition -> IfcClassification.Edition. Default "BidSchedule" keeps historical output.
    source_system: str = "BidSchedule"
    edition: str = ""
    #: `spatial_parts:` rules (issue #318): element name regex -> IFC4X3
    #: facility part, applied by `apply` to elements with no spatial_part.
    spatial_parts: list[SpatialPartRule] = field(default_factory=list)

    # -- queries ------------------------------------------------------------
    def codes_for(self, group: str) -> list[str]:
        """Every code an element of this group is classified under (sorted —
        the emission order pipe-supports-pilot/bridge-pilot settled on)."""
        return sorted(c for c, cfg in self.codes.items()
                      if cfg["group"] == group)

    def group_of(self, name: str, ifc_class: str):
        """(group, sign) by first-match rule, or (None, +1) — unmapped."""
        for r in self.rules:
            if r.matches(name, ifc_class):
                return r.group, r.sign
        return None, 1

    def classify(self, element) -> list[str]:
        """The pay codes an Element carries (ordered; [] = unmapped or a
        no-code group, i.e. reference geometry)."""
        group, _sign = self.group_of(element.name, element.ifc_class)
        return self.codes_for(group) if group else []

    def density_for(self, code: str) -> float | None:
        return self.groups.get(self.codes[code]["group"], {}).get("density_pcf")

    # -- takeoff map --------------------------------------------------------
    def takeoff_map(self, codes_used: list[str]) -> dict:
        """The est-bim takeoff map for the codes a model actually used.

        GENERATED, not hand-maintained — codes/measures/units/item numbers
        come from this one table, so the map cannot drift from the
        classification written into the IFC. The result conforms to
        docs/ifc-takeoff-contract.md (singular `measure:` per code — a group
        paying several items carries several CODES, each with its own
        measure) and round-trips through `ifc_takeoff.normalize_map`.
        """
        out_codes = {}
        for code in sorted(codes_used):
            cfg = self.codes[code]
            entry = {"measure": cfg["measure"], "unit": cfg["unit"]}
            if cfg.get("item_number"):
                entry["item_number"] = str(cfg["item_number"])
            if cfg.get("description"):
                entry["description"] = cfg["description"]
            out_codes[code] = entry
        doc = {"codes": out_codes}
        if self.organization_id:
            doc["organization_id"] = self.organization_id
        if self.project_ref:
            doc["project_ref"] = self.project_ref
        if self.defaults:
            doc["defaults"] = dict(self.defaults)
        # Round-trip the IFC identity only when it departs from the default, so
        # existing BidSchedule maps stay byte-identical.
        if self.source_system and self.source_system != "BidSchedule":
            doc["source_system"] = self.source_system
        if self.edition:
            doc["edition"] = self.edition
        return doc


def _err(msgs: list[str]):
    if msgs:
        raise ValueError("paycodes.yaml invalid:\n  - " + "\n  - ".join(msgs))


def load(path: Path | str) -> PayCodes:
    """Parse + validate a paycodes.yaml. Fails loud, all errors together."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return from_dict(data)


def from_dict(data: dict) -> PayCodes:
    msgs: list[str] = []
    rules = []
    for i, r in enumerate(data.get("rules") or []):
        if not isinstance(r, dict) or not r.get("match") or not r.get("group"):
            msgs.append(f"rules[{i}]: needs 'match' and 'group'")
            continue
        sign = int(r.get("sign", 1))
        if sign not in (1, -1):
            msgs.append(f"rules[{i}]: sign must be 1 or -1, got {sign}")
        try:
            re.compile(r["match"])
        except re.error as exc:
            msgs.append(f"rules[{i}]: bad regex {r['match']!r} ({exc})")
        rules.append(Rule(pattern=r["match"], group=r["group"],
                          ifc_class=r.get("ifc_class"), sign=sign))
    groups = data.get("groups") or {}
    codes = data.get("codes") or {}
    if not rules:
        msgs.append("no rules")
    if not codes:
        msgs.append("no codes")
    for name, g in groups.items():
        m = (g or {}).get("measure")
        if m in MEASURE_ALIASES:
            m = g["measure"] = MEASURE_ALIASES[m]
        if m and m not in KNOWN_MEASURES:
            msgs.append(f"group {name}: unknown measure {m!r}")
    for code, cfg in codes.items():
        if not isinstance(cfg, dict):
            msgs.append(f"code {code}: must be a mapping")
            continue
        if cfg.get("group") not in groups:
            msgs.append(f"code {code}: group {cfg.get('group')!r} not in groups")
        m = cfg.get("measure")
        if m in MEASURE_ALIASES:
            m = cfg["measure"] = MEASURE_ALIASES[m]
        if m not in KNOWN_MEASURES:
            msgs.append(f"code {code}: unknown measure {m!r} "
                        f"(choices: {sorted(KNOWN_MEASURES)})")
        if not cfg.get("unit"):
            msgs.append(f"code {code}: needs a pay unit")
        if (m in WEIGHT_MEASURES
                and (groups.get(cfg.get("group")) or {}).get("density_pcf") is None
                and not cfg.get("elements_carry_weight")):
            msgs.append(
                f"code {code}: {m} needs groups.{cfg.get('group')}.density_pcf "
                f"(or 'elements_carry_weight: true' when the builder writes "
                f"explicit weight_lb quantities)")
    for i, r in enumerate(rules):
        if r.group not in groups:
            msgs.append(f"rules[{i}]: group {r.group!r} not in groups")
    spatial_parts = []
    try:
        spatial_parts = parse_rules(data.get("spatial_parts"))
    except ValueError as exc:
        msgs.append(str(exc))
    _err(msgs)
    return PayCodes(rules=rules, groups=groups, codes=codes,
                    project_ref=data.get("project_ref"),
                    organization_id=int(data.get("organization_id") or 0),
                    defaults=data.get("defaults") or {},
                    # coerce to str: yaml.safe_load parses `edition: 2020` as an int,
                    # which would otherwise leak into IfcClassification.Edition (a string)
                    source_system=str(data.get("source_system") or "BidSchedule"),
                    edition=str(data.get("edition") or ""),
                    spatial_parts=spatial_parts)


def apply(model, paycodes: PayCodes) -> None:
    """Classify every element of a StructureModel in place (build-time step).

    Elements that already carry classifications are left alone — a family may
    classify explicitly; this is the rule-driven path. Elements matching no
    rule stay [] (reference geometry / unmapped — the GATE decides whether
    that is acceptable, not this function).

    The `spatial_parts:` rules assign IFC4X3 facility parts the same way:
    only to elements that do not already carry a `spatial_part`."""
    apply_spatial_parts(model, paycodes.spatial_parts)
    for el in model.elements:
        if not el.classifications:
            el.classifications = paycodes.classify(el)
        for code in el.classifications:
            cfg = paycodes.codes.get(code)
            if cfg is None:
                continue
            dens = paycodes.density_for(code)
            if (cfg["measure"] in WEIGHT_MEASURES and dens is not None
                    and "weight_lb" not in el.quantities
                    and "volume_cf" in el.quantities):
                el.quantities["weight_lb"] = el.quantities["volume_cf"] * dens
