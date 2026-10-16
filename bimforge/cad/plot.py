"""Render a paperspace layout to PDF or PNG.

Uses ezdxf's drawing add-on with the matplotlib backend (the `draw` extra).
The figure is sized to the layout's paper so a PDF/PNG prints at true scale:
one paperspace drawing unit maps to one point on the physical sheet.
"""
from __future__ import annotations

from pathlib import Path

#: DXF group codes 44/45 (``paper_width``/``paper_height``) are always stored
#: in millimeters, regardless of the layout's ``plot_paper_units`` flag (see
#: ``ezdxf.layouts.layout.Layout.page_setup``, which multiplies whatever size
#: the caller passed by a unit factor before storing it). Matplotlib figure
#: sizes are always in inches, so this is the one conversion we always need.
MM_PER_INCH = 25.4

#: Sheets here always call ``page_setup(..., units="inch")`` (see
#: ``bimforge.cad.titleblock.SHEET_SIZES``), which sets ``plot_paper_units = 0`` and
#: places paperspace entities (border blocks, viewports) in inch coordinates.
#: A layout set up in millimeters would have entities in mm coordinates
#: instead; ``plot_paper_units == 1`` marks that case.
_PLOT_PAPER_UNITS_MM = 1


def render_layout(
    doc, layout_name: str, out_path, *, dpi: int = 300, mono: bool = True
) -> Path:
    """Render a paperspace layout of a document to a PDF or PNG file.

    Args:
        doc: An open ezdxf drawing.
        layout_name: Name of the paperspace layout to render (e.g. as created
            by :func:`bimforge.cad.titleblock.apply_title_block`).
        out_path: Output file path. Must end in ``.pdf`` or ``.png``
            (case-insensitive); the format is selected from the suffix.
        dpi: Resolution in dots per inch for raster (PNG) output; ignored for
            PDF output.
        mono: If ``True`` (default), plot with a monochrome, CTB-style ink
            policy — every entity draws in black regardless of its DXF/ACI
            layer or entity color. This mirrors standard plot-style-table
            practice and keeps low-value ACI colors (e.g. ACI 2 yellow) from
            rendering illegibly light on white PDF/PNG output. Set ``False``
            to plot literal layer/entity colors instead. Either way, the
            DXF's own layer and entity colors are left untouched — this only
            affects the rendered raster/vector output.

    Returns:
        The ``Path`` of the file that was written (equal to ``out_path``).

    Raises:
        KeyError: If `layout_name` is not a layout of `doc`.
        ValueError: If `out_path` does not end in ``.pdf`` or ``.png``.
    """
    out = Path(out_path)
    if out.suffix.lower() not in (".pdf", ".png"):
        raise ValueError(f"out_path must end in .pdf or .png, got {str(out_path)!r}")

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.config import ColorPolicy, Configuration
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    layout = doc.layouts.get(layout_name)  # raises KeyError for unknown names

    paper_w_mm = float(layout.dxf.paper_width) or 36.0 * MM_PER_INCH
    paper_h_mm = float(layout.dxf.paper_height) or 24.0 * MM_PER_INCH
    paper_w_in = paper_w_mm / MM_PER_INCH
    paper_h_in = paper_h_mm / MM_PER_INCH

    # Data (paperspace entity) coordinates match whatever units the layout
    # was set up with; convert the paper size into that same coordinate
    # system so the axis limits below line up with the drawn geometry.
    if getattr(layout.dxf, "plot_paper_units", 0) == _PLOT_PAPER_UNITS_MM:
        # Defensive: bimforge.cad's page_setup always uses inches; this branch is
        # exercised only by hand-built layouts that set up in millimeters.
        data_w, data_h = paper_w_mm, paper_h_mm
    else:
        data_w, data_h = paper_w_in, paper_h_in

    fig = plt.figure(figsize=(paper_w_in, paper_h_in))
    try:
        ax = fig.add_axes((0, 0, 1, 1))
        ctx = RenderContext(doc)
        # adjust_figure=False: by default MatplotlibBackend.finalize() resizes
        # the figure to fit the drawn geometry's bounding box, which would
        # silently discard the true-paper-size figure we just set.
        backend = MatplotlibBackend(ax, adjust_figure=False)
        if mono:
            config = Configuration(color_policy=ColorPolicy.BLACK)
            frontend = Frontend(ctx, backend, config=config)
        else:
            frontend = Frontend(ctx, backend)
        frontend.draw_layout(layout, finalize=True)
        # finalize() still autoscales the axes to the geometry's bounding box;
        # pin them back to the full paper extents so the sheet plots at scale
        # instead of cropping to wherever ink happens to land.
        ax.set_xlim(0, data_w)
        ax.set_ylim(0, data_h)

        fig.savefig(out, dpi=dpi, facecolor="white")
    finally:
        plt.close(fig)
    return out
