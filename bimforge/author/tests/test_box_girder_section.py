"""author.box_girder_section: parametric CIP box-girder profile."""
import pytest

from bimforge.author.box_girder_section import BoxGirderSection
from bimforge.author.sweep import net_area_centroid, ring_self_intersects


def _sec(**kw):
    p = dict(deck_width=40.0, depth=6.0, overhang=4.0, web_count=3,
             web_thickness=1.0, top_slab=0.75, bot_slab=0.6)
    p.update(kw)
    return BoxGirderSection(**p)


def test_outline_is_deck_down_from_zero():
    s = _sec()
    xs = [p[0] for p in s.outline]
    zs = [p[1] for p in s.outline]
    assert max(xs) == pytest.approx(20.0)      # half of 40 ft, Lt side
    assert min(xs) == pytest.approx(-20.0)
    assert max(zs) == pytest.approx(0.0)       # deck surface is the origin z
    assert min(zs) == pytest.approx(-6.0)      # soffit at -depth
    assert not ring_self_intersects(s.outline)


def test_cell_count_and_void_geometry():
    s = _sec()                                  # 3 webs -> 2 cells
    assert len(s.voids) == 2
    for v in s.voids:
        assert not ring_self_intersects(v)
        vz = [p[1] for p in v]
        # cells sit between top and bottom slab
        assert max(vz) == pytest.approx(-0.75)
        assert min(vz) == pytest.approx(-5.4)   # -(6.0 - 0.6)


def test_area_matches_hand_formula():
    s = _sec()
    # soffit spans web-to-web out-to-out: 40 - 2*4 = 32 ft wide
    gross = 40.0 * 0.75 + 32.0 * 0.6 + 3 * 1.0 * (6.0 - 0.75 - 0.6)
    # cells: 2 bays, each (clear width) x (clear depth)
    clear_w = (32.0 - 3 * 1.0) / 2.0
    cells = 2 * clear_w * (6.0 - 0.75 - 0.6)
    assert s.area_sf == pytest.approx(gross)
    a, _x, _z = net_area_centroid(s.outline, s.voids)
    assert a == pytest.approx(gross)
    assert s.gross_area_sf == pytest.approx(gross + cells)


def test_centroid_is_symmetric_and_below_deck():
    s = _sec()
    _a, x, z = net_area_centroid(s.outline, s.voids)
    assert x == pytest.approx(0.0, abs=1e-9)    # symmetric section
    assert -6.0 < z < 0.0


def test_single_cell_and_solid_slab_degenerate():
    one = _sec(web_count=2)
    assert len(one.voids) == 1
    slab = _sec(web_count=1)                    # no cells: a solid tee
    assert slab.voids == []


def test_param_refusals():
    with pytest.raises(ValueError, match="overhang"):
        _sec(overhang=25.0)                     # overhangs exceed half width
    with pytest.raises(ValueError, match="slab"):
        _sec(top_slab=4.0, bot_slab=4.0)        # slabs consume the depth
    with pytest.raises(ValueError, match="web"):
        _sec(web_count=0)
    with pytest.raises(ValueError, match="web"):
        _sec(web_thickness=12.0)                # webs exceed the soffit width


def test_describe_reports_the_section_actually_built():
    assert "2-cell box" in _sec().describe()
    solid = _sec(web_count=1).describe()
    assert "SOLID section (no cells)" in solid      # the costly-typo tell


def test_zero_overhang_gives_a_clean_rectangle_outline():
    flush = _sec(overhang=0.0)
    assert len(flush.outline) == 4                  # no zero-length edges
    assert flush.soffit_width == pytest.approx(40.0)
    assert not ring_self_intersects(flush.outline)


def test_web_thickness_unvalidated_only_when_it_does_nothing():
    # a solid section ignores web_thickness, so an absurd value is accepted
    _sec(web_count=1, web_thickness=99.0)
    # but the moment it shapes cells it must be positive and must fit
    with pytest.raises(ValueError, match="web_thickness"):
        _sec(web_count=3, web_thickness=0.0)


def test_nonpositive_slabs_and_negative_overhang_refuse():
    with pytest.raises(ValueError, match="slab thicknesses"):
        _sec(top_slab=0.0)
    with pytest.raises(ValueError, match="slab thicknesses"):
        _sec(bot_slab=-0.5)
    with pytest.raises(ValueError, match="negative"):
        _sec(overhang=-1.0)
