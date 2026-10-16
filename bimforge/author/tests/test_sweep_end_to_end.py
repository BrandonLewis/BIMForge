"""End-to-end: a curved, superelevated, cambered sweep through
run_pre -> emit_ifc + emit_dxf -> run_post (spec 3.6)."""
import math
import uuid

import pytest

pytest.importorskip("ifcopenshell")

from bimforge.author.alignment import Alignment, Profile
from bimforge.author.emit_dxf import emit_dxf
from bimforge.author.emit_ifc import emit_ifc
from bimforge.author.gate import run_post, run_pre
from bimforge.author.model import Element, StructureModel
from bimforge.author.paycodes import apply as pc_apply
from bimforge.author.paycodes import from_dict
from bimforge.author.project import ProjectContext
from bimforge.author.sweep import SweptSection

PC = from_dict({
    "project_ref": "sweep-fixture",
    "rules": [{"match": "(?i)deck", "group": "deck"}],
    "groups": {"deck": {"measure": "GrossVolume"}},
    "codes": {"BR-CONC": {"group": "deck", "measure": "GrossVolume",
                          "unit": "CY", "item_number": "0510",
                          "description": "Structural concrete, bridge"}},
})


def _model():
    ctx = ProjectContext(name="Fixture Curved Structure", epsg=2226,
                         base_e=6_594_000.0, base_n=1_943_000.0, base_h=100.0,
                         guid_ns=uuid.UUID(
                             "1f7c9a2e-3b5d-4c88-8a20-6e1d2b4f7a90"))
    al = Alignment(
        {"station": 1000.0, "northing": 1_943_000.0, "easting": 6_594_000.0},
        [{"kind": "tangent", "bearing": "N 15-0-0 E", "length": 60.0},
         {"kind": "curve", "delta": "40-0-0", "radius": 500.0, "turn": "R",
          "length": math.pi * 500.0 * 40.0 / 180.0},
         {"kind": "curve", "delta": "25-0-0", "radius": 250.0, "turn": "R",
          "length": math.pi * 250.0 * 25.0 / 180.0},
         {"kind": "tangent", "bearing": "N 80-0-0 E", "length": 40.0}])
    prof = Profile([{"bvc_station": 1000.0, "bvc_elev": 130.0,
                     "g_in_pct": 1.5, "g_out_pct": -1.5, "length_ft": 300.0,
                     "evc_station": 1300.0, "evc_elev": 130.0}])
    s0, s1 = 1010.0, al.s_end - 10.0
    deck = SweptSection(
        "fixture deck", [(-8.0, -1.0), (8.0, -1.0), (8.0, 0.0), (-8.0, 0.0)],
        al, s0, s1, profile=prof,
        roll=[(s0, 0.0), ((s0 + s1) / 2.0, 0.06), (s1, 0.06)],
        camber=[(s0, 0.0), ((s0 + s1) / 2.0, 0.2), (s1, 0.0)],
        ifc="IfcSlab", layer="S-CONC-OTLN",
        # `origin` is what makes the emitted geometry LOCAL to the project
        # base. Without it this end-to-end fixture authored a deck at raw
        # State Plane coordinates and still passed every gate — the #156
        # blind spot, in the very test meant to cover the whole pipeline.
        origin=ctx)
    m = StructureModel("sweep-fixture", ctx)
    m.add(Element.from_geometry(
        deck.name, deck, ifc_class="IfcSlab", layer=deck.layer,
        quantities={"length_ft": deck.length_ft,
                    "volume_cf": deck.volume_cf}))
    m.stated_quantities.append(
        ("deck faceted vs declared", deck.faceted_volume_cf,
         deck.volume_cf, abs(deck.volume_cf) * 0.005))
    pc_apply(m, PC)
    return m


def test_pre_gate_passes():
    m = _model()
    rep = run_pre(m, PC)
    assert rep.passed, rep.format()


def test_emit_and_post_gate(tmp_path):
    m = _model()
    assert run_pre(m, PC).passed
    ifc = tmp_path / "sweep.ifc"
    dxf = tmp_path / "sweep.dxf"
    emit_ifc(m, str(ifc), PC)
    emit_dxf(m, str(dxf))
    rep = run_post(m, {"ifc": str(ifc), "dxf": str(dxf)}, PC)
    assert rep.passed, rep.format()
    assert ifc.exists() and dxf.exists()   # pass -> outputs kept


def test_pre_gate_refuses_wrong_stated_quantity():
    m = _model()
    m.stated_quantities.append(("sabotage", 1.0, 2.0, 0.001))
    rep = run_pre(m, PC)
    assert not rep.passed


def test_post_gate_deletes_outputs_when_declared_volume_is_wrong(tmp_path):
    # proves the post-emit mesh check is NOT vacuously skipping this
    # element (it matches by name and measures 0.053% against the 0.50%
    # band on the honest model): inflating the declared volume 20% must
    # fail the gate AND delete both outputs.
    m = _model()
    ifc = tmp_path / "bad.ifc"
    dxf = tmp_path / "bad.dxf"
    emit_ifc(m, str(ifc), PC)
    emit_dxf(m, str(dxf))
    m.element("fixture deck").quantities["volume_cf"] *= 1.2
    rep = run_post(m, {"ifc": str(ifc), "dxf": str(dxf)}, PC)
    assert not rep.passed
    assert "IFC mesh volume" in rep.failures[0]
    assert not ifc.exists() and not dxf.exists()
