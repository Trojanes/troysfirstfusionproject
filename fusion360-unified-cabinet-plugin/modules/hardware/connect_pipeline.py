"""One-click Connect pipeline: declare → verify-all (3a) → batch cut (3c)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

PIPELINE_ACTION = "hardware.runConnectPipeline"


def relationship_pair_key(relationship: Dict[str, Any]) -> Tuple[str, str]:
    panel_a = str((relationship.get("panelA") or {}).get("panelId") or "").strip()
    panel_b = str((relationship.get("panelB") or {}).get("panelId") or "").strip()
    if panel_a <= panel_b:
        return (panel_a, panel_b)
    return (panel_b, panel_a)


def merge_pipeline_cut_candidates(
    declared_cut_safe: Optional[List[Dict[str, Any]]] = None,
    face_verified: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Union cut pools; same panel-pair prefers generator_declared over face_verified."""
    by_pair: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for relationship in face_verified or []:
        if not isinstance(relationship, dict):
            continue
        key = relationship_pair_key(relationship)
        if not key[0] or not key[1]:
            continue
        by_pair[key] = relationship
    for relationship in declared_cut_safe or []:
        if not isinstance(relationship, dict):
            continue
        key = relationship_pair_key(relationship)
        if not key[0] or not key[1]:
            continue
        by_pair[key] = relationship
    return list(by_pair.values())


def pipeline_reminder_lines(
    *,
    declared_count: int,
    verified_count: int,
    verify_skipped: int,
    created_count: int,
    cut_skipped: int,
    auto_enabled: bool,
) -> List[str]:
    lines: List[str] = []
    lines.append(
        "流水线：生成器声明可切 {} · 面验证通过 {} · 验证跳过 {} · 五金创建 {} · 切削跳过 {}{}.".format(
            declared_count,
            verified_count,
            verify_skipped,
            created_count,
            cut_skipped,
            "（自动选型）" if auto_enabled else "",
        )
    )
    if declared_count == 0 and verified_count == 0 and created_count == 0:
        lines.append("没有可切削接头。可先用声明型生成器，或启用缝隙接头 / 检查板件是否已扫描。")
    return lines


def build_pipeline_report(
    *,
    declare_report: Optional[Dict[str, Any]] = None,
    verify_report: Optional[Dict[str, Any]] = None,
    cut_report: Optional[Dict[str, Any]] = None,
    auto_hardware: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Combine declare + 3a + 3c into one pipeline result (offline-testable)."""
    declare = declare_report if isinstance(declare_report, dict) else {}
    verify = verify_report if isinstance(verify_report, dict) else {}
    cut = cut_report if isinstance(cut_report, dict) else {}
    auto = auto_hardware if isinstance(auto_hardware, dict) else {}

    declared_count = int(declare.get("cutSafeCount") or 0)
    verify_ok = bool(verify.get("ok")) if verify else False
    cut_ok = bool(cut.get("ok")) if cut else False

    verified_count = int(verify.get("verifiedCount") or 0)
    verify_skipped = int(verify.get("skippedCount") or 0)
    created_count = int(cut.get("createdCount") or 0)
    cut_skipped = int(cut.get("skippedCount") or 0)

    errors: List[str] = []
    warnings: List[str] = []

    # Declare is soft: empty / no generator is normal; only surface hard declare errors
    # when face verify also cannot proceed.
    declare_errors = list(declare.get("errors") or [])
    if declare_errors and declared_count == 0 and not verify_ok:
        errors.extend(declare_errors)

    if verify and not verify_ok:
        verify_errors = list(verify.get("errors") or ["Batch face verify failed."])
        if declared_count > 0:
            warnings.extend(verify_errors)
            warnings.append("Face verify failed; cutting generator-declared joints only.")
        else:
            errors.extend(verify_errors)

    if cut and not cut_ok:
        errors.extend(list(cut.get("errors") or ["Batch hardware cut failed."]))

    if not cut:
        if verify_ok or declared_count > 0:
            errors.append("Missing batch cut stage.")
        ok = False
    elif cut_ok and (verify_ok or declared_count > 0):
        # Face-verify alone, declarations alone, or both — cut succeeded.
        ok = True
    else:
        ok = False

    reminders = pipeline_reminder_lines(
        declared_count=declared_count,
        verified_count=verified_count,
        verify_skipped=verify_skipped,
        created_count=created_count,
        cut_skipped=cut_skipped,
        auto_enabled=bool(auto.get("enabled")),
    )
    for line in (
        list(declare.get("reminders") or [])
        + list(verify.get("reminders") or [])
        + list(cut.get("reminders") or [])
    ):
        if line and line not in reminders:
            reminders.append(line)

    skipped = (
        list(declare.get("skipped") or [])
        + list(verify.get("skipped") or [])
        + list(cut.get("skipped") or [])
    )

    return {
        "ok": ok,
        "action": PIPELINE_ACTION,
        "cutGateUnchanged": True,
        "declarationFirst": True,
        "declare": {
            "ok": bool(declare.get("ok")) if declare else False,
            "generator": declare.get("generator"),
            "declarationCount": int(declare.get("declarationCount") or 0),
            "geometryOkCount": int(declare.get("geometryOkCount") or 0),
            "cutSafeCount": declared_count,
        },
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
            "candidateCount": int(cut.get("candidateCount") or 0),
        },
        "created": list(cut.get("created") or []),
        "skipped": skipped,
        "reminders": reminders,
        "errors": errors,
        "warnings": warnings,
        "autoHardware": auto,
    }
