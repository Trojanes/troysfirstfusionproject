import os
import sys
import types
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))
sys.path.insert(0, os.path.join(ROOT, "panel_attributes"))

# lay_flat_fusion imports adsk at module level — stub for unit tests.
if "adsk" not in sys.modules:
    adsk = types.ModuleType("adsk")
    adsk.core = types.ModuleType("adsk.core")
    adsk.fusion = types.ModuleType("adsk.fusion")
    sys.modules["adsk"] = adsk
    sys.modules["adsk.core"] = adsk.core
    sys.modules["adsk.fusion"] = adsk.fusion

import lay_flat_fusion as lay_flat  # noqa: E402
import tag_metadata_editor as editor  # noqa: E402
import attribute_state_service  # noqa: E402
import panel_source_ref  # noqa: E402


class ClassificationSyncTests(unittest.TestCase):
    def test_create_stamp_round_trips_source_ref_through_native_body(self):
        class Attribute:
            def __init__(self, value):
                self.value = value

        class Attributes:
            def __init__(self):
                self.values = {}

            def itemByName(self, group, name):
                return self.values.get((group, name))

            def add(self, group, name, value):
                item = Attribute(value)
                self.values[(group, name)] = item
                return item

        class Body:
            name = "LAY_FLAT_BODY"

            def __init__(self):
                self.attributes = Attributes()

        native = Body()
        source_ref = {
            "entityToken": "source-token-1",
            "occurrencePath": [2, 4],
            "bodyName": "OH_D1",
            "componentName": "OHC_1",
            "panelId": "overhead.D1",
        }
        lay_flat._stamp_lay_flat_body(
            native,
            {
                "id": "placement-1",
                "panelId": "overhead.D1",
                "groupIndex": 0,
                "itemIndex": 0,
                "sourceRef": source_ref,
            },
            "run-1",
            {
                "schemaVersion": 1,
                "identity": {"panelId": "overhead.D1"},
                "classification": {
                    "boardType": {"value": "carcass"},
                    "color": {"value": "metallic_white"},
                },
            },
            {},
            {"widthMm": 100, "depthMm": 200},
        )

        proxy = mock.MagicMock()
        proxy.attributes = mock.MagicMock()
        proxy.attributes.itemByName.return_value = None
        proxy.nativeObject = native
        read_back = panel_source_ref.from_lay_flat_body(proxy)
        self.assertEqual(read_back, source_ref)
        self.assertEqual(
            panel_source_ref.key(read_back), "token:source-token-1"
        )

    def test_read_prefers_richer_metadata(self):
        sparse = {"classification": {"cuttingFace": {"value": "MILLING"}}}
        rich = {
            "classification": {
                "boardType": {"value": "carcass"},
                "color": {"value": "white"},
                "cuttingFace": {"value": "MILLING"},
            }
        }

        class Entity:
            def __init__(self, payload):
                self.attributes = mock.MagicMock()
                self.attributes.itemByName.side_effect = (
                    lambda group, name: mock.MagicMock(
                        value=__import__("json").dumps(payload)
                    )
                    if name == "metadata"
                    else None
                )

        proxy = Entity(sparse)
        proxy.isProxy = True
        proxy.nativeObject = Entity(rich)
        data, err = editor._read_body_metadata_raw(proxy)
        self.assertIsNone(err)
        self.assertEqual(data["classification"]["boardType"]["value"], "carcass")
        self.assertEqual(data["classification"]["color"]["value"], "white")

    def test_sync_copies_missing_board_and_color(self):
        lay_meta = {
            "identity": {"panelId": "P1@layflat"},
            "classification": {
                "cuttingFace": {"value": "MILLING", "source": "manual", "locked": True}
            },
        }
        src_meta = {
            "identity": {"panelId": "P1"},
            "classification": {
                "boardType": {"value": "carcass", "source": "manual", "locked": True},
                "color": {
                    "value": "white_stipple",
                    "source": "manual",
                    "locked": True,
                },
                "cuttingFace": {"value": "MILLING", "source": "manual", "locked": True},
            },
            "derivedTags": {"boardTypeTag": "carcass", "colorTag": "white_stipple"},
        }
        writes = []

        fake_panel_attributes = types.ModuleType("panel_attributes")
        fake_panel_attributes.tag_metadata_editor = editor
        fake_panel_attributes.attribute_state_service = attribute_state_service

        with mock.patch.object(
            editor,
            "_read_body_metadata_raw",
            side_effect=[(lay_meta, None), (src_meta, None)],
        ), mock.patch.object(
            editor,
            "_write_body_metadata",
            side_effect=lambda body, meta: writes.append(meta) or meta,
        ), mock.patch.dict(
            sys.modules, {"panel_attributes": fake_panel_attributes}
        ):
            result = lay_flat.sync_lay_flat_classification_from_source(
                object(), object()
            )
        self.assertTrue(result["ok"])
        self.assertTrue(result["changed"])
        self.assertEqual(result["boardType"], "carcass")
        self.assertEqual(result["color"], "white_stipple")
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]["classification"]["boardType"]["value"], "carcass")

    def test_tag_move_only_appends_selected_body_to_matching_column(self):
        class Point:
            def __init__(self, x, y, z=0):
                self.x, self.y, self.z = x, y, z

        class Box:
            def __init__(self, min_x, min_y, max_x, max_y):
                self.minPoint = Point(min_x, min_y)
                self.maxPoint = Point(max_x, max_y, 1)

        class Body:
            def __init__(self, name, box):
                self.name = name
                self.boundingBox = box
                self.parentComponent = object()
                self.isProxy = False

        stationary = Body("stationary", Box(0, 0, 10, 2))
        selected = Body("selected", Box(30, 0, 38, 3))
        untouched = Body("untouched", Box(20, 0, 25, 2))
        moves = []

        class Matrix:
            translation = None

        fake_matrix = mock.MagicMock()
        fake_matrix.create.side_effect = Matrix
        fake_vector = mock.MagicMock()
        fake_vector.create.side_effect = lambda x, y, z: (x, y, z)

        metadata = {
            "identity": {"panelId": "P"},
            "nestingFlatOutline": {"geometrySignature": "old"},
        }
        with mock.patch.object(lay_flat, "_move_body_transform") as move, \
             mock.patch.object(lay_flat, "_snapshot_body_attributes", return_value={}), \
             mock.patch.object(lay_flat, "_restore_body_attributes", return_value=0), \
             mock.patch.object(lay_flat, "_read_lay_flat_metadata", return_value=(metadata, None)), \
             mock.patch.object(lay_flat, "_write_lay_flat_metadata"), \
             mock.patch.object(lay_flat, "body_geometry_signature", return_value="new"), \
             mock.patch.object(lay_flat.adsk.core, "Matrix3D", fake_matrix, create=True), \
             mock.patch.object(lay_flat.adsk.core, "Vector3D", fake_vector, create=True):
            move.side_effect = lambda component, body, matrix, prefix: moves.append(
                (body.name, matrix.translation, prefix)
            )
            result = lay_flat.append_lay_flat_bodies_to_group_ends(
                [
                    {
                        "id": "a",
                        "body": stationary,
                        "boardTypeTag": "door",
                        "colorTag": "white",
                    },
                    {
                        "id": "b",
                        "body": selected,
                        "boardTypeTag": "door",
                        "colorTag": "white",
                    },
                    {
                        "id": "c",
                        "body": untouched,
                        "boardTypeTag": "carcass",
                        "colorTag": "white",
                    },
                ],
                selected_bodies=[selected],
                origin_x_mm=0,
                origin_y_mm=0,
                part_gap_mm=50,
                column_gap_mm=200,
            )
        self.assertTrue(result["ok"])
        self.assertEqual(result["movedCount"], 1)
        self.assertEqual(len(moves), 1)
        self.assertEqual(moves[0][0], "selected")
        self.assertEqual(result["placements"][0]["targetX"], 0)
        self.assertEqual(result["placements"][0]["targetY"], 70)
        self.assertEqual(metadata["nestingFlatOutline"]["geometrySignature"], "new")

    def test_tag_move_uses_geometry_majority_when_neighbours_untagged(self):
        class Point:
            def __init__(self, x, y, z=0):
                self.x, self.y, self.z = x, y, z

        class Box:
            def __init__(self, min_x, min_y, max_x, max_y):
                self.minPoint = Point(min_x, min_y)
                self.maxPoint = Point(max_x, max_y, 1)

        class Body:
            def __init__(self, name, box):
                self.name = name
                self.boundingBox = box
                self.parentComponent = object()
                self.isProxy = False

        # Physical carcass/white column around x=0, but only one body still has tags.
        tagged = Body("tagged", Box(0, 0, 10, 2))
        untagged_a = Body("untagged_a", Box(0.5, 3, 9, 5))
        untagged_b = Body("untagged_b", Box(0.2, 6, 8, 8))
        selected = Body("selected", Box(40, 0, 48, 3))
        moves = []
        metadata = {"identity": {"panelId": "P"}, "nestingFlatOutline": {}}

        class Matrix:
            translation = None

        fake_matrix = mock.MagicMock()
        fake_matrix.create.side_effect = Matrix
        fake_vector = mock.MagicMock()
        fake_vector.create.side_effect = lambda x, y, z: (x, y, z)

        with mock.patch.object(lay_flat, "_move_body_transform") as move, \
             mock.patch.object(lay_flat, "_snapshot_body_attributes", return_value={}), \
             mock.patch.object(lay_flat, "_restore_body_attributes", return_value=0), \
             mock.patch.object(lay_flat, "_read_lay_flat_metadata", return_value=(metadata, None)), \
             mock.patch.object(lay_flat, "_write_lay_flat_metadata"), \
             mock.patch.object(lay_flat, "body_geometry_signature", return_value="new"), \
             mock.patch.object(lay_flat.adsk.core, "Matrix3D", fake_matrix, create=True), \
             mock.patch.object(lay_flat.adsk.core, "Vector3D", fake_vector, create=True):
            move.side_effect = lambda component, body, matrix, prefix: moves.append(body.name)
            result = lay_flat.append_lay_flat_bodies_to_group_ends(
                [
                    {
                        "id": "t",
                        "body": tagged,
                        "boardTypeTag": "carcass",
                        "colorTag": "white_stipple",
                    },
                    {"id": "a", "body": untagged_a, "boardTypeTag": "", "colorTag": ""},
                    {"id": "b", "body": untagged_b, "boardTypeTag": "", "colorTag": ""},
                    {
                        "id": "s",
                        "body": selected,
                        "boardTypeTag": "carcass",
                        "colorTag": "white_stipple",
                    },
                ],
                selected_bodies=[selected],
                origin_x_mm=0,
                origin_y_mm=0,
                part_gap_mm=50,
                column_gap_mm=200,
            )
        self.assertEqual(result["movedCount"], 1)
        self.assertEqual(result["placements"][0]["targetX"], 0)
        # End of geometric column: untagged_b maxY=80mm + 50 gap.
        self.assertEqual(result["placements"][0]["targetY"], 130)
        self.assertEqual(result["placements"][0]["columnSource"], "geometry")

    def test_tag_move_color_only_falls_back_to_existing_color_column(self):
        class Point:
            def __init__(self, x, y, z=0):
                self.x, self.y, self.z = x, y, z

        class Box:
            def __init__(self, min_x, min_y, max_x, max_y):
                self.minPoint = Point(min_x, min_y)
                self.maxPoint = Point(max_x, max_y, 1)

        class Body:
            def __init__(self, name, box):
                self.name = name
                self.boundingBox = box
                self.parentComponent = object()
                self.isProxy = False

        stationary = Body("stationary", Box(-682.6, 600, -455.1, 620))
        selected = Body("selected", Box(28.9, 600, 53.9, 624.2))
        metadata = {"identity": {"panelId": "P"}, "nestingFlatOutline": {}}
        fake_matrix = mock.MagicMock()
        fake_matrix.create.side_effect = lambda: type("M", (), {"translation": None})()
        fake_vector = mock.MagicMock()
        fake_vector.create.side_effect = lambda x, y, z: (x, y, z)

        with mock.patch.object(lay_flat, "_move_body_transform"), \
             mock.patch.object(lay_flat, "_snapshot_body_attributes", return_value={}), \
             mock.patch.object(lay_flat, "_restore_body_attributes", return_value=0), \
             mock.patch.object(lay_flat, "_read_lay_flat_metadata", return_value=(metadata, None)), \
             mock.patch.object(lay_flat, "_write_lay_flat_metadata"), \
             mock.patch.object(lay_flat, "body_geometry_signature", return_value="new"), \
             mock.patch.object(lay_flat.adsk.core, "Matrix3D", fake_matrix, create=True), \
             mock.patch.object(lay_flat.adsk.core, "Vector3D", fake_vector, create=True):
            result = lay_flat.append_lay_flat_bodies_to_group_ends(
                [
                    {
                        "id": "a",
                        "body": stationary,
                        "boardTypeTag": "carcass",
                        "colorTag": "white_stipple",
                    },
                    {
                        "id": "b",
                        "body": selected,
                        # Keep-current board type often arrives as empty/unknown.
                        "boardTypeTag": "",
                        "colorTag": "white_stipple",
                    },
                ],
                selected_bodies=[selected],
                origin_x_mm=-11380,
                origin_y_mm=6000,
                part_gap_mm=50,
                column_gap_mm=200,
            )
        self.assertEqual(result["movedCount"], 1)
        self.assertEqual(result["placements"][0]["boardTypeTag"], "carcass")
        self.assertEqual(result["placements"][0]["colorTag"], "white_stipple")
        self.assertAlmostEqual(result["placements"][0]["targetX"], -6826.0, places=3)
        self.assertNotEqual(result["groups"][0].get("source"), "new")


if __name__ == "__main__":
    unittest.main()
