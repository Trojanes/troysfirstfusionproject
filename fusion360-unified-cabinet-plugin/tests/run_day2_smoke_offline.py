#!/usr/bin/env python3
"""Offline smoke for Day 2 — Connect main UI preview screw holes (no Fusion).

Validates preview is allowed on bbox_candidate and returns stable hole parameters
before manual confirm / cut.

Run: python tests/run_day2_smoke_offline.py
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


def _fixture_relationship():
    from relationship_fixtures import fixture_panel_definitions
    from relationship_geometry import classify_pair
    from relationship_service import build_panel_snapshot_from_dict

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

    snap_edge = to_snapshot(panel_defs[PANEL_EDGE])
    snap_surface = to_snapshot(panel_defs[PANEL_SURFACE])
    relationship = classify_pair(snap_edge, snap_surface, tolerance_mm=0.5).to_dict()
    panel_snapshots = {
        PANEL_SURFACE: snap_surface.to_dict(),
        PANEL_EDGE: snap_edge.to_dict(),
    }
    return relationship, panel_snapshots


def main() -> int:
    relationship, panel_snapshots = _fixture_relationship()
    verification = relationship.get("verification") or {}

    if verification.get("level") != "bbox_candidate" or verification.get("safeForPreview") is not True:
        return _fail("1 bbox_candidate previewable", verification)
    print("[PASS] 1 relationship is bbox_candidate and safeForPreview")

    from connect_formal_ui import evaluate_connect_action

    preview_gate = evaluate_connect_action("preview", relationship)
    if preview_gate.get("ok") is not True:
        return _fail("2 preview gate", preview_gate)
    print("[PASS] 2 connect preview gate open on bbox_candidate")

    cut_gate = evaluate_connect_action("cut", relationship)
    if cut_gate.get("ok") is not False:
        return _fail("3 cut still blocked before confirm", cut_gate)
    print("[PASS] 3 cut still blocked before confirm")

    from screw_hole_from_relationship import preview_screw_holes_from_relationship

    preview = preview_screw_holes_from_relationship(
        relationship, rule=dict(HW_RULE), panel_snapshots=panel_snapshots
    )
    audit = preview.get("audit") or {}
    ok = (
        preview.get("ok") is True
        and preview.get("holeCount") == 2
        and preview.get("hostPanelId") == PANEL_SURFACE
        and preview.get("targetPanelId") == PANEL_EDGE
        and audit.get("diameterMm") == 4
        and audit.get("edgeOffsetMm") == 30
        and len(audit.get("positions") or []) == 2
    )
    if not ok:
        return _fail("4 preview screw holes", preview)
    print(
        "[PASS] 4 preview holes={} diameter={} mm edgeOffset={} mm positions={}".format(
            preview.get("holeCount"),
            audit.get("diameterMm"),
            audit.get("edgeOffsetMm"),
            len(audit.get("positions") or []),
        )
    )

    print()
    print("Day 2 offline smoke: ALL PASS")
    print("Next: run day2_connect_smoke.py inside Fusion (Scripts and Add-ins).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
