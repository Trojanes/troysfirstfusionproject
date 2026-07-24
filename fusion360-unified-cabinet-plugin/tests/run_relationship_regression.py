#!/usr/bin/env python3
"""Offline regression runner for Board Relationship module.

Runs without Fusion / adsk. Validates geometry classification, fixture
expectations, JSON audit schema, service scan logic, and controller routes.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
if str(REL_DIR) not in sys.path:
    sys.path.insert(0, str(REL_DIR))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


REQUIRED_AUDIT_KEYS = {
    "relationshipId",
    "panelAId",
    "panelBId",
    "panelABodyName",
    "panelBBodyName",
    "geometryType",
    "relationshipType",
    "detectionMethod",
    "verificationLevel",
    "safeForPreview",
    "safeForCut",
    "requiresManualConfirmation",
    "axis",
    "distanceMm",
    "overlapX",
    "overlapY",
    "overlapZ",
    "contactAreaMm2",
    "contactLengthMm",
    "confidence",
    "warnings",
    "errors",
}

REQUIRED_RELATIONSHIP_KEYS = {
    "schemaVersion",
    "relationshipId",
    "panelA",
    "panelB",
    "geometryType",
    "relationshipType",
    "contact",
    "roles",
    "source",
    "validation",
    "verification",
    "detectionMethod",
}


def _print_section(title: str) -> None:
    print("\n== {} ==".format(title))


def run_unittest_suite() -> bool:
    _print_section("Relationship unit tests")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for pattern in ("test_relationship*.py", "test_face_verification.py", "test_generator_declared_relationships.py"):
        suite.addTests(loader.discover(str(ROOT / "tests"), pattern=pattern))
    runner = unittest.TextTestRunner(verbosity=1)
    result = runner.run(suite)
    return result.wasSuccessful()


def validate_fixture_cases() -> bool:
    _print_section("Fixture expectation matrix")
    from relationship_fixtures import evaluate_fixture_expectations, expected_fixture_cases

    report = evaluate_fixture_expectations(include_none=True)
    ok = bool(report.get("ok"))
    print("panelCount={} relationshipCount={} ok={}".format(
        report.get("panelCount"),
        report.get("relationshipCount"),
        ok,
    ))
    for item in report.get("expectedFixtures") or []:
        status = "PASS" if item.get("matched") else "FAIL"
        print(
            "  [{}] {} {} <-> {} expected={} actual={}".format(
                status,
                item.get("caseId"),
                item.get("panelAId"),
                item.get("panelBId"),
                item.get("expectedGeometryType"),
                item.get("actualGeometryType"),
            )
        )
    if not ok:
        print("Fixture report errors:", report.get("errors"))
    return ok


def validate_audit_schema() -> bool:
    _print_section("JSON audit schema")
    from relationship_fixtures import build_fixture_snapshots, expected_fixture_cases
    from relationship_geometry import classify_pair
    from relationship_report import build_inspect_pair_report, build_scan_report, relationship_audit_row

    panels = build_fixture_snapshots()
    panel_map = {panel.panelId: panel for panel in panels}
    relationships = []
    for fixture in expected_fixture_cases():
        rel = classify_pair(panel_map[fixture["panelAId"]], panel_map[fixture["panelBId"]])
        relationships.append(rel)

        rel_dict = rel.to_dict()
        missing_rel = REQUIRED_RELATIONSHIP_KEYS - set(rel_dict.keys())
        if missing_rel:
            print("FAIL missing relationship keys:", missing_rel)
            return False

        row = relationship_audit_row(rel)
        missing_audit = REQUIRED_AUDIT_KEYS - set(row.keys())
        if missing_audit:
            print("FAIL missing audit keys:", missing_audit)
            return False

        inspect_report = build_inspect_pair_report(relationship=rel, tolerance_mm=0.5)
        if "relationship" not in inspect_report or "audit" not in inspect_report:
            print("FAIL inspectPair report missing sections")
            return False

    scan_report = build_scan_report(
        action="relationships.scan",
        panels=panels,
        relationships=relationships,
        scope="fixture",
        tolerance_mm=0.5,
        expected_fixtures=expected_fixture_cases(),
    )
    if not scan_report.get("audit"):
        print("FAIL scan report missing audit rows")
        return False

    serialized = json.dumps(scan_report, ensure_ascii=False)
    if len(serialized) < 100:
        print("FAIL scan report too small")
        return False

    print("PASS {} relationships, audit rows={}, serializedBytes={}".format(
        len(relationships),
        len(scan_report["audit"]),
        len(serialized),
    ))
    return True


def validate_pairwise_scan_simulation() -> bool:
    _print_section("Full fixture pairwise scan simulation")
    from relationship_fixtures import build_fixture_snapshots
    from relationship_service import scan_relationships

    panels = build_fixture_snapshots()
    _, relationships = scan_relationships(panels, tolerance_mm=0.5, include_none=False)
    # 10 panels -> 45 pairs, many cross-case; should find at least the 4 non-none fixture pairs
    geometry_types = {rel.geometryType for rel in relationships}
    required = {"edge_to_surface", "surface_to_surface", "gap_parallel", "intersection"}
    missing = required - geometry_types
    if missing:
        print("FAIL missing geometry types in full scan:", sorted(missing))
        print("found:", sorted(geometry_types))
        return False
    print("PASS full scan found {} non-none relationships across {} panels".format(
        len(relationships),
        len(panels),
    ))
    print("  geometry types:", sorted(geometry_types))
    return True


def validate_semantic_rules() -> bool:
    _print_section("Semantic rule checks")
    from relationship_geometry import classify_pair
    from relationship_models import BBoxMm, PanelSnapshot

    z = 12000.0

    # edge_to_surface host/target
    surface = PanelSnapshot(
        panelId="S",
        bodyName="S",
        bbox=BBoxMm(0, 300, 0, 300, z, z + 16),
        sizeX=300,
        sizeY=300,
        sizeZ=16,
        thicknessAxis="Z",
        thicknessMm=16,
        boardType="carcass_panel",
    )
    edge = PanelSnapshot(
        panelId="E",
        bodyName="E",
        bbox=BBoxMm(0, 300, 300, 315, z, z + 300),
        sizeX=300,
        sizeY=15,
        sizeZ=300,
        thicknessAxis="Y",
        thicknessMm=15,
        boardType="structural_edge",
    )
    rel = classify_pair(edge, surface)
    if rel.geometryType != "edge_to_surface":
        print("FAIL edge_to_surface rule")
        return False
    if rel.roles.hostPanelId != "S" or rel.roles.targetPanelId != "E":
        print("FAIL host/target inference", rel.roles.to_dict())
        return False
    if not any("host/target inferred" in w for w in rel.validation.warnings):
        print("FAIL missing host/target warning")
        return False

    # collision invalidates validation
    collision = classify_pair(
        PanelSnapshot("A", "A", BBoxMm(0, 100, 0, 100, 0, 100), sizeX=100, sizeY=100, sizeZ=100),
        PanelSnapshot("B", "B", BBoxMm(50, 150, 50, 150, 50, 150), sizeX=100, sizeY=100, sizeZ=100),
    )
    if collision.geometryType != "intersection" or collision.validation.ok:
        print("FAIL collision validation")
        return False

    # gap_parallel door candidate
    door = PanelSnapshot(
        panelId="D",
        bodyName="D",
        bbox=BBoxMm(0, 300, 0, 300, z, z + 16),
        sizeX=300,
        sizeY=300,
        sizeZ=16,
        thicknessAxis="Z",
        thicknessMm=16,
        boardType="door_panel",
        role="door",
    )
    carcass = PanelSnapshot(
        panelId="C",
        bodyName="C",
        bbox=BBoxMm(0, 300, 0, 300, z + 20, z + 36),
        sizeX=300,
        sizeY=300,
        sizeZ=16,
        thicknessAxis="Z",
        thicknessMm=16,
        boardType="carcass_side",
        role="carcass",
    )
    gap = classify_pair(door, carcass)
    if gap.geometryType != "gap_parallel":
        print("FAIL gap_parallel rule")
        return False
    if gap.relationshipType != "door_to_carcass_candidate":
        print("FAIL door_to_carcass_candidate", gap.relationshipType)
        return False

    print("PASS semantic rules (host/target, collision, door gap candidate)")
    return True


def validate_controller_routes() -> bool:
    _print_section("Controller route smoke (mock Fusion)")
    from modules.relationships.controller import RelationshipsController

    class MockBody:
        def __init__(self, panel_id, bbox_dict):
            self.name = panel_id
            self.isSolid = True
            self.isVisible = True
            self.attributes = MagicMock()

            def item_by_name(group, name):
                if group == "UnifiedCabinetPlugin" and name == "boardId":
                    return MagicMock(value=panel_id)
                if group == "UnifiedCabinet.Panel" and name == "panelId":
                    return MagicMock(value=panel_id)
                return None

            self.attributes.itemByName.side_effect = item_by_name
            self.boundingBox = MagicMock()
            min_pt = MagicMock()
            max_pt = MagicMock()
            min_pt.x = bbox_dict["x0"] / 10.0
            min_pt.y = bbox_dict["y0"] / 10.0
            min_pt.z = bbox_dict["z0"] / 10.0
            max_pt.x = bbox_dict["x1"] / 10.0
            max_pt.y = bbox_dict["y1"] / 10.0
            max_pt.z = bbox_dict["z1"] / 10.0
            self.boundingBox.minPoint = min_pt
            self.boundingBox.maxPoint = max_pt

        def __getattr__(self, name):
            if name in ("parentComponent", "component"):
                return None
            raise AttributeError(name)

    from relationship_fixtures import fixture_panel_definitions

    bodies = [MockBody(item["panelId"], item["bbox"]) for item in fixture_panel_definitions()]

    mock_fusion = MagicMock()
    mock_fusion.get_root_component.return_value = MagicMock()
    mock_fusion.get_selected_entities.return_value = [bodies[1], bodies[0]]

    controller = RelationshipsController(mock_fusion)

    def collect_from_mock(_bodies=None):
        from relationship_service import build_panel_snapshot

        return [build_panel_snapshot(body) for body in bodies]

    controller.service.collect_panels_from_design = collect_from_mock

    event, scan_payload = controller.scan({"scope": "all", "toleranceMm": 0.5}, None)
    if event != "relationshipScanResult" or not scan_payload.get("panelCount"):
        print("FAIL relationships.scan", scan_payload)
        return False

    event, selected_payload = controller.scan_selected({"toleranceMm": 0.5}, None)
    if event != "relationshipScanResult":
        print("FAIL relationships.scanSelected event")
        return False
    if selected_payload.get("relationshipCount", 0) < 1:
        print("FAIL relationships.scanSelected expected at least one relationship")
        return False

    event, inspect_payload = controller.inspect_pair(
        {"panelAId": "REL_EDGE_A", "panelBId": "REL_SURFACE_B", "toleranceMm": 0.5},
        None,
    )
    if event != "relationshipInspectResult" or inspect_payload.get("audit", {}).get("geometryType") != "edge_to_surface":
        print("FAIL relationships.inspectPair", inspect_payload)
        return False

    event, probe_payload = controller.probe_selection({}, None)
    if event != "relationshipSelectionResult" or probe_payload.get("selectedPanelBodyCount") != 2:
        print("FAIL relationships.probeSelection", probe_payload)
        return False

    print("PASS controller routes: scan panelCount={} selectedRelationships={} inspect={}".format(
        scan_payload.get("panelCount"),
        selected_payload.get("relationshipCount"),
        inspect_payload.get("audit", {}).get("geometryType"),
    ))
    return True


def validate_routes_registered() -> bool:
    _print_section("UnifiedCabinetPlugin route registration")
    plugin_path = ROOT / "UnifiedCabinetPlugin.py"
    text = plugin_path.read_text(encoding="utf-8")
    required = [
        "relationships.scan",
        "relationships.scanSelected",
        "relationships.inspectPair",
        "relationships.probeSelection",
        "relationships.createTestFixture",
        "relationships.showRelationshipOverlayForSelected",
        "relationships.reconcileGeneratorDeclarations",
        "relationships.verifySelectedPairFaces",
        "relationships.verifyAllBboxCandidates",
        "relationships.runOverlaySelfCheck",
        "relationships.clearRelationshipOverlays",
        "relationships.showContactPatchOverlayForSelected",
        "relationships.clearContactPatchOverlays",
        "modules.relationships.controller",
    ]
    missing = [route for route in required if route not in text]
    if missing:
        print("FAIL missing in UnifiedCabinetPlugin.py:", missing)
        return False
    print("PASS all relationships routes registered")
    return True


def main() -> int:
    checks: List[tuple[str, bool]] = [
        ("unittest", run_unittest_suite()),
        ("fixtures", validate_fixture_cases()),
        ("audit_schema", validate_audit_schema()),
        ("pairwise_scan", validate_pairwise_scan_simulation()),
        ("semantic_rules", validate_semantic_rules()),
        ("controller_routes", validate_controller_routes()),
        ("plugin_routes", validate_routes_registered()),
    ]

    _print_section("Summary")
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print("[{}] {}".format("PASS" if ok else "FAIL", name))

    if failed:
        print("\nRelationship regression FAILED:", ", ".join(failed))
        return 1

    print("\nRelationship regression ALL PASS ({} checks)".format(len(checks)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
