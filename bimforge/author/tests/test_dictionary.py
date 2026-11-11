"""The family dictionary (bSDD import format) is well formed and names
everything the typed families emit: every IFC type, its class and predefined
type, its standard-plan Reference, and every linear-reference property."""
from __future__ import annotations

import json
from importlib.resources import files

import pytest

DICTIONARY = files("bimforge.author") / "dictionary" / "bimforge-families.bsdd.json"
LINEAR_PSET = "BIMForge_LinearReference"


@pytest.fixture(scope="module")
def dictionary() -> dict:
    return json.loads(DICTIONARY.read_text(encoding="utf-8"))


def test_it_is_a_bsdd_import_document(dictionary):
    for key in ("OrganizationCode", "DictionaryCode", "DictionaryVersion",
                "LanguageIsoCode", "LanguageOnly", "UseOwnUri"):
        assert key in dictionary                      # bSDD's required fields
    codes = [c["Code"] for c in dictionary["Classes"]]
    assert len(codes) == len(set(codes))
    props = [p["Code"] for p in dictionary["Properties"]]
    assert len(props) == len(set(props))
    for c in dictionary["Classes"]:
        assert c["Name"] and c["Definition"] and c["RelatedIfcEntityNamesList"]
        for cp in c.get("ClassProperties", []):
            # exactly one of the two, as bSDD requires
            assert bool(cp.get("PropertyCode")) != bool(cp.get("PropertyUri"))
            if cp.get("PropertyCode"):
                assert cp["PropertyCode"] in props


def test_part_relations_point_at_classes_in_this_dictionary(dictionary):
    base = ("https://identifier.buildingsmart.org/uri/{OrganizationCode}/"
            "{DictionaryCode}/{DictionaryVersion}/class/").format(**dictionary)
    codes = {c["Code"] for c in dictionary["Classes"]}
    relations = [r for c in dictionary["Classes"]
                 for r in c.get("ClassRelations", [])]
    assert relations
    for r in relations:
        assert r["RelatedClassUri"].startswith(base)
        assert r["RelatedClassUri"][len(base):] in codes


# -- against what the families emit ------------------------------------------
ifcopenshell = pytest.importorskip("ifcopenshell")
yaml = pytest.importorskip("yaml")

EXAMPLES = ("concrete-barrier-842", "concrete-barrier-732sw", "bridge-standard")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> list:
    """The shipped examples, built: the 732SW run carries a B11-51 handrail,
    the bridge is stationed on its alignment."""
    import ifcopenshell.util.element  # noqa: F401
    from bimforge.author.families.registry import build_from_spec
    tmp = tmp_path_factory.mktemp("dictionary")
    examples = files("bimforge.author") / "examples"
    for entry in examples.iterdir():
        if entry.name.endswith(".yaml"):
            (tmp / entry.name).write_text(entry.read_text("utf-8"), "utf-8")
    models = []
    for name in EXAMPLES:
        spec = tmp / f"{name}.spec.yaml"
        assert build_from_spec(str(spec)) == 0
        out = yaml.safe_load(spec.read_text("utf-8"))["outputs"]["ifc"]
        models.append(ifcopenshell.open(str(tmp / out)))
    return models


def _class_for(dictionary: dict, type_name: str) -> dict | None:
    """The class a type name belongs to: the longest class Name it starts
    with (a type name may append a section size)."""
    hits = [c for c in dictionary["Classes"] if type_name.startswith(c["Name"])]
    return max(hits, key=lambda c: len(c["Name"]), default=None)


def test_every_emitted_type_is_a_dictionary_class(dictionary, built):
    ue = ifcopenshell.util.element
    seen = set()
    for model in built:
        for el in model.by_type("IfcElement"):
            el_type = ue.get_type(el)
            if el_type is None:
                continue
            cls = _class_for(dictionary, el_type.Name)
            assert cls is not None, f"no dictionary class for {el_type.Name!r}"
            seen.add(cls["Code"])
            predefined = ue.get_predefined_type(el)
            names = {el.is_a()}
            if predefined and predefined != "NOTDEFINED" \
                    and not ue.is_userdefined_type(el):
                names.add(el.is_a() + predefined)
            assert names <= set(cls["RelatedIfcEntityNamesList"]), (
                el_type.Name, names)
            for cp in cls.get("ClassProperties", []):
                pset = ue.get_pset(el, cp["PropertySet"]) or {}
                if cp["Code"] in pset:
                    assert pset[cp["Code"]] == cp["PredefinedValue"]
    # every class but the optional D90 guardrail is exercised by the examples
    assert seen == {c["Code"] for c in dictionary["Classes"]} - {"pipe-guardrail-d90"}


def test_every_standard_plan_reference_is_declared(dictionary, built):
    ue = ifcopenshell.util.element
    declared = {(cp["PropertySet"], cp["PredefinedValue"])
                for c in dictionary["Classes"]
                for cp in c.get("ClassProperties", [])}
    emitted = set()
    for model in built:
        for el in model.by_type("IfcElement"):
            for name, props in ue.get_psets(el, psets_only=True).items():
                if name.startswith("Pset_") and "Reference" in props:
                    emitted.add((name, props["Reference"]))
    assert emitted and emitted <= declared


def test_every_linear_reference_property_is_declared(dictionary, built):
    ue = ifcopenshell.util.element
    declared = {p["Code"] for p in dictionary["Properties"]}
    emitted = set()
    for model in built:
        for el in model.by_type("IfcElement"):
            emitted |= set(ue.get_pset(el, LINEAR_PSET) or {}) - {"id"}
    assert emitted and emitted <= declared
