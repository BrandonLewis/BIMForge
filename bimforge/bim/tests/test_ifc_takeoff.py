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
    # ifcopenshell default: MILLIMETRE length, but SQUARE_METRE area and
    # CUBIC_METRE volume — the shape of a Revit metric export
    ifcopenshell.api.unit.assign_unit(f)
    slab = ifcopenshell.api.root.create_entity(f, ifc_class="IfcSlab",
                                               name="Deck-1")
    qto = ifcopenshell.api.pset.add_qto(f, product=slab,
                                        name="Qto_SlabBaseQuantities")
    # 44.59 in the declared AREAUNIT (m²); the millimetre length unit must
    # not be squared onto it (issue #109: scale by the DECLARED unit of
    # each dimension, never assume SI, never derive area from length)
    ifcopenshell.api.pset.edit_qto(f, qto=qto,
                                   properties={"GrossArea": 44.59})
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


def test_weight_is_an_alias_of_gross_weight_in_the_takeoff(tmp_path):
    # #363: emit_ifc writes GrossWeight; a map (or paycodes) saying plain
    # `Weight` must read it, on both the singular and the `measures:` path
    path = _steel_gram_ifc(tmp_path / "steel.ifc")
    for tmap in ({"codes": {"STL-FAB": {"measure": "Weight", "unit": "LBS"}}},
                 {"codes": {"STL-FAB": {"measures": [
                     {"measure": "Weight", "unit": "LBS"}]}}}):
        takeoff, warnings = build_takeoff(str(path), tmap)
        (row,) = takeoff["rows"]
        assert row["unit"] == "LBS"
        assert row["quantity"] == pytest.approx(96.0 * KG_TO_LB, rel=1e-6)
        assert row["elements"][0]["measure"] == "GrossWeight"
        assert not warnings


def test_unknown_singular_measure_is_a_loud_error(tmp_path):
    # issue #108's second defect: the singular path crashed with a bare
    # KeyError (or silently fell back) where the measures: path had a real
    # error — both paths now validate up front
    path = _pile_two_codes_ifc(tmp_path / "pile.ifc")
    tmap = {"codes": {"PILE-200W-FRN": {"measure": "Bogus", "unit": "LF"}}}
    with pytest.raises(ValueError, match=r"unknown measure 'Bogus'"):
        build_takeoff(str(path), tmap)


# ----------------------------------------------------------------------------
# Units per dimension: AREAUNIT / VOLUMEUNIT are read on their own, and a
# quantity's own Unit wins — never area = length², volume = length³.
# ----------------------------------------------------------------------------
import ifcopenshell.api.unit  # noqa: E402

VOLUME_MAP = {"codes": {"51": {"measure": "NetVolume", "unit": "CY",
                               "item_number": "10"}}}


def _footing_file(units=None, volume=10.0):
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    if units is None:
        ifcopenshell.api.unit.assign_unit(f)          # mm, m2, m3
    else:
        ifcopenshell.api.unit.assign_unit(f, units=units(f))
    ftg = ifcopenshell.api.root.create_entity(f, ifc_class="IfcFooting",
                                              name="F-1")
    qto = ifcopenshell.api.pset.add_qto(f, product=ftg,
                                        name="Qto_FootingBaseQuantities")
    ifcopenshell.api.pset.edit_qto(f, qto=qto,
                                   properties={"NetVolume": volume})
    system = ifcopenshell.api.classification.add_classification(
        f, classification="BidSchedule")
    ifcopenshell.api.classification.add_reference(
        f, products=[ftg], identification="51", name="Concrete",
        classification=system)
    return f, ftg


def _exact_unit(f, name, factor):
    u = ifcopenshell.api.unit.add_conversion_based_unit(f, name=name)
    u.ConversionFactor.ValueComponent = f.create_entity(
        u.ConversionFactor.ValueComponent.is_a(), factor)
    return u


def _takeoff_qty(f):
    from bimforge.bim.ifc_takeoff import _build_takeoff
    takeoff, _ = _build_takeoff(f, VOLUME_MAP)
    (row,) = takeoff["rows"]
    return row["quantity"]


def test_takeoff_reads_volume_in_the_declared_volume_unit():
    f, _ = _footing_file()                 # mm length, but m3 volume
    assert _takeoff_qty(f) == pytest.approx(13.0795, abs=1e-4)


def test_takeoff_feet_with_cubic_yards():
    f, _ = _footing_file(lambda f: [
        _exact_unit(f, "foot", 0.3048),
        _exact_unit(f, "cubic yard", 0.764554857984)], volume=1.0)
    assert _takeoff_qty(f) == pytest.approx(1.0, abs=1e-6)


def test_takeoff_honours_a_quantity_s_own_unit():
    f, ftg = _footing_file(volume=27.0)    # project volume unit: m3
    (q,) = [q for rel in ftg.IsDefinedBy
            for q in rel.RelatingPropertyDefinition.Quantities]
    q.Unit = _exact_unit(f, "cubic foot", 0.3048 ** 3)
    assert _takeoff_qty(f) == pytest.approx(1.0, abs=1e-6)


def _three_counted_ifc(path, code="MOB"):
    """Three proxies each carrying Count=1 under one code — a lump-sum
    item's contributing elements (#366)."""
    f = ifcopenshell.file(schema="IFC4")
    ifcopenshell.api.root.create_entity(f, ifc_class="IfcProject", name="p")
    ifcopenshell.api.unit.assign_unit(f)
    system = ifcopenshell.api.classification.add_classification(
        f, classification="BidSchedule")
    for i in range(3):
        el = ifcopenshell.api.root.create_entity(
            f, ifc_class="IfcBuildingElementProxy", name=f"Sign-{i + 1}")
        qto = ifcopenshell.api.pset.add_qto(f, product=el, name="Qto_BaseQuantities")
        ifcopenshell.api.pset.edit_qto(f, qto=qto, properties={"Count": 1})
        ifcopenshell.api.classification.add_reference(
            f, products=[el], identification=code, name=code, classification=system)
    f.write(str(path))
    return path


def test_count_row_paid_lump_sum_reports_one_and_keeps_its_elements(tmp_path):
    # #366: an LS item is 1 LS however many elements contribute to it; the
    # elements still list so the audit and the push see what backs it
    path = _three_counted_ifc(tmp_path / "ls.ifc")
    tmap = {"codes": {"MOB": {"measure": "Count", "unit": "LS"}}}
    takeoff, warnings = build_takeoff(str(path), tmap)
    (row,) = takeoff["rows"]
    assert row["unit"] == "LS"
    assert row["quantity"] == 1
    assert [e["name"] for e in row["elements"]] == ["Sign-1", "Sign-2", "Sign-3"]
    assert not warnings
    # the same elements still count 3 EA under an each-paid code
    tmap = {"codes": {"MOB": {"measure": "Count", "unit": "EA"}}}
    takeoff, _ = build_takeoff(str(path), tmap)
    assert takeoff["rows"][0]["quantity"] == 3


def test_count_as_overrides_the_count_of_any_count_code(tmp_path):
    path = _three_counted_ifc(tmp_path / "ca.ifc")
    # singular path: 3 elements but the item pays 2 EA (one is a spare)
    tmap = {"codes": {"MOB": {"measure": "Count", "unit": "EA", "count_as": 2}}}
    takeoff, warnings = build_takeoff(str(path), tmap)
    (row,) = takeoff["rows"]
    assert row["quantity"] == 2 and len(row["elements"]) == 3
    assert not warnings
    # an LS row may still be told a number other than 1
    tmap = {"codes": {"MOB": {"measure": "Count", "unit": "LS", "count_as": 0.5}}}
    takeoff, _ = build_takeoff(str(path), tmap)
    assert takeoff["rows"][0]["quantity"] == 0.5
    # the measures: (plural) path honours a per-entry count_as
    tmap = {"codes": {"MOB": {"measures": [
        {"measure": "Count", "unit": "EA", "count_as": 4},
        {"measure": "Count", "unit": "LS"}]}}}
    takeoff, _ = build_takeoff(str(path), tmap)
    assert [r["quantity"] for r in takeoff["rows"]] == [4, 1]


def test_count_as_must_be_a_number(tmp_path):
    from bimforge.bim.ifc_takeoff import normalize_map
    with pytest.raises(ValueError, match="count_as"):
        normalize_map({"codes": {"MOB": {"measure": "Count", "unit": "EA",
                                         "count_as": "two"}}})
    with pytest.raises(ValueError, match="count_as"):
        normalize_map({"codes": {"MOB": {"measures": [
            {"measure": "Count", "unit": "EA", "count_as": True}]}}})
