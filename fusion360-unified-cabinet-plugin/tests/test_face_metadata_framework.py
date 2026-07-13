import os
import sys
import unittest


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
METADATA_DIR = os.path.join(PLUGIN_DIR, "metadata")
if METADATA_DIR not in sys.path:
    sys.path.insert(0, METADATA_DIR)

from face_attribute_store import (  # noqa: E402
    has_face_metadata,
    read_face_metadata,
    remove_face_metadata,
    update_face_metadata,
    write_face_metadata,
)
from face_entity_resolver import (  # noqa: E402
    RESOLVE_AMBIGUOUS,
    RESOLVE_FOUND,
    RESOLVE_NOT_FOUND,
    resolve_face,
)
from face_geometry_signature import (  # noqa: E402
    build_geometry_signature_from_values,
    signature_match_score,
    signatures_match,
)
from face_metadata_service import FaceMetadataService  # noqa: E402
from face_models import (  # noqa: E402
    BANDING_CODE_DOOR_1,
    FACE_CLASS_EDGE,
    FACE_CLASS_SURFACE,
    MACHINING_PRIMARY,
    SURFACE_MODE_DOUBLE_SIDED,
    SURFACE_MODE_SINGLE_SIDED,
    create_edge_metadata,
    default_single_sided_door_door_colour_surface,
    default_single_sided_door_white_stipple_surface,
    generate_face_id,
)
from face_validation import (  # noqa: E402
    validate_double_sided_door_defaults,
    validate_face_metadata,
    validate_panel_surface_mode,
    validate_single_sided_door_defaults,
    validate_unique_face_ids,
)


class MockAttribute:
    def __init__(self, value):
        self.value = value

    def deleteMe(self):
        self.value = None


class MockAttributeCollection:
    def __init__(self):
        self._items = {}

    def itemByName(self, group, name):
        return self._items.get((group, name))

    def add(self, group, name, value):
        self._items[(group, name)] = MockAttribute(value)


class MockFace:
    def __init__(self, token="token-1"):
        self.attributes = MockAttributeCollection()
        self.entityToken = token


class MockBody:
    def __init__(self, faces):
        self._faces = list(faces)

    @property
    def faces(self):
        return self

    @property
    def count(self):
        return len(self._faces)

    def item(self, index):
        return self._faces[index]


class FaceMetadataFrameworkTests(unittest.TestCase):
    def setUp(self):
        self.service = FaceMetadataService()
        self.panel_id = "PANEL-TEST-001"
        self.door_finish = {"finishId": "door-colour-1", "finishName": "Alpine White"}

    def test_rectangular_panel_registers_two_surfaces_and_four_edges(self):
        surface_faces = [MockFace("surface-1"), MockFace("surface-2")]
        edge_faces = [MockFace("edge-{}".format(index)) for index in range(4)]
        created_surface_ids = []
        for face in surface_faces:
            metadata = self.service.initialize_face_metadata(
                face,
                self.panel_id,
                {
                    "faceClass": FACE_CLASS_SURFACE,
                    "finish": {"finishId": "finish-a", "finishName": "Finish A"},
                    "machiningPermission": "ALLOWED",
                    "geometrySignature": build_geometry_signature_from_values(area=500000.0),
                },
            )
            created_surface_ids.append(metadata["faceId"])

        created_edge_ids = []
        for face in edge_faces:
            metadata = self.service.initialize_edge_face(
                face,
                self.panel_id,
                {
                    "required": True,
                    "bandingCode": BANDING_CODE_DOOR_1,
                    "finishId": "door-colour-1",
                    "finishName": "Alpine White",
                },
            )
            created_edge_ids.append(metadata["faceId"])

        self.assertEqual(len(created_surface_ids), 2)
        self.assertEqual(len(created_edge_ids), 4)
        registry = self.service.build_panel_face_registry(SURFACE_MODE_DOUBLE_SIDED, created_surface_ids + created_edge_ids)
        self.assertEqual(len(registry["faceIds"]), 6)

    def test_irregular_panel_allows_more_than_six_faces(self):
        face_ids = []
        for index in range(8):
            face = MockFace("edge-extra-{}".format(index))
            metadata = self.service.initialize_edge_face(
                face,
                self.panel_id,
                {
                    "required": False,
                    "bandingCode": 0,
                    "finishId": "raw-core",
                    "finishName": "Raw Core",
                },
                face_id="FACE-EDGE-{}".format(index),
            )
            face_ids.append(metadata["faceId"])
        self.assertEqual(len(face_ids), 8)

    def test_single_sided_door_defaults(self):
        door_face = MockFace("door-surface")
        white_face = MockFace("white-surface")
        result = self.service.initialize_single_sided_door_surfaces(
            door_face,
            white_face,
            self.panel_id,
            self.door_finish,
        )
        door_metadata = result["doorFace"]
        white_metadata = result["whiteStippleFace"]
        self.assertEqual(result["panelRegistry"]["surfaceMode"], SURFACE_MODE_SINGLE_SIDED)
        self.assertEqual(door_metadata["machiningPermission"], "NOT_ALLOWED")
        self.assertEqual(white_metadata["machiningPermission"], MACHINING_PRIMARY)
        validation = validate_single_sided_door_defaults(
            [door_metadata, white_metadata],
            self.door_finish["finishId"],
        )
        self.assertTrue(validation["valid"])

    def test_double_sided_door_defaults(self):
        faces = [MockFace("ds-1"), MockFace("ds-2")]
        result = self.service.initialize_double_sided_door_surfaces(
            faces,
            self.panel_id,
            self.door_finish,
        )
        validation = validate_double_sided_door_defaults(
            result["surfaceFaces"],
            self.door_finish["finishId"],
        )
        self.assertTrue(validation["valid"])
        self.assertEqual(result["panelRegistry"]["surfaceMode"], SURFACE_MODE_DOUBLE_SIDED)

    def test_single_sided_door_colour_primary_fails_validation(self):
        metadata = default_single_sided_door_door_colour_surface(
            self.panel_id,
            generate_face_id(),
            self.door_finish,
        )
        metadata["machiningPermission"] = MACHINING_PRIMARY
        validation = validate_single_sided_door_defaults([metadata], self.door_finish["finishId"])
        self.assertFalse(validation["valid"])

    def test_surface_with_edge_banding_fails_validation(self):
        metadata = default_single_sided_door_white_stipple_surface(self.panel_id, generate_face_id())
        metadata["edgeBanding"] = {"required": True, "bandingCode": 1, "finishId": "x", "finishName": "X"}
        validation = validate_face_metadata(metadata, {"panelId": self.panel_id})
        self.assertFalse(validation["valid"])

    def test_edge_faces_can_store_different_banding(self):
        edge_a = create_edge_metadata(
            self.panel_id,
            generate_face_id(),
            {
                "required": True,
                "bandingCode": 1,
                "finishId": "carcass",
                "finishName": "Carcass",
            },
        )
        edge_b = create_edge_metadata(
            self.panel_id,
            generate_face_id(),
            {
                "required": True,
                "bandingCode": BANDING_CODE_DOOR_1,
                "finishId": "door-colour-1",
                "finishName": "Alpine White",
            },
        )
        self.assertNotEqual(edge_a["edgeBanding"]["bandingCode"], edge_b["edgeBanding"]["bandingCode"])

    def test_geometry_signature_match_uses_local_snapshot(self):
        stored = build_geometry_signature_from_values(
            area=1200000.0,
            perimeter=4600.0,
            centroid_local=[1000.0, 300.0, 8.0],
            normal_local=[0.0, 0.0, 1.0],
            edge_count=4,
        )
        candidate = build_geometry_signature_from_values(
            area=1200000.0,
            perimeter=4600.0,
            centroid_local=[1000.0, 300.0, 8.0],
            normal_local=[0.0, 0.0, 1.0],
            edge_count=4,
        )
        self.assertTrue(signatures_match(stored, candidate))

    def test_resolver_finds_face_by_signature_after_token_change(self):
        signature = build_geometry_signature_from_values(
            area=800000.0,
            perimeter=3600.0,
            centroid_local=[200.0, 100.0, 8.0],
            normal_local=[0.0, 0.0, 1.0],
            edge_count=4,
        )
        old_face = MockFace("old-token")
        metadata = self.service.initialize_face_metadata(
            old_face,
            self.panel_id,
            {
                "faceClass": FACE_CLASS_SURFACE,
                "finish": {"finishId": "finish-a", "finishName": "Finish A"},
                "machiningPermission": "ALLOWED",
                "geometrySignature": signature,
            },
        )
        class SignatureFace(MockFace):
            def __init__(self, token):
                super().__init__(token)

        new_face = MockFace("new-token")
        signature_face = SignatureFace("resolved-token")
        body = MockBody([new_face, signature_face])
        status, resolved_face, diagnostics = resolve_face(
            {"body": body, "panelId": self.panel_id},
            metadata["faceId"],
            [{"faceId": metadata["faceId"], "metadata": metadata}],
        )
        self.assertEqual(status, RESOLVE_NOT_FOUND)
        self.assertIsNone(resolved_face)

        def fake_build_geometry_signature(face, panel_context=None):
            if face is signature_face:
                return signature
            return build_geometry_signature_from_values(area=1.0)

        import face_entity_resolver as resolver_module

        original = resolver_module.build_geometry_signature
        resolver_module.build_geometry_signature = fake_build_geometry_signature
        try:
            status, resolved_face, diagnostics = resolve_face(
                {"body": body, "panelId": self.panel_id},
                metadata["faceId"],
                [{"faceId": metadata["faceId"], "metadata": metadata}],
            )
        finally:
            resolver_module.build_geometry_signature = original

        self.assertEqual(status, RESOLVE_FOUND)
        self.assertIs(resolved_face, signature_face)

    def test_ambiguous_signature_returns_ambiguous(self):
        signature = build_geometry_signature_from_values(area=500000.0, centroid_local=[10, 10, 8])
        face_a = MockFace("a")
        face_b = MockFace("b")
        body = MockBody([face_a, face_b])
        metadata = {
            "faceId": "FACE-AMB",
            "geometrySignature": signature,
        }

        import face_entity_resolver as resolver_module

        original = resolver_module.build_geometry_signature
        resolver_module.build_geometry_signature = lambda face, panel_context=None: signature
        try:
            status, resolved_face, diagnostics = resolve_face(
                {"body": body, "panelId": self.panel_id},
                "FACE-AMB",
                [{"faceId": "FACE-AMB", "metadata": metadata}],
            )
        finally:
            resolver_module.build_geometry_signature = original

        self.assertEqual(status, RESOLVE_AMBIGUOUS)
        self.assertIsNone(resolved_face)

    def test_read_face_metadata_does_not_write(self):
        face = MockFace()
        metadata, error = read_face_metadata(face)
        self.assertIsNone(metadata)
        self.assertIsNone(error)
        self.assertFalse(has_face_metadata(face))

    def test_remove_one_face_metadata_leaves_others(self):
        face_a = MockFace("a")
        face_b = MockFace("b")
        metadata_a = self.service.initialize_face_metadata(
            face_a,
            self.panel_id,
            {
                "faceClass": FACE_CLASS_EDGE,
                "finish": {"finishId": "raw-core", "finishName": "Raw Core"},
                "machiningPermission": "NOT_ALLOWED",
                "edgeBanding": {
                    "required": False,
                    "bandingCode": 0,
                    "finishId": "raw-core",
                    "finishName": "Raw Core",
                },
                "geometrySignature": build_geometry_signature_from_values(area=1000.0, edge_count=4),
            },
        )
        self.service.initialize_face_metadata(
            face_b,
            self.panel_id,
            {
                "faceClass": FACE_CLASS_EDGE,
                "finish": {"finishId": "raw-core", "finishName": "Raw Core"},
                "machiningPermission": "NOT_ALLOWED",
                "edgeBanding": {
                    "required": False,
                    "bandingCode": 0,
                    "finishId": "raw-core",
                    "finishName": "Raw Core",
                },
                "geometrySignature": build_geometry_signature_from_values(area=2000.0, edge_count=4),
            },
        )
        self.assertTrue(remove_face_metadata(face_a))
        self.assertFalse(has_face_metadata(face_a))
        self.assertTrue(has_face_metadata(face_b))
        stored_after_remove, _error = read_face_metadata(face_a)
        self.assertIsNone(stored_after_remove)

    def test_panel_surface_mode_validation(self):
        surface_a = default_single_sided_door_white_stipple_surface(self.panel_id, generate_face_id())
        surface_b = default_single_sided_door_door_colour_surface(
            self.panel_id,
            generate_face_id(),
            self.door_finish,
        )
        validation = validate_panel_surface_mode(
            {"surfaceMode": SURFACE_MODE_SINGLE_SIDED},
            [surface_a, surface_b],
        )
        self.assertTrue(validation["valid"])
        validation = validate_panel_surface_mode(
            {"surfaceMode": SURFACE_MODE_DOUBLE_SIDED},
            [surface_a, surface_b],
        )
        self.assertFalse(validation["valid"])

    def test_unique_face_ids_validation(self):
        duplicate = default_single_sided_door_white_stipple_surface(self.panel_id, "FACE-DUP")
        duplicate_2 = default_single_sided_door_door_colour_surface(
            self.panel_id,
            "FACE-DUP",
            self.door_finish,
        )
        validation = validate_unique_face_ids([duplicate, duplicate_2])
        self.assertFalse(validation["valid"])

    def test_update_face_metadata_persists(self):
        face = MockFace()
        self.service.initialize_face_metadata(
            face,
            self.panel_id,
            {
                "faceClass": FACE_CLASS_SURFACE,
                "finish": {"finishId": "finish-a", "finishName": "Finish A"},
                "machiningPermission": "ALLOWED",
                "geometrySignature": build_geometry_signature_from_values(area=100.0),
            },
        )
        updated = self.service.update_face_metadata(
            face,
            {"finish": {"finishName": "Updated Name"}},
            panel_context={"panelId": self.panel_id},
        )
        self.assertEqual(updated["finish"]["finishName"], "Updated Name")
        stored, error = read_face_metadata(face)
        self.assertIsNone(error)
        self.assertEqual(stored["finish"]["finishName"], "Updated Name")


if __name__ == "__main__":
    unittest.main()
