"""cost_categories: one evaluator for IfcCostValue, composites included."""
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

import ifcopenshell.api.cost as cost  # noqa: E402
import ifcopenshell.api.root as root  # noqa: E402

from bimforge.bim.cost_categories import (  # noqa: E402
    categories_of, total_of, value_of,
)


def _item():
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    root.create_entity(f, ifc_class="IfcProject", name="p")
    cs = cost.add_cost_schedule(f, name="s")
    return f, cost.add_cost_item(f, cost_schedule=cs)


def _composite(f, ci, parts):
    top = cost.add_cost_value(f, parent=ci)
    cost.edit_cost_value(f, top, attributes={"ArithmeticOperator": "ADD"})
    for cat, amount in parts:
        cv = cost.add_cost_value(f, parent=top)
        attrs = {"AppliedValue": amount, "Name": cat or "Unallocated"}
        if cat:
            attrs["Category"] = cat
        cost.edit_cost_value(f, cv, attributes=attrs)
    return top


def test_a_composite_reads_at_its_components_sum():
    f, ci = _item()
    top = _composite(f, ci, [("Labor", 7.0), ("Material", 2.5), (None, 0.5)])
    assert top.AppliedValue is None
    assert value_of(top) == pytest.approx(10.0)
    assert total_of(ci) == pytest.approx(10.0)
    assert categories_of(ci) == {"Labor": 7.0, "Material": 2.5}


def test_sibling_values_read_as_before():
    f, ci = _item()
    for cat, amount in (("Labor", 4.0), (None, 1.0)):
        cv = cost.add_cost_value(f, parent=ci)
        attrs = {"AppliedValue": amount}
        if cat:
            attrs["Category"] = cat
        cost.edit_cost_value(f, cv, attributes=attrs)
    assert total_of(ci) == pytest.approx(5.0)
    assert categories_of(ci) == {"Labor": 4.0}


def test_a_non_add_composite_is_not_guessed_at():
    f, ci = _item()
    top = _composite(f, ci, [("Labor", 7.0)])
    top.ArithmeticOperator = "MULTIPLY"
    assert value_of(top) == 0.0
