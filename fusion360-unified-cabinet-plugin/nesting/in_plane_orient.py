"""In-plane Lay Flat orientation after the machining face is +Z.

No grain: longest bbox edge along +X (existing behaviour).
Grain set: rotate so the edge matching grainAlongMm lies along +X, so every
grained board faces the same way for visual check and .cnjob export.
"""

from __future__ import annotations


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


def grain_mm_from_metadata(metadata):
    meta = metadata if isinstance(metadata, dict) else {}
    classification = meta.get("classification") if isinstance(meta.get("classification"), dict) else {}
    state = classification.get("grainAlongMm")
    if isinstance(state, dict):
        cleaned = clean_grain_mm(state.get("value"))
        if cleaned != "":
            return cleaned
    derived = meta.get("derivedTags") if isinstance(meta.get("derivedTags"), dict) else {}
    typed = meta.get("typedTags") if isinstance(meta.get("typedTags"), dict) else {}
    return clean_grain_mm(derived.get("grainAlongMm") or typed.get("grainAlongMm") or meta.get("grainAlongMm"))


def in_plane_rotation_deg(width_mm, depth_mm, grain_along_mm=None):
    """Return 0 or -90 after milling-up.

    Grain boards: the edge closest to grainAlongMm goes to +X.
    Ungrained boards: the longer edge goes to +X.
    """
    width = float(width_mm or 0.0)
    depth = float(depth_mm or 0.0)
    grain = clean_grain_mm(grain_along_mm)
    if grain != "":
        if abs(depth - grain) + 1e-6 < abs(width - grain):
            return -90.0
        return 0.0
    if depth > width + 1e-6:
        return -90.0
    return 0.0


def swap_if_rotated(width_mm, depth_mm, rotation_deg):
    if abs(float(rotation_deg or 0.0)) > 1e-6:
        return float(depth_mm or 0.0), float(width_mm or 0.0)
    return float(width_mm or 0.0), float(depth_mm or 0.0)


def grain_angle_deg(width_mm, depth_mm, grain_along_mm, rotation_deg=0.0):
    """Flattened grain angle: 0 = along +X, 90 = along +Y. None if no grain."""
    grain = clean_grain_mm(grain_along_mm)
    if grain == "":
        return None
    width, depth = swap_if_rotated(width_mm, depth_mm, rotation_deg)
    if abs(depth - grain) + 1e-6 < abs(width - grain):
        return 90
    return 0
