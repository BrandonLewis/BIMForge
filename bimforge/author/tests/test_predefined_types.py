"""The families name what their elements are in IFC's own PredefinedTypes
(C.4 Phase 1 typing): pier caps and stems, retaining walls, approach slabs,
pad and strip footings, main bars and ligatures. A value IFC4 lacks is
written USERDEFINED with the value as its ObjectType."""
from __future__ import annotations

import contextlib
import copy
import io
import re
import uuid
from importlib.resources import files

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")
yaml = pytest.importorskip("yaml")
import ifcopenshell.util.element as ue  # noqa: E402
import ifcopenshell.validate  # noqa: E402

from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.primitives import Prism, bar_role  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402

#: (example or family, element-name pattern) -> predefined type
EXPECTED = {
    ("bridge-standard", r"bent cap$"): "PIERCAP",
    ("bridge-standard", r"column \d+$"): "PIERSTEM",
    ("caltrans-b3-retaining-wall", r"retaining wall stem"): "RETAININGWALL",
    ("caltrans-b3-retaining-wall", r"retaining wall footing"): "STRIP_FOOTING",
    ("caltrans-culvert-wingwall", r"wingwall stem"): "RETAININGWALL",
    ("caltrans-culvert-wingwall", r"wingwall footing$"): "STRIP_FOOTING",
    ("caltrans-d90-headwall", r"wingwall (left|right)$"): "RETAININGWALL",
    ("caltrans-d90-headwall", r" footing$"): "STRIP_FOOTING",
    ("caltrans-pipe-headwall", r"headwall (return )?footing$"): "STRIP_FOOTING",
    ("caltrans-pipe-headwall", r"headwall return stem$"): "RETAININGWALL",
    ("demo-box", r"demo footing$"): "PAD_FOOTING",
    ("pipe-supports", r"pipe support footing$"): "PAD_FOOTING",
    ("approach-slab", r"approach slab(?! reinforcing)"): "APPROACH_SLAB",
    ("spillway", r"wall footing$"): "STRIP_FOOTING",
    ("headwall-926", r"^headwall footing$"): "STRIP_FOOTING",
    # bars, by mark
    ("caltrans-d90-headwall", r"reinforcing tie #\d+$"): "LIGATURE",
    ("caltrans-d90-headwall", r"reinforcing long #\d+$"): "MAIN",
    ("concrete-barrier-842", r"reinforcing eb-stirrup #\d+$"): "LIGATURE",
    ("concrete-barrier-842", r"reinforcing long-barrier #\d+$"): "MAIN",
    ("concrete-barrier-732sw", r"reinforcing eb-tie #\d+$"): "LIGATURE",
    ("concrete-barrier-732sw", r"reinforcing vert-face #\d+$"): "MAIN",
    ("caltrans-culvert-wingwall", r"reinforcing front #\d+$"): "MAIN",
    ("approach-slab", r"bottom_main #\d+$"): "MAIN",
    ("pipe-supports", r"footing rebar"): "MAIN",
}


def _examples(tmp):
    from bimforge.author.families.registry import build_from_spec
    for entry in (files("bimforge.author") / "examples").iterdir():
        if entry.name.endswith(".yaml"):
            (tmp / entry.name).write_text(entry.read_text("utf-8"), "utf-8")
    for spec in sorted(tmp.glob("*.spec.yaml")):
        with contextlib.redirect_stderr(io.StringIO()):
            assert build_from_spec(str(spec)) == 0, spec.name
        ifc = yaml.safe_load(spec.read_text("utf-8"))["outputs"]["ifc"]
        yield spec.name[:-len(".spec.yaml")], ifcopenshell.open(str(tmp / ifc))


def _families(tmp):
    from bimforge.author.families import (approach_slab, headwall_926,
                                          pipe_supports, spillway)
    from bimforge.author.tests import test_approach_slab as tas
    from bimforge.author.tests import test_family_spillway as tsp
    from bimforge.author.tests import test_headwall_926 as thw
    from bimforge.author.tests import test_pipe_supports as tps
    for label, m in (
            ("spillway", spillway.build(copy.deepcopy(tsp.PARAMS), tsp.CTX)),
            ("pipe-supports", pipe_supports.build(copy.deepcopy(tps.PARAMS),
                                                  tps.CTX)),
            ("approach-slab", approach_slab.build(tas._params(), tas.CTX)),
            ("headwall-926", headwall_926.build(copy.deepcopy(thw.PARAMS),
                                                thw.CTX))):
        out = tmp / f"{label}.ifc"
        with contextlib.redirect_stderr(io.StringIO()):
            emit_ifc(m, str(out), allow_local=True)
        yield label, ifcopenshell.open(str(out))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("predefined")
    return dict(list(_examples(tmp)) + list(_families(tmp)))


@pytest.mark.parametrize("where,pattern", sorted(EXPECTED))
def test_the_families_write_ifc_predefined_types(built, where, pattern):
    hits = [el for el in built[where].by_type("IfcElement")
            if re.search(pattern, el.Name or "")]
    assert hits, (where, pattern)
    assert {el.Name: ue.get_predefined_type(el) for el in hits} == {
        el.Name: EXPECTED[(where, pattern)] for el in hits}


def test_a_bar_role_comes_from_its_mark():
    assert bar_role("eb-stirrup") == "LIGATURE"
    assert bar_role("tie") == "LIGATURE"
    assert bar_role("long-barrier") == "MAIN"
    assert bar_role("bottom_main") == "MAIN"
    # a dowel anchors and a spacer spaces: neither is a main bar
    assert bar_role("dowel") is None
    assert bar_role("haunch_dowel") is None
    assert bar_role("spacer") is None


def _model(schema):
    ctx = ProjectContext(name="Pier Fixture", epsg=2226, schema=schema,
                         base_e=6_594_000.0, base_n=1_943_000.0,
                         guid_ns=uuid.UUID(int=4))
    m = StructureModel("pier", ctx)
    for i, (cls, pdt) in enumerate((("IfcBeam", "PIERCAP"),
                                    ("IfcColumn", "PIERSTEM"),
                                    ("IfcFooting", "PAD_FOOTING"))):
        p = Prism(cls, [(4 * i, 0), (4 * i + 2, 0), (4 * i + 2, 2), (4 * i, 2)],
                  0.0, 1.0)
        m.add(Element.from_geometry(cls, p, ifc_class=cls, predefined_type=pdt))
    return m


@pytest.mark.parametrize("schema,piercap", [
    ("IFC4X3_ADD2", ("PIERCAP", None)),
    ("IFC4", ("USERDEFINED", "PIERCAP"))])
def test_a_value_the_schema_lacks_is_written_userdefined(tmp_path, schema,
                                                         piercap):
    out = tmp_path / "pier.ifc"
    emit_ifc(_model(schema), str(out))
    f = ifcopenshell.open(str(out))
    by = {el.Name: el for el in f.by_type("IfcElement")}
    assert (by["IfcBeam"].PredefinedType, by["IfcBeam"].ObjectType) == piercap
    assert ue.get_predefined_type(by["IfcColumn"]) == "PIERSTEM"
    # IFC4 has PAD_FOOTING: written as itself in both
    assert (by["IfcFooting"].PredefinedType,
            by["IfcFooting"].ObjectType) == ("PAD_FOOTING", None)
    lg = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(f, lg, express_rules=True)
    assert lg.statements == []
