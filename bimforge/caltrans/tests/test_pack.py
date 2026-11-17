"""The Caltrans pack: its tables ship in the package, a spec names one with
`tables_pack`, and a build from the pack is the build from the same rows in a
file."""
from __future__ import annotations

from importlib.resources import files

import pytest

yaml = pytest.importorskip("yaml")

from bimforge import caltrans  # noqa: E402

# example spec -> the packaged table holding the rows its example file carries.
# The B3 and D84 example files hold illustrative rows, so they are not here.
EXAMPLES = {
    "caltrans-box-culvert": "d80-box-culvert",
    "caltrans-pipe-headwall": "d89-pipe-headwall",
}


def test_every_declared_table_ships_and_parses():
    for edition, tables in caltrans.EDITIONS.items():
        shipped = {p.name for p in caltrans.tables_dir(edition).iterdir()}
        assert shipped == set(tables.values())          # none undeclared
        for name in caltrans.table_names(edition):
            assert isinstance(caltrans.load_table(name, edition), dict)
    assert caltrans.EDITION in caltrans.EDITIONS


def test_a_load_is_a_fresh_mapping():
    a = caltrans.load_table("d89-pipe-headwall")
    a.clear()
    assert caltrans.load_table("d89-pipe-headwall")


def test_an_unknown_table_or_edition_names_what_exists():
    with pytest.raises(KeyError, match="d89-pipe-headwall"):
        caltrans.table_path("d99")
    with pytest.raises(KeyError, match="2025"):
        caltrans.load_table("d89-pipe-headwall", "1999")


def _spec(tmp_path, params: str):
    (tmp_path / "pc.yaml").write_text(
        "rules: [{match: x, group: g}]\n"
        "groups: {g: {measure: GrossVolume}}\n"
        "codes: {C: {group: g, measure: GrossVolume, unit: CY}}\n",
        encoding="utf-8")
    (tmp_path / "s.yaml").write_text(
        "family: standard-plan\n"
        f"params: {params}\n"
        "paycodes: ./pc.yaml\n"
        "outputs: {dxf: out.dxf}\n"
        "project: {name: n, epsg: 2226, base: [0,0,0], guid_ns: x}\n",
        encoding="utf-8")
    return tmp_path / "s.yaml"


@pytest.mark.parametrize("ref", ["caltrans/2025/d89-pipe-headwall",
                                 "caltrans/d89-pipe-headwall"])
def test_a_spec_names_a_packaged_table(tmp_path, ref):
    from bimforge.author.families.registry import load_spec
    spec = load_spec(_spec(tmp_path, f"{{tables_pack: {ref}, walls: []}}"))
    assert spec["params"]["tables"] == caltrans.load_table("d89-pipe-headwall")
    assert "tables_pack" not in spec["params"]


@pytest.mark.parametrize("params, message", [
    ("{tables_pack: caltrans/2025/d99, walls: []}", "d89-pipe-headwall"),
    ("{tables_pack: caltrans/1999/d89-pipe-headwall, walls: []}", "edition"),
    ("{tables_pack: nowhere/x, walls: []}", "packs: caltrans"),
    ("{tables_pack: caltrans, walls: []}", "<pack>/<table>"),
    ("{tables_pack: [caltrans/d89-pipe-headwall, caltrans/d99], walls: []}",
     "d99"),
])
def test_a_bad_reference_is_refused_by_spec_name(tmp_path, params, message):
    from bimforge.author.families.registry import load_spec
    with pytest.raises(ValueError, match=message) as err:
        load_spec(_spec(tmp_path, params))
    assert "s.yaml" in str(err.value)


def test_the_projects_file_merges_over_the_packaged_tables(tmp_path):
    from bimforge.author.families.registry import load_spec
    (tmp_path / "t.yaml").write_text(
        "d90: {schedule: {footing: {size: 5}}, pipe: {mine: 1}}\n", "utf-8")
    spec = load_spec(_spec(tmp_path, (
        "{tables_pack: [caltrans/d90-headwall, caltrans/b3-retaining-wall], "
        "tables_file: ./t.yaml, walls: []}")))
    tables = spec["params"]["tables"]
    d90, b3 = (caltrans.load_table(n) for n in ("d90-headwall",
                                                "b3-retaining-wall"))
    assert tables["d90"]["schedule"] == {"footing": {"size": 5}}
    assert tables["d90"]["pipe"] == {**d90["d90"]["pipe"], "mine": 1}
    assert tables["d90"]["wingwall_types"] == d90["d90"]["wingwall_types"]
    assert tables["type_1_case_1"] == b3["type_1_case_1"]
    # the merge wrote into this spec's tables, not into the pack's
    assert "mine" not in caltrans.load_table("d90-headwall")["d90"]["pipe"]


def test_a_d90_headwall_builds_from_the_pack_and_its_own_schedule(tmp_path):
    """D90 fixes little: the wall section comes from B3 and the Engineer
    varies the wingwalls and bars, so a project names two packaged tables and
    supplies the rest."""
    pytest.importorskip("ifcopenshell")
    from bimforge.author.families.registry import build_from_spec
    examples = files("bimforge.author") / "examples"
    for entry in examples.iterdir():
        if entry.name.endswith(".yaml"):
            (tmp_path / entry.name).write_text(entry.read_text("utf-8"), "utf-8")
    path = tmp_path / "caltrans-d90-headwall.spec.yaml"
    spec = yaml.safe_load(path.read_text("utf-8"))
    example = yaml.safe_load(
        (tmp_path / spec["params"]["tables_file"]).read_text("utf-8"))
    (tmp_path / "mine.yaml").write_text(yaml.safe_dump({"d90": {
        k: example["d90"][k] for k in ("schedule", "wingwalls")}}), "utf-8")
    spec["params"]["tables_file"] = "./mine.yaml"
    spec["params"]["tables_pack"] = ["caltrans/2025/d90-headwall",
                                     "caltrans/2025/b3-retaining-wall"]
    path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
    assert build_from_spec(str(path)) == 0
    assert (tmp_path / spec["outputs"]["ifc"]).stat().st_size


@pytest.mark.parametrize("example, table", sorted(EXAMPLES.items()))
def test_a_build_from_the_pack_is_the_build_from_the_example_rows(
        tmp_path, example, table):
    """The example table files carry real rows, so swapping one for the
    packaged table must not move a byte of the model."""
    pytest.importorskip("ifcopenshell")
    from bimforge.author.families.registry import build_from_spec
    examples = files("bimforge.author") / "examples"
    built = {}
    for how in ("file", "pack"):
        d = tmp_path / how
        d.mkdir()
        for entry in examples.iterdir():
            if entry.name.endswith(".yaml"):
                (d / entry.name).write_text(entry.read_text("utf-8"), "utf-8")
        path = d / f"{example}.spec.yaml"
        spec = yaml.safe_load(path.read_text("utf-8"))
        assert spec["params"]["tables_file"]
        if how == "pack":
            del spec["params"]["tables_file"]
            spec["params"]["tables_pack"] = f"caltrans/2025/{table}"
            path.write_text(yaml.safe_dump(spec, sort_keys=False), "utf-8")
        assert build_from_spec(str(path)) == 0
        built[how] = (d / spec["outputs"]["ifc"]).read_bytes()
    assert built["file"] == built["pack"]
