import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from lay_flat_analyze import (  # noqa: E402
    ANALYZED_STATE,
    _translate_points,
    cache_is_fresh,
    feature_evidence_complete,
    orient_outline_face_down,
    outline_extraction_face_is_down,
)
import lay_flat_analyze as analyze_mod  # noqa: E402
from outline_cache import CACHE_SCHEMA, body_geometry_signature  # noqa: E402
from unittest import mock


class LayFlatAnalyzeTests(unittest.TestCase):
    def test_feature_evidence_allows_over_extract_rejects_under_extract(self):
        self.assertTrue(feature_evidence_complete([{"id": 1}, {"id": 2}], 2))
        self.assertTrue(feature_evidence_complete([{"id": 1}, {"id": 2}, {"id": 3}], 2))
        self.assertFalse(feature_evidence_complete([{"id": 1}], 2))
        self.assertFalse(feature_evidence_complete([], -1))
        self.assertTrue(feature_evidence_complete([], 0))

    def test_detailed_signature_detects_internal_face_move(self):
        class Point:
            def __init__(self, x, y, z):
                self.x, self.y, self.z = x, y, z

        class Box:
            def __init__(self, x):
                self.minPoint = Point(x, 1, 0)
                self.maxPoint = Point(x + 0.5, 1.5, 1.8)

        class Geometry:
            objectType = "Cylinder"

        class Edges:
            count = 2

        class Face:
            area = 1.0
            geometry = Geometry()
            edges = Edges()

            def __init__(self, x):
                self.boundingBox = Box(x)

        class Faces:
            def __init__(self, x):
                self._face = Face(x)
                self.count = 1

            def item(self, _index):
                return self._face

        class BodyEdges:
            count = 2

        class Body:
            volume = 100.0
            edges = BodyEdges()

            def __init__(self, face_x):
                self.faces = Faces(face_x)
                self.boundingBox = Box(0)

        left = Body(2.0)
        right = Body(3.0)
        self.assertEqual(body_geometry_signature(left), body_geometry_signature(right))
        self.assertNotEqual(
            body_geometry_signature(left, detail=True),
            body_geometry_signature(right, detail=True),
        )

    def test_translate_points_lists_and_dicts(self):
        pts = _translate_points(
            [[10.0, 20.0], {"x": 1.5, "y": 2.5}],
            dx=-10.0,
            dy=-20.0,
        )
        self.assertEqual(pts, [[0.0, 0.0], [-8.5, -17.5]])

    def test_cache_fresh_requires_state_signature_outline_features(self):
        meta = {
            "lifecycle": {"state": ANALYZED_STATE},
            "nestingFlatOutline": {
                "schemaVersion": CACHE_SCHEMA,
                "geometrySignature": "sig-1",
                "widthMm": 1,
                "depthMm": 1,
                "outline": {
                    "source": "flatBody",
                    "points": [[0, 0], [1, 0], [1, 1]],
                },
            },
            "features": [],
        }
        self.assertTrue(cache_is_fresh(meta, "sig-1"))
        self.assertFalse(cache_is_fresh(meta, "sig-other"))
        meta["lifecycle"]["state"] = "lay_flat"
        self.assertFalse(cache_is_fresh(meta, "sig-1"))

    def test_outline_extraction_face_is_down_uses_normal(self):
        class Face:
            pass

        up = Face()
        down = Face()
        with mock.patch.object(analyze_mod, "select_true_outer_face", return_value=up), \
             mock.patch.object(analyze_mod, "_face_normal_z", return_value=1.0):
            self.assertFalse(outline_extraction_face_is_down(object()))
        with mock.patch.object(analyze_mod, "select_true_outer_face", return_value=down), \
             mock.patch.object(analyze_mod, "_face_normal_z", return_value=-1.0):
            self.assertTrue(outline_extraction_face_is_down(object()))

    def test_orient_outline_face_down_flips_only_when_needed(self):
        body = object()
        with mock.patch.object(
            analyze_mod, "outline_extraction_face_is_down", return_value=True
        ):
            result = orient_outline_face_down(body)
        self.assertTrue(result["ok"])
        self.assertFalse(result["flipped"])

        with mock.patch.object(
            analyze_mod, "outline_extraction_face_is_down", return_value=False
        ), mock.patch.object(
            analyze_mod,
            "flip_lay_flat_body_thickness",
            return_value={"ok": True, "bodyName": "P", "attributesRestored": 3},
        ) as flip:
            result = orient_outline_face_down(body)
        self.assertTrue(result["ok"])
        self.assertTrue(result["flipped"])
        flip.assert_called_once_with(body)


if __name__ == "__main__":
    unittest.main()
