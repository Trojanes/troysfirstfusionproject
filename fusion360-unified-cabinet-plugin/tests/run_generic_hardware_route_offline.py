#!/usr/bin/env python3
"""Offline smoke: Connect generic hardware routes + lock pocket writeback shape."""

from __future__ import annotations

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
        normalize_hardware_type,
    )
    from panel_metadata_writeback import build_lock_cutout_panel_feature_record
    from relationship_fixtures import build_fixture_snapshots, expected_fixture_cases
    from relationship_report import build_scan_report
    from relationship_service import scan_relationships

    plugin = os.path.join(ROOT, "UnifiedCabinetPlugin.py")
    with open(plugin, "r", encoding="utf-8") as handle:
        text = handle.read()
    for route in (
        "hardware.previewHardwareFromRelationship",
        "hardware.createHardwareFromRelationship",
    ):
        if route not in text:
            return _fail("route registered", route)
    print("[PASS] generic Connect hardware routes registered")

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
    confirmed = dict(rel)
    confirmed["verification"] = {
        "level": "manual_confirmed",
        "safeForPreview": True,
        "safeForCut": True,
        "requiresManualConfirmation": False,
    }
    panel_map = {panel.panelId: panel.to_dict() for panel in panels}
    host_id = confirmed["roles"]["hostPanelId"]
    target_id = confirmed["roles"]["targetPanelId"]
    panels_payload = {host_id: panel_map[host_id], target_id: panel_map[target_id]}

    for hw_type in (
        HARDWARE_TYPE_SCREW_HOLE,
        HARDWARE_TYPE_TONGUE_GROOVE,
        HARDWARE_TYPE_HINGE_HOLE,
        HARDWARE_TYPE_LOCK_CUTOUT,
        HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
    ):
        rule = {"type": hw_type}
        if normalize_hardware_type(rule) != hw_type:
            return _fail("normalize", hw_type)
        preview = dispatch_hardware_preview(confirmed, rule=rule, panel_snapshots=panels_payload)
        if not preview.get("ok"):
            return _fail("{} preview".format(hw_type), preview)
        plan = dispatch_hardware_cut_plan(confirmed, rule=rule, panel_snapshots=panels_payload)
        if not plan.get("ok"):
            return _fail("{} cut plan".format(hw_type), plan)
        print("[PASS] generic dispatch {} preview+plan".format(hw_type))

    lock_plan = dispatch_hardware_cut_plan(
        confirmed, rule={"type": HARDWARE_TYPE_LOCK_CUTOUT}, panel_snapshots=panels_payload
    )
    record = build_lock_cutout_panel_feature_record(
        lock_plan.get("feature") or {},
        cut_metadata=lock_plan.get("metadata") or {},
        cut_feature_name="HW_REL_LOCK_OFFLINE",
    )
    if record.get("kind") != "pocket" or record.get("isCircle") is not False:
        return _fail("lock writeback record", record)
    print("[PASS] lock pocket writeback record kind=pocket")

    print("")
    print("Generic hardware route offline: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
