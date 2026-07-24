"""LED groove placement helpers (no Fusion runtime required)."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = PLUGIN_ROOT / "modules" / "general_tall" / "fusion_adapter.py"


def _load_adapter():
    # Stub Fusion / geometry deps so the adapter module imports offline.
    if "adsk" not in sys.modules:
        adsk = types.ModuleType("adsk")
        adsk.core = types.ModuleType("adsk.core")
        adsk.fusion = types.ModuleType("adsk.fusion")

        class _ExtentDirections:
            PositiveExtentDirection = "positive"
            NegativeExtentDirection = "negative"

        adsk.fusion.ExtentDirections = _ExtentDirections
        sys.modules["adsk"] = adsk
        sys.modules["adsk.core"] = adsk.core
        sys.modules["adsk.fusion"] = adsk.fusion
    else:
        fusion = sys.modules.get("adsk.fusion")
        if fusion is not None:
            class _ExtentDirections:
                PositiveExtentDirection = "positive"
                NegativeExtentDirection = "negative"

            # Other offline tests may leave a permissive MagicMock adsk module.
            fusion.ExtentDirections = _ExtentDirections

    if "geometry_ops" not in sys.modules:
        geometry_ops = types.ModuleType("geometry_ops")
        geometry_ops.ATTRIBUTE_GROUP = "UnifiedCabinet"
        geometry_ops.MODEL_Z_OFFSET_MM = 0.0

        def mm_to_cm(value):
            return float(value) / 10.0

        def sanitize_token(value, fallback="x", limit=40):
            text = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in str(value or fallback))
            return (text or fallback)[:limit]

        def _noop(*_args, **_kwargs):
            return None

        geometry_ops.mm_to_cm = mm_to_cm
        geometry_ops.sanitize_token = sanitize_token
        geometry_ops.avoid_existing_at_origin = _noop
        geometry_ops.capture_position_snapshot = _noop
        geometry_ops.move_body_by_mm = _noop
        geometry_ops.offset_matching_bodies_z_mm = _noop
        sys.modules["geometry_ops"] = geometry_ops

    sys.modules.pop("gt_fusion_adapter_led", None)
    spec = importlib.util.spec_from_file_location("gt_fusion_adapter_led", ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.path.insert(0, str(ADAPTER_PATH.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        if sys.path and sys.path[0] == str(ADAPTER_PATH.parent):
            sys.path.pop(0)
    return module


class LedGrooveWorldRectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = _load_adapter()

    def test_main_channel_stays_near_front_not_rear(self):
        bbox = {"x0": 16.0, "x1": 684.0, "y0": 0.0, "y1": 150.0, "z0": 2044.0, "z1": 2060.0}
        main = {"x0": 0.0, "x1": 668.0, "y0": 12.75, "y1": 27.25}
        rect = self.adapter._led_segment_world_rect(bbox, main)
        self.assertIsNotNone(rect)
        x0, y0, x1, y1 = rect
        self.assertAlmostEqual(x0, 16.0)
        self.assertAlmostEqual(x1, 684.0)
        self.assertLess(y0, 40.0)
        self.assertLess(y1, 40.0)
        self.assertGreater(y0, 10.0)

    def test_branches_extend_to_board_back_edge(self):
        bbox = {"x0": 16.0, "x1": 684.0, "y0": 0.0, "y1": 150.0, "z0": 0.0, "z1": 16.0}
        branch = {"x0": 72.75, "x1": 87.25, "y0": 27.25, "y1": 150.0}
        rect = self.adapter._led_segment_world_rect(bbox, branch)
        self.assertIsNotNone(rect)
        _x0, y0, _x1, y1 = rect
        self.assertAlmostEqual(y0, 27.25)
        self.assertAlmostEqual(y1, 150.0)

    def test_b3_bottom_cut_opens_downward(self):
        bbox = {"x0": 16.0, "x1": 684.0, "y0": 0.0, "y1": 150.0, "z0": 53.0, "z1": 69.0}
        plane_z, direction, cut_signed, opening = self.adapter._led_cut_plane_and_direction(
            "bottom", bbox, 6.5
        )
        self.assertAlmostEqual(plane_z, 52.95)
        self.assertEqual(direction, "positive")
        self.assertGreater(cut_signed, 0)
        self.assertEqual(opening, "downward")

    def test_t3_top_cut_into_board(self):
        bbox = {"x0": 16.0, "x1": 684.0, "y0": 0.0, "y1": 150.0, "z0": 2044.0, "z1": 2060.0}
        plane_z, direction, cut_signed, opening = self.adapter._led_cut_plane_and_direction(
            "top", bbox, 6.5
        )
        self.assertAlmostEqual(plane_z, 2060.0)
        self.assertEqual(direction, "negative")
        self.assertLess(cut_signed, 0)


if __name__ == "__main__":
    unittest.main()
