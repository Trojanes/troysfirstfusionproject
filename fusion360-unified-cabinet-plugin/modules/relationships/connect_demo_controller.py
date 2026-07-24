"""Fusion + offline routes for M4.5A Connect demo pack."""

from __future__ import annotations

import traceback
from typing import Any, Dict, Optional

from connect_demo_pack import (
    DEMO_FIXTURE_BASELINE,
    build_demo_summary,
    classify_scan_relationships,
    evaluate_screw_eligibility,
    find_first_screw_eligible,
    run_all_demos_offline,
    run_demo_3_negative_filtering,
)
from relationship_models import confirm_relationship_for_cut


class ConnectDemoController:
    def __init__(self, plugin_dir, fusion, relationships_controller, hardware_controller):
        self.plugin_dir = plugin_dir
        self.fusion = fusion
        self.relationships = relationships_controller
        self.hardware = hardware_controller

    def run_demo_pack_offline(self, _payload, _palette):
        try:
            report = run_all_demos_offline()
            return "connectDemoResult", {
                "ok": report.get("ok"),
                "action": "relationships.runDemoPackOffline",
                **report,
            }
        except Exception as ex:
            return "connectDemoResult", {
                "ok": False,
                "action": "relationships.runDemoPackOffline",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def run_demo_negative_report(self, payload, _palette):
        try:
            scan_payload = None
            if isinstance(payload, dict) and isinstance(payload.get("scan"), dict):
                scan_payload = payload.get("scan")
            elif isinstance(payload, dict) and payload.get("useFixtureScan"):
                _ev, fixture = self.relationships.create_test_fixture({"toleranceMm": 0.5}, None)
                scan_payload = (fixture.get("scan") if isinstance(fixture, dict) else None) or fixture

            demo = run_demo_3_negative_filtering()
            if scan_payload:
                demo["audit"]["liveScan"] = {
                    "panelCount": scan_payload.get("panelCount"),
                    "relationshipCount": scan_payload.get("relationshipCount"),
                    "classification": classify_scan_relationships(scan_payload.get("relationships") or []),
                }
            return "connectDemoResult", {
                "ok": demo.get("ok"),
                "action": "relationships.runDemoNegativeReport",
                "demoId": demo.get("demoId"),
                "summary": demo.get("summary"),
                "audit": demo.get("audit"),
                "errors": demo.get("errors"),
            }
        except Exception as ex:
            return "connectDemoResult", {
                "ok": False,
                "action": "relationships.runDemoNegativeReport",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def run_day1_smoke(self, _payload, palette):
        """Day 1 automated Connect smoke: fixture → inspect → contact patch → confirm → cut."""
        try:
            from day1_connect_smoke_runner import run_day1_connect_smoke

            report = run_day1_connect_smoke(
                self.plugin_dir,
                self.fusion,
                self.relationships,
                self.hardware,
                write_json=True,
            )
            return "day1SmokeResult", report
        except Exception as ex:
            return "day1SmokeResult", {
                "ok": False,
                "overall": "FAIL",
                "action": "relationships.runDay1Smoke",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def run_demo_fixture_flow(self, payload, palette):
        """Demo 1 end-to-end inside Fusion: fixture → scan → preview → confirm → cut."""
        rule = payload.get("rule") if isinstance(payload, dict) and isinstance(payload.get("rule"), dict) else None
        try:
            _ev, fixture = self.relationships.create_test_fixture({"toleranceMm": 0.5}, palette)
            scan_payload = (fixture.get("scan") if isinstance(fixture, dict) else None) or {}
            if not fixture.get("ok"):
                return "connectDemoResult", {
                    "ok": False,
                    "action": "relationships.runDemoFixtureFlow",
                    "demoId": DEMO_FIXTURE_BASELINE,
                    "errors": fixture.get("errors") or ["Fixture creation failed."],
                    "audit": {"fixture": fixture},
                }

            relationships = scan_payload.get("relationships") or []
            classification = classify_scan_relationships(relationships)
            rel = find_first_screw_eligible(relationships)
            if not rel:
                return "connectDemoResult", {
                    "ok": False,
                    "action": "relationships.runDemoFixtureFlow",
                    "demoId": DEMO_FIXTURE_BASELINE,
                    "errors": ["No screw-eligible relationship in fixture scan."],
                    "audit": {"scan": scan_payload, "classification": classification},
                }

            host_id = rel["roles"]["hostPanelId"]
            target_id = rel["roles"]["targetPanelId"]
            panels = {p["panelId"]: p for p in (scan_payload.get("panels") or []) if p.get("panelId")}
            panel_subset = {host_id: panels[host_id], target_id: panels[target_id]}

            _ev, preview = self.hardware.preview_screw_holes_from_relationship(
                {"relationship": rel, "rule": rule or {}, "panels": panel_subset},
                palette,
            )
            preview_ok = bool(preview.get("ok"))

            confirmed = confirm_relationship_for_cut(rel)
            confirm_ok = confirmed.get("verification", {}).get("level") == "manual_confirmed"

            _ev, blocked = self.hardware.create_screw_holes_from_relationship(
                {"relationship": rel, "rule": rule or {}, "panels": panel_subset},
                palette,
            )
            gate_ok = blocked.get("ok") is False

            _ev, cut = self.hardware.create_screw_holes_from_relationship(
                {"relationship": confirmed, "rule": rule or {}, "panels": panel_subset},
                palette,
            )
            cut_ok = bool(cut.get("ok"))
            host_only = cut.get("targetBodyModified") is False if cut_ok else None
            metadata_written = cut.get("metadataWritten") if cut_ok else None

            summary = build_demo_summary(
                DEMO_FIXTURE_BASELINE,
                ok=preview_ok and confirm_ok and gate_ok and cut_ok and host_only is True,
                panel_count=scan_payload.get("panelCount") or 0,
                relationship_count=classification["relationshipCount"],
                screw_eligible_count=classification["screwEligibleCount"],
                ignored_count=classification["ignoredCount"],
                collision_count=classification["collisionCount"],
                preview_ok=preview_ok,
                confirmed_ok=confirm_ok,
                cut_ok=cut_ok,
                host_only_cut=host_only,
                metadata_written=metadata_written,
                errors=[] if cut_ok else (cut.get("errors") or []),
            )

            return "connectDemoResult", {
                "ok": summary["ok"],
                "action": "relationships.runDemoFixtureFlow",
                "demoId": DEMO_FIXTURE_BASELINE,
                "summary": summary,
                "audit": {
                    "fixture": fixture,
                    "scan": scan_payload,
                    "classification": classification,
                    "selectedRelationship": rel,
                    "eligibility": evaluate_screw_eligibility(rel),
                    "preview": preview,
                    "confirm": {
                        "action": "manualConfirmForCut",
                        "ok": confirm_ok,
                        "relationshipId": confirmed.get("relationshipId"),
                        "verification": confirmed.get("verification"),
                        "persisted": False,
                    },
                    "negativeGateAttempt": blocked,
                    "cut": cut,
                },
            }
        except Exception as ex:
            return "connectDemoResult", {
                "ok": False,
                "action": "relationships.runDemoFixtureFlow",
                "demoId": DEMO_FIXTURE_BASELINE,
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }
