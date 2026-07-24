#!/usr/bin/env python3
"""Declared generators Connect smoke �?Kitchen / GT / Lounge create→reconcile→preview.

Install: python scripts/manage_fusion_smokes.py install --batch declared
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
            "connect_batch_c_runner",
            "declared_generators_fusion_smoke_runner",
            "relationship_service",
            "modules.hardware.controller",
            "modules.relationships.controller",
            "modules.kitchen.controller",
            "modules.kitchen.fusion_adapter",
            "modules.general_tall.controller",
            "modules.lounge.controller",
            "modules.lounge.fusion_adapter",
        ):
            try:
                importlib.reload(importlib.import_module(name))
            except ModuleNotFoundError:
                continue

        from connect_smoke_runner import format_summary
        from declared_generators_fusion_smoke_runner import run_declared_generators_fusion_smoke
        from modules.general_tall.controller import GeneralTallController
        from modules.hardware.controller import HardwareController
        from modules.kitchen.controller import KitchenController
        from modules.lounge.controller import LoungeController
        from modules.relationships.controller import RelationshipsController

        fusion = adapter.FusionAdapter()
        rel_ctrl = RelationshipsController(fusion)
        hw_ctrl = HardwareController(plugin_dir, fusion)
        kitchen_ctrl = KitchenController(plugin_dir, fusion)
        gt_ctrl = GeneralTallController(plugin_dir, fusion)
        lounge_ctrl = LoungeController(plugin_dir, fusion)
        result = run_declared_generators_fusion_smoke(
            plugin_dir,
            fusion,
            rel_ctrl,
            hw_ctrl,
            kitchen_ctrl,
            gt_ctrl,
            lounge_ctrl,
            write_json=True,
        )
        if ui:
            ui.messageBox(format_summary(result))
    except Exception:
        if ui:
            ui.messageBox("Declared generators smoke FAILED:\n{}".format(traceback.format_exc()))
        raise
