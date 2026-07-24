#!/usr/bin/env python3
"""Offline regression for generator-backed relationship golden cases."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
if str(REL_DIR) not in sys.path:
    sys.path.insert(0, str(REL_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def run_unittest_suite() -> bool:
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromName("tests.test_generator_relationships")
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return result.wasSuccessful()


def run_scenario_matrix() -> bool:
    from generator_relationship_service import evaluate_all_generator_relationship_scenarios

    print("\n== Generator relationship golden matrix ==")
    report = evaluate_all_generator_relationship_scenarios()
    ok = bool(report.get("ok"))
    for item in report.get("reports") or []:
        status = "PASS" if item.get("ok") else "FAIL"
        print(
            "  [{}] {} generator={} panels={} nonNone={}".format(
                status,
                item.get("scenarioId"),
                item.get("generator"),
                item.get("panelCount"),
                item.get("nonNoneRelationshipCount"),
            )
        )
        for pair in item.get("pairResults") or []:
            pair_status = "PASS" if pair.get("matched") else "FAIL"
            print(
                "    [{}] {} {} <-> {} expected={}".format(
                    pair_status,
                    pair.get("caseId"),
                    pair.get("panelAId"),
                    pair.get("panelBId"),
                    pair.get("expectedGeometryType"),
                )
            )
        for error in item.get("errors") or []:
            print("    ERROR:", error)
    print("\nGenerator relationship scenarios ok={}".format(ok))
    return ok


def main() -> int:
    checks = [
        ("unittest", run_unittest_suite()),
        ("scenario_matrix", run_scenario_matrix()),
    ]
    print("\n== Generator relationship regression summary ==")
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print("[{}] {}".format("PASS" if ok else "FAIL", name))
    if failed:
        print("FAILED:", ", ".join(failed))
        return 1
    print("Generator relationship regression ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
