import pytest

from bimforge.author.alignment import poly_area
from bimforge.author.type_842_profile import type_842_profile


def _closed_simple(ring, *, degenerate_edges=0):
    """>= 4 points and no consecutive duplicates.

    `degenerate_edges` allows an exact count of zero-length edges. The VERTICAL
    (nose) rings have exactly one by design: the back-face step collapses onto
    the back plane there, so its two vertices coincide. Keeping them -- rather
    than dropping to a shorter ring -- is what lets the end-block loft pair
    running<->nose BY INDEX, and makes the step taper to nothing across the
    transition, which is what B11-82 SECTION G-G shows.
    """
    assert len(ring) >= 4
    dupes = sum(1 for a, b in zip(ring, ring[1:] + ring[:1]) if a == b)
    assert dupes == degenerate_edges, f"{dupes} zero-length edges in {ring}"


def test_deck_profile_shape_and_area():
    # B11-82 TYPE 842, x from the EDGE OF DECK (#307): the back face steps from
    # 1/4" in (upper 1'-2") to 4" in (lower 2'-4"); toe 1'-9", top slope 1.1875.
    ring = type_842_profile({}, base_kind="deck", face="sloping")
    _closed_simple(ring)
    assert len(ring) == 6
    xs = [x for x, _z in ring]
    zs = [z for _x, z in ring]
    assert min(zs) == pytest.approx(0.0)
    assert max(zs) == pytest.approx(3.5)            # 3'-6" tall
    assert min(xs) == pytest.approx(0.25 / 12)      # upper back face, 1/4" in
    assert max(xs) == pytest.approx(1.75)           # 1'-9" base
    base_back = min(x for x, z in ring if abs(z) < 1e-9)
    assert base_back == pytest.approx(4.0 / 12)     # lower back face, 4" in
    step_z = sorted({z for x, z in ring if 0.0 < z < 3.5})
    assert step_z == [pytest.approx(3.5 - 14.0 / 12)]   # step 1'-2" below top
    # hand: the old 5.140625 trapezoid (plumb back face AT the deck edge) less
    # the 4" x 2'-4" lower notch and the 1/4" x 1'-2" upper strip
    expect = 5.140625 - (4.0 / 12) * (28.0 / 12) - (0.25 / 12) * (14.0 / 12)
    assert poly_area(ring) == pytest.approx(expect, rel=1e-12)
    assert poly_area(ring) == pytest.approx(4.3385, abs=1e-4)   # issue #307


def test_deck_ring_is_ccw_like_the_other_variants():
    ring = type_842_profile({}, base_kind="deck", face="sloping")
    signed = sum(a[0] * b[1] - b[0] * a[1]
                 for a, b in zip(ring, ring[1:] + ring[:1])) / 2
    assert signed > 0


def test_deck_step_overrides_and_validation():
    ring = type_842_profile({"step_x_ft": 0.5, "step_from_top_ft": 1.0},
                            base_kind="deck")
    assert min(x for x, z in ring if abs(z) < 1e-9) == pytest.approx(0.5)
    assert sorted({z for _x, z in ring if 0.0 < z < 3.5}) == [pytest.approx(2.5)]
    # the step follows a Mod stem height: still 1'-2" below the top
    tall = type_842_profile({"stem_h_ft": 4.0}, base_kind="deck")
    assert sorted({z for _x, z in tall if 0.0 < z < 4.0}) == [pytest.approx(4.0 - 14.0 / 12)]
    with pytest.raises(ValueError, match="back-face step"):
        type_842_profile({"step_x_ft": 2.0}, base_kind="deck")
    with pytest.raises(ValueError, match="back-face step"):
        type_842_profile({"step_from_top_ft": 4.0}, base_kind="deck")


def test_wall_profile_narrows_to_one_foot_base():
    ring = type_842_profile({}, base_kind="wall", face="sloping")
    _closed_simple(ring)
    xs = [x for x, _z in ring]
    # front face reaches its widest (1.75) mid-height, then a 1:1 haunch
    # brings the base in to the 1'-0" wall:
    assert max(xs) == pytest.approx(1.75)
    base_pts = [x for x, z in ring if abs(z) < 1e-9]
    assert max(base_pts) == pytest.approx(1.0)      # 1'-0" base at the wall
    assert poly_area(ring) < 5.140625               # less concrete than deck


def test_trench_profile_adds_a_footing_CENTRED_on_the_stem():
    """#320. The footing is 1'-11" x 2'-6" and is CENTRED on the stem, which is
    what makes 842B's alignment differ from 842's and 842A's. It closes exactly:
    the stem is 1'-9" - 4" = 1'-5" wide at the construction joint, so a 1'-11"
    footing overhangs 3" each side. 1'-5" + 3" + 3" = 1'-11".

    It used to be modelled flush with a full-height plumb back face, so its
    right edge sat at 1'-11" and nothing hung off the back at all.
    """
    ring = type_842_profile({}, base_kind="trench", face="sloping")
    _closed_simple(ring)
    zs = [z for _x, z in ring]
    assert min(zs) == pytest.approx(-2.5)           # 2'-6" footing below datum

    foot = [x for x, z in ring if z == pytest.approx(-2.5)]
    assert max(foot) - min(foot) == pytest.approx(23.0 / 12)    # 1'-11" wide

    # FOUR points meet at the joint, in x order: the footing's two top corners
    # and, between them, the stem's back and front. The outer pair is the
    # footing top, the inner pair the stem.
    joint = sorted(x for x, z in ring if abs(z) < 1e-9)
    assert len(joint) == 4, joint
    f0, s0, s1, f1 = joint
    assert f1 - f0 == pytest.approx(23.0 / 12)                  # footing top, 1'-11"
    assert s1 - s0 == pytest.approx(17.0 / 12)                  # stem, 1'-5"
    assert s0 - f0 == pytest.approx(0.25)                       # 3" behind
    assert f1 - s1 == pytest.approx(0.25)                       # 3" in front
    # centred, stated the other way: the two midpoints coincide
    assert (f0 + f1) / 2 == pytest.approx((s0 + s1) / 2)
    assert poly_area(ring) > poly_area(
        type_842_profile({}, base_kind="deck"))     # stem + footing


def test_vertical_face_is_the_plumb_1ft2_section_section_g_g_letters():
    """#320. B11-82 SECTION G-G, "TRANSITION SLOPING FACE TO VERTICAL FACE":
    the traffic face goes plumb ON THE TOP FACE LINE -- the base pulls IN -- and
    the back-face step daylights out, leaving a plain 1'-2" plumb rectangle with
    a single 1/4" on the back. G-G letters it `1'-2" | 6-3/4"`, the 6-3/4"
    running past the section to where the sloping face's base was.

    This used to push the top-of-slope vertex OUT to the base line instead,
    making the nose 1'-5" wide and keeping the step: 5.32292 sf against G-G's
    4.08333, which is ~6.1 cf (0.23 cy) of concrete per end block.
    """
    ring = type_842_profile({}, base_kind="deck", face="vertical")
    _closed_simple(ring, degenerate_edges=1)        # the collapsed step
    top_front = max(x for x, z in ring if abs(z - 3.5) < 1e-9)
    base_front = max(x for x, z in ring if abs(z) < 1e-9)
    assert top_front == pytest.approx(base_front)   # vertical, no batter
    assert top_front == pytest.approx(0.25 / 12 + 14.0 / 12)   # ON the top line
    # and the back is plumb at 1/4" -- the step is gone, not merely plumbed
    back = [x for x, _z in ring if x < 1.0]
    assert min(back) == pytest.approx(0.25 / 12)
    assert max(back) == pytest.approx(0.25 / 12)
    assert poly_area(ring) == pytest.approx(
        (14.0 / 12) * 3.5, rel=1e-12)               # a plain 1'-2" x 3'-6"


def test_vertical_deck_pairs_with_sloping_by_index():
    # the end-block loft pairs running<->nose vertices BY INDEX (#307: deck=6)
    slope = type_842_profile({}, base_kind="deck", face="sloping")
    vert = type_842_profile({}, base_kind="deck", face="vertical")
    assert len(vert) == len(slope) == 6
    moved = [i for i, (a, b) in enumerate(zip(slope, vert)) if a != b]
    # #320: three vertices move, and each one is a face going plumb --
    # 0 and 5 are the lower back face collapsing onto the back plane, 1 is the
    # traffic face's base pulling in to the top line. 2, 3 and 4 already sit on
    # the two plumb lines and stay put.
    assert moved == [0, 1, 5]
    assert vert[1] == (pytest.approx(0.25 / 12 + 14.0 / 12), pytest.approx(0.0))
    assert vert[0] == (pytest.approx(0.25 / 12), pytest.approx(0.0))
    assert vert[3] == (pytest.approx(0.25 / 12), pytest.approx(3.5))
    assert vert[4] == vert[5]                       # the collapsed step


def test_vertical_wall_preserves_vertex_count_and_plumbs_upper_face():
    slope = type_842_profile({}, base_kind="wall", face="sloping")
    vert = type_842_profile({}, base_kind="wall", face="vertical")
    assert len(vert) == len(slope)                  # same n-gon for the loft
    base_pts = [x for x, z in vert if abs(z) < 1e-9]
    assert max(base_pts) == pytest.approx(1.0)      # base still the 1'-0" wall
    top_front = max(x for x, z in vert if abs(z - 3.5) < 1e-9)
    # #320: plumb ON THE TOP FACE LINE, per SECTION G-G -- was 1.75.
    #
    # That line is `_X_TOPSLOPE` = 1/4" + 1'-2" = 1.1875, shared with the deck.
    # On the deck it is measured from the edge of deck; here x = 0 is the
    # barrier's own back plane, so the top face reads 1'-2 1/4" rather than the
    # sheet's 1'-2". Keeping the shared constant preserves the lettered 6-3/4"
    # traffic-face run (1.75 - 1.1875) and 842A's 1'-0" + 0'-9" = 1'-9" haunch
    # closure; shifting it to a flat 1'-2" would break both by the same 1/4".
    # A ~0.3% question, flagged on #320 rather than silently resolved.
    assert top_front == pytest.approx(1.1875)


def test_vertical_trench_preserves_vertex_count_and_footing():
    slope = type_842_profile({}, base_kind="trench", face="sloping")
    vert = type_842_profile({}, base_kind="trench", face="vertical")
    assert len(vert) == len(slope)                  # 6-gon <-> 6-gon
    assert min(z for _x, z in vert) == pytest.approx(-2.5)   # footing preserved


def test_unknown_base_kind_fails_loud():
    with pytest.raises(ValueError, match="base_kind"):
        type_842_profile({}, base_kind="floating", face="sloping")


def test_unknown_base_kind_fails_loud_even_for_vertical_face():
    with pytest.raises(ValueError, match="base_kind"):
        type_842_profile({}, base_kind="floating", face="vertical")


# --- #320: one stem, three bases ---------------------------------------------

def _back_step(ring, h=3.5):
    """(upper face x, lower face x, step elevation) read off a ring."""
    z_step = max(z for _x, z in ring if 0.0 < z < h)
    upper = min(x for x, z in ring if z == pytest.approx(h))
    # both step vertices share z_step; the lower FACE is the outer of the two
    lower = max(x for x, z in ring if z == pytest.approx(z_step))
    return upper, lower, z_step


def test_all_three_variants_carry_the_back_face_step():
    """B11-82's note is 'Type 842A and Type 842B are similar to Type 842 except
    as noted', and nothing notes the back face: the three views share ONE stem
    section and differ in reinforcement and in what the stem sits on. Before
    #320 only `deck` stepped, so 842A ran 15.3% heavy and 842B 10.3%.
    """
    for kind in ("deck", "wall", "trench"):
        upper, lower, z_step = _back_step(type_842_profile({}, base_kind=kind))
        assert z_step == pytest.approx(3.5 - 14.0 / 12), (
            f"{kind}: the step must sit 1'-2\" below the top")
        assert lower - upper == pytest.approx(
            (4.0 / 12) if kind != "deck" else (4.0 - 0.25) / 12), (
            f"{kind}: back-face step is {(lower - upper) * 12:.3f} in")


def test_the_quarter_inch_is_a_deck_edge_clearance_and_only_deck_has_one():
    """On the DECK both faces are lettered from the edge of deck -- `¼"` and
    `4"` -- so the barrier's back plane sits ¼" inboard and the step is their
    difference, 3¾". A wall or a footing has no edge to clear, so there x = 0
    IS the back plane and the step is the full 4"."""
    deck_up, _, _ = _back_step(type_842_profile({}, base_kind="deck"))
    assert deck_up == pytest.approx(0.25 / 12)
    for kind in ("wall", "trench"):
        up, _, _ = _back_step(type_842_profile({}, base_kind=kind))
        assert up == pytest.approx(0.0), f"{kind} should sit on its own back plane"


def test_the_wall_haunch_closes_on_the_traffic_face():
    """842A's check: 1'-0" of wall plus 0'-9" of 1:1 haunch is 1'-9", so the
    traffic face's base lands flush with the haunch's outer edge. That is what
    pins the wall variant's frame."""
    ring = type_842_profile({}, base_kind="wall")
    base = [x for x, z in ring if abs(z) < 1e-9]
    assert max(base) == pytest.approx(1.0)              # 1'-0" wall
    widest = max(x for x, _z in ring)
    assert widest == pytest.approx(1.75)                # 1'-9" at the haunch
    haunch_z = [z for x, z in ring if x == pytest.approx(1.75)][0]
    assert widest - max(base) == pytest.approx(haunch_z)   # 1:1
