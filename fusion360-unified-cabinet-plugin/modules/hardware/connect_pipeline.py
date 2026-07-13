"""One-click Connect pipeline: verify-all (3a) then batch cut (3c)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

PIPELINE_ACTION = "hardware.runConnectPipeline"


def pipeline_reminder_lines(
    *,
    verified_count: int,
    verify_skipped: int,
    created_count: int,
    cut_skipped: int,
    auto_enabled: bool,
) -> List[str]:
    lines: List[str] = []
    lines.append(
        "流水线：面验证通过 {} · 验证跳过 {} · 五金创建 {} · 切削跳过 {}{}.".format(
            verified_count,
            verify_skipped,
            created_count,
            cut_skipped,
            "（自动选型）" if auto_enabled else "",
        )
    )
    if verified_count == 0 and created_count == 0:
        lines.append("没有可切削接头。可先启用缝隙接头，或检查板件是否已扫描。")
    return lines


def build_pipeline_report(
    *,
    verify_report: Optional[Dict[str, Any]],
    cut_report: Optional[Dict[str, Any]],
    auto_hardware: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Combine 3a + 3c reports into one pipeline result (offline-testable)."""
    verify = verify_report if isinstance(verify_report, dict) else {}
    cut = cut_report if isinstance(cut_report, dict) else {}
    auto = auto_hardware if isinstance(auto_hardware, dict) else {}
    verify_ok = bool(verify.get("ok"))
    cut_ok = bool(cut.get("ok")) if cut else False

    verified_count = int(verify.get("verifiedCount") or 0)
    verify_skipped = int(verify.get("skippedCount") or 0)
    created_count = int(cut.get("createdCount") or 0)
    cut_skipped = int(cut.get("skippedCount") or 0)

    errors: List[str] = []
    if verify and not verify_ok:
        errors.extend(list(verify.get("errors") or ["Batch face verify failed."]))
    if cut and not cut_ok:
        errors.extend(list(cut.get("errors") or ["Batch hardware cut failed."]))

    ok = verify_ok and (cut_ok if cut else False)
    # Verify-only success with zero candidates still ok for pipeline shell;
    # cut may legitimately create 0.
    if verify_ok and cut and cut_ok:
        ok = True
    elif verify_ok and not cut:
        ok = False
        errors.append("Missing batch cut stage.")

    reminders = pipeline_reminder_lines(
        verified_count=verified_count,
        verify_skipped=verify_skipped,
        created_count=created_count,
        cut_skipped=cut_skipped,
        auto_enabled=bool(auto.get("enabled")),
    )
    for line in list(verify.get("reminders") or []) + list(cut.get("reminders") or []):
        if line and line not in reminders:
            reminders.append(line)

    skipped = list(verify.get("skipped") or []) + list(cut.get("skipped") or [])

    return {
        "ok": ok,
        "action": PIPELINE_ACTION,
        "cutGateUnchanged": True,
        "verify": {
            "ok": verify_ok,
            "verifiedCount": verified_count,
            "skippedCount": verify_skipped,
            "processedCount": int(verify.get("processedCount") or 0),
        },
        "cut": {
            "ok": cut_ok,
            "createdCount": created_count,
            "skippedCount": cut_skipped,
            "hardwareType": cut.get("hardwareType"),
            "hardwareTypeCounts": cut.get("hardwareTypeCounts") or {},
            "processedCount": int(cut.get("processedCount") or 0),
        },
        "created": list(cut.get("created") or []),
        "skipped": skipped,
        "reminders": reminders,
        "errors": errors,
        "autoHardware": auto,
    }
