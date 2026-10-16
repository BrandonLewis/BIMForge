"""spillway family: spillway-pilot fixture volumes vs qc-spillways.md, the block-row
end-width solve + closure refusal, mesh self-consistency, principal symmetry,
sloped-concrete termination, and the est-bim build --check-only smoke.

Fixture data is the spillway pilot's CAD/spillways.yaml, vector-extracted
off the structural sheets of a public flood-control plan set (principal
spillway sheets 69-74, auxiliary spillway sheets 75-78). Expected
quantities come from the same pilot's qc-spillways.md. Fixture literals
belong HERE, in the test — the family carries none of them.
"""
import copy
import uuid

import pytest

from bimforge.author.families import registry
from bimforge.author.families.spillway import build, solve_block_row
from bimforge.author.gate import run_pre
from bimforge.author.primitives import face_volume
from bimforge.author.project import ProjectContext

# The base MUST match the neighbourhood of the placement origins below
# (State Plane zone 3 ftUS). The family already localizes through
# `ctx.local`, so a zero base here would have it faithfully emit geometry
# 6.5 MILLION feet from the model origin — the #156 defect, arrived at from
# the spec side rather than the family side. `check_local_coordinates` now
# catches exactly that, and caught this fixture.
CTX = ProjectContext(name="spillway-pilot-fixture", guid_ns=uuid.UUID(int=21),
                     base_e=6_592_000.0, base_n=1_943_000.0)

EL0 = 100.0                       # datum: local z = elevation - 100.0

# spillways.yaml `common:` — 20-S-3004 / 30-S-3002 wall family.
COMMON = {
    "wall_top_thickness_ft": 1.0,             # 1'-0" TYP at top of wall
    "wall_batter_run_over_rise": 1.0 / 12.0,  # 1:12 on the outer face
    "wall_freeboard_ft": 3.5,                 # 3'-6" TYP above finished grade
    "cutoff_wall_thickness_ft": 1.5,          # 1'-6" TYP
}

# spillways.yaml `principal:` — sheets 69-74. Placement: local origin at
# State Plane E 6,592,369.561 / N 1,943,852.795, +X bearing 270 deg (west),
# +Y downstream (south) — qc-spillways.md "Principal spillway" section.
PRINCIPAL = {
    "placement": {
        "origin": [6592369.561, 1943852.795],
        "y_dir": [0.0, -1.0],                 # +Y downstream = due south
        "el0": EL0,
    },
    "slab": {
        "top_el": 194.0,                      # "TOP OF SLAB EL 194.0 (LEVEL)"
        "thickness_ft": 2.0,                  # 2'-0", 20-S-3004 sec A/B/C
        "half_outline": [                     # +x half, mirrored about x=0
            [25.533, 0.000], [31.190, 5.657], [22.157, 14.689],
            [16.176, 25.048], [12.498, 38.775], [12.498, 80.110],
            [38.494, 80.110], [38.494, 93.108], [0.000, 93.108],
        ],
        "cutoffs": [                          # 1'-6" x 6'-0" below top of slab
            {"edge": "inlet", "depth_ft": 6.0},
            {"edge": "outlet", "depth_ft": 6.0},
        ],
    },
    "chute_wall": {
        "half_lol": [                         # inner (vertical) face, +x half
            [27.654, 2.122], [18.156, 11.620], [11.518, 23.118],
            [7.499, 38.118], [7.499, 89.108],
        ],
        "top_profile": [                      # local y -> top of wall EL
            [2.122, 206.50], [38.122, 218.50], [52.372, 218.79],
            [73.372, 211.50], [90.108, 211.50],
        ],
    },
    "wing_wall": {                            # 90-deg return at the outlet
        "lol_y_ft": 89.108,
        "to_x_ft": 38.494,                    # 31'-0" from the chute wall LOL
        # yaml also records from_x_ft 8.499 (outer face of the chute wall);
        # the reference builder runs the wing wall from the chute-wall LOL
        # (half_lol[-1][0] = 7.499) and the family does the same.
        "top_profile": [                      # local |x| -> top of wall EL
            [8.499, 211.50], [18.499, 211.50], [38.494, 206.50],
        ],
    },
    "sloped_concrete": {
        "slope_h_to_v": 2.0,                  # "2:1 SLOPED CONCRETE, TYP"
        "floor_half_width_ft": 7.5,           # 15'-0" chute floor
        "ends_at_local_y_ft": 38.118,         # "SLOPE TRANSITIONS", 20-S-2001
    },
}

# spillways.yaml `auxiliary:` — sheets 75-78. Placement: local origin at
# State Plane E 6,592,682.565 / N 1,943,824.261, +X bearing 180 deg
# (downstream = south), +Y along the crest (east) — qc-spillways.md.
AUXILIARY = {
    "placement": {
        "origin": [6592682.565, 1943824.261],
        "y_dir": [1.0, 0.0],                  # +Y up-station on "A" = east
        "el0": EL0,
    },
    "clear_width_ft": 350.0,                  # "350'-0\" BETWEEN WALL LOL'S"
    "slab": {                                 # 1'-6" chute slab + cutoff keys
        "profile_t_el": [
            [0.000, 203.000], [24.247, 203.000], [24.247, 197.503],
            [22.747, 197.503], [22.747, 201.501], [1.501, 201.501],
            [1.501, 197.001], [0.000, 197.001],
        ],
    },
    "ogee": {                                 # 30-S-3003 coordinate table
        "toe_el": 203.000,
        "coordinates": [
            [0.000, -7.084, 203.000], [0.000, 0.000, 210.084],
            [0.083, 0.099, 210.183], [0.167, 0.154, 210.239],
            [0.233, 0.180, 210.265], [0.250, 0.185, 210.269],
            [0.333, 0.203, 210.287], [0.417, 0.213, 210.298],
            [0.483, 0.216, 210.300], [0.583, 0.212, 210.296],
            [0.667, 0.204, 210.288], [0.750, 0.190, 210.274],
            [0.852, 0.167, 210.251], [1.000, 0.121, 210.206],
            [1.167, 0.057, 210.141], [1.333, -0.022, 210.062],
            [1.474, -0.103, 209.981], [1.750, -0.286, 209.798],
            [2.000, -0.477, 209.607], [2.333, -0.776, 209.308],
            [2.574, -1.032, 209.052], [7.428, -7.084, 203.000],
        ],
        "eps_void_t_el": [                    # ASTM C578 void former
            [1.501, 203.000], [1.501, 207.000], [2.293, 207.000],
            [2.293, 206.000], [3.096, 206.000], [3.096, 205.000],
            [3.899, 205.000], [3.899, 204.001], [4.703, 204.001],
            [4.703, 203.000],
        ],
    },
    "chute_blocks": {                         # 10 3/4" TYP block and gap
        "width_in": 10.75,
        "gap_in": 10.75,
        "end_in": 9.125,                      # printed "9 1/8\" +/- ENDS"
        "profile_t_el": [
            [6.705, 203.901], [8.588, 203.901], [8.588, 203.000],
            [7.428, 203.000],
        ],
    },
    "dentated_sill": {                        # 8 3/8" TYP sill and gap
        "width_in": 8.375,
        "gap_in": 8.375,
        "end_in": 10.5,                       # printed "10 1/2\" +/- ENDS"
        "profile_t_el": [
            [21.997, 203.000], [21.997, 203.901], [22.417, 203.901],
            [24.247, 203.000],
        ],
    },
    "retaining_wall": {                       # 30-S-3001 / 30-S-3002
        "from_t_ft": -28.500,                 # 88'-2" overall
        "to_t_ft": 59.667,
        "base_el": 201.0,                     # "TOP OF FOOTING EL 201.0"
        "footing_width_ft": 13.0,
        "footing_offset_ft": 3.0,
        "footing_thickness_ft": 2.0,
        "cutoff_depth_ft": 6.0,
        "top_profile": [
            [-28.500, 206.50], [9.583, 218.50], [21.583, 218.74],
            [59.667, 206.50],
        ],
    },
}

PARAMS = {"common": COMMON, "principal": PRINCIPAL, "auxiliary": AUXILIARY}

# qc-spillways.md per-element concrete tables (element -> CY), verbatim.
QC_CY = {
    "principal spillway slab": 268.7,
    "principal spillway inlet cutoff wall": 11.3,
    "principal spillway outlet cutoff wall": 17.1,
    "principal spillway chute wall (west)": 124.4,
    "principal spillway chute wall (east)": 124.4,
    "principal spillway outlet wing wall (west)": 30.4,
    "principal spillway outlet wing wall (east)": 30.4,
    "principal spillway sloped concrete (west)": 35.6,
    "principal spillway sloped concrete (east)": 35.6,
    "auxiliary spillway chute slab": 636.5,
    "auxiliary spillway ogee weir": 318.1,
    "auxiliary spillway chute blocks": 8.9,
    "auxiliary spillway dentated sills": 7.8,
    "auxiliary spillway west retaining wall": 63.3,
    "auxiliary spillway west wall footing": 104.5,
    "auxiliary spillway east retaining wall": 63.3,
    "auxiliary spillway east wall footing": 104.5,
}


@pytest.fixture(scope="module")
def model():
    return build(copy.deepcopy(PARAMS), CTX)


def test_registered():
    assert "spillway" in registry.available()


def test_xf_solid_shifts_bottom_z_with_the_other_z_keys():
    """The placement transform must move a per-vertex `bottom_z` by the same
    z-shift it applies to z_bot/z_top/top_z; otherwise a bottom-tapered Prism
    placed by this family is emitted with its floor stuck in the local frame,
    at the wrong elevation."""
    from bimforge.author.families.spillway import _xf_solid
    d = {"kind": "prism", "units": "ft",
         "base": [(0, 0), (10, 0), (10, 2), (0, 2)],
         "holes": [], "z_bot": 0.0, "z_top": 4.0, "top_z": None,
         "bottom_z": [0.0, 2.0, 2.0, 0.0]}
    out = _xf_solid(d, world=lambda x, y: (x, y), zs=5.0)
    assert out["z_bot"] == 5.0
    assert out["z_top"] == 9.0
    assert out["bottom_z"] == [5.0, 7.0, 7.0, 5.0]


def test_missing_params():
    with pytest.raises(ValueError, match="missing"):
        build({"principal": copy.deepcopy(PRINCIPAL)}, CTX)
    with pytest.raises(ValueError, match="principal"):
        build({"common": dict(COMMON)}, CTX)


# --------------------------------------------------- auxiliary block solve
def test_block_and_sill_end_width_solve(model):
    # qc-spillways.md "Auxiliary block counts": fitting the typ width/gap
    # into the 350'-0" clear width forces n and the end pieces to:
    #   chute blocks    n=196, end 9.13"  (sheet prints 9 1/8" +/- ENDS)
    #   dentated sills  n=251, end 10.44" (sheet prints 10 1/2" +/- ENDS)
    n, end_in = solve_block_row(350.0, 10.75, 10.75)
    assert n == 196
    assert end_in == pytest.approx(9.13, abs=0.01)
    n, end_in = solve_block_row(350.0, 8.375, 8.375)
    assert n == 251
    assert end_in == pytest.approx(10.44, abs=0.01)
    assert model.element(
        "auxiliary spillway chute blocks").quantities["count"] == 196
    assert model.element(
        "auxiliary spillway dentated sills").quantities["count"] == 251


def test_block_closure_check_refuses_to_build():
    # Perturb the chute-block gap: with the sheet's 9 1/8" end pieces held,
    # an 11" gap leaves the row 0.44 ft off the 350' clear width — the
    # family must refuse to build and name the spacing.
    p = copy.deepcopy(PARAMS)
    p["auxiliary"]["chute_blocks"]["gap_in"] = 11.0
    with pytest.raises(ValueError, match=r'spacing') as exc:
        build(p, CTX)
    assert "10.75" in str(exc.value) and "11" in str(exc.value)


# ------------------------------------------------------------- QC volumes
def test_volumes_match_qc(model):
    got = {e.name: e.quantities["volume_cf"] / 27.0 for e in model.elements}
    assert set(got) == set(QC_CY)
    for name, want_cy in QC_CY.items():
        assert got[name] == pytest.approx(want_cy, rel=5e-3), name
    # qc-spillways.md totals: principal 678.1 CY, auxiliary 1,306.9 CY
    principal = sum(v for n, v in got.items() if n.startswith("principal"))
    auxiliary = sum(v for n, v in got.items() if n.startswith("auxiliary"))
    assert principal == pytest.approx(678.1, rel=1e-3)
    assert auxiliary == pytest.approx(1306.9, rel=1e-3)


def test_ogee_description_reports_the_void():
    p = copy.deepcopy(PARAMS)
    del p["principal"]
    m = build(p, CTX)
    desc = m.element("auxiliary spillway ogee weir").description or ""
    assert "polystyrene" in desc
    assert "7.99 sf" in desc          # shoelace area of the eps ring


# --------------------------------------------------- model self-consistency
def test_mesh_geometry_closes_to_declared_volume(model):
    """The QC doc's invariant by construction: for every element emitted as
    a mesh, the tessellated solid's volume IS the declared volume_cf."""
    checked = 0
    for el in model.elements:
        geoms = el.geometry if isinstance(el.geometry, list) else [el.geometry]
        if not all(isinstance(d, dict) and d.get("kind") == "mesh"
                   for d in geoms):
            continue
        got = 0.0
        for d in geoms:
            tris = [[d["verts"][i] for i in t] for t in d["tris"]]
            got += face_volume(tris)
        assert got == pytest.approx(el.quantities["volume_cf"],
                                    rel=1e-6), el.name
        checked += 1
    # chute walls x2, wing walls x2, chute slab, ogee, blocks, sills, walls x2
    assert checked >= 8


# ---------------------------------------------------------------- principal
def test_principal_symmetry(model):
    for pair in (("principal spillway chute wall (west)",
                  "principal spillway chute wall (east)"),
                 ("principal spillway outlet wing wall (west)",
                  "principal spillway outlet wing wall (east)"),
                 ("principal spillway sloped concrete (west)",
                  "principal spillway sloped concrete (east)")):
        a, b = (model.element(n).quantities["volume_cf"] for n in pair)
        assert a == pytest.approx(b, rel=1e-9), pair


def test_model_z_is_elevation_minus_project_base_h():
    """Copilot PR-126 catch: `el0` is only the params' transcription datum —
    emitted model z must land in the kernel convention z = elevation - base_h
    (ProjectContext.local), whatever el0 the spec was written against.
    Before the fix, geometry sat at elevation - el0: a silent vertical offset
    of (el0 - base_h) ft in every IFC/DXF/KML consumer."""
    # same HORIZONTAL base as CTX: this test isolates base_h, so the two
    # models must differ in nothing else (they are compared vertex-by-vertex)
    ctx = ProjectContext(name="datum-check", guid_ns=uuid.UUID(int=22),
                         base_e=6_592_000.0, base_n=1_943_000.0,
                         base_h=150.0)
    m = build({"common": COMMON, "principal": PRINCIPAL}, ctx)
    slab = next(d for d in m.element("principal spillway slab").geometry
                if d["kind"] == "prism")
    assert slab["z_top"] == pytest.approx(194.0 - 150.0)   # TOP OF SLAB EL
    assert slab["z_bot"] == pytest.approx(192.0 - 150.0)
    # mesh solids shift identically: same model at base_h=0 differs by
    # exactly -150 ft in z, and x/y are untouched
    m0 = build({"common": COMMON, "principal": PRINCIPAL}, CTX)
    w150 = m.element("principal spillway chute wall (west)").geometry[0]
    w0 = m0.element("principal spillway chute wall (west)").geometry[0]
    for (x1, y1, z1), (x0, y0, z0) in zip(w150["verts"], w0["verts"]):
        assert (x1, y1) == (x0, y0)
        assert z1 == pytest.approx(z0 - 150.0)


def test_compass_hands_land_on_their_own_side(model):
    """Mirrored pairs are volumetrically identical, so a mislabelled or
    sign-flipped hand passes every volume test — pin one pair's actual
    eastings (the fixture's +X bearing is 270 deg: local +x IS west)."""
    def mean_e(name):
        el = model.element(name)
        geoms = el.geometry if isinstance(el.geometry, list) else [el.geometry]
        xs = [v[0] for d in geoms for v in d["verts"]]
        return sum(xs) / len(xs)
    west = mean_e("principal spillway chute wall (west)")
    east = mean_e("principal spillway chute wall (east)")
    assert west < east - 1.0, (west, east)


def test_sloped_concrete_plan_terminates_at_configured_end():
    """The l.407-410 lesson: carrying the plan down the parallel throat adds
    a zero-width needle a solid modeller quietly repairs away, taking real
    volume with it — the ring must TERMINATE at ends_at_local_y_ft."""
    p = copy.deepcopy(PARAMS)
    del p["auxiliary"]
    # origin AT the project base, so ctx.local maps it to (0, 0) and the
    # frame really is the identity this test needs (a literal [0, 0] origin
    # would now localize to -base_e/-base_n)
    p["principal"]["placement"] = {"origin": [CTX.base_e, CTX.base_n],
                                   "y_dir": [0.0, 1.0], "el0": EL0}
    m = build(p, CTX)                 # identity frame: plan y IS local y
    end_y = PRINCIPAL["sloped_concrete"]["ends_at_local_y_ft"]
    found = 0
    for el in m.elements:
        if "sloped concrete" not in el.name:
            continue
        (d,) = el.geometry
        ys = [y for _x, y in d["base"]]
        assert max(ys) == pytest.approx(end_y, abs=1e-9)
        assert all(y <= end_y + 1e-9 for y in ys)
        found += 1
    assert found == 2


# ------------------------------------------------------------ gate + spec
def test_gate_passes(model):
    assert run_pre(model).passed


def test_build_spec_check_only(tmp_path):
    import yaml
    paycodes = {
        "rules": [{"match": "(?i)spillway", "group": "sp_conc"}],
        "groups": {"sp_conc": {"measure": "GrossVolume"}},
        "codes": {"SP-CONC": {"group": "sp_conc", "measure": "GrossVolume",
                              "unit": "CY", "item_number": "0007",
                              "description": "Structural concrete, spillway"}},
    }
    (tmp_path / "spillway.paycodes.yaml").write_text(
        yaml.safe_dump(paycodes), encoding="utf-8")
    spec = {
        "family": "spillway",
        "params": copy.deepcopy(PARAMS),
        "paycodes": "./spillway.paycodes.yaml",
        "outputs": {"dxf": "out/spillways.dxf", "ifc": "out/spillways.ifc",
                    "takeoff_map": "out/spillways-takeoff-map.yaml"},
        # `base` is not optional for a spec whose placement origins are State
        # Plane coordinates: without it the model lands 6.5 million ft from
        # the origin (see CTX above, issue #156).
        "project": {"name": "Spillway Fixture", "epsg": 2227,
                    "base": [6592000.0, 1943000.0],
                    "guid_ns": "3b7a5c2e-0000-4000-8000-000000000042"},
    }
    spec_path = tmp_path / "spillway.spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec), encoding="utf-8")
    assert registry.build_from_spec(spec_path, check_only=True) == 0
    assert not (tmp_path / "out").exists()
