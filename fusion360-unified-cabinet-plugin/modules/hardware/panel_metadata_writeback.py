"""M8 — append relationship-based hardware features to body-level panel metadata."""

from __future__ import annotations

import copy
import json
from typing import Any, Dict, List, Optional, Tuple

from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR

OPERATION_TYPE = "SCREW_HOLE_FROM_RELATIONSHIP"
SOURCE_HARDWARE_RELATIONSHIP = "hardware_relationship"


def _ensure_list(parent: Dict[str, Any], key: str) -> List[Any]:
    value = parent.get(key)
    if not isinstance(value, list):
        value = []
        parent[key] = value
    return value


def _feature_identity_key(record: Dict[str, Any]) -> str:
    feature_id = str(record.get("featureId") or "").strip()
    if feature_id:
        return "id:{}".format(feature_id)
    rel_id = str(record.get("sourceRelationshipId") or "").strip()
    op_type = str(record.get("operationType") or record.get("type") or "").strip()
    if rel_id and op_type:
        return "rel:{}::{}".format(rel_id, op_type)
    return ""


def _project_position_to_2d(position: Dict[str, float], contact_axis: str) -> Tuple[float, float]:
    axis = str(contact_axis or "Y").upper()
    x = float(position.get("x") or 0.0)
    y = float(position.get("y") or 0.0)
    z = float(position.get("z") or 0.0)
    if axis == "X":
        return y, z
    if axis == "Z":
        return x, y
    return x, z


def build_panel_feature_record(
    feature_intent: Dict[str, Any],
    *,
    cut_metadata: Dict[str, Any],
    cut_feature_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Convert a hardware feature intent + cut metadata into a body features[] record."""
    geometry = feature_intent.get("geometry") or {}
    contact_axis = str(geometry.get("axis") or "Y")
    diameter_mm = float(geometry.get("diameterMm") or cut_metadata.get("diameterMm") or 0.0)
    depth_mm = float(geometry.get("depthMm") or cut_metadata.get("depthMm") or 0.0)
    positions = geometry.get("positions") or []
    relationship_id = str(
        cut_metadata.get("sourceRelationshipId")
        or feature_intent.get("sourceRelationshipId")
        or ""
    )
    feature_id = str(feature_intent.get("featureId") or "{}::screw_hole".format(relationship_id))

    centers_2d = [_project_position_to_2d(pos, contact_axis) for pos in positions if isinstance(pos, dict)]
    primary_center = centers_2d[0] if centers_2d else None
    radius_mm = round(diameter_mm / 2.0, 4) if diameter_mm > 0 else None

    record: Dict[str, Any] = {
        "featureId": feature_id,
        "kind": "hole",
        "cutType": "FULL" if depth_mm > 0 else "HALF",
        "depthMm": round(depth_mm, 4),
        "isCircle": True,
        "source": SOURCE_HARDWARE_RELATIONSHIP,
        "operationType": str(cut_metadata.get("operationType") or OPERATION_TYPE),
        "sourceRelationshipId": relationship_id,
        "hostPanelId": str(cut_metadata.get("hostPanelId") or feature_intent.get("hostPanelId") or ""),
        "targetPanelId": str(cut_metadata.get("targetPanelId") or feature_intent.get("targetPanelId") or ""),
        "diameterMm": round(diameter_mm, 4),
        "ruleId": str((feature_intent.get("source") or {}).get("ruleId") or cut_metadata.get("ruleId") or ""),
        "positionsLocal": [
            {"x": round(x, 4), "y": round(y, 4)} for x, y in centers_2d
        ],
    }
    if primary_center is not None:
        record["center2d"] = [round(primary_center[0], 4), round(primary_center[1], 4)]
    if radius_mm is not None:
        record["radiusMm"] = radius_mm
    if cut_feature_name:
        record["cutFeatureName"] = cut_feature_name
    if len(centers_2d) > 1:
        record["holeCount"] = len(centers_2d)
    return record


def append_hardware_feature(
    panel_metadata: Dict[str, Any],
    feature_record: Dict[str, Any],
    *,
    allow_duplicate: bool = False,
) -> Tuple[Dict[str, Any], bool, Optional[str]]:
    """Return updated metadata, whether a row was appended, and optional skip reason."""
    metadata = copy.deepcopy(panel_metadata or {})
    features = _ensure_list(metadata, "features")
    identity = _feature_identity_key(feature_record)
    if identity and not allow_duplicate:
        for existing in features:
            if not isinstance(existing, dict):
                continue
            if _feature_identity_key(existing) == identity:
                return metadata, False, "duplicate_feature"
    features.append(feature_record)
    metadata["features"] = features
    return metadata, True, None


def find_hardware_features(
    panel_metadata: Dict[str, Any],
    *,
    source_relationship_id: Optional[str] = None,
    operation_type: Optional[str] = None,
) -> List[Dict[str, Any]]:
    features = panel_metadata.get("features") if isinstance(panel_metadata, dict) else None
    if not isinstance(features, list):
        return []
    matched: List[Dict[str, Any]] = []
    for item in features:
        if not isinstance(item, dict):
            continue
        if source_relationship_id and str(item.get("sourceRelationshipId") or "") != source_relationship_id:
            continue
        if operation_type and str(item.get("operationType") or "") != operation_type:
            continue
        matched.append(item)
    return matched


def read_panel_metadata_from_body(body) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    if not body:
        return None, "Missing body"
    try:
        attrs = body.attributes
        attr = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR) if attrs else None
        if not attr:
            return None, None
        raw = str(attr.value or "").strip()
        if not raw:
            return None, "Empty metadata attribute"
        return json.loads(raw), None
    except json.JSONDecodeError as ex:
        return None, "Invalid metadata JSON: {}".format(ex)
    except Exception as ex:
        return None, str(ex)


def write_panel_metadata_to_body(body, panel_metadata: Dict[str, Any]) -> bool:
    if not body:
        return False
    try:
        payload = json.dumps(panel_metadata, ensure_ascii=False, separators=(",", ":"))
        attrs = body.attributes
        existing = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR) if attrs else None
        if existing:
            existing.value = payload
        else:
            attrs.add(PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR, payload)
        return True
    except Exception:
        return False


def build_tongue_groove_panel_feature_record(
    feature_intent: Dict[str, Any],
    *,
    cut_metadata: Dict[str, Any],
    cut_feature_name: Optional[str] = None,
    role: str = "groove",
) -> Dict[str, Any]:
    """Convert tongue/groove intent + cut metadata into a body features[] record."""
    geometry = feature_intent.get("geometry") or {}
    groove = geometry.get("groove") or {}
    tongue = geometry.get("tongue") or {}
    role_key = "tongue" if str(role or "").lower() == "tongue" else "groove"
    part = tongue if role_key == "tongue" else groove
    sketch = (part.get("sketch") or groove.get("sketch") or {})
    relationship_id = str(
        cut_metadata.get("sourceRelationshipId")
        or feature_intent.get("sourceRelationshipId")
        or ""
    )
    feature_id = str(
        feature_intent.get("featureId") or "{}::tongue_groove".format(relationship_id)
    )
    if role_key == "tongue":
        feature_id = "{}::tongue".format(relationship_id)
    depth_mm = float(
        part.get("depthMm")
        or part.get("protrusionMm")
        or cut_metadata.get("grooveDepthMm" if role_key == "groove" else "tongueProtrusionMm")
        or 0.0
    )
    width_mm = float(part.get("widthMm") or cut_metadata.get("grooveWidthMm") or 0.0)
    length_mm = float(part.get("lengthMm") or cut_metadata.get("grooveLengthMm") or 0.0)
    record: Dict[str, Any] = {
        "featureId": feature_id,
        "kind": role_key,
        "cutType": "POCKET" if role_key == "groove" else "SHOULDER",
        "depthMm": round(depth_mm, 4),
        "widthMm": round(width_mm, 4),
        "lengthMm": round(length_mm, 4),
        "isCircle": False,
        "source": SOURCE_HARDWARE_RELATIONSHIP,
        "operationType": str(cut_metadata.get("operationType") or "TONGUE_GROOVE_FROM_RELATIONSHIP"),
        "sourceRelationshipId": relationship_id,
        "hostPanelId": str(cut_metadata.get("hostPanelId") or feature_intent.get("hostPanelId") or ""),
        "targetPanelId": str(cut_metadata.get("targetPanelId") or feature_intent.get("targetPanelId") or ""),
        "hostRole": "groove",
        "targetRole": "tongue",
        "panelRole": role_key,
        "ruleId": str((feature_intent.get("source") or {}).get("ruleId") or cut_metadata.get("ruleId") or ""),
        "contactAxis": str(geometry.get("contactAxis") or sketch.get("planeAxis") or ""),
        "tongueProtrusionMm": round(float(tongue.get("protrusionMm") or cut_metadata.get("tongueProtrusionMm") or 0.0), 4),
        "tongueCutDeferred": False,
    }
    if cut_feature_name:
        record["cutFeatureName"] = cut_feature_name
    if sketch:
        record["sketch"] = {
            "u0": sketch.get("u0"),
            "u1": sketch.get("u1"),
            "v0": sketch.get("v0"),
            "v1": sketch.get("v1"),
            "planeMm": sketch.get("planeMm"),
            "lengthAxis": sketch.get("lengthAxis"),
            "widthAxis": sketch.get("widthAxis"),
            "shoulderCount": len(sketch.get("shoulders") or []),
        }
    return record


def _writeback_feature_record(
    host_body,
    record: Dict[str, Any],
    *,
    allow_duplicate: bool = False,
) -> Dict[str, Any]:
    existing, read_error = read_panel_metadata_from_body(host_body)
    if read_error and existing is None and read_error not in (None, "Empty metadata attribute"):
        return {
            "ok": False,
            "panelWriteback": False,
            "errors": [read_error],
            "featureRecord": record,
        }

    base_metadata = existing if isinstance(existing, dict) else {"schemaVersion": 1, "features": []}
    updated, appended, skip_reason = append_hardware_feature(
        base_metadata,
        record,
        allow_duplicate=allow_duplicate,
    )
    if not appended:
        return {
            "ok": True,
            "panelWriteback": False,
            "skipped": True,
            "skipReason": skip_reason,
            "featureRecord": record,
            "featureCount": len(updated.get("features") or []),
        }

    written = write_panel_metadata_to_body(host_body, updated)
    return {
        "ok": written,
        "panelWriteback": written,
        "skipped": False,
        "featureRecord": record,
        "featureCount": len(updated.get("features") or []),
        "errors": [] if written else ["Failed to write panel metadata to host body."],
    }


def writeback_screw_hole_feature(
    host_body,
    feature_intent: Dict[str, Any],
    cut_metadata: Dict[str, Any],
    *,
    cut_feature_name: Optional[str] = None,
    allow_duplicate: bool = False,
) -> Dict[str, Any]:
    """After a successful cut, append the hardware feature to host body metadata."""
    record = build_panel_feature_record(
        feature_intent,
        cut_metadata=cut_metadata,
        cut_feature_name=cut_feature_name,
    )
    return _writeback_feature_record(host_body, record, allow_duplicate=allow_duplicate)


def writeback_hinge_hole_feature(
    host_body,
    feature_intent: Dict[str, Any],
    cut_metadata: Dict[str, Any],
    *,
    cut_feature_name: Optional[str] = None,
    allow_duplicate: bool = False,
) -> Dict[str, Any]:
    """After a successful hinge cup cut, append the feature to host body metadata."""
    return writeback_screw_hole_feature(
        host_body,
        feature_intent,
        cut_metadata,
        cut_feature_name=cut_feature_name,
        allow_duplicate=allow_duplicate,
    )


def writeback_drawer_runner_hole_feature(
    host_body,
    feature_intent: Dict[str, Any],
    cut_metadata: Dict[str, Any],
    *,
    cut_feature_name: Optional[str] = None,
    allow_duplicate: bool = False,
) -> Dict[str, Any]:
    """After a successful runner hole cut, append the feature to host body metadata."""
    return writeback_screw_hole_feature(
        host_body,
        feature_intent,
        cut_metadata,
        cut_feature_name=cut_feature_name,
        allow_duplicate=allow_duplicate,
    )


def writeback_lock_cutout_feature(
    host_body,
    feature_intent: Dict[str, Any],
    cut_metadata: Dict[str, Any],
    *,
    cut_feature_name: Optional[str] = None,
    allow_duplicate: bool = False,
) -> Dict[str, Any]:
    """After a successful lock pocket cut, append the feature to host body metadata."""
    return writeback_screw_hole_feature(
        host_body,
        feature_intent,
        cut_metadata,
        cut_feature_name=cut_feature_name,
        allow_duplicate=allow_duplicate,
    )


def writeback_tongue_groove_feature(
    body,
    feature_intent: Dict[str, Any],
    cut_metadata: Dict[str, Any],
    *,
    cut_feature_name: Optional[str] = None,
    allow_duplicate: bool = False,
    role: str = "groove",
) -> Dict[str, Any]:
    """After a successful cut, append groove or tongue feature to the panel body metadata."""
    record = build_tongue_groove_panel_feature_record(
        feature_intent,
        cut_metadata=cut_metadata,
        cut_feature_name=cut_feature_name,
        role=role,
    )
    return _writeback_feature_record(body, record, allow_duplicate=allow_duplicate)
