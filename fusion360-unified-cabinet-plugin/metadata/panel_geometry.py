"""Body-level geometry: dimensions, milling-surface SVG and feature classification.

This module derives, for an OHC panel body:

* ``dimensions`` - length x width x thickness (mm), rotation invariant because it
  is computed from body-local geometry rather than the world bounding box.
* ``millingSurfaceSvg`` - a 2D SVG of the milling surface (outer outline plus the
  inner feature openings on that face). Each outer-loop edge is emitted as its own
  ``<path>`` element with a geometry signature so it can later be bound to the
  matching EDGE face.
* ``features`` - internal features classified as HALF (blind: half-slot, hinge
  cup, pocket) vs FULL (through cut), stored structurally for later nesting.

All Fusion-touching helpers are defensive: any failure degrades to a bounding-box
rectangle / empty feature list and never blocks face initialization.
"""

try:
    import adsk.core
except ImportError:  # pragma: no cover - only present inside Fusion
    adsk = None

try:
    # Body-attached frame: the SAME frame used by face geometry signatures, so
    # outline points, feature coordinates and edge directionHints all live in
    # one canonical 2D space (rigid-move invariant).
    from face_geometry_signature import (
        express_point_in_frame,
        express_vector_in_frame,
        resolve_body_frame,
    )
except ImportError:  # pragma: no cover - standalone usage
    express_point_in_frame = None
    express_vector_in_frame = None
    resolve_body_frame = None

CUT_TYPE_HALF = "HALF"
CUT_TYPE_FULL = "FULL"

FEATURE_KIND_HOLE = "hole"
FEATURE_KIND_GROOVE = "groove"
FEATURE_KIND_POCKET = "pocket"
FEATURE_KIND_UNKNOWN = "unknown"

STROKE_TOLERANCE_CM = 0.01  # 0.1 mm
PARALLEL_DOT = 0.85
PERPENDICULAR_DOT = 0.3
CENTROID_MATCH_MM = 2.0


# ---------------------------------------------------------------------------
# Pure helpers (no Fusion dependency) - unit tested
# ---------------------------------------------------------------------------

def normalize_vector(vector):
    values = [float(vector[0]), float(vector[1]), float(vector[2])]
    length = sum(value * value for value in values) ** 0.5
    if length <= 1e-9:
        return [0.0, 0.0, 1.0]
    return [value / length for value in values]


def dot3(left, right):
    return sum(float(left[index]) * float(right[index]) for index in range(3))


def thickness_axis_from_normal(normal):
    unit = normalize_vector(normal)
    abs_values = [abs(unit[0]), abs(unit[1]), abs(unit[2])]
    return abs_values.index(max(abs_values))


def plane_axes_for(thickness_axis):
    """Return the two in-plane axis indices (ascending) for a thickness axis."""
    return [index for index in (0, 1, 2) if index != thickness_axis]


def project_local_to_2d(point_local, thickness_axis):
    axes = plane_axes_for(thickness_axis)
    return (float(point_local[axes[0]]), float(point_local[axes[1]]))


def bounds_of(point_lists):
    xs = []
    ys = []
    for points in point_lists:
        for (x, y) in points:
            xs.append(x)
            ys.append(y)
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


def _fmt(value):
    return ("{:.3f}".format(float(value))).rstrip("0").rstrip(".")


def _shift_flip(points, min_x, min_y, height):
    """Translate to origin and flip Y so the SVG is not mirrored vertically."""
    shifted = []
    for (x, y) in points:
        shifted.append((x - min_x, height - (y - min_y)))
    return shifted


def polyline_to_path(points, close=True):
    if not points:
        return ""
    commands = ["M {} {}".format(_fmt(points[0][0]), _fmt(points[0][1]))]
    for (x, y) in points[1:]:
        commands.append("L {} {}".format(_fmt(x), _fmt(y)))
    if close:
        commands.append("Z")
    return " ".join(commands)


def classify_cut_type(reaches_opposite, depth_mm, thickness_mm):
    if reaches_opposite:
        return CUT_TYPE_FULL
    try:
        if thickness_mm and depth_mm and depth_mm >= float(thickness_mm) - 0.2:
            return CUT_TYPE_FULL
    except Exception:
        pass
    return CUT_TYPE_HALF


def feature_kind_from_loop(edge_count, has_arc):
    if has_arc and edge_count <= 2:
        return FEATURE_KIND_HOLE
    if edge_count == 4 and not has_arc:
        return FEATURE_KIND_GROOVE
    return FEATURE_KIND_POCKET


def build_svg_document(outer_segments, inner_features, bounds, options=None):
    """Build an SVG string and a parallel list of outer-edge segment records.

    ``outer_segments`` : list of dicts ``{points:[(x,y)..], edgeToken, signature}``
        (already in face-local 2D mm, pre-flip).
    ``inner_features`` : list of dicts ``{points:[(x,y)..], cutType, featureId,
        kind, isCircle, center:(x,y), radiusMm}`` (face-local 2D mm, pre-flip).
    """
    options = options or {}
    min_x, min_y, max_x, max_y = bounds
    width = max(max_x - min_x, 0.001)
    height = max(max_y - min_y, 0.001)

    # Use a unitless viewBox with width/height 100% so the SVG scales to fit its
    # container (mm dimensions are kept in widthMm/heightMm below). Strokes use
    # vector-effect non-scaling-stroke so lines stay visible at any zoom.
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" '
        'viewBox="0 0 {} {}" width="100%" height="100%" '
        'preserveAspectRatio="xMidYMid meet">'.format(_fmt(width), _fmt(height))
    ]

    outline_records = []
    parts.append('<g class="outline" fill="none" stroke="#202020">')
    for index, segment in enumerate(outer_segments or []):
        flipped = _shift_flip(segment.get("points") or [], min_x, min_y, height)
        path = polyline_to_path(flipped, close=False)
        token = segment.get("edgeToken") or ""
        parts.append(
            '<path class="edge" data-seg-index="{}" data-edge-token="{}" '
            'stroke-width="1" vector-effect="non-scaling-stroke" d="{}"/>'.format(
                index, _escape(token), path
            )
        )
        outline_records.append(
            {
                "segIndex": index,
                "edgeToken": token,
                "signature": segment.get("signature"),
                # Canonical face-local mm coordinates (body-attached frame,
                # pre-flip). Use THIS for nesting / downstream geometry.
                "pointsLocal": [
                    [round(x, 3), round(y, 3)] for (x, y) in (segment.get("points") or [])
                ],
                # Display-space coordinates (shifted to origin, Y flipped for
                # SVG rendering). Do NOT use for geometry work.
                "points2d": flipped,
            }
        )
    parts.append("</g>")

    feature_records = []
    parts.append('<g class="features" fill="none">')
    for feature in inner_features or []:
        cut_type = feature.get("cutType") or CUT_TYPE_HALF
        stroke = "#c0392b" if cut_type == CUT_TYPE_FULL else "#2980b9"
        dash = "" if cut_type == CUT_TYPE_FULL else ' stroke-dasharray="3 2"'
        feature_id = feature.get("featureId") or ""
        if feature.get("isCircle") and feature.get("center"):
            cx, cy = _shift_flip([feature["center"]], min_x, min_y, height)[0]
            radius = float(feature.get("radiusMm") or 0.0)
            parts.append(
                '<circle class="feature" data-feature-id="{}" data-cut-type="{}" '
                'cx="{}" cy="{}" r="{}" stroke="{}" stroke-width="1" '
                'vector-effect="non-scaling-stroke"{}/>'.format(
                    _escape(feature_id), cut_type, _fmt(cx), _fmt(cy), _fmt(radius), stroke, dash
                )
            )
        else:
            flipped = _shift_flip(feature.get("points") or [], min_x, min_y, height)
            path = polyline_to_path(flipped, close=True)
            parts.append(
                '<path class="feature" data-feature-id="{}" data-cut-type="{}" '
                'd="{}" stroke="{}" stroke-width="1" vector-effect="non-scaling-stroke"{}/>'.format(
                    _escape(feature_id), cut_type, path, stroke, dash
                )
            )
        feature_records.append(
            {
                "featureId": feature_id,
                "cutType": cut_type,
                "kind": feature.get("kind"),
                "depthMm": feature.get("depthMm"),
                "isCircle": bool(feature.get("isCircle")),
                "radiusMm": feature.get("radiusMm"),
            }
        )
    parts.append("</g>")
    parts.append("</svg>")

    return {
        "svg": "".join(parts),
        "widthMm": round(width, 3),
        "heightMm": round(height, 3),
        "viewBox": "0 0 {} {}".format(_fmt(width), _fmt(height)),
        "outline": outline_records,
        "features": feature_records,
    }


def _escape(value):
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


# ---------------------------------------------------------------------------
# Fusion BRep extraction (defensive)
# ---------------------------------------------------------------------------

def _iter_collection(collection):
    items = []
    try:
        for index in range(collection.count):
            items.append(collection.item(index))
    except Exception:
        pass
    return items


def _face_key(face):
    for attr in ("tempId", "entityToken"):
        try:
            value = getattr(face, attr)
            if value not in (None, ""):
                return (attr, value)
        except Exception:
            continue
    return ("id", id(face))


def _entity_token(entity):
    try:
        return str(getattr(entity, "entityToken", "") or "")
    except Exception:
        return ""


def _faces_share_edge(face_a, face_b):
    key_b = _face_key(face_b)
    try:
        for edge in _iter_collection(face_a.edges):
            for neighbour in _iter_collection(edge.faces):
                if _face_key(neighbour) == key_b:
                    return True
    except Exception:
        pass
    return False


def _faces_share_edge_any(face, candidates):
    for candidate in candidates or []:
        if candidate is None:
            continue
        if _faces_share_edge(face, candidate):
            return True
    return False


def _coplanar_same_side_faces(body, reference, offset_tol_mm=0.75):
    """Other body faces on the same broad side as ``reference`` (split skins)."""
    if body is None or reference is None:
        return []
    try:
        ref_normal = _face_normal_local(reference, body)
        ref_centroid = _face_centroid_local_mm(reference, body)
    except Exception:
        return []
    ref_offset = dot3(ref_normal, ref_centroid)
    ref_key = _face_key(reference)
    siblings = []
    for face in _iter_body_faces(body):
        if _face_key(face) == ref_key:
            continue
        try:
            normal = _face_normal_local(face, body)
        except Exception:
            continue
        if abs(dot3(normal, ref_normal)) < PARALLEL_DOT:
            continue
        try:
            centroid = _face_centroid_local_mm(face, body)
        except Exception:
            continue
        if abs(dot3(ref_normal, centroid) - ref_offset) > offset_tol_mm:
            continue
        siblings.append(face)
    return siblings


_BODY_FRAME_CACHE = {"key": None, "frame": None}


def _body_frame(body):
    """Cached body-attached frame (same frame as face geometry signatures)."""
    if body is None or resolve_body_frame is None:
        return None
    try:
        key = getattr(body, "entityToken", None) or id(body)
    except Exception:
        key = id(body)
    if _BODY_FRAME_CACHE["key"] == key:
        return _BODY_FRAME_CACHE["frame"]
    frame = resolve_body_frame(body)
    _BODY_FRAME_CACHE["key"] = key
    _BODY_FRAME_CACHE["frame"] = frame
    return frame


def _to_local_point_mm(point, body):
    if point is None:
        return [0.0, 0.0, 0.0]
    frame = _body_frame(body)
    if frame is not None and express_point_in_frame is not None:
        try:
            return express_point_in_frame(
                [point.x * 10.0, point.y * 10.0, point.z * 10.0], frame
            )
        except Exception:
            pass
    # Fallback: occurrence-transform local coordinates (pre-frame behaviour).
    try:
        assembly_context = getattr(body, "assemblyContext", None)
        transform = assembly_context.transform if assembly_context else None
        if transform is not None:
            inverse = transform.copy()
            inverse.invert()
            local = point.copy()
            local.transformBy(inverse)
            point = local
    except Exception:
        pass
    return [point.x * 10.0, point.y * 10.0, point.z * 10.0]


def _face_normal_local(face, body):
    try:
        evaluator = face.evaluator
        pt = face.pointOnFace
        result = evaluator.getNormalAtPoint(pt)
        normal = None
        if isinstance(result, (tuple, list)):
            normal = result[1] if len(result) == 2 else result[-1]
        else:
            normal = result
        if normal is None:
            return [0.0, 0.0, 1.0]
        frame = _body_frame(body)
        if frame is not None and express_vector_in_frame is not None:
            try:
                return normalize_vector(
                    express_vector_in_frame([normal.x, normal.y, normal.z], frame)
                )
            except Exception:
                pass
        try:
            assembly_context = getattr(body, "assemblyContext", None)
            transform = assembly_context.transform if assembly_context else None
            if transform is not None and adsk is not None:
                inverse = transform.copy()
                inverse.invert()
                vec = adsk.core.Vector3D.create(normal.x, normal.y, normal.z)
                vec.transformBy(inverse)
                normal = vec
        except Exception:
            pass
        return normalize_vector([normal.x, normal.y, normal.z])
    except Exception:
        return [0.0, 0.0, 1.0]


def _face_centroid_local_mm(face, body):
    try:
        return _to_local_point_mm(face.pointOnFace, body)
    except Exception:
        return [0.0, 0.0, 0.0]


def _sample_edge_points(edge):
    try:
        evaluator = edge.evaluator
        ext = evaluator.getParameterExtents()
        if isinstance(ext, (tuple, list)) and len(ext) >= 3:
            start_param, end_param = ext[1], ext[2]
        else:
            return []
        strokes = evaluator.getStrokes(start_param, end_param, STROKE_TOLERANCE_CM)
        if isinstance(strokes, (tuple, list)):
            points = strokes[-1]
        else:
            points = strokes
        return list(points or [])
    except Exception:
        return []


def _edge_is_circle(edge):
    try:
        geometry = edge.geometry
        object_type = str(geometry.objectType)
        if object_type.endswith("Circle3D"):
            return True, geometry
        if object_type.endswith("Arc3D"):
            return False, geometry
    except Exception:
        pass
    return False, None


def _loop_segments_2d(loop, body, thickness_axis):
    """Return ordered (points2d, edge) per coEdge for a loop, plus arc flag."""
    segments = []
    has_arc = False
    for coedge in _iter_collection(loop.coEdges):
        try:
            edge = coedge.edge
        except Exception:
            continue
        pts3d = _sample_edge_points(edge)
        if not pts3d:
            continue
        try:
            if coedge.isOpposedToEdge:
                pts3d = list(reversed(pts3d))
        except Exception:
            pass
        pts2d = [
            project_local_to_2d(_to_local_point_mm(pt, body), thickness_axis)
            for pt in pts3d
        ]
        is_circle, _geom = _edge_is_circle(edge)
        if is_circle:
            has_arc = True
        segments.append({"points": pts2d, "edge": edge, "isCircle": is_circle})
    return segments, has_arc


def _concat_points(segments):
    points = []
    for seg in segments:
        for pt in seg["points"]:
            if not points or (abs(points[-1][0] - pt[0]) > 1e-6 or abs(points[-1][1] - pt[1]) > 1e-6):
                points.append(pt)
    return points


def _circle_center_radius_2d(edge, body, thickness_axis):
    try:
        geometry = edge.geometry
        center_local = _to_local_point_mm(geometry.center, body)
        center2d = project_local_to_2d(center_local, thickness_axis)
        radius_mm = float(geometry.radius) * 10.0
        return center2d, radius_mm
    except Exception:
        return None, None


def _iter_body_faces(body):
    faces = []
    try:
        for index in range(body.faces.count):
            faces.append(body.faces.item(index))
    except Exception:
        pass
    return faces


def _polygon_area(points):
    if len(points) < 3:
        return 0.0
    area = 0.0
    for index in range(len(points)):
        x1, y1 = points[index]
        x2, y2 = points[(index + 1) % len(points)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _between(value, a, b, tol=0.3):
    lo, hi = (a, b) if a <= b else (b, a)
    return (lo + tol) < value < (hi - tol)


def _face_outer_loop_2d(face, body, thickness_axis):
    outer, _inners = _loops_of_face(face)
    if outer is None:
        return [], [], False
    segments, has_arc = _loop_segments_2d(outer, body, thickness_axis)
    return _concat_points(segments), segments, has_arc


def _circle_feature_fields(segments, body, thickness_axis):
    if len(segments) == 1 and segments[0].get("isCircle"):
        center2d, radius_mm = _circle_center_radius_2d(segments[0]["edge"], body, thickness_axis)
        if center2d is not None:
            return {"isCircle": True, "center": center2d, "radiusMm": round(radius_mm, 3), "kind": FEATURE_KIND_HOLE}
    return {"isCircle": False, "center": None, "radiusMm": None}


def _half_feature_open_surface(
    floor_face,
    floor_normal,
    floor_offset,
    surface_a,
    surface_b,
    offset_a,
    offset_b,
    axis_unit,
    debug=None,
    body=None,
):
    """Pick the broad face a blind feature opens onto.

    Prefer topology: a pocket/cup wall shares an edge with the floor and with
    exactly one broad surface — that surface is the opening. Do not use
    nearest-surface (deep hinge cups sit closer to the closed face).

    When the milled skin is split into coplanar fragments, walls often touch a
    remnant rather than the single largest SURFACE face — so also treat
    coplanar same-side faces as that opening side.

    Normal fallback: BRep face normals point out of the solid. On a pocket
    floor that is into the cavity, toward the open face. If topology cannot
    decide, use that direction.
    """
    # --- Topology (authoritative for hinge cups / blind pockets) ---
    # Use _face_key (not `is`) for identity: Fusion re-wraps faces in fresh
    # proxy objects across collection accesses, so `edge.faces` entries may
    # not be `is`-identical to floor_face/surface_a/surface_b even when they
    # are the same underlying BRepFace.
    votes_a = 0
    votes_b = 0
    side_a = [surface_a] + _coplanar_same_side_faces(body, surface_a)
    side_b = [surface_b] + _coplanar_same_side_faces(body, surface_b)
    side_a_keys = {_face_key(face) for face in side_a if face is not None}
    side_b_keys = {_face_key(face) for face in side_b if face is not None}
    try:
        floor_key = _face_key(floor_face)
        for edge in _iter_collection(floor_face.edges):
            for neighbour in _iter_collection(edge.faces):
                neighbour_key = _face_key(neighbour)
                if neighbour_key == floor_key:
                    continue
                if neighbour_key in side_a_keys or neighbour_key in side_b_keys:
                    continue
                adj_a = _faces_share_edge_any(neighbour, side_a)
                adj_b = _faces_share_edge_any(neighbour, side_b)
                if adj_a and not adj_b:
                    votes_a += 1
                elif adj_b and not adj_a:
                    votes_b += 1
    except Exception:
        pass
    if isinstance(debug, dict):
        debug["votesA"] = votes_a
        debug["votesB"] = votes_b
        debug["sideACount"] = len(side_a)
        debug["sideBCount"] = len(side_b)
    if votes_a > votes_b:
        if isinstance(debug, dict):
            debug["method"] = "topology"
        return surface_a
    if votes_b > votes_a:
        if isinstance(debug, dict):
            debug["method"] = "topology"
        return surface_b

    # --- Which broad face has an inner loop (cup mouth) ---
    try:
        _oa, inners_a = _loops_of_face(surface_a)
        _ob, inners_b = _loops_of_face(surface_b)
        if inners_a and not inners_b:
            if isinstance(debug, dict):
                debug["method"] = "inner_loop"
            return surface_a
        if inners_b and not inners_a:
            if isinstance(debug, dict):
                debug["method"] = "inner_loop"
            return surface_b
    except Exception:
        pass

    # --- Normal fallback ---
    axis_component = dot3(floor_normal, axis_unit)
    if isinstance(debug, dict):
        debug["normalAxisComponent"] = round(axis_component, 4)
    if abs(axis_component) < 1e-9:
        d_a = abs(floor_offset - offset_a)
        d_b = abs(floor_offset - offset_b)
        if isinstance(debug, dict):
            debug["method"] = "nearest_planar"
        return surface_a if d_a <= d_b else surface_b
    if isinstance(debug, dict):
        debug["method"] = "floor_normal"
    if axis_component > 0:
        return surface_a if offset_a > floor_offset else surface_b
    return surface_a if offset_a < floor_offset else surface_b


def extract_features(body, surface_a, surface_b, thickness_axis, offset_a, offset_b, thickness_mm):
    """Detect internal features and classify each as HALF (blind) or FULL (through).

    HALF features are found from their floor face (a planar face parallel to the
    broad faces whose offset lies strictly between the two surfaces). This also
    catches grooves that open to a panel edge, which never form an inner loop.
    FULL features are found from inner loops whose walls reach the opposite face.
    """
    features = []
    axis_unit = _axis_unit(thickness_axis)
    surface_keys = {_face_key(surface_a), _face_key(surface_b)}

    # HALF (blind) features: floor faces between the two broad surfaces.
    for face in _iter_body_faces(body):
        if _face_key(face) in surface_keys:
            continue
        normal = _face_normal_local(face, body)
        if abs(dot3(normal, axis_unit)) < PARALLEL_DOT:
            continue
        offset = _face_centroid_local_mm(face, body)[thickness_axis]
        if not _between(offset, offset_a, offset_b):
            continue
        points, segments, has_arc = _face_outer_loop_2d(face, body, thickness_axis)
        if len(points) < 2:
            continue
        # Prefer wall-adjacency / inner-loop topology over nearest-surface:
        # hinge cups are often deeper than half the panel.
        open_debug = {}
        open_surface = _half_feature_open_surface(
            face, normal, offset, surface_a, surface_b, offset_a, offset_b, axis_unit,
            debug=open_debug,
            body=body,
        )
        open_offset = offset_a if open_surface is surface_a else offset_b
        depth = round(abs(offset - open_offset), 3)
        feature = {
            "featureId": "",
            "cutType": CUT_TYPE_HALF,
            "kind": feature_kind_from_loop(len(segments), has_arc),
            "depthMm": depth,
            "points": points,
            "openSurfaceToken": _entity_token(open_surface),
            "openSurfaceIs": "A" if open_surface is surface_a else "B",
            "openDecision": open_debug,
            "floorOffsetMm": round(float(offset), 3),
        }
        feature.update(_circle_feature_fields(segments, body, thickness_axis))
        if not _is_duplicate_feature(feature, features):
            features.append(feature)

    # FULL (through) features: inner loops whose walls reach the opposite face.
    for face in (surface_a, surface_b):
        _outer, inner_loops = _loops_of_face(face)
        other = surface_b if face is surface_a else surface_a
        for loop in inner_loops:
            segments, has_arc = _loop_segments_2d(loop, body, thickness_axis)
            if not segments:
                continue
            reaches_opposite = False
            for seg in segments:
                edge = seg.get("edge")
                if edge is None:
                    continue
                for wall in _iter_collection(edge.faces):
                    if _face_key(wall) in surface_keys:
                        continue
                    if _faces_share_edge(wall, other):
                        reaches_opposite = True
                        break
                if reaches_opposite:
                    break
            if not reaches_opposite:
                continue
            points = _concat_points(segments)
            if len(points) < 2:
                continue
            feature = {
                "featureId": "",
                "cutType": CUT_TYPE_FULL,
                "kind": feature_kind_from_loop(len(segments), has_arc),
                "depthMm": thickness_mm,
                "points": points,
                "openSurfaceToken": _entity_token(face),
            }
            feature.update(_circle_feature_fields(segments, body, thickness_axis))
            if not _is_duplicate_feature(feature, features):
                features.append(feature)

    for index, feature in enumerate(features):
        feature["featureId"] = "FEAT-{:02d}".format(index + 1)
    return features


def _axis_unit(axis):
    unit = [0.0, 0.0, 0.0]
    unit[axis] = 1.0
    return unit


def _outer_segments_for_svg(loop, body, thickness_axis):
    segments, _has_arc = _loop_segments_2d(loop, body, thickness_axis)
    records = []
    for seg in segments:
        edge = seg.get("edge")
        records.append(
            {
                "points": seg.get("points") or [],
                "edgeToken": _entity_token(edge) if edge is not None else "",
                "signature": _segment_signature(seg, body, thickness_axis),
            }
        )
    return records, segments


def _segment_signature(seg, body, thickness_axis):
    points = seg.get("points") or []
    if not points:
        return None
    start = points[0]
    end = points[-1]
    midx = (start[0] + end[0]) / 2.0
    midy = (start[1] + end[1]) / 2.0
    length = ((end[0] - start[0]) ** 2 + (end[1] - start[1]) ** 2) ** 0.5
    return {
        "start": [round(start[0], 3), round(start[1], 3)],
        "end": [round(end[0], 3), round(end[1], 3)],
        "mid": [round(midx, 3), round(midy, 3)],
        "lengthMm": round(length, 3),
        "isCircle": bool(seg.get("isCircle")),
    }


def _loops_of_face(face):
    outer = None
    inners = []
    for loop in _iter_collection(face.loops):
        try:
            is_outer = bool(loop.isOuter)
        except Exception:
            is_outer = outer is None
        if is_outer and outer is None:
            outer = loop
        else:
            inners.append(loop)
    return outer, inners


def build_body_geometry(body, surface_faces, milling_roles, panel_context=None):
    """Compute dimensions, milling-surface SVG and classified features.

    Returns a dict suitable for merging into the body panel metadata. Never
    raises; on failure returns best-effort partial data.
    """
    result = {"dimensions": None, "millingSurfaceSvg": None, "features": []}
    try:
        if not surface_faces or len(surface_faces) < 2:
            return result
        surface_a, surface_b = surface_faces[0], surface_faces[1]
        ref_normal = _face_normal_local(surface_a, body)
        thickness_axis = thickness_axis_from_normal(ref_normal)

        offset_a = _face_centroid_local_mm(surface_a, body)[thickness_axis]
        offset_b = _face_centroid_local_mm(surface_b, body)[thickness_axis]
        thickness_mm = round(abs(offset_a - offset_b), 3)

        # Choose the milling surface (for metadata/title only): the MILLING side
        # if known, otherwise the primary (largest) surface.
        milling_index = 0
        for index, role in enumerate(milling_roles or []):
            if role == "MILLING":
                milling_index = index
                break
        milling_face = surface_faces[milling_index]

        # Footprint outline = the broad face with the larger outer-loop area, i.e.
        # the face NOT notched by edge-open grooves. Grooves are drawn as internal
        # features instead of indenting the panel silhouette.
        pts_a, _segs_a, _arc_a = _face_outer_loop_2d(surface_a, body, thickness_axis)
        pts_b, _segs_b, _arc_b = _face_outer_loop_2d(surface_b, body, thickness_axis)
        footprint_face = surface_a if _polygon_area(pts_a) >= _polygon_area(pts_b) else surface_b

        outer_loop, _inner_loops = _loops_of_face(footprint_face)
        outer_records = []
        if outer_loop is not None:
            outer_records, _outer_segments = _outer_segments_for_svg(outer_loop, body, thickness_axis)

        features = extract_features(
            body, surface_a, surface_b, thickness_axis, offset_a, offset_b, thickness_mm
        )

        outer_point_lists = [rec["points"] for rec in outer_records if rec.get("points")]
        inner_point_lists = []
        for feat in features:
            if feat.get("isCircle") and feat.get("center"):
                cx, cy = feat["center"]
                r = float(feat.get("radiusMm") or 0.0)
                inner_point_lists.append([(cx - r, cy - r), (cx + r, cy + r)])
            elif feat.get("points"):
                inner_point_lists.append(feat["points"])
        bounds = bounds_of(outer_point_lists + inner_point_lists)

        svg_doc = build_svg_document(outer_records, features, bounds)

        length_mm = svg_doc["widthMm"]
        width_mm = svg_doc["heightMm"]
        long_dim, short_dim = (length_mm, width_mm) if length_mm >= width_mm else (width_mm, length_mm)

        result["dimensions"] = {
            "lengthMm": round(long_dim, 3),
            "widthMm": round(short_dim, 3),
            "thicknessMm": thickness_mm,
        }
        svg_doc["millingFaceToken"] = _entity_token(milling_face)
        result["millingSurfaceSvg"] = svg_doc
        result["features"] = [_public_feature(f) for f in features]
        result["featureSummary"] = _feature_summary(features)
    except Exception as ex:  # pragma: no cover - defensive
        result["error"] = str(ex)
    return result


def _public_feature(feature):
    return {
        "featureId": feature.get("featureId"),
        "cutType": feature.get("cutType"),
        "kind": feature.get("kind"),
        "depthMm": feature.get("depthMm"),
        "isCircle": bool(feature.get("isCircle")),
        "radiusMm": feature.get("radiusMm"),
        "openSurfaceToken": feature.get("openSurfaceToken"),
        "center2d": list(feature.get("center")) if feature.get("center") else None,
        # Face-local mm polygon of the feature opening (same frame as the
        # outline pointsLocal). Required by CAM/nesting feature transforms.
        "pointsLocal": [
            [round(x, 3), round(y, 3)] for (x, y) in (feature.get("points") or [])
        ],
    }


def _feature_summary(features):
    summary = {"total": len(features), "half": 0, "full": 0, "byKind": {}}
    for feature in features:
        if feature.get("cutType") == CUT_TYPE_FULL:
            summary["full"] += 1
        else:
            summary["half"] += 1
        kind = feature.get("kind") or FEATURE_KIND_UNKNOWN
        summary["byKind"][kind] = summary["byKind"].get(kind, 0) + 1
    return summary


def _feature_centroid_2d(feature):
    if feature.get("center"):
        return feature["center"]
    points = feature.get("points") or []
    if not points:
        return None
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def _is_duplicate_feature(feature, existing):
    """A through feature appears on both broad faces; dedupe by centroid."""
    centroid = _feature_centroid_2d(feature)
    if centroid is None:
        return False
    for other in existing:
        other_centroid = _feature_centroid_2d(other)
        if other_centroid is None:
            continue
        if (
            abs(centroid[0] - other_centroid[0]) <= CENTROID_MATCH_MM
            and abs(centroid[1] - other_centroid[1]) <= CENTROID_MATCH_MM
        ):
            return True
    return False
