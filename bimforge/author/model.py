"""StructureModel / Element — the model document (spec §1/§2).

The model is the SINGLE source of truth. Emitters read it; they never compute
geometry. Quantities are analytic (closed-form, feet-domain: volume_cf,
area_sf, length/width/height_ft, weight_lb, surface_sf, count) and live on
the Element — computed by the builder from its primitives, or delegated to a
geometry object's properties via `Element.from_geometry`.

Classification: `classifications` is a LIST of pay codes (one element, many
pay items — the furnish-LF + drive-EA lesson; upstream multi-code read landed
in 0.1.33). `[]` means REFERENCE GEOMETRY — deliberately unclassified so it
can never reach a pay quantity.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Quantity keys an Element may carry (feet/pounds domain; emit_ifc converts).
QUANTITY_KEYS = ("count", "length_ft", "width_ft", "height_ft", "area_sf",
                 "perimeter_ft", "volume_cf", "surface_sf", "weight_lb")

#: geometry attribute -> element quantity key, for from_geometry delegation.
_GEOM_QTY_ATTRS = {
    "volume_cf": "volume_cf", "area_sf": "area_sf", "length_ft": "length_ft",
    "width_ft": "width_ft", "height_ft": "height_ft", "weight_lb": "weight_lb",
    "surface_sf": "surface_sf", "count": "count",
}


@dataclass
class Element:
    """One physical product: name, parametric geometry, analytic quantities,
    zero-or-more pay-code classifications, and a deterministic GUID key."""

    name: str
    ifc_class: str = "IfcBuildingElementProxy"
    #: The geometry payload emit_ifc/emit_dxf/emit_step consume: an object (or
    #: list of objects) exposing `body_solids()` (see primitives), or a raw
    #: solids dict in the same schema.
    geometry: Any = None
    #: Analytic quantities, feet/pounds domain (QUANTITY_KEYS subset).
    quantities: dict[str, float] = field(default_factory=dict)
    #: Pay codes ([] = reference geometry, never a pay quantity).
    classifications: list[str] = field(default_factory=list)
    material: str | None = None
    density_pcf: float | None = None
    #: Placement: model-frame feet. Emitters place the element here.
    x_ft: float = 0.0
    y_ft: float = 0.0
    z_ft: float = 0.0
    #: Placement: rotation about +Z in degrees, applied about the element's
    #: local origin BEFORE the x/y/z translation. Geometry stays authored in
    #: the element-local frame; emitters compose Rz(bearing) with the x/y/z
    #: offset at emit time, so quantities/volumes remain rigid-motion-invariant.
    bearing_deg: float = 0.0
    #: DXF layer for the plan footprint (stylepack may restyle it).
    layer: str | None = None
    #: Deterministic-GUID key; defaults to "element/<name>".
    guid_key: str | None = None
    predefined_type: str | None = None
    #: Free-text estimator note (e.g. the spillway-pilot ogee reporting the sf of its
    #: expanded-polystyrene void). Carried on the model document; emitters
    #: that have a description slot may write it, others ignore it.
    description: str | None = None
    #: IFC4X3 facility part this element is contained in (issue #318): a part
    #: name (``"ABUTMENT"``, ``"Abut 1"``) or a mapping ``{name,
    #: predefined_type?, usage_type?}``; normalized to a
    #: `bimforge.author.spatial.SpatialPart`. Only used when the project has a
    #: `facility` under IFC4X3 — ignored otherwise. None = contained in the
    #: facility itself (or matched later by a `spatial_parts:` rule).
    spatial_part: Any = None

    def __post_init__(self):
        if self.spatial_part is not None:
            from bimforge.author.spatial import parse_part
            self.spatial_part = parse_part(self.spatial_part,
                                           f"{self.name}: spatial_part")
        if self.guid_key is None:
            self.guid_key = f"element/{self.name}"
        bad = set(self.quantities) - set(QUANTITY_KEYS)
        if bad:
            raise ValueError(f"{self.name}: unknown quantity keys {sorted(bad)}")

    @classmethod
    def from_geometry(cls, name: str, geometry: Any, **kw) -> "Element":
        """Build an Element whose quantities delegate to the geometry object."""
        q = dict(kw.pop("quantities", {}))
        for attr, key in _GEOM_QTY_ATTRS.items():
            if key not in q and hasattr(geometry, attr):
                q[key] = float(getattr(geometry, attr))
        return cls(name=name, geometry=geometry, quantities=q, **kw)

    def quantity(self, key: str) -> float | None:
        return self.quantities.get(key)

    @property
    def weight_lb(self) -> float | None:
        """Weight: explicit quantity first, else volume x density."""
        if "weight_lb" in self.quantities:
            return self.quantities["weight_lb"]
        if self.density_pcf is not None and "volume_cf" in self.quantities:
            return self.quantities["volume_cf"] * self.density_pcf
        return None


@dataclass
class StructureModel:
    """The model document a family (or a bespoke script) builds."""

    name: str
    ctx: Any                    # ProjectContext
    elements: list[Element] = field(default_factory=list)
    #: name -> list of element names aggregated into an IfcElementAssembly.
    assemblies: dict[str, list[str]] = field(default_factory=dict)
    #: Openings: (host element name, opening Element) — emitted as
    #: IfcOpeningElement voids on the host.
    openings: list[tuple[str, Element]] = field(default_factory=list)
    #: Family/script-registered gate checks: callables (model) -> list[str].
    checks: list = field(default_factory=list)
    #: DXF annotation callbacks: callables (msp, model) drawing sections/dims.
    dxf_annotations: list = field(default_factory=list)
    #: Annotation instancing plans (bimforge.author.annotate.AnnotationPlan):
    #: stationing/callouts emitted as instanced IfcAnnotation (and drawn into
    #: the DXF), kept off the pay-quantity path entirely.
    annotations: list = field(default_factory=list)
    #: (label, got, want, tol) closed-form assertions for the gate built-in.
    stated_quantities: list[tuple[str, float, float, float]] = field(default_factory=list)
    #: (label, value, expected_sign, tol) SIGNED handedness assertions. Unlike
    #: stated_quantities (magnitude-only, blind to a mirror that negates the
    #: value), each entry asserts a family-computed orientation scalar keeps a
    #: given sign — the check that catches a mirrored swept section whose area
    #: and volume are unchanged. expected_sign is +1 or -1; |value| <= tol is a
    #: degenerate/ambiguous failure. (#251)
    stated_orientations: list[tuple[str, float, int, float]] = field(default_factory=list)

    def add(self, element: Element) -> Element:
        if any(e.name == element.name for e in self.elements):
            raise ValueError(f"duplicate element name {element.name!r}")
        self.elements.append(element)
        return element

    def element(self, name: str) -> Element:
        for e in self.elements:
            if e.name == name:
                return e
        raise KeyError(name)

    def codes_used(self) -> list[str]:
        return sorted({c for e in self.elements for c in e.classifications})

    def total(self, code: str, key: str) -> float:
        """Sum a quantity over the elements classified under `code`."""
        return sum(e.quantities.get(key) or 0.0
                   for e in self.elements if code in e.classifications)
