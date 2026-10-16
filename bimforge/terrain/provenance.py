"""Terrain provenance — the Pset dict that rides the terrain element.

Terrain is reference geometry: no pay code, no Qto, SurveyGrade False. What
it DOES carry is where it came from - source product, source CRS, work-unit
acquisition vintage and quality level, the applied vertical-datum shift, the
mesh spacing, and whether the excavation was carved into it.
"""

from __future__ import annotations


def build_provenance(source, info, workunit, shift_m, spacing_m, carved):
    """Assemble the terrain provenance Pset dict.

    ``source`` is ``"dem"`` or ``"lpc"`` and selects the source block;
    ``info`` is the fetcher's metadata dict (LPC: ``project``/``publication``;
    either: ``crs_epsg`` or a preformatted ``crs`` string); ``workunit`` is
    the 3DEP work-unit vintage dict from ``workunit_meta`` (``{}`` when the
    index was unreachable - its keys are then omitted, the build continues);
    ``shift_m`` is the applied ``out_vert -> project`` vertical shift
    (recorded negated: the mesh moved by ``-shift_m``); ``carved`` echoes
    whether the excavation boolean produced a closed carved solid.
    """
    crs = info.get("crs") or (
        f"EPSG:{info['crs_epsg']} / EPSG:5703" if info.get("crs_epsg") else "")
    if source == "lpc":
        prov = {
            "Source": "USGS 3DEP Lidar Point Cloud (LPC)",
            "SourceProject": info.get("project", ""),
            "PublicationDate": info.get("publication", ""),
            "SourceCRS": crs,
            "Classification": "ASPRS class 2 (bare earth), mean return per "
                              "cell; classes 7/18 (noise) dropped",
        }
    else:
        prov = {
            "Source": "USGS 3DEP 1m DEM",
            "SourceService": "3DEPElevation ImageServer exportImage",
            "SourceCRS": crs,
        }
    if workunit:
        # Both the DEM and the LPC over a site derive from the SAME work
        # unit, so one authoritative vintage stamps either path.
        prov.setdefault("SourceProject", workunit.get("project", ""))
        prov["SourceWorkUnit"] = workunit.get("workunit", "")
        prov["AcquisitionStart"] = workunit.get("collect_start", "")
        prov["AcquisitionEnd"] = workunit.get("collect_end", "")
        prov["QualityLevel"] = workunit.get("ql", "")   # e.g. QL2 ~2 pts/m^2
    prov.update({
        "SourceVerticalDatum": "NAVD88",
        "AppliedVerticalShift": -float(shift_m),  # to the project datum
        "MeshSpacing": float(spacing_m),
        "Carved": bool(carved),
        "License": "Public domain (US Government work)",
        "SurveyGrade": False,
    })
    return prov
