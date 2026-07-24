#!/usr/bin/env python3
"""Preflight self-check for M4.6A relationship visual overlay."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
if str(REL_DIR) not in sys.path:
    sys.path.insert(0, str(REL_DIR))

from relationship_visual_overlay_selfcheck import run_overlay_selfcheck  # noqa: E402


def main() -> int:
    print("Relationship Overlay Self-Check")
    report = run_overlay_selfcheck(force_reload=True)
    print(json.dumps(report, indent=2, ensure_ascii=False))

    out_dir = ROOT / "tests" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "relationship_overlay_selfcheck.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print("\nReport: {}".format(out_path))

    if report.get("ok"):
        print("\nOVERLAY SELF-CHECK: PASS")
        print("Expected Fusion build: {}".format(report.get("expectedFusionBuild")))
        return 0

    print("\nOVERLAY SELF-CHECK: FAIL")
    for err in report.get("errors") or []:
        print(" -", err)
    return 1


if __name__ == "__main__":
    sys.exit(main())
