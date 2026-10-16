import pytest
from bimforge.author.box_section import (
    BoxCulvertSection, _parse_size_key, parse_bar_spec)
from bimforge.author.primitives import poly_area

# Real D80 single rows (8x5) + one double row; thicknesses are cover-dependent.
TABLE = {
    "single": {
        "8x5": {"covers": {
            10: {"wall_t_ft": 0.5833, "top_slab_ft": 0.7917,
                 "bot_slab_ft": 0.7083, "a": "#6@4.5", "b": "#6@5",
                 "e": "#4@9", "conc_cf_lf": 19.6, "lb_per_lf": 229},
            20: {"wall_t_ft": 0.7917, "top_slab_ft": 0.9583,
                 "bot_slab_ft": 1.0833, "a": "#6@5", "b": "#5@4.5",
                 "e": "#4@8", "conc_cf_lf": 27.5, "lb_per_lf": 210}}},
        "10x6": {"covers": {
            10: {"wall_t_ft": 0.7083, "top_slab_ft": 0.7917,
                 "bot_slab_ft": 0.8333, "a": "#6@4.5", "b": "#6@5",
                 "e": "#4@8.5", "conc_cf_lf": 27.1, "lb_per_lf": 285}}},
    },
    "double": {
        "8x5": {"covers": {
            10: {"wall_t_ft": 0.5833, "top_slab_ft": 0.7917,
                 "bot_slab_ft": 0.7083, "a": "#6@4.5", "b": "#6@5",
                 "e": "#4@9", "conc_cf_lf": 35.4, "lb_per_lf": 380}}},
    },
}


def test_lookup_exact_and_roundup():
    s = BoxCulvertSection(1, 8.0, 5.0, 10.0, TABLE)
    assert s.S_key == "8x5"
    assert s.cover_key == 10
    assert s.wall_t == pytest.approx(0.5833)
    assert s.lb_per_lf == 229
    s2 = BoxCulvertSection(1, 7.0, 4.0, 10.0, TABLE)   # rounds up to 8x5
    assert s2.S_key == "8x5"
    s3 = BoxCulvertSection(1, 8.0, 5.0, 20.0, TABLE)   # deeper cover row
    assert s3.cover_key == 20
    assert s3.lb_per_lf == 210


def test_cover_roundup_picks_next_deeper():
    s = BoxCulvertSection(1, 8.0, 5.0, 12.0, TABLE)    # 12 <= 20
    assert s.cover_key == 20


def test_out_of_range_raises():
    with pytest.raises(ValueError):
        BoxCulvertSection(1, 99.0, 99.0, 10.0, TABLE)


def test_over_cover_raises():
    with pytest.raises(ValueError):
        BoxCulvertSection(1, 8.0, 5.0, 40.0, TABLE)


def test_single_cell_profile_and_area():
    s = BoxCulvertSection(1, 8.0, 5.0, 10.0, TABLE)
    assert s.W_out == pytest.approx(8.0 + 2 * 0.5833)      # 9.1666
    assert s.H_out == pytest.approx(0.7083 + 5.0 + 0.7917)  # 6.5
    voids = s.cell_voids()
    assert len(voids) == 1
    assert poly_area(voids[0]) == pytest.approx(8.0 * 5.0)  # haunch 0 -> 40
    assert s.area_sf() == pytest.approx(s.conc_cf_lf, abs=0.1)  # ground truth


def test_double_cell_two_voids_and_area():
    s = BoxCulvertSection(2, 8.0, 5.0, 10.0, TABLE)
    assert s.W_out == pytest.approx(2 * 8.0 + 3 * 0.5833)   # 17.75
    assert len(s.cell_voids()) == 2
    assert s.area_sf() == pytest.approx(s.conc_cf_lf, abs=0.1)


def test_section_prism_degenerate_void_meshes():
    # A haunch-0 box cell void arrives as an 8-pt "octagon" whose chamfer edges
    # collapse to zero length (coincident vertices). `area_sf` tolerated this via
    # the shoelace sum, but `body_solids` -> `ear_clip` did not, crashing a real
    # DXF/IFC build with "self-intersecting profile?". Regression: the mesh path
    # must tolerate the same degenerate ring the area path already does.
    from bimforge.author.primitives import SectionPrism, face_volume
    prof = [(0.0, 0.0), (9.1666, 0.0), (9.1666, 6.5), (0.0, 6.5)]
    void_degen = [(0.5833, 0.7083), (8.5833, 0.7083), (8.5833, 0.7083),
                  (8.5833, 5.7083), (8.5833, 5.7083), (0.5833, 5.7083),
                  (0.5833, 5.7083), (0.5833, 0.7083)]
    sp = SectionPrism("degen", prof, 20.0, voids=[void_degen])
    mesh = sp.body_solids()[0]                      # must not raise
    faces = [[mesh["verts"][i] for i in tri] for tri in mesh["tris"]]
    assert face_volume(faces) == pytest.approx(sp.area_sf * 20.0, rel=1e-6)


def test_interior_wall_thins_multicell():
    base = {"wall_t_ft": 1.0, "top_slab_ft": 0.75, "bot_slab_ft": 0.75,
            "a": "#5@6", "b": "#5@6", "e": "#4@9", "conc_cf_lf": 0.0,
            "lb_per_lf": 1}
    uniform = {"double": {"8x5": {"covers": {10: dict(base)}}}}
    thin = {"double": {"8x5": {"covers": {10: {**base,
                                               "interior_wall_t_ft": 0.5}}}}}
    su = BoxCulvertSection(2, 8.0, 5.0, 10.0, uniform)
    st = BoxCulvertSection(2, 8.0, 5.0, 10.0, thin)
    assert su.W_out == pytest.approx(2 * 8.0 + 3 * 1.0)        # 19.0 uniform
    assert st.W_out == pytest.approx(2 * 8.0 + 2 * 1.0 + 0.5)  # 18.5 thin interior
    # a 0.5 ft thinner interior wall removes wall x full height of concrete
    assert st.area_sf() == pytest.approx(su.area_sf() - 0.5 * st.H_out)
    # single boxes have no interior wall, so the param is inert
    single = {"single": {"8x5": {"covers": {10: {**base,
                                                 "interior_wall_t_ft": 0.5}}}}}
    ss = BoxCulvertSection(1, 8.0, 5.0, 10.0, single)
    assert ss.W_out == pytest.approx(8.0 + 2 * 1.0)


def test_haunch_reduces_area():
    tbl = {"single": {"8x5": {"covers": {10: {
        "wall_t_ft": 0.5833, "top_slab_ft": 0.7917, "bot_slab_ft": 0.7083,
        "a": "#6@4.5", "b": "#6@5", "e": "#4@9", "conc_cf_lf": 19.6,
        "lb_per_lf": 229, "haunch_ft": 0.5}}}}}
    s = BoxCulvertSection(1, 8.0, 5.0, 10.0, tbl)
    # a 0.5 ft chamfer at each of 4 void corners adds 4*(0.5^2/2)=0.5 sf concrete
    assert s.area_sf() == pytest.approx(19.583 + 0.5, abs=1e-3)


#: Tolerance for the LB/LF schedule check against the tabulated figure.
#: NOT a round number picked for comfort — measured over all 168 rows of the
#: real D80/D81 catalog with the calibrated proxy: mean +0.1% (unbiased),
#: sd 12.2%, worst row 34.4%. 0.40 is ~3.3 sd, leaving modest headroom for
#: rows not yet transcribed while still catching the errors this check exists
#: to catch: a decimal slip (+900%) or a doubled figure (+100%). It CANNOT
#: catch a few-percent typo, and no tolerance could — see
#: `BoxCulvertSection.schedule_lb_per_lf` for why the residual is irreducible.
SCHEDULE_LB_TOL = 0.40


def test_parse_bar_spec():
    assert parse_bar_spec("#5@8") == (5, 8.0)
    assert parse_bar_spec("#4 @ 12") == (4, 12.0)


def test_schedule_lb_per_lf_is_near_tabulated():
    # one tolerance in this file, derived from the catalog (SCHEDULE_LB_TOL);
    # this hand-picked real D80 row lands at +1.6%, well inside it
    s = BoxCulvertSection(1, 8.0, 5.0, 10.0, TABLE)
    assert s.schedule_lb_per_lf() == pytest.approx(
        s.lb_per_lf, rel=SCHEDULE_LB_TOL)


def _bc_yaml(p):
    import yaml
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def _bc_check_group(group):
    for key, row in group.items():
        _parse_size_key(key)                                  # "SxH" parses
        assert "covers" in row, key
        for cov, sched in row["covers"].items():
            assert {"wall_t_ft", "top_slab_ft", "bot_slab_ft", "a", "b", "e",
                    "conc_cf_lf", "lb_per_lf"} <= set(sched), (key, cov)
            assert sched["lb_per_lf"] > 0, (key, cov)
            assert sched["conc_cf_lf"] > 0, (key, cov)
            for mark in ("a", "b", "e"):
                parse_bar_spec(sched[mark])                    # bar spec parses


def test_box_culvert_example_fixture_schema():
    from pathlib import Path
    t = _bc_yaml(Path(__file__).resolve().parents[1]
                 / "examples" / "caltrans-box-culvert-tables.example.yaml")
    for g in ("single", "double"):
        _bc_check_group(t[g])
        # the example rows are self-consistent: modeled area == tabulated CF/LF
        cells = 1 if g == "single" else 2
        for key, row in t[g].items():
            s, h = _parse_size_key(key)
            for cov in row["covers"]:
                sec = BoxCulvertSection(cells, s, h, float(cov), t)
                assert sec.area_sf() == pytest.approx(sec.conc_cf_lf, abs=0.1)


def _production_catalog():
    """The real D80/D81 catalog, or None when it is not available locally."""
    from bimforge.author.tests._tables import caltrans_table
    cat = caltrans_table("caltrans-d80-box-culvert.yaml")
    return _bc_yaml(cat) if cat is not None else None


@pytest.fixture
def production_catalog():
    t = _production_catalog()
    if t is None:
        pytest.skip("git-ignored box-culvert catalog not present")
    return t


def test_box_culvert_production_catalog_if_present():
    """Validate the real git-ignored D80/D81 catalog when present locally.

    Ground truth: the modeled concrete section area == the sheet's tabulated
    CONCRETE CF/LF for every span x height x cover. Plus the LB/LF schedule
    check (B3's W==C+B transcription-check analog), whose tolerance is
    derived in `SCHEDULE_LB_TOL`."""
    t = _production_catalog()
    if t is None:
        pytest.skip("git-ignored box-culvert catalog not present")
    # single boxes are geometry-exact; double boxes carry a modeled minimum
    # interior wall so area reproduces the tabulated concrete to ~1.3 sf (the
    # residual = minor corner fillets / invert slope the section omits).
    for cells, g, area_tol in ((1, "single", 0.15), (2, "double", 1.5)):
        if g not in t:
            continue
        _bc_check_group(t[g])
        for key, row in t[g].items():
            s, h = _parse_size_key(key)
            for cov in row["covers"]:
                sec = BoxCulvertSection(cells, s, h, float(cov), t)
                assert sec.area_sf() == pytest.approx(
                    sec.conc_cf_lf, abs=area_tol), (cells, key, cov)
                assert sec.schedule_lb_per_lf() == pytest.approx(
                    sec.lb_per_lf, rel=SCHEDULE_LB_TOL), (cells, key, cov)


def test_schedule_lb_per_lf_is_unbiased_across_the_production_catalog(
        production_catalog):
    """A tolerance is only meaningful if the model underneath is CENTRED.

    Issue #150: the old proxy measured the transverse bar path as the CELL
    perimeter x cells, which runs a double box ~22% light — a double box's
    outer perimeter is far more than twice one cell's. A band wide enough to
    swallow a systematic bias is not a check, so pin the BIAS, not only the
    spread. Measured over all 168 catalog rows: mean +0.1%, sd 12.2%.
    """
    import statistics
    t = production_catalog
    per_group = {}
    for cells, g in ((1, "single"), (2, "double")):
        if g not in t:
            continue
        errs = []
        for key, row in t[g].items():
            s, h = _parse_size_key(key)
            for cov in row["covers"]:
                sec = BoxCulvertSection(cells, s, h, float(cov), t)
                errs.append((sec.schedule_lb_per_lf() - sec.lb_per_lf)
                            / sec.lb_per_lf)
        per_group[g] = errs
    every = [e for errs in per_group.values() for e in errs]
    assert len(every) >= 100, f"catalog looks truncated: {len(every)} rows"
    assert abs(statistics.mean(every)) < 0.05, (
        f"model is biased overall: mean {statistics.mean(every):+.1%}")
    for g, errs in per_group.items():
        assert abs(statistics.mean(errs)) < 0.10, (
            f"{g} boxes are biased: mean {statistics.mean(errs):+.1%}")
