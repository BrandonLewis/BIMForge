"""IFC-level model federation — merge N co-registered IFCs into one (#193).

Solved ad hoc at least three times across earlier site builds, each hitting
the same two problems: a merged representation arrives pointing at a COPY of
its source's geometric context (several silently-divergent definitions of one
frame), and two independently authored models collide on GlobalId the moment
they share a file.

`federate` merges each source's products under a per-source storey, carries the
relationships that give a product meaning (property sets, classifications,
materials, the openings that void it, assemblies, connections), re-points every
representation onto ONE geometric context, and applies **stable per-source
GlobalId namespacing** so a collision is impossible and the mapping is
deterministic (same source key + same source id -> same federated id).

IFC4X3 facility trees (#318). A 4X3 source written with `project.facility`
carries an IfcSite > IfcBridge/IfcRoad/... > IfcBridgePart/... tree. Its
facility subtree (the facility, its parts, their aggregation and the
containment of every product in them) is carried whole and hung under the
target's IfcSite instead of being flattened into a storey; the products a
`site`-kind source contains directly in its IfcSite (terrain) are contained in
the target's IfcSite. Anything else a 4X3 source holds (a building/storey tree)
still lands in a per-source storey, created only if needed. Every source must
share one schema, and it must be the target ctx's: mixing IFC4 and IFC4X3 is
refused, because an entity cannot be copied across schemas. IFC4 sources keep
the storey behaviour.

It MERGES, it does not re-author: quantities/classifications/materials/styles
travel with the product intact, so the federated file says what its sources do.
It does NOT reproject — sources must already sit on the same base point (the
house convention keeps geometry near the origin and the datum in
IfcMapConversion), and a source whose length unit is not SI metre is refused
rather than silently rescaled.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from pathlib import Path

# relationships that carry a product's meaning; everything else about a product
# (placement, representation) travels with the product itself.
_CARRIED = ("IfcRelDefinesByProperties", "IfcRelAssociatesClassification",
            "IfcRelAssociatesMaterial", "IfcRelVoidsElement",
            "IfcRelAggregates", "IfcRelConnectsElements",
            "IfcRelDefinesByType")


@dataclass
class FederationResult:
    products: int = 0
    storeys: int = 0
    merged_contexts: int = 0
    per_source: dict = field(default_factory=dict)   # storey name -> product count
    #: IFC4X3 facilities carried whole under the target IfcSite (#318).
    facilities: int = 0
    #: products contained directly in the target IfcSite (`site`-kind sources).
    site_products: int = 0


class MixedSchemaError(ValueError):
    """Federation sources (or the target ctx) disagree on the IFC schema."""


def _length_unit_is_metre(f) -> bool:
    ua = f.by_type("IfcUnitAssignment")
    for u in (ua[0].Units if ua else ()):
        if getattr(u, "UnitType", None) == "LENGTHUNIT":
            return u.is_a("IfcSIUnit") and u.Name == "METRE" and not u.Prefix
    return False


def _schema_of(f) -> str:
    return str(getattr(f, "schema_identifier", None) or f.schema).upper()


def _is_4x3(f) -> bool:
    return _schema_of(f).startswith("IFC4X3")


def _storey(f, ctx, building, name: str):
    import ifcopenshell.api
    import numpy as np
    s = ifcopenshell.api.run("root.create_entity", f,
                             ifc_class="IfcBuildingStorey", name=name)
    s.GlobalId = ctx.guid(f"federated/storey/{name}")
    ifcopenshell.api.run("aggregate.assign_object", f, products=[s],
                         relating_object=building)
    ifcopenshell.api.run("geometry.edit_object_placement", f, product=s,
                         matrix=np.eye(4))
    return s


def _contain(tgt, products, structure, rel_key: str, ctx) -> None:
    """Contain `products` in `structure`, ONE product per call, and give the
    containment relationship a deterministic GlobalId.

    One per call: spatial.assign_container iterates a Python set while it
    re-localizes the products' placements, so a multi-product call creates the
    placement entities in a run-dependent order. The relationship it mints
    carries a random GlobalId; `rel_key` replaces it (the rel is shared by
    every product contained in `structure`, so one key per structure)."""
    import ifcopenshell.api
    rel = None
    for p in products:
        rel = ifcopenshell.api.run("spatial.assign_container", tgt,
                                   products=[p], relating_structure=structure)
    if rel is not None:
        rel.GlobalId = ctx.guid(rel_key)


def _facility_subtree(src) -> list:
    """The IFC4X3 facilities hanging off a source's IfcSite, and every spatial
    element below them (parts, nested facilities), in a deterministic order:
    file order for the roots, relationship order below them."""
    roots = []
    for fac in src.by_type("IfcFacility"):
        if fac.is_a("IfcBuilding"):
            continue
        parents = [r.RelatingObject for r in fac.Decomposes or ()]
        if any(p.is_a("IfcSite") for p in parents) or not parents:
            roots.append(fac)
    out, seen, stack = [], set(), list(reversed(roots))
    while stack:
        node = stack.pop()
        if node.id() in seen:
            continue
        seen.add(node.id())
        out.append(node)
        kids = [c for r in node.IsDecomposedBy or ()
                for c in r.RelatedObjects if c.is_a("IfcSpatialElement")]
        stack.extend(reversed(kids))
    return out, roots


def _site_contained_ids(src) -> set:
    return {p.id() for rel in src.by_type("IfcRelContainedInSpatialStructure")
            if rel.RelatingStructure.is_a("IfcSite")
            for p in rel.RelatedElements}


def _uses_facility_tree(src) -> bool:
    """A 4X3 source whose products sit in a facility tree or directly in the
    site (a `site`-kind source) — as opposed to a building/storey tree."""
    if not _is_4x3(src):
        return False
    subtree, _roots = _facility_subtree(src)
    return bool(subtree) or bool(_site_contained_ids(src))


def _carry_relationships(tgt, src, added: dict, roots: dict,
                         kinds: tuple = _CARRIED) -> None:
    for kind in kinds:
        for rel in src.by_type(kind):
            if kind == "IfcRelVoidsElement":
                if rel.RelatingBuildingElement.id() in added:
                    nr = tgt.add(rel)
                    roots[nr.id()] = nr
                continue
            # aggregates and nests travel whole (tgt.add keeps a nest's ORDERED
            # membership) or not at all: a partial copy would misstate the host
            if kind in ("IfcRelAggregates", "IfcRelNests"):
                if (rel.RelatingObject.id() in added
                        and all(o.id() in added for o in rel.RelatedObjects)):
                    nr = tgt.add(rel)
                    roots[nr.id()] = nr
                continue
            rel_of = [o for o in (getattr(rel, "RelatedObjects", None) or ())
                      if o.id() in added]
            if rel_of:
                new = tgt.add(rel)
                new.RelatedObjects = [added[o.id()] for o in rel_of]
                roots[new.id()] = new
                # IfcRelDefinesByType also pulls in the IfcTypeObject; it is an
                # IfcRoot too and can collide across sources, so re-id it.
                rt = getattr(new, "RelatingType", None)
                if rt is not None:
                    roots[rt.id()] = rt

    # styles/layers point AT representation items, so adding a product does not
    # reach them; adding now resolves onto the copies already made (add is
    # identity-keyed, so nothing duplicates).
    for st in src.by_type("IfcStyledItem"):
        if st.Item is not None:
            tgt.add(st)
    for lyr in src.by_type("IfcPresentationLayerAssignment"):
        tgt.add(lyr)


def _namespace(roots: dict, storey_name: str, ctx) -> None:
    # stable per-source GlobalId namespacing: every merged root's id becomes a
    # deterministic function of (this source, its original id), so two sources
    # sharing an id (emit_ifc derives a relationship id from what it relates,
    # so the same material association arrives identical from two models) can
    # never collide, and re-running a source maps in unchanged.
    for r in roots.values():
        if r.is_a("IfcRoot"):
            r.GlobalId = ctx.guid(f"{storey_name}/{r.GlobalId}")


def _merge_source(tgt, src, storey_name: str, dest_storey, ctx) -> int:
    """The storey path (IFC4 sources, and 4X3 sources with no facility tree):
    every non-feature product is re-contained in this source's storey."""
    products = [p for p in src.by_type("IfcProduct")
                if not p.is_a("IfcSpatialElement")
                and not p.is_a("IfcSpatialStructureElement")]
    keep = [p for p in products if not p.is_a("IfcFeatureElement")]
    added = {p.id(): tgt.add(p) for p in products}
    # every merged IfcRoot to re-id, keyed by target id so a type shared by
    # several IfcRelDefinesByType rels is namespaced exactly once (double
    # namespacing would apply ctx.guid twice, defeating stability).
    roots = {e.id(): e for e in added.values()}
    _carry_relationships(tgt, src, added, roots)
    _namespace(roots, storey_name, ctx)
    _contain(tgt, [added[p.id()] for p in keep], dest_storey,
             f"federated/contained/{storey_name}", ctx)
    return len(keep)


def _repoint_to_site(tgt, spatial, site) -> None:
    """Hang a carried facility's placement off the TARGET site's placement.

    `tgt.add` copied the facility's placement chain, so it points at a COPY of
    the source site's placement. When that copy and the target site's placement
    are the same transform (the house convention: both are emit_ifc's origin
    placement) re-point onto the target's and drop the orphaned copy; when they
    differ, keep the copy, which is still world-correct."""
    import ifcopenshell.util.element
    import ifcopenshell.util.placement
    import numpy as np
    pl = getattr(spatial, "ObjectPlacement", None)
    tp = getattr(site, "ObjectPlacement", None)
    if pl is None or tp is None or not pl.is_a("IfcLocalPlacement"):
        return
    old = pl.PlacementRelTo
    if old is None or old == tp:
        return
    if not np.allclose(ifcopenshell.util.placement.get_local_placement(old),
                       ifcopenshell.util.placement.get_local_placement(tp)):
        return
    pl.PlacementRelTo = tp
    if not tgt.get_total_inverses(old):
        ifcopenshell.util.element.remove_deep2(tgt, old)


def _merge_facility_source(tgt, src, name: str, ctx, site, make_storey):
    """The IFC4X3 facility path (#318). Returns (products, facilities,
    site_products)."""
    import ifcopenshell.api
    subtree, fac_roots = _facility_subtree(src)
    spatial_ids = {s.id() for s in subtree}
    site_ids = _site_contained_ids(src)
    products = [p for p in src.by_type("IfcProduct")
                if not p.is_a("IfcSpatialElement")
                and not p.is_a("IfcSpatialStructureElement")]
    keep = [p for p in products if not p.is_a("IfcFeatureElement")]

    # the facility subtree first (deterministic order), then the products
    added = {s.id(): tgt.add(s) for s in subtree}
    added.update({p.id(): tgt.add(p) for p in products})
    roots = {e.id(): e for e in added.values()}
    # incl. facility -> parts; nests too, because a nested product is not
    # re-contained below (the storey path contains every product, so it can
    # leave nests behind without orphaning anything)
    _carry_relationships(tgt, src, added, roots, _CARRIED + ("IfcRelNests",))

    # containment: carried whole when it is IN the facility subtree; the site's
    # own products go to the target site; a building/storey's go to a storey.
    to_site, to_storey, contained = [], [], set()
    for rel in src.by_type("IfcRelContainedInSpatialStructure"):
        members = [p for p in rel.RelatedElements if p.id() in added]
        contained |= {p.id() for p in members}
        if rel.RelatingStructure.id() in spatial_ids:
            nr = tgt.add(rel)
            nr.RelatedElements = [added[p.id()] for p in members]
            roots[nr.id()] = nr
        elif rel.RelatingStructure.is_a("IfcSite"):
            to_site += members
        else:
            to_storey += members
    # a product in no container and in no aggregate/nest/void is an orphan:
    # the storey path's rule (every kept product lands in the storey) holds.
    for p in keep:
        if p.id() in contained or p.id() in site_ids:
            continue
        nested = any(r.RelatingObject.id() in added
                     and all(o.id() in added for o in r.RelatedObjects)
                     for r in getattr(p, "Nests", None) or ())
        if p.Decomposes or nested or getattr(p, "VoidsElements", None):
            continue
        to_storey.append(p)

    _namespace(roots, name, ctx)

    for fac in fac_roots:
        new = added[fac.id()]
        ifcopenshell.api.run("aggregate.assign_object", tgt, products=[new],
                             relating_object=site)
        _repoint_to_site(tgt, new, site)
    if to_site:
        _contain(tgt, [added[p.id()] for p in to_site], site,
                 "federated/contained/site", ctx)
    if to_storey:
        _contain(tgt, [added[p.id()] for p in to_storey], make_storey(),
                 f"federated/contained/{name}", ctx)
    return len(keep), len(fac_roots), len(to_site)


def _unify_contexts(f, model_ctx, body_ctx) -> int:
    """Re-point every representation onto the one model/body context and delete
    the merged copies. Returns the number of contexts collapsed."""
    keep = {model_ctx.id(), body_ctx.id()}
    for rep in f.by_type("IfcRepresentation"):
        c = rep.ContextOfItems
        if c is not None and c.id() not in keep:
            rep.ContextOfItems = (body_ctx
                                  if rep.RepresentationIdentifier == "Body"
                                  else model_ctx)
    dead = {c.id() for c in f.by_type("IfcGeometricRepresentationContext")
            if c.id() not in keep}
    for cid in dead:                       # drop from IfcProject.RepresentationContexts
        c = f.by_id(cid)
        for inv in f.get_inverse(c):
            if inv.is_a("IfcProject"):
                inv.RepresentationContexts = tuple(
                    x for x in inv.RepresentationContexts if x.id() != cid)
    # subcontexts reference their parent, so remove them first, then parents
    for cid in sorted(dead, key=lambda i: not f.by_id(i).is_a(
            "IfcGeometricRepresentationSubContext")):
        f.remove(f.by_id(cid))
    return len(dead)


def _dedupe_nonproduct_globalids(f, ctx) -> int:
    """Re-issue any duplicate NON-product IfcRoot GlobalId deterministically.

    Products are namespaced per source at merge time; but relationships the
    federation itself mints (spatial containment per source, the storey's
    aggregate) are api-minted and two sources can land the same id. A duplicate
    IfcRoot id violates IfcRoot.UR1 the moment they share a file, so re-issue
    the later non-product collisions (mirrors emit_ifc's determinism sweep).
    """
    seen: set = set()
    n = 0
    for r in f.by_type("IfcRoot"):
        if r.GlobalId not in seen:
            seen.add(r.GlobalId)
            continue
        if r.is_a("IfcProduct"):
            continue                       # products are the merge key; _assert catches
        while r.GlobalId in seen:
            r.GlobalId = ctx.guid(f"federated/dedup/{r.id()}/{r.GlobalId}")
        seen.add(r.GlobalId)
        n += 1
    return n


def _assert_products_unique(f) -> None:
    seen: dict = {}
    for p in f.by_type("IfcProduct"):
        first = seen.setdefault(p.GlobalId, p)
        if first is not p:
            raise ValueError(
                f"duplicate product GlobalId {p.GlobalId}: {first.is_a()} "
                f"{first.Name!r} and {p.is_a()} {p.Name!r}")


def _open_sources(sources, ctx, unit_check: bool):
    """Open every source BEFORE anything is written, and refuse a federation
    whose sources (or target ctx) disagree on the schema."""
    import ifcopenshell
    opened = []
    for src_path, name in sources:
        src = ifcopenshell.open(str(src_path))
        if unit_check and not _length_unit_is_metre(src):
            raise ValueError(
                f"{src_path}: length unit is not SI metre — a federation cannot "
                "silently rescale geometry")
        opened.append((Path(src_path), name, src))
    schemas = {_schema_of(src) for _p, _n, src in opened}
    if len(schemas) > 1:
        detail = ", ".join(f"{p.name}: {_schema_of(s)}" for p, _n, s in opened)
        raise MixedSchemaError(
            f"federate: sources mix IFC schemas ({detail}). An entity cannot be "
            "copied across schemas; re-emit every source with one "
            "project.schema (IFC4X3_ADD2 to keep facility trees, IFC4 for "
            "mainstream viewers).")
    want = str(ctx.schema).upper()
    if schemas and schemas != {want}:
        raise MixedSchemaError(
            f"federate: the sources are {schemas.pop()} but the federation "
            f"ctx.schema is {ctx.schema}; give the target ctx the sources' "
            "schema.")
    return opened


def federate(sources, out_path: str, ctx, *, unit_check: bool = True
             ) -> FederationResult:
    """Merge co-registered source IFCs into one federated file at `out_path`.

    `sources` is a list of ``(ifc_path, storey_name)``; each source's products
    land under a storey of that name — or, for an IFC4X3 source written with
    a facility tree (#318), its facility subtree is carried under the target
    IfcSite (the name then only namespaces its GlobalIds). `ctx` is the
    ProjectContext for the federated file — its base point, guid_ns and
    schema, which must match the sources'. Returns a FederationResult.
    """
    import ifcopenshell

    from bimforge.author.emit_ifc import _pin_relationship_order, emit_ifc
    from bimforge.author.model import StructureModel

    opened = _open_sources(sources, ctx, unit_check)

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    # the target opens as a plain Site > Building > Storey file: a ctx facility
    # is a property of the SOURCES' trees, not something to mint here.
    base_ctx = (dataclasses.replace(ctx, facility=None)
                if getattr(ctx, "facility", None) is not None else ctx)
    emit_ifc(StructureModel(name="Federated Model", ctx=base_ctx),
             str(out_path))
    f = ifcopenshell.open(str(out_path))
    site = f.by_type("IfcSite")[0]
    building = f.by_type("IfcBuilding")[0]
    placeholder = f.by_type("IfcBuildingStorey")[0]
    model_ctx = next(c for c in f.by_type("IfcGeometricRepresentationContext")
                     if not c.is_a("IfcGeometricRepresentationSubContext"))
    body_ctx = next((c for c in f.by_type("IfcGeometricRepresentationSubContext")
                     if c.ContextIdentifier == "Body"), model_ctx)

    result = FederationResult()
    used_facility_path = False
    for src_path, name, src in opened:
        if _uses_facility_tree(src):
            used_facility_path = True
            storey: list = []

            def make_storey(name=name, storey=storey):
                if not storey:
                    storey.append(_storey(f, ctx, building, name))
                return storey[0]

            n, n_fac, n_site = _merge_facility_source(
                f, src, name, ctx, site, make_storey)
            result.facilities += n_fac
            result.site_products += n_site
        else:
            n = _merge_source(f, src, name, _storey(f, ctx, building, name),
                              ctx)
        result.per_source[name] = n
        result.products += n

    # the placeholder storey emit_ifc opened the file with holds nothing
    placeholder_pl = placeholder.ObjectPlacement
    for rel in list(f.get_inverse(placeholder)):
        f.remove(rel)
    f.remove(placeholder)
    # ...and on the facility path, neither may the building: an empty
    # IfcBuilding beside the facilities is a navigation dead end.
    if used_facility_path and not any(
            r.RelatedObjects for r in building.IsDecomposedBy or ()):
        for rel in list(building.Decomposes or ()):
            rest = [o for o in rel.RelatedObjects if o != building]
            if rest:
                rel.RelatedObjects = rest
            else:
                f.remove(rel)
        for rel in list(building.IsDecomposedBy or ()):
            f.remove(rel)
        import ifcopenshell.util.element
        if placeholder_pl is not None and not f.get_total_inverses(
                placeholder_pl):
            ifcopenshell.util.element.remove_deep2(f, placeholder_pl)
        bpl = building.ObjectPlacement
        f.remove(building)
        if bpl is not None and not f.get_total_inverses(bpl):
            ifcopenshell.util.element.remove_deep2(f, bpl)
    if used_facility_path:
        # carried spatial elements and site products are re-localized onto the
        # target's placements, which strands the copies of each source's
        # site/building/storey placements; nothing references them any more.
        import ifcopenshell.util.element
        for pl in list(f.by_type("IfcLocalPlacement")):
            if not f.get_total_inverses(pl):
                ifcopenshell.util.element.remove_deep2(f, pl)

    _dedupe_nonproduct_globalids(f, ctx)
    _assert_products_unique(f)
    result.merged_contexts = _unify_contexts(f, model_ctx, body_ctx)
    # ifcopenshell.api's aggregate/containment usecases merge members through
    # Python set unions, so relationship member order is run-dependent; sort
    # them by GlobalId exactly as emit_ifc does (#318: byte-deterministic).
    _pin_relationship_order(f)
    result.storeys = len(f.by_type("IfcBuildingStorey"))
    f.write(str(out_path))
    return result
