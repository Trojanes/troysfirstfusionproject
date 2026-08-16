import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from lay_flat_analyze import (  # noqa: E402
    ANALYZED_STATE,
    _translate_points,
    analyze_lay_flat_body,
    cache_is_fresh,
    feature_evidence_complete,
    milling_side_faces,
    tint_milling_face,
    tint_milling_side,
)
import lay_flat_analyze as analyze_mod  # noqa: E402
from outline_cache import CACHE_SCHEMA, body_geometry_signature  # noqa: E402


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
                "halfOpeningStatus": "none",
                "bottomHalfCount": 0,
                "outline": {
                    "source": "flatBody",
                    "points": [[0, 0], [1, 0], [1, 1]],
                },
            },
            "features": [],
        }
        self.assertTrue(cache_is_fresh(meta, "sig-1"))
        self.assertFalse(cache_is_fresh(meta, "sig-other"))
        meta["features"] = [
            {
                "featureId": "P1",
                "kind": "pocket",
                "cutType": "HALF",
                "openSurfaceIs": "B",
            }
        ]
        self.assertFalse(cache_is_fresh(meta, "sig-1"))
        meta["features"][0]["openSurfaceIs"] = "A"
        self.assertTrue(cache_is_fresh(meta, "sig-1"))
        meta["lifecycle"]["state"] = "lay_flat"
        self.assertFalse(cache_is_fresh(meta, "sig-1"))

    def test_analyze_has_no_geometry_flip_dependency(self):
        self.assertFalse(hasattr(analyze_mod, "flip_lay_flat_body_thickness"))
        self.assertFalse(hasattr(analyze_mod, "orient_outline_face_down"))

    def test_analyze_blocks_bottom_half_without_writing_or_flipping(self):
        body = mock.MagicMock()
        body.name = "P1"
        with mock.patch.object(
            analyze_mod, "_read_metadata", return_value={}
        ), mock.patch.object(
            analyze_mod, "body_geometry_signature", return_value="sig"
        ), mock.patch.object(
            analyze_mod,
            "evaluate_body_faces_up",
            return_value={
                "ok": False,
                "reasons": ["feature_face_not_machining"],
                "halfStatus": "bottomHalf",
                "topHalfCount": 0,
                "bottomHalfCount": 1,
            },
        ), mock.patch.object(analyze_mod, "_write_metadata") as write:
            result = analyze_lay_flat_body(body)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "feature_face_not_machining")
        write.assert_not_called()

    def test_analyze_blocks_double_side_without_writing(self):
        body = mock.MagicMock()
        body.name = "P2"
        with mock.patch.object(
            analyze_mod, "_read_metadata", return_value={}
        ), mock.patch.object(
            analyze_mod, "body_geometry_signature", return_value="sig"
        ), mock.patch.object(
            analyze_mod,
            "evaluate_body_faces_up",
            return_value={
                "ok": False,
                "reasons": ["double_side_unsupported"],
                "halfStatus": "doubleSide",
                "topHalfCount": 1,
                "bottomHalfCount": 1,
            },
        ), mock.patch.object(analyze_mod, "_write_metadata") as write:
            result = analyze_lay_flat_body(body)
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "double_side_unsupported")
        write.assert_not_called()

    def test_tint_milling_face_reuses_cached_appearance(self):
        class Face:
            appearance = None

        face_a = Face()
        face_b = Face()
        shared = object()
        tint_ctx = {"appearance": shared, "applied": 0, "failed": 0}
        self.assertTrue(tint_milling_face(face_a, tint_ctx=tint_ctx))
        self.assertTrue(tint_milling_face(face_b, tint_ctx=tint_ctx))
        self.assertIs(face_a.appearance, shared)
        self.assertIs(face_b.appearance, shared)
        self.assertEqual(tint_ctx["applied"], 2)
        self.assertEqual(tint_ctx["failed"], 0)

    def test_milling_side_faces_includes_coplanar_siblings(self):
        class Face:
            def __init__(self, name):
                self.name = name
                self.appearance = None

        milling = Face("milling")
        sibling = Face("sibling")
        side = Face("side")
        colour = Face("colour")
        body = object()

        def fake_plane(face):
            if face is milling or face is sibling:
                return (0.0, 0.0, 1.0), None
            if face is colour:
                return (0.0, 0.0, -1.0), None
            return (1.0, 0.0, 0.0), None

        with mock.patch.object(analyze_mod, "face_world_plane", side_effect=fake_plane), mock.patch.object(
            analyze_mod, "_iter_body_faces", return_value=[milling, sibling, side, colour]
        ):
            faces = milling_side_faces(body, milling)
        self.assertEqual(faces, [milling, sibling])

        tint_ctx = {"appearance": object(), "applied": 0, "failed": 0, "bodies": 0}
        with mock.patch.object(analyze_mod, "face_world_plane", side_effect=fake_plane), mock.patch.object(
            analyze_mod, "_iter_body_faces", return_value=[milling, sibling, side, colour]
        ):
            self.assertTrue(tint_milling_side(body, milling, tint_ctx))
        self.assertEqual(tint_ctx["applied"], 2)
        self.assertEqual(tint_ctx["bodies"], 1)

if __name__ == "__main__":
    unittest.main()
