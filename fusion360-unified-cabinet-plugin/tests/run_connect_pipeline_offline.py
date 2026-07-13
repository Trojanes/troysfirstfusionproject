#!/usr/bin/env python3
"""Offline smoke: one-click Connect pipeline report (3a + 3c shell)."""

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
    from connect_pipeline import PIPELINE_ACTION, build_pipeline_report, pipeline_reminder_lines

    if PIPELINE_ACTION != "hardware.runConnectPipeline":
        return _fail("action", PIPELINE_ACTION)

    ok_report = build_pipeline_report(
        verify_report={
            "ok": True,
            "verifiedCount": 2,
            "skippedCount": 1,
            "processedCount": 3,
            "skipped": [{"reason": "not_hardware_eligible"}],
            "reminders": ["验证提醒"],
        },
        cut_report={
            "ok": True,
            "createdCount": 1,
            "skippedCount": 1,
            "processedCount": 2,
            "hardwareType": "screw_hole",
            "hardwareTypeCounts": {"screw_hole": 1},
            "created": [{"relationshipId": "r1", "cutFeatureName": "cut1"}],
            "skipped": [{"reason": "cut_failed"}],
            "reminders": ["切削提醒"],
        },
        auto_hardware={"enabled": True},
    )
    if not ok_report.get("ok"):
        return _fail("ok_report.ok", ok_report)
    if ok_report.get("action") != PIPELINE_ACTION:
        return _fail("ok_report.action", ok_report.get("action"))
    if ok_report["verify"]["verifiedCount"] != 2:
        return _fail("verify count", ok_report["verify"])
    if ok_report["cut"]["createdCount"] != 1:
        return _fail("cut count", ok_report["cut"])
    if ok_report["cut"]["hardwareTypeCounts"].get("screw_hole") != 1:
        return _fail("type counts", ok_report["cut"])
    if len(ok_report.get("skipped") or []) != 2:
        return _fail("merged skipped", ok_report.get("skipped"))
    if not any("流水线" in line for line in ok_report.get("reminders") or []):
        return _fail("pipeline reminder", ok_report.get("reminders"))
    if not any("自动选型" in line for line in ok_report.get("reminders") or []):
        return _fail("auto hint", ok_report.get("reminders"))
    print("[PASS] combined ok pipeline report")

    verify_fail = build_pipeline_report(
        verify_report={"ok": False, "errors": ["verify boom"], "verifiedCount": 0, "skippedCount": 0},
        cut_report=None,
        auto_hardware={"enabled": False},
    )
    if verify_fail.get("ok"):
        return _fail("verify_fail should not ok", verify_fail)
    if "verify boom" not in " ".join(verify_fail.get("errors") or []):
        return _fail("verify errors", verify_fail.get("errors"))
    print("[PASS] verify failure short-circuits cut")

    missing_cut = build_pipeline_report(
        verify_report={"ok": True, "verifiedCount": 0, "skippedCount": 0},
        cut_report=None,
    )
    if missing_cut.get("ok"):
        return _fail("missing cut should fail", missing_cut)
    if not any("Missing batch cut" in err for err in missing_cut.get("errors") or []):
        return _fail("missing cut error", missing_cut.get("errors"))
    print("[PASS] missing cut stage fails")

    empty_ok = build_pipeline_report(
        verify_report={"ok": True, "verifiedCount": 0, "skippedCount": 2, "processedCount": 2},
        cut_report={"ok": True, "createdCount": 0, "skippedCount": 0, "processedCount": 0},
        auto_hardware={"enabled": False},
    )
    if not empty_ok.get("ok"):
        return _fail("empty candidates should still ok", empty_ok)
    lines = pipeline_reminder_lines(
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

    palette_path = os.path.join(ROOT, "palette.html")
    with open(palette_path, "r", encoding="utf-8") as handle:
        palette = handle.read()
    for token in (
        'id="connectPipelineBtn"',
        "connectUiRunConnectPipeline",
        "connectUiHandlePipelineResult",
        "hardware.runConnectPipeline",
        "hardwarePipelineResult",
    ):
        if token not in palette:
            return _fail("palette missing", token)
    print("[PASS] palette pipeline UI wired")

    print("")
    print("Connect pipeline offline: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
