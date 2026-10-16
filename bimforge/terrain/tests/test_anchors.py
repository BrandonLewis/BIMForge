"""Anchors files: vertical datum, unread records, page placement."""
from __future__ import annotations

import pytest
import yaml

from bimforge.terrain.anchors import (
    Anchors, load_anchors, manifest_page_to_world, place_anchors,
)


def test_vertical_datum_is_required():
    with pytest.raises(ValueError, match="vertical_datum"):
        place_anchors({"contours": [{"elev": 100, "xy": [0, 0]}]})


def test_places_xy_and_page_records_and_counts_unread():
    raw = {"sheet": 94, "vertical_datum": "NGVD29", "interval_ft": 1.0,
           "index_interval_ft": 5.0,
           "contours": [{"elev": 100, "xy": [1, 2]},
                        {"elev": 110, "page": [10, 20], "id": "L001"},
                        {"elev": None, "page": [5, 5]}],
           "spots": [{"elev": 99.5, "xy": [3, 4]}]}
    a = place_anchors(raw, page_to_world=lambda x, y: (2 * x, -2 * y))
    assert isinstance(a, Anchors)
    assert a.contours == [{"elev": 100.0, "xy": (1.0, 2.0), "id": None},
                          {"elev": 110.0, "xy": (20.0, -40.0), "id": "L001"}]
    assert a.spots == [{"elev": 99.5, "xy": (3.0, 4.0), "id": None}]
    assert (a.sheet, a.vertical_datum, a.unread) == (94, "NGVD29", 1)
    assert (a.interval_ft, a.index_interval_ft) == (1.0, 5.0)


def test_extra_spots_are_placed_and_unread_ones_counted():
    a = place_anchors({"vertical_datum": "NAVD88"},
                      extra_spots=[{"elev": 5, "xy": [0, 0]},
                                   {"elev": None, "xy": [1, 1]}])
    assert a.spots == [{"elev": 5.0, "xy": (0.0, 0.0), "id": None}]
    assert a.unread == 1


def test_a_string_sheet_is_a_page_number(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text('sheet: "94"\nvertical_datum: NGVD29\n', encoding="utf-8")
    assert load_anchors(p)["sheet"] == 94
    assert place_anchors({"sheet": "94", "vertical_datum": "X"}).sheet == 94


_OK = {"vertical_datum": "NGVD29"}


@pytest.mark.parametrize("raw, match", [
    ([1, 2], "expected a mapping"),
    ({**_OK, "contours": [5]}, r"contours\[0\]: expected a record"),
    ({**_OK, "contours": 5}, "contours: must be a list"),
    ({**_OK, "spots": [{"elev": 1, "xy": [1]}]}, r"spots\[0\]: xy must be 2 numbers"),
    ({**_OK, "contours": [{"elev": 1, "xy": [0, 0]}, {"elev": 1, "page": [1, 2, 3]}]},
     r"contours\[1\]: page must be 2 numbers"),
    ({**_OK, "contours": [{"elev": [1], "xy": [0, 0]}]},
     r"contours\[0\]: elev must be a number"),
    ({**_OK, "interval_ft": -1}, "interval_ft: must be > 0"),
    ({**_OK, "interval_ft": 0}, "interval_ft: must be > 0"),
    ({**_OK, "index_interval_ft": -5}, "index_interval_ft: must be > 0"),
    ({**_OK, "sheet": "ninety-four"}, "sheet: must be a page number"),
])
def test_malformed_anchors_raise_value_error_naming_the_record(raw, match):
    with pytest.raises(ValueError, match=match):
        place_anchors(raw, page_to_world=lambda x, y: (x, y))


@pytest.mark.parametrize("text, match", [
    ("- 1\n- 2\n", "expected a mapping"),
    ("5\n", "expected a mapping"),
    ("a: [1\n", "not valid YAML"),
])
def test_load_anchors_refuses_a_file_that_is_not_a_mapping(tmp_path, text, match):
    p = tmp_path / "a.yaml"
    p.write_text(text, encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        load_anchors(p)


def test_page_record_without_a_placement_source_says_how_to_place_it():
    with pytest.raises(ValueError, match="--tie"):
        place_anchors({"vertical_datum": "X",
                       "contours": [{"elev": 1, "page": [0, 0]}]})


def test_record_needs_xy_or_page():
    with pytest.raises(ValueError, match="xy or page"):
        place_anchors({"vertical_datum": "X", "contours": [{"elev": 1}]})


def test_manifest_page_to_world_reads_the_v2_transform():
    fn = manifest_page_to_world(
        {"georef": {"transform": [2, 0, 1000, 0, -2, 5000]}})
    assert fn(10, 20) == (1020.0, 4960.0)
    assert manifest_page_to_world({"sheet": 1}) is None      # v1


def test_load_anchors(tmp_path):
    p = tmp_path / "a.yaml"
    p.write_text(yaml.safe_dump({"vertical_datum": "NGVD29"}), encoding="utf-8")
    assert load_anchors(p) == {"vertical_datum": "NGVD29"}
    empty = tmp_path / "e.yaml"
    empty.write_text("", encoding="utf-8")
    assert load_anchors(empty) == {}
