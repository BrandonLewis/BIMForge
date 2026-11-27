"""3DEP answered locally, for tests (G.9): the transport is replaced and the
DEM is a float32 TIFF, flat or on a plane. Needs pytest, and Pillow to
write the TIFF (a test with no Pillow skips)."""
from __future__ import annotations

import io
import json
from importlib.util import find_spec

import numpy as np

from bimforge.terrain import fetch as F

#: what building a spec's terrain: block from the offline DEM imports
#: (bimforge[terrain]): Pillow reads the DEM, scipy and trimesh the rest
TERRAIN_DEPS = ("PIL", "scipy", "trimesh")


def missing_terrain_deps() -> list[str]:
    """The TERRAIN_DEPS this interpreter cannot import."""
    return [m for m in TERRAIN_DEPS if find_spec(m) is None]


def _image():
    import pytest
    return pytest.importorskip("PIL.Image")


def tiff(rows=40, cols=40, z_m=30.48):
    Image = _image()
    buf = io.BytesIO()
    Image.fromarray(np.full((rows, cols), z_m, dtype="float32"), mode="F").save(
        buf, format="TIFF")
    return buf.getvalue()


class _Resp:
    def __init__(self, data):
        self.data = data

    def read(self):
        return self.data


def plane_tiff(url, plane):
    """The DEM the request asks for, its pixel centres on `plane(e, n)`
    (metres, the request's CRS units in plan)."""
    Image = _image()
    from urllib.parse import parse_qs, urlparse
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    x0, y0, x1, y1 = (float(v) for v in q["bbox"].split(","))
    cols, rows = (int(v) for v in q["size"].split(","))
    es = x0 + (np.arange(cols) + 0.5) * (x1 - x0) / cols
    ns = y1 - (np.arange(rows) + 0.5) * (y1 - y0) / rows      # row 0 north
    z = np.array([[plane(e, n) for e in es] for n in ns], dtype="float32")
    buf = io.BytesIO()
    Image.fromarray(z, mode="F").save(buf, format="TIFF")
    return buf.getvalue()


def offline(monkeypatch, calls=None, plane=None):
    """3DEP answered locally: the DEM a flat 30.48 m, or `plane` over the
    requested bbox; the work-unit index one feature."""
    def fake(url, timeout):
        if calls is not None:
            calls.append(url)
        if "exportImage" in url:
            return _Resp(tiff() if plane is None else plane_tiff(url, plane))
        return _Resp(json.dumps({"features": [{"attributes": {
            "project": "CA_Test", "workunit": "W1", "collect_start": 0,
            "collect_end": 0, "ql": "QL2"}}]}).encode())
    monkeypatch.setattr(F, "_urlopen", fake)
