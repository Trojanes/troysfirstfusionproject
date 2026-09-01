"""CAD line/arc segments for manufacturing export.

Tessellated ``points`` stay for nesting and old OmniCam builds.
``segments`` carry exact Fusion Line3D / Arc3D / Circle3D so CAM can
offset and emit G1/G2 instead of guessing arcs from a polyline.
"""

from __future__ import annotations

import math


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _xy(value):
    if isinstance(value, dict):
        return [_num(value.get("x")), _num(value.get("y"))]
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return [_num(value[0]), _num(value[1])]
    return None


def _same(a, b, tol=1e-6):
    return a is not None and b is not None and (
        abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol
    )


def line_segment(start, end):
    a, b = _xy(start), _xy(end)
    if a is None or b is None:
        return None
    return {
        "type": "line",
        "start": [round(a[0], 4), round(a[1], 4)],
        "end": [round(b[0], 4), round(b[1], 4)],
    }


def arc_segment(start, end, center, radius_mm, cw):
    a, b, c = _xy(start), _xy(end), _xy(center)
    if a is None or b is None or c is None:
        return None
    radius = _num(radius_mm)
    if radius <= 1e-6:
        return line_segment(a, b)
    return {
        "type": "arc",
        "start": [round(a[0], 4), round(a[1], 4)],
        "end": [round(b[0], 4), round(b[1], 4)],
        "center": [round(c[0], 4), round(c[1], 4)],
        "radiusMm": round(radius, 4),
        "cw": bool(cw),
    }


def circle_segment(center, radius_mm, start=None, cw=False):
    c = _xy(center)
    radius = _num(radius_mm)
    if c is None or radius <= 1e-6:
        return None
    origin = _xy(start) or [c[0] + radius, c[1]]
    return {
        "type": "circle",
        "start": [round(origin[0], 4), round(origin[1], 4)],
        "end": [round(origin[0], 4), round(origin[1], 4)],
        "center": [round(c[0], 4), round(c[1], 4)],
        "radiusMm": round(radius, 4),
        "cw": bool(cw),
    }


def normalize_segment(raw):
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("type") or "").strip().lower()
    if kind == "line":
        return line_segment(raw.get("start"), raw.get("end"))
    if kind == "circle":
        return circle_segment(
            raw.get("center"),
            raw.get("radiusMm"),
            start=raw.get("start"),
            cw=raw.get("cw"),
        )
    if kind == "arc":
        return arc_segment(
            raw.get("start"),
            raw.get("end"),
            raw.get("center"),
            raw.get("radiusMm"),
            raw.get("cw"),
        )
    return None


def normalize_segments(raw):
    out = []
    for item in raw or []:
        seg = normalize_segment(item)
        if seg is not None:
            out.append(seg)
    return out


def segments_are_complete(segments, min_count=1):
    segs = normalize_segments(segments)
    if len(segs) < min_count:
        return False
    for seg in segs:
        if seg["type"] not in ("line", "arc", "circle"):
            return False
        if seg["type"] != "line" and _num(seg.get("radiusMm")) <= 0:
            return False
    return True


def translate_segment(seg, dx, dy):
    item = normalize_segment(seg)
    if item is None:
        return None

    def shift(pt):
        return [round(_num(pt[0]) + dx, 4), round(_num(pt[1]) + dy, 4)]

    item["start"] = shift(item["start"])
    item["end"] = shift(item["end"])
    if item.get("center") is not None:
        item["center"] = shift(item["center"])
    return item


def translate_segments(segments, dx, dy):
    out = []
    for seg in segments or []:
        item = translate_segment(seg, dx, dy)
        if item is not None:
            out.append(item)
    return out


def rotate_point(x, y, degrees):
    angle = math.radians(_num(degrees))
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return [x * cos_a - y * sin_a, x * sin_a + y * cos_a]


def rotate_segment(seg, degrees):
    item = normalize_segment(seg)
    if item is None:
        return None

    def spin(pt):
        xy = rotate_point(_num(pt[0]), _num(pt[1]), degrees)
        return [round(xy[0], 4), round(xy[1], 4)]

    item["start"] = spin(item["start"])
    item["end"] = spin(item["end"])
    if item.get("center") is not None:
        item["center"] = spin(item["center"])
    return item


def rotate_segments(segments, degrees):
    if abs(_num(degrees)) <= 1e-12:
        return normalize_segments(segments)
    out = []
    for seg in segments or []:
        item = rotate_segment(seg, degrees)
        if item is not None:
            out.append(item)
    return out


def reverse_segment(seg):
    item = normalize_segment(seg)
    if item is None:
        return None
    if item["type"] == "circle":
        item["cw"] = not bool(item.get("cw"))
        return item
    start, end = item["end"], item["start"]
    item["start"] = start
    item["end"] = end
    if item["type"] == "arc":
        item["cw"] = not bool(item.get("cw"))
    return item


def reverse_segments(segments):
    out = []
    for seg in reversed(list(segments or [])):
        item = reverse_segment(seg)
        if item is not None:
            out.append(item)
    return out


def cw_from_samples(center, samples):
    """True when samples travel clockwise around center (Y-up)."""
    c = _xy(center)
    pts = [_xy(p) for p in (samples or []) if _xy(p) is not None]
    if c is None or len(pts) < 2:
        return False
    area = 0.0
    for i in range(len(pts) - 1):
        x0, y0 = pts[i][0] - c[0], pts[i][1] - c[1]
        x1, y1 = pts[i + 1][0] - c[0], pts[i + 1][1] - c[1]
        area += x0 * y1 - x1 * y0
    return area < 0.0


def lines_from_samples(points, min_len=1e-6):
    """Fallback: one line per consecutive sample pair (splines / unknown)."""
    pts = [_xy(p) for p in (points or []) if _xy(p) is not None]
    out = []
    for i in range(len(pts) - 1):
        if math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]) < min_len:
            continue
        item = line_segment(pts[i], pts[i + 1])
        if item is not None:
            out.append(item)
    return out
