"""Every IfcTypeObject is declared to the IfcProject (IfcRelDeclares), as
IFC 4.3's Project Declaration concept asks (C.4 Phase 1 declarations).

The declaration is keyed as the embedders key a relationship
(`rel/IfcRelDeclares/<project id>` under the project's GlobalId), so a cost
schedule cost5d declares later joins it and keeps its id; and it is written
after the file's other roots are numbered, so no existing GlobalId moves.
"""
from __future__ import annotations

import uuid

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.validate  # noqa: E402

from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.primitives import Prism  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402
from bimforge.bim import stable_ids  # noqa: E402


def _model(typed=True):
    ctx = ProjectContext(name="Declare Fixture", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=6))
    m = StructureModel("declare", ctx)
    for i in range(2):
        p = Prism(f"post {i}", [(2 * i, 0), (2 * i + 1, 0), (2 * i + 1, 1),
                                (2 * i, 1)], 0.0, 3.0)
        m.add(Element.from_geometry(
            p.name, p, ifc_class="IfcMember", predefined_type="POST",
            type_name="post" if typed else None))
    m.add(Element("bars #5", "IfcReinforcingBar", predefined_type="MAIN",
                  quantities={"count": 2, "length_ft": 6.0, "weight_lb": 6.3},
                  bar_size=5 if typed else None))
    return m


def _emit(m, tmp_path):
    out = tmp_path / "d.ifc"
    emit_ifc(m, str(out))
    return ifcopenshell.open(str(out))


def test_every_type_is_declared_to_the_project(tmp_path):
    f = _emit(_model(), tmp_path)
    (project,) = f.by_type("IfcProject")
    (rel,) = f.by_type("IfcRelDeclares")
    assert rel.RelatingContext == project
    assert {t.Name for t in rel.RelatedDefinitions} == {
        "post", "Reinforcing bar #5"}
    assert set(rel.RelatedDefinitions) == set(f.by_type("IfcTypeObject"))
    assert rel.GlobalId == stable_ids.stable_id(
        f, f"rel/IfcRelDeclares/{project.GlobalId}")
    lg = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, lg, express_rules=True)
    assert lg.statements == []


def test_an_untyped_model_declares_nothing(tmp_path):
    f = _emit(_model(typed=False), tmp_path)
    assert not f.by_type("IfcTypeObject")
    assert not f.by_type("IfcRelDeclares")


def test_a_cost_schedule_joins_the_declaration_and_keeps_its_id(tmp_path):
    from bimforge.bim.cost5d import add_declared_cost_schedule
    f = _emit(_model(), tmp_path)
    (rel,) = f.by_type("IfcRelDeclares")
    gid = rel.GlobalId
    cs = add_declared_cost_schedule(f, name="bid", predefined_type="TENDER")
    stable_ids.key_relationships(f)
    (rel,) = f.by_type("IfcRelDeclares")
    assert rel.GlobalId == gid
    assert cs in rel.RelatedDefinitions
    assert len(rel.RelatedDefinitions) == 3
