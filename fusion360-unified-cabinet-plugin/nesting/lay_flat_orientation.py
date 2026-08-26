"""Canonical manufacturing-orientation inspection for LAY_FLAT bodies.

Contract:

* world +Z is machining side A;
* world -Z is colour / underside B;
* HALF features may open on A only for single-sided manufacturing;
* HALF features on both sides are unsupported;
* colour / −Z outer must stay the full panel. An edge-open HALF or FULL
  that has been eaten into the underside outer (U/C bite) is a fail.
  Floor ``openSurfaceIs`` alone is not enough: a top-side groove can
  still notch the colour loop.

This module is read-only.  Role writes and geometry flips belong to the
controller transaction so a failed repair can be rolled back safely.
"""

from __future__ import annotations

try:
    from nesting.fusion_layout import _fast_broad_faces
except Exception:
    try:
        from fusion_layout import _fast_broad_faces  # type: ignore
    except Exception:
        _fast_broad_faces = None

try:
    from panel_attributes.milling_surface_propagation import face_world_plane
except Exception:
    try:
        from milling_surface_propagation import face_world_plane  # type: ignore
    except Exception:
        face_world_plane = None

try:
    from metadata.panel_geometry import (
        _face_centroid_local_mm,
        extract_features,
    )
except Exception:
    try:
        from panel_geometry import (  # type: ignore
            _face_centroid_local_mm,
            extract_features,
        )
    except Exception:
        _face_centroid_local_mm = None
        extract_features = None

try:
    from nesting.outline import close_ring, point_in_polygon, polygon_area
except Exception:
    try:
        from outline import close_ring, point_in_polygon, polygon_area  # type: ignore
    except Exception:
        close_ring = None
        point_in_polygon = None
        polygon_area = None

try:
    from nesting.brep_loops import _rings_from_broad_face
except Exception:
    try:
        from brep_loops import _rings_from_broad_face  # type: ignore
    except Exception:
        _rings_from_broad_face = None


HALF_TOP = "topHalf"
HALF_BOTTOM = "bottomHalf"
HALF_DOUBLE = "doubleSide"
HALF_NONE = "none"
BOTTOM_OUTLINE_AREA_RATIO = 0.90
FEATURE_OUTSIDE_FRACTION = 0.45
EDGE_TOLERANCE_MM = 0.75


def classify_half_openings(features):
    """Classify HALF feature openings when A=top and B=bottom."""
    top = []
    bottom = []
    unknown = []
    for feature in features or []:
        if not isinstance(feature, dict):
            continue
        cut_type = str(feature.get("cutType") or "").strip().upper()
        if cut_type == "FULL" or bool(feature.get("through")):
            continue
        if cut_type and cut_type != "HALF":
            continue
        side = str(feature.get("openSurfaceIs") or "").strip().upper()
        if side == "A":
            top.append(feature)
        elif side == "B":
            bottom.append(feature)
        else:
            unknown.append(feature)
    if top and bottom:
        status = HALF_DOUBLE
    elif bottom:
        status = HALF_BOTTOM
    elif top:
        status = HALF_TOP
    else:
        status = HALF_NONE
    return {
        "status": status,
        "topHalfCount": len(top),
        "bottomHalfCount": len(bottom),
        "unknownHalfCount": len(unknown),
        "topFeatures": top,
        "bottomFeatures": bottom,
        "unknownFeatures": unknown,
    }


def _point_to_segment_mm(point, start, end):
    px, py = float(point[0]), float(point[1])
    x0, y0 = float(start[0]), float(start[1])
    x1, y1 = float(end[0]), float(end[1])
    dx, dy = x1 - x0, y1 - y0
    length2 = dx * dx + dy * dy
    if length2 <= 1e-18:
        return ((px - x0) ** 2 + (py - y0) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / length2))
    return ((px - x0 - t * dx) ** 2 + (py - y0 - t * dy) ** 2) ** 0.5


def _on_or_inside_outer(point, outer, edge_tol_mm=EDGE_TOLERANCE_MM):
    """Boundary counts as inside so a top-side groove touching the edge passes."""
    if not callable(point_in_polygon) or not callable(close_ring):
        return False
    if point_in_polygon(point, outer):
        return True
    ring = close_ring(outer)
    if len(ring) < 4:
        return False
    for index in range(len(ring) - 1):
        if _point_to_segment_mm(point, ring[index], ring[index + 1]) <= edge_tol_mm:
            return True
    return False


def _feature_ring_points(feature):
    if not isinstance(feature, dict):
        return []
    points = feature.get("points") or feature.get("pointsLocal") or []
    return [p for p in points if p is not None and len(p) >= 2]


def _ring_centroid(points):
    if not points:
        return None
    xs = [float(p[0]) for p in points]
    ys = [float(p[1]) for p in points]
    return (sum(xs) / len(xs), sum(ys) / len(ys))


def feature_bites_outer(feature_points, outer_points, outside_fraction=FEATURE_OUTSIDE_FRACTION):
    """True when a feature mostly sits outside the face outer (U-bite)."""
    if not callable(close_ring):
        return False
    outer = close_ring(outer_points)
    ring = _feature_ring_points({"points": feature_points})
    if len(outer) < 4 or len(ring) < 2:
        return False
    samples = [(float(p[0]), float(p[1])) for p in ring]
    centroid = _ring_centroid(ring)
    if centroid is not None:
        samples.append(centroid)
    outside = sum(1 for sample in samples if not _on_or_inside_outer(sample, outer))
    return (outside / float(len(samples))) >= float(outside_fraction)


def bottom_outer_more_notched(bottom_outer, top_outer, ratio=BOTTOM_OUTLINE_AREA_RATIO):
    """True when the underside outer is materially smaller than the top outer."""
    if not callable(polygon_area):
        return False
    bottom_area = float(polygon_area(bottom_outer) or 0.0)
    top_area = float(polygon_area(top_outer) or 0.0)
    if bottom_area < 1.0 or top_area < 1.0:
        return False
    return bottom_area < top_area * float(ratio)


def _face_area(face):
    try:
        return float(face.area)
    except Exception:
        return 0.0


def classify_bottom_outline_notch(bottom_outer, top_outer, features, bottom_face=None, top_face=None):
    """Detect colour-outer bites that floor ``openSurfaceIs`` misses.

    A top-only HALF still fails when its 2D ring (or a FULL) sits in the
    bite of a notched underside outer, or when that outer is much smaller
    than the machining-face outer.
    """
    bitten = []
    for feature in features or []:
        points = _feature_ring_points(feature)
        if feature_bites_outer(points, bottom_outer):
            bitten.append(feature)
    area_notched = bottom_outer_more_notched(bottom_outer, top_outer)
    if not area_notched and bottom_face is not None and top_face is not None:
        bottom_area = _face_area(bottom_face)
        top_area = _face_area(top_face)
        if bottom_area > 1e-9 and top_area > 1e-9:
            area_notched = bottom_area < top_area * BOTTOM_OUTLINE_AREA_RATIO
    notched = bool(bitten) or bool(area_notched)
    reason = ""
    if bitten:
        reason = "feature_outside_colour_outer"
    elif area_notched:
        reason = "colour_outer_smaller_than_milling"
    return {
        "bottomOutlineNotched": notched,
        "bottomOutlineNotchReason": reason,
        "bottomOutlineNotchCount": len(bitten),
    }


def broad_faces_by_world_z(body):
    """Return broad faces ordered as top (+Z), bottom (-Z)."""
    if (
        body is None
        or not callable(_fast_broad_faces)
        or not callable(face_world_plane)
    ):
        return None
    try:
        face_a, face_b = _fast_broad_faces(body)
    except Exception:
        face_a = face_b = None
    if face_a is None or face_b is None:
        return None
    normal_a, _centroid_a = face_world_plane(face_a)
    normal_b, _centroid_b = face_world_plane(face_b)
    if not normal_a or not normal_b:
        return None
    if float(normal_a[2]) >= float(normal_b[2]):
        return {
            "topFace": face_a,
            "bottomFace": face_b,
            "topNormal": normal_a,
            "bottomNormal": normal_b,
        }
    return {
        "topFace": face_b,
        "bottomFace": face_a,
        "topNormal": normal_b,
        "bottomNormal": normal_a,
    }


def inspect_half_openings(body):
    """Extract HALF evidence in the final world-Z manufacturing frame."""
    faces = broad_faces_by_world_z(body)
    if not faces:
        return {
            "ok": False,
            "status": "unresolved",
            "reason": "broad_faces_not_found",
            "topHalfCount": 0,
            "bottomHalfCount": 0,
            "unknownHalfCount": 0,
            "rawFeatures": [],
        }
    if not callable(extract_features) or not callable(_face_centroid_local_mm):
        return {
            "ok": False,
            "status": "unresolved",
            "reason": "feature_helpers_unavailable",
            "topHalfCount": 0,
            "bottomHalfCount": 0,
            "unknownHalfCount": 0,
            "rawFeatures": [],
            **faces,
        }
    try:
        top_offset = _face_centroid_local_mm(
            faces["topFace"], body, coordinate_mode="world"
        )[2]
        bottom_offset = _face_centroid_local_mm(
            faces["bottomFace"], body, coordinate_mode="world"
        )[2]
        thickness = abs(float(top_offset) - float(bottom_offset))
        raw = extract_features(
            body,
            faces["topFace"],
            faces["bottomFace"],
            2,
            top_offset,
            bottom_offset,
            thickness,
            coordinate_mode="world",
        ) or []
    except Exception as ex:
        return {
            "ok": False,
            "status": "unresolved",
            "reason": "feature_extract_failed:{}".format(ex),
            "topHalfCount": 0,
            "bottomHalfCount": 0,
            "unknownHalfCount": 0,
            "rawFeatures": [],
            **faces,
        }
    result = classify_half_openings(raw)
    bottom_outer = []
    top_outer = []
    if callable(_rings_from_broad_face):
        try:
            bottom_outer, _ = _rings_from_broad_face(
                faces["bottomFace"], body, include_holes=False, through_only=True
            )
        except Exception:
            bottom_outer = []
        try:
            top_outer, _ = _rings_from_broad_face(
                faces["topFace"], body, include_holes=False, through_only=True
            )
        except Exception:
            top_outer = []
    notch = classify_bottom_outline_notch(
        bottom_outer,
        top_outer,
        raw,
        bottom_face=faces.get("bottomFace"),
        top_face=faces.get("topFace"),
    )
    result.update(
        {
            "ok": not result.get("unknownHalfCount"),
            "reason": (
                ""
                if not result.get("unknownHalfCount")
                else "feature_face_unresolved"
            ),
            "rawFeatures": raw,
            "topOffsetMm": float(top_offset),
            "bottomOffsetMm": float(bottom_offset),
            "thicknessMm": float(thickness),
            **notch,
            **faces,
        }
    )
    return result
