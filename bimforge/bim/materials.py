"""The material an element is made of, through whatever IFC puts between
them (C.5).

An element's IfcRelAssociatesMaterial names an IfcMaterial, or a set of
them: a layer set (walls, slabs) or a profile set (members), each usually
through a usage on the occurrence (IfcMaterialLayerSetUsage,
IfcMaterialProfileSetUsage), a constituent set, or a list. Readers want one
material, the one that governs: by BIMForge's convention, and as
ProjectCommand reads it, the first of a set. X.5 and X.6 write sets in that
order, so readers unwrap them here before any writer does.
"""
from __future__ import annotations

#: (set class, attribute holding its members, the member's material)
_SETS = (("IfcMaterialLayerSet", "MaterialLayers"),
         ("IfcMaterialProfileSet", "MaterialProfiles"),
         ("IfcMaterialConstituentSet", "MaterialConstituents"))


def first_material(definition):
    """The first IfcMaterial of a material definition: the material itself,
    a usage's set, a set's first member, a list's first entry. None when
    there is none (an empty set, a member with no material)."""
    m = definition
    if m is None:
        return None
    if m.is_a("IfcMaterialLayerSetUsage"):
        m = m.ForLayerSet
    elif m.is_a("IfcMaterialProfileSetUsage"):
        m = m.ForProfileSet
    if m is None:
        return None
    if m.is_a("IfcMaterial"):
        return m
    for cls, attr in _SETS:
        if m.is_a(cls):
            members = getattr(m, attr, None) or ()
            return next((x.Material for x in members
                         if getattr(x, "Material", None) is not None), None)
    if m.is_a("IfcMaterialList"):
        return next(iter(m.Materials or ()), None)
    return None


def governing_material(element):
    """The IfcMaterial that governs `element`, its own or its type's: the
    first material of whatever it is associated with. None without one."""
    import ifcopenshell.util.element as ue
    return first_material(ue.get_material(element, should_skip_usage=True))
