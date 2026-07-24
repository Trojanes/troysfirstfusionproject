"""Conservative Fusion BRep loop extraction for flattened nesting bodies."""

from __future__ import annotations


STROKE_TOLERANCE_CM = 0.01
Z_TOLERANCE_CM = 0.01


def _items(collection):
    if collection is None:
        return []
    try:
        return [collection.item(index) for index in range(collection.count)]
    except Exception:
        try:
            return list(collection)
        except Exception:
            return []


def _xyz(point):
    try:
        return float(point.x), float(point.y), float(point.z)
    except Exception:
        return None


def _same_point(a, b, tolerance=1e-7):
    return (
        abs(a[0] - b[0]) <= tolerance
        and abs(a[1] - b[1]) <= tolerance
        and abs(a[2] - b[2]) <= tolerance
    )


def _distance_squared(a, b):
    return sum((float(a[index]) - float(b[index])) ** 2 for index in range(3))


def _evaluator_strokes(edge):
    """Return native-edge-direction stroke points, or [] when uncertain."""
    evaluator = getattr(edge, "evaluator", None)
    if evaluator is None:
        geometry = getattr(edge, "geometry", None)
        evaluator = getattr(geometry, "evaluator", None)
    if evaluator is None:
        return []
    try:
        extents = evaluator.getParameterExtents()
        if not isinstance(extents, (tuple, list)):
            return []
        if len(extents) >= 3 and isinstance(extents[0], bool):
            if not extents[0]:
                return []
            start, end = extents[1], extents[2]
        elif len(extents) >= 2:
            start, end = extents[-2], extents[-1]
        else:
            return []
        result = evaluator.getStrokes(start, end, STROKE_TOLERANCE_CM)
        if isinstance(result, (tuple, list)) and result and isinstance(result[0], bool):
            if not result[0]:
                return []
            samples = result[1] if len(result) > 1 else []
        else:
            samples = result
        return [coords for coords in (_xyz(p) for p in samples or []) if coords]
    except Exception:
        return []


def directed_coedge_points(coedge):
    """Sample one coedge in loop direction, falling back to its vertices."""
    try:
        edge = coedge.edge
        opposed = bool(coedge.isOpposedToEdge)
    except Exception:
        return []
    points = _evaluator_strokes(edge)
    # Evaluator parameter direction is not guaranteed to match BRepEdge's
    # start/end vertices. Establish native edge direction first, then apply
    # the coedge reversal. Otherwise valid loops can become disconnected and
    # unnecessarily fall back to rectangles.
    if len(points) >= 2:
        try:
            native_start = _xyz(edge.startVertex.geometry)
            native_end = _xyz(edge.endVertex.geometry)
            if (
                native_start
                and native_end
                and _distance_squared(points[0], native_end)
                < _distance_squared(points[0], native_start)
            ):
                points.reverse()
        except Exception:
            pass
    if opposed:
        points.reverse()
    if len(points) >= 2:
        return points
    try:
        start = edge.endVertex if opposed else edge.startVertex
        end = edge.startVertex if opposed else edge.endVertex
        points = [_xyz(start.geometry), _xyz(end.geometry)]
        return [point for point in points if point]
    except Exception:
        return []


def traverse_coedge_loop(loop):
    """Walk ordered coedges and return one closed XYZ-centimetre ring."""
    ring = []
    for coedge in _items(getattr(loop, "coEdges", None)):
        segment = directed_coedge_points(coedge)
        if len(segment) < 2:
            return []
        if ring and _same_point(ring[-1], segment[0]):
            ring.extend(segment[1:])
        elif ring:
            # Never stitch a discontinuous loop: a malformed true-shape
            # polygon is less safe than the rectangle fallback.
            return []
        else:
            ring.extend(segment)
    if len(ring) < 3:
        return []
    if not _same_point(ring[0], ring[-1]):
        ring.append(ring[0])
    return ring


def _face_normal_z(face):
    geometry = getattr(face, "geometry", None)
    normal = getattr(geometry, "normal", None)
    if normal is not None:
        try:
            return float(normal.z)
        except Exception:
            pass
    evaluator = getattr(face, "evaluator", None)
    point = getattr(face, "pointOnFace", None)
    if evaluator is not None and point is not None:
        try:
            result = evaluator.getNormalAtPoint(point)
            if isinstance(result, (tuple, list)) and len(result) >= 2 and result[0]:
                return float(result[1].z)
        except Exception:
            pass
    return None


def select_largest_positive_z_face(body):
    """Select the largest planar-looking +Z broad face."""
    ranked = []
    for face in _items(getattr(body, "faces", None)):
        normal_z = _face_normal_z(face)
        if normal_z is None or normal_z < 0.7:
            continue
        try:
            area = float(face.area)
        except Exception:
            area = 0.0
        ranked.append((area, face))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def select_largest_negative_z_face(body):
    """Select the largest planar-looking -Z broad face (underside)."""
    ranked = []
    for face in _items(getattr(body, "faces", None)):
        normal_z = _face_normal_z(face)
        if normal_z is None or normal_z > -0.7:
            continue
        try:
            area = float(face.area)
        except Exception:
            area = 0.0
        ranked.append((area, face))
    if not ranked:
        return None
    ranked.sort(key=lambda item: item[0], reverse=True)
    return ranked[0][1]


def _face_area(face):
    try:
        return float(face.area)
    except Exception:
        return 0.0


def select_true_outer_face(body):
    """Broad face whose outer loop is the real panel outline.

    Edge-open grooves notch the milled face outer loop. The opposite skin
    (usually the underside) keeps the full rectangle and has larger area, so
    prefer the larger of bottom (-Z) vs top (+Z), with bottom winning ties.
    """
    bottom = select_largest_negative_z_face(body)
    top = select_largest_positive_z_face(body)
    if bottom is None:
        return top
    if top is None:
        return bottom
    if _face_area(bottom) + 1e-9 >= _face_area(top):
        return bottom
    return top


def iter_feature_floor_faces(body, outer_face=None, tolerance_cm=Z_TOLERANCE_CM):
    """Yield mid-thickness horizontal floors (grooves / pockets / hinge cups).

    Each floor is a separate enclosed feature — project one-by-one rather than
    projecting the notched milling face that opens onto the panel edge.
    """
    body_z = _bbox_z(body)
    if body_z is None:
        return
    min_z, max_z = body_z
    if max_z - min_z <= tolerance_cm * 2.0:
        return
    skip_ids = set()
    for face in (outer_face, select_largest_positive_z_face(body), select_largest_negative_z_face(body)):
        if face is None:
            continue
        try:
            skip_ids.add(face.tempId)
        except Exception:
            skip_ids.add(id(face))
    floors = []
    for face in _items(getattr(body, "faces", None)):
        try:
            face_key = face.tempId
        except Exception:
            face_key = id(face)
        if face_key in skip_ids:
            continue
        normal_z = _face_normal_z(face)
        if normal_z is None or abs(normal_z) < 0.7:
            continue
        face_z = _bbox_z(face)
        if face_z is None:
            continue
        mid_z = 0.5 * (face_z[0] + face_z[1])
        if mid_z <= min_z + tolerance_cm or mid_z >= max_z - tolerance_cm:
            continue
        floors.append((_face_area(face), face_key, face))
    floors.sort(key=lambda item: (-item[0], item[1] if isinstance(item[1], int) else 0))
    for _area, _key, face in floors:
        yield face


def _bbox_z(entity):
    try:
        bounds = entity.boundingBox
        return float(bounds.minPoint.z), float(bounds.maxPoint.z)
    except Exception:
        return None


def _edge_adjacent_faces(edge):
    return _items(getattr(edge, "faces", None))


def inner_loop_is_full_through(loop, reference_face, body, tolerance_cm=Z_TOLERANCE_CM):
    """Require every inner-loop edge wall to reach the opposite body Z extent."""
    body_z = _bbox_z(body)
    if body_z is None:
        return False
    min_z, max_z = body_z
    normal_z = _face_normal_z(reference_face)
    # Top (+Z) face → walls must reach underside. Bottom (-Z) → reach top skin.
    from_bottom = normal_z is not None and normal_z < 0.0
    coedges = _items(getattr(loop, "coEdges", None))
    if not coedges:
        return False
    for coedge in coedges:
        edge = getattr(coedge, "edge", None)
        if edge is None:
            return False
        walls = [
            face for face in _edge_adjacent_faces(edge) if face is not reference_face
        ]
        if not walls:
            return False
        reaches_opposite = False
        for wall in walls:
            wall_z = _bbox_z(wall)
            if wall_z is None:
                continue
            if from_bottom:
                if wall_z[1] >= max_z - tolerance_cm:
                    reaches_opposite = True
                    break
            elif wall_z[0] <= min_z + tolerance_cm:
                reaches_opposite = True
                break
        if not reaches_opposite:
            return False
    return True


def _ring_xy_mm(loop):
    return [[point[0] * 10.0, point[1] * 10.0] for point in traverse_coedge_loop(loop)]


def extract_flattened_rings_mm(body, include_holes=True, through_only=True):
    """Return ``(outer, holes)`` from the true outer broad face.

    Outer comes from :func:`select_true_outer_face` (underside when the milled
    face is notched by edge-open grooves). Blind floors are collected
    separately via :func:`_floor_feature_rings_mm`.
    """
    face = select_true_outer_face(body)
    if face is None:
        return [], []
    loops = _items(getattr(face, "loops", None))
    if not loops:
        return [], []
    outer_loop = None
    for loop in loops:
        try:
            if bool(loop.isOuter):
                outer_loop = loop
                break
        except Exception:
            continue
    if outer_loop is None:
        return [], []
    outer = _ring_xy_mm(outer_loop)
    if not include_holes or not outer:
        return outer, []
    holes = []
    for loop in loops:
        if loop is outer_loop:
            continue
        try:
            if bool(loop.isOuter):
                continue
        except Exception:
            pass
        is_through = inner_loop_is_full_through(loop, face, body)
        if through_only and not is_through:
            continue
        points = _ring_xy_mm(loop)
        if points:
            holes.append(
                {
                    "points": points,
                    "source": "flatBody",
                    "cutType": "FULL" if is_through else "HALF",
                }
            )
    return outer, holes


def _ring_bounds_key(points, quantum_mm=0.5):
    if not points:
        return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return (
        round(min(xs) / quantum_mm),
        round(min(ys) / quantum_mm),
        round(max(xs) / quantum_mm),
        round(max(ys) / quantum_mm),
        len(points),
    )


def _floor_feature_rings_mm(body, top_face=None, tolerance_cm=Z_TOLERANCE_CM):
    """Collect mid-thickness floor rings (blind pockets / grooves / hinge cups)."""
    del top_face  # call-site compat; floors skip both broad skins
    rings = []
    for face in iter_feature_floor_faces(body, outer_face=None, tolerance_cm=tolerance_cm):
        outer_loop = None
        for loop in _items(getattr(face, "loops", None)):
            try:
                if bool(loop.isOuter):
                    outer_loop = loop
                    break
            except Exception:
                continue
        if outer_loop is None:
            continue
        points = _ring_xy_mm(outer_loop)
        if len(points) >= 4:
            rings.append(
                {
                    "points": points,
                    "source": "flatBodyFloor",
                    "cutType": "HALF",
                }
            )
    return rings


def extract_dxf_projection_rings_mm(body):
    """Top-down rings: true outer, through/inner holes, each floor feature."""
    top_face = select_largest_positive_z_face(body)
    outer, holes = extract_flattened_rings_mm(
        body, include_holes=True, through_only=False
    )
    rings = []
    seen = set()
    if outer:
        key = _ring_bounds_key(outer)
        if key is not None:
            seen.add(key)
        rings.append(
            {
                "points": outer,
                "source": "flatBody",
                "cutType": "OUTER",
                "role": "outer",
            }
        )
    for hole in holes:
        points = hole.get("points") or []
        key = _ring_bounds_key(points)
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        rings.append(
            {
                "points": points,
                "source": hole.get("source") or "flatBody",
                "cutType": hole.get("cutType") or "HALF",
                "role": "feature",
            }
        )
    for floor in _floor_feature_rings_mm(body, top_face):
        points = floor.get("points") or []
        key = _ring_bounds_key(points)
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        rings.append(
            {
                "points": points,
                "source": floor.get("source") or "flatBodyFloor",
                "cutType": "HALF",
                "role": "feature",
            }
        )
    return rings


def extract_xy_outline_mm(body):
    """Compatibility outer-only entry point."""
    return extract_flattened_rings_mm(body, include_holes=False)[0]
