"""Tests for terrain/provenance.py — Pset dict assembly (pure, offline)."""

import pytest

from bimforge.terrain.provenance import build_provenance


def test_dem_source_block_no_workunit():
    prov = build_provenance("dem", {"crs_epsg": 26910}, {}, 0.712, 3.0, False)

    assert prov["Source"] == "USGS 3DEP 1m DEM"
    assert prov["SourceService"] == "3DEPElevation ImageServer exportImage"
    assert prov["SourceCRS"] == "EPSG:26910 / EPSG:5703"
    # DEM block never carries the LPC-only keys.
    assert "Classification" not in prov
    assert "PublicationDate" not in prov
    # Empty workunit adds no vintage keys.
    assert "SourceWorkUnit" not in prov
    assert "AcquisitionStart" not in prov
    assert "AcquisitionEnd" not in prov
    assert "QualityLevel" not in prov
    # Common tail.
    assert prov["SourceVerticalDatum"] == "NAVD88"
    assert prov["AppliedVerticalShift"] == pytest.approx(-0.712)
    assert prov["MeshSpacing"] == 3.0
    assert prov["Carved"] is False
    assert prov["SurveyGrade"] is False
    assert "Public domain" in prov["License"]


def test_lpc_source_block_with_workunit():
    info = {"project": "OR_Example_2020", "publication": "2021-05-01",
            "crs_epsg": 26910}
    wu = {"project": "OR_Example_2020_B20", "workunit": "OR_Example_1",
          "collect_start": "2020-06-01", "collect_end": "2020-08-15",
          "ql": "QL2"}
    prov = build_provenance("lpc", info, wu, 0.5, 1.0, True)

    assert prov["Source"] == "USGS 3DEP Lidar Point Cloud (LPC)"
    # info's project wins over the workunit's (setdefault semantics).
    assert prov["SourceProject"] == "OR_Example_2020"
    assert prov["PublicationDate"] == "2021-05-01"
    assert "ASPRS class 2" in prov["Classification"]
    assert prov["SourceCRS"] == "EPSG:26910 / EPSG:5703"
    # Workunit vintage keys present when workunit non-empty.
    assert prov["SourceWorkUnit"] == "OR_Example_1"
    assert prov["AcquisitionStart"] == "2020-06-01"
    assert prov["AcquisitionEnd"] == "2020-08-15"
    assert prov["QualityLevel"] == "QL2"
    assert prov["AppliedVerticalShift"] == pytest.approx(-0.5)
    assert prov["MeshSpacing"] == 1.0
    assert prov["Carved"] is True
    assert prov["SurveyGrade"] is False


def test_dem_workunit_fills_source_project():
    wu = {"project": "WA_Sample_2019", "workunit": "WA_Sample_2",
          "collect_start": "2019-04-01", "collect_end": "2019-05-30",
          "ql": "QL1"}
    prov = build_provenance("dem", {}, wu, 0.0, 3.0, False)
    # DEM block has no SourceProject of its own; the workunit supplies it.
    assert prov["SourceProject"] == "WA_Sample_2019"
    assert prov["SourceWorkUnit"] == "WA_Sample_2"
    assert prov["QualityLevel"] == "QL1"


def test_source_crs_falls_back_to_info_crs_string():
    prov = build_provenance("dem", {"crs": "EPSG:32610"}, {}, 0.0, 3.0, False)
    assert prov["SourceCRS"] == "EPSG:32610"
    prov = build_provenance("dem", {}, {}, 0.0, 3.0, False)
    assert prov["SourceCRS"] == ""
