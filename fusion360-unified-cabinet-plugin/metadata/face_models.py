import uuid

FACE_ATTRIBUTE_GROUP = "UC_FACE_METADATA"
FACE_PAYLOAD_ATTR = "payload"

FACE_METADATA_SCHEMA_VERSION = 1
PANEL_FACE_METADATA_VERSION = 1

SURFACE_MODE_SINGLE_SIDED = "SINGLE_SIDED"
SURFACE_MODE_DOUBLE_SIDED = "DOUBLE_SIDED"
SURFACE_MODE_UNASSIGNED = "UNASSIGNED"
SURFACE_MODES = {
    SURFACE_MODE_SINGLE_SIDED,
    SURFACE_MODE_DOUBLE_SIDED,
    SURFACE_MODE_UNASSIGNED,
}

FACE_CLASS_SURFACE = "SURFACE"
FACE_CLASS_EDGE = "EDGE"
FACE_CLASSES = {FACE_CLASS_SURFACE, FACE_CLASS_EDGE}

MACHINING_PRIMARY = "PRIMARY"
MACHINING_SECONDARY = "SECONDARY"
MACHINING_ALLOWED = "ALLOWED"
MACHINING_NOT_ALLOWED = "NOT_ALLOWED"
MACHINING_PERMISSIONS = {
    MACHINING_PRIMARY,
    MACHINING_SECONDARY,
    MACHINING_ALLOWED,
    MACHINING_NOT_ALLOWED,
}

# Per-SURFACE machining role. Of a body's two broad faces, the side a half-slot
# (or other machined feature) opens onto is the MILLING surface; the opposite
# side is NON_MILLING. When neither side carries a half-slot, either side may be
# the milled face, so both are EITHER.
MILLING_SURFACE = "MILLING"
NON_MILLING_SURFACE = "NON_MILLING"
MILLING_SURFACE_EITHER = "EITHER"
MILLING_SURFACE_UNASSIGNED = "UNASSIGNED"
MILLING_SURFACE_VALUES = {
    MILLING_SURFACE,
    NON_MILLING_SURFACE,
    MILLING_SURFACE_EITHER,
    MILLING_SURFACE_UNASSIGNED,
}

FINISH_UNASSIGNED_ID = "UNASSIGNED"
FINISH_RAW_CORE_ID = "raw-core"
FINISH_WHITE_STIPPLE_ID = "white-stipple"

BANDING_CODE_NONE = 0
BANDING_CODE_CARCASS = 1
BANDING_CODE_DOOR_1 = 2
BANDING_CODE_DOOR_2 = 3
VALID_BANDING_CODES = {
    BANDING_CODE_NONE,
    BANDING_CODE_CARCASS,
    BANDING_CODE_DOOR_1,
    BANDING_CODE_DOOR_2,
}


def generate_face_id():
    return "FACE-{}".format(uuid.uuid4().hex[:8].upper())


def unassigned_finish():
    return {"finishId": FINISH_UNASSIGNED_ID, "finishName": "Unassigned"}


def raw_core_finish():
    return {"finishId": FINISH_RAW_CORE_ID, "finishName": "Raw Core"}


def white_stipple_finish():
    return {"finishId": FINISH_WHITE_STIPPLE_ID, "finishName": "White Stipple"}


def door_colour_finish(finish_id, finish_name):
    return {
        "finishId": str(finish_id or FINISH_UNASSIGNED_ID),
        "finishName": str(finish_name or "Selected Door Colour"),
    }


def empty_geometry_signature():
    return {
        "surfaceType": "UNKNOWN",
        "area": 0.0,
        "perimeter": 0.0,
        "centroidLocal": [0.0, 0.0, 0.0],
        "normalLocal": [0.0, 0.0, 1.0],
        "edgeCount": 0,
    }


def create_base_face_metadata(panel_id, face_id, face_class, geometry_signature=None):
    metadata = {
        "schemaVersion": FACE_METADATA_SCHEMA_VERSION,
        "panelId": str(panel_id),
        "faceId": str(face_id),
        "faceClass": face_class,
        "finish": unassigned_finish(),
        "machiningPermission": MACHINING_ALLOWED,
        "edgeBanding": None,
        "geometrySignature": geometry_signature or empty_geometry_signature(),
    }
    if face_class == FACE_CLASS_EDGE:
        metadata["machiningPermission"] = MACHINING_NOT_ALLOWED
        metadata["finish"] = raw_core_finish()
        metadata["edgeBanding"] = {
            "required": False,
            "bandingCode": BANDING_CODE_NONE,
            "finishId": FINISH_UNASSIGNED_ID,
            "finishName": "Unassigned",
        }
    return metadata


def create_surface_metadata(
    panel_id,
    face_id,
    finish,
    machining_permission,
    geometry_signature=None,
):
    metadata = create_base_face_metadata(
        panel_id,
        face_id,
        FACE_CLASS_SURFACE,
        geometry_signature=geometry_signature,
    )
    metadata["finish"] = dict(finish or unassigned_finish())
    metadata["machiningPermission"] = machining_permission
    metadata["edgeBanding"] = None
    return metadata


def create_edge_metadata(
    panel_id,
    face_id,
    edge_banding,
    geometry_signature=None,
    finish=None,
):
    metadata = create_base_face_metadata(
        panel_id,
        face_id,
        FACE_CLASS_EDGE,
        geometry_signature=geometry_signature,
    )
    metadata["finish"] = dict(finish or raw_core_finish())
    metadata["edgeBanding"] = dict(edge_banding or _default_edge_banding(False))
    return metadata


def _default_edge_banding(required):
    return {
        "required": bool(required),
        "bandingCode": BANDING_CODE_NONE if not required else BANDING_CODE_CARCASS,
        "finishId": FINISH_UNASSIGNED_ID,
        "finishName": "Unassigned",
    }


def default_single_sided_door_door_colour_surface(panel_id, face_id, door_finish, geometry_signature=None):
    return create_surface_metadata(
        panel_id,
        face_id,
        door_colour_finish(door_finish.get("finishId"), door_finish.get("finishName")),
        MACHINING_NOT_ALLOWED,
        geometry_signature=geometry_signature,
    )


def default_single_sided_door_white_stipple_surface(panel_id, face_id, geometry_signature=None):
    return create_surface_metadata(
        panel_id,
        face_id,
        white_stipple_finish(),
        MACHINING_PRIMARY,
        geometry_signature=geometry_signature,
    )


def default_double_sided_door_surface(panel_id, face_id, door_finish, geometry_signature=None):
    return create_surface_metadata(
        panel_id,
        face_id,
        door_colour_finish(door_finish.get("finishId"), door_finish.get("finishName")),
        MACHINING_ALLOWED,
        geometry_signature=geometry_signature,
    )


def default_carcass_surface(panel_id, face_id, finish=None, geometry_signature=None):
    return create_surface_metadata(
        panel_id,
        face_id,
        finish or unassigned_finish(),
        MACHINING_ALLOWED,
        geometry_signature=geometry_signature,
    )


def panel_face_registry_fields(surface_mode=SURFACE_MODE_UNASSIGNED, face_ids=None):
    return {
        "surfaceMode": surface_mode,
        "faceMetadataVersion": PANEL_FACE_METADATA_VERSION,
        "faceIds": list(face_ids or []),
    }


def merge_panel_face_registry(panel_metadata, surface_mode=None, face_ids=None):
    merged = dict(panel_metadata or {})
    if surface_mode is not None:
        merged["surfaceMode"] = surface_mode
    if face_ids is not None:
        merged["faceIds"] = list(face_ids)
    if "faceMetadataVersion" not in merged:
        merged["faceMetadataVersion"] = PANEL_FACE_METADATA_VERSION
    return merged


def build_face_registry(surface_mode, face_entries, reference_front_face_id=None, edge_groups=None, edges=None, feature_faces=None):
    entries = []
    for item in face_entries or []:
        if not isinstance(item, dict):
            continue
        face_id = str(item.get("faceId") or "").strip()
        if not face_id:
            continue
        entry = {
            "faceId": face_id,
            "faceRole": str(item.get("faceRole") or "unknown"),
            "faceClass": str(item.get("faceClass") or FACE_CLASS_SURFACE),
            "entityToken": str(item.get("entityToken") or ""),
        }
        milling_surface = str(item.get("millingSurface") or "").strip()
        if milling_surface:
            entry["millingSurface"] = milling_surface
        edge_id = str(item.get("edgeId") or "").strip()
        if edge_id:
            entry["edgeId"] = edge_id
        edge_group_id = str(item.get("edgeGroupId") or "").strip()
        if edge_group_id:
            entry["edgeGroupId"] = edge_group_id
        entries.append(entry)
    edge_list = list(edges or [])
    registry = {
        "surfaceMode": surface_mode or SURFACE_MODE_UNASSIGNED,
        "faceMetadataVersion": PANEL_FACE_METADATA_VERSION,
        "referenceFrontFaceId": str(reference_front_face_id or "") or None,
        "faces": entries,
        "faceIds": [item["faceId"] for item in entries],
        "edges": edge_list,
        "edgeGroups": list(edge_groups or []),
        "featureFaces": list(feature_faces or []),
    }
    return {"faceRegistry": registry}
