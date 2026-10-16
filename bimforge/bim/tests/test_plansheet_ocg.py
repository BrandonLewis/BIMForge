"""Segment.layer — the PDF optional-content group each path belongs to (#200)."""
from __future__ import annotations

from collections import Counter

import pytest

fitz = pytest.importorskip("fitz")

from bimforge.bim.plansheet.vectors import Segment, extract_sheet  # noqa: E402
from bimforge.bim.tests._pdf_fixtures import write_ocg_sheet  # noqa: E402


def test_segments_carry_their_ocg_name(tmp_path):
    sv = extract_sheet(write_ocg_sheet(tmp_path / "ocg.pdf"), 0)
    assert Counter(s.layer for s in sv.segments) == {
        "Topo|CONT_MNR": 2, "Grading|C-TOPO-MAJR-N": 2, None: 1}


def test_layer_defaults_to_none():
    assert Segment(0.0, 0.0, 1.0, 1.0).layer is None
