"""One-call sheet composition: title block layout + fitted viewport.

The viewport window defaults suit each bundled border; callers can override.
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

from bimforge.cad.titleblock import SHEET_SIZES, TitleBlockFields, apply_title_block
from bimforge.cad.viewport import ARCH_D_WINDOW, Extents, add_fitted_viewport

if TYPE_CHECKING:
    from ezdxf.document import Drawing
    from ezdxf.layouts import Layout

#: viewport window (center, size) in paper inches per sheet size — inside the border
SHEET_WINDOWS: dict[str, dict[str, tuple[float, float]]] = {
    "ARCH_D": dict(ARCH_D_WINDOW),
    "11x17": {"center": (5.5, 8.5), "size": (9.5, 13.0)},
}


def compose_sheet(
    doc: "Drawing",
    *,
    size: str,
    fields: TitleBlockFields,
    layout_name: str,
    extents: Extents,
    scale: Optional[float] = None,
    window: Optional[dict[str, tuple[float, float]]] = None,
    library: Optional[str] = None,
) -> "Layout":
    """Create a paperspace layout with the border and a fitted viewport.

    Combines :func:`bimforge.cad.titleblock.apply_title_block` and
    :func:`bimforge.cad.viewport.add_fitted_viewport` into a single call: stamp the
    border for ``size`` onto a new layout named ``layout_name``, then add
    a viewport centred on ``extents`` and sized per ``scale``.

    Args:
        doc: An open ezdxf drawing.
        size: A key of :data:`bimforge.cad.titleblock.SHEET_SIZES` (``"11x17"`` or
            ``"ARCH_D"``).
        fields: Text to stamp into the title block.
        layout_name: Name for the new paperspace layout.
        extents: World-coordinate bounds ``(min_x, min_y, max_x, max_y)`` of
            the geometry to frame (e.g. from :func:`bimforge.cad.viewport.bbox`).
        scale: Drawing scale as paper-inch per world-foot (e.g. ``1/30`` for
            1" = 30'). If ``None`` (default), the viewport auto-fits
            ``extents`` to the paper window.
        window: Override for the viewport window, as
            ``{"center": (x, y), "size": (w, h)}`` in paper inches. Merged
            over :data:`SHEET_WINDOWS` for ``size``, so a partial override
            (e.g. just ``{"center": ...}``) keeps that size's default for
            the keys it omits.
        library: Optional override for the title-block DXF library path; see
            :func:`bimforge.cad.titleblock.apply_title_block`.

    Returns:
        The newly created layout, with the border block and viewport added.

    Raises:
        ValueError: If ``size`` is not a known sheet size. Also propagates
            from :func:`bimforge.cad.viewport.add_fitted_viewport` if ``scale`` is
            not positive — at that point the layout has already been added
            to ``doc`` (via ``apply_title_block``) and is not rolled back.
    """
    if size not in SHEET_SIZES:
        raise ValueError(f"unknown sheet size {size!r} (use one of {list(SHEET_SIZES)})")
    lay = apply_title_block(doc, size, fields, layout_name, library=library)
    win = {**SHEET_WINDOWS[size], **(window or {})}
    add_fitted_viewport(lay, extents, scale, **win)
    return lay
