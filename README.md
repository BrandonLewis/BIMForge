# bimforge

A standalone CAD/BIM toolkit in Python: measure 2D plan sheets, author
parametric IFC models, roll them up into quantities, stage them in 4D/5D, and
produce control, layout and structure sheets.

- **`bimforge.bim`** — DXF → IFC authoring (IFC4X3 by default, exact
  extrusions and alignment sweeps), IFC → quantity takeoff, plan-sheet
  calibration and vector measurement, georeferencing, 3D KML/KMZ for Google
  Earth, 4D schedule embed/read-back (`IfcWorkSchedule`) and 5D cost and
  resource loading (`IfcCostSchedule`). Schedule readers for GanttWarrior JSON,
  Primavera P6 XER and MS Project MSPDI live here too.
- **`bimforge.author`** — the structure-family kernel: alignments, section
  prisms, battered walls, reinforcing bars, plates, saddles, spillways,
  standard-plan families, with quantities taken from the emitted geometry and
  never from a parallel formula.
- **`bimforge.sheets`** and **`bimforge.cad`** — sheet production and the
  org-neutral DXF/KML/geo engine, styled by pluggable **style packs**.
- **`bimforge.terrain`** — terrain grids, watertight terrain solids and
  excavation carves from point clouds and contours.
- **`bimforge.blender`** — Blender add-ons. *Alignment Section* puts a station
  slider in the 3D view sidebar that cuts a live cross-section along an IFC4X3
  `IfcAlignment` (see below).

## Install

```bash
pip install bimforge            # IFC stack included (ifcopenshell, ezdxf, shapely, pyproj, numpy)
pip install 'bimforge[all]'     # + PDF plan sheets, matplotlib drawing, build123d exact solids
pip install 'bimforge[terrain]' # + point-cloud / mesh terrain
```

Two CLIs ship with the package:

```bash
est-bim --help      # dxf2bim, ifc2dxf, takeoff, schedule, cost5d, kml, calibrate, measure, build, ...
est-sheets --help   # control / layout / structure sheet production
```

## Blender: alignment section slider

```bash
python -m bimforge.blender        # writes bimforge_alignment_section.zip
```

In Blender 4.2+ install the zip from *Edit > Preferences > Add-ons > Install
from Disk*. It needs ifcopenshell inside Blender, which Bonsai provides. Then
go to *3D View > Sidebar (N) > Section*, pick **Bonsai** (the IFC Bonsai has
open) or **File**, and press **Load Alignments**. Drag **Station** to slide the
section. You can also step by a fixed interval or type a station and press
**Go**. **View Section** looks through an orthographic camera whose near clip
sits on the cut. Every mesh is cut at the plane, and the cut is filled into
*Section Cut*. Each item is filled per its own styling: its material's
colour, which is the IFC surface style when Bonsai loaded it. An unstyled
item (no material, or the default grey) is filled by what its material or
object name says it is: concrete, rebar, asphalt, gravel, steel, timber or
earthwork. **Single colour** switches back to one highlight colour. The panel reports station, grade elevation, grade and bearing.
With **Follow timeline** on, frames sweep the whole alignment, so rendering
the animation makes a fly-through. Stations read in feet when the project is
in feet or its map conversion is to a feet grid.

## Style packs

CAD styling (title-block borders, layer colours, KML and IFC surface styles)
comes from a *style pack*: a package or directory with `templates/*.dxf` and an
optional `styles.yaml`. Resolution is explicit argument → registered providers
→ built-in neutral defaults. Any installed distribution can register a provider
through the `bimforge.style_packs` entry-point group (a zero-argument callable
returning a pack spec or `None`).

## Fixture provenance

Test fixtures cite public sources or derive their quantities in-repo. They
carry no employer bid numbers and no working-directory paths, and CI's
de-org scan refuses a change that adds one.

## License

Apache-2.0. See `LICENSE` and `NOTICE`. Security reports: `SECURITY.md`.
