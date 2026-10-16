"""Convert a georeferenced est-bim IFC into 3D KML for Google Earth.

Reads the IFC's IfcMapConversion + IfcProjectedCRS, triangulates every product
with ifcopenshell.geom, maps model metres onto the projected CRS
(E_crs = Eastings + x_model * Scale), reprojects to WGS84 with pyproj, and
writes each element as a KML Placemark of absolute-altitude polygons,
colour-coded by IFC class and grouped into folders by classification
(cost code), falling back to the IFC class.

Assumes a CORRECT IfcMapConversion as written by `dxf2bim` in this version:
Eastings/Northings are the base in CRS units and Scale converts model metres
to CRS units. IFCs written by estimating_tools <= 0.1.10 carried a broken
georeference (the CRS base was subtracted from metre coordinates without unit
conversion), which leaves model coordinates in the millions of metres; those
files are detected and rejected — regenerate them with this version.

Altitudes are the vertical half of the same mapping: model Z plus the
IfcMapConversion OrthogonalHeight, converted to metres. The house convention
keeps geometry near the model origin and carries the site datum in
OrthogonalHeight, so ignoring it buried the high-elevation bridge 2440 ft underground
(issue #134). On top of that, Google Earth reads absolute altitude as height
above the EGM96 geoid while a US plan-set model is NAVD88, so pass
``vshift_m`` — derived with `bimforge.terrain.datum.geoid_shift_m` — for the
local geoid separation (decimetres; NOT a unit conversion). The two shifts
add; the returned ``vshift_m`` is the total actually applied.

Requires the `bim` extra (ifcopenshell, pyproj).

Document assembly uses `bimforge.cad.kml`'s builder (shared per-class styles,
one MultiGeometry placemark per element).
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import ifcopenshell
import ifcopenshell.geom
from pyproj import Transformer

from bimforge.bim.georef import read_map_conversion

# |model coordinate| beyond this is not plausible for a properly-based model
# in metres; it is the signature of the <= 0.1.10 georeferencing bug.
_LEGACY_COORD_LIMIT_M = 1e6

COLORS = {  # KML aabbggrr
    "IfcSlab": "ff9bb5d1",      # concrete tan-grey
    "IfcWall": "ffb0c4c9",
    "IfcFooting": "ff8fa3ad",
    "IfcPile": "ff4a6a8a",      # steel-brown
    "IfcRailing": "ff2f4fd1",   # red-orange
    "IfcCovering": "ff5a8a5a",  # rock green-grey
}


def _group_of(prod) -> str:
    """Folder label: classification code(s) when present, else IFC class.
    A multi-classified element (issue #106: furnish + drive on one pile)
    shows every code so the label agrees with the takeoff rows it feeds.
    Deduped by code (first name wins) and sorted by code, so elements with
    the same code set share one folder regardless of association order."""
    by_code: dict[str, str] = {}
    for rel in getattr(prod, "HasAssociations", []) or []:
        if rel.is_a("IfcRelAssociatesClassification"):
            ref = rel.RelatingClassification
            code = getattr(ref, "Identification", None) or getattr(ref, "ItemReference", None)
            label = getattr(ref, "Name", None)
            if code and str(code) not in by_code:
                by_code[str(code)] = f"{code} — {label}" if label else str(code)
    if not by_code:
        return prod.is_a()
    return " + ".join(by_code[c] for c in sorted(by_code))


def _box_rings(pts, lonlat) -> list[list[tuple[float, float, float]]]:
    """Six bounding-box faces as (lon, lat, alt) rings (massing view: one
    block per element instead of its full triangle mesh — orders of magnitude
    smaller; Google Earth chokes on per-triangle KML for a detailed bridge).
    Axis-aligned in model space, so the block aligns with the structure grid.
    Empty geometry yields no rings — matching the non-massing path's empty
    MultiGeometry rather than raising on min()/max()."""
    if not pts:
        return []
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    zs = [p[2] for p in pts]
    x0, x1, y0, y1, z0, z1 = min(xs), max(xs), min(ys), max(ys), min(zs), max(zs)
    quads = [
        [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0)],   # bottom
        [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)],   # top
        [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)],   # front
        [(x0, y1, z0), (x1, y1, z0), (x1, y1, z1), (x0, y1, z1)],   # back
        [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)],   # left
        [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)],   # right
    ]
    rings = []
    for q in quads:
        ring = []
        for x, y, z in q:
            lon, lat = lonlat(x, y)
            ring.append((lon, lat, z))
        rings.append(ring)
    return rings


def ifc_to_kml(ifc_path, out_path=None, *, schedule: bool = False,
               massing: bool = False, vshift_m: float | None = None,
               precision: tuple[int, int] = (8, 2), omit: str | None = None,
               drop_degenerate: bool = False) -> dict:
    """Write the KML next to the IFC (or at `out_path`).

    Returns {"out": Path, "elements": n, "groups": n, "timed": n,
    "vshift_m": the total altitude shift applied, "datum_height_m": the part
    of it that came from IfcMapConversion.OrthogonalHeight, "placemarks": n,
    "vertices": printed coordinates incl. ring closures, "omitted": [names],
    "degenerate_dropped": n}. Raises
    ValueError for a non-georeferenced IFC or one carrying the legacy
    (<= 0.1.10) broken georeference.

    With `schedule=True`, each element assigned to a scheduled task (a
    slice-2 `est-bim schedule` embed) gets a KML `<TimeSpan>` beginning at
    its earliest task's ScheduleStart, so Google Earth's time slider plays
    the construction staging; unscheduled elements stay untimed (always
    visible). `timed` counts the elements that got a TimeSpan.

    With `massing=True`, each element is drawn as its bounding-box block
    instead of its full triangle mesh — the staging view for detailed models
    whose per-triangle KML is too large for Google Earth to open (a real
    bridge is millions of triangles / gigabytes; massing is a few MB and the
    right level of detail for watching volumes appear over time).

    With `vshift_m`, every emitted altitude is shifted by that many metres ON
    TOP of the datum height — the NAVD88 -> EGM96 vertical-datum correction
    (derive the value with `bimforge.terrain.datum.geoid_shift_m`). The
    default None applies the datum height alone.

    `precision` is (lon/lat decimals, altitude decimals) for the printed
    coordinates. `omit` is a regex on element names: matching elements are
    left out (reference-only geometry such as an existing-ground mesh, which
    z-fights Google Earth's own terrain); a folder they empty is not written.
    With `drop_degenerate`, a triangle whose ring has fewer than three unique
    PRINTED coordinates is dropped (Google Earth discards such rings anyway).
    """
    ifc_path = Path(ifc_path)
    if not ifc_path.is_file():
        raise OSError(f"no such IFC file: {ifc_path}")
    out = Path(out_path) if out_path else ifc_path.with_suffix(".kml")

    model = ifcopenshell.open(str(ifc_path))
    starts = {}
    if schedule:
        from bimforge.bim.schedule_read import element_start_dates
        starts = element_start_dates(model)
    georef = read_map_conversion(model)
    base_e, base_n, scale = georef.base_e, georef.base_n, georef.scale
    tfm = Transformer.from_crs(f"EPSG:{georef.epsg}", "EPSG:4326", always_xy=True)

    # The VERTICAL half of the georeference, which this converter used to drop
    # on the floor (issue #134). OrthogonalHeight is the site datum in MAP
    # units, and one map unit is `unit_scale / Scale` metres (1 file unit =
    # unit_scale metres = Scale map units) — so this is the exact vertical
    # analogue of the `base_e + x * Scale` mapping `lonlat` does horizontally.
    #
    # It is not optional, because the house convention deliberately keeps
    # geometry near the model origin and carries the datum HERE: authoring
    # true elevations into model Z instead puts the geometry hundreds of
    # metres from the origin, where Bonsai's default view never frames it and
    # the model reads as empty. Before this, doing the right thing for the
    # IFC broke the KML — the high-elevation bridge came out 2440 ft underground.
    from ifcopenshell.util.unit import calculate_unit_scale
    datum_m = georef.height * calculate_unit_scale(model) / scale
    # `vshift_m` keeps its meaning — the NAVD88 -> EGM96 geoid correction —
    # and ADDS to the datum height; the two answer different questions.
    total_vshift_m = datum_m + (vshift_m or 0.0)

    from bimforge.cad.kml import KMLDocument, Style
    from bimforge.cad.stylepack import resolve_style_pack
    kml_styles = resolve_style_pack().styles.get("kml") or {}
    colors = {**COLORS, **(kml_styles.get("colors") or {})}

    settings = ifcopenshell.geom.settings()

    def lonlat(x_m: float, y_m: float) -> tuple[float, float]:
        # Correct IFC4 MapConversion: CRS coordinate = base + model * Scale.
        return tfm.transform(base_e + x_m * scale, base_n + y_m * scale)

    # group -> [(display name, style id, rings, timespan)] — assembled into
    # the KMLDocument after the loop so folders come out in sorted order.
    groups: dict[str, list] = defaultdict(list)
    style_ids: dict[str, str] = {}          # color -> shared style id
    counts = 0
    timed = 0
    xy_d, z_d = precision
    omit_re = re.compile(omit) if omit else None
    omitted: list[str] = []
    dropped = 0
    vertices = 0
    from bimforge.cad.kml import _fmt_coord
    for prod in model.by_type("IfcProduct"):
        if not prod.Representation:
            continue
        if omit_re and omit_re.search(prod.Name or ""):
            omitted.append(prod.Name)
            continue
        try:
            # Local geometry + a per-shape placement multiply, deliberately NOT
            # the `use-world-coords` setting: world-coords is unnecessary here
            # — the per-shape matrix (shape.transformation.matrix) is applied
            # by hand below / baked by the serializer, so default (local
            # coords) settings already give us what we need.
            shape = ifcopenshell.geom.create_shape(settings, prod)
        except Exception:
            continue
        verts = shape.geometry.verts  # flat [x y z ...] metres, local coords
        faces = shape.geometry.faces  # flat triangle indices
        mt = shape.transformation.matrix  # column-major 4x4, last column = T

        def world(i: int) -> tuple[float, float, float]:
            x, y, z = verts[i * 3], verts[i * 3 + 1], verts[i * 3 + 2]
            return (
                mt[0] * x + mt[4] * y + mt[8] * z + mt[12],
                mt[1] * x + mt[5] * y + mt[9] * z + mt[13],
                mt[2] * x + mt[6] * y + mt[10] * z + mt[14],
            )

        pts = [world(i) for i in range(len(verts) // 3)]
        for x, y, _z in pts:
            if abs(x) > _LEGACY_COORD_LIMIT_M or abs(y) > _LEGACY_COORD_LIMIT_M:
                raise ValueError(
                    f"{prod.is_a()} '{prod.Name}' sits at |model coordinate| > 1e6 m — "
                    "this IFC was written with the broken pre-0.1.11 georeferencing "
                    "(base subtracted without unit conversion); regenerate the IFC "
                    "with est-bim >= 0.1.11")
        if total_vshift_m:
            # Datum height + any geoid correction; both the mesh and massing
            # paths take their altitudes from pts, so one shift covers both.
            pts = [(x, y, z + total_vshift_m) for x, y, z in pts]
        if massing:
            rings = _box_rings(pts, lonlat)
        else:
            rings = []
            for f in range(0, len(faces), 3):
                tri = [pts[faces[f]], pts[faces[f + 1]], pts[faces[f + 2]]]
                ring = []
                for x, y, z in tri:
                    lon, lat = lonlat(x, y)
                    ring.append((lon, lat, z))
                rings.append(ring)
        if drop_degenerate:
            kept = [r for r in rings
                    if len({_fmt_coord(c, xy_d, z_d) for c in r}) >= 3]
            dropped += len(rings) - len(kept)
            rings = kept
        # printed coordinates: the builder closes every open ring
        vertices += sum(len(r) + (1 if r and r[0] != r[-1] else 0) for r in rings)
        cls = prod.is_a()
        color = colors.get(cls, "ffaaaaaa")
        sid = style_ids.setdefault(color, f"c-{color}")
        name = prod.Name or f"{cls} {prod.GlobalId[:6]}"
        begin = starts.get(prod.id())
        if begin:
            timed += 1
        groups[_group_of(prod)].append(
            (name, sid, rings, ((begin, None) if begin else None)))
        counts += 1

    doc = KMLDocument(ifc_path.stem, xy_digits=xy_d, z_digits=z_d)
    for color in sorted(style_ids):
        doc.add_style(Style(style_ids[color], line_color="66000000",
                            line_width=1, poly_color=color))
    for group in sorted(groups):
        folder = doc.folder(group)
        for name, sid, rings, timespan in groups[group]:
            folder.multipolygon(name, rings, style=sid, absolute=True,
                                timespan=timespan)
    out.write_text(doc.to_string(), encoding="utf-8")
    return {"out": out, "elements": counts, "groups": len(groups),
            "timed": timed, "vshift_m": total_vshift_m,
            "datum_height_m": datum_m, "placemarks": counts,
            "vertices": vertices, "omitted": omitted,
            "degenerate_dropped": dropped}
