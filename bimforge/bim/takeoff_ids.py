"""The takeoff contract as IDS (buildingSMART Information Delivery Specification).

`est-bim takeoff` reads classification codes and Qto quantities off every
IfcElement (`bimforge.bim.ifc_takeoff`). This module states the part of that
contract a model checker can test, as two IDS 1.0 documents any IDS tool
(Bonsai, `python -m ifctester`, a Revit or Tekla checker) can run against an
export before it reaches the takeoff:

* `takeoff.ids` -- the rules whose breach makes a pay quantity wrong or
  missing: a classified element with nothing to measure, a quantity stored
  as the wrong dimension, a classification reference with no code.
* `takeoff-coverage.ids` -- the advisory rule: every measured element is
  classified. The takeoff only warns about these, and a model may leave
  parts unpaid on purpose, so it is a separate document.

The quantity names come from `ifc_takeoff.MEASURE_DIM`, so the documents
cannot drift from the reader. The committed copies live in
`bimforge/bim/contract/`; a test regenerates and compares them.

    python -m bimforge.bim.takeoff_ids            # rewrite the committed copies

What IDS cannot say, and the reader still does: measure selection and the
takeoff map, unit scaling, one code associated twice counting once, and a
map-declared code that matched no element. IDS also selects a quantity set
by NAME, not by type, so the documents ask for sets named `Qto_*` or
`*BaseQuantities`; the reader itself takes any IfcElementQuantity.
"""
from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import ifcopenshell

from bimforge.bim.ifc_takeoff import MEASURE_DIM

IDS_NS = "http://standards.buildingsmart.org/IDS"
XS_NS = "http://www.w3.org/2001/XMLSchema"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
SCHEMA_LOCATION = (f"{IDS_NS} "
                   "http://standards.buildingsmart.org/IDS/1.0/ids.xsd")

# The reader's classification read is IFC4-shaped
# (IfcClassificationReference.Identification); an IFC2X3 reference carries
# ItemReference instead and is not read.
IFC_VERSIONS = ("IFC4", "IFC4X3_ADD2")

# Quantity sets are selected by name (see the module docstring).
QTO_SET_PATTERN = r"Qto_.*|.*BaseQuantities"

# A quantity's IDS dataType is the measure type of its IfcQuantity* value.
DIM_DATATYPE = {"length": "IFCLENGTHMEASURE", "area": "IFCAREAMEASURE",
                "volume": "IFCVOLUMEMEASURE", "count": "IFCCOUNTMEASURE",
                "mass": "IFCMASSMEASURE"}

# The names a row can sum: pick_measure's natural order, then the weights a
# map may declare. Width, Height and Perimeter only dimension an element.
SUMMABLE = ("Count", "GrossVolume", "NetVolume", "GrossArea", "NetArea",
            "Length", "GrossWeight", "NetWeight", "Weight")

CONTRACT_DIR = Path(__file__).parent / "contract"
DOCUMENTS = ("takeoff.ids", "takeoff-coverage.ids")


def element_classes() -> list[str]:
    """Every instantiable IfcElement subtype in the supported schemas,
    upper-cased as IDS names them. IDS matches an entity by exact class, so
    "any IfcElement" (what the reader walks) has to be spelled out."""
    names: set[str] = set()

    def walk(decl) -> None:
        if not decl.is_abstract():
            names.add(decl.name().upper())
        for sub in decl.subtypes():
            walk(sub)

    for version in IFC_VERSIONS:
        schema = ifcopenshell.ifcopenshell_wrapper.schema_by_name(version)
        walk(schema.declaration_by_name("IfcElement"))
    return sorted(names)


# -- XML helpers -------------------------------------------------------------
def _ids(tag: str) -> str:
    return f"{{{IDS_NS}}}{tag}"


def _simple(parent, tag: str, value: str):
    el = ET.SubElement(parent, _ids(tag))
    ET.SubElement(el, _ids("simpleValue")).text = value
    return el


def _restricted(parent, tag: str, *, enumeration=(), pattern: str | None = None):
    el = ET.SubElement(parent, _ids(tag))
    r = ET.SubElement(el, f"{{{XS_NS}}}restriction", base="xs:string")
    for value in enumeration:
        ET.SubElement(r, f"{{{XS_NS}}}enumeration", value=value)
    if pattern is not None:
        ET.SubElement(r, f"{{{XS_NS}}}pattern", value=pattern)
    return el


def _elements(parent) -> None:
    entity = ET.SubElement(parent, _ids("entity"))
    _restricted(entity, "name", enumeration=element_classes())


def _classified(parent, **attrs) -> None:
    """Any classification reference, under any system."""
    facet = ET.SubElement(parent, _ids("classification"), **attrs)
    _restricted(facet, "system", pattern=".+")


def _quantity(parent, names, **attrs) -> None:
    facet = ET.SubElement(parent, _ids("property"), **attrs)
    _restricted(facet, "propertySet", pattern=QTO_SET_PATTERN)
    _restricted(facet, "baseName", enumeration=names)


def _specification(parent, name: str, description: str, instructions: str):
    spec = ET.SubElement(parent, _ids("specification"), name=name,
                         ifcVersion=" ".join(IFC_VERSIONS),
                         description=description, instructions=instructions)
    applicability = ET.SubElement(spec, _ids("applicability"),
                                  minOccurs="0", maxOccurs="unbounded")
    return applicability, ET.SubElement(spec, _ids("requirements"))


def _document(title: str, description: str, purpose: str):
    root = ET.Element(_ids("ids"), {f"{{{XSI_NS}}}schemaLocation": SCHEMA_LOCATION})
    info = ET.SubElement(root, _ids("info"))
    ET.SubElement(info, _ids("title")).text = title
    ET.SubElement(info, _ids("description")).text = description
    ET.SubElement(info, _ids("purpose")).text = purpose
    return root, ET.SubElement(root, _ids("specifications"))


def _serialise(root) -> str:
    ET.register_namespace("ids", IDS_NS)
    ET.register_namespace("xs", XS_NS)
    ET.register_namespace("xsi", XSI_NS)
    ET.indent(root, space="  ")
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            + ET.tostring(root, encoding="unicode") + "\n")


# -- the two documents -------------------------------------------------------
def takeoff_ids() -> str:
    """The hard rules: a breach makes a pay quantity wrong or missing."""
    root, specs = _document(
        "bimforge takeoff contract",
        "What an IFC must carry for est-bim takeoff to roll it up into pay "
        "quantities: classification codes as the pay-item key and Qto "
        "quantities as the measure. Generated by bimforge.bim.takeoff_ids.",
        "Quantity takeoff")

    applies, requires = _specification(
        specs, "Classified elements carry a quantity to measure",
        "An element with a classification code is a pay item. The takeoff "
        "sums one of its quantities; with none of these it is skipped and "
        "the pay item comes up short.",
        "Give the element a quantity set named Qto_* or *BaseQuantities "
        "holding at least one of: " + ", ".join(SUMMABLE) + ".")
    _elements(applies)
    _classified(applies)
    _quantity(requires, SUMMABLE, cardinality="required")

    applies, requires = _specification(
        specs, "Quantities are stored as their own dimension",
        "The takeoff scales a quantity by the unit of the dimension its "
        "name implies, so an area stored as a length is scaled wrongly.",
        "Store each named quantity as the matching IfcQuantity type "
        "(GrossArea as IfcQuantityArea, Length as IfcQuantityLength, ...).")
    _elements(applies)
    for dim, data_type in DIM_DATATYPE.items():
        names = [n for n, d in MEASURE_DIM.items() if d == dim]
        _quantity(requires, names, dataType=data_type, cardinality="optional")

    applies, requires = _specification(
        specs, "Classification references carry a code",
        "The reference's Identification is the code pay items key on.",
        "Set Identification on every IfcClassificationReference.")
    _simple(ET.SubElement(applies, _ids("entity")), "name",
            "IFCCLASSIFICATIONREFERENCE")
    attribute = ET.SubElement(requires, _ids("attribute"), cardinality="required")
    _simple(attribute, "name", "Identification")
    return _serialise(root)


def coverage_ids() -> str:
    """The advisory rule: the takeoff warns about these, it does not fail."""
    root, specs = _document(
        "bimforge takeoff coverage",
        "Advisory companion to the bimforge takeoff contract: every measured "
        "element is classified. est-bim takeoff counts and reports "
        "unclassified elements; it never drops them silently. Generated by "
        "bimforge.bim.takeoff_ids.",
        "Quantity takeoff")
    applies, requires = _specification(
        specs, "Measured elements are classified",
        "An element with quantities and no classification code reaches no "
        "pay item.",
        "Associate the element with an IfcClassificationReference whose "
        "Identification is its pay code, or accept that it is unpaid.")
    _elements(applies)
    _quantity(applies, SUMMABLE)
    _classified(requires, cardinality="required")
    return _serialise(root)


def documents() -> dict[str, str]:
    return {"takeoff.ids": takeoff_ids(), "takeoff-coverage.ids": coverage_ids()}


def main(argv: list[str] | None = None) -> int:
    CONTRACT_DIR.mkdir(exist_ok=True)
    for name, text in documents().items():
        (CONTRACT_DIR / name).write_text(text, encoding="utf-8")
        print(f"wrote {CONTRACT_DIR / name}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
