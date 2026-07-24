#!/usr/bin/env python3
"""Batch C Connect smoke â€?real overhead pairs + dual-path confirm/face_verified.

Install: python scripts/manage_fusion_smokes.py install --batch c
"""

from __future__ import annotations

import importlib
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
    # Keep in sync with UnifiedCabinetPlugin._ensure_paths
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
        import connect_batch_c_runner
        import connect_smoke_runner

        importlib.reload(connect_smoke_runner)
        importlib.reload(connect_batch_c_runner)

        from connect_batch_c_runner import format_summary, run_connect_batch_c_smoke
        from modules.hardware.controller import HardwareController
        from modules.overhead.controller import OverheadController
        from modules.relationships.controller import RelationshipsController

        fusion = adapter.FusionAdapter()
        rel_ctrl = RelationshipsController(fusion)
        hw_ctrl = HardwareController(plugin_dir, fusion)
        overhead_ctrl = OverheadController(plugin_dir, fusion)
        result = run_connect_batch_c_smoke(
            plugin_dir, fusion, rel_ctrl, hw_ctrl, overhead_ctrl, write_json=True,
        )
        if ui:
            ui.messageBox(format_summary(result))
    except Exception:
        if ui:
            ui.messageBox("Connect Batch C smoke FAILED:\n{}".format(traceback.format_exc()))
        raise
