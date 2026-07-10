#!/usr/bin/env python3
"""Offline pre-check for day1_connect_smoke.py (no Fusion required).

Validates the same pipeline logic the Fusion script exercises:

  1. fixture definitions contain REL_EDGE_A / REL_SURFACE_B pair
  2. classification: edge_to_surface + structural_butt_joint + bbox_candidate
  3. contact patch generated with positive area, host/target correct
  4. connect gate blocks cut on bbox_candidate
  5. connect gate confirm -> manual_confirmed, safeForCut=true
  6. screw-hole cut plan: 2 holes, metadata stable

Run: python tests/run_day1_smoke_offline.py
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

PANEL_EDGE = "REL_EDGE_A"
PANEL_SURFACE = "REL_SURFACE_B"

HW_RULE = {
    "type": "screw_hole",
    "diameterMm": 4,
    "edgeOffsetMm": 30,
    "minSpacingMm": 80,
    "depthMode": "host_thickness",
}


def _fail(step: str, detail) -> int:
    print("[FAIL] {} -> {}".format(step, detail))
    return 1


def main() -> int:
    from relationship_fixtures import fixture_panel_definitions
    from relationship_geometry import classify_pair
    from relationship_service import build_panel_snapshot_from_dict

    # Step 1 — fixture definitions
    panel_defs = {item["panelId"]: item for item in fixture_panel_definitions()}
    if PANEL_EDGE not in panel_defs or PANEL_SURFACE not in panel_defs:
        return _fail("1 fixture definitions", sorted(panel_defs))
    print("[PASS] 1 fixture definitions ({} panels)".format(len(panel_defs)))

    # Step 2 — classification
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

    snap_edge = to_snapshot(panel_defs[PANEL_EDGE])
    snap_surface = to_snapshot(panel_defs[PANEL_SURFACE])
    relationship = classify_pair(snap_edge, snap_surface, tolerance_mm=0.5).to_dict()

    verification = relationship.get("verification") or {}
    roles = relationship.get("roles") or {}
    ok = (
        relationship.get("geometryType") == "edge_to_surface"
        and relationship.get("relationshipType") == "structural_butt_joint"
        and verification.get("level") == "bbox_candidate"
        and verification.get("safeForCut") is False
        and roles.get("hostPanelId") == PANEL_SURFACE
        and roles.get("targetPanelId") == PANEL_EDGE
    )
    if not ok:
        return _fail("2 classification", relationship)
    print("[PASS] 2 classification edge_to_surface / structural_butt_joint / bbox_candidate")

    # Step 3 — contact patch
    from contact_patch import build_contact_patch_from_relationship

    patch_result = build_contact_patch_from_relationship(
        relationship, snap_edge.to_dict(), snap_surface.to_dict()
    )
    patch = patch_result.get("contactPatch") or {}
    ok = (
        patch_result.get("ok") is True
        and float(patch.get("contactAreaMm2") or 0) > 0
        and patch.get("hostPanelId") == PANEL_SURFACE
        and patch.get("targetPanelId") == PANEL_EDGE
    )
    if not ok:
        return _fail("3 contact patch", patch_result)
    print(
        "[PASS] 3 contact patch area={} mm2 axis={}".format(
            patch.get("contactAreaMm2"), patch.get("contactAxis")
        )
    )

    # Step 4 — cut blocked on bbox_candidate
    from connect_formal_ui import evaluate_connect_action

    blocked = evaluate_connect_action("cut", relationship)
    if blocked.get("ok") is not False:
        return _fail("4 bbox cut blocked", blocked)
    print("[PASS] 4 bbox_candidate cut blocked")

    # Step 5 — confirm -> manual_confirmed
    confirm_gate = evaluate_connect_action("confirm", relationship)
    confirmed = confirm_gate.get("confirmedRelationship")
    confirmed_verification = (confirmed or {}).get("verification") or {}
    ok = (
        confirm_gate.get("ok") is True
        and confirmed_verification.get("level") == "manual_confirmed"
        and confirmed_verification.get("safeForCut") is True
    )
    if not ok:
        return _fail("5 confirm", confirm_gate)
    cut_gate = evaluate_connect_action("cut", confirmed)
    if cut_gate.get("ok") is not True:
        return _fail("5b confirmed cut gate", cut_gate)
    print("[PASS] 5 confirm -> manual_confirmed, cut gate open")

    # Step 6 — screw-hole plan
    from screw_hole_from_relationship import plan_screw_hole_cut_from_relationship

    panel_snapshots = {
        PANEL_SURFACE: snap_surface.to_dict(),
        PANEL_EDGE: snap_edge.to_dict(),
    }
    plan = plan_screw_hole_cut_from_relationship(
        confirmed, rule=dict(HW_RULE), panel_snapshots=panel_snapshots
    )
    metadata = plan.get("metadata") or {}
    ok = (
        plan.get("ok") is True
        and plan.get("hostPanelId") == PANEL_SURFACE
        and plan.get("targetPanelId") == PANEL_EDGE
        and metadata.get("holeCount") == 2
        and metadata.get("diameterMm") == 4
    )
    if not ok:
        return _fail("6 screw-hole plan", plan)
    print(
        "[PASS] 6 screw-hole plan holes={} diameter={} mm host={}".format(
            metadata.get("holeCount"), metadata.get("diameterMm"), plan.get("hostPanelId")
        )
    )

    print()
    print("Day 1 offline smoke: ALL PASS")
    print("Next: run day1_connect_smoke.py inside Fusion (Scripts and Add-Ins -> Scripts).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
