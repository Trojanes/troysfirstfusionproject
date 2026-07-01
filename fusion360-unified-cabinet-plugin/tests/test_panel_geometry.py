import os
import sys
import unittest


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
METADATA_DIR = os.path.join(PLUGIN_DIR, "metadata")
if METADATA_DIR not in sys.path:
    sys.path.insert(0, METADATA_DIR)

from panel_geometry import (  # noqa: E402
    CUT_TYPE_FULL,
    CUT_TYPE_HALF,
    FEATURE_KIND_GROOVE,
    FEATURE_KIND_HOLE,
    FEATURE_KIND_POCKET,
    build_svg_document,
    bounds_of,
    classify_cut_type,
    feature_kind_from_loop,
    plane_axes_for,
    polyline_to_path,
    project_local_to_2d,
    thickness_axis_from_normal,
)


class PanelGeometryPureTests(unittest.TestCase):
    def test_thickness_axis_from_normal(self):
        self.assertEqual(thickness_axis_from_normal([0, 0, 1]), 2)
        self.assertEqual(thickness_axis_from_normal([0.99, 0.0, 0.1]), 0)
        self.assertEqual(thickness_axis_from_normal([0.0, -1.0, 0.0]), 1)

    def test_plane_axes_for(self):
        self.assertEqual(plane_axes_for(2), [0, 1])
        self.assertEqual(plane_axes_for(0), [1, 2])
        self.assertEqual(plane_axes_for(1), [0, 2])

    def test_project_local_to_2d_drops_thickness(self):
        self.assertEqual(project_local_to_2d([10, 20, 999], 2), (10.0, 20.0))
        self.assertEqual(project_local_to_2d([999, 20, 30], 0), (20.0, 30.0))

    def test_classify_cut_type_through_when_reaches_opposite(self):
        self.assertEqual(classify_cut_type(True, None, 18.0), CUT_TYPE_FULL)

    def test_classify_cut_type_full_when_depth_equals_thickness(self):
        self.assertEqual(classify_cut_type(False, 18.0, 18.0), CUT_TYPE_FULL)

    def test_classify_cut_type_half_when_blind(self):
        self.assertEqual(classify_cut_type(False, 6.0, 18.0), CUT_TYPE_HALF)
        self.assertEqual(classify_cut_type(False, None, 18.0), CUT_TYPE_HALF)

    def test_feature_kind(self):
        self.assertEqual(feature_kind_from_loop(1, True), FEATURE_KIND_HOLE)
        self.assertEqual(feature_kind_from_loop(4, False), FEATURE_KIND_GROOVE)
        self.assertEqual(feature_kind_from_loop(6, False), FEATURE_KIND_POCKET)

    def test_polyline_to_path(self):
        path = polyline_to_path([(0, 0), (10, 0), (10, 5)], close=True)
        self.assertEqual(path, "M 0 0 L 10 0 L 10 5 Z")

    def test_bounds_of(self):
        self.assertEqual(bounds_of([[(0, 0), (10, 5)], [(-2, 3)]]), (-2.0, 0.0, 10.0, 5.0))

    def test_build_svg_document_outer_and_feature(self):
        outer = [
            {"points": [(0, 0), (100, 0)], "edgeToken": "E1", "signature": {"lengthMm": 100}},
            {"points": [(100, 0), (100, 50)], "edgeToken": "E2", "signature": {"lengthMm": 50}},
        ]
        inner = [
            {
                "featureId": "FEAT-01",
                "cutType": CUT_TYPE_HALF,
                "kind": FEATURE_KIND_HOLE,
                "isCircle": True,
                "center": (50, 25),
                "radiusMm": 5.0,
                "depthMm": 12.0,
            }
        ]
        bounds = bounds_of([[(0, 0), (100, 50)]])
        doc = build_svg_document(outer, inner, bounds)
        self.assertIn("<svg", doc["svg"])
        self.assertIn('data-cut-type="HALF"', doc["svg"])
        self.assertIn("<circle", doc["svg"])
        self.assertEqual(doc["viewBox"], "0 0 100 50")
        self.assertEqual(len(doc["outline"]), 2)
        self.assertEqual(doc["outline"][0]["edgeToken"], "E1")
        self.assertEqual(doc["features"][0]["cutType"], CUT_TYPE_HALF)

    def test_build_svg_full_cut_marked(self):
        outer = [{"points": [(0, 0), (10, 0)], "edgeToken": "E", "signature": None}]
        inner = [
            {
                "featureId": "FEAT-02",
                "cutType": CUT_TYPE_FULL,
                "kind": "groove",
                "isCircle": False,
                "points": [(2, 2), (8, 2), (8, 4), (2, 4)],
            }
        ]
        doc = build_svg_document(outer, inner, bounds_of([[(0, 0), (10, 6)]]))
        self.assertIn('data-cut-type="FULL"', doc["svg"])
        self.assertEqual(doc["features"][0]["cutType"], CUT_TYPE_FULL)


if __name__ == "__main__":
    unittest.main()
