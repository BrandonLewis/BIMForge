import math

from bimforge.author import rail_section as rs


def test_hollow_area_matches_section_formula():
    # HSS3x2x3/16: outer 3x2 in, wall 0.1875 in; inner (3-2t)x(2-2t).
    b, d, t = 3.0, 2.0, 0.1875
    expect_in2 = b * d - (b - 2 * t) * (d - 2 * t)
    assert rs.area_sf("HSS3x2x3/16") == expect_in2 / 144.0


def test_hollow_ring_is_outer_plus_one_void_centred():
    outer, voids = rs.hollow_ring("HSS2x2x3/16", 0.0, 1.0)
    assert len(voids) == 1
    # outer is 2in = 1/6 ft square centred at (0, 1.0)
    xs = [p[0] for p in outer]
    zs = [p[1] for p in outer]
    assert math.isclose(max(xs) - min(xs), 2.0 / 12.0)
    assert math.isclose((max(zs) + min(zs)) / 2.0, 1.0)
    # void is inner square, smaller by 2t on each axis
    inner = voids[0]
    ixs = [p[0] for p in inner]
    assert math.isclose(max(ixs) - min(ixs), (2.0 - 2 * 0.1875) / 12.0)


def test_unknown_size_fails_loud():
    import pytest
    with pytest.raises(KeyError):
        rs.hollow_ring("HSS9x9x9/16")


def test_b11_51_config_two_rails_top_is_payment():
    cfg = rs.CONFIG_B11_51
    assert len(cfg.rails) == 2
    top = [r for r in cfg.rails if r.is_payment]
    assert len(top) == 1
    assert top[0].size == "HSS3x2x3/16"
    assert math.isclose(cfg.height_ft, 16.0 / 12.0)
    assert cfg.post_size == "HSS2x2x3/16"
