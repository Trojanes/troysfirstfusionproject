"""Shared Connect smoke runner for Fusion Scripts (day1/day2)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

PANEL_EDGE = "REL_EDGE_A"
PANEL_SURFACE = "REL_SURFACE_B"
EXPECTED_HOLE_COUNT = 2

HW_RULE = {
    "type": "screw_hole",
    "diameterMm": 4,
    "edgeOffsetMm": 30,
    "minSpacingMm": 80,
    "depthMode": "host_thickness",
}


def cut_feature_exists(root, feature_name: Optional[str]) -> bool:
    if not root or not feature_name:
        return False

    def scan_component(comp) -> bool:
        for index in range(comp.features.count):
            try:
                if comp.features.item(index).name == feature_name:
                    return True
            except Exception:
                continue
        return False

    if scan_component(root):
        return True
    for index in range(root.allOccurrences.count):
        try:
            if scan_component(root.allOccurrences.item(index).component):
                return True
        except Exception:
            continue
    return False


def find_body_by_panel_id(root, panel_id: str, panel_snapshot: Optional[Dict[str, Any]] = None):
    def match(body) -> bool:
        try:
            if str(getattr(body, "name", "")) == panel_id:
                return True
            attrs = getattr(body, "attributes", None)
            if attrs is not None:
                for group, name in (("UnifiedCabinetPlugin", "boardId"), ("UnifiedCabinet.Panel", "panelId")):
                    attr = attrs.itemByName(group, name)
                    if attr is not None and str(getattr(attr, "value", "")) == panel_id:
                        return True
        except Exception:
            pass
        return False

    matches = []
    try:
        for index in range(root.bRepBodies.count):
            body = root.bRepBodies.item(index)
            if match(body):
                matches.append(body)
        for index in range(root.allOccurrences.count):
            comp = root.allOccurrences.item(index).component
            for body_index in range(comp.bRepBodies.count):
                body = comp.bRepBodies.item(body_index)
                if match(body):
                    matches.append(body)
    except Exception:
        pass
    if not matches:
        return None
    if len(matches) == 1 or not isinstance(panel_snapshot, dict):
        return matches[-1]
    expected = panel_snapshot.get("bbox") if isinstance(panel_snapshot.get("bbox"), dict) else None
    if not expected:
        return matches[-1]
    best = matches[-1]
    best_score = None
    for body in matches:
        try:
            bbox = body.boundingBox
            actual = {
                "x0": bbox.minPoint.x * 10.0,
                "x1": bbox.maxPoint.x * 10.0,
                "y0": bbox.minPoint.y * 10.0,
                "y1": bbox.maxPoint.y * 10.0,
                "z0": bbox.minPoint.z * 10.0,
                "z1": bbox.maxPoint.z * 10.0,
            }
            score = sum(abs(float(actual[k]) - float(expected.get(k, 0.0))) for k in actual)
        except Exception:
            continue
        if best_score is None or score < best_score:
            best_score = score
            best = body
    return best


def safe_volume(body) -> float:
    try:
        return float(getattr(body, "volume", 0.0) or 0.0)
    except Exception:
        return 0.0


def write_results(plugin_dir: str, result: Dict[str, Any], *, smoke_id: str = "day1") -> str:
    out_dir = os.path.join(plugin_dir, "tests", "output")
    try:
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, "{}_connect_smoke_results.json".format(smoke_id))
        with open(out_path, "w", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, ensure_ascii=False)
        return out_path
    except Exception:
        return "(write failed)"


def format_summary(result: Dict[str, Any]) -> str:
    smoke_id = str(result.get("smoke") or "day1_connect").replace("_connect", "")
    title = smoke_id.replace("_", " ").title()
    lines = ["{} Connect smoke: {}".format(title, result.get("overall"))]
    for step in result.get("steps") or []:
        lines.append("  [{}] {}".format(step["status"], step["step"]))
    cut_audit = result.get("cutAudit") or {}
    if cut_audit.get("cutFeatureName"):
        hole_count = cut_audit.get("holeCount")
        if hole_count is not None:
            lines.append("Cut: {} · {} holes".format(cut_audit.get("cutFeatureName"), hole_count))
        else:
            lines.append("Cut: {}".format(cut_audit.get("cutFeatureName")))
    if result.get("resultsPath"):
        lines.append("Results: {}".format(result["resultsPath"]))
    return "\n".join(lines)


def run_connect_smoke(
    plugin_dir: str,
    fusion,
    rel_ctrl,
    hw_ctrl,
    *,
    write_json: bool = True,
    include_preview: bool = False,
    smoke_id: str = "day1",
) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []

    def record(step: str, ok: bool, data: Dict[str, Any]) -> bool:
        steps.append({"step": step, "status": "PASS" if ok else "FAIL", "data": data})
        return ok

    def build_result(overall: bool, **extra) -> Dict[str, Any]:
        action = "relationships.runDay2Smoke" if include_preview else "relationships.runDay1Smoke"
        payload = {
            "ok": overall,
            "overall": "PASS" if overall else "FAIL",
            "smoke": "{}_connect".format(smoke_id),
            "action": action,
            "pluginDir": plugin_dir,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "steps": steps,
        }
        payload.update(extra)
        if write_json:
            payload["resultsPath"] = write_results(plugin_dir, payload, smoke_id=smoke_id)
        payload["summaryText"] = format_summary(payload)
        return payload

    root = fusion.get_root_component()
    if not root:
        record("0 active design", False, {"errors": ["No active Fusion design."]})
        return build_result(False, errors=["No active Fusion design."])

    _ev, fixture_payload = rel_ctrl.create_test_fixture({}, None)
    step1_ok = bool(fixture_payload.get("ok")) and int(fixture_payload.get("createdBodies") or 0) >= 10
    if not record("1 create fixture", step1_ok, {
        "createdBodies": fixture_payload.get("createdBodies"),
        "flatMode": fixture_payload.get("flatMode"),
        "errors": fixture_payload.get("errors"),
    }):
        return build_result(False)

    _ev, inspect_payload = rel_ctrl.inspect_pair(
        {"panelAId": PANEL_EDGE, "panelBId": PANEL_SURFACE, "toleranceMm": 0.5},
        None,
    )
    relationship = inspect_payload.get("relationship") if isinstance(inspect_payload, dict) else None
    audit = inspect_payload.get("audit") or {}
    verification = (relationship or {}).get("verification") or {}
    roles = (relationship or {}).get("roles") or {}
    step2_ok = (
        bool(inspect_payload.get("ok"))
        and relationship is not None
        and relationship.get("geometryType") == "edge_to_surface"
        and relationship.get("relationshipType") == "structural_butt_joint"
        and verification.get("level") == "bbox_candidate"
        and verification.get("safeForCut") is False
        and roles.get("hostPanelId") == PANEL_SURFACE
        and roles.get("targetPanelId") == PANEL_EDGE
    )
    if not record("2 inspect pair", step2_ok, {
        "geometryType": (relationship or {}).get("geometryType") or audit.get("geometryType"),
        "relationshipType": (relationship or {}).get("relationshipType"),
        "verificationLevel": verification.get("level"),
        "hostPanelId": roles.get("hostPanelId"),
        "targetPanelId": roles.get("targetPanelId"),
        "errors": inspect_payload.get("errors"),
    }):
        return build_result(False, inspect=inspect_payload)

    from relationship_service import build_panel_snapshot

    host_body = find_body_by_panel_id(root, PANEL_SURFACE)
    target_body = find_body_by_panel_id(root, PANEL_EDGE)
    if host_body is None or target_body is None:
        record("2b resolve bodies", False, {
            "hostFound": host_body is not None,
            "targetFound": target_body is not None,
        })
        return build_result(False)
    host_snap = build_panel_snapshot(host_body).to_dict()
    target_snap = build_panel_snapshot(target_body).to_dict()

    from contact_patch import build_contact_patch_from_relationship

    patch_result = build_contact_patch_from_relationship(relationship, target_snap, host_snap)
    patch = patch_result.get("contactPatch") or {}
    step3_ok = (
        bool(patch_result.get("ok"))
        and float(patch.get("contactAreaMm2") or 0) > 0
        and patch.get("hostPanelId") == PANEL_SURFACE
        and patch.get("targetPanelId") == PANEL_EDGE
    )
    if not record("3 contact patch", step3_ok, {
        "contactAreaMm2": patch.get("contactAreaMm2"),
        "contactAxis": patch.get("contactAxis"),
        "hostPanelId": patch.get("hostPanelId"),
        "targetPanelId": patch.get("targetPanelId"),
        "errors": patch_result.get("errors"),
    }):
        return build_result(False)

    if include_preview:
        _ev, preview_gate = rel_ctrl.connect_execute({"action": "preview", "relationship": relationship}, None)
        preview_gate_ok = preview_gate.get("ok") is True
        if not record("4 preview gate", preview_gate_ok, {"gate": preview_gate}):
            return build_result(False)

        preview_payload = {
            "relationship": relationship,
            "rule": dict(HW_RULE),
            "panels": {PANEL_SURFACE: host_snap, PANEL_EDGE: target_snap},
        }
        _ev, preview_report = hw_ctrl.preview_screw_holes_from_relationship(preview_payload, None)
        preview_audit = preview_report.get("audit") or {}
        preview_ok = (
            bool(preview_report.get("ok"))
            and preview_report.get("holeCount") == EXPECTED_HOLE_COUNT
            and preview_report.get("hostPanelId") == PANEL_SURFACE
            and preview_audit.get("diameterMm") == 4
            and preview_audit.get("edgeOffsetMm") == 30
            and len(preview_audit.get("positions") or []) == EXPECTED_HOLE_COUNT
        )
        if not record("5 preview screw holes", preview_ok, {
            "holeCount": preview_report.get("holeCount"),
            "diameterMm": preview_audit.get("diameterMm"),
            "edgeOffsetMm": preview_audit.get("edgeOffsetMm"),
            "positionCount": len(preview_audit.get("positions") or []),
            "errors": preview_report.get("errors"),
        }):
            return build_result(False, previewAudit=preview_report)

    _ev, blocked_gate = rel_ctrl.connect_execute({"action": "cut", "relationship": relationship}, None)
    cut_block_step = "6 bbox_candidate cut blocked" if include_preview else "4 bbox_candidate cut blocked"
    cut_blocked_ok = blocked_gate.get("ok") is False
    if not record(cut_block_step, cut_blocked_ok, {"gate": blocked_gate}):
        return build_result(False)

    _ev, confirm_gate = rel_ctrl.connect_execute({"action": "confirm", "relationship": relationship}, None)
    confirmed = confirm_gate.get("confirmedRelationship") or confirm_gate.get("relationship")
    confirmed_verification = (confirmed or {}).get("verification") or {}
    confirm_ok = (
        bool(confirm_gate.get("ok"))
        and confirmed is not None
        and confirmed_verification.get("level") == "manual_confirmed"
        and confirmed_verification.get("safeForCut") is True
    )
    confirm_step = "7 confirm relationship" if include_preview else "5 confirm relationship"
    if not record(confirm_step, confirm_ok, {
        "verificationLevel": confirmed_verification.get("level"),
        "safeForCut": confirmed_verification.get("safeForCut"),
        "errors": confirm_gate.get("errors"),
    }):
        return build_result(False)

    target_volume_before = safe_volume(target_body)
    cut_payload = {
        "relationship": confirmed,
        "rule": dict(HW_RULE),
        "panels": {PANEL_SURFACE: host_snap, PANEL_EDGE: target_snap},
    }
    _ev, cut_report = hw_ctrl.create_screw_holes_from_relationship(cut_payload, None)
    target_volume_after = safe_volume(target_body)
    target_untouched = abs(target_volume_after - target_volume_before) <= 0.01
    cut_ok = (
        bool(cut_report.get("ok"))
        and cut_report.get("holeCount") == EXPECTED_HOLE_COUNT
        and cut_report.get("metadataWritten") is True
        and cut_report.get("hostPanelId") == PANEL_SURFACE
        and target_untouched
    )
    cut_step = "8 create screw holes" if include_preview else "6 create screw holes"
    if not record(cut_step, cut_ok, {
        "holeCount": cut_report.get("holeCount"),
        "cutFeatureName": cut_report.get("cutFeatureName"),
        "metadataWritten": cut_report.get("metadataWritten"),
        "panelWriteback": cut_report.get("panelWriteback"),
        "targetUntouched": target_untouched,
        "errors": cut_report.get("errors"),
    }):
        return build_result(False, cutAudit=cut_report)

    cut_name = cut_report.get("cutFeatureName")
    timeline_ok = cut_feature_exists(root, cut_name)
    timeline_step = "9 timeline feature" if include_preview else "7 timeline feature"
    record(timeline_step, timeline_ok, {"cutFeatureName": cut_name, "found": timeline_ok})

    overall = all(item["status"] == "PASS" for item in steps)
    return build_result(overall, cutAudit=cut_report, contactPatch=patch)
