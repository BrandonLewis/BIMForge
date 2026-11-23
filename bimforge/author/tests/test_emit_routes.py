"""emit_ifc writes BIMForge_Route (roadmap M.8): the route, the class an
element is based on, and each difference as an IfcComplexProperty."""
import uuid

import pytest

from bimforge.author.emit_ifc import emit_ifc
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import Prism
from bimforge.author.project import ProjectContext

CLASS = "retaining-wall-b3-type-1-footing"


@pytest.fixture
def emitted_footing(tmp_path):
    """(**element overrides) -> (ifc file, the IfcFooting): one B3 footing
    in a US survey foot project (EPSG 2226), emitted and reopened."""
    import ifcopenshell

    def emit(**overrides):
        ctx = ProjectContext(name="routes", epsg=2226, base_e=6_594_000.0,
                             base_n=1_943_000.0, base_h=200.0,
                             guid_ns=uuid.UUID(int=0x5e))
        m = StructureModel("routes", ctx)
        p = Prism("W-1 footing", [(-2, -2), (2, -2), (2, 2), (-2, 2)],
                  z_bot=0.0, z_top=2.0, ifc="IfcFooting")
        el = Element.from_geometry(p.name, p, ifc_class="IfcFooting")
        el.family_class = overrides.pop("family_class", CLASS)
        if el.family_class:                 # a class's required dimensions
            el.dimensions = {"DesignHeight": 8.0, "ToeWidth": 2.3333,
                             "HeelWidth": 4.25}
        for k, v in overrides.items():
            setattr(el, k, v)
        m.add(el)
        out = tmp_path / "routes.ifc"
        emit_ifc(m, str(out))
        f = ifcopenshell.open(str(out))
        (product,) = f.by_type("IfcFooting")
        return f, product

    return emit


def _route_pset(product):
    for rel in product.IsDefinedBy:
        p = rel.RelatingPropertyDefinition
        if p.is_a("IfcPropertySet") and p.Name == "BIMForge_Route":
            return p
    return None


def test_a_standard_element_says_so(emitted_footing):
    _, product = emitted_footing(route="standard")
    p = _route_pset(product)
    vals = {q.Name: q.NominalValue.wrappedValue for q in p.HasProperties}
    assert vals == {"Route": "standard", "BasedOn": CLASS}


def test_a_difference_is_a_complex_property_in_metres(emitted_footing):
    _, product = emitted_footing(route="modified-by-value", differences=[
        {"name": "ToeWidth", "standard": 2.3333, "actual": 2.0,
         "source": "caltrans/2025/b3-retaining-wall type_1_case_1.table.8.C_ft"},
        {"name": "W_ft", "standard": None, "actual": 7.0, "source": "s"}])
    p = _route_pset(product)
    cx = {q.Name: q for q in p.HasProperties if q.is_a("IfcComplexProperty")}
    toe = {q.Name: q.NominalValue for q in cx["ToeWidth"].HasProperties}
    assert cx["ToeWidth"].UsageName == "Difference"
    assert toe["Standard"].is_a("IfcLengthMeasure")
    assert abs(toe["Standard"].wrappedValue - 2.3333 * 0.3048006096) < 1e-6
    assert abs(toe["Actual"].wrappedValue - 2.0 * 0.3048006096) < 1e-6
    assert toe["Source"].wrappedValue.endswith("table.8.C_ft")
    assert "Standard" not in {q.Name for q in cx["W_ft"].HasProperties}


def test_a_text_difference_is_a_label(emitted_footing):
    _, product = emitted_footing(route="modified-by-value", differences=[
        {"name": "Note", "standard": "A", "actual": "B", "source": "s"}])
    (cx,) = [q for q in _route_pset(product).HasProperties
             if q.is_a("IfcComplexProperty")]
    vals = {q.Name: q.NominalValue for q in cx.HasProperties}
    assert vals["Actual"].is_a("IfcLabel") and vals["Actual"].wrappedValue == "B"


def test_bespoke_based_on_classifies_and_routes(emitted_footing):
    from bimforge.bim.ifc_takeoff import family_class_of
    _, product = emitted_footing(family_class=None, based_on=CLASS)
    vals = {q.Name: q.NominalValue.wrappedValue
            for q in _route_pset(product).HasProperties}
    assert vals["Route"] == "bespoke"
    assert family_class_of(product)["code"] == CLASS


def test_an_unrouted_element_has_no_route_set(emitted_footing):
    _, product = emitted_footing(route=None)
    assert _route_pset(product) is None


def test_the_route_set_is_keyed_and_moves_no_other_id(emitted_footing):
    f0, _ = emitted_footing(route=None)
    before = {e.GlobalId for e in f0.by_type("IfcRoot")}
    f1, _ = emitted_footing(route="standard")
    after = {e.GlobalId for e in f1.by_type("IfcRoot")}
    assert before < after
    new = {f1.by_guid(g) for g in after - before}
    assert {e.is_a() for e in new} == {"IfcPropertySet",
                                       "IfcRelDefinesByProperties"}
    f2, _ = emitted_footing(route="standard")
    assert {e.GlobalId for e in f2.by_type("IfcRoot")} == after


def test_an_unknown_route_is_refused(emitted_footing):
    with pytest.raises(ValueError, match="route 'mod'"):
        emitted_footing(route="mod")
