import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HW_DIR = ROOT / "modules" / "hardware"
REL_DIR = ROOT / "modules" / "relationships"
for path in (HW_DIR, REL_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from relationship_fixtures import build_fixture_snapshots, expected_fixture_cases  # noqa: E402
from relationship_geometry import classify_pair  # noqa: E402
from screw_hole_from_relationship import (  # noqa: E402
    CREATE_ACTION,
    PREVIEW_ACTION,
    build_cut_success_report,
    hole_count_from_contact_length,
    plan_screw_hole_cut_from_relationship,
    preview_screw_holes_from_relationship,
)


def _fixture_edge_to_surface():
    panels = {panel.panelId: panel for panel in build_fixture_snapshots()}
    rel = classify_pair(panels["REL_EDGE_A"], panels["REL_SURFACE_B"])
    snapshots = {panel.panelId: panel.to_dict() for panel in panels.values()}
    return rel.to_dict(), snapshots


def _relationship_with_contact_length(length_mm: float):
    rel, snapshots = _fixture_edge_to_surface()
    rel["contact"]["contactLengthMm"] = length_mm
    return rel, snapshots


class HardwareFromRelationshipTests(unittest.TestCase):
    def test_valid_edge_to_surface_generates_screw_holes(self):
        rel, snapshots = _fixture_edge_to_surface()
        report = preview_screw_holes_from_relationship(
            rel,
            rule={"type": "screw_hole", "diameterMm": 4, "edgeOffsetMm": 30, "depthMode": "host_thickness"},
            panel_snapshots=snapshots,
        )
        self.assertTrue(report["ok"], report)
        self.assertEqual(len(report["features"]), 1)
        feature = report["features"][0]
        self.assertEqual(feature["type"], "screw_hole")
        self.assertEqual(feature["hostPanelId"], "REL_SURFACE_B")
        self.assertEqual(feature["targetPanelId"], "REL_EDGE_A")
        self.assertEqual(feature["source"]["ruleId"], "screw_hole_from_edge_to_surface_v1")
        self.assertGreater(len(feature["geometry"]["positions"]), 0)
        self.assertIn("audit", report)

    def test_non_edge_to_surface_returns_error(self):
        rel, snapshots = _fixture_edge_to_surface()
        rel["geometryType"] = "surface_to_surface"
        rel["relationshipType"] = "face_contact"
        report = preview_screw_holes_from_relationship(rel, panel_snapshots=snapshots)
        self.assertFalse(report["ok"])
        self.assertEqual(report["features"], [])
        self.assertTrue(any("Only edge_to_surface" in err for err in report["errors"]))

    def test_missing_host_target_returns_error(self):
        rel, snapshots = _fixture_edge_to_surface()
        rel["roles"] = {"hostPanelId": None, "targetPanelId": None}
        report = preview_screw_holes_from_relationship(rel, panel_snapshots=snapshots)
        self.assertFalse(report["ok"])
        self.assertTrue(any("hostPanelId and targetPanelId are required" in err for err in report["errors"]))

    def test_short_contact_length_generates_one_hole(self):
        rel, snapshots = _relationship_with_contact_length(80)
        report = preview_screw_holes_from_relationship(rel, panel_snapshots=snapshots)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["holeCount"], 1)
        self.assertEqual(len(report["features"][0]["geometry"]["positions"]), 1)

    def test_medium_contact_length_generates_two_holes(self):
        rel, snapshots = _relationship_with_contact_length(200)
        report = preview_screw_holes_from_relationship(rel, panel_snapshots=snapshots)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["holeCount"], 2)
        self.assertEqual(len(report["features"][0]["geometry"]["positions"]), 2)

    def test_long_contact_length_generates_three_holes(self):
        rel, snapshots = _relationship_with_contact_length(500)
        report = preview_screw_holes_from_relationship(rel, panel_snapshots=snapshots)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["holeCount"], 3)
        self.assertEqual(len(report["features"][0]["geometry"]["positions"]), 3)

    def test_hole_count_helper_thresholds(self):
        self.assertEqual(hole_count_from_contact_length(80), 1)
        self.assertEqual(hole_count_from_contact_length(119.9), 1)
        self.assertEqual(hole_count_from_contact_length(120), 2)
        self.assertEqual(hole_count_from_contact_length(399.9), 2)
        self.assertEqual(hole_count_from_contact_length(400), 3)

    def test_warnings_errors_are_stable(self):
        rel, snapshots = _fixture_edge_to_surface()
        bad = preview_screw_holes_from_relationship(
            {**rel, "geometryType": "gap_parallel", "relationshipType": "unknown"},
            panel_snapshots=snapshots,
        )
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["features"], [])
        self.assertEqual(bad["audit"]["errors"], bad["errors"])

        missing_panels = preview_screw_holes_from_relationship(rel, panel_snapshots={})
        self.assertFalse(missing_panels["ok"])
        self.assertTrue(
            any("Panel snapshots are required" in err or "panels[" in err for err in missing_panels["errors"])
        )

    def test_fixture_case_edge_to_surface_end_to_end(self):
        panels = {panel.panelId: panel for panel in build_fixture_snapshots()}
        snapshots = {panel.panelId: panel.to_dict() for panel in panels.values()}
        for fixture in expected_fixture_cases():
            if fixture["expectedGeometryType"] != "edge_to_surface":
                continue
            rel = classify_pair(panels[fixture["panelAId"]], panels[fixture["panelBId"]]).to_dict()
            report = preview_screw_holes_from_relationship(rel, panel_snapshots=snapshots)
            self.assertTrue(report["ok"], report)
            self.assertGreaterEqual(report["holeCount"], 1)

    def test_cut_plan_valid_edge_to_surface_passes(self):
        rel, snapshots = _fixture_edge_to_surface()
        plan = plan_screw_hole_cut_from_relationship(rel, panel_snapshots=snapshots)
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["action"], CREATE_ACTION)
        self.assertIn("feature", plan)
        self.assertIn("metadata", plan)

    def test_cut_plan_unsupported_relationship_returns_error(self):
        rel, snapshots = _fixture_edge_to_surface()
        rel["geometryType"] = "surface_to_surface"
        rel["relationshipType"] = "face_contact"
        plan = plan_screw_hole_cut_from_relationship(rel, panel_snapshots=snapshots)
        self.assertFalse(plan["ok"])
        self.assertEqual(plan["action"], CREATE_ACTION)
        self.assertTrue(any("Only edge_to_surface" in err for err in plan["errors"]))

    def test_cut_plan_missing_host_panel_id_returns_error(self):
        rel, snapshots = _fixture_edge_to_surface()
        rel["roles"] = {"hostPanelId": None, "targetPanelId": rel["roles"]["targetPanelId"]}
        plan = plan_screw_hole_cut_from_relationship(rel, panel_snapshots=snapshots)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("hostPanelId" in err for err in plan["errors"]))

    def test_cut_plan_missing_target_panel_id_returns_error(self):
        rel, snapshots = _fixture_edge_to_surface()
        rel["roles"] = {"hostPanelId": rel["roles"]["hostPanelId"], "targetPanelId": None}
        plan = plan_screw_hole_cut_from_relationship(rel, panel_snapshots=snapshots)
        self.assertFalse(plan["ok"])
        self.assertTrue(any("targetPanelId" in err for err in plan["errors"]))

    def test_cut_feature_metadata_payload_is_stable(self):
        rel, snapshots = _fixture_edge_to_surface()
        plan = plan_screw_hole_cut_from_relationship(rel, panel_snapshots=snapshots)
        self.assertTrue(plan["ok"], plan)
        metadata = plan["metadata"]
        self.assertEqual(
            set(metadata.keys()),
            {
                "operationType",
                "sourceRelationshipId",
                "hostPanelId",
                "targetPanelId",
                "ruleId",
                "holeCount",
                "diameterMm",
                "depthMm",
            },
        )
        self.assertEqual(metadata["operationType"], "SCREW_HOLE_FROM_RELATIONSHIP")
        self.assertEqual(metadata["ruleId"], "screw_hole_from_edge_to_surface_v1")
        self.assertEqual(metadata["hostPanelId"], "REL_SURFACE_B")
        self.assertEqual(metadata["targetPanelId"], "REL_EDGE_A")
        self.assertGreater(metadata["holeCount"], 0)
        self.assertEqual(metadata["diameterMm"], 4.0)

    def test_cut_success_report_payload_is_stable(self):
        rel, snapshots = _fixture_edge_to_surface()
        plan = plan_screw_hole_cut_from_relationship(rel, panel_snapshots=snapshots)
        report = build_cut_success_report(
            relationship_id=plan["relationshipId"],
            host_panel_id=plan["hostPanelId"],
            target_panel_id=plan["targetPanelId"],
            host_body_name="HOST_BODY",
            target_body_name="TARGET_BODY",
            cut_feature_name="HW_REL_SCREW_HOLE_TEST",
            metadata=plan["metadata"],
            metadata_written=True,
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["operationType"], "SCREW_HOLE_FROM_RELATIONSHIP")
        self.assertEqual(report["cutFeatureName"], "HW_REL_SCREW_HOLE_TEST")
        self.assertTrue(report["metadataWritten"])
        self.assertFalse(report["targetBodyModified"])
        self.assertEqual(report["warnings"], [])
        self.assertEqual(report["errors"], [])

    def test_preview_route_unchanged_by_cut_helpers(self):
        rel, snapshots = _fixture_edge_to_surface()
        preview = preview_screw_holes_from_relationship(rel, panel_snapshots=snapshots)
        self.assertTrue(preview["ok"], preview)
        self.assertEqual(preview["action"], PREVIEW_ACTION)
        self.assertNotIn("cutFeatureName", preview)
        self.assertNotIn("metadataWritten", preview)

        plan = plan_screw_hole_cut_from_relationship(rel, panel_snapshots=snapshots)
        self.assertTrue(plan["ok"], plan)
        self.assertEqual(plan["action"], CREATE_ACTION)
        self.assertIn("preview", plan)

        preview_again = preview_screw_holes_from_relationship(rel, panel_snapshots=snapshots)
        self.assertEqual(preview_again, preview)


if __name__ == "__main__":
    unittest.main()
