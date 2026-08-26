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
        self.assertEqual(notch["bottomOutlineNotchReason"], "feature_outside_colour_outer")

    def test_full_cutout_outside_u_also_notches_colour_outer(self):
        colour_u = [[0, 0], [200, 0], [200, 400], [0, 400]]
        through_cut = {
            "cutType": "FULL",
            "points": [[220, 40], [380, 40], [380, 360], [220, 360]],
        }
        openings = classify_half_openings([through_cut])
        self.assertEqual(openings["status"], HALF_NONE)
        notch = classify_bottom_outline_notch(colour_u, colour_u, [through_cut])
        self.assertTrue(notch["bottomOutlineNotched"])

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

    def test_smaller_colour_outer_area_is_notched(self):
        colour_u = [[0, 0], [200, 0], [200, 400], [0, 400]]
        milling_full = [[0, 0], [400, 0], [400, 400], [0, 400]]
        notch = classify_bottom_outline_notch(colour_u, milling_full, [])
        self.assertTrue(notch["bottomOutlineNotched"])
        self.assertEqual(
            notch["bottomOutlineNotchReason"], "colour_outer_smaller_than_milling"
        )


if __name__ == "__main__":
    unittest.main()
