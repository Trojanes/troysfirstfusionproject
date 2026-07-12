import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL_ATTR_DIR = ROOT / "panel_attributes"
if str(PANEL_ATTR_DIR) not in sys.path:
    sys.path.insert(0, str(PANEL_ATTR_DIR))

import metadata_inspector as inspector  # noqa: E402


class DeriveColorTagTests(unittest.TestCase):
    def test_keeps_custom_color_tag(self):
        metadata = {
            "defaultAttributes": {"materialClass": "door_board"},
            "typedTags": {"colorTag": "alpine_white"},
        }
        self.assertEqual(inspector._derive_color_tag(metadata, "door_board"), "alpine_white")

    def test_slugs_door_color_name_without_sidedness(self):
        metadata = {
            "defaultAttributes": {
                "materialClass": "door_board",
                "doorColorName": "Alpine White",
                "surfaceMode": "DOUBLE_SIDED",
            },
        }
        self.assertEqual(inspector._derive_color_tag(metadata, "door_board"), "alpine_white")

    def test_slugs_generic_panel_color_name(self):
        metadata = {
            "defaultAttributes": {
                "materialClass": "partition_board",
                "colorName": "Smoked Oak",
            }
        }
        self.assertEqual(
            inspector._derive_color_tag(metadata, "partition_board"),
            "smoked_oak",
        )

    def test_surface_mode_from_face_registry(self):
        metadata = {
            "faceRegistry": {"surfaceMode": "SINGLE_SIDED"},
        }
        self.assertEqual(inspector._metadata_surface_mode(metadata), "single_sided")

    def test_legacy_slot_tag_when_no_custom_name(self):
        metadata = {
            "defaultAttributes": {
                "materialClass": "door_board",
                "doorColorSlot": 1,
                "surfaceMode": "single_sided",
            },
        }
        self.assertEqual(
            inspector._derive_color_tag(metadata, "door_board"),
            "door_colour_1_single_sided",
        )

    def test_carcass_colour(self):
        metadata = {"defaultAttributes": {"materialClass": "carcass_board"}}
        self.assertEqual(inspector._derive_color_tag(metadata, "carcass_board"), "carcass_colour")

    def test_metadata_looks_like_door(self):
        self.assertTrue(
            inspector.metadata_looks_like_door(
                {"defaultAttributes": {"materialClass": "door_board"}}
            )
        )
        self.assertTrue(
            inspector.metadata_looks_like_door(
                {"derivedTags": {"boardTypeTag": "door"}}
            )
        )
        self.assertFalse(
            inspector.metadata_looks_like_door(
                {"defaultAttributes": {"materialClass": "carcass_board", "role": "carcass"}}
            )
        )

    def test_infer_material_class_front_panel(self):
        self.assertEqual(
            inspector._infer_material_class("kitchen", "front_panel", "front_panel", "frontPanel"),
            "door_board",
        )
        self.assertEqual(
            inspector._infer_material_class("kitchen", "k-zone-1", "front_panel", "frontPanel"),
            "door_board",
        )

    def test_body_name_looks_like_door(self):
        self.assertTrue(
            inspector._body_name_looks_like_door(
                "KITCHEN_frontPanel_k-zone-left-door-front-panel"
            )
        )
        self.assertTrue(inspector._body_name_looks_like_door("GT_FP_FP_zone-1_L"))
        self.assertTrue(inspector._body_name_looks_like_door("OH_FP0"))
        self.assertFalse(inspector._body_name_looks_like_door("GT_B3"))
        self.assertFalse(inspector._body_name_looks_like_door("KITCHEN_vPanel_V1"))
        self.assertFalse(inspector._body_name_looks_like_door("GT_SidePanel_L"))

    def test_derive_board_type_from_free_tags(self):
        self.assertEqual(
            inspector._derive_board_type_tag({"defaultAttributes": {"tags": ["PARTITION", "demo"]}}),
            "partition",
        )
        self.assertEqual(
            inspector._derive_board_type_tag({"tags": ["door"]}),
            "door",
        )

    def test_scan_thickness_is_suggestion_only(self):
        record = {
            "measuredThicknessMm": 18.0,
            "metadata": {
                "schemaVersion": 1,
                "identity": {"panelId": "manual.p1"},
                "defaultAttributes": {},
            },
            "derivedTags": {"boardTypeTag": ""},
            "typedTags": {"boardTypeTag": ""},
        }
        rules = {
            "toleranceMm": 0.6,
            "rules": [
                {
                    "boardTypeTag": "partition",
                    "materialClass": "partition_board",
                    "thicknessMm": 18.0,
                }
            ],
        }
        updated = inspector._apply_thickness_classification(record, rules)
        self.assertEqual(
            updated["thicknessSuggestion"]["boardTypeTag"], "partition"
        )
        self.assertNotIn(
            "classification", updated["metadata"]
        )
        self.assertEqual(updated["derivedTags"]["boardTypeTag"], "")

    def test_body_looks_like_door_from_synthesized_kitchen(self):
        class FakeAttrs:
            def __init__(self, values):
                self._values = values

            def itemByName(self, group, name):
                key = (group, name)
                if key not in self._values:
                    return None
                return type("A", (), {"value": self._values[key]})()

        class FakeBody:
            def __init__(self):
                self.name = "KITCHEN_frontPanel_k-zone-left-door-front-panel"
                self.attributes = FakeAttrs({
                    ("CabinetNC", "module"): "kitchen",
                    ("CabinetNC", "panelKind"): "frontPanel",
                    ("CabinetNC", "panelId"): "k-zone-left-door-front-panel",
                    ("CabinetNC", "panelType"): "front_panel",
                })
                self.assemblyContext = None

        self.assertTrue(inspector.body_looks_like_door(FakeBody()))

        class CarcassBody:
            def __init__(self):
                self.name = "GT_B3"
                self.attributes = FakeAttrs({})
                self.assemblyContext = None

        self.assertFalse(inspector.body_looks_like_door(CarcassBody()))

    def test_manual_canonical_board_type_outranks_door_name(self):
        import json

        class FakeAttr:
            def __init__(self, value):
                self.value = value

        class FakeAttrs:
            def __init__(self, metadata):
                self.metadata = metadata

            def itemByName(self, group, name):
                if group == "UnifiedCabinet.Panel" and name == "metadata":
                    return FakeAttr(json.dumps(self.metadata))
                return None

        class FakeBody:
            name = "KITCHEN_frontPanel_should_not_win"
            assemblyContext = None

            def __init__(self):
                self.attributes = FakeAttrs({
                    "classification": {
                        "boardType": {
                            "value": "partition",
                            "source": "manual",
                            "locked": True,
                        }
                    }
                })

        self.assertFalse(inspector.body_looks_like_door(FakeBody()))


if __name__ == "__main__":
    unittest.main()
