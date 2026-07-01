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
        self.assertEqual(updated["lifecycle"]["state"], "adjusted")

        updated = editor.apply_body_field_patch(updated, "materialClass", "door_board")
        self.assertEqual(updated["defaultAttributes"]["materialClass"], "door_board")

        updated = editor.apply_body_field_patch(updated, "lifecycleState", "verified")
        self.assertEqual(updated["lifecycle"]["state"], "verified")

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
        self.assertEqual(metadata["lifecycle"]["state"], "adjusted")
        self.assertNotIn(("UnifiedCabinet.Panel", "metadata"), stored)


if __name__ == "__main__":
    unittest.main()
