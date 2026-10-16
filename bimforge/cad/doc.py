"""Standard ezdxf document factory.

Civil/structural drawings open the same way — R2018, imperial units, feet, a
Civil-3D-safe ``romans.shx`` text style, and the default layer table. This
module captures that boilerplate as :func:`new_doc`.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

import ezdxf
from ezdxf import units

from .layers import DEFAULT_LAYERS, LayerDef, add_layers

if TYPE_CHECKING:
    from ezdxf.document import Drawing

#: Font for the ``STANDARD`` style — an SHX shipped with AutoCAD/Civil 3D, so
#: drawings open without a missing-font substitution prompt.
STANDARD_FONT = "romans.shx"

#: Default CIVIL dimension-style settings (from the box-culvert template).
CIVIL_DIMSTYLE = dict(
    dimtxt=0.28, dimasz=0.20, dimblk="ARCHTICK", dimdle=0.08, dimexo=0.08,
    dimexe=0.10, dimdec=2, dimtad=1, dimgap=0.08, dimclrd=3, dimclre=3,
    dimclrt=2,
)


def new_doc(
    *,
    ltscale: float = 1.0,
    dwg_version: str = "R2018",
    layers: "Optional[tuple[LayerDef, ...]]" = DEFAULT_LAYERS,
    add_dimstyle: bool = True,
    text_size: Optional[float] = None,
) -> "Drawing":
    """Create a new ezdxf drawing configured to these conventions.

    Sets imperial feet units (``$INSUNITS = FT``, ``$MEASUREMENT = 0``), the
    given global linetype scale, a ``romans.shx`` ``STANDARD`` style plus
    ``NOTES``/``TITLE`` (Arial) styles, optionally a ``CIVIL`` dimension style,
    and stamps the default layer table.

    Args:
        ltscale: Global linetype scale (``$LTSCALE``). Site-scale plan drawings
            in feet often use larger values (Milton used 40); detail sheets use
            1-5.
        dwg_version: ezdxf/AutoCAD version string (default ``"R2018"``).
        layers: Layer table to create, or ``None`` to skip. Defaults to
            :data:`bimforge.cad.layers.DEFAULT_LAYERS`.
        add_dimstyle: If true, register the :data:`CIVIL_DIMSTYLE` dimension
            style.
        text_size: If given, set ``$TEXTSIZE`` (default text height in feet).

    Returns:
        The configured drawing. Get its modelspace with ``doc.modelspace()``.
    """
    doc = ezdxf.new(dwg_version, setup=True)
    doc.header["$INSUNITS"] = units.FT
    doc.header["$LTSCALE"] = ltscale
    doc.header["$MEASUREMENT"] = 0            # imperial
    if text_size is not None:
        doc.header["$TEXTSIZE"] = text_size

    # STANDARD -> Civil-3D-safe SHX; NOTES/TITLE -> TrueType Arial where present.
    if "STANDARD" in doc.styles:
        doc.styles.get("STANDARD").dxf.font = STANDARD_FONT
    else:
        doc.styles.add("STANDARD", font=STANDARD_FONT)
    for style in ("NOTES", "TITLE"):
        try:
            doc.styles.add(style, font="Arial.ttf")
        except Exception:
            # Duplicate or unavailable font: leave the drawing usable regardless.
            pass

    if add_dimstyle:
        ds = doc.dimstyles.new("CIVIL")
        for key, value in CIVIL_DIMSTYLE.items():
            setattr(ds.dxf, key, value)
        ds.dxf.dimtxsty = "NOTES"

    if layers:
        add_layers(doc, layers)

    return doc
