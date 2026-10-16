"""author.emit_alignment: the model's alignments as IFC4X3 IfcAlignment (#332).

The model has always carried its alignment — every `SweptSection` sweeps
along one — but the file did not: no IfcAlignment, no IfcCompositeCurve, no
IfcGradientCurve. That curve is the directrix every alignment-swept IFC solid
needs, and a downstream tool that wants stations (staging, layout, #310's
barrier runs) needs it too. This writes it, in the project's model frame, so
it lies exactly under the geometry swept from the same `Alignment`.

Semantic layouts (IfcAlignmentHorizontal / IfcAlignmentVertical segments) are
written and ifcopenshell.api.alignment derives the geometric curves from them,
so the business logic and the geometry cannot disagree. IFC4 has no
IfcAlignment: under it this writes nothing and says so.
"""
from __future__ import annotations

import math
import sys

from bimforge.author.alignment import sta
from bimforge.author.sweep import to_model, to_model_elev


def model_alignments(models) -> list[tuple]:
    """Distinct (alignment, profile, origin) the models' geometry sweeps along.

    Found from the geometry rather than declared, so no family has to opt
    in: anything exposing `.alignment` (SweptSection, and wrappers that
    delegate to one) contributes, exact or not, and so does every solids
    dict carrying an exact alignment sweep (primitives.exact_of) — a raw
    dict on Element.geometry included. Ordered by first appearance —
    deterministic, since element order is.
    """
    from bimforge.author.emit_ifc import body_dicts
    from bimforge.author.primitives import exact_of
    seen, out = set(), []
    for m in models:
        for el in m.elements:
            if el.geometry is None:
                continue
            geoms = (el.geometry if isinstance(el.geometry, (list, tuple))
                     else [el.geometry])
            found = [(g.alignment, getattr(g, "profile", None),
                      getattr(g, "origin", None)) for g in geoms
                     if not isinstance(g, dict)
                     and getattr(g, "alignment", None) is not None]
            found += [(ex["alignment"], ex["vprofile"], ex["origin"])
                      for dicts in body_dicts(el) for d in dicts
                      if (ex := exact_of(d)) and ex["kind"] == "sectioned"]
            for al, prof, origin in found:
                key = (id(al), id(prof), id(origin))
                if key not in seen:
                    seen.add(key)
                    out.append((al, prof, origin))
    return out


def _direction(az_deg: float) -> float:
    """Survey azimuth (clockwise from north) -> model-frame angle (radians,
    counter-clockwise from +x = east)."""
    return math.radians(90.0 - az_deg)


def _horizontal(f, layout, al, origin, k):
    import ifcopenshell.api.alignment as api
    for seg in al.segments:
        if seg["kind"] == "tangent":
            n0, e0, az = seg["n0"], seg["e0"], seg["az"]
            r = 0.0
            kind = "LINE"
        else:
            n0, e0, az = al.point_az(seg["s0"])
            # IFC: positive radius turns counter-clockwise (left); bimforge's
            # sign is +1 for a RIGHT turn.
            r = -seg["sign"] * seg["radius"] * k
            kind = "CIRCULARARC"
        x, y, _z = to_model(origin, n0, e0)
        api.create_layout_segment(f, layout, f.create_entity(
            "IfcAlignmentHorizontalSegment",
            StartPoint=f.create_entity("IfcCartesianPoint",
                                       Coordinates=(x * k, y * k)),
            StartDirection=_direction(az), StartRadiusOfCurvature=r,
            EndRadiusOfCurvature=r, SegmentLength=seg["length"] * k,
            PredefinedType=kind))


def _vertical(f, layout, al, prof, origin, k):
    """The profile over the whole traverse, cut at every BVC/EVC.

    A piece inside a vertical curve is a PARABOLICARC (a sub-span of a
    parabola is a parabola of the same rate, so a VC clipped by the traverse
    end still maps exactly); a piece between curves is a CONSTANTGRADIENT.
    """
    import ifcopenshell.api.alignment as api
    s0, s1 = al.s_start, al.s_end
    cuts = sorted({s0, s1, *prof.breaks(s0, s1)})
    for a, b in zip(cuts, cuts[1:]):
        eps = 1e-9 * (b - a)
        g0, g1 = prof.grade(a + eps), prof.grade(b - eps)
        curved = abs(g1 - g0) > 1e-12
        kw = {}
        if curved:
            # IFC4.3: the positive minimum-parabola radius; crest vs sag is
            # read from the gradients
            kw["RadiusOfCurvature"] = abs((b - a) * k / (g1 - g0))
        api.create_layout_segment(f, layout, f.create_entity(
            "IfcAlignmentVerticalSegment",
            StartDistAlong=(a - s0) * k, HorizontalLength=(b - a) * k,
            StartHeight=to_model_elev(origin, prof.elev(a)) * k,
            StartGradient=g0, EndGradient=g1,
            PredefinedType="PARABOLICARC" if curved else "CONSTANTGRADIENT",
            **kw))


def emit_alignments(run, f, models, ctx, site) -> dict:
    """Write each swept-along alignment; returns {(id(al), id(profile),
    id(origin)): IfcCurve} — the gradient curve when there is a profile, the
    horizontal composite curve when there is not — for the sweep emitter.

    The alignment is aggregated to the IfcProject (IFC4.3 concept template
    4.1.4.1.1, which ifcopenshell.api does) and referenced into the site, so
    a tree-driven outliner shows it where the structure is.
    """
    found = model_alignments(models)
    if not found:
        return {}
    if not ctx.schema.upper().startswith("IFC4X3"):
        print(f"note: {len(found)} alignment(s) not written — IfcAlignment is "
              f"IFC4X3-only and project.schema is {ctx.schema}",
              file=sys.stderr)
        return {}
    import ifcopenshell.api.alignment as api
    k = ctx.ft_to_m
    out = {}
    names: dict[str, int] = {}
    for al, prof, origin in found:
        n = names[al.name] = names.get(al.name, 0) + 1
        ifc_al = api.create(f, al.name if n == 1 else f"{al.name} ({n})",
                            include_vertical=prof is not None)
        _horizontal(f, api.get_horizontal_layout(ifc_al), al, origin, k)
        if prof is not None:
            _vertical(f, api.get_vertical_layout(ifc_al), al, prof, origin, k)
        api.add_stationing_referent(
            f, name=sta(al.s_start), alignment=ifc_al, distance_along=0.0,
            station=al.s_start * k)
        run("spatial.reference_structure", f, products=[ifc_al],
            relating_structure=site)
        out[(id(al), id(prof), id(origin))] = api.get_curve(ifc_al)
    return out
