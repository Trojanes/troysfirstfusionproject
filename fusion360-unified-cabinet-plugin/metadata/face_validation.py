from face_models import (
    BANDING_CODE_NONE,
    FACE_CLASS_EDGE,
    FACE_CLASS_SURFACE,
    FACE_CLASSES,
    FINISH_UNASSIGNED_ID,
    MACHINING_NOT_ALLOWED,
    MACHINING_PRIMARY,
    MACHINING_PERMISSIONS,
    NESTING_DOWN,
    NESTING_EITHER,
    NESTING_NOT_APPLICABLE,
    NESTING_ORIENTATIONS,
    NESTING_UP,
    SURFACE_MODE_DOUBLE_SIDED,
    SURFACE_MODE_SINGLE_SIDED,
    SURFACE_MODES,
    VALID_BANDING_CODES,
)


def validation_result(valid=True, errors=None, warnings=None):
    return {
        "valid": bool(valid),
        "errors": list(errors or []),
        "warnings": list(warnings or []),
    }


def _finish_id(metadata):
    finish = (metadata or {}).get("finish") or {}
    return str(finish.get("finishId") or "").strip()


def _validate_edge_banding(edge_banding):
    errors = []
    if not isinstance(edge_banding, dict):
        return ["edgeBanding must be an object"]
    required = bool(edge_banding.get("required"))
    code = int(edge_banding.get("bandingCode", BANDING_CODE_NONE))
    if not required and code != BANDING_CODE_NONE:
        errors.append("bandingCode must be 0 when required is false")
    if required and code not in {1, 2, 3}:
        errors.append("bandingCode must be 1, 2, or 3 when required is true")
    if code not in VALID_BANDING_CODES:
        errors.append("bandingCode is invalid")
    finish_id = str(edge_banding.get("finishId") or "").strip()
    if not finish_id or finish_id == "":
        errors.append("edgeBanding.finishId must not be empty")
    return errors


def validate_face_metadata(metadata, panel_context=None):
    errors = []
    warnings = []
    if not isinstance(metadata, dict):
        return validation_result(False, ["Face metadata must be an object"])

    if metadata.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")

    panel_id = str(metadata.get("panelId") or "").strip()
    face_id = str(metadata.get("faceId") or "").strip()
    if not panel_id:
        errors.append("panelId is required")
    if not face_id:
        errors.append("faceId is required")

    owner_panel_id = str((panel_context or {}).get("panelId") or "").strip()
    if owner_panel_id and panel_id and panel_id != owner_panel_id:
        errors.append("panelId does not match owner panel")

    face_class = metadata.get("faceClass")
    if face_class not in FACE_CLASSES:
        errors.append("faceClass must be SURFACE or EDGE")

    finish = metadata.get("finish") or {}
    finish_id = _finish_id(metadata)
    if not finish_id or finish_id == "":
        errors.append("finish.finishId must not be empty")
    elif finish_id == FINISH_UNASSIGNED_ID:
        warnings.append("finish is UNASSIGNED")

    nesting_orientation = metadata.get("nestingOrientation")
    if nesting_orientation not in NESTING_ORIENTATIONS:
        errors.append("nestingOrientation is invalid")

    machining_permission = metadata.get("machiningPermission")
    if machining_permission not in MACHINING_PERMISSIONS:
        errors.append("machiningPermission is invalid")

    edge_banding = metadata.get("edgeBanding")
    geometry_signature = metadata.get("geometrySignature")
    if not geometry_signature:
        warnings.append("geometrySignature is missing")

    if face_class == FACE_CLASS_SURFACE:
        if edge_banding is not None:
            errors.append("SURFACE face edgeBanding must be null")
    elif face_class == FACE_CLASS_EDGE:
        if edge_banding is None:
            errors.append("EDGE face must include edgeBanding")
        else:
            errors.extend(_validate_edge_banding(edge_banding))
        if nesting_orientation != NESTING_NOT_APPLICABLE:
            errors.append("EDGE face nestingOrientation must be NOT_APPLICABLE")
        if machining_permission == MACHINING_PRIMARY:
            errors.append("EDGE face cannot be PRIMARY machining face")

    return validation_result(not errors, errors, warnings)


def validate_panel_surface_mode(panel_metadata, face_metadatas):
    errors = []
    warnings = []
    surface_mode = (panel_metadata or {}).get("surfaceMode")
    if surface_mode not in SURFACE_MODES:
        errors.append("surfaceMode is invalid")
        return validation_result(False, errors, warnings)

    surfaces = [
        metadata
        for metadata in (face_metadatas or [])
        if metadata and metadata.get("faceClass") == FACE_CLASS_SURFACE
    ]
    if len(surfaces) < 2:
        warnings.append("Expected at least two SURFACE faces for surfaceMode validation")
        return validation_result(not errors, errors, warnings)

    primary_surfaces = sorted(surfaces, key=lambda item: float((item.get("geometrySignature") or {}).get("area", 0.0)), reverse=True)[:2]
    finish_ids = [_finish_id(surface) for surface in primary_surfaces]

    if surface_mode == SURFACE_MODE_SINGLE_SIDED and len(set(finish_ids)) < 2:
        errors.append("SINGLE_SIDED panel requires two different SURFACE finishes")
    if surface_mode == SURFACE_MODE_DOUBLE_SIDED and len(set(finish_ids)) > 1:
        errors.append("DOUBLE_SIDED panel requires identical SURFACE finishes")

    return validation_result(not errors, errors, warnings)


def validate_single_sided_door_defaults(face_metadatas, door_finish_id):
    errors = []
    surfaces = [
        metadata
        for metadata in (face_metadatas or [])
        if metadata and metadata.get("faceClass") == FACE_CLASS_SURFACE
    ]
    if len(surfaces) < 2:
        return validation_result(True, [], ["Not enough SURFACE faces to validate door defaults"])

    door_faces = [surface for surface in surfaces if _finish_id(surface) == str(door_finish_id)]
    white_faces = [surface for surface in surfaces if _finish_id(surface) == "white-stipple"]

    for face in door_faces:
        if face.get("nestingOrientation") != NESTING_DOWN:
            errors.append("Door colour face must default to nestingOrientation DOWN")
        if face.get("machiningPermission") != MACHINING_NOT_ALLOWED:
            errors.append("Door colour face must default to machiningPermission NOT_ALLOWED")

    for face in white_faces:
        if face.get("nestingOrientation") != NESTING_UP:
            errors.append("White Stipple face must default to nestingOrientation UP")
        if face.get("machiningPermission") != MACHINING_PRIMARY:
            errors.append("White Stipple face must default to machiningPermission PRIMARY")

    return validation_result(not errors, errors)


def validate_double_sided_door_defaults(face_metadatas, door_finish_id):
    errors = []
    surfaces = [
        metadata
        for metadata in (face_metadatas or [])
        if metadata and metadata.get("faceClass") == FACE_CLASS_SURFACE
    ]
    for face in surfaces:
        if _finish_id(face) != str(door_finish_id):
            errors.append("DOUBLE_SIDED door surfaces must share the same finishId")
        if face.get("nestingOrientation") != NESTING_EITHER:
            errors.append("DOUBLE_SIDED door surfaces must use nestingOrientation EITHER")
    return validation_result(not errors, errors)


def validate_unique_face_ids(face_metadatas):
    seen = set()
    errors = []
    for metadata in face_metadatas or []:
        face_id = str((metadata or {}).get("faceId") or "").strip().lower()
        if not face_id:
            continue
        if face_id in seen:
            errors.append("Duplicate faceId: {}".format(metadata.get("faceId")))
        seen.add(face_id)
    return validation_result(not errors, errors)
