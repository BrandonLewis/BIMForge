"""bimforge.author — the model-document authoring kernel (Phase 3a).

Parametric structure models (:mod:`~bimforge.author.model`) built from
closed-form primitives (:mod:`~bimforge.author.primitives`) on a survey
alignment (:mod:`~bimforge.author.alignment`) inside a georeferenced
:class:`~bimforge.author.project.ProjectContext`, classified against per-bid
pay codes (:mod:`~bimforge.author.paycodes`), bracketed by a validation gate
(:mod:`~bimforge.author.gate`), and emitted by independent writers
(``emit_dxf`` / ``emit_ifc`` / ``emit_qto`` / ``emit_step``). Registered
construct families live in :mod:`bimforge.author.families` and are driven by
``est-bim build <spec.yaml>``.

The model is the single source of truth; emitters never compute geometry.
The CanonicalTakeoff is never computed here — it is derived from the emitted
IFC through :mod:`bimforge.bim.ifc_takeoff` (see docs/ifc-takeoff-contract.md).
"""
