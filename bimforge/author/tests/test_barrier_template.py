import pytest
from bimforge.author.barrier_template import (
    BarrierTemplate, bar_elements, build_barrier, end_kinds)
from bimforge.author.project import ProjectContext


class _Bar:
    def __init__(self, mark, size, length, weight):
        self.mark, self.size, self.length, self.weight = mark, size, length, weight


def test_bar_elements_groups_by_mark_and_size():
    bars = [_Bar("a", 5, 10.0, 5.0), _Bar("a", 5, 10.0, 5.0),
            _Bar("b", 4, 3.0, 1.0)]
    els = bar_elements("NB", "842", bars)
    assert len(els) == 2                       # (a,5) and (b,4)
    a = next(e for e in els if "a #5" in e.name)
    assert a.name == "NB 842 reinforcing a #5"
    assert a.quantities == {"count": 2, "length_ft": 20.0, "weight_lb": 10.0}
    assert a.ifc_class == "IfcReinforcingBar" and a.layer == "S-REBAR"


def test_end_kinds_enum_dialect_takes_precedence():
    assert end_kinds({"start_end": "approach", "end_end": "none"}) == \
        ("approach", "none")


def test_end_kinds_bool_dialect_maps_to_approach_departure():
    assert end_kinds({"approach_end_block": True,
                      "departure_end_block": False}) == ("approach", "none")


def test_end_kinds_defaults_to_both_present():
    assert end_kinds({}) == ("approach", "departure")


def _ctx():
    return ProjectContext.from_spec({
        "name": "t", "epsg": 2226, "base": [0.0, 0.0],
        "guid_ns": "6f0e5a1a-0000-4000-8000-000000000042"})


class _Sec:                         # stand-in section: 1'x1' square, top_z=1
    outline = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    top_z = 1.0


def _tmpl(**kw):
    base = dict(
        family_id="fake-barrier", label="fake", endblock_len_ft=3.0,
        section_fn=lambda run: _Sec(),
        rebar_fn=lambda name, sec, run, run_len: [],
        endblock_fn=lambda name, run, sec, *, kind, pos, y_nose, y_inboard: [])
    base.update(kw)
    return BarrierTemplate(**base)


def test_requires_runs():
    import pytest
    with pytest.raises(ValueError, match="runs"):
        build_barrier(_tmpl(), {}, _ctx())


def test_running_prism_lf_accounts_for_end_blocks():
    # 100' run, both ends -> running prism 94', two 3' blocks handled by endblock_fn
    seen = []
    t = _tmpl(endblock_fn=lambda name, run, sec, *, kind, pos, y_nose, y_inboard:
              seen.append((kind, pos)) or [])
    m = build_barrier(t, {"runs": [{"name": "R",
                          "straight_length_ft": 100.0}]}, _ctx())
    prism = [e for e in m.elements if "fake barrier" in e.name][0]
    assert prism.quantities["length_ft"] == pytest.approx(94.0)
    assert set(seen) == {("approach", "start"), ("departure", "end")}


def test_bad_end_value_fails_loud():
    import pytest
    with pytest.raises(ValueError, match="must be one of"):
        build_barrier(_tmpl(), {"runs": [{"name": "R",
                      "straight_length_ft": 100.0, "start_end": "wing"}]}, _ctx())


def test_too_short_fails_loud():
    import pytest
    with pytest.raises(ValueError, match="too short"):
        build_barrier(_tmpl(), {"runs": [{"name": "R",
                      "straight_length_ft": 5.0}]}, _ctx())
