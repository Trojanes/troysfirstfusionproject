#!/usr/bin/env python3
"""Offline smoke: 3c batch cut-safe hardware candidate filter + reminders."""

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
    from batch_hardware_from_relationships import (
        DEFAULT_BATCH_CUT_MAX_PAIRS,
        batch_cut_reminder_lines,
        filter_cut_safe_hardware_candidates,
    )
    from relationship_fixtures import build_fixture_snapshots
    from relationship_service import scan_relationships
    from relationship_verification_store import (
        build_persisted_verification_record,
        hydrate_relationships_from_panel_metadata,
        upsert_relationship_verification,
    )
    from screw_hole_from_relationship import assert_safe_for_cut

    if DEFAULT_BATCH_CUT_MAX_PAIRS != 50:
        return _fail("default maxPairs", DEFAULT_BATCH_CUT_MAX_PAIRS)

    panels = build_fixture_snapshots()
    _plist, relationships = scan_relationships(panels, include_none=False)
    rels = [rel.to_dict() for rel in relationships]

    empty = filter_cut_safe_hardware_candidates(rels)
    if empty:
        return _fail("bbox should not be cut-safe candidates", len(empty))
    print("[PASS] bbox candidates excluded from batch cut")

    edge = next(rel for rel in rels if rel.get("geometryType") == "edge_to_surface")
    if assert_safe_for_cut(edge) is None:
        return _fail("expected bbox blocked", edge.get("verification"))

    rid = edge["relationshipId"]
    panel_a = (edge.get("panelA") or {}).get("panelId")
    record = build_persisted_verification_record(edge, for_panel_id=panel_a)
    meta = upsert_relationship_verification({"schemaVersion": 1, "features": []}, rid, record)
    hydrated = hydrate_relationships_from_panel_metadata(rels, {panel_a: meta})
    candidates = filter_cut_safe_hardware_candidates(hydrated)
    if len(candidates) < 1:
        return _fail("face_verified should be cut-safe candidate", candidates)
    print("[PASS] face_verified edge_to_surface enters batch cut pool ({})".format(len(candidates)))

    s2s = next((rel for rel in rels if rel.get("geometryType") == "surface_to_surface"), None)
    if s2s is not None:
        s2s_id = s2s["relationshipId"]
        s2s_panel = (s2s.get("panelA") or {}).get("panelId")
        s2s_record = build_persisted_verification_record(s2s, for_panel_id=s2s_panel)
        s2s_meta = upsert_relationship_verification({"schemaVersion": 1, "features": []}, s2s_id, s2s_record)
        s2s_hydrated = hydrate_relationships_from_panel_metadata(rels, {s2s_panel: s2s_meta})
        s2s_candidates = [
            item
            for item in filter_cut_safe_hardware_candidates(s2s_hydrated)
            if item.get("geometryType") == "surface_to_surface"
        ]
        if len(s2s_candidates) < 1:
            return _fail("face_verified surface_to_surface should enter batch cut", s2s_candidates)
        print("[PASS] face_verified surface_to_surface enters batch cut pool ({})".format(len(s2s_candidates)))
    else:
        print("[PASS] no surface_to_surface in fixture (skipped S2S pool check)")

    reminders = batch_cut_reminder_lines(
        hardware_type="screw_hole",
        created_count=1,
        skipped=[{"reason": "cut_failed"}],
        capped=False,
        candidate_count=1,
    )
    if not any("批量创建" in line for line in reminders):
        return _fail("reminders", reminders)
    if not any("跳过" in line for line in reminders):
        return _fail("skip reminder", reminders)
    print("[PASS] batch cut reminders")

    from batch_hardware_from_relationships import repair_hint_for_skip_reason

    hint_cut = repair_hint_for_skip_reason("cut_failed")
    if "预览" not in hint_cut or "创建" not in hint_cut:
        return _fail("cut_failed hint", hint_cut)
    hint_face = repair_hint_for_skip_reason("no_opposing_faces")
    if "面验证" not in hint_face:
        return _fail("face skip hint", hint_face)
    print("[PASS] repair hints for skip reasons")

    palette_path = os.path.join(ROOT, "palette.html")
    with open(palette_path, "r", encoding="utf-8") as handle:
        palette = handle.read()
    for token in (
        "connectUiRepairFromSkip",
        "connectUiRepairHint",
        "connect-skip-repair-btn",
        "relationships.inspectPair",
        "跳过与手修列表",
    ):
        if token not in palette:
            return _fail("palette repair missing", token)
    print("[PASS] palette skip→repair wiring")

    print("")
    print("Batch hardware cut offline: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
