"""IFC presentation styling — the builtin default surface/material table and a
pure resolver. Consumed by emit_ifc; a style pack's styles.yaml `ifc.surfaces`
section (a palette: per company through the org pack, per job through the
build spec's `style_pack`, #65) overrides it field by field (the kml.COLORS
merge pattern). Keys match, first hit wins: `material:<name>` (the element's
material), the DXF layer, `category:<category>` (the material's
IfcMaterial.Category), then the ifc_class; unknown -> neutral gray.

Besides colour and transparency an entry may carry `reflectance` (an
IfcReflectanceMethodEnum member, e.g. MATT for concrete, METAL for steel) and
`specular` (IfcSpecularRoughness, 0 = mirror, 1 = fully diffuse). Those two
promote the emitted style from a flat IfcSurfaceStyleShading to an
IfcSurfaceStyleRendering, which is what makes concrete read as concrete and
steel as steel in a viewer. Both are optional; an entry without them still
resolves, and emit_ifc falls back to plain shading. `diffuse` and
`specular_colour` (IfcSurfaceStyleRendering DiffuseColour / SpecularColour,
each a 0..1 factor or an rgb triple) are optional too. `texture` is reserved
for IfcSurfaceStyleWithTextures and ignored with a warning until it is built.

Each entry also names its `category`, one of IFC's IfcMaterial.Category
keywords (MATERIAL_CATEGORIES). `material_category` decides the Category an
IfcMaterial is written with (#65): an explicit value, else the first keyword
in the material's name, else the category of the surface it resolved to. A
reader styles by Category, never by the free-text Name.

Presentation only: nothing here touches geometry or quantities.
"""
from __future__ import annotations

import re
import warnings

#: IfcReflectanceMethodEnum members that IFC4 actually defines.
REFLECTANCE_METHODS = frozenset((
    "BLINN", "FLAT", "GLASS", "MATT", "METAL", "MIRROR", "PHONG", "PLASTIC",
    "STRAUSS", "NOTDEFINED"))

#: IfcMaterial.Category keywords IFC itself recommends.
MATERIAL_CATEGORIES = frozenset((
    "concrete", "steel", "aluminium", "block", "brick", "stone", "wood",
    "glass", "gypsum", "plastic", "earth"))

#: Words in a material's name that say its category. Whole words (a plural s
#: allowed, a hyphen separates), so "fill" does not match "filled"; the word
#: that comes FIRST in the name decides: "Steel pipe pile, concrete filled" is
#: steel, "Concrete backfill" concrete.
CATEGORY_WORDS: dict[str, tuple[str, ...]] = {
    "concrete": ("concrete", "shotcrete", "mortar", "grout", "cdf", "slurry",
                 "pcc"),
    "steel": ("steel", "rebar", "bar", "rod", "pipe", "cable", "strand",
              "channel", "plate", "bolt", "nut", "washer", "wire", "galvanized",
              "beam", "angle", "anchor"),
    "aluminium": ("aluminium", "aluminum"),
    "wood": ("wood", "timber", "lumber", "plyform", "plywood", "df-l",
             "cribbing", "lagging"),
    "earth": ("earth", "earthwork", "ground", "soil", "backfill", "fill",
              "embankment", "excavation"),
    "stone": ("stone", "rock", "riprap", "gravel", "aggregate"),
    "plastic": ("plastic", "elastomer", "elastomeric", "neoprene", "hdpe",
                "pvc", "polyethylene"),
    "glass": ("glass", "glazing"),
    "block": ("block", "cmu"),
    "brick": ("brick",),
    "gypsum": ("gypsum",),
}
_CATEGORY_RE = re.compile(
    r"(?<!\w)(" + "|".join(sorted(
        (re.escape(w) for ws in CATEGORY_WORDS.values() for w in ws),
        key=len, reverse=True)) + r")s?(?!\w)", re.IGNORECASE)
_WORD_CATEGORY = {w: c for c, ws in CATEGORY_WORDS.items() for w in ws}

_CONCRETE = {"rgb": [0.75, 0.73, 0.68], "transparency": 0.0,
             "material": "Concrete", "reflectance": "MATT", "specular": 0.85,
             "category": "concrete"}
_REBAR = {"rgb": [0.75, 0.15, 0.12], "transparency": 0.0,
          "material": "Reinforcing Steel",
          "reflectance": "METAL", "specular": 0.45,
          "category": "steel"}
_STEEL = {"rgb": [0.55, 0.60, 0.66], "transparency": 0.0,
          "material": "Structural Steel",
          "reflectance": "METAL", "specular": 0.30,
          "category": "steel"}
_EARTH = {"rgb": [0.56, 0.44, 0.30], "transparency": 0.5,
          "material": "Earthwork", "reflectance": "MATT", "specular": 0.95,
          "category": "earth"}
#: Placed and compacted fill (backfill, embankment, refill): a light straw,
#: opaque, against the dark native ground (_EARTH) it is placed in, so a
#: section or a 4D playback tells the ground dug from the fill put back.
#: Concrete (_CONCRETE), lean concrete / CDF (_LEAN, pale cream) and concrete
#: backfill (_BACKFILL, blue-grey) are kept as far apart as fill and earth:
#: a section must tell each from the next. Hatches: bim/section_style.py.
_FILL = {"rgb": [0.80, 0.69, 0.46], "transparency": 0.0,
         "material": "Compacted Fill", "reflectance": "MATT", "specular": 0.95,
         "category": "earth"}

_PRECAST = {"rgb": [0.78, 0.77, 0.74], "transparency": 0.0,
            "material": "Precast Concrete", "reflectance": "MATT",
            "specular": 0.80,
            "category": "concrete"}
_LEAN = {"rgb": [0.90, 0.85, 0.62], "transparency": 0.0,
         "material": "Lean Concrete", "reflectance": "MATT", "specular": 0.90,
         "category": "concrete"}
_BACKFILL = {"rgb": [0.58, 0.64, 0.70], "transparency": 0.0,
             "material": "Concrete Backfill", "reflectance": "MATT",
             "specular": 0.90,
             "category": "concrete"}
_TIMBER = {"rgb": [0.55, 0.40, 0.24], "transparency": 0.0,
           "material": "Timber", "reflectance": "MATT", "specular": 0.90,
           "category": "wood"}
_ELASTOMER = {"rgb": [0.20, 0.20, 0.22], "transparency": 0.0,
              "material": "Elastomeric Bearing", "reflectance": "PLASTIC",
              "specular": 0.70,
              "category": "plastic"}
#: A surface TREATMENT (stain, seal, coating): a colour on a face, not a solid.
_COATING = {"rgb": [0.45, 0.36, 0.28], "transparency": 0.0,
            "material": "Concrete Surface Treatment", "reflectance": "MATT",
            "specular": 0.90,
            "category": "concrete"}
#: Architectural formed relief - warmer than the concrete behind it so the
#: treated band reads as a band.
_RELIEF = {"rgb": [0.72, 0.68, 0.60], "transparency": 0.0,
           "material": "Architectural Concrete Finish", "reflectance": "MATT",
           "specular": 0.85,
           "category": "concrete"}
#: Geometry carried for reference only, never a pay quantity - see through it.
_REFERENCE = {"rgb": [0.70, 0.72, 0.75], "transparency": 0.6,
              "material": None, "reflectance": "PLASTIC", "specular": 0.5,
              "category": None}

_ALUMINIUM = {"rgb": [0.77, 0.78, 0.80], "transparency": 0.0,
              "material": "Aluminium", "reflectance": "METAL",
              "specular": 0.25, "category": "aluminium"}
_GLASS = {"rgb": [0.70, 0.80, 0.85], "transparency": 0.6,
          "material": "Glass", "reflectance": "GLASS", "specular": 0.05,
          "category": "glass"}
_STONE = {"rgb": [0.60, 0.58, 0.55], "transparency": 0.0,
          "material": "Stone", "reflectance": "MATT", "specular": 0.90,
          "category": "stone"}
_BLOCK = {"rgb": [0.68, 0.67, 0.64], "transparency": 0.0,
          "material": "Concrete Block", "reflectance": "MATT",
          "specular": 0.90, "category": "block"}
_BRICK = {"rgb": [0.62, 0.33, 0.25], "transparency": 0.0,
          "material": "Brick", "reflectance": "MATT", "specular": 0.90,
          "category": "brick"}
_GYPSUM = {"rgb": [0.92, 0.91, 0.88], "transparency": 0.0,
           "material": "Gypsum", "reflectance": "MATT", "specular": 0.90,
           "category": "gypsum"}
_PLASTIC = {"rgb": [0.30, 0.30, 0.32], "transparency": 0.0,
            "material": "Plastic", "reflectance": "PLASTIC",
            "specular": 0.60, "category": "plastic"}

#: Representative defaults. Layer keys (S-*) resolve before the material's
#: category (category:*), which resolves before ifc_class keys.
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
    "S-EW-FILL": _FILL,
    "S-PIPE-REF": _REFERENCE,
    "terrain": _EARTH,
    "IfcWall": _CONCRETE, "IfcFooting": _CONCRETE,
    "IfcReinforcingBar": _REBAR,
    "IfcRailing": _STEEL, "IfcDiscreteAccessory": _STEEL,
    "IfcGeographicElement": _EARTH,
    "IfcEarthworksFill": _FILL,
    # one look per IfcMaterial.Category (#65): a material the layer table
    # does not know still reads as what it is
    "category:concrete": _CONCRETE, "category:steel": _STEEL,
    "category:aluminium": _ALUMINIUM, "category:block": _BLOCK,
    "category:brick": _BRICK, "category:stone": _STONE,
    "category:wood": _TIMBER, "category:glass": _GLASS,
    "category:gypsum": _GYPSUM, "category:plastic": _PLASTIC,
    "category:earth": _EARTH,
}
NEUTRAL: dict = {"rgb": [0.80, 0.80, 0.80], "transparency": 0.0, "material": None,
                 "reflectance": None, "specular": None, "category": None,
                 "diffuse": None, "specular_colour": None}


def _num(v) -> bool:
    """A real number in [0,1] — bool excluded (YAML true/false must not pass)."""
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and 0.0 <= v <= 1.0)


def _valid_rgb(v) -> bool:
    return isinstance(v, (list, tuple)) and len(v) == 3 and all(_num(c) for c in v)


def _colour_or_factor(v):
    """An IfcColourOrFactor value: a 0..1 factor (float) or an rgb triple
    (list), else None."""
    if _num(v):
        return float(v)
    if _valid_rgb(v):
        return [float(c) for c in v]
    return None


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
        for fld in ("diffuse", "specular_colour"):
            if fld in entry:
                v = entry[fld]
                if v is None or _colour_or_factor(v) is not None:
                    c[fld] = None if v is None else _colour_or_factor(v)
                else:
                    warnings.warn(f"ifc styles: {key!r} has invalid {fld} "
                                  f"{v!r} (want a 0..1 factor or an rgb "
                                  f"triple); keeping default", UserWarning,
                                  stacklevel=2)
        if "texture" in entry:
            warnings.warn(f"ifc styles: {key!r} has a texture, which is "
                          f"reserved (IfcSurfaceStyleWithTextures) and not "
                          f"written yet; ignoring it", UserWarning,
                          stacklevel=2)
        if "category" in entry:
            v = entry["category"]
            if v is None or (isinstance(v, str)
                             and v.lower() in MATERIAL_CATEGORIES):
                c["category"] = v.lower() if isinstance(v, str) else None
            else:
                warnings.warn(f"ifc styles: {key!r} has invalid category "
                              f"{v!r} (want one of "
                              f"{', '.join(sorted(MATERIAL_CATEGORIES))}); "
                              f"keeping default", UserWarning, stacklevel=2)
        clean[key] = c
    return clean


def surface_keys(layer: str | None, ifc_class: str | None,
                 el_material: str | None = None,
                 category: str | None = None) -> list[str]:
    """The keys an element's appearance is looked up by, first hit wins."""
    return [k for k in (f"material:{el_material}" if el_material else None,
                        layer,
                        f"category:{category}" if category else None,
                        ifc_class) if k]


def resolve_surface(layer: str | None, ifc_class: str | None,
                    pack_ifc: dict | None = None,
                    el_material: str | None = None,
                    category: str | None = None) -> dict:
    """Appearance for an element: the pack's VALID fields for the first key
    (`surface_keys`) either the builtin table or the pack has, merged per
    field OVER the first builtin entry at or after that key (a partial
    override keeps the builtin's other fields). Falls back to neutral.
    ``el_material`` overrides the material NAME, and keys a
    ``material:<name>`` entry; ``category`` (the material's
    IfcMaterial.Category, #65) keys a ``category:<category>`` entry.

    Robust to a raw (un-sanitized) pack: an invalid field is ignored (kept from
    the base) rather than discarding the whole entry. rgb/transparency always
    valid on return; reflectance/specular are None when absent or invalid.
    """
    pack = pack_ifc or {}
    keys = surface_keys(layer, ifc_class, el_material, category)
    base: dict | None = None
    override: dict = {}
    first = next((i for i, k in enumerate(keys)
                  if k in SURFACE_DEFAULTS or k in pack), None)
    if first is not None:
        override = pack.get(keys[first]) or {}
        base = next((SURFACE_DEFAULTS[k] for k in keys[first:]
                     if k in SURFACE_DEFAULTS), None)
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
        if "category" in override:
            v = override["category"]
            if v is None:
                entry["category"] = None
            elif isinstance(v, str) and v.lower() in MATERIAL_CATEGORIES:
                entry["category"] = v.lower()
        for fld in ("diffuse", "specular_colour"):
            if fld in override:
                v = override[fld]
                if v is None or _colour_or_factor(v) is not None:
                    entry[fld] = None if v is None else _colour_or_factor(v)
    rgb = entry.get("rgb")
    if not _valid_rgb(rgb):
        rgb = NEUTRAL["rgb"]
    material = (el_material if el_material is not None
               else entry.get("material", NEUTRAL["material"]))
    refl = entry.get("reflectance")
    spec = entry.get("specular")
    cat = entry.get("category")
    return {"rgb": [float(c) for c in rgb],
            "transparency": float(entry.get("transparency", 0.0) or 0.0),
            "material": material,
            # both optional: without them emit_ifc keeps plain IfcSurfaceStyleShading
            "reflectance": (refl.upper() if isinstance(refl, str)
                            and refl.upper() in REFLECTANCE_METHODS else None),
            "specular": float(spec) if _num(spec) else None,
            "category": cat if cat in MATERIAL_CATEGORIES else None,
            "diffuse": _colour_or_factor(entry.get("diffuse")),
            "specular_colour": _colour_or_factor(entry.get("specular_colour"))}


def material_category(name: str | None, explicit: str | None = None,
                      surface: str | None = None) -> str | None:
    """The IfcMaterial.Category for a material (#65).

    `explicit` (an Element's `material_category`) wins; else the category of
    the first CATEGORY_WORDS word in `name`; else `surface`, the category of
    the surface the element resolved to; else None. Unset is better than a
    guess: a reader gives an uncategorised material a plain look.
    """
    if explicit:
        return explicit
    hit = _CATEGORY_RE.search(name or "")
    if hit:
        return _WORD_CATEGORY[hit.group(1).lower()]
    return surface
