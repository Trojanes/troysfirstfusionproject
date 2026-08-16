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
    classify_half_openings,
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


if __name__ == "__main__":
    unittest.main()
