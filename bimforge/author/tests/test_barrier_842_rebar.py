import pytest

from bimforge.author.barrier_842_rebar import barrier_842_bars


def test_longitudinal_bars_run_full_length():
    bars = barrier_842_bars(20.0, [
        {"mark": "long", "size": 5, "kind": "long", "count": 12}])
    assert len(bars) == 12
    for b in bars:
        assert b.length == pytest.approx(20.0)
        assert b.weight == pytest.approx(20.0 * 1.043, rel=1e-3)   # #5 = 1.043 plf


def test_vertical_bars_step_at_spacing():
    bars = barrier_842_bars(20.0, [
        {"mark": "stir", "size": 5, "kind": "vert",
         "spacing_in": 8.0, "length_ft": 4.0}])
    # bar_stations(0, 20, 8/12) inclusive -> 31 stations
    assert len(bars) == 31
    assert all(b.length == pytest.approx(4.0) for b in bars)


def test_unknown_kind_fails_loud():
    with pytest.raises(ValueError, match="unknown bar kind"):
        barrier_842_bars(10.0, [{"mark": "x", "size": 5, "kind": "diagonal"}])
