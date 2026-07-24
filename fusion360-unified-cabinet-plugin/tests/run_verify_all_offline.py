#!/usr/bin/env python3
"""Offline smoke: batch face-verify bbox candidates (3a skip + remind)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (
    ROOT,
    os.path.join(ROOT, "modules", "hardware"),
    os.path.join(ROOT, "modules", "relationships"),
):
    if path not in sys.path:
        sys.path.insert(0, path)


def _fail(step: str, detail) -> int:
    print("[FAIL] {} -> {}".format(step, detail))
    return 1


def main() -> int:
    from connect_formal_ui import evaluate_connect_action, is_cut_allowed
    from face_verification import filter_face_verifiable_candidates, verify_all_bbox_candidates
    from relationship_fixtures import build_fixture_snapshots
    from relationship_service import scan_relationships
    from screw_hole_from_relationship import assert_safe_for_cut

    panels = build_fixture_snapshots()
    panel_list, relationships = scan_relationships(panels, include_none=False)
    panel_map = {panel.panelId: panel.to_dict() for panel in panel_list}
    rels = [rel.to_dict() for rel in relationships]

    candidates = filter_face_verifiable_candidates(rels)
    if not candidates:
        return _fail("filter candidates", "expected at least one contact hardware bbox candidate")
    print("[PASS] filter candidates={}".format(len(candidates)))
    geometries = sorted({str(item.get("geometryType") or "") for item in candidates})
    print("[PASS] candidate geometries={}".format(geometries))

    # Unfiltered bbox must still be blocked for cut
    sample = candidates[0]
    if assert_safe_for_cut(sample) is None or is_cut_allowed(sample):
        return _fail("bbox still blocked", sample.get("verification"))
    print("[PASS] bbox_candidate cut blocked before batch")

    report = verify_all_bbox_candidates(rels, panel_map)
    if not report.get("ok") or not report.get("cutGateUnchanged"):
        return _fail("batch report", report)
    if int(report.get("verifiedCount") or 0) < 1:
        return _fail("verifiedCount", report)
    if not report.get("reminders"):
        return _fail("reminders", report)
    print(
        "[PASS] batch verified={} skipped={} reminders={}".format(
            report.get("verifiedCount"),
            report.get("skippedCount"),
            len(report.get("reminders") or []),
        )
    )

    upgraded = (report.get("verifiedRelationships") or [])[0]
    cut_gate = evaluate_connect_action("cut", upgraded)
    if not cut_gate.get("ok") or not is_cut_allowed(upgraded):
        return _fail("verified cut-safe", cut_gate)
    print("[PASS] face_verified cut allowed")

    # Cap path
    padded = list(candidates) + [dict(candidates[0], relationshipId="rel.cap.offline")]
    capped = verify_all_bbox_candidates(padded, panel_map, max_pairs=1)
    if not any(item.get("reason") == "cap_reached" for item in (capped.get("skipped") or [])):
        return _fail("cap_reached", capped)
    print("[PASS] maxPairs cap skips overflow")

    print("")
    print("Verify-all offline: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
