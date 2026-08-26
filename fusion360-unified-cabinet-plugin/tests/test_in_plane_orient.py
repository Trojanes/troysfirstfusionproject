import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from in_plane_orient import (  # noqa: E402
    grain_angle_deg,
    grain_mm_from_metadata,
    in_plane_rotation_deg,
)


class InPlaneOrientTests(unittest.TestCase):
    def test_no_grain_puts_longest_edge_on_x(self):
        self.assertEqual(in_plane_rotation_deg(450, 720, None), -90.0)
        self.assertEqual(in_plane_rotation_deg(720, 450, None), 0.0)

    def test_grain_along_short_edge_rotates_onto_x(self):
        # After milling-up a standing door: X=450 (width), Y=720 (height).
        # Vertical grain stored 720. Rotate so 720 lies on +X.
        self.assertEqual(in_plane_rotation_deg(450, 720, 720), -90.0)
        self.assertEqual(grain_angle_deg(450, 720, 720, rotation_deg=-90.0), 0)

    def test_grain_already_on_x_stays(self):
        self.assertEqual(in_plane_rotation_deg(720, 450, 720), 0.0)
        self.assertEqual(grain_angle_deg(720, 450, 720, rotation_deg=0.0), 0)

    def test_two_doors_same_grain_same_rotation(self):
        first = in_plane_rotation_deg(450, 720, 720)
        second = in_plane_rotation_deg(500, 720, 720)
        self.assertEqual(first, second)
        self.assertEqual(first, -90.0)

    def test_reads_grain_from_classification(self):
        mm = grain_mm_from_metadata(
            {"classification": {"grainAlongMm": {"value": 720, "source": "manual"}}}
        )
        self.assertEqual(mm, 720.0)

    def test_missing_grain_is_empty(self):
        self.assertEqual(grain_mm_from_metadata({}), "")


if __name__ == "__main__":
    unittest.main()
