"""The road corridor's dictionary classes, dimensions and quantity
Formulas (V1.1; roadmap M.1, M.2, M.3).

Each course, cut, fill and guardrail element is a family-dictionary class
whose Codes are its BIMForge_Dimensions names. A station is a length along
the alignment, so an element's Length is `EndStation - StartStation`, on
curves as on tangents. A course declares its exact volume (loft.pappus):
its section area times the path its centroid travels, so `PathLength *
Width * Thickness` is that volume for a course of constant width, on
tangents, grades and curves, to (kappa g r)^2 / 2 (r the centroid's
distance from the alignment): under the gate's 1e-6 while kappa g r stays
under about 1.4e-3. Through a width transition the trapezoid is exact on a
tangent; on a curve the centroid drifts as the width changes. Each is
written only where the family has checked it holds.
"""
from __future__ import annotations

from bimforge.author.alignment import sta

COURSE = "road-corridor-course"
CUT = "road-corridor-cut"
FILL = "road-corridor-fill"
GUARDRAIL = "road-corridor-guardrail"
LENGTH = "EndStation - StartStation"
VOLUME = "PathLength * Width * Thickness"
TRAPEZOID = "PathLength * (StartWidth + EndWidth) / 2 * Thickness"


def stations(s0: float, s1: float) -> dict:
    """An element's station dimensions: lengths, with their texts."""
    return {"StartStation": s0, "EndStation": s1,
            "StartStationText": sta(s0), "EndStationText": sta(s1)}


def band_mean(stations: list, values: list) -> float:
    """The mean of `values` (one per station) over the band, each bay's
    mean weighted by its length: densified bays are of unequal length."""
    return sum(0.5 * (a + b) * (s1 - s0) for a, b, s0, s1
               in zip(values, values[1:], stations, stations[1:])) / (
        stations[-1] - stations[0])


def course_volume(volume_cf: float, path_ft: float, widths: list,
                  thickness: float) -> tuple:
    """(width dimensions, Volume entry for Element.standard_qto) of a course
    whose combined width is `widths` at its stations: `Width` with VOLUME
    where it is constant, `StartWidth` and `EndWidth` with TRAPEZOID where
    it is not; the Formula only where it is the declared volume within the
    gate's formula tolerance."""
    from bimforge.author.gate import FORMULA_TOLERANCE
    w0, w1 = widths[0], widths[-1]
    if max(widths) - min(widths) <= 1e-9 * max(1.0, max(widths)):
        shape, formula, box = {"Width": w0}, VOLUME, path_ft * w0 * thickness
    else:
        shape, formula = {"StartWidth": w0, "EndWidth": w1}, TRAPEZOID
        box = path_ft * (w0 + w1) / 2.0 * thickness
    if abs(box - volume_cf) <= FORMULA_TOLERANCE * abs(volume_cf):
        return shape, ("volume", volume_cf, formula)
    return shape, ("volume", volume_cf)


#: V1.2 C: the shared-use path's road part, and its rail on a wall
SHARED_USE_PATH = "road-corridor-shared-use-path"
PATH_RAIL = "road-corridor-path-rail"
#: V1.2 C: the equestrian tread's road part, the rail on a wall along it,
#: and the fence on the buffer
EQUESTRIAN_TREAD = "road-corridor-equestrian-tread"
EQUESTRIAN_RAIL = "road-corridor-equestrian-rail"
PATH_FENCE = "road-corridor-path-fence"
