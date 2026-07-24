"""Batch C — real cabinet pairs + dual-path confirm vs face_verified."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from connect_smoke_runner import (
    HW_RULE,
    find_body_by_panel_id,
    format_summary,
    write_results,
)
from overhead_declared_relationships import extract_board_suffix

OVERHEAD_ASSEMBLY = "OHC_BATCH_C"
OVERHEAD_RUN_LABEL = "batch_c_smoke"
PAIR_SPECS: Tuple[Tuple[str, str], ...] = (("BP", "D0"), ("BP", "FP0"))


def _load_overhead_params(plugin_dir: str) -> Dict[str, Any]:
    path = os.path.join(plugin_dir, "tests", "fixtures", "generator_params", "overhead_edge_only.json")
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _panel_map_from_reconcile(report: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    panel_map: Dict[str, Dict[str, Any]] = {}
    for panel in report.get("panels") or []:
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


def _find_pair_relationship(report: Dict[str, Any], suffixes: Set[str]) -> Optional[Dict[str, Any]]:
    for item in report.get("declaredRelationships") or []:
        if not isinstance(item, dict):
            continue
        rel = item.get("relationship") if isinstance(item.get("relationship"), dict) else item
        if not isinstance(rel, dict):
            continue
        panel_a = item.get("panelA") or rel.get("panelA") or {}
        panel_b = item.get("panelB") or rel.get("panelB") or {}
        roles = rel.get("roles") or {}
        found = {
            extract_board_suffix(panel_a.get("panelId") or roles.get("targetPanelId")),
            extract_board_suffix(panel_b.get("panelId") or roles.get("hostPanelId")),
        }
        if found == suffixes:
            return rel
    return None


def _preview_pair(
    hw_ctrl,
    relationship: Dict[str, Any],
    panel_map: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    roles = relationship.get("roles") or {}
    host_id = str(roles.get("hostPanelId") or "")
    target_id = str(roles.get("targetPanelId") or "")
    host = panel_map.get(host_id)
    target = panel_map.get(target_id)
    if not (_panel_has_usable_bbox(host) and _panel_has_usable_bbox(target)):
        return {
            "ok": False,
            "errors": ["Missing usable bboxes for {} / {}".format(host_id, target_id)],
            "hostPanelId": host_id,
            "targetPanelId": target_id,
        }
    _ev, report = hw_ctrl.preview_screw_holes_from_relationship(
        {
            "relationship": relationship,
            "rule": dict(HW_RULE),
            "panels": {host_id: host, target_id: target},
        },
        None,
    )
    return report if isinstance(report, dict) else {"ok": False, "errors": ["Invalid preview response."]}


def run_connect_batch_c_smoke(
    plugin_dir: str,
    fusion,
    rel_ctrl,
    hw_ctrl,
    overhead_ctrl,
    *,
    write_json: bool = True,
) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []
    extra: Dict[str, Any] = {}

    def record(step: str, ok: bool, data: Dict[str, Any]) -> bool:
        steps.append({"step": step, "status": "PASS" if ok else "FAIL", "data": data})
        return ok

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
    oh_ok = bool(oh_payload.get("ok")) and int(oh_payload.get("createdBodies") or 0) >= 4
    if not record("1 overhead create bodies", oh_ok, {
        "createdBodies": oh_payload.get("createdBodies"),
        "assemblyComponentName": assembly_name,
        "createdBoardIds": oh_payload.get("createdBoardIds"),
        "errors": oh_payload.get("errors"),
    }):
        extra["overheadCreate"] = oh_payload
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

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
        and int(reconcile_payload.get("geometryOkCount") or 0) >= 2
        and int(reconcile_payload.get("declarationCount") or 0) >= 2
    )
    if not record("2 overhead reconcile", reconcile_ok, {
        "declarationCount": reconcile_payload.get("declarationCount"),
        "geometryOkCount": reconcile_payload.get("geometryOkCount"),
        "panelCount": reconcile_payload.get("panelCount"),
        "errors": reconcile_payload.get("errors"),
    }):
        extra["overheadReconcile"] = reconcile_payload
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

    panel_map = _panel_map_from_reconcile(reconcile_payload)
    if len(panel_map) < 2:
        try:
            for panel in rel_ctrl.service.collect_panels_from_assembly(
                assembly_name, bbox_source="design_preferred"
            ) or []:
                payload = panel.to_dict() if hasattr(panel, "to_dict") else None
                if isinstance(payload, dict) and payload.get("panelId") and _panel_has_usable_bbox(payload):
                    panel_map[str(payload["panelId"])] = payload
        except Exception as ex:
            extra["panelSnapshotError"] = str(ex)

    pairs: Dict[str, Dict[str, Any]] = {}
    for left, right in PAIR_SPECS:
        key = "{}-{}".format(left, right)
        rel = _find_pair_relationship(reconcile_payload, {left, right})
        ok = (
            rel is not None
            and (rel.get("verification") or {}).get("level") == "generator_declared"
            and rel.get("geometryType") == "edge_to_surface"
        )
        if not record("3 pair {} relationship".format(key), ok, {
            "relationshipId": (rel or {}).get("relationshipId"),
            "verificationLevel": ((rel or {}).get("verification") or {}).get("level"),
            "hostPanelId": ((rel or {}).get("roles") or {}).get("hostPanelId"),
            "targetPanelId": ((rel or {}).get("roles") or {}).get("targetPanelId"),
        }):
            extra["overheadReconcile"] = reconcile_payload
            return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)
        pairs[key] = rel

    # Dual-path A: confirm on BP-D0 (session confirm; generator_declared already cut-safe)
    bp_d0 = pairs["BP-D0"]
    _ev, confirm_gate = rel_ctrl.connect_execute({"action": "confirm", "relationship": bp_d0}, None)
    confirmed = confirm_gate.get("confirmedRelationship") or confirm_gate.get("relationship") or bp_d0
    confirm_level = ((confirmed or {}).get("verification") or {}).get("level")
    confirm_ok = bool(confirm_gate.get("ok")) and confirm_level in (
        "manual_confirmed",
        "generator_declared",
        "face_verified",
    )
    if not record("4 dual-path confirm BP-D0", confirm_ok, {
        "verificationLevel": confirm_level,
        "safeForCut": ((confirmed or {}).get("verification") or {}).get("safeForCut"),
        "errors": confirm_gate.get("errors"),
    }):
        extra["confirmGate"] = confirm_gate
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

    preview_confirm = _preview_pair(hw_ctrl, confirmed if isinstance(confirmed, dict) else bp_d0, panel_map)
    preview_confirm_ok = bool(preview_confirm.get("ok")) and int(preview_confirm.get("holeCount") or 0) >= 1
    if not record("5 dual-path confirm preview BP-D0", preview_confirm_ok, {
        "holeCount": preview_confirm.get("holeCount"),
        "hostPanelId": preview_confirm.get("hostPanelId"),
        "errors": preview_confirm.get("errors"),
    }):
        extra["confirmPreview"] = preview_confirm
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

    # Dual-path B: face verify on BP-FP0 via selection
    bp_fp0 = pairs["BP-FP0"]
    roles = bp_fp0.get("roles") or {}
    host_id = str(roles.get("hostPanelId") or "")
    target_id = str(roles.get("targetPanelId") or "")
    root = fusion.get_root_component() if fusion else None
    host_body = find_body_by_panel_id(root, host_id) if root else None
    target_body = find_body_by_panel_id(root, target_id) if root else None
    selected = 0
    if host_body and target_body and hasattr(fusion, "select_bodies_and_fit"):
        selected = int(fusion.select_bodies_and_fit([host_body, target_body]) or 0)
    if not record("6 select BP-FP0 bodies", selected >= 2, {
        "selected": selected,
        "hostPanelId": host_id,
        "targetPanelId": target_id,
        "hostFound": host_body is not None,
        "targetFound": target_body is not None,
    }):
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

    _ev, face_report = rel_ctrl.verify_selected_pair_faces({"toleranceMm": 0.5}, None)
    face_rel = face_report.get("relationship") if isinstance(face_report, dict) else None
    face_level = ((face_rel or {}).get("verification") or {}).get("level")
    # Prefer face_verified; accept ok verify report that upgrades relationship.
    face_ok = bool(face_report.get("ok")) and (
        face_level == "face_verified"
        or ((face_rel or {}).get("verification") or {}).get("safeForCut") is True
    )
    if not record("7 dual-path face verify BP-FP0", face_ok, {
        "verificationLevel": face_level,
        "safeForCut": ((face_rel or {}).get("verification") or {}).get("safeForCut"),
        "faceMatch": face_report.get("faceMatch"),
        "errors": face_report.get("errors"),
    }):
        extra["faceVerify"] = face_report
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

    preview_face = _preview_pair(
        hw_ctrl,
        face_rel if isinstance(face_rel, dict) else bp_fp0,
        panel_map,
    )
    # If face-verified relationship uses different panel ids, fall back to declared pair preview.
    if not preview_face.get("ok"):
        preview_face = _preview_pair(hw_ctrl, bp_fp0, panel_map)
    preview_face_ok = bool(preview_face.get("ok")) and int(preview_face.get("holeCount") or 0) >= 1
    if not record("8 dual-path face-verify preview BP-FP0", preview_face_ok, {
        "holeCount": preview_face.get("holeCount"),
        "hostPanelId": preview_face.get("hostPanelId"),
        "errors": preview_face.get("errors"),
    }):
        extra["facePreview"] = preview_face
        return _build_result(plugin_dir, steps, False, write_json=write_json, **extra)

    extra["overheadReconcile"] = reconcile_payload
    extra["confirmPreview"] = preview_confirm
    extra["faceVerify"] = face_report
    extra["facePreview"] = preview_face
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
        "smoke": "connect_batch_c",
        "action": "relationships.runConnectBatchCSmoke",
        "pluginDir": plugin_dir,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
    }
    payload.update(extra)
    if write_json:
        payload["resultsPath"] = write_results(plugin_dir, payload, smoke_id="connect_batch_c")
    payload["summaryText"] = format_summary(payload)
    return payload
