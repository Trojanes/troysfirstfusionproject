#!/usr/bin/env python3
"""Offline smoke for post-M9 tongue/groove preview + host groove + target tongue plan."""

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
        HARDWARE_TYPE_TONGUE_GROOVE,
        dispatch_hardware_cut_plan,
        dispatch_hardware_preview,
        list_hardware_types,
    )
    from panel_metadata_writeback import build_tongue_groove_panel_feature_record
    from relationship_fixtures import build_fixture_snapshots, expected_fixture_cases
    from relationship_models import confirm_relationship_for_cut
    from relationship_report import build_scan_report
    from relationship_service import scan_relationships
    from tongue_groove_from_relationship import plan_tongue_groove_cut_from_relationship

    rows = list_hardware_types()
    tongue = next(row for row in rows if row["type"] == HARDWARE_TYPE_TONGUE_GROOVE)
    if not (tongue.get("implemented") and tongue.get("cutReady") and not tongue.get("previewOnly")):
        return _fail("registry tongue_groove flags", tongue)
    print("[PASS] tongue_groove registry implemented + cutReady")

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
    rule = {"type": HARDWARE_TYPE_TONGUE_GROOVE, "grooveDepthMm": 8, "tongueProtrusionMm": 7}

    preview = dispatch_hardware_preview(rel, rule=rule, panel_snapshots=panels_payload)
    if not preview.get("ok"):
        return _fail("tongue_groove preview", preview)
    feature = (preview.get("features") or [{}])[0]
    if feature.get("hostRole") != "groove" or feature.get("targetRole") != "tongue":
        return _fail("tongue_groove roles", feature)
    groove_sketch = ((feature.get("geometry") or {}).get("groove") or {}).get("sketch") or {}
    tongue_sketch = ((feature.get("geometry") or {}).get("tongue") or {}).get("sketch") or {}
    if not groove_sketch.get("depthMm") or not groove_sketch.get("lengthAxis"):
        return _fail("tongue_groove groove.sketch", groove_sketch)
    if not tongue_sketch.get("shoulders"):
        return _fail("tongue_groove tongue.sketch.shoulders", tongue_sketch)
    if ((feature.get("geometry") or {}).get("tongue") or {}).get("cutDeferred"):
        return _fail("tongue must not be deferred", feature.get("geometry"))
    print("[PASS] tongue_groove preview host groove + target tongue shoulders")

    blocked = dispatch_hardware_cut_plan(rel, rule=rule, panel_snapshots=panels_payload)
    if blocked.get("ok"):
        return _fail("bbox cut must stay blocked", blocked)
    print("[PASS] tongue_groove cut blocked without verification")

    confirmed = confirm_relationship_for_cut(rel)
    plan = plan_tongue_groove_cut_from_relationship(confirmed, rule=rule, panel_snapshots=panels_payload)
    if not plan.get("ok"):
        return _fail("tongue_groove cut plan", plan)
    meta = plan.get("metadata") or {}
    if meta.get("tongueCutDeferred"):
        return _fail("tongueCutDeferred must be false", meta)
    if int(meta.get("tongueShoulderCount") or 0) < 1:
        return _fail("tongueShoulderCount", meta)
    dispatched = dispatch_hardware_cut_plan(confirmed, rule=rule, panel_snapshots=panels_payload)
    if not dispatched.get("ok"):
        return _fail("dispatch cut plan after confirm", dispatched)
    print("[PASS] tongue_groove cut plan after confirm (groove + tongue)")

    groove_record = build_tongue_groove_panel_feature_record(
        plan.get("feature") or {},
        cut_metadata=meta,
        cut_feature_name="HW_REL_TONGUE_GROOVE_TEST",
        role="groove",
    )
    tongue_record = build_tongue_groove_panel_feature_record(
        plan.get("feature") or {},
        cut_metadata=meta,
        cut_feature_name="HW_REL_TONGUE_SHOULDER_TEST",
        role="tongue",
    )
    if groove_record.get("kind") != "groove" or tongue_record.get("kind") != "tongue":
        return _fail("writeback records", {"groove": groove_record, "tongue": tongue_record})
    if groove_record.get("tongueCutDeferred") or tongue_record.get("tongueCutDeferred"):
        return _fail("writeback deferred flags", {"groove": groove_record, "tongue": tongue_record})
    print("[PASS] tongue_groove panel writeback records groove + tongue")

    print()
    print("Tongue/groove post-M9 offline smoke: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
