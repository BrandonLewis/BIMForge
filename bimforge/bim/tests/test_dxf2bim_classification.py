"""dxf2bim: a layer rule's classification carries IfcClassification
Source/Edition (audit C.4 Phase 1)."""
from __future__ import annotations

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.api  # noqa: E402

from bimforge.bim.dxf2bim import _add_classification  # noqa: E402


def _model():
    f = ifcopenshell.api.run("project.create_file", version="IFC4")
    ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcProject", name="P")
    return f


def _slab(f):
    return ifcopenshell.api.run("root.create_entity", f, ifc_class="IfcSlab")


def test_a_rule_names_its_source_and_edition():
    f, cache = _model(), {}
    _add_classification(f, _slab(f), cache,
                        {"system": "Caltrans", "code": "51-01", "name": "Concrete",
                         "source": "Caltrans", "edition": 2024})
    (c,) = f.by_type("IfcClassification")
    assert (c.Name, c.Source, c.Edition) == ("Caltrans", "Caltrans", "2024")


def test_a_published_system_defaults_to_its_publisher_and_others_stay_unset():
    f, cache = _model(), {}
    _add_classification(f, _slab(f), cache, {"system": "MasterFormat", "code": "03 30 00"})
    _add_classification(f, _slab(f), cache, {"system": "Custom", "code": "X"})
    by_name = {c.Name: c for c in f.by_type("IfcClassification")}
    assert by_name["MasterFormat"].Source == "CSI/CSC"
    assert by_name["Custom"].Source is None and by_name["Custom"].Edition is None
