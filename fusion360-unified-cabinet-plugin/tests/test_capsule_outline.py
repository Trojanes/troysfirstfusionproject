import os
import sys
import unittest

PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
NESTING_DIR = os.path.join(PLUGIN_DIR, "nesting")
if NESTING_DIR not in sys.path:
    sys.path.insert(0, NESTING_DIR)

from capsule_outline import (  # noqa: E402
    capsule_outline_from_aabb,
    capsule_outline_from_centerline,
    looks_like_lock_slot_aabb,
    looks_like_lock_slot_points,
)


class CapsuleOutlineTests(unittest.TestCase):
    def test_lock_slot_aabb_detection(self):
        self.assertTrue(looks_like_lock_slot_aabb(0, 55, 0, 15.5))
        self.assertTrue(looks_like_lock_slot_aabb(10, 25.5, 0, 55))
        self.assertFalse(looks_like_lock_slot_aabb(0, 80, 0, 20))

    def test_capsule_has_rounded_ends(self):
        points = capsule_outline_from_aabb(0, 55, 0, 15.5)
        self.assertGreater(len(points), 8)
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        self.assertAlmostEqual(max(xs) - min(xs), 55.0, places=4)
        self.assertAlmostEqual(max(ys) - min(ys), 15.5, places=4)
        # Mid-height at the extreme X should sit near the end-cap centerline.
        rightmost = max(points, key=lambda p: p[0])
        self.assertAlmostEqual(rightmost[1], 7.75, places=2)

    def test_centerline_rebuild_matches_lock_size(self):
        # Overall 55 x 15.5 → centreline length 39.5 at mid height.
        points = capsule_outline_from_centerline([[7.75, 7.75], [47.25, 7.75]], 15.5)
        self.assertTrue(looks_like_lock_slot_points(points))
        self.assertGreater(len(points), 8)


if __name__ == "__main__":
    unittest.main()
