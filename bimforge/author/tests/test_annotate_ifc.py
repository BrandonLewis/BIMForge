"""emit_ifc / emit_dxf consume a StructureModel.annotations plan (#195).

Each unique stamp -> ONE IfcRepresentationMap; each placement -> ONE
IfcMappedItem; the product is an IfcAnnotation. A model with no annotations
emits exactly as before (no annotation context, no IfcAnnotation), guarding
byte-determinism of every existing family.
"""
from __future__ import annotations

import uuid

import pytest

from bimforge.author.alignment import Alignment
from bimforge.author.annotate import station_annotation
from bimforge.author.model import StructureModel
from bimforge.author.project import ProjectContext

POB = {"station": 0.0, "northing": 0.0, "easting": 0.0}
NORTH = {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 500.0}


def _ctx():
    return ProjectContext(name="anno", guid_ns=uuid.UUID(int=21))


def _model_with_annotation():
    al = Alignment(POB, [NORTH])
    m = StructureModel(name="anno", ctx=_ctx())
    m.annotations.append(
        station_annotation(al, 0.0, 200.0, interval=100.0, name="Stationing"))
    return m


def test_emit_ifc_instances_stamps_as_mapped_items(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    from bimforge.author.emit_ifc import emit_ifc

    m = _model_with_annotation()
    plan = m.annotations[0]
    out = tmp_path / "anno.ifc"
    emit_ifc(m, str(out), allow_local=True)
    f = ifcopenshell.open(str(out))

    anns = f.by_type("IfcAnnotation")
    assert len(anns) == 1
    assert anns[0].Name == "Stationing"
    # one representation map per UNIQUE stamp, one mapped item per placement
    assert len(f.by_type("IfcRepresentationMap")) == len(plan.stamps)
    assert len(f.by_type("IfcMappedItem")) == len(plan.instances)
    # the product's representation is the mapped set
    rep = anns[0].Representation.Representations[0]
    assert rep.RepresentationType == "MappedRepresentation"
    assert len(rep.Items) == len(plan.instances)


def test_emit_ifc_annotation_is_byte_deterministic(tmp_path):
    pytest.importorskip("ifcopenshell")
    from bimforge.author.emit_ifc import emit_ifc

    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    emit_ifc(_model_with_annotation(), str(a), allow_local=True)
    emit_ifc(_model_with_annotation(), str(b), allow_local=True)
    assert a.read_bytes() == b.read_bytes()


def test_no_annotations_emits_no_annotation_entities(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    from bimforge.author.emit_ifc import emit_ifc

    m = StructureModel(name="plain", ctx=_ctx())
    out = tmp_path / "plain.ifc"
    emit_ifc(m, str(out), allow_local=True)
    f = ifcopenshell.open(str(out))
    assert not f.by_type("IfcAnnotation")
    assert not f.by_type("IfcRepresentationMap")
    assert not f.by_type("IfcMappedItem")


def test_emit_dxf_draws_annotation_polylines(tmp_path):
    pytest.importorskip("ezdxf")
    import ezdxf

    from bimforge.author.emit_dxf import emit_dxf

    m = _model_with_annotation()
    plan = m.annotations[0]
    out = tmp_path / "anno.dxf"
    emit_dxf(m, str(out))
    doc = ezdxf.readfile(str(out))
    lwpolys = list(doc.modelspace().query("LWPOLYLINE"))
    # one polyline drawn per resolved stroke of the plan
    assert len(lwpolys) >= len(plan.polylines())
