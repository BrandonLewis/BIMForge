"""Caltrans Concrete Barrier Type 842 cross-sections (B11-81/82/82A). A
constant (x, z) profile in FEET, swept along a straight run. x increases
toward the sloping TRAFFIC face; z = 0 at the base datum (top of bridge deck,
or the const joint on a wall/footing), z up.

Where x = 0 is depends on the variant -- read this before placing a ring:
  deck  (842)  -- x = 0 is the EDGE OF DECK. B11-82 view TYPE 842 letters the
                  section from the deck edge: top chain 1/4" | 1'-2" | 6-3/4"
                  = 1'-9" (deck edge -> upper back face -> top face -> base of
                  the traffic face), height 3'-6". The back face STEPS: the
                  upper 1'-2" stands 1/4" in from the deck edge, the lower
                  2'-4" stands 4" in. So no vertex sits at x = 0; the ring is
                  6 vertices, 4.3386 sf. Place x = 0 on the deck edge.
  wall  (842A) -- x = 0 is the barrier's own BACK PLANE, which is also the back
                  of the wall. No 1/4" setback: that 1/4" is clearance from an
                  edge of deck and a wall has none, so the step here is the
                  full 4". Below: 1'-0" of wall, then a 1:1 haunch out to
                  1'-9" (1'-0" + 0'-9"), landing the traffic face's base flush
                  with the haunch's outer edge. 7 vertices, 4.2925 sf.
  trench(842B) -- x = 0 is the barrier's own BACK PLANE, same as 842A. A
                  1'-11" x 2'-6" buried footing CENTRED ON THE STEM -- that
                  centring is what makes 842B's alignment differ from the other
                  two, and it closes exactly: the stem is 1'-9" - 4" = 1'-5" at
                  the construction joint, so the footing overhangs 3" each side
                  (1'-5" + 3" + 3" = 1'-11"). 10 vertices, 9.1545 sf.

Until #307 the deck ring squared the back-face step away into a 4-vertex
trapezoid (5.1406 sf), 18.5 % heavy. The step is not a "reveal": it is 0.80 sf
of section. #320 then read B11-82's 842A/842B views: both carry the same step
(842B dimensions the 4" explicitly), and the sheet's note -- "Type 842A and
Type 842B are similar to Type 842 except as noted", with nothing noting the
back face -- means the THREE VIEWS SHARE ONE STEM SECTION, differing in
reinforcement and in what the stem sits on.

`face="vertical"` returns the section the end-block loft tapers to. Per B11-82
SECTION G-G, "TRANSITION SLOPING FACE TO VERTICAL FACE": the traffic face goes
plumb ON THE TOP FACE LINE -- the base pulls IN, it does not push out -- and
the back-face step daylights out, leaving a plain plumb section (the deck nose
is a 1'-2" x 3'-6" rectangle, 4.0833 sf). G-G letters it `1'-2" | 6-3/4"`, the
6-3/4" running past the section to where the sloping face's base was, with a
single 1/4" on a plumb back.

Done by substitution, so vertex COUNT and ORDER survive: the loft pairs
running<->nose by index, and the two rings must match per variant
(deck=6, wall=7, trench=10). The step's two vertices coincide at the nose, so
the nose ring carries exactly one zero-length edge by design. 1" chamfers and
R-fillets are squared off -- a documented sub-percent simplification matching
the shipped 732SW/836 sharp-corner convention.
"""
from __future__ import annotations

#: governing dims (feet), verified against B11-82. Deck (842) dims are measured
#: from the EDGE OF DECK. The shared-stem dims (_H, _X_TOPSLOPE, _X_BASE_DECK)
#: are overridable per row via stem_h_ft / top_slope_x_ft / base_w_ft, and the
#: deck back-face step via back_x_ft / step_x_ft / step_from_top_ft; the
#: wall/trench dims below are fixed sheet constants (no per-row override --
#: add row.get plumbing if a variant needs it).
_H = 3.5                       # 3'-6" stem height above the base datum
_X_TOPSLOPE = 0.25 / 12.0 + 14.0 / 12.0    # 1/4" + 1'-2" = 1.1875: top of the traffic slope
_X_BASE_DECK = 21.0 / 12.0     # 1'-9" base of the traffic face
_X_BACK_UPPER = 0.25 / 12.0    # deck: upper back face, 1/4" in from the deck edge
_X_BACK_LOWER = 4.0 / 12.0     # deck: lower back face, 4" in from the deck edge
_STEP_FROM_TOP = 14.0 / 12.0   # deck: the back-face step, 1'-2" below the top (2'-4" up)
_X_BASE_WALL = 12.0 / 12.0     # 1'-0" wall base (fixed)
_HAUNCH_TOP_Z = 0.75           # widest point of the wall-variant front face, 1:1 (fixed)
_FOOT_W = 23.0 / 12.0          # 1'-11" trench footing width (fixed)
_FOOT_D = 30.0 / 12.0          # 2'-6" trench footing depth, min (fixed)

def type_842_profile(row: dict, *, base_kind: str = "deck",
                     face: str = "sloping") -> list[tuple[float, float]]:
    if face not in ("sloping", "vertical"):
        raise ValueError(f"type_842_profile: face {face!r} "
                         f"must be 'sloping' or 'vertical'")

    h = float(row.get("stem_h_ft", _H))
    x_top = float(row.get("top_slope_x_ft", _X_TOPSLOPE))
    x_base_deck = float(row.get("base_w_ft", _X_BASE_DECK))

    # The back-face step, shared by all three variants (#307 for deck, #320 for
    # the other two). On the DECK both faces are lettered from the edge of
    # deck, 1/4" and 4", so the step there is their difference; off a deck the
    # barrier's own back plane is x = 0 and the step is the full 4".
    x_up = float(row.get("back_x_ft", _X_BACK_UPPER))
    x_lo = float(row.get("step_x_ft", _X_BACK_LOWER))
    z_step = h - float(row.get("step_from_top_ft", _STEP_FROM_TOP))
    x_step = x_lo               # off a deck: the full 4" from the back plane
    if not (0.0 < z_step < h):
        raise ValueError(
            f"type_842_profile: back-face step elevation {z_step} does not fit "
            f"a {h} ft stem")

    if base_kind == "deck":
        # lower back face -> base -> up the front slope -> across the top ->
        # down the upper back face -> step out to the lower back face (B11-82)
        if not (x_up < x_lo < x_base_deck and x_up < x_top):
            raise ValueError(
                f"type_842_profile: deck back-face step (upper x {x_up}, lower "
                f"x {x_lo}, z {z_step}) does not fit the section")
        x_back_lo, x_back_up = x_lo, x_up
        ring = [(x_lo, 0.0), (x_base_deck, 0.0), (x_top, h), (x_up, h),
                (x_up, z_step), (x_lo, z_step)]
    elif base_kind == "wall":
        # The SAME stem as TYPE 842 (#320) -- the three views share one section
        # and differ in reinforcement and in what the stem sits on. Here x = 0
        # is the barrier's own back plane, which is also the back of the wall:
        # there is no 1/4" setback because that 1/4" is clearance from an edge
        # of deck, and a wall has none. The stem's lower 2'-4" stands 4" in.
        #
        # Below: 1'-0" of wall, then a 1:1 haunch out to 1'-9" -- 1'-0" + 0'-9"
        # -- so the traffic face's base lands flush with the haunch's outer
        # edge, which is the check that pins this frame.
        x_back_lo, x_back_up = x_step, 0.0
        ring = [(x_step, 0.0), (_X_BASE_WALL, 0.0),
                (x_base_deck, _HAUNCH_TOP_Z), (x_top, h),
                (0.0, h), (0.0, z_step), (x_step, z_step)]
    elif base_kind == "trench":
        # The same stem again, carried down to the construction joint at z = 0
        # (no haunch -- 842B has none), over a buried 1'-11" x 2'-6" footing
        # CENTRED ON THE STEM. That centring is what makes 842B's alignment
        # differ from 842's and 842A's, and it closes exactly: the stem is
        # 1'-9" - 4" = 1'-5" wide at the joint, so a 1'-11" footing overhangs
        # 3" each side (1'-5" + 3" + 3" = 1'-11").
        over = (_FOOT_W - (x_base_deck - x_step)) / 2.0
        if over <= 0:
            raise ValueError(
                f"type_842_profile: 1'-11\" footing cannot centre on a "
                f"{x_base_deck - x_step:g} ft stem")
        fx0, fx1 = x_step - over, x_base_deck + over
        x_back_lo, x_back_up = x_step, 0.0
        ring = [(fx0, -_FOOT_D), (fx1, -_FOOT_D), (fx1, 0.0),
                (x_base_deck, 0.0), (x_top, h),
                (0.0, h), (0.0, z_step), (x_step, z_step), (x_step, 0.0),
                (fx0, 0.0)]
    else:
        raise ValueError(f"type_842_profile: base_kind {base_kind!r} must be "
                         f"'deck', 'wall', or 'trench'")

    if face == "vertical":
        # B11-82 SECTION G-G, "TRANSITION SLOPING FACE TO VERTICAL FACE": the
        # traffic face becomes plumb ON THE TOP FACE LINE -- the base pulls IN,
        # it does not push out -- and the back-face step daylights out, leaving
        # a plain plumb section. G-G letters it `1'-2" | 6-3/4"`, the 6-3/4"
        # running PAST the section to where the sloping face's base was, with a
        # single 1/4" on a plumb back.
        #
        # This used to push the top-of-slope vertex OUT to the base line
        # instead, which made the nose 1'-5" wide and kept the step: 5.32292 sf
        # against G-G's 4.08333, about 6.1 cf (0.23 cy) per end block.
        #
        # Substitution, not reconstruction, so vertex COUNT and ORDER survive
        # for every variant -- the end-block loft pairs running<->nose by index.
        # The step's two vertices collapse onto the back plane, so it tapers to
        # nothing across the transition, which is what the sheet shows. Base
        # geometry below the joint (wall, haunch, footing) is untouched.
        swap = {x_base_deck: x_top, x_back_lo: x_back_up}
        ring = [(swap.get(x, x), z) for x, z in ring]
    return ring
