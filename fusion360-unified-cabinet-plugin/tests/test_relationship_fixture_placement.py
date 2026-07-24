import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
if str(REL_DIR) not in sys.path:
    sys.path.insert(0, str(REL_DIR))

from relationship_fixtures import (  # noqa: E402
    FIXTURE_BASE_Z_MM,
    FIXTURE_PART_BASE_Z_MM,
    FIXTURE_PART_X_OFFSET_MM,
    fixture_panel_definitions,
    resolve_fixture_base_x_mm,
    resolve_fixture_base_z_mm,
)


class RelationshipFixturePlacementTests(unittest.TestCase):
    def test_offline_defaults_remain_at_legacy_z(self):
        panels = fixture_panel_definitions()
        self.assertEqual(panels[0]["bbox"]["z0"], FIXTURE_BASE_Z_MM)

    def test_part_mode_uses_ground_level_and_x_offset(self):
        self.assertEqual(resolve_fixture_base_z_mm(True), FIXTURE_PART_BASE_Z_MM)
        self.assertEqual(resolve_fixture_base_x_mm(True), FIXTURE_PART_X_OFFSET_MM)
        panels = fixture_panel_definitions(base_z_mm=0.0, base_x_mm=FIXTURE_PART_X_OFFSET_MM)
        self.assertEqual(panels[0]["bbox"]["z0"], 0.0)
        self.assertEqual(panels[0]["bbox"]["x0"], FIXTURE_PART_X_OFFSET_MM)

    def test_assembly_mode_keeps_high_z(self):
        self.assertEqual(resolve_fixture_base_z_mm(False), FIXTURE_BASE_Z_MM)
        self.assertEqual(resolve_fixture_base_x_mm(False), 0.0)


if __name__ == "__main__":
    unittest.main()
