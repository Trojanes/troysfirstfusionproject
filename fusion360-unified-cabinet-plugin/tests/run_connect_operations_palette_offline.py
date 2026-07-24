#!/usr/bin/env python3
"""Offline smoke: Connect operations + tab IA (pair / cabinet / ops)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fail(step: str, detail) -> int:
    print("[FAIL] {} -> {}".format(step, detail))
    return 1


def main() -> int:
    plugin = open(os.path.join(ROOT, "UnifiedCabinetPlugin.py"), encoding="utf-8").read()
    for token in (
        "OPS_PALETTE_ID",
        "ops_palette_controller",
        "ui.showConnectOperationsPalette",
        "connect_operations_palette.html",
        "Connect 已创建操作",
        "show_ops_palette",
    ):
        if token not in plugin:
            return _fail("plugin missing", token)
    for banned in (
        "SIDE_PALETTE_ID",
        "side_palette_controller",
        "ui.showSideContactPalette",
        "connect_side_contact_palette.html",
        "侧向接触钻孔",
        "hardware.createSideContactTestBoards",
    ):
        if banned in plugin:
            return _fail("plugin still registers retired side-contact UI", banned)
    print("[PASS] plugin ops sub-palette registration; side-contact retired")

    controller = open(
        os.path.join(ROOT, "ui", "palette_controller.py"), encoding="utf-8"
    ).read()
    for token in ("html_file", "width", "height"):
        if token not in controller:
            return _fail("palette_controller missing", token)
    print("[PASS] PaletteController multi-html support")

    ops_html = open(
        os.path.join(ROOT, "connect_operations_palette.html"), encoding="utf-8"
    ).read()
    for token in (
        "已创建操作",
        "修改此操作参数",
        "hardware.listHardwareOperations",
        "hardware.updateHardwareOperation",
        "opsUpdateBtn",
        "fusionJavaScriptHandler",
    ):
        if token not in ops_html:
            return _fail("ops palette missing", token)
    print("[PASS] connect_operations_palette.html")

    main_html = open(os.path.join(ROOT, "palette.html"), encoding="utf-8").read()
    for token in (
        'data-connect-view="pair"',
        'data-connect-view="cabinet"',
        'data-connect-view="ops"',
        "connectViewPair",
        "connectViewCabinet",
        "connectViewOps",
        "connectOpsList",
        "connectOpsUpdateBtn",
        "function connectUiShowView(",
        "hardware.listHardwareOperations",
        "hardware.updateHardwareOperation",
        "connectCutBtn",
        "connectPipelineBtn",
    ):
        if token not in main_html:
            return _fail("main palette tab IA missing", token)

    # Pair owns create; cabinet owns pipeline; ids must not share one section only.
    pair_start = main_html.find('id="connectViewPair"')
    cabinet_start = main_html.find('id="connectViewCabinet"')
    ops_start = main_html.find('id="connectViewOps"')
    if not (0 <= pair_start < cabinet_start < ops_start):
        return _fail("connect view order", "pair < cabinet < ops")
    pair_html = main_html[pair_start:cabinet_start]
    cabinet_html = main_html[cabinet_start:ops_start]
    if 'id="connectCutBtn"' not in pair_html:
        return _fail("pair tab missing create", "connectCutBtn")
    if 'id="connectPipelineBtn"' in pair_html:
        return _fail("pair tab still has pipeline", "connectPipelineBtn")
    if 'id="connectPipelineBtn"' not in cabinet_html:
        return _fail("cabinet tab missing pipeline", "connectPipelineBtn")
    if 'id="connectCutBtn"' in cabinet_html:
        return _fail("cabinet tab still has pair create", "connectCutBtn")
    if 'id="connectOpsList"' not in main_html[ops_start : ops_start + 2500]:
        return _fail("ops tab missing list", "connectOpsList")

    for banned in (
        'id="connectOperationsList"',
        'id="connectUpdateOperationBtn"',
        'id="connectOperationEditParams"',
        "connectOpenSideContactPaletteBtn",
        "ui.showSideContactPalette",
        'id="connectDevTools"',
        "hwRelRunDay1SmokeBtn",
        "侧向接触钻孔",
        "connectOpenOperationsPaletteBtn",
    ):
        if banned in main_html:
            return _fail("main palette still has retired UI", banned)
    print("[PASS] main Connect tab IA: pair / cabinet / ops")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
