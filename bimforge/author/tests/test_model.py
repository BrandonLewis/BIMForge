"""StructureModel/Element: quantity delegation, multi-code, dupes, totals."""
import uuid

import pytest

from bimforge.author.model import Element, StructureModel
from bimforge.author.project import ProjectContext

CTX = ProjectContext(name="Fixture", guid_ns=uuid.UUID(int=1))


class _FakeGeom:
    volume_cf = 32.0
    area_sf = 16.0
    height_ft = 2.0


def test_from_geometry_delegates_quantities():
    el = Element.from_geometry("footing 1", _FakeGeom(), ifc_class="IfcFooting")
    assert el.quantities["volume_cf"] == 32.0
    assert el.quantities["area_sf"] == 16.0
    assert el.quantity("length_ft") is None
    assert el.guid_key == "element/footing 1"


def test_weight_via_density_and_explicit_override():
    el = Element("bar", quantities={"volume_cf": 2.0}, density_pcf=490.0)
    assert el.weight_lb == pytest.approx(980.0)
    el2 = Element("bar2", quantities={"volume_cf": 2.0, "weight_lb": 5.0})
    assert el2.weight_lb == 5.0
    assert Element("ref").weight_lb is None


def test_unknown_quantity_key_rejected():
    with pytest.raises(ValueError, match="unknown quantity"):
        Element("x", quantities={"volume_cy": 1.0})


def test_model_add_total_and_codes():
    m = StructureModel("fixture", CTX)
    m.add(Element("a", quantities={"volume_cf": 27.0},
                  classifications=["X-CONC"]))
    m.add(Element("b", quantities={"volume_cf": 54.0},
                  classifications=["X-CONC", "X-FORM"]))
    m.add(Element("ref"))                       # reference geometry, no code
    assert m.codes_used() == ["X-CONC", "X-FORM"]
    assert m.total("X-CONC", "volume_cf") == pytest.approx(81.0)
    assert m.total("X-FORM", "volume_cf") == pytest.approx(54.0)
    with pytest.raises(ValueError, match="duplicate"):
        m.add(Element("a"))
    assert m.element("b").name == "b"
    with pytest.raises(KeyError):
        m.element("zzz")
