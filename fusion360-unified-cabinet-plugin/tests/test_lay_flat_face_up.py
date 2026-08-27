import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from lay_flat_face_up import evaluate_face_up_normals  # noqa: E402
import lay_flat_face_up as face_up_mod  # noqa: E402


class LayFlatFaceUpTests(unittest.TestCase):
    def test_pass_milling_plus_z_colour_minus_z(self):
        result = evaluate_face_up_normals(
            [0.0, 0.0, 1.0],
            [0.0, 0.0, -1.0],
            cutting_face="MILLING",
        )
        self.assertTrue(result["ok"])
        self.assertTrue(result["millingOk"])
        self.assertTrue(result["colourOk"])
        self.assertEqual(result["reasons"], [])

    def test_fail_milling_sideways(self):
        result = evaluate_face_up_normals(
            [1.0, 0.0, 0.0],
            [-1.0, 0.0, 0.0],
            cutting_face="MILLING",
        )
        self.assertFalse(result["ok"])
        self.assertIn("milling_not_plus_z", result["reasons"])
        self.assertIn("colour_not_minus_z", result["reasons"])

    def test_fail_upside_down(self):
        result = evaluate_face_up_normals(
            [0.0, 0.0, -1.0],
            [0.0, 0.0, 1.0],
            cutting_face="MILLING",
        )
        self.assertFalse(result["ok"])
        self.assertIn("upside_down", result["reasons"])

    def test_near_vertical_within_tolerance(self):
        # Unit normals with nz = ±0.95 (boundary of default minDot).
        result = evaluate_face_up_normals(
            [0.0, 0.3122498999, 0.95],
            [0.0, -0.3122498999, -0.95],
            cutting_face="MILLING",
            min_dot=0.95,
        )
        self.assertTrue(result["ok"])

    def test_missing_normals(self):
        result = evaluate_face_up_normals(None, [0, 0, -1])
        self.assertFalse(result["ok"])
        self.assertIn("missing_normals", result["reasons"])

    def test_bottom_half_recommends_transactional_fix(self):
        top = object()
        bottom = object()
        with mock.patch.object(
            face_up_mod, "_fast_broad_faces", return_value=(top, bottom)
        ), mock.patch.object(
            face_up_mod,
            "face_world_plane",
            side_effect=[
                ([0, 0, 1], [0, 0, 1]),
                ([0, 0, -1], [0, 0, 0]),
            ],
        ), mock.patch.object(
            face_up_mod,
            "_assign_milling_and_colour",
            return_value=(top, bottom, [0, 0, 1], [0, 0, -1], "role"),
        ), mock.patch.object(
            face_up_mod,
            "inspect_half_openings",
            return_value={
                "ok": True,
                "status": "bottomHalf",
                "topHalfCount": 0,
                "bottomHalfCount": 1,
                "unknownHalfCount": 0,
            },
        ):
            result = face_up_mod.evaluate_body_faces_up(object())
        self.assertFalse(result["ok"])
        self.assertTrue(result["autoFixRecommended"])
        self.assertIn("feature_face_not_machining", result["reasons"])

    def test_double_side_is_blocked_not_auto_fixed(self):
        top = object()
        bottom = object()
        with mock.patch.object(
            face_up_mod, "_fast_broad_faces", return_value=(top, bottom)
        ), mock.patch.object(
            face_up_mod,
            "face_world_plane",
            side_effect=[
                ([0, 0, 1], [0, 0, 1]),
                ([0, 0, -1], [0, 0, 0]),
            ],
        ), mock.patch.object(
            face_up_mod,
            "_assign_milling_and_colour",
            return_value=(top, bottom, [0, 0, 1], [0, 0, -1], "role"),
        ), mock.patch.object(
            face_up_mod,
            "inspect_half_openings",
            return_value={
                "ok": True,
                "status": "doubleSide",
                "topHalfCount": 1,
                "bottomHalfCount": 1,
                "unknownHalfCount": 0,
            },
        ):
            result = face_up_mod.evaluate_body_faces_up(object())
        self.assertFalse(result["ok"])
        self.assertFalse(result["autoFixRecommended"])
        self.assertIn("double_side_unsupported", result["reasons"])

    def test_colour_outer_notch_is_bottom_half_and_auto_fixed(self):
        top = object()
        bottom = object()
        with mock.patch.object(
            face_up_mod, "_fast_broad_faces", return_value=(top, bottom)
        ), mock.patch.object(
            face_up_mod,
            "face_world_plane",
            side_effect=[
                ([0, 0, 1], [0, 0, 1]),
                ([0, 0, -1], [0, 0, 0]),
            ],
        ), mock.patch.object(
            face_up_mod,
            "_assign_milling_and_colour",
            return_value=(top, bottom, [0, 0, 1], [0, 0, -1], "role"),
        ), mock.patch.object(
            face_up_mod,
            "inspect_half_openings",
            return_value={
                "ok": True,
                "status": "topHalf",
                "topHalfCount": 1,
                "bottomHalfCount": 0,
                "unknownHalfCount": 0,
                "bottomOutlineNotched": True,
                "bottomOutlineNotchReason": "colour_outer_smaller_than_milling",
            },
        ):
            result = face_up_mod.evaluate_body_faces_up(object())
        self.assertFalse(result["ok"])
        self.assertTrue(result["autoFixRecommended"])
        self.assertTrue(result["bottomOutlineNotched"])
        self.assertIn("feature_face_not_machining", result["reasons"])
        self.assertEqual(result["halfStatus"], "bottomHalf")
        self.assertEqual(
            result.get("orientationOverride"), "colour_outer_smaller_than_milling"
        )

    def test_top_rebate_passes_when_floor_votes_intact_underside(self):
        top = object()
        bottom = object()
        with mock.patch.object(
            face_up_mod, "_fast_broad_faces", return_value=(top, bottom)
        ), mock.patch.object(
            face_up_mod,
            "face_world_plane",
            side_effect=[
                ([0, 0, 1], [0, 0, 1]),
                ([0, 0, -1], [0, 0, 0]),
            ],
        ), mock.patch.object(
            face_up_mod,
            "_assign_milling_and_colour",
            return_value=(top, bottom, [0, 0, 1], [0, 0, -1], "role"),
        ), mock.patch.object(
            face_up_mod,
            "inspect_half_openings",
            return_value={
                "ok": True,
                "status": "bottomHalf",
                "topHalfCount": 0,
                "bottomHalfCount": 1,
                "unknownHalfCount": 0,
                "bottomOutlineNotched": False,
                "topOutlineNotched": True,
                "topOutlineNotchReason": "rebate_on_plus_z",
            },
        ):
            result = face_up_mod.evaluate_body_faces_up(object())
        self.assertTrue(result["ok"])
        self.assertFalse(result["autoFixRecommended"])
        self.assertEqual(result["halfStatus"], "topHalf")
        self.assertEqual(result.get("orientationOverride"), "rebate_on_plus_z")


if __name__ == "__main__":
    unittest.main()
