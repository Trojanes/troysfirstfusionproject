#!/usr/bin/env python3
"""Offline smoke: declaration-first Connect pipeline (declare → 3a → 3c)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (
    ROOT,
    os.path.join(ROOT, "modules", "hardware"),
):
    if path not in sys.path:
        sys.path.insert(0, path)


def _fail(step: str, detail) -> int:
    print("[FAIL] {} -> {}".format(step, detail))
    return 1


def main() -> int:
    from connect_pipeline import (
        PIPELINE_ACTION,
        build_pipeline_report,
        merge_pipeline_cut_candidates,
        pipeline_reminder_lines,
        relationship_pair_key,
    )

    if PIPELINE_ACTION != "hardware.runConnectPipeline":
        return _fail("action", PIPELINE_ACTION)

    declared = {
        "relationshipId": "d1",
        "panelA": {"panelId": "A"},
        "panelB": {"panelId": "B"},
        "verification": {"level": "generator_declared", "safeForCut": True},
    }
    face = {
        "relationshipId": "f1",
        "panelA": {"panelId": "B"},
        "panelB": {"panelId": "A"},
        "verification": {"level": "face_verified", "safeForCut": True},
    }
    other = {
        "relationshipId": "f2",
        "panelA": {"panelId": "C"},
        "panelB": {"panelId": "D"},
        "verification": {"level": "face_verified", "safeForCut": True},
    }
    if relationship_pair_key(declared) != ("A", "B"):
        return _fail("pair key", relationship_pair_key(declared))
    merged = merge_pipeline_cut_candidates([declared], [face, other])
    if len(merged) != 2:
        return _fail("merge count", merged)
    preferred = next(item for item in merged if relationship_pair_key(item) == ("A", "B"))
    if preferred.get("relationshipId") != "d1":
        return _fail("declare preferred over face", preferred)
    print("[PASS] merge prefers generator_declared on same pair")

    ok_report = build_pipeline_report(
        declare_report={
            "ok": True,
            "generator": "overhead",
            "declarationCount": 2,
            "geometryOkCount": 2,
            "cutSafeCount": 2,
        },
        verify_report={
            "ok": True,
            "verifiedCount": 1,
            "skippedCount": 1,
            "processedCount": 2,
            "skipped": [{"reason": "not_hardware_eligible"}],
            "reminders": ["验证提醒"],
        },
        cut_report={
            "ok": True,
            "createdCount": 2,
            "skippedCount": 0,
            "processedCount": 2,
            "hardwareType": "screw_hole",
            "hardwareTypeCounts": {"screw_hole": 2},
            "created": [{"relationshipId": "d1"}, {"relationshipId": "f2"}],
            "reminders": ["切削提醒"],
        },
        auto_hardware={"enabled": True},
    )
    if not ok_report.get("ok"):
        return _fail("ok_report.ok", ok_report)
    if not ok_report.get("declarationFirst"):
        return _fail("declarationFirst flag", ok_report)
    if ok_report["declare"]["cutSafeCount"] != 2:
        return _fail("declare count", ok_report["declare"])
    if ok_report["verify"]["verifiedCount"] != 1:
        return _fail("verify count", ok_report["verify"])
    if ok_report["cut"]["createdCount"] != 2:
        return _fail("cut count", ok_report["cut"])
    if not any("生成器声明可切" in line for line in ok_report.get("reminders") or []):
        return _fail("declare reminder", ok_report.get("reminders"))
    if not any("自动选型" in line for line in ok_report.get("reminders") or []):
        return _fail("auto hint", ok_report.get("reminders"))
    print("[PASS] combined declare+verify+cut report")

    declare_only = build_pipeline_report(
        declare_report={"ok": True, "cutSafeCount": 3, "declarationCount": 3, "geometryOkCount": 3},
        verify_report={"ok": False, "errors": ["verify boom"], "verifiedCount": 0, "skippedCount": 0},
        cut_report={"ok": True, "createdCount": 3, "skippedCount": 0, "processedCount": 3},
    )
    if not declare_only.get("ok"):
        return _fail("declare-only should ok when cut ok", declare_only)
    if not any("generator-declared" in w or "Face verify failed" in w for w in declare_only.get("warnings") or []):
        return _fail("verify soft warning", declare_only.get("warnings"))
    print("[PASS] declarations alone survive face-verify failure")

    # Declare "no panels" must not by itself be a hard pipeline error when verify can proceed.
    soft_declare = build_pipeline_report(
        declare_report={
            "ok": False,
            "cutSafeCount": 0,
            "errors": [],
            "warnings": ["未从声明路径扫到面板元数据，继续尝试面验证。"],
        },
        verify_report={"ok": True, "verifiedCount": 1, "skippedCount": 0, "processedCount": 1},
        cut_report={"ok": True, "createdCount": 1, "skippedCount": 0, "processedCount": 1},
    )
    if not soft_declare.get("ok"):
        return _fail("soft declare + verify should ok", soft_declare)
    print("[PASS] soft declare empty panels + verify still ok")

    verify_fail = build_pipeline_report(
        declare_report={"ok": False, "cutSafeCount": 0, "errors": ["No declarations"]},
        verify_report={"ok": False, "errors": ["verify boom"], "verifiedCount": 0, "skippedCount": 0},
        cut_report=None,
        auto_hardware={"enabled": False},
    )
    if verify_fail.get("ok"):
        return _fail("verify_fail should not ok", verify_fail)
    if "verify boom" not in " ".join(verify_fail.get("errors") or []):
        return _fail("verify errors", verify_fail.get("errors"))
    print("[PASS] verify failure with no declarations short-circuits cut")

    missing_cut = build_pipeline_report(
        declare_report={"cutSafeCount": 1},
        verify_report={"ok": True, "verifiedCount": 0, "skippedCount": 0},
        cut_report=None,
    )
    if missing_cut.get("ok"):
        return _fail("missing cut should fail", missing_cut)
    if not any("Missing batch cut" in err for err in missing_cut.get("errors") or []):
        return _fail("missing cut error", missing_cut.get("errors"))
    print("[PASS] missing cut stage fails")

    empty_ok = build_pipeline_report(
        declare_report={"cutSafeCount": 0},
        verify_report={"ok": True, "verifiedCount": 0, "skippedCount": 2, "processedCount": 2},
        cut_report={"ok": True, "createdCount": 0, "skippedCount": 0, "processedCount": 0},
        auto_hardware={"enabled": False},
    )
    if not empty_ok.get("ok"):
        return _fail("empty candidates should still ok", empty_ok)
    lines = pipeline_reminder_lines(
        declared_count=0,
        verified_count=0,
        verify_skipped=2,
        created_count=0,
        cut_skipped=0,
        auto_enabled=False,
    )
    if not any("没有可切削接头" in line for line in lines):
        return _fail("empty reminder", lines)
    print("[PASS] zero-candidate pipeline still ok + hint")

    plugin_path = os.path.join(ROOT, "UnifiedCabinetPlugin.py")
    with open(plugin_path, "r", encoding="utf-8") as handle:
        plugin = handle.read()
    if "hardware.runConnectPipeline" not in plugin:
        return _fail("plugin route missing", "hardware.runConnectPipeline")
    print("[PASS] plugin route registered")

    controller_path = os.path.join(ROOT, "modules", "hardware", "controller.py")
    with open(controller_path, "r", encoding="utf-8") as handle:
        controller = handle.read()
    for token in (
        "RelationshipsController",
        "reconcile_generator_declarations",
        "merge_pipeline_cut_candidates",
        "filter_cut_safe_hardware_candidates",
    ):
        if token not in controller:
            return _fail("controller missing", token)
    print("[PASS] controller declaration-first wiring")

    palette_path = os.path.join(ROOT, "palette.html")
    with open(palette_path, "r", encoding="utf-8") as handle:
        palette = handle.read()
    for token in (
        'id="connectPipelineBtn"',
        "connectUiRunConnectPipeline",
        "connectUiHandlePipelineResult",
        "hardware.runConnectPipeline",
        "hardwarePipelineResult",
        "生成器声明",
    ):
        if token not in palette:
            return _fail("palette missing", token)
    print("[PASS] palette pipeline UI wired")

    print("")
    print("Connect pipeline offline: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
