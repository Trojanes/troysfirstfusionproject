"""Palette / Fusion routes for board relationship detection."""

from __future__ import annotations

import importlib
import traceback
from typing import Any, Dict

from relationship_fixtures import create_relationship_test_fixture, evaluate_fixture_expectations, expected_fixture_cases
from relationship_service import RelationshipService


class RelationshipsController:
    def __init__(self, fusion_adapter):
        self.fusion = fusion_adapter
        self.service = RelationshipService(fusion_adapter)

    def _float_param(self, payload: Dict[str, Any], key: str, default: float) -> float:
        if not isinstance(payload, dict):
            return default
        try:
            return float(payload.get(key, default))
        except Exception:
            return default

    def scan(self, payload, _palette):
        try:
            tolerance_mm = self._float_param(payload, "toleranceMm", 0.5)
            include_none = bool(payload.get("includeNone")) if isinstance(payload, dict) else False
            expected = payload.get("expectedFixtures") if isinstance(payload, dict) else None
            report = self.service.scan(
                scope=str((payload or {}).get("scope") or "all"),
                tolerance_mm=tolerance_mm,
                include_none=include_none,
                expected_fixtures=expected,
            )
            return "relationshipScanResult", report
        except Exception as ex:
            return "relationshipScanResult", {
                "ok": False,
                "action": "relationships.scan",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def scan_selected(self, payload, _palette):
        try:
            tolerance_mm = self._float_param(payload, "toleranceMm", 0.5)
            include_none = bool(payload.get("includeNone")) if isinstance(payload, dict) else False
            selected = self._selected_bodies()
            report = self.service.scan_selected(
                selected,
                tolerance_mm=tolerance_mm,
                include_none=include_none,
            )
            return "relationshipScanResult", report
        except Exception as ex:
            return "relationshipScanResult", {
                "ok": False,
                "action": "relationships.scanSelected",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def inspect_selected(self, payload, _palette):
        try:
            from relationship_service import build_panel_snapshot, is_panel_body

            tolerance_mm = self._float_param(payload, "toleranceMm", 0.5)
            include_none = bool(payload.get("includeNone")) if isinstance(payload, dict) else False
            selected = self._selected_bodies()
            panel_bodies = [body for body in (selected or []) if is_panel_body(body)]
            if len(panel_bodies) < 2:
                return "relationshipInspectResult", {
                    "ok": False,
                    "action": "relationships.inspectSelected",
                    "selectedPanelBodyCount": len(panel_bodies),
                    "errors": ["Select at least 2 panel bodies to inspect a relationship pair."],
                }
            if len(panel_bodies) == 2:
                panels = [build_panel_snapshot(body) for body in panel_bodies]
                report = self.service.inspect_pair_by_id(
                    panels,
                    panels[0].panelId,
                    panels[1].panelId,
                    tolerance_mm=tolerance_mm,
                )
                return "relationshipInspectResult", report

            report = self.service.scan_selected(
                panel_bodies,
                tolerance_mm=tolerance_mm,
                include_none=include_none,
            )
            return "relationshipScanResult", report
        except Exception as ex:
            return "relationshipInspectResult", {
                "ok": False,
                "action": "relationships.inspectSelected",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def inspect_pair(self, payload, _palette):
        try:
            if not isinstance(payload, dict):
                return "relationshipInspectResult", {
                    "ok": False,
                    "action": "relationships.inspectPair",
                    "errors": ["Missing inspectPair payload."],
                }
            panel_a_id = str(payload.get("panelAId") or "").strip()
            panel_b_id = str(payload.get("panelBId") or "").strip()
            if not panel_a_id or not panel_b_id:
                return "relationshipInspectResult", {
                    "ok": False,
                    "action": "relationships.inspectPair",
                    "errors": ["panelAId and panelBId are required."],
                }
            tolerance_mm = self._float_param(payload, "toleranceMm", 0.5)
            report = self.service.inspect_pair_from_design(
                panel_a_id,
                panel_b_id,
                tolerance_mm=tolerance_mm,
            )
            return "relationshipInspectResult", report
        except Exception as ex:
            return "relationshipInspectResult", {
                "ok": False,
                "action": "relationships.inspectPair",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def create_test_fixture(self, payload, _palette):
        try:
            root = self.fusion.get_root_component() if self.fusion else None
            if not root:
                return "relationshipFixtureResult", {
                    "ok": False,
                    "action": "relationships.createTestFixture",
                    "errors": ["No active Fusion design."],
                }

            fixture_module = importlib.reload(importlib.import_module("modules.relationships.relationship_fixtures"))
            created, error, mode_note = fixture_module.create_relationship_test_fixture(root)
            if error:
                return "relationshipFixtureResult", {
                    "ok": False,
                    "action": "relationships.createTestFixture",
                    "errors": [error],
                    "createdBodies": len(created),
                }

            warnings = []
            if mode_note:
                warnings.append(mode_note)
            flat_mode = any(item.get("flatMode") for item in created)
            tolerance_mm = self._float_param(payload, "toleranceMm", 0.5)
            created_panel_ids = {item["panelId"] for item in created}
            panels = [
                panel
                for panel in self.service.collect_panels_from_design()
                if panel.panelId in created_panel_ids
            ]
            from relationship_service import scan_relationships
            from relationship_report import build_scan_report

            _, relationships = scan_relationships(panels, tolerance_mm=tolerance_mm, include_none=True)
            scan_report = build_scan_report(
                action="relationships.scan",
                panels=panels,
                relationships=relationships,
                scope="fixture",
                tolerance_mm=tolerance_mm,
                expected_fixtures=expected_fixture_cases(),
            )

            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass

            return "relationshipFixtureResult", {
                "ok": scan_report.get("ok", False),
                "action": "relationships.createTestFixture",
                "createdBodies": len(created),
                "flatMode": flat_mode,
                "fixtures": expected_fixture_cases(),
                "created": created,
                "scan": scan_report,
                "warnings": warnings,
            }
        except Exception as ex:
            return "relationshipFixtureResult", {
                "ok": False,
                "action": "relationships.createTestFixture",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def _selected_bodies(self):
        getter = getattr(self.fusion, "get_selected_entities", None)
        if callable(getter):
            entities = getter()
        else:
            entities = []

        bodies = []
        for entity in entities or []:
            if entity is None:
                continue
            if hasattr(entity, "isSolid") and entity.isSolid:
                bodies.append(entity)
        return bodies
