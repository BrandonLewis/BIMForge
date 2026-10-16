"""ProjectContext: deterministic GUIDs, local transform, from_spec validation."""
import uuid

import pytest

from bimforge.author.project import (
    INTL_FT_TO_M, US_SURVEY_FT_TO_M, ProjectContext)

NS = uuid.UUID("6b1f3c8e-5a2d-4e77-9c31-0b2f4a6d8e10")


def _ctx(**kw):
    base = dict(name="Fixture Project", epsg=2226, base_e=6_594_000.0,
                base_n=1_943_000.0, base_h=200.0, guid_ns=NS)
    base.update(kw)
    return ProjectContext(**base)


def test_guid_is_deterministic_and_22_chars():
    pytest.importorskip("ifcopenshell")
    a, b = _ctx(), _ctx()
    g = a.guid("element/footing PS-1")
    assert len(g) == 22
    assert g == b.guid("element/footing PS-1")          # instance-independent
    assert g != a.guid("element/footing PS-2")          # key-sensitive
    assert g != _ctx(guid_ns=uuid.uuid4()).guid("element/footing PS-1")


def test_local_transform():
    ctx = _ctx()
    assert ctx.local(6_594_100.0, 1_943_050.0) == (100.0, 50.0)
    assert ctx.local(6_594_100.0, 1_943_050.0, 210.0) == (100.0, 50.0, 10.0)


def test_from_spec_happy_path_and_units():
    ctx = ProjectContext.from_spec({
        "name": "Fixture", "epsg": 2226, "base": [6594000, 1943000, 200],
        "guid_ns": str(NS)})
    assert ctx.crs_name == "EPSG:2226"
    assert ctx.ft_to_m == US_SURVEY_FT_TO_M
    assert ProjectContext.from_spec(
        {"name": "F", "guid_ns": str(NS), "unit": "ft"}).ft_to_m == INTL_FT_TO_M


def test_unit_metre_is_refused_rather_than_silently_reinterpreting_feet():
    """#303. `unit: m` mapped to ft_to_m = 1.0, which does not produce a metric
    model — it reinterprets every family's foot literals AS metres, and the
    validation gate passed either way. A loud error beats a silent 3.28x."""
    with pytest.raises(ValueError, match="unit 'm' is not supported"):
        ProjectContext.from_spec({"name": "F", "guid_ns": str(NS), "unit": "m"})


def test_the_metre_refusal_says_the_output_is_already_si_metre():
    """The reason someone reaches for `unit: m` is wanting a metric IFC, and they
    already have one. If the message does not say so, they go looking for another
    way to force it."""
    with pytest.raises(ValueError) as exc:
        ProjectContext.from_spec({"name": "F", "guid_ns": str(NS), "unit": "m"})
    assert "ALREADY" in str(exc.value) and "SI metre" in str(exc.value)


def _emitted_842_stem_height_m(tmp_path, unit: str) -> float:
    """Build the 842 family, emit the IFC, and MEASURE the barrier's z-extent.

    Deliberately not `_H * ctx.ft_to_m`: that recomputes the conversion the test
    is supposed to be checking, so it would agree with a double conversion or any
    other emitter bug. The number has to come off the emitted geometry.
    """
    import ifcopenshell
    import ifcopenshell.geom
    import numpy as np

    from bimforge.author.emit_ifc import emit_ifc
    from bimforge.author.families import concrete_barrier_842 as fam

    ctx = ProjectContext.from_spec({
        "name": "F", "epsg": 2226, "base": [0.0, 0.0],
        "guid_ns": str(NS), "unit": unit})
    model = fam.build(
        {"runs": [{"name": "NB", "straight_length_ft": 100.0,
                   "start_end": "none", "end_end": "none"}]}, ctx)
    out = tmp_path / f"842-{unit}.ifc"
    emit_ifc(model, str(out))

    f = ifcopenshell.open(str(out))
    walls = [w for w in f.by_type("IfcWall") if "842 barrier" in (w.Name or "")]
    assert len(walls) == 1, f"expected one 842 barrier wall, got {len(walls)}"
    shape = ifcopenshell.geom.create_shape(ifcopenshell.geom.settings(), walls[0])
    verts = np.asarray(shape.geometry.verts, dtype=float).reshape(-1, 3)
    return float(verts[:, 2].max() - verts[:, 2].min())


#: Units `from_spec` accepts. Driving the test off this means a newly accepted
#: unit is exercised automatically rather than silently skipped.
_ACCEPTED_UNITS = ("us-survey-ft", "ft")


@pytest.mark.parametrize("unit", _ACCEPTED_UNITS)
def test_a_known_published_dimension_reaches_the_ifc_at_its_real_size(tmp_path, unit):
    """#303 ask 3 — a scale check that does not care WHY the scale is wrong.

    The Caltrans Type 842 stem is 3'-6" above the base datum, so the emitted
    barrier must be 1.067 m tall in the IFC for every accepted unit. Measured off
    the emitted geometry, so it catches a mistyped constant, a double conversion
    in the emitter, or a new unit added without thought — not just the `unit: m`
    path, and not merely the arithmetic this test could have repeated itself.
    """
    pytest.importorskip("ifcopenshell")
    from bimforge.author import type_842_profile

    assert type_842_profile._H == 3.5, "842 stem is 3'-6\"; the literal moved"
    height = _emitted_842_stem_height_m(tmp_path, unit)
    assert abs(height - 1.0668) < 0.002, (
        f"unit {unit!r} emits the 842 barrier {height:.4f} m tall, not 1.067 m")


def test_from_spec_requires_name_and_guid_ns():
    with pytest.raises(ValueError, match="name"):
        ProjectContext.from_spec({"guid_ns": str(NS)})
    with pytest.raises(ValueError, match="guid_ns"):
        ProjectContext.from_spec({"name": "F"})
    with pytest.raises(ValueError, match="unit"):
        ProjectContext.from_spec({"name": "F", "guid_ns": str(NS), "unit": "furlong"})
