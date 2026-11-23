"""Modified standards (M.8, M.9): the table diff and the routes."""
from bimforge.author.modified import (
    Difference, ROUTES, difference_measure, path_text, table_differences)


def test_equal_tables_differ_in_nothing():
    t = {"type_1_case_1": {"table": {8: {"W_ft": 6.5833, "batter": "0.5:12"}}}}
    assert table_differences(t, {"type_1_case_1": {"table": {
        8: {"W_ft": 6.5833, "batter": "0.5:12"}}}}) == []


def test_a_changed_field_is_one_difference():
    std = {"t": {"table": {8: {"W_ft": 6.5833, "C_ft": 2.3333}}}}
    got = {"t": {"table": {8: {"W_ft": 7.0, "C_ft": 2.3333}}}}
    assert table_differences(std, got) == [
        Difference(("t", "table", 8, "W_ft"), 6.5833, 7.0)]


def test_numbers_within_1e9_are_the_same_and_int_equals_float():
    assert table_differences({"a": 1}, {"a": 1.0 + 1e-12}) == []


def test_text_is_compared_exactly():
    assert table_differences({"b": "0.5:12"}, {"b": "NONE"}) == [
        Difference(("b",), "0.5:12", "NONE")]


def test_an_added_row_has_no_standard():
    std = {"t": {"table": {8: {"W_ft": 6.5}}}}
    got = {"t": {"table": {8: {"W_ft": 6.5}, 9: {"W_ft": 7.0, "C_ft": 2.5}}}}
    assert table_differences(std, got) == [
        Difference(("t", "table", 9, "W_ft"), None, 7.0),
        Difference(("t", "table", 9, "C_ft"), None, 2.5)]


def test_a_string_key_is_not_an_int_key():
    # "8" is a new row, not row 8: the merge adds it, so the diff says so
    assert table_differences({"t": {8: {"W": 1}}}, {"t": {8: {"W": 1}, "8": {"W": 2}}}) \
        == [Difference(("t", "8", "W"), None, 2)]


def test_path_text_and_routes():
    assert path_text(("type_1_case_1", "table", 8, "W_ft")) == \
        "type_1_case_1.table.8.W_ft"
    assert ROUTES == ("standard", "modified-by-value", "modified-by-part",
                      "modified-by-section", "bespoke")


def test_difference_measure_names_the_unit():
    assert difference_measure("ToeWidth") == ("IfcLengthMeasure", 1.0)
    assert difference_measure("Batter") == ("IfcRatioMeasure", None)
    assert difference_measure("W_ft") == ("IfcLengthMeasure", 1.0)
    assert difference_measure("chamfer_in") == ("IfcLengthMeasure", 1.0 / 12.0)
    assert difference_measure("deck_slope_pct") == ("IfcReal", None)
