import pytest
from bimforge.author.wingwall_section import taper_stem_prism, taper_footing_prism
from bimforge.author.wingwall_section import WarpedStem, stiffening_beam_prism
from bimforge.author.primitives import face_volume, loft_faces


def test_taper_stem_wedge_volume():
    # T=10", L=18', H=8' -> h_max=8.5, h_min=1.0, footing top F=1.0
    stem = taper_stem_prism(length=18.0, stem_t=0.8333, toe=1.0, foot_t=1.0,
                            h_max=8.5, h_min=1.0)
    assert stem.volume_cf == pytest.approx(0.8333 * 18.0 * (8.5 + 1.0) / 2.0,
                                           abs=0.05)
    # base sits above the footing (z_bot = F) and the plan strip is T wide
    assert stem.z_bot == pytest.approx(1.0)
    assert stem.area_sf == pytest.approx(18.0 * 0.8333, abs=0.02)
    assert stem.top_z[0] == pytest.approx(1.0 + 8.5)   # culvert end (x=0) is tall: F + h_max


def test_taper_footing_clean_box():
    foot = taper_footing_prism(length=18.0, toe=1.0, heel=4.0, foot_t=1.0)
    assert foot.volume_cf == pytest.approx(18.0 * 5.0 * 1.0, abs=0.02)  # W=C+B=5
    assert foot.dims_ft == (18.0, 5.0)                                   # clean box


def test_taper_footing_heel_taper_trapezoid():
    # heel tapers 4.0 (culvert) -> 1.0 (toe): W=5.0, W_toe=C+1.0=2.0
    foot = taper_footing_prism(length=18.0, toe=1.0, heel=4.0, foot_t=1.0,
                               heel_toe=1.0)
    assert foot.dims_ft is None                                          # trapezoid
    assert foot.volume_cf == pytest.approx(1.0 * 18.0 * (5.0 + 2.0) / 2.0, abs=0.02)


def test_warped_stem_volume_is_exact_shear_taper():
    # The batter is a pure horizontal SHEAR: each cross-section stays a
    # parallelogram of area T*h (shear-invariant), so the concrete volume is
    # EXACTLY the straight taper's T*L*(h_max+h_min)/2 -- declared closed-form,
    # batter-independent. (The faceted loft the emitters draw is a separate,
    # tolerance-bounded number; see the next test.)
    T, L, h_max, h_min = 0.8333, 18.0, 8.5, 1.0
    w = WarpedStem("s", length=L, stem_t=T, toe=1.0, foot_t=1.0,
                   h_max=h_max, h_min=h_min, batter_toe=0.125)
    assert w.volume_cf == pytest.approx(T * L * (h_max + h_min) / 2.0, rel=1e-9)


def test_warped_faceted_loft_within_mesh_tolerance():
    # `faceted_volume_cf` is `face_volume` of the emitted loft (what the
    # IFC/DXF/STEP actually draw). A triangulated warped face systematically
    # over-encloses vs the true shear volume (O(1/n) diagonal bias), so the
    # exact quantity is `volume_cf`; the loft is held within the gate's 0.5%
    # MESH_TOLERANCE for realistic batters (curved-primitive discipline, same
    # as ArcBand's volume_in3 vs faceted_volume_in3).
    T, L, h_max, h_min = 0.8333, 18.0, 8.5, 1.0
    w = WarpedStem("s", length=L, stem_t=T, toe=1.0, foot_t=1.0,
                   h_max=h_max, h_min=h_min, batter_toe=0.125)   # ~1.5:12
    assert w.faceted_volume_cf == pytest.approx(face_volume(loft_faces(w.sections)))
    assert w.faceted_volume_cf > w.volume_cf     # triangulated warp over-encloses
    rel = abs(w.faceted_volume_cf - w.volume_cf) / w.volume_cf
    assert rel < 0.005                       # inside MESH_TOLERANCE at n=48


def test_warped_face_batters_at_the_toe():
    # Direction check (uses a steep batter to make the lean unambiguous): the
    # face is vertical at the culvert (x=0) and leans +y at the toe (x=L).
    w = WarpedStem("s", length=18.0, stem_t=0.8333, toe=1.0, foot_t=1.0,
                   h_max=8.5, h_min=1.0, batter_toe=0.5)
    culvert, toe = w.sections[0], w.sections[-1]
    # section vertex order: 0 front-bottom, 1 back-bottom, 2 back-top, 3 front-top
    assert culvert[3][1] == pytest.approx(culvert[0][1], abs=1e-9)  # vertical @ culvert
    assert toe[3][1] > toe[0][1] + 0.4          # leans batter_toe*h_min = 0.5 ft


def test_stiffening_beam_box_volume():
    beam = stiffening_beam_prism(length=18.0, w=1.0, d=1.5, z0=9.0,
                                 name="b")
    assert beam.volume_cf == pytest.approx(18.0 * 1.0 * 1.5, abs=0.02)
    assert beam.dims_ft == (18.0, 1.0)
