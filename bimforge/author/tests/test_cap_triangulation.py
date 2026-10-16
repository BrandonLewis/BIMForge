"""Loft caps are ear-clipped, not fanned from vertex 0 (#315).

`loft_faces` returns its two end caps as whole rings, and five paths used to
fan them from vertex 0. A fan is valid only on a CONVEX ring; on a re-entrant
one it lays the notch twice, once each way, so the emitted surface carries
facets outside the solid.

The volume cannot catch it. A fan's SIGNED areas are the shoelace whatever the
convexity, so the two extra facets cancel in the integral and `volume_cf`,
`face_volume`, Qto-vs-mesh and section-area x length all agree with each other
and with the truth. The only cheap tell is SURFACE: sum |triangle area| over
one cap and compare it to the ring's shoelace.

So that is what these tests measure. #253 fixed the same bug in one consumer
(`culvert_headwall_wingwall._BarrierSolid`); this is the rest of them.
"""
import math

import pytest

from bimforge.author import footing_run as fr
from bimforge.author import primitives as pr
from bimforge.author import wingwall_section as ws
from bimforge.author.primitives import (
    Prismatoid, face_volume, poly_area, taper_prism_triangles)

#: An L-shaped plan, 64 sf: the most ordinary re-entrant shape in the kernel's
#: reach (an earthwork pad), and the one that made this active rather than
#: latent. A fan from vertex 0 covers the 36 sf notch twice.
L_PLAN = [(0.0, 0.0), (10.0, 0.0), (10.0, 4.0), (4.0, 4.0), (4.0, 10.0), (0.0, 10.0)]

#: The B11-82 Type 842 running section, whose back face steps (#307) — the
#: re-entrant ring that found this on a live bid.
RING_842 = [(0.33333, 0.0), (1.75, 0.0), (1.1875, 3.5),
            (0.02083, 3.5), (0.02083, 2.33333), (0.33333, 2.33333)]


def _tri_area(a, b, c) -> float:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    return 0.5 * math.sqrt((uy * vz - uz * vy) ** 2 + (uz * vx - ux * vz) ** 2
                           + (ux * vy - uy * vx) ** 2)


def _horizontal_cap_area(verts, tris) -> float:
    """Summed |area| of the facets lying in one z plane — the two caps."""
    return sum(_tri_area(*(verts[i] for i in t)) for t in tris
               if len({round(verts[i][2], 9) for i in t}) == 1)


def _is_closed(tris) -> bool:
    edges: dict = {}
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            k = tuple(sorted((a, b)))
            edges[k] = edges.get(k, 0) + 1
    return bool(edges) and all(n == 2 for n in edges.values())


def test_a_reentrant_prismatoid_emits_exactly_its_cap_area():
    """The headline measurement. Fanned, this was 164.0 sf over a 128.0 sf cap
    pair — 36 sf of facets outside the solid — at exactly the right volume."""
    pad = Prismatoid("pad", [(x, y, 0.0) for x, y in L_PLAN],
                     [(x, y, 1.0) for x, y in L_PLAN])
    sol = pad.body_solids()[0]
    truth = 2.0 * poly_area(L_PLAN)
    assert truth == pytest.approx(128.0)
    assert _horizontal_cap_area(sol["verts"], sol["tris"]) == pytest.approx(
        truth, abs=1e-9), "emitted cap facets do not sum to the plan area"
    assert pad.volume_cf == pytest.approx(64.0)
    assert _is_closed(sol["tris"]), "emitted shell is not closed"


def test_a_convex_prismatoid_is_unaffected():
    """The fan was never wrong on a convex ring; the fix must not move it."""
    sq = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    pad = Prismatoid("pad", [(x, y, 0.0) for x, y in sq],
                     [(x, y, 2.0) for x, y in sq])
    sol = pad.body_solids()[0]
    assert _horizontal_cap_area(sol["verts"], sol["tris"]) == pytest.approx(200.0)
    assert pad.volume_cf == pytest.approx(200.0)
    assert _is_closed(sol["tris"])


def test_taper_prism_triangles_caps_a_reentrant_base_without_excess():
    """These triangles are EMITTED (emit_ifc's _faceted_brep), so the excess
    reached the IFC. Fanned: 5.06772 sf over a 4.33855 sf ring, 16.8% high."""
    tris = taper_prism_triangles(RING_842, [1.0] * len(RING_842), 0.0)
    top = [t for t in tris if all(abs(p[2] - 1.0) < 1e-12 for p in t)]
    assert top, "no top cap facets emitted"
    assert sum(_tri_area(*t) for t in top) == pytest.approx(
        poly_area(RING_842), abs=1e-9)
    # and the exact-volume contract the fan was there for still holds
    assert face_volume([list(t) for t in tris]) == pytest.approx(
        poly_area(RING_842), abs=1e-9)


def _fan_excess(ring) -> float:
    """How much |area| a fan from vertex 0 lays over the ring itself, for the
    worse of the two windings.

    The winding matters, which is half of why this bug survived: `loft_faces`
    returns the FIRST cap reversed, so one cap fans from the opposite corner.
    The L-plan is star-shaped from (0, 0) — a fan from there is valid and
    measures exactly 64 sf — and is not star-shaped from (0, 10), where the
    same fan lays 100 sf. One cap right, one cap wrong, volume exact.
    """
    worst = 0.0
    for r in (list(ring), list(reversed(ring))):
        fan = sum(_tri_area((*r[0], 0.0), (*r[i], 0.0), (*r[i + 1], 0.0))
                  for i in range(1, len(r) - 1))
        worst = max(worst, fan - poly_area(r))
    return worst


def test_the_fan_would_have_failed_these_measurements():
    """Guards the two tests above from passing vacuously: on these rings a fan
    from vertex 0 really does overshoot, by the area of the notch it covers
    twice. If this ever stops being true the fixtures have gone convex."""
    assert _fan_excess(L_PLAN) == pytest.approx(36.0, abs=1e-4)
    assert _fan_excess(RING_842) == pytest.approx(0.72917, abs=1e-4)
    # a convex ring is fine under either winding — which is why the fix has to
    # leave convex output alone rather than re-baseline every shipped model
    assert _fan_excess([(0.0, 0.0), (4.0, 0.0), (4.0, 3.0), (0.0, 3.0)]) == (
        pytest.approx(0.0, abs=1e-12))


#: The solids whose caps come from `loft_faces` and used to be fanned. Their
#: own sections are convex today (trapezoids, rectangles), so no fixture can
#: make them emit a bad facet — what is testable is that they consult the
#: shared triangulator for every face rather than carrying their own fan.
def _battered_wall():
    return pr.BatteredWall("w", lol=[(0.0, 0.0), (20.0, 0.0)],
                           top_profile=[(0.0, 6.0), (20.0, 6.0)], key_index=0,
                           base_el=0.0, t_top=1.0, batter=0.5 / 12.0, side=1.0)


def _footing_run():
    return fr.FootingRun("f", lol=[(0.0, 0.0), (20.0, 0.0)], toe=1.0, heel=1.0,
                         side=1.0, thickness=1.5, top_el=1.5)


def _wingwall():
    return ws.WarpedStem("ww", length=12.0, stem_t=1.0, toe=1.0, foot_t=1.5,
                         h_max=6.0, h_min=2.0, batter_toe=1.0, n_sections=4)


@pytest.mark.parametrize("module, build", [
    (pr, _battered_wall), (fr, _footing_run), (ws, _wingwall)])
def test_every_loft_cap_consumer_uses_the_shared_triangulator(
        module, build, monkeypatch):
    seen = []
    real = pr.triangulate_planar_face

    def spy(ring):
        seen.append(len(ring))
        return real(ring)

    monkeypatch.setattr(pr, "triangulate_planar_face", spy, raising=True)
    if module is not pr:
        monkeypatch.setattr(module, "triangulate_planar_face", spy,
                            raising=False)
    try:
        solid = build()
    except Exception as exc:                     # pragma: no cover - fixture slip
        pytest.fail(f"fixture for {module.__name__} did not build: {exc}")
    sol = solid.body_solids()[0]
    assert seen, (f"{module.__name__} triangulated its loft faces without "
                  "triangulate_planar_face — the fan from vertex 0 is back")
    assert any(n > 3 for n in seen), (
        "only triangles reached the triangulator, so the CAP rings went "
        "somewhere else")
    assert _is_closed(sol["tris"])
