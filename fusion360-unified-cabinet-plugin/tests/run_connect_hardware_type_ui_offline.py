#!/usr/bin/env python3
"""Offline check for Connect UI hardware-type selector routing."""

from __future__ import annotations

import copy
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (
    ROOT,
    os.path.join(ROOT, "modules", "hardware"),
    os.path.join(ROOT, "modules", "relationships"),
    os.path.join(ROOT, "panel_attributes"),
):
    if path not in sys.path:
        sys.path.insert(0, path)


def _fail(step: str, detail) -> int:
    print("[FAIL] {} -> {}".format(step, detail))
    return 1


def _confirm(rel: dict) -> dict:
    confirmed = copy.deepcopy(rel)
    confirmed["verification"] = {
        "level": "manual_confirmed",
        "safeForPreview": True,
        "safeForCut": True,
        "requiresManualConfirmation": False,
    }
    return confirmed


def main() -> int:
    from connect_demo_pack import find_first_screw_eligible
    from hardware_rule_engine import (
        HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
        HARDWARE_TYPE_HINGE_HOLE,
        HARDWARE_TYPE_LOCK_CUTOUT,
        HARDWARE_TYPE_SCREW_HOLE,
        HARDWARE_TYPE_TONGUE_GROOVE,
        dispatch_hardware_cut_plan,
        dispatch_hardware_preview,
        list_hardware_types,
        normalize_hardware_type,
    )
    from relationship_fixtures import build_fixture_snapshots, expected_fixture_cases
    from relationship_report import build_scan_report
    from relationship_service import scan_relationships

    rows = {row["type"]: row for row in list_hardware_types()}
    expected = {
        HARDWARE_TYPE_SCREW_HOLE: True,
        HARDWARE_TYPE_TONGUE_GROOVE: True,
        HARDWARE_TYPE_HINGE_HOLE: True,
        HARDWARE_TYPE_DRAWER_RUNNER_HOLE: True,
        HARDWARE_TYPE_LOCK_CUTOUT: True,
    }
    for hw_type, cut_ready in expected.items():
        meta = rows.get(hw_type)
        if not meta or bool(meta.get("cutReady")) != cut_ready:
            return _fail("registry {}".format(hw_type), meta)
        if not meta.get("label"):
            return _fail("label {}".format(hw_type), meta)
    print("[PASS] list_hardware_types cutReady map for Connect selector")

    for raw, want in (
        ({}, HARDWARE_TYPE_SCREW_HOLE),
        ({"type": "hinge_hole"}, HARDWARE_TYPE_HINGE_HOLE),
        ({"type": "TONGUE_GROOVE"}, HARDWARE_TYPE_TONGUE_GROOVE),
    ):
        if normalize_hardware_type(raw) != want:
            return _fail("normalize", (raw, want))
    print("[PASS] normalize_hardware_type")

    panels = build_fixture_snapshots()
    _, relationships = scan_relationships(panels, tolerance_mm=0.5, include_none=True)
    scan = build_scan_report(
        action="relationships.scan",
        panels=panels,
        relationships=relationships,
        scope="fixture",
        tolerance_mm=0.5,
        expected_fixtures=expected_fixture_cases(),
    )
    rel = find_first_screw_eligible(scan.get("relationships") or [])
    panel_map = {panel.panelId: panel.to_dict() for panel in panels}
    host_id = rel["roles"]["hostPanelId"]
    target_id = rel["roles"]["targetPanelId"]
    panels_payload = {host_id: panel_map[host_id], target_id: panel_map[target_id]}
    confirmed = _confirm(rel)

    # Mirror Connect UI: each selector value builds rule={type:...} and dispatches.
    for hw_type in expected:
        preview = dispatch_hardware_preview(
            rel, rule={"type": hw_type}, panel_snapshots=panels_payload
        )
        if not preview.get("ok"):
            return _fail("preview {}".format(hw_type), preview)
        if preview.get("hardwareType") != hw_type:
            return _fail("preview hardwareType {}".format(hw_type), preview)
    print("[PASS] selector preview dispatch for all 5 types")

    for hw_type, cut_ready in expected.items():
        plan = dispatch_hardware_cut_plan(
            confirmed, rule={"type": hw_type}, panel_snapshots=panels_payload
        )
        if cut_ready:
            if not plan.get("ok"):
                return _fail("cut plan {}".format(hw_type), plan)
        else:
            if plan.get("ok") or not plan.get("previewOnly"):
                return _fail("cut blocked {}".format(hw_type), plan)
    print("[PASS] selector cut plan: 5 ready / 0 blocked")

    # Plugin route registration (no Fusion).
    plugin_path = os.path.join(ROOT, "UnifiedCabinetPlugin.py")
    with open(plugin_path, "r", encoding="utf-8") as handle:
        text = handle.read()
    for route in (
        "hardware.listHardwareTypes",
        "hardware.previewHardwareFromRelationship",
            "hardware.createHardwareFromRelationship",
            "hardware.createHardwareForCutSafeRelationships",
            "hardware.runConnectPipeline",
        ):
        if route not in text:
            return _fail("plugin route missing", route)
    print("[PASS] UnifiedCabinetPlugin generic hardware routes registered")

    palette_path = os.path.join(ROOT, "palette.html")
    with open(palette_path, "r", encoding="utf-8") as handle:
        palette = handle.read()
    for token in (
        'id="connectHardwareType"',
        'id="connectHardwareParams"',
        "CONNECT_HW_PARAM_FIELDS",
        "connectUiReadHardwareRuleFromForm",
        "hardware.previewHardwareFromRelationship",
        "hardware.createHardwareFromRelationship",
        "CONNECT_HW_RULES",
        "connectUiRefreshHardwareTypeUi",
        'id="connectInspectSummary"',
        "hardware-shell-simple",
        'data-connect-view="pair"',
        'data-connect-view="cabinet"',
        'data-connect-view="ops"',
        "connectContactDistance",
        'id="connectVerifyAllBtn"',
        "connectUiVerifyAllBboxCandidates",
        "relationshipFaceVerifyBatchResult",
        "relationships.verifyAllBboxCandidates",
        'id="connectBatchCutBtn"',
        "connectUiBatchCutHardware",
        "hardware.createHardwareForCutSafeRelationships",
        'id="connectPipelineBtn"',
        "connectUiRunConnectPipeline",
        "hardware.runConnectPipeline",
        "connectUiRepairFromSkip",
        "relationships.inspectPair",
        'id="connectGapJointsEnabled"',
        "connectUiReadGapJoints",
        "cabinetnc.connect.gapJoints.v1",
        'id="connectAutoHardwareEnabled"',
        "connectUiReadAutoHardware",
        "cabinetnc.connect.autoHardware.v1",
    ):
        if token not in palette:
            return _fail("palette missing", token)
    print("[PASS] palette.html hardware-type selector + params + simplified layout wired")

    print()
    print("Connect hardware-type selector offline: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
