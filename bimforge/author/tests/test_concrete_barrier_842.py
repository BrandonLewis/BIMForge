import pytest

from bimforge.author.families import concrete_barrier_842 as fam
from bimforge.author.families.registry import available
from bimforge.author.project import ProjectContext


def _ctx():
    return ProjectContext.from_spec({
        "name": "t", "epsg": 2226, "base": [0.0, 0.0],
        "guid_ns": "6f0e5a1a-0000-4000-8000-000000000042"})


def _els(model, token):
    return [e for e in model.elements if token in e.name]


def test_registered_in_family_registry():
    assert available()["concrete-barrier-842"] is fam.build


def test_requires_runs():
    with pytest.raises(ValueError, match="runs"):
        fam.build({}, _ctx())


def test_running_prism_and_rebar_emitted():
    m = fam.build({"runs": [{"name": "NB", "straight_length_ft": 100.0,
                             "start_end": "none", "end_end": "none"}]}, _ctx())
    barr = _els(m, "842 barrier")
    assert len(barr) == 1 and barr[0].ifc_class == "IfcWall"
    assert barr[0].quantities["length_ft"] == pytest.approx(100.0)
    assert _els(m, "842 reinforcing")


def test_lf_does_not_regress_when_end_blocks_shorten_the_prism():
    # the R29 lesson: end blocks shorten the running prism, but total barrier
    # LF (running + both blocks) must still equal the full run length.
    m = fam.build({"runs": [{"name": "NB", "straight_length_ft": 100.0,
                             "start_end": "approach", "end_end": "departure"}]},
                  _ctx())
    lf = sum(e.quantities.get("length_ft", 0.0)
             for e in m.elements if "842 barrier" in e.name)
    assert lf == pytest.approx(100.0)
    assert len(_els(m, "end block")) == 2


def test_default_end_blocks_on():
    # start_end/end_end omitted -> approach at start, departure at end
    m = fam.build({"runs": [{"name": "NB", "straight_length_ft": 100.0}]},
                  _ctx())
    assert _els(m, "end block (approach)")
    assert _els(m, "end block (departure)")
    assert _els(m, "842 transition HSS")            # hardware present by default


def test_transition_hss_billed_at_block_length():
    # HSS tubes are block-mounted hardware on the 3'-6" end block, not the
    # full 9'-10" end treatment -- length_ft must be 3.5, never 9.833.
    m = fam.build({"runs": [{"name": "NB", "straight_length_ft": 100.0}]},
                  _ctx())
    hss = _els(m, "842 transition HSS")
    assert hss
    for e in hss:
        assert e.quantities["length_ft"] == pytest.approx(3.5)


def test_base_kind_selects_variant():
    m = fam.build({"runs": [{"name": "NB", "straight_length_ft": 100.0,
                             "base_kind": "trench", "start_end": "none",
                             "end_end": "none"}]}, _ctx())
    barr = _els(m, "842 barrier")[0]
    # trench adds a footing -> more concrete per LF than deck (4.3385 sf)
    assert barr.quantities["volume_cf"] / barr.quantities["length_ft"] > 4.3385


def test_trench_min_length_guard():
    # message names both the 40' minimum AND the offending length (30) so a
    # failure across multiple runs stays diagnosable.
    with pytest.raises(ValueError, match=r"minimum length is 40.*got 30"):
        fam.build({"runs": [{"name": "NB", "straight_length_ft": 30.0,
                             "base_kind": "trench"}]}, _ctx())


def test_too_short_for_end_blocks_fails_loud():
    with pytest.raises(ValueError, match="too short"):
        fam.build({"runs": [{"name": "NB", "straight_length_ft": 20.0,
                             "start_end": "approach", "end_end": "departure"}]},
                  _ctx())


def test_bad_end_value_fails_loud():
    # message wording comes from the shared build_barrier validator now
    # ("{start,end} end ... must be one of"), not the family's own text.
    with pytest.raises(ValueError, match="must be one of"):
        fam.build({"runs": [{"name": "NB", "straight_length_ft": 100.0,
                             "start_end": "wing"}]}, _ctx())


def test_mod_item_stem_height_override_changes_concrete():
    base = fam.build({"runs": [{"name": "M", "straight_length_ft": 100.0,
                     "start_end": "none", "end_end": "none"}]}, _ctx())
    mod = fam.build({"runs": [{"name": "M", "straight_length_ft": 100.0,
                    "start_end": "none", "end_end": "none",
                    "stem_h_ft": 4.0}]}, _ctx())
    def cf(m):
        return next(e.quantities["volume_cf"] for e in m.elements
                   if "842 barrier" in e.name)
    assert cf(mod) > cf(base)


def test_mod_item_stem_height_override_reaches_end_block():
    # the Mod dim must also flow into the end-block loft (run -> endblock_solid),
    # not only the running prism.
    def eb_cf(m):
        return next(e.quantities["volume_cf"] for e in m.elements
                   if "end block (approach) [start]" in e.name)
    base = fam.build({"runs": [{"name": "M", "straight_length_ft": 100.0,
                     "start_end": "approach", "end_end": "none"}]}, _ctx())
    mod = fam.build({"runs": [{"name": "M", "straight_length_ft": 100.0,
                    "start_end": "approach", "end_end": "none",
                    "stem_h_ft": 4.0}]}, _ctx())
    assert eb_cf(mod) > eb_cf(base)


def test_same_kind_at_both_ends_does_not_collide():
    # a two-way run may legitimately carry the same end treatment at both ends;
    # end blocks are identified by POSITION, so this must not raise the cryptic
    # "duplicate element name" -- every emitted name (solid, rebar, hardware)
    # stays distinct per end.
    m = fam.build({"runs": [{"name": "NB", "straight_length_ft": 100.0,
                             "start_end": "approach", "end_end": "approach"}]},
                  _ctx())
    blocks = _els(m, "end block")
    assert len(blocks) == 2
    assert len({e.name for e in blocks}) == 2                 # distinct solids
    hss = _els(m, "842 transition HSS")
    assert hss and len({e.name for e in hss}) == len(hss)     # no dup hardware
    reo = _els(m, "endblock-ap")
    assert reo and len({e.name for e in reo}) == len(reo)     # no dup rebar


def test_example_builds_clean(tmp_path):
    """The shipped worked example through the real `est-bim build` pipeline:
    copy both yaml files into a tmp dir (so `load_spec` resolves the relative
    paycodes/outputs from there) and assert rc 0 + the IFC exists."""
    pytest.importorskip("ifcopenshell")
    import shutil
    from pathlib import Path

    from bimforge.author.families.registry import build_from_spec

    ex = Path(__file__).resolve().parents[1] / "examples"
    work = tmp_path / "ex"
    work.mkdir()
    for f in ("concrete-barrier-842.spec.yaml",
              "concrete-barrier-842.paycodes.yaml"):
        shutil.copy(ex / f, work / f)
    (work / "CAD").mkdir()
    rc = build_from_spec(str(work / "concrete-barrier-842.spec.yaml"))
    assert rc == 0
    assert (work / "CAD" / "barrier-842.ifc").exists()


def test_curved_run_with_end_blocks_sums_lf_to_path_length():
    import math
    run = {"name": "NB",
           "path": [{"kind": "straight", "length": 20.0},
                    {"kind": "arc", "radius": 300.0, "delta": 25.0, "turn": "R"},
                    {"kind": "straight", "length": 20.0}],
           "start_end": "approach", "end_end": "departure"}
    m = fam.build({"runs": [run]}, _ctx())
    total = 20.0 + 300.0 * math.radians(25.0) + 20.0
    lf = sum(e.quantities.get("length_ft", 0.0)
             for e in m.elements if "842 barrier" in e.name)
    assert lf == pytest.approx(total)
    assert len(_els(m, "end block")) == 2


def test_curved_end_block_on_an_arc_terminal_builds():
    # terminal segment is an ARC (departure block sits on the curve)
    run = {"name": "NB",
           "path": [{"kind": "straight", "length": 20.0},
                    {"kind": "arc", "radius": 120.0, "delta": 30.0, "turn": "L"}],
           "start_end": "approach", "end_end": "departure"}
    m = fam.build({"runs": [run]}, _ctx())
    blocks = _els(m, "end block")
    assert len(blocks) == 2
    assert all(e.quantities["volume_cf"] > 0.0 for e in blocks)


def test_curved_trench_run_builds_and_enforces_the_40ft_floor():
    import math
    # a curved base_kind="trench" run must NOT KeyError on the missing
    # straight_length_ft; it builds when the arc length clears the B11-82
    # Note-8 40 ft floor.
    long_run = {"name": "NB", "base_kind": "trench",
                "path": [{"kind": "straight", "length": 20.0},
                         {"kind": "arc", "radius": 300.0, "delta": 25.0,
                          "turn": "R"}, {"kind": "straight", "length": 20.0}],
                "start_end": "none", "end_end": "none"}
    m = fam.build({"runs": [long_run]}, _ctx())          # must not raise
    assert any("842 barrier" in e.name for e in m.elements)


def test_curved_trench_run_too_short_is_rejected_with_note8():
    # a curved trench arc under 40 ft trips the SAME Note-8 message the
    # straight path uses.
    short = {"name": "NB", "base_kind": "trench",
             "path": [{"kind": "arc", "radius": 20.0, "delta": 60.0,
                       "turn": "R"}],           # 20*rad(60) ~ 20.9 ft < 40
             "start_end": "none", "end_end": "none"}
    with pytest.raises(ValueError, match="40"):
        fam.build({"runs": [short]}, _ctx())


def test_wall_and_trench_variants_build_clean(tmp_path):
    """Drive the wall (5-gon) and trench (6-gon) fan=True end-block lofts
    through emit_ifc's OCCT B-rep path -- the deck variant alone is covered by
    test_example_builds_clean, but loft_faces warns a 4-fan can flip OCCT's
    shell orientation, so exercise the non-deck fans end-to-end here."""
    pytest.importorskip("ifcopenshell")
    import shutil
    from pathlib import Path

    from bimforge.author.families.registry import build_from_spec

    ex = Path(__file__).resolve().parents[1] / "examples"
    work = tmp_path / "wt"
    work.mkdir()
    shutil.copy(ex / "concrete-barrier-842.paycodes.yaml",
                work / "concrete-barrier-842.paycodes.yaml")
    (work / "CAD").mkdir()
    spec = work / "wall-trench-842.spec.yaml"
    spec.write_text(
        "family: concrete-barrier-842\n"
        "params:\n"
        "  runs:\n"
        "    - name: WALL\n"
        "      straight_length_ft: 100.0\n"
        "      base_kind: wall\n"
        "      start_end: approach\n"
        "      end_end: departure\n"
        "    - name: TRENCH\n"
        "      straight_length_ft: 60.0\n"
        "      base_kind: trench\n"
        "      start_end: approach\n"
        "      end_end: departure\n"
        "paycodes: ./concrete-barrier-842.paycodes.yaml\n"
        "outputs:\n"
        "  dxf: CAD/wall-trench-842.dxf\n"
        "  ifc: CAD/wall-trench-842.ifc\n"
        "  takeoff_map: CAD/wall-trench-842-takeoff-map.yaml\n"
        "  qto: null\n"
        "  step: null\n"
        "  bbs: null\n"
        "  ifc_allow_local: true\n"
        "project:\n"
        "  name: \"R31 842 wall+trench\"\n"
        "  epsg: 2226\n"
        "  base: [0.0, 0.0]\n"
        "  guid_ns: \"6f0e5a1a-0000-4000-8000-000000000842\"\n")
    rc = build_from_spec(str(spec))
    assert rc == 0
    assert (work / "CAD" / "wall-trench-842.ifc").exists()


def _closed_manifold(solid):
    """Every edge of the emitted mesh is shared by exactly two triangles."""
    from collections import Counter
    edges = Counter()
    for sd in solid.body_solids():
        for t in sd["tris"]:
            for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
                edges[tuple(sorted((a, b)))] += 1
    return all(n == 2 for n in edges.values())


def test_stepped_deck_section_builds_closed_positive_solids():
    # #307: the 6-vertex (non-convex) deck ring must still emit closed,
    # positive-volume running prism + end blocks, and keep the LF contract.
    m = fam.build({"runs": [{"name": "S", "straight_length_ft": 120.0,
                             "start_end": "approach", "end_end": "departure"}]},
                  _ctx())
    conc = [e for e in m.elements if e.ifc_class == "IfcWall"]
    assert len(conc) == 3
    for e in conc:
        assert e.quantities["volume_cf"] > 0.0
        assert _closed_manifold(e.geometry)
    assert sum(e.quantities["length_ft"] for e in conc) == pytest.approx(120.0)
    run = next(e for e in conc if e.name == "S 842 barrier")
    assert run.quantities["volume_cf"] / run.quantities["length_ft"] ==         pytest.approx(4.338541666666667)
