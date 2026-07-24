#!/usr/bin/env python3
"""M4.5A Connect demo / golden case pack — offline runner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
HW_DIR = ROOT / "modules" / "hardware"
for path in (ROOT, REL_DIR, HW_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from connect_demo_pack import (  # noqa: E402
    DEMO_FIXTURE_BASELINE,
    DEMO_NEGATIVE_FILTERING,
    DEMO_OVERHEAD_STRUCTURAL,
    run_all_demos_offline,
)


def main() -> int:
    print("M4.5A Connect Demo Pack (offline)")
    report = run_all_demos_offline()
    demos = report.get("demos") or []

    for demo in demos:
        summary = demo.get("summary") or {}
        status = "PASS" if demo.get("ok") else "FAIL"
        print("\n== {}: {} ==".format(demo.get("demoId"), status))
        print(
            "panels={} relationships={} screwEligible={} previewOk={} confirmedOk={} cutOk={}".format(
                summary.get("panelCount"),
                summary.get("relationshipCount"),
                summary.get("screwEligibleCount"),
                summary.get("previewOk"),
                summary.get("confirmedOk"),
                summary.get("cutOk"),
            )
        )
        if demo.get("errors"):
            for err in demo["errors"]:
                print("  error:", err)

    out_dir = ROOT / "tests" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "connect_demo_pack_offline_results.json"
    out_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    summary_path = out_dir / "connect_demo_pack_summaries.json"
    summary_path.write_text(
        json.dumps({"milestone": "M4.5A", "summaries": report.get("summaries") or []}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    overall = "PASS" if report.get("ok") else "FAIL"
    print("\n== Summary ==")
    print("M4.5A offline: {}".format(overall))
    print("Full report: {}".format(out_path))
    print("Summaries: {}".format(summary_path))
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
