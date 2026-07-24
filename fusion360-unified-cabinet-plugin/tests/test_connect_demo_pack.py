import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
HW_DIR = ROOT / "modules" / "hardware"
for path in (ROOT, REL_DIR, HW_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from connect_demo_pack import (  # noqa: E402
    DEMO_FIXTURE_BASELINE,
    DEMO_NEGATIVE_FILTERING,
    DEMO_OVERHEAD_STRUCTURAL,
    evaluate_screw_eligibility,
    run_all_demos_offline,
    run_demo_1_fixture_baseline,
    run_demo_2_overhead_structural,
    run_demo_3_negative_filtering,
)
from relationship_fixtures import build_fixture_snapshots  # noqa: E402
from relationship_geometry import classify_pair  # noqa: E402
from relationship_service import scan_relationships  # noqa: E402


class ConnectDemoPackTests(unittest.TestCase):
    def test_evaluate_screw_eligibility_fixture_edge_to_surface(self):
        panels = {panel.panelId: panel for panel in build_fixture_snapshots()}
        rel = classify_pair(panels["REL_EDGE_A"], panels["REL_SURFACE_B"]).to_dict()
        audit = evaluate_screw_eligibility(rel)
        self.assertTrue(audit["screwEligible"])
        self.assertIsNone(audit["rejectReason"])
        self.assertEqual(audit["geometryType"], "edge_to_surface")
        self.assertEqual(audit["relationshipType"], "structural_butt_joint")

    def test_evaluate_screw_eligibility_gap_parallel_rejected(self):
        panels = {panel.panelId: panel for panel in build_fixture_snapshots()}
        rel = classify_pair(panels["REL_GAP_A"], panels["REL_GAP_B"]).to_dict()
        audit = evaluate_screw_eligibility(rel)
        self.assertFalse(audit["screwEligible"])
        self.assertEqual(audit["rejectReason"], "gap_parallel_not_screw_joint")

    def test_demo_1_fixture_baseline_end_to_end(self):
        demo = run_demo_1_fixture_baseline()
        self.assertEqual(demo["demoId"], DEMO_FIXTURE_BASELINE)
        self.assertTrue(demo["ok"], demo.get("errors"))
        summary = demo["summary"]
        self.assertTrue(summary["previewOk"])
        self.assertTrue(summary["confirmedOk"])
        self.assertTrue(summary["cutOk"])
        self.assertGreater(summary["screwEligibleCount"], 0)
        selected = demo["audit"]["selectedRelationship"]
        self.assertEqual(selected["geometryType"], "edge_to_surface")
        self.assertEqual(selected["relationshipType"], "structural_butt_joint")
        ver = selected.get("verification") or {}
        self.assertEqual(ver.get("level"), "bbox_candidate")
        self.assertFalse(ver.get("safeForCut"))

    def test_demo_2_overhead_structural_joint(self):
        demo = run_demo_2_overhead_structural()
        self.assertEqual(demo["demoId"], DEMO_OVERHEAD_STRUCTURAL)
        self.assertTrue(demo["ok"], demo.get("errors"))
        summary = demo["summary"]
        self.assertGreater(summary["panelCount"], 0)
        self.assertGreater(summary["relationshipCount"], 0)
        self.assertGreater(summary["screwEligibleCount"], 0)
        self.assertTrue(summary["previewOk"])
        self.assertTrue(summary["confirmedOk"])
        self.assertTrue(summary["cutOk"])

    def test_demo_3_negative_filtering_blocks_non_screw(self):
        demo = run_demo_3_negative_filtering()
        self.assertEqual(demo["demoId"], DEMO_NEGATIVE_FILTERING)
        self.assertTrue(demo["ok"], demo.get("errors"))
        cases = demo["audit"]["negativeCases"]
        self.assertGreaterEqual(len(cases), 3)
        for case in cases:
            self.assertFalse(case["eligibility"]["screwEligible"])
            self.assertFalse(case["previewOk"])
            self.assertFalse(case["cutPlanOk"])
            self.assertIsNotNone(case["confirmGateError"])

    def test_run_all_demos_offline(self):
        report = run_all_demos_offline()
        self.assertTrue(report["ok"])
        self.assertEqual(len(report["demos"]), 3)
        self.assertEqual(len(report["summaries"]), 3)
        demo_ids = {item["demoId"] for item in report["demos"]}
        self.assertIn(DEMO_FIXTURE_BASELINE, demo_ids)
        self.assertIn(DEMO_OVERHEAD_STRUCTURAL, demo_ids)
        self.assertIn(DEMO_NEGATIVE_FILTERING, demo_ids)


if __name__ == "__main__":
    unittest.main()
