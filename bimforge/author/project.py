"""ProjectContext — one definition of a project's frame, so the survey-control,
alignment and structure models can never drift apart.

Generalized from the spillway-pilot lineage's `project_base.py`: schema, EPSG/CRS names,
geodetic + vertical datum, base E/N/H for IfcMapConversion, project/site names,
and a per-project uuid5 GUID namespace -> `guid(key)`. Deterministic GlobalIds
make IFC outputs diffable in tests: `ifcopenshell.guid.new()` is random, which
makes every re-run a different file.

House convention carried over: civil models are AUTHORED in U.S. SURVEY feet
(0.30480060960121924 m). Every family's geometry is foot literals.

The IFC that comes out is SI metre, always: `emit_ifc` declares LENGTH, AREA and
VOLUME through `unit.add_si_unit`. So `unit:` in a spec says what the authored
geometry and the base point are in — it is NOT a choice of output unit, and there
is no `IfcConversionBasedUnit` named 'foot' in the file.

**The authoring factor is recorded in the file only when the model is
georeferenced.** `emit_ifc` writes `IfcMapConversion.Scale = 1/ft_to_m` inside
`if ctx.epsg is not None`, so a local model (no EPSG) carries the metre geometry
with nothing stating what it was authored in. Nor do the CRS/site descriptions
carry it on their own: `from_spec` defaults `crs_desc`/`site_desc` to empty and
`emit_ifc` only copies them, so the survey-vs-international distinction appears
there just when a caller supplies that wording. For a georeferenced file the
numeric MapConversion scale is what actually distinguishes the two (0.3048006…
vs 0.3048).

An earlier version of this docstring said the opposite (a ConversionBasedUnit
named 'foot', chosen because IFC has no name for the survey foot and a
nonstandard name crashes Bonsai/BlenderBIM) and asserted the descriptions
recorded the distinction unconditionally. That described a file this package has
not written. Consumers' house-convention notes copied the wording from here, so a
consumer repo may still carry the wrong description (#303).

Because the families are foot-native, `unit: 'm'` is refused rather than
accepted with a factor of 1.0 — see `from_spec`.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from bimforge.author.spatial import Facility

#: U.S. survey foot -> metres. NOT the international foot (0.3048).
US_SURVEY_FT_TO_M = 0.30480060960121924
#: International foot -> metres.
INTL_FT_TO_M = 0.3048


@dataclass(frozen=True)
class ProjectContext:
    """The project frame every builder and emitter shares."""

    name: str
    #: IFC4X3 by DEFAULT (#332): it is the schema civil work is defined in —
    #: IfcAlignment, the infrastructure facility tree, IfcEarthworksFill —
    #: and the only one that can carry the alignment-swept solids. The cost,
    #: and the reason #133 once defaulted to IFC4: Navisworks, Revit,
    #: Solibri, BIMcollab and most browser viewers cannot read IFC4X3 AT ALL
    #: — they open the file, show an empty model and raise no error. A
    #: consumer on one of those sets `schema: IFC4` in the spec's `project:`
    #: block; everything 4X3-only then degrades with a note (the class
    #: fallback, the facility tree, meshes for the alignment sweeps).
    schema: str = "IFC4X3_ADD2"
    #: Projected CRS. None => NO georeference — emit_ifc REFUSES to write
    #: unless allow_local=True is passed explicitly (the rebar-pilot regression:
    #: a local-only IFC is a drift bug unless deliberately chosen).
    epsg: int | None = None
    crs_desc: str = ""
    geodetic_datum: str | None = None
    vertical_datum: str | None = None
    #: Project base point, in CRS units (feet for a ftUS CRS). State Plane is
    #: recovered by plain addition: E = base_e + x.
    base_e: float = 0.0
    base_n: float = 0.0
    base_h: float = 0.0
    #: Model foot -> metre factor (survey foot by default; see module docstring).
    ft_to_m: float = US_SURVEY_FT_TO_M
    long_name: str = ""
    site_name: str = ""
    site_desc: str = ""
    #: uuid5 namespace for deterministic GlobalIds. Every project picks its own.
    guid_ns: uuid.UUID = field(
        default=uuid.UUID("00000000-0000-0000-0000-000000000000"))
    #: IFC4X3 facility tree (issue #318; `bimforge.author.spatial`). None (the
    #: default) keeps the Site > Building > Storey tree. Honoured only under an
    #: IFC4X3 schema — emit_ifc ignores it, with a note, under IFC4.
    facility: Facility | None = None

    @property
    def crs_name(self) -> str | None:
        return f"EPSG:{self.epsg}" if self.epsg else None

    def guid(self, key: str) -> str:
        """A stable 22-char IFC GlobalId derived from `key`."""
        import ifcopenshell.guid
        return ifcopenshell.guid.compress(uuid.uuid5(self.guid_ns, key).hex)

    def local(self, e: float, n: float, z: float | None = None):
        """CRS coordinates (feet) -> model feet relative to the base point."""
        if z is None:
            return e - self.base_e, n - self.base_n
        return e - self.base_e, n - self.base_n, z - self.base_h

    @classmethod
    def from_spec(cls, spec: dict) -> "ProjectContext":
        """Build from an `est-bim build` spec's `project:` block.

        Recognized keys: name (required), epsg, base ([e, n] or [e, n, h]),
        guid_ns (uuid string; REQUIRED — determinism is not optional),
        schema ('IFC4X3_ADD2' default; 'IFC4' for a viewer that cannot read
        4X3 — see the field docstring), crs_desc,
        geodetic_datum, vertical_datum, long_name, site_name, site_desc,
        unit ('us-survey-ft' default | 'ft'; 'm' is refused, see below),
        facility ({kind: bridge|road|railway|marine|facility|site, name?,
        predefined_type?} — IFC4X3 only, see bimforge.author.spatial).
        """
        if not spec.get("name"):
            raise ValueError("project: 'name' is required")
        if not spec.get("guid_ns"):
            raise ValueError(
                "project: 'guid_ns' (a uuid) is required — deterministic "
                "GlobalIds are part of the output contract")
        base = list(spec.get("base") or [0.0, 0.0]) + [0.0]
        unit = spec.get("unit", "us-survey-ft")
        if unit == "m":
            # #303. `unit` declares the unit the AUTHORED geometry and the base
            # point are in -- not the output unit, which is always SI metre.
            # Every shipped family is written in foot literals (type_842_profile
            # `_H = 3.5` is 3'-6"), so a factor of 1.0 does not produce a metric
            # model: it reinterprets each of those literals AS metres. The 842
            # stem came out 3.500 m instead of 1.067 m -- an 11'-6" barrier with
            # 35x the concrete volume -- and both builds passed the validation
            # gate, so nothing downstream noticed. Refuse loudly instead.
            raise ValueError(
                "project: unit 'm' is not supported. The IFC output is ALREADY "
                "SI metre whatever you choose here; `unit` declares the unit the "
                "authored geometry and base point are in, and every shipped "
                "family is authored in feet. Setting 'm' would reinterpret every "
                "foot literal as a metre, scaling the model 3.28x (volumes 35x) "
                "with no error. Use 'us-survey-ft' (the default) for a ftUS "
                "State Plane CRS, or 'ft' for international feet. Authoring a "
                "genuinely metric family needs the unit-agnostic kernel in "
                "issue #303.")
        try:
            ft_to_m = {"us-survey-ft": US_SURVEY_FT_TO_M,
                       "ft": INTL_FT_TO_M}[unit]
        except KeyError:
            raise ValueError(f"project: unknown unit {unit!r} "
                             "(us-survey-ft | ft)") from None
        return cls(
            name=spec["name"], schema=spec.get("schema", "IFC4X3_ADD2"),
            epsg=spec.get("epsg"), crs_desc=spec.get("crs_desc", ""),
            geodetic_datum=spec.get("geodetic_datum"),
            vertical_datum=spec.get("vertical_datum"),
            base_e=float(base[0]), base_n=float(base[1]), base_h=float(base[2]),
            ft_to_m=ft_to_m, long_name=spec.get("long_name", ""),
            site_name=spec.get("site_name", spec["name"]),
            site_desc=spec.get("site_desc", ""),
            guid_ns=uuid.UUID(str(spec["guid_ns"])),
            facility=Facility.from_spec(spec.get("facility")),
        )
