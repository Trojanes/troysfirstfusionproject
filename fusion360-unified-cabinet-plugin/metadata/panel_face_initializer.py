import copy

from face_geometry_signature import build_geometry_signature
from face_metadata_service import FaceMetadataService
from face_models import (
    BANDING_CODE_NONE,
    FACE_CLASS_EDGE,
    FACE_CLASS_SURFACE,
    MILLING_SURFACE,
    MILLING_SURFACE_EITHER,
    NON_MILLING_SURFACE,
    SURFACE_MODE_DOUBLE_SIDED,
    SURFACE_MODE_SINGLE_SIDED,
    SURFACE_MODE_UNASSIGNED,
    build_face_registry,
    create_edge_metadata,
    generate_face_id,
    raw_core_finish,
)

OH_FACE_SKELETON_BOARD_IDS = {"BP", "T1", "T2", "T3", "T4"}


def is_oh_skeleton_board(board_id):
    board_id = str(board_id or "").strip()
    if not board_id:
        return False
    if board_id in OH_FACE_SKELETON_BOARD_IDS:
        return True
    if board_id.startswith("D") and board_id[1:].isdigit():
        return True
    if board_id.startswith("FP"):
        return True
    return False
DIRECTION_ALIGNMENT_DOT = 0.95
PLANE_OFFSET_TOLERANCE_MM = 0.5


def _path_value(metadata, paths):
    if not isinstance(metadata, dict):
        return ""
    for path in paths:
        cursor = metadata
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                cursor = None
                break
            cursor = cursor.get(key)
        if cursor not in (None, ""):
            return cursor
    return ""


def iter_body_faces(body):
    faces = []
    if not body:
        return faces
    try:
        for index in range(body.faces.count):
            faces.append(body.faces.item(index))
    except Exception:
        pass
    return faces


def _first_numeric(value):
    """Pull the first non-boolean number out of a scalar or tuple/list.

    Fusion's ``SurfaceEvaluator.getArea()`` returns ``(bool, area)`` while the
    test mock returns ``(area, bool, error)``; picking the first numeric handles
    both orderings.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, (tuple, list)):
        for item in value:
            number = _first_numeric(item)
            if number is not None:
                return number
    return None


def face_area_mm2(face):
    try:
        evaluator = face.evaluator
        area_cm2 = _first_numeric(evaluator.getArea())
        if area_cm2 is not None:
            return area_cm2 * 100.0
    except Exception:
        pass
    try:
        return float(face.area) * 100.0
    except Exception:
        return 0.0


def _body_bbox_center_mm(body):
    try:
        bbox = body.boundingBox
        return [
            (bbox.minPoint.x + bbox.maxPoint.x) * 5.0,
            (bbox.minPoint.y + bbox.maxPoint.y) * 5.0,
            (bbox.minPoint.z + bbox.maxPoint.z) * 5.0,
        ]
    except Exception:
        return [0.0, 0.0, 0.0]


def _face_normal(face, panel_context):
    signature = build_geometry_signature(face, panel_context)
    normal = signature.get("normalLocal") or [0.0, 0.0, 1.0]
    return [float(normal[0]), float(normal[1]), float(normal[2])]


def _face_centroid(face, panel_context):
    signature = build_geometry_signature(face, panel_context)
    centroid = signature.get("centroidLocal") or [0.0, 0.0, 0.0]
    return [float(centroid[0]), float(centroid[1]), float(centroid[2])]


SURFACE_OPPOSITE_DOT = -0.7


def classify_box_faces(body, panel_context=None):
    """Pick exactly the two broad SURFACE faces; everything else is an EDGE.

    A flat panel has exactly two broad faces (the largest pair, with opposing
    normals along the thickness axis). We always return exactly two surfaces:

    1. The largest-area face is always one of the broad faces.
    2. The second surface is the largest face whose normal opposes the first
       (anti-parallel). This correctly skips thin edge bands.
    3. If no opposing face is found (for example when normals are unavailable),
       we fall back to the second-largest face by area.

    Everything that is not one of the two chosen surfaces becomes an EDGE band.
    """
    faces = iter_body_faces(body)
    if len(faces) < 2:
        return {"surfaceFaces": [], "edgeFaces": [], "warnings": ["Body has fewer than 2 faces."]}

    face_infos = []
    for face in faces:
        face_infos.append(
            {
                "face": face,
                "area": face_area_mm2(face),
                "normal": _normalize_vector(_face_normal(face, panel_context)),
            }
        )

    face_infos.sort(key=lambda info: info["area"], reverse=True)
    primary = face_infos[0]
    ref_normal = primary["normal"]

    warnings = []
    opposite = None
    for info in face_infos[1:]:
        if _dot(info["normal"], ref_normal) <= SURFACE_OPPOSITE_DOT:
            opposite = info
            break
    if opposite is None:
        warnings.append("No opposing broad face found; using the two largest faces by area.")
        opposite = face_infos[1]

    surface_faces = [primary["face"], opposite["face"]]
    edge_faces = [
        info["face"]
        for info in face_infos
        if info["face"] is not primary["face"] and info["face"] is not opposite["face"]
    ]

    if not edge_faces:
        warnings.append("No edge-band candidate faces detected.")

    return {
        "surfaceFaces": surface_faces,
        "edgeFaces": edge_faces,
        "warnings": warnings,
        "referenceNormal": [round(value, 4) for value in ref_normal],
    }


SURFACE_PERPENDICULAR_DOT = 0.3


def _face_key(face):
    for attr in ("tempId", "entityToken"):
        try:
            value = getattr(face, attr)
            if value not in (None, ""):
                return (attr, value)
        except Exception:
            continue
    return ("id", id(face))


def _iter_collection(collection):
    items = []
    try:
        for index in range(collection.count):
            items.append(collection.item(index))
    except Exception:
        pass
    return items


def _faces_share_edge(face_a, face_b):
    """True when face_a and face_b share a BRep edge (are adjacent)."""
    key_b = _face_key(face_b)
    try:
        for edge in _iter_collection(face_a.edges):
            for neighbour in _iter_collection(edge.faces):
                if _face_key(neighbour) == key_b:
                    return True
    except Exception:
        pass
    return False


def detect_surface_milling_roles(surface_faces, edge_faces, panel_context=None):
    """Decide MILLING / NON_MILLING / EITHER for the two broad surfaces.

    A half-slot (groove cut into one broad face) leaves wall faces that touch
    only the side it opens onto, whereas a true outer edge band touches BOTH
    broad faces (it spans the full panel thickness). So a perpendicular face
    adjacent to exactly one surface marks that surface as the milled side.

    After Extrude-Cut the milled skin may split into coplanar remnants that are
    classified as EDGE. Walls often touch those remnants, so treat coplanar
    same-side EDGE faces as part of that broad side.

    Returns a list aligned to ``surface_faces``. With no half-slot on either
    side both surfaces are EITHER; with a half-slot on one side that side is
    MILLING and the opposite NON_MILLING.

    Half-slots on both sides still return complementary roles (prefer A as
    MILLING / B as NON_MILLING). Colour face (NON_MILLING) and milling face
    must never be the same role pair or the same entity.
    """
    if len(surface_faces) < 2:
        return [MILLING_SURFACE_EITHER for _ in surface_faces]

    surface_a, surface_b = surface_faces[0], surface_faces[1]
    ref_normal = _normalize_vector(_face_normal(surface_a, panel_context))
    body = None
    if isinstance(panel_context, dict):
        body = panel_context.get("body")

    def _same_side_group(reference):
        group = [reference]
        ref_n = _normalize_vector(_face_normal(reference, panel_context))
        try:
            ref_c = _face_centroid(reference, panel_context)
        except Exception:
            ref_c = None
        if ref_c is None:
            return group
        ref_offset = _dot(ref_n, ref_c)
        for face in edge_faces or []:
            normal = _normalize_vector(_face_normal(face, panel_context))
            if abs(_dot(normal, ref_n)) < 0.85:
                continue
            try:
                centroid = _face_centroid(face, panel_context)
            except Exception:
                continue
            if abs(_dot(ref_n, centroid) - ref_offset) > 0.75:
                continue
            group.append(face)
        return group

    # Optional body-wide coplanar remnants when panel_context carries the body.
    if body is not None:
        try:
            from panel_geometry import _coplanar_same_side_faces
        except Exception:
            try:
                from metadata.panel_geometry import _coplanar_same_side_faces
            except Exception:
                _coplanar_same_side_faces = None
        if callable(_coplanar_same_side_faces):
            side_a = [surface_a] + list(_coplanar_same_side_faces(body, surface_a) or [])
            side_b = [surface_b] + list(_coplanar_same_side_faces(body, surface_b) or [])
        else:
            side_a = _same_side_group(surface_a)
            side_b = _same_side_group(surface_b)
    else:
        side_a = _same_side_group(surface_a)
        side_b = _same_side_group(surface_b)

    side_a_ids = {_face_key(face) for face in side_a}
    side_b_ids = {_face_key(face) for face in side_b}

    opens_on_a = False
    opens_on_b = False
    for face in edge_faces or []:
        face_key = _face_key(face)
        if face_key in side_a_ids or face_key in side_b_ids:
            # Coplanar skin remnant — not a slot wall.
            continue
        normal = _normalize_vector(_face_normal(face, panel_context))
        if abs(_dot(normal, ref_normal)) > SURFACE_PERPENDICULAR_DOT:
            # Parallel-ish faces (groove floors / steps) are not slot walls.
            continue
        adj_a = any(_faces_share_edge(face, candidate) for candidate in side_a)
        adj_b = any(_faces_share_edge(face, candidate) for candidate in side_b)
        if adj_a and adj_b:
            # Spans full thickness -> genuine outer edge band, not a half-slot.
            continue
        if adj_a:
            opens_on_a = True
        elif adj_b:
            opens_on_b = True

    if opens_on_a and opens_on_b:
        # Never MILLING/MILLING: colour face must remain the opposite side.
        return [MILLING_SURFACE, NON_MILLING_SURFACE]
    if opens_on_a:
        return [MILLING_SURFACE, NON_MILLING_SURFACE]
    if opens_on_b:
        return [NON_MILLING_SURFACE, MILLING_SURFACE]
    return [MILLING_SURFACE_EITHER, MILLING_SURFACE_EITHER]


def _normalize_vector(vector):
    values = [float(vector[0]), float(vector[1]), float(vector[2])]
    length = sum(value * value for value in values) ** 0.5
    if length <= 1e-9:
        return [0.0, 0.0, 1.0]
    return [value / length for value in values]


def _dot(left, right):
    return sum(float(left[index]) * float(right[index]) for index in range(3))


def _direction_bucket(normal):
    unit = _normalize_vector(normal)
    axis_labels = ("X", "Y", "Z")
    best_axis = 0
    best_abs = abs(unit[0])
    for index in range(1, 3):
        axis_abs = abs(unit[index])
        if axis_abs > best_abs:
            best_abs = axis_abs
            best_axis = index
    if best_abs >= DIRECTION_ALIGNMENT_DOT:
        sign = "+" if unit[best_axis] >= 0 else "-"
        return "{}{}".format(sign, axis_labels[best_axis])
    rounded = tuple(round(value, 2) for value in unit)
    return "N:{}:{}:{}".format(*rounded)


def _plane_offset_mm(normal, centroid):
    unit = _normalize_vector(normal)
    return round(_dot(unit, centroid), 3)


def edge_role_from_direction(direction_bucket, centroid, body):
    bucket = str(direction_bucket or "")
    if bucket == "+X":
        return "edge_right"
    if bucket == "-X":
        return "edge_left"
    if bucket == "+Y":
        return "edge_front"
    if bucket == "-Y":
        return "edge_back"
    if bucket == "+Z":
        return "edge_top"
    if bucket == "-Z":
        return "edge_bottom"

    # Non-axis-aligned buckets fall back to centroid hints.
    center = _body_bbox_center_mm(body)
    axis, _component = _dominant_axis_component(_normalize_vector(centroid))
    delta = float(centroid[axis]) - float(center[axis])
    if axis == 0:
        return "edge_right" if delta >= 0 else "edge_left"
    if axis == 1:
        return "edge_front" if delta >= 0 else "edge_back"
    return "edge_top" if delta >= 0 else "edge_bottom"


def list_all_edge_faces(edge_faces, panel_context=None):
    """Enumerate every edge-band candidate face without semantic grouping.

    Classification (direction, coplanar merge, edge_top/right, etc.) is deferred.
    Each physical face becomes one registry edge with geometry hints attached.
    """
    ranked = sorted(edge_faces or [], key=face_area_mm2, reverse=True)
    entries = []
    for index, face in enumerate(ranked):
        normal = _face_normal(face, panel_context)
        centroid = _face_centroid(face, panel_context)
        sequence = index + 1
        edge_id = "EDGE-{:02d}".format(sequence)
        entries.append(
            {
                "edgeId": edge_id,
                "edgeRole": "edge_{:02d}".format(sequence),
                "faceRole": "edge_unclassified",
                "classificationStatus": "unclassified",
                "face": face,
                "areaMm2": round(face_area_mm2(face), 3),
                "normalLocal": normal,
                "centroidLocal": centroid,
                "directionHint": _direction_bucket(normal),
                "planeOffsetMm": _plane_offset_mm(normal, centroid),
            }
        )
    return entries


def group_edge_faces(edge_faces, body, panel_context=None):
    """Deferred: logical edge grouping will be implemented later."""
    return list_all_edge_faces(edge_faces, panel_context)


def _outer_loop_edge_keys(face):
    keys = set()
    try:
        for loop in _iter_collection(face.loops):
            try:
                is_outer = bool(loop.isOuter)
            except Exception:
                is_outer = True
            if not is_outer:
                continue
            for coedge in _iter_collection(loop.coEdges):
                try:
                    keys.add(_face_key(coedge.edge))
                except Exception:
                    continue
    except Exception:
        pass
    return keys


def _face_touches_keys(face, edge_keys):
    if not edge_keys:
        return False
    try:
        for edge in _iter_collection(face.edges):
            if _face_key(edge) in edge_keys:
                return True
    except Exception:
        pass
    return False


def split_true_edges_and_feature_faces(surface_faces, edge_faces):
    """Separate real perimeter edge-band faces from internal feature faces.

    A true edge band spans the full panel thickness, so it shares boundary edges
    with the OUTER loop of BOTH broad surfaces. Everything else (groove walls and
    floors, hole/cylinder walls, chamfers, blind-pocket walls) is an internal
    feature face and is grouped separately so it can be used later if needed.
    """
    if len(surface_faces) < 2:
        return list(edge_faces or []), []
    outer_a = _outer_loop_edge_keys(surface_faces[0])
    outer_b = _outer_loop_edge_keys(surface_faces[1])
    if not outer_a or not outer_b:
        # Loop data unavailable -> keep current behaviour (treat all as edges).
        return list(edge_faces or []), []
    true_edges = []
    feature_faces = []
    for face in edge_faces or []:
        if _face_touches_keys(face, outer_a) and _face_touches_keys(face, outer_b):
            true_edges.append(face)
        else:
            feature_faces.append(face)
    return true_edges, feature_faces


EDGE_ROLE_BANDABLE = "edge_bandable"
EDGE_ROLE_NON_BANDABLE = "edge_non_bandable"
BANDABLE_TOLERANCE_MM = 1.0


def classify_edge_bandability(edge_entries, surface_normal, tolerance_mm=BANDABLE_TOLERANCE_MM):
    """Tag each true edge as bandable vs non-bandable via the bounding rectangle.

    An edge that lies on the panel's overall bounding-rectangle frame can be run
    on the edge bander; an edge set back from the frame (notch / cut-out interior)
    cannot. The 2D frame extremes are recovered from the edge centroids: a frame
    edge sits exactly at the min/max of its dominant in-plane axis, while an
    interior edge sits between them.
    """
    entries = edge_entries or []
    if not entries:
        return entries
    thickness_axis, _component = _dominant_axis_component(_normalize_vector(surface_normal))
    in_plane = [axis for axis in (0, 1, 2) if axis != thickness_axis]

    coords = {axis: [] for axis in in_plane}
    for entry in entries:
        centroid = entry.get("centroidLocal") or [0.0, 0.0, 0.0]
        for axis in in_plane:
            coords[axis].append(float(centroid[axis]))
    extremes = {axis: (min(values), max(values)) for axis, values in coords.items() if values}

    for entry in entries:
        normal = entry.get("normalLocal") or [0.0, 0.0, 1.0]
        centroid = entry.get("centroidLocal") or [0.0, 0.0, 0.0]
        dominant = in_plane[0]
        if abs(float(normal[in_plane[1]])) > abs(float(normal[in_plane[0]])):
            dominant = in_plane[1]
        lo, hi = extremes.get(dominant, (0.0, 0.0))
        coord = float(centroid[dominant])
        on_frame = abs(coord - lo) <= tolerance_mm or abs(coord - hi) <= tolerance_mm
        entry["bandable"] = bool(on_frame)
        entry["faceRole"] = EDGE_ROLE_BANDABLE if on_frame else EDGE_ROLE_NON_BANDABLE
        entry["classificationStatus"] = "classified"
    return entries


def build_edge_groups(edge_registry):
    """Merge bandable edge faces that lie on the same rectangle side into one
    logical edge.

    Manufacturing rule: one straight board edge is banded in a single continuous
    pass, so every coplanar/collinear face on that side shares ONE banding strip
    (one colour/material). Faces are grouped by their outward direction (a frame
    side maps to a single direction such as +X), and each group carries a single
    banding colour. Non-bandable edges (notch interiors) are not grouped.
    """
    by_key = {}
    order = []
    for item in edge_registry or []:
        if not item.get("bandable"):
            item["edgeGroupId"] = None
            continue
        key = item.get("directionHint") or "unknown"
        if key not in by_key:
            by_key[key] = {
                "edgeGroupId": None,
                "side": key,
                "directionHint": key,
                "bandable": True,
                "bandingRequired": False,
                "bandingColor": "raw-core",
                "bandingFinishName": "Raw Core",
                "edgeIds": [],
                "faceIds": [],
                "entityTokens": [],
                "areaMm2": 0.0,
            }
            order.append(key)
        group = by_key[key]
        if item.get("edgeId"):
            group["edgeIds"].append(item.get("edgeId"))
        if item.get("faceId"):
            group["faceIds"].append(item.get("faceId"))
        if item.get("entityToken"):
            group["entityTokens"].append(item.get("entityToken"))
        group["areaMm2"] += float(item.get("areaMm2") or 0.0)

    groups = []
    for index, key in enumerate(order):
        group = by_key[key]
        group["edgeGroupId"] = "EG-{:02d}".format(index + 1)
        group["memberCount"] = len(group["edgeIds"])
        group["areaMm2"] = round(group["areaMm2"], 3)
        groups.append(group)

    for item in edge_registry or []:
        if item.get("bandable"):
            item["edgeGroupId"] = by_key[item.get("directionHint") or "unknown"]["edgeGroupId"]
    return groups


def validate_edge_group_banding(edge_groups, face_banding_by_id):
    """Same-side rule: every face in a logical edge must use one banding colour.

    ``face_banding_by_id`` maps faceId -> banding colour. Returns a list of
    violation messages for groups whose members carry more than one colour
    (physically impossible on the edge bander).
    """
    violations = []
    for group in edge_groups or []:
        colours = set()
        for face_id in group.get("faceIds") or []:
            colour = face_banding_by_id.get(face_id)
            if colour:
                colours.add(str(colour))
        if len(colours) > 1:
            violations.append(
                "Edge {} spans one board edge but has mixed banding colours {}; "
                "a single edge can only carry one colour.".format(
                    group.get("edgeGroupId") or group.get("side"), sorted(colours)
                )
            )
    return violations


def list_feature_faces(feature_faces, panel_context=None):
    """Enumerate internal feature faces as a separate, unclassified group."""
    ranked = sorted(feature_faces or [], key=face_area_mm2, reverse=True)
    entries = []
    for index, face in enumerate(ranked):
        normal = _face_normal(face, panel_context)
        centroid = _face_centroid(face, panel_context)
        sequence = index + 1
        entries.append(
            {
                "featureFaceId": "FF-{:02d}".format(sequence),
                "faceRole": "feature_unclassified",
                "classificationStatus": "unclassified",
                "face": face,
                "entityToken": _entity_token(face),
                "areaMm2": round(face_area_mm2(face), 3),
                "normalLocal": normal,
                "centroidLocal": centroid,
                "directionHint": _direction_bucket(normal),
                "planeOffsetMm": _plane_offset_mm(normal, centroid),
            }
        )
    return entries


def _dominant_axis_component(vector):
    if not vector:
        return 2, 0.0
    abs_values = [abs(float(vector[0])), abs(float(vector[1])), abs(float(vector[2]))]
    axis = abs_values.index(max(abs_values))
    return axis, float(vector[axis])


def edge_role_from_geometry(face, body, panel_context=None):
    normal = _face_normal(face, panel_context)
    centroid = _face_centroid(face, panel_context)
    return edge_role_from_direction(_direction_bucket(normal), centroid, body)


def surface_roles_for_board(board_id, surface_faces):
    board_id = str(board_id or "")
    count = len(surface_faces or [])
    if count < 1:
        return []
    role_map = {
        "BP": ("carcass_bottom_outer", "carcass_bottom_inner"),
        "T1": ("door_front_visible", "door_back_hidden"),
        "T2": ("carcass_rail_outer", "carcass_rail_inner"),
        "T3": ("carcass_rear_outer", "carcass_rear_inner"),
        "T4": ("carcass_front_outer", "carcass_front_inner"),
    }
    if board_id in role_map:
        base = list(role_map[board_id])
    elif board_id.startswith("D"):
        base = ["divider_outer", "divider_inner"]
    elif board_id.startswith("FP"):
        base = ["door_outer", "door_inner"]
    else:
        base = ["surface_primary", "surface_secondary"]

    roles = []
    for index in range(count):
        if index < len(base):
            roles.append(base[index])
        else:
            roles.append("{}_{:02d}".format(base[-1], index + 1))
    return roles


def surface_mode_for_board(board_id, panel_metadata=None):
    board_id = str(board_id or "")
    material_class = str(
        _path_value(panel_metadata or {}, [["defaultAttributes", "materialClass"], ["materialClass"]]) or ""
    )
    if material_class == "door_board" or board_id == "T1" or board_id.startswith("FP"):
        return SURFACE_MODE_SINGLE_SIDED
    if is_oh_skeleton_board(board_id):
        return SURFACE_MODE_DOUBLE_SIDED
    return SURFACE_MODE_UNASSIGNED


def _panel_id_from_metadata(panel_metadata):
    return str(
        _path_value(panel_metadata, [["identity", "panelId"], ["panelId"]]) or ""
    ).strip()


def _entity_token(entity):
    try:
        return str(getattr(entity, "entityToken", "") or "")
    except Exception:
        return ""


def initialize_oh_panel_faces(body, panel_metadata, board_id, service=None):
    board_id = str(board_id or "").strip()
    result = {
        "boardId": board_id,
        "initialized": False,
        "skipped": False,
        "warnings": [],
        "surfaceCount": 0,
        "edgeCount": 0,
        "edgeGroupCount": 0,
    }
    if not is_oh_skeleton_board(board_id):
        result["skipped"] = True
        result["warnings"].append("Board {} is not part of the OHC face skeleton.".format(board_id or "unknown"))
        return panel_metadata, result

    panel_id = _panel_id_from_metadata(panel_metadata)
    if not panel_id:
        result["warnings"].append("panelId is missing; face metadata was not initialized.")
        return panel_metadata, result

    face_service = service or FaceMetadataService()
    panel_context = {
        "panelId": panel_id,
        "body": body,
        "bodyName": getattr(body, "name", "") or "",
    }
    classified = classify_box_faces(body, panel_context)
    result["warnings"].extend(classified.get("warnings") or [])
    surface_faces = classified.get("surfaceFaces") or []
    edge_faces = classified.get("edgeFaces") or []
    if not surface_faces:
        result["warnings"].append("No SURFACE faces detected for face metadata initialization.")
        return panel_metadata, result

    surface_roles = surface_roles_for_board(board_id, surface_faces)
    try:
        milling_roles = detect_surface_milling_roles(surface_faces, edge_faces, panel_context)
    except Exception as ex:
        milling_roles = [MILLING_SURFACE_EITHER for _ in surface_faces]
        result["warnings"].append("Milling-surface detection failed: {}".format(ex))
    registry_entries = []
    reference_front_face_id = None

    for index, face in enumerate(surface_faces):
        face_role = surface_roles[index] if index < len(surface_roles) else "surface_{}".format(index + 1)
        milling_role = milling_roles[index] if index < len(milling_roles) else MILLING_SURFACE_EITHER
        metadata = face_service.initialize_face_metadata(
            face,
            panel_id,
            {
                "faceClass": FACE_CLASS_SURFACE,
                "faceRole": face_role,
                "millingSurface": milling_role,
                "millingSource": "geometry",
                "millingLocked": False,
                "finish": raw_core_finish(),
                "machiningPermission": "ALLOWED",
            },
            panel_context=panel_context,
        )
        if index == 0:
            reference_front_face_id = metadata.get("faceId")
        registry_entries.append(
            {
                "faceId": metadata.get("faceId"),
                "faceRole": metadata.get("faceRole") or face_role,
                "faceClass": FACE_CLASS_SURFACE,
                "millingSurface": metadata.get("millingSurface") or milling_role,
                "millingSource": metadata.get("millingSource") or "geometry",
                "millingLocked": bool(metadata.get("millingLocked", False)),
                "entityToken": _entity_token(face),
            }
        )

    true_edge_faces, feature_only_faces = split_true_edges_and_feature_faces(surface_faces, edge_faces)
    edge_entries = list_all_edge_faces(true_edge_faces, panel_context)
    classify_edge_bandability(edge_entries, _face_normal(surface_faces[0], panel_context))
    edge_registry = []

    for edge_entry in edge_entries:
        face = edge_entry.get("face")
        edge_values = create_edge_metadata(
            panel_id,
            generate_face_id(),
            {
                "required": False,
                "bandingCode": BANDING_CODE_NONE,
                "finishId": "raw-core",
                "finishName": "Raw Core",
            },
            geometry_signature=build_geometry_signature(face, panel_context),
        )
        edge_values["faceRole"] = edge_entry.get("faceRole")
        edge_values["edgeId"] = edge_entry.get("edgeId")
        edge_values["classificationStatus"] = edge_entry.get("classificationStatus")
        metadata = face_service.initialize_face_metadata(
            face,
            panel_id,
            edge_values,
            panel_context=panel_context,
        )
        face_id = metadata.get("faceId")
        registry_entries.append(
            {
                "faceId": face_id,
                "faceRole": metadata.get("faceRole") or edge_entry.get("faceRole"),
                "faceClass": FACE_CLASS_EDGE,
                "entityToken": _entity_token(face),
                "edgeId": edge_entry.get("edgeId"),
            }
        )
        edge_registry.append(
            {
                "edgeId": edge_entry.get("edgeId"),
                "edgeRole": edge_entry.get("edgeRole"),
                "faceRole": edge_entry.get("faceRole"),
                "bandable": edge_entry.get("bandable"),
                "classificationStatus": edge_entry.get("classificationStatus"),
                "faceId": face_id,
                "entityToken": _entity_token(face),
                "areaMm2": edge_entry.get("areaMm2"),
                "directionHint": edge_entry.get("directionHint"),
                "planeOffsetMm": edge_entry.get("planeOffsetMm"),
                "normalLocal": edge_entry.get("normalLocal"),
                "centroidLocal": edge_entry.get("centroidLocal"),
            }
        )

    edge_groups = build_edge_groups(edge_registry)
    group_by_face = {
        face_id: group.get("edgeGroupId")
        for group in edge_groups
        for face_id in (group.get("faceIds") or [])
    }
    for entry in registry_entries:
        if entry.get("faceClass") == FACE_CLASS_EDGE and entry.get("faceId") in group_by_face:
            entry["edgeGroupId"] = group_by_face[entry["faceId"]]

    feature_face_entries = list_feature_faces(feature_only_faces, panel_context)
    feature_face_registry = [
        {
            "featureFaceId": entry.get("featureFaceId"),
            "faceRole": entry.get("faceRole"),
            "classificationStatus": entry.get("classificationStatus"),
            "entityToken": entry.get("entityToken"),
            "areaMm2": entry.get("areaMm2"),
            "directionHint": entry.get("directionHint"),
            "planeOffsetMm": entry.get("planeOffsetMm"),
            "normalLocal": entry.get("normalLocal"),
            "centroidLocal": entry.get("centroidLocal"),
        }
        for entry in feature_face_entries
    ]

    updated = copy.deepcopy(panel_metadata)
    updated.update(
        build_face_registry(
            surface_mode_for_board(board_id, panel_metadata),
            registry_entries,
            reference_front_face_id=reference_front_face_id,
            edge_groups=edge_groups,
            edges=edge_registry,
            feature_faces=feature_face_registry,
        )
    )
    registry = updated.get("faceRegistry")
    if isinstance(registry, dict):
        registry["faceUpState"] = {
            "source": "geometry",
            "locked": False,
        }

    try:
        from panel_geometry import build_body_geometry

        geometry = build_body_geometry(body, surface_faces, milling_roles, panel_context)
        if geometry.get("dimensions"):
            updated["dimensions"] = geometry["dimensions"]
        if geometry.get("millingSurfaceSvg"):
            updated["millingSurfaceSvg"] = geometry["millingSurfaceSvg"]
        updated["features"] = geometry.get("features") or []
        if geometry.get("featureSummary"):
            updated["featureSummary"] = geometry["featureSummary"]
        result["dimensions"] = geometry.get("dimensions")
        result["featureSummary"] = geometry.get("featureSummary")
    except Exception as ex:
        result["warnings"].append("Body geometry/SVG generation failed: {}".format(ex))

    result["initialized"] = True
    result["surfaceCount"] = len(surface_faces)
    result["edgeCount"] = len(true_edge_faces)
    result["edgeGroupCount"] = len(edge_groups)
    result["bandableEdgeCount"] = sum(1 for item in edge_registry if item.get("bandable"))
    result["featureFaceCount"] = len(feature_only_faces)
    result["faceCount"] = len(registry_entries)
    return updated, result


def list_body_face_records(body, panel_metadata=None):
    panel_metadata = panel_metadata if isinstance(panel_metadata, dict) else {}
    registry = panel_metadata.get("faceRegistry") or {}
    registry_faces = {
        str(item.get("faceId") or ""): item
        for item in (registry.get("faces") or [])
        if isinstance(item, dict)
    }
    records = []
    try:
        from face_attribute_store import read_face_metadata
    except Exception:
        read_face_metadata = None

    for face in iter_body_faces(body):
        metadata = None
        error = None
        if read_face_metadata:
            metadata, error = read_face_metadata(face)
        face_id = str((metadata or {}).get("faceId") or "")
        registry_entry = registry_faces.get(face_id) or {}
        finish = (metadata or {}).get("finish") if isinstance((metadata or {}).get("finish"), dict) else {}
        edge_banding = (metadata or {}).get("edgeBanding") if isinstance((metadata or {}).get("edgeBanding"), dict) else {}
        records.append(
            {
                "faceId": face_id,
                "entityToken": _entity_token(face),
                "faceClass": str((metadata or {}).get("faceClass") or registry_entry.get("faceClass") or "unknown"),
                "faceRole": str((metadata or {}).get("faceRole") or registry_entry.get("faceRole") or "unknown"),
                "millingSurface": str(
                    (metadata or {}).get("millingSurface")
                    or registry_entry.get("millingSurface")
                    or "UNASSIGNED"
                ),
                "millingSource": str(
                    (metadata or {}).get("millingSource")
                    or registry_entry.get("millingSource")
                    or "legacy"
                ),
                "millingLocked": bool(
                    (metadata or {}).get(
                        "millingLocked",
                        registry_entry.get("millingLocked", False),
                    )
                ),
                "edgeGroupId": str((metadata or {}).get("edgeGroupId") or registry_entry.get("edgeGroupId") or ""),
                "edgeId": str((metadata or {}).get("edgeId") or registry_entry.get("edgeId") or ""),
                "classificationStatus": str(
                    (metadata or {}).get("classificationStatus")
                    or registry_entry.get("classificationStatus")
                    or ""
                ),
                "finishId": finish.get("finishId") or "",
                "finishName": finish.get("finishName") or "",
                "edgeBandingRequired": edge_banding.get("required"),
                "metadataStatus": "defined" if metadata else "missing",
                "warnings": [error] if error else [],
            }
        )
    return records
