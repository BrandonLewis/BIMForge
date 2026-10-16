"""IFC presentation styling — the builtin default surface/material table and a
pure resolver. Consumed by emit_ifc; an org style pack's styles.yaml
`ifc.surfaces` section overrides it (the kml.COLORS merge pattern). Keys match
the element's DXF layer first, then its ifc_class; unknown -> neutral gray.

Besides colour and transparency an entry may carry `reflectance` (an
IfcReflectanceMethodEnum member, e.g. MATT for concrete, METAL for steel) and
`specular` (IfcSpecularRoughness, 0 = mirror, 1 = fully diffuse). Those two
promote the emitted style from a flat IfcSurfaceStyleShading to an
IfcSurfaceStyleRendering, which is what makes concrete read as concrete and
steel as steel in a viewer. Both are optional; an entry without them still
resolves, and emit_ifc falls back to plain shading.

Presentation only: nothing here touches geometry or quantities.
"""
from __future__ import annotations

import warnings

#: IfcReflectanceMethodEnum members that IFC4 actually defines.
REFLECTANCE_METHODS = frozenset((
    "BLINN", "FLAT", "GLASS", "MATT", "METAL", "MIRROR", "PHONG", "PLASTIC",
    "STRAUSS", "NOTDEFINED"))

_CONCRETE = {"rgb": [0.75, 0.73, 0.68], "transparency": 0.0,
             "material": "Concrete", "reflectance": "MATT", "specular": 0.85}
_REBAR = {"rgb": [0.75, 0.15, 0.12], "transparency": 0.0,
          "material": "Reinforcing Steel",
          "reflectance": "METAL", "specular": 0.45}
_STEEL = {"rgb": [0.55, 0.60, 0.66], "transparency": 0.0,
          "material": "Structural Steel",
          "reflectance": "METAL", "specular": 0.30}
_EARTH = {"rgb": [0.55, 0.45, 0.32], "transparency": 0.5,
          "material": "Earthwork", "reflectance": "MATT", "specular": 0.95}

_PRECAST = {"rgb": [0.78, 0.77, 0.74], "transparency": 0.0,
            "material": "Precast Concrete", "reflectance": "MATT",
            "specular": 0.80}
_LEAN = {"rgb": [0.82, 0.81, 0.78], "transparency": 0.0,
         "material": "Lean Concrete", "reflectance": "MATT", "specular": 0.90}
_BACKFILL = {"rgb": [0.70, 0.69, 0.65], "transparency": 0.0,
             "material": "Concrete Backfill", "reflectance": "MATT",
             "specular": 0.90}
_TIMBER = {"rgb": [0.55, 0.40, 0.24], "transparency": 0.0,
           "material": "Timber", "reflectance": "MATT", "specular": 0.90}
_ELASTOMER = {"rgb": [0.20, 0.20, 0.22], "transparency": 0.0,
              "material": "Elastomeric Bearing", "reflectance": "PLASTIC",
              "specular": 0.70}
#: A surface TREATMENT (stain, seal, coating): a colour on a face, not a solid.
_COATING = {"rgb": [0.45, 0.36, 0.28], "transparency": 0.0,
            "material": "Concrete Surface Treatment", "reflectance": "MATT",
            "specular": 0.90}
#: Architectural formed relief - warmer than the concrete behind it so the
#: treated band reads as a band.
_RELIEF = {"rgb": [0.72, 0.68, 0.60], "transparency": 0.0,
           "material": "Architectural Concrete Finish", "reflectance": "MATT",
           "specular": 0.85}
#: Geometry carried for reference only, never a pay quantity - see through it.
_REFERENCE = {"rgb": [0.70, 0.72, 0.75], "transparency": 0.6,
              "material": None, "reflectance": "PLASTIC", "specular": 0.5}

#: Representative defaults. Layer keys (S-*) resolve first, ifc_class keys second.
SURFACE_DEFAULTS: dict[str, dict] = {
    # cast-in-place concrete and its variants
    "S-CONC": _CONCRETE, "S-CONC-OTLN": _CONCRETE,
    "S-COPING-SLAB": _CONCRETE, "S-BARRIER": _CONCRETE,
    "S-LAGGING-PC": _PRECAST,
    "S-BACKFILL-CONC": _BACKFILL, "S-BACKFILL-LEAN": _LEAN,
    "S-BARRIER-RELIEF": _RELIEF,
    "S-STAIN": _COATING,
    # steel, in the spellings the families actually use
    "S-STEEL": _STEEL, "S-STL": _STEEL, "S-METAL": _STEEL, "S-METL": _STEEL,
    "S-BOLT": _STEEL, "S-PILE": _STEEL, "S-PILE-CAP": _STEEL,
    "S-REBAR": _REBAR, "S-REBR": _REBAR, "S-REIN": _REBAR,
    # everything else
    "S-LAGGING-TIMB": _TIMBER,
    "S-BEARING-PAD": _ELASTOMER,
    "S-EW-FILL": _EARTH,
    "S-PIPE-REF": _REFERENCE,
    "terrain": _EARTH,
    "IfcWall": _CONCRETE, "IfcFooting": _CONCRETE,
    "IfcReinforcingBar": _REBAR,
    "IfcRailing": _STEEL, "IfcDiscreteAccessory": _STEEL,
    "IfcGeographicElement": _EARTH,
}
NEUTRAL: dict = {"rgb": [0.80, 0.80, 0.80], "transparency": 0.0, "material": None,
                 "reflectance": None, "specular": None}


def _num(v) -> bool:
    """A real number in [0,1] — bool excluded (YAML true/false must not pass)."""
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and 0.0 <= v <= 1.0)


def _valid_rgb(v) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == 3 and all(_num(c) for c in v)


def sanitize_pack(pack_ifc) -> dict:
    """Reduce an org pack's ``ifc.surfaces`` to its VALID fields, emitting one
    UserWarning per malformed section/key/field (warn-and-degrade). A non-mapping
    input degrades to ``{}`` with a warning; ``None`` -> ``{}`` silently.
    """
    if pack_ifc is None:
        return {}
    if not isinstance(pack_ifc, dict):
        warnings.warn(f"ifc styles: 'surfaces' is not a mapping "
                      f"({type(pack_ifc).__name__}); ignoring org overrides",
                      UserWarning, stacklevel=2)
        return {}
    clean: dict = {}
    for key, entry in pack_ifc.items():
        if not isinstance(entry, dict):
            warnings.warn(f"ifc styles: surface override {key!r} is not a "
                          f"mapping; ignoring", UserWarning, stacklevel=2)
            continue
        c: dict = {}
        if "rgb" in entry:
            if _valid_rgb(entry["rgb"]):
                c["rgb"] = [float(x) for x in entry["rgb"]]
            else:
                warnings.warn(f"ifc styles: {key!r} has invalid rgb "
                              f"{entry['rgb']!r}; keeping default color",
                              UserWarning, stacklevel=2)
        if "transparency" in entry:
            if _num(entry["transparency"]):
                c["transparency"] = float(entry["transparency"])
            else:
                warnings.warn(f"ifc styles: {key!r} has invalid transparency "
                              f"{entry['transparency']!r}; keeping default",
                              UserWarning, stacklevel=2)
        if "material" in entry:
            m = entry["material"]
            if m is None or isinstance(m, str):
                c["material"] = m
            else:
                warnings.warn(f"ifc styles: {key!r} has invalid material "
                              f"{m!r}; keeping default", UserWarning, stacklevel=2)
        if "reflectance" in entry:
            r = entry["reflectance"]
            if r is None or (isinstance(r, str) and r.upper() in REFLECTANCE_METHODS):
                c["reflectance"] = r.upper() if isinstance(r, str) else None
            else:
                warnings.warn(f"ifc styles: {key!r} has invalid reflectance "
                              f"{r!r} (want one of "
                              f"{', '.join(sorted(REFLECTANCE_METHODS))}); "
                              f"keeping default", UserWarning, stacklevel=2)
        if "specular" in entry:
            v = entry["specular"]
            if v is None or _num(v):
                c["specular"] = float(v) if v is not None else None
            else:
                warnings.warn(f"ifc styles: {key!r} has invalid specular "
                              f"{v!r} (want 0..1); keeping default",
                              UserWarning, stacklevel=2)
        clean[key] = c
    return clean


def resolve_surface(layer: str | None, ifc_class: str | None,
                    pack_ifc: dict | None = None,
                    el_material: str | None = None) -> dict:
    """Appearance for an element: builtin base for the first matching key
    (layer, then ifc_class), with the org pack's VALID fields merged OVER that
    base per field (a partial override keeps the builtin's other fields). Falls
    back to neutral. ``el_material`` overrides the material NAME only.

    Robust to a raw (un-sanitized) pack: an invalid field is ignored (kept from
    the base) rather than discarding the whole entry. rgb/transparency always
    valid on return; reflectance/specular are None when absent or invalid.
    """
    pack = pack_ifc or {}
    base: dict | None = None
    override: dict = {}
    for key in (layer, ifc_class):
        if key and (key in SURFACE_DEFAULTS or key in pack):
            base = SURFACE_DEFAULTS.get(key)
            override = pack.get(key) or {}
            break
    entry = dict(base) if isinstance(base, dict) else {}
    if isinstance(override, dict):
        if _valid_rgb(override.get("rgb")):
            entry["rgb"] = [float(x) for x in override["rgb"]]
        if _num(override.get("transparency")):
            entry["transparency"] = float(override["transparency"])
        if "material" in override:
            m = override["material"]
            if m is None or isinstance(m, str):
                entry["material"] = m
        # explicit null CLEARS, matching `material` above: an org pack must be
        # able to force flat shading while keeping the builtin colour. An
        # INVALID value is still ignored (the base survives) for a raw pack.
        if "reflectance" in override:
            r = override["reflectance"]
            if r is None:
                entry["reflectance"] = None
            elif isinstance(r, str) and r.upper() in REFLECTANCE_METHODS:
                entry["reflectance"] = r.upper()
        if "specular" in override:
            v = override["specular"]
            if v is None:
                entry["specular"] = None
            elif _num(v):
                entry["specular"] = float(v)
    rgb = entry.get("rgb")
    if not _valid_rgb(rgb):
        rgb = NEUTRAL["rgb"]
    material = (el_material if el_material is not None
               else entry.get("material", NEUTRAL["material"]))
    refl = entry.get("reflectance")
    spec = entry.get("specular")
    return {"rgb": [float(c) for c in rgb],
            "transparency": float(entry.get("transparency", 0.0) or 0.0),
            "material": material,
            # both optional: without them emit_ifc keeps plain IfcSurfaceStyleShading
            "reflectance": (refl.upper() if isinstance(refl, str)
                            and refl.upper() in REFLECTANCE_METHODS else None),
            "specular": float(spec) if _num(spec) else None}
