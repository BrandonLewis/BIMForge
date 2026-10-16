"""Type 842 end blocks (B11-81 / B11-82A): the approach and departure blocks
that terminate a run. Each is a tapered concrete solid lofted from the running
(sloping-face) Section A-A profile at the inboard end to the plumb VERTICAL-face
"nose" section at the traffic end -- the sheet's 6'-8" sloping->vertical
transition plus the end block, approximated as ONE linear loft over the 9'-10"
end treatment (an estimate-level under/over-count in the documented spirit of
the family's squared-off chamfers). CF is measured from the emitted triangles
(Qto == geometry), never a parallel hand formula.
"""
from __future__ import annotations

from bimforge.author.barrier_732sw_endblock import _EndBlockSolid
from bimforge.author.barrier_842_rebar import barrier_842_bars
from bimforge.author.type_842_profile import type_842_profile

#: end-treatment length (feet), B11-81 "9'-10"" (6'-8" transition + block).
ENDBLOCK_842_LEN = 9.0 + 10.0 / 12.0


def nose_section(row: dict, *, base_kind: str = "deck") -> list:
    """The plumb VERTICAL-face nose ring the loft tapers to (B11-82 Section
    G-G: the traffic face becomes vertical so the guardrail bolts flat)."""
    return type_842_profile(row, base_kind=base_kind, face="vertical")


def endblock_solid(name: str, row: dict, *, base_kind: str = "deck",
                   y_inboard: float, y_nose: float,
                   ifc: str = "IfcWall",
                   layer: str | None = "S-CONC") -> _EndBlockSolid:
    """Tapered end-block loft; extrusion length is |y_nose - y_inboard|.

    Uses the centroid 4-fan (``fan=True``): the sloping->vertical taper twists
    the traffic-face side quad, and a single diagonal would bias its volume
    ~2.9% high; the 4-fan integrates it to the exact prismatoid CF.
    """
    return _EndBlockSolid(name,
                          type_842_profile(row, base_kind=base_kind,
                                           face="sloping"),
                          nose_section(row, base_kind=base_kind),
                          y_inboard, y_nose, ifc, layer, fan=True)


def endblock_bars(length_ft: float = ENDBLOCK_842_LEN, *, approach: bool) -> list:
    """Developed-length reinforcing estimate for one end block (B11-82A
    Approach End Block Details). Approach uses the heavier Type E-1 schedule
    (#6 traffic face); departure is the lighter all-#5 layout.
    """
    # Base-kind-agnostic by design: a trench (842B) end block gets no footing
    # bars here even though the running section does. This is an intentional
    # conservative-direction sub-percent undercount (footing bars in the two
    # ~9.8' end-block regions omitted); estimate-level, matching the family's
    # documented simplifications.
    height = 3.5                       # bars develop over the 3'-6" stem
    face_size = 6 if approach else 5
    groups = [
        {"mark": "eb-long", "size": 5, "kind": "long", "count": 4},
        {"mark": "eb-long-top", "size": 5, "kind": "long", "count": 12},
        {"mark": "eb-face", "size": face_size, "kind": "vert",
         "spacing_in": 6.0, "length_ft": height},
        {"mark": "eb-stirrup", "size": 5, "kind": "vert",
         "spacing_in": 6.0, "length_ft": height},
    ]
    return barrier_842_bars(length_ft, groups)
