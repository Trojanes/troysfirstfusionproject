import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from lay_flat_face_up import evaluate_face_up_normals  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()
