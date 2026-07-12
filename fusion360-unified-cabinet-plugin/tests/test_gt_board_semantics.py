import importlib.util
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[1]
ADAPTER_PATH = ROOT / "modules" / "general_tall" / "fusion_adapter.py"
PANEL_ATTR_DIR = ROOT / "panel_attributes"


def _load_adapter():
    # Stub Fusion API modules so the adapter can import outside Fusion.
    if "adsk" not in sys.modules:
        adsk = MagicMock()
        adsk.core = MagicMock()
        adsk.fusion = MagicMock()
        sys.modules["adsk"] = adsk
        sys.modules["adsk.core"] = adsk.core
        sys.modules["adsk.fusion"] = adsk.fusion
    geometry_ops_path = ROOT / "fusion" / "geometry_ops.py"
    if "geometry_ops" not in sys.modules and geometry_ops_path.exists():
        # Prefer a lightweight stub; adapter only needs a few symbols at import.
        stub = MagicMock()
        stub.ATTRIBUTE_GROUP = "UnifiedCabinetPlugin"
        stub.MODEL_Z_OFFSET_MM = 0.0
        stub.mm_to_cm = lambda mm: float(mm) / 10.0
        stub.sanitize_token = lambda value, fallback="x", limit=40: str(value or fallback)[:limit]
        stub.avoid_existing_at_origin = MagicMock(return_value=(0, 0, None))
        stub.capture_position_snapshot = MagicMock()
        stub.move_body_by_mm = MagicMock()
        stub.offset_matching_bodies_z_mm = MagicMock()
        sys.modules["geometry_ops"] = stub

    spec = importlib.util.spec_from_file_location("gt_fusion_adapter_under_test", ADAPTER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class GtBoardSemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter = _load_adapter()

    def test_t3_and_b3_are_carcass(self):
        for board_id in ("T3", "B3"):
            semantics = self.adapter._gt_board_semantics({"id": board_id, "boardType": board_id})
            self.assertEqual(semantics["materialClass"], "carcass_board", board_id)
            self.assertEqual(semantics["role"], "carcass", board_id)
            meta = self.adapter._gt_panel_metadata(
                {"id": board_id, "boardType": board_id, "materialThickness": 16,
                 "profilePlane": "XY", "thicknessAxis": "Z"},
                {"x0": 0, "x1": 600, "y0": 0, "y1": 150, "z0": 0, "z1": 16},
                "run1",
            )
            self.assertEqual(meta["defaultAttributes"]["materialClass"], "carcass_board")
            self.assertEqual(meta["classification"]["boardType"]["value"], "carcass")
            self.assertEqual(meta["classification"]["boardType"]["source"], "generator")
            self.assertNotIn("derivedTags", meta)
            self.assertIn(board_id, meta["identity"]["panelId"])

    def test_t1_and_b1_are_door_colour_fascia(self):
        for board_id in ("T1", "B1"):
            semantics = self.adapter._gt_board_semantics({"id": board_id, "boardType": board_id})
            self.assertEqual(semantics["materialClass"], "door_board", board_id)
            self.assertEqual(semantics["role"], "front_visible", board_id)

    def test_front_panel_is_door(self):
        semantics = self.adapter._gt_board_semantics({
            "id": "FP_zone-1",
            "boardType": "cabinet_door",
            "category": "front_panel",
        })
        self.assertEqual(semantics["materialClass"], "door_board")
        self.assertEqual(semantics["role"], "door")


class GtScanInferenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if str(PANEL_ATTR_DIR) not in sys.path:
            sys.path.insert(0, str(PANEL_ATTR_DIR))
        import metadata_inspector as inspector  # noqa: E402
        cls.inspector = inspector

    def test_infer_t3_b3_carcass_even_when_cpt_matches_door(self):
        self.assertEqual(self.inspector._infer_material_class("generalTall", "T3", None, None), "carcass_board")
        self.assertEqual(self.inspector._infer_material_class("generalTall", "B3", None, None), "carcass_board")
        self.assertEqual(self.inspector._infer_material_class("generalTall", "T1", None, None), "door_board")
        self.assertEqual(self.inspector._infer_material_class("generalTall", "B1", None, None), "door_board")


if __name__ == "__main__":
    unittest.main()
