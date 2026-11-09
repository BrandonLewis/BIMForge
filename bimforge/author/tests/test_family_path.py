"""est-bim build --family-path, spec ifc_surfaces and gate.unread_params."""
import shutil
import uuid
from pathlib import Path

import pytest
import yaml

from bimforge.author.families import registry
from bimforge.author.params_tracking import TrackedParams, unread_params

EXAMPLES = Path(registry.__file__).resolve().parents[1] / "examples"


def _family_dir(tmp_path, family="side-box", extra=""):
    """A directory with one family module that imports a sibling helper.
    Module names are unique per test: discovery imports by plain name."""
    d = tmp_path / "families"
    d.mkdir()
    tag = uuid.uuid4().hex[:8]
    (d / f"helper_{tag}.py").write_text("SCALE = 1.0\n", encoding="utf-8")
    (d / f"fam_{tag}.py").write_text(
        f"import helper_{tag} as h\n"
        "from bimforge.author.families.demo_box import build as _demo\n"
        "def build(params, ctx):\n"
        "    assert h.SCALE == 1.0\n"
        "    return _demo(params, ctx)\n"
        f"FAMILIES = {{{family!r}: build}}\n" + extra, encoding="utf-8")
    return d, tag


def _spec(tmp_path, family="side-box", **extra):
    for f in ("demo-box.spec.yaml", "demo-box.paycodes.yaml"):
        shutil.copy(EXAMPLES / f, tmp_path / f)
    p = tmp_path / "demo-box.spec.yaml"
    spec = yaml.safe_load(p.read_text(encoding="utf-8"))
    spec["family"] = family
    spec.update(extra)
    p.write_text(yaml.safe_dump(spec, sort_keys=False), encoding="utf-8")
    return p


def test_a_family_in_a_directory_builds_through_the_cli(tmp_path):
    from bimforge.bim.cli import main
    d, _ = _family_dir(tmp_path)
    spec = _spec(tmp_path)
    assert main(["build", str(spec), "--check-only"]) == 1          # not found
    assert main(["build", str(spec), "--check-only", "--family-path", str(d)]) == 0


def test_a_name_declared_twice_is_an_error(tmp_path):
    d, _ = _family_dir(tmp_path)
    (d / f"dup_{uuid.uuid4().hex[:8]}.py").write_text(
        "FAMILIES = {'side-box': print}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="declared in both"):
        registry.available([d])


def test_a_dir_family_may_not_shadow_a_shipped_one(tmp_path):
    d, _ = _family_dir(tmp_path, family="demo-box")
    with pytest.raises(ValueError, match="collides"):
        registry.available([d])


def test_a_module_missing_an_optional_dependency_is_skipped(tmp_path, capsys):
    d, _ = _family_dir(tmp_path)
    bad = f"needs_{uuid.uuid4().hex[:8]}.py"
    (d / bad).write_text("import no_such_wheel_xyz\n", encoding="utf-8")
    assert "side-box" in registry.available([d])
    assert f"skipping {bad}" in capsys.readouterr().err


def test_tracked_params_records_what_was_read():
    t = TrackedParams({"a": 1, "b": {"c": 2, "d": [3, {"e": 4}]}, "notes": "x"})
    assert t["a"] == 1
    assert t["b"]["d"][1]["e"] == 4
    assert unread_params(t) == ["b.c", "notes"]
    assert unread_params(t, ignore=("notes",)) == ["b.c"]


def test_unread_params_warn_error_and_off(tmp_path, capsys):
    params = dict(yaml.safe_load((EXAMPLES / "demo-box.spec.yaml").read_text())["params"],
                  skew_deg=12.0)
    spec = _spec(tmp_path, family="demo-box", params=params)
    assert registry.build_from_spec(spec, check_only=True) == 0      # off by default
    assert "skew_deg" not in capsys.readouterr().err
    assert registry.build_from_spec(spec, check_only=True, unread_params="warn") == 0
    assert "spec declares 'skew_deg'" in capsys.readouterr().err

    spec = _spec(tmp_path, family="demo-box", params=params,
                 gate={"unread_params": "error"})
    assert registry.build_from_spec(spec, check_only=True) == 1
    assert "skew_deg" in capsys.readouterr().err
    spec = _spec(tmp_path, family="demo-box", params=params,
                 gate={"unread_params": "error", "ignore": ["skew_deg"]})
    assert registry.build_from_spec(spec, check_only=True) == 0

    spec = _spec(tmp_path, family="demo-box", gate={"unread_params": "loud"})
    with pytest.raises(ValueError, match="unread_params"):
        registry.load_spec(spec)


def test_ifc_surfaces_merge_over_the_pack(tmp_path):
    assert registry.spec_stylepack({}) is None
    pack = registry.spec_stylepack({"ifc_surfaces": {"IfcFooting": {"rgb": [0.1, 0.2, 0.3]}}})
    assert pack.styles["ifc"]["surfaces"]["IfcFooting"] == {"rgb": [0.1, 0.2, 0.3]}
    spec = _spec(tmp_path, family="demo-box", ifc_surfaces=["not", "a", "mapping"])
    with pytest.raises(ValueError, match="ifc_surfaces"):
        registry.load_spec(spec)


def test_ifc_surfaces_reach_the_written_ifc(tmp_path):
    ifcopenshell = pytest.importorskip("ifcopenshell")
    spec = _spec(tmp_path, family="demo-box",
                 # demo-box's layer: a layer key wins over an IfcClass key
                 ifc_surfaces={"S-CONC-OTLN": {"rgb": [0.1, 0.2, 0.3]}})
    assert registry.build_from_spec(spec) == 0
    f = ifcopenshell.open(str(tmp_path / "out" / "demo-box.ifc"))
    rgbs = {(round(c.Red, 3), round(c.Green, 3), round(c.Blue, 3))
            for c in f.by_type("IfcColourRgb")}
    assert (0.1, 0.2, 0.3) in rgbs
