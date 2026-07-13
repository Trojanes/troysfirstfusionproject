"""Post-M9 hinge / lock / runner intents (all cut-ready)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from screw_hole_from_relationship import (
    UNSUPPORTED_CONTACT_PAIR_MESSAGE,
    _axis_size,
    _bounds_for_axes,
    _build_hole_positions,
    _contact_patch_from_snapshots,
    assert_safe_for_cut,
    assert_safe_for_preview,
    resolve_relationship_verification,
)
from connect_formal_ui import is_hardware_eligible, gap_settings_from_rule

HARDWARE_TYPE_HINGE_HOLE = "hinge_hole"
HARDWARE_TYPE_LOCK_CUTOUT = "lock_cutout"
HARDWARE_TYPE_DRAWER_RUNNER_HOLE = "drawer_runner_hole"

HINGE_RULE_ID = "hinge_hole_from_edge_to_surface_v1"
HINGE_OPERATION_TYPE = "HINGE_HOLE_FROM_RELATIONSHIP"
HINGE_CREATE_ACTION = "hardware.createHingeHolesFromRelationship"
HINGE_PREVIEW_ACTION = "hardware.previewHingeHolesFromRelationship"

LOCK_RULE_ID = "lock_cutout_from_edge_to_surface_v1"
LOCK_OPERATION_TYPE = "LOCK_CUTOUT_FROM_RELATIONSHIP"
LOCK_CREATE_ACTION = "hardware.createLockCutoutFromRelationship"
LOCK_PREVIEW_ACTION = "hardware.previewLockCutoutFromRelationship"

RUNNER_RULE_ID = "drawer_runner_hole_from_edge_to_surface_v1"
RUNNER_OPERATION_TYPE = "DRAWER_RUNNER_HOLE_FROM_RELATIONSHIP"
RUNNER_CREATE_ACTION = "hardware.createDrawerRunnerHolesFromRelationship"
RUNNER_PREVIEW_ACTION = "hardware.previewDrawerRunnerHolesFromRelationship"

DEFAULT_HINGE_DIAMETER_MM = 35.0
DEFAULT_HINGE_DEPTH_MM = 13.0
DEFAULT_HINGE_EDGE_OFFSET_MM = 100.0
DEFAULT_LOCK_WIDTH_MM = 22.0
DEFAULT_LOCK_HEIGHT_MM = 40.0
DEFAULT_LOCK_DEPTH_MM = 12.0
DEFAULT_RUNNER_DIAMETER_MM = 5.0
DEFAULT_RUNNER_DEPTH_MM = 12.0
DEFAULT_RUNNER_EDGE_OFFSET_MM = 37.0


def _error_report(
    hardware_type: str,
    action: str,
    message: str,
    *,
    errors: Optional[List[str]] = None,
) -> Dict[str, Any]:
    errs = list(errors or [message])
    return {
        "ok": False,
        "action": action,
        "hardwareType": hardware_type,
        "message": message,
        "features": [],
        "audit": {"warnings": [], "errors": errs},
        "errors": errs,
        "previewOnly": True,
        "cutReady": False,
    }


def _common_preview_context(
    relationship: Dict[str, Any],
    *,
    hardware_type: str,
    action: str,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]],
    rule: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not isinstance(relationship, dict):
        return _error_report(hardware_type, action, "Relationship payload must be an object.", errors=["Missing relationship object."])

    preview_gate_error = assert_safe_for_preview(relationship)
    if preview_gate_error:
        return _error_report(hardware_type, action, "Relationship is not verified for preview.", errors=[preview_gate_error])

    geometry_type = str(relationship.get("geometryType") or "")
    relationship_type = str(relationship.get("relationshipType") or "")
    if not is_hardware_eligible(relationship, gap_settings_from_rule(rule)):
        return _error_report(
            hardware_type,
            action,
            "Relationship type not supported for {} preview.".format(hardware_type),
            errors=[
                UNSUPPORTED_CONTACT_PAIR_MESSAGE.format(
                    geometry_type, relationship_type
                )
            ],
        )

    roles = relationship.get("roles") or {}
    host_panel_id = str(roles.get("hostPanelId") or "").strip()
    target_panel_id = str(roles.get("targetPanelId") or "").strip()
    if not host_panel_id or not target_panel_id:
        return _error_report(
            hardware_type,
            action,
            "Relationship roles are incomplete.",
            errors=["hostPanelId and targetPanelId are required."],
        )

    contact = relationship.get("contact") or {}
    contact_axis = str(contact.get("axis") or "NONE")
    if contact_axis not in ("X", "Y", "Z"):
        return _error_report(
            hardware_type,
            action,
            "Relationship contact axis is invalid.",
            errors=["contact.axis must be X, Y, or Z."],
        )

    contact_length_mm = float(contact.get("contactLengthMm") or 0.0)
    if contact_length_mm <= 0:
        return _error_report(
            hardware_type,
            action,
            "Relationship contact length is invalid.",
            errors=["contact.contactLengthMm must be greater than zero."],
        )

    panel_snapshots = panel_snapshots or {}
    host_snapshot = panel_snapshots.get(host_panel_id)
    target_snapshot = panel_snapshots.get(target_panel_id)
    if not host_snapshot or not target_snapshot:
        return _error_report(
            hardware_type,
            action,
            "Panel snapshots are required for preview coordinates.",
            errors=["Provide panels[hostPanelId] and panels[targetPanelId] snapshots."],
        )

    try:
        x0, x1, y0, y1, z0, z1, host_face = _contact_patch_from_snapshots(
            host_snapshot, target_snapshot, contact_axis
        )
    except Exception as ex:
        return _error_report(
            hardware_type,
            action,
            "Failed to derive contact patch from panel snapshots.",
            errors=[str(ex)],
        )

    return {
        "ok": True,
        "relationshipId": str(relationship.get("relationshipId") or "unknown"),
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "contactAxis": contact_axis,
        "contactLengthMm": contact_length_mm,
        "hostSnapshot": host_snapshot,
        "hostFace": float(host_face),
        "bounds": _bounds_for_axes(x0, x1, y0, y1, z0, z1),
        "patch": {"x0": x0, "x1": x1, "y0": y0, "y1": y1, "z0": z0, "z1": z1},
        "verification": resolve_relationship_verification(relationship),
        "overlaps": {
            "X": float(contact.get("overlapX") or (x1 - x0)),
            "Y": float(contact.get("overlapY") or (y1 - y0)),
            "Z": float(contact.get("overlapZ") or (z1 - z0)),
        },
    }


def preview_hinge_holes_from_relationship(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Preview hinge cup holes on the host (surface) panel along the contact."""
    action = HINGE_PREVIEW_ACTION
    rule = rule or {}
    ctx = _common_preview_context(
        relationship,
        hardware_type=HARDWARE_TYPE_HINGE_HOLE,
        action=action,
        panel_snapshots=panel_snapshots,
        rule=rule,
    )
    if not ctx.get("ok"):
        return ctx

    diameter_mm = float(rule.get("diameterMm") or DEFAULT_HINGE_DIAMETER_MM)
    depth_mm = float(rule.get("depthMm") or DEFAULT_HINGE_DEPTH_MM)
    edge_offset_mm = float(rule.get("edgeOffsetMm") or DEFAULT_HINGE_EDGE_OFFSET_MM)
    hole_count = int(rule.get("holeCount") or 2)
    hole_count = max(1, min(hole_count, 3))
    host_thickness = _axis_size(ctx["hostSnapshot"], ctx["contactAxis"])
    if depth_mm >= host_thickness:
        return _error_report(
            HARDWARE_TYPE_HINGE_HOLE,
            action,
            "Hinge depth exceeds host thickness.",
            errors=["depthMm ({}) must be less than host thickness ({}).".format(depth_mm, host_thickness)],
        )

    try:
        positions = _build_hole_positions(
            contact_axis=ctx["contactAxis"],
            host_face=ctx["hostFace"],
            bounds=ctx["bounds"],
            overlaps=ctx["overlaps"],
            hole_count=hole_count,
            edge_offset_mm=edge_offset_mm,
        )
    except ValueError as ex:
        return _error_report(HARDWARE_TYPE_HINGE_HOLE, action, "Failed to place hinge cups.", errors=[str(ex)])

    relationship_id = ctx["relationshipId"]
    feature = {
        "schemaVersion": 1,
        "featureId": "{}::hinge_hole".format(relationship_id),
        "type": HARDWARE_TYPE_HINGE_HOLE,
        "sourceRelationshipId": relationship_id,
        "hostPanelId": ctx["hostPanelId"],
        "targetPanelId": ctx["targetPanelId"],
        "hostRole": "hinge_cup",
        "geometry": {
            "axis": ctx["contactAxis"],
            "diameterMm": round(diameter_mm, 4),
            "depthMm": round(depth_mm, 4),
            "positions": positions,
            "contactLengthMm": round(ctx["contactLengthMm"], 4),
        },
        "source": {"method": "relationship_based_rule", "ruleId": HINGE_RULE_ID},
        "validation": {"ok": True, "warnings": [], "errors": []},
    }
    return {
        "ok": True,
        "action": action,
        "hardwareType": HARDWARE_TYPE_HINGE_HOLE,
        "relationshipId": relationship_id,
        "hostPanelId": ctx["hostPanelId"],
        "targetPanelId": ctx["targetPanelId"],
        "verificationLevel": (ctx.get("verification") or {}).get("level"),
        "featureCount": 1,
        "holeCount": len(positions),
        "features": [feature],
        "audit": {
            "diameterMm": diameter_mm,
            "depthMm": depth_mm,
            "edgeOffsetMm": edge_offset_mm,
            "positions": positions,
            "warnings": [],
            "errors": [],
        },
        "errors": [],
        "previewOnly": False,
        "cutReady": True,
        "message": "Hinge hole preview intent ready.",
    }


def build_hinge_cut_feature_metadata(
    feature: Dict[str, Any],
    *,
    relationship_id: str,
    host_panel_id: str,
    target_panel_id: str,
) -> Dict[str, Any]:
    geometry = feature.get("geometry") or {}
    return {
        "operationType": HINGE_OPERATION_TYPE,
        "sourceRelationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "ruleId": HINGE_RULE_ID,
        "holeCount": len(geometry.get("positions") or []),
        "diameterMm": round(float(geometry.get("diameterMm") or 0.0), 4),
        "depthMm": round(float(geometry.get("depthMm") or 0.0), 4),
    }


def plan_hinge_hole_cut_from_relationship(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cut_gate_error = assert_safe_for_cut(relationship)
    if cut_gate_error:
        report = _error_report(
            HARDWARE_TYPE_HINGE_HOLE,
            HINGE_CREATE_ACTION,
            "Relationship is not verified for cut.",
            errors=[cut_gate_error],
        )
        report["previewOnly"] = False
        report["cutReady"] = True
        return report

    preview = preview_hinge_holes_from_relationship(
        relationship,
        rule=rule,
        panel_snapshots=panel_snapshots,
    )
    if not preview.get("ok"):
        report = dict(preview)
        report["action"] = HINGE_CREATE_ACTION
        report["cutReady"] = False
        return report

    features = preview.get("features") or []
    if not features:
        return _error_report(
            HARDWARE_TYPE_HINGE_HOLE,
            HINGE_CREATE_ACTION,
            "No hardware features were generated.",
            errors=["Missing feature intents."],
        )

    feature = features[0]
    relationship_id = str(preview.get("relationshipId") or relationship.get("relationshipId") or "")
    host_panel_id = str(preview.get("hostPanelId") or "")
    target_panel_id = str(preview.get("targetPanelId") or "")
    metadata = build_hinge_cut_feature_metadata(
        feature,
        relationship_id=relationship_id,
        host_panel_id=host_panel_id,
        target_panel_id=target_panel_id,
    )
    return {
        "ok": True,
        "action": HINGE_CREATE_ACTION,
        "hardwareType": HARDWARE_TYPE_HINGE_HOLE,
        "relationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "holeCount": preview.get("holeCount"),
        "feature": feature,
        "metadata": metadata,
        "preview": preview,
        "previewOnly": False,
        "cutReady": True,
    }


def build_hinge_cut_success_report(
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
        "action": HINGE_CREATE_ACTION,
        "operationType": HINGE_OPERATION_TYPE,
        "hardwareType": HARDWARE_TYPE_HINGE_HOLE,
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
            "operationType": HINGE_OPERATION_TYPE,
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


def preview_lock_cutout_from_relationship(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Preview a lock pocket centered on the host contact patch."""
    action = "hardware.previewLockCutoutFromRelationship"
    rule = rule or {}
    ctx = _common_preview_context(
        relationship,
        hardware_type=HARDWARE_TYPE_LOCK_CUTOUT,
        action=action,
        panel_snapshots=panel_snapshots,
        rule=rule,
    )
    if not ctx.get("ok"):
        return ctx

    width_mm = float(rule.get("widthMm") or DEFAULT_LOCK_WIDTH_MM)
    height_mm = float(rule.get("heightMm") or DEFAULT_LOCK_HEIGHT_MM)
    depth_mm = float(rule.get("depthMm") or DEFAULT_LOCK_DEPTH_MM)
    host_thickness = _axis_size(ctx["hostSnapshot"], ctx["contactAxis"])
    if depth_mm >= host_thickness:
        return _error_report(
            HARDWARE_TYPE_LOCK_CUTOUT,
            action,
            "Lock depth exceeds host thickness.",
            errors=["depthMm ({}) must be less than host thickness ({}).".format(depth_mm, host_thickness)],
        )

    # Center pocket on contact patch using the two non-contact axes.
    contact_axis = ctx["contactAxis"]
    non_contact = [axis for axis in ("X", "Y", "Z") if axis != contact_axis]
    length_axis, width_axis = non_contact[0], non_contact[1]
    if abs(ctx["overlaps"][non_contact[1]]) > abs(ctx["overlaps"][non_contact[0]]):
        length_axis, width_axis = non_contact[1], non_contact[0]
    lc = (ctx["bounds"][length_axis][0] + ctx["bounds"][length_axis][1]) / 2.0
    wc = (ctx["bounds"][width_axis][0] + ctx["bounds"][width_axis][1]) / 2.0
    half_l = width_mm / 2.0
    half_w = height_mm / 2.0
    pocket = {
        "planeAxis": contact_axis,
        "planeMm": round(ctx["hostFace"], 4),
        "lengthAxis": length_axis,
        "widthAxis": width_axis,
        "u0": round(lc - half_l, 4),
        "u1": round(lc + half_l, 4),
        "v0": round(wc - half_w, 4),
        "v1": round(wc + half_w, 4),
        "depthMm": round(depth_mm, 4),
    }

    relationship_id = ctx["relationshipId"]
    feature = {
        "schemaVersion": 1,
        "featureId": "{}::lock_cutout".format(relationship_id),
        "type": HARDWARE_TYPE_LOCK_CUTOUT,
        "sourceRelationshipId": relationship_id,
        "hostPanelId": ctx["hostPanelId"],
        "targetPanelId": ctx["targetPanelId"],
        "hostRole": "lock_pocket",
        "geometry": {
            "contactAxis": contact_axis,
            "widthMm": round(width_mm, 4),
            "heightMm": round(height_mm, 4),
            "depthMm": round(depth_mm, 4),
            "pocket": pocket,
        },
        "source": {"method": "relationship_based_rule", "ruleId": LOCK_RULE_ID},
        "validation": {"ok": True, "warnings": [], "errors": []},
    }
    return {
        "ok": True,
        "action": action,
        "hardwareType": HARDWARE_TYPE_LOCK_CUTOUT,
        "relationshipId": relationship_id,
        "hostPanelId": ctx["hostPanelId"],
        "targetPanelId": ctx["targetPanelId"],
        "verificationLevel": (ctx.get("verification") or {}).get("level"),
        "featureCount": 1,
        "features": [feature],
        "audit": {
            "widthMm": width_mm,
            "heightMm": height_mm,
            "depthMm": depth_mm,
            "pocket": pocket,
            "warnings": [],
            "errors": [],
        },
        "errors": [],
        "previewOnly": False,
        "cutReady": True,
        "message": "Lock cutout preview intent ready.",
    }


def build_lock_cut_feature_metadata(
    feature: Dict[str, Any],
    *,
    relationship_id: str,
    host_panel_id: str,
    target_panel_id: str,
) -> Dict[str, Any]:
    geometry = feature.get("geometry") or {}
    pocket = geometry.get("pocket") or {}
    return {
        "operationType": LOCK_OPERATION_TYPE,
        "sourceRelationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "ruleId": LOCK_RULE_ID,
        "widthMm": round(float(geometry.get("widthMm") or 0.0), 4),
        "heightMm": round(float(geometry.get("heightMm") or 0.0), 4),
        "depthMm": round(float(geometry.get("depthMm") or pocket.get("depthMm") or 0.0), 4),
    }


def plan_lock_cutout_from_relationship(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cut_gate_error = assert_safe_for_cut(relationship)
    if cut_gate_error:
        report = _error_report(
            HARDWARE_TYPE_LOCK_CUTOUT,
            LOCK_CREATE_ACTION,
            "Relationship is not verified for cut.",
            errors=[cut_gate_error],
        )
        report["previewOnly"] = False
        report["cutReady"] = True
        return report

    preview = preview_lock_cutout_from_relationship(
        relationship,
        rule=rule,
        panel_snapshots=panel_snapshots,
    )
    if not preview.get("ok"):
        report = dict(preview)
        report["action"] = LOCK_CREATE_ACTION
        report["cutReady"] = False
        return report

    features = preview.get("features") or []
    if not features:
        return _error_report(
            HARDWARE_TYPE_LOCK_CUTOUT,
            LOCK_CREATE_ACTION,
            "No hardware features were generated.",
            errors=["Missing feature intents."],
        )

    feature = features[0]
    relationship_id = str(preview.get("relationshipId") or relationship.get("relationshipId") or "")
    host_panel_id = str(preview.get("hostPanelId") or "")
    target_panel_id = str(preview.get("targetPanelId") or "")
    metadata = build_lock_cut_feature_metadata(
        feature,
        relationship_id=relationship_id,
        host_panel_id=host_panel_id,
        target_panel_id=target_panel_id,
    )
    return {
        "ok": True,
        "action": LOCK_CREATE_ACTION,
        "hardwareType": HARDWARE_TYPE_LOCK_CUTOUT,
        "relationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "feature": feature,
        "metadata": metadata,
        "preview": preview,
        "previewOnly": False,
        "cutReady": True,
    }


def build_lock_cut_success_report(
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
        "action": LOCK_CREATE_ACTION,
        "operationType": LOCK_OPERATION_TYPE,
        "hardwareType": HARDWARE_TYPE_LOCK_CUTOUT,
        "relationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "hostBodyName": host_body_name,
        "targetBodyName": target_body_name,
        "cutFeatureName": cut_feature_name,
        "metadataWritten": metadata_written,
        "metadata": metadata,
        "targetBodyModified": False,
        "warnings": list(warnings or []),
        "errors": [],
        "audit": {
            "operationType": LOCK_OPERATION_TYPE,
            "relationshipId": relationship_id,
            "hostPanelId": host_panel_id,
            "targetPanelId": target_panel_id,
            "cutFeatureName": cut_feature_name,
            "metadataWritten": metadata_written,
            "targetBodyModified": False,
            "metadata": metadata,
            "warnings": list(warnings or []),
            "errors": [],
        },
    }


def preview_drawer_runner_holes_from_relationship(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Preview drawer-runner mounting holes on the host panel along the contact."""
    action = RUNNER_PREVIEW_ACTION
    rule = rule or {}
    ctx = _common_preview_context(
        relationship,
        hardware_type=HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
        action=action,
        panel_snapshots=panel_snapshots,
        rule=rule,
    )
    if not ctx.get("ok"):
        return ctx

    diameter_mm = float(rule.get("diameterMm") or DEFAULT_RUNNER_DIAMETER_MM)
    depth_mm = float(rule.get("depthMm") or DEFAULT_RUNNER_DEPTH_MM)
    edge_offset_mm = float(rule.get("edgeOffsetMm") or DEFAULT_RUNNER_EDGE_OFFSET_MM)
    hole_count = int(rule.get("holeCount") or 3)
    hole_count = max(2, min(hole_count, 5))
    host_thickness = _axis_size(ctx["hostSnapshot"], ctx["contactAxis"])
    if depth_mm >= host_thickness:
        return _error_report(
            HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
            action,
            "Runner hole depth exceeds host thickness.",
            errors=["depthMm ({}) must be less than host thickness ({}).".format(depth_mm, host_thickness)],
        )

    try:
        positions = _build_hole_positions(
            contact_axis=ctx["contactAxis"],
            host_face=ctx["hostFace"],
            bounds=ctx["bounds"],
            overlaps=ctx["overlaps"],
            hole_count=hole_count,
            edge_offset_mm=edge_offset_mm,
        )
    except ValueError as ex:
        return _error_report(
            HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
            action,
            "Failed to place runner holes.",
            errors=[str(ex)],
        )

    relationship_id = ctx["relationshipId"]
    feature = {
        "schemaVersion": 1,
        "featureId": "{}::drawer_runner_hole".format(relationship_id),
        "type": HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
        "sourceRelationshipId": relationship_id,
        "hostPanelId": ctx["hostPanelId"],
        "targetPanelId": ctx["targetPanelId"],
        "hostRole": "runner_mount",
        "geometry": {
            "axis": ctx["contactAxis"],
            "diameterMm": round(diameter_mm, 4),
            "depthMm": round(depth_mm, 4),
            "positions": positions,
            "contactLengthMm": round(ctx["contactLengthMm"], 4),
        },
        "source": {"method": "relationship_based_rule", "ruleId": RUNNER_RULE_ID},
        "validation": {"ok": True, "warnings": [], "errors": []},
    }
    return {
        "ok": True,
        "action": action,
        "hardwareType": HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
        "relationshipId": relationship_id,
        "hostPanelId": ctx["hostPanelId"],
        "targetPanelId": ctx["targetPanelId"],
        "verificationLevel": (ctx.get("verification") or {}).get("level"),
        "featureCount": 1,
        "holeCount": len(positions),
        "features": [feature],
        "audit": {
            "diameterMm": diameter_mm,
            "depthMm": depth_mm,
            "edgeOffsetMm": edge_offset_mm,
            "positions": positions,
            "warnings": [],
            "errors": [],
        },
        "errors": [],
        "previewOnly": False,
        "cutReady": True,
        "message": "Drawer runner hole preview intent ready.",
    }


def build_runner_cut_feature_metadata(
    feature: Dict[str, Any],
    *,
    relationship_id: str,
    host_panel_id: str,
    target_panel_id: str,
) -> Dict[str, Any]:
    geometry = feature.get("geometry") or {}
    return {
        "operationType": RUNNER_OPERATION_TYPE,
        "sourceRelationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "ruleId": RUNNER_RULE_ID,
        "holeCount": len(geometry.get("positions") or []),
        "diameterMm": round(float(geometry.get("diameterMm") or 0.0), 4),
        "depthMm": round(float(geometry.get("depthMm") or 0.0), 4),
    }


def plan_drawer_runner_hole_cut_from_relationship(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cut_gate_error = assert_safe_for_cut(relationship)
    if cut_gate_error:
        report = _error_report(
            HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
            RUNNER_CREATE_ACTION,
            "Relationship is not verified for cut.",
            errors=[cut_gate_error],
        )
        report["previewOnly"] = False
        report["cutReady"] = True
        return report

    preview = preview_drawer_runner_holes_from_relationship(
        relationship,
        rule=rule,
        panel_snapshots=panel_snapshots,
    )
    if not preview.get("ok"):
        report = dict(preview)
        report["action"] = RUNNER_CREATE_ACTION
        report["cutReady"] = False
        return report

    features = preview.get("features") or []
    if not features:
        return _error_report(
            HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
            RUNNER_CREATE_ACTION,
            "No hardware features were generated.",
            errors=["Missing feature intents."],
        )

    feature = features[0]
    relationship_id = str(preview.get("relationshipId") or relationship.get("relationshipId") or "")
    host_panel_id = str(preview.get("hostPanelId") or "")
    target_panel_id = str(preview.get("targetPanelId") or "")
    metadata = build_runner_cut_feature_metadata(
        feature,
        relationship_id=relationship_id,
        host_panel_id=host_panel_id,
        target_panel_id=target_panel_id,
    )
    return {
        "ok": True,
        "action": RUNNER_CREATE_ACTION,
        "hardwareType": HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
        "relationshipId": relationship_id,
        "hostPanelId": host_panel_id,
        "targetPanelId": target_panel_id,
        "holeCount": preview.get("holeCount"),
        "feature": feature,
        "metadata": metadata,
        "preview": preview,
        "previewOnly": False,
        "cutReady": True,
    }


def build_runner_cut_success_report(
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
        "action": RUNNER_CREATE_ACTION,
        "operationType": RUNNER_OPERATION_TYPE,
        "hardwareType": HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
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
            "operationType": RUNNER_OPERATION_TYPE,
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
