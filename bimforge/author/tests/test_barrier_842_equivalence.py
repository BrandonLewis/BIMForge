"""Regression guard for the concrete-barrier-842 template refactor.

During the refactor this suite proved `fam.build` (the new build_barrier path)
byte-identical to `fam._build_legacy` (the pre-refactor code) across these cases;
`_build_legacy` has since been deleted. To keep the exact-output property guarded
now that the legacy oracle is gone, each case asserts its aggregate output totals
(element count + summed volume_cf / length_ft / weight_lb) against committed
baselines captured from the proven-equivalent build. Any drift in element count
or a per-element quantity shifts a total and trips this guard; the family suite
(test_concrete_barrier_842.py) covers the meaningful invariants behind them.
"""
import pytest

from bimforge.author.families import concrete_barrier_842 as fam
from bimforge.author.project import ProjectContext


def _ctx():
    return ProjectContext.from_spec({
        "name": "t", "epsg": 2226, "base": [0.0, 0.0],
        "guid_ns": "6f0e5a1a-0000-4000-8000-000000000042"})


def _agg(model):
    """(element count, Σvolume_cf, Σlength_ft, Σweight_lb) — a compact,
    informative-on-failure fingerprint of the whole model's quantities."""
    return (
        len(model.elements),
        sum(e.quantities.get("volume_cf", 0.0) for e in model.elements),
        sum(e.quantities.get("length_ft", 0.0) for e in model.elements),
        sum(e.quantities.get("weight_lb", 0.0) for e in model.elements),
    )


# params -> (count, Σcf, Σlf, Σwt) baselines from the byte-identical build.
# #307 re-baselined the three DECK cases' Σcf (the B11-82 back-face step:
# 5.140625 -> 4.338542 sf of running section, and the end blocks loft from it).
# #320 then read B11-82's 842A/842B views and re-baselined the remaining two:
# all three variants share ONE stem section, so the wall and trench rings carry
# the same step (5.070312 -> 4.292535 and 10.205729 -> 9.154514 sf), and 842B's
# footing is CENTRED on the stem rather than flush with its back face.
# #320 also corrected the NOSE the end blocks loft to (B11-82 SECTION G-G: the
# traffic face goes plumb on the TOP face line and the back step daylights out,
# 5.322917 -> 4.083333 sf), so every case WITH an end block drops again. Case
# p1 is start/end "none" -- no end blocks -- and is the control: it does not
# move here, which is how you can tell this baseline shift is the nose and not
# the running section.
# Throughout, counts, LF and rebar weight are unchanged -- only concrete moves.
CASES = [
    ({"runs": [{"name": "NB", "straight_length_ft": 120.0,
                "start_end": "approach", "end_end": "departure"}]},
     (21, 518.115451, 2924.333333, 3010.693256)),
    ({"runs": [{"name": "NB", "straight_length_ft": 100.0,
                "start_end": "none", "end_end": "none"}]},
     (5, 433.854167, 2294.500000, 2288.863500)),
    ({"runs": [{"name": "NB", "straight_length_ft": 60.0, "base_kind": "wall",
                "start_end": "approach", "end_end": "none"}]},
     (14, 256.536314, 1465.666667, 1534.958552)),
    ({"runs": [{"name": "NB", "straight_length_ft": 80.0, "base_kind": "trench",
                "start_end": "approach", "end_end": "departure"}]},
     (23, 730.329572, 2608.916667, 2723.433672)),
    ({"runs": [{"name": "NB", "straight_length_ft": 100.0,
                "start_end": "approach", "end_end": "approach"}]},   # same-kind
     (23, 431.344618, 2470.333333, 2609.954104)),
]


@pytest.mark.parametrize("p,expected", CASES)
def test_842_output_matches_baseline(p, expected):
    n, cf, lf, wt = _agg(fam.build(p, _ctx()))
    exp_n, exp_cf, exp_lf, exp_wt = expected
    assert n == exp_n
    assert cf == pytest.approx(exp_cf)
    assert lf == pytest.approx(exp_lf)
    assert wt == pytest.approx(exp_wt)
