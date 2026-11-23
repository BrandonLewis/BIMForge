"""Modified standards (M.8, M.9): the table diff and the routes."""
from bimforge.author.alignment import WallSection
from bimforge.author.model import Element
from bimforge.author.modified import (
    ROUTES,
    Difference,
    difference_measure,
    modified_mode,
    path_text,
    table_differences,
)


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


def _el(name, cls="retaining-wall-b3-type-1-footing", reads=None,
        rows=None, **kw):
    return Element(name, "IfcFooting", family_class=cls,
                   table_reads=reads or {}, table_rows=rows or {}, **kw)


class _Model:
    def __init__(self, *els, row_lookup=None):
        self.elements = list(els)
        self.row_lookup = row_lookup


def test_assign_routes_gives_each_typed_element_its_route():
    from bimforge.author.modified import assign_routes
    w = ("type_1_case_1", "table", 8, "W_ft")
    b = ("type_1_case_1", "table", 8, "batter")
    hit = _el("f8", reads={w: "W_ft"})
    stem = _el("s8", cls="retaining-wall-b3-type-1", reads={b: "Batter"})
    plain = Element("loose", "IfcBuildingElementProxy")
    unchecked = _el("headwall")           # typed, but nothing to check
    kept = _el("barrier", route="modified-by-section")
    m = _Model(hit, stem, plain, unchecked, kept)
    assign_routes(m, [Difference(w, 6.5833, 7.0)],
                  "caltrans/2025/b3-retaining-wall")
    assert hit.route == "modified-by-value"
    assert hit.differences == [{"name": "W_ft", "standard": 6.5833,
                                "actual": 7.0, "source":
                                "caltrans/2025/b3-retaining-wall "
                                "type_1_case_1.table.8.W_ft"}]
    assert stem.route == "standard" and stem.differences == []
    assert plain.route is None
    assert unchecked.route is None and unchecked.differences == []
    assert kept.route == "modified-by-section"


def test_a_batter_difference_is_a_ratio():
    from bimforge.author.modified import assign_routes
    b = ("type_1_case_1", "table", 8, "batter")
    stem = _el("s8", cls="retaining-wall-b3-type-1", reads={b: "Batter"})
    assign_routes(_Model(stem), [Difference(b, "0.5:12", "NONE")], "pack")
    assert stem.differences[0]["standard"] == 0.5 / 12
    assert stem.differences[0]["actual"] == 0.0


def test_values_print_as_written_and_an_added_one_says_so():
    from bimforge.author.modified import fmt_value
    assert fmt_value(7.0) == "7"
    assert fmt_value(6.5833) == "6.5833"
    assert fmt_value("0.5:12") == "0.5:12"
    assert fmt_value(None) == "(added)"


def test_modified_lines_group_alike_elements():
    from bimforge.author.modified import modified_check, modified_lines
    d = [{"name": "W_ft", "standard": 6.5833, "actual": 7.0, "source": "s"}]
    m = _Model(_el("a", route="modified-by-value", differences=d),
               _el("b", route="modified-by-value", differences=list(d)),
               _el("c", route="standard"))
    lines = modified_lines(m)
    assert lines == [("2 elements (a, ...) modified-by-value of "
                      "retaining-wall-b3-type-1-footing: W_ft 6.5833 -> 7")]
    assert modified_check(m)(m) == lines
    assert modified_check(_Model(_el("c", route="standard")))(None) == []


def test_an_empty_gate_modified_is_warn():
    assert modified_mode(None) == "warn"
    assert modified_mode(False) == "off"
    assert modified_mode("ERROR") == "error"


def test_a_raw_batter_field_is_a_ratio():
    from bimforge.author.modified import assign_routes
    assert difference_measure("batter") == ("IfcRatioMeasure", None)
    b = ("type_5_case_1", "table", 8, "batter")
    toe = _el("f8", cls="retaining-wall-b3-type-5-footing",
              reads={b: "batter"})
    assign_routes(_Model(toe), [Difference(b, "0.25:12", "0.5:12")], "pack")
    assert toe.differences[0]["standard"] == 0.25 / 12
    assert toe.differences[0]["actual"] == 0.5 / 12


#: The packaged Type 1a rows; a project's file with only 8 and 12
_BASELINE = {"type_1a_case_1": {"table": {
    k: {"W_ft": float(k)} for k in (4, 6, 8, 10, 12)}}}
_ROW_1A = ("type_1a_case_1", "table")


def _row_el(H, key):
    return _el("f", cls="retaining-wall-b3-type-1a-footing",
               rows={_ROW_1A: (H, key)})


def test_a_row_the_standard_would_not_choose_is_a_row_difference():
    from bimforge.author.modified import assign_routes
    el = _row_el(10.0, 12)               # the project has no row 10
    assign_routes(_Model(el, row_lookup=WallSection._lookup_key), [],
                  "caltrans/2025/b3-retaining-wall", baseline=_BASELINE)
    assert el.route == "modified-by-value"
    assert el.differences == [{
        "name": "Row", "standard": 10, "actual": 12,
        "source": "caltrans/2025/b3-retaining-wall type_1a_case_1.table"}]


def test_the_row_the_standard_chooses_is_standard():
    from bimforge.author.modified import assign_routes
    el = _row_el(8.0, 8)
    assign_routes(_Model(el, row_lookup=WallSection._lookup_key), [], "s",
                  baseline=_BASELINE)
    assert el.route == "standard" and el.differences == []


def test_a_table_the_standard_does_not_have_is_a_row_difference():
    from bimforge.author.modified import assign_routes
    el = _el("f", rows={("type_9_case_1", "table"): (8.0, 8)})
    assign_routes(_Model(el, row_lookup=WallSection._lookup_key), [], "s",
                  baseline=_BASELINE)
    assert el.differences == [{"name": "Row", "standard": None, "actual": 8,
                               "source": "s type_9_case_1.table"}]
