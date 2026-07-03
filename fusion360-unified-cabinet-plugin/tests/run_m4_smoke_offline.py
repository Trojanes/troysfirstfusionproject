#!/usr/bin/env python3
"""M4 smoke test — offline automation on generator-backed cabinet snapshots (Overhead)."""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
TESTS_DIR = Path(__file__).resolve().parent
REL_DIR = ROOT / "modules" / "relationships"
HW_DIR = ROOT / "modules" / "hardware"
for path in (ROOT, TESTS_DIR, REL_DIR, HW_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from generator_relationship_service import evaluate_generator_relationship_scenario  # noqa: E402
from generator_relationship_cases import list_generator_relationship_scenarios  # noqa: E402
from relationship_service import build_panel_snapshot_from_dict, scan_relationships  # noqa: E402
from relationship_report import build_scan_report  # noqa: E402
from screw_hole_from_relationship import (  # noqa: E402
    plan_screw_hole_cut_from_relationship,
    preview_screw_holes_from_relationship,
    validate_manual_confirmed_relationship_for_cut,
)

OVERHEAD_PREFERRED_PAIRS = [
    ("BP", "D0"),
    ("BP", "FP0"),
    ("D0", "FP0"),
]

HW_REL_DEBUG_RULE = {
    "type": "screw_hole",
    "diameterMm": 4,
    "edgeOffsetMm": 30,
    "minSpacingMm": 80,
    "depthMode": "host_thickness",
}
HW_REL_MANUAL_CONFIRMED = {
    "level": "manual_confirmed",
    "safeForPreview": True,
    "safeForCut": True,
    "requiresManualConfirmation": False,
}


class StepResult:
    def __init__(self, step: str, passed: bool, notes: str = "", data: Optional[Dict[str, Any]] = None):
        self.step = step
        self.passed = passed
        self.notes = notes
        self.data = data or {}


def _overhead_scenario():
    for scenario in list_generator_relationship_scenarios():
        if scenario.get("scenarioId") == "overhead_edge_only":
            return scenario
    raise RuntimeError("overhead_edge_only scenario not found")


def _find_rel(scan_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    from smoke_connect_helpers import find_preview_relationship

    return find_preview_relationship(scan_payload, OVERHEAD_PREFERRED_PAIRS)


def _panels_map(scan_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {p["panelId"]: p for p in (scan_payload.get("panels") or []) if p.get("panelId")}


def _confirm(rel: Dict[str, Any]) -> Dict[str, Any]:
    notes = list(rel.get("auditNotes") or [])
    notes.append("Manual cut confirmation applied (debug session only).")
    return {**rel, "verification": dict(HW_REL_MANUAL_CONFIRMED), "auditNotes": notes}


def run_smoke() -> Tuple[List[StepResult], bool]:
    results: List[StepResult] = []
    scenario = _overhead_scenario()

    try:
        # Step 1 — generator golden scenario
        report = evaluate_generator_relationship_scenario(scenario)
        step1_ok = bool(report.get("ok"))
        results.append(StepResult(
            "1 generator",
            step1_ok,
            "generator=overhead panelCount={} nonNone={}".format(
                report.get("panelCount"), report.get("nonNoneRelationshipCount")
            ),
            {"scenarioReport": report},
        ))
        if not step1_ok:
            return results, False

        # Build scan payload from generator bridge snapshots
        from generator_bridge_runner import run_overhead, load_params_fixture
        from generator_panel_adapter import snapshots_from_generator_result

        bridge = run_overhead(load_params_fixture("overhead_edge_only.json"))
        snapshots = [build_panel_snapshot_from_dict(item) for item in snapshots_from_generator_result("overhead", bridge)]
        _, relationships = scan_relationships(snapshots, include_none=True)
        scan_payload = build_scan_report(
            action="relationships.scan",
            panels=snapshots,
            relationships=relationships,
            scope="generator",
            tolerance_mm=0.5,
        )

        rel = _find_rel(scan_payload)
        step2_ok = bool(rel)
        results.append(StepResult(
            "2 scan",
            step2_ok,
            "relationshipId={}".format((rel or {}).get("relationshipId")),
            {"relationshipCount": scan_payload.get("relationshipCount"), "selected": rel},
        ))
        if not step2_ok or not rel:
            return results, False

        host_id = rel["roles"]["hostPanelId"]
        target_id = rel["roles"]["targetPanelId"]
        panel_snapshots = _panels_map(scan_payload)

        preview = preview_screw_holes_from_relationship(
            rel, rule=HW_REL_DEBUG_RULE, panel_snapshots={host_id: panel_snapshots[host_id], target_id: panel_snapshots[target_id]}
        )
        step3_ok = preview.get("ok") and int(preview.get("holeCount") or 0) >= 1
        results.append(StepResult("3 preview", step3_ok, "holeCount={}".format(preview.get("holeCount")), {"preview": preview}))
        if not step3_ok:
            return results, False

        confirmed = _confirm(rel)
        step4_ok = confirmed["verification"]["level"] == "manual_confirmed"
        results.append(StepResult("4 confirm", step4_ok, "ok", {"relationshipId": confirmed.get("relationshipId")}))
        if not step4_ok:
            return results, False

        gate_bbox = validate_manual_confirmed_relationship_for_cut(rel)
        gate_missing = validate_manual_confirmed_relationship_for_cut(None)
        step5_ok = gate_bbox is not None and gate_missing is not None
        results.append(StepResult("5 negative gate", step5_ok, "bbox blocked", {"bboxError": gate_bbox}))

        plan = plan_screw_hole_cut_from_relationship(
            confirmed,
            rule=HW_REL_DEBUG_RULE,
            panel_snapshots={host_id: panel_snapshots[host_id], target_id: panel_snapshots[target_id]},
        )
        step6_ok = bool(plan.get("ok"))
        results.append(StepResult("6 cut plan", step6_ok, "host={} target={}".format(host_id, target_id), {"plan": plan}))
        return results, step6_ok
    except Exception as ex:
        results.append(StepResult("error", False, traceback.format_exc()))
        return results, False


def main() -> int:
    print("M4 Smoke Test (offline — Overhead generator snapshots)")
    results, overall = run_smoke()
    for item in results:
        status = "PASS" if item.passed else "FAIL"
        print("\n== Step {}: {} ==".format(item.step, status))
        if item.notes:
            print(item.notes)

    out_dir = ROOT / "tests" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "m4_smoke_offline_results.json"
    out_path.write_text(
        json.dumps(
            {"overall": "PASS" if overall else "FAIL", "generator": "overhead", "steps": [item.__dict__ for item in results]},
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print("\n== Summary ==")
    print("M4 offline: {}".format("PASS" if overall else "FAIL"))
    print("Results: {}".format(out_path))
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())
