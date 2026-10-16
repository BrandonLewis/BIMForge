from bimforge.author.ifc_styles import resolve_surface, SURFACE_DEFAULTS, NEUTRAL


def test_layer_hit_wins():
    s = resolve_surface("S-REBAR", "IfcReinforcingBar", pack_ifc=None)
    assert s["rgb"] == [0.75, 0.15, 0.12]
    assert s["material"] == "Reinforcing Steel"
    assert s["transparency"] == 0.0


def test_class_fallback_when_no_layer():
    s = resolve_surface(None, "IfcFooting", pack_ifc=None)
    assert s["rgb"] == [0.75, 0.73, 0.68]        # concrete default via class
    assert s["material"] == "Concrete"


def test_neutral_when_unknown():
    s = resolve_surface("S-NOPE", "IfcWhatever", pack_ifc=None)
    assert s == dict(NEUTRAL)
    assert s["rgb"] == [0.80, 0.80, 0.80]
    assert s["material"] is None
    # no finish on the fallback: emit_ifc must keep plain shading for it
    assert s["reflectance"] is None and s["specular"] is None


def test_pack_override_merges_over_default():
    pack = {"S-CONC": {"rgb": [0.1, 0.2, 0.3], "transparency": 0.25,
                       "material": "OrgConcrete"}}
    s = resolve_surface("S-CONC", "IfcWall", pack_ifc=pack)
    assert s["rgb"] == [0.1, 0.2, 0.3]
    assert s["transparency"] == 0.25
    assert s["material"] == "OrgConcrete"
    assert resolve_surface("S-REBAR", None, pack_ifc=pack)["rgb"] == [0.75, 0.15, 0.12]


def test_malformed_pack_entry_degrades_to_next_key():
    pack = {"S-CONC": {"rgb": [2.0, 0.0, 0.0], "transparency": 0.0}}
    s = resolve_surface("S-CONC", "IfcWall", pack_ifc=pack)
    assert s["rgb"] == [0.75, 0.73, 0.68]        # IfcWall concrete default


def test_partial_override_bad_transparency_keeps_valid_rgb():
    # valid rgb applies; the bad transparency is ignored (kept from base), NOT
    # discarding the whole entry.
    pack = {"S-CONC": {"rgb": [0.1, 0.2, 0.3], "transparency": "oops"}}
    s = resolve_surface("S-CONC", "IfcWall", pack_ifc=pack)
    assert s["rgb"] == [0.1, 0.2, 0.3]
    assert s["transparency"] == 0.0


def test_partial_material_override_keeps_builtin_color():
    pack = {"IfcWall": {"material": "HES Concrete"}}
    s = resolve_surface(None, "IfcWall", pack_ifc=pack)
    assert s["rgb"] == [0.75, 0.73, 0.68]          # builtin concrete color kept
    assert s["material"] == "HES Concrete"


def test_bool_rgb_is_rejected():
    pack = {"S-CONC": {"rgb": [True, False, False]}}
    s = resolve_surface("S-CONC", "IfcWall", pack_ifc=pack)
    assert s["rgb"] == [0.75, 0.73, 0.68]          # bool rgb ignored, base kept


def test_sanitize_pack_warns_on_malformed(recwarn):
    from bimforge.author.ifc_styles import sanitize_pack
    clean = sanitize_pack({"S-CONC": {"rgb": [2.0, 0, 0], "material": 123},
                           "S-STEEL": "not-a-dict"})
    # invalid fields dropped; valid ones (none here for S-CONC) absent
    assert clean["S-CONC"] == {}
    assert "S-STEEL" not in clean
    assert len(recwarn.list) >= 2                  # >=1 per malformed key/field


def test_sanitize_pack_non_mapping_warns():
    import pytest
    from bimforge.author.ifc_styles import sanitize_pack
    with pytest.warns(UserWarning):
        assert sanitize_pack(["not", "a", "mapping"]) == {}


def test_element_material_overrides_table():
    s = resolve_surface("S-CONC", "IfcWall", pack_ifc=None, el_material="HES Concrete")
    assert s["material"] == "HES Concrete"
    assert s["rgb"] == [0.75, 0.73, 0.68]


def test_geographic_element_gets_earth_default():
    s = resolve_surface(None, "IfcGeographicElement", pack_ifc=None)
    assert s["rgb"] == [0.55, 0.45, 0.32]
    assert s["transparency"] == 0.5
    assert s["material"] == "Earthwork"


def test_finish_resolves_and_is_optional():
    """Reflectance/specular ride the same layer-then-class lookup as colour."""
    conc = resolve_surface("S-CONC", None, pack_ifc=None)
    assert conc["reflectance"] == "MATT" and conc["specular"] == 0.85
    steel = resolve_surface(None, "IfcRailing", pack_ifc=None)
    assert steel["reflectance"] == "METAL"
    # an entry that predates the finish fields still resolves, with None
    plain = resolve_surface("S-X", None, pack_ifc={"S-X": {"rgb": [0.1, 0.1, 0.1]}})
    assert plain["rgb"] == [0.1, 0.1, 0.1]
    assert plain["reflectance"] is None and plain["specular"] is None


def test_pack_can_set_and_case_normalise_finish():
    pack = {"S-CONC": {"reflectance": "plastic", "specular": 0.2}}
    s = resolve_surface("S-CONC", None, pack_ifc=pack)
    assert s["reflectance"] == "PLASTIC" and s["specular"] == 0.2
    assert s["rgb"] == [0.75, 0.73, 0.68]        # colour still the builtin


def test_bad_finish_degrades_and_warns():
    import warnings
    from bimforge.author.ifc_styles import sanitize_pack
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        clean = sanitize_pack({"S-A": {"reflectance": "SHINY", "specular": 4}})
    assert clean == {"S-A": {}}
    assert len(w) == 2
    # and an unsanitised pack must not poison the resolved appearance either
    s = resolve_surface("S-CONC", None,
                        pack_ifc={"S-CONC": {"reflectance": "SHINY",
                                             "specular": 4}})
    assert s["reflectance"] == "MATT" and s["specular"] == 0.85


def test_pack_can_clear_a_builtin_finish():
    """An org must be able to force flat shading while keeping builtin colour.

    `material` has always supported an explicit null; the finish fields have
    to match it, or a pack can add a finish but never take one away.
    """
    pack = {"S-CONC": {"reflectance": None, "specular": None}}
    s = resolve_surface("S-CONC", None, pack_ifc=pack)
    assert s["reflectance"] is None and s["specular"] is None
    assert s["rgb"] == [0.75, 0.73, 0.68]        # colour untouched
    # clearing only one of the two leaves the other alone
    half = resolve_surface("S-CONC", None, pack_ifc={"S-CONC": {"reflectance": None}})
    assert half["reflectance"] is None and half["specular"] == 0.85
