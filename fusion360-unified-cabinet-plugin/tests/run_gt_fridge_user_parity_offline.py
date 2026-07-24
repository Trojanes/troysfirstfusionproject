#!/usr/bin/env python3
"""Offline: GT fridge stack covers Fridge-module user effects (not board-ID clone)."""

from __future__ import annotations

import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(ROOT)
GT = os.path.join(REPO, "modules", "generalTallCabinet")
FIXTURE = os.path.join(ROOT, "tests", "fixtures", "generator_params", "general_tall_fridge_stack.json")


def _fail(step: str, detail) -> int:
    print("[FAIL] {} -> {}".format(step, detail))
    return 1


def main() -> int:
    checklist = os.path.join(REPO, "docs", "connect-gt-fridge-user-parity-checklist.md")
    if not os.path.isfile(checklist):
        return _fail("checklist missing", checklist)
    print("[PASS] user-parity checklist present")

    if not os.path.isfile(FIXTURE):
        return _fail("fixture missing", FIXTURE)
    params = json.loads(open(FIXTURE, encoding="utf-8").read())
    if params.get("exteriorSide") != "right":
        return _fail("fixture exteriorSide", params.get("exteriorSide"))
    zones = params.get("zones") or []
    types = [z.get("type") for z in zones if isinstance(z, dict)]
    if types != ["drawer", "fridge", "top_flap"]:
        return _fail("fixture zone order", types)
    print("[PASS] classic fridge stack fixture")

    from generator_bridge_runner import run_general_tall

    result = run_general_tall(params)
    boards = {str(b.get("id")) for b in (result.get("boards") or []) if isinstance(b, dict)}
    fps = [p for p in (result.get("frontPanels") or []) if isinstance(p, dict)]
    decls = {
        str(d.get("declarationId"))
        for d in (result.get("relationshipDeclarations") or [])
        if isinstance(d, dict)
    }
    errors = (result.get("validation") or {}).get("errors") or result.get("errors") or []
    if errors:
        return _fail("gt generate errors", errors)
    if "V5" not in boards:
        return _fail("missing V5", sorted(boards)[:20])
    if "SidePanel_R" not in boards:
        return _fail("missing SidePanel_R", sorted(boards)[:20])
    if any(p.get("zoneId") == "fridge" for p in fps):
        return _fail("fridge cavity must stay open", fps)
    if not any(p.get("zoneId") == "drawer" for p in fps):
        return _fail("drawer front missing", fps)
    if not any(p.get("zoneId") == "flap" for p in fps):
        return _fail("flap front missing", fps)
    if "gt_v5_v1" not in decls:
        return _fail("missing gt_v5_v1", sorted(decls))
    if "gt_sidepanel_r_v2" not in decls:
        return _fail("missing gt_sidepanel_r_v2", sorted(decls))
    mode = ((result.get("debug") or {}).get("fridgeAvoidance") or {}).get("finalMode")
    if mode not in ("normal", "raised"):
        return _fail("fridgeAvoidance.finalMode", mode)
    print("[PASS] bridge user-effect parity (open cavity, SidePanel, V5, fronts, decls)")

    palette = open(os.path.join(ROOT, "palette.html"), encoding="utf-8").read()
    for token in (
        "applyGeneralTallFridgeLayout",
        "gtLoadFridgeLayoutBtn",
        'activeModule = "generalTall"',
    ):
        if token not in palette:
            return _fail("palette cutover missing", token)
    if "FridgeCabinetLogic" in palette or "fridge_logic.js" in palette:
        return _fail("standalone Fridge still in palette", "FridgeCabinetLogic/fridge_logic.js")
    if 'data-module="fridge"' in palette:
        return _fail("standalone Fridge nav still present", "data-module=fridge")
    print("[PASS] palette GT fridge path; standalone Fridge removed")

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
    print("GT fridge user-parity offline: ALL PASS")
    return 0


if __name__ == "__main__":
    # Prefer plugin relationships path for bridge import.
    sys.path.insert(0, os.path.join(ROOT, "modules", "relationships"))
    raise SystemExit(main())
