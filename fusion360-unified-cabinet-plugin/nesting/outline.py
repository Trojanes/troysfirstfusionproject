"""Nesting outline helpers: closed 2D polygons in millimetres.

Preferred sources (in order):
1. Flattened body XY outer loop (same frame as prepare_flat_copy bbox)
2. ``millingSurfaceSvg.outline[].pointsLocal`` from panel metadata
3. Axis-aligned rectangle fallback from width/depth
"""

from __future__ import annotations

import math
import re


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def close_ring(points):
    ring = [[_num(p[0]), _num(p[1])] for p in (points or []) if p is not None]
    if len(ring) < 3:
        return []
    if (
        abs(ring[0][0] - ring[-1][0]) > 1e-6
        or abs(ring[0][1] - ring[-1][1]) > 1e-6
    ):
        ring.append([ring[0][0], ring[0][1]])
    return ring


def polygon_area(points):
    return abs(signed_polygon_area(points))


def signed_polygon_area(points):
    """Signed polygon area (positive for counter-clockwise rings)."""
    ring = close_ring(points)
    if len(ring) < 4:
        return 0.0
    area = 0.0
    for index in range(len(ring) - 1):
        x0, y0 = ring[index]
        x1, y1 = ring[index + 1]
        area += x0 * y1 - x1 * y0
    return area * 0.5


def ensure_ring_winding(points, clockwise=False):
    """Return a closed ring with the requested winding."""
    ring = close_ring(points)
    if len(ring) < 4:
        return ring
    is_clockwise = signed_polygon_area(ring) < 0.0
    if is_clockwise != bool(clockwise):
        ring = close_ring(list(reversed(ring[:-1])))
    return ring


def outer_ccw(points):
    return ensure_ring_winding(points, clockwise=False)


def hole_cw(points):
    return ensure_ring_winding(points, clockwise=True)


def polygon_bounds(points):
    ring = close_ring(points)
    if len(ring) < 4:
        return {"minX": 0.0, "minY": 0.0, "maxX": 0.0, "maxY": 0.0, "widthMm": 0.0, "depthMm": 0.0}
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    return {
        "minX": min_x,
        "minY": min_y,
        "maxX": max_x,
        "maxY": max_y,
        "widthMm": max_x - min_x,
        "depthMm": max_y - min_y,
    }


def _aabb_clearance(bounds_a, bounds_b):
    """Minimum axis-aligned gap between two AABBs (0 if they overlap)."""
    dx = max(
        0.0,
        max(bounds_a["minX"] - bounds_b["maxX"], bounds_b["minX"] - bounds_a["maxX"]),
    )
    dy = max(
        0.0,
        max(bounds_a["minY"] - bounds_b["maxY"], bounds_b["minY"] - bounds_a["maxY"]),
    )
    if dx > 0.0 and dy > 0.0:
        return (dx * dx + dy * dy) ** 0.5
    return max(dx, dy)


def simplify_ring(points, max_points=48, tolerance_mm=0.75):
    """Reduce outline density for faster collision tests (Douglas-Peucker + cap)."""
    ring = close_ring(points)
    if len(ring) <= max(4, max_points):
        return ring
    # Work without duplicate closing point during DP.
    open_ring = ring[:-1]
    if len(open_ring) <= 3:
        return ring

    def _perpendicular_distance(point, start, end):
        x, y = point
        x0, y0 = start
        x1, y1 = end
        dx = x1 - x0
        dy = y1 - y0
        length2 = dx * dx + dy * dy
        if length2 <= 1e-18:
            return math.hypot(x - x0, y - y0)
        t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / length2))
        return math.hypot(x - (x0 + t * dx), y - (y0 + t * dy))

    def _dp(segment):
        if len(segment) <= 2:
            return list(segment)
        start, end = segment[0], segment[-1]
        farthest_i = 0
        farthest_d = -1.0
        for index in range(1, len(segment) - 1):
            distance = _perpendicular_distance(segment[index], start, end)
            if distance > farthest_d:
                farthest_d = distance
                farthest_i = index
        if farthest_d > tolerance_mm:
            left = _dp(segment[: farthest_i + 1])
            right = _dp(segment[farthest_i:])
            return left[:-1] + right
        return [start, end]

    simplified = _dp(open_ring)
    if len(simplified) > max_points:
        step = max(1, int(math.ceil(float(len(simplified)) / float(max_points))))
        capped = simplified[::step]
        if capped[-1] != simplified[-1]:
            capped.append(simplified[-1])
        simplified = capped
    return close_ring(simplified)


def translate_polygon(points, dx, dy):
    return [[_num(p[0]) + dx, _num(p[1]) + dy] for p in (points or [])]


def translate_ring_set(rings, dx, dy):
    """Translate rings or hole records without discarding metadata."""
    translated = []
    for value in rings or []:
        if isinstance(value, dict):
            record = dict(value)
            record["points"] = translate_polygon(
                value.get("points") or value.get("pointsLocal") or [], dx, dy
            )
            translated.append(record)
        else:
            translated.append(translate_polygon(value, dx, dy))
    return translated


def normalize_polygon_to_origin(points):
    bounds = polygon_bounds(points)
    return translate_polygon(points, -bounds["minX"], -bounds["minY"]), bounds


def rotate_polygon(points, degrees):
    angle = math.radians(_num(degrees))
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    rotated = []
    for x, y in points or []:
        rotated.append([x * cos_a - y * sin_a, x * sin_a + y * cos_a])
    return rotated


def rotate_ring_set(rings, degrees):
    """Rotate rings or hole records about the origin."""
    rotated = []
    for value in rings or []:
        if isinstance(value, dict):
            record = dict(value)
            record["points"] = rotate_polygon(
                value.get("points") or value.get("pointsLocal") or [], degrees
            )
            rotated.append(record)
        else:
            rotated.append(rotate_polygon(value, degrees))
    return rotated


def rectangle_polygon(width_mm, depth_mm):
    width = max(_num(width_mm), 0.0)
    depth = max(_num(depth_mm), 0.0)
    if width <= 0.0 or depth <= 0.0:
        return []
    return close_ring([[0.0, 0.0], [width, 0.0], [width, depth], [0.0, depth]])


def outline_from_milling_svg(milling_svg):
    """Join outline segment pointsLocal into one closed ring."""
    if not isinstance(milling_svg, dict):
        return []
    outline = milling_svg.get("outline")
    if not isinstance(outline, list) or not outline:
        # Fallback: parse SVG path d= from first outline path (display space).
        svg = str(milling_svg.get("svg") or "")
        return _polygon_from_svg_paths(svg)

    points = []
    for segment in outline:
        if not isinstance(segment, dict):
            continue
        local = segment.get("pointsLocal") or segment.get("points2d") or []
        for point in local:
            if not point or len(point) < 2:
                continue
            x, y = _num(point[0]), _num(point[1])
            if points and abs(points[-1][0] - x) < 1e-6 and abs(points[-1][1] - y) < 1e-6:
                continue
            points.append([x, y])
    ring = close_ring(points)
    if polygon_area(ring) <= 1e-6:
        return []
    return ring


_PATH_CMD_RE = re.compile(
    r"([MLZmlz])|([+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
)


def _polygon_from_svg_paths(svg_text):
    if not svg_text:
        return []
    # Prefer the outline group paths; otherwise first path commands.
    chunks = re.findall(
        r'<path[^>]*class="edge"[^>]*\sd="([^"]+)"',
        svg_text,
    )
    if not chunks:
        chunks = re.findall(r'\sd="([^"]+)"', svg_text)
    points = []
    for data in chunks:
        tokens = [tok for tok in _PATH_CMD_RE.findall(data) if tok]
        # findall with groups returns tuples; flatten.
        flat = []
        for match in _PATH_CMD_RE.finditer(data):
            flat.append(match.group(1) or match.group(2))
        command = "L"
        nums = []
        cursor = None
        for token in flat:
            if token in ("M", "L", "Z", "m", "l", "z"):
                if token in ("Z", "z"):
                    break
                command = token
                nums = []
                continue
            nums.append(_num(token))
            if len(nums) < 2:
                continue
            x, y = nums[0], nums[1]
            nums = []
            if command == "m" and cursor is not None:
                x += cursor[0]
                y += cursor[1]
                command = "l"
            elif command == "l" and cursor is not None:
                x += cursor[0]
                y += cursor[1]
            cursor = [x, y]
            if points and abs(points[-1][0] - x) < 1e-6 and abs(points[-1][1] - y) < 1e-6:
                continue
            points.append([x, y])
            if command == "M":
                command = "L"
    ring = close_ring(points)
    if polygon_area(ring) <= 1e-6:
        return []
    return ring


def _orient(ax, ay, bx, by, cx, cy):
    return (by - ay) * (cx - bx) - (bx - ax) * (cy - by)


def _on_segment(ax, ay, bx, by, cx, cy, eps=1e-9):
    return (
        min(ax, bx) - eps <= cx <= max(ax, bx) + eps
        and min(ay, by) - eps <= cy <= max(ay, by) + eps
    )


def segments_intersect(a0, a1, b0, b1):
    """True only for proper crossings. Endpoint/collinear touching is allowed."""
    ax, ay = a0
    bx, by = a1
    cx, cy = b0
    dx, dy = b1
    o1 = _orient(ax, ay, bx, by, cx, cy)
    o2 = _orient(ax, ay, bx, by, dx, dy)
    o3 = _orient(cx, cy, dx, dy, ax, ay)
    o4 = _orient(cx, cy, dx, dy, bx, by)
    return o1 * o2 < 0 and o3 * o4 < 0


def _segments_touch_or_intersect(a0, a1, b0, b1, eps=1e-9):
    if segments_intersect(a0, a1, b0, b1):
        return True
    ax, ay = a0
    bx, by = a1
    cx, cy = b0
    dx, dy = b1
    tests = (
        (_orient(ax, ay, bx, by, cx, cy), ax, ay, bx, by, cx, cy),
        (_orient(ax, ay, bx, by, dx, dy), ax, ay, bx, by, dx, dy),
        (_orient(cx, cy, dx, dy, ax, ay), cx, cy, dx, dy, ax, ay),
        (_orient(cx, cy, dx, dy, bx, by), cx, cy, dx, dy, bx, by),
    )
    return any(
        abs(orientation) <= eps and _on_segment(x0, y0, x1, y1, px, py, eps)
        for orientation, x0, y0, x1, y1, px, py in tests
    )


def is_simple_polygon(points):
    """Return False for degenerate or self-intersecting polygon rings."""
    ring = close_ring(points)
    edge_count = len(ring) - 1
    if edge_count < 3 or polygon_area(ring) <= 1e-9:
        return False
    for index in range(edge_count):
        a0 = ring[index]
        a1 = ring[index + 1]
        if abs(a0[0] - a1[0]) <= 1e-9 and abs(a0[1] - a1[1]) <= 1e-9:
            return False
        for other in range(index + 1, edge_count):
            if other == index + 1 or (index == 0 and other == edge_count - 1):
                continue
            if _segments_touch_or_intersect(
                a0, a1, ring[other], ring[other + 1]
            ):
                return False
    return True


def point_in_polygon(point, polygon):
    x, y = _num(point[0]), _num(point[1])
    ring = close_ring(polygon)
    if len(ring) < 4:
        return False
    inside = False
    for index in range(len(ring) - 1):
        x0, y0 = ring[index]
        x1, y1 = ring[index + 1]
        if ((y0 > y) != (y1 > y)) and (
            x < (x1 - x0) * (y - y0) / ((y1 - y0) or 1e-15) + x0
        ):
            inside = not inside
    return inside


def polygons_intersect(poly_a, poly_b):
    a = close_ring(poly_a)
    b = close_ring(poly_b)
    if len(a) < 4 or len(b) < 4:
        return False
    for i in range(len(a) - 1):
        for j in range(len(b) - 1):
            if segments_intersect(a[i], a[i + 1], b[j], b[j + 1]):
                return True
    if point_in_polygon(a[0], b) or point_in_polygon(b[0], a):
        return True
    return False


def ring_boundaries_touch_or_intersect(poly_a, poly_b):
    """Return True when any two ring boundary segments touch or cross."""
    a = close_ring(poly_a)
    b = close_ring(poly_b)
    if len(a) < 4 or len(b) < 4:
        return False
    for i in range(len(a) - 1):
        for j in range(len(b) - 1):
            if _segments_touch_or_intersect(a[i], a[i + 1], b[j], b[j + 1]):
                return True
    return False


def rings_touch_or_intersect(poly_a, poly_b):
    """Return True for crossings, shared boundary points, or overlap."""
    a = close_ring(poly_a)
    b = close_ring(poly_b)
    if ring_boundaries_touch_or_intersect(a, b):
        return True
    return point_in_polygon(a[0], b) or point_in_polygon(b[0], a)


def hole_is_valid(hole, outer, accepted_holes=None):
    """Conservatively validate a hole against its outer and prior holes."""
    ring = close_ring(hole)
    boundary = close_ring(outer)
    if not is_simple_polygon(ring) or not is_simple_polygon(boundary):
        return False
    if ring_boundaries_touch_or_intersect(ring, boundary):
        return False
    if not all(point_in_polygon(point, boundary) for point in ring[:-1]):
        return False
    for accepted in accepted_holes or []:
        other = accepted.get("points") if isinstance(accepted, dict) else accepted
        if rings_touch_or_intersect(ring, other):
            return False
    return True


def _point_segment_distance(px, py, ax, ay, bx, by):
    dx = bx - ax
    dy = by - ay
    length2 = dx * dx + dy * dy
    if length2 <= 1e-18:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def min_polygon_distance(poly_a, poly_b):
    a = close_ring(poly_a)
    b = close_ring(poly_b)
    if len(a) < 4 or len(b) < 4:
        return 0.0
    if polygons_intersect(a, b):
        return 0.0
    best = float("inf")
    for i in range(len(a) - 1):
        ax, ay = a[i]
        for j in range(len(b) - 1):
            best = min(
                best,
                _point_segment_distance(ax, ay, b[j][0], b[j][1], b[j + 1][0], b[j + 1][1]),
            )
        for bx, by in b[:-1]:
            best = min(
                best,
                _point_segment_distance(bx, by, a[i][0], a[i][1], a[i + 1][0], a[i + 1][1]),
            )
    return best if best < float("inf") else 0.0


def polygons_too_close(poly_a, poly_b, spacing_mm):
    spacing = max(_num(spacing_mm), 0.0)
    a = close_ring(poly_a)
    b = close_ring(poly_b)
    if len(a) < 4 or len(b) < 4:
        return False
    # Cheap AABB reject before O(n*m) segment tests (this was freezing 200-part nests).
    ba = polygon_bounds(a)
    bb = polygon_bounds(b)
    if (
        ba["maxX"] + spacing < bb["minX"]
        or bb["maxX"] + spacing < ba["minX"]
        or ba["maxY"] + spacing < bb["minY"]
        or bb["maxY"] + spacing < ba["minY"]
    ):
        return False
    if polygons_intersect(a, b):
        return True
    if spacing <= 1e-9:
        return False
    return min_polygon_distance(a, b) + 1e-9 < spacing


def oriented_outline(points, degrees):
    """Rotate about origin then shift so min corner is at (0,0)."""
    rotated = rotate_polygon(points, degrees)
    normalized, bounds = normalize_polygon_to_origin(rotated)
    return normalized, bounds


def build_outline_payload(points, source, width_mm=None, depth_mm=None, holes=None):
    ring = close_ring(points)
    if len(ring) < 4:
        ring = rectangle_polygon(width_mm or 0.0, depth_mm or 0.0)
        source = "rectangle"
    if not ring:
        return None
    bounds = polygon_bounds(ring)
    dx, dy = -bounds["minX"], -bounds["minY"]
    normalized = outer_ccw(translate_polygon(ring, dx, dy))
    normalized_holes = []
    for value in holes or []:
        source_record = value if isinstance(value, dict) else {}
        raw_points = (
            source_record.get("points") or source_record.get("pointsLocal") or []
            if isinstance(value, dict)
            else value
        )
        candidate = hole_cw(translate_polygon(raw_points, dx, dy))
        if not hole_is_valid(candidate, normalized, normalized_holes):
            continue
        record = {
            "points": candidate,
            "areaMm2": polygon_area(candidate),
        }
        for key in ("source", "cutType", "kind", "featureId"):
            if source_record.get(key) is not None:
                record[key] = source_record.get(key)
        normalized_holes.append(record)
    return {
        "points": normalized,
        "source": source,
        "pointCount": max(len(normalized) - 1, 0),
        "areaMm2": polygon_area(normalized),
        "widthMm": bounds["widthMm"],
        "depthMm": bounds["depthMm"],
        "holes": normalized_holes,
        "holeCount": len(normalized_holes),
    }
