"""The B3 wall says which table values each element read (M.8)."""
from bimforge import caltrans
from bimforge.author.alignment import WallSection


def _tables():
    return caltrans.load_table("b3-retaining-wall")


def test_a_type_1_section_names_its_row():
    ws = WallSection(1, 8.0, _tables())
    row = ("type_1_case_1", "table", 8)
    assert ws.sources["W"] == [row + ("W_ft",)]
    assert ws.sources["T"] == [row + ("T_ft",)]
    assert ws.sources["batter"] == [row + ("batter",)]


def test_a_type_5_toe_is_read_from_the_batter():
    ws = WallSection(5, 8.0, _tables())
    tab = _tables()["type_5_case_1"]["table"]
    key = next(k for k in sorted(tab, key=float) if 8.0 <= float(k) + 0.5)
    row = ("type_5_case_1", "table", key)
    assert ws.sources["T"] == [("type_5_case_1", "stem_top_thickness_ft")]
    assert ws.sources["C"] == [row + ("batter",)]
    assert ws.sources["B"] == [row + ("W_ft",), row + ("batter",)]


def test_the_stem_and_footing_read_their_own_fields():
    from bimforge.author.families.standard_plan import _table_reads
    ws = WallSection(1, 8.0, _tables())
    row = ("type_1_case_1", "table", 8)
    stem = _table_reads("retaining-wall-b3-type-1", ws, ("T", "batter"))
    foot = _table_reads("retaining-wall-b3-type-1-footing", ws,
                        ("W", "C", "B", "F"))
    assert stem == {row + ("T_ft",): "StemThickness",
                    row + ("batter",): "Batter"}
    assert foot == {row + ("W_ft",): "W_ft", row + ("C_ft",): "ToeWidth",
                    row + ("B_ft",): "HeelWidth", row + ("F_ft",): "F_ft"}
