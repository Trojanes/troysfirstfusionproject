"""Pure 2D capsule / stadium outlines (mm) for lock slots and similar openings."""

from __future__ import annotations

import math

CAPSULE_ARC_SEGMENTS = 16

# Door lock cutouts from cabinet generators: 55 x 15.5 stadium (R = short/2).
LOCK_SLOT_LONG_MM = 55.0
LOCK_SLOT_SHORT_MM = 15.5
LOCK_SLOT_SIZE_TOL_MM = 1.0


def looks_like_lock_slot_aabb(min_x, max_x, min_y, max_y, tol_mm=LOCK_SLOT_SIZE_TOL_MM):
    """True when axis-aligned bounds match the standard door-lock slot size."""
    width = float(max_x) - float(min_x)
    height = float(max_y) - float(min_y)
    if width <= 0 or height <= 0:
        return False
    long_side = max(width, height)
    short_side = min(width, height)
    return (
        abs(long_side - LOCK_SLOT_LONG_MM) <= tol_mm
        and abs(short_side - LOCK_SLOT_SHORT_MM) <= tol_mm
    )


def looks_like_lock_slot_points(points, tol_mm=LOCK_SLOT_SIZE_TOL_MM):
    ring = [list(point[:2]) for point in (points or []) if len(point) >= 2]
    if len(ring) < 2:
        return False
    xs = [float(p[0]) for p in ring]
    ys = [float(p[1]) for p in ring]
    return looks_like_lock_slot_aabb(min(xs), max(xs), min(ys), max(ys), tol_mm)


def capsule_outline_from_aabb(min_x, max_x, min_y, max_y, arc_segments=CAPSULE_ARC_SEGMENTS):
    """Closed stadium polyline in XY mm. End radius is half the short side."""
    x0, x1 = float(min_x), float(max_x)
    y0, y1 = float(min_y), float(max_y)
    if x1 <= x0 or y1 <= y0:
        return []
    radius = min((x1 - x0) * 0.5, (y1 - y0) * 0.5)
    if radius <= 1e-9:
        return []
    segments = max(4, int(arc_segments))
    horizontal = (x1 - x0) >= (y1 - y0)
    points = []
    if horizontal:
        cy = (y0 + y1) * 0.5
        left_cx = x0 + radius
        right_cx = x1 - radius
        points.append([left_cx, y1])
        points.append([right_cx, y1])
        for step in range(1, segments):
            angle = math.pi / 2.0 - math.pi * step / segments
            points.append(
                [right_cx + radius * math.cos(angle), cy + radius * math.sin(angle)]
            )
        points.append([right_cx, y0])
        points.append([left_cx, y0])
        for step in range(1, segments):
            angle = -math.pi / 2.0 - math.pi * step / segments
            points.append(
                [left_cx + radius * math.cos(angle), cy + radius * math.sin(angle)]
            )
    else:
        cx = (x0 + x1) * 0.5
        bottom_cy = y0 + radius
        top_cy = y1 - radius
        points.append([x0, bottom_cy])
        points.append([x0, top_cy])
        for step in range(1, segments):
            angle = math.pi + math.pi * step / segments
            points.append(
                [cx + radius * math.cos(angle), top_cy - radius * math.sin(angle)]
            )
        points.append([x1, top_cy])
        points.append([x1, bottom_cy])
        for step in range(1, segments):
            angle = math.pi * step / segments
            points.append(
                [cx + radius * math.cos(angle), bottom_cy - radius * math.sin(angle)]
            )
    if points:
        points.append(list(points[0]))
    return points


def capsule_outline_from_points_aabb(points, arc_segments=CAPSULE_ARC_SEGMENTS):
    ring = [list(point[:2]) for point in (points or []) if len(point) >= 2]
    if len(ring) < 2:
        return []
    xs = [float(p[0]) for p in ring]
    ys = [float(p[1]) for p in ring]
    return capsule_outline_from_aabb(min(xs), max(xs), min(ys), max(ys), arc_segments)


def capsule_outline_from_centerline(centerline, width_mm, arc_segments=CAPSULE_ARC_SEGMENTS):
    """Stadium around a 2-point centreline; overall size matches the strip AABB."""
    ring = [list(point[:2]) for point in (centerline or []) if len(point) >= 2]
    if len(ring) < 2:
        return []
    width = float(width_mm)
    if width <= 1e-9:
        return []
    start, finish = ring[0], ring[-1]
    dx = float(finish[0]) - float(start[0])
    dy = float(finish[1]) - float(start[1])
    length = math.hypot(dx, dy)
    if length <= 1e-9:
        return []
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    half = width * 0.5
    # Expand ends by radius so overall long side = centreline + width.
    corners = []
    for dist in (-half, length + half):
        px = float(start[0]) + ux * dist
        py = float(start[1]) + uy * dist
        for side in (-1.0, 1.0):
            corners.append([px + nx * half * side, py + ny * half * side])
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    return capsule_outline_from_aabb(min(xs), max(xs), min(ys), max(ys), arc_segments)
