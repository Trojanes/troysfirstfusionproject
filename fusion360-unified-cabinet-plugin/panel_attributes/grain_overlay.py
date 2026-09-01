"""Fusion-free wood-grain hatch overlay on the two broad faces.

Uses the same bbox + grainAlongMm rules as grain_direction. No face walk, no UV.
Grain is an axis, not a one-way arrow — draw parallel strokes.
"""

from __future__ import annotations

import grain_direction

OVERLAY_GROUP_ID = "UC_GrainOverlay"
OVERLAY_ATTR_GROUP = "UnifiedCabinet"
OVERLAY_ATTR_NAME = "grainOverlayOn"
GRAIN_MM_ATTR_NAME = "grainAlongMm"

_OUTWARD_MM = 2.4
_OUTWARD_TOP_MM = 6.0
_INSET_RATIO = 0.08
_CROSS_COVER = 0.58
_HATCH_COUNT = 5
_MIN_HATCH = 3
_AXIS_INDEX = {"x": 0, "y": 1, "z": 2}


def clean_grain_mm(value):
    if isinstance(value, dict):
        value = value.get("value")
    if value in (None, ""):
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return ""
    if number <= 1e-6:
        return ""
    return round(number, 2)


def grain_mm_from_any(metadata):
    """Read grainAlongMm from classification, tags, dimensions, or outline cache."""
    meta = metadata if isinstance(metadata, dict) else {}
    classification = meta.get("classification") if isinstance(meta.get("classification"), dict) else {}
    state = classification.get("grainAlongMm")
    cleaned = clean_grain_mm(state.get("value") if isinstance(state, dict) else state)
    if cleaned != "":
        return cleaned
    derived = meta.get("derivedTags") if isinstance(meta.get("derivedTags"), dict) else {}
    typed = meta.get("typedTags") if isinstance(meta.get("typedTags"), dict) else {}
    cleaned = clean_grain_mm(
        derived.get("grainAlongMm") or typed.get("grainAlongMm") or meta.get("grainAlongMm")
    )
    if cleaned != "":
        return cleaned
    dims = meta.get("dimensions") if isinstance(meta.get("dimensions"), dict) else {}
    cleaned = clean_grain_mm(dims.get("grainAlongMm"))
    if cleaned != "":
        return cleaned
    cache = meta.get("nestingFlatOutline") if isinstance(meta.get("nestingFlatOutline"), dict) else {}
    cleaned = clean_grain_mm(cache.get("grainAlongMm"))
    if cleaned != "":
        return cleaned
    outline = cache.get("outline") if isinstance(cache.get("outline"), dict) else {}
    if not outline:
        outline = meta.get("outline") if isinstance(meta.get("outline"), dict) else {}
    return clean_grain_mm(outline.get("grainAlongMm"))


def resolve_grain_axis(dx, dy, dz, grain_mm):
    """Return 'x'/'y'/'z' for the face edge closest to grainAlongMm, or None."""
    try:
        grain = float(grain_mm)
    except (TypeError, ValueError):
        return None
    if grain <= 1e-6:
        return None
    grain = round(grain, 2)
    detail = grain_direction.describe_face_edges(dx, dy, dz)
    candidates = []
    for axis, length in (
        ("x", detail.get("alongXMm")),
        ("y", detail.get("alongYMm")),
        ("z", detail.get("alongZMm")),
    ):
        if length is None:
            continue
        candidates.append((abs(round(float(length), 2) - grain), axis))
    if not candidates:
        return None
    candidates.sort()
    return candidates[0][1]


def merge_roster(roster, updates):
    """Merge {key: grain_mm}. Empty / None removes the key."""
    next_roster = dict(roster or {})
    for key, grain in (updates or {}).items():
        if not key:
            continue
        if grain in (None, ""):
            next_roster.pop(key, None)
            continue
        try:
            number = float(grain)
        except (TypeError, ValueError):
            next_roster.pop(key, None)
            continue
        if number <= 1e-6:
            next_roster.pop(key, None)
            continue
        next_roster[key] = round(number, 2)
    return next_roster


def _axis_tuple(min_pt, max_pt):
    mins = [
        min(float(min_pt[0]), float(max_pt[0])),
        min(float(min_pt[1]), float(max_pt[1])),
        min(float(min_pt[2]), float(max_pt[2])),
    ]
    maxs = [
        max(float(min_pt[0]), float(max_pt[0])),
        max(float(min_pt[1]), float(max_pt[1])),
        max(float(min_pt[2]), float(max_pt[2])),
    ]
    return mins, maxs


def overlay_segments_mm(min_pt, max_pt, grain_mm):
    """Return parallel grain strokes (mm) on both broad faces.

    Each item is ((x, y, z), (x, y, z)). Empty when grain is unset.
    """
    mins, maxs = _axis_tuple(min_pt, max_pt)
    dx = maxs[0] - mins[0]
    dy = maxs[1] - mins[1]
    dz = maxs[2] - mins[2]
    axis = resolve_grain_axis(dx, dy, dz, grain_mm)
    if axis is None:
        return []
    detail = grain_direction.describe_face_edges(dx, dy, dz)
    thick = detail.get("thicknessAxis")
    if thick not in _AXIS_INDEX or axis not in _AXIS_INDEX:
        return []
    grain_i = _AXIS_INDEX[axis]
    thick_i = _AXIS_INDEX[thick]
    if grain_i == thick_i:
        return []
    other_i = next(index for index in range(3) if index not in (grain_i, thick_i))

    grain_len = maxs[grain_i] - mins[grain_i]
    cross_len = maxs[other_i] - mins[other_i]
    if grain_len <= 1e-6 or cross_len <= 1e-6:
        return []
    inset = max(grain_len * _INSET_RATIO, 6.0)
    if inset * 2 >= grain_len:
        inset = grain_len * 0.12
    start_g = mins[grain_i] + inset
    end_g = maxs[grain_i] - inset

    hatch = _HATCH_COUNT if cross_len >= 90.0 else _MIN_HATCH
    cover = cross_len * _CROSS_COVER
    if cover < 12.0:
        cover = min(cross_len * 0.8, max(cross_len - 4.0, 4.0))
    mid_cross = (mins[other_i] + maxs[other_i]) * 0.5
    if hatch == 1:
        offsets = [mid_cross]
    else:
        span = cover
        first = mid_cross - span * 0.5
        step = span / float(hatch - 1)
        offsets = [first + step * index for index in range(hatch)]

    segments = []
    for thick_val, sign in ((mins[thick_i], -1.0), (maxs[thick_i], 1.0)):
        lift = _OUTWARD_TOP_MM if sign > 0 else _OUTWARD_MM
        face = thick_val + sign * lift
        for cross in offsets:
            start = [0.0, 0.0, 0.0]
            tip = [0.0, 0.0, 0.0]
            start[thick_i] = face
            tip[thick_i] = face
            start[other_i] = cross
            tip[other_i] = cross
            start[grain_i] = start_g
            tip[grain_i] = end_g
            segments.append((tuple(start), tuple(tip)))
    return segments


def flatten_coords_cm(segments):
    """CustomGraphics line pairs in centimetres (isLineStrip=False)."""
    coords = []
    for start, tip in segments or []:
        coords.extend(
            (
                float(start[0]) / 10.0,
                float(start[1]) / 10.0,
                float(start[2]) / 10.0,
                float(tip[0]) / 10.0,
                float(tip[1]) / 10.0,
                float(tip[2]) / 10.0,
            )
        )
    return coords
