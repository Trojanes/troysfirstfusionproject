#!/usr/bin/env python3
"""M4 Real Cabinet smoke test — run INSIDE Fusion 360 (Scripts and Add-Ins → Run).

Generates an Overhead cabinet, then runs scan → preview → confirm → cut on a real
edge_to_surface structural_butt_joint (prefers BP↔D0 golden pair).

Results: fusion360-unified-cabinet-plugin/tests/output/m4_fusion_smoke_results.json

NOTE: When copied to Fusion Scripts folder, helpers load from repo plugin tests/.
"""

from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import adsk.core

DEFAULT_REPO_PLUGIN_DIR = r"d:\project\troysfirstfusionproject-main\fusion360-unified-cabinet-plugin"

OVERHEAD_PREFERRED_PAIRS = [
    ("BP", "D0"),
    ("BP", "FP0"),
    ("D0", "FP0"),
]


def _bootstrap_imports(script_file: str):
    """Resolve repo plugin + import smoke_connect_helpers (must run inside run())."""
    script_dir = os.path.dirname(os.path.abspath(script_file))
    candidates = [
        script_dir,
        os.path.dirname(script_dir),
        os.environ.get("CABINETNC_PLUGIN_DIR") or "",
        DEFAULT_REPO_PLUGIN_DIR,
    ]
    plugin_dir = None
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isfile(os.path.join(candidate, "UnifiedCabinetPlugin.py")):
            plugin_dir = candidate
            break
    if not plugin_dir:
        plugin_dir = DEFAULT_REPO_PLUGIN_DIR

    tests_dir = os.path.join(plugin_dir, "tests")
    for path in (tests_dir, script_dir):
        if path and path not in sys.path:
            sys.path.insert(0, path)

    import smoke_connect_helpers as helpers  # noqa: WPS433

    return plugin_dir, helpers


def _run_smoke(plugin_dir: str, helpers, fusion, rel_ctrl, hw_ctrl, screw_mod, import_meta) -> Dict[str, Any]:
    import importlib

    overhead_mod = importlib.import_module("modules.overhead.controller")
    overhead_ctrl = overhead_mod.OverheadController(plugin_dir, fusion)

    steps: List[Dict[str, Any]] = []
    preview_report: Optional[Dict[str, Any]] = None
    cut_report: Dict[str, Any] = {}

    params = helpers.load_json_fixture(plugin_dir, "tests", "fixtures", "generator_params", "overhead_edge_only.json")
    _ev, gen_payload = overhead_ctrl.create_fusion_rough_bodies(
        {
            "params": params,
            "assemblyName": "M4_OH_SMOKE",
            "caseName": "m4_smoke",
        },
        None,
    )
    step1_ok = bool(gen_payload.get("ok")) and int(gen_payload.get("createdBodies") or 0) > 0
    steps.append({
        "step": "1 generate overhead",
        "status": "PASS" if step1_ok else "FAIL",
        "data": {
            "createdBodies": gen_payload.get("createdBodies"),
            "assemblyComponentName": gen_payload.get("assemblyComponentName"),
            "createdBoardIds": gen_payload.get("createdBoardIds"),
            "errors": gen_payload.get("errors"),
        },
    })
    if not step1_ok:
        return {"overall": "FAIL", "pluginDir": plugin_dir, "importMeta": import_meta, "steps": steps}

    _ev, scan_payload = rel_ctrl.scan({"scope": "all", "toleranceMm": 0.5}, None)
    rel = helpers.find_preview_relationship(scan_payload, OVERHEAD_PREFERRED_PAIRS)
    ver = helpers.resolve_verification(rel or {}, scan_payload)
    step2_ok = bool(scan_payload.get("ok")) and bool(rel) and ver.get("level") == "bbox_candidate"
    steps.append({
        "step": "2 scan",
        "status": "PASS" if step2_ok else "FAIL",
        "data": {
            "panelCount": scan_payload.get("panelCount"),
            "relationshipCount": scan_payload.get("relationshipCount"),
            "relationshipId": (rel or {}).get("relationshipId"),
            "verification": ver,
            "preferredPairTried": OVERHEAD_PREFERRED_PAIRS,
        },
    })
    if not step2_ok or not rel:
        return {"overall": "FAIL", "pluginDir": plugin_dir, "importMeta": import_meta, "steps": steps}

    panel_map = helpers.panels_map(scan_payload)
    host_id = rel["roles"]["hostPanelId"]
    target_id = rel["roles"]["targetPanelId"]
    panel_snapshots = {host_id: panel_map[host_id], target_id: panel_map[target_id]}

    preview_report = screw_mod.preview_screw_holes_from_relationship(
        rel, rule=helpers.HW_REL_DEBUG_RULE, panel_snapshots=panel_snapshots
    )
    audit = preview_report.get("audit") or {}
    step3_ok = preview_report.get("ok") and int(preview_report.get("holeCount") or 0) >= 1
    steps.append({
        "step": "3 preview",
        "status": "PASS" if step3_ok else "FAIL",
        "data": {"holeCount": preview_report.get("holeCount"), "hostPanelId": host_id, "targetPanelId": target_id, "audit": audit},
    })
    if not step3_ok:
        return {"overall": "FAIL", "pluginDir": plugin_dir, "importMeta": import_meta, "steps": steps}

    confirmed = helpers.confirm_for_cut(rel)
    step4_ok = confirmed["verification"]["level"] == "manual_confirmed"
    steps.append({"step": "4 confirm", "status": "PASS" if step4_ok else "FAIL", "data": {"relationshipId": confirmed.get("relationshipId")}})
    if not step4_ok:
        return {"overall": "FAIL", "pluginDir": plugin_dir, "importMeta": import_meta, "steps": steps}

    blocked = screw_mod.plan_screw_hole_cut_from_relationship(
        rel, rule=helpers.HW_REL_DEBUG_RULE, panel_snapshots=panel_snapshots
    )
    step5_ok = blocked.get("ok") is False and any(
        token in str(e).lower()
        for e in (blocked.get("errors") or [])
        for token in ("cut-safe", "cut safe", "manual confirmation", "not verified for cut", "not cut-safe")
    )
    steps.append({"step": "5 negative gate", "status": "PASS" if step5_ok else "FAIL", "data": {"errors": blocked.get("errors")}})
    if not step5_ok:
        return {"overall": "FAIL", "pluginDir": plugin_dir, "importMeta": import_meta, "steps": steps}

    root = fusion.get_root_component()
    _ev, cut_report = hw_ctrl.create_screw_holes_from_relationship(
        helpers.build_cut_payload(confirmed, scan_payload), None
    )
    step6_ok = (
        cut_report.get("ok") is True
        and cut_report.get("operationType") == "SCREW_HOLE_FROM_RELATIONSHIP"
        and bool(cut_report.get("cutFeatureName"))
        and cut_report.get("metadataWritten") is True
        and cut_report.get("targetBodyModified") is False
    )
    steps.append({"step": "6 create cut", "status": "PASS" if step6_ok else "FAIL", "data": cut_report})

    cut_name = cut_report.get("cutFeatureName")
    step7_ok = step6_ok and helpers.cut_feature_exists(root, cut_name)
    steps.append({
        "step": "7 visual",
        "status": "PASS" if step7_ok else "FAIL",
        "data": {
            "cutFeatureName": cut_name,
            "cutFeatureInTimeline": helpers.cut_feature_exists(root, cut_name),
            "targetBodyModified": cut_report.get("targetBodyModified"),
        },
    })

    overall = all(item["status"] == "PASS" for item in steps)
    return {
        "overall": "PASS" if overall else "FAIL",
        "generator": "overhead",
        "pluginDir": plugin_dir,
        "importMeta": import_meta,
        "fusionVersion": adsk.core.Application.get().version if adsk.core.Application.get() else "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "previewAudit": preview_report.get("audit") if preview_report else None,
        "cutAudit": cut_report,
    }


def _notify(ui, message: str) -> None:
    if ui:
        ui.messageBox(message)
        return
    app = adsk.core.Application.get()
    if app:
        try:
            app.log("M4 smoke", message[:3500])
        except Exception:
            pass
    print(message)


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface if app else None
        plugin_dir, helpers = _bootstrap_imports(__file__)
        fusion, rel_ctrl, hw_ctrl, screw_mod, import_meta = helpers.import_plugin_modules(plugin_dir)
        result = _run_smoke(plugin_dir, helpers, fusion, rel_ctrl, hw_ctrl, screw_mod, import_meta)
        out_path = helpers.write_smoke_results(plugin_dir, __file__, "m4_fusion_smoke_results.json", result)
        _notify(
            ui,
            "M4 Real Cabinet smoke: {}\nGenerator: overhead\nPlugin: {}\nResults: {}".format(
                result.get("overall"), plugin_dir, out_path
            ),
        )
    except Exception:
        msg = traceback.format_exc()
        _notify(ui, "M4 Fusion smoke FAILED:\n{}".format(msg))
        raise
