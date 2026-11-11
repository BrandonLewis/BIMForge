"""A minimal glTF 2.0 binary (GLB) writer for per-element meshes.

One node per element, named by its GlobalId, each with its own mesh of one
triangle primitive (float32 POSITION, uint32 indices). No materials, no
normals: the viewer computes flat normals and colours by element. This is
the geometry the Excel add-in's viewer measures on, and it is the SAME
tessellation the takeoff's mesh checks use (`bimforge.bim.ifc_mesh`), so a
viewer measurement agrees with the sheet.

Two transforms, both recorded by the caller in its manifest:

* an **offset**: georeferenced world coordinates (millions of metres) do
  not survive float32, so every vertex is shifted by `offset` first and
  the offset is written beside the file;
* **Z-up to Y-up**: glTF is Y-up, IFC is Z-up. `(x, y, z) -> (x, z, -y)`.
  Lengths and areas are invariant; a consumer that wants IFC coordinates
  back applies `(x, y, z) -> (x, -z, y)` and adds the offset.

Output is byte-deterministic for the same input: no timestamps, no
generator version in the asset block, and the caller sorts its elements.
numpy only; no glTF library.
"""
from __future__ import annotations

import json
import struct

_MAGIC = b"glTF"
_JSON = 0x4E4F534A
_BIN = 0x004E4942
_FLOAT = 5126
_UINT32 = 5125
_ARRAY_BUFFER = 34962
_ELEMENT_ARRAY_BUFFER = 34963
_TRIANGLES = 4


def _pad(b: bytes, fill: bytes) -> bytes:
    return b + fill * (-len(b) % 4)


def to_y_up(verts):
    """IFC Z-up metres -> glTF Y-up: (x, y, z) -> (x, z, -y)."""
    import numpy as np
    v = np.asarray(verts, dtype=float).reshape(-1, 3)
    return np.stack([v[:, 0], v[:, 2], -v[:, 1]], axis=1)


def write_glb(meshes, path, *, offset=(0.0, 0.0, 0.0), extras: dict | None = None) -> dict:
    """Write `meshes` — an iterable of (name, verts (N,3) m, faces (M,3) int,
    extras dict | None) — as one GLB at `path`, in the order given.

    `offset` (IFC metres, Z-up) is subtracted from every vertex BEFORE the
    Y-up rotation. `extras` lands on the scene. Returns {"nodes", "bytes",
    "triangles"}.
    """
    import numpy as np

    off = np.asarray(offset, dtype=float).reshape(3)
    bin_parts: list[bytes] = []
    views, accessors, gltf_meshes, nodes = [], [], [], []
    tri_total = 0
    cursor = 0

    def view(data: bytes, target: int) -> int:
        nonlocal cursor
        padded = _pad(data, b"\0")
        views.append({"buffer": 0, "byteOffset": cursor, "byteLength": len(data), "target": target})
        bin_parts.append(padded)
        cursor += len(padded)
        return len(views) - 1

    for name, verts, faces, node_extras in meshes:
        v = to_y_up(np.asarray(verts, dtype=float).reshape(-1, 3) - off).astype("<f4")
        f = np.asarray(faces, dtype=np.int64).reshape(-1, 3).astype("<u4")
        if not len(v) or not len(f):
            continue
        pv = view(v.tobytes(), _ARRAY_BUFFER)
        accessors.append({"bufferView": pv, "componentType": _FLOAT, "count": int(len(v)), "type": "VEC3",
                          "min": [float(x) for x in v.min(axis=0)], "max": [float(x) for x in v.max(axis=0)]})
        iv = view(f.tobytes(), _ELEMENT_ARRAY_BUFFER)
        accessors.append({"bufferView": iv, "componentType": _UINT32, "count": int(f.size), "type": "SCALAR"})
        gltf_meshes.append({"name": name, "primitives": [{"attributes": {"POSITION": len(accessors) - 2},
                                                          "indices": len(accessors) - 1, "mode": _TRIANGLES}]})
        node = {"name": name, "mesh": len(gltf_meshes) - 1}
        if node_extras:
            node["extras"] = node_extras
        nodes.append(node)
        tri_total += int(len(f))

    scene = {"nodes": list(range(len(nodes)))}
    if extras:
        scene["extras"] = extras
    doc = {
        "asset": {"version": "2.0", "generator": "bimforge"},
        "scene": 0,
        "scenes": [scene],
        "nodes": nodes,
        "meshes": gltf_meshes,
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": cursor}],
    }
    json_bytes = _pad(json.dumps(doc, separators=(",", ":"), sort_keys=True).encode("utf-8"), b" ")
    bin_bytes = b"".join(bin_parts)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_bytes)
    with open(path, "wb") as fh:
        fh.write(_MAGIC + struct.pack("<II", 2, total))
        fh.write(struct.pack("<II", len(json_bytes), _JSON) + json_bytes)
        fh.write(struct.pack("<II", len(bin_bytes), _BIN) + bin_bytes)
    return {"nodes": len(nodes), "bytes": total, "triangles": tri_total}


def read_glb(path) -> tuple[dict, bytes]:
    """(json document, binary chunk) of a GLB — enough for a test to check
    what `write_glb` wrote; not a general loader."""
    with open(path, "rb") as fh:
        data = fh.read()
    magic, version, length = struct.unpack_from("<4sII", data, 0)
    if magic != _MAGIC or version != 2 or length != len(data):
        raise ValueError("not a glTF 2.0 binary")
    pos, doc, blob = 12, None, b""
    while pos < len(data):
        n, kind = struct.unpack_from("<II", data, pos)
        chunk = data[pos + 8:pos + 8 + n]
        if kind == _JSON:
            doc = json.loads(chunk.decode("utf-8"))
        elif kind == _BIN:
            blob = chunk
        pos += 8 + n
    if doc is None:
        raise ValueError("GLB has no JSON chunk")
    return doc, blob
