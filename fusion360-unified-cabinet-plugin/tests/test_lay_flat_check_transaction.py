import os
import sys
import types
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [ROOT, os.path.join(ROOT, "panel_attributes")]

if "adsk" not in sys.modules:
    adsk = types.ModuleType("adsk")
    adsk.core = types.ModuleType("adsk.core")
    adsk.fusion = types.ModuleType("adsk.fusion")
    adsk.doEvents = lambda: None
    sys.modules["adsk"] = adsk
    sys.modules["adsk.core"] = adsk.core
    sys.modules["adsk.fusion"] = adsk.fusion

import controller as controller_mod  # noqa: E402


def _metadata(role_a="MILLING", role_b="NON_MILLING", locked=True):
    return {
        "classification": {
            "cuttingFace": {
                "value": "MILLING",
                "source": "manual" if locked else "half_feature",
                "locked": locked,
            }
        },
        "faceRegistry": {
            "faces": [
                {
                    "faceId": "A",
                    "faceClass": "SURFACE",
                    "millingSurface": role_a,
                    "millingLocked": locked,
                },
                {
                    "faceId": "B",
                    "faceClass": "SURFACE",
                    "millingSurface": role_b,
                    "millingLocked": locked,
                },
            ]
        },
    }


class LayFlatCheckTransactionTests(unittest.TestCase):
    def setUp(self):
        self.method = (
            controller_mod.PanelAttributesController._auto_fix_lay_flat_bottom_half
        )
        self.owner = object()
        self.root = object()
        self.copy = mock.MagicMock()
        self.copy.name = "LAY_COPY"
        self.source = mock.MagicMock()
        self.source.name = "SOURCE"
        self.source_snapshot = {"bodyMetadata": _metadata(), "faces": []}
        self.copy_snapshot = {"bodyMetadata": _metadata(), "faces": []}
        self.after_source = _metadata(
            role_a="NON_MILLING", role_b="MILLING", locked=False
        )

    def _base_patches(self):
        return (
            mock.patch.object(
                controller_mod.panel_source_ref,
                "from_lay_flat_body",
                return_value={"entityToken": "TOKEN-1"},
            ),
            mock.patch.object(
                controller_mod.panel_source_ref,
                "key",
                return_value="token:TOKEN-1",
            ),
            mock.patch.object(
                controller_mod.panel_body_resolver,
                "resolve_source_bodies_for_lay_flat",
                return_value=([self.source], {}, "entityToken"),
            ),
            mock.patch.object(
                controller_mod.tag_metadata_editor,
                "snapshot_milling_state",
                side_effect=[self.copy_snapshot, self.source_snapshot],
            ),
            mock.patch.object(
                controller_mod.milling_surface_propagation,
                "analyze_milling_surfaces",
                return_value={
                    "updatedCount": 1,
                    "updated": [{"source": "half_slot"}],
                    "skipped": [],
                },
            ),
            mock.patch.object(
                controller_mod.tag_metadata_editor,
                "apply_surface_milling_roles",
            ),
            mock.patch.object(
                controller_mod.tag_metadata_editor,
                "_read_body_metadata_raw",
                side_effect=[(self.after_source, None), (_metadata(locked=False), None)],
            ),
            mock.patch.object(
                controller_mod.tag_metadata_editor, "_write_body_metadata"
            ),
        )

    def test_success_uses_exact_source_then_flips_copy(self):
        patches = self._base_patches()
        precheck = {
            "ok": False,
            "halfStatus": "bottomHalf",
            "halfInspection": {
                "bottomFace": object(),
                "topFace": object(),
            },
        }
        postcheck = {"ok": True, "halfStatus": "topHalf"}
        with patches[0], patches[1], patches[2] as resolve, patches[3], \
             patches[4], patches[5], patches[6], patches[7], mock.patch.object(
                 controller_mod.nesting_lay_flat_fusion,
                 "flip_lay_flat_body_thickness",
                 return_value={"ok": True},
             ), mock.patch.object(
                 controller_mod.nesting_lay_flat_face_up,
                 "evaluate_body_faces_up",
                 side_effect=[precheck, postcheck],
             ):
            fixed = set()
            result = self.method(
                self.owner,
                self.root,
                self.copy,
                min_dot=0.95,
                source_fixed_keys=fixed,
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["sourceUpdated"])
        self.assertTrue(result["geometryFlipped"])
        self.assertIn("token:TOKEN-1", fixed)
        self.assertFalse(
            resolve.call_args.kwargs["allow_panel_id_fallback"]
        )

    def test_failed_recheck_flips_back_and_restores_both_states(self):
        patches = self._base_patches()
        restore = mock.Mock()
        geometry_flip = mock.Mock(
            side_effect=[{"ok": True}, {"ok": True}]
        )
        precheck = {
            "ok": False,
            "halfStatus": "bottomHalf",
            "halfInspection": {
                "bottomFace": object(),
                "topFace": object(),
            },
        }
        postcheck = {
            "ok": False,
            "reasons": ["feature_face_not_machining"],
        }
        with patches[0], patches[1], patches[2], patches[3], patches[4], \
             patches[5], patches[6], patches[7], mock.patch.object(
                 controller_mod.nesting_lay_flat_fusion,
                 "flip_lay_flat_body_thickness",
                 geometry_flip,
             ), mock.patch.object(
                 controller_mod.nesting_lay_flat_face_up,
                 "evaluate_body_faces_up",
                 side_effect=[precheck, postcheck],
             ), mock.patch.object(
                 controller_mod.tag_metadata_editor,
                 "restore_milling_state",
                 restore,
             ):
            result = self.method(
                self.owner,
                self.root,
                self.copy,
                source_fixed_keys=set(),
            )
        self.assertFalse(result["ok"])
        self.assertTrue(result["rollback"])
        self.assertEqual(geometry_flip.call_count, 2)
        self.assertEqual(restore.call_count, 2)

    def test_second_copy_does_not_write_same_source_twice(self):
        precheck = {
            "ok": False,
            "halfStatus": "bottomHalf",
            "halfInspection": {
                "bottomFace": object(),
                "topFace": object(),
            },
        }
        postcheck = {"ok": True, "halfStatus": "topHalf"}
        analyze_source = mock.Mock()
        with mock.patch.object(
            controller_mod.panel_source_ref,
            "from_lay_flat_body",
            return_value={"entityToken": "TOKEN-1"},
        ), mock.patch.object(
            controller_mod.panel_source_ref,
            "key",
            return_value="token:TOKEN-1",
        ), mock.patch.object(
            controller_mod.panel_body_resolver,
            "resolve_source_bodies_for_lay_flat",
            return_value=([self.source], {}, "entityToken"),
        ), mock.patch.object(
            controller_mod.tag_metadata_editor,
            "snapshot_milling_state",
            return_value=self.copy_snapshot,
        ), mock.patch.object(
            controller_mod.milling_surface_propagation,
            "analyze_milling_surfaces",
            analyze_source,
        ), mock.patch.object(
            controller_mod.tag_metadata_editor,
            "apply_surface_milling_roles",
        ), mock.patch.object(
            controller_mod.tag_metadata_editor,
            "_read_body_metadata_raw",
            return_value=(_metadata(locked=False), None),
        ), mock.patch.object(
            controller_mod.tag_metadata_editor,
            "_write_body_metadata",
        ), mock.patch.object(
            controller_mod.nesting_lay_flat_fusion,
            "flip_lay_flat_body_thickness",
            return_value={"ok": True},
        ), mock.patch.object(
            controller_mod.nesting_lay_flat_face_up,
            "evaluate_body_faces_up",
            side_effect=[precheck, postcheck],
        ):
            fixed = {"token:TOKEN-1"}
            result = self.method(
                self.owner,
                self.root,
                self.copy,
                source_fixed_keys=fixed,
            )
        self.assertTrue(result["ok"])
        self.assertFalse(result["sourceUpdated"])
        analyze_source.assert_not_called()


if __name__ == "__main__":
    unittest.main()
