"""Canonical manufacturing-orientation inspection for LAY_FLAT bodies.

Contract:

* world +Z is machining side A;
* world -Z is colour / underside B;
* HALF features may open on A only for single-sided manufacturing;
* HALF features on both sides are unsupported;
* a small edge-open lock may walk the colour BRep loop; face.area is
  the gate. The smaller skin is the rebate / 半槽. If it is −Z, flip;
  if it is +Z, pass even when floor topology votes the intact face.

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


def refine_half_orientation(half):
    """Use the smaller skin as the 半槽 side; ignore floor votes on the intact face.

    Overlay rebates shrink one broad face. Topology often still votes the
    intact remnant, so ``openSurfaceIs`` points the wrong way. A lock nick
    does not delete 10% of a skin — the area flags are the gate.

    * smaller −Z → HALF_BOTTOM (Check Faces Up flips and rewrites milling)
    * smaller +Z → HALF_TOP (already machining-up; Analyze must pass)
    """
    if not isinstance(half, dict):
        return half
    status = str(half.get("status") or "")
    if status == HALF_DOUBLE:
        return half
    refined = dict(half)
    if half.get("bottomOutlineNotched") and status in (HALF_TOP, HALF_NONE, ""):
        refined["status"] = HALF_BOTTOM
        refined["bottomHalfCount"] = max(int(half.get("bottomHalfCount") or 0), 1)
        refined["topHalfCount"] = 0
        refined["orientationOverride"] = str(
            half.get("bottomOutlineNotchReason") or "colour_outer_smaller_than_milling"
        )
        return refined
    if half.get("topOutlineNotched") and status in (HALF_BOTTOM, HALF_NONE, ""):
        refined["status"] = HALF_TOP
        refined["topHalfCount"] = max(int(half.get("topHalfCount") or 0), 1)
        refined["bottomHalfCount"] = 0
        refined["orientationOverride"] = str(
            half.get("topOutlineNotchReason") or "rebate_on_plus_z"
        )
        return refined
    return half


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
    """Fail only when the colour *skin* is a large eaten U, not a lock bite.

    Door lock / through edge-open features make the BRep colour loop walk
    into a small notch (sometimes a broken/small ring). Those rings then
    look "much smaller" than the milling outer. That is legal hardware.
    When both Fusion faces exist, their ``face.area`` is authoritative —
    a lock nicks the loop, it does not delete 10% of the colour skin.
    ``features`` is kept for callers and tests; it does not fail the gate.
    """
    _ = features
    bottom_area = _face_area(bottom_face)
    top_area = _face_area(top_face)
    if bottom_area > 1e-9 and top_area > 1e-9:
        bottom_notched = bottom_area < top_area * BOTTOM_OUTLINE_AREA_RATIO
        top_notched = top_area < bottom_area * BOTTOM_OUTLINE_AREA_RATIO
    else:
        bottom_notched = bottom_outer_more_notched(bottom_outer, top_outer)
        top_notched = bottom_outer_more_notched(top_outer, bottom_outer)
    return {
        "bottomOutlineNotched": bool(bottom_notched),
        "bottomOutlineNotchReason": (
            "colour_outer_smaller_than_milling" if bottom_notched else ""
        ),
        "bottomOutlineNotchCount": 0,
        "topOutlineNotched": bool(top_notched),
        "topOutlineNotchReason": (
            "rebate_on_plus_z" if top_notched else ""
        ),
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
    return refine_half_orientation(result)
