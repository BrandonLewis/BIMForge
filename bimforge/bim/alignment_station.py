"""Station an IFC4X3 IfcAlignment: point, plan direction and grade at any
distance along it, in SI metres in the model frame.

This is the evaluator behind the Blender section slider
(:mod:`bimforge.blender.alignment_section`), kept free of `bpy` and of the
rest of bimforge so it ships inside the add-on zip unchanged and runs on the
ifcopenshell that Bonsai bundles. Its only dependency is ifcopenshell.

The alignment's representation curve (IfcGradientCurve, IfcCompositeCurve or
IfcSegmentedReferenceCurve) is evaluated by ifcopenshell's geometry kernel —
the same function that tessellates it — so every horizontal segment type
(LINE, CIRCULARARC, CLOTHOID, ...) and every vertical one is handled
exactly, not by re-deriving the IFC math here. A polyline-only alignment
(IfcPolyline / IfcIndexedPolyCurve, as `alignment.create_as_polyline`
writes) is evaluated by linear interpolation along its vertices.

The kernel works in SI metres whatever the project's length unit, so
distances along here are METRES; stations are reported in the project unit,
from the alignment's first Pset_Stationing referent (0 when it has none).
Station equations are not applied — distance along is mapped to station
linearly from the start station.

Examples:
    import ifcopenshell
    from bimforge.bim.alignment_station import AlignmentStationer, alignments
    f = ifcopenshell.open("bridge.ifc")
    st = AlignmentStationer(f, alignments(f)[0])
    fr = st.frame_at_station(1050.0)
    fr.point, fr.plan_tangent, fr.grade
    st.format_station(fr.station)          # '10+50.00' on a feet project
"""
from __future__ import annotations

import math
from typing import NamedTuple

US_SURVEY_FT_M = 1200.0 / 3937.0
INTL_FT_M = 0.3048


class StationFrame(NamedTuple):
    """The alignment at one distance along it (model frame, metres)."""
    distance: float                         # metres along, from the start
    station: float                          # project length unit
    point: tuple[float, float, float]       # on the profile grade line
    tangent: tuple[float, float, float]     # unit, 3-D (carries the grade)
    plan_tangent: tuple[float, float, float]  # unit, horizontal (z = 0)
    left: tuple[float, float, float]        # unit, horizontal, 90 deg CCW
    grade: float                            # rise / run (0.02 = 2 %)
    azimuth: float                          # degrees clockwise from model +y


def alignments(f) -> list:
    """Every IfcAlignment in the file that has a curve to station along.

    Child alignments (IFC4X3 nests a horizontal-only parent over 3-D
    children) are kept: each is its own stationable curve. Ordered as in the
    file, so the choice is deterministic.
    """
    if not f.schema.upper().startswith("IFC4X3"):
        return []
    return [a for a in f.by_type("IfcAlignment") if _axis_curve(a) is not None]


def _axis_curve(alignment):
    for rep in _representations(alignment):
        if rep.RepresentationIdentifier == "Axis" and rep.Items:
            return rep.Items[0]
    return None


def _representations(product):
    shape = getattr(product, "Representation", None)
    return list(shape.Representations) if shape else []


def _unit_scale(f) -> float:
    import ifcopenshell.util.unit
    return ifcopenshell.util.unit.calculate_unit_scale(f)


def _placement(alignment, scale):
    """The alignment's ObjectPlacement as a 4x4 (rows), translation in m."""
    if alignment.ObjectPlacement is None:
        return None
    import ifcopenshell.util.placement
    m = ifcopenshell.util.placement.get_local_placement(alignment.ObjectPlacement)
    rows = [[float(m[i][j]) for j in range(4)] for i in range(4)]
    for i in range(3):
        rows[i][3] *= scale
    ident = all(abs(rows[i][j] - (i == j)) < 1e-12
                for i in range(4) for j in range(4))
    return None if ident else rows


def station_unit(f) -> str:
    """'ft' or 'm': how stations read on this project.

    A file whose length unit is a foot is a feet project. So is a metre file
    whose IfcMapConversion scales to a feet CRS (bimforge writes SI metres
    with Scale = 3.2808 for a State Plane ftUS grid): its plans and stations
    are in feet even though the IFC is metric.
    """
    scale = _unit_scale(f)
    if abs(scale - US_SURVEY_FT_M) < 1e-6 or abs(scale - INTL_FT_M) < 1e-6:
        return "ft"
    if f.schema.upper().startswith("IFC4"):
        for mc in f.by_type("IfcMapConversion"):
            s = mc.Scale or 1.0
            if abs(s * scale - 1.0 / US_SURVEY_FT_M) < 1e-4 or \
                    abs(s * scale - 1.0 / INTL_FT_M) < 1e-4:
                return "ft"
    return "m"


def metres_to(value_m: float, unit: str) -> float:
    """Metres in 'ft' (US survey) or 'm'."""
    return value_m / US_SURVEY_FT_M if unit == "ft" else value_m


def format_station(value: float, unit: str = "ft", places: int | None = None
                   ) -> str:
    """12+34.56 (feet, 100-ft stations) or 1+234.567 (metres, km stations)."""
    per, width, dp = (100, 2, 2) if unit == "ft" else (1000, 3, 3)
    if places is not None:
        dp = places
    sign = "-" if value < 0 else ""
    q = 10 ** dp                       # integer hundredths: no 99.995 -> 100.00
    ticks = int(round(abs(value) * q))
    whole, rest = divmod(ticks, per * q)
    return f"{sign}{whole}+{rest / q:0{width + (dp + 1 if dp else 0)}.{dp}f}"


class AlignmentStationer:
    """Evaluate one IfcAlignment by distance along or by station."""

    def __init__(self, f, alignment, step: float = 1.0) -> None:
        import ifcopenshell.geom
        from ifcopenshell import ifcopenshell_wrapper as w

        self.file = f
        self.alignment = alignment
        self.name = alignment.Name or f"#{alignment.id()}"
        self.unit_scale = _unit_scale(f)            # project unit -> metres
        self.station_unit = station_unit(f)
        self.start_station = self._start_station()
        curve = _axis_curve(alignment)
        if curve is None:
            raise ValueError(f"alignment {self.name!r} has no Axis curve")
        self.curve = curve
        self._xf = _placement(alignment, self.unit_scale)
        self._poly = None
        if curve.is_a() in ("IfcGradientCurve", "IfcCompositeCurve",
                            "IfcSegmentedReferenceCurve"):
            s = ifcopenshell.geom.settings()
            fn = w.map_shape(s, curve)
            self._eval = w.function_item_evaluator(s, fn)
            self.length = float(fn.length())
        else:
            self._eval = None
            self._poly = self._polyline(curve)
            self.length = self._poly[-1][0]
        self.has_profile = curve.is_a() != "IfcCompositeCurve" and (
            self._poly is None or any(abs(p[1][2]) > 0 for p in self._poly))
        self._step = step

    # ------------------------------------------------------------- stations
    def _start_station(self) -> float:
        try:
            import ifcopenshell.api.alignment as api
            v = api.get_alignment_start_station(self.file, self.alignment)
            return float(v or 0.0)
        except Exception:               # older ifcopenshell, odd nests
            return 0.0

    @property
    def end_station(self) -> float:
        return self.station_at(self.length)

    def station_at(self, distance: float) -> float:
        return self.start_station + distance / self.unit_scale

    def distance_at(self, station: float) -> float:
        return (station - self.start_station) * self.unit_scale

    def format_station(self, station: float, unit: str | None = None) -> str:
        """The station in `unit` ('ft' / 'm'; default the project's)."""
        unit = unit or self.station_unit
        return format_station(self.convert(station, unit), unit)

    def convert(self, value: float, unit: str) -> float:
        """A project-unit length (station, elevation) in 'ft' or 'm'."""
        return metres_to(value * self.unit_scale, unit)

    def elevation_m(self, z: float) -> float:
        """Model-frame z (metres) as a true elevation in metres.

        The model frame sits at the IfcMapConversion's OrthogonalHeight
        (in map units, which are project units / Scale), so a bimforge file
        with its base at elevation 200 ft reports 200 ft at model z = 0.
        """
        for mc in self.file.by_type("IfcMapConversion") if \
                self.file.schema.upper().startswith("IFC4") else []:
            oh = mc.OrthogonalHeight or 0.0
            return z + oh * self.unit_scale / (mc.Scale or 1.0)
        return z

    # --------------------------------------------------------------- frames
    def frame(self, distance: float) -> StationFrame:
        d = min(max(float(distance), 0.0), self.length)
        if self._eval is not None:
            p, t = self._kernel(d)
        else:
            p, t = self._interp(d)
        if self._xf is not None:
            p, t = _apply(self._xf, p, 1.0), _apply(self._xf, t, 0.0)
        h = math.hypot(t[0], t[1])
        if h < 1e-12:
            raise ValueError(f"alignment {self.name!r} is vertical at {d} m")
        pt = (t[0] / h, t[1] / h, 0.0)
        n = math.sqrt(t[0] ** 2 + t[1] ** 2 + t[2] ** 2)
        return StationFrame(
            distance=d, station=self.station_at(d), point=tuple(p),
            tangent=(t[0] / n, t[1] / n, t[2] / n), plan_tangent=pt,
            left=(-pt[1], pt[0], 0.0), grade=t[2] / h,
            azimuth=math.degrees(math.atan2(pt[0], pt[1])) % 360.0)

    def frame_at_station(self, station: float) -> StationFrame:
        return self.frame(self.distance_at(station))

    def frame_at_fraction(self, u: float) -> StationFrame:
        return self.frame(u * self.length)

    def points(self, step: float | None = None) -> list[tuple]:
        """The curve sampled every `step` metres (and at both ends)."""
        step = step or self._step
        n = max(1, int(math.ceil(self.length / step)))
        return [self.frame(self.length * i / n).point for i in range(n + 1)]

    def _kernel(self, d):
        m = self._eval.evaluate(d)
        return ((m[0][3], m[1][3], m[2][3]), (m[0][0], m[1][0], m[2][0]))

    # ------------------------------------------------- polyline alignments
    def _polyline(self, curve):
        k = self.unit_scale
        if curve.is_a("IfcPolyline"):
            pts = [tuple(p.Coordinates) for p in curve.Points]
        elif curve.is_a("IfcIndexedPolyCurve"):
            pts = [tuple(c) for c in curve.Points.CoordList]
        else:
            raise NotImplementedError(
                f"alignment {self.name!r}: cannot station a {curve.is_a()}")
        pts = [(p[0] * k, p[1] * k, (p[2] if len(p) > 2 else 0.0) * k)
               for p in pts]
        out, d = [(0.0, pts[0])], 0.0
        for a, b in zip(pts, pts[1:]):
            step = math.hypot(b[0] - a[0], b[1] - a[1])   # horizontal, as IFC
            if step > 0:
                d += step
                out.append((d, b))
        if len(out) < 2:
            raise ValueError(f"alignment {self.name!r} has no length")
        return out

    def _interp(self, d):
        poly = self._poly
        lo, hi = 0, len(poly) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if poly[mid][0] <= d:
                lo = mid
            else:
                hi = mid
        (d0, a), (d1, b) = poly[lo], poly[hi]
        u = (d - d0) / (d1 - d0)
        p = tuple(a[i] + u * (b[i] - a[i]) for i in range(3))
        t = tuple(b[i] - a[i] for i in range(3))
        return p, t


def _apply(m, v, w):
    return tuple(sum(m[i][j] * v[j] for j in range(3)) + m[i][3] * w
                 for i in range(3))
