#!/usr/bin/env python3
"""Day 2 Connect smoke â€?preview screw holes + full cut pipeline.

Run from Fusion Scripts and Add-ins (Scripts tab, â–?play):
  day2_connect_smoke.py

Or install via: scripts/install_fusion_connect_smokes.ps1
"""

from __future__ import annotations

import os
import sys
import traceback

import adsk.core

DEFAULT_REPO_PLUGIN_DIR = r"d:\project\troysfirstfusionproject-main\fusion360-unified-cabinet-plugin"


def _resolve_plugin_dir(script_file: str) -> str:
    script_dir = os.path.dirname(os.path.abspath(script_file))
    for candidate in (
        script_dir,
        os.environ.get("CABINETNC_PLUGIN_DIR") or "",
        DEFAULT_REPO_PLUGIN_DIR,
    ):
        if candidate and os.path.isfile(os.path.join(candidate, "UnifiedCabinetPlugin.py")):
            return candidate
    return DEFAULT_REPO_PLUGIN_DIR


def _ensure_paths(plugin_dir: str) -> None:
    # Keep in sync with UnifiedCabinetPlugin._ensure_paths (flat imports under fusion/metadata/â€?.
    for path in (
        plugin_dir,
        os.path.join(plugin_dir, "fusion"),
        os.path.join(plugin_dir, "ui"),
        os.path.join(plugin_dir, "modules"),
        os.path.join(plugin_dir, "modules", "general_tall"),
        os.path.join(plugin_dir, "modules", "overhead"),
        os.path.join(plugin_dir, "modules", "kitchen"),
        os.path.join(plugin_dir, "modules", "lounge"),
        os.path.join(plugin_dir, "modules", "tools"),
        os.path.join(plugin_dir, "modules", "hardware"),
        os.path.join(plugin_dir, "modules", "relationships"),
        os.path.join(plugin_dir, "panel_attributes"),
        os.path.join(plugin_dir, "metadata"),
    ):
        if path not in sys.path:
            sys.path.insert(0, path)


def run(_context):
    ui = None
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface if app else None
        plugin_dir = _resolve_plugin_dir(__file__)
        _ensure_paths(plugin_dir)

        import adapter
        import importlib

        import connect_smoke_runner
        import day2_connect_smoke_runner

        importlib.reload(connect_smoke_runner)
        importlib.reload(day2_connect_smoke_runner)

        from day2_connect_smoke_runner import format_summary, run_day2_connect_smoke
        from modules.hardware.controller import HardwareController
        from modules.relationships.controller import RelationshipsController

        fusion = adapter.FusionAdapter()
        rel_ctrl = RelationshipsController(fusion)
        hw_ctrl = HardwareController(plugin_dir, fusion)
        result = run_day2_connect_smoke(plugin_dir, fusion, rel_ctrl, hw_ctrl, write_json=True)
        if ui:
            ui.messageBox(format_summary(result))
    except Exception:
        if ui:
            ui.messageBox("Day 2 Connect smoke FAILED:\n{}".format(traceback.format_exc()))
        raise
