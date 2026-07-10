#!/usr/bin/env python3
"""Offline smoke for post-M9 hinge/lock/runner cut-ready."""

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
        dispatch_hardware_cut_plan,
        dispatch_hardware_preview,
        list_hardware_types,
    )
    from relationship_fixtures import build_fixture_snapshots, expected_fixture_cases
    from relationship_report import build_scan_report
    from relationship_service import scan_relationships

    rows = {row["type"]: row for row in list_hardware_types()}
    for hw_type in (HARDWARE_TYPE_HINGE_HOLE, HARDWARE_TYPE_LOCK_CUTOUT, HARDWARE_TYPE_DRAWER_RUNNER_HOLE):
        meta = rows[hw_type]
        if not (meta.get("implemented") and meta.get("cutReady") and not meta.get("previewOnly")):
            return _fail("registry {}".format(hw_type), meta)
    print("[PASS] hinge/lock/runner cutReady")

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

    hinge = dispatch_hardware_preview(
        rel, rule={"type": HARDWARE_TYPE_HINGE_HOLE}, panel_snapshots=panels_payload
    )
    if not hinge.get("ok") or int(hinge.get("holeCount") or 0) < 1:
        return _fail("hinge preview", hinge)
    if hinge.get("previewOnly") or not hinge.get("cutReady"):
        return _fail("hinge flags", hinge)
    print("[PASS] hinge_hole preview cups={}".format(hinge.get("holeCount")))

    lock = dispatch_hardware_preview(
        rel, rule={"type": HARDWARE_TYPE_LOCK_CUTOUT}, panel_snapshots=panels_payload
    )
    if not lock.get("ok"):
        return _fail("lock preview", lock)
    pocket = ((lock.get("features") or [{}])[0].get("geometry") or {}).get("pocket") or {}
    if not pocket.get("depthMm"):
        return _fail("lock pocket", pocket)
    if lock.get("previewOnly") or not lock.get("cutReady"):
        return _fail("lock flags", lock)
    print("[PASS] lock_cutout preview pocket")

    runner = dispatch_hardware_preview(
        rel, rule={"type": HARDWARE_TYPE_DRAWER_RUNNER_HOLE}, panel_snapshots=panels_payload
    )
    if not runner.get("ok") or int(runner.get("holeCount") or 0) < 2:
        return _fail("runner preview", runner)
    if runner.get("previewOnly") or not runner.get("cutReady"):
        return _fail("runner flags", runner)
    print("[PASS] drawer_runner_hole preview holes={}".format(runner.get("holeCount")))

    for hw_type in (HARDWARE_TYPE_HINGE_HOLE, HARDWARE_TYPE_LOCK_CUTOUT, HARDWARE_TYPE_DRAWER_RUNNER_HOLE):
        blocked = dispatch_hardware_cut_plan(rel, rule={"type": hw_type}, panel_snapshots=panels_payload)
        if blocked.get("ok"):
            return _fail("{} cut must block without confirm".format(hw_type), blocked)
    print("[PASS] hinge/lock/runner cut blocked on bbox_candidate")

    confirmed = _confirm(rel)
    for hw_type, op_type in (
        (HARDWARE_TYPE_HINGE_HOLE, "HINGE_HOLE_FROM_RELATIONSHIP"),
        (HARDWARE_TYPE_LOCK_CUTOUT, "LOCK_CUTOUT_FROM_RELATIONSHIP"),
        (HARDWARE_TYPE_DRAWER_RUNNER_HOLE, "DRAWER_RUNNER_HOLE_FROM_RELATIONSHIP"),
    ):
        cut = dispatch_hardware_cut_plan(confirmed, rule={"type": hw_type}, panel_snapshots=panels_payload)
        if not cut.get("ok") or not cut.get("feature") or not cut.get("metadata"):
            return _fail("{} cut plan".format(hw_type), cut)
        if cut.get("metadata", {}).get("operationType") != op_type:
            return _fail("{} metadata".format(hw_type), cut.get("metadata"))
        print("[PASS] {} cut plan after confirm".format(hw_type))

    print()
    print("Scaffold hardware post-M9 offline smoke: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
