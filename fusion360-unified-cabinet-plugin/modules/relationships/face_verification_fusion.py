"""Fusion helpers for M5 face verification."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

try:
    import adsk.core as adsk_core
except Exception:
    adsk_core = None

from face_verification import extract_axis_aligned_faces_from_panel

# Skip near-axis-aligned filter below this |normal| component dominance.
_AXIS_ALIGN_MIN = 0.99


def _normalize_vector(vec) -> Optional[List[float]]:
    if vec is None:
        return None
    try:
        x, y, z = float(vec.x), float(vec.y), float(vec.z)
    except Exception:
        try:
            x, y, z = float(vec[0]), float(vec[1]), float(vec[2])
        except Exception:
            return None
    mag = (x * x + y * y + z * z) ** 0.5
    if mag <= 1e-9:
        return None
    return [x / mag, y / mag, z / mag]


def _face_world_point_mm(face) -> Optional[List[float]]:
    try:
        pt = face.pointOnFace
        return [pt.x * 10.0, pt.y * 10.0, pt.z * 10.0]
    except Exception:
        return None


def _face_world_normal(face) -> Optional[List[float]]:
    try:
        evaluator = face.evaluator
        pt = face.pointOnFace
        result = evaluator.getNormalAtPoint(pt)
        normal = result[1] if isinstance(result, (tuple, list)) and len(result) == 2 else result
        return _normalize_vector(normal)
    except Exception:
        return None


def _face_area_mm2(face) -> float:
    try:
        props = face.areaProperties(adsk_core.CalculationAccuracy.MediumCalculationAccuracy)
        return float(props.area) * 100.0
    except Exception:
        return 0.0


def _classify_brep_face(normal: List[float], thickness_axis: str) -> str:
    comps = [("X", abs(normal[0])), ("Y", abs(normal[1])), ("Z", abs(normal[2]))]
    axis = max(comps, key=lambda item: item[1])[0]
    if thickness_axis in ("X", "Y", "Z") and axis == thickness_axis:
        return "SURFACE"
    return "EDGE"


def _is_axis_aligned_normal(normal: List[float]) -> bool:
    return max(abs(normal[0]), abs(normal[1]), abs(normal[2])) >= _AXIS_ALIGN_MIN


def bounds_mm_from_points(points_mm: List[Tuple[float, float, float]]) -> Optional[Dict[str, float]]:
    """AABB in mm from sampled world points. Pure helper for offline tests."""
    if not points_mm:
        return None
    xs = [float(p[0]) for p in points_mm]
    ys = [float(p[1]) for p in points_mm]
    zs = [float(p[2]) for p in points_mm]
    return {
        "x0": min(xs),
        "x1": max(xs),
        "y0": min(ys),
        "y1": max(ys),
        "z0": min(zs),
        "z1": max(zs),
    }


def clamp_bounds_to_panel(bounds: Dict[str, float], panel_bbox: Optional[Dict[str, Any]]) -> Dict[str, float]:
    """Intersect face AABB with panel bbox when available."""
    if not panel_bbox:
        return dict(bounds)
    out = dict(bounds)
    for axis in ("x", "y", "z"):
        lo_key = "{}0".format(axis)
        hi_key = "{}1".format(axis)
        if lo_key not in panel_bbox or hi_key not in panel_bbox:
            continue
        out[lo_key] = max(float(out[lo_key]), float(panel_bbox[lo_key]))
        out[hi_key] = min(float(out[hi_key]), float(panel_bbox[hi_key]))
        if out[lo_key] > out[hi_key]:
            # Degenerate after clamp — keep original axis span.
            out[lo_key] = float(bounds[lo_key])
            out[hi_key] = float(bounds[hi_key])
    return out


def select_face_bound_points(
    outer_loop_vertices_mm: List[Tuple[float, float, float]],
    edge_sample_points_mm: List[Tuple[float, float, float]],
) -> Tuple[List[Tuple[float, float, float]], str]:
    """Prefer outer-loop vertices (exact endpoints); fall back to edge samples.

    Offline-pure helper so v1.2 selection is unit-testable without Fusion.
    """
    if len(outer_loop_vertices_mm) >= 3:
        return list(outer_loop_vertices_mm), "outer_loop_vertices"
    if edge_sample_points_mm:
        return list(edge_sample_points_mm), "edge_sample_aabb"
    return [], "none"


def _point3d_to_mm(pt) -> Optional[Tuple[float, float, float]]:
    try:
        return (float(pt.x) * 10.0, float(pt.y) * 10.0, float(pt.z) * 10.0)
    except Exception:
        return None


def _outer_loop_vertex_points_mm(face) -> List[Tuple[float, float, float]]:
    """Collect unique outer-loop edge endpoint vertices in world mm."""
    points: List[Tuple[float, float, float]] = []
    seen = set()
    try:
        for loop_index in range(face.loops.count):
            loop = face.loops.item(loop_index)
            is_outer = True
            try:
                is_outer = bool(loop.isOuter)
            except Exception:
                is_outer = True
            if not is_outer:
                continue
            for coedge_index in range(loop.coEdges.count):
                coedge = loop.coEdges.item(coedge_index)
                edge = getattr(coedge, "edge", None)
                if edge is None:
                    continue
                for attr in ("startVertex", "endVertex"):
                    try:
                        vertex = getattr(edge, attr, None)
                        geom = getattr(vertex, "geometry", None) if vertex is not None else None
                        point = _point3d_to_mm(geom) if geom is not None else None
                    except Exception:
                        point = None
                    if point is None:
                        continue
                    key = (round(point[0], 4), round(point[1], 4), round(point[2], 4))
                    if key in seen:
                        continue
                    seen.add(key)
                    points.append(point)
    except Exception:
        return points
    return points


def _sample_face_edge_points_mm(face, max_points: int = 64) -> List[Tuple[float, float, float]]:
    """Sample world-mm points along face edge loops (Fusion-only)."""
    points: List[Tuple[float, float, float]] = []
    try:
        for loop_index in range(face.loops.count):
            loop = face.loops.item(loop_index)
            for coedge_index in range(loop.coEdges.count):
                coedge = loop.coEdges.item(coedge_index)
                edge = getattr(coedge, "edge", None)
                if edge is None:
                    continue
                try:
                    evaluator = edge.evaluator
                    extents = evaluator.getParameterExtents()
                    if isinstance(extents, (tuple, list)) and len(extents) >= 3:
                        start_param, end_param = extents[1], extents[2]
                    else:
                        continue
                    steps = max(2, min(8, max_points - len(points)))
                    for step in range(steps + 1):
                        t = start_param + (end_param - start_param) * (step / float(steps))
                        result = evaluator.getPointAtParameter(t)
                        if isinstance(result, (tuple, list)) and len(result) >= 2:
                            ok_pt, pt = result[0], result[1]
                        else:
                            ok_pt, pt = True, result
                        if not ok_pt or pt is None:
                            continue
                        points.append((pt.x * 10.0, pt.y * 10.0, pt.z * 10.0))
                        if len(points) >= max_points:
                            return points
                except Exception:
                    continue
    except Exception:
        return points
    return points


def extract_brep_faces_from_body(body, panel: Dict[str, Any]) -> List[Dict[str, Any]]:
    if body is None or adsk_core is None:
        return []
    panel_id = str(panel.get("panelId") or getattr(body, "name", "") or "panel")
    thickness_axis = (panel.get("inferred") or {}).get("thicknessAxis") or "UNKNOWN"
    panel_bbox = panel.get("bbox") if isinstance(panel.get("bbox"), dict) else None
    faces: List[Dict[str, Any]] = []
    try:
        for index in range(body.faces.count):
            face = body.faces.item(index)
            normal = _face_world_normal(face)
            origin = _face_world_point_mm(face)
            if not normal or not origin:
                continue
            if not _is_axis_aligned_normal(normal):
                continue
            vertices = _outer_loop_vertex_points_mm(face)
            samples = [] if len(vertices) >= 3 else _sample_face_edge_points_mm(face)
            points, bounds_source = select_face_bound_points(vertices, samples)
            bounds = bounds_mm_from_points(points)
            if not bounds:
                # Fallback: thin slab at origin using panel bbox span on other axes.
                bounds = dict(panel_bbox or {})
                bounds_source = "panel_bbox_fallback"
                if not bounds:
                    continue
            else:
                bounds = clamp_bounds_to_panel(bounds, panel_bbox)
            face_id = "{}::BREP_{}".format(panel_id, index)
            faces.append(
                {
                    "faceId": face_id,
                    "panelId": panel_id,
                    "faceClass": _classify_brep_face(normal, thickness_axis),
                    "normal": normal,
                    "planeOriginMm": origin,
                    "boundsMm": bounds,
                    "areaMm2": round(_face_area_mm2(face), 4),
                    "source": "fusion_brep",
                    # v1.2: outer-loop vertices first; edge-sample AABB only when verts are sparse.
                    "boundsSource": bounds_source,
                }
            )
    except Exception:
        return []
    return faces


def extract_faces_for_panel(body, panel: Dict[str, Any]) -> List[Dict[str, Any]]:
    brep_faces = extract_brep_faces_from_body(body, panel)
    if brep_faces:
        return brep_faces
    return extract_axis_aligned_faces_from_panel(panel)
