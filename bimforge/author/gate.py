"""The validation gate (spec §5): pre-emit refuse-to-write, post-emit
verify-and-delete.

Pre-emit built-ins (all run, all failures reported together):
  * lxw-volume     — every classified element carrying the full L/W/H/volume
                     quantity set has Count x L x W x H reproduce its
                     GrossVolume (the bridge-pilot §3a invariant `push-takeoff`
                     depends on); elements measured by Count or weight
                     legitimately lack those keys and are skipped;
  * arc-faceting   — every geometry carrying a faceted counterpart stays
                     within FACET_TOLERANCE of its closed form (the check
                     that caught the 1.7% arc error); covers both the
                     fabrication-domain volume_in3/faceted_volume_in3 pair
                     and the sweep engine's volume_cf/faceted_volume_cf;
  * classification — every element is classified or DELIBERATELY reference
                     ([]); every code used exists in the paycodes table;
  * stated-qty     — the model's `stated_quantities` closed-form assertions
                     (got vs an independently stated figure, NOT x == x);
  * local-coords   — geometry sits near the model ORIGIN, not at raw survey
                     coordinates or true elevation. Volume is
                     translation-invariant, so this is the only pre-emit
                     check able to see it (issue #156).

Family/script checks: `model.checks` callables plus anything passed in
`extra_checks`. Each is (model) -> list[str] of failure messages.

Post-emit: reopen what was written and verify — IFC mesh volumes vs analytic
(ifcopenshell.geom ITERATOR; per-product create_shape silently returns EMPTY
meshes and must not be used — pipe-supports-pilot lesson), IFC spatial-decomposition
reachability (Project -> Site -> Building -> Storey; the ONLY check that
looks at the file the way a third-party importer does — issue #132),
takeoff-map <-> classification coverage (multi-code aware), DXF entity
sanity. Failure DELETES the outputs and reports.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from bimforge.author.primitives import FACET_TOLERANCE

#: Post-emit mesh-vs-analytic tolerance (tessellation is the only slack).
MESH_TOLERANCE = 0.005


@dataclass
class GateReport:
    failures: list[str] = field(default_factory=list)
    checks_run: int = 0

    @property
    def passed(self) -> bool:
        return not self.failures

    def extend(self, msgs) -> None:
        self.failures.extend(msgs)

    def format(self, phase: str = "pre") -> str:
        head = ("validation gate passed"
                if self.passed else
                f"VALIDATION GATE FAILED ({phase}-emit) - nothing written:"
                if phase == "pre" else
                f"POST-EMIT GATE FAILED - outputs deleted:")
        lines = [head] + [f"  - {f}" for f in self.failures]
        lines.append(f"  ({self.checks_run} checks run)")
        return "\n".join(lines)


# ------------------------------------------------------------- pre built-ins
def check_lxw_volume(model) -> list[str]:
    fail = []
    for el in model.elements:
        if not el.classifications:
            continue
        q = el.quantities
        need = ("length_ft", "width_ft", "height_ft", "volume_cf")
        if not all(k in q for k in need):
            continue
        n = q.get("count", 1) or 1
        got = n * q["length_ft"] * q["width_ft"] * q["height_ft"]
        want = q["volume_cf"]
        if want > 1e-9 and abs(got - want) / want > 1e-6:
            fail.append(f"{el.name}: count x L x W x H = {got:.6f} cf does not "
                        f"reproduce GrossVolume {want:.6f} cf")
    return fail


def check_arc_faceting(model, tol: float = FACET_TOLERANCE) -> list[str]:
    fail = []
    for el in model.elements:
        geoms = el.geometry if isinstance(el.geometry, (list, tuple)) else [el.geometry]
        for g in geoms:
            for exact_key, facet_key in (("volume_in3", "faceted_volume_in3"),
                                         ("volume_cf", "faceted_volume_cf")):
                exact = getattr(g, exact_key, None)
                faceted = getattr(g, facet_key, None)
                if exact is None or faceted is None:
                    continue
                if exact and abs(faceted - exact) / exact > tol:
                    # swept sections face by station bays, not arc segments,
                    # so the segment count is reported only when it exists
                    segs = getattr(g, "arc_segments", None)
                    at = f" at {segs} segments" if segs is not None else ""
                    fail.append(
                        f"{el.name}: faceting error "
                        f"{abs(faceted - exact) / exact:.4%} exceeds "
                        f"{tol:.2%}{at}")
    return fail


def check_classification(model, paycodes=None) -> list[str]:
    fail = []
    for el in model.elements:
        for code in el.classifications:
            if paycodes is not None and code not in paycodes.codes:
                fail.append(f"{el.name}: code {code!r} not in the paycodes table")
    if paycodes is not None and not model.codes_used():
        fail.append("no element carries any pay code - a model that pays "
                    "nothing is a wiring error, not a takeoff")
    return fail


def check_stated_quantities(model) -> list[str]:
    fail = []
    for label, got, want, tol in model.stated_quantities:
        if abs(got - want) > tol:
            fail.append(f"{label}: computed {got:.4f} != stated {want} "
                        f"(tolerance {tol})")
    return fail


def check_stated_orientations(model) -> list[str]:
    """Assert each declared SIGNED handedness scalar keeps its expected sign.

    The check no scalar-magnitude check could be: a MIRRORED swept section has
    identical area and volume, so check_lxw_volume, check_stated_quantities and
    _ifc_mesh_check all pass on a shape that is geometrically backwards (the
    #251 mirror-wedge, caught only by a human in Bonsai). A family computes an
    orientation scalar that FLIPS SIGN under a mirror — e.g. the direction a
    section's reference edge slopes, or a signed cross-product of two landmark
    edges — and declares the sign it must hold. A value within `tol` of zero is
    ambiguous (neither hand) and fails rather than silently satisfy either."""
    fail = []
    for label, value, expected_sign, tol in model.stated_orientations:
        if abs(value) <= tol:
            fail.append(f"{label}: orientation scalar {value:.4f} is within "
                        f"tolerance {tol} of zero — degenerate/ambiguous "
                        f"handedness")
        elif (value > 0) != (expected_sign > 0):
            want = "+" if expected_sign > 0 else "-"
            fail.append(f"{label}: orientation scalar {value:.4f} has the "
                        f"wrong sign (expected {want}) — a mirrored/flipped "
                        f"section")
    return fail


#: Largest plausible |model coordinate|, feet (~19 miles). A structure model
#: is authored LOCAL to its project base — the datum rides in
#: IfcMapConversion, not in every vertex. State Plane eastings run 1e6-1e7 ft
#: and true elevations 1e2-1e4 ft, so this separates "a long corridor" from "a
#: survey coordinate leaked into the geometry" with orders of magnitude spare.
LOCAL_COORD_LIMIT_FT = 1e5


def _solid_points(d):
    """Yield representative (x, y, z) points a solids dict contributes.

    Extremes are not needed — a survey coordinate is off by six orders of
    magnitude, so one point per feature localizes the element beyond doubt.
    A GENERATOR on purpose: the caller only iterates, and a terrain `mesh`
    can carry six figures of vertices that would otherwise be copied into a
    throwaway list on every pre-emit run.
    """
    kind = d.get("kind")
    if kind in ("prism", "fill"):
        z = d.get("z_bot", 0.0)
        for u, v in d.get("base", ()):
            yield u, v, z
        for h in d.get("holes", ()) or ():
            for u, v in h:
                yield u, v, z
    elif kind == "mesh":
        yield from d.get("verts", ())          # already (x, y, z)
    elif kind == "swept_disk":
        yield from d.get("verts", ())          # bar directrix, already (x, y, z)
    elif kind == "ribbon":
        yield from d.get("points", ())         # centreline, already (x, y, z)
    elif kind == "box":
        for b in d.get("boxes", ()):
            yield b[0], b[1], b[2]
    elif kind == "rod":
        yield from d.get("centres", ())
    elif kind == "tube":
        yield d.get("x0", 0.0), d.get("y0", 0.0), d.get("cz", 0.0)
    elif kind == "arc_band":
        yield d.get("cx", 0.0), 0.0, d.get("cz", 0.0)
    elif kind == "gusset":
        # a gusset keys its X off each entry in `placements`, NOT a `cx`
        # key — reading cx scored every gusset at the origin and let a
        # far-flung one straight through this gate (PR #157 review).
        cz = d.get("cz", 0.0)
        for cx, ring_uv in d.get("placements", ()):
            for u, v in ring_uv:
                yield cx, u, cz + v


def check_local_coordinates(model, limit_ft: float = LOCAL_COORD_LIMIT_FT):
    """Every element's geometry sits within `limit_ft` of the model origin.

    The check no other check could be. Volume is translation-invariant, so a
    model authored at raw State Plane coordinates — or at true elevation
    rather than relative to the datum — passes lxw, faceting,
    mesh-vs-analytic and STEP true-volume without a murmur (issue #156:
    `bridge_standard` put all 11 elements ~2,009,887 m from the origin;
    issue #134: the high-elevation bridge authored at 2440 ft elevation). The only symptom was
    `est-bim kml` refusing the file, and misattributing it when it did.

    It matters because a viewer's default view never frames geometry that far
    out — the model reads as EMPTY, the same end state #132 and #133 produced
    by other routes — and single-precision graphics pipelines lose visible
    resolution there. Fail at build time, naming the fix.
    """
    fail = []
    for el in model.elements:
        geoms = (el.geometry if isinstance(el.geometry, (list, tuple))
                 else [el.geometry])
        place = (el.x_ft, el.y_ft, el.z_ft)
        worst, axis = 0.0, "x"
        for i, p in enumerate(place):
            if abs(p) > worst:
                worst, axis = abs(p), "xyz"[i]
        for g in geoms:
            if hasattr(g, "body_solids"):
                dicts = g.body_solids()
            elif isinstance(g, dict):
                dicts = [g]
            else:
                continue
            for d in dicts:
                scale = 1.0 if d.get("units", "ft") == "ft" else 1.0 / 12.0
                for pt in _solid_points(d):
                    for i, c in enumerate(pt):
                        v = abs(c * scale + place[i])
                        if v > worst:
                            worst, axis = v, "xyz"[i]
        if worst > limit_ft:
            fail.append(
                f"{el.name}: {axis} reaches {worst:,.0f} ft from the model "
                f"origin (limit {limit_ft:,.0f}) — survey coordinates or true "
                "elevations look baked into the geometry. Author LOCAL to the "
                "project base (ctx.local) and let IfcMapConversion carry the "
                "datum; a viewer never frames geometry this far out and reads "
                "the model as empty.")
    return fail


BUILTINS = (check_lxw_volume, check_arc_faceting, check_stated_quantities,
            check_stated_orientations, check_local_coordinates)


def run_pre(model, paycodes=None, extra_checks=()) -> GateReport:
    """Run every pre-emit check; ANY failure blocks ALL writes."""
    rep = GateReport()
    for chk in BUILTINS:
        rep.extend(chk(model))
        rep.checks_run += 1
    rep.extend(check_classification(model, paycodes))
    rep.checks_run += 1
    for chk in tuple(model.checks) + tuple(extra_checks):
        rep.extend(chk(model))
        rep.checks_run += 1
    return rep


# ------------------------------------------------------------ post built-ins
def _exact_sweep_names(ifc_path: str) -> set:
    """Products whose Body is an IfcSectionedSolidHorizontal."""
    import ifcopenshell
    f = ifcopenshell.open(str(ifc_path))
    if not f.schema_identifier.upper().startswith("IFC4X3"):
        return set()
    return {i.Name for i in f.by_type("IfcProduct") if i.Representation
            and any(it.is_a("IfcSectionedSolidHorizontal")
                    for r in i.Representation.Representations
                    for it in r.Items)}


def _ifc_mesh_check(model, ifc_path: str, tol: float) -> list[str]:
    from bimforge.bim.ifc_mesh import mesh_leg
    got: dict[str, float] = {}
    for info in mesh_leg(str(ifc_path)).values():
        got[info["name"]] = got.get(info["name"], 0.0) + info["mesh"]["volume_m3"]
    # ifcopenshell 0.9 draws an IfcSectionedSolidHorizontal with its caps
    # doubled and a stray cap inside (IfcOpenShell#9820), so the shell is not
    # closed and its "volume" depends on where the solid sits — not a check.
    # _ifc_exact_sweep_check verifies those elements instead.
    exact = _exact_sweep_names(ifc_path)
    fail = []
    m_per_ft = model.ctx.ft_to_m
    for el in model.elements:
        want_cf = el.quantities.get("volume_cf")
        if not want_cf or el.name not in got or el.name in exact:
            continue
        want_m3 = want_cf * m_per_ft ** 3
        err = abs(got[el.name] - want_m3) / want_m3
        if err > tol:
            fail.append(f"{el.name}: IFC mesh volume {got[el.name]:.6f} m3 is "
                        f"{err:.4%} off analytic {want_m3:.6f} m3 (tol {tol:.2%})")
    return fail


#: how far an engine's drawing of an exact sweep may stray from the true
#: swept surface, feet (5 mm). Measured: 0.02 mm on a plan-only directrix,
#: under 1.5 mm with a vertical curve (ifcopenshell's gradient evaluation).
#: A wrong side, datum or station mapping is off by feet.
EXACT_SWEEP_TOL_FT = 0.005 / 0.3048
#: relative tolerance on the swept wall area (measured agreement: 0.01%)
EXACT_SWEEP_AREA_TOL = 0.005


def _quiet_stdout():
    """Silence C++ writes to fd 1 for the duration: ifcopenshell 0.9 dumps
    debug topology for every IfcSectionedSolidHorizontal it draws
    (IfcOpenShell#9820), pages of it per sweep."""
    import contextlib
    import os
    import sys

    @contextlib.contextmanager
    def quiet():
        sys.stdout.flush()
        try:
            saved = os.dup(1)
        except OSError:                     # no real fd 1 (embedded host)
            yield
            return
        try:
            with open(os.devnull, "w") as null:
                os.dup2(null.fileno(), 1)
                yield
        finally:
            os.dup2(saved, 1)
            os.close(saved)
    return quiet()


def _tessellate_item(st, item, matrix, k):
    """(verts in model feet, tris) of one representation item, moved by its
    product's placement `matrix` (metres)."""
    import ifcopenshell.geom
    import numpy as np
    g = ifcopenshell.geom.create_shape(st, item)
    v = np.asarray(g.verts, float).reshape(-1, 3)
    v = (v @ matrix[:3, :3].T + matrix[:3, 3]) / k
    fc = g.faces
    return ([tuple(p) for p in v.tolist()],
            [(fc[i], fc[i + 1], fc[i + 2]) for i in range(0, len(fc), 3)])


def _closed_volume(verts, tris) -> float:
    return abs(sum(
        (verts[a][0] * (verts[b][1] * verts[c][2] - verts[b][2] * verts[c][1])
         - verts[a][1] * (verts[b][0] * verts[c][2] - verts[b][2] * verts[c][0])
         + verts[a][2] * (verts[b][0] * verts[c][1] - verts[b][1] * verts[c][0]))
        for a, b, c in tris) / 6.0)


def _ifc_exact_sweep_check(model, ifc_path: str,
                           tol: float = MESH_TOLERANCE) -> list[str]:
    """Every exact alignment sweep is drawn where its SweptSection is (#332).

    Stands in for the volume check, which ifcopenshell 0.9 cannot give for
    this entity (IfcOpenShell#9820). Each IfcSectionedSolidHorizontal item is
    paired, in order, with the exact sweep the element's solids carry
    (primitives.exact_of — so a raw dict, a wrapper or a list of sweeps all
    count) and measured four ways, none of which needs a closed shell:
    every tessellated vertex lies on the true swept surface; the vertices
    span exactly the sweep's stations; every cap lies in a section plane, so
    no section leans; and the swept wall area matches the sweep's own mesh,
    so no wall (outer or void) is missing. With the shapes
    proven, the element's declared volume must be its sweeps' closed forms
    plus its other items' drawn volumes, within `tol` — the leg the volume
    check carried for these elements.
    """
    import ifcopenshell
    import ifcopenshell.geom
    import ifcopenshell.util.placement as up
    from bimforge.author.emit_ifc import body_dicts
    from bimforge.author.primitives import exact_of
    exact = _exact_sweep_names(ifc_path)
    if not exact:
        return []
    f = ifcopenshell.open(str(ifc_path))
    st = ifcopenshell.geom.settings()
    k = model.ctx.ft_to_m
    by_name = {p.Name: p for p in f.by_type("IfcProduct") if p.Name in exact}
    fail = []
    for el in model.elements:
        prod = by_name.get(el.name)
        if prod is None:
            continue
        items = [it for r in prod.Representation.Representations
                 if r.RepresentationIdentifier == "Body" for it in r.Items]
        drawn = [it for it in items if it.is_a("IfcSectionedSolidHorizontal")]
        sweeps = [ex["sweep"] for dicts in body_dicts(el) for d in dicts
                  if (ex := exact_of(d)) and ex["kind"] == "sectioned"]
        if len(sweeps) != len(drawn):
            fail.append(f"{el.name}: {len(drawn)} exact sweeps in the IFC, "
                        f"{len(sweeps)} in the model")
            continue
        matrix = up.get_local_placement(prod.ObjectPlacement)
        volume = 0.0
        with _quiet_stdout():
            for i, (sw, item) in enumerate(zip(sweeps, drawn)):
                tag = el.name if len(sweeps) == 1 else f"{el.name} sweep {i + 1}"
                verts, tris = _tessellate_item(st, item, matrix, k)
                res, s_lo, s_hi = sw.surface_residual_ft(verts)
                if res > EXACT_SWEEP_TOL_FT:
                    fail.append(f"{tag}: IFC sweep strays {res * 304.8:.1f} mm "
                                f"from the swept surface (tol "
                                f"{EXACT_SWEEP_TOL_FT * 304.8:.0f} mm)")
                if (abs(s_lo - sw.s0) > EXACT_SWEEP_TOL_FT
                        or abs(s_hi - sw.s1) > EXACT_SWEEP_TOL_FT):
                    fail.append(f"{tag}: IFC sweep spans stations "
                                f"{s_lo:.3f}-{s_hi:.3f}, the sweep "
                                f"{sw.s0:.3f}-{sw.s1:.3f}")
                cap = sw.cap_station_error_ft(verts, tris)
                if cap > EXACT_SWEEP_TOL_FT:
                    fail.append(f"{tag}: IFC sweep end sections lean "
                                f"{cap * 304.8:.0f} mm off their stations "
                                f"(tol {EXACT_SWEEP_TOL_FT * 304.8:.0f} mm)")
                d = sw.body_solids()[0]
                want = sw.wall_area_sf(d["verts"], d["tris"])
                got = sw.wall_area_sf(verts, tris)
                if want and abs(got - want) / want > EXACT_SWEEP_AREA_TOL:
                    fail.append(f"{tag}: IFC sweep wall area {got:.1f} sf vs "
                                f"{want:.1f} sf swept — a wall is missing or "
                                f"extra")
                volume += sw.volume_cf
            for item in items:
                if not item.is_a("IfcSectionedSolidHorizontal"):
                    volume += _closed_volume(
                        *_tessellate_item(st, item, matrix, k))
        want_cf = el.quantities.get("volume_cf")
        if want_cf and abs(want_cf - volume) / volume > tol:
            fail.append(f"{el.name}: declared volume {want_cf:.3f} cf is "
                        f"{abs(want_cf - volume) / volume:.4%} off the "
                        f"{volume:.3f} cf its exact sweeps and other solids "
                        f"hold (tol {tol:.2%})")
    return fail


#: how far an engine's drawing of an exact revolution may stray from the
#: model's, feet (0.1 mm): its vertices are the profile's corners, turned
EXACT_REVOLUTION_TOL_FT = 0.0001 / 0.3048


def _ifc_exact_revolution_check(model, ifc_path: str) -> list[str]:
    """Every IfcRevolvedAreaSolid is drawn where its model revolution is (#331).

    The volume check cannot see a turn the wrong way, about the wrong side of
    the axis or from a shifted profile: each has the same volume. So each
    item is paired, in order, with the revolutions the element's solids
    carry (primitives.exact_of), tessellated by ifcopenshell, and every
    drawn vertex must be a profile point turned by an angle inside the
    model's sweep, with the profile drawn at both ends.
    """
    import ifcopenshell
    import ifcopenshell.geom
    import numpy as np
    from bimforge.author.emit_ifc import body_dicts
    from bimforge.author.primitives import _on_revolution, exact_of
    f = ifcopenshell.open(str(ifc_path))
    st = ifcopenshell.geom.settings()
    k = model.ctx.ft_to_m
    by_name = {p.Name: p for p in f.by_type("IfcProduct") if p.Representation
               and any(it.is_a("IfcRevolvedAreaSolid")
                       for r in p.Representation.Representations
                       for it in r.Items)}
    fail = []
    for el in model.elements:
        prod = by_name.get(el.name)
        if prod is None:
            continue
        drawn = [it for r in prod.Representation.Representations
                 if r.RepresentationIdentifier == "Body" for it in r.Items
                 if it.is_a("IfcRevolvedAreaSolid")]
        revs = [ex for dicts in body_dicts(el) for d in dicts
                if (ex := exact_of(d)) and ex["kind"] == "revolution"]
        if len(revs) != len(drawn):
            fail.append(f"{el.name}: {len(drawn)} revolved solids in the IFC, "
                        f"{len(revs)} in the model")
            continue
        # the model's revolutions are element-local (solids_for writes them
        # relative to the element's placement), so the drawn solid is held
        # to them in that frame, not moved by the product's placement
        matrix = np.eye(4)
        with _quiet_stdout():
            for i, (ex, item) in enumerate(zip(revs, drawn)):
                verts, _tris = _tessellate_item(st, item, matrix, k)
                if not _on_revolution(verts, ex, EXACT_REVOLUTION_TOL_FT):
                    tag = el.name if len(revs) == 1 else f"{el.name} solid {i + 1}"
                    fail.append(f"{tag}: the IFC revolved solid is not drawn "
                                f"where the model's revolution is (turned the "
                                f"other way, about another axis, or from "
                                f"another profile)")
    return fail


def _ifc_representation_type_check(model, ifc_path: str) -> list[str]:
    """Every shape representation's items are ones its RepresentationType admits.

    The check ifcopenshell.validate cannot make (#329): RepresentationType is
    a bare IfcLabel, so 'SweptSolid' over an IfcFacetedBrep validates clean
    while strict importers and MVD/IDS checkers reject it. A Body
    representation must also carry a type the table knows at all.
    """
    import ifcopenshell
    from bimforge.author.emit_ifc import REPRESENTATION_ITEMS, admits
    f = ifcopenshell.open(str(ifc_path))
    fail = []
    for rep in f.by_type("IfcShapeRepresentation"):
        rt = rep.RepresentationType
        if rt not in REPRESENTATION_ITEMS:
            if rep.RepresentationIdentifier == "Body":
                fail.append(f"#{rep.id()} Body representation has "
                            f"unrecognised RepresentationType {rt!r}")
            continue
        bad = sorted({i.is_a() for i in rep.Items if not admits(rt, i)})
        if bad:
            owners = [p.Name for s in (rep.OfProductRepresentation or ())
                      for p in (s.ShapeOfProduct or ())]
            fail.append(f"{', '.join(owners) or f'#{rep.id()}'}: "
                        f"RepresentationType {rt!r} does not admit {bad}")
    return fail


def _ifc_spatial_chain_check(model, ifc_path: str) -> list[str]:
    """Every storey must be reachable from IfcProject through IfcRelAggregates.

    The check none of the others could be: `ifcopenshell.validate()` returns
    0 issues on a storey with no building and `geom.iterator` builds every
    shape, because products carry ABSOLUTE placements and never traverse the
    spatial tree — so unit scale, georeference round-trip, mesh-vs-analytic
    volume and takeoff coverage all pass on a file no third-party viewer will
    render (issue #132: Site -> Storey with no IfcBuilding opened completely
    empty in Bonsai). Reading the file back with the library that wrote it
    proves nothing about an importer; walking the decomposition the way an
    importer does is the only thing that can.

    Also (#318): every product's container chain reaches the IfcSite, and an
    IFC4X3 file with a facility tree has every facility under the site, every
    part under a facility, no empty part, and a clean ifcopenshell.validate.
    """
    import ifcopenshell
    f = ifcopenshell.open(str(ifc_path))
    projects = f.by_type("IfcProject")
    if not projects:
        return [f"{ifc_path}: no IfcProject — the file has no spatial root"]

    reached, frontier = set(), [projects[0]]
    while frontier:
        for rel in frontier.pop().IsDecomposedBy or []:
            for child in rel.RelatedObjects:
                if child.id() not in reached:
                    reached.add(child.id())
                    frontier.append(child)

    fail = []
    for storey in f.by_type("IfcBuildingStorey"):
        if storey.id() not in reached:
            fail.append(
                f"spatial tree: storey '{storey.Name}' is not reachable from "
                "IfcProject through IfcRelAggregates — an importer walking "
                "Project -> Site -> Building -> Storey never visits it, so "
                "the model renders empty")
            continue
        parents = [r.RelatingObject for r in storey.Decomposes]
        if not any(p.is_a("IfcBuilding") for p in parents):
            fail.append(
                f"spatial tree: storey '{storey.Name}' decomposes "
                f"{[p.is_a() for p in parents]}, not an IfcBuilding — a "
                "storey decomposes a building and a site contains buildings")
    for rel in f.by_type("IfcRelContainedInSpatialStructure"):
        if rel.RelatingStructure.id() not in reached:
            fail.append(
                f"spatial tree: {len(rel.RelatedElements)} product(s) hang "
                f"off {rel.RelatingStructure.is_a()} "
                f"'{rel.RelatingStructure.Name}', which is not reachable "
                "from IfcProject")
    if f.schema.upper().startswith("IFC4X3"):
        fail += _ifc4x3_facility_check(f, reached)
    fail += _products_reach_site(f)
    return fail


def _ifc4x3_facility_check(f, reached) -> list[str]:
    """The IFC4X3 facility tree (#318): every facility hangs off the IfcSite,
    every facility part off a facility, and no part is empty — then the file
    must pass ifcopenshell.validate (the 4X3 path writes entities and
    enumerations the IFC4 path never touches, e.g. the REQUIRED
    IfcFacilityPart.UsageType)."""
    fail = []
    facilities = [x for x in f.by_type("IfcFacility")
                  if not x.is_a("IfcBuilding")]
    parts = f.by_type("IfcFacilityPart")
    for fac in facilities:
        parents = [r.RelatingObject for r in fac.Decomposes]
        if fac.id() not in reached or not any(
                p.is_a("IfcSite") or p.is_a("IfcFacility") for p in parents):
            fail.append(
                f"spatial tree: {fac.is_a()} '{fac.Name}' does not decompose "
                "an IfcSite reachable from IfcProject")
    for part in parts:
        parents = [r.RelatingObject for r in part.Decomposes]
        if part.id() not in reached or not any(
                p.is_a("IfcFacility") or p.is_a("IfcFacilityPart")
                for p in parents):
            fail.append(
                f"spatial tree: {part.is_a()} '{part.Name}' does not decompose "
                "a facility reachable from IfcProject")
        contains = any(r.RelatedElements for r in part.ContainsElements or ())
        children = any(r.RelatedObjects for r in part.IsDecomposedBy or ())
        if not (contains or children):
            fail.append(
                f"spatial tree: {part.is_a()} '{part.Name}' is empty — a part "
                "that contains nothing is a navigation dead end")
    if facilities or parts:
        import ifcopenshell.validate
        logger = ifcopenshell.validate.json_logger()
        ifcopenshell.validate.validate(f, logger)
        for stmt in logger.statements[:20]:
            msg = stmt.get("message", stmt) if isinstance(stmt, dict) else stmt
            fail.append(f"ifcopenshell.validate: {msg}")
        if len(logger.statements) > 20:
            fail.append(f"ifcopenshell.validate: ... "
                        f"{len(logger.statements) - 20} more")
    return fail


def _products_reach_site(f) -> list[str]:
    """Every non-spatial product's container chain must reach the IfcSite.

    An element is placed in the tree by containment (IfcRelContainedIn-
    SpatialStructure), by aggregation into another product (assembly
    members), by nesting, or, for an opening, by the element it voids. Walk
    those links upward the way an importer resolves a product's location; a
    product whose walk never meets an IfcSite is invisible in a tree-driven
    outliner even though it renders.

    The one other legal end is the IfcProject, reached THROUGH a positioning
    element: IFC4.3 aggregates a top-level IfcAlignment to the project
    (concept template 4.1.4.1.1), and its layouts, segments and referents
    nest under it (#332)."""
    fail, bad = [], []
    for p in f.by_type("IfcProduct"):
        if p.is_a("IfcSpatialElement") or p.is_a("IfcSite"):
            continue
        node, seen, positioned = p, set(), False
        while node is not None and not node.is_a("IfcSite"):
            positioned = positioned or node.is_a("IfcPositioningElement")
            if positioned and node.is_a("IfcProject"):
                break
            if node.id() in seen:
                node = None
                break
            seen.add(node.id())
            nxt = None
            for attr, end in (("ContainedInStructure", "RelatingStructure"),
                              ("Decomposes", "RelatingObject"),
                              ("Nests", "RelatingObject"),
                              ("VoidsElements", "RelatingBuildingElement")):
                rels = getattr(node, attr, None) or ()
                if rels:
                    nxt = getattr(rels[0], end)
                    break
            node = nxt
        if node is None:
            bad.append(f"{p.is_a()} '{p.Name}'")
    if bad:
        fail.append(
            f"spatial tree: {len(bad)} product(s) have no container chain to "
            f"the IfcSite: {', '.join(bad[:10])}"
            + (f" ... {len(bad) - 10} more" if len(bad) > 10 else ""))
    return fail


def _map_coverage_check(model, map_path: str) -> list[str]:
    import yaml
    doc = yaml.safe_load(Path(map_path).read_text(encoding="utf-8")) or {}
    map_codes = set(doc.get("codes") or {})
    model_codes = set(model.codes_used())
    fail = []
    if map_codes != model_codes:
        missing = sorted(model_codes - map_codes)
        extra = sorted(map_codes - model_codes)
        if missing:
            fail.append(f"takeoff map is missing model codes {missing}")
        if extra:
            fail.append(f"takeoff map carries codes no element uses {extra}")
    return fail


def _dxf_sanity_check(model, dxf_path: str) -> list[str]:
    import ezdxf
    doc = ezdxf.readfile(str(dxf_path))
    n = sum(1 for _ in doc.modelspace())
    if n == 0:
        return [f"{dxf_path}: DXF modelspace is empty"]
    return []


def _run_contained(rep: GateReport, chk, *args) -> None:
    """Run one post-check; a RAISE becomes a failure entry instead of
    propagating. An uncontained exception would bypass delete_outputs and
    leave unverified outputs on disk — the delete-on-fail contract must hold
    even when a check crashes rather than politely returning failures."""
    try:
        rep.extend(chk(*args))
    except Exception as exc:
        name = getattr(chk, "__name__", repr(chk))
        rep.failures.append(f"{name} raised: {exc!r}")
    rep.checks_run += 1


def run_post(model, outputs: dict, paycodes=None,
             mesh_tol: float = MESH_TOLERANCE,
             extra_checks=()) -> GateReport:
    """Verify written outputs; on failure DELETE them all and report.

    `outputs`: {"ifc": path|None, "dxf": path|None, "takeoff_map": path|None,
    "qto": path|None, "step": path|None} — whatever was written.
    """
    rep = GateReport()
    if outputs.get("ifc"):
        with _quiet_stdout():
            _run_contained(rep, _ifc_mesh_check, model, outputs["ifc"],
                           mesh_tol)
        _run_contained(rep, _ifc_spatial_chain_check, model, outputs["ifc"])
        _run_contained(rep, _ifc_representation_type_check, model,
                       outputs["ifc"])
        _run_contained(rep, _ifc_exact_sweep_check, model, outputs["ifc"],
                       mesh_tol)
        _run_contained(rep, _ifc_exact_revolution_check, model,
                       outputs["ifc"])
    if outputs.get("takeoff_map"):
        _run_contained(rep, _map_coverage_check, model, outputs["takeoff_map"])
    if outputs.get("dxf"):
        _run_contained(rep, _dxf_sanity_check, model, outputs["dxf"])
    for chk in tuple(extra_checks):
        _run_contained(rep, chk, model, outputs)
    if not rep.passed:
        delete_outputs(outputs)
    return rep


def delete_outputs(outputs: dict) -> None:
    for path in outputs.values():
        if path and Path(path).exists():
            Path(path).unlink()
