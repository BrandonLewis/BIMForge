"""C.5: readers unwrap set usages to the governing (first) material."""
import pytest

ifcopenshell = pytest.importorskip("ifcopenshell")

import ifcopenshell.api.material as mat  # noqa: E402
import ifcopenshell.api.root as root  # noqa: E402

from bimforge.bim.materials import first_material, governing_material  # noqa: E402


def _file():
    f = ifcopenshell.file(schema="IFC4X3_ADD2")
    root.create_entity(f, ifc_class="IfcProject")
    return f


def _materials(f):
    return (mat.add_material(f, name="Concrete", category="concrete"),
            mat.add_material(f, name="Steel", category="steel"))


def test_a_direct_material():
    f = _file()
    concrete, _ = _materials(f)
    wall = root.create_entity(f, ifc_class="IfcWall")
    mat.assign_material(f, products=[wall], material=concrete)
    assert governing_material(wall) == concrete


def test_a_layer_set_usage_on_the_occurrence_gives_its_first_layer():
    f = _file()
    concrete, steel = _materials(f)
    wtype = root.create_entity(f, ifc_class="IfcWallType", name="W")
    lset = mat.add_material_set(f, name="W", set_type="IfcMaterialLayerSet")
    for m in (concrete, steel):
        mat.add_layer(f, layer_set=lset, material=m)
    mat.assign_material(f, products=[wtype], material=lset)
    wall = root.create_entity(f, ifc_class="IfcWall")
    usage = f.create_entity("IfcMaterialLayerSetUsage", ForLayerSet=lset,
                            LayerSetDirection="AXIS2",
                            DirectionSense="POSITIVE", OffsetFromReferenceLine=0.)
    f.create_entity("IfcRelAssociatesMaterial",
                    GlobalId=ifcopenshell.guid.new(), RelatedObjects=[wall],
                    RelatingMaterial=usage)
    assert governing_material(wall) == concrete
    assert governing_material(wtype) == concrete


def test_a_profile_set_usage_gives_its_first_profile():
    f = _file()
    _, steel = _materials(f)
    pset = mat.add_material_set(f, name="Post", set_type="IfcMaterialProfileSet")
    mat.add_profile(f, profile_set=pset, material=steel)
    usage = f.create_entity("IfcMaterialProfileSetUsage", ForProfileSet=pset)
    assert first_material(usage) == steel


def test_an_untyped_element_inherits_its_types_material():
    f = _file()
    concrete, _ = _materials(f)
    ftype = root.create_entity(f, ifc_class="IfcFootingType", name="F")
    mat.assign_material(f, products=[ftype], material=concrete)
    ftg = root.create_entity(f, ifc_class="IfcFooting")
    import ifcopenshell.api.type as type_api
    type_api.assign_type(f, related_objects=[ftg], relating_type=ftype)
    assert governing_material(ftg) == concrete


def test_constituents_lists_and_nothing():
    f = _file()
    concrete, steel = _materials(f)
    cset = mat.add_material_set(f, name="C", set_type="IfcMaterialConstituentSet")
    for m in (steel, concrete):
        mat.add_constituent(f, constituent_set=cset, material=m)
    assert first_material(cset) == steel
    mlist = f.create_entity("IfcMaterialList", Materials=[concrete, steel])
    assert first_material(mlist) == concrete
    empty = mat.add_material_set(f, name="E", set_type="IfcMaterialLayerSet")
    assert first_material(empty) is None
    assert governing_material(root.create_entity(f, ifc_class="IfcWall")) is None
