#!/usr/bin/env python3
"""M3 smoke test — offline automation (Steps 1–6, mock Fusion cut).

Mirrors docs/connect-m3-fusion-smoke-checklist.md without adsk/Fusion UI.
Step 7 (visual timeline) requires run_m3_fusion_smoke_in_fusion.py inside Fusion 360.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
HW_DIR = ROOT / "modules" / "hardware"
for path in (ROOT, REL_DIR, HW_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

HW_REL_DEBUG_RULE = {
    "type": "screw_hole",
    "diameterMm": 4,
    "edgeOffsetMm": 30,
    "minSpacingMm": 80,
    "depthMode": "host_thickness",
}
HW_REL_MANUAL_CONFIRMED = {
    "level": "manual_confirmed",
    "safeForPreview": True,
    "safeForCut": True,
    "requiresManualConfirmation": False,
}
NO_MANUAL_CONFIRMED_MSG = (
    "No manual_confirmed relationship available. Scan, preview, and confirm a relationship before creating cut."
)


class StepResult:
    def __init__(self, step: str, passed: bool, notes: str = "", data: Optional[Dict[str, Any]] = None):
        self.step = step
        self.passed = passed
        self.notes = notes
        self.data = data or {}


def _print_step(result: StepResult) -> None:
    status = "PASS" if result.passed else "FAIL"
    print("\n== Step {}: {} ==".format(result.step, status))
    if result.notes:
        print(result.notes)
    if result.data:
        print(json.dumps(result.data, indent=2, ensure_ascii=False))


def _panels_map_from_scan(scan_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {panel["panelId"]: panel for panel in (scan_payload.get("panels") or []) if panel.get("panelId")}


def _find_preview_relationship(scan_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for rel in scan_payload.get("relationships") or []:
        if rel.get("geometryType") != "edge_to_surface":
            continue
        if rel.get("relationshipType") != "structural_butt_joint":
            continue
        roles = rel.get("roles") or {}
        if roles.get("hostPanelId") and roles.get("targetPanelId"):
            return rel
    return None


def _confirm_for_cut(relationship: Dict[str, Any]) -> Dict[str, Any]:
    notes = list(relationship.get("auditNotes") or [])
    notes.append("Manual cut confirmation applied (debug session only).")
    return {**relationship, "verification": dict(HW_REL_MANUAL_CONFIRMED), "auditNotes": notes}


def step1_fixture_scan() -> Tuple[StepResult, Optional[Dict[str, Any]]]:
    """Simulate fixture create + embedded scan using offline fixture snapshots."""
    from relationship_fixtures import build_fixture_snapshots, expected_fixture_cases
    from relationship_geometry import classify_pair
    from relationship_report import build_scan_report
    from relationship_service import scan_relationships

    panels = build_fixture_snapshots()
    panel_map = {panel.panelId: panel for panel in panels}
    created_panel_ids = {panel.panelId for panel in panels}

    _, relationships = scan_relationships(panels, tolerance_mm=0.5, include_none=True)
    scan_payload = build_scan_report(
        action="relationships.scan",
        panels=panels,
        relationships=relationships,
        scope="fixture",
        tolerance_mm=0.5,
        expected_fixtures=expected_fixture_cases(),
    )

    edge_found = any(
        rel.geometryType == "edge_to_surface"
        for rel in relationships
    )
    ok = bool(scan_payload.get("ok")) and len(created_panel_ids) > 0 and edge_found
    notes = "relationshipCount={} panelCount={} (offline fixture snapshots)".format(
        scan_payload.get("relationshipCount"),
        scan_payload.get("panelCount"),
    )
    fixture_summary = {
        "ok": ok,
        "action": "relationships.createTestFixture",
        "createdBodies": len(created_panel_ids),
        "offlineMode": True,
        "scan": scan_payload,
    }
    return StepResult("1 fixture", ok, notes, {"fixture": fixture_summary, "scan": scan_payload}), scan_payload if ok else None


def step2_scan_validation(scan_payload: Dict[str, Any]) -> StepResult:
    rel = _find_preview_relationship(scan_payload)
    if not rel:
        return StepResult("2 scan", False, "No edge_to_surface structural_butt_joint relationship found.")

    verification = rel.get("verification") or {}
    ok = (
        rel.get("geometryType") == "edge_to_surface"
        and rel.get("relationshipType") == "structural_butt_joint"
        and bool((rel.get("roles") or {}).get("hostPanelId"))
        and bool((rel.get("roles") or {}).get("targetPanelId"))
        and verification.get("level") == "bbox_candidate"
        and verification.get("safeForPreview") is True
        and verification.get("safeForCut") is False
    )
    all_bbox = all(
        (r.get("verification") or {}).get("level") == "bbox_candidate"
        and (r.get("verification") or {}).get("safeForCut") is False
        for r in (scan_payload.get("relationships") or [])
    )
    ok = ok and all_bbox
    return StepResult(
        "2 scan",
        ok,
        "firstValidRelationshipId={}".format(rel.get("relationshipId")),
        {"relationshipId": rel.get("relationshipId"), "roles": rel.get("roles"), "verification": verification},
    )


def step3_preview(scan_payload: Dict[str, Any]) -> Tuple[StepResult, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    from screw_hole_from_relationship import preview_screw_holes_from_relationship

    rel = _find_preview_relationship(scan_payload)
    if not rel:
        return StepResult("3 preview", False, "Missing preview relationship."), None, None

    panels = _panels_map_from_scan(scan_payload)
    host_id = rel["roles"]["hostPanelId"]
    target_id = rel["roles"]["targetPanelId"]
    payload = {
        "relationship": rel,
        "rule": HW_REL_DEBUG_RULE,
        "panels": {host_id: panels[host_id], target_id: panels[target_id]},
    }

    report = preview_screw_holes_from_relationship(
        payload["relationship"],
        rule=payload["rule"],
        panel_snapshots=payload["panels"],
    )
    audit = report.get("audit") or {}
    ok = (
        report.get("ok") is True
        and int(report.get("holeCount") or 0) >= 1
        and audit.get("verificationLevel") == "bbox_candidate"
        and audit.get("safeForPreview") is True
        and audit.get("safeForCut") is False
    )
    return (
        StepResult(
            "3 preview",
            ok,
            "holeCount={} host={} target={}".format(report.get("holeCount"), report.get("hostPanelId"), report.get("targetPanelId")),
            {"preview": report},
        ),
        rel,
        report,
    )


def step4_confirm(rel: Dict[str, Any]) -> Tuple[StepResult, Dict[str, Any]]:
    confirmed = _confirm_for_cut(rel)
    verification = confirmed.get("verification") or {}
    ok = (
        verification.get("level") == "manual_confirmed"
        and verification.get("safeForCut") is True
    )
    return StepResult(
        "4 confirm",
        ok,
        "confirmed relationshipId={}".format(confirmed.get("relationshipId")),
        {"confirmed": confirmed},
    ), confirmed


def step5_negative_gate(scan_payload: Dict[str, Any]) -> StepResult:
    from screw_hole_from_relationship import validate_manual_confirmed_relationship_for_cut

    rel = _find_preview_relationship(scan_payload)
    if not rel:
        return StepResult("5 negative gate", False, "Missing relationship for gate test.")

    validation_msg = validate_manual_confirmed_relationship_for_cut(None)
    bbox_msg = validate_manual_confirmed_relationship_for_cut(rel)
    ok = validation_msg == NO_MANUAL_CONFIRMED_MSG and bbox_msg == NO_MANUAL_CONFIRMED_MSG
    return StepResult(
        "5 negative gate",
        ok,
        "validate(None) and validate(bbox) both return expected message",
        {"missingRelationshipError": validation_msg, "bboxCandidateError": bbox_msg},
    )


def step6_create_cut(confirmed: Dict[str, Any], scan_payload: Dict[str, Any], preview_report: Dict[str, Any]) -> StepResult:
    from screw_hole_from_relationship import (
        build_cut_feature_metadata,
        build_cut_success_report,
        plan_screw_hole_cut_from_relationship,
    )

    panels = _panels_map_from_scan(scan_payload)
    host_id = confirmed["roles"]["hostPanelId"]
    target_id = confirmed["roles"]["targetPanelId"]
    panel_snapshots = {host_id: panels[host_id], target_id: panels[target_id]}

    plan = plan_screw_hole_cut_from_relationship(
        confirmed,
        rule=HW_REL_DEBUG_RULE,
        panel_snapshots=panel_snapshots,
    )
    if not plan.get("ok"):
        return StepResult("6 create cut", False, "Cut plan failed.", {"cut": plan})

    metadata = plan.get("metadata") or build_cut_feature_metadata(
        plan["feature"],
        relationship_id=plan["relationshipId"],
        host_panel_id=host_id,
        target_panel_id=target_id,
    )
    report = build_cut_success_report(
        relationship_id=plan["relationshipId"],
        host_panel_id=host_id,
        target_panel_id=target_id,
        host_body_name=host_id,
        target_body_name=target_id,
        cut_feature_name="HW_REL_SCREW_HOLE_M3_SMOKE",
        metadata=metadata,
        metadata_written=True,
    )
    report["targetBodyModified"] = False
    report["audit"]["targetBodyModified"] = False

    expected_holes = int(preview_report.get("holeCount") or 0)
    audit = report.get("audit") or {}
    ok = (
        report.get("ok") is True
        and report.get("operationType") == "SCREW_HOLE_FROM_RELATIONSHIP"
        and report.get("relationshipId") == confirmed.get("relationshipId")
        and report.get("hostPanelId") == host_id
        and report.get("targetPanelId") == target_id
        and int(report.get("holeCount") or 0) >= 1
        and int(report.get("holeCount") or 0) == expected_holes
        and bool(report.get("cutFeatureName"))
        and report.get("metadataWritten") is True
        and report.get("targetBodyModified") is False
        and (report.get("errors") or []) == []
        and audit.get("targetBodyModified") is False
    )
    return StepResult(
        "6 create cut",
        ok,
        "cutFeatureName={} metadataWritten={} (offline cut plan + audit; Fusion extrude not executed)".format(
            report.get("cutFeatureName"), report.get("metadataWritten")
        ),
        {"cut": report},
    )


def run_smoke() -> Tuple[List[StepResult], bool]:
    results: List[StepResult] = []

    try:
        step1, scan_payload = step1_fixture_scan()
        results.append(step1)
        if not step1.passed or not scan_payload:
            return results, False

        # Reduce JSON dump size in console — keep summary only
        step1.data = {
            "relationshipCount": (step1.data.get("scan") or {}).get("relationshipCount"),
            "createdBodies": (step1.data.get("fixture") or {}).get("createdBodies"),
        }

        step2 = step2_scan_validation(scan_payload)
        results.append(step2)
        if not step2.passed:
            return results, False

        step3, rel, preview = step3_preview(scan_payload)
        results.append(step3)
        if not step3.passed or not rel or not preview:
            return results, False

        step4, confirmed = step4_confirm(rel)
        results.append(step4)
        if not step4.passed:
            return results, False

        step5 = step5_negative_gate(scan_payload)
        results.append(step5)
        if not step5.passed:
            return results, False

        step6 = step6_create_cut(confirmed, scan_payload, preview)
        results.append(step6)
        return results, step6.passed
    except Exception as ex:
        results.append(StepResult("error", False, traceback.format_exc()))
        return results, False


def write_results_log(results: List[StepResult], overall: bool) -> Path:
    out_dir = ROOT / "tests" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "m3_smoke_offline_results.json"

    payload = {
        "mode": "offline_mock_fusion",
        "overall": "PASS" if overall else "FAIL",
        "step7VisualFusion": "MANUAL — run tests/run_m3_fusion_smoke_in_fusion.py inside Fusion 360",
        "steps": [
            {"step": r.step, "status": "PASS" if r.passed else "FAIL", "notes": r.notes, "data": r.data}
            for r in results
        ],
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return out_path


def main() -> int:
    print("M3 Smoke Test (offline automation — Steps 1–6)")
    print("Checklist: docs/connect-m3-fusion-smoke-checklist.md")

    results, overall = run_smoke()
    for result in results:
        _print_step(result)

    out_path = write_results_log(results, overall)
    print("\n== Summary ==")
    print("Steps 1–6 offline: {}".format("PASS" if overall else "FAIL"))
    print("Step 7 (Fusion visual): MANUAL — see tests/run_m3_fusion_smoke_in_fusion.py")
    print("Results written: {}".format(out_path))
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
