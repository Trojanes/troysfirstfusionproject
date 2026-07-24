import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from outline import (  # noqa: E402
    build_outline_payload,
    close_ring,
    is_simple_polygon,
    min_polygon_distance,
    outline_from_milling_svg,
    polygon_area,
    rotate_ring_set,
    signed_polygon_area,
    polygons_intersect,
    polygons_too_close,
    rectangle_polygon,
    translate_ring_set,
)


class OutlineTests(unittest.TestCase):
    def test_simple_polygon_rejects_bow_tie_and_repeated_vertices(self):
        self.assertTrue(
            is_simple_polygon([[0, 0], [100, 0], [100, 100], [0, 100]])
        )
        self.assertTrue(
            is_simple_polygon(
                [[0, 0], [100, 0], [100, 40], [40, 40], [40, 100], [0, 100]]
            )
        )
        self.assertFalse(
            is_simple_polygon([[0, 0], [100, 100], [0, 100], [100, 0]])
        )
        self.assertFalse(
            is_simple_polygon([[0, 0], [100, 0], [100, 100], [100, 0], [0, 100]])
        )

    def test_rectangle_area(self):
        ring = rectangle_polygon(100, 50)
        self.assertAlmostEqual(polygon_area(ring), 5000.0)

    def test_outline_from_milling_svg_segments(self):
        svg = {
            "outline": [
                {"pointsLocal": [[0, 0], [100, 0]]},
                {"pointsLocal": [[100, 0], [100, 40]]},
                {"pointsLocal": [[100, 40], [40, 40]]},
                {"pointsLocal": [[40, 40], [40, 100]]},
                {"pointsLocal": [[40, 100], [0, 100]]},
                {"pointsLocal": [[0, 100], [0, 0]]},
            ]
        }
        ring = outline_from_milling_svg(svg)
        self.assertGreaterEqual(len(ring), 4)
        self.assertAlmostEqual(polygon_area(ring), 100 * 40 + 40 * 60)

    def test_l_and_small_do_not_intersect_in_notch(self):
        ell = close_ring(
            [[0, 0], [100, 0], [100, 40], [40, 40], [40, 100], [0, 100]]
        )
        small = close_ring([[50, 50], [80, 50], [80, 80], [50, 80]])
        self.assertFalse(polygons_intersect(ell, small))
        self.assertGreater(min_polygon_distance(ell, small), 9.0)
        self.assertFalse(polygons_too_close(ell, small, 8.0))
        self.assertTrue(polygons_too_close(ell, small, 12.0))

    def test_build_outline_payload_normalizes(self):
        payload = build_outline_payload(
            [[10, 20], [60, 20], [60, 50], [10, 50]],
            "metadataSvg",
        )
        self.assertEqual(payload["source"], "metadataSvg")
        self.assertAlmostEqual(payload["points"][0][0], 0.0)
        self.assertAlmostEqual(payload["points"][0][1], 0.0)
        self.assertAlmostEqual(payload["widthMm"], 50.0)
        self.assertAlmostEqual(payload["depthMm"], 30.0)

    def test_outer_and_holes_share_normalization_and_winding(self):
        payload = build_outline_payload(
            [[10, 20], [10, 70], [110, 70], [110, 20]],
            "flatBody",
            holes=[{
                "points": [[30, 30], [50, 30], [50, 50], [30, 50]],
                "source": "flatBody",
                "cutType": "FULL",
                "kind": "HOLE",
                "featureId": "H1",
            }],
        )
        self.assertGreater(signed_polygon_area(payload["points"]), 0.0)
        self.assertLess(signed_polygon_area(payload["holes"][0]["points"]), 0.0)
        self.assertIn([20.0, 10.0], payload["holes"][0]["points"])
        self.assertEqual(payload["holes"][0]["featureId"], "H1")
        self.assertEqual(payload["holeCount"], 1)
        self.assertAlmostEqual(payload["holes"][0]["areaMm2"], 400.0)

    def test_invalid_outside_and_intersecting_holes_are_dropped(self):
        payload = build_outline_payload(
            [[0, 0], [100, 0], [100, 100], [0, 100]],
            "flatBody",
            holes=[
                [[10, 10], [30, 10], [30, 30], [10, 30]],
                [[20, 20], [40, 20], [40, 40], [20, 40]],
                [[90, 90], [110, 90], [110, 110], [90, 110]],
                [[50, 50], [70, 70], [50, 70], [70, 50]],
            ],
        )
        self.assertEqual(payload["holeCount"], 1)

    def test_ring_set_transforms_preserve_metadata(self):
        rings = [{"points": [[1, 2], [3, 2], [2, 4]], "featureId": "F"}]
        moved = translate_ring_set(rings, 10, -2)
        rotated = rotate_ring_set(moved, 90)
        self.assertEqual(moved[0]["featureId"], "F")
        self.assertAlmostEqual(rotated[0]["points"][0][0], 0.0, places=6)
        self.assertAlmostEqual(rotated[0]["points"][0][1], 11.0, places=6)


if __name__ == "__main__":
    unittest.main()
