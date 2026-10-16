import pytest
from bimforge.author.barrier_section import BarrierSection
from bimforge.author.barrier_rebar import barrier_bars

TABLE = {"barriers": {"type_60": {"shape": "single_slope", "variants": {
    "32": {"height_ft": 2.667, "base_width_ft": 2.0, "top_width_ft": 0.667,
           "concrete_cf_per_lf": 3.556,
           "bars": {"longitudinal": {"size": 5, "count": 6},
                    "ties": {"size": 4, "spacing_in": 12}}}}}}}


def test_longitudinal_bars_run_full_length():
    sec = BarrierSection("type_60", "32", TABLE)
    bars = barrier_bars(sec, TABLE["barriers"]["type_60"]["variants"]["32"],
                        run_length=100.0, cover_in=2.0)
    longs = [b for b in bars if b.mark == "long"]
    assert len(longs) == 6
    assert all(b.size == 5 for b in longs)
    assert all(b.length == pytest.approx(100.0) for b in longs)


def test_ties_count_at_spacing_and_positive_length():
    sec = BarrierSection("type_60", "32", TABLE)
    bars = barrier_bars(sec, TABLE["barriers"]["type_60"]["variants"]["32"],
                        run_length=100.0, cover_in=2.0)
    ties = [b for b in bars if b.mark == "tie"]
    # bar_stations(0, 100, 1.0) -> 101 stations
    assert len(ties) == 101
    assert all(b.size == 4 for b in ties)
    assert all(b.length > 0 for b in ties)


def test_tie_length_matches_perimeter_formula():
    from bimforge.author.primitives import RebarBuilder
    sec = BarrierSection("type_60", "32", TABLE)
    hook = RebarBuilder(size=4, cover_in=2.0, spacing_in=12.0).hook
    bars = barrier_bars(sec, TABLE["barriers"]["type_60"]["variants"]["32"],
                        run_length=50.0, cover_in=2.0)
    ties = [b for b in bars if b.mark == "tie"]
    expected = sec.perimeter_ft - 8.0 * (2.0 / 12.0) + 2.0 * hook
    assert ties[0].length == pytest.approx(expected)
    assert expected > 0


def test_longitudinal_total_length_is_count_times_run():
    sec = BarrierSection("type_60", "32", TABLE)
    bars = barrier_bars(sec, TABLE["barriers"]["type_60"]["variants"]["32"],
                        run_length=50.0, cover_in=2.0)
    longs = [b for b in bars if b.mark == "long"]
    assert sum(b.length for b in longs) == pytest.approx(6 * 50.0)
