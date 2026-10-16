"""Type 842 guardrail-transition connection hardware (B11-82A Details A/B/C):
the HSS tubes bolted through an end block plus their galvanized HS bolts.
Estimate-level: HSS as galvanized structural steel paid by weight (LBS, sharp
rect-hollow section x length x 490 pcf); each HSS Element also carries length_ft
for a future LF template but is paid by LBS here. The HSS is billed at the
3'-6" end-block length (``HSS_LEN_FT``): per B11-82A the tubes are block-mounted
connection hardware (bolt group 8"+1'-3-3/4"+10" ~= 2.8' sits within the 3'-6"
block) and do NOT span the 6'-8" sloping->vertical transition -- a documented
basis. Bolts via the Bolt primitive (count EA + galvanized weight incl. nut
allowance). The roadside MGS/thrie-beam run (Plan A77/A79) is a separate roadway
item, out of scope.
"""
from __future__ import annotations

from bimforge.author.model import Element
from bimforge.author.primitives import STEEL_LB_PER_IN3, Bolt

#: name -> (outer height in, outer width in, wall in). Sharp corners (radii
#: omitted -> small documented over-count).
HSS = {
    "2.5x1.5x3/16": (2.5, 1.5, 3.0 / 16.0),
    "2.5x1x1/8": (2.5, 1.0, 1.0 / 8.0),
}

#: 3'-6" end block length (B11-82A); HSS is block-mounted hardware, NOT the
#: 6'-8" transition.
HSS_LEN_FT = 3.5

#: bolt length through the block + a 3" projection for the nut/washer. The 842
#: block is ~1'-2" (14") wide at the connection (B11-82A), so 17" is the
#: conservative through-length -- longer than 732sw's 15" (its block is 1'-0").
_BOLT_LEN_IN = 14.0 + 3.0


def hss_weight_lb(name: str, length_ft: float) -> float:
    h, w, t = HSS[name]
    area_in2 = h * w - (h - 2 * t) * (w - 2 * t)
    return area_in2 * (length_ft * 12.0) * STEEL_LB_PER_IN3


def _hss_element(run: str, name: str, length_ft: float) -> Element:
    return Element(
        f"{run} 842 transition HSS {name}", "IfcMember",
        quantities={"length_ft": float(length_ft),
                    "weight_lb": hss_weight_lb(name, length_ft)},
        layer="S-METL", description=f"HSS{name} transition rail")


def _bolt_element(run: str, dia_in: float, count: int, tag: str) -> Element:
    b = Bolt(f"{run} 842 transition HS bolts {tag}", diameter_in=dia_in,
             length_in=_BOLT_LEN_IN, count=count, nuts=2)
    return Element(
        b.name, "IfcMechanicalFastener",
        quantities={"count": count, "weight_lb": b.weight_lb},
        layer="S-METL",
        description=f'{dia_in:g}" dia galv HS bolt (Tot {count})')


def transition_elements(run: str, *, approach: bool,
                        length_ft: float = HSS_LEN_FT) -> list[Element]:
    """Elements (ready for `model.add`) for one end block's transition
    hardware. Approach (Type AGT, Details A+B): HSS2.5x1.5 + HSS2.5x1 on
    7/8"(x4) + 5/8"(x2) HS bolts. Departure (MGS, Detail C): one HSS2.5x1.5 on
    a 1" HS bolt. The HSS is billed at the 3'-6" block length (``HSS_LEN_FT``)
    by default -- the tubes are block-mounted hardware, not the 6'-8"
    transition span (B11-82A).
    """
    if approach:
        return [
            _hss_element(run, "2.5x1.5x3/16", length_ft),
            _hss_element(run, "2.5x1x1/8", length_ft),
            _bolt_element(run, 7.0 / 8.0, 4, "7/8"),
            _bolt_element(run, 5.0 / 8.0, 2, "5/8"),
        ]
    return [
        _hss_element(run, "2.5x1.5x3/16", length_ft),
        _bolt_element(run, 1.0, 1, "1in"),
    ]
