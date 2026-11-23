"""A barrier run's Mod dimensions and profile are its route (M.8)."""
from pathlib import Path

import yaml

from bimforge.author.barrier_template import run_route
from bimforge.author.families import concrete_barrier_732sw, concrete_barrier_842
from bimforge.author.project import ProjectContext
from bimforge.author.type_842_profile import STANDARD_DIMS

_EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def test_a_standard_842_run():
    assert run_route(concrete_barrier_842.template(),
                     {"straight_length_ft": 40}) == ("standard", [])


def test_an_842_with_a_taller_stem_is_modified_by_value():
    route, diffs = run_route(concrete_barrier_842.template(),
                             {"straight_length_ft": 40, "stem_h_ft": 4.0})
    assert route == "modified-by-value"
    assert diffs == [{"name": "stem_h_ft", "standard": 3.5, "actual": 4.0,
                      "source": diffs[0]["source"]}]
    assert diffs[0]["source"].endswith("stem_h_ft")


def test_a_run_given_at_the_standard_value_is_standard():
    assert run_route(concrete_barrier_842.template(),
                     {"stem_h_ft": 3.5})[0] == "standard"


def test_a_profile_is_modified_by_section():
    ring = [[0, 0], [1.75, 0], [1.2, 3.5], [0, 3.5]]
    assert run_route(concrete_barrier_842.template(),
                     {"profile": ring}) == ("modified-by-section", [])


def test_a_732sw_sidewalk_width_mod():
    route, diffs = run_route(concrete_barrier_732sw.template(),
                             {"sw_width_ft": 8.0})
    assert route == "modified-by-value"
    assert diffs[0]["name"] == "sw_width_ft" and diffs[0]["actual"] == 8.0


def test_a_732sw_profile_is_modified_by_section():
    ring = [[0, 0], [2.0, 0], [2.0, 2.0], [0, 2.67]]
    assert run_route(concrete_barrier_732sw.template(),
                     {"profile": ring})[0] == "modified-by-section"


def test_a_732sw_deck_slope_is_where_it_sits_not_a_mod():
    assert run_route(concrete_barrier_732sw.template(),
                     {"deck_slope_pct": 2.0}) == ("standard", [])


def test_the_842_standard_dims_are_its_mod_keys():
    assert set(STANDARD_DIMS) == set(concrete_barrier_842._MOD_KEYS)


def test_an_842_run_with_a_taller_stem_builds_modified():
    spec = yaml.safe_load((_EXAMPLES / "concrete-barrier-842.spec.yaml")
                          .read_text(encoding="utf-8"))
    params = spec["params"]
    params["runs"][0]["stem_h_ft"] = 4.0
    ctx = ProjectContext.from_spec(spec["project"])
    model = concrete_barrier_842.build(params, ctx)
    whole = next(e for e in model.elements if e.name.endswith("barrier run"))
    bodies = [e for e in model.elements if e.ifc_class == "IfcWall"
              and e is not whole]
    others = [e for e in model.elements if e.ifc_class != "IfcWall"]
    assert bodies and others
    for el in [whole] + bodies:
        assert el.route == "modified-by-value", el.name
        assert [d["name"] for d in el.differences] == ["stem_h_ft"]
    assert all(e.route is None and not e.differences for e in others)
