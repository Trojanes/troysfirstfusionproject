"""Day 1 Connect smoke runner — backward-compatible wrapper."""

from __future__ import annotations

from typing import Any, Dict

from connect_smoke_runner import (
    EXPECTED_HOLE_COUNT,
    HW_RULE,
    PANEL_EDGE,
    PANEL_SURFACE,
    cut_feature_exists,
    find_body_by_panel_id,
    format_summary,
    run_connect_smoke,
    safe_volume,
    write_results,
)

__all__ = [
    "EXPECTED_HOLE_COUNT",
    "HW_RULE",
    "PANEL_EDGE",
    "PANEL_SURFACE",
    "cut_feature_exists",
    "find_body_by_panel_id",
    "format_summary",
    "run_day1_connect_smoke",
    "safe_volume",
    "write_results",
]


def run_day1_connect_smoke(
    plugin_dir: str,
    fusion,
    rel_ctrl,
    hw_ctrl,
    *,
    write_json: bool = True,
    include_preview: bool = False,
    smoke_id: str = "day1",
) -> Dict[str, Any]:
    return run_connect_smoke(
        plugin_dir,
        fusion,
        rel_ctrl,
        hw_ctrl,
        write_json=write_json,
        include_preview=include_preview,
        smoke_id=smoke_id,
    )
