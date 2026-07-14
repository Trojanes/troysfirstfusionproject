import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[1]
PANEL_ATTR_DIR = ROOT / "panel_attributes"
if str(PANEL_ATTR_DIR) not in sys.path:
    sys.path.insert(0, str(PANEL_ATTR_DIR))

import tag_metadata_editor as editor  # noqa: E402


class TagMetadataEditorTests(unittest.TestCase):
    def test_normalize_complementary_rejects_same_face(self):
        face = object()
        with self.assertRaises(ValueError):
            editor.normalize_complementary_surface_roles(
                "MILLING", "NON_MILLING", face, face
            )

    def test_normalize_complementary_coerces_dual_milling(self):
        role_a, role_b = editor.normalize_complementary_surface_roles(
            "MILLING", "MILLING"
        )
        self.assertEqual((role_a, role_b), ("MILLING", "NON_MILLING"))

    def test_normalize_manual_overrides_either_to_definite(self):
        role_a, role_b = editor.normalize_complementary_surface_roles(
            "EITHER", "EITHER", require_definite=True
        )
        self.assertEqual((role_a, role_b), ("MILLING", "NON_MILLING"))
        kept_a, kept_b = editor.normalize_complementary_surface_roles(
            "EITHER", "EITHER", require_definite=False
        )
        self.assertEqual((kept_a, kept_b), ("EITHER", "EITHER"))

    def test_apply_body_field_patch_updates_nested_paths(self):
        metadata = {
            "schemaVersion": 1,
            "identity": {"panelId": "panel-1", "boardType": "bottom_panel"},
            "defaultAttributes": {"materialClass": "carcass_board", "role": "carcass"},
            "lifecycle": {"state": "generated"},
        }

        updated = editor.apply_body_field_patch(metadata, "boardTypeTag", "door")
        self.assertEqual(updated["derivedTags"]["boardTypeTag"], "door")
        self.assertEqual(updated["typedTags"]["boardTypeTag"], "door")
        self.assertEqual(updated["defaultAttributes"]["materialClass"], "door_board")
        self.assertEqual(updated["defaultAttributes"]["role"], "door")
        self.assertEqual(updated["identity"]["boardType"], "bottom_panel")
        self.assertTrue(updated["classification"]["boardType"]["locked"])
        self.assertEqual(updated["classification"]["boardType"]["source"], "manual")
        # Workflow state is independent from pure nesting readiness.
        self.assertEqual(updated["lifecycle"]["state"], "adjusted")

        updated = editor.apply_body_field_patch(updated, "boardTypeTag", "partition")
        self.assertEqual(updated["derivedTags"]["boardTypeTag"], "partition")
        self.assertEqual(updated["defaultAttributes"]["materialClass"], "partition_board")
        self.assertEqual(updated["defaultAttributes"]["role"], "partition")
        self.assertEqual(updated["identity"]["boardType"], "bottom_panel")

        with self.assertRaises(ValueError):
            editor.apply_body_field_patch(updated, "materialClass", "door_board")
        with self.assertRaises(ValueError):
            editor.apply_body_field_patch(updated, "lifecycleState", "verified")

    def test_apply_face_field_patch_updates_finish_and_edge_banding(self):
        metadata = {
            "schemaVersion": 1,
            "faceClass": "SURFACE",
            "finish": {"finishId": "UNASSIGNED", "finishName": "Unassigned"},
            "edgeBanding": {"required": False, "finishId": "UNASSIGNED", "finishName": "Unassigned"},
        }

        updated = editor.apply_face_field_patch(metadata, "color", "Alpine White Gloss")
        self.assertEqual(updated["finish"]["finishId"], "Alpine White Gloss")
        self.assertEqual(updated["finish"]["finishName"], "Alpine White Gloss")

        updated = editor.apply_face_field_patch(updated, "edgeBandingRequired", "Yes")
        self.assertTrue(updated["edgeBanding"]["required"])

        updated = editor.apply_face_field_patch(updated, "edgeBandingColor", "DW-101")
        self.assertEqual(updated["edgeBanding"]["finishId"], "DW-101")

    def test_find_scan_result_matches_token_key(self):
        results = [
            {
                "selectionType": "body",
                "body": {
                    "entityToken": "abc123",
                    "panelId": "panel-1",
                    "bodyName": "BP",
                    "componentName": "OHC",
                },
                "selection": {"selectionType": "body"},
            }
        ]
        found = editor.find_scan_result(results, "token:abc123|body")
        self.assertIsNotNone(found)
        self.assertEqual(found["body"]["bodyName"], "BP")

    def test_apply_tag_scan_drafts_writes_body_metadata(self):
        results = [
            {
                "selectionType": "body",
                "body": {"entityToken": "body-token", "bodyName": "BP"},
                "selection": {"selectionType": "body", "selectionEntityToken": "body-token"},
            }
        ]
        drafts = [
            {
                "resultKey": "token:body-token|body",
                "scope": "body",
                "fieldKey": "boardTypeTag",
                "label": "Board Type",
                "draftValue": "door",
            }
        ]

        stored = {}

        class FakeAttr:
            def __init__(self, value=""):
                self.value = value

            def deleteMe(self):
                pass

        class FakeAttrs:
            def __init__(self):
                self._items = {}

            def itemByName(self, group, name):
                return self._items.get((group, name))

            def add(self, group, name, value):
                self._items[(group, name)] = FakeAttr(value)

        body = MagicMock()
        body.attributes = FakeAttrs()
        body.name = "BP"

        def resolve_entity(token, kind, _result):
            if token == "body-token" and kind == "body":
                return body
            return None

        applied, failed = editor.apply_tag_scan_drafts(results, drafts, resolve_entity)
        self.assertEqual(len(applied), 1)
        self.assertEqual(failed, [])

        raw = body.attributes.itemByName("UnifiedCabinet.Panel", "metadata").value
        metadata = json.loads(raw)
        self.assertEqual(metadata["derivedTags"]["boardTypeTag"], "door")
        # Workflow lifecycle is not overloaded by derived nesting readiness.
        self.assertEqual(metadata["lifecycle"]["state"], "adjusted")
        self.assertTrue(metadata["classification"]["boardType"]["locked"])
        self.assertNotIn(("UnifiedCabinet.Panel", "metadata"), stored)

    def test_slug_color_tag(self):
        self.assertEqual(editor.slug_color_tag("Alpine White"), "alpine_white")
        self.assertEqual(editor.slug_color_tag("  Smoked Oak!! "), "smoked_oak")
        self.assertEqual(editor.slug_color_tag(""), "")
        self.assertEqual(len(editor.slug_color_tag("a" * 50)), 32)

    def test_apply_door_color_to_metadata(self):
        metadata = {
            "schemaVersion": 1,
            "identity": {"panelId": "door-1"},
            "defaultAttributes": {"materialClass": "door_board", "role": "door"},
        }
        updated, color_tag, mode = editor.apply_door_color_to_metadata(
            metadata, "Alpine White", "single_sided"
        )
        self.assertEqual(color_tag, "alpine_white")
        self.assertEqual(mode, "SINGLE_SIDED")
        self.assertEqual(updated["defaultAttributes"]["colorName"], "Alpine White")
        self.assertEqual(updated["defaultAttributes"]["doorColorName"], "Alpine White")
        self.assertEqual(updated["defaultAttributes"]["surfaceMode"], "SINGLE_SIDED")
        self.assertEqual(updated["faceRegistry"]["surfaceMode"], "SINGLE_SIDED")
        self.assertEqual(updated["derivedTags"]["colorTag"], "alpine_white")
        self.assertEqual(updated["typedTags"]["colorTag"], "alpine_white")
        # Surface mode must not be baked into the colorTag.
        self.assertNotIn("single", color_tag)
        self.assertTrue(updated["classification"]["color"]["locked"])
        self.assertEqual(updated["classification"]["color"]["source"], "manual")

        with self.assertRaises(ValueError):
            editor.apply_door_color_to_metadata(metadata, "", "single_sided")
        with self.assertRaises(ValueError):
            editor.apply_door_color_to_metadata(metadata, "Oak", "triple")

    def test_apply_panel_color_is_generic_and_locked(self):
        metadata = {
            "schemaVersion": 1,
            "identity": {"panelId": "panel-1", "boardType": "side_panel"},
            "defaultAttributes": {
                "materialClass": "carcass_board",
                "role": "carcass",
            },
        }
        updated, color_tag, mode = editor.apply_panel_color_to_metadata(
            metadata, "Smoked Oak", "double_sided", is_door=False
        )
        self.assertEqual(color_tag, "smoked_oak")
        self.assertEqual(mode, "DOUBLE_SIDED")
        self.assertEqual(updated["defaultAttributes"]["colorName"], "Smoked Oak")
        self.assertNotIn("doorColorName", updated["defaultAttributes"])
        self.assertEqual(updated["classification"]["color"]["value"], "smoked_oak")
        self.assertTrue(updated["classification"]["color"]["locked"])

    def test_color_scope_rules(self):
        self.assertTrue(editor.color_scope_allows("doors", True))
        self.assertFalse(editor.color_scope_allows("doors", False))
        self.assertTrue(editor.color_scope_allows("panels", True))
        self.assertTrue(editor.color_scope_allows("panels", False))
        with self.assertRaises(ValueError):
            editor.color_scope_allows("invalid", True)


if __name__ == "__main__":
    unittest.main()
