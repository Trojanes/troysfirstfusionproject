"""Fusion smoke — real Overhead cabinet cuts via generic hardware routes.

Cuts screw_hole on BP↔D0 and tongue_groove on BP↔FP0 using
hardware.createHardwareFromRelationship (Connect UI path).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from connect_batch_c_runner import (
    OVERHEAD_ASSEMBLY,
    OVERHEAD_RUN_LABEL,
    _find_pair_relationship,
    _load_overhead_params,
    _panel_map_from_reconcile,
)
from connect_smoke_runner import cut_feature_exists, find_body_by_panel_id, format_summary, safe_volume

SCREW_RULE = {"type": "screw_hole", "diameterMm": 4, "edgeOffsetMm": 30, "minSpacingMm": 80, "depthMode": "host_thickness"}
TONGUE_RULE = {"type": "tongue_groove", "grooveDepthMm": 8, "grooveWidthMm": 4, "tongueProtrusionMm": 7}


def run_real_cabinet_hardware_fusion_smoke(
    plugin_dir: str,
    fusion,
    rel_ctrl,
    hw_ctrl,
    overhead_ctrl,
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
            "smoke": "real_cabinet_hardware_connect",
            "action": "hardware.runRealCabinetHardwareSmoke",
            "pluginDir": plugin_dir,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "steps": steps,
        }
        payload.update(extra)
        if write_json:
            out_dir = os.path.join(plugin_dir, "tests", "output")
            try:
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, "real_cabinet_hardware_connect_smoke_results.json")
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

    params = _load_overhead_params(plugin_dir)
    _ev, oh_payload = overhead_ctrl.create_fusion_rough_bodies(
        {
            "params": params,
            "caseName": OVERHEAD_RUN_LABEL + "_hw",
            "assemblyName": OVERHEAD_ASSEMBLY + "_HW",
        },
        None,
    )
    assembly_name = oh_payload.get("assemblyComponentName") or (OVERHEAD_ASSEMBLY + "_HW")
    oh_ok = bool(oh_payload.get("ok")) and int(oh_payload.get("createdBodies") or 0) >= 4
    if not record("1 overhead create bodies", oh_ok, {
        "createdBodies": oh_payload.get("createdBodies"),
        "assemblyComponentName": assembly_name,
        "errors": oh_payload.get("errors"),
    }):
        return build_result(False, overheadCreate=oh_payload)

    run_label = str(oh_payload.get("runLabel") or OVERHEAD_RUN_LABEL + "_hw")
    reconcile_request = {
        "generator": "overhead",
        "runLabel": run_label,
        "toleranceMm": 1.0,
        "bboxSource": "design_preferred",
        "assemblyComponentName": assembly_name,
    }
    _ev, reconcile_payload = rel_ctrl.reconcile_generator_declarations(reconcile_request, None)
    if not reconcile_payload.get("ok"):
        reconcile_request.pop("assemblyComponentName", None)
        _ev, reconcile_payload = rel_ctrl.reconcile_generator_declarations(reconcile_request, None)
    reconcile_ok = bool(reconcile_payload.get("ok")) and int(reconcile_payload.get("geometryOkCount") or 0) >= 2
    if not record("2 overhead reconcile", reconcile_ok, {
        "declarationCount": reconcile_payload.get("declarationCount"),
        "geometryOkCount": reconcile_payload.get("geometryOkCount"),
        "errors": reconcile_payload.get("errors"),
    }):
        return build_result(False, overheadReconcile=reconcile_payload)

    panel_map = _panel_map_from_reconcile(reconcile_payload)
    bp_d0 = _find_pair_relationship(reconcile_payload, {"BP", "D0"})
    bp_fp0 = _find_pair_relationship(reconcile_payload, {"BP", "FP0"})
    if not bp_d0 or not bp_fp0:
        record("2b find declared pairs", False, {"bpD0": bool(bp_d0), "bpFp0": bool(bp_fp0)})
        return build_result(False, overheadReconcile=reconcile_payload)

    def _panels_for(rel: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        roles = rel.get("roles") or {}
        host_id = str(roles.get("hostPanelId") or "")
        target_id = str(roles.get("targetPanelId") or "")
        return {host_id: panel_map[host_id], target_id: panel_map[target_id]}

    # Screw on BP-D0 via generic route
    screw_panels = _panels_for(bp_d0)
    host_id = bp_d0["roles"]["hostPanelId"]
    host_body = find_body_by_panel_id(root, host_id, panel_map.get(host_id))
    if host_body is None:
        record("3 resolve BP-D0 host", False, {"hostPanelId": host_id})
        return build_result(False)
    vol_before = safe_volume(host_body)
    _ev, screw_cut = hw_ctrl.create_hardware_from_relationship(
        {"relationship": bp_d0, "rule": dict(SCREW_RULE), "panels": screw_panels},
        None,
    )
    host_after = find_body_by_panel_id(root, host_id, panel_map.get(host_id)) or host_body
    vol_after = safe_volume(host_after)
    screw_name = str((screw_cut or {}).get("cutFeatureName") or "")
    feature_ok = cut_feature_exists(root, screw_name)
    volume_delta = abs(vol_after - vol_before)
    screw_ok = (
        bool((screw_cut or {}).get("ok"))
        and (screw_cut or {}).get("hardwareType") == "screw_hole"
        and bool(screw_name)
        and feature_ok
        and volume_delta > 0.01
    )
    if not record("3 generic screw cut BP-D0", screw_ok, {
        "cutFeatureName": screw_name,
        "cutFeatureExists": feature_ok,
        "hostVolumeBefore": vol_before,
        "hostVolumeAfter": vol_after,
        "hostVolumeDelta": vol_after - vol_before,
        "panelWriteback": (screw_cut or {}).get("panelWriteback"),
        "errors": (screw_cut or {}).get("errors"),
    }):
        return build_result(False, screwCut=screw_cut)

    # Tongue/groove on BP-FP0 via generic route
    tg_panels = _panels_for(bp_fp0)
    tg_host_id = bp_fp0["roles"]["hostPanelId"]
    tg_target_id = bp_fp0["roles"]["targetPanelId"]
    tg_host = find_body_by_panel_id(root, tg_host_id, panel_map.get(tg_host_id))
    tg_target = find_body_by_panel_id(root, tg_target_id, panel_map.get(tg_target_id))
    if tg_host is None or tg_target is None:
        record("4 resolve BP-FP0 bodies", False, {"host": tg_host_id, "target": tg_target_id})
        return build_result(False)
    h_before = safe_volume(tg_host)
    t_before = safe_volume(tg_target)
    _ev, tg_cut = hw_ctrl.create_hardware_from_relationship(
        {"relationship": bp_fp0, "rule": dict(TONGUE_RULE), "panels": tg_panels},
        None,
    )
    tg_host = find_body_by_panel_id(root, tg_host_id, panel_map.get(tg_host_id)) or tg_host
    tg_target = find_body_by_panel_id(root, tg_target_id, panel_map.get(tg_target_id)) or tg_target
    h_after = safe_volume(tg_host)
    t_after = safe_volume(tg_target)
    tg_name = str((tg_cut or {}).get("cutFeatureName") or (tg_cut or {}).get("tongueFeatureName") or "")
    tg_ok = (
        bool((tg_cut or {}).get("ok"))
        and (tg_cut or {}).get("hardwareType") == "tongue_groove"
        and abs(h_after - h_before) > 0.01
        and abs(t_after - t_before) > 0.01
    )
    if not record("4 generic tongue/groove cut BP-FP0", tg_ok, {
        "cutFeatureName": tg_name,
        "hostVolumeDelta": h_after - h_before,
        "targetVolumeDelta": t_after - t_before,
        "hostWriteback": (tg_cut or {}).get("panelWriteback"),
        "targetWriteback": (tg_cut or {}).get("targetPanelWriteback"),
        "errors": (tg_cut or {}).get("errors"),
    }):
        return build_result(False, tongueCut=tg_cut)

    return build_result(True, screwCut=screw_cut, tongueCut=tg_cut)
