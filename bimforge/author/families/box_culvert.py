"""box_culvert -- Caltrans D80 (single) / D81 (double) CIP RC box culverts,
generalized to N cells. A section (BoxCulvertSection) times a barrel run
(SectionPrism); reinforcing by the sheet's tabulated LB/LF (added later).

Params (all data; agency tables live bid-side via params.tables_file):
    tables: {single: {...}, double: {...}}   # BoxCulvertSection format
    culverts:
      - name: C1
        cells: 1
        span_ft, height_ft, earth_cover_ft
        barrel_length_ft
"""
from __future__ import annotations

from bimforge.author.box_section import BoxCulvertSection
from bimforge.author.model import Element, StructureModel
from bimforge.author.primitives import SectionPrism

REQUIRED = ("tables", "culverts")


def build(params: dict, ctx) -> StructureModel:
    missing = [k for k in REQUIRED if params.get(k) is None]
    if missing:
        raise ValueError(f"box-culvert params missing {missing}")
    table = params["tables"]
    model = StructureModel("box-culvert", ctx)

    for c in params["culverts"]:
        tag = c["name"]
        sec = BoxCulvertSection(c["cells"], c["span_ft"], c["height_ft"],
                                c["earth_cover_ft"], table)
        length = float(c["barrel_length_ft"])
        p = SectionPrism(f"{tag} box culvert barrel", sec.outer_profile(),
                         length, voids=sec.cell_voids(),
                         ifc="IfcBuildingElementProxy", layer="S-CONC-OTLN")
        # A voided SectionPrism is not a solid L x W x H box, so it carries
        # length + net volume only (like the spillway ogee weir) -- emitting
        # bounding width/height would trip the gate's L x W x H = volume check.
        model.add(Element.from_geometry(
            p.name, p, ifc_class="IfcBuildingElementProxy", layer="S-CONC-OTLN",
            quantities={"length_ft": length, "volume_cf": p.volume_cf}))

        steel_lb = sec.lb_per_lf * length
        model.add(Element(
            f"{tag} box culvert reinforcing", "IfcReinforcingBar",
            quantities={"length_ft": length, "weight_lb": steel_lb},
            layer="S-REBAR"))
    return model
