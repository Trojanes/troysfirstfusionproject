"""Attribute-first identity helpers (no Fusion runtime required)."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GEOMETRY_OPS_PATH = PLUGIN_ROOT / "fusion" / "geometry_ops.py"


class _Attr:
    def __init__(self, value):
        self.value = value


class _Attrs:
    def __init__(self, values):
        self._values = values

    def itemByName(self, group, name):
        key = (group, name)
        if key not in self._values:
            return None
        return _Attr(self._values[key])


class _Entity:
    def __init__(self, name="", attrs=None):
        self.name = name
        self.attributes = _Attrs(attrs or {})


def _load_geometry_ops():
    if "adsk" not in sys.modules:
        adsk = types.ModuleType("adsk")
        adsk.core = types.ModuleType("adsk.core")
        sys.modules["adsk"] = adsk
        sys.modules["adsk.core"] = adsk.core
    spec = importlib.util.spec_from_file_location("geometry_ops_identity", GEOMETRY_OPS_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class EntityIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ops = _load_geometry_ops()

    def test_entity_module_reads_cabinetnc_first(self):
        entity = _Entity(
            name="Island-V1",
            attrs={("CabinetNC", "module"): "kitchen", ("CabinetNC", "boardId"): "V1"},
        )
        self.assertEqual(self.ops.entity_module(entity), "kitchen")
        self.assertEqual(self.ops.entity_board_id(entity), "V1")
        self.assertTrue(self.ops.is_module_artifact(entity, "kitchen"))

    def test_custom_assembly_name_is_not_identity(self):
        entity = _Entity(name="Island-V1")
        self.assertFalse(self.ops.name_looks_like_module("Island-V1", "kitchen"))
        self.assertFalse(self.ops.is_module_artifact(entity, "kitchen"))
        tagged = _Entity(
            name="Island-V1",
            attrs={("CabinetNC", "module"): "kitchen", ("CabinetNC", "boardId"): "V1"},
        )
        self.assertTrue(self.ops.is_module_artifact(tagged, "kitchen"))
        self.assertFalse(self.ops.is_module_artifact(tagged, "lounge"))

    def test_module_attr_blocks_other_module_name_fallback(self):
        entity = _Entity(
            name="Lounge-MAIN_L",
            attrs={("UnifiedCabinetPlugin", "module"): "kitchen"},
        )
        self.assertTrue(self.ops.is_module_artifact(entity, "kitchen"))
        self.assertFalse(self.ops.is_module_artifact(entity, "lounge"))

    def test_legacy_name_is_fallback_only(self):
        entity = _Entity(name="KITCHEN_vPanel_V1")
        self.assertTrue(self.ops.name_looks_like_module(entity.name, "kitchen"))
        self.assertTrue(self.ops.is_module_artifact(entity, "kitchen"))
        self.assertTrue(self.ops.name_looks_like_module("GT_B3", "general_tall"))
        self.assertTrue(self.ops.name_looks_like_module("Lounge-MAIN_L", "lounge"))

    def test_body_matches_module_prefers_attribute_over_name(self):
        body = _Entity(
            name="GT_B3",
            attrs={("UnifiedCabinetPlugin", "module"): "lounge"},
        )
        self.assertTrue(self.ops.body_matches_module(body, name_prefixes=["GT_"], module="lounge"))
        self.assertFalse(self.ops.body_matches_module(body, name_prefixes=["LOUNGE_"], module="kitchen"))
        self.assertFalse(self.ops.body_matches_module(body, name_prefixes=["GT_"], module="general_tall"))

    def test_legacy_name_used_only_when_module_attr_missing(self):
        body = _Entity(name="GT_B3")
        self.assertTrue(self.ops.body_matches_module(body, name_prefixes=["GT_"], module="general_tall"))
        self.assertTrue(self.ops.body_matches_module(body, module="general_tall"))


if __name__ == "__main__":
    unittest.main()
