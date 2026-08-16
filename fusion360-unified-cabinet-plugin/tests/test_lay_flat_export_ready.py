import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from lay_flat_analyze import ANALYZED_STATE  # noqa: E402
from lay_flat_export_ready import evaluate_metadata  # noqa: E402
from outline_cache import CACHE_SCHEMA  # noqa: E402


def _ready_metadata(**overrides):
    meta = {
        "identity": {"panelId": "P-1"},
        "lifecycle": {"state": ANALYZED_STATE},
        "dimensions": {"thicknessMm": 18.0, "widthMm": 600.0, "depthMm": 400.0},
        "classification": {
            "boardType": {"value": "PB"},
            "color": {"value": "White"},
            "cuttingFace": {"value": "MILLING"},
        },
        "nestingFlatOutline": {
            "schemaVersion": CACHE_SCHEMA,
            "geometrySignature": "sig-1",
            "widthMm": 600.0,
            "depthMm": 400.0,
            "halfOpeningStatus": "none",
            "bottomHalfCount": 0,
            "outline": {
                "source": "flatBody",
                "points": [[0, 0], [600, 0], [600, 400], [0, 400]],
                "pointCount": 4,
            },
        },
        "features": [],
    }
    meta.update(overrides)
    return meta


class LayFlatExportReadyTests(unittest.TestCase):
    def test_ready_when_analyzed_outline_and_classification_ok(self):
        result = evaluate_metadata(_ready_metadata(), geometry_signature="sig-1")
        self.assertTrue(result["ready"])
        self.assertEqual(result["reasons"], [])

    def test_not_analyzed(self):
        meta = _ready_metadata(lifecycle={"state": "lay_flat"})
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("not_analyzed", result["reasons"])

    def test_analyze_stale_signature_mismatch(self):
        result = evaluate_metadata(_ready_metadata(), geometry_signature="sig-other")
        self.assertFalse(result["ready"])
        self.assertIn("analyze_stale", result["reasons"])

    def test_outline_missing(self):
        meta = _ready_metadata()
        meta["nestingFlatOutline"]["outline"] = {"source": "flatBody", "points": []}
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("outline_missing", result["reasons"])

    def test_degenerate_outline_rejected(self):
        meta = _ready_metadata()
        meta["nestingFlatOutline"]["outline"]["points"] = [[0, 0], [10, 0], [20, 0]]
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("outline_missing", result["reasons"])

    def test_bbox_fallback(self):
        meta = _ready_metadata()
        meta["nestingFlatOutline"]["outline"]["source"] = "bboxFallback"
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("non_production_outline", result["reasons"])

    def test_rectangle_fallback(self):
        meta = _ready_metadata()
        meta["nestingFlatOutline"]["outline"]["source"] = "rectangle"
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("non_production_outline", result["reasons"])

    def test_thickness_required(self):
        meta = _ready_metadata(dimensions={"thicknessMm": 0, "widthMm": 100, "depthMm": 100})
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("thickness", result["reasons"])

    def test_classification_missing(self):
        meta = _ready_metadata(
            classification={
                "boardType": {"value": ""},
                "color": {"value": "unassigned"},
                "cuttingFace": {"value": ""},
            }
        )
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("board_type", result["reasons"])
        self.assertIn("color", result["reasons"])
        self.assertIn("cutting_face", result["reasons"])

    def test_double_side_blind_features(self):
        meta = _ready_metadata(
            features=[
                {
                    "featureId": "F1",
                    "kind": "pocket",
                    "cutType": "HALF",
                    "openSurfaceIs": "A",
                    "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
                },
                {
                    "featureId": "F2",
                    "kind": "pocket",
                    "cutType": "HALF",
                    "openSurfaceIs": "B",
                    "points": [[20, 0], [30, 0], [30, 10], [20, 10]],
                },
            ]
        )
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("double_side_unsupported", result["reasons"])

    def test_feature_face_unknown(self):
        meta = _ready_metadata(
            features=[
                {
                    "featureId": "F1",
                    "kind": "pocket",
                    "cutType": "HALF",
                    "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
                }
            ]
        )
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("feature_face_unknown", result["reasons"])

    def test_through_feature_ok_without_open_surface(self):
        meta = _ready_metadata(
            features=[
                {
                    "featureId": "F1",
                    "kind": "pocket",
                    "cutType": "FULL",
                    "through": True,
                    "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
                }
            ]
        )
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertTrue(result["ready"])

    def test_groove_ok_with_quad_and_width(self):
        meta = _ready_metadata(
            features=[
                {
                    "featureId": "G1",
                    "kind": "groove",
                    "cutType": "HALF",
                    "openSurfaceIs": "A",
                    "depthMm": 8.0,
                    "widthMm": 8.0,
                    "points": [[0, 0], [100, 0], [100, 8], [0, 8]],
                }
            ]
        )
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertTrue(result["ready"], result["reasons"])

    def test_groove_rejects_bad_geometry(self):
        meta = _ready_metadata(
            features=[
                {
                    "featureId": "G1",
                    "kind": "groove",
                    "cutType": "HALF",
                    "openSurfaceIs": "A",
                    "depthMm": 8.0,
                    "points": [[0, 0], [10, 0]],
                }
            ]
        )
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("groove_geometry", result["reasons"])

    def test_tessellated_rectangular_groove_is_ready(self):
        meta = _ready_metadata(
            features=[
                {
                    "featureId": "G1",
                    "kind": "groove",
                    "cutType": "HALF",
                    "openSurfaceIs": "A",
                    "depthMm": 8.0,
                    "points": [
                        [0, 0],
                        [50, 0],
                        [100, 0],
                        [100, 4],
                        [100, 8],
                        [50, 8],
                        [0, 8],
                        [0, 4],
                    ],
                }
            ]
        )
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertTrue(result["ready"], result["reasons"])

    def test_blind_b_face_is_not_production_ready(self):
        meta = _ready_metadata(
            features=[
                {
                    "featureId": "P1",
                    "kind": "pocket",
                    "cutType": "HALF",
                    "openSurfaceIs": "B",
                    # Deep B open is a true underside feature — keep blocked.
                    "depthMm": 12.0,
                    "points": [[0, 0], [10, 0], [10, 10]],
                }
            ]
        )
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("feature_face_not_machining", result["reasons"])

    def test_shallow_b_face_is_still_blocked(self):
        meta = _ready_metadata(
            features=[
                {
                    "featureId": "P1",
                    "kind": "pocket",
                    "cutType": "HALF",
                    "openSurfaceIs": "B",
                    "depthMm": 2.0,
                    "points": [[0, 0], [10, 0], [10, 10], [0, 10]],
                }
            ]
        )
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("feature_face_not_machining", result["reasons"])

    def test_noisy_tessellated_groove_is_ready(self):
        meta = _ready_metadata(
            features=[
                {
                    "featureId": "G1",
                    "kind": "groove",
                    "cutType": "HALF",
                    "openSurfaceIs": "A",
                    "depthMm": 8.0,
                    "points": [
                        [0, 0],
                        [50, 0.05],
                        [100, 0],
                        [100.04, 4],
                        [100, 8],
                        [50, 7.96],
                        [0, 8],
                        [-0.03, 4],
                    ],
                }
            ]
        )
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertTrue(result["ready"], result["reasons"])

    def test_blind_depth_required_and_cannot_exceed_thickness(self):
        missing = _ready_metadata(
            features=[
                {
                    "featureId": "P1",
                    "kind": "pocket",
                    "cutType": "HALF",
                    "openSurfaceIs": "A",
                    "points": [[0, 0], [10, 0], [10, 10]],
                }
            ]
        )
        result = evaluate_metadata(missing, geometry_signature="sig-1")
        self.assertIn("feature_depth", result["reasons"])

        missing["features"][0]["depthMm"] = 20.0
        result = evaluate_metadata(missing, geometry_signature="sig-1")
        self.assertIn("feature_depth_over_thickness", result["reasons"])

    def test_duplicate_feature_ids_rejected(self):
        feature = {
            "featureId": "P1",
            "kind": "pocket",
            "cutType": "HALF",
            "openSurfaceIs": "A",
            "depthMm": 5.0,
            "points": [[0, 0], [10, 0], [10, 10]],
        }
        meta = _ready_metadata(features=[feature, dict(feature)])
        result = evaluate_metadata(meta, geometry_signature="sig-1")
        self.assertFalse(result["ready"])
        self.assertIn("feature_id_duplicate", result["reasons"])


if __name__ == "__main__":
    unittest.main()
