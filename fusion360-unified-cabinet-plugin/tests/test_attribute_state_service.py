import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_ATTR_DIR = os.path.join(ROOT, "panel_attributes")
if PANEL_ATTR_DIR not in sys.path:
    sys.path.insert(0, PANEL_ATTR_DIR)

import attribute_state_service as state  # noqa: E402


def legacy_meta():
    return {
        "schemaVersion": 1,
        "identity": {
            "panelId": "gt.run.B3",
            "boardType": "bottom_insert_board",
            "sourceBoardType": "B3",
        },
        "defaultAttributes": {
            "materialClass": "carcass_board",
            "role": "carcass",
        },
        "lifecycle": {"state": "generated"},
        "faceRegistry": {
            "faces": [
                {"faceClass": "SURFACE", "millingSurface": "EITHER"},
                {"faceClass": "SURFACE", "millingSurface": "EITHER"},
            ],
        },
    }


class AttributeStateServiceTests(unittest.TestCase):
    def test_migration_preserves_generator_semantic_board_type(self):
        migrated = state.migrate_metadata(legacy_meta())
        self.assertEqual(
            migrated["identity"]["boardType"], "bottom_insert_board"
        )
        self.assertEqual(
            migrated["classification"]["boardType"]["value"], "carcass"
        )
        self.assertEqual(
            migrated["classification"]["boardType"]["source"], "generator"
        )
        self.assertEqual(state.migrate_metadata(migrated), migrated)

    def test_manual_board_type_locks_and_syncs_mirrors(self):
        updated, result = state.apply_board_type(
            legacy_meta(), "partition", source="manual"
        )
        self.assertTrue(result["changed"])
        self.assertEqual(
            updated["classification"]["boardType"],
            {"value": "partition", "source": "manual", "locked": True},
        )
        self.assertEqual(
            updated["identity"]["boardType"], "bottom_insert_board"
        )
        self.assertEqual(
            updated["defaultAttributes"]["materialClass"], "partition_board"
        )
        self.assertEqual(updated["defaultAttributes"]["role"], "partition")
        self.assertEqual(
            updated["derivedTags"]["boardTypeTag"], "partition"
        )

    def test_migrates_old_manual_board_and_color_as_locked(self):
        old = {
            "identity": {"panelId": "p1", "boardType": "partition"},
            "defaultAttributes": {
                "materialClass": "partition_board",
                "role": "partition",
                "doorColorName": "Alpine White",
            },
            "derivedTags": {
                "boardTypeTag": "partition",
                "colorTag": "alpine_white",
            },
            "lifecycle": {"state": "adjusted"},
        }
        migrated = state.migrate_metadata(old)
        self.assertTrue(
            migrated["classification"]["boardType"]["locked"]
        )
        self.assertEqual(
            migrated["classification"]["boardType"]["source"], "manual"
        )
        self.assertTrue(migrated["classification"]["color"]["locked"])

    def test_automatic_board_type_cannot_overwrite_manual_lock(self):
        manual, _ = state.apply_board_type(
            legacy_meta(), "partition", source="manual"
        )
        automatic, result = state.apply_board_type(
            manual, "door", source="thickness", force=True
        )
        self.assertFalse(result["changed"])
        self.assertEqual(result["reason"], "manual_locked")
        self.assertEqual(
            automatic["classification"]["boardType"]["value"], "partition"
        )

    def test_reset_unlocks_for_automatic_write(self):
        manual, _ = state.apply_board_type(
            legacy_meta(), "partition", source="manual"
        )
        unlocked = state.reset_to_auto(manual, "boardType")
        automatic, result = state.apply_board_type(
            unlocked, "door", source="thickness", force=True
        )
        self.assertTrue(result["changed"])
        self.assertEqual(
            automatic["classification"]["boardType"]["value"], "door"
        )
        self.assertFalse(
            automatic["classification"]["boardType"]["locked"]
        )

    def test_manual_face_up_lock_blocks_geometry(self):
        manual = state.mark_face_up(
            legacy_meta(), source="manual", lock=True, value="MILLING"
        )
        allowed, reason = state.can_apply_face_up(
            manual, source="hinge_cups", force=True
        )
        self.assertFalse(allowed)
        self.assertEqual(reason, "manual_locked")
        self.assertTrue(
            manual["classification"]["cuttingFace"]["locked"]
        )
        self.assertTrue(
            manual["faceRegistry"]["faceUpState"]["locked"]
        )

    def test_color_lock_and_reset(self):
        colored, _ = state.apply_color(
            legacy_meta(), "alpine_white", source="manual"
        )
        blocked, result = state.apply_color(
            colored, "oak", source="generator"
        )
        self.assertEqual(result["reason"], "manual_locked")
        self.assertEqual(
            blocked["classification"]["color"]["value"], "alpine_white"
        )
        reset = state.reset_to_auto(blocked, "color")
        changed, result = state.apply_color(
            reset, "oak", source="generator", force=True
        )
        self.assertTrue(result["changed"])
        self.assertEqual(
            changed["classification"]["color"]["value"], "oak"
        )

    def test_manual_result_is_order_independent(self):
        auto_first, _ = state.apply_board_type(
            legacy_meta(), "door", source="thickness", force=True
        )
        auto_then_manual, _ = state.apply_board_type(
            auto_first, "partition", source="manual"
        )

        manual_first, _ = state.apply_board_type(
            legacy_meta(), "partition", source="manual"
        )
        manual_then_auto, _ = state.apply_board_type(
            manual_first, "door", source="thickness", force=True
        )
        self.assertEqual(
            auto_then_manual["classification"]["boardType"],
            manual_then_auto["classification"]["boardType"],
        )
        self.assertEqual(
            auto_then_manual["derivedTags"]["boardTypeTag"],
            "partition",
        )

    def test_empty_classification_shell_recovers_legacy_color_and_board(self):
        """Empty v2 shells must not wipe previously stored derived tags."""
        old = {
            "identity": {"panelId": "door.1"},
            "defaultAttributes": {
                "materialClass": "door_board",
                "role": "door",
                "doorColorName": "Super Matt White",
            },
            "classification": {
                "boardType": {"value": "", "source": "legacy", "locked": False},
                "color": {"value": "", "source": "legacy", "locked": False},
            },
            "derivedTags": {
                "boardTypeTag": "door",
                "colorTag": "supermatt_white",
            },
            "typedTags": {
                "boardTypeTag": "door",
                "colorTag": "supermatt_white",
            },
            "faceRegistry": {
                "faces": [
                    {"faceClass": "SURFACE", "millingSurface": "MILLING"},
                    {"faceClass": "SURFACE", "millingSurface": "NON_MILLING"},
                ],
            },
        }
        migrated = state.migrate_metadata(old)
        self.assertEqual(migrated["classification"]["boardType"]["value"], "door")
        self.assertEqual(
            migrated["classification"]["color"]["value"], "supermatt_white"
        )
        self.assertEqual(migrated["derivedTags"]["colorTag"], "supermatt_white")
        self.assertEqual(migrated["derivedTags"]["boardTypeTag"], "door")
        self.assertEqual(
            migrated["classification"]["cuttingFace"]["value"], "MILLING"
        )

    def test_apply_cutting_face_same_shape_as_board_color(self):
        updated, result = state.apply_cutting_face(
            legacy_meta(), "MILLING", source="geometry"
        )
        self.assertTrue(result["changed"])
        self.assertEqual(
            updated["classification"]["cuttingFace"],
            {"value": "MILLING", "source": "geometry", "locked": False},
        )
        self.assertEqual(
            updated["faceRegistry"]["faceUpState"]["source"], "geometry"
        )

    def test_manual_cutting_face_lock_blocks_geometry(self):
        manual, _ = state.apply_cutting_face(
            legacy_meta(), "MILLING", source="manual", lock=True
        )
        blocked, result = state.apply_cutting_face(
            manual, "EITHER", source="hinge_cups", force=True
        )
        self.assertEqual(result["reason"], "manual_locked")
        self.assertEqual(
            blocked["classification"]["cuttingFace"]["value"], "MILLING"
        )
        unlocked = state.reset_to_auto(blocked, "cuttingFace")
        changed, result = state.apply_cutting_face(
            unlocked, "EITHER", source="geometry", force=True
        )
        self.assertTrue(result["changed"])
        self.assertEqual(
            changed["classification"]["cuttingFace"]["value"], "EITHER"
        )

    def test_cutting_face_from_surface_roles(self):
        self.assertEqual(
            state.cutting_face_from_surface_roles("MILLING", "NON_MILLING"),
            "MILLING",
        )
        self.assertEqual(
            state.cutting_face_from_surface_roles("EITHER", "EITHER"),
            "EITHER",
        )
        self.assertEqual(
            state.cutting_face_from_surface_roles("NON_MILLING", "NON_MILLING"),
            "",
        )


if __name__ == "__main__":
    unittest.main()
