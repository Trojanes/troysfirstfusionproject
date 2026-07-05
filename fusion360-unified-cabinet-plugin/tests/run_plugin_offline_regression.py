#!/usr/bin/env python3
"""Run all offline plugin regression checks available without Fusion/adsk."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent


def run(cmd, cwd=None, label=None):
    print("\n>>> {}".format(label or " ".join(map(str, cmd))))
    proc = subprocess.run(cmd, cwd=str(cwd or REPO_ROOT), capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if proc.stderr:
        print(proc.stderr.rstrip())
    return proc.returncode


def main() -> int:
    failures = []

    code = run(
        [sys.executable, str(ROOT / "tests" / "run_relationship_regression.py")],
        cwd=ROOT,
        label="relationship regression",
    )
    if code != 0:
        failures.append("relationship_regression")

    code = run(
        [sys.executable, str(ROOT / "tests" / "run_generator_relationship_regression.py")],
        cwd=ROOT,
        label="generator relationship regression",
    )
    if code != 0:
        failures.append("generator_relationship_regression")

    for script in (
        "run_fridge_bridge_tests.js",
        "run_general_tall_bridge_tests.js",
        "run_overhead_bridge_tests.js",
    ):
        code = run(
            ["node", str(ROOT / "tests" / script)],
            label=script,
        )
        if code != 0:
            failures.append(script)

    code = run(
        [sys.executable, str(ROOT / "tests" / "run_relationship_overlay_selfcheck.py")],
        cwd=ROOT,
        label="relationship overlay selfcheck",
    )
    if code != 0:
        failures.append("relationship_overlay_selfcheck")

    code = run(
        [sys.executable, str(ROOT / "tests" / "run_connect_demo_pack_offline.py")],
        cwd=ROOT,
        label="connect demo pack offline",
    )
    if code != 0:
        failures.append("connect_demo_pack_offline")

    code = run(
        [
            sys.executable,
            "-m",
            "unittest",
            "tests.test_face_geometry_signature",
            "tests.test_panel_geometry",
            "tests.test_tag_metadata_editor",
            "tests.test_relationship_geometry",
            "tests.test_relationship_classification",
            "tests.test_relationship_report",
            "tests.test_hardware_from_relationship",
            "tests.test_generator_relationships",
            "tests.test_connect_demo_pack",
            "tests.test_connect_formal_ui",
            "tests.test_contact_patch",
            "tests.test_panel_metadata_writeback",
            "tests.test_relationship_visual_overlay",
            "tests.test_relationship_overlay_selfcheck",
            "tests.test_relationship_fixture_placement",
            "-v",
        ],
        cwd=ROOT,
        label="python pure tests (no adsk)",
    )
    if code != 0:
        failures.append("python_pure_tests")

    print("\n== Plugin offline regression summary ==")
    if failures:
        print("FAILED:", ", ".join(failures))
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
