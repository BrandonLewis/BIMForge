"""Canonical default layer table and layer-creation helper.

Layer names follow the U.S. National CAD Standard discipline-major-minor scheme
(``S-CONC-OTLN``, ``C-ROAD-CNTR``, ``V-CTRL-PNTS`` ...). Each entry carries an
AutoCAD Color Index, an optional linetype, and a lineweight in 1/100 mm.

Use :func:`add_layers` to stamp a table onto a document. :data:`DEFAULT_LAYERS` is
the merged default; the per-discipline subsets (:data:`STRUCT_LAYERS`,
:data:`CIVIL_LAYERS`, :data:`ELEV_LAYERS`) are provided for scripts that only
want part of the table. Org-specific tables come from style packs
(:mod:`bimforge.cad.stylepack`), not from edits here.
"""
from __future__ import annotations

from typing import NamedTuple, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ezdxf.document import Drawing


class LayerDef(NamedTuple):
    """One layer: name, ACI color, optional linetype, lineweight (1/100 mm)."""

    name: str
    color: int
    linetype: Optional[str] = None
    lineweight: int = 18


# --- Structural concrete / foundations / piles / rails ----------------------
STRUCT_LAYERS: tuple[LayerDef, ...] = (
    LayerDef("S-CONC-OTLN", 5, None, 50),        # concrete outline
    LayerDef("S-CONC-PATT", 252, None, 9),       # concrete hatch pattern
    LayerDef("S-CONC-PRPT", 30, None, 50),       # parapet outline
    LayerDef("S-CONC-DECK", 5, None, 50),
    LayerDef("S-CONC-BARR", 2, None, 35),
    LayerDef("S-CONC-CAP", 1, None, 50),
    LayerDef("S-CONC-ABUT", 4, None, 50),
    LayerDef("S-CONC-WWAL", 6, None, 35),
    LayerDef("S-FNDN-OTLN", 8, "DASHED", 18),    # footing / foundation outline
    LayerDef("S-PILE", 4, None, 35),             # piles (generic)
    LayerDef("S-PILE-VERT", 4, None, 35),        # vertical piles
    LayerDef("S-PILE-BATR", 6, None, 35),        # battered piles
    LayerDef("S-PILE-CISS", 2, None, 35),        # CISS / CIDH piles
    LayerDef("S-WALL-WING", 210, None, 35),      # wingwall
    LayerDef("S-WALL-BKWL", 40, None, 35),       # backwall
    LayerDef("S-BRDG-DECK", 8, "DASHED", 25),
    LayerDef("S-RAIL", 4, None, 25),             # railing / parapet rail
    LayerDef("S-RAIL-CABL", 3, None, 25),        # cable railing
    LayerDef("S-CNTR", 6, "CENTER", 9),          # structure centerline
    LayerDef("S-HIDN", 8, "DASHED", 13),         # hidden lines
)

# --- Civil alignment / survey / annotation ----------------------------------
CIVIL_LAYERS: tuple[LayerDef, ...] = (
    LayerDef("C-ROAD-CNTR", 1, "CENTER", 9),     # alignment centerline
    LayerDef("C-ANNO-STAN", 3, None, 18),        # station ticks + labels
    LayerDef("C-ANNO-TEXT", 2),                  # control-point / general annotation
    LayerDef("C-MON", 3, None, 25),              # survey monuments / ties
    LayerDef("V-CTRL-PNTS", 7, None, 25),        # survey control points
    LayerDef("G-GRID", 9, "CENTER", 9),          # coordinate grid
    LayerDef("S-ANNO-TEXT", 2, None, 18),        # general text
    LayerDef("S-ANNO-DIMS", 3, None, 18),        # dimensions
    LayerDef("S-ANNO-SYMB", 2, None, 25),        # symbols / viewports / north arrow
)

# --- Developed / true elevation views ---------------------------------------
ELEV_LAYERS: tuple[LayerDef, ...] = (
    LayerDef("S-ELEV-GRID", 8, None, 9),         # datum / station ticks
    LayerDef("S-ELEV-OTLN", 5, None, 50),        # structure outline
    LayerDef("S-ELEV-PILE", 6, None, 35),
    LayerDef("S-ELEV-WATR", 4, "DASHED", 18),    # water surface / scour
    LayerDef("S-ELEV-TEXT", 2, None, 18),
)


def _merge(*groups: tuple[LayerDef, ...]) -> tuple[LayerDef, ...]:
    """Concatenate layer groups, keeping the first definition of each name."""
    seen: dict[str, LayerDef] = {}
    for group in groups:
        for layer in group:
            seen.setdefault(layer.name, layer)
    return tuple(seen.values())


#: The full merged default layer table (structural + civil + elevation).
DEFAULT_LAYERS: tuple[LayerDef, ...] = _merge(STRUCT_LAYERS, CIVIL_LAYERS, ELEV_LAYERS)


def add_layers(doc: "Drawing", layers: "tuple[LayerDef, ...]" = DEFAULT_LAYERS) -> None:
    """Create every layer in ``layers`` on ``doc`` (skips names already present).

    Args:
        doc: An open ezdxf drawing.
        layers: Layer definitions to add; defaults to :data:`DEFAULT_LAYERS`.
    """
    existing = {layer.dxf.name for layer in doc.layers}
    for ld in layers:
        if ld.name in existing:
            continue
        kwargs: dict[str, object] = {"color": ld.color, "lineweight": ld.lineweight}
        if ld.linetype:
            kwargs["linetype"] = ld.linetype
        doc.layers.add(ld.name, **kwargs)
