"""bimforge.terrain — site-context terrain acquisition, datum, solid, provenance.

Public API is re-exported here as modules land (grid, fetch, datum, solid,
provenance, attach, contours, diff).
"""

from .attach import attach_terrain
from .contours import (ContourTIN, assign_lettered, build_adjacency,
                       build_tin, merge_fragments, propagate, sample_tin,
                       score_against_spots, score_stats, tin_provenance)
from .datum import geoid_shift_m, ncat_vertshift
from .diff import diff_surface, plot_diff, sample_grid, write_diff_csv
from .fetch import bin_points, fetch_3dep_dem, fetch_3dep_lpc, workunit_meta
from .grid import TerrainGrid, fill_nodata, grid_to_mesh
from .provenance import build_provenance
from .solid import carve, close_surface, frustum

__all__ = [
    "TerrainGrid", "fill_nodata", "grid_to_mesh",
    "bin_points", "fetch_3dep_dem", "fetch_3dep_lpc", "workunit_meta",
    "ncat_vertshift", "geoid_shift_m",
    "build_provenance",
    "close_surface", "frustum", "carve",
    "attach_terrain",
    "ContourTIN", "merge_fragments", "assign_lettered", "build_adjacency",
    "propagate", "build_tin", "sample_tin", "score_against_spots",
    "score_stats", "tin_provenance",
    "sample_grid", "diff_surface", "write_diff_csv", "plot_diff",
]
