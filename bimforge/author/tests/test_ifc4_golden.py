"""Golden bytes for the IFC4 (and facility-less IFC4X3) writer paths (#318).

#318 added an opt-in IFC4X3 facility tree to emit_ifc / federate. Its contract
is that nothing changes unless `project.facility` is set under IFC4X3: IFC4
output stays byte-identical, and so does IFC4X3 output without a facility.
These digests were recorded on the writer BEFORE #318 landed, so a change to
any of them means an existing consumer's IFC changed.

The federation entry is a canonical signature (see `_federation_signature`),
not bytes: pre-#318 federate output was not byte-deterministic, so there were
no stable bytes to record. #318 made it byte-deterministic (one-product
containment calls, deterministic containment ids, pinned relationship order)
without changing what the file says, which is exactly what the signature pins.

The emit digests cover the DATA section only. The STEP header carries the
ifcopenshell version, which says nothing about what bimforge wrote. A different
ifcopenshell can still legitimately change the entities its api usecases mint,
so on a version other than the recorded one a mismatch skips (with the new
digest in the reason) instead of failing: re-record the digests then, after
checking the diff is ifcopenshell's and not ours.
"""
from __future__ import annotations

import hashlib
import uuid

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author.emit_ifc import emit_combined_ifc, emit_ifc  # noqa: E402
from bimforge.author.federate import federate  # noqa: E402
from bimforge.author.model import Element, StructureModel  # noqa: E402
from bimforge.author.primitives import Prism  # noqa: E402
from bimforge.author.project import ProjectContext  # noqa: E402

#: the ifcopenshell the digests below were recorded with
RECORDED_WITH = "0.9.0"

GOLDEN = {
    "ifc4_single":
        "213e0fe01192b9e1b52ace2f009ad14a79a5a9e9987c1c1a4323e1f9b623724e",
    "ifc4_combined":
        "fbb88f0d5a835e0017265e1c4c268f3b5895c5751bc4593c6a29cd22610ac32f",
    "ifc4x3_no_facility":
        "0720b7ec6360a28a9922f2eb1f5f3870c02517a64d0724439d12f2bb191bfd6f",
    "ifc4_federated":
        "98a3dd0ad463d6ddedd7a64f2acc127b2a48c0dc9cec9999d98dcf40e603e6a3",
}


def _ctx(schema="IFC4", name="Golden Fixture"):
    return ProjectContext(name=name, schema=schema, epsg=2226,
                          base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
                          guid_ns=uuid.UUID("8d0c2f6e-3b1a-4c5d-9e7f-318031803180"))


def _model(name, schema="IFC4"):
    m = StructureModel(name, _ctx(schema))
    for i, x in enumerate((0.0, 60.0)):
        p = Prism(f"Abut {i+1} footing", [(-4, -10), (4, -10), (4, 10), (-4, 10)],
                  z_bot=0.0, z_top=3.0, ifc="IfcFooting")
        m.add(Element.from_geometry(p.name, p, ifc_class="IfcFooting", x_ft=x,
                                    classifications=["F-CONC"],
                                    material="Concrete"))
    deck = Prism("Deck slab", [(0, -12), (60, -12), (60, 12), (0, 12)],
                 z_bot=12.0, z_top=13.5, ifc="IfcSlab")
    m.add(Element.from_geometry(deck.name, deck, ifc_class="IfcSlab",
                                classifications=["D-CONC"], material="Concrete"))
    m.assemblies["footings"] = ["Abut 1 footing", "Abut 2 footing"]
    return m


def _digest(path) -> str:
    # LF-normalized: ifcopenshell writes the SPF in text mode, so the same
    # model is CRLF on Windows and LF on Linux.
    data = path.read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data[data.index(b"DATA;"):]).hexdigest()


def _federation_signature(path) -> str:
    """A canonical digest of a federated file's MEANING, not its bytes.

    Before #318 federate was not byte-deterministic: `spatial.assign_container`
    over several products iterates a Python set while it re-localizes their
    placements (so placement entities are created in a run-dependent order),
    and the per-source containment relationships got random GlobalIds. A byte
    digest of that output cannot be recorded. This signature covers what a
    consumer reads: every IfcRoot's GlobalId/class/name, every product's
    container, spatial parent and world placement, and every relationship's
    members by GlobalId (containment rels by their structure instead of their
    old random id).
    """
    import ifcopenshell.util.placement as up
    f = ifcopenshell.open(str(path))
    rows = []
    for p in f.by_type("IfcProduct"):
        cont = [r.RelatingStructure.GlobalId
                for r in getattr(p, "ContainedInStructure", None) or ()]
        parent = [r.RelatingObject.GlobalId for r in p.Decomposes or ()]
        mtx = (up.get_local_placement(p.ObjectPlacement).round(6).tolist()
               if p.ObjectPlacement else None)
        rows.append(("P", p.GlobalId, p.is_a(), p.Name, cont, parent, mtx))
    for r in f.by_type("IfcRelationship"):
        members = []
        for i in range(len(r)):
            v = r[i]
            if hasattr(v, "GlobalId"):
                members.append(v.GlobalId)
            elif isinstance(v, (list, tuple)) and v and hasattr(v[0], "GlobalId"):
                members.append(sorted(x.GlobalId for x in v))
        rid = ("-" if r.is_a("IfcRelContainedInSpatialStructure")
               else r.GlobalId)
        rows.append(("R", r.is_a(), rid, members))
    for r in f.by_type("IfcRoot"):
        if not r.is_a("IfcProduct") and not r.is_a("IfcRelationship"):
            rows.append(("O", r.GlobalId, r.is_a(), getattr(r, "Name", None)))
    rows.sort(key=repr)
    return hashlib.sha256(repr(rows).encode()).hexdigest()


def _check(key, path, digest=_digest):
    got = digest(path)
    if got == GOLDEN[key]:
        return
    if ifcopenshell.version != RECORDED_WITH:
        pytest.skip(f"{key}: digest {got} differs under ifcopenshell "
                    f"{ifcopenshell.version} (recorded with {RECORDED_WITH})")
    assert got == GOLDEN[key], f"{key}: IFC bytes changed (got {got})"


def test_ifc4_single_structure_bytes_unchanged(tmp_path):
    out = tmp_path / "single.ifc"
    emit_ifc(_model("Bridge"), str(out))
    _check("ifc4_single", out)


def test_ifc4_combined_bytes_unchanged(tmp_path):
    out = tmp_path / "combined.ifc"
    emit_combined_ifc([_model("Bridge"), _model("Culvert")], str(out))
    _check("ifc4_combined", out)


def test_ifc4x3_without_facility_bytes_unchanged(tmp_path):
    out = tmp_path / "x3.ifc"
    emit_ifc(_model("Bridge", "IFC4X3_ADD2"), str(out))
    _check("ifc4x3_no_facility", out)


def test_ifc4_federation_bytes_unchanged(tmp_path):
    a, b = tmp_path / "a.ifc", tmp_path / "b.ifc"
    emit_ifc(_model("Bridge"), str(a))
    emit_ifc(_model("Culvert"), str(b))
    out = tmp_path / "fed.ifc"
    federate([(a, "Bridge"), (b, "Culvert")], str(out), _ctx())
    _check("ifc4_federated", out, _federation_signature)
