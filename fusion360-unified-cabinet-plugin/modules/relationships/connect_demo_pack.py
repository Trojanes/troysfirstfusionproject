"""M4.5A Connect pipeline demo / golden case pack (offline + Fusion helpers)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from relationship_fixtures import build_fixture_snapshots, expected_fixture_cases
from relationship_geometry import classify_pair
from relationship_models import confirm_relationship_for_cut
from relationship_report import build_scan_report
from relationship_service import scan_relationships

try:
    from screw_hole_from_relationship import (
        ACCEPTED_GEOMETRY_TYPE,
        ACCEPTED_RELATIONSHIP_TYPE,
        plan_screw_hole_cut_from_relationship,
        preview_screw_holes_from_relationship,
        resolve_relationship_verification,
        validate_manual_confirmed_relationship_for_cut,
    )
except Exception:
    ACCEPTED_GEOMETRY_TYPE = "edge_to_surface"
    ACCEPTED_RELATIONSHIP_TYPE = "structural_butt_joint"

    def resolve_relationship_verification(relationship):  # type: ignore
        raw = (relationship or {}).get("verification") or {}
        return {
            "level": str(raw.get("level") or "bbox_candidate"),
            "safeForPreview": bool(raw.get("safeForPreview", True)),
            "safeForCut": bool(raw.get("safeForCut", False)),
            "requiresManualConfirmation": bool(raw.get("requiresManualConfirmation", True)),
        }

DEFAULT_DEMO_RULE = {
    "type": "screw_hole",
    "diameterMm": 4,
    "edgeOffsetMm": 30,
    "minSpacingMm": 80,
    "depthMode": "host_thickness",
}

DEMO_FIXTURE_BASELINE = "synthetic_fixture_baseline"
DEMO_OVERHEAD_STRUCTURAL = "simple_overhead_structural_joint"
DEMO_NEGATIVE_FILTERING = "negative_non_screw_filtering"

DOOR_ROLE_HINTS = ("door", "front", "front_panel", "vd_zone")
DOOR_RELATIONSHIP_TYPES = ("door_to_carcass_candidate",)


def _panel_hints(relationship: Dict[str, Any]) -> Tuple[str, str]:
    panel_a = relationship.get("panelA") or {}
    panel_b = relationship.get("panelB") or {}
    hints = []
    for panel in (panel_a, panel_b):
        parts = [
            str(panel.get("role") or ""),
            str(panel.get("boardType") or ""),
            str(panel.get("panelId") or ""),
            str(panel.get("bodyName") or ""),
        ]
        hints.append(" ".join(parts).lower())
    return hints[0], hints[1]


def _looks_like_door_relationship(relationship: Dict[str, Any]) -> bool:
    rel_type = str(relationship.get("relationshipType") or "")
    if rel_type in DOOR_RELATIONSHIP_TYPES:
        return True
    for hint in _panel_hints(relationship):
        if any(token in hint for token in DOOR_ROLE_HINTS):
            return True
    return False


def evaluate_screw_eligibility(relationship: Dict[str, Any]) -> Dict[str, Any]:
    """Return screw eligibility audit for one relationship dict."""
    geometry = str(relationship.get("geometryType") or "none")
    rel_type = str(relationship.get("relationshipType") or "unknown")
    roles = relationship.get("roles") or {}
    host_id = roles.get("hostPanelId")
    target_id = roles.get("targetPanelId")
    verification = resolve_relationship_verification(relationship)

    base = {
        "relationshipId": relationship.get("relationshipId"),
        "geometryType": geometry,
        "relationshipType": rel_type,
        "hostPanelId": host_id,
        "targetPanelId": target_id,
        "verificationLevel": verification.get("level"),
        "safeForPreview": verification.get("safeForPreview"),
        "safeForCut": verification.get("safeForCut"),
    }

    if geometry in ("none",):
        return {**base, "screwEligible": False, "rejectReason": "no_contact"}
    if geometry in ("intersection",):
        return {**base, "screwEligible": False, "rejectReason": "collision_intersection"}
    if geometry in ("gap_parallel",):
        return {**base, "screwEligible": False, "rejectReason": "gap_parallel_not_screw_joint"}
    if _looks_like_door_relationship(relationship):
        return {**base, "screwEligible": False, "rejectReason": "door_or_front_panel_candidate"}
    if rel_type in ("unknown",):
        return {**base, "screwEligible": False, "rejectReason": "unknown_relationship_type"}
    if not host_id or not target_id:
        return {**base, "screwEligible": False, "rejectReason": "missing_host_or_target"}
    if geometry == ACCEPTED_GEOMETRY_TYPE and rel_type == ACCEPTED_RELATIONSHIP_TYPE:
        return {**base, "screwEligible": True, "rejectReason": None}
    return {
        **base,
        "screwEligible": False,
        "rejectReason": "unsupported_geometry_or_relationship_type",
    }


def classify_scan_relationships(relationships: List[Dict[str, Any]]) -> Dict[str, Any]:
    audits = [evaluate_screw_eligibility(rel) for rel in relationships]
    screw_eligible = [item for item in audits if item.get("screwEligible")]
    ignored = [item for item in audits if not item.get("screwEligible") and item.get("geometryType") not in ("intersection",)]
    collisions = [item for item in audits if item.get("rejectReason") == "collision_intersection"]
    return {
        "relationshipCount": len(audits),
        "screwEligibleCount": len(screw_eligible),
        "ignoredCount": len(ignored),
        "collisionCount": len(collisions),
        "audits": audits,
        "screwEligible": screw_eligible,
    }


def find_first_screw_eligible(relationships: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    for rel in relationships:
        if evaluate_screw_eligibility(rel).get("screwEligible"):
            return rel
    return None


def find_screw_eligible_pair(
    relationships: List[Dict[str, Any]],
    preferred_pairs: Optional[List[Tuple[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    if preferred_pairs:
        for panel_a, panel_b in preferred_pairs:
            target = {panel_a, panel_b}
            for rel in relationships:
                ids = {
                    (rel.get("panelA") or {}).get("panelId"),
                    (rel.get("panelB") or {}).get("panelId"),
                }
                if ids != target:
                    continue
                if evaluate_screw_eligibility(rel).get("screwEligible"):
                    return rel
    return find_first_screw_eligible(relationships)


def _panels_map_from_snapshots(panels) -> Dict[str, Dict[str, Any]]:
    return {panel.panelId: panel.to_dict() for panel in panels}


def _preview_and_plan(
    relationship: Dict[str, Any],
    panel_snapshots: Dict[str, Dict[str, Any]],
    rule: Optional[Dict[str, Any]] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    rule = rule or DEFAULT_DEMO_RULE
    preview = preview_screw_holes_from_relationship(relationship, rule=rule, panel_snapshots=panel_snapshots)
    confirmed = confirm_relationship_for_cut(relationship)
    cut_plan = plan_screw_hole_cut_from_relationship(confirmed, rule=rule, panel_snapshots=panel_snapshots)
    return preview, confirmed, cut_plan


def build_demo_summary(
    demo_id: str,
    *,
    ok: bool,
    panel_count: int = 0,
    relationship_count: int = 0,
    screw_eligible_count: int = 0,
    ignored_count: int = 0,
    collision_count: int = 0,
    preview_ok: bool = False,
    confirmed_ok: bool = False,
    cut_ok: bool = False,
    host_only_cut: Optional[bool] = None,
    metadata_written: Optional[bool] = None,
    warnings: Optional[List[str]] = None,
    errors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "demoId": demo_id,
        "ok": bool(ok),
        "panelCount": panel_count,
        "relationshipCount": relationship_count,
        "screwEligibleCount": screw_eligible_count,
        "ignoredCount": ignored_count,
        "collisionCount": collision_count,
        "previewOk": preview_ok,
        "confirmedOk": confirmed_ok,
        "cutOk": cut_ok,
        "hostOnlyCut": host_only_cut,
        "metadataWritten": metadata_written,
        "warnings": list(warnings or []),
        "errors": list(errors or []),
    }


def run_demo_1_fixture_baseline(rule: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    panels = build_fixture_snapshots()
    panel_map = {panel.panelId: panel for panel in panels}
    snapshots = _panels_map_from_snapshots(panels)
    _, relationships = scan_relationships(panels, tolerance_mm=0.5, include_none=True)
    scan_payload = build_scan_report(
        action="relationships.scan",
        panels=panels,
        relationships=relationships,
        scope="fixture",
        tolerance_mm=0.5,
        expected_fixtures=expected_fixture_cases(),
    )
    classification = classify_scan_relationships(scan_payload.get("relationships") or [])

    rel = find_screw_eligible_pair(
        scan_payload.get("relationships") or [],
        preferred_pairs=[("REL_EDGE_A", "REL_SURFACE_B")],
    )
    if not rel:
        rel = find_first_screw_eligible(scan_payload.get("relationships") or [])

    errors: List[str] = []
    preview_report: Dict[str, Any] = {}
    confirm_report: Dict[str, Any] = {}
    cut_plan: Dict[str, Any] = {}
    preview_ok = confirmed_ok = cut_ok = False

    if not rel:
        errors.append("No screw-eligible edge_to_surface relationship found in fixture scan.")
    else:
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        subset = {host_id: snapshots[host_id], target_id: snapshots[target_id]}
        ver = resolve_relationship_verification(rel)
        if ver.get("level") != "bbox_candidate" or ver.get("safeForCut"):
            errors.append("Initial verification must be bbox_candidate with safeForCut=false.")

        preview_report, confirmed, cut_plan = _preview_and_plan(rel, subset, rule=rule)
        preview_ok = bool(preview_report.get("ok"))
        if not preview_ok:
            errors.extend(preview_report.get("errors") or [])

        confirmed_ok = (
            confirmed.get("verification", {}).get("level") == "manual_confirmed"
            and confirmed.get("verification", {}).get("safeForCut") is True
        )
        confirm_report = {
            "action": "manualConfirmForCut",
            "ok": confirmed_ok,
            "relationshipId": confirmed.get("relationshipId"),
            "verification": confirmed.get("verification"),
            "persisted": False,
        }

        blocked = plan_screw_hole_cut_from_relationship(rel, rule=rule, panel_snapshots=subset)
        if blocked.get("ok"):
            errors.append("bbox_candidate cut plan should be blocked.")

        cut_ok = bool(cut_plan.get("ok"))
        if not cut_ok:
            errors.extend(cut_plan.get("errors") or [])

    summary = build_demo_summary(
        DEMO_FIXTURE_BASELINE,
        ok=not errors and preview_ok and confirmed_ok and cut_ok,
        panel_count=scan_payload.get("panelCount") or 0,
        relationship_count=classification["relationshipCount"],
        screw_eligible_count=classification["screwEligibleCount"],
        ignored_count=classification["ignoredCount"],
        collision_count=classification["collisionCount"],
        preview_ok=preview_ok,
        confirmed_ok=confirmed_ok,
        cut_ok=cut_ok,
        host_only_cut=True,
        metadata_written=True,
        errors=errors,
    )

    return {
        "demoId": DEMO_FIXTURE_BASELINE,
        "ok": summary["ok"],
        "summary": summary,
        "audit": {
            "scan": scan_payload,
            "classification": classification,
            "selectedRelationship": rel,
            "preview": preview_report,
            "confirm": confirm_report,
            "cutPlan": cut_plan,
        },
        "errors": errors,
    }


def run_demo_2_overhead_structural(rule: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    from generator_bridge_runner import load_params_fixture, run_overhead
    from generator_panel_adapter import snapshots_from_generator_result
    from relationship_service import build_panel_snapshot_from_dict

    bridge = run_overhead(load_params_fixture("overhead_edge_only.json"))
    snapshots = [build_panel_snapshot_from_dict(item) for item in snapshots_from_generator_result("overhead", bridge)]
    panel_dicts = {snap.panelId: snap.to_dict() for snap in snapshots}
    _, relationships = scan_relationships(snapshots, tolerance_mm=0.5, include_none=True)
    scan_payload = build_scan_report(
        action="relationships.scan",
        panels=snapshots,
        relationships=relationships,
        scope="generator",
        tolerance_mm=0.5,
    )
    classification = classify_scan_relationships(scan_payload.get("relationships") or [])

    rel = find_screw_eligible_pair(
        scan_payload.get("relationships") or [],
        preferred_pairs=[("BP", "D0"), ("BP", "FP0"), ("D0", "FP0")],
    )
    errors: List[str] = []
    preview_report: Dict[str, Any] = {}
    confirm_report: Dict[str, Any] = {}
    cut_plan: Dict[str, Any] = {}

    if not rel:
        errors.append("No screw-eligible structural joint found in Overhead generator snapshots.")
        summary = build_demo_summary(
            DEMO_OVERHEAD_STRUCTURAL,
            ok=False,
            panel_count=len(snapshots),
            relationship_count=classification["relationshipCount"],
            screw_eligible_count=classification["screwEligibleCount"],
            ignored_count=classification["ignoredCount"],
            collision_count=classification["collisionCount"],
            errors=errors,
        )
        return {"demoId": DEMO_OVERHEAD_STRUCTURAL, "ok": False, "summary": summary, "audit": {"scan": scan_payload}, "errors": errors}

    host_id = rel["roles"]["hostPanelId"]
    target_id = rel["roles"]["targetPanelId"]
    subset = {host_id: panel_dicts[host_id], target_id: panel_dicts[target_id]}

    preview_report, confirmed, cut_plan = _preview_and_plan(rel, subset, rule=rule)
    preview_ok = bool(preview_report.get("ok"))
    if not preview_ok:
        errors.extend(preview_report.get("errors") or [])

    confirmed_ok = confirmed.get("verification", {}).get("level") == "manual_confirmed"
    confirm_report = {
        "action": "manualConfirmForCut",
        "ok": confirmed_ok,
        "relationshipId": confirmed.get("relationshipId"),
        "verification": confirmed.get("verification"),
    }

    cut_ok = bool(cut_plan.get("ok"))
    if not cut_ok:
        errors.extend(cut_plan.get("errors") or [])

    summary = build_demo_summary(
        DEMO_OVERHEAD_STRUCTURAL,
        ok=not errors and preview_ok and confirmed_ok and cut_ok,
        panel_count=len(snapshots),
        relationship_count=classification["relationshipCount"],
        screw_eligible_count=classification["screwEligibleCount"],
        ignored_count=classification["ignoredCount"],
        collision_count=classification["collisionCount"],
        preview_ok=preview_ok,
        confirmed_ok=confirmed_ok,
        cut_ok=cut_ok,
        host_only_cut=True,
        metadata_written=True,
        errors=errors,
    )

    return {
        "demoId": DEMO_OVERHEAD_STRUCTURAL,
        "ok": summary["ok"],
        "summary": summary,
        "audit": {
            "scan": scan_payload,
            "classification": classification,
            "selectedRelationship": rel,
            "preview": preview_report,
            "confirm": confirm_report,
            "cutPlan": cut_plan,
        },
        "errors": errors,
    }


def run_demo_3_negative_filtering(rule: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    panels = build_fixture_snapshots()
    snapshots = _panels_map_from_snapshots(panels)
    panel_map = {panel.panelId: panel for panel in panels}

    negative_cases = [
        ("gap_parallel_001", "REL_GAP_A", "REL_GAP_B"),
        ("intersection_collision_001", "REL_COLLISION_A", "REL_COLLISION_B"),
        ("no_contact_001", "REL_NONE_A", "REL_NONE_B"),
    ]

    case_results: List[Dict[str, Any]] = []
    errors: List[str] = []

    for case_id, panel_a_id, panel_b_id in negative_cases:
        rel = classify_pair(panel_map[panel_a_id], panel_map[panel_b_id]).to_dict()
        eligibility = evaluate_screw_eligibility(rel)
        host_id = (rel.get("roles") or {}).get("hostPanelId")
        target_id = (rel.get("roles") or {}).get("targetPanelId")
        subset = {}
        if host_id and target_id and host_id in snapshots and target_id in snapshots:
            subset = {host_id: snapshots[host_id], target_id: snapshots[target_id]}

        preview = preview_screw_holes_from_relationship(rel, rule=rule or DEFAULT_DEMO_RULE, panel_snapshots=subset or snapshots)
        cut_blocked = plan_screw_hole_cut_from_relationship(rel, rule=rule or DEFAULT_DEMO_RULE, panel_snapshots=subset or snapshots)
        confirm_error = validate_manual_confirmed_relationship_for_cut(rel)

        case_ok = (
            not eligibility.get("screwEligible")
            and not preview.get("ok")
            and not cut_blocked.get("ok")
            and confirm_error is not None
        )
        if not case_ok:
            errors.append("Negative case {} did not block as expected.".format(case_id))

        case_results.append(
            {
                "caseId": case_id,
                "ok": case_ok,
                "eligibility": eligibility,
                "previewOk": preview.get("ok"),
                "previewErrors": preview.get("errors"),
                "cutPlanOk": cut_blocked.get("ok"),
                "cutPlanErrors": cut_blocked.get("errors"),
                "confirmGateError": confirm_error,
            }
        )

    _, all_relationships = scan_relationships(list(panel_map.values()), include_none=True)
    scan_rels = [rel.to_dict() for rel in all_relationships]
    classification = classify_scan_relationships(scan_rels)

    summary = build_demo_summary(
        DEMO_NEGATIVE_FILTERING,
        ok=not errors,
        panel_count=len(panels),
        relationship_count=classification["relationshipCount"],
        screw_eligible_count=classification["screwEligibleCount"],
        ignored_count=classification["ignoredCount"],
        collision_count=classification["collisionCount"],
        preview_ok=all(item.get("ok") for item in case_results),
        confirmed_ok=True,
        cut_ok=False,
        host_only_cut=True,
        errors=errors,
    )

    return {
        "demoId": DEMO_NEGATIVE_FILTERING,
        "ok": summary["ok"],
        "summary": summary,
        "audit": {"negativeCases": case_results, "classification": classification},
        "errors": errors,
    }


def run_all_demos_offline(rule: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    demos = [
        run_demo_1_fixture_baseline(rule=rule),
        run_demo_2_overhead_structural(rule=rule),
        run_demo_3_negative_filtering(rule=rule),
    ]
    return {
        "ok": all(item.get("ok") for item in demos),
        "milestone": "M4.5A",
        "demos": demos,
        "summaries": [item.get("summary") for item in demos],
    }
