"""PredefinedType and ObjectType as IFC pairs them (#77).

IFC 4.3 carries a custom type in ObjectType only beside PredefinedType
USERDEFINED (the "Object Predefined Type" concept, the CorrectPredefinedType
where rule); on a type object the custom type is its ElementType, and the
occurrence is left NOTDEFINED ("Element Type Predefined Type").
"""
from __future__ import annotations

import contextlib
import copy
import io
import uuid
from importlib.resources import files

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
import ifcopenshell.util.element as ue  # noqa: E402
import ifcopenshell.validate  # noqa: E402

from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.primitives import Prism  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402


def _model(schema="IFC4X3_ADD2"):
    ctx = ProjectContext(name="Typing Fixture", epsg=2226, schema=schema,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=77))
    return StructureModel("typing", ctx)


def _box(name, x=0.0):
    return Prism(name, [(x, 0), (x + 2, 0), (x + 2, 2), (x, 2)], 0.0, 1.0)


def _add(m, name, ifc_class="IfcBuildingElementProxy", x=0.0, **kw):
    m.add(Element.from_geometry(name, _box(name, x), ifc_class=ifc_class, **kw))


def _emit(m, tmp_path):
    out = tmp_path / "t.ifc"
    emit_ifc(m, str(out))
    return ifcopenshell.open(str(out))


def _by_name(f, name):
    (el,) = [e for e in f.by_type("IfcElement") if e.Name == name]
    return el


def _valid(f):
    lg = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, lg, express_rules=True)
    return lg.statements


def test_an_object_type_alone_is_written_userdefined(tmp_path):
    m = _model()
    _add(m, "pad", object_type="GROUT_PAD")
    _add(m, "wall", "IfcWall", x=5.0, object_type="CUTOFF")
    f = _emit(m, tmp_path)
    for name, ot in (("pad", "GROUT_PAD"), ("wall", "CUTOFF")):
        el = _by_name(f, name)
        assert (el.PredefinedType, el.ObjectType) == ("USERDEFINED", ot)
        assert ue.get_predefined_type(el) == ot
    assert _valid(f) == []


def test_a_predefined_type_alone_carries_no_object_type(tmp_path):
    m = _model()
    _add(m, "wall", "IfcWall", predefined_type="parapet")
    el = _by_name(_emit(m, tmp_path), "wall")
    assert (el.PredefinedType, el.ObjectType) == ("PARAPET", None)


def test_a_conflicting_predefined_type_and_object_type_are_refused(tmp_path):
    m = _model()
    _add(m, "wall", "IfcWall", predefined_type="PARAPET", object_type="CUTOFF")
    with pytest.raises(ValueError, match="only with PredefinedType USERDEFINED"):
        emit_ifc(m, str(tmp_path / "t.ifc"))
    assert not (tmp_path / "t.ifc").exists()


def test_userdefined_with_an_object_type_is_accepted(tmp_path):
    m = _model()
    _add(m, "wall", "IfcWall", predefined_type="USERDEFINED",
         object_type="CUTOFF")
    el = _by_name(_emit(m, tmp_path), "wall")
    assert (el.PredefinedType, el.ObjectType) == ("USERDEFINED", "CUTOFF")


def test_userdefined_without_an_object_type_is_refused(tmp_path):
    m = _model()
    _add(m, "wall", "IfcWall", predefined_type="USERDEFINED")
    with pytest.raises(ValueError, match="needs an object_type"):
        emit_ifc(m, str(tmp_path / "t.ifc"))


def test_a_type_carries_the_custom_type_and_the_occurrence_is_notdefined(
        tmp_path):
    m = _model()
    for i in range(2):
        _add(m, f"mortar {i}", x=5.0 * i, object_type="POCKET_MORTAR",
             type_name="post pocket mortar")
    f = _emit(m, tmp_path)
    (t,) = f.by_type("IfcBuildingElementProxyType")
    assert (t.PredefinedType, t.ElementType) == ("USERDEFINED", "POCKET_MORTAR")
    for i in range(2):
        el = _by_name(f, f"mortar {i}")
        assert ue.get_type(el) == t
        assert (el.PredefinedType, el.ObjectType) == ("NOTDEFINED", None)
        assert ue.get_predefined_type(el) == "POCKET_MORTAR"
    assert _valid(f) == []


def test_a_type_with_a_predefined_type_leaves_the_occurrence_notdefined(
        tmp_path):
    m = _model()
    _add(m, "wall", "IfcWall", predefined_type="PARAPET", type_name="barrier")
    f = _emit(m, tmp_path)
    (t,) = f.by_type("IfcWallType")
    assert (t.PredefinedType, t.ElementType) == ("PARAPET", None)
    el = _by_name(f, "wall")
    assert (el.PredefinedType, el.ObjectType) == ("NOTDEFINED", None)
    assert ue.get_predefined_type(el) == "PARAPET"


def test_one_type_name_with_two_object_types_is_refused(tmp_path):
    m = _model()
    _add(m, "a", object_type="GROUT_PAD", type_name="pad")
    _add(m, "b", x=5.0, object_type="BEARING_PAD", type_name="pad")
    with pytest.raises(ValueError, match="more than one predefined type"):
        emit_ifc(m, str(tmp_path / "t.ifc"))


def test_the_ifc4_downgrade_writes_userdefined_with_the_wanted_class(
        tmp_path, capsys):
    m = _model(schema="IFC4")
    _add(m, "fill", "IfcEarthworksFill")
    _add(m, "fill 2", "IfcEarthworksFill", x=5.0, predefined_type="BACKFILL")
    f = _emit(m, tmp_path)
    for name in ("fill", "fill 2"):
        el = _by_name(f, name)
        assert el.is_a() == "IfcBuildingElementProxy"
        assert (el.PredefinedType, el.ObjectType) == (
            "USERDEFINED", "IfcEarthworksFill")
    assert _valid(f) == []


def test_a_class_without_a_predefined_type_keeps_the_object_type(tmp_path):
    """IfcEarthworksElement has no PredefinedType: the unhosted cut's
    EXCAVATION stays in ObjectType alone (#364)."""
    m = _model()
    _add(m, "pit", "IfcEarthworksCut")
    el = _by_name(_emit(m, tmp_path), "pit")
    assert el.is_a() == "IfcEarthworksElement"
    assert el.ObjectType == "EXCAVATION"


# -- every proxy a family writes ------------------------------------------
yaml = pytest.importorskip("yaml")


def _proxy_typing(el):
    """(PredefinedType, custom type) a proxy reads as, through its type."""
    t = ue.get_type(el)
    if t is not None and t.PredefinedType not in (None, "NOTDEFINED"):
        return t.PredefinedType, t.ElementType
    return el.PredefinedType, el.ObjectType


def _family_models():
    """(label, model) for every shipped family that writes a proxy and is not
    covered by an example spec, with its option that writes one turned on."""
    from bimforge.author.families import approach_slab, pipe_supports, spillway
    from bimforge.author.tests import test_approach_slab as tas
    from bimforge.author.tests import test_family_spillway as tsp
    from bimforge.author.tests import test_pipe_supports as tps
    sp = copy.deepcopy(tsp.PARAMS)
    sp["principal"]["boxes"] = [{"name": "equipment pad", "bot_el": 100.0,
                                 "top_el": 101.0,
                                 "plan": [[0, 0], [4, 0], [4, 4], [0, 4]]}]
    yield "spillway", spillway.build(sp, tsp.CTX)
    yield "pipe-supports", pipe_supports.build(copy.deepcopy(tps.PARAMS),
                                               tps.CTX)
    yield "approach-slab", approach_slab.build(tas._params(drainage=True),
                                               tas.CTX)


def _example_ifcs(tmp):
    from bimforge.author.families.registry import build_from_spec
    for entry in (files("bimforge.author") / "examples").iterdir():
        if entry.name.endswith(".yaml"):
            (tmp / entry.name).write_text(entry.read_text("utf-8"), "utf-8")
    for spec in sorted(tmp.glob("*.spec.yaml")):
        with contextlib.redirect_stderr(io.StringIO()):
            assert build_from_spec(str(spec)) == 0, spec.name
        ifc = yaml.safe_load(spec.read_text("utf-8"))["outputs"]["ifc"]
        yield spec.name, ifcopenshell.open(str(tmp / ifc))


def test_every_proxy_a_family_writes_is_userdefined_with_an_object_type(
        tmp_path):
    seen = {}
    for label, f in _example_ifcs(tmp_path):
        for el in f.by_type("IfcBuildingElementProxy"):
            seen[(label, el.Name)] = _proxy_typing(el)
    for label, m in _family_models():
        out = tmp_path / f"{label}.ifc"
        with contextlib.redirect_stderr(io.StringIO()):
            emit_ifc(m, str(out), allow_local=True)
        f = ifcopenshell.open(str(out))      # held: an entity outlives no file
        for el in f.by_type("IfcBuildingElementProxy"):
            seen[(label, el.Name)] = _proxy_typing(el)
    labels = {label for label, _ in seen}
    assert {"spillway", "pipe-supports", "approach-slab",
            "caltrans-box-culvert.spec.yaml",
            "tubular-handrail.spec.yaml"} <= labels
    bad = {k: v for k, v in seen.items()
           if v[0] != "USERDEFINED" or not v[1]}
    assert not bad
