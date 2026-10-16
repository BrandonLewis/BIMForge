import pytest

from bimforge.author.type_836_section import type_836_section
from bimforge.author.barrier_section import BarrierSection

_ROW = {  # mirrors TCB_836 in test_culvert_headwall.py
    "barrier_type": "836", "h_ft": 3.0, "per_standard_plan": "B11-80",
    "shape": "single_slope",
    "profile": [[0.0, 0.0], [1.5, 0.0], [0.5, 3.0], [0.0, 3.0]],
    "concrete_cf_per_lf": 3.908, "haunch_ft": 1.0,
}


def test_builds_barrier_section_from_row():
    sec = type_836_section(_ROW)
    assert isinstance(sec, BarrierSection)
    assert sec.barrier_type == "836"
    assert sec.top_z == pytest.approx(3.0)          # tallest profile z


def test_missing_shape_fails_loud():
    with pytest.raises(ValueError, match="shape"):
        type_836_section({"barrier_type": "836", "h_ft": 3.0})


def test_height_key_falls_back_to_height_ft():
    # h_ft absent -> the key must fall back to height_ft (a broken fallback would
    # yield sec.height == "None", not "3.0", so this assertion actually bites).
    sec = type_836_section({"barrier_type": "836", "height_ft": 3.0,
                            "shape": "single_slope",
                            "profile": [[0.0, 0.0], [1.5, 0.0], [0.0, 3.0]]})
    assert sec.height == "3.0"


def test_explicit_none_h_ft_falls_back_to_height_ft():
    # `h_ft: null` in yaml parses to None; dict.get returns that None (it only
    # short-circuits on a MISSING key), so a naive `row.get("h_ft", ...)` would
    # yield sec.height == "None". None must be treated as absent.
    sec = type_836_section({"barrier_type": "836", "h_ft": None,
                            "height_ft": 3.0, "shape": "single_slope",
                            "profile": [[0.0, 0.0], [1.5, 0.0], [0.0, 3.0]]})
    assert sec.height == "3.0"
