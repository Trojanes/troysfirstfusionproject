"""Lounge assembly-pose cut plane mapping (no Fusion runtime required)."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = PLUGIN_ROOT / "modules" / "lounge" / "fusion_adapter.py"


def _load_adapter():
    if "adsk" not in sys.modules:
        adsk = types.ModuleType("adsk")
        adsk.core = types.ModuleType("adsk.core")
        adsk.fusion = types.ModuleType("adsk.fusion")
        sys.modules["adsk"] = adsk
        sys.modules["adsk.core"] = adsk.core
        sys.modules["adsk.fusion"] = adsk.fusion

    if "geometry_ops" not in sys.modules:
        geometry_ops = types.ModuleType("geometry_ops")
        geometry_ops.ATTRIBUTE_GROUP = "UnifiedCabinetPlugin"
        geometry_ops.MODEL_Z_OFFSET_MM = 0.0
        geometry_ops.mm_to_cm = lambda value: float(value) / 10.0
        geometry_ops.sanitize_token = lambda value, fallback="x", limit=40: str(value or fallback)[:limit]
        geometry_ops.entity_module = lambda _entity: ""
        geometry_ops.is_module_artifact = lambda *_args, **_kwargs: False
        geometry_ops.name_looks_like_module = lambda *_args, **_kwargs: False
        geometry_ops.offset_matching_bodies_z_mm = lambda *_args, **_kwargs: {}
        geometry_ops.capture_position_snapshot = lambda *_args, **_kwargs: None
        geometry_ops.avoid_existing_at_origin = lambda _root, x, y, _footprint: (x, y, {"shifted": False, "slots": 0})
        sys.modules["geometry_ops"] = geometry_ops

    if "workpiece_names" not in sys.modules:
        names = types.ModuleType("workpiece_names")
        names.board_component_label = lambda assembly, board_id, fallback_assembly="x": "{}-{}".format(assembly, board_id)
        names.resolve_assembly_name = lambda *args, **kwargs: kwargs.get("default_name") or "Lounge"
        sys.modules["workpiece_names"] = names
        sys.modules["nesting.workpiece_names"] = names

    if "generator_default_attributes" not in sys.modules:
        attrs = types.ModuleType("generator_default_attributes")
        attrs.extract_carcass_color_from_result = lambda *_args, **_kwargs: (None, None)
        attrs.write_generator_panel_metadata = lambda *_args, **_kwargs: ({}, True)
        sys.modules["generator_default_attributes"] = attrs

    spec = importlib.util.spec_from_file_location("lounge_fusion_adapter_cuts", ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LoungeOrientedCutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = _load_adapter()

    def test_mid_shelf_grooves_cut_inner_yz_faces(self):
        left = {"x0": 630, "x1": 645, "y0": 635, "y1": 900, "z0": 315, "z1": 685}
        right = {"x0": 1235, "x1": 1250, "y0": 635, "y1": 900, "z0": 315, "z1": 685}
        left_spec = self.adapter._oriented_cut_plane_spec("YZ", left, "top")
        right_spec = self.adapter._oriented_cut_plane_spec("YZ", right, "bottom")
        self.assertEqual(left_spec["plane"], "YZ")
        self.assertEqual(left_spec["anchorMm"], 645)
        self.assertFalse(left_spec["intoPositive"])
        self.assertEqual(right_spec["anchorMm"], 1235)
        self.assertTrue(right_spec["intoPositive"])

    def test_draw_placement_moves_yz_top_face_to_x1(self):
        placement = {"x0": 630, "x1": 645, "y0": 635, "z0": 315}
        draw = self.adapter._draw_placement_for_cut_face("YZ", placement, "top")
        self.assertEqual(draw["x0"], 645)
        bottom = self.adapter._draw_placement_for_cut_face("YZ", placement, "bottom")
        self.assertEqual(bottom["x0"], 630)

    def test_door_lock_world_point_stays_on_door_interior(self):
        placement = {"x0": 647, "x1": 939, "y0": 635, "y1": 650, "z0": 317, "z1": 683}
        draw = self.adapter._draw_placement_for_cut_face("XZ", placement, "top")
        world = self.adapter._profile_world_point("XZ", draw, [262, 195])
        self.assertEqual(world[1], 650)
        self.assertAlmostEqual(world[0], 909)
        self.assertAlmostEqual(world[2], 512)

    def test_hinge_interior_face_anchors_at_door_y1(self):
        placement = {"x0": 647, "x1": 939, "y0": 635, "y1": 650, "z0": 317, "z1": 683}
        spec = self.adapter._oriented_cut_plane_spec("XZ", placement, "top")
        self.assertEqual(spec["anchorMm"], 650)

    def test_flipped_xz_axis_reverses_arc_sweep_sign(self):
        self.assertEqual(self.adapter._sketch_handedness_sign(1, 0, 0, 1), 1.0)
        self.assertEqual(self.adapter._sketch_handedness_sign(1, 0, 0, -1), -1.0)

    def test_cut_from_door_interior_goes_into_thickness(self):
        self.assertEqual(
            self.adapter._extrude_sign_from_plane_to_point(0, 65.0, 0, 0, 1, 0, 0, 64.25, 0),
            -1.0,
        )
        self.assertEqual(
            self.adapter._extrude_sign_from_plane_to_point(0, 65.0, 0, 0, -1, 0, 0, 64.25, 0),
            1.0,
        )

    def test_mid_shelf_groove_world_point_stays_on_inner_yz(self):
        placement = {"x0": 630, "x1": 645, "y0": 635, "y1": 900, "z0": 315, "z1": 685}
        draw = self.adapter._draw_placement_for_cut_face("YZ", placement, "top")
        world = self.adapter._profile_world_point("YZ", draw, [135, 177])
        self.assertEqual(world[0], 645)
        self.assertAlmostEqual(world[1], 770)
        self.assertAlmostEqual(world[2], 492)

    def test_assembly_footprint_uses_placement_xy(self):
        result = {
            "panels": [
                {"id": "left", "placement": {"x0": 0, "x1": 900, "y0": 0, "y1": 600}},
                {"id": "right", "placement": {"x0": 900, "x1": 1880, "y0": 0, "y1": 900}},
            ]
        }
        footprint = self.adapter._lounge_result_footprint_mm(result, "assembly")
        self.assertEqual(footprint, (0.0, 1880.0, 0.0, 900.0))


if __name__ == "__main__":
    unittest.main()
