#!/usr/bin/env python3
"""M3 Fusion smoke test — run INSIDE Fusion 360 (Scripts and Add-Ins → Run).

Executes checklist Steps 1–7 with real adsk geometry and writes JSON results to:
  fusion360-unified-cabinet-plugin/tests/output/m3_fusion_smoke_results.json

Usage:
  1. Open Fusion 360 → Design document (new empty design is fine)
  2. Scripts and Add-Ins → Add → select this file → Run
  3. Check results file and Fusion timeline for host cut feature
"""

from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import adsk.core

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

# Fallback when script is copied to Fusion Scripts folder (not run from repo tests/)
DEFAULT_REPO_PLUGIN_DIR = r"d:\project\troysfirstfusionproject-main\fusion360-unified-cabinet-plugin"


def _resolve_plugin_dir() -> str:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        script_dir,
        os.path.dirname(script_dir),
        os.environ.get("CABINETNC_PLUGIN_DIR") or "",
        DEFAULT_REPO_PLUGIN_DIR,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isfile(os.path.join(candidate, "UnifiedCabinetPlugin.py")):
            return candidate
    return os.path.dirname(os.path.dirname(script_dir))


def _ensure_paths(plugin_dir: str) -> None:
    paths = [
        plugin_dir,
        os.path.join(plugin_dir, "fusion"),
        os.path.join(plugin_dir, "ui"),
        os.path.join(plugin_dir, "modules"),
        os.path.join(plugin_dir, "modules", "hardware"),
        os.path.join(plugin_dir, "modules", "relationships"),
        os.path.join(plugin_dir, "panel_attributes"),
        os.path.join(plugin_dir, "metadata"),
    ]
    for path in reversed(paths):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)


def _purge_stale_plugin_modules() -> None:
    """Drop cached plugin modules so imports resolve from repo plugin_dir, not old add-in."""
    stale_prefixes = (
        "adapter",
        "modules.",
        "relationship_",
        "screw_hole_from_relationship",
        "relationship_screw_hole_fusion",
        "hardware_models",
        "geometry_ops",
        "face_attribute_store",
        "face_metadata_service",
        "face_models",
        "panel_metadata_types",
    )
    for key in list(sys.modules.keys()):
        if key == "adapter" or any(key.startswith(prefix) for prefix in stale_prefixes):
            del sys.modules[key]


def _import_plugin_modules(plugin_dir: str):
    import importlib

    _purge_stale_plugin_modules()
    _ensure_paths(plugin_dir)

    adapter_mod = importlib.import_module("adapter")
    screw_mod = importlib.import_module("screw_hole_from_relationship")
    rel_ctrl_mod = importlib.import_module("modules.relationships.controller")
    hw_ctrl_mod = importlib.import_module("modules.hardware.controller")

    fusion = adapter_mod.FusionAdapter()
    rel_ctrl = rel_ctrl_mod.RelationshipsController(fusion)
    hw_ctrl = hw_ctrl_mod.HardwareController(plugin_dir, fusion)
    import_meta = {
        "pluginDir": plugin_dir,
        "hardwareControllerFile": getattr(hw_ctrl_mod, "__file__", ""),
        "hasPreviewRoute": hasattr(hw_ctrl, "preview_screw_holes_from_relationship"),
        "hasCutRoute": hasattr(hw_ctrl, "create_screw_holes_from_relationship"),
    }
    if not import_meta["hasCutRoute"]:
        raise RuntimeError(
            "Loaded HardwareController from {} lacks create_screw_holes_from_relationship. "
            "Reload CabinetNC add-in from repo: {}".format(
                import_meta["hardwareControllerFile"], plugin_dir
            )
        )
    return fusion, rel_ctrl, hw_ctrl, screw_mod, import_meta


def _audit_row_for_relationship(scan_payload: Dict[str, Any], relationship_id: Optional[str]) -> Dict[str, Any]:
    if not relationship_id:
        return {}
    for row in scan_payload.get("audit") or []:
        if row.get("relationshipId") == relationship_id:
            return row
    return {}


def _resolve_verification(rel: Dict[str, Any], scan_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Read verification from relationship dict or scan audit row (palette JSON uses both)."""
    raw = rel.get("verification") if isinstance(rel, dict) else None
    if isinstance(raw, dict) and raw.get("level"):
        return raw

    row = _audit_row_for_relationship(scan_payload, rel.get("relationshipId"))
    if row.get("verificationLevel"):
        return {
            "level": row.get("verificationLevel"),
            "safeForPreview": bool(row.get("safeForPreview", True)),
            "safeForCut": bool(row.get("safeForCut", False)),
            "requiresManualConfirmation": bool(row.get("requiresManualConfirmation", True)),
        }

    return {
        "level": "bbox_candidate",
        "safeForPreview": True,
        "safeForCut": False,
        "requiresManualConfirmation": True,
    }


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


def _panels_map(scan_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {p["panelId"]: p for p in (scan_payload.get("panels") or []) if p.get("panelId")}


def _confirm_for_cut(relationship: Dict[str, Any]) -> Dict[str, Any]:
    notes = list(relationship.get("auditNotes") or [])
    notes.append("Manual cut confirmation applied (debug session only).")
    return {**relationship, "verification": dict(HW_REL_MANUAL_CONFIRMED), "auditNotes": notes}


def _build_cut_payload(confirmed: Dict[str, Any], scan_payload: Dict[str, Any]) -> Dict[str, Any]:
    panels = _panels_map(scan_payload)
    host_id = (confirmed.get("roles") or {}).get("hostPanelId")
    target_id = (confirmed.get("roles") or {}).get("targetPanelId")
    payload = {"relationship": confirmed, "rule": HW_REL_DEBUG_RULE}
    if host_id and target_id and host_id in panels and target_id in panels:
        payload["panels"] = {host_id: panels[host_id], target_id: panels[target_id]}
    return payload


def _cut_feature_exists(root, feature_name: Optional[str]) -> bool:
    if not root or not feature_name:
        return False

    def _scan_component(comp) -> bool:
        for index in range(comp.features.count):
            try:
                if comp.features.item(index).name == feature_name:
                    return True
            except Exception:
                continue
        return False

    if _scan_component(root):
        return True
    for index in range(root.allOccurrences.count):
        try:
            if _scan_component(root.allOccurrences.item(index).component):
                return True
        except Exception:
            continue
    return False


def _run_smoke(plugin_dir: str, fusion, rel_ctrl, hw_ctrl, screw_mod, import_meta: Dict[str, Any]) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []
    preview_report: Optional[Dict[str, Any]] = None
    scan_payload: Optional[Dict[str, Any]] = None
    cut_report: Dict[str, Any] = {}

    # Step 1 — fixture
    _ev, fixture = rel_ctrl.create_test_fixture({"toleranceMm": 0.5}, None)
    scan_payload = fixture.get("scan") or {}
    edge_ok = any(r.get("geometryType") == "edge_to_surface" for r in (scan_payload.get("relationships") or []))
    step1_ok = bool(fixture.get("ok")) and int(fixture.get("createdBodies") or 0) > 0 and edge_ok
    steps.append({"step": "1 fixture", "status": "PASS" if step1_ok else "FAIL", "data": {"createdBodies": fixture.get("createdBodies"), "relationshipCount": scan_payload.get("relationshipCount")}})
    if not step1_ok:
        return {"overall": "FAIL", "steps": steps}

    # Step 2 — scan validation
    rel = _find_preview_relationship(scan_payload)
    ver = _resolve_verification(rel or {}, scan_payload)
    step2_ok = bool(rel) and ver.get("level") == "bbox_candidate" and ver.get("safeForCut") is False
    steps.append({
        "step": "2 scan",
        "status": "PASS" if step2_ok else "FAIL",
        "data": {
            "relationshipId": (rel or {}).get("relationshipId"),
            "verification": ver,
            "verificationSource": "relationship" if (rel or {}).get("verification", {}).get("level") else "audit",
            "pluginDir": plugin_dir,
            "importMeta": import_meta,
        },
    })
    if not step2_ok or not rel:
        return {"overall": "FAIL", "steps": steps}

    # Step 3 — preview
    panels = _panels_map(scan_payload)
    host_id = rel["roles"]["hostPanelId"]
    target_id = rel["roles"]["targetPanelId"]
    panel_snapshots = {host_id: panels[host_id], target_id: panels[target_id]}
    preview_report = screw_mod.preview_screw_holes_from_relationship(
        rel,
        rule=HW_REL_DEBUG_RULE,
        panel_snapshots=panel_snapshots,
    )
    audit = preview_report.get("audit") or {}
    step3_ok = preview_report.get("ok") and int(preview_report.get("holeCount") or 0) >= 1 and audit.get("verificationLevel") == "bbox_candidate"
    steps.append({"step": "3 preview", "status": "PASS" if step3_ok else "FAIL", "data": {"holeCount": preview_report.get("holeCount"), "audit": audit}})
    if not step3_ok:
        return {"overall": "FAIL", "steps": steps}

    # Step 4 — confirm
    confirmed = _confirm_for_cut(rel)
    step4_ok = confirmed["verification"]["level"] == "manual_confirmed" and confirmed["verification"]["safeForCut"] is True
    steps.append({"step": "4 confirm", "status": "PASS" if step4_ok else "FAIL", "data": {"relationshipId": confirmed.get("relationshipId")}})
    if not step4_ok:
        return {"overall": "FAIL", "steps": steps}

    # Step 5 — negative gate (bbox cut blocked)
    blocked = screw_mod.plan_screw_hole_cut_from_relationship(
        rel,
        rule=HW_REL_DEBUG_RULE,
        panel_snapshots=panel_snapshots,
    )
    step5_ok = blocked.get("ok") is False and any(
        token in str(e).lower()
        for e in (blocked.get("errors") or [])
        for token in ("cut-safe", "cut safe", "manual confirmation", "not verified for cut", "not cut-safe")
    )
    steps.append({"step": "5 negative gate", "status": "PASS" if step5_ok else "FAIL", "data": {"errors": blocked.get("errors")}})
    if not step5_ok:
        return {"overall": "FAIL", "steps": steps}

    # Step 6 — create cut
    root = fusion.get_root_component()

    _ev, cut_report = hw_ctrl.create_screw_holes_from_relationship(_build_cut_payload(confirmed, scan_payload), None)
    step6_ok = (
        cut_report.get("ok") is True
        and cut_report.get("operationType") == "SCREW_HOLE_FROM_RELATIONSHIP"
        and bool(cut_report.get("cutFeatureName"))
        and cut_report.get("metadataWritten") is True
        and cut_report.get("targetBodyModified") is False
        and (cut_report.get("errors") or []) == []
    )
    steps.append({"step": "6 create cut", "status": "PASS" if step6_ok else "FAIL", "data": cut_report})

    # Step 7 — timeline verification
    cut_name = cut_report.get("cutFeatureName")
    step7_ok = step6_ok and _cut_feature_exists(root, cut_name)
    steps.append({
        "step": "7 visual",
        "status": "PASS" if step7_ok else "FAIL",
        "data": {
            "cutFeatureName": cut_name,
            "cutFeatureInTimeline": _cut_feature_exists(root, cut_name),
            "targetBodyModified": cut_report.get("targetBodyModified"),
        },
    })

    overall = all(s["status"] == "PASS" for s in steps)
    return {
        "overall": "PASS" if overall else "FAIL",
        "pluginDir": plugin_dir,
        "importMeta": import_meta,
        "fusionVersion": adsk.core.Application.get().version if adsk.core.Application.get() else "",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "steps": steps,
        "previewAudit": preview_report.get("audit") if preview_report else None,
        "cutAudit": cut_report if step6_ok else cut_report,
    }


def run(context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface if app else None
        plugin_dir = _resolve_plugin_dir()
        fusion, rel_ctrl, hw_ctrl, screw_mod, import_meta = _import_plugin_modules(plugin_dir)

        result = _run_smoke(plugin_dir, fusion, rel_ctrl, hw_ctrl, screw_mod, import_meta)
        out_paths = []
        for out_dir in (
            os.path.join(plugin_dir, "tests", "output"),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tests", "output"),
        ):
            try:
                out_dir = os.path.normpath(out_dir)
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, "m3_fusion_smoke_results.json")
                with open(out_path, "w", encoding="utf-8") as handle:
                    json.dump(result, handle, indent=2, ensure_ascii=False)
                out_paths.append(out_path)
            except Exception:
                continue

        out_path = out_paths[0] if out_paths else "(write failed)"
        summary = "M3 Fusion smoke: {}\nPlugin: {}\nResults: {}".format(
            result.get("overall"), result.get("pluginDir") or plugin_dir, out_path
        )
        if ui:
            ui.messageBox(summary)
        else:
            print(summary)
    except Exception:
        msg = traceback.format_exc()
        if ui:
            ui.messageBox("M3 Fusion smoke FAILED:\n{}".format(msg))
        raise
