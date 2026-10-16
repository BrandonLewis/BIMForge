"""Tests for bimforge.cad.stylepack — resolution order and pack layout."""
from __future__ import annotations

import importlib
import textwrap

import pytest

pytest.importorskip("ezdxf")

from bimforge.cad import stylepack
from bimforge.cad.stylepack import STYLE_PACK_GROUP, resolve_style_pack


class _FakeEntryPoint:
    def __init__(self, fn):
        self._fn = fn

    def load(self):
        return self._fn


def _providers(monkeypatch, *fns):
    """Make `entry_points(group=STYLE_PACK_GROUP)` return these providers only."""
    def fake_entry_points(group=None):
        assert group == STYLE_PACK_GROUP
        return [_FakeEntryPoint(fn) for fn in fns]
    monkeypatch.setattr(stylepack, "entry_points", fake_entry_points)


def _make_pack_dir(base, name="pack"):
    root = base / name
    (root / "templates").mkdir(parents=True)
    (root / "templates" / "a-borders.dxf").write_text("stub", encoding="utf-8")
    (root / "styles.yaml").write_text(textwrap.dedent("""\
        layers:
          IFCSLAB: {color: 5, linetype: DASHED}
        kml:
          colors:
            IfcSlab: ff112233
    """), encoding="utf-8")
    return root


def test_explicit_path_pack_wins(tmp_path, monkeypatch):
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    root = _make_pack_dir(tmp_path)
    pack = resolve_style_pack(str(root))
    assert pack.title_block_library == root / "templates" / "a-borders.dxf"
    assert pack.styles["layers"]["IFCSLAB"] == {"color": 5, "linetype": "DASHED"}
    assert pack.styles["kml"]["colors"]["IfcSlab"] == "ff112233"


def test_package_name_pack_resolves(tmp_path, monkeypatch):
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    pkg = tmp_path / "fake_style_pack"
    (pkg / "templates").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "templates" / "x.dxf").write_text("stub", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    pack = resolve_style_pack("fake_style_pack")
    assert pack.title_block_library is not None
    assert pack.title_block_library.name == "x.dxf"
    assert pack.styles == {}


def test_no_pack_falls_back_to_builtin(monkeypatch):
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    pack = resolve_style_pack()
    assert pack.title_block_library is not None
    assert pack.title_block_library.name == "generic-title-blocks.dxf"


def test_provider_spec_consulted_after_explicit_and_before_builtin(tmp_path, monkeypatch):
    root = _make_pack_dir(tmp_path, "orgpack")
    _providers(monkeypatch, lambda: root.as_posix())
    pack = resolve_style_pack()
    assert pack.title_block_library == root / "templates" / "a-borders.dxf"
    # an explicit spec still wins over the provider
    other = _make_pack_dir(tmp_path, "explicit")
    assert resolve_style_pack(str(other)).title_block_library == \
        other / "templates" / "a-borders.dxf"


def test_failing_or_empty_providers_contribute_nothing(monkeypatch):
    def boom():
        raise RuntimeError("profile system unavailable")
    _providers(monkeypatch, boom, lambda: None, lambda: "", lambda: 42)
    pack = resolve_style_pack()
    assert pack.title_block_library.name == "generic-title-blocks.dxf"


def test_first_usable_provider_wins_and_a_bad_one_warns(tmp_path, monkeypatch):
    root = _make_pack_dir(tmp_path, "second")
    _providers(monkeypatch, lambda: "totally-bogus-pack", lambda: root.as_posix())
    with pytest.warns(UserWarning, match="did not resolve"):
        pack = resolve_style_pack()
    assert pack.title_block_library == root / "templates" / "a-borders.dxf"


def test_estimating_layer_registers_the_profile_provider(tmp_path, monkeypatch):
    """End to end through the REAL entry point: the estimating_tools
    distribution declares `bimforge.style_packs = profile`, which reads the
    active org profile's `cad_style_pack`. Skipped when that distribution is
    not installed (standalone bimforge)."""
    pytest.importorskip("estimating_tools.profiles.loader")
    pytest.importorskip("jsonschema")
    from importlib.metadata import entry_points
    names = {ep.name for ep in entry_points(group=STYLE_PACK_GROUP)}
    if "profile" not in names:
        pytest.skip("estimating_tools entry point not registered in this env "
                    "(reinstall it: pip install -e packages/estimating-tools)")
    root = _make_pack_dir(tmp_path, "orgpack")
    profile_dir = tmp_path / "org-profile"
    profile_dir.mkdir()
    (profile_dir / "profile.yaml").write_text(
        f"cad_style_pack: {root.as_posix()}\n", encoding="utf-8")
    monkeypatch.setenv("ESTIMATING_PROFILES", str(profile_dir))
    pack = resolve_style_pack()
    assert pack.title_block_library == root / "templates" / "a-borders.dxf"


def test_unresolvable_pack_warns_and_degrades_to_builtin(monkeypatch):
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    with pytest.warns(UserWarning, match="did not resolve"):
        pack = resolve_style_pack("totally-bogus-pack")
    assert pack.title_block_library is not None
    assert pack.title_block_library.name == "generic-title-blocks.dxf"


def test_invalid_styles_yaml_warns_but_templates_still_used(tmp_path, monkeypatch):
    monkeypatch.delenv("ESTIMATING_PROFILES", raising=False)
    root = tmp_path / "badpack"
    (root / "templates").mkdir(parents=True)
    (root / "templates" / "a-borders.dxf").write_text("stub", encoding="utf-8")
    (root / "styles.yaml").write_text("layers: [unclosed\n", encoding="utf-8")
    with pytest.warns(UserWarning, match="invalid YAML"):
        pack = resolve_style_pack(str(root))
    assert pack.styles == {}
    assert pack.title_block_library == root / "templates" / "a-borders.dxf"
