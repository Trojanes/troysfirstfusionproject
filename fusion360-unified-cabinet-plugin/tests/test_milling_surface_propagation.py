import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL_ATTR_DIR = ROOT / "panel_attributes"
if str(PANEL_ATTR_DIR) not in sys.path:
    sys.path.insert(0, str(PANEL_ATTR_DIR))

import milling_surface_propagation as prop  # noqa: E402


class MillingSurfacePropagationPureTests(unittest.TestCase):
    def test_is_hinge_cup_feature(self):
        self.assertTrue(prop.is_hinge_cup_feature({
            "cutType": "HALF",
            "isCircle": True,
            "kind": "hole",
        }))
        self.assertTrue(prop.is_hinge_cup_feature({
            "cutType": "HALF",
            "isCircle": True,
            "kind": "",
        }))
        self.assertFalse(prop.is_hinge_cup_feature({
            "cutType": "FULL",
            "isCircle": True,
            "kind": "hole",
        }))
        self.assertFalse(prop.is_hinge_cup_feature({
            "cutType": "HALF",
            "isCircle": False,
            "kind": "groove",
        }))
        self.assertFalse(prop.is_hinge_cup_feature(None))

    def test_planes_coplanar_same_orientation(self):
        n = [0.0, 0.0, 1.0]
        c1 = [0.0, 0.0, 10.0]
        c2 = [100.0, 50.0, 10.2]  # within 0.5 mm plane offset after projection
        self.assertTrue(prop.planes_coplanar_same_orientation(n, c1, n, c2, tol_mm=0.5))

        # Opposite normals on same plane → reject
        self.assertFalse(prop.planes_coplanar_same_orientation(n, c1, [0.0, 0.0, -1.0], c2, tol_mm=0.5))

        # Parallel but offset too far
        c3 = [0.0, 0.0, 12.0]
        self.assertFalse(prop.planes_coplanar_same_orientation(n, c1, n, c3, tol_mm=0.5))

        # Slightly tilted but still same-ish
        n_tilt = prop.normalize_vector([0.01, 0.0, 1.0])
        self.assertTrue(prop.planes_coplanar_same_orientation(n, c1, n_tilt, c1, tol_mm=0.5))

    def test_normalize_and_dot(self):
        unit = prop.normalize_vector([0.0, 0.0, 5.0])
        self.assertEqual(unit, [0.0, 0.0, 1.0])
        self.assertAlmostEqual(prop.dot3([1, 0, 0], [0, 1, 0]), 0.0)

    def test_swap_decision(self):
        self.assertEqual(prop.swap_decision("MILLING", "NON_MILLING"), "B")
        self.assertEqual(prop.swap_decision("NON_MILLING", "MILLING"), "A")
        self.assertEqual(prop.swap_decision("MILLING", ""), "B")
        self.assertEqual(prop.swap_decision("", "MILLING"), "A")
        self.assertIsNone(prop.swap_decision("EITHER", "EITHER"))
        self.assertIsNone(prop.swap_decision("", ""))
        self.assertIsNone(prop.swap_decision("MILLING", "MILLING"))
        self.assertIsNone(prop.swap_decision("NON_MILLING", "NON_MILLING"))


class SwapSurfaceRolesTests(unittest.TestCase):
    def setUp(self):
        class FakeBody:
            def __init__(self, name):
                self.name = name

        self.door = FakeBody("door_1")
        self.carcass = FakeBody("side_panel")
        self.face_a = object()
        self.face_b = object()

        self._orig_classify = prop.classify_body_surfaces
        self._orig_role = prop._current_milling_role
        prop.classify_body_surfaces = lambda body: (self.face_a, self.face_b, [])
        self.roles = {id(self.face_a): "MILLING", id(self.face_b): "NON_MILLING"}
        prop._current_milling_role = lambda face: self.roles.get(id(face), "")

    def tearDown(self):
        prop.classify_body_surfaces = self._orig_classify
        prop._current_milling_role = self._orig_role

    def test_swaps_door_and_ignores_non_door(self):
        writes = []

        def write_roles(body, milling, non_milling):
            writes.append((body, milling, non_milling))

        result = prop.swap_surface_roles(
            [self.door, self.carcass],
            write_roles=write_roles,
            is_door_body=lambda body: body is self.door,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["updatedCount"], 1)
        # A was MILLING -> new milling must be B, non-milling A.
        self.assertEqual(writes, [(self.door, self.face_b, self.face_a)])
        reasons = [item["reason"] for item in result["skipped"]]
        self.assertIn("not_door", reasons)

    def test_skips_when_no_clear_milling(self):
        self.roles = {}
        writes = []
        # Stub geometry helpers so EITHER/empty commits A=milling, B=colour.
        orig_hinge = prop.detect_hinge_back_face
        orig_slot = prop._half_slot_surface_roles
        prop.detect_hinge_back_face = lambda body: None
        prop._half_slot_surface_roles = lambda body, a, b: None
        try:
            result = prop.swap_surface_roles(
                [self.door],
                write_roles=lambda body, milling, non_milling: writes.append(
                    (body, milling, non_milling)
                ),
                is_door_body=lambda body: True,
            )
        finally:
            prop.detect_hinge_back_face = orig_hinge
            prop._half_slot_surface_roles = orig_slot
        self.assertTrue(result["ok"])
        self.assertEqual(result["updatedCount"], 1)
        self.assertEqual(writes, [(self.door, self.face_a, self.face_b)])

    def test_either_with_preferred_face_sets_colour(self):
        self.roles = {id(self.face_a): "EITHER", id(self.face_b): "EITHER"}
        writes = []
        orig_hinge = prop.detect_hinge_back_face
        orig_slot = prop._half_slot_surface_roles
        prop.detect_hinge_back_face = lambda body: None
        prop._half_slot_surface_roles = lambda body, a, b: None
        # Fake face keys so preferred_face matching works without entityToken.
        orig_key = prop._safe_face_key
        prop._safe_face_key = lambda face: "A" if face is self.face_a else ("B" if face is self.face_b else "")
        try:
            result = prop.swap_surface_roles(
                [self.door],
                write_roles=lambda body, milling, non_milling: writes.append(
                    (milling, non_milling)
                ),
                is_door_body=lambda body: True,
                preferred_faces={id(self.door): self.face_a},
            )
        finally:
            prop.detect_hinge_back_face = orig_hinge
            prop._half_slot_surface_roles = orig_slot
            prop._safe_face_key = orig_key
        self.assertTrue(result["ok"])
        # Selected face_a becomes colour (NON_MILLING); milling is face_b.
        self.assertEqual(writes, [(self.face_b, self.face_a)])


class AnalyzeMillingSurfacesTests(unittest.TestCase):
    def setUp(self):
        class FakeBody:
            def __init__(self, name):
                self.name = name

        self.body = FakeBody("panel_1")
        self.face_a = object()
        self.face_b = object()

        self._orig_classify = prop.classify_body_surfaces
        self._orig_detect = prop.detect_hinge_back_face
        self._orig_slot = prop._half_slot_surface_roles
        self._orig_role = prop._current_milling_role
        prop.classify_body_surfaces = lambda body: (self.face_a, self.face_b, [])
        prop.detect_hinge_back_face = lambda body: None
        prop._half_slot_surface_roles = lambda body, a, b: None
        self.roles = {}
        prop._current_milling_role = lambda face: self.roles.get(id(face), "")

    def tearDown(self):
        prop.classify_body_surfaces = self._orig_classify
        prop.detect_hinge_back_face = self._orig_detect
        prop._half_slot_surface_roles = self._orig_slot
        prop._current_milling_role = self._orig_role

    def test_hinge_cups_win(self):
        prop.detect_hinge_back_face = lambda body: {
            "millingFace": self.face_b,
            "nonMillingFace": self.face_a,
        }
        writes = []
        result = prop.analyze_milling_surfaces(
            [self.body],
            write_pair=lambda body, fa, ra, fb, rb: writes.append((fa, ra, fb, rb)),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["updated"][0]["source"], "hinge_cups")
        self.assertEqual(writes, [(self.face_a, "NON_MILLING", self.face_b, "MILLING")])

    def test_half_slot_roles_prefer_feature_open_surface(self):
        """Groove-floor openSurfaceIs must beat naive wall adjacency."""
        import milling_surface_propagation as prop

        body = object()
        surface_a = object()
        surface_b = object()
        orig_extract = prop._extract_half_features
        orig_classify = prop.classify_box_faces
        prop._extract_half_features = lambda _body, _a, _b: [
            {"cutType": "HALF", "openSurfaceIs": "B", "kind": "groove"},
            {"cutType": "HALF", "openSurfaceIs": "B", "kind": "groove"},
        ]
        # If floor votes are ignored, wall fallback could mark A — ensure B wins.
        prop.classify_box_faces = lambda *_args, **_kwargs: {
            "edgeFaces": [],
            "warnings": [],
        }
        try:
            roles = self._orig_slot(body, surface_a, surface_b)
            self.assertEqual(roles, ["NON_MILLING", "MILLING"])
        finally:
            prop._extract_half_features = orig_extract
            prop.classify_box_faces = orig_classify

    def test_half_slot_when_no_hinge(self):
        prop._half_slot_surface_roles = lambda body, a, b: ["MILLING", "NON_MILLING"]
        writes = []
        result = prop.analyze_milling_surfaces(
            [self.body],
            write_pair=lambda body, fa, ra, fb, rb: writes.append((ra, rb)),
        )
        self.assertEqual(result["updated"][0]["source"], "half_slot")
        self.assertEqual(writes, [("MILLING", "NON_MILLING")])

    def test_no_evidence_unassigned_becomes_either(self):
        writes = []
        result = prop.analyze_milling_surfaces(
            [self.body],
            write_pair=lambda body, fa, ra, fb, rb: writes.append((ra, rb)),
        )
        self.assertEqual(result["updated"][0]["source"], "either")
        self.assertEqual(writes, [("EITHER", "EITHER")])

    def test_no_evidence_keeps_existing_assignment(self):
        self.roles = {id(self.face_a): "MILLING", id(self.face_b): "NON_MILLING"}
        writes = []
        result = prop.analyze_milling_surfaces(
            [self.body],
            write_pair=lambda body, fa, ra, fb, rb: writes.append((ra, rb)),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(writes, [])
        self.assertEqual(result["skippedCount"], 1)

    def test_collect_milling_faces(self):
        self.roles = {id(self.face_b): "MILLING"}
        collected = prop.collect_milling_faces([self.body])
        self.assertEqual(collected["faces"], [self.face_b])
        self.assertEqual(collected["eitherPicked"], [])

        self.roles = {}
        collected = prop.collect_milling_faces([self.body])
        self.assertEqual(collected["faces"], [])
        self.assertTrue(collected["skipped"])

    def test_collect_milling_faces_picks_either(self):
        self.roles = {
            id(self.face_a): "EITHER",
            id(self.face_b): "EITHER",
        }
        collected = prop.collect_milling_faces([self.body])
        self.assertEqual(len(collected["faces"]), 1)
        self.assertIn(collected["faces"][0], (self.face_a, self.face_b))
        self.assertEqual(len(collected["eitherPicked"]), 1)
        self.assertEqual(collected["skipped"], [])

    def test_collect_colour_faces(self):
        self.roles = {id(self.face_a): "NON_MILLING", id(self.face_b): "MILLING"}
        collected = prop.collect_colour_faces([self.body])
        self.assertEqual(collected["faces"], [self.face_a])
        self.assertEqual(collected["eitherPicked"], [])

        # Colour never returns the MILLING face.
        self.roles = {id(self.face_a): "MILLING", id(self.face_b): "MILLING"}
        collected = prop.collect_colour_faces([self.body])
        self.assertEqual(collected["faces"], [])
        self.assertTrue(collected["skipped"])

    def test_collect_colour_faces_doors_only(self):
        self.roles = {id(self.face_a): "NON_MILLING", id(self.face_b): "MILLING"}

        class FakeBody:
            def __init__(self, name):
                self.name = name

        door = self.body
        carcass = FakeBody("carcass_1")
        collected = prop.collect_colour_faces(
            [door, carcass],
            is_door_body=lambda body: body is door,
        )
        self.assertEqual(collected["faces"], [self.face_a])
        self.assertEqual(collected["skipped"][0]["reason"], "not_door")

    def test_collect_colour_faces_picks_either(self):
        self.roles = {
            id(self.face_a): "EITHER",
            id(self.face_b): "EITHER",
        }
        collected = prop.collect_colour_faces([self.body])
        self.assertEqual(len(collected["faces"]), 1)
        self.assertIn(collected["faces"][0], (self.face_a, self.face_b))
        self.assertEqual(len(collected["eitherPicked"]), 1)


if __name__ == "__main__":
    unittest.main()
