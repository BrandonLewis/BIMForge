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


#: One Type 1 wall at design H 8 ft over its 32 ft, from the shipped B3
#: example spec's first wall; its tables are the project's `t.yaml`.
WALL_8FT_PARAMS = (
    "{tables_file: ./t.yaml, "
    "alignment: {pob: {station: 0.0, northing: 0.0, easting: 0.0}, "
    "run: [{kind: tangent, bearing: 'N 0-0-0 E', length: 32.0}]}, "
    "walls: [{name: R1, wall_type: 1, front_side: Lt, "
    "beg: {station: 0.0}, end: {station: 32.0}, grid_ft: 8.0, "
    "design_h_segments: [{length_ft: 32.0, H_ft: 8}], "
    "top_of_wall: {start_station: 0.0, grid_ft: 8.0, "
    "elevs: [109.0, 109.0, 109.0, 109.0, 109.0]}, "
    "footing_bottom: {steps: [{station: 0.0, elev: 100.0}]}}]}")


def _modified_spec(tmp_path, gate: str = ""):
    """The B3 spec over the packaged tables with row 8's footing 7 ft wide,
    not 6.5833, its heel taking the 5 in (W == C + B): its paycodes the
    example's own, by absolute path."""
    from importlib.resources import files

    import yaml
    pack = _tables()
    pack["type_1_case_1"]["table"][8].update(W_ft=7.0, B_ft=4.6667)
    (tmp_path / "t.yaml").write_text(yaml.safe_dump(pack), "utf-8")
    paycodes = (files("bimforge.author") / "examples"
                / "caltrans-b3-retaining-wall.paycodes.yaml")
    path = tmp_path / "s.yaml"
    path.write_text(
        "family: standard-plan\n"
        f"params: {WALL_8FT_PARAMS}\n"
        f"paycodes: '{paycodes}'\n"
        "outputs: {dxf: out.dxf}\n"
        "project: {name: n, epsg: 2226, "
        "base: [6594000.0, 1943000.0, 100.0], "
        "guid_ns: 3b7a5c2e-0000-4000-8000-0000000000b3}\n"
        + gate, encoding="utf-8")
    return path


def test_a_changed_row_modifies_only_the_elements_that_read_it(tmp_path, capsys):
    from bimforge.author.families.registry import build_from_spec
    assert build_from_spec(str(_modified_spec(tmp_path)), check_only=True) == 0
    err = capsys.readouterr().err
    assert "tables: type_1_case_1.table.8.W_ft 6.5833 -> 7 " in err
    assert "tables: type_1_case_1.table.8.B_ft 4.25 -> 4.6667 " in err
    assert ("modified: 4 elements (R1 retaining wall footing 0+00.00, ...) "
            "modified-by-value of retaining-wall-b3-type-1-footing: "
            "W_ft 6.5833 -> 7, HeelWidth 4.25 -> 4.6667") in err
    assert "of retaining-wall-b3-type-1:" not in err      # stems are standard


def test_gate_modified_error_fails_the_build(tmp_path):
    from bimforge.author.families.registry import build_from_spec
    path = _modified_spec(tmp_path, "gate: {modified: error}\n")
    assert build_from_spec(str(path), check_only=True) == 1


def test_gate_modified_off_says_nothing(tmp_path, capsys):
    from bimforge.author.families.registry import build_from_spec
    path = _modified_spec(tmp_path, "gate: {modified: off}\n")
    assert build_from_spec(str(path), check_only=True) == 0
    assert "modified: " not in capsys.readouterr().err


def test_a_section_names_the_row_it_chose_and_for_which_H():
    tables = _tables()
    del tables["type_1a_case_1"]["table"][10]
    ws = WallSection("1a", 10.0, tables)
    assert ws.rows == {("type_1a_case_1", "table"): (10.0, 12)}


#: A Type 1a wall at design H 8 ft over the packaged tables less Type 1a's
#: row 8 (as the shipped example lacks rows 10 and 6): the project's tables
#: choose row 10 where the pack chooses 8, and no value differs
WALL_1A_8FT_PARAMS = WALL_8FT_PARAMS.replace("wall_type: 1,", "wall_type: 1a,")


def _row_spec(tmp_path):
    from importlib.resources import files

    import yaml
    tables = _tables()
    del tables["type_1a_case_1"]["table"][8]
    (tmp_path / "t.yaml").write_text(yaml.safe_dump(tables), "utf-8")
    paycodes = (files("bimforge.author") / "examples"
                / "caltrans-b3-retaining-wall.paycodes.yaml")
    path = tmp_path / "s.yaml"
    path.write_text(
        "family: standard-plan\n"
        f"params: {WALL_1A_8FT_PARAMS}\n"
        f"paycodes: '{paycodes}'\n"
        "outputs: {dxf: out.dxf}\n"
        "project: {name: n, epsg: 2226, "
        "base: [6594000.0, 1943000.0, 100.0], "
        "guid_ns: 3b7a5c2e-0000-4000-8000-0000000000b3}\n", encoding="utf-8")
    return path


def test_the_elements_carry_the_row_and_the_model_how_one_is_chosen(tmp_path):
    from bimforge.author.families import standard_plan
    from bimforge.author.families.registry import load_spec
    from bimforge.author.project import ProjectContext
    spec = load_spec(_row_spec(tmp_path))
    assert "_tables_baseline" not in spec["params"]
    assert (spec["_tables_baseline"]["type_1a_case_1"]["table"].keys()
            == _tables()["type_1a_case_1"]["table"].keys())
    model = standard_plan.build(spec["params"],
                                ProjectContext.from_spec(spec["project"]))
    assert model.row_lookup is WallSection._lookup_key
    assert {tuple(el.table_rows.items()) for el in model.elements} == {
        ((("type_1a_case_1", "table"), (8.0, 10)),)}


def test_a_row_the_pack_would_not_choose_modifies_the_wall(tmp_path, capsys):
    from bimforge.author.families.registry import build_from_spec
    assert build_from_spec(str(_row_spec(tmp_path)), check_only=True) == 0
    err = capsys.readouterr().err
    assert "tables: " not in err                   # no value differs
    assert ("modified: 4 elements (R1 retaining wall footing 0+00.00, ...) "
            "modified-by-value of retaining-wall-b3-type-1a-footing: "
            "Row 8 -> 10") in err
    assert "of retaining-wall-b3-type-1a: Row 8 -> 10" in err


def test_an_empty_gate_modified_is_warn(tmp_path, capsys):
    from bimforge.author.families.registry import build_from_spec, load_spec
    path = _modified_spec(tmp_path, "gate: {modified: }\n")
    assert load_spec(path)["gate"] == {"modified": None}
    assert build_from_spec(str(path), check_only=True) == 0
    assert "modified: 4 elements" in capsys.readouterr().err
