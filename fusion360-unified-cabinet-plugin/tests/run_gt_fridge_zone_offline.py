#!/usr/bin/env python3
"""Offline smoke: GT fridge zone P1 wiring (palette + unit tests)."""

from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GT = os.path.join(os.path.dirname(ROOT), "modules", "generalTallCabinet")


def _fail(step: str, detail) -> int:
    print("[FAIL] {} -> {}".format(step, detail))
    return 1


def main() -> int:
    types = open(os.path.join(GT, "types.ts"), encoding="utf-8").read()
    for token in (
        '| "fridge"',
        "applianceWidthMm",
        "applianceDepthMm",
        "applianceHeightMm",
    ):
        if token not in types:
            return _fail("types missing", token)
    print("[PASS] GT types fridge zone fields")

    boundary = open(os.path.join(GT, "boundaryResolver.ts"), encoding="utf-8").read()
    if 'aboveZone.type === "fridge"' not in boundary:
        return _fail("boundary missing fridge full_zi", "fridge")
    print("[PASS] boundaryResolver includes fridge")

    generator = open(os.path.join(GT, "generator.ts"), encoding="utf-8").read()
    for token in (
        'zone.type !== "fridge"',
        "applianceHeightMm",
        "exceeds interior midWidth",
        'zone.type === "fridge"',
        "exteriorSide",
        "SidePanel_L thickness 16mm",
        "Cabinet width synced from fridge",
        "addFridgeV5Boards",
        '"V5"',
        "cutProfileVector = v5Profile",
        "applyFridgeRaisedAvoidance",
        "addFridgeRaisedHSetBoards",
        "raised avoidance mode",
        "omitBottomForRaised",
    ):
        if token not in generator:
            return _fail("generator missing", token)
    print("[PASS] generator fridge sync + exterior + V5 profile + raised HSet + omit H_bot")

    decls = open(os.path.join(GT, "relationshipDeclarations.ts"), encoding="utf-8").read()
    for token in (
        "gt_sidepanel_l_v1",
        "gt_sidepanel_r_v2",
        "gt_v5_v1",
        "gt_v5_v2",
        "fridgeExtrasForBoards",
    ):
        if token not in decls:
            return _fail("relationshipDeclarations missing", token)
    print("[PASS] relationshipDeclarations fridge joints")

    py_decls = open(
        os.path.join(ROOT, "modules", "relationships", "general_tall_declared_relationships.py"),
        encoding="utf-8",
    ).read()
    for token in (
        "GENERAL_TALL_FRIDGE_DECLARED_JOINTS",
        "gt_sidepanel_l_v1",
        "_fridge_joint_allowed",
    ):
        if token not in py_decls:
            return _fail("python GT decls missing", token)
    print("[PASS] python GT fridge declaration mirror")

    palette = open(os.path.join(ROOT, "palette.html"), encoding="utf-8").read()
    for token in (
        "gtPropApplianceWidth",
        "gtPropApplianceHeight",
        "gtPropExteriorSide",
        "applianceWidthMm",
        "exteriorSide",
        "generalTallApplyFridgeExteriorToForm",
        "applyGeneralTallFridgeLayout",
        "gtLoadFridgeLayoutBtn",
        '"fridge"',
    ):
        if token not in palette:
            return _fail("palette missing", token)
    if "FridgeCabinetLogic" in palette or "fridge_logic.js" in palette:
        return _fail("standalone Fridge still in palette", "FridgeCabinetLogic/fridge_logic.js")
    if 'data-module="fridge"' in palette:
        return _fail("standalone Fridge nav still present", "data-module=fridge")
    print("[PASS] palette GT fridge controls; standalone Fridge removed")

    test = subprocess.run(
        ["node", "--experimental-strip-types", "fridgeZone.test.ts"],
        cwd=GT,
        capture_output=True,
        text=True,
    )
    if test.returncode != 0:
        sys.stdout.write(test.stdout or "")
        sys.stderr.write(test.stderr or "")
        return _fail("fridgeZone.test.ts", test.returncode)
    print("[PASS] fridgeZone.test.ts")
    print()
    print("GT fridge zone P1 offline: ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
