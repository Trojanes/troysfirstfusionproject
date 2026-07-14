import os
import sys
import unittest
from unittest.mock import MagicMock


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
METADATA_DIR = os.path.join(PLUGIN_DIR, "metadata")
if METADATA_DIR not in sys.path:
    sys.path.insert(0, METADATA_DIR)

from face_models import (  # noqa: E402
    FACE_CLASS_EDGE,
    FACE_CLASS_SURFACE,
    MILLING_SURFACE,
    MILLING_SURFACE_EITHER,
    NON_MILLING_SURFACE,
    build_face_registry,
)
from panel_face_initializer import (  # noqa: E402
    classify_box_faces,
    EDGE_ROLE_BANDABLE,
    EDGE_ROLE_NON_BANDABLE,
    build_edge_groups,
    classify_edge_bandability,
    detect_surface_milling_roles,
    edge_role_from_geometry,
    is_oh_skeleton_board,
    list_all_edge_faces,
    split_true_edges_and_feature_faces,
    surface_roles_for_board,
    validate_edge_group_banding,
)


class MockFace:
    def __init__(self, area, normal, centroid, token=""):
        self.area = area
        self._normal = normal
        self._centroid = centroid
        self.entityToken = token
        self.evaluator = self
        self.attributes = MagicMock()
        self.attributes.itemByName.return_value = None

    def getArea(self):
        return self.area / 100.0, True, None

    @property
    def pointOnFace(self):
        point = MagicMock()
        point.x = self._centroid[0] / 10.0
        point.y = self._centroid[1] / 10.0
        point.z = self._centroid[2] / 10.0
        return point

    def getNormalAtPoint(self, _point):
        normal = MagicMock()
        normal.x = self._normal[0]
        normal.y = self._normal[1]
        normal.z = self._normal[2]
        return True, normal


class MockBody:
    def __init__(self, faces):
        self._faces = list(faces)
        self.boundingBox = MagicMock()
        self.boundingBox.minPoint = MagicMock(x=0.0, y=0.0, z=0.0)
        self.boundingBox.maxPoint = MagicMock(x=100.0, y=40.0, z=1.5)

    @property
    def faces(self):
        return self

    @property
    def count(self):
        return len(self._faces)

    def item(self, index):
        return self._faces[index]


class MockCollection:
    def __init__(self, items):
        self._items = list(items)

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]


class MockEdge:
    def __init__(self, faces):
        self._faces = faces

    @property
    def faces(self):
        return MockCollection(self._faces)


class AdjFace:
    def __init__(self, token, normal):
        self.entityToken = token
        self.tempId = token
        self._normal = normal
        self.evaluator = self
        self._edges = []
        self.attributes = MagicMock()
        self.attributes.itemByName.return_value = None

    @property
    def pointOnFace(self):
        point = MagicMock()
        point.x = point.y = point.z = 0.0
        return point

    def getNormalAtPoint(self, _point):
        normal = MagicMock()
        normal.x, normal.y, normal.z = self._normal
        return True, normal

    @property
    def edges(self):
        return MockCollection(self._edges)


def _connect(face_a, face_b):
    edge = MockEdge([face_a, face_b])
    face_a._edges.append(edge)
    face_b._edges.append(edge)


class KeyEdge:
    def __init__(self, token):
        self.entityToken = token


class CoEdge:
    def __init__(self, edge):
        self.edge = edge


class Loop:
    def __init__(self, edges, is_outer=True):
        self.isOuter = is_outer
        self.coEdges = MockCollection([CoEdge(edge) for edge in edges])


class LoopFace:
    def __init__(self, token, loops, edges):
        self.entityToken = token
        self.loops = MockCollection(loops)
        self.edges = MockCollection(edges)


class PanelFaceInitializerTests(unittest.TestCase):
    def test_build_face_registry_contains_roles(self):
        registry = build_face_registry(
            "DOUBLE_SIDED",
            [
                {"faceId": "FACE-1", "faceRole": "carcass_bottom_outer", "faceClass": FACE_CLASS_SURFACE},
                {"faceId": "FACE-2", "faceRole": "edge_top", "faceClass": FACE_CLASS_EDGE},
            ],
            reference_front_face_id="FACE-1",
        )
        payload = registry["faceRegistry"]
        self.assertEqual(payload["surfaceMode"], "DOUBLE_SIDED")
        self.assertEqual(payload["referenceFrontFaceId"], "FACE-1")
        self.assertEqual(len(payload["faces"]), 2)
        self.assertEqual(payload["faceIds"], ["FACE-1", "FACE-2"])

    def test_classify_box_faces_splits_two_surfaces_and_edges(self):
        surfaces = [
            MockFace(800000, [0, 0, 1], [50, 20, 0.75], "s1"),
            MockFace(790000, [0, 0, -1], [50, 20, 0.75], "s2"),
        ]
        edges = [
            MockFace(30000, [0, 1, 0], [50, 40, 0.75], "e1"),
            MockFace(29000, [0, -1, 0], [50, 0, 0.75], "e2"),
            MockFace(12000, [1, 0, 0], [100, 20, 0.75], "e3"),
            MockFace(11000, [-1, 0, 0], [0, 20, 0.75], "e4"),
        ]
        body = MockBody(surfaces + edges)
        classified = classify_box_faces(body)
        self.assertEqual(len(classified["surfaceFaces"]), 2)
        self.assertEqual(len(classified["edgeFaces"]), 4)

    def test_classify_always_returns_exactly_two_surfaces(self):
        front = MockFace(900000, [0, 1, 0], [50, 40, 0.75], "front")
        back = MockFace(880000, [0, -1, 0], [50, 0, 0.75], "back")
        groove_bottom = MockFace(50000, [0, 1, 0], [50, 30, 0.75], "groove")
        edges = [
            MockFace(30000, [0, 0, 1], [50, 20, 0.75], "e1"),
            MockFace(29000, [0, 0, -1], [50, 20, 0.75], "e2"),
            MockFace(12000, [1, 0, 0], [100, 20, 0.75], "e3"),
        ]
        body = MockBody([front, back, groove_bottom] + edges)
        classified = classify_box_faces(body)
        self.assertEqual(len(classified["surfaceFaces"]), 2)
        surface_tokens = {face.entityToken for face in classified["surfaceFaces"]}
        self.assertEqual(surface_tokens, {"front", "back"})
        self.assertEqual(len(classified["edgeFaces"]), 4)

    def test_classify_falls_back_to_two_largest_without_opposing_normal(self):
        faces = [
            MockFace(900000, [0, 1, 0], [50, 40, 0.75], "a"),
            MockFace(880000, [0, 1, 0], [50, 30, 0.75], "b"),
            MockFace(30000, [0, 0, 1], [50, 20, 0.75], "e1"),
        ]
        body = MockBody(faces)
        classified = classify_box_faces(body)
        self.assertEqual(len(classified["surfaceFaces"]), 2)
        surface_tokens = {face.entityToken for face in classified["surfaceFaces"]}
        self.assertEqual(surface_tokens, {"a", "b"})

    def test_milling_roles_both_either_without_half_slot(self):
        surface_a = AdjFace("A", [0, 0, 1])
        surface_b = AdjFace("B", [0, 0, -1])
        edge_one = AdjFace("e1", [1, 0, 0])
        edge_two = AdjFace("e2", [-1, 0, 0])
        for band in (edge_one, edge_two):
            _connect(band, surface_a)
            _connect(band, surface_b)
        roles = detect_surface_milling_roles([surface_a, surface_b], [edge_one, edge_two])
        self.assertEqual(roles, [MILLING_SURFACE_EITHER, MILLING_SURFACE_EITHER])

    def test_milling_roles_half_slot_marks_open_side(self):
        surface_a = AdjFace("A", [0, 0, 1])
        surface_b = AdjFace("B", [0, 0, -1])
        edge_one = AdjFace("e1", [1, 0, 0])
        _connect(edge_one, surface_a)
        _connect(edge_one, surface_b)
        slot_wall = AdjFace("wall", [0, 1, 0])
        _connect(slot_wall, surface_a)
        roles = detect_surface_milling_roles([surface_a, surface_b], [edge_one, slot_wall])
        self.assertEqual(roles, [MILLING_SURFACE, NON_MILLING_SURFACE])

    def test_milling_roles_half_slot_on_second_surface(self):
        surface_a = AdjFace("A", [0, 0, 1])
        surface_b = AdjFace("B", [0, 0, -1])
        slot_wall = AdjFace("wall", [0, 1, 0])
        _connect(slot_wall, surface_b)
        roles = detect_surface_milling_roles([surface_a, surface_b], [slot_wall])
        self.assertEqual(roles, [NON_MILLING_SURFACE, MILLING_SURFACE])

    def test_milling_roles_both_sides_never_dual_milling(self):
        surface_a = AdjFace("A", [0, 0, 1])
        surface_b = AdjFace("B", [0, 0, -1])
        wall_a = AdjFace("wallA", [0, 1, 0])
        wall_b = AdjFace("wallB", [0, -1, 0])
        _connect(wall_a, surface_a)
        _connect(wall_b, surface_b)
        roles = detect_surface_milling_roles(
            [surface_a, surface_b], [wall_a, wall_b]
        )
        self.assertEqual(roles, [MILLING_SURFACE, NON_MILLING_SURFACE])
        self.assertNotEqual(roles[0], roles[1])

    def test_split_true_edges_from_feature_faces(self):
        e_top = KeyEdge("eTop")
        e_bot = KeyEdge("eBot")
        e_extra_a = KeyEdge("eExtraA")
        e_extra_b = KeyEdge("eExtraB")
        e_feature = KeyEdge("eFeature")
        surface_a = LoopFace("A", [Loop([e_top, e_extra_a])], [e_top, e_extra_a])
        surface_b = LoopFace("B", [Loop([e_bot, e_extra_b])], [e_bot, e_extra_b])
        band = LoopFace("band", [Loop([e_top, e_bot])], [e_top, e_bot])
        feature_wall = LoopFace("wall", [Loop([e_feature])], [e_feature])

        true_edges, feature_faces = split_true_edges_and_feature_faces(
            [surface_a, surface_b], [band, feature_wall]
        )
        self.assertEqual([f.entityToken for f in true_edges], ["band"])
        self.assertEqual([f.entityToken for f in feature_faces], ["wall"])

    def test_split_falls_back_when_no_loop_data(self):
        plain_a = AdjFace("A", [0, 0, 1])
        plain_b = AdjFace("B", [0, 0, -1])
        e1 = AdjFace("e1", [1, 0, 0])
        true_edges, feature_faces = split_true_edges_and_feature_faces([plain_a, plain_b], [e1])
        self.assertEqual(true_edges, [e1])
        self.assertEqual(feature_faces, [])

    def test_classify_edge_bandability_frame_vs_notch(self):
        # Panel in XY plane (thickness axis Z). Frame edges sit at x/y extremes;
        # a notch edge sits set back from the frame.
        entries = [
            {"normalLocal": [1, 0, 0], "centroidLocal": [100, 20, 0]},   # +X frame
            {"normalLocal": [-1, 0, 0], "centroidLocal": [0, 20, 0]},     # -X frame
            {"normalLocal": [0, 1, 0], "centroidLocal": [50, 40, 0]},     # +Y frame
            {"normalLocal": [0, -1, 0], "centroidLocal": [50, 0, 0]},     # -Y frame
            {"normalLocal": [-1, 0, 0], "centroidLocal": [70, 20, 0]},    # notch wall (interior x)
        ]
        classify_edge_bandability(entries, [0, 0, 1])
        roles = [e["faceRole"] for e in entries]
        self.assertEqual(roles[:4], [EDGE_ROLE_BANDABLE] * 4)
        self.assertEqual(roles[4], EDGE_ROLE_NON_BANDABLE)
        self.assertTrue(entries[0]["bandable"])
        self.assertFalse(entries[4]["bandable"])

    def test_build_edge_groups_merges_same_side(self):
        # Two faces on the +X side (e.g. split by a groove) must share one group;
        # the -X side is a different group; a non-bandable face is excluded.
        edge_registry = [
            {"edgeId": "EDGE-01", "faceId": "F1", "bandable": True, "directionHint": "+X", "areaMm2": 100.0, "entityToken": "t1"},
            {"edgeId": "EDGE-02", "faceId": "F2", "bandable": True, "directionHint": "+X", "areaMm2": 50.0, "entityToken": "t2"},
            {"edgeId": "EDGE-03", "faceId": "F3", "bandable": True, "directionHint": "-X", "areaMm2": 120.0, "entityToken": "t3"},
            {"edgeId": "EDGE-04", "faceId": "F4", "bandable": False, "directionHint": "+Y", "areaMm2": 30.0, "entityToken": "t4"},
        ]
        groups = build_edge_groups(edge_registry)
        self.assertEqual(len(groups), 2)
        plus_x = next(g for g in groups if g["side"] == "+X")
        self.assertEqual(sorted(plus_x["faceIds"]), ["F1", "F2"])
        self.assertEqual(plus_x["bandingColor"], "raw-core")
        # Members carry the shared group id; non-bandable face has none.
        self.assertEqual(edge_registry[0]["edgeGroupId"], plus_x["edgeGroupId"])
        self.assertEqual(edge_registry[1]["edgeGroupId"], plus_x["edgeGroupId"])
        self.assertIsNone(edge_registry[3]["edgeGroupId"])

    def test_validate_edge_group_banding_flags_mixed_colours(self):
        groups = [{"edgeGroupId": "EG-01", "side": "+X", "faceIds": ["F1", "F2"]}]
        ok = validate_edge_group_banding(groups, {"F1": "white", "F2": "white"})
        self.assertEqual(ok, [])
        bad = validate_edge_group_banding(groups, {"F1": "white", "F2": "black"})
        self.assertEqual(len(bad), 1)

    def test_surface_roles_for_bp(self):
        roles = surface_roles_for_board("BP", [1, 2])
        self.assertEqual(roles[0], "carcass_bottom_outer")
        self.assertEqual(roles[1], "carcass_bottom_inner")

    def test_surface_roles_for_fp_board(self):
        roles = surface_roles_for_board("FP1", [1, 2])
        self.assertEqual(roles, ["door_outer", "door_inner"])

    def test_surface_roles_for_extra_fragments(self):
        roles = surface_roles_for_board("FP2", [1, 2, 3])
        self.assertEqual(roles, ["door_outer", "door_inner", "door_inner_03"])

    def test_is_oh_skeleton_board_accepts_ohc_ids(self):
        self.assertTrue(is_oh_skeleton_board("BP"))
        self.assertTrue(is_oh_skeleton_board("T1"))
        self.assertTrue(is_oh_skeleton_board("D3"))
        self.assertTrue(is_oh_skeleton_board("FP2"))
        self.assertFalse(is_oh_skeleton_board("Zi1"))

    def test_edge_role_from_geometry(self):
        body = MockBody([])
        face = MockFace(1000, [1, 0, 0], [100, 20, 0.75])
        self.assertEqual(edge_role_from_geometry(face, body), "edge_right")

    def test_list_all_edge_faces_enumerates_every_candidate(self):
        body = MockBody([])
        face_a = MockFace(1000, [1, 0, 0], [100, 20, 10])
        face_b = MockFace(900, [1, 0, 0], [50, 20, 10])
        face_c = MockFace(800, [0, 1, 0], [50, 40, 10])
        entries = list_all_edge_faces([face_a, face_b, face_c], None)
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["edgeId"], "EDGE-01")
        self.assertEqual(entries[0]["classificationStatus"], "unclassified")
        self.assertEqual(entries[0]["faceRole"], "edge_unclassified")
        self.assertEqual(entries[1]["edgeId"], "EDGE-02")
        self.assertEqual(entries[2]["directionHint"], "+Y")


if __name__ == "__main__":
    unittest.main()
