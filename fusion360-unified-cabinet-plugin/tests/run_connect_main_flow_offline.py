#!/usr/bin/env python3
"""Offline smoke for Connect main flow (fixture preview path + overhead BP-D0).

Run: python tests/run_connect_main_flow_offline.py
"""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (
    ROOT,
    os.path.join(ROOT, "modules", "relationships"),
    os.path.join(ROOT, "modules", "hardware"),
):
    if path not in sys.path:
        sys.path.insert(0, path)


def _fail(step: str, detail) -> int:
    print("[FAIL] {} -> {}".format(step, detail))
    return 1


def _run_day2_checks() -> int:
    from relationship_fixtures import fixture_panel_definitions
    from relationship_geometry import classify_pair
    from relationship_service import build_panel_snapshot_from_dict
    from connect_formal_ui import evaluate_connect_action
    from face_verification import (
        apply_face_verification_to_relationship,
        verify_fixture_pair_offline,
    )
    from screw_hole_from_relationship import (
        preview_screw_holes_from_relationship,
        validate_relationship_for_cut,
    )

    panel_edge = "REL_EDGE_A"
    panel_surface = "REL_SURFACE_B"
    hw_rule = {
        "type": "screw_hole",
        "diameterMm": 4,
        "edgeOffsetMm": 30,
        "minSpacingMm": 80,
        "depthMode": "host_thickness",
    }
    panel_defs = {item["panelId"]: item for item in fixture_panel_definitions()}

    def to_snapshot(item):
        return build_panel_snapshot_from_dict(
            {
                "panelId": item["panelId"],
                "bodyName": item["bodyName"],
                "boardType": item.get("boardType"),
                "role": item.get("role"),
                "bbox": item["bbox"],
            }
        )

    snap_edge = to_snapshot(panel_defs[panel_edge])
    snap_surface = to_snapshot(panel_defs[panel_surface])
    relationship = classify_pair(snap_edge, snap_surface, tolerance_mm=0.5).to_dict()
    panel_edge_dict = snap_edge.to_dict()
    panel_surface_dict = snap_surface.to_dict()
    panel_snapshots = {panel_surface: panel_surface_dict, panel_edge: panel_edge_dict}

    if evaluate_connect_action("preview", relationship).get("ok") is not True:
        return _fail("fixture preview gate", relationship)
    print("[PASS] fixture preview gate")

    preview = preview_screw_holes_from_relationship(relationship, rule=hw_rule, panel_snapshots=panel_snapshots)
    if not (preview.get("ok") and preview.get("holeCount") == 2):
        return _fail("fixture preview holes", preview)
    print("[PASS] fixture preview 2 holes")

    if evaluate_connect_action("cut", relationship).get("ok") is not False:
        return _fail("fixture cut blocked before confirm", relationship)
    print("[PASS] fixture cut blocked before confirm")

    # Batch B: main Connect face-verify path (same gate as palette 面验证)
    verify_report = verify_fixture_pair_offline(
        panel_edge_dict,
        panel_surface_dict,
        relationship,
        tolerance_mm=0.5,
    )
    if not verify_report.get("ok"):
        return _fail("fixture face verify", verify_report)
    upgraded = apply_face_verification_to_relationship(relationship, verify_report)
    verification = upgraded.get("verification") or {}
    if verification.get("level") != "face_verified" or verification.get("safeForCut") is not True:
        return _fail("fixture face_verified upgrade", upgraded)
    if validate_relationship_for_cut(upgraded) is not None:
        return _fail("fixture face_verified cut gate", upgraded)
    if evaluate_connect_action("cut", upgraded).get("ok") is not True:
        return _fail("fixture cut allowed after face verify", upgraded)
    print("[PASS] fixture face verify -> face_verified cut gate open")
    return 0


def _run_overhead_checks() -> int:
    from generator_bridge_runner import load_params_fixture, run_overhead
    from generator_declared_service import reconcile_generator_declarations
    from generator_panel_adapter import snapshots_from_generator_result
    from overhead_declared_relationships import extract_board_suffix
    from relationship_service import build_panel_snapshot_from_dict
    from screw_hole_from_relationship import preview_screw_holes_from_relationship

    bridge = run_overhead(load_params_fixture("overhead_edge_only.json"))
    snapshots = [
        build_panel_snapshot_from_dict(item)
        for item in snapshots_from_generator_result("overhead", bridge)
    ]
    report = reconcile_generator_declarations(
        snapshots,
        generator="overhead",
        embedded_declarations=bridge.get("relationshipDeclarations") or [],
    )
    if not report.get("ok"):
        return _fail("overhead reconcile", report)

    print("[PASS] overhead reconcile declarations={} geometryOk={}".format(
        report.get("declarationCount"), report.get("geometryOkCount"),
    ))

    rel = None
    for item in report.get("declaredRelationships") or []:
        candidate = item.get("relationship") if isinstance(item.get("relationship"), dict) else item
        panel_a = item.get("panelA") or candidate.get("panelA") or {}
        panel_b = item.get("panelB") or candidate.get("panelB") or {}
        if {extract_board_suffix(panel_a.get("panelId")), extract_board_suffix(panel_b.get("panelId"))} == {"BP", "D0"}:
            rel = candidate
            break
    if not rel:
        return _fail("overhead BP-D0 relationship", report)

    panel_map = {snap.panelId: snap.to_dict() for snap in snapshots}
    host_id = rel["roles"]["hostPanelId"]
    target_id = rel["roles"]["targetPanelId"]
    preview = preview_screw_holes_from_relationship(
        rel,
        panel_snapshots={host_id: panel_map[host_id], target_id: panel_map[target_id]},
    )
    if not preview.get("ok"):
        return _fail("overhead BP-D0 preview", preview)
    print("[PASS] overhead BP-D0 preview holes={}".format(preview.get("holeCount")))
    return 0


def main() -> int:
    code = _run_day2_checks()
    if code != 0:
        return code
    code = _run_overhead_checks()
    if code != 0:
        return code
    print()
    print("Connect main flow offline smoke: ALL PASS")
    print("Next: run connect_main_flow_smoke.py inside Fusion (Scripts and Add-ins).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
