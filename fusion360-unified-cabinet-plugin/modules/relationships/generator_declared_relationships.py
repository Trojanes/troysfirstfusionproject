"""M6 generator-declared relationship core logic (offline-testable)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from relationship_models import (
    DETECTION_METHOD_BBOX_AABB,
    BoardRelationship,
    RelationshipSource,
    generator_declared_verification,
    make_relationship_id,
)

SOURCE_METHOD_GENERATOR_DECLARED = "generator_declared"
DETECTION_METHOD_GENERATOR_DECLARED = "generator_declared"


def pair_key(panel_a_id: str, panel_b_id: str) -> Tuple[str, str]:
    a = str(panel_a_id or "")
    b = str(panel_b_id or "")
    return (a, b) if a <= b else (b, a)


def find_geometry_relationship(
    relationships: List[BoardRelationship],
    panel_a_id: str,
    panel_b_id: str,
) -> Optional[BoardRelationship]:
    target = {panel_a_id, panel_b_id}
    for rel in relationships:
        if {rel.panelA.panelId, rel.panelB.panelId} == target:
            return rel
    return None


def validate_declared_against_geometry(
    declaration: Dict[str, Any],
    geometry: Optional[BoardRelationship],
) -> Dict[str, Any]:
    errors: List[str] = []
    warnings: List[str] = []
    panel_a_id = str(declaration.get("panelAId") or "")
    panel_b_id = str(declaration.get("panelBId") or "")
    expected_geometry = str(declaration.get("geometryType") or "")
    expected_type = str(declaration.get("relationshipType") or "")

    if geometry is None:
        errors.append("No geometry relationship found for declared pair {} ↔ {}.".format(panel_a_id, panel_b_id))
        return {"ok": False, "errors": errors, "warnings": warnings}

    if geometry.geometryType != expected_geometry:
        errors.append(
            "Declared geometryType {} does not match detected {}.".format(
                expected_geometry,
                geometry.geometryType,
            )
        )
    if geometry.relationshipType != expected_type:
        warnings.append(
            "Declared relationshipType {} differs from detected {}.".format(
                expected_type,
                geometry.relationshipType,
            )
        )

    declared_host = str(declaration.get("hostPanelId") or "")
    declared_target = str(declaration.get("targetPanelId") or "")
    if declared_host and declared_target:
        roles = geometry.roles.to_dict()
        if roles.get("hostPanelId") != declared_host or roles.get("targetPanelId") != declared_target:
            warnings.append(
                "Declared host/target ({}/{}) differ from geometry inference ({}/{}).".format(
                    declared_host,
                    declared_target,
                    roles.get("hostPanelId"),
                    roles.get("targetPanelId"),
                )
            )

    ok = not errors
    return {"ok": ok, "errors": errors, "warnings": warnings}


def merge_declared_with_geometry(
    declaration: Dict[str, Any],
    geometry: BoardRelationship,
    geometry_validation: Dict[str, Any],
) -> Dict[str, Any]:
    verification = generator_declared_verification(geometry_ok=bool(geometry_validation.get("ok"))).to_dict()
    roles = geometry.roles.to_dict()
    if declaration.get("hostPanelId"):
        roles["hostPanelId"] = declaration.get("hostPanelId")
    if declaration.get("targetPanelId"):
        roles["targetPanelId"] = declaration.get("targetPanelId")

    relationship_id = str(
        declaration.get("relationshipId")
        or geometry.relationshipId
        or make_relationship_id(geometry.panelA.panelId, geometry.panelB.panelId)
    )
    merged = geometry.to_dict()
    merged.update(
        {
            "relationshipId": relationship_id,
            "relationshipType": str(declaration.get("relationshipType") or geometry.relationshipType),
            "geometryType": str(declaration.get("geometryType") or geometry.geometryType),
            "roles": roles,
            "verification": verification,
            "detectionMethod": DETECTION_METHOD_GENERATOR_DECLARED,
            "source": RelationshipSource(
                method=SOURCE_METHOD_GENERATOR_DECLARED,
                confidence=geometry.source.confidence,
                ruleId=str(declaration.get("ruleId") or geometry.source.ruleId or ""),
            ).to_dict(),
            "geometryValidation": dict(geometry_validation or {}),
            "declaration": {
                "declarationId": declaration.get("declarationId"),
                "generator": declaration.get("generator"),
                "ruleId": declaration.get("ruleId"),
                "allowedHardware": list(declaration.get("allowedHardware") or []),
            },
        }
    )
    notes = list(merged.get("auditNotes") or [])
    notes.append("Generator-declared relationship reconciled with geometry (M6).")
    merged["auditNotes"] = notes
    if geometry_validation.get("warnings"):
        merged.setdefault("validation", {})
        merged["validation"]["warnings"] = list(
            dict.fromkeys(list(merged["validation"].get("warnings") or []) + list(geometry_validation.get("warnings") or []))
        )
    if geometry_validation.get("errors"):
        merged.setdefault("validation", {})
        merged["validation"]["errors"] = list(
            dict.fromkeys(list(merged["validation"].get("errors") or []) + list(geometry_validation.get("errors") or []))
        )
    return merged


def reconcile_declarations_with_geometry(
    declarations: List[Dict[str, Any]],
    geometry_relationships: List[BoardRelationship],
) -> Dict[str, Any]:
    reconciled: List[Dict[str, Any]] = []
    errors: List[str] = []
    warnings: List[str] = []
    geometry_ok_count = 0

    for declaration in declarations or []:
        panel_a_id = str(declaration.get("panelAId") or "")
        panel_b_id = str(declaration.get("panelBId") or "")
        geometry = find_geometry_relationship(geometry_relationships, panel_a_id, panel_b_id)
        validation = validate_declared_against_geometry(declaration, geometry)
        if validation.get("warnings"):
            warnings.extend(["{}: {}".format(declaration.get("declarationId"), item) for item in validation["warnings"]])
        if geometry is None:
            errors.extend(["{}: {}".format(declaration.get("declarationId"), item) for item in validation.get("errors") or []])
            reconciled.append(
                {
                    "declarationId": declaration.get("declarationId"),
                    "panelAId": panel_a_id,
                    "panelBId": panel_b_id,
                    "ok": False,
                    "geometryValidation": validation,
                    "relationship": None,
                }
            )
            continue
        if validation.get("ok"):
            geometry_ok_count += 1
        else:
            errors.extend(["{}: {}".format(declaration.get("declarationId"), item) for item in validation.get("errors") or []])
        merged = merge_declared_with_geometry(declaration, geometry, validation)
        reconciled.append(
            {
                "declarationId": declaration.get("declarationId"),
                "panelAId": panel_a_id,
                "panelBId": panel_b_id,
                "ok": bool(validation.get("ok")),
                "geometryValidation": validation,
                "relationship": merged,
            }
        )

    return {
        "ok": geometry_ok_count > 0 and not any(item.get("ok") is False for item in reconciled if item.get("relationship")),
        "declarationCount": len(declarations or []),
        "geometryOkCount": geometry_ok_count,
        "reconciled": reconciled,
        "relationships": [item["relationship"] for item in reconciled if item.get("relationship")],
        "errors": errors,
        "warnings": warnings,
    }


def build_reconcile_report(
    *,
    generator: str,
    panels: List[Any],
    reconcile_result: Dict[str, Any],
    geometry_relationships: List[BoardRelationship],
    action: str = "relationships.reconcileGeneratorDeclarations",
) -> Dict[str, Any]:
    panel_payloads = []
    for panel in panels or []:
        if hasattr(panel, "to_dict"):
            panel_payloads.append(panel.to_dict())
        elif isinstance(panel, dict):
            panel_payloads.append(panel)
    return {
        "ok": bool(reconcile_result.get("ok")),
        "action": action,
        "generator": generator,
        "panelCount": len(panels),
        "geometryRelationshipCount": len(geometry_relationships),
        "declarationCount": reconcile_result.get("declarationCount", 0),
        "geometryOkCount": reconcile_result.get("geometryOkCount", 0),
        "declaredRelationships": reconcile_result.get("relationships") or [],
        "reconciled": reconcile_result.get("reconciled") or [],
        "panels": panel_payloads,
        "errors": list(reconcile_result.get("errors") or []),
        "warnings": list(reconcile_result.get("warnings") or []),
    }
