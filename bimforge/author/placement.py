"""Shared alignments and the spec `placement:` block.

A project's control lines live in ONE file that every spec names, instead of
each spec copying its own:

    # alignments.yaml (the spec's `project.alignments:`, relative to the spec)
    alignments:
      ROUTE-59_SEC-7:
        pob: {station: 53850.0, northing: 1906707.6, easting: 6565162.6}
        run: [{kind: tangent, bearing: "N 0-06-03 W", length: 2210.0}]
        profile:                       # optional: bimforge Profile curves
          - {bvc_station: 54182.87, bvc_elev: 154.76, g_in_pct: 1.727,
             g_out_pct: -1.621, length_ft: 1220.0, evc_station: 55402.87,
             evc_elev: 155.40}

A line may carry the plan's control ties, which every model built on it is
held to (a pre-gate check):

        ties:                          # station/offset <-> N/E (LOTB, control)
          - {id: RC-23-001, station: 54875.22, offset: 54.74, side: Lt,
             northing: 1907732.72, easting: 6565106.03, tol_ft: 0.10}
        profile_ties:                  # station <-> lettered CL elevation
          - {station: 54762.90, elev: 160.16, tol_ft: 0.01}

A family that takes its own line reads it from the file: `{ref: NAME}` in
`params.alignment` becomes `{pob, run, name}`, in `params.profile`
`{curves}` (`resolve_refs`). A family that builds in its own local frame
(a headwall, a culvert, a sign foundation) is put on the line by the spec:

    placement:
      alignment: ROUTE-59_SEC-7
      items:                           # element-name regex, first match wins
        - match: '^HW DS 26 '
          station: 54996.20
          offset: 54.00                # + = side
          side: Rt                     # Rt | Lt (of increasing station)
          anchor: {of: '^HW DS 26 headwall stem$', x: mid, y: mid, z: max}
          elevation: 150.91            # of the anchor; or `grade: dz` (profile + dz)
          x: left                      # where local +x points: ahead|back|left|right
          y: back                      # (local x, y, up must be right-handed)
          skew_deg: 0.0                # turns the item clockwise in plan

The `anchor` (a local point, or a bounding-box point of the elements matching
`of`) lands on the station/offset at the elevation. Each element keeps its
geometry in its own frame; only its rigid placement (Element.x_ft / y_ft /
z_ft / bearing_deg, which every emitter applies) changes, so exact forms,
volumes and rebar come through untouched. The alignment is declared on the
model, so the IFC carries the IfcAlignment the item is placed on.

A model that declares an alignment of a shared name itself (a family that
builds its line from its own parameters) is held to the shared one and then
declares the SHARED object (`adopt_shared`): one line, one IfcAlignment after
federation (`federate` merges same-named, same-geometry alignments).
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import yaml

_CACHE: dict = {}

DIRECTIONS = ("ahead", "back", "left", "right")


class SharedAlignment:
    """One named control line: bimforge (Alignment, Profile | None)."""

    def __init__(self, name: str, data: dict):
        from bimforge.author.alignment import Alignment, Profile
        self.name = name
        self.data = data
        if "pob" not in data or "run" not in data:
            raise ValueError(f"alignment {name!r}: needs pob and run")
        self.alignment = Alignment(data["pob"], data["run"], name=name)
        prof = data.get("profile")
        if prof is not None and not isinstance(prof, list):
            raise ValueError(f"alignment {name!r}: profile is a list of curves")
        self.profile = Profile(prof) if prof else None
        self.ties = list(data.get("ties") or [])
        self.profile_ties = list(data.get("profile_ties") or [])
        for t in self.ties:
            for k in ("station", "northing", "easting"):
                if k not in t:
                    raise ValueError(f"alignment {name!r}: tie {t.get('id', t)} needs {k}")

    def tie_problems(self, default_tol: float = 0.10) -> list[str]:
        """The line against its control ties: plan (station/offset -> N/E)
        and profile (station -> elevation)."""
        out = []
        for t in self.ties:
            off = float(t.get("offset", 0.0))
            side = str(t.get("side", "Rt"))
            if off:
                n, e = self.alignment.station_offset(float(t["station"]), abs(off),
                                                     side if off >= 0 else _flip(side))
            else:
                n, e = self.alignment.point_az(float(t["station"]))[:2]
            d = math.hypot(n - float(t["northing"]), e - float(t["easting"]))
            tol = float(t.get("tol_ft", default_tol))
            if d > tol:
                out.append(f"alignment {self.name}: tie {t.get('id', t['station'])} "
                           f"is {d:.3f} ft off the line (tol {tol:g})")
        for t in self.profile_ties:
            if self.profile is None:
                out.append(f"alignment {self.name}: profile_ties but no profile")
                break
            dz = abs(self.profile.elev(float(t["station"])) - float(t["elev"]))
            tol = float(t.get("tol_ft", 0.01))
            if dz > tol:
                out.append(f"alignment {self.name}: profile at {t['station']} is "
                           f"{dz:.3f} ft off El {t['elev']} (tol {tol:g})")
        return out

    def pair(self) -> tuple:
        return self.alignment, self.profile


def load_alignments(path) -> dict[str, SharedAlignment]:
    """{name: SharedAlignment} from an alignments file. Cached per file (and
    its mtime): every spec of a run that names the same file gets the SAME
    objects, so the model writers see one line, not copies of it."""
    p = Path(path).resolve()
    key = (str(p), p.stat().st_mtime_ns)
    if key not in _CACHE:
        doc = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        als = doc.get("alignments")
        if not isinstance(als, dict) or not als:
            raise ValueError(f"{p.name}: no `alignments:` mapping")
        _CACHE[key] = {str(n): SharedAlignment(str(n), d) for n, d in als.items()}
    return _CACHE[key]


def _shared(alignments: dict | None, name: str, where: str) -> SharedAlignment:
    if not alignments:
        raise ValueError(f"{where}: alignment {name!r} referenced but the spec "
                         "names no `project.alignments:` file")
    if name not in alignments:
        raise ValueError(f"{where}: no alignment {name!r} in project.alignments "
                         f"(has {sorted(alignments)})")
    return alignments[name]


def _is_ref(v) -> bool:
    return isinstance(v, dict) and set(v) == {"ref"}


def resolve_refs(params: dict, alignments: dict | None) -> dict:
    """`params` with `alignment: {ref: NAME}` replaced by the shared line's
    `{pob, run, name}` and `profile: {ref: NAME}` by `{curves: [...]}` - the
    shapes the line-native families (bridge-standard, approach-slab,
    standard-plan) read. Anything else is left alone."""
    out = dict(params)
    if _is_ref(out.get("alignment")):
        sa = _shared(alignments, str(out["alignment"]["ref"]), "params.alignment")
        out["alignment"] = {"pob": dict(sa.data["pob"]),
                            "run": [dict(r) for r in sa.data["run"]],
                            "name": sa.name,
                            # the shared object itself, for a family that sweeps
                            # on it (so the IFC has ONE IfcAlignment for it)
                            "_object": sa.alignment, "_profile": sa.profile}
    if _is_ref(out.get("profile")):
        sa = _shared(alignments, str(out["profile"]["ref"]), "params.profile")
        if sa.profile is None:
            raise ValueError(f"params.profile: alignment {sa.name!r} has no profile")
        out["profile"] = {"curves": [dict(c) for c in sa.data["profile"]]}
    return out


# ------------------------------------------------------------- placement
def _dict_points(d: dict):
    """Corner points (feet, element frame) of one body_solids dict."""
    k = 1.0 / 12.0 if d.get("units") == "in" else 1.0
    kind = d.get("kind")
    if kind in ("mesh", "ribbon") and d.get("verts"):
        return [tuple(c * k for c in v) for v in d["verts"]]
    if kind in ("prism", "fill") and d.get("base"):
        z = [d["z_bot"], d["z_top"]]
        return [(x * k, y * k, zz * k) for x, y in d["base"] for zz in z]
    return None


def local_bounds(elements) -> tuple:
    """((xmin, ymin, zmin), (xmax, ymax, zmax)) of the elements' geometry in
    their own frame (before placement), feet. Mesh / prism / fill bodies;
    a body of another kind can not anchor and raises."""
    from bimforge.author.emit_ifc import body_dicts
    pts = []
    for el in elements:
        for ds in body_dicts(el):
            for d in ds:
                p = _dict_points(d)
                if p is None:
                    raise ValueError(f"{el.name}: a {d.get('kind')!r} body can "
                                     "not anchor a placement; give the anchor "
                                     "as a local point [x, y, z]")
                pts += p
    if not pts:
        raise ValueError("anchor: the matched elements carry no geometry")
    return (tuple(min(p[i] for p in pts) for i in range(3)),
            tuple(max(p[i] for p in pts) for i in range(3)))


def _anchor(model, a, where: str) -> tuple:
    if a is None:
        return (0.0, 0.0, 0.0)
    if isinstance(a, (list, tuple)) and len(a) == 3:
        return tuple(float(v) for v in a)
    if not isinstance(a, dict) or "of" not in a:
        raise ValueError(f"{where}: anchor is [x, y, z] or {{of: regex, x:, y:, z:}}")
    rx = re.compile(a["of"])
    els = [e for e in model.elements if rx.search(e.name)]
    if not els:
        raise ValueError(f"{where}: anchor `of` {a['of']!r} matches no element")
    lo, hi = local_bounds(els)
    pick = {"min": 0.0, "mid": 0.5, "max": 1.0}
    out = []
    for i, ax in enumerate("xyz"):
        w = a.get(ax, "mid")
        if w not in pick:
            raise ValueError(f"{where}: anchor {ax}: {w!r} is not min|mid|max")
        out.append(lo[i] + pick[w] * (hi[i] - lo[i]))
    return tuple(out)


def frame(model, sa: SharedAlignment, station: float, offset: float, side: str):
    """(model-frame point (x, y) of the station/offset, unit model-frame
    vectors ahead and left there) - feet, survey through `to_model`."""
    from bimforge.author.sweep import to_model, to_model_dir
    al = sa.alignment
    n, e = (al.station_offset(station, abs(offset),
                              side if offset >= 0 else _flip(side))
            if offset else al.point_az(station)[:2])
    x, y, _ = to_model(model.ctx, n, e, 0.0)
    az = al.point_az(station)[2]
    dn, de = math.cos(math.radians(az)), math.sin(math.radians(az))
    ax, ay = to_model_dir(dn, de)
    return (x, y), (ax, ay), (-ay, ax)


def _flip(side: str) -> str:
    return "Lt" if str(side).strip().upper() in ("RT", "R", "RIGHT") else "Rt"


def _axis(name: str, ahead, left, where: str):
    v = {"ahead": ahead, "back": (-ahead[0], -ahead[1]),
         "left": left, "right": (-left[0], -left[1])}
    if name not in v:
        raise ValueError(f"{where}: {name!r} is not one of {DIRECTIONS}")
    return v[name]


def apply_placement(model, block: dict, alignments: dict | None) -> list[str]:
    """Place the spec's `placement:` items on their alignment (see the module
    docstring). Returns one report line per item; raises on an element no
    item places when `block.require_all` is true, on an item matching
    nothing, and on a left-handed axis pair."""
    from bimforge.author.sweep import to_model_elev
    if not block:
        return []
    where = "placement"
    default_al = block.get("alignment")
    report, placed = [], set()
    for i, it in enumerate(block.get("items") or [], 1):
        w = f"{where}.items[{i}]"
        name = it.get("alignment", default_al)
        if not name:
            raise ValueError(f"{w}: no alignment (set placement.alignment)")
        sa = _shared(alignments, str(name), w)
        rx = re.compile(it["match"])
        els = [e for e in model.elements if e.name not in placed and rx.search(e.name)]
        if not els:
            raise ValueError(f"{w}: match {it['match']!r} places no element")
        sta, off = float(it["station"]), float(it.get("offset", 0.0))
        side = str(it.get("side", "Rt"))
        (px, py), ahead, left = frame(model, sa, sta, off, side)
        ux = _axis(str(it.get("x", "right")), ahead, left, w)
        uy = _axis(str(it.get("y", "ahead")), ahead, left, w)
        if abs(ux[0] * uy[1] - ux[1] * uy[0] - 1.0) > 1e-9:
            raise ValueError(f"{w}: x {it.get('x')!r} / y {it.get('y')!r} with z up "
                             "is not a right-handed frame (it would mirror the item)")
        theta = math.degrees(math.atan2(ux[1], ux[0])) - float(it.get("skew_deg", 0.0))
        ax_, ay_, az_ = _anchor(model, it.get("anchor"), w)
        if "elevation" in it and "grade" in it:
            raise ValueError(f"{w}: give elevation OR grade, not both")
        if "elevation" in it:
            elev = float(it["elevation"])
        elif "grade" in it:
            if sa.profile is None:
                raise ValueError(f"{w}: grade needs a profile on {sa.name!r}")
            elev = sa.profile.elev(sta) + float(it["grade"])
        else:
            raise ValueError(f"{w}: needs elevation (absolute, of the anchor) or "
                             "grade (profile + dz)")
        pz = to_model_elev(model.ctx, elev)
        th = math.radians(theta)
        c, s = math.cos(th), math.sin(th)
        # local x -> R x + t, with the anchor landing on (px, py, pz)
        tx = px - (c * ax_ - s * ay_)
        ty = py - (s * ax_ + c * ay_)
        tz = pz - az_
        for el in els:
            # compose with what the element already carries: R (R_e x + t_e) + t
            ex, ey, ez, eb = el.x_ft, el.y_ft, el.z_ft, el.bearing_deg
            el.x_ft = c * ex - s * ey + tx
            el.y_ft = s * ex + c * ey + ty
            el.z_ft = ez + tz
            el.bearing_deg = eb + theta
            el.placed_on = {"alignment": sa.name, "station": sta,
                            "offset": off, "side": side, "elevation": elev,
                            # the anchor in the element's OWN frame (before its
                            # placement), for the post-emit check
                            "anchor": _unplace(el, ex, ey, ez, eb, (ax_, ay_, az_))}
            placed.add(el.name)
        _declare(model, sa)
        report.append(f"{it['match']}: {len(els)} elements on {sa.name} at "
                      f"{sta:.2f} {abs(off):.2f} {side if off >= 0 else _flip(side)}, "
                      f"El {elev:.2f}")
    if block.get("require_all"):
        left_over = [e.name for e in model.elements if e.name not in placed]
        if left_over:
            raise ValueError(f"{where}: require_all, but no item places {left_over[:5]}")
    return report


def _unplace(el, ex, ey, ez, eb, p) -> tuple:
    """Item-frame point `p` in the element's own geometry frame, given the
    element's placement BEFORE this item placed it (ex, ey, ez, eb)."""
    th = math.radians(-eb)
    c, s = math.cos(th), math.sin(th)
    x, y = p[0] - ex, p[1] - ey
    return (c * x - s * y, s * x + c * y, p[2] - ez)


def check_ties(alignments: dict | None):
    """A pre-gate check: every shared line the model is built on (declared,
    adopted, placed on or swept along) against its control ties."""
    def check_alignment_ties(model):
        from bimforge.author.emit_alignment import model_alignments
        used = {id(a) for a, _p, _o in model_alignments([model])}
        out = []
        for sa in (alignments or {}).values():
            if id(sa.alignment) in used:
                out += sa.tie_problems()
        return out
    return check_alignment_ties


def ifc_alignment_problems(model, ifc_path, *, plan_tol_ft: float = 0.005,
                           z_tol_ft: float = 0.005, samples: int = 40) -> list[str]:
    """Post-emit: what the IFC says against what the model meant.

    * every alignment the model is built on, re-stationed from the file
      (bimforge.bim.alignment_station): plan within `plan_tol_ft`, profile
      within `z_tol_ft`, at `samples` stations;
    * every spec-placed element: its anchor, taken through the element's
      placement IN THE FILE and located on the file's alignment, lands on
      the authored station / offset / elevation.
    """
    import ifcopenshell
    import ifcopenshell.util.placement as up
    import numpy as np
    from bimforge.author.emit_alignment import model_alignments
    from bimforge.author.sweep import to_model
    from bimforge.bim.alignment_station import AlignmentStationer, alignments
    f = ifcopenshell.open(str(ifc_path))
    found = {a.Name: a for a in alignments(f)}
    if not found:
        return []
    k = model.ctx.ft_to_m
    out, st_by = [], {}
    for al, prof, origin in model_alignments([model]):
        ia = found.get(al.name)
        if ia is None:
            out.append(f"alignment {al.name}: not in the IFC")
            continue
        st = AlignmentStationer(f, ia)
        st_by[al.name] = st
        for i in range(samples + 1):
            s = al.s_start + (al.s_end - al.s_start) * i / samples
            fr = st.frame_at_station(s * k / st.unit_scale)
            n, e, _ = al.point_az(s)
            want = to_model(origin, n, e, prof.elev(s) if prof else 0.0)
            d = math.hypot(fr.point[0] / k - want[0], fr.point[1] / k - want[1])
            if d > plan_tol_ft:
                out.append(f"alignment {al.name} at {s:.2f}: the IFC's line is "
                           f"{d:.4f} ft off the model's")
                break
            if prof is not None and st.has_profile:
                dz = abs(fr.point[2] / k - want[2])
                if dz > z_tol_ft:
                    out.append(f"alignment {al.name} profile at {s:.2f}: the IFC's "
                               f"is {dz:.4f} ft off the model's")
                    break
    by_name = {p.Name: p for p in f.by_type("IfcElement")}
    for el in model.elements:
        p = getattr(el, "placed_on", None)
        if not p or "anchor" not in p:
            continue
        prod, st = by_name.get(el.name), st_by.get(p["alignment"])
        if prod is None or st is None:
            continue
        M = up.get_local_placement(prod.ObjectPlacement)
        x, y, z = (M @ np.array([c * k for c in p["anchor"]] + [1.0]))[:3]
        d, off = st.locate(x, y)
        sta = st.station_at(d) * st.unit_scale / k
        want_off = (-1 if str(p["side"]).upper() in ("RT", "R", "RIGHT") else 1) \
            * float(p["offset"])
        elev = z / k + model.ctx.base_h
        bad = [f"station {sta:.4f} vs {p['station']}" if abs(sta - p["station"]) > plan_tol_ft
               else None,
               f"offset {off / k:+.4f} (+Lt) vs {want_off:+.4f}"
               if abs(off / k - want_off) > plan_tol_ft else None,
               f"elevation {elev:.4f} vs {p['elevation']}"
               if abs(elev - p["elevation"]) > z_tol_ft else None]
        bad = [b for b in bad if b]
        if bad:
            out.append(f"{el.name}: placed anchor in the IFC - " + "; ".join(bad))
    return out


def _declare(model, sa: SharedAlignment) -> None:
    als = getattr(model, "alignments", None)
    if als is None:
        return
    if not any(a is sa.alignment for a, _p in als):
        als.append(sa.pair())


def adopt_shared(model, alignments: dict | None, *, tol_ft: float = 0.005,
                 samples: int = 40) -> list[str]:
    """For each alignment the model declares under a SHARED name: check it
    against the shared line (plan within `tol_ft`, profile within
    `tol_ft`, along the shorter of the two extents) and, if it holds,
    declare the shared object in its place. Returns the problems (the
    model's own declaration is then left as it was)."""
    if not alignments or not getattr(model, "alignments", None):
        return []
    out, new = [], []
    for al, prof in model.alignments:
        sa = alignments.get(getattr(al, "name", None))
        if sa is None or sa.alignment is al:
            new.append((al, prof))
            continue
        bad = _compare(al, prof, sa, tol_ft, samples)
        if bad:
            out += bad
            new.append((al, prof))
        else:
            new.append(sa.pair())
    model.alignments[:] = new
    return out


def _compare(al, prof, sa: SharedAlignment, tol: float, samples: int) -> list[str]:
    s0 = max(al.s_start, sa.alignment.s_start)
    s1 = min(al.s_end, sa.alignment.s_end)
    if s1 <= s0:
        return [f"alignment {sa.name}: the model's line and the shared one "
                "do not overlap in station"]
    out = []
    for i in range(samples + 1):
        s = s0 + (s1 - s0) * i / samples
        n1, e1, _ = al.point_az(s)
        n2, e2, _ = sa.alignment.point_az(s)
        d = math.hypot(n1 - n2, e1 - e2)
        if d > tol:
            out.append(f"alignment {sa.name} at {s:.2f}: the model's line is "
                       f"{d:.4f} ft off the shared one")
            break
    if prof is not None and sa.profile is not None:
        for i in range(samples + 1):
            s = s0 + (s1 - s0) * i / samples
            dz = abs(prof.elev(s) - sa.profile.elev(s))
            if dz > tol:
                out.append(f"alignment {sa.name} profile at {s:.2f}: "
                           f"{dz:.4f} ft off the shared one")
                break
    elif (prof is None) != (sa.profile is None):
        out.append(f"alignment {sa.name}: one of the model's / the shared line "
                   "has a profile and the other does not")
    return out
