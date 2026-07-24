#!/usr/bin/env python3
"""Batch face-verify Connect smoke â€?verifyAllBboxCandidates (3a).

Install: python scripts/manage_fusion_smokes.py install --batch verifyall
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
    # Force repo plugin first so reloads pick up local edits (not a stale Add-In copy).
    ordered = (
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
    )
    for path in ordered:
        if path in sys.path:
            sys.path.remove(path)
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
            "face_verification",
            "face_verification_fusion",
            "relationship_report",
            "relationship_service",
            "connect_formal_ui",
            "modules.relationships.controller",
            "verify_all_fusion_smoke_runner",
        ):
            try:
                importlib.reload(importlib.import_module(name))
            except ModuleNotFoundError:
                continue

        relationships_module = sys.modules["modules.relationships.controller"]
        runner = sys.modules["verify_all_fusion_smoke_runner"]
        run_verify_all_fusion_smoke = runner.run_verify_all_fusion_smoke

        fusion = adapter.FusionAdapter()
        rel_ctrl = relationships_module.RelationshipsController(fusion)
        if not hasattr(rel_ctrl, "verify_all_bbox_candidates"):
            raise RuntimeError(
                "RelationshipsController missing verify_all_bbox_candidates; "
                "reload the CabinetNC add-in or confirm pluginDir={}".format(plugin_dir)
            )
        result = run_verify_all_fusion_smoke(plugin_dir, fusion, rel_ctrl, write_json=True)
        if ui:
            ui.messageBox(str(result.get("summaryText") or result.get("overall") or "done"))
    except Exception:
        if ui:
            ui.messageBox("Verify-all Connect smoke FAILED:\n{}".format(traceback.format_exc()))
        raise
