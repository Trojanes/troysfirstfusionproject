"""Relationship-driven screw hole preview rule (v1)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from hardware_models import (
    HARDWARE_SCHEMA_VERSION,
    HardwareFeatureGeometry,
    HardwareFeatureIntent,
    HardwareFeatureSource,
    HardwareFeatureValidation,
)

RULE_ID = "screw_hole_from_edge_to_surface_v1"
OPERATION_TYPE = "SCREW_HOLE_FROM_RELATIONSHIP"
CREATE_ACTION = "hardware.createScrewHolesFromRelationship"
PREVIEW_ACTION = "hardware.previewScrewHolesFromRelationship"
ACCEPTED_GEOMETRY_TYPE = "edge_to_surface"
ACCEPTED_RELATIONSHIP_TYPE = "structural_butt_joint"
CUT_BLOCKED_MESSAGE = (
    "Relationship is not cut-safe. Apply manual confirmation or face verification before cut."
)
NO_MANUAL_CONFIRMED_FOR_CUT_MESSAGE = (
    "No manual_confirmed relationship available. Scan, preview, and confirm a relationship before creating cut."
)


def resolve_relationship_verification(relationship: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from relationship_models import verification_from_dict

        return verification_from_dict(
            relationship.get("verification") if isinstance(relationship, dict) else None
        ).to_dict()
    except Exception:
        raw = (relationship or {}).get("verification") if isinstance(relationship, dict) else {}
        if not isinstance(raw, dict):
            raw = {}
        return {
            "level": str(raw.get("level") or "bbox_candidate"),
            "safeForPreview": bool(raw.get("safeForPreview", True)),
            "safeForCut": bool(raw.get("safeForCut", False)),
            "requiresManualConfirmation": bool(raw.get("requiresManualConfirmation", True)),
        }


def assert_safe_for_preview(relationship: Dict[str, Any]) -> Optional[str]:
    verification = resolve_relationship_verification(relationship)
    if not verification.get("safeForPreview"):
        return "Relationship verification does not allow hardware preview."
    return None


def assert_safe_for_cut(relationship: Dict[str, Any]) -> Optional[str]:
    verification = resolve_relationship_verification(relationship)
    if not verification.get("safeForCut"):
        return CUT_BLOCKED_MESSAGE
    return None


def validate_manual_confirmed_relationship_for_cut(relationship: Dict[str, Any]) -> Optional[str]:
    """Return an error message when relationship is not manual_confirmed with safeForCut=true."""
    if not isinstance(relationship, dict):
        return NO_MANUAL_CONFIRMED_FOR_CUT_MESSAGE
    verification = resolve_relationship_verification(relationship)
    if verification.get("level") != "manual_confirmed" or not verification.get("safeForCut"):
        if verification.get("level") == "manual_confirmed" and not verification.get("safeForCut"):
            return CUT_BLOCKED_MESSAGE
        return NO_MANUAL_CONFIRMED_FOR_CUT_MESSAGE
    return None


def hole_count_from_contact_length(contact_length_mm: float) -> int:
    length = float(contact_length_mm)
    if length < 120:
        return 1
    if length < 400:
        return 2
    return 3


def _axis_value(snapshot: Dict[str, Any], axis: str, bound: str) -> float:
    bbox = snapshot.get("bbox") or {}
    key = "{}{}".format(axis.lower(), "0" if bound == "min" else "1")
    return float(bbox.get(key, 0.0))


def _axis_size(snapshot: Dict[str, Any], axis: str) -> float:
    return abs(_axis_value(snapshot, axis, "max") - _axis_value(snapshot, axis, "min"))


def _contact_patch_from_snapshots(
    host_snapshot: Dict[str, Any],
    target_snapshot: Dict[str, Any],
    contact_axis: str,
) -> Tuple[float, float, float, float, float, float, float]:
    """Return x0,x1,y0,y1,z0,z1 overlap bounds and host contact face coordinate."""
    axes = ["X", "Y", "Z"]
    bounds = {}
    for axis in axes:
        h0 = _axis_value(host_snapshot, axis, "min")
        h1 = _axis_value(host_snapshot, axis, "max")
        t0 = _axis_value(target_snapshot, axis, "min")
        t1 = _axis_value(target_snapshot, axis, "max")
        bounds[axis] = (max(h0, t0), min(h1, t1))

    for axis in axes:
        if axis == contact_axis:
            continue
        low, high = bounds[axis]
        if high <= low:
            raise ValueError("Contact patch overlap is empty on {} axis.".format(axis))

    x0, x1 = bounds["X"]
    y0, y1 = bounds["Y"]
    z0, z1 = bounds["Z"]

    host_min = _axis_value(host_snapshot, contact_axis, "min")
    host_max = _axis_value(host_snapshot, contact_axis, "max")
    target_min = _axis_value(target_snapshot, contact_axis, "min")
    target_max = _axis_value(target_snapshot, contact_axis, "max")

    candidates = [
        (abs(target_min - host_max), host_max),
        (abs(target_max - host_min), host_min),
    ]
    host_face = min(candidates, key=lambda item: item[0])[1]

    return x0, x1, y0, y1, z0, z1, host_face


def _length_and_width_axes(contact_axis: str, overlaps: Dict[str, float]) -> Tuple[str, str]:
    non_contact = [axis for axis in ("X", "Y", "Z") if axis != contact_axis]
    if overlaps[non_contact[0]] >= overlaps[non_contact[1]]:
        return non_contact[0], non_contact[1]
    return non_contact[1], non_contact[0]


def _bounds_for_axes(x0, x1, y0, y1, z0, z1) -> Dict[str, Tuple[float, float]]:
    return {"X": (x0, x1), "Y": (y0, y1), "Z": (z0, z1)}


def _point_from_axes(
    axis_values: Dict[str, float],
) -> Dict[str, float]:
    return {
        "x": round(float(axis_values.get("X", 0.0)), 4),
        "y": round(float(axis_values.get("Y", 0.0)), 4),
        "z": round(float(axis_values.get("Z", 0.0)), 4),
    }


def _build_hole_positions(
    *,
    contact_axis: str,
    host_face: float,
    bounds: Dict[str, Tuple[float, float]],
    overlaps: Dict[str, float],
    hole_count: int,
    edge_offset_mm: float,
) -> List[Dict[str, float]]:
    length_axis, width_axis = _length_and_width_axes(contact_axis, overlaps)
    length_start, length_end = bounds[length_axis]
    width_center = (bounds[width_axis][0] + bounds[width_axis][1]) / 2.0
    positions = []
    for value in _spread_positions(length_start, length_end, hole_count, edge_offset_mm):
        axis_values = {
            length_axis: value,
            width_axis: width_center,
            contact_axis: host_face,
        }
        positions.append(_point_from_axes(axis_values))
    return positions


def _spread_positions(start: float, end: float, count: int, edge_offset_mm: float) -> List[float]:
    length = end - start
    if length <= 0:
        raise ValueError("Contact length must be greater than zero.")
    if count == 1:
        return [(start + end) / 2.0]
    usable_start = start + edge_offset_mm
    usable_end = end - edge_offset_mm
    if usable_end < usable_start:
        raise ValueError("edgeOffsetMm is too large for contact length.")
    if count == 2:
        return [usable_start, usable_end]
    step = (usable_end - usable_start) / float(count - 1)
    return [usable_start + step * index for index in range(count)]


def _resolve_host_depth_mm(host_snapshot: Dict[str, Any], contact_axis: str, depth_mode: str) -> float:
    if depth_mode != "host_thickness":
        raise ValueError("Unsupported depthMode: {}".format(depth_mode))
    inferred = ((host_snapshot.get("inferred") or {}).get("thicknessAxis"))
    thickness = ((host_snapshot.get("dimensions") or {}).get("thicknessMm"))
    if thickness is not None:
        return float(thickness)
    if inferred in ("X", "Y", "Z"):
        return _axis_size(host_snapshot, inferred)
    return _axis_size(host_snapshot, contact_axis)


def preview_screw_holes_from_relationship(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    rule = rule or {}
    warnings: List[str] = []
    errors: List[str] = []

    if not isinstance(relationship, dict):
        return _error_report("Relationship payload must be an object.", errors=["Missing relationship object."])

    preview_gate_error = assert_safe_for_preview(relationship)
    if preview_gate_error:
        return _error_report("Relationship is not verified for preview.", errors=[preview_gate_error])

    geometry_type = str(relationship.get("geometryType") or "")
    relationship_type = str(relationship.get("relationshipType") or "")
    if geometry_type != ACCEPTED_GEOMETRY_TYPE or relationship_type != ACCEPTED_RELATIONSHIP_TYPE:
        return _error_report(
            "Relationship type not supported for screw_hole preview.",
            errors=[
                "Only edge_to_surface + structural_butt_joint is supported; got {} / {}.".format(
                    geometry_type,
                    relationship_type,
                )
            ],
        )

    roles = relationship.get("roles") or {}
    host_panel_id = str(roles.get("hostPanelId") or "").strip()
    target_panel_id = str(roles.get("targetPanelId") or "").strip()
    if not host_panel_id or not target_panel_id:
        return _error_report(
            "Relationship roles are incomplete.",
            errors=["hostPanelId and targetPanelId are required; relationship roles must not be inferred here."],
        )

    contact = relationship.get("contact") or {}
    contact_axis = str(contact.get("axis") or "NONE")
    if contact_axis not in ("X", "Y", "Z"):
        return _error_report(
            "Relationship contact axis is invalid.",
            errors=["contact.axis must be X, Y, or Z for screw_hole preview."],
        )

    contact_length_mm = float(contact.get("contactLengthMm") or 0.0)
    if contact_length_mm <= 0:
        return _error_report(
            "Relationship contact length is invalid.",
            errors=["contact.contactLengthMm must be greater than zero."],
        )

    panel_snapshots = panel_snapshots or {}
    host_snapshot = panel_snapshots.get(host_panel_id)
    target_snapshot = panel_snapshots.get(target_panel_id)
    if not host_snapshot or not target_snapshot:
        return _error_report(
            "Panel snapshots are required for absolute screw-hole preview coordinates.",
            errors=[
                "Provide panels[hostPanelId] and panels[targetPanelId] snapshots for previewScrewHolesFromRelationship.",
            ],
        )

    diameter_mm = float(rule.get("diameterMm") or 4.0)
    edge_offset_mm = float(rule.get("edgeOffsetMm") or 30.0)
    depth_mode = str(rule.get("depthMode") or "host_thickness")
    hole_count = hole_count_from_contact_length(contact_length_mm)

    try:
        x0, x1, y0, y1, z0, z1, host_face = _contact_patch_from_snapshots(
            host_snapshot,
            target_snapshot,
            contact_axis,
        )
        depth_mm = _resolve_host_depth_mm(host_snapshot, contact_axis, depth_mode)
        bounds = _bounds_for_axes(x0, x1, y0, y1, z0, z1)
        overlaps = {
            "X": float(contact.get("overlapX") or (x1 - x0)),
            "Y": float(contact.get("overlapY") or (y1 - y0)),
            "Z": float(contact.get("overlapZ") or (z1 - z0)),
        }
        positions = _build_hole_positions(
            contact_axis=contact_axis,
            host_face=host_face,
            bounds=bounds,
            overlaps=overlaps,
            hole_count=hole_count,
            edge_offset_mm=edge_offset_mm,
        )
    except ValueError as ex:
        return _error_report("Failed to derive contact patch from panel snapshots.", errors=[str(ex)])

    relationship_id = str(relationship.get("relationshipId") or "relationship.unknown")
    verification = resolve_relationship_verification(relationship)
    detection_method = str(relationship.get("detectionMethod") or "bbox_aabb")
    feature = HardwareFeatureIntent(
        schemaVersion=HARDWARE_SCHEMA_VERSION,
        featureId="{}::screw_hole".format(relationship_id),
        type="screw_hole",
        sourceRelationshipId=relationship_id,
        hostPanelId=host_panel_id,
        targetPanelId=target_panel_id,
        geometry=HardwareFeatureGeometry(
            diameterMm=diameter_mm,
            depthMm=depth_mm,
            axis=contact_axis,
            positions=positions,
        ),
        source=HardwareFeatureSource(method="relationship_based_rule", ruleId=RULE_ID),
        validation=HardwareFeatureValidation(ok=True, warnings=warnings, errors=errors),
    )

    return {
        "ok": True,
        "action": PREVIEW_ACTION,
        "relationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "contactLengthMm": round(contact_length_mm, 4),
        "holeCount": hole_count,
        "features": [feature.to_dict()],
        "audit": {
            "geometryType": geometry_type,
            "relationshipType": relationship_type,
            "ruleId": RULE_ID,
            "contactAxis": contact_axis,
            "diameterMm": diameter_mm,
            "edgeOffsetMm": edge_offset_mm,
            "depthMode": depth_mode,
            "depthMm": round(depth_mm, 4),
            "positions": feature.geometry.to_dict()["positions"],
            "detectionMethod": detection_method,
            "verification": verification,
            "verificationLevel": verification.get("level"),
            "safeForPreview": verification.get("safeForPreview"),
            "safeForCut": verification.get("safeForCut"),
            "requiresManualConfirmation": verification.get("requiresManualConfirmation"),
            "warnings": warnings,
            "errors": errors,
        },
    }


def _error_report(message: str, errors: List[str], warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "ok": False,
        "action": PREVIEW_ACTION,
        "message": message,
        "features": [],
        "audit": {
            "warnings": list(warnings or []),
            "errors": list(errors),
        },
        "errors": list(errors),
    }


def _create_error_report(message: str, errors: List[str], warnings: Optional[List[str]] = None) -> Dict[str, Any]:
    report = _error_report(message, errors, warnings)
    report["action"] = CREATE_ACTION
    return report


def build_cut_feature_metadata(
    feature: Dict[str, Any],
    *,
    relationship_id: str,
    host_panel_id: str,
    target_panel_id: str,
) -> Dict[str, Any]:
    geometry = feature.get("geometry") or {}
    return {
        "operationType": OPERATION_TYPE,
        "sourceRelationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "ruleId": RULE_ID,
        "holeCount": len(geometry.get("positions") or []),
        "diameterMm": round(float(geometry.get("diameterMm") or 0.0), 4),
        "depthMm": round(float(geometry.get("depthMm") or 0.0), 4),
    }


def plan_screw_hole_cut_from_relationship(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cut_gate_error = assert_safe_for_cut(relationship)
    if cut_gate_error:
        return _create_error_report(
            "Relationship is not verified for cut.",
            errors=[cut_gate_error],
        )

    preview = preview_screw_holes_from_relationship(
        relationship,
        rule=rule,
        panel_snapshots=panel_snapshots,
    )
    if not preview.get("ok"):
        return _create_error_report(
            preview.get("message") or "Screw-hole preview failed.",
            list(preview.get("errors") or ["Preview failed."]),
            list((preview.get("audit") or {}).get("warnings") or []),
        )

    features = preview.get("features") or []
    if not features:
        return _create_error_report("No hardware features were generated.", errors=["Missing feature intents."])

    feature = features[0]
    relationship_id = str(preview.get("relationshipId") or relationship.get("relationshipId") or "")
    host_panel_id = str(preview.get("hostPanelId") or "")
    target_panel_id = str(preview.get("targetPanelId") or "")
    metadata = build_cut_feature_metadata(
        feature,
        relationship_id=relationship_id,
        host_panel_id=host_panel_id,
        target_panel_id=target_panel_id,
    )
    return {
        "ok": True,
        "action": CREATE_ACTION,
        "relationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "holeCount": preview.get("holeCount"),
        "feature": feature,
        "metadata": metadata,
        "preview": preview,
    }


def build_cut_success_report(
    *,
    relationship_id: str,
    host_panel_id: str,
    target_panel_id: str,
    host_body_name: str,
    target_body_name: str,
    cut_feature_name: str,
    metadata: Dict[str, Any],
    metadata_written: bool,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "ok": True,
        "action": CREATE_ACTION,
        "operationType": OPERATION_TYPE,
        "relationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "hostBodyName": host_body_name,
        "targetBodyName": target_body_name,
        "holeCount": metadata.get("holeCount"),
        "cutFeatureName": cut_feature_name,
        "metadataWritten": metadata_written,
        "metadata": metadata,
        "targetBodyModified": False,
        "warnings": list(warnings or []),
        "errors": [],
        "audit": {
            "operationType": OPERATION_TYPE,
            "relationshipId": relationship_id,
            "hostPanelId": host_panel_id,
            "targetPanelId": target_panel_id,
            "holeCount": metadata.get("holeCount"),
            "cutFeatureName": cut_feature_name,
            "metadataWritten": metadata_written,
            "targetBodyModified": False,
            "metadata": metadata,
            "warnings": list(warnings or []),
            "errors": [],
        },
    }
