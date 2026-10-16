"""Unit tests for bim.ifc_takeoff helpers (stub elements — no IFC file)."""
import pytest

from bimforge.bim.ifc_takeoff import element_entry


class _El:
    def __init__(self, name="Deck-1", cls="IfcSlab", gid="2FakeGuid0000000000001"):
        self.Name = name
        self.GlobalId = gid
        self._cls = cls

    def is_a(self):
        return self._cls


def test_element_entry_carries_global_id_measure_and_si_value():
    qtys = {"GrossArea": 46.45, "Length": 3.0, "Width": 1.5, "Height": 0.3}
    e = element_entry(_El(), qtys, "GrossArea")
    assert e["global_id"] == "2FakeGuid0000000000001"
    assert e["measure"] == "GrossArea"
    assert e["value_si"] == 46.45
    # pre-existing keys unchanged
    assert e["name"] == "Deck-1"
    assert e["section_type"] == "decks"
    assert e["count"] == 1
    assert round(e["length_ft"], 2) == 9.84


def test_element_entry_tolerates_missing_measure():
    # defensive: a caller with no chosen measure still gets identity keys
    e = element_entry(_El(), {}, None)
    assert e["global_id"] and e["measure"] is None and e["value_si"] is None


def test_volume_element_carries_cy_for_the_structures_planner():
    # a swept solid records only GrossVolume (+ maybe a height), no full box;
    # element_entry hands the planner an explicit CY so it need not recompute
    # one from an incomplete L×W×H (issue #210). 3.1 m³ -> 4.0546 CY.
    e = element_entry(_El(cls="IfcWall"), {"GrossVolume": 3.1, "Height": 1.9}, "GrossVolume")
    assert e["cy"] == pytest.approx(3.1 * 1.30795061931, rel=1e-4)
    assert e["value_si"] == 3.1


def test_non_volume_element_has_no_cy():
    # area/length/count/weight elements are not volumes — no cy key
    e = element_entry(_El(), {"GrossArea": 46.45}, "GrossArea")
    assert "cy" not in e


import ifcopenshell
import ifcopenshell.api.pset
import ifcopenshell.api.root
import ifcopenshell.api.unit

from bimforge.bim.ifc_takeoff import ifc_leg


def _qto_ifc(path):
    f = ifcopenshell.file(schema="IFC4")
    project = ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject",
                                                  name="p")
    ifcopenshell.api.unit.assign_unit(f)   # ifcopenshell default: MILLIMETRES
    slab = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlab",
                                               name="Deck-1")
    qto = ifcopenshell.api.pset.add_qto(f, product=slab,
                                        name="Qto_SlabBaseQuantities")
    # native mm² — 44.59 m²; the reader must scale by the declared unit
    # (issue #109), never assume SI
    ifcopenshell.api.pset.edit_qto(f, qto=qto,
                                   properties={"GrossArea": 44_590_000.0})
    f.write(str(path))
    return path


def test_ifc_leg_maps_global_ids_to_si_qtys(tmp_path):
    path = _qto_ifc(tmp_path / "leg.ifc")
    leg = ifc_leg(str(path))
    (gid, info), = leg.items()
    assert info["name"] == "Deck-1"
    assert info["ifc_class"] == "IfcSlab"
    # the fixture file is mm-declared; the leg must come back in SI m²
    assert info["qtys"]["GrossArea"] == pytest.approx(44.59)
    assert len(gid) == 22          # an IFC GlobalId


# ----------------------------------------------------------------------------
# Multi-classification (issue #106): one element, several pay codes —
# furnish-and-drive piling pays twice off one physical pile.
# ----------------------------------------------------------------------------
import ifcopenshell.api.classification  # noqa: E402

from bimforge.bim.ifc_takeoff import (  # noqa: E402
    build_takeoff, classification_of, classifications_of,
)

M_TO_FT = 3.28083989501


def _pile_two_codes_ifc(path, codes=("PILE-200W-FRN", "PILE-200W-DRV")):
    """One IfcPile carrying a classification reference per entry in `codes`
    (duplicates allowed — the dedupe test relies on that), with Length and
    Count Qtos so each code can sum a different measure. The file is
    mm-declared (assign_unit default), so Length is authored in native mm —
    12.5 m — and the reader's unit scaling (issue #109) is exercised by
    every test on this fixture."""
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.unit.assign_unit(f)   # default: MILLIMETRES
    pile = ifcopenshell.api.root.create_entity(f, ifc_class="IfcPile",
                                               name="P-1")
    qto = ifcopenshell.api.pset.add_qto(f, product=pile,
                                        name="Qto_PileBaseQuantities")
    ifcopenshell.api.pset.edit_qto(f, qto=qto,
                                   properties={"Length": 12_500.0, "Count": 1})
    system = ifcopenshell.api.classification.add_classification(
        f, classification="BidSchedule")
    for code in codes:
        ifcopenshell.api.classification.add_reference(
            f, products=[pile], identification=code, name=code,
            classification=system)
    f.write(str(path))
    return path


def test_classifications_of_returns_every_code(tmp_path):
    path = _pile_two_codes_ifc(tmp_path / "pile.ifc")
    f = ifcopenshell.open(str(path))
    pile = f.by_type("IfcPile")[0]
    got = classifications_of(pile)
    assert {c["code"] for c in got} == {"PILE-200W-FRN", "PILE-200W-DRV"}
    assert all(c["system"] == "BidSchedule" for c in got)
    # the singular shim keeps its old first-hit contract
    assert classification_of(pile) == got[0]


def test_build_takeoff_gives_every_code_its_own_row(tmp_path):
    # the issue #106 case: FRN sums Length, DRV sums Count, one element
    path = _pile_two_codes_ifc(tmp_path / "pile.ifc")
    tmap = {"codes": {"PILE-200W-FRN": {"measure": "Length", "unit": "LF"},
                      "PILE-200W-DRV": {"measure": "Count", "unit": "EA"}}}
    takeoff, warnings = build_takeoff(str(path), tmap)
    rows = {r["cost_code"]: r for r in takeoff["rows"]}
    assert set(rows) == {"PILE-200W-FRN", "PILE-200W-DRV"}
    assert abs(rows["PILE-200W-FRN"]["quantity"] - 12.5 * M_TO_FT) < 0.01
    assert rows["PILE-200W-DRV"]["quantity"] == 1
    # the same physical element backs both rows — traceable, not doubled
    gids = {r["elements"][0]["global_id"] for r in rows.values()}
    assert len(gids) == 1
    assert not any("produced no rows" in w for w in warnings)


def test_same_code_twice_on_one_element_counts_once(tmp_path):
    path = _pile_two_codes_ifc(tmp_path / "dup.ifc",
                               codes=("PILE-200W-FRN", "PILE-200W-FRN"))
    tmap = {"codes": {"PILE-200W-FRN": {"measure": "Length", "unit": "LF"}}}
    takeoff, _ = build_takeoff(str(path), tmap)
    (row,) = takeoff["rows"]
    assert abs(row["quantity"] - 12.5 * M_TO_FT) < 0.01   # once, not twice
    assert len(row["elements"]) == 1


def test_map_codes_sharing_item_number_with_different_units_warn(tmp_path):
    # issue #106 addendum: downstream layers key on (schedule, item_number);
    # two codes sharing one under DIFFERENT measures/units collide there
    # (their reporter's 2 EA + 416.75 LBS -> 418.75 EA collapse). Same
    # measure+unit is a legitimate rollup and stays silent.
    path = _pile_two_codes_ifc(tmp_path / "pile.ifc")
    tmap = {"codes": {
        "PILE-200W-FRN": {"measure": "Length", "unit": "LF",
                          "item_number": "129"},
        "PILE-200W-DRV": {"measure": "Count", "unit": "EA",
                          "item_number": "129"}}}
    _takeoff, warnings = build_takeoff(str(path), tmap)
    assert any("share item_number 129" in w and "PILE-200W-DRV" in w
               and "PILE-200W-FRN" in w for w in warnings)

    rollup = {"codes": {
        "PILE-200W-FRN": {"measure": "Length", "unit": "LF",
                          "item_number": "129"},
        "PILE-200W-DRV": {"measure": "Length", "unit": "LF",
                          "item_number": "129"}}}
    _takeoff, warnings = build_takeoff(str(path), rollup)
    assert not any("share item_number" in w for w in warnings)


def test_declared_code_with_no_rows_warns(tmp_path):
    # a map code no element carries must be a loud review line, not silence
    path = _pile_two_codes_ifc(tmp_path / "pile.ifc")
    tmap = {"codes": {"PILE-200W-FRN": {"measure": "Length", "unit": "LF"},
                      "PILE-200W-DRV": {"measure": "Count", "unit": "EA"},
                      "GHOST-CODE": {"measure": "Count", "unit": "EA"}}}
    _takeoff, warnings = build_takeoff(str(path), tmap)
    assert any("GHOST-CODE" in w and "produced no rows" in w
               for w in warnings)


# ----------------------------------------------------------------------------
# Weight dimension (issue #108) + declared-unit Qto scaling (issue #109)
# ----------------------------------------------------------------------------
from bimforge.bim.ifc_takeoff import convert  # noqa: E402

KG_TO_LB = 2.20462262185


def _steel_gram_ifc(path):
    """A fabricated-steel plate whose GrossWeight rides an IfcQuantityWeight
    in the file's declared MASSUNIT — GRAM, the common case #108 flags —
    with the usual mm length units. 96 000 g = 96 kg."""
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.unit.assign_unit(f)   # mm defaults
    gram = f.create_entity("IfcSIUnit", UnitType="MASSUNIT", Name="GRAM")
    ua = f.by_type("IfcUnitAssignment")[0]
    ua.Units = tuple(ua.Units) + (gram,)
    plate = ifcopenshell.api.root.create_entity(
        f, ifc_class="IfcPlate", name="Saddle-1")
    qto = ifcopenshell.api.pset.add_qto(f, product=plate,
                                        name="Qto_PlateBaseQuantities")
    ifcopenshell.api.pset.edit_qto(f, qto=qto,
                                   properties={"GrossWeight": 96_000.0})
    system = ifcopenshell.api.classification.add_classification(
        f, classification="BidSchedule")
    ifcopenshell.api.classification.add_reference(
        f, products=[plate], identification="STL-FAB", name="Fabricated steel",
        classification=system)
    f.write(str(path))
    return path


def test_weight_measure_maps_to_pounds(tmp_path):
    # issue #108's regression shape: GrossWeight -> LBS row, honoring the
    # file's GRAM mass unit (96 000 g = 96 kg = 211.64 lb)
    path = _steel_gram_ifc(tmp_path / "steel.ifc")
    tmap = {"codes": {"STL-FAB": {"measure": "GrossWeight", "unit": "LBS"}}}
    takeoff, warnings = build_takeoff(str(path), tmap)
    (row,) = takeoff["rows"]
    assert row["unit"] == "LBS"
    assert row["quantity"] == pytest.approx(96.0 * KG_TO_LB, rel=1e-6)
    assert row["elements"][0]["value_si"] == pytest.approx(96.0)  # SI kg
    assert not warnings


def test_mass_conversions_cover_the_units_metal_is_paid_in():
    assert convert(1.0, "mass", "KG") == 1.0
    assert convert(1.0, "mass", "LB") == pytest.approx(KG_TO_LB)
    assert convert(45.359237, "mass", "CWT") == pytest.approx(1.0)
    assert convert(907.18474, "mass", "TON") == pytest.approx(1.0)  # US short


def test_plain_weight_is_a_mass_measure():
    # Qto_ReinforcingElementBaseQuantities names its quantity plain "Weight"
    # (the naming exception — plates/beams use GrossWeight/NetWeight); the
    # reinforcing route is unreachable without it
    from bimforge.bim.ifc_takeoff import MEASURE_DIM
    assert MEASURE_DIM["Weight"] == "mass"


def test_unknown_singular_measure_is_a_loud_error(tmp_path):
    # issue #108's second defect: the singular path crashed with a bare
    # KeyError (or silently fell back) where the measures: path had a real
    # error — both paths now validate up front
    path = _pile_two_codes_ifc(tmp_path / "pile.ifc")
    tmap = {"codes": {"PILE-200W-FRN": {"measure": "Bogus", "unit": "LF"}}}
    with pytest.raises(ValueError, match=r"unknown measure 'Bogus'"):
        build_takeoff(str(path), tmap)
