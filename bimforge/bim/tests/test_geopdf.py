"""GeoPDF PDF-object parser and scale gates — pure, no pymupdf.

The pymupdf-dependent tests (``read_viewports`` against real PDFs) live in
``test_geopdf_pdf.py`` so this module's parser/gate tests always run, even
where the ``bim`` extra (and pymupdf with it) is not installed.
"""
from __future__ import annotations

import pytest

from bimforge.bim.plansheet.geopdf import (
    Name, Viewport, anisotropy_ok, is_foot_crs, parse_pdf_object,
)


# ------------------------------------------------------ parser (no pymupdf)
def test_parse_pdf_object_basics():
    got = parse_pdf_object("<</A [1 2.5 -.5 (x(y)z\\)) /N true null <414243>]"
                           "/WKT (PROJCS[\"a\",GEOGCS[\"b\"]])>>")
    assert got == {"A": [1, 2.5, -0.5, "x(y)z)", "N", True, None, "ABC"],
                   "WKT": 'PROJCS["a",GEOGCS["b"]]'}
    assert isinstance(got["A"][4], Name)


def test_parse_pdf_object_resolves_indirect_refs():
    objs = {12: "<</EPSG 2226>>"}

    def resolve(x):
        return parse_pdf_object(objs[x], resolve)

    assert parse_pdf_object("[12 0 R]", resolve) == [{"EPSG": 2226}]
    assert parse_pdf_object("[12 0 R]") == [("ref", 12)]


def test_parse_pdf_object_rejects_garbage():
    with pytest.raises(ValueError):
        parse_pdf_object("<</A }>>")


# ------------------------------------------------------ gates (no pymupdf)
def _vp(transform, unit="US survey foot"):
    return Viewport(0, (0.0, 0.0, 100.0, 100.0), 2226, unit, transform,
                    [0.0], "viewport")


def test_anisotropy_gate():
    assert anisotropy_ok(_vp((2.0, 0.0, 0.0, 0.0, -2.0, 0.0)))
    assert not anisotropy_ok(_vp((2.0, 0.0, 0.0, 0.0, -2.1, 0.0)))     # 4.8 %


def test_anisotropy_zero_scale_is_infinite_and_fails_the_gate():
    vp = _vp((2.0, 0.0, 0.0, 0.0, 0.0, 0.0))     # scale_y == 0
    assert vp.anisotropy_pct == float("inf")
    assert not anisotropy_ok(vp)


def test_foot_crs_only():
    assert is_foot_crs(_vp((1, 0, 0, 0, -1, 0)))
    assert is_foot_crs(_vp((1, 0, 0, 0, -1, 0), unit="foot"))
    assert not is_foot_crs(_vp((1, 0, 0, 0, -1, 0), unit="metre"))
