import math
import os
import sys
import unittest
from unittest.mock import MagicMock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if "adsk" not in sys.modules:
    adsk = MagicMock()
    adsk.core = MagicMock()
    adsk.fusion = MagicMock()
    sys.modules["adsk"] = adsk
    sys.modules["adsk.core"] = adsk.core
    sys.modules["adsk.fusion"] = adsk.fusion

from nesting import fusion_layout  # noqa: E402
from nesting.fusion_layout import rotation_from_to  # noqa: E402
from nesting import dxf_export  # noqa: E402
from nesting.brep_loops import (  # noqa: E402
    directed_coedge_points,
    inner_loop_is_full_through,
)


class _Collection:
    def __init__(self, values):
        self._values = values
        self.count = len(values)

    def item(self, index):
        return self._values[index]


class _Point:
    def __init__(self, x, y, z=0):
        self.x, self.y, self.z = x, y, z


class _Bounds:
    def __init__(self, min_z, max_z):
        self.minPoint = _Point(0, 0, min_z)
        self.maxPoint = _Point(0, 0, max_z)


class _Evaluator:
    def __init__(self, points):
        self.points = points
        self.stroke_args = None

    def getParameterExtents(self):
        return True, 2.0, 8.0

    def getStrokes(self, start, end, tolerance):
        self.stroke_args = (start, end, tolerance)
        return True, self.points


class _Entity:
    pass


class NestingFusionLayoutMathTests(unittest.TestCase):
    def test_same_direction_needs_no_rotation(self):
        angle, axis = rotation_from_to([0, 0, 1], [0, 0, 1])
        self.assertAlmostEqual(angle, 0.0)
        self.assertEqual(len(axis), 3)

    def test_side_face_rotates_ninety_degrees(self):
        angle, axis = rotation_from_to([1, 0, 0], [0, 0, 1])
        self.assertAlmostEqual(angle, math.pi / 2.0)
        self.assertAlmostEqual(sum(v * v for v in axis), 1.0)

    def test_opposite_face_rotates_one_eighty(self):
        angle, axis = rotation_from_to([0, 0, -1], [0, 0, 1])
        self.assertAlmostEqual(angle, math.pi)
        self.assertAlmostEqual(sum(v * v for v in axis), 1.0)

    def test_workpiece_uses_one_body_marker_and_returns_manifest_record(self):
        body = MagicMock()
        placement = {
            "panelId": "P1",
            "bodyName": "Source",
            "boardTypeTag": "carcass",
            "colorTag": "white",
            "groupIndex": 0,
            "itemIndex": 1,
            "sheetIndex": 2,
            "rotationDeg": 90,
        }
        with patch.object(fusion_layout, "_strip_panel_attributes"), patch.object(
            fusion_layout, "_set_attr", return_value=True
        ) as set_attr:
            details = fusion_layout._mark_workpiece(body, placement, "run-1")
        self.assertEqual(set_attr.call_count, 1)
        self.assertEqual(
            set_attr.call_args.args[1:],
            (
                fusion_layout.OUTPUT_MARKER_GROUP,
                fusion_layout.OUTPUT_MARKER_NAME,
                "nestingWorkpiece",
            ),
        )
        self.assertEqual(details["sourcePanelId"], "P1")
        self.assertEqual(details["sheetIndex"], 2)

    def test_dxf_manifest_reader_parses_component_record(self):
        raw = (
            '{"version":1,"runId":"r","workpieces":'
            '{"NEST_A":{"sheetIndex":3,"sourcePanelId":"P9"}}}'
        )
        with patch.object(dxf_export, "_attr", return_value=raw):
            manifest = dxf_export._workpiece_manifest(MagicMock())
        self.assertEqual(manifest["NEST_A"]["sheetIndex"], 3)

    def test_coedge_strokes_follow_reversed_loop_direction(self):
        evaluator = _Evaluator([_Point(0, 0), _Point(0.5, 0.2), _Point(1, 0)])
        edge = _Entity()
        edge.evaluator = evaluator
        coedge = _Entity()
        coedge.edge = edge
        coedge.isOpposedToEdge = True
        points = directed_coedge_points(coedge)
        self.assertEqual(points[0], (1.0, 0.0, 0.0))
        self.assertEqual(points[-1], (0.0, 0.0, 0.0))
        self.assertEqual(evaluator.stroke_args, (2.0, 8.0, 0.01))

    def test_coedge_reverses_after_opposite_evaluator_direction_is_normalized(self):
        evaluator = _Evaluator([_Point(1, 0), _Point(0.5, 0.2), _Point(0, 0)])
        edge = _Entity()
        edge.evaluator = evaluator
        edge.startVertex = _Entity()
        edge.startVertex.geometry = _Point(0, 0)
        edge.endVertex = _Entity()
        edge.endVertex.geometry = _Point(1, 0)
        coedge = _Entity()
        coedge.edge = edge
        coedge.isOpposedToEdge = True

        points = directed_coedge_points(coedge)

        self.assertEqual(points[0], (1.0, 0.0, 0.0))
        self.assertEqual(points[1], (0.5, 0.2, 0.0))
        self.assertEqual(points[-1], (0.0, 0.0, 0.0))

    def test_full_through_wall_reaches_opposite_extent_but_blind_does_not(self):
        body = _Entity()
        body.boundingBox = _Bounds(0.0, 2.0)
        top = _Entity()

        def loop_with_wall(min_z):
            wall = _Entity()
            wall.boundingBox = _Bounds(min_z, 2.0)
            edge = _Entity()
            edge.faces = _Collection([top, wall])
            coedge = _Entity()
            coedge.edge = edge
            loop = _Entity()
            loop.coEdges = _Collection([coedge])
            return loop

        self.assertTrue(inner_loop_is_full_through(loop_with_wall(0.0), top, body))
        self.assertFalse(inner_loop_is_full_through(loop_with_wall(1.5), top, body))


if __name__ == "__main__":
    unittest.main()
