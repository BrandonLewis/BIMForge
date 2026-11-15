"""One IfcReinforcingBarType per bar size (C.4 Phase 1 typing).

Every bar that knows its size (Element.bar_size) is typed to one
IfcReinforcingBarType per size, carrying the bar's NominalDiameter,
CrossSectionArea and BarSurface. The type leaves PredefinedType NOTDEFINED:
bars of one size are main bars and ligatures both, so each occurrence keeps
its own MAIN / LIGATURE.

The types and their relationships are written after the file's other roots
are numbered, under keys of their own, so no existing GlobalId moves
(test_example_globalids).
"""
from __future__ import annotations

import uuid

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.util.element as ue  # noqa: E402
import ifcopenshell.validate  # noqa: E402

from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.primitives import BAR_PROPS, Prism  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402

IN = 0.0254


def _model(schema="IFC4X3_ADD2"):
    ctx = ProjectContext(name="Bar Fixture", epsg=2226, schema=schema,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=5))
    m = StructureModel("bars", ctx)
    wall = Prism("wall", [(0, 0), (10, 0), (10, 1), (0, 1)], 0.0, 4.0)
    m.add(Element.from_geometry("wall", wall, ifc_class="IfcWall"))
    for mark, size, role in (("long", 5, "MAIN"), ("tie", 5, "LIGATURE"),
                             ("vert", 4, "MAIN"), ("dowel", 4, None)):
        m.add(Element(f"wall reinforcing {mark} #{size}", "IfcReinforcingBar",
                      quantities={"count": 4, "length_ft": 40.0,
                                  "weight_lb": 40.0 * BAR_PROPS[size][2]},
                      predefined_type=role, bar_size=size))
    # a weight-only total with no size stays untyped
    m.add(Element("wall reinforcing", "IfcReinforcingBar",
                  quantities={"weight_lb": 100.0}))
    return m


def _emit(m, tmp_path):
    out = tmp_path / "bars.ifc"
    emit_ifc(m, str(out))
    return ifcopenshell.open(str(out))


@pytest.mark.parametrize("schema", ["IFC4X3_ADD2", "IFC4"])
def test_one_bar_type_per_size_with_its_section(tmp_path, schema):
    f = _emit(_model(schema), tmp_path)
    types = {t.Name: t for t in f.by_type("IfcReinforcingBarType")}
    assert sorted(types) == ["Reinforcing bar #4", "Reinforcing bar #5"]
    for size in (4, 5):
        t = types[f"Reinforcing bar #{size}"]
        dia_in, area_in2, _plf = BAR_PROPS[size]
        assert t.NominalDiameter == pytest.approx(dia_in * IN)
        assert t.CrossSectionArea == pytest.approx(area_in2 * IN * IN)
        assert t.BarSurface == "TEXTURED"
        assert t.PredefinedType == "NOTDEFINED"
    bars = {b.Name: b for b in f.by_type("IfcReinforcingBar")}
    for name, size, role in (("long #5", 5, "MAIN"), ("tie #5", 5, "LIGATURE"),
                             ("vert #4", 4, "MAIN"),
                             ("dowel #4", 4, None)):
        b = bars[f"wall reinforcing {name}"]
        assert ue.get_type(b) == types[f"Reinforcing bar #{size}"]
        # the type is NOTDEFINED, so the occurrence's own role stands
        assert ue.get_predefined_type(b) == role
    assert ue.get_type(bars["wall reinforcing"]) is None
    lg = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, lg, express_rules=True)
    assert lg.statements == []


def test_bar_types_take_keyed_globalids(tmp_path):
    m = _model()
    f = _emit(m, tmp_path)
    for t in f.by_type("IfcReinforcingBarType"):
        assert t.GlobalId == m.ctx.guid(f"type/IfcReinforcingBarType/{t.Name}")
        (rel,) = t.Types if hasattr(t, "Types") else t.ObjectTypeOf
        assert rel.GlobalId == m.ctx.guid(
            f"rel/IfcRelDefinesByType/{t.GlobalId}")
    # and a rebuild writes the same file
    again = _emit(m, tmp_path / ".." / tmp_path.name)
    assert sorted(r.GlobalId for r in again.by_type("IfcRoot")) == sorted(
        r.GlobalId for r in f.by_type("IfcRoot"))


def test_the_families_size_their_bars(tmp_path):
    """The per-mark bar emitters carry the size they name."""
    from bimforge.author.barrier_template import bar_elements
    from bimforge.author.primitives import RebarBuilder
    rb = RebarBuilder(size=6, cover_in=2.0, spacing_in=12.0)
    (el,) = bar_elements("NB", "842", [rb.bar("long-barrier", "wall",
                                              [(0, 0, 0), (0, 0, 10.0)],
                                              "straight")])
    assert el.bar_size == 6 and el.predefined_type == "MAIN"
