import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from lay_flat_orientation import (  # noqa: E402
    HALF_BOTTOM,
    HALF_DOUBLE,
    HALF_NONE,
    HALF_TOP,
    classify_bottom_outline_notch,
    classify_half_openings,
    feature_bites_outer,
    refine_half_orientation,
)


class LayFlatOrientationTests(unittest.TestCase):
    def test_top_half_is_manufacturing_ready_orientation(self):
        result = classify_half_openings(
            [
                {
                    "featureId": "G1",
                    "kind": "groove",
                    "cutType": "HALF",
                    "openSurfaceIs": "A",
                }
            ]
        )
        self.assertEqual(result["status"], HALF_TOP)
        self.assertEqual(result["topHalfCount"], 1)
        self.assertEqual(result["bottomHalfCount"], 0)

    def test_bottom_half_requires_repair(self):
        result = classify_half_openings(
            [
                {
                    "featureId": "P1",
                    "kind": "pocket",
                    "cutType": "HALF",
                    "openSurfaceIs": "B",
                }
            ]
        )
        self.assertEqual(result["status"], HALF_BOTTOM)
        self.assertEqual(result["bottomHalfCount"], 1)

    def test_half_on_both_sides_is_double_side(self):
        result = classify_half_openings(
            [
                {"cutType": "HALF", "openSurfaceIs": "A"},
                {"cutType": "HALF", "openSurfaceIs": "B"},
            ]
        )
        self.assertEqual(result["status"], HALF_DOUBLE)
        self.assertEqual(result["topHalfCount"], 1)
        self.assertEqual(result["bottomHalfCount"], 1)

    def test_full_features_do_not_choose_orientation(self):
        result = classify_half_openings(
            [
                {"cutType": "FULL", "openSurfaceIs": "A"},
                {"cutType": "FULL", "openSurfaceIs": "B"},
            ]
        )
        self.assertEqual(result["status"], HALF_NONE)
        self.assertEqual(result["topHalfCount"], 0)
        self.assertEqual(result["bottomHalfCount"], 0)

    def test_unknown_half_is_reported_not_guessed(self):
        result = classify_half_openings(
            [{"cutType": "HALF", "openSurfaceIs": ""}]
        )
        self.assertEqual(result["status"], HALF_NONE)
        self.assertEqual(result["unknownHalfCount"], 1)

    def test_top_half_pocket_outside_u_notches_colour_outer(self):
        # Intact underside would be 400x400; eaten outer is a C/U missing x>200.
        colour_u = [[0, 0], [200, 0], [200, 400], [0, 400]]
        milling_full = [[0, 0], [400, 0], [400, 400], [0, 400]]
        pocket = {
            "cutType": "HALF",
            "openSurfaceIs": "A",
            "points": [[220, 40], [380, 40], [380, 360], [220, 360]],
        }
        openings = classify_half_openings([pocket])
        self.assertEqual(openings["status"], HALF_TOP)
        notch = classify_bottom_outline_notch(colour_u, milling_full, [pocket])
        self.assertTrue(notch["bottomOutlineNotched"])
        self.assertEqual(
            notch["bottomOutlineNotchReason"], "colour_outer_smaller_than_milling"
        )

    def test_broken_small_colour_ring_passes_when_face_areas_match(self):
        colour_stub = [[0, 0], [40, 0], [40, 40], [0, 40]]
        milling_full = [[0, 0], [400, 0], [400, 700], [0, 700]]
        colour_face = type("F", (), {"area": 400.0 * 700.0})()
        milling_face = type("F", (), {"area": 400.0 * 700.0})()
        notch = classify_bottom_outline_notch(
            colour_stub,
            milling_full,
            [],
            bottom_face=colour_face,
            top_face=milling_face,
        )
        self.assertFalse(notch["bottomOutlineNotched"])

    def test_small_edge_lock_does_not_fail_colour_outer(self):
        # Door ~400x700; colour BRep walks into a 55x55 lock bite on the left.
        milling_full = [[0, 0], [400, 0], [400, 700], [0, 700]]
        colour_lock_bite = [
            [0, 0],
            [400, 0],
            [400, 700],
            [0, 700],
            [0, 413],
            [55, 413],
            [55, 358],
            [0, 358],
        ]
        lock = {
            "cutType": "FULL",
            "through": True,
            "kind": "throughCutout",
            "hardwareType": "lock_cutout",
            "points": [[0, 358], [55, 358], [55, 413], [0, 413]],
        }
        notch = classify_bottom_outline_notch(
            colour_lock_bite, milling_full, [lock]
        )
        self.assertFalse(notch["bottomOutlineNotched"])

    def test_full_cutout_outside_same_size_outers_is_not_orientation_fail(self):
        colour_u = [[0, 0], [200, 0], [200, 400], [0, 400]]
        through_cut = {
            "cutType": "FULL",
            "points": [[220, 40], [380, 40], [380, 360], [220, 360]],
        }
        openings = classify_half_openings([through_cut])
        self.assertEqual(openings["status"], HALF_NONE)
        notch = classify_bottom_outline_notch(colour_u, colour_u, [through_cut])
        self.assertFalse(notch["bottomOutlineNotched"])

    def test_edge_open_groove_inside_full_colour_outer_passes(self):
        colour_full = [[0, 0], [400, 0], [400, 400], [0, 400]]
        milling_notched = [[0, 0], [200, 0], [200, 400], [0, 400]]
        groove = {
            "cutType": "HALF",
            "openSurfaceIs": "A",
            "points": [[0, 40], [40, 40], [40, 360], [0, 360]],
        }
        self.assertFalse(feature_bites_outer(groove["points"], colour_full))
        notch = classify_bottom_outline_notch(
            colour_full, milling_notched, [groove]
        )
        self.assertFalse(notch["bottomOutlineNotched"])

    def test_smaller_colour_skin_overrides_false_top_half(self):
        refined = refine_half_orientation(
            {
                "status": HALF_TOP,
                "topHalfCount": 1,
                "bottomHalfCount": 0,
                "bottomOutlineNotched": True,
                "bottomOutlineNotchReason": "colour_outer_smaller_than_milling",
            }
        )
        self.assertEqual(refined["status"], HALF_BOTTOM)
        self.assertEqual(refined["bottomHalfCount"], 1)
        self.assertEqual(refined["topHalfCount"], 0)
        self.assertEqual(
            refined["orientationOverride"], "colour_outer_smaller_than_milling"
        )

    def test_lock_nick_without_area_drop_keeps_top_half(self):
        refined = refine_half_orientation(
            {
                "status": HALF_TOP,
                "topHalfCount": 1,
                "bottomHalfCount": 0,
                "bottomOutlineNotched": False,
            }
        )
        self.assertEqual(refined["status"], HALF_TOP)
        self.assertEqual(refined["bottomHalfCount"], 0)

    def test_double_side_is_not_overridden_by_colour_notch(self):
        refined = refine_half_orientation(
            {
                "status": HALF_DOUBLE,
                "topHalfCount": 1,
                "bottomHalfCount": 1,
                "bottomOutlineNotched": True,
            }
        )
        self.assertEqual(refined["status"], HALF_DOUBLE)

    def test_smaller_top_skin_overrides_false_bottom_half(self):
        refined = refine_half_orientation(
            {
                "status": HALF_BOTTOM,
                "topHalfCount": 0,
                "bottomHalfCount": 1,
                "bottomOutlineNotched": False,
                "topOutlineNotched": True,
                "topOutlineNotchReason": "rebate_on_plus_z",
            }
        )
        self.assertEqual(refined["status"], HALF_TOP)
        self.assertEqual(refined["topHalfCount"], 1)
        self.assertEqual(refined["bottomHalfCount"], 0)
        self.assertEqual(refined["orientationOverride"], "rebate_on_plus_z")

    def test_smaller_colour_outer_area_is_notched(self):
        colour_u = [[0, 0], [200, 0], [200, 400], [0, 400]]
        milling_full = [[0, 0], [400, 0], [400, 400], [0, 400]]
        notch = classify_bottom_outline_notch(colour_u, milling_full, [])
        self.assertTrue(notch["bottomOutlineNotched"])
        self.assertFalse(notch["topOutlineNotched"])
        self.assertEqual(
            notch["bottomOutlineNotchReason"], "colour_outer_smaller_than_milling"
        )

    def test_smaller_top_outer_area_is_rebate_up(self):
        rebate = [[0, 0], [200, 0], [200, 400], [0, 400]]
        full = [[0, 0], [400, 0], [400, 400], [0, 400]]
        notch = classify_bottom_outline_notch(full, rebate, [])
        self.assertFalse(notch["bottomOutlineNotched"])
        self.assertTrue(notch["topOutlineNotched"])
        self.assertEqual(notch["topOutlineNotchReason"], "rebate_on_plus_z")


if __name__ == "__main__":
    unittest.main()
