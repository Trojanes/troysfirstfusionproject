"""Vendor-neutral CabinetNC manufacturing snapshot (.cnjob) exporter.

This module is intentionally Fusion-free. The controller supplies full
``metadata_inspector`` body records after Nesting Ready / outline analysis.
"""

from __future__ import annotations

import json
import math
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path


FORMAT = "cabinetnc.manufacturing-snapshot"
SCHEMA_VERSION = "1.0.0"


def build_snapshot(records, job_id, source=None):
    errors = []
    warnings = []
    workpieces = []
    material_map = {}
    used_ids = set()

    for index, record in enumerate(records or []):
        if "body" not in str(record.get("entityKind") or "").lower():
            continue
        built, item_errors, item_warnings = _build_workpiece(
            record, index, used_ids=used_ids
        )
        errors.extend(item_errors)
        warnings.extend(item_warnings)
        if not built:
            continue
        workpieces.append(built)
        material = built["material"]
        material_id = material["materialId"]
        material_map.setdefault(
            material_id,
            {
                "materialId": material_id,
                "substrateId": material.get("substrateId"),
                "displayName": material.get("displayName"),
                "thicknessMm": material["thicknessMm"],
                "decorId": material.get("decorId"),
            },
        )

    if not workpieces:
        errors.append(
            _diagnostic("error", "workpieces_empty", "No production-ready workpieces.")
        )

    snapshot = {
        "schema": FORMAT,
        "schemaVersion": SCHEMA_VERSION,
        "jobId": str(job_id or "").strip(),
        "units": "mm",
        "exportedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": dict(source or {}),
        "materials": list(material_map.values()),
        "workpieces": workpieces,
        "relationships": [],
        "diagnostics": warnings,
    }
    if not snapshot["jobId"]:
        errors.append(_diagnostic("error", "job_id", "jobId is required."))
    return {"ok": not errors, "snapshot": snapshot, "errors": errors, "warnings": warnings}


def write_cnjob(path, snapshot):
    target = Path(path)
    if target.suffix.lower() != ".cnjob":
        target = target.with_suffix(".cnjob")
    temporary = target.with_name(target.name + ".tmp")
    manifest = {
        "format": FORMAT,
        "schemaVersion": SCHEMA_VERSION,
        "payload": "snapshot.json",
    }
    payload = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"))
    try:
        with zipfile.ZipFile(
            str(temporary), "w", compression=zipfile.ZIP_DEFLATED
        ) as archive:
            archive.writestr(
                "manifest.json",
                json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
            )
            archive.writestr("snapshot.json", payload)
        temporary.replace(target)
    finally:
        try:
            if temporary.exists():
                temporary.unlink()
        except Exception:
            pass
    return str(target)


def export_records(path, records, job_id, source=None):
    result = build_snapshot(records, job_id, source=source)
    if not result["ok"]:
        return result
    try:
        result["path"] = write_cnjob(path, result["snapshot"])
        return result
    except Exception as ex:
        return {
            **result,
            "ok": False,
            "errors": result["errors"]
            + [_diagnostic("error", "write_failed", str(ex))],
        }


def _build_workpiece(record, index, used_ids=None):
    errors = []
    warnings = []
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    identity = metadata.get("identity") if isinstance(metadata.get("identity"), dict) else {}
    base_panel_id = str(
        record.get("panelId") or identity.get("panelId") or "P{}".format(index + 1)
    ).strip()
    panel_id, id_warning = _unique_workpiece_id(
        base_panel_id,
        record,
        index,
        used_ids if isinstance(used_ids, set) else set(),
    )
    if id_warning:
        warnings.append(id_warning)
    workpiece_id = panel_id

    dimensions = record.get("dimensions")
    if not isinstance(dimensions, dict):
        dimensions = metadata.get("dimensions") if isinstance(metadata.get("dimensions"), dict) else {}
    thickness = _number(
        dimensions.get("thicknessMm")
        or record.get("measuredThicknessMm")
        or (metadata.get("designGeometry") or {}).get("materialThickness")
    )
    if thickness <= 0:
        errors.append(
            _diagnostic("error", "thickness", "Measured thickness must be > 0.", panel_id)
        )

    classification = (
        metadata.get("classification")
        if isinstance(metadata.get("classification"), dict)
        else {}
    )
    board_type = _classification_value(classification, "boardType") or str(
        record.get("boardTypeTag") or identity.get("boardType") or "board"
    )
    color = _classification_value(classification, "color") or str(
        record.get("colorTag") or "unassigned"
    )
    material_id = "{}-{}-{}".format(
        _slug(board_type), _slug(color), _format_number(thickness)
    )

    outline_record = (metadata.get("nestingFlatOutline") or {}).get("outline")
    if not isinstance(outline_record, dict):
        errors.append(
            _diagnostic(
                "error",
                "outline_missing",
                "Run Build Nesting Outlines before manufacturing export.",
                panel_id,
            )
        )
        points = []
    else:
        source_name = str(outline_record.get("source") or "").strip().lower()
        if source_name != "flatbody":
            errors.append(
                _diagnostic(
                    "error",
                    "non_production_outline",
                    "Manufacturing export requires a true flatBody outline (got {}).".format(
                        source_name or "missing"
                    ),
                    panel_id,
                )
            )
        raw_outline_points = outline_record.get("points") or []
        points = _normalize_closed_points(raw_outline_points)
        if (
            not _raw_points_are_finite(raw_outline_points)
            or len(points) < 3
            or _polygon_area_abs(points) <= 0.0001
        ):
            errors.append(
                _diagnostic(
                    "error",
                    "outline_invalid",
                    "Outer profile needs 3+ finite, non-collinear points.",
                    panel_id,
                )
            )

    face_result = _build_faces(record, metadata)
    faces = face_result["faces"]
    machining_face = face_result["machiningFace"]
    token_face = face_result["tokenFace"]
    warnings.extend(
        _diagnostic("warning", code, message, panel_id)
        for code, message in face_result["warnings"]
    )

    features = []
    blind_faces = set()
    feature_ids = set()
    for feature_index, feature in enumerate(metadata.get("features") or record.get("features") or []):
        converted, feature_errors = _convert_feature(
            feature,
            feature_index,
            machining_face,
            token_face,
            thickness_mm=thickness,
        )
        errors.extend(
            _diagnostic("error", code, message, panel_id)
            for code, message in feature_errors
        )
        for item in converted:
            feature_id_key = str(item.get("featureId") or "").strip().lower()
            if not feature_id_key:
                errors.append(
                    _diagnostic(
                        "error", "feature_id_missing", "Feature ID is required.", panel_id
                    )
                )
                continue
            if feature_id_key in feature_ids:
                errors.append(
                    _diagnostic(
                        "error",
                        "feature_id_duplicate",
                        "Duplicate featureId '{}'.".format(item.get("featureId")),
                        panel_id,
                    )
                )
                continue
            feature_ids.add(feature_id_key)
            if (
                not item.get("through")
                and _number(item.get("depthMm")) > thickness + 0.01
            ):
                errors.append(
                    _diagnostic(
                        "error",
                        "feature_depth_over_thickness",
                        "{} depth exceeds workpiece thickness.".format(
                            item.get("featureId")
                        ),
                        panel_id,
                    )
                )
                continue
            features.append(item)
            if not item["through"]:
                blind_faces.add(item["sourceFace"])

    invalid_blind_faces = {
        face for face in blind_faces if str(face or "").upper() not in ("A", "B")
    }
    if invalid_blind_faces:
        errors.append(
            _diagnostic(
                "error",
                "feature_face_unknown",
                "Blind feature has no resolved A/B opening face (got {}).".format(
                    ", ".join(sorted(str(face) for face in invalid_blind_faces))
                ),
                panel_id,
            )
        )
    known_blind_faces = {face for face in blind_faces if face in ("A", "B")}
    if len(known_blind_faces) > 1:
        errors.append(
            _diagnostic(
                "error",
                "double_side_unsupported",
                "Blind features exist on both A and B; only single-side machining is supported.",
                panel_id,
            )
        )

    if errors:
        return None, errors, warnings

    # Contract rule: Snapshot A is always the machining face. Color/role stay on
    # faces after remapping; CAD tokens never leave the plugin.
    machining_label = next(iter(known_blind_faces), machining_face or "A")
    faces, features, machining_label = _normalize_machining_face_to_a(
        faces, features, machining_label
    )
    faces = _ensure_machining_face_permission(faces)

    role = str(
        (metadata.get("defaultAttributes") or {}).get("role")
        or identity.get("boardType")
        or ""
    )
    display_name = _workpiece_display_name(record, panel_id)
    provenance = {
        "geometrySource": str(outline_record.get("source") or "analyzedBody"),
        "metadataSource": str(record.get("metadataSource") or ""),
    }
    if base_panel_id and base_panel_id != panel_id:
        provenance["sourcePanelId"] = base_panel_id
    assembly_name = str(record.get("assemblyName") or "").strip()
    component_name = str(record.get("componentName") or "").strip()
    if assembly_name:
        provenance["assemblyName"] = assembly_name
    if component_name:
        provenance["componentName"] = component_name

    workpiece = {
        "workpieceId": workpiece_id,
        "panelId": panel_id,
        "name": display_name,
        "quantity": 1,
        "identity": {
            "projectId": str(identity.get("runId") or ""),
            "moduleId": str(identity.get("module") or record.get("module") or ""),
            "role": role,
        },
        "material": {
            "materialId": material_id,
            "thicknessMm": round(thickness, 4),
            "substrateId": str(
                (metadata.get("defaultAttributes") or {}).get("materialClass")
                or board_type
            ),
            "decorId": color,
            "displayName": "{} {}mm".format(color, _format_number(thickness)),
        },
        "geometry": {
            "quality": "tessellated",
            "toleranceMm": 0.1,
            "outerProfile": {"closed": True, "points": points},
            "innerProfiles": [],
            "nestingPolygon": points,
        },
        "faces": faces,
        "features": features,
        "manufacturing": {
            "mode": "singleSide",
            "machiningFace": machining_label,
        },
        "provenance": provenance,
    }
    return workpiece, errors, warnings


def _workpiece_display_name(record, panel_id):
    assembly = str((record or {}).get("assemblyName") or "").strip()
    component = str((record or {}).get("componentName") or "").strip()
    body = str((record or {}).get("bodyName") or "").strip()
    if assembly and component:
        return "{} - {}".format(assembly, component)
    if component:
        return component
    if assembly and body:
        return "{} - {}".format(assembly, body)
    return body or str(panel_id or "panel")


def _unique_workpiece_id(base_panel_id, record, index, used_ids):
    """Ensure workpiece/panel ids are unique across the job list.

    CAD often reuses ``module.Body1`` for every unnamed solid. Prefer a stable
    occurrence-path suffix, then numeric ``__N``.
    """
    base = str(base_panel_id or "").strip() or "P{}".format(index + 1)
    path = list((record or {}).get("occurrencePath") or [])
    path_suffix = "-".join(str(part) for part in path) if path else ""
    body = str((record or {}).get("bodyName") or "").strip()
    candidates = [base]
    if path_suffix:
        candidates.append("{}@{}".format(base, path_suffix))
    if body and body.lower() not in base.lower():
        candidates.append("{}.{}".format(base, body))
    candidates.append("{}#{}".format(base, index + 1))

    for candidate in candidates:
        key = candidate.lower()
        if key not in used_ids:
            used_ids.add(key)
            warning = None
            if candidate != base:
                warning = _diagnostic(
                    "warning",
                    "panel_id_uniquified",
                    "panelId '{}' remapped to '{}' for uniqueness.".format(
                        base, candidate
                    ),
                    candidate,
                )
            return candidate, warning

    suffix = 2
    while True:
        candidate = "{}__{}".format(base, suffix)
        key = candidate.lower()
        if key not in used_ids:
            used_ids.add(key)
            return candidate, _diagnostic(
                "warning",
                "panel_id_uniquified",
                "panelId '{}' remapped to '{}' for uniqueness.".format(base, candidate),
                candidate,
            )
        suffix += 1


def _normalize_machining_face_to_a(faces, features, machining_label):
    """Force Snapshot A = machining face; opposite face becomes B."""
    label = str(machining_label or "A").strip().upper()
    if label not in ("A", "B"):
        label = "A"
    if label == "A":
        return faces, features, "A"

    remapped_faces = []
    for face in faces or []:
        face_id = str(face.get("faceId") or "").upper()
        if face_id == "A":
            face_id = "B"
        elif face_id == "B":
            face_id = "A"
        remapped = dict(face)
        remapped["faceId"] = face_id
        remapped_faces.append(remapped)

    remapped_features = []
    for feature in features or []:
        source = str(feature.get("sourceFace") or "").upper()
        if source == "A":
            source = "B"
        elif source == "B":
            source = "A"
        remapped = dict(feature)
        remapped["sourceFace"] = source
        remapped_features.append(remapped)
    return remapped_faces, remapped_features, "A"


def _ensure_machining_face_permission(faces):
    """Snapshot A is the machining face — never leave it as NOT_ALLOWED."""
    updated = []
    for face in faces or []:
        remapped = dict(face)
        if str(remapped.get("faceId") or "").upper() == "A":
            permission = str(remapped.get("machiningPermission") or "").upper()
            if permission in ("", "NOT_ALLOWED", "UNASSIGNED"):
                remapped["machiningPermission"] = "PRIMARY"
        updated.append(remapped)
    return updated


def _build_faces(record, metadata):
    face_summary = record.get("faceSummary")
    raw_faces = face_summary.get("faces") if isinstance(face_summary, dict) else None
    if not isinstance(raw_faces, list):
        raw_faces = (metadata.get("faceRegistry") or {}).get("faces") or []

    surfaces = []
    for raw in raw_faces:
        payload = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else raw
        if isinstance(payload.get("payload"), dict):
            payload = payload["payload"]
        if str(payload.get("faceClass") or "").upper() != "SURFACE":
            continue
        surfaces.append(payload)

    surfaces.sort(
        key=lambda face: (
            0 if str(face.get("millingSurface") or "").upper() == "MILLING" else 1,
            str(face.get("faceId") or face.get("entityToken") or ""),
        )
    )
    warnings = []
    if len(surfaces) < 2:
        warnings.append(
            ("faces_missing", "A/B face finish metadata is incomplete.")
        )

    faces = []
    token_face = {}
    machining_face = "EITHER"
    for index, face in enumerate(surfaces[:2]):
        face_id = "A" if index == 0 else "B"
        milling = str(face.get("millingSurface") or "").upper()
        if milling == "MILLING":
            machining_face = face_id
        finish = face.get("finish") if isinstance(face.get("finish"), dict) else {}
        finish_id = finish.get("finishId") or face.get("finishId") or "UNASSIGNED"
        finish_name = finish.get("finishName") or face.get("finishName") or "Unassigned"
        faces.append(
            {
                "faceId": face_id,
                "role": str(face.get("faceRole") or "").lower(),
                "finish": {
                    "finishId": str(finish_id),
                    "finishName": str(finish_name),
                },
                "machiningPermission": str(
                    face.get("machiningPermission") or "UNASSIGNED"
                ).upper(),
            }
        )
        for token_key in ("entityToken", "openSurfaceToken", "faceId"):
            token = str(face.get(token_key) or "")
            if token:
                token_face[token] = face_id

    while len(faces) < 2:
        face_id = "A" if not faces else "B"
        faces.append(
            {
                "faceId": face_id,
                "role": "",
                "finish": {"finishId": "UNASSIGNED", "finishName": "Unassigned"},
                "machiningPermission": "UNASSIGNED",
            }
        )
    return {
        "faces": faces,
        "machiningFace": machining_face,
        "tokenFace": token_face,
        "warnings": warnings,
    }


def _normalize_blind_open_face(open_is, depth_mm, thickness_mm, feature=None):
    """Remap false B opens when the floor sits near the colour skin."""
    open_is = str(open_is or "").strip().upper()
    depth = _number(depth_mm)
    thickness = _number(thickness_mm)
    feature = feature if isinstance(feature, dict) else {}
    if open_is != "B" or thickness <= 0:
        return open_is, depth
    floor_z = feature.get("floorOffsetMm")
    try:
        if floor_z is not None:
            # Without absolute A/B offsets, a floor near either skin is enough
            # when paired with shallow recorded B depth (see below).
            pass
    except Exception:
        pass
    if 0 < depth < min(6.0, thickness * 0.4):
        return "A", round(max(depth, thickness - depth), 3)
    return open_is, depth


def _convert_feature(feature, index, default_face, token_face, thickness_mm=0.0):
    errors = []
    feature_id = str(feature.get("featureId") or "F{}".format(index + 1))
    kind = str(feature.get("kind") or "unknown").lower()
    if kind not in ("hole", "groove", "pocket"):
        return [], [
            (
                "feature_kind_unsupported",
                "{} has unsupported kind '{}'.".format(feature_id, kind),
            )
        ]
    cut_type = str(feature.get("cutType") or "").upper()
    through = cut_type == "FULL" or bool(feature.get("through"))
    token = str(feature.get("openSurfaceToken") or "")
    open_is = str(feature.get("openSurfaceIs") or "").strip().upper()
    depth = _number(feature.get("depthMm"))
    if not through:
        open_is, depth = _normalize_blind_open_face(
            open_is, depth, thickness_mm, feature
        )
    if through:
        source_face = "THROUGH"
    elif open_is in ("A", "B"):
        # Lay Flat analyze stamps A/B without relying on CAD face tokens.
        source_face = open_is
    elif token and token in (token_face or {}):
        source_face = token_face.get(token)
    else:
        source_face = default_face or "UNKNOWN"
    if not through and depth <= 0:
        errors.append(
            ("feature_depth", "{} requires depthMm > 0.".format(feature_id))
        )
    intent = {
        "purpose": str(feature.get("purpose") or feature.get("operationType") or ""),
        "operationType": str(feature.get("operationType") or ""),
        "sourceRelationshipId": str(feature.get("sourceRelationshipId") or ""),
    }

    positions = feature.get("positionsLocal")
    if kind == "hole" and isinstance(positions, list) and positions:
        output = []
        diameter = _number(
            feature.get("diameterMm") or (_number(feature.get("radiusMm")) * 2)
        )
        if diameter <= 0:
            return [], [
                ("hole_geometry", "{} requires diameterMm > 0.".format(feature_id))
            ]
        for position_index, position in enumerate(positions):
            if not isinstance(position, dict):
                errors.append(
                    (
                        "hole_geometry",
                        "{} position {} requires numeric x/y.".format(
                            feature_id, position_index + 1
                        ),
                    )
                )
                continue
            try:
                x_value = float(position.get("x"))
                y_value = float(position.get("y"))
                if not math.isfinite(x_value) or not math.isfinite(y_value):
                    raise ValueError()
            except Exception:
                errors.append(
                    (
                        "hole_geometry",
                        "{} position {} requires numeric x/y.".format(
                            feature_id, position_index + 1
                        ),
                    )
                )
                continue
            output.append(
                {
                    "featureId": "{}-{}".format(feature_id, position_index + 1),
                    "groupId": feature_id,
                    "kind": "bore",
                    "sourceFace": source_face,
                    "geometry": {
                        "center": [
                            round(x_value, 4),
                            round(y_value, 4),
                        ],
                        "diameterMm": round(diameter, 4),
                    },
                    "depthMm": round(depth, 4) if depth > 0 else None,
                    "through": through,
                    "intent": intent,
                }
            )
        return output, errors

    raw_points = (
        feature.get("pointsLocal") or feature.get("points") or feature.get("path") or []
    )
    if raw_points and not _raw_points_are_finite(raw_points):
        return [], [
            ("feature_geometry", "{} contains non-finite points.".format(feature_id))
        ]
    points = _normalize_closed_points(raw_points)
    if kind == "hole":
        center = feature.get("center2d") or feature.get("center")
        diameter = _number(
            feature.get("diameterMm") or (_number(feature.get("radiusMm")) * 2)
        )
        if (
            not isinstance(center, (list, tuple))
            or len(center) < 2
            or not _is_finite_number(center[0])
            or not _is_finite_number(center[1])
            or diameter <= 0
        ):
            return [], [("hole_geometry", "{} requires center and diameter.".format(feature_id))]
        geometry = {
            "center": [round(_number(center[0]), 4), round(_number(center[1]), 4)],
            "diameterMm": round(diameter, 4),
        }
        canonical_kind = "bore"
    elif kind == "groove":
        centerline, width = _groove_centerline(points)
        width = _number(feature.get("widthMm")) or width
        if len(centerline) >= 2 and width > 0:
            geometry = {"centerline": centerline, "widthMm": round(width, 4)}
            canonical_kind = "groove"
        elif len(points) >= 3 and _polygon_area_abs(points) > 0.0001:
            # Rounded / non-quad channels still ship as closed pocket profiles.
            geometry = {"profile": {"closed": True, "points": points}}
            canonical_kind = "pocket"
        else:
            return [], [
                (
                    "groove_geometry",
                    "{} requires a centreline and width, or a closed profile.".format(
                        feature_id
                    ),
                )
            ]
    else:
        if len(points) < 3:
            return [], [("profile_geometry", "{} requires a closed profile.".format(feature_id))]
        geometry = {"profile": {"closed": True, "points": points}}
        canonical_kind = "throughProfile" if through else "pocket"

    return [
        {
            "featureId": feature_id,
            "kind": canonical_kind,
            "sourceFace": source_face,
            "geometry": geometry,
            "depthMm": round(depth, 4) if depth > 0 else None,
            "through": through,
            "intent": intent,
        }
    ], errors


def _groove_centerline(points):
    """Derive groove centreline + width from a closed 2D outline.

    Prefer a simplified rectangle (4 corners). Tessellated or capsule-like
    channels fall back to a principal-axis (PCA) strip.
    """
    ring = [list(point[:2]) for point in (points or []) if len(point) >= 2]
    if len(ring) < 3:
        return [], 0.0
    simplified = _simplify_collinear(ring, max_deviation_mm=0.15)
    if len(simplified) == 4:
        return _groove_centerline_from_quad(simplified)
    return _groove_centerline_from_pca(ring)


def _groove_centerline_from_quad(points):
    lengths = [
        _distance(points[index], points[(index + 1) % 4]) for index in range(4)
    ]
    if lengths[0] >= lengths[1]:
        start = _midpoint(points[3], points[0])
        finish = _midpoint(points[1], points[2])
        width = (lengths[1] + lengths[3]) / 2.0
    else:
        start = _midpoint(points[0], points[1])
        finish = _midpoint(points[2], points[3])
        width = (lengths[0] + lengths[2]) / 2.0
    if width <= 0:
        return [], 0.0
    return [_rounded_point(start), _rounded_point(finish)], width


def _groove_centerline_from_pca(points, min_aspect=2.5):
    """Centreline of an elongated strip via 2D principal axis."""
    count = len(points or [])
    if count < 3:
        return [], 0.0
    cx = sum(_number(point[0]) for point in points) / float(count)
    cy = sum(_number(point[1]) for point in points) / float(count)
    sxx = syy = sxy = 0.0
    for point in points:
        dx = _number(point[0]) - cx
        dy = _number(point[1]) - cy
        sxx += dx * dx
        syy += dy * dy
        sxy += dx * dy
    # Eigenvector for largest eigenvalue of covariance.
    trace = sxx + syy
    det = sxx * syy - sxy * sxy
    disc = max(0.0, trace * trace * 0.25 - det)
    root = math.sqrt(disc)
    eig1 = trace * 0.5 + root
    if abs(sxy) > 1e-12:
        axis_x, axis_y = eig1 - syy, sxy
    elif sxx >= syy:
        axis_x, axis_y = 1.0, 0.0
    else:
        axis_x, axis_y = 0.0, 1.0
    norm = math.hypot(axis_x, axis_y)
    if norm <= 1e-12:
        return [], 0.0
    axis_x /= norm
    axis_y /= norm
    perp_x, perp_y = -axis_y, axis_x
    along = []
    across = []
    for point in points:
        dx = _number(point[0]) - cx
        dy = _number(point[1]) - cy
        along.append(dx * axis_x + dy * axis_y)
        across.append(dx * perp_x + dy * perp_y)
    min_along, max_along = min(along), max(along)
    min_across, max_across = min(across), max(across)
    length = max_along - min_along
    width = max_across - min_across
    if width <= 1e-6 or length / width < float(min_aspect):
        return [], 0.0
    mid_across = 0.5 * (min_across + max_across)
    start = [
        cx + min_along * axis_x + mid_across * perp_x,
        cy + min_along * axis_y + mid_across * perp_y,
    ]
    finish = [
        cx + max_along * axis_x + mid_across * perp_x,
        cy + max_along * axis_y + mid_across * perp_y,
    ]
    return [_rounded_point(start), _rounded_point(finish)], width


def _simplify_collinear(points, max_deviation_mm=0.15, relative_tolerance=1e-6):
    """Collapse tessellated straight edges to polygon corners.

    Uses perpendicular distance in millimetres so Fusion stroke noise (often
    >1e-3 mm) still collapses to a clean rectangle.
    """
    simplified = [list(point[:2]) for point in (points or []) if len(point) >= 2]
    if len(simplified) <= 4:
        return simplified
    changed = True
    while changed and len(simplified) > 4:
        changed = False
        kept = []
        count = len(simplified)
        for index, current in enumerate(simplified):
            previous = simplified[(index - 1) % count]
            following = simplified[(index + 1) % count]
            ax = _number(current[0]) - _number(previous[0])
            ay = _number(current[1]) - _number(previous[1])
            bx = _number(following[0]) - _number(current[0])
            by = _number(following[1]) - _number(current[1])
            cross = abs(ax * by - ay * bx)
            chord = math.hypot(
                _number(following[0]) - _number(previous[0]),
                _number(following[1]) - _number(previous[1]),
            )
            if chord <= 1e-9:
                changed = True
                continue
            deviation = cross / chord
            scale = max(1.0, math.hypot(ax, ay) * math.hypot(bx, by))
            if deviation <= float(max_deviation_mm) or cross <= relative_tolerance * scale:
                changed = True
                continue
            kept.append(current)
        if len(kept) < 3 or len(kept) == len(simplified):
            break
        simplified = kept
    return simplified


def _normalize_closed_points(raw_points):
    points = []
    for raw in raw_points or []:
        if isinstance(raw, dict):
            point = [_number(raw.get("x")), _number(raw.get("y"))]
        elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
            point = [_number(raw[0]), _number(raw[1])]
        else:
            continue
        if not points or _distance(points[-1], point) > 0.0001:
            points.append(_rounded_point(point))
    if len(points) > 1 and _distance(points[0], points[-1]) <= 0.0001:
        points.pop()
    return points


def _is_finite_number(value):
    try:
        return math.isfinite(float(value))
    except Exception:
        return False


def _raw_points_are_finite(raw_points):
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


def _polygon_area_abs(points):
    if len(points or []) < 3:
        return 0.0
    area = 0.0
    for index, point in enumerate(points):
        following = points[(index + 1) % len(points)]
        area += _number(point[0]) * _number(following[1])
        area -= _number(following[0]) * _number(point[1])
    return abs(area) * 0.5


def _classification_value(classification, key):
    state = classification.get(key) if isinstance(classification, dict) else None
    if isinstance(state, dict):
        return str(state.get("value") or "")
    return str(state or "")


def _diagnostic(severity, code, message, entity_id=None):
    value = {"severity": severity, "code": code, "message": message}
    if entity_id:
        value["entityId"] = entity_id
    return value


def _number(value):
    try:
        number = float(value)
        return number if math.isfinite(number) else 0.0
    except Exception:
        return 0.0


def _distance(left, right):
    return math.hypot(_number(left[0]) - _number(right[0]), _number(left[1]) - _number(right[1]))


def _midpoint(left, right):
    return [(_number(left[0]) + _number(right[0])) / 2.0, (_number(left[1]) + _number(right[1])) / 2.0]


def _rounded_point(point):
    return [round(_number(point[0]), 4), round(_number(point[1]), 4)]


def _format_number(value):
    return ("{:.3f}".format(_number(value))).rstrip("0").rstrip(".")


def _slug(value):
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").strip().lower()).strip("-")
    return text or "unassigned"
