"""Paperspace viewport helpers that frame model geometry.

Site sheets place geometry at true State Plane coordinates (millions of feet
from the DXF origin), so a paperspace viewport must be told exactly where to
look and how tall a slice of the world to show. Builder scripts computed this
by hand for each sheet::

    cE = (min(Es) + max(Es)) / 2
    cN = (min(Ns) + max(Ns)) / 2
    vh = max((max(Ns) - min(Ns)) * 1.25,
             (max(Es) - min(Es)) * 1.25 / (27.0 / 19.0))
    lay.add_viewport(center=(18, 12), size=(27, 19),
                     view_center_point=(cE, cN), view_height=vh, ...)

:func:`add_fitted_viewport` captures that: given the world-coordinate ``extents``
of what you drew, it centres a viewport on them and sizes ``view_height`` either
to a fixed drawing ``scale`` or to fit the paper window with a margin.
"""
from __future__ import annotations

from typing import Iterable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ezdxf.layouts import Layout
    from ezdxf.entities import Viewport

#: Default viewport window in paper inches for an ARCH D sheet with the
#: bundled border: centre ``(18, 12)`` on the 36x24 sheet, ``27x19`` window.
ARCH_D_WINDOW = dict(center=(18.0, 12.0), size=(27.0, 19.0))

Extents = tuple[float, float, float, float]  # (min_x, min_y, max_x, max_y)


def bbox(points: Iterable[tuple[float, float]], margin: float = 0.0) -> Extents:
    """Axis-aligned bounding box of ``points`` as ``(min_x, min_y, max_x, max_y)``.

    Args:
        points: Iterable of ``(x, y)`` world coordinates.
        margin: Distance to expand the box on every side (world units).

    Raises:
        ValueError: If ``points`` is empty.
    """
    xs: list[float] = []
    ys: list[float] = []
    for x, y in points:
        xs.append(x)
        ys.append(y)
    if not xs:
        raise ValueError("bbox() requires at least one point")
    return (min(xs) - margin, min(ys) - margin, max(xs) + margin, max(ys) + margin)


def resolve_scale(
    extents: Extents,
    scale: Optional[float] = None,
    *,
    size: tuple[float, float] = ARCH_D_WINDOW["size"],
    margin: float = 1.05,
) -> float:
    """The effective paper-per-world scale a fitted viewport plots at.

    ``scale`` when given (validated positive); otherwise the auto-fit scale
    for ``extents`` in a ``size`` paper window with ``margin`` padding — the
    same math :func:`add_fitted_viewport` uses, exposed so callers can size
    paper-relative annotation BEFORE composing the sheet."""
    if scale is not None:
        if scale <= 0:
            raise ValueError(f"scale must be positive, got {scale!r}")
        return scale
    min_x, min_y, max_x, max_y = extents
    paper_w, paper_h = size
    world_w, world_h = max_x - min_x, max_y - min_y
    view_height = max(world_h * margin, (world_w * margin) / (paper_w / paper_h))
    # Degenerate zero-area extents: fall back to 1:1 instead of dividing
    # by zero (intentional new behavior vs the old inline auto-fit math).
    return paper_h / view_height if view_height > 0 else 1.0


def add_fitted_viewport(
    layout: "Layout",
    extents: Extents,
    scale: Optional[float] = None,
    *,
    center: tuple[float, float] = ARCH_D_WINDOW["center"],
    size: tuple[float, float] = ARCH_D_WINDOW["size"],
    margin: float = 1.05,
    layer: str = "S-ANNO-SYMB",
) -> "Viewport":
    """Add a paperspace viewport centred on and framing ``extents``.

    Args:
        layout: The paperspace layout (e.g. from
            :func:`bimforge.cad.titleblock.apply_title_block`).
        extents: World-coordinate bounds ``(min_x, min_y, max_x, max_y)`` of the
            geometry to frame.
        scale: Drawing scale as *paper units per world unit* (e.g. ``1/30`` for
            1" = 30'). If given, ``view_height`` is ``size_height / scale`` so the
            sheet plots at exactly that scale. If ``None`` (default), the height
            is fit to the paper window so all geometry is visible, padded by
            ``margin``.
        center: Viewport window centre on the sheet, in paper inches.
        size: Viewport window ``(width, height)`` on the sheet, in paper inches.
        margin: Fit padding factor when ``scale`` is ``None`` (``1.05`` = 5%).
        layer: Layer for the viewport entity (kept off the plotted geometry).

    Returns:
        The created viewport entity.
    """
    min_x, min_y, max_x, max_y = extents
    view_center = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
    paper_w, paper_h = size

    view_height = paper_h / resolve_scale(extents, scale, size=size,
                                          margin=margin)

    return layout.add_viewport(
        center=center,
        size=size,
        view_center_point=view_center,
        view_height=view_height,
        dxfattribs={"layer": layer},
    )
