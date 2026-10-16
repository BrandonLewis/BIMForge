"""Stroked-text + station annotation, promoted into the kernel (#195).

The annotation layer produces an emitter-agnostic *instancing plan*: a small
set of unique stamps (the tick, one per distinct glyph) plus a placement per
occurrence. emit_ifc turns each stamp into ONE IfcRepresentationMap and each
placement into an IfcMappedItem — so a station label reuses its glyphs instead
of duplicating polylines (the field stationing_to_ifc lesson).
"""
from __future__ import annotations

import math

import pytest

from bimforge.author.alignment import Alignment
from bimforge.author.annotate import (
    ADVANCE, FONT, AnnotationPlan, Instance, station_annotation, text_strokes,
)

POB = {"station": 0.0, "northing": 0.0, "easting": 0.0}
NORTH = {"kind": "tangent", "bearing": "N 0-0-0 E", "length": 500.0}
EAST = {"kind": "tangent", "bearing": "N 90-0-0 E", "length": 500.0}


# --------------------------------------------------------------------- font
def test_font_covers_station_glyphs():
    for ch in "0123456789+-. ":
        assert ch in FONT


def test_glyph_strokes_live_in_the_em_box():
    for ch, polys in FONT.items():
        for poly in polys:
            for x, y in poly:
                assert -1e-9 <= x <= 0.5 + 1e-9, f"{ch!r} x={x}"
                assert -1e-9 <= y <= 1.0 + 1e-9, f"{ch!r} y={y}"


# ---------------------------------------------------------------- text_strokes
def test_text_strokes_scales_with_height():
    small = text_strokes("8", height=1.0)
    big = text_strokes("8", height=3.0)
    assert len(small) == len(big) > 0
    # every coordinate triples with the height
    for ps, pb in zip(small, big):
        for (xs, ys), (xb, yb) in zip(ps, pb):
            assert math.isclose(xb, xs * 3.0, abs_tol=1e-9)
            assert math.isclose(yb, ys * 3.0, abs_tol=1e-9)


def test_text_strokes_advances_monospace():
    # the second glyph's strokes are shifted by exactly one advance in x
    one = text_strokes("1", height=2.0)
    oneone = text_strokes("11", height=2.0)
    shift = ADVANCE * 2.0
    first = oneone[: len(one)]
    second = oneone[len(one):]
    for p0, p1 in zip(first, second):
        for (x0, _), (x1, _) in zip(p0, p1):
            assert math.isclose(x1 - x0, shift, abs_tol=1e-9)


def test_text_strokes_rejects_unsupported_glyph():
    with pytest.raises(ValueError, match="unsupported"):
        text_strokes("Z", height=1.0)


def test_space_advances_but_draws_nothing():
    assert text_strokes(" ", height=1.0) == []
    # "1 1" is two glyphs of strokes, the middle space contributing none
    assert len(text_strokes("1 1")) == 2 * len(text_strokes("1"))


# ----------------------------------------------------------- station_annotation
def test_tick_at_each_interval_station():
    al = Alignment(POB, [NORTH])
    plan = station_annotation(al, 0.0, 300.0, interval=100.0, label=False)
    ticks = [i for i in plan.instances if i.stamp == "tick"]
    # stations 0, 100, 200, 300
    assert len(ticks) == 4
    assert [round(t.y, 6) for t in ticks] == [0.0, 100.0, 200.0, 300.0]
    # centreline is due north (easting 0) so every tick sits on x == 0
    assert all(math.isclose(t.x, 0.0, abs_tol=1e-9) for t in ticks)


def test_tick_rotation_is_minus_azimuth():
    al = Alignment(POB, [EAST])          # heading due east, az == 90
    plan = station_annotation(al, 0.0, 100.0, interval=100.0, label=False)
    tick = next(i for i in plan.instances if i.stamp == "tick")
    assert math.isclose(tick.rot_deg % 360.0, (-90.0) % 360.0, abs_tol=1e-9)
    # resolved, a tick on an east-heading line lies along +/- north (x const)
    xs = {round(x, 6) for poly in _resolve(plan, tick) for x, _ in poly}
    assert len(xs) == 1


def test_label_glyphs_and_stamp_reuse():
    al = Alignment(POB, [NORTH])
    plan = station_annotation(al, 0.0, 100.0, interval=100.0, tick_len=5.0)
    # station 0+00.00 and 1+00.00 -> glyphs '0','+','.','1'
    stamp_keys = set(plan.stamps)
    assert "tick" in stamp_keys
    assert {"0", "1", "+", "."} <= stamp_keys
    # one stamp per distinct glyph despite '0' appearing many times
    glyph_instances = [i for i in plan.instances if i.stamp == "0"]
    assert len(glyph_instances) > 1                 # reused
    assert len(plan.stamps["0"]) == len(FONT["0"])  # stored once


def test_plan_is_deterministic():
    al = Alignment(POB, [NORTH])
    a = station_annotation(al, 0.0, 200.0, interval=100.0)
    b = station_annotation(al, 0.0, 200.0, interval=100.0)
    assert a.instances == b.instances
    assert a.stamps == b.stamps


def test_polylines_resolves_every_instance():
    al = Alignment(POB, [NORTH])
    plan = station_annotation(al, 0.0, 100.0, interval=100.0)
    polys = plan.polylines()
    expect = sum(len(plan.stamps[i.stamp]) for i in plan.instances)
    assert len(polys) == expect
    assert all(len(p) >= 2 for p in polys)


def test_station_annotation_rejects_non_positive_interval():
    al = Alignment(POB, [NORTH])
    with pytest.raises(ValueError, match="interval must be > 0"):
        station_annotation(al, 0.0, 100.0, interval=0.0)
    with pytest.raises(ValueError, match="interval must be > 0"):
        station_annotation(al, 0.0, 100.0, interval=-25.0)


class _Origin:
    """Minimal ProjectContext stand-in: survey (e, n) -> model, base-relative."""

    def __init__(self, base_e, base_n):
        self.base_e, self.base_n = base_e, base_n

    def local(self, e, n, z=None):
        return (e - self.base_e, n - self.base_n)


def test_origin_puts_annotation_in_the_model_frame():
    # a raw state-plane alignment; without base subtraction the tick would land
    # millions of feet from the base-relative structure (the georef-drift trap).
    pob = {"station": 0.0, "northing": 1_943_000.0, "easting": 6_594_000.0}
    al = Alignment(pob, [NORTH])
    origin = _Origin(base_e=6_594_000.0, base_n=1_943_000.0)
    plan = station_annotation(al, 0.0, 100.0, interval=100.0, label=False,
                              origin=origin)
    ticks = [i for i in plan.instances if i.stamp == "tick"]
    # station 0 sits exactly on the base point -> model (0, 0)
    assert math.isclose(ticks[0].x, 0.0, abs_tol=1e-6)
    assert math.isclose(ticks[0].y, 0.0, abs_tol=1e-6)
    # station 100 is 100 ft north of it -> (0, 100), NOT ~1.9e6
    assert math.isclose(ticks[1].y, 100.0, abs_tol=1e-6)


def _resolve(plan: AnnotationPlan, inst: Instance):
    th = math.radians(inst.rot_deg)
    c, s = math.cos(th), math.sin(th)
    return [[(inst.x + c * px - s * py, inst.y + s * px + c * py)
             for px, py in poly] for poly in plan.stamps[inst.stamp]]
