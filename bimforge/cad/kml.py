"""A small, reusable KML builder.

Builder scripts each hand-rolled their own KML string assembly — repeating the
same ``<Style>`` / ``<Folder>`` / ``<Placemark>`` boilerplate and XML
escaping. This module unifies them behind a builder.

It is pure stdlib (only :func:`xml.sax.saxutils.escape`): it deals purely in
lon/lat/altitude coordinates and never projects. Feed it geographic coordinates
directly, or project State Plane -> WGS84 first with :mod:`bimforge.cad.geo`.
See also :mod:`bimforge.bim.kml` for the IFC-to-KML converter.

Example::

    from bimforge.cad.kml import KMLDocument, Style

    doc = KMLDocument("My Bridge", "From the 100% plans")
    doc.add_style(Style("deck", line_color="ff0000ff", line_width=2,
                        poly_color="553c14dc"))
    f = doc.folder("Deck")
    f.polygon("Deck slab", [(-120.84, 37.92), (-120.84, 37.921), ...],
              style="deck", description="126' x 32'")
    open("bridge.kml", "w", encoding="utf-8").write(doc.to_string())

Colors are KML ``aabbggrr`` hex (alpha, blue, green, red), matching the source
scripts (e.g. ``"ff00aaff"`` is opaque orange).

Coordinates print with 8 decimals of lon/lat and 2 of altitude by default;
``KMLDocument(..., xy_digits=9, z_digits=4)`` raises that for detailed meshes,
whose small triangles can otherwise collapse below three unique printed points
(Google Earth drops such rings).

Placemarks accept ``timespan=("2026-07-10", None)`` for Google Earth's time
slider (begin-only or begin+end), and ``Folder.multipolygon`` groups many
polygon rings into one placemark (one IFC element's triangles, say).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Union
from xml.sax.saxutils import escape

#: A coordinate is ``(lon, lat)`` or ``(lon, lat, altitude_metres)``.
Coord = Union[tuple[float, float], tuple[float, float, float]]


def _fmt_coord(c: Coord, xy: int = 8, z: int = 2) -> str:
    """Format one coordinate tuple as ``lon,lat,alt`` (alt defaults to 0),
    with ``xy`` decimals of lon/lat and ``z`` decimals of altitude."""
    if len(c) == 2:
        return f"{c[0]:.{xy}f},{c[1]:.{xy}f},0"
    return f"{c[0]:.{xy}f},{c[1]:.{xy}f},{c[2]:.{z}f}"


def _coords(pts: Sequence[Coord], xy: int = 8, z: int = 2) -> str:
    """Join coordinates into a KML ``<coordinates>`` payload."""
    return " ".join(_fmt_coord(c, xy, z) for c in pts)


@dataclass
class Style:
    """A KML shared style (line, polygon, and/or icon).

    Only the sub-elements whose inputs are set are emitted, so a line-only style
    produces just a ``<LineStyle>``.
    """

    id: str
    line_color: Optional[str] = None      # aabbggrr
    line_width: float = 1.0
    poly_color: Optional[str] = None      # aabbggrr; None => no fill color
    poly_fill: bool = True
    poly_outline: bool = True
    icon_color: Optional[str] = None
    icon_scale: Optional[float] = None
    icon_href: Optional[str] = None
    label_scale: Optional[float] = None

    def to_xml(self) -> str:
        parts = [f'  <Style id="{self.id}">']
        if self.line_color is not None:
            parts.append(
                f"<LineStyle><color>{self.line_color}</color>"
                f"<width>{self.line_width:g}</width></LineStyle>"
            )
        if self.poly_color is not None or not self.poly_fill or not self.poly_outline:
            poly = "<PolyStyle>"
            if self.poly_color is not None:
                poly += f"<color>{self.poly_color}</color>"
            poly += f"<fill>{1 if self.poly_fill else 0}</fill>"
            poly += f"<outline>{1 if self.poly_outline else 0}</outline></PolyStyle>"
            parts.append(poly)
        if self.icon_color is not None or self.icon_scale is not None or self.icon_href:
            icon = "<IconStyle>"
            if self.icon_color is not None:
                icon += f"<color>{self.icon_color}</color>"
            if self.icon_scale is not None:
                icon += f"<scale>{self.icon_scale:g}</scale>"
            if self.icon_href:
                icon += f"<Icon><href>{escape(self.icon_href)}</href></Icon>"
            icon += "</IconStyle>"
            parts.append(icon)
        if self.label_scale is not None:
            parts.append(f"<LabelStyle><scale>{self.label_scale:g}</scale></LabelStyle>")
        parts.append("</Style>")
        return "".join(parts)


class Folder:
    """A named group of placemarks inside a :class:`KMLDocument`."""

    def __init__(self, name: str, xy_digits: int = 8, z_digits: int = 2):
        self.name = name
        self.xy_digits, self.z_digits = xy_digits, z_digits
        self._items: list[str] = []

    def _c(self, pts: Sequence[Coord]) -> str:
        return _coords(pts, self.xy_digits, self.z_digits)

    def _placemark(self, name: str, style: Optional[str], geom: str,
                   description: str = "",
                   timespan: Optional[tuple[str, Optional[str]]] = None) -> str:
        style_url = f"<styleUrl>#{style}</styleUrl>" if style else ""
        desc = f"<description>{escape(description)}</description>" if description else ""
        ts = ""
        if timespan:
            begin, end = timespan
            ts = f"<TimeSpan><begin>{escape(str(begin))}</begin>"
            if end:
                ts += f"<end>{escape(str(end))}</end>"
            ts += "</TimeSpan>"
        return (f"    <Placemark><name>{escape(name)}</name>{desc}{ts}{style_url}"
                f"{geom}</Placemark>\n")

    def point(self, name: str, coord: Coord, style: Optional[str] = None,
              description: str = "", absolute: bool = False,
              timespan: Optional[tuple[str, Optional[str]]] = None) -> "Folder":
        """Add a ``<Point>`` placemark. Returns self for chaining."""
        alt = "<altitudeMode>absolute</altitudeMode>" if absolute else ""
        geom = f"<Point>{alt}<coordinates>{_fmt_coord(coord, self.xy_digits, self.z_digits)}</coordinates></Point>"
        self._items.append(self._placemark(name, style, geom, description, timespan))
        return self

    def line(self, name: str, coords: Sequence[Coord], style: Optional[str] = None,
             description: str = "", tessellate: bool = True,
             absolute: bool = False,
             timespan: Optional[tuple[str, Optional[str]]] = None) -> "Folder":
        """Add a ``<LineString>`` placemark through ``coords``."""
        mode = ("<altitudeMode>absolute</altitudeMode>" if absolute
                else f"<tessellate>{1 if tessellate else 0}</tessellate>")
        geom = (f"<LineString>{mode}"
                f"<coordinates>{self._c(coords)}</coordinates></LineString>")
        self._items.append(self._placemark(name, style, geom, description, timespan))
        return self

    def polygon(self, name: str, ring: Sequence[Coord], style: Optional[str] = None,
                description: str = "", tessellate: bool = True,
                absolute: bool = False, close: bool = True,
                timespan: Optional[tuple[str, Optional[str]]] = None) -> "Folder":
        """Add a ``<Polygon>`` placemark from an outer boundary ``ring``.

        If ``close`` is true and the ring is not already closed, the first point
        is appended so the ``LinearRing`` closes.
        """
        pts = list(ring)
        if close and pts and pts[0] != pts[-1]:
            pts = pts + [pts[0]]
        mode = ("<altitudeMode>absolute</altitudeMode>" if absolute
                else f"<tessellate>{1 if tessellate else 0}</tessellate>")
        geom = (f"<Polygon>{mode}<outerBoundaryIs><LinearRing>"
                f"<coordinates>{self._c(pts)}</coordinates>"
                f"</LinearRing></outerBoundaryIs></Polygon>")
        self._items.append(self._placemark(name, style, geom, description, timespan))
        return self

    def multipolygon(self, name: str, rings: Sequence[Sequence[Coord]],
                     style: Optional[str] = None, description: str = "",
                     tessellate: bool = True, absolute: bool = False,
                     close: bool = True,
                     timespan: Optional[tuple[str, Optional[str]]] = None
                     ) -> "Folder":
        """ONE placemark holding a ``<MultiGeometry>`` of polygons — e.g. an
        IFC element's triangles or box faces as a single selectable feature.
        Each ring is closed like :meth:`polygon`; empty ``rings`` yields an
        empty MultiGeometry."""
        mode = ("<altitudeMode>absolute</altitudeMode>" if absolute
                else f"<tessellate>{1 if tessellate else 0}</tessellate>")
        polys = []
        for ring in rings:
            pts = list(ring)
            if close and pts and pts[0] != pts[-1]:
                pts = pts + [pts[0]]
            polys.append(f"<Polygon>{mode}<outerBoundaryIs><LinearRing>"
                         f"<coordinates>{self._c(pts)}</coordinates>"
                         f"</LinearRing></outerBoundaryIs></Polygon>")
        geom = f"<MultiGeometry>{''.join(polys)}</MultiGeometry>"
        self._items.append(self._placemark(name, style, geom, description,
                                           timespan))
        return self

    def to_xml(self) -> str:
        return (f"  <Folder><name>{escape(self.name)}</name>\n"
                f"{''.join(self._items)}  </Folder>\n")


class KMLDocument:
    """Assembles styles and folders into a complete KML document."""

    def __init__(self, name: str, description: str = "", *,
                 xy_digits: int = 8, z_digits: int = 2):
        self.name = name
        self.description = description
        self.xy_digits, self.z_digits = xy_digits, z_digits
        self._styles: list[Style] = []
        self._folders: list[Folder] = []

    def add_style(self, style: Style) -> "KMLDocument":
        """Register a shared :class:`Style`. Returns self for chaining."""
        self._styles.append(style)
        return self

    def folder(self, name: str) -> Folder:
        """Create and register a :class:`Folder`, returning it to fill in."""
        f = Folder(name, self.xy_digits, self.z_digits)
        self._folders.append(f)
        return f

    def to_string(self) -> str:
        """Render the full KML document as a string."""
        styles = "".join(s.to_xml() + "\n" for s in self._styles)
        body = "".join(f.to_xml() for f in self._folders)
        desc = (f"  <description>{escape(self.description)}</description>\n"
                if self.description else "")
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2">\n<Document>\n'
            f"  <name>{escape(self.name)}</name>\n"
            f"{desc}{styles}{body}"
            "</Document>\n</kml>\n"
        )
