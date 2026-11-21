"""road-corridor mass haul (P.6)."""
import pytest

from bimforge.author.corridor.masshaul import HEADER, mass_haul, to_csv

BANDS = [(0.0, 100.0, 2700.0, 0.0), (100.0, 200.0, 0.0, 2160.0)]


def test_the_ordinate_adds_cut_less_the_bank_volume_fill_takes():
    rows = mass_haul(BANDS, shrink=0.2)
    assert [r.cumulative_cy for r in rows] == pytest.approx([100.0, 0.0])
    assert rows[1].fill_cy == pytest.approx(80.0)
    assert rows[1].adjusted_fill_cy == pytest.approx(100.0)
    assert (rows[1].start, rows[1].station) == (100.0, 200.0)


def test_a_balanced_cut_then_fill_ends_near_zero_after_shrink():
    # 5400 cf of cut = 200 CY bank. 4320 cf of fill = 160 CY compacted, which
    # takes 160 / (1 - 0.2) = 200 CY of bank: the ordinate comes back to zero.
    rows = mass_haul([(0.0, 50.0, 5400.0, 0.0), (50.0, 100.0, 0.0, 4320.0)], shrink=0.2)
    assert rows[0].cumulative_cy == pytest.approx(200.0)
    assert rows[1].adjusted_fill_cy == pytest.approx(200.0)
    assert rows[1].cumulative_cy == pytest.approx(0.0, abs=1e-9)


def test_no_shrink_leaves_fill_as_it_is():
    rows = mass_haul([(0.0, 10.0, 540.0, 270.0)], shrink=0.0)
    assert (rows[0].cut_cy, rows[0].adjusted_fill_cy) == pytest.approx((20.0, 10.0))
    assert rows[0].cumulative_cy == pytest.approx(10.0)


@pytest.mark.parametrize("shrink", [-0.1, 1.0, 1.5])
def test_a_shrink_outside_zero_to_one_is_refused(shrink):
    with pytest.raises(ValueError, match="shrink"):
        mass_haul(BANDS, shrink=shrink)


def test_the_csv_has_a_row_per_band():
    lines = to_csv(mass_haul(BANDS, shrink=0.2)).strip().splitlines()
    assert lines[0] == HEADER == "start,station,cut_cy,fill_cy,adjusted_fill_cy,cumulative_cy"
    assert lines[1] == "0.00,100.00,100.000,0.000,0.000,100.000"
    assert lines[2] == "100.00,200.00,0.000,80.000,100.000,0.000"
    assert len(lines) == 3
