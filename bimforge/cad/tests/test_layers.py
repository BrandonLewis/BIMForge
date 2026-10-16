"""Tests for bimforge.cad.layers — layer table integrity and add_layers()."""
from __future__ import annotations

import pytest

ezdxf = pytest.importorskip("ezdxf")

from bimforge.cad.layers import (  # noqa: E402
    CIVIL_LAYERS,
    DEFAULT_LAYERS,
    ELEV_LAYERS,
    STRUCT_LAYERS,
    add_layers,
)


def test_add_layers_adds_all_default_layers():
    doc = ezdxf.new("R2018", setup=True)
    add_layers(doc)
    names = {layer.dxf.name for layer in doc.layers}
    for ld in DEFAULT_LAYERS:
        assert ld.name in names, f"layer {ld.name} missing after add_layers()"


def test_c_anno_text_is_in_civil_layers_and_created():
    # Undefined layers are silently dropped by ezdxf's viewport render path;
    # C-ANNO-TEXT must be defined so annotation survives plots.
    assert "C-ANNO-TEXT" in {ld.name for ld in CIVIL_LAYERS}
    assert "C-ANNO-TEXT" in {ld.name for ld in DEFAULT_LAYERS}
    doc = ezdxf.new("R2018", setup=True)
    add_layers(doc)
    assert "C-ANNO-TEXT" in {layer.dxf.name for layer in doc.layers}


def test_add_layers_applies_definition_attributes():
    doc = ezdxf.new("R2018", setup=True)
    add_layers(doc)
    for ld in DEFAULT_LAYERS:
        layer = doc.layers.get(ld.name)
        assert layer.dxf.color == ld.color
        assert layer.dxf.lineweight == ld.lineweight
        if ld.linetype:
            assert layer.dxf.linetype == ld.linetype


@pytest.mark.parametrize("subset", [STRUCT_LAYERS, CIVIL_LAYERS, ELEV_LAYERS],
                         ids=["struct", "civil", "elev"])
def test_discipline_subsets_are_subsets_of_full_table(subset):
    full_names = {ld.name for ld in DEFAULT_LAYERS}
    assert {ld.name for ld in subset} <= full_names


def test_no_duplicate_layer_names_in_merged_table():
    names = [ld.name for ld in DEFAULT_LAYERS]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("subset", [STRUCT_LAYERS, CIVIL_LAYERS, ELEV_LAYERS],
                         ids=["struct", "civil", "elev"])
def test_no_duplicate_layer_names_within_subset(subset):
    names = [ld.name for ld in subset]
    assert len(names) == len(set(names))
