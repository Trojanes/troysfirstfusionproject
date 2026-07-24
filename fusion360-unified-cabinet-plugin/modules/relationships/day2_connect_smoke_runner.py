"""Day 2 Connect smoke runner — imports fresh connect_smoke_runner (no Fusion cache)."""

from __future__ import annotations

from typing import Any, Dict

from connect_smoke_runner import format_summary, run_connect_smoke

__all__ = ["format_summary", "run_day2_connect_smoke"]


def run_day2_connect_smoke(
    plugin_dir: str,
    fusion,
    rel_ctrl,
    hw_ctrl,
    *,
    write_json: bool = True,
) -> Dict[str, Any]:
    return run_connect_smoke(
        plugin_dir,
        fusion,
        rel_ctrl,
        hw_ctrl,
        write_json=write_json,
        include_preview=True,
        smoke_id="day2",
    )
