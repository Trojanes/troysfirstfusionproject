"""Tag scan + Export Ready troubleshoot for Lay Flat bodies.

The Attributes-page Tag Scan skips nested/Lay Flat copies. This module scans
LAY_FLAT workpieces for classification tags and, at the same time, runs the
Export Ready checks so tag gaps and machining blockers show up together.
"""

from __future__ import annotations

import json

try:
    from nesting.outline_cache import attribute_entities
except Exception:
    try:
        from outline_cache import attribute_entities  # type: ignore
    except Exception:

        def attribute_entities(entity):
            if entity is not None:
                yield entity

try:
    from nesting.lay_flat_export_ready import evaluate_body as evaluate_export_ready_body
except Exception:
    try:
        from lay_flat_export_ready import (  # type: ignore
            evaluate_body as evaluate_export_ready_body,
        )
    except Exception:
        evaluate_export_ready_body = None


PANEL_GROUP = "UnifiedCabinet.Panel"

# Tag-scan codes that Export Ready also emits under the same (or aliased) name.
_TAG_EXPORT_ALIASES = {
    "board_type": ("board_type",),
    "color": ("color",),
    "cutting_face": ("cutting_face",),
    "thickness": ("thickness",),
}


def _undefined(value):
    text = str(value or "").strip().lower()
    return (
        not text
        or "unknown" in text
        or text in ("undefined", "unassigned", "none", "n/a", "missing")
    )


def _canonical(metadata, field):
    classification = (
        metadata.get("classification") if isinstance(metadata, dict) else {}
    )
    state = classification.get(field) if isinstance(classification, dict) else {}
    if isinstance(state, dict):
        return str(state.get("value") or "").strip()
    return str(state or "").strip()


def _derived(metadata, key):
    derived = metadata.get("derivedTags") if isinstance(metadata, dict) else {}
    typed = metadata.get("typedTags") if isinstance(metadata, dict) else {}
    if isinstance(derived, dict) and derived.get(key):
        return str(derived.get(key) or "").strip()
    if isinstance(typed, dict) and typed.get(key):
        return str(typed.get(key) or "").strip()
    return ""


def read_body_metadata(body):
    for entity in attribute_entities(body):
        try:
            attr = entity.attributes.itemByName(PANEL_GROUP, "metadata")
            raw = str(attr.value or "") if attr else ""
        except Exception:
            continue
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if isinstance(data, dict):
            return data
    return {}


def evaluate_metadata_tags(metadata, body_name="", panel_id=""):
    """Pure tag readiness check from stored Lay Flat metadata."""
    meta = metadata if isinstance(metadata, dict) else {}
    identity = meta.get("identity") if isinstance(meta.get("identity"), dict) else {}
    dimensions = (
        meta.get("dimensions") if isinstance(meta.get("dimensions"), dict) else {}
    )
    lifecycle = meta.get("lifecycle") if isinstance(meta.get("lifecycle"), dict) else {}

    board = _canonical(meta, "boardType") or _derived(meta, "boardTypeTag")
    color = _canonical(meta, "color") or _derived(meta, "colorTag")
    cutting = _canonical(meta, "cuttingFace") or _derived(meta, "requiredFaceUp")
    cutting = str(cutting or "").strip().upper()

    thickness = 0.0
    for key in ("thicknessMm", "materialThickness", "heightMm"):
        try:
            thickness = float(dimensions.get(key) or 0.0)
        except Exception:
            thickness = 0.0
        if thickness > 0:
            break

    resolved_panel = (
        panel_id
        or str(identity.get("panelId") or "").strip()
        or body_name
        or ""
    )
    missing = []
    if _undefined(board):
        missing.append("board_type")
    if _undefined(color):
        missing.append("color")
    if cutting not in ("MILLING", "NON_MILLING", "EITHER", "COLOUR", "COLOR"):
        missing.append("cutting_face")
    if thickness <= 0:
        missing.append("thickness")
    if not str(resolved_panel or "").strip():
        missing.append("panel_id")

    return {
        "ok": not missing,
        "bodyName": body_name or "",
        "panelId": resolved_panel,
        "boardTypeTag": board,
        "colorTag": color,
        "cuttingFace": cutting,
        "thicknessMm": thickness if thickness > 0 else None,
        "lifecycleState": str(lifecycle.get("state") or ""),
        "missing": missing,
        "missingCount": len(missing),
    }


def _export_only_reasons(tag_missing, export_reasons):
    """Drop Export Ready reasons already covered by tag missing list."""
    covered = set()
    for tag in tag_missing or []:
        for alias in _TAG_EXPORT_ALIASES.get(tag, (tag,)):
            covered.add(alias)
    ordered = []
    seen = set()
    for reason in export_reasons or []:
        code = str(reason or "").split(":", 1)[0]
        if code in covered or reason in seen:
            continue
        seen.add(reason)
        ordered.append(reason)
    return ordered


def _classification_state(meta, field):
    classification = meta.get("classification") if isinstance(meta, dict) else {}
    state = classification.get(field) if isinstance(classification, dict) else {}
    if not isinstance(state, dict):
        value = str(state or "").strip()
        return {
            "value": value,
            "source": "legacy" if value else "missing",
            "locked": False,
        }
    return {
        "value": str(state.get("value") or "").strip(),
        "source": str(state.get("source") or "legacy").strip() or "legacy",
        "locked": bool(state.get("locked")),
    }


def _feature_summary(features):
    summary = {"total": 0, "half": 0, "full": 0, "byKind": {}}
    if not isinstance(features, list):
        return summary
    summary["total"] = len(features)
    for feature in features:
        if not isinstance(feature, dict):
            continue
        cut = str(feature.get("cutType") or "").upper()
        if cut == "FULL" or bool(feature.get("through")):
            summary["full"] += 1
        else:
            summary["half"] += 1
        kind = str(feature.get("kind") or "unknown")
        summary["byKind"][kind] = int(summary["byKind"].get(kind) or 0) + 1
    return summary


def _public_features(features, limit=40):
    output = []
    for feature in features or []:
        if not isinstance(feature, dict):
            continue
        output.append(
            {
                "featureId": str(feature.get("featureId") or ""),
                "kind": str(feature.get("kind") or ""),
                "cutType": str(feature.get("cutType") or ""),
                "depthMm": feature.get("depthMm"),
                "openSurfaceIs": str(feature.get("openSurfaceIs") or ""),
                "diameterMm": feature.get("diameterMm"),
                "radiusMm": feature.get("radiusMm"),
                "widthMm": feature.get("widthMm"),
                "pointCount": len(
                    feature.get("pointsLocal")
                    or feature.get("points")
                    or feature.get("path")
                    or []
                ),
            }
        )
        if len(output) >= limit:
            break
    return output


def _detail_from_metadata(meta, body=None):
    meta = meta if isinstance(meta, dict) else {}
    identity = meta.get("identity") if isinstance(meta.get("identity"), dict) else {}
    defaults = (
        meta.get("defaultAttributes")
        if isinstance(meta.get("defaultAttributes"), dict)
        else {}
    )
    derived = meta.get("derivedTags") if isinstance(meta.get("derivedTags"), dict) else {}
    typed = meta.get("typedTags") if isinstance(meta.get("typedTags"), dict) else {}
    dimensions = meta.get("dimensions") if isinstance(meta.get("dimensions"), dict) else {}
    features = meta.get("features") if isinstance(meta.get("features"), list) else []
    cached = (
        meta.get("nestingFlatOutline")
        if isinstance(meta.get("nestingFlatOutline"), dict)
        else {}
    )
    outline = cached.get("outline") if isinstance(cached.get("outline"), dict) else {}
    component_name = ""
    try:
        parent = getattr(body, "parentComponent", None)
        component_name = str(getattr(parent, "name", "") or "")
    except Exception:
        component_name = ""
    return {
        "componentName": component_name,
        "identity": {
            "panelId": str(identity.get("panelId") or ""),
            "sourcePanelId": str(identity.get("sourcePanelId") or ""),
            "sourceBoardId": str(identity.get("sourceBoardId") or ""),
            "boardType": str(identity.get("boardType") or ""),
            "module": str(identity.get("module") or ""),
            "runId": str(identity.get("runId") or ""),
        },
        "defaultAttributes": {
            "role": str(defaults.get("role") or ""),
            "materialClass": str(defaults.get("materialClass") or ""),
        },
        "derivedTags": {
            "boardTypeTag": str(derived.get("boardTypeTag") or typed.get("boardTypeTag") or ""),
            "colorTag": str(derived.get("colorTag") or typed.get("colorTag") or ""),
            "requiredFaceUp": str(
                derived.get("requiredFaceUp") or typed.get("requiredFaceUp") or ""
            ),
        },
        "classification": {
            "boardType": _classification_state(meta, "boardType"),
            "color": _classification_state(meta, "color"),
            "cuttingFace": _classification_state(meta, "cuttingFace"),
        },
        "dimensions": {
            "widthMm": dimensions.get("widthMm"),
            "depthMm": dimensions.get("depthMm"),
            "lengthMm": dimensions.get("lengthMm"),
            "thicknessMm": dimensions.get("thicknessMm")
            or dimensions.get("materialThickness")
            or dimensions.get("heightMm"),
        },
        "outline": {
            "source": str(outline.get("source") or cached.get("source") or ""),
            "pointCount": int(
                outline.get("pointCount")
                or cached.get("pointCount")
                or len(outline.get("points") or [])
                or 0
            ),
            "widthMm": outline.get("widthMm") or cached.get("widthMm"),
            "depthMm": outline.get("depthMm") or cached.get("depthMm"),
            "featureCount": cached.get("featureCount"),
            "analyzedAtMs": cached.get("analyzedAtMs"),
            "schemaVersion": cached.get("schemaVersion"),
        },
        "features": _public_features(features),
        "featureSummary": _feature_summary(features),
    }


def evaluate_body(body, min_dot=None):
    """Tag scan + Export Ready troubleshoot for one Lay Flat body."""
    body_name = ""
    try:
        body_name = str(getattr(body, "name", "") or "")
    except Exception:
        body_name = ""
    if body is None:
        return {
            "ok": False,
            "exportReady": False,
            "problem": True,
            "bodyName": body_name,
            "panelId": "",
            "boardTypeTag": "",
            "colorTag": "",
            "cuttingFace": "",
            "thicknessMm": None,
            "lifecycleState": "",
            "missing": ["missing_body"],
            "missingCount": 1,
            "troubleshoot": ["missing_body"],
            "troubleshootCount": 1,
            "featureCount": 0,
            "pointCount": 0,
            "outlineSource": "",
            "analyzed": False,
            "faceUp": None,
            "detail": _detail_from_metadata({}),
            "_body": None,
        }

    meta = read_body_metadata(body)
    item = evaluate_metadata_tags(meta, body_name=body_name)
    item["_body"] = body
    detail = _detail_from_metadata(meta, body=body)

    export_reasons = []
    export_ready = None
    face_up = None
    feature_count = int((detail.get("featureSummary") or {}).get("total") or 0)
    point_count = int((detail.get("outline") or {}).get("pointCount") or 0)
    outline_source = str((detail.get("outline") or {}).get("source") or "")
    analyzed = False
    if callable(evaluate_export_ready_body):
        try:
            export_check = evaluate_export_ready_body(body, min_dot=min_dot) or {}
        except Exception as ex:
            export_check = {
                "ready": False,
                "reasons": ["export_ready_error:{}".format(ex)],
            }
        export_ready = bool(export_check.get("ready"))
        export_reasons = list(export_check.get("reasons") or [])
        face_up = export_check.get("faceUp")
        feature_count = int(export_check.get("featureCount") or feature_count or 0)
        point_count = int(export_check.get("pointCount") or point_count or 0)
        outline_source = str(export_check.get("outlineSource") or outline_source or "")
        analyzed = bool(export_check.get("analyzed"))
        # Prefer Export Ready's resolved tags when present.
        if export_check.get("panelId"):
            item["panelId"] = str(export_check.get("panelId") or item["panelId"])
        if export_check.get("boardTypeTag"):
            item["boardTypeTag"] = str(export_check.get("boardTypeTag"))
        if export_check.get("colorTag"):
            item["colorTag"] = str(export_check.get("colorTag"))
        if export_check.get("cuttingFace"):
            item["cuttingFace"] = str(export_check.get("cuttingFace"))
        if export_check.get("thicknessMm") is not None:
            item["thicknessMm"] = export_check.get("thicknessMm")
        if export_check.get("lifecycleState"):
            item["lifecycleState"] = str(export_check.get("lifecycleState"))
    else:
        export_ready = False
        export_reasons = ["export_ready_helpers_unavailable"]

    troubleshoot = _export_only_reasons(item.get("missing") or [], export_reasons)
    problem = (not item.get("ok")) or (export_ready is False)
    item.update(
        {
            "exportReady": export_ready,
            "problem": problem,
            "troubleshoot": troubleshoot,
            "troubleshootCount": len(troubleshoot),
            "featureCount": feature_count,
            "pointCount": point_count,
            "outlineSource": outline_source,
            "analyzed": analyzed,
            "faceUp": face_up,
            "detail": detail,
        }
    )
    return item


def _public_record(item):
    return {
        "ok": bool(item.get("ok")),
        "exportReady": item.get("exportReady"),
        "problem": bool(item.get("problem")),
        "bodyName": item.get("bodyName") or "",
        "panelId": item.get("panelId") or "",
        "boardTypeTag": item.get("boardTypeTag") or "",
        "colorTag": item.get("colorTag") or "",
        "cuttingFace": item.get("cuttingFace") or "",
        "thicknessMm": item.get("thicknessMm"),
        "lifecycleState": item.get("lifecycleState") or "",
        "missing": list(item.get("missing") or []),
        "missingCount": int(item.get("missingCount") or 0),
        "troubleshoot": list(item.get("troubleshoot") or []),
        "troubleshootCount": int(item.get("troubleshootCount") or 0),
        "featureCount": int(item.get("featureCount") or 0),
        "pointCount": int(item.get("pointCount") or 0),
        "outlineSource": item.get("outlineSource") or "",
        "analyzed": bool(item.get("analyzed")),
        "faceUp": item.get("faceUp"),
        "detail": item.get("detail") if isinstance(item.get("detail"), dict) else {},
        "_body": item.get("_body"),
    }


def scan_bodies(bodies, min_dot=None):
    records = []
    missing_records = []
    problem_records = []
    not_export_ready = []
    reason_counts = {}
    for body in bodies or []:
        item = evaluate_body(body, min_dot=min_dot)
        public = _public_record(item)
        records.append(public)
        if not public["ok"]:
            missing_records.append(public)
            for reason in public["missing"]:
                reason_counts[reason] = int(reason_counts.get(reason) or 0) + 1
        if public["exportReady"] is False:
            not_export_ready.append(public)
            for reason in public["troubleshoot"]:
                key = str(reason).split(":", 1)[0]
                reason_counts[key] = int(reason_counts.get(key) or 0) + 1
        if public["problem"]:
            problem_records.append(public)

    return {
        "ok": not problem_records,
        "bodyCount": len(records),
        "completeCount": len(records) - len(missing_records),
        "missingCount": len(missing_records),
        "exportReadyCount": len(records) - len(not_export_ready),
        "notExportReadyCount": len(not_export_ready),
        "problemCount": len(problem_records),
        "reasonCounts": reason_counts,
        "records": records,
        "missing": missing_records,
        "notExportReady": not_export_ready,
        "problems": problem_records,
    }
