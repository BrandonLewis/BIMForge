"""Kernel ops: station line drawing + wingwall section helper."""
import pytest

pytest.importorskip("ezdxf")
import ezdxf

from bimforge.author.alignment import Alignment
from bimforge.author.ops import station_line, wingwall_section

AL = Alignment({"station": 0.0, "northing": 0.0, "easting": 0.0},
               [{"kind": "tangent", "bearing": "N 0-0-0 E", "length": 250.0}])


def test_station_line_draws_polyline_ticks_labels():
    doc = ezdxf.new("R2018")
    msp = doc.modelspace()
    drawn = station_line(msp, AL, 0.0, 250.0, tick_interval=100.0)
    kinds = [e.dxftype() for e in msp]
    assert kinds.count("LWPOLYLINE") == 1
    assert kinds.count("LINE") == 3          # ticks at 0+00, 1+00, 2+00
    texts = [e.dxf.text for e in msp if e.dxftype() == "TEXT"]
    assert texts == ["0+00.00", "1+00.00", "2+00.00"]
    assert drawn == 1 + 3 * 2


TABLES = {"type_1_case_1": {"stem_top_thickness_ft": 1.0, "table": {
    8: {"W_ft": 6.0, "C_ft": 2.0, "B_ft": 4.0, "F_ft": 1.0, "T_ft": 1.0,
        "batter": "NONE"}}}}


def test_wingwall_section_prisms():
    foot, stem = wingwall_section(AL, TABLES, 1, 8.0, 0.0, 10.0, "Lt",
                                  ft_top=100.0)
    assert foot.volume_cf == pytest.approx(10.0 * 6.0 * 1.0)
    assert stem.volume_cf == pytest.approx(10.0 * 1.0 * 8.0)
    assert stem.z_bot == 100.0 and stem.z_top == 108.0
