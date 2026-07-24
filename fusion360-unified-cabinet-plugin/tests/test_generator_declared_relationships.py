"""Tests for M6 generator-declared relationships."""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HW_DIR = ROOT / "modules" / "hardware"
REL_DIR = ROOT / "modules" / "relationships"
for path in (HW_DIR, REL_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from generator_bridge_runner import load_params_fixture, run_general_tall, run_kitchen, run_lounge, run_overhead  # noqa: E402
from generator_declared_service import reconcile_generator_declarations  # noqa: E402
from generator_panel_adapter import snapshots_from_generator_result  # noqa: E402
from general_tall_declared_relationships import (  # noqa: E402
    list_general_tall_declarations_for_panel_ids,
)
from kitchen_declared_relationships import (  # noqa: E402
    list_kitchen_declarations_for_panel_ids,
)
from lounge_declared_relationships import (  # noqa: E402
    list_lounge_declarations_for_panel_ids,
)
from overhead_declared_relationships import extract_board_suffix, list_overhead_declarations_for_panel_ids  # noqa: E402
from relationship_service import build_panel_snapshot_from_dict, dedupe_panel_snapshots  # noqa: E402
from screw_hole_from_relationship import (  # noqa: E402
    plan_screw_hole_cut_from_relationship,
    preview_screw_holes_from_relationship,
    validate_relationship_for_cut,
)


class GeneratorDeclaredRelationshipTests(unittest.TestCase):
    def _overhead_snapshots(self):
        bridge = run_overhead(load_params_fixture("overhead_edge_only.json"))
        return [
            build_panel_snapshot_from_dict(item)
            for item in snapshots_from_generator_result("overhead", bridge)
        ]

    def _general_tall_snapshots(self):
        bridge = run_general_tall(load_params_fixture("general_tall_base.json"))
        return [
            build_panel_snapshot_from_dict(item)
            for item in snapshots_from_generator_result("general_tall", bridge)
        ]

    def test_overhead_declarations_match_skeleton_boards(self):
        snapshots = self._overhead_snapshots()
        panel_ids = {snap.panelId for snap in snapshots}
        declarations = list_overhead_declarations_for_panel_ids(panel_ids)
        self.assertGreaterEqual(len(declarations), 4)
        ids = {item["declarationId"] for item in declarations}
        self.assertIn("oh_bp_d0_back_to_divider", ids)

    def test_overhead_declarations_match_prefixed_panel_ids(self):
        panel_ids = {
            "ohc.m6_smoke.BP",
            "ohc.m6_smoke.D0",
            "ohc.m6_smoke.FP0",
            "ohc.m6_smoke.T1",
            "ohc.m6_smoke.T2",
        }
        declarations = list_overhead_declarations_for_panel_ids(panel_ids, preferred_run_token="m6_smoke")
        self.assertGreaterEqual(len(declarations), 3)
        bp_d0 = next(item for item in declarations if item["declarationId"] == "oh_bp_d0_back_to_divider")
        self.assertEqual(bp_d0["panelAId"], "ohc.m6_smoke.BP")
        self.assertEqual(bp_d0["panelBId"], "ohc.m6_smoke.D0")

    def test_reconcile_scopes_to_preferred_run_when_multiple_runs_present(self):
        snapshots = self._overhead_snapshots()
        stale = [
            build_panel_snapshot_from_dict(
                {
                    **snap.to_dict(),
                    "panelId": snap.panelId.replace("ohc.", "ohc.old_run.", 1) if snap.panelId.startswith("ohc.") else f"ohc.old_run.{snap.panelId}",
                }
            )
            for snap in snapshots[:5]
        ]
        mixed = snapshots + stale
        report = reconcile_generator_declarations(
            mixed,
            generator="overhead",
            preferred_run_token="m6_smoke",
        )
        self.assertTrue(report.get("ok"), report.get("errors"))
        self.assertGreaterEqual(report.get("declarationCount", 0), 4)

    def test_overhead_bridge_emits_relationship_declarations(self):
        bridge = run_overhead(load_params_fixture("overhead_edge_only.json"))
        declarations = bridge.get("relationshipDeclarations") or []
        self.assertGreaterEqual(len(declarations), 4)
        ids = {item.get("declarationId") for item in declarations}
        self.assertIn("oh_bp_d0_back_to_divider", ids)

    def test_reconcile_uses_embedded_generator_declarations(self):
        bridge = run_overhead(load_params_fixture("overhead_edge_only.json"))
        snapshots = [
            build_panel_snapshot_from_dict(item)
            for item in snapshots_from_generator_result("overhead", bridge)
        ]
        embedded = bridge.get("relationshipDeclarations") or []
        report = reconcile_generator_declarations(
            snapshots,
            generator="overhead",
            embedded_declarations=embedded,
        )
        self.assertTrue(report.get("ok"), report.get("errors"))
        self.assertGreaterEqual(report.get("geometryOkCount", 0), 4)

    def test_reconcile_overhead_declarations(self):
        snapshots = self._overhead_snapshots()
        report = reconcile_generator_declarations(snapshots, generator="overhead")
        self.assertTrue(report.get("ok"), report.get("errors"))
        self.assertGreaterEqual(report.get("declarationCount", 0), 4)
        self.assertGreaterEqual(report.get("geometryOkCount", 0), 4)
        relationships = report.get("declaredRelationships") or []
        bp_d0 = next(
            rel
            for rel in relationships
            if extract_board_suffix(rel["panelA"]["panelId"]) == "BP"
            and extract_board_suffix(rel["panelB"]["panelId"]) == "D0"
        )
        self.assertEqual(bp_d0["verification"]["level"], "generator_declared")
        self.assertTrue(bp_d0["geometryValidation"]["ok"])
        self.assertTrue(bp_d0["verification"]["safeForCut"])

    def test_declared_bp_d0_supports_preview_and_cut_plan(self):
        snapshots = self._overhead_snapshots()
        report = reconcile_generator_declarations(snapshots, generator="overhead")
        rel = next(
            item["relationship"]
            for item in report.get("reconciled") or []
            if item.get("declarationId") == "oh_bp_d0_back_to_divider"
        )
        panel_map = {snap.panelId: snap.to_dict() for snap in snapshots}
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        panel_snapshots = {host_id: panel_map[host_id], target_id: panel_map[target_id]}
        self.assertIsNone(validate_relationship_for_cut(rel))
        preview = preview_screw_holes_from_relationship(rel, panel_snapshots=panel_snapshots)
        self.assertTrue(preview.get("ok"), preview)
        plan = plan_screw_hole_cut_from_relationship(rel, panel_snapshots=panel_snapshots)
        self.assertTrue(plan.get("ok"), plan)

    def test_design_geometry_reconcile_accepts_bp_d0_when_physical_bbox_overlaps(self):
        snapshots = self._overhead_snapshots()
        panel_map = {snap.panelId: snap for snap in snapshots}
        bp = panel_map["BP"]
        d0 = panel_map["D0"]
        physical_overlap = [
            build_panel_snapshot_from_dict(
                {
                    **bp.to_dict(),
                    "bbox": {"x0": bp.bbox.x0, "x1": bp.bbox.x1, "y0": bp.bbox.y0, "y1": bp.bbox.y1, "z0": 15.0, "z1": 30.0},
                }
            ),
            build_panel_snapshot_from_dict(
                {
                    **d0.to_dict(),
                    "bbox": {"x0": d0.bbox.x0, "x1": d0.bbox.x1, "y0": d0.bbox.y0, "y1": d0.bbox.y1, "z0": 23.0, "z1": d0.bbox.z1},
                }
            ),
        ]
        physical_report = reconcile_generator_declarations(physical_overlap, generator="overhead")
        self.assertFalse(physical_report.get("ok"))
        design_report = reconcile_generator_declarations(snapshots, generator="overhead")
        self.assertTrue(design_report.get("ok"), design_report.get("errors"))
        self.assertGreaterEqual(design_report.get("geometryOkCount", 0), 4)

    def test_general_tall_bridge_emits_relationship_declarations(self):
        bridge = run_general_tall(load_params_fixture("general_tall_base.json"))
        declarations = bridge.get("relationshipDeclarations") or []
        self.assertGreaterEqual(len(declarations), 4)
        ids = {item.get("declarationId") for item in declarations}
        self.assertIn("gt_b1_b3_bottom_rail_to_deck", ids)
        self.assertIn("gt_t1_t3_top_rail_to_deck", ids)

    def test_general_tall_declarations_match_skeleton_boards(self):
        snapshots = self._general_tall_snapshots()
        panel_ids = {snap.panelId for snap in snapshots}
        declarations = list_general_tall_declarations_for_panel_ids(panel_ids)
        self.assertGreaterEqual(len(declarations), 4)
        ids = {item["declarationId"] for item in declarations}
        self.assertIn("gt_b1_b3_bottom_rail_to_deck", ids)

    def test_general_tall_fridge_panel_ids_filter_declarations(self):
        skeleton = {"B1", "B2", "B3", "T1", "T2", "T3", "V1", "V2"}
        base_ids = {
            item["declarationId"]
            for item in list_general_tall_declarations_for_panel_ids(skeleton)
        }
        self.assertIn("gt_b1_b3_bottom_rail_to_deck", base_ids)
        self.assertNotIn("gt_sidepanel_l_v1", base_ids)
        self.assertNotIn("gt_v5_v1", base_ids)

        left = skeleton | {"SidePanel_L", "V5"}
        left_ids = {
            item["declarationId"]
            for item in list_general_tall_declarations_for_panel_ids(left)
        }
        self.assertIn("gt_sidepanel_l_v1", left_ids)
        self.assertIn("gt_v5_v2", left_ids)
        self.assertNotIn("gt_v5_v1", left_ids)
        self.assertNotIn("gt_sidepanel_r_v2", left_ids)

        none = skeleton | {"V5"}
        none_ids = {
            item["declarationId"]
            for item in list_general_tall_declarations_for_panel_ids(none)
        }
        self.assertIn("gt_v5_v1", none_ids)
        self.assertNotIn("gt_v5_v2", none_ids)
        self.assertNotIn("gt_sidepanel_l_v1", none_ids)

    def test_reconcile_general_tall_declarations(self):
        snapshots = self._general_tall_snapshots()
        report = reconcile_generator_declarations(snapshots, generator="general_tall")
        self.assertTrue(report.get("ok"), report.get("errors"))
        self.assertGreaterEqual(report.get("declarationCount", 0), 4)
        self.assertGreaterEqual(report.get("geometryOkCount", 0), 4)
        relationships = report.get("declaredRelationships") or []
        b1_b3 = next(
            rel
            for rel in relationships
            if extract_board_suffix(rel["panelA"]["panelId"]) == "B1"
            and extract_board_suffix(rel["panelB"]["panelId"]) == "B3"
        )
        self.assertEqual(b1_b3["verification"]["level"], "generator_declared")
        self.assertTrue(b1_b3["geometryValidation"]["ok"])
        self.assertTrue(b1_b3["verification"]["safeForCut"])

    def test_declared_gt_b1_b3_supports_preview_and_cut_plan(self):
        snapshots = self._general_tall_snapshots()
        report = reconcile_generator_declarations(snapshots, generator="general_tall")
        rel = next(
            item["relationship"]
            for item in report.get("reconciled") or []
            if item.get("declarationId") == "gt_b1_b3_bottom_rail_to_deck"
        )
        panel_map = {snap.panelId: snap.to_dict() for snap in snapshots}
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        panel_snapshots = {host_id: panel_map[host_id], target_id: panel_map[target_id]}
        self.assertIsNone(validate_relationship_for_cut(rel))
        preview = preview_screw_holes_from_relationship(rel, panel_snapshots=panel_snapshots)
        self.assertTrue(preview.get("ok"), preview)
        plan = plan_screw_hole_cut_from_relationship(rel, panel_snapshots=panel_snapshots)
        self.assertTrue(plan.get("ok"), plan)

    def _kitchen_snapshots(self):
        bridge = run_kitchen(load_params_fixture("kitchen_base.json"))
        return [
            build_panel_snapshot_from_dict(item)
            for item in snapshots_from_generator_result("kitchen", bridge)
        ]

    def test_kitchen_bridge_emits_relationship_declarations(self):
        bridge = run_kitchen(load_params_fixture("kitchen_base.json"))
        declarations = bridge.get("relationshipDeclarations") or []
        self.assertGreaterEqual(len(declarations), 2)
        ids = {item.get("declarationId") for item in declarations}
        self.assertIn("kt_b1_b3_bottom_rail_to_deck", ids)
        self.assertIn("kt_b2_b3_carcass_rail_to_deck", ids)

    def test_kitchen_declarations_match_skeleton_boards(self):
        snapshots = self._kitchen_snapshots()
        panel_ids = {snap.panelId for snap in snapshots}
        declarations = list_kitchen_declarations_for_panel_ids(panel_ids)
        self.assertGreaterEqual(len(declarations), 2)
        ids = {item["declarationId"] for item in declarations}
        self.assertIn("kt_b1_b3_bottom_rail_to_deck", ids)

    def test_reconcile_kitchen_declarations(self):
        snapshots = self._kitchen_snapshots()
        report = reconcile_generator_declarations(snapshots, generator="kitchen")
        self.assertTrue(report.get("ok"), report.get("errors"))
        self.assertGreaterEqual(report.get("declarationCount", 0), 2)
        self.assertGreaterEqual(report.get("geometryOkCount", 0), 2)
        relationships = report.get("declaredRelationships") or []
        b1_b3 = next(
            rel
            for rel in relationships
            if extract_board_suffix(rel["panelA"]["panelId"]) == "B1"
            and extract_board_suffix(rel["panelB"]["panelId"]) == "B3"
        )
        self.assertEqual(b1_b3["verification"]["level"], "generator_declared")
        self.assertTrue(b1_b3["geometryValidation"]["ok"])
        self.assertTrue(b1_b3["verification"]["safeForCut"])

    def test_declared_kt_b1_b3_supports_preview_and_cut_plan(self):
        snapshots = self._kitchen_snapshots()
        report = reconcile_generator_declarations(snapshots, generator="kitchen")
        rel = next(
            item["relationship"]
            for item in report.get("reconciled") or []
            if item.get("declarationId") == "kt_b1_b3_bottom_rail_to_deck"
        )
        panel_map = {snap.panelId: snap.to_dict() for snap in snapshots}
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        panel_snapshots = {host_id: panel_map[host_id], target_id: panel_map[target_id]}
        self.assertIsNone(validate_relationship_for_cut(rel))
        preview = preview_screw_holes_from_relationship(rel, panel_snapshots=panel_snapshots)
        self.assertTrue(preview.get("ok"), preview)
        plan = plan_screw_hole_cut_from_relationship(rel, panel_snapshots=panel_snapshots)
        self.assertTrue(plan.get("ok"), plan)

    def _lounge_snapshots(self):
        bridge = run_lounge(load_params_fixture("lounge_l_shape.json"))
        return [
            build_panel_snapshot_from_dict(item)
            for item in snapshots_from_generator_result("lounge", bridge)
        ]

    def test_lounge_bridge_emits_relationship_declarations(self):
        bridge = run_lounge(load_params_fixture("lounge_l_shape.json"))
        declarations = bridge.get("relationshipDeclarations") or []
        self.assertGreaterEqual(len(declarations), 3)
        ids = {item.get("declarationId") for item in declarations}
        self.assertIn("lg_main_front_to_top", ids)
        self.assertIn("lg_l_front_to_side", ids)
        self.assertIn("lg_l_front_to_top", ids)

    def test_lounge_declarations_match_skeleton_panels(self):
        snapshots = self._lounge_snapshots()
        panel_ids = {snap.panelId for snap in snapshots}
        declarations = list_lounge_declarations_for_panel_ids(panel_ids)
        self.assertGreaterEqual(len(declarations), 3)
        ids = {item["declarationId"] for item in declarations}
        self.assertIn("lg_main_front_to_top", ids)

    def test_reconcile_lounge_declarations(self):
        snapshots = self._lounge_snapshots()
        report = reconcile_generator_declarations(snapshots, generator="lounge")
        self.assertTrue(report.get("ok"), report.get("errors"))
        self.assertGreaterEqual(report.get("declarationCount", 0), 3)
        self.assertGreaterEqual(report.get("geometryOkCount", 0), 3)
        relationships = report.get("declaredRelationships") or []
        front_top = next(
            rel
            for rel in relationships
            if extract_board_suffix(rel["panelA"]["panelId"]) == "main_front"
            and extract_board_suffix(rel["panelB"]["panelId"]) == "main_top"
        )
        self.assertEqual(front_top["verification"]["level"], "generator_declared")
        self.assertTrue(front_top["geometryValidation"]["ok"])
        self.assertTrue(front_top["verification"]["safeForCut"])

    def test_declared_lg_main_front_to_top_supports_preview_and_cut_plan(self):
        snapshots = self._lounge_snapshots()
        report = reconcile_generator_declarations(snapshots, generator="lounge")
        rel = next(
            item["relationship"]
            for item in report.get("reconciled") or []
            if item.get("declarationId") == "lg_main_front_to_top"
        )
        panel_map = {snap.panelId: snap.to_dict() for snap in snapshots}
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        panel_snapshots = {host_id: panel_map[host_id], target_id: panel_map[target_id]}
        self.assertIsNone(validate_relationship_for_cut(rel))
        preview = preview_screw_holes_from_relationship(rel, panel_snapshots=panel_snapshots)
        self.assertTrue(preview.get("ok"), preview)
        plan = plan_screw_hole_cut_from_relationship(rel, panel_snapshots=panel_snapshots)
        self.assertTrue(plan.get("ok"), plan)


if __name__ == "__main__":
    unittest.main()
