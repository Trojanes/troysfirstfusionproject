"""3c — batch create hardware on cut-safe relationships; skip failures + remind."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from connect_formal_ui import is_hardware_eligible, is_cut_allowed, gap_settings_from_rule

BATCH_CUT_ACTION = "hardware.createHardwareForCutSafeRelationships"
DEFAULT_BATCH_CUT_MAX_PAIRS = 50


def filter_cut_safe_hardware_candidates(
    relationships: List[Dict[str, Any]],
    gap_settings: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Cut-safe contact joints (+ optional gap joints when enabled)."""
    accepted: List[Dict[str, Any]] = []
    for relationship in relationships or []:
        if not isinstance(relationship, dict):
            continue
        if not is_cut_allowed(relationship):
            continue
        if not is_hardware_eligible(relationship, gap_settings, for_batch=True):
            continue
        accepted.append(relationship)
    return accepted


def _panel_ids(relationship: Dict[str, Any]) -> tuple:
    panel_a = relationship.get("panelA") or {}
    panel_b = relationship.get("panelB") or {}
    return (
        str(panel_a.get("panelId") or "").strip(),
        str(panel_b.get("panelId") or "").strip(),
    )


def batch_cut_reminder_lines(
    *,
    hardware_type: str,
    created_count: int,
    skipped: List[Dict[str, Any]],
    capped: bool,
    candidate_count: int,
) -> List[str]:
    lines: List[str] = []
    hw = str(hardware_type or "hardware")
    if created_count:
        lines.append("已批量创建 {} · {} 对接头。".format(hw, created_count))
    if skipped:
        lines.append("跳过 {} 对（见列表），请检查后手动创建。".format(len(skipped)))
    if capped:
        lines.append("已达本批切削上限，请缩小范围后重试。")
    if candidate_count == 0 and not created_count and not skipped:
        lines.append("没有可切削的已验证关系（需接触类接头且已面验证/声明）。")
    return lines


def summarize_cut_skip(relationship: Dict[str, Any], reason: str, errors: Optional[List[str]] = None) -> Dict[str, Any]:
    panel_a, panel_b = _panel_ids(relationship)
    return {
        "relationshipId": str(relationship.get("relationshipId") or ""),
        "panelA": panel_a,
        "panelB": panel_b,
        "reason": reason,
        "errors": list(errors or []),
    }


def repair_hint_for_skip_reason(reason: Optional[str]) -> str:
    """Next manual step after clicking a batch/pipeline skip row."""
    key = str(reason or "").strip()
    if key in ("cut_failed", "cut_exception"):
        return "已加载该板对。可先预览再创建；若门控关闭，先同步声明或面验证。"
    if key == "cap_reached":
        return "已加载该板对（本批上限跳过）。确认关系后可单独创建，或缩小批量重试。"
    if key in ("no_opposing_faces", "face_extract_failed", "class_mismatch", "geometry_not_supported"):
        return "已加载该板对。建议：同步声明（OH/GT/Kitchen）→ 面验证 → 预览 → 创建。"
    if key in ("panel_missing", "body_not_found"):
        return "跳过项指向的板可能已丢失。请在 Fusion 中确认两块板仍在，再点检查。"
    return "已加载该板对。请检查 → 同步声明或面验证 → 预览 → 创建。"
