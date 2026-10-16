"""bimforge.bim.ifc_mesh.classify_faces + the est-bim sfca subcommand.

Triangle-normal classification off the tessellated boundary (the spillway-pilot
build_takeoff port): top where nz > flat, bottom where nz < -flat, side
otherwise — battered/sloped faces land in side and are measured on the TRUE
slope, which is the SFCA surface a form carpenter actually builds. `buried`
is a SUBSET of side, clipped EXACTLY at the split elevation.
"""
import math
import uuid

import numpy as np
import pytest

pytest.importorskip("ifcopenshell")

from bimforge.author.emit_ifc import emit_ifc
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import Prism
from bimforge.author.project import ProjectContext
from bimforge.bim import cli
from bimforge.bim.ifc_mesh import classify_faces
from bimforge.bim.tests.test_ifc_mesh import CUBE_F, CUBE_V

KEYS = ("volume_cf", "top_sf", "bottom_sf", "side_sf", "buried_sf")


def _cube(dx=0.0, dy=0.0, dz=0.0):
    v = np.asarray(CUBE_V, dtype=float).reshape(-1, 3)
    return v + [dx, dy, dz], np.asarray(CUBE_F, dtype=np.int64).reshape(-1, 3)


# ------------------------------------------------------------- classify_faces
def test_unit_cube_classification():
    v, f = _cube()
    r = classify_faces(v, f)
    assert set(r) == set(KEYS)
    assert r["volume_cf"] == pytest.approx(1.0)
    assert r["top_sf"] == pytest.approx(1.0)
    assert r["bottom_sf"] == pytest.approx(1.0)
    assert r["side_sf"] == pytest.approx(4.0)
    assert r["buried_sf"] == 0.0


def test_battered_face_lands_in_side_on_the_true_slope():
    # A wedge whose sloped face rises 45 deg: nz = 1/sqrt(2) ~ 0.707 < 0.85,
    # so it is SIDE (formwork), measured on the true slope — plan area 1,
    # slope area sqrt(2). Faces: bottom 1 (nz=-1), vertical back 1, two
    # triangular ends 0.5 each, slope sqrt(2). No top face at all.
    v = np.array([[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
                  [0, 0, 1], [0, 1, 1]], dtype=float)
    f = np.array([[0, 2, 1], [0, 3, 2],      # bottom, outward -z
                  [0, 4, 5], [0, 5, 3],      # back x=0, outward -x
                  [0, 1, 4],                 # end y=0, outward -y
                  [3, 5, 2],                 # end y=1, outward +y
                  [1, 2, 5], [1, 5, 4]],     # 45 deg slope, outward (1,0,1)
                 dtype=np.int64)
    r = classify_faces(v, f)
    assert r["volume_cf"] == pytest.approx(0.5)
    assert r["top_sf"] == pytest.approx(0.0)            # NOT plan-projected
    assert r["bottom_sf"] == pytest.approx(1.0)
    assert r["side_sf"] == pytest.approx(2.0 + math.sqrt(2.0))


def test_split_el_exact_clipping_one_vertex_below():
    # Apex-down vertical triangle, 2 units tall, area 1 (base 1 at z=2,
    # apex at z=0). split_el at 25% height (z=0.5): one vertex below, so
    # frac = t01*t02 = 0.25*0.25 — the similar triangle cut off the corner.
    v = np.array([[0, 0, 2], [1, 0, 2], [0.5, 0, 0]], dtype=float)
    f = np.array([[0, 1, 2]], dtype=np.int64)
    r = classify_faces(v, f, split_el=0.5)
    assert r["side_sf"] == pytest.approx(1.0)
    assert r["buried_sf"] == pytest.approx(0.25 * 0.25)


def test_split_el_exact_clipping_two_vertices_below():
    # Apex-up: base 1 at z=0, apex at z=2, area 1. split_el=0.5: two
    # vertices below, frac = 1 - t20*t21 = 1 - 0.75^2 = 0.4375.
    v = np.array([[0, 0, 0], [1, 0, 0], [0.5, 0, 2]], dtype=float)
    f = np.array([[0, 1, 2]], dtype=np.int64)
    r = classify_faces(v, f, split_el=0.5)
    assert r["side_sf"] == pytest.approx(1.0)
    assert r["buried_sf"] == pytest.approx(1.0 - 0.75 * 0.75)


def test_split_el_degenerate_all_above_and_all_below():
    v = np.array([[0, 0, 0], [1, 0, 0], [0.5, 0, 2]], dtype=float)
    f = np.array([[0, 1, 2]], dtype=np.int64)
    assert classify_faces(v, f, split_el=-1.0)["buried_sf"] == 0.0
    below = classify_faces(v, f, split_el=3.0)
    assert below["buried_sf"] == pytest.approx(below["side_sf"])


def test_translation_invariance_at_state_plane_scale():
    # The cube parked at State Plane coordinates (E 6,592,000 / N 1,943,000)
    # must classify identically — mesh_volume shifts into a local frame, and
    # areas are built from coordinate differences.
    v0, f = _cube()
    r0 = classify_faces(v0, f, split_el=0.5)
    v1, _ = _cube(6_592_000.0, 1_943_000.0, 0.0)
    r1 = classify_faces(v1, f, split_el=0.5)
    assert r0["buried_sf"] == pytest.approx(2.0)   # 4 side faces cut in half
    for k in KEYS:
        assert r1[k] == pytest.approx(r0[k], rel=1e-9)


# ----------------------------------------------------------------- CLI: sfca
def _emit_two_boxes(tmp_path):
    """A 4x4x2 ft footing plus an IfcPipeSegment barrel (skipped by default)."""
    ctx = ProjectContext(
        name="SFCA Fixture", epsg=2226,
        base_e=6_594_000.0, base_n=1_943_000.0, base_h=200.0,
        guid_ns=uuid.UUID("5a0e2c4d-9b17-4f36-8d25-3c1a7e9b0f42"))
    m = StructureModel("sfca", ctx)
    box = Prism("box footing", [(0, 0), (4, 0), (4, 4), (0, 4)],
                z_bot=0.0, z_top=2.0, ifc="IfcFooting")
    m.add(Element.from_geometry(box.name, box, ifc_class="IfcFooting"))
    barrel = Prism("barrel through", [(10, 0), (12, 0), (12, 2), (10, 2)],
                   z_bot=0.0, z_top=2.0, ifc="IfcPipeSegment")
    m.add(Element.from_geometry(barrel.name, barrel,
                                ifc_class="IfcPipeSegment"))
    out = tmp_path / "sfca.ifc"
    emit_ifc(m, str(out))
    return str(out)


def test_cli_sfca_table_skips_pipe_class(tmp_path, capsys):
    ifc = _emit_two_boxes(tmp_path)
    rc = cli.main(["sfca", ifc])
    assert rc == 0
    out = capsys.readouterr().out
    assert "barrel" not in out                    # IfcPipeSegment skipped
    assert "IfcPipeSegment" not in out
    assert "BURIED" not in out.upper()            # no split, no buried column
    footing = [l for l in out.splitlines() if "box footing" in l]
    assert len(footing) == 1                      # exactly one data row
    total = [l for l in out.splitlines() if "TOTAL" in l.upper()]
    assert len(total) == 1
    # 4x4x2 ft box: 32 CF, top/bottom 16 SF, side 32 SF
    nums = [float(t.replace(",", "")) for t in footing[0].split()
            if t.replace(",", "").replace(".", "").isdigit()]
    assert nums[-4:] == pytest.approx([32.0, 16.0, 16.0, 32.0], rel=1e-3)
    tnums = [float(t.replace(",", "")) for t in total[0].split()
             if t.replace(",", "").replace(".", "").isdigit()]
    assert tnums[-4:] == pytest.approx([32.0, 16.0, 16.0, 32.0], rel=1e-3)


def test_cli_sfca_split_el_adds_buried_column(tmp_path, capsys):
    ifc = _emit_two_boxes(tmp_path)
    rc = cli.main(["sfca", ifc, "--split-el", "0.5"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "BURIED" in out.upper()
    footing = [l for l in out.splitlines() if "box footing" in l]
    assert len(footing) == 1
    nums = [float(t.replace(",", "")) for t in footing[0].split()
            if t.replace(",", "").replace(".", "").isdigit()]
    # side 32 SF, split 0.5 ft up a 2 ft face -> buried 25% = 8 SF
    assert nums[-5:] == pytest.approx([32.0, 16.0, 16.0, 32.0, 8.0], rel=1e-3)


def test_cli_sfca_skip_class_is_overridable(tmp_path, capsys):
    ifc = _emit_two_boxes(tmp_path)
    rc = cli.main(["sfca", ifc, "--skip-class", "IfcFooting"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "box footing" not in out
    assert "barrel" in out                        # pipe now included
