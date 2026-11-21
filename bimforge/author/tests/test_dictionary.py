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

EXAMPLES = ("concrete-barrier-842", "concrete-barrier-732sw", "bridge-standard",
            "caltrans-b3-retaining-wall", "caltrans-b3-wall-types")


@pytest.fixture(scope="module")
def built(tmp_path_factory) -> list:
    """The shipped examples, built: the 732SW run carries a B11-51 handrail,
    the bridge is stationed on its alignment, and the B3 wall types example
    builds one wall of every wall type."""
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
                if cp["Code"] in pset and "PredefinedValue" in cp:
                    assert pset[cp["Code"]] == cp["PredefinedValue"]
    # every class but the optional D90 guardrail is exercised by the examples
    assert seen == {c["Code"] for c in dictionary["Classes"]} - {"pipe-guardrail-d90"}


def test_every_standard_plan_reference_is_declared(dictionary, built):
    ue = ifcopenshell.util.element
    declared = {(cp["PropertySet"], cp["PredefinedValue"])
                for c in dictionary["Classes"]
                for cp in c.get("ClassProperties", [])
                if "PredefinedValue" in cp}
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


def test_every_typed_element_references_its_class(dictionary, built):
    """M.1: an element of a dictionary type carries a class reference to
    that class, under the dictionary's own system, which no pay reader
    takes for a pay code."""
    from bimforge.author import family_dictionary as fd
    from bimforge.bim.ifc_takeoff import classifications_of, family_class_of
    ue = ifcopenshell.util.element
    checked = 0
    for model in built:
        for el in model.by_type("IfcElement"):
            el_type = ue.get_type(el)
            got = family_class_of(el)
            if el_type is None:
                assert got is None, el.Name
                continue
            cls = _class_for(dictionary, el_type.Name)
            assert got == {"code": cls["Code"], "name": cls["Name"],
                           "uri": fd.class_uri(cls["Code"])}, el.Name
            assert all(c["code"] != cls["Code"] for c in classifications_of(el))
            checked += 1
        systems = [c for c in model.by_type("IfcClassification")
                   if c.Name == fd.system()["name"]]
        assert len(systems) <= 1
        for system in systems:
            assert system.Source == "bimforge" and system.Edition
    assert checked


def test_constant_stems_are_layered_and_the_rest_plain(built):
    """X.6: a B3 stem of constant thickness (Types 1A, 6A, 6B) is an IfcWall
    with a material layer set usage, its type the one-layer set, the layer
    its stem thickness, located by an 'Axis'; a battered stem (Types 1, 5)
    and every footing keep a plain material (IFC's IfcWall: an L-shaped or
    battered retaining wall carries no layer set usage)."""
    from bimforge.author.families.standard_plan import CONSTANT_STEM
    ue = ifcopenshell.util.element
    model = built[EXAMPLES.index("caltrans-b3-wall-types")]
    k = 0.3048
    layered = set()
    for el in model.by_type("IfcWall") + model.by_type("IfcFooting"):
        mat = ue.get_material(el)
        wall_type = el.Name.split()[0][1:].lower()           # "T1a ..." -> "1a"
        if el.is_a("IfcWall") and wall_type in CONSTANT_STEM:
            assert mat.is_a("IfcMaterialLayerSetUsage"), el.Name
            assert mat.LayerSetDirection == "AXIS2"
            assert ue.get_material(ue.get_type(el)) == mat.ForLayerSet
            (layer,) = mat.ForLayerSet.MaterialLayers
            assert layer.Material.Name == "Concrete"
            width = ue.get_pset(el, "Qto_BaseQuantities")["Width"]
            assert abs(layer.LayerThickness - width) < 1e-9
            reps = {r.RepresentationIdentifier: r
                    for r in el.Representation.Representations}
            assert reps["Axis"].RepresentationType == "Curve2D"
            length = ue.get_pset(el, "Qto_BaseQuantities")["Length"]
            (p0, p1) = reps["Axis"].Items[0].Points
            assert p0.Coordinates == (0.0, 0.0)
            assert abs(p1.Coordinates[0] - length) < 1e-6 * max(1.0, length / k)
            layered.add(wall_type)
        else:
            assert mat.is_a("IfcMaterial") and mat.Name == "Concrete", el.Name
    assert layered == set(CONSTANT_STEM)


def test_every_class_dimension_is_written(dictionary, built):
    """M.2: an element of a class carries BIMForge_Dimensions with exactly
    the dimensions the class declares, each the measure the dictionary
    gives it; a class that declares none writes no set."""
    from bimforge.author import family_dictionary as fd
    from bimforge.bim.ifc_takeoff import family_class_of
    measures = {"IfcLengthMeasure": float, "IfcRatioMeasure": float}
    seen = set()
    for model in built:
        for el in model.by_type("IfcElement"):
            cls = family_class_of(el)
            declared = fd.dimensions(cls["code"]) if cls else []
            pset = ue_pset(el, fd.DIMENSIONS)
            if not declared:
                assert pset is None, el.Name
                continue
            assert sorted(pset) == sorted(declared), el.Name
            for code in declared:
                prop = pset[code]
                assert prop.NominalValue.is_a() == fd.measure(code)[0]
                assert isinstance(prop.NominalValue.wrappedValue,
                                  measures[prop.NominalValue.is_a()])
            seen |= set(declared)
    assert seen == {p["Code"] for p in dictionary["Properties"]
                    if fd.DIMENSIONS in p.get("Description", "")}


def ue_pset(el, name):
    """{property name: IfcPropertySingleValue} of `el`'s set `name`."""
    for rel in el.IsDefinedBy or ():
        pset = getattr(rel, "RelatingPropertyDefinition", None)
        if pset is not None and pset.is_a("IfcPropertySet") and pset.Name == name:
            return {p.Name: p for p in pset.HasProperties}
    return None


def test_b3_dimensions_are_the_sections(built):
    """The B3 values are the slice's section, lengths in metres: design H
    as specified (8 ft or 6 ft in the wall types example), the batter a
    plain ratio."""
    from bimforge.author import family_dictionary as fd
    from bimforge.author.alignment import parse_batter
    import yaml as _yaml
    tables = _yaml.safe_load(
        (files("bimforge.author") / "examples" / "caltrans-b3-tables.example.yaml")
        .read_text("utf-8"))
    model = built[EXAMPLES.index("caltrans-b3-wall-types")]
    k = 0.3048 * 1200 / 3937 / 0.3048            # us-survey-ft -> m
    heights = {"T1": 8, "T1a": 8, "T5": 8, "T6a": 6, "T6b": 6}
    for el in model.by_type("IfcWall") + model.by_type("IfcFooting"):
        dims = {n: p.NominalValue.wrappedValue
                for n, p in ue_pset(el, fd.DIMENSIONS).items()}
        tag = el.Name.split()[0]
        assert abs(dims["DesignHeight"] - heights[tag] * k) < 1e-9, el.Name
        if tag == "T6a" and el.is_a("IfcWall"):
            assert abs(dims["StemThickness"]
                       - tables["type_6a_case_1"]["stem_thickness_ft"] * k) < 1e-9
        if tag == "T5" and el.is_a("IfcWall"):
            row = tables["type_5_case_1"]["table"]
            assert dims["Batter"] > 0 and dims["StemBaseThickness"] > dims["StemThickness"]
            assert any(abs(dims["Batter"] - parse_batter(r["batter"])) < 1e-9
                       for r in (row.values() if isinstance(row, dict) else row))


def test_b3_volumes_are_boxes_over_their_own_quantities(built):
    """M.3: every B3 stem and footing slice is a prism the family sized, so
    its GrossVolume says `Length * Width * Height`, and that product of the
    set's own Length, Width and Height is the volume in the file."""
    from bimforge.author.gate import (FORMULA_TOLERANCE, formula_value,
                                      quantity_value)
    model = built[EXAMPLES.index("caltrans-b3-wall-types")]
    els = model.by_type("IfcWall") + model.by_type("IfcFooting")
    assert els
    for el in els:
        qset = next(r.RelatingPropertyDefinition for r in el.IsDefinedBy
                    if r.RelatingPropertyDefinition.is_a("IfcElementQuantity"))
        q = {x.Name: x for x in qset.Quantities}
        vol = q["GrossVolume"]
        assert vol.Formula == "Length * Width * Height", el.Name
        got = formula_value(vol.Formula, {n: quantity_value(x) for n, x in q.items()})
        assert abs(got - vol.VolumeValue) <= FORMULA_TOLERANCE * vol.VolumeValue
