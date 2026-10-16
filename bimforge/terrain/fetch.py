"""USGS 3DEP acquisition: DEM raster, lidar point cloud (LPC), work-unit meta.

3DEP is public domain, so its terrain can ride inside a deliverable IFC.
All transport goes through the module-level `_urlopen` / `_urlretrieve`
helpers (stdlib urllib — no requests dependency) so tests monkeypatch one
seam and warm caches keep rebuilds offline and deterministic. Heavy decoders
(Pillow for the DEM GeoTIFF, laspy for LAZ tiles) import at call time;
a missing one raises a RuntimeError naming the ``bimforge[terrain]`` extra.
Ported from the bridge-pilot build_bridge.py terrain arc.
"""
from __future__ import annotations

from pathlib import Path

from .grid import TerrainGrid, fill_nodata

DEM_URL = ("https://elevation.nationalmap.gov/arcgis/rest/services/"
           "3DEPElevation/ImageServer/exportImage")
TNM_URL = "https://tnmaccess.nationalmap.gov/api/v1/products"
INDEX_URL = ("https://index.nationalmap.gov/arcgis/rest/services/"
             "3DEPElevationIndex/MapServer/8/query")


def _urlopen(url, timeout):
    """The transport seam: stdlib urlopen. Tests monkeypatch THIS."""
    import urllib.request
    return urllib.request.urlopen(url, timeout=timeout)


def _urlretrieve(url, path):
    """The bulk-download seam (LAZ tiles). Tests monkeypatch THIS."""
    import urllib.request
    urllib.request.urlretrieve(url, str(path))


def fetch_3dep_dem(bbox_m, spacing_m, crs_epsg, cache_path, refresh=False,
                   log=print):
    """TerrainGrid of NAVD88-metre elevations over a metric `bbox_m` in the
    project CRS (`crs_epsg`). Requests the DEM straight in the project CRS
    (server-side reprojection — no client-side resampling or axis-order
    traps) as a float32 GeoTIFF and reads it with Pillow. The raw TIFF is
    cached so rebuilds are offline and deterministic; refresh=True refetches.

    Pillow does not expose the GeoTIFF geotransform tags, so pixels are
    mapped from the REQUESTED bbox (the service honours size with
    adjustAspectRatio off). Fine for SurveyGrade-FALSE context terrain; swap
    in tifffile to read the true geotransform if survey-tight fidelity is
    ever needed.
    """
    import io
    import time
    import urllib.parse
    import numpy as np
    try:
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            "Pillow is required to decode the 3DEP DEM GeoTIFF — "
            'pip install "bimforge[terrain]"') from e
    cache_path = Path(cache_path)
    xmin, ymin, xmax, ymax = bbox_m
    cols = max(2, int(round((xmax - xmin) / spacing_m)))
    rows = max(2, int(round((ymax - ymin) / spacing_m)))
    if cache_path.exists() and not refresh:
        log(f"  terrain DEM: cache hit {cache_path.name}")
        raw = cache_path.read_bytes()
    else:
        q = {"bbox": f"{xmin},{ymin},{xmax},{ymax}", "bboxSR": str(crs_epsg),
             "imageSR": str(crs_epsg), "size": f"{cols},{rows}",
             "format": "tiff", "pixelType": "F32",
             "noDataInterpretation": "esriNoDataMatchAny",
             "interpolation": "RSP_BilinearInterpolation",
             "adjustAspectRatio": "false", "f": "image"}
        url = DEM_URL + "?" + urllib.parse.urlencode(q)
        raw = None
        for attempt in range(5):                       # 502s are common
            try:
                raw = _urlopen(url, 90).read()
                break
            except Exception as e:
                log(f"  terrain DEM: attempt {attempt + 1} failed ({e}); "
                    "retrying")
                time.sleep(2 * (attempt + 1))
        if raw is None:
            raise RuntimeError("3DEP DEM fetch failed after 5 attempts")
        cache_path.write_bytes(raw)
        log(f"  terrain DEM: fetched {len(raw) / 1024:.0f} KB -> "
            f"{cache_path.name}")
    z = np.asarray(Image.open(io.BytesIO(raw)), dtype="float64")
    return TerrainGrid(z=z, bbox_m=(xmin, ymin, xmax, ymax),
                       spacing_m=float(spacing_m), crs_epsg=int(crs_epsg),
                       info={})


def bin_points(E, N, Z, bbox_m, spacing_m):
    """Bin scattered returns into a `(rows, cols)` grid over `bbox_m`: the
    MEAN of the returns falling in each cell; empty cells are NaN; points
    outside the bbox are dropped.

    Mean, not lowest: the LPC path feeds this ASPRS class-2 (already
    classified ground) returns, so there is no vegetation to duck under, and
    the mean matches the DEM's interpolated surface — which keeps a
    cross-source DEM-vs-lidar comparison honest. Pure numpy so that decision
    stays testable without laspy.
    """
    import numpy as np
    xmin, ymin, xmax, ymax = bbox_m
    cols = max(2, int(round((xmax - xmin) / spacing_m)))
    rows = max(2, int(round((ymax - ymin) / spacing_m)))
    E = np.asarray(E, dtype="float64")
    N = np.asarray(N, dtype="float64")
    Z = np.asarray(Z, dtype="float64")
    col = ((E - xmin) / spacing_m).astype(int)
    row = ((ymax - N) / spacing_m).astype(int)
    inb = (col >= 0) & (col < cols) & (row >= 0) & (row < rows)
    idx = row[inb] * cols + col[inb]
    gsum = np.zeros(rows * cols)
    gcnt = np.zeros(rows * cols)
    np.add.at(gsum, idx, Z[inb])
    np.add.at(gcnt, idx, 1)
    grid = np.where(gcnt > 0, gsum / np.maximum(gcnt, 1), np.nan)
    return grid.reshape(rows, cols)


def fetch_3dep_lpc(bbox_m, spacing_m, crs_epsg, wgs_bbox, cache_stem,
                   refresh=False, log=print):
    """TerrainGrid of NAVD88-metre bare-earth elevations from 3DEP LIDAR
    point-cloud tiles, gridded to match the DEM path so everything downstream
    (solid, carve, IFC) is identical.

    Finds LAZ tiles via TNM Access (`wgs_bbox` is the "lonmin,latmin,lonmax,
    latmax" discovery string), reads ASPRS class-2 ground with laspy (only
    class 2 is selected, so noise classes 7/18 never enter), reprojects the
    horizontal CRS — read from the LAS header, never the filename; a
    filename-guessed CRS silently shifts the whole terrain, and compound
    CRSs unwrap to their horizontal member — into the project CRS
    (`crs_epsg`), and bins the MEAN class-2 return into each cell. Mean, not
    lowest: class-2 is already classified ground so there is no vegetation
    to duck under, and the mean matches the DEM's interpolated surface,
    which keeps cross-source comparison honest (see `bin_points`). The heavy
    LAZ tiles cache locally; the small gridded .npz is the reproducible
    artifact.
    """
    import json
    import urllib.parse
    import numpy as np
    grid_cache = Path(str(cache_stem) + f"-3DEP-LPC-grid-{spacing_m:g}m.npz")
    if grid_cache.exists() and not refresh:
        # info rides as a JSON string array — never allow_pickle on a
        # cache file whose path the caller controls.
        dd = np.load(grid_cache)
        log(f"  terrain LPC: cache hit {grid_cache.name}")
        return TerrainGrid(z=dd["z"],
                           bbox_m=(float(dd["xmin"]), float(dd["ymin"]),
                                   float(dd["xmax"]), float(dd["ymax"])),
                           spacing_m=float(spacing_m),
                           crs_epsg=int(crs_epsg),
                           info=json.loads(str(dd["info"])))
    try:
        import laspy
    except ImportError as e:
        raise RuntimeError(
            "laspy is required to read 3DEP LAZ tiles — "
            'pip install "bimforge[terrain]"') from e
    try:
        from pyproj import Transformer
    except ImportError as e:
        raise RuntimeError(
            "pyproj is required for LPC CRS transforms — "
            'pip install "bimforge[terrain]"') from e
    xmin, ymin, xmax, ymax = bbox_m
    q = {"bbox": wgs_bbox, "datasets": "Lidar Point Cloud (LPC)",
         "prodFormats": "LAZ", "max": 20, "outputFormat": "JSON"}
    items = json.loads(_urlopen(
        TNM_URL + "?" + urllib.parse.urlencode(q), 90).read()).get("items", [])
    if not items:
        raise RuntimeError("TNM Access returned no LPC tiles for the site")
    lpc_dir = Path(str(cache_stem) + "-LPC")
    lpc_dir.mkdir(exist_ok=True)
    project = items[0]["downloadURL"].split("/Projects/")[-1].split("/")[0]
    Es, Ns, Zs = [], [], []
    for it in items:
        fn = it["downloadURL"].split("/")[-1]
        p = lpc_dir / fn
        if not p.exists() or refresh:
            log(f"  terrain LPC: downloading {fn} "
                f"({it.get('sizeInBytes', 0) / 1e6:.0f} MB)")
            _urlretrieve(it["downloadURL"], p)
        las = laspy.read(str(p))
        crs = las.header.parse_crs()
        horiz = crs.sub_crs_list[0] if (crs and crs.is_compound) else crs
        # EPSG:6350 (CONUS Albers) is 3DEP LPC's standard delivery CRS — the
        # fallback when a header carries no CRS at all.
        to_prj = Transformer.from_crs(horiz or 6350, crs_epsg, always_xy=True)
        cl = np.asarray(las.classification)
        g = cl == 2                                     # ASPRS ground
        E, N = to_prj.transform(np.asarray(las.x)[g], np.asarray(las.y)[g])
        Es.append(np.asarray(E))
        Ns.append(np.asarray(N))
        Zs.append(np.asarray(las.z)[g])                 # NAVD88 m
    grid = bin_points(np.concatenate(Es), np.concatenate(Ns),
                      np.concatenate(Zs), bbox_m, spacing_m)
    z = fill_nodata(grid)
    rows, cols = z.shape
    info = {"project": project, "tiles": len(items),
            "publication": items[0].get("publicationDate", "")}
    np.savez_compressed(grid_cache, z=z, xmin=xmin, ymin=ymin,
                        xmax=xmax, ymax=ymax, info=json.dumps(info))
    log(f"  terrain LPC: {len(items)} tile(s) {project}, class-2 gridded "
        f"{rows}x{cols} @ {spacing_m:g} m -> {grid_cache.name}")
    return TerrainGrid(z=z, bbox_m=(xmin, ymin, xmax, ymax),
                       spacing_m=float(spacing_m), crs_epsg=int(crs_epsg),
                       info=info)


def workunit_meta(lon, lat, cache_path, log=print):
    """Acquisition vintage and quality of the 3DEP work unit covering
    (lon, lat), from the USGS 3DEP elevation index. Both the DEM and the LPC
    over a site derive from the SAME work unit, so this stamps one
    authoritative vintage into either path. Cached; returns {} (and the
    build still runs) if the index is unreachable.
    """
    import json
    import urllib.parse
    cache_path = Path(cache_path)
    if cache_path.exists():
        return json.loads(cache_path.read_text())
    meta = {}
    try:
        import datetime
        q = {"geometry": f"{lon},{lat}",
             "geometryType": "esriGeometryPoint", "inSR": "4326",
             "spatialRel": "esriSpatialRelIntersects",
             "outFields": "project,workunit,collect_start,collect_end,ql",
             "returnGeometry": "false", "f": "json"}
        d = json.loads(_urlopen(
            INDEX_URL + "?" + urllib.parse.urlencode(q), 30).read())
        fs = d.get("features", [])
        if fs:
            a = fs[0]["attributes"]

            def day(ms):
                return (datetime.datetime.fromtimestamp(
                    ms / 1000, datetime.timezone.utc).strftime("%Y-%m-%d")
                    if ms else "")

            meta = {"project": a.get("project", ""),
                    "workunit": a.get("workunit", ""),
                    "collect_start": day(a.get("collect_start")),
                    "collect_end": day(a.get("collect_end")),
                    "ql": a.get("ql", "")}
    except Exception as e:
        log(f"  terrain: 3DEP index lookup skipped ({e})")
    cache_path.write_text(json.dumps(meta))
    if meta:
        log(f"  terrain: 3DEP work unit {meta['workunit']} collected "
            f"{meta['collect_start']}..{meta['collect_end']} {meta['ql']}")
    return meta
