#!/usr/bin/env python3
"""Lock cutout Connect smoke â€?host pocket + metadata writeback.

Install: python scripts/manage_fusion_smokes.py install --batch lock
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

        for name in (
            "connect_smoke_runner",
            "relationship_fixtures",
            "modules.relationships.relationship_fixtures",
            "scaffold_hardware_from_relationship",
            "relationship_tongue_groove_fusion",
            "panel_metadata_writeback",
            "modules.hardware.controller",
            "modules.relationships.controller",
            "lock_cutout_fusion_smoke_runner",
        ):
            try:
                importlib.reload(importlib.import_module(name))
            except ModuleNotFoundError:
                continue

        hardware_module = sys.modules["modules.hardware.controller"]
        relationships_module = sys.modules["modules.relationships.controller"]
        runner = sys.modules["lock_cutout_fusion_smoke_runner"]
        from connect_smoke_runner import format_summary

        run_lock_cutout_fusion_smoke = runner.run_lock_cutout_fusion_smoke

        fusion = adapter.FusionAdapter()
        rel_ctrl = relationships_module.RelationshipsController(fusion)
        hw_ctrl = hardware_module.HardwareController(plugin_dir, fusion)
        if not hasattr(hw_ctrl, "create_lock_cutout_from_relationship"):
            raise RuntimeError(
                "HardwareController missing lock cutout methods after reload; "
                "stop/start CabinetNC add-in, then re-run this smoke."
            )
        result = run_lock_cutout_fusion_smoke(
            plugin_dir, fusion, rel_ctrl, hw_ctrl, write_json=True,
        )
        if ui:
            ui.messageBox(format_summary(result))
    except Exception:
        if ui:
            ui.messageBox("Lock cutout smoke FAILED:\n{}".format(traceback.format_exc()))
        raise
