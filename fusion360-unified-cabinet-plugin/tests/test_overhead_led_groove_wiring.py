"""Pure-logic checks for Overhead BP LED groove plane math (no Fusion runtime)."""

from __future__ import annotations

import math
import unittest


def led_cut_plane_and_direction(face, target_bbox, effective_depth, mm_to_cm=lambda mm: mm / 10.0):
    """Mirror of fusion_adapter._led_cut_plane_and_direction for offline tests."""
    depth_cm = mm_to_cm(effective_depth)
    if face == "bottom":
        plane_nudge_mm = 0.05
        return (
            target_bbox["z0"] - plane_nudge_mm,
            "PositiveExtentDirection",
            depth_cm + mm_to_cm(plane_nudge_mm),
            "downward",
        )
    return (
        target_bbox["z1"],
        "NegativeExtentDirection",
        -depth_cm,
        "downward_into_board_from_top",
    )


def collect_led_groove_features(result):
    features = result.get("features")
    if not isinstance(features, list):
        return {}
    by_target = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        if feature.get("type") not in ("b3_groove", "t3_groove"):
            continue
        target_id = feature.get("targetBoardId")
        if not isinstance(target_id, str) or not target_id:
            continue
        by_target.setdefault(target_id, []).append(feature)
    return by_target


class OverheadLedGrooveMathTests(unittest.TestCase):
    def test_bp_feature_collected(self):
        by_target = collect_led_groove_features(
            {
                "features": [
                    {
                        "id": "BP_led_groove",
                        "type": "b3_groove",
                        "targetBoardId": "BP",
                        "face": "bottom",
                    }
                ]
            }
        )
        self.assertEqual(list(by_target.keys()), ["BP"])

    def test_bottom_plane_nudged_below_z0(self):
        bbox = {"z0": 0.0, "z1": 15.0}
        plane_z, direction, cut_signed, opening = led_cut_plane_and_direction("bottom", bbox, 6.5)
        self.assertAlmostEqual(plane_z, -0.05)
        self.assertEqual(direction, "PositiveExtentDirection")
        self.assertGreater(cut_signed, 0.65)
        self.assertEqual(opening, "downward")
        # Total cut length reaches into the board by ~6.5 mm past the true face.
        self.assertTrue(math.isclose(cut_signed * 10.0 - 0.05, 6.5, abs_tol=1e-9))


if __name__ == "__main__":
    unittest.main()
