import math

from face_models import empty_geometry_signature

SIGNATURE_TOLERANCE_MM = 0.5
SIGNATURE_AREA_TOLERANCE_MM2 = 25.0
SIGNATURE_NORMAL_DOT_TOLERANCE = 0.995

try:
    import adsk.core
except ImportError:
    adsk = None


def _round_mm(value):
    return round(float(value), 3)


def _vector_from_point(point):
    if point is None:
        return [0.0, 0.0, 0.0]
    return [_round_mm(point.x * 10.0), _round_mm(point.y * 10.0), _round_mm(point.z * 10.0)]


def _normal_from_components(x, y, z):
    length = math.sqrt(x * x + y * y + z * z)
    if length <= 1e-9:
        return [0.0, 0.0, 1.0]
    return [_round_mm(x / length), _round_mm(y / length), _round_mm(z / length)]


def _normal_from_vector(vector):
    if vector is None:
        return [0.0, 0.0, 1.0]
    return _normal_from_components(vector.x, vector.y, vector.z)


def _surface_type_name(face):
    try:
        geometry = face.geometry
        if geometry is None:
            return "UNKNOWN"
        object_type = geometry.objectType
        if object_type.endswith("Plane"):
            return "PLANE"
        if object_type.endswith("Cylinder"):
            return "CYLINDER"
        if object_type.endswith("Cone"):
            return "CONE"
        if object_type.endswith("Sphere"):
            return "SPHERE"
        if object_type.endswith("Torus"):
            return "TORUS"
        if object_type.endswith("NurbsSurface"):
            return "NURBS"
        return str(object_type).split("::")[-1].upper()
    except Exception:
        return "UNKNOWN"


def _first_numeric(value):
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


def _face_area_mm2(face):
    try:
        evaluator = face.evaluator
        area_cm2 = _first_numeric(evaluator.getArea())
        if area_cm2 is not None:
            return _round_mm(area_cm2 * 100.0)
    except Exception:
        pass
    try:
        return _round_mm(float(face.area) * 100.0)
    except Exception:
        return 0.0


def _face_perimeter_mm(face):
    total = 0.0
    try:
        for loop_index in range(face.loops.count):
            loop = face.loops.item(loop_index)
            for coedge_index in range(loop.coEdges.count):
                coedge = loop.coEdges.item(coedge_index)
                edge = coedge.edge
                if edge and edge.geometry and hasattr(edge.geometry, "length"):
                    total += float(edge.geometry.length) * 10.0
    except Exception:
        pass
    return _round_mm(total)


def _face_edge_count(face):
    try:
        return int(face.edges.count)
    except Exception:
        return 0


def _transform_point_to_body_local(point, body):
    if point is None or body is None:
        return point
    try:
        assembly_context = getattr(body, "assemblyContext", None)
        transform = assembly_context.transform if assembly_context else None
        if transform is None:
            return point
        inverse = transform.copy()
        inverse.invert()
        local_point = point.copy()
        local_point.transformBy(inverse)
        return local_point
    except Exception:
        return point


def _transform_vector_to_body_local(vector, body):
    if vector is None or body is None:
        return vector
    try:
        assembly_context = getattr(body, "assemblyContext", None)
        transform = assembly_context.transform if assembly_context else None
        if transform is None or adsk is None:
            return vector
        inverse = transform.copy()
        inverse.invert()
        local_vector = adsk.core.Vector3D.create(vector.x, vector.y, vector.z)
        local_vector.transformBy(inverse)
        return local_vector
    except Exception:
        return vector


def _point_on_face(face):
    """Return a Point3D guaranteed to lie on the face.

    ``BRepFace.pointOnFace`` is reliable; the evaluator parametric helpers take a
    Point2D inside the face parametric range (not normalized 0..1), so we avoid
    them here to keep the geometry signature robust.
    """
    try:
        point = face.pointOnFace
        if point is not None:
            return point
    except Exception:
        pass
    try:
        evaluator = face.evaluator
        param_range = evaluator.parametricRange()
        mid_u = (param_range.minPoint.x + param_range.maxPoint.x) * 0.5
        mid_v = (param_range.minPoint.y + param_range.maxPoint.y) * 0.5
        if adsk is not None:
            param = adsk.core.Point2D.create(mid_u, mid_v)
            ok, point = evaluator.getPointAtParameter(param)
            if ok and point is not None:
                return point
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Body-attached reference frame (rigid-move invariant signatures)
#
# Centroid/normal are stored relative to a frame derived from the body's own
# geometry (area-weighted centroid + axes from face-normal clustering). Because
# the frame is built from the geometry itself, it travels with the body under any
# rigid motion (occurrence move, in-component move, rotation), so the stored
# coordinates stay constant and faces can be re-bound after a manual move.
# ---------------------------------------------------------------------------

FRAME_AXIS_PARALLEL_DOT = 0.9


def _vec_sub(a, b):
    return [a[0] - b[0], a[1] - b[1], a[2] - b[2]]


def _vec_dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _vec_cross(a, b):
    return [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]


def _vec_scale(a, s):
    return [a[0] * s, a[1] * s, a[2] * s]


def _vec_unit(a):
    length = (a[0] * a[0] + a[1] * a[1] + a[2] * a[2]) ** 0.5
    if length <= 1e-9:
        return [0.0, 0.0, 1.0]
    return [a[0] / length, a[1] / length, a[2] / length]


def _vec_any_perp(a):
    a = _vec_unit(a)
    ref = [1.0, 0.0, 0.0] if abs(a[0]) < 0.9 else [0.0, 1.0, 0.0]
    return _vec_unit(_vec_cross(a, ref))


def _canonical_axis_sign(axis, face_infos, origin):
    """Pick a deterministic, rigid-motion-equivariant sign for an axis.

    Uses the (area-weighted) third moment of face centroids along the axis. The
    moment is equivariant under rigid motion, so the chosen sign is consistent
    when the body is moved/rotated. For (near-)symmetric bodies the moment is ~0
    and there is genuinely no canonical sign, so we keep the cluster-representative
    orientation (also equivariant) instead of an unstable near-zero comparison.
    """
    skew = 0.0
    scale = 0.0
    for info in face_infos:
        proj = _vec_dot(_vec_sub(info["centroid"], origin), axis)
        weight = max(info.get("area", 0.0), 0.0)
        skew += (proj ** 3) * weight
        scale += abs(proj ** 3) * weight
    if scale > 0.0 and skew < -1e-6 * scale:
        return _vec_scale(axis, -1.0)
    return axis


def build_body_frame_from_faces(face_infos):
    """Build a body-attached orthonormal frame from world-space face data.

    ``face_infos`` : list of ``{"centroid": [x,y,z] mm, "normal": [x,y,z],
    "area": mm2}`` in world coordinates. Returns ``{"origin", "x", "y", "z"}`` or
    ``None`` if a frame cannot be determined.
    """
    infos = [fi for fi in (face_infos or []) if fi.get("centroid") and fi.get("normal")]
    if len(infos) < 2:
        return None
    total_area = sum(max(fi.get("area", 0.0), 0.0) for fi in infos)
    if total_area <= 1e-9:
        return None

    origin = [sum(max(fi.get("area", 0.0), 0.0) * fi["centroid"][i] for fi in infos) / total_area for i in range(3)]

    clusters = []
    for fi in infos:
        normal = _vec_unit(fi["normal"])
        placed = False
        for cluster in clusters:
            if abs(_vec_dot(cluster["axis"], normal)) >= FRAME_AXIS_PARALLEL_DOT:
                cluster["area"] += max(fi.get("area", 0.0), 0.0)
                placed = True
                break
        if not placed:
            clusters.append({"axis": normal, "area": max(fi.get("area", 0.0), 0.0)})
    clusters.sort(key=lambda cluster: cluster["area"], reverse=True)

    z = _vec_unit(clusters[0]["axis"])
    x = None
    for cluster in clusters[1:]:
        if abs(_vec_dot(cluster["axis"], z)) < FRAME_AXIS_PARALLEL_DOT:
            x = cluster["axis"]
            break
    if x is None:
        x = _vec_any_perp(z)
    x = _vec_unit(_vec_sub(x, _vec_scale(z, _vec_dot(x, z))))

    z = _canonical_axis_sign(z, infos, origin)
    x = _canonical_axis_sign(x, infos, origin)
    y = _vec_unit(_vec_cross(z, x))
    return {"origin": origin, "x": x, "y": y, "z": z}


def express_point_in_frame(point, frame):
    delta = _vec_sub(point, frame["origin"])
    return [_vec_dot(delta, frame["x"]), _vec_dot(delta, frame["y"]), _vec_dot(delta, frame["z"])]


def express_vector_in_frame(vector, frame):
    return [_vec_dot(vector, frame["x"]), _vec_dot(vector, frame["y"]), _vec_dot(vector, frame["z"])]


def _face_world_point_mm(face):
    point = _point_on_face(face)
    if point is None:
        return None
    try:
        return [point.x * 10.0, point.y * 10.0, point.z * 10.0]
    except Exception:
        return None


def _face_world_normal_vec(face):
    try:
        evaluator = face.evaluator
        point = _point_on_face(face)
        if point is None:
            return None
        result = evaluator.getNormalAtPoint(point)
        if isinstance(result, (tuple, list)):
            if len(result) == 2:
                ok, candidate = result
                normal = candidate if ok else None
            else:
                normal = result[-1]
        else:
            normal = result
        if normal is None:
            return None
        return [normal.x, normal.y, normal.z]
    except Exception:
        return None


def _collect_face_infos(body):
    infos = []
    try:
        for index in range(body.faces.count):
            face = body.faces.item(index)
            centroid = _face_world_point_mm(face)
            normal = _face_world_normal_vec(face)
            if centroid and normal:
                infos.append({"centroid": centroid, "normal": normal, "area": _face_area_mm2(face)})
    except Exception:
        pass
    return infos


def _body_of(face, panel_context):
    body = (panel_context or {}).get("body") if isinstance(panel_context, dict) else None
    if body is not None:
        return body
    try:
        return face.body
    except Exception:
        return None


def _resolve_body_frame(face, panel_context):
    body = _body_of(face, panel_context)
    if body is None:
        return None
    key = None
    try:
        key = getattr(body, "entityToken", None) or id(body)
    except Exception:
        key = id(body)
    if isinstance(panel_context, dict):
        if panel_context.get("_bodyFrame") is not None and panel_context.get("_bodyFrameKey") == key:
            return panel_context["_bodyFrame"]
    try:
        frame = build_body_frame_from_faces(_collect_face_infos(body))
    except Exception:
        frame = None
    if isinstance(panel_context, dict) and frame is not None:
        panel_context["_bodyFrame"] = frame
        panel_context["_bodyFrameKey"] = key
    return frame


def _face_centroid_local_mm(face, panel_context=None):
    frame = _resolve_body_frame(face, panel_context)
    if frame is not None:
        world = _face_world_point_mm(face)
        if world is not None:
            return [_round_mm(value) for value in express_point_in_frame(world, frame)]
    body = (panel_context or {}).get("body") if isinstance(panel_context, dict) else None
    point = _point_on_face(face)
    if point is not None:
        local_point = _transform_point_to_body_local(point, body)
        return _vector_from_point(local_point)
    return [0.0, 0.0, 0.0]


def _face_normal_local(face, panel_context=None):
    frame = _resolve_body_frame(face, panel_context)
    if frame is not None:
        world_normal = _face_world_normal_vec(face)
        if world_normal is not None:
            return _normal_from_components(*express_vector_in_frame(world_normal, frame))
    body = (panel_context or {}).get("body") if isinstance(panel_context, dict) else None
    try:
        evaluator = face.evaluator
        point = _point_on_face(face)
        normal = None
        if point is not None:
            result = evaluator.getNormalAtPoint(point)
            if isinstance(result, (tuple, list)):
                if len(result) == 2:
                    ok, candidate = result
                    normal = candidate if ok else None
                elif len(result) >= 1:
                    normal = result[-1]
            else:
                normal = result
        if normal is None:
            return [0.0, 0.0, 1.0]
        local_normal = _transform_vector_to_body_local(normal, body)
        return _normal_from_vector(local_normal)
    except Exception:
        return [0.0, 0.0, 1.0]


def build_geometry_signature(face, panel_context=None):
    if face is None:
        return empty_geometry_signature()
    return {
        "surfaceType": _surface_type_name(face),
        "area": _face_area_mm2(face),
        "perimeter": _face_perimeter_mm(face),
        "centroidLocal": _face_centroid_local_mm(face, panel_context),
        "normalLocal": _face_normal_local(face, panel_context),
        "edgeCount": _face_edge_count(face),
    }


def build_geometry_signature_from_values(
    surface_type="PLANE",
    area=0.0,
    perimeter=0.0,
    centroid_local=None,
    normal_local=None,
    edge_count=0,
):
    normal = normal_local or [0.0, 0.0, 1.0]
    return {
        "surfaceType": surface_type,
        "area": _round_mm(area),
        "perimeter": _round_mm(perimeter),
        "centroidLocal": [_round_mm(v) for v in (centroid_local or [0.0, 0.0, 0.0])],
        "normalLocal": _normal_from_components(normal[0], normal[1], normal[2]),
        "edgeCount": int(edge_count),
    }


def _centroid_distance_mm(left, right):
    if not left or not right:
        return float("inf")
    return math.sqrt(sum((float(left[i]) - float(right[i])) ** 2 for i in range(3)))


def _normal_dot(left, right):
    if not left or not right:
        return -1.0
    return sum(float(left[i]) * float(right[i]) for i in range(3))


def signature_match_score(stored, candidate):
    if not stored or not candidate:
        return 0.0
    score = 0.0
    if stored.get("surfaceType") == candidate.get("surfaceType"):
        score += 2.0
    area_delta = abs(float(stored.get("area", 0.0)) - float(candidate.get("area", 0.0)))
    if area_delta <= SIGNATURE_AREA_TOLERANCE_MM2:
        score += 2.0
    perimeter_delta = abs(float(stored.get("perimeter", 0.0)) - float(candidate.get("perimeter", 0.0)))
    if perimeter_delta <= SIGNATURE_TOLERANCE_MM:
        score += 1.0
    centroid_delta = _centroid_distance_mm(stored.get("centroidLocal"), candidate.get("centroidLocal"))
    if centroid_delta <= SIGNATURE_TOLERANCE_MM:
        score += 3.0
    normal_dot = abs(_normal_dot(stored.get("normalLocal"), candidate.get("normalLocal")))
    if normal_dot >= SIGNATURE_NORMAL_DOT_TOLERANCE:
        score += 3.0
    if int(stored.get("edgeCount", 0)) == int(candidate.get("edgeCount", 0)):
        score += 1.0
    return score


def signatures_match(stored, candidate):
    return signature_match_score(stored, candidate) >= 9.0
