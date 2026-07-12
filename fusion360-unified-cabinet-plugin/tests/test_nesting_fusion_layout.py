import math
import os
import sys
import unittest
from unittest.mock import MagicMock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if "adsk" not in sys.modules:
    adsk = MagicMock()
    adsk.core = MagicMock()
    adsk.fusion = MagicMock()
    sys.modules["adsk"] = adsk
    sys.modules["adsk.core"] = adsk.core
    sys.modules["adsk.fusion"] = adsk.fusion

from nesting.fusion_layout import rotation_from_to  # noqa: E402


class NestingFusionLayoutMathTests(unittest.TestCase):
    def test_same_direction_needs_no_rotation(self):
        angle, axis = rotation_from_to([0, 0, 1], [0, 0, 1])
        self.assertAlmostEqual(angle, 0.0)
        self.assertEqual(len(axis), 3)

    def test_side_face_rotates_ninety_degrees(self):
        angle, axis = rotation_from_to([1, 0, 0], [0, 0, 1])
        self.assertAlmostEqual(angle, math.pi / 2.0)
        self.assertAlmostEqual(sum(v * v for v in axis), 1.0)

    def test_opposite_face_rotates_one_eighty(self):
        angle, axis = rotation_from_to([0, 0, -1], [0, 0, 1])
        self.assertAlmostEqual(angle, math.pi)
        self.assertAlmostEqual(sum(v * v for v in axis), 1.0)


if __name__ == "__main__":
    unittest.main()
