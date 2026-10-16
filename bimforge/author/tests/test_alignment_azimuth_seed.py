import math
import pytest
from bimforge.author.alignment import Alignment


def test_pob_azimuth_seeds_a_leading_curve():
    # a run that STARTS with a curve needs an incoming azimuth; pob["azimuth"]
    # supplies it (0 deg = due north) instead of raising "curve before any
    # tangent".
    al = Alignment(
        {"northing": 0.0, "easting": 0.0, "station": 0.0, "azimuth": 0.0},
        [{"kind": "curve", "delta": 90.0, "radius": 100.0, "turn": "R",
          "length": 100.0 * math.pi / 2.0}])
    n, e, az = al.point_az(0.0)
    assert az == pytest.approx(0.0, abs=1e-6)          # starts due north
    _n, _e, az_end = al.point_az(al.s_end)
    assert az_end == pytest.approx(90.0, abs=1e-6)     # 90 deg right turn


def test_absent_azimuth_still_requires_a_leading_tangent():
    # unchanged legacy behavior: no seed + leading curve still raises
    with pytest.raises(ValueError, match="curve before any tangent"):
        Alignment({"northing": 0.0, "easting": 0.0, "station": 0.0},
                  [{"kind": "curve", "delta": 90.0, "radius": 100.0,
                    "turn": "R", "length": 157.08}])
