"""Label candidates — masks, gaps, label-layer glyphs, spot markers."""
from __future__ import annotations

import pytest

from bimforge.bim.plansheet.labels import (
    Candidate, dedupe, find_candidates, gap_candidates, layer_candidates,
    mask_candidates, nearest_line, page_lines, spot_candidates,
)

# world = (x, -y): page y 100 is world N -100.
MANIFEST = {"manifest_version": 2,
            "georef": {"transform": [1, 0, 0, 0, -1, 0]},
            "layers": {
                "A": {"lines": [{"points": [[0, -100], [200, -100]]},
                                {"points": [[230, -100], [400, -100]]}]},
                "B": {"lines": [{"points": [[0, -300], [400, -300]]}]}}}


def _d(layer, rect, fill=None):
    return {"layer": layer, "fill": fill, "rect": rect}


WHITE = (1.0, 1.0, 1.0)
DRAWINGS = [
    _d("ANN", (90, 92, 110, 108), WHITE),        # mask over line A (page y 100)
    _d("ANN", (90, 192, 110, 208), WHITE),       # white box over no line
    _d("ANN", (300, 292, 320, 308), (0, 0, 0)),  # black fill: not a mask
    _d("ANN", (0, 280, 200, 320), WHITE),        # too big to be a label mask
    _d("LBL", (150, 296, 153, 304)),             # two glyphs by line B
    _d("LBL", (154, 296, 157, 304)),
    _d("SPT", (50, 50, 54, 54)),                 # a spot marker
]


def test_page_lines_inverts_the_georef():
    lines = page_lines(MANIFEST)
    assert [ln["id"] for ln in lines] == [0, 1, 2]
    assert [ln["layer"] for ln in lines] == ["A", "A", "B"]
    assert lines[0]["page"].tolist() == [[0.0, 100.0], [200.0, 100.0]]


def test_page_lines_refuses_a_v1_manifest():
    with pytest.raises(ValueError, match="v2"):
        page_lines({"layers": {}})


def test_mask_candidates_need_a_small_white_box_over_a_contour():
    got = mask_candidates(DRAWINGS, page_lines(MANIFEST))
    assert [(c.source, c.page) for c in got] == [("mask", (100.0, 100.0))]


def test_gap_candidates_pair_facing_ends_of_long_lines_only():
    lines = page_lines(MANIFEST)
    assert [c.page for c in gap_candidates(lines)] == [(215.0, 100.0)]
    assert gap_candidates(lines, min_line=250.0) == []        # a 170 pt side


def test_layer_candidates_cluster_glyphs_next_to_a_contour():
    got = layer_candidates(DRAWINGS, "LBL", page_lines(MANIFEST))
    assert [c.page for c in got] == [(153.5, 300.0)]


def test_spot_candidates_have_a_crop_big_enough_for_the_number():
    (c,) = spot_candidates(DRAWINGS, "SPT")
    assert c.page == (52.0, 52.0)
    assert c.bbox[2] - c.bbox[0] >= 70.0


def test_dedupe_keeps_the_higher_priority_source():
    got = dedupe([Candidate((215.0, 100.0), "gap", ()),
                  Candidate((212.0, 100.0), "mask", ())])
    assert [(c.source, c.page) for c in got] == [("mask", (212.0, 100.0))]


def test_nearest_line_reports_distance_and_margin_in_world_feet():
    (c,) = nearest_line([Candidate((100.0, 100.0), "mask", ())],
                        page_lines(MANIFEST), MANIFEST)
    assert (c.line, c.dist_ft, c.margin_ft) == (0, 0.0, 130.0)


def test_find_candidates_default_and_opt_in_sources():
    labels, spots = find_candidates(DRAWINGS, MANIFEST)
    assert sorted(c.source for c in labels) == ["gap", "mask"]
    assert spots == []
    labels, spots = find_candidates(DRAWINGS, MANIFEST, labels_glob="LBL",
                                    spots_glob="SPT")
    assert sorted(c.source for c in labels) == ["gap", "layer", "mask"]
    assert [s.source for s in spots] == ["spot"]
    only_masks, _ = find_candidates(DRAWINGS, MANIFEST, sources=("mask",))
    assert [c.source for c in only_masks] == ["mask"]
    assert all(c.line is not None for c in labels)
