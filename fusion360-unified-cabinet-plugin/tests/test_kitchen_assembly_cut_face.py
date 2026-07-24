import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KITCHEN_DIR = os.path.join(ROOT, "modules", "kitchen")
if KITCHEN_DIR not in sys.path:
    sys.path.insert(0, KITCHEN_DIR)

from assembly_cut_face import assembly_cut_face  # noqa: E402


class AssemblyCutFaceTests(unittest.TestCase):
    def setUp(self):
        self.bbox = {"x0": 100.0, "x1": 115.0, "y0": 0.0, "y1": 560.0, "z0": 55.0, "z1": 880.0}

    def test_yz_half_left_cuts_from_x0_toward_plus_x(self):
        face = assembly_cut_face(
            "YZ",
            self.bbox,
            {"kind": "slot", "slotType": "half", "side": "left"},
        )
        self.assertEqual(face["originMm"], 100.0)
        self.assertEqual(face["extrudeSign"], 1)
        self.assertEqual(face["side"], "left")

    def test_yz_half_right_cuts_from_x1_toward_minus_x(self):
        face = assembly_cut_face(
            "YZ",
            self.bbox,
            {"kind": "slot", "slotType": "half", "side": "right"},
        )
        self.assertEqual(face["originMm"], 115.0)
        self.assertEqual(face["extrudeSign"], -1)
        self.assertEqual(face["side"], "right")

    def test_yz_through_keeps_legacy_plus_face(self):
        face = assembly_cut_face(
            "YZ",
            self.bbox,
            {"kind": "slot", "slotType": "through", "side": "left"},
        )
        self.assertEqual(face["originMm"], 115.0)
        self.assertEqual(face["extrudeSign"], -1)
        self.assertFalse(face["isHalf"])

    def test_half_without_side_defaults_to_right_face(self):
        face = assembly_cut_face(
            "YZ",
            self.bbox,
            {"kind": "slot", "slotType": "half"},
        )
        self.assertEqual(face["originMm"], 115.0)
        self.assertEqual(face["extrudeSign"], -1)
        self.assertEqual(face["side"], "right")


if __name__ == "__main__":
    unittest.main()
