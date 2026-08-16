"""Export Ready checkup for Lay Flat manufacturing bodies."""

from __future__ import annotations

import json
import math

try:
    from nesting.lay_flat_analyze import (
        ANALYZED_STATE,
        _brep_feature_ring_count,
        cache_is_fresh,
    )
    from nesting.outline_cache import (
        CACHE_KEY,
        attribute_entities,
        body_geometry_signature,
    )
except Exception:
    from lay_flat_analyze import (  # type: ignore
        ANALYZED_STATE,
        _brep_feature_ring_count,
        cache_is_fresh,
    )
    from outline_cache import (  # type: ignore
        CACHE_KEY,
        attribute_entities,
        body_geometry_signature,
    )

try:
    from nesting.manufacturing_snapshot_export import (
        _groove_centerline,
        _normalize_closed_points,
        _number,
    )
except Exception:
    try:
        from manufacturing_snapshot_export import (  # type: ignore
            _groove_centerline,
            _normalize_closed_points,
            _number,
        )
    except Exception:
        _groove_centerline = None
        _normalize_closed_points = None
        _number = None

try:
    from nesting.lay_flat_face_up import evaluate_body_role_normals
except Exception:
    try:
        from lay_flat_face_up import evaluate_body_role_normals  # type: ignore
    except Exception:
        evaluate_body_role_normals = None

try:
    from nesting.preflight import _undefined
except Exception:
    try:
        from preflight import _undefined  # type: ignore
    except Exception:

        def _undefined(value):
            text = str(value or "").strip().lower()
            return (
                not text
                or "unknown" in text
                or text in ("undefined", "unassigned", "none", "n/a")
            )


PANEL_GROUP = "UnifiedCabinet.Panel"


def _canonical(metadata, field):
    classification = (
        metadata.get("classification") if isinstance(metadata, dict) else {}
    )
    state = classification.get(field) if isinstance(classification, dict) else {}
    if isinstance(state, dict):
        return str(state.get("value") or "").strip()
    return str(state or "").strip()


def _point_count(raw_points):
    count = 0
    for raw in raw_points or []:
        if isinstance(raw, dict) and ("x" in raw or "y" in raw):
            count += 1
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            count += 1
    return count


def _points_are_finite(raw_points):
    for raw in raw_points or []:
        if isinstance(raw, dict):
            x_value, y_value = raw.get("x"), raw.get("y")
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            x_value, y_value = raw[0], raw[1]
        else:
            return False
        if not _is_finite_number(x_value) or not _is_finite_number(y_value):
            return False
    return True


def _polygon_area_abs(raw_points):
    points = _closed_points(raw_points)
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index, point in enumerate(points):
        following = points[(index + 1) % len(points)]
        area += point[0] * following[1] - following[0] * point[1]
    return abs(area) * 0.5


def _as_number(value):
    if callable(_number):
        return float(_number(value))
    try:
        number = float(value)
        return number if math.isfinite(number) else 0.0
    except Exception:
        return 0.0


def _is_finite_number(value):
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def _closed_points(raw_points):
    if callable(_normalize_closed_points):
        return list(_normalize_closed_points(raw_points) or [])
    points = []
    for raw in raw_points or []:
        if isinstance(raw, dict):
            points.append([_as_number(raw.get("x")), _as_number(raw.get("y"))])
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            points.append([_as_number(raw[0]), _as_number(raw[1])])
    return points


def _groove_exportable(feature, raw_points):
    """True when groove can convert like manufacturing_snapshot_export."""
    points = _closed_points(raw_points)
    if callable(_groove_centerline):
        centerline, width = _groove_centerline(points)
        width = _as_number(feature.get("widthMm")) or _as_number(width)
        if len(centerline or []) >= 2 and width > 0:
            return True
    # Match export fallback: non-quad channels ship as closed pocket profiles.
    return _point_count(points) >= 3 and _polygon_area_abs(points) > 0.0001


def _feature_reasons(features, thickness_mm=0.0):
    reasons = []
    blind_faces = set()
    feature_ids = set()
    for index, feature in enumerate(features or []):
        if not isinstance(feature, dict):
            reasons.append("feature_invalid")
            continue
        cut_type = str(feature.get("cutType") or "").upper()
        through = cut_type == "FULL" or bool(feature.get("through"))
        open_is = str(feature.get("openSurfaceIs") or "").strip().upper()
        kind = str(feature.get("kind") or "").lower()
        feature_id = str(feature.get("featureId") or "").strip()
        feature_key = feature_id.lower()
        if not feature_id:
            reasons.append("feature_id_missing")
        elif feature_key in feature_ids:
            reasons.append("feature_id_duplicate")
        else:
            feature_ids.add(feature_key)
        if kind not in ("hole", "groove", "pocket"):
            reasons.append("feature_kind_unsupported")
        points = feature.get("pointsLocal") or feature.get("points") or feature.get("path") or []
        positions = feature.get("positionsLocal")
        if points and not _points_are_finite(points):
            reasons.append("feature_geometry")

        depth = _as_number(feature.get("depthMm"))
        if not through:
            if open_is in ("A", "B"):
                blind_faces.add(open_is)
                if open_is != "A":
                    reasons.append("feature_face_not_machining")
            else:
                reasons.append("feature_face_unknown")
            if depth <= 0:
                reasons.append("feature_depth")
            elif thickness_mm > 0 and depth > float(thickness_mm) + 0.01:
                reasons.append("feature_depth_over_thickness")

        if kind == "hole":
            diameter = feature.get("diameterMm")
            if diameter is None and feature.get("radiusMm") is not None:
                try:
                    diameter = float(feature.get("radiusMm")) * 2.0
                except Exception:
                    diameter = 0.0
            diameter = _as_number(diameter)
            has_positions = (
                isinstance(positions, list)
                and bool(positions)
                and diameter > 0
                and all(
                    isinstance(position, dict)
                    and _is_finite_number(position.get("x"))
                    and _is_finite_number(position.get("y"))
                    for position in positions
                )
            )
            center = feature.get("center2d") or feature.get("center")
            has_center = isinstance(center, (list, tuple)) and len(center) >= 2 and diameter > 0
            if not has_positions and not has_center:
                reasons.append("feature_geometry")
        elif kind == "groove":
            # Align with export: 4-pt outline → centreline + width > 0.
            if not _groove_exportable(feature, points):
                reasons.append("groove_geometry")
        else:
            # Pocket / throughProfile / unknown profile features need a closed ring.
            if _point_count(points) < 3:
                reasons.append("feature_geometry")

    if "A" in blind_faces and "B" in blind_faces:
        reasons.append("double_side_unsupported")
    # Deduplicate while preserving order.
    seen = set()
    ordered = []
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        ordered.append(reason)
    return ordered


def evaluate_metadata(metadata, geometry_signature=None):
    """Pure Export Ready check from body metadata (+ optional geometry signature)."""
    meta = metadata if isinstance(metadata, dict) else {}
    reasons = []

    lifecycle = meta.get("lifecycle") if isinstance(meta.get("lifecycle"), dict) else {}
    state = str(lifecycle.get("state") or "")
    analyzed = state == ANALYZED_STATE
    if not analyzed:
        reasons.append("not_analyzed")

    signature = str(geometry_signature or "")
    if analyzed and signature and not cache_is_fresh(meta, signature):
        reasons.append("analyze_stale")
    elif analyzed and not signature:
        # Without a live signature, still require outline + features list.
        cached = meta.get(CACHE_KEY) if isinstance(meta.get(CACHE_KEY), dict) else {}
        outline = cached.get("outline") if isinstance(cached.get("outline"), dict) else {}
        if not outline.get("points") or not isinstance(meta.get("features"), list):
            reasons.append("analyze_stale")

    cached = meta.get(CACHE_KEY) if isinstance(meta.get(CACHE_KEY), dict) else {}
    outline = cached.get("outline") if isinstance(cached.get("outline"), dict) else {}
    points = outline.get("points") or []
    if (
        not _points_are_finite(points)
        or _point_count(points) < 3
        or _polygon_area_abs(points) <= 0.0001
    ):
        reasons.append("outline_missing")
    source_name = str(outline.get("source") or "").lower()
    if source_name != "flatbody":
        reasons.append("non_production_outline")

    dimensions = meta.get("dimensions") if isinstance(meta.get("dimensions"), dict) else {}
    thickness = 0.0
    for key in ("thicknessMm", "materialThickness"):
        try:
            thickness = float(dimensions.get(key) or 0.0)
        except Exception:
            thickness = 0.0
        if thickness > 0:
            break
    if thickness <= 0:
        design = meta.get("designGeometry") if isinstance(meta.get("designGeometry"), dict) else {}
        try:
            thickness = float(design.get("materialThickness") or 0.0)
        except Exception:
            thickness = 0.0
    if thickness <= 0:
        reasons.append("thickness")

    board_type = _canonical(meta, "boardType")
    color = _canonical(meta, "color")
    cutting_face = _canonical(meta, "cuttingFace").upper()
    if cutting_face not in ("MILLING", "EITHER"):
        cutting_face = "UNASSIGNED"
    if _undefined(board_type):
        reasons.append("board_type")
    if _undefined(color):
        reasons.append("color")
    if cutting_face not in ("MILLING", "EITHER"):
        reasons.append("cutting_face")

    features = meta.get("features")
    if analyzed and not isinstance(features, list):
        reasons.append("features_missing")
        features = []
    reasons.extend(
        _feature_reasons(
            features if isinstance(features, list) else [],
            thickness_mm=thickness,
        )
    )

    seen = set()
    ordered = []
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        ordered.append(reason)

    identity = meta.get("identity") if isinstance(meta.get("identity"), dict) else {}
    return {
        "ready": not ordered,
        "reasons": ordered,
        "panelId": str(identity.get("panelId") or ""),
        "boardTypeTag": board_type,
        "colorTag": color,
        "cuttingFace": cutting_face,
        "thicknessMm": thickness,
        "featureCount": len(features) if isinstance(features, list) else 0,
        "pointCount": _point_count(points),
        "outlineSource": str(outline.get("source") or ""),
        "lifecycleState": state,
        "analyzed": analyzed,
    }


def _metadata_richness(metadata):
    if not isinstance(metadata, dict):
        return 0
    score = 0
    classification = metadata.get("classification")
    if isinstance(classification, dict):
        for field in ("boardType", "color", "cuttingFace"):
            state = classification.get(field)
            if isinstance(state, dict) and str(state.get("value") or "").strip():
                score += 2
    if metadata.get(CACHE_KEY):
        score += 1
    if metadata.get("features"):
        score += 1
    return score


def _read_metadata(body):
    best = None
    best_score = -1
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
        if not isinstance(data, dict):
            continue
        score = _metadata_richness(data)
        if score > best_score:
            best = data
            best_score = score
    return best or {}


def evaluate_body(body, min_dot=None):
    """Inspect one Lay Flat body for Export Ready (metadata + Face Up)."""
    body_name = ""
    try:
        body_name = str(getattr(body, "name", "") or "")
    except Exception:
        body_name = ""
    if body is None:
        return {
            "ready": False,
            "bodyName": body_name,
            "reasons": ["missing_body"],
            "_body": None,
        }

    metadata = _read_metadata(body)
    try:
        from panel_attributes import attribute_state_service as _attr_state
    except Exception:
        try:
            import attribute_state_service as _attr_state
        except Exception:
            _attr_state = None
    if _attr_state is not None and metadata:
        try:
            metadata = _attr_state.migrate_metadata(metadata)
        except Exception:
            pass
    try:
        signature = body_geometry_signature(body, detail=True)
    except Exception:
        signature = ""
    check = evaluate_metadata(metadata, geometry_signature=signature)
    reasons = list(check.get("reasons") or [])

    face_up = None
    if callable(evaluate_body_role_normals):
        try:
            face_up = evaluate_body_role_normals(body, min_dot=min_dot)
        except Exception as ex:
            face_up = {"ok": False, "reasons": ["faces_up_error:{}".format(ex)]}
        if not face_up.get("ok"):
            reasons.append("faces_up_fail")
            for item in face_up.get("reasons") or []:
                code = "faces_up:{}".format(item)
                if code not in reasons:
                    reasons.append(code)
    else:
        reasons.extend(["faces_up_fail", "faces_up:helpers_unavailable"])

    try:
        evidence_count = int(_brep_feature_ring_count(body) or 0)
    except Exception:
        evidence_count = -1
    if evidence_count < 0:
        reasons.append("feature_evidence_unavailable")
    elif int(check.get("featureCount") or 0) < evidence_count:
        # Under-extraction only. Over-count vs ring evidence is allowed.
        reasons.append("feature_extract_incomplete")

    # Deduplicate
    seen = set()
    ordered = []
    for reason in reasons:
        if reason in seen:
            continue
        seen.add(reason)
        ordered.append(reason)

    return {
        "ready": not ordered,
        "bodyName": body_name,
        "panelId": check.get("panelId") or "",
        "reasons": ordered,
        "boardTypeTag": check.get("boardTypeTag") or "",
        "colorTag": check.get("colorTag") or "",
        "cuttingFace": check.get("cuttingFace") or "",
        "thicknessMm": check.get("thicknessMm"),
        "featureCount": check.get("featureCount") or 0,
        "pointCount": check.get("pointCount") or 0,
        "outlineSource": check.get("outlineSource") or "",
        "lifecycleState": check.get("lifecycleState") or "",
        "analyzed": bool(check.get("analyzed")),
        "faceUp": {
            "ok": bool((face_up or {}).get("ok")),
            "reasons": list((face_up or {}).get("reasons") or []),
            "millingDotPlusZ": (face_up or {}).get("millingDotPlusZ"),
            "colourDotMinusZ": (face_up or {}).get("colourDotMinusZ"),
        }
        if face_up is not None
        else None,
        "_body": body,
    }


def check_bodies(bodies, min_dot=None, wait_callback=None):
    ready = []
    not_ready = []
    reason_counts = {}
    for index, body in enumerate(bodies or []):
        item = evaluate_body(body, min_dot=min_dot)
        slim = {
            "bodyName": item.get("bodyName") or "",
            "panelId": item.get("panelId") or "",
            "ready": bool(item.get("ready")),
            "reasons": list(item.get("reasons") or []),
            "boardTypeTag": item.get("boardTypeTag") or "",
            "colorTag": item.get("colorTag") or "",
            "cuttingFace": item.get("cuttingFace") or "",
            "thicknessMm": item.get("thicknessMm"),
            "featureCount": item.get("featureCount") or 0,
            "pointCount": item.get("pointCount") or 0,
            "outlineSource": item.get("outlineSource") or "",
            "lifecycleState": item.get("lifecycleState") or "",
            "analyzed": bool(item.get("analyzed")),
            "faceUp": item.get("faceUp"),
        }
        slim["_body"] = item.get("_body")
        if slim["ready"]:
            ready.append(slim)
        else:
            not_ready.append(slim)
            for reason in slim["reasons"]:
                # Aggregate top-level codes (strip faces_up: detail).
                key = reason.split(":", 1)[0] if reason.startswith("faces_up:") else reason
                reason_counts[key] = int(reason_counts.get(key) or 0) + 1
        if callable(wait_callback) and (index + 1) % 20 == 0:
            try:
                wait_callback()
            except Exception:
                pass
    return {
        "ok": not not_ready,
        "bodyCount": len(bodies or []),
        "readyCount": len(ready),
        "notReadyCount": len(not_ready),
        "reasonCounts": reason_counts,
        "ready": ready,
        "notReady": not_ready,
    }
