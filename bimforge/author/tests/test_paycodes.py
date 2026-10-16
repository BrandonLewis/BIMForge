"""paycodes: validation, rule order, multi-code, weight density, map round-trip."""
import pytest

from bimforge.author.model import Element
from bimforge.author.paycodes import PayCodes, from_dict

pytest.importorskip("yaml")

FIXTURE = {
    "project_ref": "fixture-structure",
    "defaults": {"schedule": "Base Bid"},
    "rules": [
        # order matters: the wall rule must precede the generic footing rule,
        # or "RW2 footing seg 1" bills as a plain footing (ifc_qto lesson).
        {"match": r"retaining wall|^RW\d", "group": "wall"},
        {"match": r"(?i)footing", "ifc_class": "IfcFooting", "group": "footing"},
        {"match": r"(?i)pile", "ifc_class": "IfcPile", "group": "pile"},
        {"match": r"(?i)void", "group": "footing", "sign": -1},
        {"match": r"(?i)plate|saddle", "group": "steel"},
    ],
    "groups": {
        "wall": {"measure": "GrossVolume"},
        "footing": {"measure": "GrossVolume"},
        "pile": {},
        "steel": {"measure": "GrossWeight", "density_pcf": 490.0},
    },
    "codes": {
        "F-CONC": {"group": "footing", "measure": "GrossVolume", "unit": "CY",
                   "item_number": "0040"},
        "W-CONC": {"group": "wall", "measure": "GrossVolume", "unit": "CY"},
        # multi-code group: one element pays two items (furnish + drive)
        "P-FRN": {"group": "pile", "measure": "Length", "unit": "LF"},
        "P-DRV": {"group": "pile", "measure": "Count", "unit": "EA"},
        "S-STL": {"group": "steel", "measure": "GrossWeight", "unit": "LBS"},
    },
}


def test_classification_identity_defaults_and_overrides_and_round_trips():
    # default identity is BidSchedule (backward-compatible), not round-tripped
    pc = from_dict(FIXTURE)
    assert pc.source_system == "BidSchedule"
    assert pc.edition == ""
    default_map = pc.takeoff_map(["F-CONC"])
    assert "source_system" not in default_map and "edition" not in default_map

    # explicit identity is parsed and round-tripped through the takeoff map
    pc2 = from_dict({**FIXTURE, "source_system": "MasterFormat", "edition": "2020"})
    assert pc2.source_system == "MasterFormat"
    assert pc2.edition == "2020"
    doc = pc2.takeoff_map(["F-CONC"])
    assert doc["source_system"] == "MasterFormat"
    assert doc["edition"] == "2020"

    # yaml.safe_load parses an unquoted `edition: 2020` as an int; it must be
    # coerced to a string so it can't leak a non-string into IfcClassification.Edition
    pc3 = from_dict({**FIXTURE, "source_system": "MasterFormat", "edition": 2020})
    assert pc3.edition == "2020" and isinstance(pc3.edition, str)


def test_rule_order_first_match_wins():
    pc = from_dict(FIXTURE)
    assert pc.group_of("RW2 footing seg 1", "IfcFooting") == ("wall", 1)
    assert pc.group_of("abutment footing", "IfcFooting") == ("footing", 1)
    assert pc.group_of("footing sketch", "IfcAnnotation") == (None, 1)  # class gate
    assert pc.group_of("cell void", "IfcFooting")[1] == -1


def test_multi_code_classification():
    pc = from_dict(FIXTURE)
    el = Element("bent pile 3", ifc_class="IfcPile")
    assert pc.classify(el) == ["P-DRV", "P-FRN"]      # sorted, both codes
    assert pc.classify(Element("mystery", ifc_class="IfcWall")) == []


def test_apply_fills_weight_from_group_density():
    from bimforge.author.model import StructureModel
    from bimforge.author.paycodes import apply
    from bimforge.author.project import ProjectContext
    import uuid
    m = StructureModel("f", ProjectContext(name="f", guid_ns=uuid.UUID(int=1)))
    el = m.add(Element("base plate", quantities={"volume_cf": 2.0}))
    apply(m, from_dict(FIXTURE))
    assert el.classifications == ["S-STL"]
    assert el.quantities["weight_lb"] == pytest.approx(980.0)


def test_validation_errors_reported_together():
    bad = {
        "rules": [{"match": "(", "group": "ghost", "sign": 3}],
        "groups": {"g": {"measure": "Sideways"}},
        "codes": {
            "A": {"group": "ghost", "measure": "GrossVolume", "unit": "CY"},
            "B": {"group": "g", "measure": "Nope", "unit": "CY"},
            "C": {"group": "g", "measure": "GrossWeight", "unit": "LBS"},
            "D": {"group": "g", "measure": "GrossVolume"},
        },
    }
    with pytest.raises(ValueError) as exc:
        from_dict(bad)
    msg = str(exc.value)
    for frag in ("bad regex", "sign must be", "unknown measure", "not in groups",
                 "density_pcf", "needs a pay unit"):
        assert frag in msg, f"missing {frag!r} in: {msg}"


def test_takeoff_map_round_trips_through_normalize_map():
    pc = from_dict(FIXTURE)
    tmap = pc.takeoff_map(["F-CONC", "P-FRN", "P-DRV", "S-STL"])
    assert tmap["project_ref"] == "fixture-structure"
    assert tmap["codes"]["F-CONC"] == {"measure": "GrossVolume", "unit": "CY",
                                       "item_number": "0040"}
    assert tmap["codes"]["S-STL"]["measure"] == "GrossWeight"
    pytest.importorskip("ifcopenshell")
    from bimforge.bim.ifc_takeoff import normalize_map
    codes_cfg, defaults, entries = normalize_map(tmap)   # must not raise
    assert set(codes_cfg) == {"F-CONC", "P-FRN", "P-DRV", "S-STL"}
    assert defaults == {"schedule": "Base Bid"}
    assert all(v is None for v in entries.values())      # singular form
