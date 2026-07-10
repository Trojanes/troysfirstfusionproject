"""Relationship-driven tongue/groove preview + host-groove cut plan (post-M9)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from screw_hole_from_relationship import (
    ACCEPTED_GEOMETRY_TYPE,
    ACCEPTED_RELATIONSHIP_TYPE,
    _axis_size,
    _contact_patch_from_snapshots,
    _length_and_width_axes,
    assert_safe_for_cut,
    assert_safe_for_preview,
    resolve_relationship_verification,
)

RULE_ID = "tongue_groove_from_edge_to_surface_v1"
OPERATION_TYPE = "TONGUE_GROOVE_FROM_RELATIONSHIP"
PREVIEW_ACTION = "hardware.previewTongueGrooveFromRelationship"
CREATE_ACTION = "hardware.createTongueGrooveFromRelationship"
DEFAULT_GROOVE_DEPTH_MM = 8.0
DEFAULT_GROOVE_WIDTH_MM = 4.0
DEFAULT_TONGUE_PROTRUSION_MM = 7.0


def _error_report(
    message: str,
    *,
    errors: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
    action: str = PREVIEW_ACTION,
) -> Dict[str, Any]:
    errs = list(errors or [message])
    return {
        "ok": False,
        "action": action,
        "hardwareType": "tongue_groove",
        "message": message,
        "features": [],
        "audit": {"warnings": list(warnings or []), "errors": errs},
        "errors": errs,
        "previewOnly": False,
        "cutReady": True,
    }


def _groove_sketch_rect(
    *,
    contact_axis: str,
    x0: float,
    x1: float,
    y0: float,
    y1: float,
    z0: float,
    z1: float,
    host_face: float,
    groove_width_mm: float,
    groove_depth_mm: float,
) -> Dict[str, Any]:
    bounds = {"X": (x0, x1), "Y": (y0, y1), "Z": (z0, z1)}
    overlaps = {
        "X": max(0.0, x1 - x0),
        "Y": max(0.0, y1 - y0),
        "Z": max(0.0, z1 - z0),
    }
    length_axis, width_axis = _length_and_width_axes(contact_axis, overlaps)
    length_start, length_end = bounds[length_axis]
    width_center = (bounds[width_axis][0] + bounds[width_axis][1]) / 2.0
    half_w = max(0.05, groove_width_mm / 2.0)
    width_start = width_center - half_w
    width_end = width_center + half_w
    return {
        "planeAxis": contact_axis,
        "planeMm": round(float(host_face), 4),
        "depthMm": round(float(groove_depth_mm), 4),
        "lengthAxis": length_axis,
        "widthAxis": width_axis,
        "lengthMm": round(float(length_end - length_start), 4),
        "widthMm": round(float(groove_width_mm), 4),
        "u0": round(float(length_start), 4),
        "u1": round(float(length_end), 4),
        "v0": round(float(width_start), 4),
        "v1": round(float(width_end), 4),
    }


def _tongue_shoulders_from_groove_sketch(
    groove_sketch: Dict[str, Any],
    *,
    tongue_protrusion_mm: float,
    contact_patch_bounds: Dict[str, float],
) -> Dict[str, Any]:
    """Build target tongue as two shoulder cut rects flanking the groove width."""
    length_axis = str(groove_sketch.get("lengthAxis") or "")
    width_axis = str(groove_sketch.get("widthAxis") or "")
    contact_axis = str(groove_sketch.get("planeAxis") or "")
    u0 = float(groove_sketch.get("u0") or 0.0)
    u1 = float(groove_sketch.get("u1") or 0.0)
    tongue_v0 = float(groove_sketch.get("v0") or 0.0)
    tongue_v1 = float(groove_sketch.get("v1") or 0.0)
    patch_v0 = float(contact_patch_bounds.get("{}0".format(width_axis.lower())) or tongue_v0)
    patch_v1 = float(contact_patch_bounds.get("{}1".format(width_axis.lower())) or tongue_v1)
    # Keep shoulder order low→high on width axis.
    lo, hi = (patch_v0, patch_v1) if patch_v0 <= patch_v1 else (patch_v1, patch_v0)
    tv0, tv1 = (tongue_v0, tongue_v1) if tongue_v0 <= tongue_v1 else (tongue_v1, tongue_v0)
    shoulders = []
    if tv0 - lo > 0.05:
        shoulders.append({"u0": round(u0, 4), "u1": round(u1, 4), "v0": round(lo, 4), "v1": round(tv0, 4)})
    if hi - tv1 > 0.05:
        shoulders.append({"u0": round(u0, 4), "u1": round(u1, 4), "v0": round(tv1, 4), "v1": round(hi, 4)})
    if not shoulders:
        raise ValueError("Contact patch width is too narrow for tongue shoulders around groove width.")
    return {
        "planeAxis": contact_axis,
        "planeMm": float(groove_sketch.get("planeMm") or 0.0),
        "depthMm": round(float(tongue_protrusion_mm), 4),
        "lengthAxis": length_axis,
        "widthAxis": width_axis,
        "lengthMm": round(abs(u1 - u0), 4),
        "widthMm": round(abs(tv1 - tv0), 4),
        "u0": round(u0, 4),
        "u1": round(u1, 4),
        "v0": round(tv0, 4),
        "v1": round(tv1, 4),
        "shoulders": shoulders,
    }


def preview_tongue_groove_from_relationship(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Build tongue/groove machining intent from a verified edge_to_surface joint.

    Cut executes host groove + target tongue shoulders.
    """
    rule = rule or {}
    warnings: List[str] = []

    if not isinstance(relationship, dict):
        return _error_report("Relationship payload must be an object.", errors=["Missing relationship object."])

    preview_gate_error = assert_safe_for_preview(relationship)
    if preview_gate_error:
        return _error_report("Relationship is not verified for preview.", errors=[preview_gate_error])

    geometry_type = str(relationship.get("geometryType") or "")
    relationship_type = str(relationship.get("relationshipType") or "")
    if geometry_type != ACCEPTED_GEOMETRY_TYPE or relationship_type != ACCEPTED_RELATIONSHIP_TYPE:
        return _error_report(
            "Relationship type not supported for tongue_groove preview.",
            errors=[
                "Only edge_to_surface + structural_butt_joint is supported; got {} / {}.".format(
                    geometry_type,
                    relationship_type,
                )
            ],
        )

    roles = relationship.get("roles") or {}
    # Host receives groove (surface panel); target receives tongue (edge panel).
    host_panel_id = str(roles.get("hostPanelId") or "").strip()
    target_panel_id = str(roles.get("targetPanelId") or "").strip()
    if not host_panel_id or not target_panel_id:
        return _error_report(
            "Relationship roles are incomplete.",
            errors=["hostPanelId and targetPanelId are required."],
        )

    contact = relationship.get("contact") or {}
    contact_axis = str(contact.get("axis") or "NONE")
    if contact_axis not in ("X", "Y", "Z"):
        return _error_report(
            "Relationship contact axis is invalid.",
            errors=["contact.axis must be X, Y, or Z for tongue_groove preview."],
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
            "Panel snapshots are required for tongue/groove preview coordinates.",
            errors=[
                "Provide panels[hostPanelId] and panels[targetPanelId] snapshots.",
            ],
        )

    groove_depth_mm = float(rule.get("grooveDepthMm") or DEFAULT_GROOVE_DEPTH_MM)
    groove_width_mm = float(rule.get("grooveWidthMm") or DEFAULT_GROOVE_WIDTH_MM)
    tongue_protrusion_mm = float(rule.get("tongueProtrusionMm") or DEFAULT_TONGUE_PROTRUSION_MM)
    if tongue_protrusion_mm >= groove_depth_mm:
        warnings.append(
            "tongueProtrusionMm ({}) should be less than grooveDepthMm ({}) for clearance.".format(
                tongue_protrusion_mm, groove_depth_mm
            )
        )

    try:
        x0, x1, y0, y1, z0, z1, host_face = _contact_patch_from_snapshots(
            host_snapshot,
            target_snapshot,
            contact_axis,
        )
    except Exception as ex:
        return _error_report(
            "Failed to derive contact patch from panel snapshots.",
            errors=[str(ex)],
        )

    host_thickness = _axis_size(host_snapshot, contact_axis)
    if groove_depth_mm >= host_thickness:
        return _error_report(
            "Groove depth exceeds host thickness.",
            errors=[
                "grooveDepthMm ({}) must be less than host thickness on {} ({}).".format(
                    groove_depth_mm, contact_axis, host_thickness
                )
            ],
        )

    target_thickness = _axis_size(target_snapshot, contact_axis)
    if tongue_protrusion_mm >= target_thickness:
        return _error_report(
            "Tongue protrusion exceeds target thickness.",
            errors=[
                "tongueProtrusionMm ({}) must be less than target thickness on {} ({}).".format(
                    tongue_protrusion_mm, contact_axis, target_thickness
                )
            ],
        )

    sketch = _groove_sketch_rect(
        contact_axis=contact_axis,
        x0=x0,
        x1=x1,
        y0=y0,
        y1=y1,
        z0=z0,
        z1=z1,
        host_face=host_face,
        groove_width_mm=groove_width_mm,
        groove_depth_mm=groove_depth_mm,
    )
    if sketch["lengthMm"] <= 0:
        return _error_report(
            "Groove length is invalid.",
            errors=["Derived groove length must be greater than zero."],
        )

    try:
        tongue_sketch = _tongue_shoulders_from_groove_sketch(
            sketch,
            tongue_protrusion_mm=tongue_protrusion_mm,
            contact_patch_bounds={
                "x0": x0,
                "x1": x1,
                "y0": y0,
                "y1": y1,
                "z0": z0,
                "z1": z1,
            },
        )
    except ValueError as ex:
        return _error_report("Failed to derive tongue shoulders.", errors=[str(ex)])

    relationship_id = str(relationship.get("relationshipId") or "unknown")
    verification = resolve_relationship_verification(relationship)
    feature = {
        "schemaVersion": 1,
        "featureId": "{}::tongue_groove".format(relationship_id),
        "type": "tongue_groove",
        "sourceRelationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "hostRole": "groove",
        "targetRole": "tongue",
        "geometry": {
            "contactAxis": contact_axis,
            "contactLengthMm": round(contact_length_mm, 4),
            "contactPatchBoundsMm": {
                "x0": round(x0, 4),
                "x1": round(x1, 4),
                "y0": round(y0, 4),
                "y1": round(y1, 4),
                "z0": round(z0, 4),
                "z1": round(z1, 4),
            },
            "hostContactFaceMm": round(float(host_face), 4),
            "groove": {
                "panelId": host_panel_id,
                "widthMm": round(groove_width_mm, 4),
                "depthMm": round(groove_depth_mm, 4),
                "lengthMm": round(float(sketch["lengthMm"]), 4),
                "sketch": sketch,
            },
            "tongue": {
                "panelId": target_panel_id,
                "widthMm": round(groove_width_mm, 4),
                "protrusionMm": round(tongue_protrusion_mm, 4),
                "lengthMm": round(float(sketch["lengthMm"]), 4),
                "cutDeferred": False,
                "sketch": tongue_sketch,
            },
        },
        "source": {
            "method": "relationship_based_rule",
            "ruleId": RULE_ID,
        },
        "validation": {
            "ok": True,
            "warnings": list(warnings),
            "errors": [],
        },
    }

    return {
        "ok": True,
        "action": PREVIEW_ACTION,
        "hardwareType": "tongue_groove",
        "operationType": OPERATION_TYPE,
        "relationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "verificationLevel": verification.get("level"),
        "featureCount": 1,
        "features": [feature],
        "audit": {
            "ruleId": RULE_ID,
            "grooveDepthMm": groove_depth_mm,
            "grooveWidthMm": groove_width_mm,
            "tongueProtrusionMm": tongue_protrusion_mm,
            "contactAxis": contact_axis,
            "contactLengthMm": contact_length_mm,
            "tongueShoulderCount": len(tongue_sketch.get("shoulders") or []),
            "warnings": list(warnings),
            "errors": [],
        },
        "errors": [],
        "previewOnly": False,
        "cutReady": True,
        "message": "Tongue/groove preview intent ready (host groove + target tongue).",
    }


def build_cut_feature_metadata(
    feature: Dict[str, Any],
    *,
    relationship_id: str,
    host_panel_id: str,
    target_panel_id: str,
) -> Dict[str, Any]:
    geometry = feature.get("geometry") or {}
    groove = geometry.get("groove") or {}
    tongue = geometry.get("tongue") or {}
    tongue_sketch = tongue.get("sketch") or {}
    return {
        "operationType": OPERATION_TYPE,
        "sourceRelationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "ruleId": RULE_ID,
        "hostRole": "groove",
        "targetRole": "tongue",
        "grooveDepthMm": round(float(groove.get("depthMm") or 0.0), 4),
        "grooveWidthMm": round(float(groove.get("widthMm") or 0.0), 4),
        "grooveLengthMm": round(float(groove.get("lengthMm") or 0.0), 4),
        "tongueProtrusionMm": round(float(tongue.get("protrusionMm") or 0.0), 4),
        "tongueShoulderCount": len(tongue_sketch.get("shoulders") or []),
        "tongueCutDeferred": False,
        "depthMm": round(float(groove.get("depthMm") or 0.0), 4),
    }


def plan_tongue_groove_cut_from_relationship(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cut_gate_error = assert_safe_for_cut(relationship)
    if cut_gate_error:
        return _error_report(
            "Relationship is not verified for cut.",
            errors=[cut_gate_error],
            action=CREATE_ACTION,
        )

    preview = preview_tongue_groove_from_relationship(
        relationship,
        rule=rule,
        panel_snapshots=panel_snapshots,
    )
    if not preview.get("ok"):
        report = _error_report(
            preview.get("message") or "Tongue/groove preview failed.",
            errors=list(preview.get("errors") or ["Preview failed."]),
            warnings=list((preview.get("audit") or {}).get("warnings") or []),
            action=CREATE_ACTION,
        )
        return report

    features = preview.get("features") or []
    if not features:
        return _error_report(
            "No hardware features were generated.",
            errors=["Missing feature intents."],
            action=CREATE_ACTION,
        )

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
        "hardwareType": "tongue_groove",
        "relationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "feature": feature,
        "metadata": metadata,
        "preview": preview,
        "cutReady": True,
        "warnings": list((preview.get("audit") or {}).get("warnings") or []),
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
    tongue_feature_name: str = "",
    host_body_modified: bool = True,
    target_body_modified: bool = True,
) -> Dict[str, Any]:
    return {
        "ok": True,
        "action": CREATE_ACTION,
        "hardwareType": "tongue_groove",
        "operationType": OPERATION_TYPE,
        "relationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "hostBodyName": host_body_name,
        "targetBodyName": target_body_name,
        "cutFeatureName": cut_feature_name,
        "tongueFeatureName": tongue_feature_name,
        "metadataWritten": metadata_written,
        "metadata": metadata,
        "hostBodyModified": host_body_modified,
        "targetBodyModified": target_body_modified,
        "warnings": list(warnings or []),
        "errors": [],
        "audit": {
            "operationType": OPERATION_TYPE,
            "relationshipId": relationship_id,
            "hostPanelId": host_panel_id,
            "targetPanelId": target_panel_id,
            "cutFeatureName": cut_feature_name,
            "tongueFeatureName": tongue_feature_name,
            "metadataWritten": metadata_written,
            "hostBodyModified": host_body_modified,
            "targetBodyModified": target_body_modified,
            "metadata": metadata,
            "warnings": list(warnings or []),
            "errors": [],
        },
    }
