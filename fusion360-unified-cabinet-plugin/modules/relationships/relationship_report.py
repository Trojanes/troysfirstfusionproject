"""JSON audit reports for relationship scans."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from relationship_models import BoardRelationship, PanelSnapshot


def relationship_audit_row(relationship: BoardRelationship) -> Dict[str, Any]:
    verification = relationship.verification.to_dict()
    return {
        "relationshipId": relationship.relationshipId,
        "panelAId": relationship.panelA.panelId,
        "panelBId": relationship.panelB.panelId,
        "panelABodyName": relationship.panelA.bodyName,
        "panelBBodyName": relationship.panelB.bodyName,
        "geometryType": relationship.geometryType,
        "relationshipType": relationship.relationshipType,
        "detectionMethod": relationship.detectionMethod,
        "verificationLevel": verification["level"],
        "safeForPreview": verification["safeForPreview"],
        "safeForCut": verification["safeForCut"],
        "requiresManualConfirmation": verification["requiresManualConfirmation"],
        "axis": relationship.contact.axis,
        "distanceMm": relationship.contact.distanceMm,
        "overlapX": relationship.contact.overlapX,
        "overlapY": relationship.contact.overlapY,
        "overlapZ": relationship.contact.overlapZ,
        "contactAreaMm2": relationship.contact.contactAreaMm2,
        "contactLengthMm": relationship.contact.contactLengthMm,
        "confidence": relationship.source.confidence,
        "ruleId": relationship.source.ruleId,
        "hostPanelId": relationship.roles.hostPanelId,
        "targetPanelId": relationship.roles.targetPanelId,
        "warnings": list(relationship.validation.warnings),
        "errors": list(relationship.validation.errors),
        "auditNotes": list(relationship.auditNotes),
    }


def build_scan_report(
    *,
    action: str,
    panels: Iterable[PanelSnapshot],
    relationships: Iterable[BoardRelationship],
    scope: str,
    tolerance_mm: float,
    expected_fixtures: Optional[List[Dict[str, Any]]] = None,
    errors: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    panel_list = list(panels)
    relationship_list = list(relationships)
    audit_rows = [relationship_audit_row(item) for item in relationship_list]

    matched_expected: List[Dict[str, Any]] = []
    if expected_fixtures:
        for fixture in expected_fixtures:
            case_id = fixture.get("caseId")
            panel_a_id = fixture.get("panelAId")
            panel_b_id = fixture.get("panelBId")
            expected_geometry = fixture.get("expectedGeometryType")
            match = next(
                (
                    row
                    for row in audit_rows
                    if {row["panelAId"], row["panelBId"]} == {panel_a_id, panel_b_id}
                    and row["geometryType"] == expected_geometry
                ),
                None,
            )
            matched_expected.append(
                {
                    "caseId": case_id,
                    "panelAId": panel_a_id,
                    "panelBId": panel_b_id,
                    "expectedGeometryType": expected_geometry,
                    "matched": bool(match),
                    "actualGeometryType": match["geometryType"] if match else None,
                    "relationshipId": match["relationshipId"] if match else None,
                }
            )

    ok = not errors
    if expected_fixtures:
        ok = ok and all(item.get("matched") for item in matched_expected)

    return {
        "ok": ok,
        "action": action,
        "scope": scope,
        "toleranceMm": tolerance_mm,
        "panelCount": len(panel_list),
        "relationshipCount": len(relationship_list),
        "panels": [panel.to_dict() for panel in panel_list],
        "relationships": [item.to_dict() for item in relationship_list],
        "audit": audit_rows,
        "expectedFixtures": matched_expected,
        "warnings": list(warnings or []),
        "errors": list(errors or []),
    }


def build_inspect_pair_report(
    *,
    relationship: BoardRelationship,
    tolerance_mm: float,
) -> Dict[str, Any]:
    return {
        "ok": relationship.validation.ok,
        "action": "relationships.inspectPair",
        "toleranceMm": tolerance_mm,
        "relationship": relationship.to_dict(),
        "audit": relationship_audit_row(relationship),
    }
