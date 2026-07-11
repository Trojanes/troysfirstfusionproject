import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HW_DIR = ROOT / "modules" / "hardware"
PANEL_ATTR_DIR = ROOT / "panel_attributes"
REL_DIR = ROOT / "modules" / "relationships"
for path in (ROOT, HW_DIR, PANEL_ATTR_DIR, REL_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from connect_demo_pack import find_first_screw_eligible  # noqa: E402
from hardware_rule_engine import (  # noqa: E402
    HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
    HARDWARE_TYPE_HINGE_HOLE,
    HARDWARE_TYPE_LOCK_CUTOUT,
    HARDWARE_TYPE_SCREW_HOLE,
    HARDWARE_TYPE_TONGUE_GROOVE,
    dispatch_hardware_cut_plan,
    dispatch_hardware_preview,
    evaluate_hardware_rule,
    list_hardware_types,
)
from panel_metadata_writeback import (  # noqa: E402
    OPERATION_TYPE,
    append_hardware_feature,
    build_lock_cutout_panel_feature_record,
    build_panel_feature_record,
    build_tongue_groove_panel_feature_record,
    find_hardware_features,
)
from relationship_fixtures import build_fixture_snapshots, expected_fixture_cases  # noqa: E402
from relationship_models import confirm_relationship_for_cut  # noqa: E402
from relationship_report import build_scan_report  # noqa: E402
from relationship_service import scan_relationships  # noqa: E402
from screw_hole_from_relationship import build_cut_feature_metadata  # noqa: E402
from tongue_groove_from_relationship import (  # noqa: E402
    build_cut_feature_metadata as build_tg_cut_metadata,
    plan_tongue_groove_cut_from_relationship,
)


def _fixture_scan():
    panels = build_fixture_snapshots()
    _, relationships = scan_relationships(panels, tolerance_mm=0.5, include_none=True)
    return build_scan_report(
        action="relationships.scan",
        panels=panels,
        relationships=relationships,
        scope="fixture",
        tolerance_mm=0.5,
        expected_fixtures=expected_fixture_cases(),
    )


class PanelMetadataWritebackTests(unittest.TestCase):
    def test_build_panel_feature_record_from_screw_hole_intent(self):
        feature = {
            "featureId": "rel.test::screw_hole",
            "geometry": {
                "axis": "Y",
                "diameterMm": 4,
                "depthMm": 15,
                "positions": [{"x": 10, "y": 0, "z": 20}, {"x": 90, "y": 0, "z": 20}],
            },
            "sourceRelationshipId": "rel.test",
            "hostPanelId": "HOST",
            "targetPanelId": "TARGET",
            "source": {"ruleId": "screw_hole_from_edge_to_surface_v1"},
        }
        cut_meta = build_cut_feature_metadata(
            feature,
            relationship_id="rel.test",
            host_panel_id="HOST",
            target_panel_id="TARGET",
        )
        record = build_panel_feature_record(feature, cut_metadata=cut_meta, cut_feature_name="HW_REL_SCREW_HOLE_1")
        self.assertEqual(record["kind"], "hole")
        self.assertEqual(record["operationType"], OPERATION_TYPE)
        self.assertEqual(record["sourceRelationshipId"], "rel.test")
        self.assertEqual(record["holeCount"], 2)
        self.assertEqual(record["center2d"], [10.0, 20.0])

    def test_append_hardware_feature_deduplicates(self):
        base = {"schemaVersion": 1, "features": []}
        record = {
            "featureId": "rel.test::screw_hole",
            "operationType": OPERATION_TYPE,
            "sourceRelationshipId": "rel.test",
        }
        updated, appended, _ = append_hardware_feature(base, record)
        self.assertTrue(appended)
        updated2, appended2, reason = append_hardware_feature(updated, record)
        self.assertFalse(appended2)
        self.assertEqual(reason, "duplicate_feature")
        self.assertEqual(len(updated2["features"]), 1)

    def test_find_hardware_features_by_relationship(self):
        metadata = {
            "features": [
                {"featureId": "a", "sourceRelationshipId": "rel.one", "operationType": OPERATION_TYPE},
                {"featureId": "b", "sourceRelationshipId": "rel.two", "operationType": OPERATION_TYPE},
            ]
        }
        found = find_hardware_features(metadata, source_relationship_id="rel.one")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["featureId"], "a")


class HardwareRuleEngineTests(unittest.TestCase):
    def test_list_hardware_types_includes_scaffold_types(self):
        rows = list_hardware_types()
        types = {row["type"] for row in rows}
        self.assertIn(HARDWARE_TYPE_SCREW_HOLE, types)
        self.assertIn(HARDWARE_TYPE_TONGUE_GROOVE, types)
        self.assertIn(HARDWARE_TYPE_DRAWER_RUNNER_HOLE, types)
        screw = next(row for row in rows if row["type"] == HARDWARE_TYPE_SCREW_HOLE)
        tongue = next(row for row in rows if row["type"] == HARDWARE_TYPE_TONGUE_GROOVE)
        hinge = next(row for row in rows if row["type"] == HARDWARE_TYPE_HINGE_HOLE)
        lock = next(row for row in rows if row["type"] == HARDWARE_TYPE_LOCK_CUTOUT)
        runner = next(row for row in rows if row["type"] == HARDWARE_TYPE_DRAWER_RUNNER_HOLE)
        self.assertTrue(screw["implemented"])
        self.assertTrue(screw["cutReady"])
        self.assertTrue(tongue["implemented"])
        self.assertTrue(tongue["cutReady"])
        self.assertFalse(tongue["previewOnly"])
        self.assertTrue(tongue["previewReady"])
        self.assertTrue(hinge["implemented"])
        self.assertTrue(hinge["cutReady"])
        self.assertFalse(hinge["previewOnly"])
        self.assertTrue(hinge["previewReady"])
        self.assertTrue(runner["implemented"])
        self.assertTrue(runner["cutReady"])
        self.assertFalse(runner["previewOnly"])
        self.assertTrue(runner["previewReady"])
        self.assertTrue(lock["implemented"])
        self.assertTrue(lock["cutReady"])
        self.assertFalse(lock["previewOnly"])
        self.assertTrue(lock["previewReady"])

    def test_scaffold_hardware_preview_dispatch_fixture(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        panel_map = {panel.panelId: panel.to_dict() for panel in build_fixture_snapshots()}
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        panels = {host_id: panel_map[host_id], target_id: panel_map[target_id]}

        hinge = dispatch_hardware_preview(rel, rule={"type": HARDWARE_TYPE_HINGE_HOLE}, panel_snapshots=panels)
        self.assertTrue(hinge.get("ok"), hinge.get("errors"))
        self.assertGreaterEqual(int(hinge.get("holeCount") or 0), 1)
        self.assertFalse(hinge.get("previewOnly"))
        self.assertTrue(hinge.get("cutReady"))

        lock = dispatch_hardware_preview(rel, rule={"type": HARDWARE_TYPE_LOCK_CUTOUT}, panel_snapshots=panels)
        self.assertTrue(lock.get("ok"), lock.get("errors"))
        pocket = ((lock.get("features") or [{}])[0].get("geometry") or {}).get("pocket") or {}
        self.assertGreater(float(pocket.get("depthMm") or 0), 0)
        self.assertFalse(lock.get("previewOnly"))
        self.assertTrue(lock.get("cutReady"))

        runner = dispatch_hardware_preview(
            rel, rule={"type": HARDWARE_TYPE_DRAWER_RUNNER_HOLE}, panel_snapshots=panels
        )
        self.assertTrue(runner.get("ok"), runner.get("errors"))
        self.assertGreaterEqual(int(runner.get("holeCount") or 0), 2)
        self.assertFalse(runner.get("previewOnly"))
        self.assertTrue(runner.get("cutReady"))

        for hw_type in (HARDWARE_TYPE_HINGE_HOLE, HARDWARE_TYPE_LOCK_CUTOUT, HARDWARE_TYPE_DRAWER_RUNNER_HOLE):
            blocked = dispatch_hardware_cut_plan(rel, rule={"type": hw_type})
            self.assertFalse(blocked.get("ok"))

    def test_hinge_hole_cut_plan_after_confirm(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        panel_map = {panel.panelId: panel.to_dict() for panel in build_fixture_snapshots()}
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        panels = {host_id: panel_map[host_id], target_id: panel_map[target_id]}
        confirmed = dict(rel)
        confirmed["verification"] = {
            "level": "manual_confirmed",
            "safeForPreview": True,
            "safeForCut": True,
            "requiresManualConfirmation": False,
        }
        plan = dispatch_hardware_cut_plan(
            confirmed, rule={"type": HARDWARE_TYPE_HINGE_HOLE}, panel_snapshots=panels
        )
        self.assertTrue(plan.get("ok"), plan.get("errors"))
        self.assertEqual(plan.get("hardwareType"), HARDWARE_TYPE_HINGE_HOLE)
        self.assertTrue(plan.get("feature"))
        self.assertEqual((plan.get("metadata") or {}).get("operationType"), "HINGE_HOLE_FROM_RELATIONSHIP")

    def test_lock_cutout_cut_plan_after_confirm(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        panel_map = {panel.panelId: panel.to_dict() for panel in build_fixture_snapshots()}
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        panels = {host_id: panel_map[host_id], target_id: panel_map[target_id]}
        confirmed = dict(rel)
        confirmed["verification"] = {
            "level": "manual_confirmed",
            "safeForPreview": True,
            "safeForCut": True,
            "requiresManualConfirmation": False,
        }
        plan = dispatch_hardware_cut_plan(
            confirmed, rule={"type": HARDWARE_TYPE_LOCK_CUTOUT}, panel_snapshots=panels
        )
        self.assertTrue(plan.get("ok"), plan.get("errors"))
        self.assertEqual(plan.get("hardwareType"), HARDWARE_TYPE_LOCK_CUTOUT)
        self.assertTrue(plan.get("feature"))
        self.assertEqual((plan.get("metadata") or {}).get("operationType"), "LOCK_CUTOUT_FROM_RELATIONSHIP")
        pocket = ((plan.get("feature") or {}).get("geometry") or {}).get("pocket") or {}
        self.assertGreater(float(pocket.get("depthMm") or 0), 0)
        feature = plan.get("feature") or {}
        record = build_lock_cutout_panel_feature_record(
            feature,
            cut_metadata=plan.get("metadata") or {},
            cut_feature_name="HW_REL_LOCK_1",
        )
        self.assertEqual(record.get("kind"), "pocket")
        self.assertEqual(record.get("cutType"), "POCKET")
        self.assertFalse(record.get("isCircle"))
        self.assertEqual(record.get("hardwareType"), "lock_cutout")
        self.assertEqual(record.get("hostRole"), "lock_pocket")
        self.assertGreater(float(record.get("widthMm") or 0), 0)
        self.assertGreater(float(record.get("heightMm") or 0), 0)
        self.assertGreater(float(record.get("depthMm") or 0), 0)
        self.assertIn("sketch", record)

    def test_drawer_runner_hole_cut_plan_after_confirm(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        panel_map = {panel.panelId: panel.to_dict() for panel in build_fixture_snapshots()}
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        panels = {host_id: panel_map[host_id], target_id: panel_map[target_id]}
        confirmed = dict(rel)
        confirmed["verification"] = {
            "level": "manual_confirmed",
            "safeForPreview": True,
            "safeForCut": True,
            "requiresManualConfirmation": False,
        }
        plan = dispatch_hardware_cut_plan(
            confirmed, rule={"type": HARDWARE_TYPE_DRAWER_RUNNER_HOLE}, panel_snapshots=panels
        )
        self.assertTrue(plan.get("ok"), plan.get("errors"))
        self.assertEqual(plan.get("hardwareType"), HARDWARE_TYPE_DRAWER_RUNNER_HOLE)
        self.assertTrue(plan.get("feature"))
        self.assertEqual((plan.get("metadata") or {}).get("operationType"), "DRAWER_RUNNER_HOLE_FROM_RELATIONSHIP")

    def test_screw_hole_preview_dispatch_fixture(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        panel_map = {panel.panelId: panel.to_dict() for panel in build_fixture_snapshots()}
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        report = dispatch_hardware_preview(
            rel,
            rule={"type": HARDWARE_TYPE_SCREW_HOLE},
            panel_snapshots={host_id: panel_map[host_id], target_id: panel_map[target_id]},
        )
        self.assertEqual(report.get("hardwareType"), HARDWARE_TYPE_SCREW_HOLE)
        self.assertTrue(report.get("ok"))
        self.assertGreaterEqual(int(report.get("holeCount") or 0), 1)

    def test_tongue_groove_preview_dispatch_fixture(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        panel_map = {panel.panelId: panel.to_dict() for panel in build_fixture_snapshots()}
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        report = dispatch_hardware_preview(
            rel,
            rule={"type": HARDWARE_TYPE_TONGUE_GROOVE},
            panel_snapshots={host_id: panel_map[host_id], target_id: panel_map[target_id]},
        )
        self.assertTrue(report.get("ok"), report.get("errors"))
        self.assertEqual(report.get("hardwareType"), HARDWARE_TYPE_TONGUE_GROOVE)
        self.assertFalse(report.get("previewOnly"))
        self.assertTrue(report.get("cutReady"))
        self.assertEqual(int(report.get("featureCount") or 0), 1)
        feature = (report.get("features") or [{}])[0]
        self.assertEqual(feature.get("hostRole"), "groove")
        self.assertEqual(feature.get("targetRole"), "tongue")
        self.assertEqual(feature.get("geometry", {}).get("groove", {}).get("panelId"), host_id)
        self.assertIn("sketch", feature.get("geometry", {}).get("groove", {}))
        tongue = feature.get("geometry", {}).get("tongue", {})
        self.assertFalse(tongue.get("cutDeferred"))
        self.assertGreaterEqual(len((tongue.get("sketch") or {}).get("shoulders") or []), 1)

    def test_tongue_groove_cut_requires_verification(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        gate = evaluate_hardware_rule(HARDWARE_TYPE_TONGUE_GROOVE, rel, action="cut")
        self.assertFalse(gate.get("ok"))
        blocked = dispatch_hardware_cut_plan(rel, rule={"type": HARDWARE_TYPE_TONGUE_GROOVE})
        self.assertFalse(blocked.get("ok"))

    def test_tongue_groove_cut_plan_after_confirm(self):
        scan = _fixture_scan()
        rel = confirm_relationship_for_cut(find_first_screw_eligible(scan.get("relationships") or []))
        panel_map = {panel.panelId: panel.to_dict() for panel in build_fixture_snapshots()}
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        plan = plan_tongue_groove_cut_from_relationship(
            rel,
            rule={"type": HARDWARE_TYPE_TONGUE_GROOVE},
            panel_snapshots={host_id: panel_map[host_id], target_id: panel_map[target_id]},
        )
        self.assertTrue(plan.get("ok"), plan.get("errors"))
        self.assertFalse((plan.get("metadata") or {}).get("tongueCutDeferred"))
        self.assertGreaterEqual(int((plan.get("metadata") or {}).get("tongueShoulderCount") or 0), 1)
        groove_record = build_tongue_groove_panel_feature_record(
            plan.get("feature") or {},
            cut_metadata=plan.get("metadata") or {},
            cut_feature_name="HW_TG_GROOVE",
            role="groove",
        )
        tongue_record = build_tongue_groove_panel_feature_record(
            plan.get("feature") or {},
            cut_metadata=plan.get("metadata") or {},
            cut_feature_name="HW_TG_TONGUE",
            role="tongue",
        )
        self.assertEqual(groove_record.get("kind"), "groove")
        self.assertEqual(tongue_record.get("kind"), "tongue")
        self.assertFalse(groove_record.get("tongueCutDeferred"))
        meta = build_tg_cut_metadata(
            plan["feature"],
            relationship_id=plan["relationshipId"],
            host_panel_id=host_id,
            target_panel_id=target_id,
        )
        self.assertEqual(meta.get("operationType"), "TONGUE_GROOVE_FROM_RELATIONSHIP")
        self.assertFalse(meta.get("tongueCutDeferred"))

    def test_screw_hole_cut_plan_requires_verification(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        blocked = dispatch_hardware_cut_plan(rel, rule={"type": HARDWARE_TYPE_SCREW_HOLE})
        self.assertFalse(blocked.get("ok"))


if __name__ == "__main__":
    unittest.main()
