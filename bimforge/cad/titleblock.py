"""Title block application for ezdxf documents.

Stamps a border block onto a new paperspace layout and fills its attributes
from a :class:`TitleBlockFields` record.

The default border blocks live in the packaged DXF library
``templates/generic-title-blocks.dxf`` (11x17 and ARCH D). Pass an explicit
``library`` path, or provide an org style pack (:mod:`bimforge.cad.stylepack`),
to use branded borders instead.
"""
from __future__ import annotations

from dataclasses import dataclass, fields as dc_fields
from importlib.resources import files
from typing import TYPE_CHECKING, Optional

import ezdxf
from ezdxf.addons import Importer

if TYPE_CHECKING:
    from ezdxf.document import Drawing
    from ezdxf.layouts import Layout

#: Default title-block DXF library (org-neutral 11x17 + ARCH D borders).
#: Ships in the package under ``templates/``; org borders come from style
#: packs (:mod:`bimforge.cad.stylepack`) or an explicit ``library`` argument.
TITLE_BLOCK_LIBRARY: str = str(
    files("bimforge.cad") / "templates" / "generic-title-blocks.dxf"
)


@dataclass(frozen=True)
class SheetSize:
    """One printable sheet: its border block name and paper geometry."""

    block: str
    #: Paper size in inches, ``(width, height)`` as passed to ``page_setup``.
    paper_in: tuple[float, float]
    landscape: bool


#: Registered sheet sizes, keyed by short name.
SHEET_SIZES: dict[str, SheetSize] = {
    "11x17": SheetSize("border_11X17 TITLE", (11, 17), False),
    "ARCH_D": SheetSize("border_ARCH D TITLE", (36, 24), True),
}


@dataclass
class TitleBlockFields:
    """Editable text values for the title block.

    Each field maps to the block attribute of the same name, upper-cased (see
    :meth:`as_attribs`). Unset fields render blank.
    """

    project: str = ""
    contract: str = ""
    bridge: str = ""
    job_no: str = ""
    project_name: str = ""
    subtitle: str = ""
    sheet_title: str = ""
    city: str = ""
    county: str = ""
    date: str = ""
    scale: str = ""
    drafter: str = ""
    designer: str = ""
    checked: str = ""
    sht: str = ""
    sht_total: str = ""

    def as_attribs(self) -> dict[str, str]:
        """Return ``{ATTRIB_TAG: value}`` for ``add_auto_attribs``.

        Field names are upper-cased to match the block's attribute tags.
        """
        return {f.name.upper(): getattr(self, f.name) for f in dc_fields(self)}


def _import_block(doc: "Drawing", block_name: str, library: str) -> None:
    """Import ``block_name`` from ``library`` into ``doc`` (idempotent)."""
    if block_name in doc.blocks:
        return
    src = ezdxf.readfile(library)
    imp = Importer(src, doc)
    imp.import_block(block_name)
    imp.finalize()


def apply_title_block(
    doc: "Drawing",
    size: str,
    fields: TitleBlockFields,
    layout_name: str,
    library: Optional[str] = None,
) -> "Layout":
    """Create a paperspace layout carrying the border for ``size``.

    Imports the border block (once per document), makes a new layout named
    ``layout_name``, sets its page size, inserts the border at the origin, and
    fills the title-block attributes from ``fields``.

    Args:
        doc: An open ezdxf drawing.
        size: A key of :data:`SHEET_SIZES` (``"11x17"`` or ``"ARCH_D"``).
        fields: Text to stamp into the title block.
        layout_name: Name for the new paperspace layout.
        library: Optional override for the title-block DXF library path;
            defaults to :data:`TITLE_BLOCK_LIBRARY`.

    Returns:
        The newly created layout.

    Raises:
        ValueError: If ``size`` is not a known sheet size.
    """
    if size not in SHEET_SIZES:
        raise ValueError(f"unknown sheet size {size!r}; known: {list(SHEET_SIZES)}")
    ss = SHEET_SIZES[size]
    if library is None:
        from bimforge.cad.stylepack import resolve_style_pack
        lib = resolve_style_pack().title_block_library
        library = str(lib) if lib else TITLE_BLOCK_LIBRARY
    _import_block(doc, ss.block, library)
    lay = doc.layouts.new(layout_name)
    lay.page_setup(size=ss.paper_in, units="inch")
    br = lay.add_blockref(ss.block, (0, 0))
    br.add_auto_attribs(fields.as_attribs())
    return lay
