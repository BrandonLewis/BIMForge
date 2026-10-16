"""bimforge.cad — org-neutral CAD/KML/geo engine (absorbed the in-house CAD core, 0.1.38).

Submodules
----------
* :mod:`bimforge.cad.doc`        — :func:`~bimforge.cad.doc.new_doc`, standard ezdxf setup.
* :mod:`bimforge.cad.layers`     — NCS layer table + :func:`~bimforge.cad.layers.add_layers`.
* :mod:`bimforge.cad.titleblock` — :func:`~bimforge.cad.titleblock.apply_title_block`.
* :mod:`bimforge.cad.viewport`   — :func:`~bimforge.cad.viewport.add_fitted_viewport`.
* :mod:`bimforge.cad.sheet`      — :func:`~bimforge.cad.sheet.compose_sheet` (title block + fitted viewport).
* :mod:`bimforge.cad.plot`       — :func:`~bimforge.cad.plot.render_layout` (paperspace to PDF/PNG).
* :mod:`bimforge.cad.formats`    — :func:`~bimforge.cad.formats.ft_in`, ``station``, ``dms``, ``FT2M``.
* :mod:`bimforge.cad.kml`        — :class:`~bimforge.cad.kml.KMLDocument` builder.
* :mod:`bimforge.cad.geo`        — pyproj State Plane <-> WGS84 helpers.
* :mod:`bimforge.cad.stylepack`  — org style-pack resolution (title blocks + model styling).

``formats`` and ``kml`` are pure stdlib; ``geo`` needs pyproj (the ``bim``
extra); the rest need ezdxf (a base dependency). Org branding lives in style
packs (see :mod:`bimforge.cad.stylepack`), never in this engine.
"""
from __future__ import annotations

from .formats import FT2M, bearing_to_azimuth, dms, forward, ft_in, station
from .sheet import compose_sheet

__all__ = [
    "FT2M",
    "ft_in",
    "station",
    "dms",
    "bearing_to_azimuth",
    "forward",
    "compose_sheet",
]
