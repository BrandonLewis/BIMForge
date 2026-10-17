"""Exact revolutions (#331): the B11-51 bent-down return and its tip cap are
a rectangular HSS section turned about a fixed axis, so they are one
IfcRevolvedAreaSolid each, not a disk sweep and not a mesh.

The volume check cannot tell a solid turned the wrong way, about the wrong
side of the axis or from a shifted profile from the right one, so the
tampering tests hold the post-emit placement check to each of those.
"""
from __future__ import annotations

import math
import uuid

import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

from bimforge.author import emit_ifc as emit_mod  # noqa: E402
from bimforge.author import gate  # noqa: E402
from bimforge.author import rail_run as rr  # noqa: E402
from bimforge.author.emit_ifc import emit_ifc  # noqa: E402
from bimforge.author.model import StructureModel  # noqa: E402
from bimforge.author.primitives import (  # noqa: E402
    as_mesh, exact_of, place_exact,
)
from bimforge.author.project import ProjectContext  # noqa: E402


def _ctx(schema="IFC4X3_ADD2"):
    return ProjectContext(name="Exact Revolution Fixture", schema=schema,
                          epsg=2226, base_e=6_594_000.0, base_n=1_943_000.0,
                          base_h=200.0, guid_ns=uuid.UUID(int=3310))


def _bent(els):
    return [e for e in els if "end return" in e.name or "rail cap" in e.name]


def _model(schema="IFC4X3_ADD2"):
    m = StructureModel("rail", _ctx(schema))
    for el in rr.build_run(length_ft=24.0, base_z_ft=2.0, run_name="NB",
                           end_posts=("start", "end"), joints=()):
        m.add(el)
    return m


def _emit(tmp_path, m):
    out = tmp_path / "x.ifc"
    emit_ifc(m, str(out))
    return out, ifcopenshell.open(str(out))


def test_every_bent_member_carries_its_revolution():
    for el in _bent(_model().elements):
        (d,) = el.geometry.body_solids()
        ex = exact_of(d)
        assert ex is not None and ex["kind"] == "revolution", el.name
        assert ex["angle"] == pytest.approx(el.geometry.phi1 - el.geometry.phi0)


@pytest.mark.parametrize("schema", ["IFC4X3_ADD2", "IFC4"])
def test_written_as_revolved_solids_that_pass_the_gate(tmp_path, schema):
    m = _model(schema)
    out, f = _emit(tmp_path, m)
    names = {e.name for e in _bent(m.elements)}
    assert len(names) == 4
    for p in f.by_type("IfcProduct"):
        if p.Name not in names:
            continue
        (rep,) = p.Representation.Representations
        (item,) = rep.Items
        assert item.is_a("IfcRevolvedAreaSolid"), p.Name
        assert rep.RepresentationType == "SweptSolid"
    # the angle is stated in radians, not left to the reader
    units = f.by_type("IfcUnitAssignment")[0].Units
    assert any(u.UnitType == "PLANEANGLEUNIT" and u.Name == "RADIAN"
               for u in units)
    rep_post = gate.run_post(m, {"ifc": str(out)})
    assert rep_post.passed, rep_post.failures
    assert gate._ifc_exact_revolution_check(m, out) == []



def test_a_placed_member_passes_the_gate(tmp_path):
    # the revolution is element-local; the check must not hold the drawn
    # solid to it in world coordinates once the element is placed
    m = _model()
    for el in _bent(m.elements):
        el.x_ft, el.y_ft, el.z_ft, el.bearing_deg = 10.0, -4.0, 1.5, 30.0
    out, _f = _emit(tmp_path, m)
    assert gate._ifc_exact_revolution_check(m, out) == []

def _tampered(monkeypatch, edit):
    real = emit_mod._revolved_solid

    def wrong(f, d, k):
        return real(f, edit(dict(d)), k)
    monkeypatch.setattr(emit_mod, "_revolved_solid", wrong)


@pytest.mark.parametrize("what, edit", [
    ("turned the other way",
     lambda d: dict(d, axis=dict(d["axis"], dir=tuple(
         -c for c in d["axis"]["dir"])))),
    ("about the far side",
     lambda d: dict(d, axis=dict(d["axis"], o=tuple(
         2 * p - a for p, a in zip(d["plane"]["o"], d["axis"]["o"]))))),
    # (the HSS ring is symmetric, so a mirror would draw the same solid)
    ("shifted profile",
     lambda d: dict(d, profile=[(u, v + 0.05) for u, v in d["profile"]],
                    voids=[[(u, v + 0.05) for u, v in h] for h in d["voids"]])),
    ("short turn", lambda d: dict(d, angle=d["angle"] * 0.9)),
])
def test_the_placement_check_sees_what_volume_cannot(tmp_path, monkeypatch,
                                                     what, edit):
    m = _model()
    _tampered(monkeypatch, edit)
    out, _f = _emit(tmp_path, m)
    fails = gate._ifc_exact_revolution_check(m, out)
    assert fails and all("not drawn where" in s for s in fails), what


def test_an_edited_mesh_is_written_as_its_mesh():
    (d,) = _bent(_model().elements)[0].geometry.body_solids()
    v = list(d["verts"])
    v[0] = (v[0][0] + 0.01, v[0][1], v[0][2])
    assert exact_of(dict(d, verts=v)) is None
    assert exact_of(as_mesh(d)) is None


def _moved(d, lin, off):
    import numpy as np
    m = place_exact(d, lin, off)
    m["verts"] = [tuple(np.asarray(lin) @ np.asarray(p) + np.asarray(off))
                  for p in d["verts"]]
    return m


@pytest.mark.parametrize("lin", [
    [[math.cos(0.7), -math.sin(0.7), 0], [math.sin(0.7), math.cos(0.7), 0],
     [0, 0, 1]],                                   # a plan rotation
    [[-1, 0, 0], [0, 1, 0], [0, 0, 1]],            # MirrorX
])
def test_a_rigid_map_keeps_the_revolution(lin):
    (d,) = _bent(_model().elements)[0].geometry.body_solids()
    moved = _moved(d, lin, (3.0, -2.0, 1.5))
    ex = exact_of(moved)
    assert ex is not None and ex["kind"] == "revolution"


def test_a_shear_drops_it():
    (d,) = _bent(_model().elements)[0].geometry.body_solids()
    sheared = _moved(d, [[1, 0, 0], [0, 1, 0], [0.1, 0, 1]], (0, 0, 0))
    assert "exact" not in sheared and exact_of(sheared) is None
