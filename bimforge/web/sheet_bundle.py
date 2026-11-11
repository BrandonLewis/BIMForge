"""The sheet bundle: an IFC flattened into the tables a spreadsheet edits,
in chunks, with the geometry beside each chunk (`est-bim sheet-bundle`).

This is what the IFC Navigator Excel add-in loads. The add-in never parses
IFC: it reads this directory, writes the tables into sheets, and hands back
a change-set (`bimforge.web.changes`) that `est-bim apply-changes` writes
into the IFC with IfcOpenShell. Reading and writing stay here, in Python,
where the byte-determinism discipline lives.

A bundle is a directory::

    manifest.json              contract bimforge-sheet/1 (below)
    chunks/<id>.json           one chunk's tables
    chunks/<id>.glb            that chunk's per-element meshes (optional)

The manifest::

    {"contract": "bimforge-sheet/1",
     "model": {"file", "schema", "project", "site", "generator",
               "counts": {"elements", "chunks", "properties", "types"}},
     "units": {"length": "m", "area": "m2", "volume": "m3", "mass": "kg"},
     "geometry": {"format": "glb", "up": "Y", "offset_m": [x, y, z]} | null,
     "psets": [every property-set name seen, sorted],
     "chunks": [{"id", "label", "elements", "properties",
                 "files": {"data": "chunks/<id>.json",
                           "geometry": "chunks/<id>.glb" | null}}]}

A chunk is the elements of one spatial container (`--chunk-by container`,
the default) or everything (`none`). The add-in loads one chunk at a time,
so a large model costs one container's worth of cells and triangles, not
the whole file's. A chunk's tables::

    {"chunk": {"id", "label"},
     "elements":   [{"global_id", "ifc_class", "predefined_type", "name",
                     "type", "type_global_id", "container", "whole",
                     "codes": [..]}],
     "properties": [{"global_id", "pset", "property", "value",
                     "value_type"}],          the element's OWN single values
     "types":      [{"global_id", "name", "ifc_class", "pset", "property",
                     "value", "value_type"}], the types' single values
     "quantities": [{"global_id", "quantity", "value"}]}   SI, read-only

Property rows carry the IFC value type (`IfcLabel`, `IfcBoolean`,
`IfcLengthMeasure`, ...) so the sheet can validate a cell and the
change-set can write the value back with the same type. Quantities are the
model's `Qto_*` values scaled to SI (`bimforge.bim.ifc_takeoff`): they
come from geometry, so the sheet shows them and refuses to edit them.

Geometry is the geometry iterator's tessellation (`bimforge.bim.ifc_mesh`),
the same triangles the takeoff's volume and SFCA checks run on, written
with `bimforge.web.glb`. Elements are sorted by GlobalId everywhere, and
nothing carries a timestamp, so a rebuild of an unchanged model is
byte-identical.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CONTRACT = "bimforge-sheet/1"
UNITS = {"length": "m", "area": "m2", "volume": "m3", "mass": "kg"}
_SLUG = re.compile(r"[^a-z0-9]+")


def _generator() -> str:
    try:
        from importlib.metadata import version
        return f"bimforge {version('bimforge')}"
    except Exception:                                   # not installed
        return "bimforge"


def _slug(text: str, taken: set) -> str:
    base = _SLUG.sub("-", (text or "").lower()).strip("-") or "chunk"
    slug, n = base, 2
    while slug in taken:
        slug, n = f"{base}-{n}", n + 1
    taken.add(slug)
    return slug


def _container(el):
    """The spatial element the element (or the whole it is a part of) sits in."""
    for rel in getattr(el, "ContainedInStructure", None) or ():
        return rel.RelatingStructure
    for rel in getattr(el, "Decomposes", None) or ():
        if rel.is_a("IfcRelAggregates") and rel.RelatingObject.is_a("IfcElement"):
            return _container(rel.RelatingObject)
    return None


def _whole(el):
    for rel in getattr(el, "Decomposes", None) or ():
        if rel.is_a("IfcRelAggregates") and rel.RelatingObject.is_a("IfcElement"):
            return rel.RelatingObject.GlobalId
    return None


def _predefined(el):
    import ifcopenshell.util.element as ue
    try:
        pdt = ue.get_predefined_type(el)
    except Exception:
        pdt = getattr(el, "PredefinedType", None)
    return None if pdt in (None, "NOTDEFINED") else pdt


def _single_values(obj, *, inherit: bool) -> list[tuple[str, str, object, str]]:
    """(pset, property, value, value_type) for every IfcPropertySingleValue
    on `obj`'s property sets (not quantity sets), psets sorted, properties
    in their IFC order."""
    import ifcopenshell.util.element as ue
    out = []
    psets = ue.get_psets(obj, psets_only=True, should_inherit=inherit, verbose=True)
    for pset_name in sorted(psets):
        for prop, info in psets[pset_name].items():
            if prop == "id" or not isinstance(info, dict):
                continue
            if info.get("class") != "IfcPropertySingleValue":
                continue
            out.append((pset_name, prop, info.get("value"), info.get("value_type")))
    return out


def _element_row(el, codes: list[str]) -> dict:
    import ifcopenshell.util.element as ue
    typ = ue.get_type(el)
    cont = _container(el)
    return {
        "global_id": el.GlobalId,
        "ifc_class": el.is_a(),
        "predefined_type": _predefined(el),
        "name": el.Name,
        "type": (typ.Name if typ is not None else None),
        "type_global_id": (typ.GlobalId if typ is not None else None),
        "container": (cont.Name or cont.GlobalId) if cont is not None else None,
        "whole": _whole(el),
        "codes": codes,
    }


def build_sheet_bundle(ifc_path, *, chunk_by: str = "container",
                       geometry: bool = True) -> dict:
    """{"manifest": ..., "chunks": {id: tables}, "meshes": {id: [(guid,
    verts, faces, extras)]}} for one IFC. `write_sheet_bundle` lays it out.
    `chunk_by` is "container" or "none"."""
    import ifcopenshell
    import ifcopenshell.util.element as ue
    from bimforge.bim.ifc_takeoff import (_unit_scales, classifications_of,
                                          quantities_of)

    if chunk_by not in ("container", "none"):
        raise ValueError(f"chunk_by must be 'container' or 'none', not {chunk_by!r}")
    path = Path(ifc_path)
    model = ifcopenshell.open(str(path))
    scales = _unit_scales(model)
    elements = sorted(model.by_type("IfcElement"), key=lambda e: e.GlobalId)

    # group by container (a part sits with its whole's container)
    groups: dict[str, list] = {}
    labels: dict[str, str] = {}
    taken: set = set()
    for el in elements:
        if chunk_by == "none":
            key, label = "all", "All elements"
        else:
            cont = _container(el)
            key = cont.GlobalId if cont is not None else "~unplaced"
            label = (cont.Name or cont.GlobalId) if cont is not None else "Unplaced"
        groups.setdefault(key, []).append(el)
        labels.setdefault(key, label)
    order = sorted(groups, key=lambda k: (k == "~unplaced", labels[k], k))
    ids = {k: ("all" if chunk_by == "none" else
               _slug(labels[k], taken) if k != "~unplaced" else _slug("unplaced", taken))
           for k in order}

    meshes_by_guid = {}
    offset = [0.0, 0.0, 0.0]
    if geometry:
        import numpy as np
        from bimforge.bim.ifc_mesh import element_meshes
        for gid, _name, _typ, verts, faces in element_meshes(str(path)):
            meshes_by_guid[gid] = (verts, faces)
        if meshes_by_guid:
            lo = np.min([v.min(axis=0) for v, _ in meshes_by_guid.values()], axis=0)
            offset = [float(x) for x in np.floor(lo)]

    chunks, meshes, psets = {}, {}, set()
    n_props = n_types = 0
    for key in order:
        cid = ids[key]
        rows, props, types, qtos, type_seen = [], [], [], [], set()
        chunk_meshes = []
        for el in groups[key]:
            codes = sorted({c["code"] for c in classifications_of(el) if c.get("code")})
            rows.append(_element_row(el, codes))
            for pset, prop, value, vtype in _single_values(el, inherit=False):
                psets.add(pset)
                props.append({"global_id": el.GlobalId, "pset": pset, "property": prop,
                              "value": value, "value_type": vtype})
            for q, v in sorted(quantities_of(el, scales).items()):
                qtos.append({"global_id": el.GlobalId, "quantity": q, "value": round(float(v), 9)})
            typ = ue.get_type(el)
            if typ is not None and typ.GlobalId not in type_seen:
                type_seen.add(typ.GlobalId)
                for pset, prop, value, vtype in _single_values(typ, inherit=False):
                    psets.add(pset)
                    types.append({"global_id": typ.GlobalId, "name": typ.Name, "ifc_class": typ.is_a(),
                                  "pset": pset, "property": prop, "value": value, "value_type": vtype})
            m = meshes_by_guid.get(el.GlobalId)
            if m is not None:
                chunk_meshes.append((el.GlobalId, m[0], m[1], {"ifc_class": el.is_a()}))
        types.sort(key=lambda r: (r["global_id"], r["pset"], r["property"]))
        chunks[cid] = {"chunk": {"id": cid, "label": labels[key]}, "elements": rows,
                       "properties": props, "types": types, "quantities": qtos}
        meshes[cid] = chunk_meshes
        n_props += len(props)
        n_types += len(type_seen)

    project = next(iter(model.by_type("IfcProject")), None)
    site = next(iter(model.by_type("IfcSite")), None)
    manifest = {
        "contract": CONTRACT,
        "model": {"file": path.name, "schema": model.schema,
                  "project": (project.Name if project else None),
                  "site": (site.Name if site else None),
                  "generator": _generator(),
                  "counts": {"elements": len(elements), "chunks": len(chunks),
                             "properties": n_props, "types": n_types}},
        "units": dict(UNITS),
        "geometry": ({"format": "glb", "up": "Y", "offset_m": offset}
                     if geometry and meshes_by_guid else None),
        "psets": sorted(psets),
        "chunks": [{"id": cid, "label": chunks[cid]["chunk"]["label"],
                    "elements": len(chunks[cid]["elements"]),
                    "properties": len(chunks[cid]["properties"]),
                    "files": {"data": f"chunks/{cid}.json",
                              "geometry": (f"chunks/{cid}.glb" if meshes[cid] else None)}}
                   for cid in (ids[k] for k in order)],
    }
    return {"manifest": manifest, "chunks": chunks, "meshes": meshes}


def dump_json(doc) -> str:
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False)


def write_sheet_bundle(bundle: dict, out_dir) -> Path:
    """Lay `build_sheet_bundle`'s result out as a directory; returns the
    manifest path."""
    from bimforge.web.glb import write_glb
    out = Path(out_dir)
    (out / "chunks").mkdir(parents=True, exist_ok=True)
    manifest = bundle["manifest"]
    offset = (manifest["geometry"] or {}).get("offset_m", (0.0, 0.0, 0.0))
    for entry in manifest["chunks"]:
        cid = entry["id"]
        (out / entry["files"]["data"]).write_text(dump_json(bundle["chunks"][cid]) + "\n",
                                                  encoding="utf-8")
        if entry["files"]["geometry"]:
            write_glb(bundle["meshes"][cid], out / entry["files"]["geometry"], offset=offset,
                      extras={"chunk": cid, "offset_m": list(offset), "units": "m"})
    (out / "manifest.json").write_text(dump_json(manifest) + "\n", encoding="utf-8")
    return out / "manifest.json"


def validate_manifest(manifest: dict) -> None:
    """Raise ValueError unless `manifest` is a manifest of this contract."""
    if not isinstance(manifest, dict) or manifest.get("contract") != CONTRACT:
        raise ValueError(f"not a {CONTRACT} manifest: contract="
                         f"{(manifest or {}).get('contract')!r}")
    for key in ("model", "units", "geometry", "psets", "chunks"):
        if key not in manifest:
            raise ValueError(f"manifest lacks {key!r}")
    seen = set()
    for c in manifest["chunks"]:
        if c["id"] in seen:
            raise ValueError(f"duplicate chunk id {c['id']!r}")
        seen.add(c["id"])
