"""Connect hardware as editable operations (not CAD entities).

An operation is one applied hardware action on a relationship (e.g. screw cut),
stored in host panel metadata.features[] and replayable with new params.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional

# Keep local copies to avoid circular import with panel_metadata_writeback.
SOURCE_HARDWARE_RELATIONSHIP = "hardware_relationship"


def _feature_identity_key(record: Dict[str, Any]) -> str:
    feature_id = str(record.get("featureId") or record.get("operationId") or "").strip()
    if feature_id:
        return "id:{}".format(feature_id)
    rel_id = str(record.get("sourceRelationshipId") or "").strip()
    op_type = str(record.get("operationType") or record.get("type") or "").strip()
    if rel_id and op_type:
        return "rel:{}::{}".format(rel_id, op_type)
    return ""


STATUS_APPLIED = "applied"
STATUS_OUTDATED = "outdated"
STATUS_RETIRED = "retired"
STATUS_FAILED = "failed"

OPERATION_TYPE_TO_HARDWARE = {
    "SCREW_HOLE_FROM_RELATIONSHIP": "screw_hole",
    "HINGE_HOLE_FROM_RELATIONSHIP": "hinge_hole",
    "DRAWER_RUNNER_HOLE_FROM_RELATIONSHIP": "drawer_runner_hole",
    "LOCK_CUTOUT_FROM_RELATIONSHIP": "lock_cutout",
    "TONGUE_GROOVE_FROM_RELATIONSHIP": "tongue_groove",
}


def infer_hardware_type(feature_record: Dict[str, Any]) -> str:
    explicit = str(feature_record.get("hardwareType") or "").strip()
    if explicit:
        return explicit
    op_type = str(feature_record.get("operationType") or "").strip()
    if op_type in OPERATION_TYPE_TO_HARDWARE:
        return OPERATION_TYPE_TO_HARDWARE[op_type]
    kind = str(feature_record.get("kind") or "").strip().lower()
    if kind in ("hole", "circle"):
        return "screw_hole"
    return "screw_hole"


def rule_from_feature_record(feature_record: Dict[str, Any]) -> Dict[str, Any]:
    """Rebuild a Connect rule dict for the hardware form / recreate."""
    stored = feature_record.get("rule")
    if isinstance(stored, dict) and stored.get("type"):
        return dict(stored)
    hw_type = infer_hardware_type(feature_record)
    rule: Dict[str, Any] = {"type": hw_type}
    for key in (
        "diameterMm",
        "depthMm",
        "edgeOffsetMm",
        "minSpacingMm",
        "widthMm",
        "heightMm",
        "grooveDepthMm",
        "grooveWidthMm",
        "tongueProtrusionMm",
        "lengthMm",
    ):
        if feature_record.get(key) is not None:
            rule[key] = float(feature_record.get(key) or 0.0)
    if feature_record.get("holeCount") is not None:
        rule["holeCount"] = int(feature_record.get("holeCount") or 0)
    # Tongue/groove writeback stores dims on the record itself.
    if hw_type == "tongue_groove":
        if rule.get("grooveDepthMm") is None and feature_record.get("depthMm") is not None:
            rule["grooveDepthMm"] = float(feature_record.get("depthMm") or 0.0)
        if rule.get("grooveWidthMm") is None and feature_record.get("widthMm") is not None:
            rule["grooveWidthMm"] = float(feature_record.get("widthMm") or 0.0)
        if rule.get("tongueProtrusionMm") is None and feature_record.get("tongueProtrusionMm") is not None:
            rule["tongueProtrusionMm"] = float(feature_record.get("tongueProtrusionMm") or 0.0)
    return rule


def cut_feature_names_for_update(
    operation: Dict[str, Any],
    payload: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Collect Fusion timeline feature names to delete before replaying an update."""
    payload = payload if isinstance(payload, dict) else {}
    feature_record = operation.get("featureRecord") if isinstance(operation, dict) else None
    if not isinstance(feature_record, dict):
        feature_record = {}
    names: List[str] = []

    def _push(value) -> None:
        text = str(value or "").strip()
        if text and text not in names:
            names.append(text)

    for source in (operation, feature_record, payload):
        if not isinstance(source, dict):
            continue
        _push(source.get("cutFeatureName"))
        _push(source.get("tongueFeatureName"))
        for item in source.get("tongueFeatureNames") or []:
            _push(item)
    return names


def enrich_feature_as_operation(
    feature_record: Dict[str, Any],
    *,
    hardware_type: Optional[str] = None,
    rule: Optional[Dict[str, Any]] = None,
    relationship: Optional[Dict[str, Any]] = None,
    status: str = STATUS_APPLIED,
) -> Dict[str, Any]:
    """Stamp operation fields onto a writeback feature record (same featureId)."""
    record = copy.deepcopy(feature_record or {})
    hw_type = str(hardware_type or infer_hardware_type(record) or "screw_hole").strip()
    record["hardwareType"] = hw_type
    record["status"] = str(status or STATUS_APPLIED)
    if isinstance(rule, dict) and rule:
        record["rule"] = dict(rule)
        record["rule"]["type"] = hw_type
    elif not isinstance(record.get("rule"), dict):
        record["rule"] = rule_from_feature_record(record)
    if isinstance(relationship, dict) and relationship:
        record["relationship"] = relationship
    if not str(record.get("featureId") or "").strip():
        rel_id = str(record.get("sourceRelationshipId") or "unknown").strip()
        record["featureId"] = "{}::{}".format(rel_id, hw_type)
    record["operationId"] = str(record.get("featureId") or "")
    record["source"] = record.get("source") or SOURCE_HARDWARE_RELATIONSHIP
    return record


def ensure_relationship_cut_safe_for_update(relationship: Dict[str, Any]) -> Dict[str, Any]:
    """Replay of an already-applied operation may skip re-verification.

    Fresh inspect often returns bbox_candidate (not cut-safe). Updating an applied
    cut is a parameter replay, not a new joint approval.
    """
    rel = copy.deepcopy(relationship or {})
    verification = rel.get("verification") if isinstance(rel.get("verification"), dict) else {}
    if verification.get("safeForCut"):
        return rel
    level = str(verification.get("level") or "").strip() or "manual_confirmed"
    rel["verification"] = {
        "level": level if level in ("face_verified", "generator_declared", "manual_confirmed") else "manual_confirmed",
        "safeForPreview": True,
        "safeForCut": True,
        "requiresManualConfirmation": False,
        "source": "operation_update_replay",
    }
    return rel


def operation_from_feature_record(feature_record: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not isinstance(feature_record, dict):
        return None
    source = str(feature_record.get("source") or "").strip()
    if source and source != SOURCE_HARDWARE_RELATIONSHIP:
        # Still accept relationship-sourced rows missing source stamp if operationType looks like ours.
        op_type = str(feature_record.get("operationType") or "")
        if "RELATIONSHIP" not in op_type and not feature_record.get("sourceRelationshipId"):
            return None
    operation_id = str(
        feature_record.get("operationId")
        or feature_record.get("featureId")
        or ""
    ).strip()
    if not operation_id:
        return None
    hw_type = infer_hardware_type(feature_record)
    tongue_names = []
    for item in feature_record.get("tongueFeatureNames") or []:
        text = str(item or "").strip()
        if text and text not in tongue_names:
            tongue_names.append(text)
    tongue_name = str(feature_record.get("tongueFeatureName") or "").strip()
    if tongue_name and tongue_name not in tongue_names:
        tongue_names.insert(0, tongue_name)
    return {
        "operationId": operation_id,
        "featureId": operation_id,
        "status": str(feature_record.get("status") or STATUS_APPLIED),
        "hardwareType": hw_type,
        "sourceRelationshipId": str(feature_record.get("sourceRelationshipId") or ""),
        "hostPanelId": str(feature_record.get("hostPanelId") or ""),
        "targetPanelId": str(feature_record.get("targetPanelId") or ""),
        "cutFeatureName": str(feature_record.get("cutFeatureName") or ""),
        "tongueFeatureName": tongue_name or (tongue_names[0] if tongue_names else ""),
        "tongueFeatureNames": tongue_names,
        "rule": rule_from_feature_record(feature_record),
        "relationship": feature_record.get("relationship")
        if isinstance(feature_record.get("relationship"), dict)
        else None,
        "featureRecord": feature_record,
        "label": "{} · {} → {}".format(
            hw_type,
            str(feature_record.get("hostPanelId") or "?"),
            str(feature_record.get("targetPanelId") or "?"),
        ),
    }


def list_operations_from_panel_metadata_map(
    metadata_by_panel_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Collect Connect hardware operations from many panel metadata dicts."""
    operations: List[Dict[str, Any]] = []
    seen = set()
    for panel_id, metadata in (metadata_by_panel_id or {}).items():
        if not isinstance(metadata, dict):
            continue
        features = metadata.get("features")
        if not isinstance(features, list):
            continue
        for item in features:
            op = operation_from_feature_record(item if isinstance(item, dict) else {})
            if not op:
                continue
            if not op.get("hostPanelId"):
                op["hostPanelId"] = str(panel_id or "")
            key = op["operationId"]
            if key in seen:
                continue
            seen.add(key)
            operations.append(op)
    operations.sort(key=lambda row: (row.get("hostPanelId") or "", row.get("operationId") or ""))
    return operations


def upsert_feature_record(
    panel_metadata: Dict[str, Any],
    feature_record: Dict[str, Any],
) -> Dict[str, Any]:
    """Replace existing featureId/operation identity or append."""
    metadata = copy.deepcopy(panel_metadata or {})
    features = metadata.get("features")
    if not isinstance(features, list):
        features = []
    identity = _feature_identity_key(feature_record)
    replaced = False
    if identity:
        for index, existing in enumerate(features):
            if isinstance(existing, dict) and _feature_identity_key(existing) == identity:
                features[index] = copy.deepcopy(feature_record)
                replaced = True
                break
    if not replaced:
        features.append(copy.deepcopy(feature_record))
    metadata["features"] = features
    return metadata


def mark_operation_status(
    panel_metadata: Dict[str, Any],
    operation_id: str,
    status: str,
) -> Dict[str, Any]:
    metadata = copy.deepcopy(panel_metadata or {})
    features = metadata.get("features")
    if not isinstance(features, list):
        return metadata
    oid = str(operation_id or "").strip()
    for item in features:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("operationId") or item.get("featureId") or "").strip()
        if fid == oid:
            item["status"] = status
    metadata["features"] = features
    return metadata
