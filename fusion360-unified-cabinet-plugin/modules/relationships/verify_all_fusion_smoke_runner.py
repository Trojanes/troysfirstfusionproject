"""Fusion smoke runner — batch face-verify all bbox candidates (3a)."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List

from connect_formal_ui import evaluate_connect_action, is_cut_allowed
from connect_smoke_runner import PANEL_EDGE, PANEL_SURFACE, format_summary


def run_verify_all_fusion_smoke(
    plugin_dir: str,
    fusion,
    rel_ctrl,
    *,
    write_json: bool = True,
) -> Dict[str, Any]:
    steps: List[Dict[str, Any]] = []

    def record(step: str, ok: bool, data: Dict[str, Any]) -> bool:
        steps.append({"step": step, "status": "PASS" if ok else "FAIL", "data": data})
        return ok

    def build_result(overall: bool, **extra) -> Dict[str, Any]:
        payload = {
            "ok": overall,
            "overall": "PASS" if overall else "FAIL",
            "smoke": "verify_all_connect",
            "action": "relationships.runVerifyAllSmoke",
            "pluginDir": plugin_dir,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "steps": steps,
        }
        payload.update(extra)
        if write_json:
            out_dir = os.path.join(plugin_dir, "tests", "output")
            try:
                os.makedirs(out_dir, exist_ok=True)
                out_path = os.path.join(out_dir, "verify_all_connect_smoke_results.json")
                with open(out_path, "w", encoding="utf-8") as handle:
                    json.dump(payload, handle, indent=2, ensure_ascii=False)
                payload["resultsPath"] = out_path
            except Exception:
                payload["resultsPath"] = "(write failed)"
        payload["summaryText"] = format_summary(payload)
        return payload

    root = fusion.get_root_component() if fusion else None
    if not root:
        record("0 active design", False, {"errors": ["No active Fusion design."]})
        return build_result(False, errors=["No active Fusion design."])

    _ev, fixture_payload = rel_ctrl.create_test_fixture({}, None)
    fixture_ok = bool(fixture_payload.get("ok")) and int(fixture_payload.get("createdBodies") or 0) >= 10
    if not record("1 create fixture", fixture_ok, {
        "createdBodies": fixture_payload.get("createdBodies"),
        "errors": fixture_payload.get("errors"),
    }):
        return build_result(False, fixture=fixture_payload)

    _ev, batch = rel_ctrl.verify_all_bbox_candidates(
        {"toleranceMm": 1.0, "maxPairs": 200},
        None,
    )
    verified = list((batch or {}).get("verifiedRelationships") or [])
    skipped = list((batch or {}).get("skipped") or [])
    batch_ok = (
        bool((batch or {}).get("ok"))
        and bool((batch or {}).get("cutGateUnchanged"))
        and int((batch or {}).get("verifiedCount") or 0) >= 1
        and len(verified) >= 1
        and bool((batch or {}).get("reminders"))
    )
    if not record("2 batch verify all bbox candidates", batch_ok, {
        "verifiedCount": (batch or {}).get("verifiedCount"),
        "skippedCount": (batch or {}).get("skippedCount"),
        "candidateCount": (batch or {}).get("candidateCount"),
        "reminders": (batch or {}).get("reminders"),
        "errors": (batch or {}).get("errors"),
    }):
        return build_result(False, batch=batch)

    first = verified[0]
    cut_ok = (
        (first.get("verification") or {}).get("level") == "face_verified"
        and is_cut_allowed(first)
        and bool(evaluate_connect_action("cut", first).get("ok"))
    )
    if not record("3 verified relationship cut-safe", cut_ok, {
        "relationshipId": first.get("relationshipId"),
        "verificationLevel": (first.get("verification") or {}).get("level"),
        "safeForCut": (first.get("verification") or {}).get("safeForCut"),
    }):
        return build_result(False, batch=batch)

    _ev, inspect_payload = rel_ctrl.inspect_pair(
        {"panelAId": PANEL_EDGE, "panelBId": PANEL_SURFACE, "toleranceMm": 1.0},
        None,
    )
    fresh = inspect_payload.get("relationship") if isinstance(inspect_payload, dict) else None
    bbox_blocked = (
        isinstance(fresh, dict)
        and (fresh.get("verification") or {}).get("level") == "bbox_candidate"
        and not is_cut_allowed(fresh)
        and not evaluate_connect_action("cut", fresh).get("ok")
    )
    if not record("4 fresh bbox_candidate still cut-blocked", bbox_blocked, {
        "verificationLevel": (fresh or {}).get("verification", {}).get("level") if isinstance(fresh, dict) else None,
        "cutGate": evaluate_connect_action("cut", fresh) if isinstance(fresh, dict) else None,
        "errors": (inspect_payload or {}).get("errors"),
    }):
        return build_result(False, batch=batch, inspect=inspect_payload)

    return build_result(True, batch=batch, skippedSample=skipped[:5])
