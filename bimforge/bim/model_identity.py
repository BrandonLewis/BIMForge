"""The model's own identity: `BIMForge_Model` on the IfcProject (M.6).

Every bimforge writer that makes a file (`est-bim build`, `dxf2bim`,
`federate`) writes one property set on the file's IfcProject:

- `BuildId`: sha256 over the canonical source, the bimforge version and the
  schema. The same source built by the same bimforge into the same schema
  gets the same id, on any machine and after any rebuild;
- `BimforgeVersion`, `Schema`;
- `Source`: the spec's file name, the DXF's, or the federated sources'.

The canonical source is what the build reads, parsed, never the bytes on
disk: a spec and the files it names (paycodes, tables, alignments, a style
pack, a family module from outside bimforge), with the paths it writes to
left out; for dxf2bim, the layer map and the features read from the DXF
(a DXF re-saved unchanged keeps its id); for a federation, each source's
label and BuildId. A model emitted by a caller that names no source (a
script calling `emit_ifc`) is identified by the file as emitted.

The embedders (schedule, cost, estimate, alignments) leave the set alone:
it names the model as built, not what was added to it. Downstream tools
read `BuildId` from a `*_Model` set on the IfcProject; the property name
and the set's place stay fixed.
"""
from __future__ import annotations

import hashlib
import inspect
import json
from importlib import metadata
from pathlib import Path

import yaml

PSET = "BIMForge_Model"


def version() -> str:
    try:
        return metadata.version("bimforge")
    except metadata.PackageNotFoundError:
        return "unknown"


def build_id(source, schema: str) -> str:
    """sha256 hex over the canonical source, the bimforge version and the
    schema."""
    doc = {"source": source, "bimforge": version(), "schema": schema}
    text = json.dumps(doc, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_source(f) -> dict:
    """The source of a model nobody named: the file as it stands, entity by
    entity (the header carries nothing of the model)."""
    h = hashlib.sha256()
    for ent in f:
        h.update(str(ent).encode("utf-8"))
        h.update(b"\n")
    return {"file": h.hexdigest()}


def write(f, source, name: str | None) -> str:
    """Write the set on `f`'s IfcProject, replacing one already there, and
    return its BuildId. `source` is the canonical source (JSON-able).

    The set and its relationship are keyed under the IfcProject's GlobalId
    (`pset/<project id>/BIMForge_Model`), as the embedders key theirs."""
    import ifcopenshell.api
    import ifcopenshell.util.element

    from bimforge.bim import stable_ids
    project = f.by_type("IfcProject")[0]
    old = ifcopenshell.util.element.get_psets(project).get(PSET)
    if old:
        ifcopenshell.api.run("pset.remove_pset", f, product=project,
                             pset=f.by_id(old["id"]))
    bid = build_id(source, f.schema_identifier)
    props = {"BuildId": bid, "BimforgeVersion": version(),
             "Schema": f.schema_identifier}
    if name:
        props["Source"] = name
    pset = ifcopenshell.api.run("pset.add_pset", f, product=project, name=PSET)
    ifcopenshell.api.run("pset.edit_pset", f, pset=pset, properties=props)
    stable_ids.assign(f, pset, f"pset/{project.GlobalId}/{PSET}")
    (rel,) = pset.DefinesOccurrence
    stable_ids.assign(f, rel, f"rel/{rel.is_a()}/{pset.GlobalId}")
    return bid


def read(f) -> dict | None:
    """The set's properties on `f`'s IfcProject, or None."""
    import ifcopenshell.util.element
    projects = f.by_type("IfcProject")
    if not projects:
        return None
    props = ifcopenshell.util.element.get_psets(projects[0]).get(PSET)
    return {k: v for k, v in props.items() if k != "id"} if props else None


def _parsed(path: Path):
    """A file's content as the build reads it: YAML or JSON parsed, any
    other file as text with its line endings made LF, so a checkout on
    another platform keeps the id."""
    if path.suffix.lower() in (".yaml", ".yml", ".json"):
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def _tree(path: Path) -> dict:
    return {p.relative_to(path).as_posix(): _parsed(p)
            for p in sorted(path.rglob("*"))
            if p.is_file() and "__pycache__" not in p.parts}


#: `outputs:` keys that change the file; the rest only say where it goes
_OUTPUT_SETTINGS = ("ifc_allow_local", "ifc_sweeps", "ifc_instancing")


def spec_source(spec_path, builder=None, style_pack: str | None = None) -> dict:
    """The canonical source of `est-bim build`: the spec as written, each
    file it names replaced by that file's content, its output paths left
    out. `builder` is the family function; one from outside bimforge (a
    `--family-path` module) is part of the source. `style_pack` is the
    CLI's, over the spec's."""
    path = Path(spec_path)
    base = path.parent
    doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    doc["paycodes"] = _parsed(base / doc["paycodes"])
    doc["outputs"] = {k: v for k, v in (doc.get("outputs") or {}).items()
                      if k in _OUTPUT_SETTINGS}
    params = doc.get("params") or {}
    if params.get("tables_file"):
        params["tables_file"] = _parsed(base / params["tables_file"])
    proj = doc.get("project") or {}
    if proj.get("alignments"):
        proj["alignments"] = _parsed(base / proj["alignments"])
    pack = style_pack or doc.get("style_pack")
    if pack and (base / pack).is_dir():
        doc["style_pack"] = _tree(base / pack)
    elif pack:
        doc["style_pack"] = pack       # a package's, versioned with bimforge
    if builder is not None:
        src = inspect.getsourcefile(builder)
        here = Path(__file__).resolve().parents[1]
        if src and here not in Path(src).resolve().parents:
            doc["family_module"] = _parsed(Path(src))
    return doc


def features_source(features, config: dict) -> dict:
    """The canonical source of dxf2bim: the layer map and the features read
    from the DXF, each footprint as WKT."""
    return {"config": config,
            "features": [{**vars(ft), "polygon": ft.polygon.wkt}
                         for ft in features]}
