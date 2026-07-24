import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
if str(REL_DIR) not in sys.path:
    sys.path.insert(0, str(REL_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from generator_panel_adapter import (  # noqa: E402
    snapshot_dict_from_bbox_board,
    snapshot_dict_from_lounge_panel,
)
from generator_relationship_cases import list_generator_relationship_scenarios  # noqa: E402
from generator_relationship_service import (  # noqa: E402
    evaluate_all_generator_relationship_scenarios,
    evaluate_generator_relationship_scenario,
)


class GeneratorRelationshipTests(unittest.TestCase):
    def test_all_four_generators_have_scenarios(self):
        generators = {item["generator"] for item in list_generator_relationship_scenarios()}
        self.assertEqual(
            generators,
            {"general_tall", "overhead", "kitchen", "lounge"},
        )

    def test_bbox_board_adapter_roundtrip(self):
        payload = snapshot_dict_from_bbox_board(
            {
                "id": "V1",
                "name": "Vertical 1",
                "boardType": "vertical",
                "x0": 0,
                "x1": 16,
                "y0": 0,
                "y1": 584,
                "z0": 0,
                "z1": 2000,
            }
        )
        self.assertEqual(payload["panelId"], "V1")
        self.assertEqual(payload["bbox"]["x1"], 16)

    def test_lounge_panel_adapter_uses_placement(self):
        payload = snapshot_dict_from_lounge_panel(
            {
                "id": "main_front",
                "kind": "front",
                "placement": {"x0": 0, "x1": 400, "y0": 582, "y1": 600, "z0": 0, "z1": 402},
            }
        )
        self.assertEqual(payload["panelId"], "main_front")
        self.assertEqual(payload["bbox"]["y0"], 582)

    def test_all_generator_scenarios_pass(self):
        report = evaluate_all_generator_relationship_scenarios()
        self.assertTrue(report["ok"], report)

    def test_generator_relationships_are_bbox_candidates(self):
        for scenario in list_generator_relationship_scenarios():
            result = evaluate_generator_relationship_scenario(scenario)
            self.assertTrue(result["ok"], result)
            for pair in result["pairResults"]:
                self.assertTrue(pair["matched"], pair)


if __name__ == "__main__":
    unittest.main()
