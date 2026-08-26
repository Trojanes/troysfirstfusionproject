"""Wood-grain edge length from a panel bbox (Fusion-free).

UI 横/竖 is relative to world +Z. Metadata stores only the matching face-edge
length (mm), never the words horizontal / vertical.
"""

from __future__ import annotations


ORIENT_NONE = "none"
ORIENT_HORIZONTAL = "horizontal"
ORIENT_VERTICAL = "vertical"
_VERTICAL_ALIASES = frozenset({"vertical", "竖", "along_z"})
_HORIZONTAL_ALIASES = frozenset({"horizontal", "横", "across_z"})
_NONE_ALIASES = frozenset({"", "none", "无", "clear", "off"})


def normalize_orientation(value):
    text = str(value or "").strip().lower()
    if text in _NONE_ALIASES:
        return ORIENT_NONE
    if text in _VERTICAL_ALIASES:
        return ORIENT_VERTICAL
    if text in _HORIZONTAL_ALIASES:
        return ORIENT_HORIZONTAL
    raise ValueError("orientation must be none, horizontal (横), or vertical (竖).")


def _span_tuple(dx, dy, dz):
    return (
        ("x", float(dx)),
        ("y", float(dy)),
        ("z", float(dz)),
    )


def describe_face_edges(dx, dy, dz):
    """Split bbox spans into thickness + the two broad-face edges.

    Axis-aligned cabinets: shortest span is thickness.
    Standing (thickness is X or Y): 竖 follows Z, 横 follows the other face edge.
    Lying (thickness is Z): top-view 横 follows X, 竖 follows Y.
    """
    spans = _span_tuple(dx, dy, dz)
    if any(length <= 1e-6 for _axis, length in spans):
        raise ValueError("Body bounding box is degenerate.")
    thickness_axis, thickness_mm = min(spans, key=lambda item: item[1])
    along_x_mm = round(float(dx), 2)
    along_y_mm = round(float(dy), 2)
    along_z_mm = round(float(dz), 2)
    face = [(axis, length) for axis, length in spans if axis != thickness_axis]
    if thickness_axis == "z":
        return {
            "thicknessAxis": thickness_axis,
            "thicknessMm": round(thickness_mm, 2),
            "alongXMm": along_x_mm,
            "alongYMm": along_y_mm,
            "alongZMm": None,
            "acrossZMm": None,
            "faceEdgesMm": [along_x_mm, along_y_mm],
            "standing": False,
        }
    across = next((length for axis, length in face if axis != "z"), None)
    if across is None:
        raise ValueError("Could not resolve the face edge across Z.")
    return {
        "thicknessAxis": thickness_axis,
        "thicknessMm": round(thickness_mm, 2),
        "alongXMm": along_x_mm if thickness_axis != "x" else None,
        "alongYMm": along_y_mm if thickness_axis != "y" else None,
        "alongZMm": along_z_mm,
        "acrossZMm": round(float(across), 2),
        "faceEdgesMm": [along_z_mm, round(float(across), 2)],
        "standing": True,
    }


def resolve_grain_along_mm(dx, dy, dz, orientation):
    """Return the face-edge length (mm) that grain follows.

    Standing panel: 竖 = along Z, 横 = the other face edge.
    Lying panel (thickness along Z, top view): 横 = along X, 竖 = along Y.
    """
    key = normalize_orientation(orientation)
    if key == ORIENT_NONE:
        return None, describe_face_edges(dx, dy, dz)
    detail = describe_face_edges(dx, dy, dz)
    if detail["standing"]:
        if key == ORIENT_VERTICAL:
            return detail["alongZMm"], detail
        return detail["acrossZMm"], detail
    if key == ORIENT_VERTICAL:
        return detail["alongYMm"], detail
    return detail["alongXMm"], detail


def body_bbox_spans_mm(body):
    """World-axis bbox spans in millimetres (Fusion cm × 10)."""
    bbox = getattr(body, "boundingBox", None)
    if bbox is None:
        raise ValueError("Body has no bounding box.")
    try:
        min_pt = bbox.minPoint
        max_pt = bbox.maxPoint
        dx = abs(float(max_pt.x) - float(min_pt.x)) * 10.0
        dy = abs(float(max_pt.y) - float(min_pt.y)) * 10.0
        dz = abs(float(max_pt.z) - float(min_pt.z)) * 10.0
    except Exception as exc:
        raise ValueError("Could not read body bounding box.") from exc
    return dx, dy, dz


def grain_along_mm_for_body(body, orientation):
    """Measure a Fusion (or mock) body and resolve grainAlongMm."""
    dx, dy, dz = body_bbox_spans_mm(body)
    return resolve_grain_along_mm(dx, dy, dz, orientation)


def swapped_grain_along_mm(dx, dy, dz, current_grain_mm):
    """Return the other face-edge length (横↔竖). Raises if grain is unset."""
    try:
        current = float(current_grain_mm)
    except (TypeError, ValueError):
        current = 0.0
    if current <= 1e-6:
        raise ValueError("No grainAlongMm to rotate 90°.")
    current = round(current, 2)
    detail = describe_face_edges(dx, dy, dz)
    edges = [round(float(item), 2) for item in (detail.get("faceEdgesMm") or [])]
    if len(edges) < 2:
        raise ValueError("Could not resolve two face edges for grain swap.")
    first, second = edges[0], edges[1]
    if abs(first - current) <= abs(second - current):
        return second
    return first
