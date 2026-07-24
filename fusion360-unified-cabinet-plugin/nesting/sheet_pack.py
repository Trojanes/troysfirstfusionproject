"""Fast hybrid sheet packing for cabinet panels.

MaxRects/BSSF free rectangles provide a cheap placement shortlist. True-shape
polygon checks, a sheet-local spatial grid, and a bounded BLF compaction pass
preserve concave/notched behavior without the old 50-part AABB-only downgrade.
"""

from __future__ import annotations

import random
import hashlib
import math

try:
    from nesting.outline import (
        build_outline_payload,
        oriented_outline,
        point_in_polygon,
        polygon_area,
        polygon_bounds,
        polygons_too_close,
        rectangle_polygon,
        rotate_polygon,
        simplify_ring,
        translate_polygon,
    )
except Exception:
    from outline import (
        build_outline_payload,
        oriented_outline,
        point_in_polygon,
        polygon_area,
        polygon_bounds,
        polygons_too_close,
        rectangle_polygon,
        rotate_polygon,
        simplify_ring,
        translate_polygon,
    )

DEFAULT_SHEET_WIDTH_MM = 2440.0
DEFAULT_SHEET_HEIGHT_MM = 1220.0
DEFAULT_BORDER_MM = 15.0
DEFAULT_SPACING_MM = 12.0
DEFAULT_SHEET_GAP_MM = 100.0
ENGINE_NAME = "sheet_pack_hybrid_v3"

# Cap candidate explosion on dense sheets (still prefer bottom-left order).
MAX_CANDIDATE_POINTS = 240
# Fixed local-search budget: swap two items in the order, keep fewer sheets.
LOCAL_SEARCH_ATTEMPTS = 8
# Gravity-slide binary search tolerance (mm). Coarser = fewer conflict tests.
SLIDE_TOLERANCE_MM = 1.5
# Pack-time outline density cap (true-shape fidelity vs freeze risk).
PACK_OUTLINE_MAX_POINTS = 32
PACK_OUTLINE_TOLERANCE_MM = 1.0
# Above this part count per material job: keep exact nearby polygon checks, but
# skip expensive gravity sliding and use a tighter deterministic search budget.
FAST_PACK_PART_THRESHOLD = 50
SPATIAL_CELL_MM = 300.0
MAX_FREE_RECT_CANDIDATES = 48


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _tag(value):
    return str(value or "").strip().lower()


def normalize_sheet_params(sheet_params):
    """Normalize UI/controller payload into a stable dict."""
    raw = sheet_params if isinstance(sheet_params, dict) else {}
    sheets = {}
    for entry in raw.get("sheets") or []:
        if not isinstance(entry, dict):
            continue
        tag = _tag(entry.get("boardTypeTag"))
        if not tag:
            continue
        width = max(_num(entry.get("widthMm"), DEFAULT_SHEET_WIDTH_MM), 1.0)
        height = max(_num(entry.get("heightMm"), DEFAULT_SHEET_HEIGHT_MM), 1.0)
        sheets[tag] = {
            "boardTypeTag": tag,
            "widthMm": width,
            "heightMm": height,
        }
    border = max(_num(raw.get("borderMm"), DEFAULT_BORDER_MM), 0.0)
    spacing = max(_num(raw.get("spacingMm"), DEFAULT_SPACING_MM), 0.0)
    allow_rotation = bool(raw.get("allowRotation"))
    allow_parts_in_part = bool(raw.get("allowPartsInPart"))
    increment = raw.get("rotationIncrementDeg")
    if increment is None:
        increment = 90.0
    increment = max(_num(increment, 90.0), 1.0)
    return {
        "sheets": sheets,
        "borderMm": border,
        "spacingMm": spacing,
        "allowRotation": allow_rotation,
        "allowPartsInPart": allow_parts_in_part,
        "rotationIncrementDeg": increment if allow_rotation else None,
        "sheetGapMm": max(
            _num(raw.get("sheetGapMm"), DEFAULT_SHEET_GAP_MM),
            0.0,
        ),
        "layoutWidthMm": max(_num(raw.get("layoutWidthMm"), 0.0), 0.0),
        "qualityTimeLimitSec": max(
            _num(raw.get("qualityTimeLimitSec"), 30.0),
            1.0,
        ),
    }


def sheet_size_for_type(params, board_type_tag):
    tag = _tag(board_type_tag)
    sheets = params.get("sheets") or {}
    if tag in sheets:
        return dict(sheets[tag])
    return {
        "boardTypeTag": tag or "unknown",
        "widthMm": DEFAULT_SHEET_WIDTH_MM,
        "heightMm": DEFAULT_SHEET_HEIGHT_MM,
    }


def rotation_candidates(params):
    """In-plane rotations for packing. Include 180° so triangles can pair."""
    if not params.get("allowRotation"):
        return (0.0,)
    increment = float(params.get("rotationIncrementDeg") or 90.0)
    if increment <= 1e-9:
        return (0.0,)
    angles = []
    angle = 0.0
    while angle < 360.0 - 1e-9:
        angles.append(round(angle, 6))
        angle += increment
    # Always allow 180° for chiral panels even when UI increment is 90.
    if 180.0 not in angles:
        angles.append(180.0)
    return tuple(sorted(set(angles)))


def _job_key(item):
    return (_tag(item.get("boardTypeTag")), _tag(item.get("colorTag")))


def _part_sort_key(item):
    """Hard shapes first: large area, then awkward aspect, then long side."""
    outline = item.get("outline") if isinstance(item.get("outline"), dict) else {}
    area = _num(outline.get("areaMm2"))
    width = _num(item.get("widthMm"))
    depth = _num(item.get("depthMm"))
    if area <= 0.0:
        area = width * depth
    long_side = max(width, depth)
    short_side = max(min(width, depth), 1e-6)
    aspect = long_side / short_side
    # Prefer non-rectangular / high vertex counts earlier (fill notches later).
    points = outline.get("points") or []
    complexity = max(len(points) - 5, 0)
    identity = str(
        item.get("panelId") or item.get("id") or item.get("bodyName") or ""
    )
    return (-area, -aspect, -complexity, -long_side, identity)


def _item_outline_points(item):
    outline = item.get("outline") if isinstance(item.get("outline"), dict) else {}
    points = outline.get("points")
    if isinstance(points, list) and len(points) >= 4:
        return simplify_ring(
            points,
            max_points=PACK_OUTLINE_MAX_POINTS,
            tolerance_mm=PACK_OUTLINE_TOLERANCE_MM,
        )
    return rectangle_polygon(
        item.get("widthMm"),
        item.get("depthMm"),
    )


def _item_is_rectangle(item):
    points = _item_outline_points(item)
    opened = points[:-1] if len(points) > 1 and points[0] == points[-1] else points
    if len(opened) != 4:
        return False
    bounds = polygon_bounds(points)
    bbox_area = float(bounds["widthMm"]) * float(bounds["depthMm"])
    return abs(polygon_area(points) - bbox_area) <= max(1e-6, bbox_area * 1e-6)


def _oriented_part(item, rotation_deg):
    points = _item_outline_points(item)
    oriented, bounds = oriented_outline(points, rotation_deg)
    holes = []
    raw_outline = item.get("outline") if isinstance(item.get("outline"), dict) else {}
    for raw_hole in raw_outline.get("holes") or []:
        record = raw_hole if isinstance(raw_hole, dict) else {"points": raw_hole}
        if str(record.get("cutType") or "FULL").upper() != "FULL":
            continue
        ring = record.get("points") or []
        if len(ring) < 4:
            continue
        rotated = rotate_polygon(ring, rotation_deg)
        holes.append(
            translate_polygon(rotated, -bounds["minX"], -bounds["minY"])
        )
    return {
        "points": oriented,
        "holes": holes,
        "isRectangle": _item_is_rectangle(item),
        "bounds": bounds,
        "widthMm": bounds["widthMm"],
        "depthMm": bounds["depthMm"],
        "rotationDeg": float(rotation_deg),
        "areaMm2": polygon_area(oriented),
    }


def _bounds_expand(bounds, pad):
    return {
        "minX": float(bounds["minX"]) - pad,
        "minY": float(bounds["minY"]) - pad,
        "maxX": float(bounds["maxX"]) + pad,
        "maxY": float(bounds["maxY"]) + pad,
    }


def _bounds_overlap(a, b):
    return not (
        a["maxX"] <= b["minX"] + 1e-9
        or b["maxX"] <= a["minX"] + 1e-9
        or a["maxY"] <= b["minY"] + 1e-9
        or b["maxY"] <= a["minY"] + 1e-9
    )


class _SpatialIndex:
    """Small uniform grid broad phase for one physical sheet."""

    def __init__(self, cell_size=SPATIAL_CELL_MM):
        self.cell_size = max(float(cell_size), 1.0)
        self.cells = {}

    def _keys(self, bounds):
        min_x = int(float(bounds["minX"]) // self.cell_size)
        max_x = int(float(bounds["maxX"]) // self.cell_size)
        min_y = int(float(bounds["minY"]) // self.cell_size)
        max_y = int(float(bounds["maxY"]) // self.cell_size)
        for gx in range(min_x, max_x + 1):
            for gy in range(min_y, max_y + 1):
                yield (gx, gy)

    def add(self, entry):
        bounds = entry.get("bounds") or polygon_bounds(entry.get("points") or [])
        for key in self._keys(bounds):
            self.cells.setdefault(key, []).append(entry)

    def query(self, bounds):
        found = []
        seen = set()
        for key in self._keys(bounds):
            for entry in self.cells.get(key, ()):
                marker = id(entry)
                if marker in seen:
                    continue
                seen.add(marker)
                found.append(entry)
        return found


def _rect_intersection(a, b):
    x0 = max(float(a["x"]), float(b["x"]))
    y0 = max(float(a["y"]), float(b["y"]))
    x1 = min(float(a["x"]) + float(a["w"]), float(b["x"]) + float(b["w"]))
    y1 = min(float(a["y"]) + float(a["h"]), float(b["y"]) + float(b["h"]))
    if x1 <= x0 + 1e-9 or y1 <= y0 + 1e-9:
        return None
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _rect_contains(outer, inner):
    return (
        float(inner["x"]) >= float(outer["x"]) - 1e-9
        and float(inner["y"]) >= float(outer["y"]) - 1e-9
        and float(inner["x"]) + float(inner["w"])
        <= float(outer["x"]) + float(outer["w"]) + 1e-9
        and float(inner["y"]) + float(inner["h"])
        <= float(outer["y"]) + float(outer["h"]) + 1e-9
    )


def _prune_free_rectangles(rectangles):
    usable = [
        rect
        for rect in rectangles
        if float(rect["w"]) > 1e-6 and float(rect["h"]) > 1e-6
    ]
    pruned = []
    for index, rect in enumerate(usable):
        if any(
            index != other_index and _rect_contains(other, rect)
            for other_index, other in enumerate(usable)
        ):
            continue
        pruned.append(rect)
    return pruned


def _split_free_rectangles(free_rectangles, used):
    """Classic MaxRects split; AABB free space is only a candidate shortlist."""
    output = []
    ux0 = float(used["x"])
    uy0 = float(used["y"])
    ux1 = ux0 + float(used["w"])
    uy1 = uy0 + float(used["h"])
    for free in free_rectangles:
        if _rect_intersection(free, used) is None:
            output.append(free)
            continue
        fx0 = float(free["x"])
        fy0 = float(free["y"])
        fx1 = fx0 + float(free["w"])
        fy1 = fy0 + float(free["h"])
        if ux0 > fx0 + 1e-9:
            output.append({"x": fx0, "y": fy0, "w": ux0 - fx0, "h": fy1 - fy0})
        if ux1 < fx1 - 1e-9:
            output.append({"x": ux1, "y": fy0, "w": fx1 - ux1, "h": fy1 - fy0})
        if uy0 > fy0 + 1e-9:
            output.append({"x": fx0, "y": fy0, "w": fx1 - fx0, "h": uy0 - fy0})
        if uy1 < fy1 - 1e-9:
            output.append({"x": fx0, "y": uy1, "w": fx1 - fx0, "h": fy1 - uy1})
    return _prune_free_rectangles(output)


def _maxrects_candidates(free_rectangles, width, height):
    scored = []
    for rect in free_rectangles or []:
        rw = float(rect["w"])
        rh = float(rect["h"])
        if width > rw + 1e-9 or height > rh + 1e-9:
            continue
        short_fit = min(rw - width, rh - height)
        long_fit = max(rw - width, rh - height)
        area_fit = rw * rh - width * height
        scored.append(
            (
                short_fit,
                long_fit,
                area_fit,
                float(rect["y"]),
                float(rect["x"]),
            )
        )
    return [
        (score[4], score[3])
        for score in sorted(scored)[:MAX_FREE_RECT_CANDIDATES]
    ]


def _candidate_points(
    placed,
    border,
    spacing,
    free_rectangles=None,
    width=0.0,
    height=0.0,
    rich=True,
):
    """Bottom-left-fill style candidates: corners, vertices, pairwise holes."""
    points = [(border, border)]
    points.extend(_maxrects_candidates(free_rectangles, width, height))
    if not rich:
        return sorted(set(points), key=lambda point: (point[1], point[0]))
    boxes = []
    candidate_entries = placed if len(placed) <= 48 else placed[-32:]
    for entry in candidate_entries:
        px = float(entry["x"])
        py = float(entry["y"])
        pw = float(entry["w"])
        ph = float(entry["h"])
        right = px + pw + spacing
        top = py + ph + spacing
        boxes.append((px, py, right, top))
        points.append((right, py))
        points.append((px, top))
        points.append((right, top))
        # Sparse true-shape samples — dense lounge rings used to explode candidates.
        ring = entry.get("points") or []
        step = max(1, len(ring) // 12)
        for vx, vy in ring[::step]:
            points.append((float(vx) + spacing, float(vy)))
            points.append((float(vx), float(vy) + spacing))
        for hole in entry.get("holes") or []:
            hole_bounds = polygon_bounds(hole)
            points.append(
                (
                    float(hole_bounds["minX"]) + spacing,
                    float(hole_bounds["minY"]) + spacing,
                )
            )

    # Pairwise BLF corners: right-of-A × top-of-B (and swap) fill rectangular holes.
    # Pairwise holes help small jobs but dominate candidate counts on 100–200
    # panel cabinets. MaxRects + shape vertices are sufficient past 40 placed.
    box_limit = min(len(boxes), 16) if len(boxes) <= 40 else 0
    for i in range(box_limit):
        _ax, _ay, ar, at = boxes[i]
        for j in range(box_limit):
            if i == j:
                continue
            _bx, _by, br, bt = boxes[j]
            points.append((ar, bt))
            points.append((br, at))

    unique = sorted(
        set((round(float(x), 3), round(float(y), 3)) for x, y in points),
        key=lambda p: (p[1], p[0]),
    )
    candidate_limit = 80 if len(placed) > 40 else MAX_CANDIDATE_POINTS
    if len(unique) <= candidate_limit:
        return unique
    # Keep densest bottom-left band, then evenly sample the rest for hole fill.
    head = unique[: candidate_limit // 2]
    tail = unique[candidate_limit // 2 :]
    step = max(len(tail) // max(candidate_limit - len(head), 1), 1)
    sampled = tail[::step][: candidate_limit - len(head)]
    return head + sampled


def _inside_hole_with_spacing(world, holes, spacing):
    def point_segment_distance(point, start, end):
        px, py = float(point[0]), float(point[1])
        ax, ay = float(start[0]), float(start[1])
        bx, by = float(end[0]), float(end[1])
        dx, dy = bx - ax, by - ay
        length_sq = dx * dx + dy * dy
        if length_sq <= 1e-12:
            return math.hypot(px - ax, py - ay)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_sq))
        return math.hypot(px - (ax + t * dx), py - (ay + t * dy))

    def boundary_distance(a, b):
        best = float("inf")
        for index in range(len(a) - 1):
            a0, a1 = a[index], a[index + 1]
            for other_index in range(len(b) - 1):
                b0, b1 = b[other_index], b[other_index + 1]
                best = min(
                    best,
                    point_segment_distance(a0, b0, b1),
                    point_segment_distance(a1, b0, b1),
                    point_segment_distance(b0, a0, a1),
                    point_segment_distance(b1, a0, a1),
                )
        return best

    for hole in holes or []:
        if not hole:
            continue
        if not all(point_in_polygon(point, hole) for point in world[:-1]):
            continue
        if boundary_distance(world, hole) + 1e-6 < spacing:
            continue
        return True
    return False


def _placement_conflicts(
    world,
    placed,
    spacing,
    world_bounds=None,
    aabb_only=False,
    spatial_index=None,
    candidate_is_rectangle=False,
):
    if world_bounds is None:
        world_bounds = polygon_bounds(world)
    probe = _bounds_expand(world_bounds, spacing)
    candidates = spatial_index.query(probe) if spatial_index is not None else placed
    for entry in candidates:
        other_bounds = entry.get("bounds")
        if other_bounds is None:
            other_bounds = polygon_bounds(entry["points"])
        if not _bounds_overlap(probe, other_bounds):
            continue
        if _inside_hole_with_spacing(world, entry.get("holes"), spacing):
            continue
        if aabb_only:
            return True
        if candidate_is_rectangle and entry.get("isRectangle"):
            return True
        if polygons_too_close(world, entry["points"], spacing):
            return True
    return False


def _in_sheet(x, y, width, height, sheet_w, sheet_h, border):
    inner_x1 = sheet_w - border
    inner_y1 = sheet_h - border
    if x < border - 1e-9 or y < border - 1e-9:
        return False
    if x + width > inner_x1 + 1e-9 or y + height > inner_y1 + 1e-9:
        return False
    return True


def _slide_left_down(
    placed,
    local_points,
    x,
    y,
    width,
    height,
    sheet_w,
    sheet_h,
    border,
    spacing,
    aabb_only=False,
    spatial_index=None,
    candidate_is_rectangle=False,
):
    """Gravity-tighten a feasible placement toward bottom-left."""

    def feasible(px, py):
        if not _in_sheet(px, py, width, height, sheet_w, sheet_h, border):
            return False
        world = translate_polygon(local_points, px, py)
        world_bounds = {
            "minX": px,
            "minY": py,
            "maxX": px + width,
            "maxY": py + height,
            "widthMm": width,
            "depthMm": height,
        }
        return not _placement_conflicts(
            world,
            placed,
            spacing,
            world_bounds=world_bounds,
            aabb_only=aabb_only,
            spatial_index=spatial_index,
            candidate_is_rectangle=candidate_is_rectangle,
        )

    best_x, best_y = x, y
    # Slide left.
    lo, hi = border, best_x
    while hi - lo > SLIDE_TOLERANCE_MM:
        mid = (lo + hi) * 0.5
        if feasible(mid, best_y):
            best_x = mid
            hi = mid
        else:
            lo = mid
    # Slide down.
    lo, hi = border, best_y
    while hi - lo > SLIDE_TOLERANCE_MM:
        mid = (lo + hi) * 0.5
        if feasible(best_x, mid):
            best_y = mid
            hi = mid
        else:
            lo = mid
    world = translate_polygon(local_points, best_x, best_y)
    return best_x, best_y, world


def _bottom_left_fit_polygon(
    placed,
    part,
    sheet_w,
    sheet_h,
    border,
    spacing,
    aabb_only=False,
    allow_slide=True,
    spatial_index=None,
    free_rectangles=None,
    prefer_maxrects=False,
):
    width = float(part["widthMm"])
    height = float(part["depthMm"])
    if width > sheet_w - 2.0 * border + 1e-9 or height > sheet_h - 2.0 * border + 1e-9:
        return None
    local_points = part["points"]
    if prefer_maxrects and free_rectangles:
        for x, y in _maxrects_candidates(free_rectangles, width, height):
            if _in_sheet(x, y, width, height, sheet_w, sheet_h, border):
                # MaxRects free space is carved from spacing-inflated occupied
                # AABBs, so this is a conservative true-shape-safe placement.
                return (x, y, translate_polygon(local_points, x, y))
    if (prefer_maxrects or len(placed) >= 40) and free_rectangles:
        # Dense sheets: a BSSF free-rectangle candidate is AABB-safe by
        # construction. Only fall back to polygon/vertex candidates when none
        # of those candidates can be used.
        candidate_sets = [
            _maxrects_candidates(free_rectangles, width, height),
            _candidate_points(
                placed,
                border,
                spacing,
                free_rectangles=None,
                width=width,
                height=height,
                rich=not aabb_only,
            ),
        ]
    else:
        candidate_sets = [
            _candidate_points(
                placed,
                border,
                spacing,
                free_rectangles=free_rectangles,
                width=width,
                height=height,
                rich=not aabb_only,
            )
        ]
    for candidates in candidate_sets:
        for x, y in candidates:
            if not _in_sheet(x, y, width, height, sheet_w, sheet_h, border):
                continue
            world = translate_polygon(local_points, x, y)
            world_bounds = {
                "minX": x,
                "minY": y,
                "maxX": x + width,
                "maxY": y + height,
                "widthMm": width,
                "depthMm": height,
            }
            if _placement_conflicts(
                world,
                placed,
                spacing,
                world_bounds=world_bounds,
                aabb_only=aabb_only,
                spatial_index=spatial_index,
                candidate_is_rectangle=bool(part.get("isRectangle")),
            ):
                continue
            if not allow_slide:
                return (x, y, world)
            sx, sy, slid = _slide_left_down(
                placed,
                local_points,
                x,
                y,
                width,
                height,
                sheet_w,
                sheet_h,
                border,
                spacing,
                aabb_only=aabb_only,
                spatial_index=spatial_index,
                candidate_is_rectangle=bool(part.get("isRectangle")),
            )
            return (sx, sy, slid)
    return None


def _pack_bin(
    parts,
    sheet_w,
    sheet_h,
    border,
    spacing,
    rotations,
    aabb_only=False,
    allow_slide=True,
    allow_parts_in_part=False,
    prefer_maxrects=False,
):
    """Pack as many parts as possible onto one sheet. Returns (placed, remaining)."""
    placed = []
    placements = []
    remaining = []
    spatial_index = _SpatialIndex()
    free_rectangles = [{
        "x": border,
        "y": border,
        "w": max(sheet_w - 2.0 * border, 0.0),
        "h": max(sheet_h - 2.0 * border, 0.0),
    }]
    for item in parts:
        best = None
        oriented_cache = {}
        for rot in rotations:
            oriented = oriented_cache.setdefault(float(rot), _oriented_part(item, rot))
            if oriented["widthMm"] <= 0.0 or oriented["depthMm"] <= 0.0:
                continue
            fit = _bottom_left_fit_polygon(
                placed,
                oriented,
                sheet_w,
                sheet_h,
                border,
                spacing,
                aabb_only=aabb_only,
                allow_slide=allow_slide,
                spatial_index=spatial_index,
                free_rectangles=free_rectangles,
                prefer_maxrects=prefer_maxrects,
            )
            if fit is None:
                continue
            x, y, world_points = fit
            # Prefer lower / lefter; then lower gravity-ish (y then x); prefer 0°.
            score = (y, x, abs(float(rot)))
            if best is None or score < best["score"]:
                best = {
                    "score": score,
                    "x": x,
                    "y": y,
                    "w": oriented["widthMm"],
                    "h": oriented["depthMm"],
                    "rotationDeg": oriented["rotationDeg"],
                    "points": world_points,
                    "areaMm2": oriented["areaMm2"],
                    "bounds": {
                        "minX": x,
                        "minY": y,
                        "maxX": x + oriented["widthMm"],
                        "maxY": y + oriented["depthMm"],
                        "widthMm": oriented["widthMm"],
                        "depthMm": oriented["depthMm"],
                    },
                }
        if best is None:
            remaining.append(item)
            continue
        placed_entry = {
            "x": best["x"],
            "y": best["y"],
            "w": best["w"],
            "h": best["h"],
            "points": best["points"],
            "holes": [
                translate_polygon(hole, best["x"], best["y"])
                for hole in oriented_cache[float(best["rotationDeg"])].get("holes") or []
            ] if allow_parts_in_part else [],
            "isRectangle": bool(
                oriented_cache[float(best["rotationDeg"])].get("isRectangle")
            ),
            "bounds": best["bounds"],
        }
        placed.append(placed_entry)
        spatial_index.add(placed_entry)
        # Reserve spacing on every side so any future free-rectangle origin is
        # conservative regardless of which side of the part it lands on.
        free_rectangles = _split_free_rectangles(
            free_rectangles,
            {
                "x": best["x"] - spacing,
                "y": best["y"] - spacing,
                "w": best["w"] + 2.0 * spacing,
                "h": best["h"] + 2.0 * spacing,
            },
        )
        placements.append(
            {
                **item,
                "localX": best["x"],
                "localY": best["y"],
                "packedWidthMm": best["w"],
                "packedDepthMm": best["h"],
                "rotationDeg": best["rotationDeg"],
                "packedOutline": best["points"],
                "packedAreaMm2": best["areaMm2"],
                "isRectangle": bool(placed_entry["isRectangle"]),
                "nestedInHole": any(
                    _inside_hole_with_spacing(best["points"], entry.get("holes"), spacing)
                    for entry in placed[:-1]
                ) if allow_parts_in_part else False,
            }
        )
    return placements, remaining


def _pack_score(sheets_out, unplaced):
    """Lexicographic: place everything, then minimize sheets/waste/extent."""
    sheet_count = len(sheets_out)
    unplaced_count = len(unplaced)
    util = 0.0
    if sheets_out:
        util = sum(float(s.get("utilization") or 0.0) for s in sheets_out) / sheet_count
    used_extent = 0.0
    for sheet in sheets_out:
        for placement in sheet.get("placements") or []:
            used_extent = max(
                used_extent,
                float(placement.get("localY") or 0.0)
                + float(placement.get("packedDepthMm") or 0.0),
            )
    return (unplaced_count, sheet_count, -util, used_extent)


def _pack_job_ordered(ordered, sheet, params):
    sheet_w = float(sheet["widthMm"])
    sheet_h = float(sheet["heightMm"])
    border = float(params["borderMm"])
    spacing = float(params["spacingMm"])
    rotations = rotation_candidates(params)
    fast = len(ordered) >= FAST_PACK_PART_THRESHOLD
    # Spatial broad phase keeps exact true-shape checks affordable for large jobs.
    aabb_only = (
        bool(ordered)
        and not params.get("allowPartsInPart")
        and all(_item_is_rectangle(item) for item in ordered)
    )
    allow_slide = not fast
    if fast and params.get("allowRotation"):
        # Keep 0/90 only — enough for grain-ish boards without 4x search.
        rotations = tuple(a for a in rotations if abs(float(a) % 180.0) < 1e-6 or abs(float(a) - 90.0) < 1e-6)
        if not rotations:
            rotations = (0.0, 90.0)
    sheets_out = []
    unplaced = []
    queue = list(ordered)

    fit_queue = []
    for item in queue:
        fits = False
        for rot in rotations:
            oriented = _oriented_part(item, rot)
            if (
                oriented["widthMm"] <= sheet_w - 2.0 * border + 1e-9
                and oriented["depthMm"] <= sheet_h - 2.0 * border + 1e-9
            ):
                fits = True
                break
        if fits:
            fit_queue.append(item)
        else:
            unplaced.append(
                {
                    **item,
                    "reason": "Part outline exceeds sheet usable area (after border).",
                }
            )

    while fit_queue:
        placed, fit_queue = _pack_bin(
            fit_queue,
            sheet_w,
            sheet_h,
            border,
            spacing,
            rotations,
            aabb_only=aabb_only,
            allow_slide=allow_slide,
            allow_parts_in_part=bool(params.get("allowPartsInPart")),
            prefer_maxrects=fast,
        )
        if not placed:
            for item in fit_queue:
                unplaced.append(
                    {
                        **item,
                        "reason": "Could not place on a new sheet.",
                    }
                )
            break
        used_area = sum(_num(p.get("packedAreaMm2")) for p in placed)
        if used_area <= 1e-9:
            used_area = sum(
                _num(p.get("packedWidthMm")) * _num(p.get("packedDepthMm"))
                for p in placed
            )
        inner_area = max(sheet_w - 2.0 * border, 0.0) * max(
            sheet_h - 2.0 * border, 0.0
        )
        sheets_out.append(
            {
                "sheetIndex": len(sheets_out),
                "boardTypeTag": sheet["boardTypeTag"],
                "widthMm": sheet_w,
                "heightMm": sheet_h,
                "count": len(placed),
                "usedAreaMm2": used_area,
                "innerAreaMm2": inner_area,
                "utilization": (used_area / inner_area) if inner_area > 1e-9 else 0.0,
                "placements": placed,
            }
        )
    sheets_out = _consolidate_sheets(
        sheets_out,
        sheet_w,
        sheet_h,
        border,
        spacing,
        rotations,
        part_count=len(ordered),
        aabb_only=aabb_only,
        allow_slide=allow_slide,
    )
    return sheets_out, unplaced


def _sheet_placed_boxes(sheet):
    boxes = []
    for entry in sheet.get("placements") or []:
        x = float(entry["localX"])
        y = float(entry["localY"])
        w = float(entry["packedWidthMm"])
        h = float(entry["packedDepthMm"])
        boxes.append(
            {
                "x": x,
                "y": y,
                "w": w,
                "h": h,
                "points": entry.get("packedOutline") or [],
                "bounds": {
                    "minX": x,
                    "minY": y,
                    "maxX": x + w,
                    "maxY": y + h,
                    "widthMm": w,
                    "depthMm": h,
                },
                "isRectangle": bool(entry.get("isRectangle", False)),
            }
        )
    return boxes


def _recompute_sheet_stats(sheet, sheet_w, sheet_h, border):
    placements = sheet.get("placements") or []
    used_area = sum(_num(p.get("packedAreaMm2")) for p in placements)
    if used_area <= 1e-9:
        used_area = sum(
            _num(p.get("packedWidthMm")) * _num(p.get("packedDepthMm"))
            for p in placements
        )
    inner_area = max(sheet_w - 2.0 * border, 0.0) * max(
        sheet_h - 2.0 * border, 0.0
    )
    sheet["count"] = len(placements)
    sheet["usedAreaMm2"] = used_area
    sheet["innerAreaMm2"] = inner_area
    sheet["utilization"] = (used_area / inner_area) if inner_area > 1e-9 else 0.0


def _consolidate_sheets(
    sheets_out,
    sheet_w,
    sheet_h,
    border,
    spacing,
    rotations,
    part_count=0,
    aabb_only=False,
    allow_slide=True,
):
    """Backfill earlier sheets so sparse tail sheets can disappear.

    Large jobs only backfill from the last 1–2 sheets (lightweight), so leftover
    strips can reclaim empty space without a full quadratic re-pack.
    """
    if len(sheets_out) <= 1:
        return sheets_out
    # MaxRects already provides good dense-sheet behavior; avoid a quadratic
    # tail-sheet replay for very large jobs.
    if int(part_count or 0) >= 100:
        return sheets_out
    sheets = [dict(sheet, placements=list(sheet.get("placements") or [])) for sheet in sheets_out]
    large = int(part_count or 0) >= 40 or len(sheets) >= 8
    if large:
        donor_indices = list(range(max(1, len(sheets) - 2), len(sheets)))
        max_guard = 1 if int(part_count or 0) >= FAST_PACK_PART_THRESHOLD else 2
    else:
        donor_indices = list(range(len(sheets) - 1, 0, -1))
        max_guard = 4

    changed = True
    guard = 0
    while changed and guard < max_guard:
        changed = False
        guard += 1
        for donor_index in sorted(donor_indices, reverse=True):
            if donor_index <= 0 or donor_index >= len(sheets):
                continue
            donor = sheets[donor_index]
            remaining = []
            for placement in list(donor.get("placements") or []):
                item = {
                    key: value
                    for key, value in placement.items()
                    if key
                    not in (
                        "localX",
                        "localY",
                        "packedWidthMm",
                        "packedDepthMm",
                        "rotationDeg",
                        "packedOutline",
                        "packedAreaMm2",
                    )
                }
                moved = False
                for target_index in range(donor_index):
                    target = sheets[target_index]
                    placed_boxes = _sheet_placed_boxes(target)
                    best = None
                    for rot in rotations:
                        oriented = _oriented_part(item, rot)
                        if oriented["widthMm"] <= 0.0 or oriented["depthMm"] <= 0.0:
                            continue
                        fit = _bottom_left_fit_polygon(
                            placed_boxes,
                            oriented,
                            sheet_w,
                            sheet_h,
                            border,
                            spacing,
                            aabb_only=aabb_only,
                            allow_slide=allow_slide,
                            spatial_index=None,
                            free_rectangles=None,
                        )
                        if fit is None:
                            continue
                        x, y, world_points = fit
                        score = (y, x, abs(float(rot)))
                        if best is None or score < best["score"]:
                            best = {
                                "score": score,
                                "x": x,
                                "y": y,
                                "w": oriented["widthMm"],
                                "h": oriented["depthMm"],
                                "rotationDeg": oriented["rotationDeg"],
                                "points": world_points,
                                "areaMm2": oriented["areaMm2"],
                            }
                    if best is None:
                        continue
                    target.setdefault("placements", []).append(
                        {
                            **item,
                            "localX": best["x"],
                            "localY": best["y"],
                            "packedWidthMm": best["w"],
                            "packedDepthMm": best["h"],
                            "rotationDeg": best["rotationDeg"],
                            "packedOutline": best["points"],
                            "packedAreaMm2": best["areaMm2"],
                        }
                    )
                    moved = True
                    changed = True
                    break
                if not moved:
                    remaining.append(placement)
            donor["placements"] = remaining
        sheets = [sheet for sheet in sheets if sheet.get("placements")]
        if large:
            donor_indices = list(range(max(1, len(sheets) - 2), len(sheets)))
        else:
            donor_indices = list(range(len(sheets) - 1, 0, -1))
    for index, sheet in enumerate(sheets):
        sheet["sheetIndex"] = index
        _recompute_sheet_stats(sheet, sheet_w, sheet_h, border)
    return sheets


def _order_seed(parts):
    identity = "|".join(
        str(p.get("panelId") or p.get("id") or p.get("bodyName") or i)
        for i, p in enumerate(parts)
    )
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _deterministic_orders(parts):
    """Small bounded multi-start set; no global/metaheuristic search."""
    identity = lambda item: str(
        item.get("panelId") or item.get("id") or item.get("bodyName") or ""
    )

    def metrics(item):
        outline = item.get("outline") if isinstance(item.get("outline"), dict) else {}
        width = max(_num(item.get("widthMm")), 0.0)
        depth = max(_num(item.get("depthMm")), 0.0)
        area = _num(outline.get("areaMm2"), width * depth)
        long_side = max(width, depth)
        short_side = max(min(width, depth), 1e-6)
        return area, long_side, short_side, long_side / short_side

    orders = [
        sorted(parts, key=_part_sort_key),
        sorted(
            parts,
            key=lambda item: (
                -metrics(item)[1],
                -metrics(item)[0],
                -metrics(item)[3],
                identity(item),
            ),
        ),
        sorted(
            parts,
            key=lambda item: (
                -metrics(item)[3],
                -metrics(item)[0],
                -metrics(item)[2],
                identity(item),
            ),
        ),
    ]
    unique = []
    signatures = set()
    for order in orders:
        signature = tuple(identity(item) for item in order)
        if signature in signatures:
            continue
        signatures.add(signature)
        unique.append(order)
    return unique


def _pack_job(parts, sheet, params):
    """Pack one material group with bounded deterministic hybrid search."""
    orders = _deterministic_orders(parts)
    # Large groups get two deterministic passes; exact nearby polygon checks
    # remain enabled, but no unbounded order exploration is allowed.
    if len(parts) >= FAST_PACK_PART_THRESHOLD:
        orders = orders[:2]
    if len(parts) >= 100:
        orders = orders[:1]
    best_sheets = []
    best_unplaced = list(parts)
    best_score = _pack_score(best_sheets, best_unplaced)
    ordered = orders[0] if orders else []
    for trial_order in orders:
        sheets, unplaced = _pack_job_ordered(trial_order, sheet, params)
        score = _pack_score(sheets, unplaced)
        if score < best_score:
            best_sheets, best_unplaced, best_score = sheets, unplaced, score
    if len(ordered) < 2 or LOCAL_SEARCH_ATTEMPTS <= 0:
        return best_sheets, best_unplaced

    # Keep large jobs responsive: skip local search past ~40 parts.
    if len(ordered) >= 40:
        return best_sheets, best_unplaced
    if len(ordered) >= 25:
        attempts = 2
    elif len(ordered) >= 15:
        attempts = 4
    else:
        attempts = LOCAL_SEARCH_ATTEMPTS

    rng = random.Random(_order_seed(ordered))
    current = list(ordered)
    for _attempt in range(attempts):
        trial = list(current)
        i, j = rng.sample(range(len(trial)), 2)
        trial[i], trial[j] = trial[j], trial[i]
        sheets, unplaced = _pack_job_ordered(trial, sheet, params)
        score = _pack_score(sheets, unplaced)
        if score < best_score:
            best_sheets, best_unplaced = sheets, unplaced
            best_score = score
            current = trial
    return best_sheets, best_unplaced


def sheet_pack_layout(
    items,
    sheet_params,
    origin_x_mm,
    origin_y_mm,
):
    """Pack items onto per-boardType sheets and map into Nesting Zone world XY.

    Item fields: id, boardTypeTag, colorTag, widthMm, depthMm, outline(+passthrough).
    Placement targetX/Y is the packed body's minimum XY corner in world mm.
    """
    params = normalize_sheet_params(sheet_params)
    origin_x = _num(origin_x_mm)
    origin_y = _num(origin_y_mm)
    sheet_gap = float(params["sheetGapMm"])

    jobs = {}
    outline_counts = {"flatBody": 0, "metadataSvg": 0, "rectangle": 0, "other": 0}
    for item in items or []:
        width = max(_num((item or {}).get("widthMm")), 0.0)
        depth = max(_num((item or {}).get("depthMm")), 0.0)
        if width <= 0.0 or depth <= 0.0:
            continue
        normalized = dict(item)
        normalized["widthMm"] = width
        normalized["depthMm"] = depth
        normalized["boardTypeTag"] = _tag(normalized.get("boardTypeTag"))
        normalized["colorTag"] = _tag(normalized.get("colorTag"))
        outline = normalized.get("outline")
        if not isinstance(outline, dict) or not outline.get("points"):
            outline = build_outline_payload(
                rectangle_polygon(width, depth), "rectangle", width, depth
            )
            normalized["outline"] = outline
        source = str((outline or {}).get("source") or "other")
        if source in outline_counts:
            outline_counts[source] += 1
        else:
            outline_counts["other"] += 1
        jobs.setdefault(_job_key(normalized), []).append(normalized)

    placements = []
    groups = []
    sheets_summary = []
    unplaced = []
    type_cursor_y = origin_y
    max_x = origin_x
    max_y = origin_y
    global_group_index = 0
    true_shape_count = outline_counts["flatBody"] + outline_counts["metadataSvg"]

    for job_index, key in enumerate(sorted(jobs)):
        board_type, color = key
        sheet = sheet_size_for_type(params, board_type)
        packed_sheets, job_unplaced = _pack_job(jobs[key], sheet, params)
        unplaced.extend(job_unplaced)

        sheet_cursor_x = origin_x
        sheet_cursor_y = type_cursor_y
        row_height = 0.0
        layout_width = float(params.get("layoutWidthMm") or 0.0)
        for local_sheet in packed_sheets:
            sheet_w = float(local_sheet["widthMm"])
            sheet_h = float(local_sheet["heightMm"])
            if (
                layout_width > 0.0
                and sheet_cursor_x > origin_x + 1e-9
                and sheet_cursor_x + sheet_w > origin_x + layout_width + 1e-9
            ):
                sheet_cursor_x = origin_x
                sheet_cursor_y += row_height + sheet_gap
                row_height = 0.0
            sheet_origin_x = sheet_cursor_x
            sheet_origin_y = sheet_cursor_y
            sheet_index_global = len(sheets_summary)
            item_index = 0
            for local in local_sheet["placements"]:
                placement = {
                    **local,
                    "groupIndex": global_group_index,
                    "itemIndex": item_index,
                    "sheetIndex": sheet_index_global,
                    "sheetLocalIndex": local_sheet["sheetIndex"],
                    "groupKey": {
                        "boardTypeTag": board_type,
                        "colorTag": color,
                    },
                    "sheetOriginX": sheet_origin_x,
                    "sheetOriginY": sheet_origin_y,
                    "sheetWidthMm": sheet_w,
                    "sheetHeightMm": sheet_h,
                    "targetX": sheet_origin_x + float(local["localX"]),
                    "targetY": sheet_origin_y + float(local["localY"]),
                    "targetZ": 0.0,
                    "rotationDeg": float(local.get("rotationDeg") or 0.0),
                }
                placements.append(placement)
                item_index += 1

            sheets_summary.append(
                {
                    **{k: v for k, v in local_sheet.items() if k != "placements"},
                    "sheetIndex": sheet_index_global,
                    "boardTypeTag": board_type,
                    "colorTag": color,
                    "originX": sheet_origin_x,
                    "originY": sheet_origin_y,
                    "jobIndex": job_index,
                }
            )
            groups.append(
                {
                    "groupIndex": global_group_index,
                    "boardTypeTag": board_type,
                    "colorTag": color,
                    "sheetIndex": sheet_index_global,
                    "originX": sheet_origin_x,
                    "originY": sheet_origin_y,
                    "widthMm": sheet_w,
                    "depthMm": sheet_h,
                    "count": local_sheet["count"],
                    "utilization": local_sheet["utilization"],
                }
            )
            global_group_index += 1
            sheet_cursor_x += sheet_w + sheet_gap
            row_height = max(row_height, sheet_h)
            max_x = max(max_x, sheet_origin_x + sheet_w)
            max_y = max(max_y, sheet_origin_y + sheet_h)

        if packed_sheets:
            type_cursor_y = sheet_cursor_y + row_height + sheet_gap

    return {
        "engine": ENGINE_NAME,
        "placements": placements,
        "groups": groups,
        "sheets": sheets_summary,
        "unplaced": unplaced,
        "requiredWidthMm": max(max_x - origin_x, 0.0),
        "requiredDepthMm": max(max_y - origin_y, 0.0),
        "borderMm": params["borderMm"],
        "spacingMm": params["spacingMm"],
        "allowRotation": params["allowRotation"],
        "allowPartsInPart": params["allowPartsInPart"],
        "partsInPartApplied": any(
            bool(placement.get("nestedInHole")) for placement in placements
        ),
        "nestedInHoleCount": sum(
            1 for placement in placements if placement.get("nestedInHole")
        ),
        "holeOutlineCount": sum(
            len(((item.get("outline") or {}).get("holes") or []))
            for item in (items or [])
            if isinstance(item.get("outline"), dict)
        ),
        "sheetGapMm": params["sheetGapMm"],
        "sheetParams": params,
        "outlineCounts": outline_counts,
        "trueShapeCount": true_shape_count,
        "rectangleFallbackCount": outline_counts.get("rectangle", 0),
        "localSearchAttempts": LOCAL_SEARCH_ATTEMPTS,
    }
