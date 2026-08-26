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

    def test_roles_from_milling_direction_plus_y(self):
        # Stove / front door: milling +Y (into cabinet), colour −Y (outward).
        roles = prop.roles_from_milling_direction([0, 1, 0], [0, -1, 0], "+Y")
        self.assertEqual(roles, ("MILLING", "NON_MILLING"))
        roles = prop.roles_from_milling_direction([0, -1, 0], [0, 1, 0], "+Y")
        self.assertEqual(roles, ("NON_MILLING", "MILLING"))
        self.assertIsNone(prop.roles_from_milling_direction([1, 0, 0], [-1, 0, 0], "+Y"))

    def test_resolve_flip_faces_swaps_complementary(self):
        a, b = object(), object()
        milling, non = prop.resolve_flip_faces(a, b, "MILLING", "NON_MILLING")
        self.assertIs(milling, b)
        self.assertIs(non, a)
        milling, non = prop.resolve_flip_faces(a, b, "NON_MILLING", "MILLING")
        self.assertIs(milling, a)
        self.assertIs(non, b)

    def test_resolve_flip_faces_preferred_becomes_colour(self):
        a, b = object(), object()
        orig_key = prop._safe_face_key
        prop._safe_face_key = lambda face: "A" if face is a else ("B" if face is b else "")
        try:
            milling, non = prop.resolve_flip_faces(a, b, "EITHER", "EITHER", preferred_face=a)
            self.assertIs(milling, b)
            self.assertIs(non, a)
            milling, non = prop.resolve_flip_faces(a, b, "", "", preferred_face=b)
            self.assertIs(milling, a)
            self.assertIs(non, b)
        finally:
            prop._safe_face_key = orig_key

    def test_read_source_panel_id_from_attribute(self):
        body = type("Body", (), {})()
        body.attributes = type("Attrs", (), {})()

        class Attr:
            value = "SRC-42"

        body.attributes.itemByName = lambda group, name: (
            Attr() if group == "UnifiedCabinet" and name == "sourcePanelId" else None
        )
        self.assertEqual(prop.read_source_panel_id(body), "SRC-42")
        self.assertEqual(prop.read_source_panel_id(None), "")

    def test_read_source_panel_id_from_layflat_panel_id(self):
        body = type("Body", (), {})()
        body.attributes = type("Attrs", (), {})()

        class Attr:
            value = "overhead.D1@layflat-2-0"

        body.attributes.itemByName = lambda group, name: (
            Attr()
            if group == "UnifiedCabinet.Panel" and name == "panelId"
            else None
        )
        self.assertEqual(prop.read_source_panel_id(body), "overhead.D1")
        self.assertEqual(
            prop._source_panel_id_from_panel_id("overhead.D1@layflat-2-0"),
            "overhead.D1",
        )


class FlipSelectedBodyMillingTests(unittest.TestCase):
    def setUp(self):
        class FakeBody:
            def __init__(self, name):
                self.name = name

        self.body = FakeBody("panel_1")
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

    def test_flips_only_given_bodies(self):
        writes = []
        result = prop.flip_selected_body_milling(
            [self.body],
            write_roles=lambda body, milling, non: writes.append((body, milling, non)),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["updatedCount"], 1)
        self.assertTrue(result["updated"][0]["fastPath"])
        self.assertEqual(writes, [(self.body, self.face_b, self.face_a)])

    def test_does_not_call_hinge_or_slot_scan(self):
        hinge_calls = []
        slot_calls = []
        orig_hinge = prop.detect_hinge_back_face
        orig_slot = prop._half_slot_surface_roles
        prop.detect_hinge_back_face = lambda body: hinge_calls.append(body) or None
        prop._half_slot_surface_roles = lambda *a, **k: slot_calls.append(a) or None
        try:
            prop.flip_selected_body_milling(
                [self.body],
                write_roles=lambda *a, **k: None,
            )
        finally:
            prop.detect_hinge_back_face = orig_hinge
            prop._half_slot_surface_roles = orig_slot
        self.assertEqual(hinge_calls, [])
        self.assertEqual(slot_calls, [])


class MakeSelectedFacesColourTests(unittest.TestCase):
    def setUp(self):
        class FakeBody:
            def __init__(self, name):
                self.name = name

        self.body = FakeBody("panel_1")
        self.face_a = object()
        self.face_b = object()
        self._orig_classify = prop.classify_body_surfaces
        self._orig_key = prop._safe_face_key
        prop.classify_body_surfaces = lambda body: (
            self.face_a, self.face_b, []
        )
        prop._safe_face_key = lambda face: (
            "A" if face is self.face_a else ("B" if face is self.face_b else "")
        )

    def tearDown(self):
        prop.classify_body_surfaces = self._orig_classify
        prop._safe_face_key = self._orig_key

    def test_single_sided_selected_face_becomes_colour(self):
        writes = []
        result = prop.make_selected_faces_colour(
            [{
                "body": self.body,
                "faces": [self.face_a],
                "surfaceMode": "SINGLE_SIDED",
            }],
            write_roles=lambda body, milling, colour: writes.append(
                (body, milling, colour)
            ),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["updatedCount"], 1)
        self.assertEqual(writes, [(self.body, self.face_b, self.face_a)])

    def test_double_sided_needs_no_orientation_write(self):
        writes = []
        result = prop.make_selected_faces_colour(
            [{
                "body": self.body,
                "faces": [self.face_a],
                "surfaceMode": "DOUBLE_SIDED",
            }],
            write_roles=lambda *args: writes.append(args),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["doubleSidedCount"], 1)
        self.assertEqual(writes, [])

    def test_rejects_both_faces_on_single_sided_panel(self):
        result = prop.make_selected_faces_colour(
            [{
                "body": self.body,
                "faces": [self.face_a, self.face_b],
                "surfaceMode": "SINGLE_SIDED",
            }],
            write_roles=lambda *args: self.fail("must not write conflicting faces"),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["skippedCount"], 1)
        self.assertIn("both broad faces", result["skipped"][0]["reason"])

    def test_does_not_run_hinge_or_slot_analysis(self):
        hinge_calls = []
        slot_calls = []
        orig_hinge = prop.detect_hinge_back_face
        orig_slot = prop._half_slot_surface_roles
        prop.detect_hinge_back_face = lambda body: hinge_calls.append(body)
        prop._half_slot_surface_roles = lambda *args: slot_calls.append(args)
        try:
            prop.make_selected_faces_colour(
                [{
                    "body": self.body,
                    "faces": [self.face_b],
                    "surfaceMode": "SINGLE_SIDED",
                }],
                write_roles=lambda *args: None,
            )
        finally:
            prop.detect_hinge_back_face = orig_hinge
            prop._half_slot_surface_roles = orig_slot
        self.assertEqual(hinge_calls, [])
        self.assertEqual(slot_calls, [])


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

    def test_edge_open_u_overrides_wrong_floor_vote(self):
        """Bitten colour-style U is MILLING even if openSurfaceIs points at the intact face."""
        full = [(0.0, 0.0), (400.0, 0.0), (400.0, 400.0), (0.0, 400.0)]
        notched = [
            (0.0, 0.0), (400.0, 0.0), (400.0, 400.0),
            (210.0, 400.0), (210.0, 20.0), (190.0, 20.0), (190.0, 400.0),
            (0.0, 400.0),
        ]
        pocket = {
            "cutType": "HALF",
            "openSurfaceIs": "A",
            "kind": "groove",
            "points": [(192.0, 30.0), (208.0, 30.0), (208.0, 380.0), (192.0, 380.0)],
        }
        roles = prop.decide_half_slot_roles([pocket], outer_a=full, outer_b=notched)
        self.assertEqual(roles, ["NON_MILLING", "MILLING"])

    def test_closed_groove_keeps_floor_vote_when_outers_match(self):
        rect = [(0.0, 0.0), (400.0, 0.0), (400.0, 400.0), (0.0, 400.0)]
        pocket = {
            "cutType": "HALF",
            "openSurfaceIs": "B",
            "kind": "groove",
            "points": [(80.0, 80.0), (120.0, 80.0), (120.0, 320.0), (80.0, 320.0)],
        }
        roles = prop.decide_half_slot_roles([pocket], outer_a=rect, outer_b=rect)
        self.assertEqual(roles, ["NON_MILLING", "MILLING"])

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

    def test_generator_milling_direction_before_either(self):
        orig_directed = prop.roles_from_body_milling_direction
        prop.roles_from_body_milling_direction = lambda body, a, b: ("NON_MILLING", "MILLING")
        try:
            writes = []
            result = prop.analyze_milling_surfaces(
                [self.body],
                write_pair=lambda body, fa, ra, fb, rb: writes.append((ra, rb)),
            )
            self.assertEqual(result["updated"][0]["source"], "generator_direction")
            self.assertEqual(writes, [("NON_MILLING", "MILLING")])
        finally:
            prop.roles_from_body_milling_direction = orig_directed

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
