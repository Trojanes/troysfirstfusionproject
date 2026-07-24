import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
HW_DIR = ROOT / "modules" / "hardware"
for path in (ROOT, REL_DIR, HW_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from connect_formal_ui import (  # noqa: E402
    apply_manual_confirm,
    build_connect_view_model,
    evaluate_connect_action,
    filter_relationships,
    format_relationship_row,
    is_cut_allowed,
    is_preview_allowed,
    match_declared_relationship_for_pair,
    preferred_verify_step,
)
from connect_demo_pack import find_first_screw_eligible  # noqa: E402
from relationship_fixtures import build_fixture_snapshots, expected_fixture_cases  # noqa: E402
from relationship_report import build_scan_report  # noqa: E402
from relationship_service import scan_relationships  # noqa: E402


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


class ConnectFormalUiTests(unittest.TestCase):
    def test_format_relationship_row_includes_verification_ui(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        self.assertIsNotNone(rel)
        row = format_relationship_row(rel)
        self.assertEqual(row["geometryType"], "edge_to_surface")
        self.assertEqual(row["verificationLevel"], "bbox_candidate")
        self.assertEqual(row["verificationLabel"], "BBox candidate")
        self.assertEqual(row["verificationTone"], "warn")
        self.assertFalse(row["safeForCut"])
        self.assertTrue(row["safeForPreview"])

    def test_filter_relationships_by_geometry_and_cut_safe(self):
        scan = _fixture_scan()
        relationships = scan.get("relationships") or []
        edge_only = filter_relationships(relationships, geometry_type="edge_to_surface")
        self.assertGreater(len(edge_only), 0)
        self.assertTrue(all(item.get("geometryType") == "edge_to_surface" for item in edge_only))

        cut_safe = filter_relationships(relationships, cut_safe_only=True)
        self.assertEqual(len(cut_safe), 0)

    def test_build_connect_view_model_rows_and_actions(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        view = build_connect_view_model(
            scan,
            filters={"geometryType": "edge_to_surface"},
            selected_relationship_id=rel.get("relationshipId"),
        )
        self.assertTrue(view["ok"])
        self.assertGreater(view["relationshipCount"], 0)
        self.assertGreater(view["filteredCount"], 0)
        self.assertEqual(view["selectedRelationshipId"], rel.get("relationshipId"))
        self.assertTrue(view["actions"]["preview"]["ok"])
        self.assertTrue(view["actions"]["confirm"]["ok"])
        self.assertFalse(view["actions"]["cut"]["ok"])

    def test_bbox_candidate_cut_blocked_preview_and_confirm_allowed(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        self.assertTrue(is_preview_allowed(rel))
        self.assertFalse(is_cut_allowed(rel))

        preview_gate = evaluate_connect_action("preview", rel)
        confirm_gate = evaluate_connect_action("confirm", rel)
        cut_gate = evaluate_connect_action("cut", rel)

        self.assertTrue(preview_gate["ok"])
        self.assertTrue(confirm_gate["ok"])
        self.assertFalse(cut_gate["ok"])
        self.assertIn("BBox candidates cannot be cut directly", " ".join(cut_gate.get("errors") or []))

    def test_manual_confirm_enables_cut_gate(self):
        scan = _fixture_scan()
        rel = find_first_screw_eligible(scan.get("relationships") or [])
        confirm_gate = evaluate_connect_action("confirm", rel)
        confirmed = confirm_gate.get("confirmedRelationship") or apply_manual_confirm(rel)
        self.assertEqual(confirmed["verification"]["level"], "manual_confirmed")
        self.assertTrue(confirmed["verification"]["safeForCut"])

        cut_gate = evaluate_connect_action("cut", confirmed)
        self.assertTrue(cut_gate["ok"])

    def test_surface_to_surface_confirm_allowed_when_roles_present(self):
        scan = _fixture_scan()
        rel = next(
            item
            for item in scan.get("relationships") or []
            if item.get("geometryType") == "surface_to_surface"
        )
        self.assertTrue(is_preview_allowed(rel))
        roles = rel.get("roles") or {}
        self.assertTrue(roles.get("hostPanelId"))
        self.assertTrue(roles.get("targetPanelId"))
        self.assertTrue(evaluate_connect_action("preview", rel)["ok"])
        self.assertTrue(evaluate_connect_action("confirm", rel)["ok"])
        self.assertFalse(evaluate_connect_action("cut", rel)["ok"])

    def test_merge_declared_relationships_overlays_verification(self):
        from connect_formal_ui import merge_declared_relationships_into_scan
        from generator_bridge_runner import load_params_fixture, run_overhead
        from generator_declared_service import reconcile_generator_declarations
        from generator_panel_adapter import snapshots_from_generator_result
        from relationship_service import build_panel_snapshot_from_dict

        snapshots = [
            build_panel_snapshot_from_dict(item)
            for item in snapshots_from_generator_result("overhead", run_overhead(load_params_fixture("overhead_edge_only.json")))
        ]
        reconcile = reconcile_generator_declarations(snapshots, generator="overhead")
        declared = next(item["relationship"] for item in reconcile.get("reconciled") or [] if item.get("declarationId") == "oh_bp_d0_back_to_divider")
        scan = {
            "ok": True,
            "panels": [s.to_dict() for s in snapshots],
            "relationships": reconcile.get("declaredRelationships") or [],
        }
        bbox_only = dict(declared)
        bbox_only["verification"] = {
            "level": "bbox_candidate",
            "safeForPreview": True,
            "safeForCut": False,
            "requiresManualConfirmation": True,
        }
        scan["relationships"] = [bbox_only]
        merged = merge_declared_relationships_into_scan(scan, reconcile.get("declaredRelationships"))
        rel = next(
            item
            for item in merged.get("relationships") or []
            if item.get("relationshipId") == declared.get("relationshipId")
        )
        self.assertEqual(rel.get("verification", {}).get("level"), "generator_declared")
        view = build_connect_view_model(
            merged,
            filters={"geometryType": "edge_to_surface"},
            selected_relationship_id=declared.get("relationshipId"),
        )
        self.assertTrue(view["actions"]["cut"]["ok"])

    def test_preferred_verify_step_and_declared_pair_match(self):
        from generator_bridge_runner import load_params_fixture, run_overhead
        from generator_declared_service import reconcile_generator_declarations
        from generator_panel_adapter import snapshots_from_generator_result
        from relationship_service import build_panel_snapshot_from_dict

        scan = _fixture_scan()
        bbox = find_first_screw_eligible(scan.get("relationships") or [])
        self.assertEqual(preferred_verify_step(bbox), "face_verify")
        confirmed = apply_manual_confirm(bbox)
        self.assertEqual(preferred_verify_step(confirmed), "cut_ready")

        snapshots = [
            build_panel_snapshot_from_dict(item)
            for item in snapshots_from_generator_result(
                "overhead", run_overhead(load_params_fixture("overhead_edge_only.json"))
            )
        ]
        reconcile = reconcile_generator_declarations(snapshots, generator="overhead")
        declared = reconcile.get("declaredRelationships") or []
        bp_d0 = next(
            item
            for item in declared
            if {(item.get("panelA") or {}).get("panelId"), (item.get("panelB") or {}).get("panelId")} == {"BP", "D0"}
        )
        panel_a = (bp_d0.get("panelA") or {}).get("panelId")
        panel_b = (bp_d0.get("panelB") or {}).get("panelId")
        match = match_declared_relationship_for_pair(declared, [panel_a, panel_b])
        self.assertIsNotNone(match)
        self.assertEqual(match.get("verification", {}).get("level"), "generator_declared")
        self.assertEqual(preferred_verify_step(match), "cut_ready")
        self.assertIsNone(match_declared_relationship_for_pair(declared, ["NOPE_A", "NOPE_B"]))


if __name__ == "__main__":
    unittest.main()
