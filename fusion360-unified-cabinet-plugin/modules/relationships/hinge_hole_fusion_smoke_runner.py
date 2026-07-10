"""Fusion smoke runner — hinge cup host-only cut + writeback."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from connect_smoke_runner import (
    PANEL_EDGE,
    PANEL_SURFACE,
    cut_feature_exists,
    find_body_by_panel_id,
    format_summary,
    safe_volume,
)

HINGE_RULE = {
    "type": "hinge_hole",
    "diameterMm": 35,
    "depthMm": 13,
    "edgeOffsetMm": 100,
    "holeCount": 2,
}


def run_hinge_hole_fusion_smoke(
    plugin_dir: str,
    fusion,
    rel_ctrl,
    hw_ctrl,
    *,
    write_json: bool = True,
) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []

    def record(step: str, ok: bool, data: Dict[str, Any]) -> bool:
        steps.append({"step": step, "status": "PASS" if ok else "FAIL", "data": data})
        return ok

    def build_result(overall: bool, **extra) -> Dict[str, Any]:
        payload = {
            "ok": overall,
            "overall": "PASS" if overall else "FAIL",
            "smoke": "hinge_hole_connect",
            "action": "hardware.runHingeHoleSmoke",
            "pluginDir": plugin_dir,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "steps": steps,
        }
        payload.update(extra)
        if write_json:
            out_dir = os.path.join(plugin_dir, "tests", "output")
            try:
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, "hinge_hole_connect_smoke_results.json")
                with open(out_path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, ensure_ascii=False)
                payload["resultsPath"] = out_path
            except Exception:
                payload["resultsPath"] = "(write failed)"
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
        "errors": fixture_payload.get("errors"),
        "cleanup": ((fixture_payload.get("fixtureOrigin") or {}).get("cleanup")
                    if isinstance(fixture_payload, dict) else None),
        "warnings": fixture_payload.get("warnings"),
    }):
        return build_result(False)

    _ev, inspect_payload = rel_ctrl.inspect_pair(
        {"panelAId": PANEL_EDGE, "panelBId": PANEL_SURFACE, "toleranceMm": 0.5},
        None,
    )
    relationship = inspect_payload.get("relationship") if isinstance(inspect_payload, dict) else None
    roles = (relationship or {}).get("roles") or {}
    step2_ok = (
        bool(inspect_payload.get("ok"))
        and relationship is not None
        and relationship.get("geometryType") == "edge_to_surface"
        and roles.get("hostPanelId") == PANEL_SURFACE
        and roles.get("targetPanelId") == PANEL_EDGE
    )
    if not record("2 inspect pair", step2_ok, {
        "geometryType": (relationship or {}).get("geometryType"),
        "hostPanelId": roles.get("hostPanelId"),
        "targetPanelId": roles.get("targetPanelId"),
        "errors": inspect_payload.get("errors"),
    }):
        return build_result(False)

    from relationship_service import build_panel_snapshot

    created_rows = fixture_payload.get("created") if isinstance(fixture_payload, dict) else None
    fixture_panels: Dict[str, Dict[str, Any]] = {}
    if isinstance(created_rows, list):
        for row in created_rows:
            if isinstance(row, dict) and row.get("panelId") and isinstance(row.get("bbox"), dict):
                fixture_panels[str(row["panelId"])] = {
                    "panelId": str(row["panelId"]),
                    "bbox": dict(row["bbox"]),
                }

    host_body = find_body_by_panel_id(root, PANEL_SURFACE, fixture_panels.get(PANEL_SURFACE))
    target_body = find_body_by_panel_id(root, PANEL_EDGE, fixture_panels.get(PANEL_EDGE))
    if host_body is None or target_body is None:
        record("2b resolve bodies", False, {
            "hostFound": host_body is not None,
            "targetFound": target_body is not None,
            "fixturePanelIds": sorted(fixture_panels.keys()),
        })
        return build_result(False)
    host_snap = build_panel_snapshot(host_body).to_dict()
    target_snap = build_panel_snapshot(target_body).to_dict()
    if PANEL_SURFACE in fixture_panels:
        host_snap["bbox"] = dict(fixture_panels[PANEL_SURFACE]["bbox"])
    if PANEL_EDGE in fixture_panels:
        target_snap["bbox"] = dict(fixture_panels[PANEL_EDGE]["bbox"])
    panels = {PANEL_SURFACE: host_snap, PANEL_EDGE: target_snap}

    preview_payload = {"relationship": relationship, "rule": dict(HINGE_RULE), "panels": panels}
    _ev, preview_report = hw_ctrl.preview_hinge_holes_from_relationship(preview_payload, None)
    feature = ((preview_report.get("features") or [{}])[0]) if isinstance(preview_report, dict) else {}
    preview_ok = (
        bool(preview_report.get("ok"))
        and feature.get("hostRole") == "hinge_cup"
        and int(preview_report.get("holeCount") or 0) >= 1
        and bool((feature.get("geometry") or {}).get("positions"))
        and preview_report.get("cutReady") is True
    )
    if not record("3 preview hinge cups", preview_ok, {
        "hostRole": feature.get("hostRole"),
        "holeCount": preview_report.get("holeCount"),
        "cutReady": preview_report.get("cutReady"),
        "errors": (preview_report or {}).get("errors"),
    }):
        return build_result(False, preview=preview_report)

    _ev, blocked_gate = rel_ctrl.connect_execute({"action": "cut", "relationship": relationship}, None)
    if not record("4 bbox_candidate cut blocked", blocked_gate.get("ok") is False, {"gate": blocked_gate}):
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
    if not record("5 confirm relationship", confirm_ok, {
        "verificationLevel": confirmed_verification.get("level"),
        "safeForCut": confirmed_verification.get("safeForCut"),
        "errors": confirm_gate.get("errors"),
    }):
        return build_result(False)

    host_volume_before = safe_volume(host_body)
    target_volume_before = safe_volume(target_body)
    cut_payload = {"relationship": confirmed, "rule": dict(HINGE_RULE), "panels": panels}
    _ev, cut_report = hw_ctrl.create_hinge_holes_from_relationship(cut_payload, None)
    host_volume_after = safe_volume(host_body)
    target_volume_after = safe_volume(target_body)
    cut_name = str((cut_report or {}).get("cutFeatureName") or "")
    cut_ok = (
        bool((cut_report or {}).get("ok"))
        and bool(cut_name)
        and cut_feature_exists(root, cut_name)
        and abs(host_volume_after - host_volume_before) > 0.01
        and abs(target_volume_after - target_volume_before) <= 0.01
        and (cut_report or {}).get("targetBodyModified") is False
    )
    if not record("6 host hinge cup cut", cut_ok, {
        "cutFeatureName": cut_name,
        "hostVolumeDelta": host_volume_after - host_volume_before,
        "targetVolumeDelta": target_volume_after - target_volume_before,
        "panelWriteback": (cut_report or {}).get("panelWriteback"),
        "errors": (cut_report or {}).get("errors"),
    }):
        return build_result(False, cutAudit=cut_report)

    writeback_ok = (
        (cut_report or {}).get("panelWriteback") is True
        or (cut_report or {}).get("panelWritebackSkipped") is True
    )
    if not record("7 panel writeback host", writeback_ok, {
        "panelWriteback": (cut_report or {}).get("panelWriteback"),
        "panelFeatureCount": (cut_report or {}).get("panelFeatureCount"),
        "writeback": (cut_report or {}).get("writeback"),
    }):
        return build_result(False, cutAudit=cut_report)

    return build_result(True, cutAudit=cut_report)
