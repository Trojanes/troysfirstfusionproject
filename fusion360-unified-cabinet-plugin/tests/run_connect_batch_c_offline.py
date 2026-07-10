#!/usr/bin/env python3
"""Offline smoke for Batch C: dual-path confirm vs face_verified + overhead pairs.

Run: python tests/run_connect_batch_c_offline.py
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


def _run_dual_path_fixture() -> int:
    from connect_formal_ui import evaluate_connect_action
    from face_verification import (
        apply_face_verification_to_relationship,
        verify_fixture_pair_offline,
    )
    from relationship_fixtures import fixture_panel_definitions
    from relationship_geometry import classify_pair
    from relationship_service import build_panel_snapshot_from_dict
    from screw_hole_from_relationship import (
        preview_screw_holes_from_relationship,
        validate_relationship_for_cut,
    )

    panel_defs = {item["panelId"]: item for item in fixture_panel_definitions()}
    edge = build_panel_snapshot_from_dict(panel_defs["REL_EDGE_A"]).to_dict()
    surface = build_panel_snapshot_from_dict(panel_defs["REL_SURFACE_B"]).to_dict()
    relationship = classify_pair(
        build_panel_snapshot_from_dict(panel_defs["REL_EDGE_A"]),
        build_panel_snapshot_from_dict(panel_defs["REL_SURFACE_B"]),
        tolerance_mm=0.5,
    ).to_dict()
    panels = {"REL_EDGE_A": edge, "REL_SURFACE_B": surface}

    if evaluate_connect_action("cut", relationship).get("ok") is not False:
        return _fail("bbox cut blocked", relationship)
    print("[PASS] dual-path: bbox_candidate cut blocked")

    confirm = evaluate_connect_action("confirm", relationship)
    confirmed = confirm.get("confirmedRelationship")
    if not (confirm.get("ok") and (confirmed or {}).get("verification", {}).get("level") == "manual_confirmed"):
        return _fail("confirm path", confirm)
    if validate_relationship_for_cut(confirmed) is not None:
        return _fail("confirm cut gate", confirmed)
    if evaluate_connect_action("cut", confirmed).get("ok") is not True:
        return _fail("confirm cut allowed", confirmed)
    print("[PASS] dual-path: confirm -> manual_confirmed cut gate open")

    verify_report = verify_fixture_pair_offline(edge, surface, relationship, tolerance_mm=0.5)
    if not verify_report.get("ok"):
        return _fail("face verify", verify_report)
    upgraded = apply_face_verification_to_relationship(relationship, verify_report)
    if (upgraded.get("verification") or {}).get("level") != "face_verified":
        return _fail("face_verified upgrade", upgraded)
    if validate_relationship_for_cut(upgraded) is not None:
        return _fail("face_verified cut gate", upgraded)
    if evaluate_connect_action("cut", upgraded).get("ok") is not True:
        return _fail("face_verified cut allowed", upgraded)
    preview = preview_screw_holes_from_relationship(upgraded, panel_snapshots=panels)
    if not (preview.get("ok") and int(preview.get("holeCount") or 0) >= 1):
        return _fail("face_verified preview", preview)
    print("[PASS] dual-path: face_verified cut gate open + preview")
    return 0


def _run_overhead_pairs() -> int:
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

    panel_map = {snap.panelId: snap.to_dict() for snap in snapshots}
    wanted = ({"BP", "D0"}, {"BP", "FP0"})
    found = []
    for item in report.get("declaredRelationships") or []:
        rel = item.get("relationship") if isinstance(item.get("relationship"), dict) else item
        roles = (rel or {}).get("roles") or {}
        suffixes = {
            extract_board_suffix(roles.get("hostPanelId")),
            extract_board_suffix(roles.get("targetPanelId")),
        }
        if suffixes in wanted:
            found.append((frozenset(suffixes), rel))

    if len(found) < 2:
        return _fail("overhead pairs BP-D0/BP-FP0", [list(item[0]) for item in found])

    for suffixes, rel in found:
        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        preview = preview_screw_holes_from_relationship(
            rel,
            panel_snapshots={host_id: panel_map[host_id], target_id: panel_map[target_id]},
        )
        label = "-".join(sorted(suffixes))
        if not (preview.get("ok") and int(preview.get("holeCount") or 0) >= 1):
            return _fail("overhead {} preview".format(label), preview)
        print("[PASS] overhead {} preview holes={}".format(label, preview.get("holeCount")))
    return 0


def main() -> int:
    code = _run_dual_path_fixture()
    if code != 0:
        return code
    code = _run_overhead_pairs()
    if code != 0:
        return code
    print()
    print("Connect Batch C offline smoke: ALL PASS")
    print("Next: run connect_batch_c_smoke.py inside Fusion (Scripts and Add-ins).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
