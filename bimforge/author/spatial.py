"""IFC4X3 facility spatial tree: `project.facility`, `Element.spatial_part`, and
the `spatial_parts:` rule list (issue #318).

Opt-in and IFC4X3-only. Under IFC4 (opt-in, see ProjectContext.schema) and
under IFC4X3 with no facility, emit_ifc writes the historical
Project > Site > Building > Storey tree byte-for-byte. With a facility under
IFC4X3 a structure is written the way 4X3-aware viewers navigate it instead:

    IfcSite
     +- IfcBridge (or IfcRoad / IfcRailway / IfcMarineFacility / IfcFacility)
     |   +- IfcBridgePart ABUTMENT / DECK / ...   (one per distinct spatial_part)
     |       +- contained elements
     +- (kind: site) elements contained directly in the IfcSite, e.g. terrain

Spec shape (`project:` block of an est-bim build spec):

    project:
      schema: IFC4X3_ADD2
      facility: {kind: bridge, name: "Br 39-0063", predefined_type: GIRDER}

    spatial_parts:                 # spec top level and/or paycodes.yaml
      - {match: "(?i)abut", part: ABUTMENT}
      - {match: "(?i)deck|girder", part: {name: Deck, predefined_type: DECK}}

`kind` is one of FACILITY_KINDS. `name` defaults to the structure (model) name.
`predefined_type` is the facility's enum (IfcBridgeTypeEnum etc.); a value the
enum does not have becomes USERDEFINED + ObjectType. A part is a string (its
name) or a mapping {name, predefined_type?, usage_type?}; a part name that IS an
enum value of the part class (ABUTMENT, DECK, ...) is its own predefined type.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

#: kind -> (facility class, part class). `site` has neither: its products are
#: contained directly in the IfcSite.
FACILITY_KINDS = {
    "bridge": ("IfcBridge", "IfcBridgePart"),
    "road": ("IfcRoad", "IfcRoadPart"),
    "railway": ("IfcRailway", "IfcRailwayPart"),
    "marine": ("IfcMarineFacility", "IfcMarinePart"),
    # IfcFacilityPart is ABSTRACT in IFC4X3_ADD2; IfcFacilityPartCommon is the
    # instantiable part of a generic IfcFacility.
    "facility": ("IfcFacility", "IfcFacilityPartCommon"),
    "site": (None, None),
}

#: IfcFacilityPart.UsageType is REQUIRED (not optional) in IFC4X3_ADD2.
USAGE_TYPES = ("LATERAL", "LONGITUDINAL", "REGION", "VERTICAL",
               "USERDEFINED", "NOTDEFINED")


def schema_has_facilities(schema: str) -> bool:
    """True for the IFC4X3 family of schemas (the only ones with IfcFacility)."""
    return str(schema).upper().startswith("IFC4X3")


@dataclass(frozen=True)
class Facility:
    """`project.facility`: the 4X3 facility a structure is written as."""

    kind: str
    name: str | None = None
    predefined_type: str | None = None

    def __post_init__(self):
        if self.kind not in FACILITY_KINDS:
            raise ValueError(
                f"project.facility: unknown kind {self.kind!r} "
                f"(choices: {', '.join(FACILITY_KINDS)})")

    @property
    def facility_class(self) -> str | None:
        return FACILITY_KINDS[self.kind][0]

    @property
    def part_class(self) -> str | None:
        return FACILITY_KINDS[self.kind][1]

    @classmethod
    def from_spec(cls, spec) -> "Facility | None":
        """`project.facility` as a mapping, or a bare kind string."""
        if spec is None:
            return None
        if isinstance(spec, str):
            spec = {"kind": spec}
        if not isinstance(spec, dict):
            raise ValueError("project.facility must be a mapping "
                             "{kind, name?, predefined_type?} or a kind string")
        unknown = set(spec) - {"kind", "name", "predefined_type"}
        if unknown:
            raise ValueError(f"project.facility: unknown keys {sorted(unknown)}")
        if not spec.get("kind"):
            raise ValueError("project.facility: 'kind' is required")
        return cls(kind=str(spec["kind"]).lower(),
                   name=(str(spec["name"]) if spec.get("name") else None),
                   predefined_type=(str(spec["predefined_type"])
                                    if spec.get("predefined_type") else None))


@dataclass(frozen=True)
class SpatialPart:
    """One facility part: its name, and optionally a predefined/usage type."""

    name: str
    predefined_type: str | None = None
    usage_type: str | None = None


def parse_part(value, where: str = "spatial_part") -> SpatialPart | None:
    """A part as written on an Element or a rule: str | {name, ...} | None."""
    if value is None or value == "":
        return None
    if isinstance(value, SpatialPart):
        return value
    if isinstance(value, str):
        return SpatialPart(name=value)
    if isinstance(value, dict):
        unknown = set(value) - {"name", "predefined_type", "usage_type"}
        if unknown:
            raise ValueError(f"{where}: unknown keys {sorted(unknown)}")
        if not value.get("name"):
            raise ValueError(f"{where}: 'name' is required")
        usage = value.get("usage_type")
        if usage is not None and str(usage).upper() not in USAGE_TYPES:
            raise ValueError(f"{where}: usage_type {usage!r} is not one of "
                             f"{USAGE_TYPES}")
        return SpatialPart(
            name=str(value["name"]),
            predefined_type=(str(value["predefined_type"])
                             if value.get("predefined_type") else None),
            usage_type=str(usage).upper() if usage else None)
    raise ValueError(f"{where}: expected a part name or a mapping "
                     f"{{name, predefined_type?, usage_type?}}, got {value!r}")


@dataclass(frozen=True)
class SpatialPartRule:
    """`spatial_parts:` entry: first rule whose regex matches the element name
    (and ifc_class, if given) assigns the part."""

    pattern: str
    part: SpatialPart
    ifc_class: str | None = None

    def matches(self, name: str, ifc_class: str) -> bool:
        if self.ifc_class and self.ifc_class != ifc_class:
            return False
        return bool(re.search(self.pattern, name, re.I))


def parse_rules(data, where: str = "spatial_parts") -> list[SpatialPartRule]:
    """Parse + validate a `spatial_parts:` list; all errors together."""
    if not data:
        return []
    if not isinstance(data, list):
        raise ValueError(f"{where}: must be a list of {{match, part}} rules")
    rules, msgs = [], []
    for i, r in enumerate(data):
        if not isinstance(r, dict) or not r.get("match") or not r.get("part"):
            msgs.append(f"{where}[{i}]: needs 'match' and 'part'")
            continue
        unknown = set(r) - {"match", "part", "ifc_class"}
        if unknown:
            msgs.append(f"{where}[{i}]: unknown keys {sorted(unknown)}")
        try:
            re.compile(r["match"])
        except re.error as exc:
            msgs.append(f"{where}[{i}]: bad regex {r['match']!r} ({exc})")
            continue
        try:
            part = parse_part(r["part"], f"{where}[{i}].part")
        except ValueError as exc:
            msgs.append(str(exc))
            continue
        rules.append(SpatialPartRule(pattern=r["match"], part=part,
                                     ifc_class=r.get("ifc_class")))
    if msgs:
        raise ValueError(f"{where} invalid:\n  - " + "\n  - ".join(msgs))
    return rules


def apply_spatial_parts(model, rules) -> int:
    """Assign a part to every element that has none, by first-match rule.

    Elements that already carry a `spatial_part` are left alone (a family or
    bespoke script may place them explicitly). Returns the number assigned."""
    n = 0
    for el in model.elements:
        if el.spatial_part:
            continue
        for rule in rules or ():
            if rule.matches(el.name, el.ifc_class):
                el.spatial_part = rule.part
                n += 1
                break
    return n


# ----------------------------------------------------------- enum resolution
def _enum_items(schema: str, ifc_class: str) -> tuple[str, ...]:
    """The PredefinedType enumeration of `ifc_class`, or () if it has none."""
    import ifcopenshell.ifcopenshell_wrapper as wrapper
    decl = wrapper.schema_by_name(schema).declaration_by_name(ifc_class)
    for attr in decl.all_attributes():
        if attr.name() == "PredefinedType":
            t = attr.type_of_attribute()
            while hasattr(t, "declared_type") and not hasattr(
                    t, "enumeration_items"):
                t = t.declared_type()
            if hasattr(t, "enumeration_items"):
                return tuple(t.enumeration_items())
    return ()


def _enum_token(value: str) -> str:
    return re.sub(r"[\s\-]+", "_", value.strip()).upper()


def resolve_predefined(schema: str, ifc_class: str, value: str | None
                       ) -> tuple[str | None, str | None]:
    """(PredefinedType, ObjectType) for `value` on `ifc_class`.

    A value the class's enum has is used as is; anything else becomes
    USERDEFINED with the value in ObjectType (the schema's own rule for a
    user-defined type). A class with no PredefinedType at all (plain
    IfcFacility) carries the value in ObjectType alone. None -> (None, None).
    """
    if not value:
        return None, None
    items = _enum_items(schema, ifc_class)
    if not items:
        return None, value
    tok = _enum_token(value)
    if tok in items and tok != "USERDEFINED":
        return tok, None
    return "USERDEFINED", value


def resolve_part_type(schema: str, part_class: str, part: SpatialPart
                      ) -> tuple[str, str | None]:
    """(PredefinedType, ObjectType) for a part: its explicit predefined_type,
    else its NAME when that is an enum value (`ABUTMENT`), else USERDEFINED +
    ObjectType=name (`Abut 1`)."""
    if part.predefined_type and _enum_token(part.predefined_type) == "USERDEFINED":
        return "USERDEFINED", part.name
    pdt, obj = resolve_predefined(schema, part_class,
                                  part.predefined_type or part.name)
    return pdt or "NOTDEFINED", obj
