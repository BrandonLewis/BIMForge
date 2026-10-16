import math
import pytest
from bimforge.author.barrier_section import BarrierSection
from bimforge.author.culvert_headwall_wingwall import (
    flared_wingwall, rail_barrier)

# a representative Type-836-like explicit profile (x transverse, z up, z=0 base;
# traffic-side base corner at max-x). Values in feet.
TABLE = {"barriers": {"836": {"shape": "single_slope", "variants": {"3.0": {
    "profile": [[0.0, 0.0], [0.0, 1.8333], [-0.3333, 1.9167], [-0.3333, 2.8958],
                [-0.2292, 3.0], [0.8542, 3.0], [0.9507, 2.9177], [1.4167, 0.0]],
    "concrete_cf_per_lf": 3.9}}}}}


def _sec():
    return BarrierSection("836", "3.0", TABLE)


def test_flared_wingwall_tapers_and_volume():
    # a plate from the headwall end, splayed 30 deg, 8 ft long, tapering from
    # h_near=6 to h_far=1, thickness 1
    w = flared_wingwall("WW L", x0=0.0, y0=0.0, angle_deg=30.0, length=8.0,
                        h_near=6.0, h_far=1.0, t=1.0, z_base=0.0)
    # per-vertex tapered top: volume = mean height * length * thickness
    assert w.volume_cf == pytest.approx((6.0 + 1.0) / 2.0 * 8.0 * 1.0, rel=1e-6)
    # the top actually tapers (shape assertion)
    assert max(w.top_z) - min(w.top_z) == pytest.approx(5.0)


def _rail_lol():
    a = math.radians(30.0); wl = 8.0; L = 10.0
    lf = (-math.cos(a) * wl, math.sin(a) * wl)
    rf = (L + math.cos(a) * wl, math.sin(a) * wl)
    lol = [lf, (0.0, 0.0), (L, 0.0), rf]
    top = sorted([(lf[0], 1.0), (0.0, 6.0), (L, 6.0), (rf[0], 1.0)])
    return lol, top


def test_rail_is_continuous_across_wings_and_headwall():
    lol, top = _rail_lol()
    bar = rail_barrier("r", lol, top, _sec(), key_index=0, side_sign=1.0, seat=1.0)
    assert bar.volume_cf > 0
    xs = [p[0] for p in bar.base]
    assert min(xs) < -1.0 and max(xs) > 10.0 + 1.0        # spans both free ends


def test_rail_base_rides_the_wall_top_profile():
    lol, top = _rail_lol()
    bar = rail_barrier("r", lol, top, _sec(), key_index=0, side_sign=1.0, seat=1.0)
    zs = [v[2] for sol in bar.body_solids() for v in sol["verts"]]
    assert max(zs) == pytest.approx(6.0 + 3.0, abs=1e-6)  # top at the headwall corners
    assert min(zs) == pytest.approx(1.0, abs=1e-6)        # base at the free ends (no haunch)


def test_rail_battered_face_lays_to_the_normal_side():
    # side_sign=+1 -> right-of-travel normal is -Y on the +x headwall run, so the
    # battered (max-x) face lands on -Y (earth) and the plumb back on +Y (channel).
    lol = [(0.0, 0.0), (10.0, 0.0)]
    top = [(0.0, 6.0), (10.0, 6.0)]
    bar = rail_barrier("r", lol, top, _sec(), key_index=0, side_sign=1.0, seat=0.0)
    ys = [v[1] for sol in bar.body_solids() for v in sol["verts"]]
    assert min(ys) < -1e-6                                 # body reaches the -Y (earth) side


def test_rail_haunch_adds_earth_side_volume_and_drops_the_base():
    lol, top = _rail_lol()
    plain = rail_barrier("r", lol, top, _sec(), seat=1.0)
    haun = rail_barrier("r", lol, top, _sec(), seat=1.0, haunch_ft=1.0)
    assert haun.volume_cf > plain.volume_cf                # the haunch adds concrete
    # haunch drops the earth face 1.0 ft then a 1:1 soffit 0.75 more to the wall,
    # so a free end (base 1.0) reaches 1.0 - 1.75 = -0.75.
    zs = [v[2] for sol in haun.body_solids() for v in sol["verts"]]
    assert min(zs) == pytest.approx(-0.75, abs=1e-6)
