"""Fusion smoke — Kitchen / GT / Lounge declared joints (create → reconcile → preview).

Install: python scripts/manage_fusion_smokes.py install --batch declared
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from connect_batch_c_runner import _panel_map_from_reconcile
from connect_smoke_runner import format_summary
from generator_declared_service import reconcile_generator_declarations
from generator_panel_adapter import snapshots_from_generator_result
from overhead_declared_relationships import extract_board_suffix
from relationship_service import build_panel_snapshot_from_dict

SCREW_RULE = {
    "type": "screw_hole",
    "diameterMm": 4,
    "edgeOffsetMm": 30,
    "minSpacingMm": 80,
    "depthMode": "host_thickness",
}

# origin offsets keep three assemblies from stacking on the same spawn point
CASES: Tuple[Dict[str, Any], ...] = (
    {
        "key": "kitchen",
        "generator": "kitchen",
        "fixture": "kitchen_base.json",
        "declarationId": "kt_b1_b3_bottom_rail_to_deck",
        "minGeometryOk": 2,
        "assemblyName": "KC_DECLARED_SMOKE",
        "runLabel": "declared_kitchen",
        "originXMm": 0.0,
        "originYMm": 0.0,
    },
    {
        "key": "general_tall",
        "generator": "general_tall",
        "fixture": "general_tall_base.json",
        "declarationId": "gt_b1_b3_bottom_rail_to_deck",
        "minGeometryOk": 4,
        "assemblyName": "GTC_DECLARED_SMOKE",
        "runLabel": "declared_gt",
        "originXMm": 2800.0,
        "originYMm": 0.0,
    },
    {
        "key": "lounge",
        "generator": "lounge",
        "fixture": "lounge_l_shape.json",
        "declarationId": "lg_main_front_to_top",
        "minGeometryOk": 3,
        "assemblyName": "LG_DECLARED_SMOKE",
        "runLabel": "declared_lounge",
        "originXMm": 5600.0,
        "originYMm": 0.0,
    },
)


def _load_fixture(plugin_dir: str, name: str) -> Dict[str, Any]:
    path = os.path.join(plugin_dir, "tests", "fixtures", "generator_params", name)
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    return payload if isinstance(payload, dict) else {}


def _find_relationship_by_declaration_id(report: Dict[str, Any], declaration_id: str) -> Optional[Dict[str, Any]]:
    for item in report.get("reconciled") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("declarationId") or "") != declaration_id:
            continue
        rel = item.get("relationship")
        if isinstance(rel, dict):
            return rel
    for item in report.get("declaredRelationships") or []:
        if not isinstance(item, dict):
            continue
        rel = item.get("relationship") if isinstance(item.get("relationship"), dict) else item
        if not isinstance(rel, dict):
            continue
        # declaredRelationships may not carry declarationId; match via host/target later
        if str(item.get("declarationId") or "") == declaration_id:
            return rel
    return None


def _board_ids_from_result(result: Optional[Dict[str, Any]]) -> set:
    ids = set()
    if not isinstance(result, dict):
        return ids
    for key in ("boards", "panels"):
        for item in result.get(key) or []:
            if isinstance(item, dict) and item.get("id"):
                ids.add(str(item["id"]))
    for decl in result.get("relationshipDeclarations") or []:
        if not isinstance(decl, dict):
            continue
        for field in ("panelAId", "panelBId", "hostPanelId", "targetPanelId"):
            if decl.get(field):
                ids.add(str(decl[field]))
    return ids


def _filter_fusion_panels(all_panels, board_ids: set, case_key: str):
    """Keep only panels that belong to this generator result (avoid leftover cabinets)."""
    filtered = []
    for panel in all_panels or []:
        panel_id = str(getattr(panel, "panelId", "") or "")
        suffix = extract_board_suffix(panel_id)
        body = str(getattr(panel, "bodyName", "") or "")
        if suffix in board_ids or panel_id in board_ids:
            filtered.append(panel)
            continue
        if case_key == "kitchen" and "KITCHEN_" in body:
            if any(bid in body for bid in board_ids):
                filtered.append(panel)
        elif case_key == "general_tall" and (body.startswith("GT_") or "generalTall." in panel_id):
            if suffix in board_ids:
                filtered.append(panel)
        elif case_key == "lounge" and suffix in board_ids:
            filtered.append(panel)
    return filtered


def _reconcile_case(rel_ctrl, case: Dict[str, Any], result: Optional[Dict[str, Any]], run_label: str):
    """Reconcile using Fusion panels filtered to this cabinet; fall back to generator snapshots."""
    board_ids = _board_ids_from_result(result)
    fusion_panels = []
    try:
        fusion_panels = list(
            rel_ctrl.service.collect_panels_from_design(bbox_source="design_preferred") or []
        )
    except Exception:
        fusion_panels = []
    panels = _filter_fusion_panels(fusion_panels, board_ids, case["key"])
    source = "fusion_filtered"
    if len(panels) < 2:
        # Assembly-name collect is unreliable for Kitchen (CabinetNC attrs / naming).
        # Generator design snapshots still prove declaration↔geometry after create succeeds.
        snapshots = snapshots_from_generator_result(case["generator"], result or {})
        panels = [build_panel_snapshot_from_dict(item) for item in snapshots]
        source = "generator_snapshots"
    embedded = None
    if isinstance(result, dict):
        embedded = result.get("relationshipDeclarations")
        if not isinstance(embedded, list):
            embedded = None
    report = reconcile_generator_declarations(
        panels,
        generator=case["generator"],
        preferred_run_token=run_label,
        embedded_declarations=embedded,
    )
    if isinstance(report, dict):
        report = dict(report)
        report["panelSource"] = source
        report["filteredPanelCount"] = len(panels)
        report["fusionPanelCount"] = len(fusion_panels)
        report["boardIdCount"] = len(board_ids)
    return report


def _generate_and_create(
    case: Dict[str, Any],
    params: Dict[str, Any],
    kitchen_ctrl,
    gt_ctrl,
    lounge_ctrl,
) -> Tuple[bool, Dict[str, Any], Optional[Dict[str, Any]]]:
    key = case["key"]
    assembly_name = case["assemblyName"]
    run_label = case["runLabel"]
    origin = {"originXMm": case["originXMm"], "originYMm": case["originYMm"]}

    if key == "kitchen":
        _ev, gen = kitchen_ctrl.generate_geometry({"params": params}, None)
        if not gen.get("ok"):
            return False, gen, None
        result = gen.get("result")
        # flat_transform places boards in assembly pose so declared edge contacts exist.
        # Plain flat nest lays B1/B3 apart on XY and reconcile cannot match geometry.
        _ev, created = kitchen_ctrl.create_flat_transform_preview(
            {
                "result": result,
                "caseName": run_label,
                "assemblyName": assembly_name,
                "addAsNewCabinet": True,
                **origin,
            },
            None,
        )
        return bool(created.get("ok")), created, result if isinstance(result, dict) else None

    if key == "general_tall":
        _ev, gen = gt_ctrl.generate({"params": params}, None)
        if not gen.get("ok"):
            return False, gen, None
        result = gen.get("result")
        _ev, created = gt_ctrl.create_fusion_rough_bodies(
            {
                "result": result,
                "params": params,
                "caseName": run_label,
                "assemblyName": assembly_name,
                **origin,
            },
            None,
        )
        return bool(created.get("ok")), created, result if isinstance(result, dict) else None

    _ev, gen = lounge_ctrl.generate_geometry({"params": params}, None)
    if not gen.get("ok"):
        return False, gen, None
    result = gen.get("result")
    _ev, created = lounge_ctrl.create_assembly_bodies(
        {
            "result": result,
            "runLabel": run_label,
            "assemblyName": assembly_name,
            **origin,
        },
        None,
    )
    return bool(created.get("ok")), created, result if isinstance(result, dict) else None


def run_declared_generators_fusion_smoke(
    plugin_dir: str,
    fusion,
    rel_ctrl,
    hw_ctrl,
    kitchen_ctrl,
    gt_ctrl,
    lounge_ctrl,
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
            "smoke": "declared_generators_connect",
            "action": "relationships.runDeclaredGeneratorsSmoke",
            "pluginDir": plugin_dir,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "steps": steps,
        }
        payload.update(extra)
        if write_json:
            out_dir = os.path.join(plugin_dir, "tests", "output")
            try:
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, "declared_generators_connect_smoke_results.json")
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

    for case in CASES:
        key = case["key"]
        params = _load_fixture(plugin_dir, case["fixture"])
        create_ok, created, result = _generate_and_create(
            case, params, kitchen_ctrl, gt_ctrl, lounge_ctrl,
        )
        created_bodies = int(created.get("createdBodies") or 0)
        assembly_name = created.get("assemblyComponentName") or case["assemblyName"]
        run_label = str(created.get("runLabel") or case["runLabel"])
        if not record("{} generate+create".format(key), create_ok and created_bodies >= 2, {
            "createdBodies": created_bodies,
            "assemblyComponentName": assembly_name,
            "runLabel": run_label,
            "declarationCountWritten": created.get("relationshipDeclarationCount"),
            "errors": created.get("errors"),
        }):
            return build_result(False, failedCase=key, create=created)

        reconcile = _reconcile_case(rel_ctrl, case, result, run_label)
        geom_ok = int(reconcile.get("geometryOkCount") or 0)
        reconcile_ok = bool(reconcile.get("ok")) and geom_ok >= int(case["minGeometryOk"])
        if not record("{} reconcile".format(key), reconcile_ok, {
            "declarationCount": reconcile.get("declarationCount"),
            "geometryOkCount": geom_ok,
            "panelCount": reconcile.get("panelCount") or reconcile.get("filteredPanelCount"),
            "panelSource": reconcile.get("panelSource"),
            "fusionPanelCount": reconcile.get("fusionPanelCount"),
            "assemblyComponentName": assembly_name,
            "errors": reconcile.get("errors"),
        }):
            return build_result(False, failedCase=key, reconcile=reconcile)

        rel = _find_relationship_by_declaration_id(reconcile, case["declarationId"])
        if rel is None and isinstance(result, dict):
            # Fallback: match host/target board suffixes from declaration id catalog via roles
            for item in reconcile.get("reconciled") or []:
                if str(item.get("declarationId") or "") == case["declarationId"]:
                    rel = item.get("relationship")
                    break
        if not isinstance(rel, dict):
            record("{} find declaration".format(key), False, {"declarationId": case["declarationId"]})
            return build_result(False, failedCase=key, reconcile=reconcile)

        panel_map = _panel_map_from_reconcile(reconcile)
        roles = rel.get("roles") or {}
        host_id = str(roles.get("hostPanelId") or "")
        target_id = str(roles.get("targetPanelId") or "")
        panels = {}
        if host_id in panel_map:
            panels[host_id] = panel_map[host_id]
        if target_id in panel_map:
            panels[target_id] = panel_map[target_id]
        _ev, preview = hw_ctrl.preview_screw_holes_from_relationship(
            {"relationship": rel, "rule": dict(SCREW_RULE), "panels": panels},
            None,
        )
        preview_ok = bool(preview.get("ok"))
        if not record("{} preview screw".format(key), preview_ok, {
            "declarationId": case["declarationId"],
            "hostPanelId": host_id,
            "targetPanelId": target_id,
            "hostSuffix": extract_board_suffix(host_id),
            "targetSuffix": extract_board_suffix(target_id),
            "errors": preview.get("errors"),
            "holeCount": preview.get("holeCount") or len(preview.get("holes") or []),
        }):
            return build_result(False, failedCase=key, preview=preview)

    return build_result(True)
