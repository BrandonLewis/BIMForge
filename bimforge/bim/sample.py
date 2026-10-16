"""Generate a small sample DXF so the DXF -> BIM -> takeoff pipeline runs
out of the box (paired with the shipped example layer/takeoff maps).

Coordinates are in millimetres and offset to a realistic survey-like origin
so the georeferencing / base-point handling gets exercised. Layers:
  A-SLAB   closed polyline (area)  -> IfcSlab
  A-WALL   open polyline  (linear) -> IfcWall
  C-CURB   line           (linear) -> IfcBuildingElementProxy
  A-HATCH  hatch          (area)   -> IfcCovering
  E-COL    block inserts  (count)  -> IfcColumn
"""
from __future__ import annotations

import ezdxf

# survey-ish origin (mm) so geometry isn't at 0,0
OX, OY = 500_000_000, 4_100_000_000  # ~ easting/northing in mm


def write_sample_dxf(out_path: str = "sample_plan.dxf") -> str:
    """Write the sample plan DXF to `out_path` and return the path."""
    doc = ezdxf.new("R2010")
    msp = doc.modelspace()
    for name in ("A-SLAB", "A-WALL", "C-CURB", "A-HATCH", "E-COL"):
        doc.layers.add(name)

    # A 10m x 6m slab (mm)
    slab = [(0, 0), (10000, 0), (10000, 6000), (0, 6000)]
    msp.add_lwpolyline([(OX + x, OY + y) for x, y in slab],
                       close=True, dxfattribs={"layer": "A-SLAB"})

    # An L-shaped wall run (open polyline)
    wall = [(0, 0), (10000, 0), (10000, 6000)]
    msp.add_lwpolyline([(OX + x, OY + y) for x, y in wall],
                       dxfattribs={"layer": "A-WALL"})

    # A curb as a single LINE
    msp.add_line((OX + 0, OY + 6000), (OX + 10000, OY + 6000),
                 dxfattribs={"layer": "C-CURB"})

    # A 3m x 2m hatched area (finish/covering)
    hpts = [(1000, 1000), (4000, 1000), (4000, 3000), (1000, 3000)]
    hatch = msp.add_hatch(dxfattribs={"layer": "A-HATCH"})
    hatch.paths.add_polyline_path([(OX + x, OY + y) for x, y in hpts], is_closed=True)

    # A column block, inserted 4 times (count takeoff)
    blk = doc.blocks.new(name="COL")
    blk.add_circle((0, 0), 150)
    for gx, gy in [(0, 0), (10000, 0), (10000, 6000), (0, 6000)]:
        msp.add_blockref("COL", (OX + gx, OY + gy), dxfattribs={"layer": "E-COL"})

    doc.saveas(out_path)
    return out_path
