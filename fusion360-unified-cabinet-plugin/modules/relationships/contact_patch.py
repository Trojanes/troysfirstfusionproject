"""ContactPatch — bbox axis-aligned contact region derived from relationship + panel snapshots."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = 1
SUPPORTED_GEOMETRY_TYPES = frozenset({"edge_to_surface", "surface_to_surface"})

DEFAULT_PATCH_VERIFICATION: Dict[str, Any] = {
    "level": "bbox_contact_patch",
    "safeForPreview": True,
    "safeForCut": False,
}


def _panel_dict(panel: Any) -> Dict[str, Any]:
    if panel is None:
        return {}
    if hasattr(panel, "to_dict"):
        return panel.to_dict()
    return dict(panel) if isinstance(panel, dict) else {}


def _axis_value(snapshot: Dict[str, Any], axis: str, bound: str) -> float:
    bbox = snapshot.get("bbox") or {}
    key = "{}{}".format(axis.lower(), "0" if bound == "min" else "1")
    return float(bbox.get(key, 0.0))


def _overlap_bounds(panel_a: Dict[str, Any], panel_b: Dict[str, Any]) -> Dict[str, Tuple[float, float]]:
    bounds: Dict[str, Tuple[float, float]] = {}
    for axis in ("X", "Y", "Z"):
        a0 = _axis_value(panel_a, axis, "min")
        a1 = _axis_value(panel_a, axis, "max")
        b0 = _axis_value(panel_b, axis, "min")
        b1 = _axis_value(panel_b, axis, "max")
        low = max(a0, b0)
        high = min(a1, b1)
        bounds[axis] = (low, high)
    return bounds


def _contact_plane_coordinate(
    host_snapshot: Dict[str, Any],
    target_snapshot: Dict[str, Any],
    contact_axis: str,
) -> Tuple[float, float]:
    host_min = _axis_value(host_snapshot, contact_axis, "min")
    host_max = _axis_value(host_snapshot, contact_axis, "max")
    target_min = _axis_value(target_snapshot, contact_axis, "min")
    target_max = _axis_value(target_snapshot, contact_axis, "max")
    candidates = [
        (abs(target_min - host_max), host_max),
        (abs(target_max - host_min), host_min),
    ]
    plane_coord = min(candidates, key=lambda item: item[0])[1]
    plane_distance = min(item[0] for item in candidates)
    return plane_coord, plane_distance


def _patch_verification(relationship: Dict[str, Any], source: str) -> Dict[str, Any]:
    rel_verification = relationship.get("verification") or {}
    level = str(rel_verification.get("level") or "bbox_candidate")
    if source == "bbox_axis_aligned":
        return dict(DEFAULT_PATCH_VERIFICATION)
    if source == "face_verified":
        return {
            "level": "face_verified",
            "safeForPreview": bool(rel_verification.get("safeForPreview", True)),
            "safeForCut": bool(rel_verification.get("safeForCut", False)),
        }
    if source == "generator_declared":
        return {
            "level": "generator_declared",
            "safeForPreview": bool(rel_verification.get("safeForPreview", True)),
            "safeForCut": bool(rel_verification.get("safeForCut", False)),
        }
    if level == "manual_confirmed":
        return {
            "level": "manual_confirmed",
            "safeForPreview": bool(rel_verification.get("safeForPreview", True)),
            "safeForCut": bool(rel_verification.get("safeForCut", False)),
        }
    return dict(DEFAULT_PATCH_VERIFICATION)


def _resolve_patch_source(relationship: Dict[str, Any]) -> str:
    level = str((relationship.get("verification") or {}).get("level") or "bbox_candidate")
    if level == "face_verified":
        return "face_verified"
    if level == "generator_declared":
        return "generator_declared"
    return "bbox_axis_aligned"


def _resolve_host_target_ids(relationship: Dict[str, Any], panel_a: Dict[str, Any], panel_b: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], List[str]]:
    errors: List[str] = []
    roles = relationship.get("roles") or {}
    geometry_type = str(relationship.get("geometryType") or "")
    host_id = roles.get("hostPanelId")
    target_id = roles.get("targetPanelId")

    if geometry_type == "edge_to_surface":
        if not host_id or not target_id:
            errors.append("Missing hostPanelId or targetPanelId for edge_to_surface contact patch.")
            return None, None, errors
        return str(host_id), str(target_id), errors

    host_id = host_id or (relationship.get("panelA") or {}).get("panelId") or panel_a.get("panelId")
    target_id = target_id or (relationship.get("panelB") or {}).get("panelId") or panel_b.get("panelId")
    if not host_id or not target_id:
        errors.append("Missing panel identifiers for contact patch.")
        return None, None, errors
    return str(host_id), str(target_id), errors


def _snapshot_for_panel_id(panel_a: Dict[str, Any], panel_b: Dict[str, Any], panel_id: str) -> Optional[Dict[str, Any]]:
    if panel_a.get("panelId") == panel_id:
        return panel_a
    if panel_b.get("panelId") == panel_id:
        return panel_b
    return None


def build_contact_patch_from_relationship(
    relationship: Dict[str, Any],
    panel_a: Any,
    panel_b: Any,
) -> Dict[str, Any]:
    """Build a ContactPatch dict from relationship + two panel snapshots."""
    errors: List[str] = []
    warnings: List[str] = []

    if not isinstance(relationship, dict):
        return {"ok": False, "errors": ["Missing relationship object."]}

    geometry_type = str(relationship.get("geometryType") or "")
    if geometry_type not in SUPPORTED_GEOMETRY_TYPES:
        return {
            "ok": False,
            "errors": ["Unsupported geometryType for ContactPatch: {}.".format(geometry_type or "unknown")],
        }

    pa = _panel_dict(panel_a)
    pb = _panel_dict(panel_b)
    host_id, target_id, id_errors = _resolve_host_target_ids(relationship, pa, pb)
    if id_errors:
        return {"ok": False, "errors": id_errors}

    host_snapshot = _snapshot_for_panel_id(pa, pb, host_id or "")
    target_snapshot = _snapshot_for_panel_id(pa, pb, target_id or "")
    if not host_snapshot or not target_snapshot:
        return {"ok": False, "errors": ["Panel snapshots do not match relationship host/target IDs."]}

    contact = relationship.get("contact") or {}
    contact_axis = str(contact.get("axis") or "NONE").upper()
    if contact_axis not in ("X", "Y", "Z"):
        return {"ok": False, "errors": ["Invalid or missing contact.axis."]}

    overlaps = _overlap_bounds(pa, pb)
    for axis in ("X", "Y", "Z"):
        if axis == contact_axis:
            continue
        low, high = overlaps[axis]
        if high <= low:
            return {"ok": False, "errors": ["Contact patch overlap is empty on {} axis.".format(axis)]}

    x0, x1 = overlaps["X"]
    y0, y1 = overlaps["Y"]
    z0, z1 = overlaps["Z"]
    plane_coord, plane_distance = _contact_plane_coordinate(host_snapshot, target_snapshot, contact_axis)

    bounds_world = {
        "x0": round(x0, 4),
        "x1": round(x1, 4),
        "y0": round(y0, 4),
        "y1": round(y1, 4),
        "z0": round(z0, 4),
        "z1": round(z1, 4),
    }

    non_contact = [axis for axis in ("X", "Y", "Z") if axis != contact_axis]
    contact_length = max(overlaps[non_contact[0]][1] - overlaps[non_contact[0]][0], overlaps[non_contact[1]][1] - overlaps[non_contact[1]][0])
    contact_area = (overlaps[non_contact[0]][1] - overlaps[non_contact[0]][0]) * (overlaps[non_contact[1]][1] - overlaps[non_contact[1]][0])

    center = {
        "X": (x0 + x1) / 2.0,
        "Y": (y0 + y1) / 2.0,
        "Z": (z0 + z1) / 2.0,
    }
    center[contact_axis] = plane_coord
    center_world = [round(center["X"], 4), round(center["Y"], 4), round(center["Z"], 4)]

    rel_id = str(relationship.get("relationshipId") or "unknown")
    source = _resolve_patch_source(relationship)
    verification = _patch_verification(relationship, source)
    if source == "bbox_axis_aligned":
        warnings.append("BBox axis-aligned contact patch is not production-grade face contact.")

    contact_type = geometry_type
    patch = {
        "schemaVersion": SCHEMA_VERSION,
        "contactPatchId": "cp.{}".format(rel_id),
        "sourceRelationshipId": rel_id,
        "hostPanelId": host_id,
        "targetPanelId": target_id,
        "contactType": contact_type,
        "source": source,
        "contactAxis": contact_axis,
        "planeDistanceMm": round(plane_distance, 4),
        "contactAreaMm2": round(contact_area, 4),
        "contactLengthMm": round(contact_length, 4),
        "centerWorldMm": center_world,
        "boundsWorldMm": bounds_world,
        "verification": verification,
        "warnings": warnings,
        "errors": errors,
    }
    return {"ok": True, "contactPatch": patch, "warnings": warnings, "errors": errors}


def build_contact_patch_label_text(contact_patch: Dict[str, Any], relationship: Optional[Dict[str, Any]] = None) -> str:
    relationship = relationship or {}
    verification = contact_patch.get("verification") or {}
    lines = [
        str(relationship.get("relationshipType") or "unknown"),
        str(relationship.get("geometryType") or contact_patch.get("contactType") or "unknown"),
        "contactArea = {} mm²".format(contact_patch.get("contactAreaMm2", "-")),
        str(verification.get("level") or "bbox_contact_patch"),
        "safeForCut = {}".format(str(bool(verification.get("safeForCut"))).lower()),
    ]
    return "\n".join(lines)
