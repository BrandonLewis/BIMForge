"""Regression guard for the concrete-barrier-732sw template refactor (Task 5).

During the refactor this suite proved `fam.build` (the new build_barrier path)
position-normalized byte-identical to `fam._build_legacy` (the pre-refactor
code) across three cases -- both-ends+handrail, no-handrail+no-blocks, and a Mod
(sw_width_ft) override; `_build_legacy` has since been deleted. The refactor
DELIBERATELY adds a `[start]`/`[end]` position suffix to 732sw end-block/hardware
element names (collision-safety + cross-family consistency with 842/R31);
quantities are unchanged. To keep the exact-output property guarded now that the
legacy oracle is gone, each case asserts its aggregate output totals (element
count + summed volume_cf / length_ft / weight_lb) against committed baselines
captured from the proven-equivalent build. The family suite
(test_concrete_barrier_732sw.py) covers the meaningful invariants behind them.
"""
import pytest

from bimforge.author.families import concrete_barrier_732sw as fam
from bimforge.author.project import ProjectContext


def _ctx():
    return ProjectContext.from_spec({
        "name": "t", "epsg": 2226, "base": [0.0, 0.0],
        "guid_ns": "6f0e5a1a-0000-4000-8000-000000000042"})


def _agg(model):
    return (
        len(model.elements),
        sum(e.quantities.get("volume_cf", 0.0) for e in model.elements),
        sum(e.quantities.get("length_ft", 0.0) for e in model.elements),
        sum(e.quantities.get("weight_lb", 0.0) for e in model.elements),
    )


# params -> (count, Σcf, Σlf, Σwt) baselines from the byte-identical build.
CASES = [
    ({"runs": [{"name": "NB", "straight_length_ft": 120.0}]},         # both ends + handrail
     (111, 902.684022, 4279.121333, 4318.338502)),
    ({"runs": [{"name": "NB", "straight_length_ft": 100.0, "handrail": False,
                "approach_end_block": False, "departure_end_block": False}]},
     (7, 745.828889, 3369.898133, 3472.418935)),
    ({"runs": [{"name": "NB", "straight_length_ft": 90.0,
                "sw_width_ft": 5.0}]},                                # Mod
     (95, 602.852823, 3050.111467, 3117.733839)),
]


@pytest.mark.parametrize("p,expected", CASES)
def test_732sw_output_matches_baseline(p, expected):
    n, cf, lf, wt = _agg(fam.build(p, _ctx()))
    exp_n, exp_cf, exp_lf, exp_wt = expected
    assert n == exp_n
    assert cf == pytest.approx(exp_cf)
    assert lf == pytest.approx(exp_lf)
    assert wt == pytest.approx(exp_wt)
