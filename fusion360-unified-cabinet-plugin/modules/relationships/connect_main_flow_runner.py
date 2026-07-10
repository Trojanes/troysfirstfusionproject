"""Batch B — full Connect main flow smoke (fixture + overhead pair)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from connect_smoke_runner import HW_RULE, format_summary, run_connect_smoke, write_results
from overhead_declared_relationships import extract_board_suffix

OVERHEAD_DECLARATION_ID = "oh_bp_d0_back_to_divider"
OVERHEAD_ASSEMBLY = "OHC_CONNECT_MAIN"
OVERHEAD_RUN_LABEL = "connect_main_smoke"


def _load_overhead_params(plugin_dir: str) -> Dict[str, Any]:
    path = os.path.join(plugin_dir, "tests", "fixtures", "generator_params", "overhead_edge_only.json")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _find_bp_d0_relationship(report: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for item in report.get("declaredRelationships") or []:
        if not isinstance(item, dict):
            continue
        rel = item.get("relationship") if isinstance(item.get("relationship"), dict) else item
        panel_a = item.get("panelA") or rel.get("panelA") or {}
        panel_b = item.get("panelB") or rel.get("panelB") or {}
        suffix_a = extract_board_suffix(panel_a.get("panelId") or rel.get("roles", {}).get("targetPanelId"))
        suffix_b = extract_board_suffix(panel_b.get("panelId") or rel.get("roles", {}).get("hostPanelId"))
        if {suffix_a, suffix_b} == {"BP", "D0"}:
            return rel
    for item in report.get("reconciled") or []:
        if item.get("declarationId") == OVERHEAD_DECLARATION_ID:
            rel = item.get("relationship")
            if isinstance(rel, dict):
                return rel
    return None


def _panel_map_from_declared(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Prefer full reconcile panels (with bbox); fall back to panelA/B stubs only if they have bbox."""
    panel_map: Dict[str, Dict[str, Any]] = {}
    for panel in report.get("panels") or []:
        if isinstance(panel, dict) and panel.get("panelId") and isinstance(panel.get("bbox"), dict):
            panel_map[str(panel["panelId"])] = panel
    if panel_map:
        return panel_map
    for item in report.get("declaredRelationships") or []:
        rel = item.get("relationship") if isinstance(item.get("relationship"), dict) else item
        for key in ("panelA", "panelB"):
            panel = item.get(key) or (rel.get(key) if isinstance(rel, dict) else None)
            if isinstance(panel, dict) and panel.get("panelId") and isinstance(panel.get("bbox"), dict):
                panel_map[str(panel["panelId"])] = panel
    return panel_map


def _panel_has_usable_bbox(panel: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(panel, dict):
        return False
    bbox = panel.get("bbox")
    if not isinstance(bbox, dict):
        return False
    try:
        return any(abs(float(bbox.get(key, 0.0))) > 1e-9 for key in ("x0", "x1", "y0", "y1", "z0", "z1"))
    except Exception:
        return False


def run_connect_main_flow_smoke(
    plugin_dir: str,
    fusion,
    rel_ctrl,
    hw_ctrl,
    overhead_ctrl,
    *,
    write_json: bool = True,
) -> Dict[str, Any]:
    fixture_result = run_connect_smoke(
        plugin_dir,
        fusion,
        rel_ctrl,
        hw_ctrl,
        write_json=False,
        include_preview=True,
        smoke_id="main_flow_fixture",
    )
    steps: List[Dict[str, Any]] = list(fixture_result.get("steps") or [])
    extra: Dict[str, Any] = {
        "fixturePhase": fixture_result,
        "cutAudit": fixture_result.get("cutAudit"),
        "contactPatch": fixture_result.get("contactPatch"),
    }
    overall = bool(fixture_result.get("ok"))

    def record(step: str, ok: bool, data: Dict[str, Any]) -> bool:
        steps.append({"step": step, "status": "PASS" if ok else "FAIL", "data": data})
        return ok

    if not overall:
        return _build_result(plugin_dir, steps, overall, write_json=write_json, **extra)

    params = _load_overhead_params(plugin_dir)
    _ev, oh_payload = overhead_ctrl.create_fusion_rough_bodies(
        {
            "params": params,
            "caseName": OVERHEAD_RUN_LABEL,
            "assemblyName": OVERHEAD_ASSEMBLY,
        },
        None,
    )
    assembly_name = oh_payload.get("assemblyComponentName") or OVERHEAD_ASSEMBLY
    oh_ok = (
        bool(oh_payload.get("ok"))
        and int(oh_payload.get("createdBodies") or 0) >= 4
    )
    if not record("10 overhead create bodies", oh_ok, {
        "createdBodies": oh_payload.get("createdBodies"),
        "assemblyComponentName": assembly_name,
        "createdBoardIds": oh_payload.get("createdBoardIds"),
        "errors": oh_payload.get("errors"),
    }):
        extra["overheadCreate"] = oh_payload
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

    assembly_name = oh_payload.get("assemblyComponentName") or OVERHEAD_ASSEMBLY
    run_label = str(oh_payload.get("runLabel") or OVERHEAD_RUN_LABEL)
    reconcile_request = {
        "generator": "overhead",
        "runLabel": run_label,
        "toleranceMm": 0.5,
        "bboxSource": "design_preferred",
        "assemblyComponentName": assembly_name,
    }
    _ev, reconcile_payload = rel_ctrl.reconcile_generator_declarations(reconcile_request, None)
    if not reconcile_payload.get("ok"):
        reconcile_request.pop("assemblyComponentName", None)
        _ev, reconcile_payload = rel_ctrl.reconcile_generator_declarations(reconcile_request, None)
    reconcile_ok = (
        bool(reconcile_payload.get("ok"))
        and int(reconcile_payload.get("geometryOkCount") or 0) >= 1
        and int(reconcile_payload.get("declarationCount") or 0) >= 1
    )
    if not record("11 overhead reconcile declarations", reconcile_ok, {
        "declarationCount": reconcile_payload.get("declarationCount"),
        "geometryOkCount": reconcile_payload.get("geometryOkCount"),
        "panelCount": reconcile_payload.get("panelCount"),
        "runLabel": run_label,
        "assemblyComponentName": assembly_name,
        "errors": reconcile_payload.get("errors"),
    }):
        extra["overheadReconcile"] = reconcile_payload
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

    relationship = _find_bp_d0_relationship(reconcile_payload)
    rel_ok = relationship is not None and relationship.get("verification", {}).get("level") == "generator_declared"
    if not record("12 overhead BP-D0 relationship", rel_ok, {
        "relationshipId": (relationship or {}).get("relationshipId"),
        "verificationLevel": ((relationship or {}).get("verification") or {}).get("level"),
        "hostPanelId": ((relationship or {}).get("roles") or {}).get("hostPanelId"),
        "targetPanelId": ((relationship or {}).get("roles") or {}).get("targetPanelId"),
    }):
        extra["overheadReconcile"] = reconcile_payload
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

    roles = relationship.get("roles") or {}
    host_id = str(roles.get("hostPanelId") or "")
    target_id = str(roles.get("targetPanelId") or "")

    # Prefer panels captured during reconcile (same design_preferred assembly set).
    # Declared panelA/B stubs often omit bbox; using them yields empty X overlap in Fusion.
    panel_map = _panel_map_from_declared(reconcile_payload)
    if not (_panel_has_usable_bbox(panel_map.get(host_id)) and _panel_has_usable_bbox(panel_map.get(target_id))):
        try:
            assembly_panels = rel_ctrl.service.collect_panels_from_assembly(
                assembly_name,
                bbox_source="design_preferred",
            )
            for panel in assembly_panels or []:
                panel_id = str(getattr(panel, "panelId", "") or "")
                if not panel_id:
                    continue
                payload = panel.to_dict() if hasattr(panel, "to_dict") else None
                if isinstance(payload, dict) and _panel_has_usable_bbox(payload):
                    panel_map[panel_id] = payload
        except Exception as ex:
            extra["panelSnapshotError"] = str(ex)

    host_panel = panel_map.get(host_id)
    target_panel = panel_map.get(target_id)
    if not (_panel_has_usable_bbox(host_panel) and _panel_has_usable_bbox(target_panel)):
        preview_report = {
            "ok": False,
            "errors": [
                "Missing usable host/target bboxes for preview (host={}, target={}, known={}).".format(
                    host_id,
                    target_id,
                    sorted(panel_map.keys()),
                )
            ],
        }
        record("13 overhead BP-D0 preview holes", False, {
            "holeCount": None,
            "hostPanelId": host_id,
            "errors": preview_report["errors"],
            "hostBBox": (host_panel or {}).get("bbox") if isinstance(host_panel, dict) else None,
            "targetBBox": (target_panel or {}).get("bbox") if isinstance(target_panel, dict) else None,
            "panelIds": sorted(panel_map.keys()),
        })
        extra["overheadReconcile"] = reconcile_payload
        extra["overheadPreview"] = preview_report
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

    preview_payload = {
        "relationship": relationship,
        "rule": dict(HW_RULE),
        "panels": {host_id: host_panel, target_id: target_panel},
    }
    _ev, preview_report = hw_ctrl.preview_screw_holes_from_relationship(preview_payload, None)
    preview_audit = preview_report.get("audit") or {}
    preview_ok = (
        bool(preview_report.get("ok"))
        and int(preview_report.get("holeCount") or 0) >= 1
        and preview_report.get("hostPanelId") == host_id
    )
    if not record("13 overhead BP-D0 preview holes", preview_ok, {
        "holeCount": preview_report.get("holeCount"),
        "diameterMm": preview_audit.get("diameterMm"),
        "hostPanelId": preview_report.get("hostPanelId"),
        "errors": preview_report.get("errors"),
        "hostBBox": host_panel.get("bbox"),
        "targetBBox": target_panel.get("bbox"),
    }):
        extra["overheadReconcile"] = reconcile_payload
        extra["overheadPreview"] = preview_report
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

    extra["overheadReconcile"] = reconcile_payload
    extra["overheadPreview"] = preview_report
    return _build_result(plugin_dir, steps, True, write_json=write_json, **extra)


def _build_result(
    plugin_dir: str,
    steps: List[Dict[str, Any]],
    overall: bool,
    *,
    write_json: bool,
    **extra: Any,
) -> Dict[str, Any]:
    payload = {
        "ok": overall,
        "overall": "PASS" if overall else "FAIL",
        "smoke": "connect_main_flow",
        "action": "relationships.runConnectMainFlowSmoke",
        "pluginDir": plugin_dir,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
    }
    payload.update(extra)
    if write_json:
        payload["resultsPath"] = write_results(plugin_dir, payload, smoke_id="connect_main_flow")
    payload["summaryText"] = format_summary(payload)
    return payload
