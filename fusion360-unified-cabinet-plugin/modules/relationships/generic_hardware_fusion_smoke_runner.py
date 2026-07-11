"""Fusion smoke — Connect generic createHardwareFromRelationship (lock pocket).

Proves the Connect UI route (not legacy per-type create_* methods) cuts and
writes a rectangular lock pocket feature record.
"""

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

LOCK_RULE = {
    "type": "lock_cutout",
    "widthMm": 22,
    "heightMm": 40,
    "depthMm": 12,
}

PREVIEW_TYPES = (
    "screw_hole",
    "tongue_groove",
    "hinge_hole",
    "lock_cutout",
    "drawer_runner_hole",
)


def run_generic_hardware_fusion_smoke(
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
            "smoke": "generic_hardware_connect",
            "action": "hardware.runGenericHardwareSmoke",
            "pluginDir": plugin_dir,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "steps": steps,
        }
        payload.update(extra)
        if write_json:
            out_dir = os.path.join(plugin_dir, "tests", "output")
            try:
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, "generic_hardware_connect_smoke_results.json")
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
        })
        return build_result(False)
    host_snap = build_panel_snapshot(host_body).to_dict()
    target_snap = build_panel_snapshot(target_body).to_dict()
    if PANEL_SURFACE in fixture_panels:
        host_snap["bbox"] = dict(fixture_panels[PANEL_SURFACE]["bbox"])
    if PANEL_EDGE in fixture_panels:
        target_snap["bbox"] = dict(fixture_panels[PANEL_EDGE]["bbox"])
    panels = {PANEL_SURFACE: host_snap, PANEL_EDGE: target_snap}

    _ev, confirm_gate = rel_ctrl.connect_execute({"action": "confirm", "relationship": relationship}, None)
    confirmed = confirm_gate.get("confirmedRelationship") or confirm_gate.get("relationship")
    confirm_ok = bool(confirm_gate.get("ok")) and confirmed is not None
    if not record("3 confirm relationship", confirm_ok, {
        "verificationLevel": ((confirmed or {}).get("verification") or {}).get("level"),
        "errors": confirm_gate.get("errors"),
    }):
        return build_result(False)

    preview_ok_count = 0
    for hw_type in PREVIEW_TYPES:
        _ev, preview_report = hw_ctrl.preview_hardware_from_relationship(
            {"relationship": confirmed, "rule": {"type": hw_type}, "panels": panels},
            None,
        )
        if bool((preview_report or {}).get("ok")):
            preview_ok_count += 1
    if not record("4 generic preview all 5 types", preview_ok_count == len(PREVIEW_TYPES), {
        "previewOkCount": preview_ok_count,
        "expected": len(PREVIEW_TYPES),
    }):
        return build_result(False)

    host_volume_before = safe_volume(host_body)
    target_volume_before = safe_volume(target_body)
    cut_payload = {"relationship": confirmed, "rule": dict(LOCK_RULE), "panels": panels}
    _ev, cut_report = hw_ctrl.create_hardware_from_relationship(cut_payload, None)
    host_volume_after = safe_volume(host_body)
    target_volume_after = safe_volume(target_body)
    cut_name = str((cut_report or {}).get("cutFeatureName") or "")
    cut_ok = (
        bool((cut_report or {}).get("ok"))
        and (cut_report or {}).get("hardwareType") == "lock_cutout"
        and bool(cut_name)
        and cut_feature_exists(root, cut_name)
        and abs(host_volume_after - host_volume_before) > 0.01
        and abs(target_volume_after - target_volume_before) <= 0.01
        and (cut_report or {}).get("targetBodyModified") is False
    )
    if not record("5 generic createHardware lock cut", cut_ok, {
        "cutFeatureName": cut_name,
        "hardwareType": (cut_report or {}).get("hardwareType"),
        "hostVolumeDelta": host_volume_after - host_volume_before,
        "panelWriteback": (cut_report or {}).get("panelWriteback"),
        "errors": (cut_report or {}).get("errors"),
    }):
        return build_result(False, cutAudit=cut_report)

    writeback_ok = (
        (cut_report or {}).get("panelWriteback") is True
        or (cut_report or {}).get("panelWritebackSkipped") is True
    )
    feature_record = ((cut_report or {}).get("writeback") or {}).get("featureRecord") or {}
    kind_ok = True
    if feature_record:
        kind_ok = feature_record.get("kind") == "pocket" and feature_record.get("isCircle") is False
    if not record("6 lock pocket writeback", writeback_ok and kind_ok, {
        "panelWriteback": (cut_report or {}).get("panelWriteback"),
        "featureKind": feature_record.get("kind"),
        "isCircle": feature_record.get("isCircle"),
        "widthMm": feature_record.get("widthMm"),
        "heightMm": feature_record.get("heightMm"),
    }):
        return build_result(False, cutAudit=cut_report)

    return build_result(True, cutAudit=cut_report)
