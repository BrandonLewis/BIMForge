"""Station and offset written INTO the IFC: where each element sits along
its alignment, so a viewer, a GIS or a takeoff reads it rather than works it
out again.

For every element with a body, `annotate` writes a property set
`BIMForge_LinearReference`:

    Alignment            IfcLabel           the IfcAlignment's Name
    StationStart / End   IfcLengthMeasure   station range of its body (project
                                            length unit, as the alignment's)
    StationStartText /   IfcLabel           "547+58.20" in the station unit
      StationEndText
    OffsetLeftMin / Max  IfcLengthMeasure   offset range, + = LEFT of the line
                                            (IfcPointByDistanceExpression
                                            OffsetLateral's sense)
    OffsetText           IfcLabel           "12.00 Lt to 3.50 Rt"
    StationUnit          IfcLabel           ft | m (the texts' unit)

and, for an element a spec `placement:` put on the line (its anchor; see
bimforge.author.placement), also AnchorStation / AnchorStationText /
AnchorOffsetLeft / AnchorOffsetText: the exact authored values, not a
measurement. One `IfcRelPositions` per alignment links the elements to it
(IFC4X3: the positioning element positions the products).

Ranges are measured on the file's own bodies (the geometry iterator, world
coordinates), stationed with `AlignmentStationer.locate_many` - exact on
tangents and circular curves. An element goes to the alignment it was placed
on, else the one it lies nearest (smallest offset), else the first.

Re-running replaces what an earlier run wrote (and keeps its anchors), with
GlobalIds derived from the element's, so a rebuild is byte-stable and a
federated model can be annotated again after its sources were.

Examples:
    from bimforge.bim.linear_ref import annotate, read
    annotate("model.ifc")                     # in place
    refs = read(ifcopenshell.open("model.ifc"))   # GlobalId -> dict
    est-bim stations model.ifc --out model.stationed.ifc --csv stations.csv
"""
from __future__ import annotations

import uuid

PSET = "BIMForge_LinearReference"
REL_NAME = "BIMForge linear reference"
_NS = uuid.UUID("6c1b3f0e-5a4e-4b8f-9d61-2b7d4c0e9a11")
#: plan points per element used to CHOOSE its alignment when there are
#: several (the ranges use every point)
MAX_POINTS = 4000


def _guid(*parts) -> str:
    import ifcopenshell.guid
    return ifcopenshell.guid.compress(uuid.uuid5(_NS, "/".join(parts)).hex)


def _bodies(f) -> dict:
    """{element id: (n, 3) world points (project units)} for every IfcElement
    with a body."""
    import ifcopenshell.geom as geom
    import numpy as np
    s = geom.settings()
    s.set("use-world-coords", True)
    s.set("weld-vertices", False)
    out = {}
    it = geom.iterator(s, f)
    if not it.initialize():
        return out
    while True:
        sh = it.get()
        el = f.by_id(sh.id)
        if el.is_a("IfcElement"):
            v = np.asarray(sh.geometry.verts, dtype=float).reshape(-1, 3)
            if len(v):
                out[sh.id] = (np.vstack([out[sh.id], v]) if sh.id in out else v)
        if not it.next():
            break
    return out


def _texts(st, s0, s1, o0, o1) -> dict:
    from bimforge.bim.alignment_station import format_offset
    u = st.station_unit
    om = (o0 * st.unit_scale, o1 * st.unit_scale)        # project -> metres
    ft = st.foot_m
    if format_offset(om[0], u, ft) == format_offset(om[1], u, ft):
        off = format_offset(om[0], u, ft)
    else:
        off = f"{format_offset(om[1], u, ft)} to {format_offset(om[0], u, ft)}"
    return {"StationStartText": st.format_station(s0),
            "StationEndText": st.format_station(s1), "OffsetText": off}


def measure(f, stationers=None, anchors: dict | None = None) -> dict:
    """{element id: values} - what `annotate` writes (see the module
    docstring), without writing it. `anchors`: {element Name or GlobalId:
    {alignment, station, offset_left}} in project units."""
    import numpy as np
    from bimforge.bim.alignment_station import (AlignmentStationer, alignments,
                                                format_offset)
    if stationers is None:
        stationers = [AlignmentStationer(f, a) for a in alignments(f)]
    if not stationers:
        return {}
    by_name = {st.name: st for st in stationers}
    anchors = anchors or {}
    out = {}
    for eid, pts in _bodies(f).items():
        el = f.by_id(eid)
        anc = anchors.get(el.GlobalId) or anchors.get(el.Name)
        # every distinct plan point: a subsample can miss the vertices that
        # set the element's extremes (locate_many works in bounded batches)
        xy = np.unique(np.round(pts[:, :2], 9), axis=0)
        if anc and anc["alignment"] in by_name:
            cands = [by_name[anc["alignment"]]]
        else:
            cands = stationers
        if len(cands) > 1:
            # which line: the nearest, judged on a sample (a choice, not a range)
            sample = xy[:: max(1, len(xy) // MAX_POINTS)]
            st = min(cands, key=lambda c: float(np.median(np.abs(
                c.locate_many(sample)[1]))))
        else:
            st = cands[0]
        # distances are metres along the curve; offsets metres left
        d, o = st.locate_many(xy)
        k = 1.0 / st.unit_scale                          # metres -> project
        s0, s1 = st.station_at(float(d.min())), st.station_at(float(d.max()))
        o0, o1 = float(o.min()) * k, float(o.max()) * k
        v = {"Alignment": st.name, "StationStart": s0, "StationEnd": s1,
             "OffsetLeftMin": o0, "OffsetLeftMax": o1,
             "StationUnit": st.station_unit, "_stationer": st}
        v.update(_texts(st, s0, s1, o0, o1))
        if anc:
            v.update({"AnchorStation": float(anc["station"]),
                      "AnchorStationText": st.format_station(float(anc["station"])),
                      "AnchorOffsetLeft": float(anc["offset_left"]),
                      "AnchorOffsetText": format_offset(
                          float(anc["offset_left"]) * st.unit_scale, st.station_unit,
                          st.foot_m)})
        out[eid] = v
    return out


def read(f) -> dict:
    """{GlobalId: {property: value}} of every `BIMForge_LinearReference`."""
    import ifcopenshell.util.element as ue
    out = {}
    for el in f.by_type("IfcElement"):
        ps = ue.get_pset(el, PSET)
        if ps:
            out[el.GlobalId] = {k: v for k, v in ps.items() if k != "id"}
    return out


_LENGTHS = ("StationStart", "StationEnd", "OffsetLeftMin", "OffsetLeftMax",
            "AnchorStation", "AnchorOffsetLeft")


def _carry_anchors(f, anchors: dict | None) -> dict:
    """{GlobalId: anchor}: anchors an earlier run wrote (a federated model's
    sources), under the new ones. A new anchor given by element NAME is
    resolved to its elements' GlobalIds first, so it replaces what was
    carried for them; one given by GlobalId wins over one given by name."""
    old = {}
    for gid, ps in read(f).items():
        if "AnchorStation" in ps:
            old[gid] = {"alignment": ps["Alignment"], "station": ps["AnchorStation"],
                        "offset_left": ps["AnchorOffsetLeft"]}
    new = dict(anchors or {})
    by_gid, by_name = {}, {}
    for key, anc in new.items():
        try:
            f.by_guid(key)
            by_gid[key] = anc
        except RuntimeError:
            by_name[key] = anc
    if by_name:
        for el in f.by_type("IfcElement"):
            if el.Name in by_name and el.GlobalId not in by_gid:
                old[el.GlobalId] = by_name[el.Name]
    old.update(by_gid)
    return old


def _clear(f) -> None:
    """Remove what an earlier run wrote."""
    import ifcopenshell.api
    for rel in list(f.by_type("IfcRelDefinesByProperties")):
        ps = rel.RelatingPropertyDefinition
        if ps.is_a("IfcPropertySet") and ps.Name == PSET:
            for obj in list(rel.RelatedObjects):
                ifcopenshell.api.run("pset.remove_pset", f, product=obj, pset=ps)
    for rel in list(f.by_type("IfcRelPositions")):
        if rel.Name == REL_NAME:
            f.remove(rel)


def annotate(path_or_file, out: str | None = None, *, anchors: dict | None = None
             ) -> dict:
    """Write the station/offset of every element into the IFC (see the
    module docstring). `path_or_file`: a path (written back in place, or to
    `out`) or an open file (left to the caller to write). Returns
    {"elements": n, "alignments": {name: n}}; nothing written when the file
    has no stationable alignment."""
    import ifcopenshell
    import ifcopenshell.api
    from bimforge.bim.alignment_station import alignments
    f = ifcopenshell.open(str(path_or_file)) if isinstance(path_or_file, (str, bytes)) \
        or hasattr(path_or_file, "__fspath__") else path_or_file
    rep = {"elements": 0, "alignments": {}}
    if not alignments(f):
        return rep
    anchors = _carry_anchors(f, anchors)
    _clear(f)
    vals = measure(f, anchors=anchors)
    owner = None
    try:
        owner = f.by_type("IfcOwnerHistory")[0]
    except IndexError:
        pass
    by_al: dict = {}
    for eid in sorted(vals):
        v = vals[eid]
        el = f.by_id(eid)
        st = v.pop("_stationer")
        ps = ifcopenshell.api.run("pset.add_pset", f, product=el, name=PSET)
        ps.GlobalId = _guid(el.GlobalId, "pset")
        for rel in el.IsDefinedBy or ():
            if rel.is_a("IfcRelDefinesByProperties") and \
                    rel.RelatingPropertyDefinition == ps:
                rel.GlobalId = _guid(el.GlobalId, "pset-rel")
        props = {}
        for k, x in v.items():
            if k in _LENGTHS:
                props[k] = f.create_entity("IfcLengthMeasure", round(float(x), 9))
            else:
                props[k] = f.create_entity("IfcLabel", str(x))
        ifcopenshell.api.run("pset.edit_pset", f, pset=ps, properties=props)
        by_al.setdefault(st.alignment.id(), []).append(el)
        rep["elements"] += 1
        rep["alignments"][st.name] = rep["alignments"].get(st.name, 0) + 1
    for aid, els in sorted(by_al.items()):
        al = f.by_id(aid)
        f.create_entity("IfcRelPositions", GlobalId=_guid(al.GlobalId, "positions"),
                        OwnerHistory=owner, Name=REL_NAME,
                        RelatingPositioningElement=al, RelatedProducts=els)
    if f is not path_or_file:
        f.write(str(out or path_or_file))
    return rep


def anchors_from_model(model) -> dict:
    """{element name: anchor} from a bimforge StructureModel's spec-placed
    elements (Element.placed_on), in the IFC's project unit (metres: emit_ifc
    writes SI)."""
    k = getattr(model.ctx, "ft_to_m", None) or 0.3048006096012192
    out = {}
    for el in model.elements:
        p = getattr(el, "placed_on", None)
        if not p:
            continue
        right = str(p.get("side", "Rt")).strip().upper() in ("RT", "R", "RIGHT")
        off = float(p.get("offset", 0.0))
        out[el.name] = {"alignment": p["alignment"], "station": float(p["station"]) * k,
                        "offset_left": (-off if right else off) * k}
    return out
