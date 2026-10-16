"""Org style packs — pluggable CAD styling for bimforge outputs.

A style pack is a Python package or a directory that provides, by convention:

* ``templates/*.dxf`` — title-block border libraries (the first, sorted by
  name, is used as the title-block library);
* ``styles.yaml`` — optional model/output styling, namespaced by consumer:
  a ``layers:`` mapping (DXF layer name -> ``{color, linetype}``) consumed by
  :mod:`bimforge.bim.ifc2dxf`, the ``kml:`` mapping (``colors:`` IFC class ->
  aabbggrr) consumed by :mod:`bimforge.bim.kml`, and an ``ifc:`` mapping
  (``surfaces:`` layer-or-class ->
  ``{rgb, transparency, material, reflectance, specular}``; the last two
  are optional and promote the emitted style to IfcSurfaceStyleRendering)
  consumed by :mod:`bimforge.author.emit_ifc` for IFC presentation colors.
  Unknown sections are ignored, so packs can still carry future sections
  harmlessly.

Resolution order (first hit wins):

1. an explicit package-name-or-path argument;
2. the first spec returned by a registered **provider** — any installed
   distribution may declare an entry point in the ``bimforge.style_packs``
   group whose target is a zero-argument callable returning a pack spec
   (package name or directory path) or ``None``. The estimating layer
   registers one that reads the active org profile's ``cad_style_pack`` key;
   bimforge itself imports nothing from it and works standalone with none;
3. bimforge's built-in neutral defaults (packaged generic templates, no styles).

Failure contract: warn-and-degrade, uniformly. A requested pack that does not
resolve to anything usable (nonexistent path, unimportable package, or a root
providing neither ``templates/`` nor ``styles.yaml``) emits a
:class:`UserWarning` and resolution falls through (ultimately to the builtin).
A syntactically invalid ``styles.yaml`` warns and is treated as empty while
the pack's valid ``templates/*.dxf`` are still used. Only the no-config path —
nothing requested, builtin returned — is silent.

Any installed package satisfies the interface by shipping its own
``templates/*.dxf`` library (and optionally ``styles.yaml``) at its root.
"""
from __future__ import annotations

import warnings
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from pathlib import Path

import yaml

#: Entry-point group a distribution declares to offer a style-pack spec.
#: Target: a zero-argument callable returning ``str | None``.
STYLE_PACK_GROUP = "bimforge.style_packs"


@dataclass(frozen=True)
class StylePack:
    """A resolved style pack: where its templates live and its parsed styles."""

    templates_dir: Path | None = None
    styles: dict = field(default_factory=dict)

    @property
    def title_block_library(self) -> Path | None:
        """First ``*.dxf`` (sorted by name) under ``templates/``, or None."""
        if self.templates_dir is None or not self.templates_dir.is_dir():
            return None
        hits = sorted(self.templates_dir.glob("*.dxf"))
        return hits[0] if hits else None


def _pack_root(spec: str) -> Path | None:
    """A pack given as a directory path, else as an importable package name."""
    path = Path(spec)
    if path.is_dir():
        return path
    try:
        from importlib.resources import files
        return Path(str(files(spec)))
    except (ImportError, ModuleNotFoundError, TypeError, ValueError):
        return None


def _load_styles(root: Path, spec: str) -> dict:
    """Parse the pack's styles.yaml; warn and degrade to ``{}`` on bad YAML."""
    f = root / "styles.yaml"
    if not f.is_file():
        return {}
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        warnings.warn(
            f"styles.yaml in pack {spec!r} is invalid YAML ({err}); "
            "ignoring styles",
            stacklevel=3,
        )
        return {}
    return data if isinstance(data, dict) else {}


def _provider_specs() -> list[str]:
    """Pack specs from every registered ``bimforge.style_packs`` provider, in
    entry-point order. A provider that fails to load or raises contributes
    nothing (an org profile that is unset or invalid is the normal standalone
    case, not an error here); a provider returning a non-string is ignored.
    """
    specs: list[str] = []
    for ep in entry_points(group=STYLE_PACK_GROUP):
        try:
            value = ep.load()()
        except Exception:
            continue
        if isinstance(value, str) and value:
            specs.append(value)
    return specs


def builtin_pack() -> StylePack:
    """bimforge's neutral defaults: the packaged generic templates, no styles."""
    return StylePack(templates_dir=Path(__file__).parent / "templates", styles={})


def resolve_style_pack(explicit: str | None = None) -> StylePack:
    """Resolve the active style pack: explicit arg -> providers -> builtin.

    A requested spec that does not resolve to a usable pack warns (UserWarning)
    and degrades; with nothing requested the builtin is returned silently.
    """
    for spec in (explicit, *_provider_specs()):
        if not spec:
            continue
        root = _pack_root(spec)
        templates = root / "templates" if root is not None else None
        has_templates = templates is not None and templates.is_dir()
        has_styles = root is not None and (root / "styles.yaml").is_file()
        if not has_templates and not has_styles:
            warnings.warn(
                f"cad style pack {spec!r} did not resolve; "
                "falling back",
                stacklevel=2,
            )
            continue
        return StylePack(
            templates_dir=templates if has_templates else None,
            styles=_load_styles(root, spec),
        )
    return builtin_pack()
