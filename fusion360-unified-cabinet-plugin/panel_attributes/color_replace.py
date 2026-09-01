"""Fusion-free color rename + per-color grain catalog helpers."""

from __future__ import annotations

import json
import re

import attribute_state_service
import tag_metadata_editor

GRAIN_COLORS_ATTR_GROUP = "UnifiedCabinet"
GRAIN_COLORS_ATTR_NAME = "grainColorTags"


def normalize_color_key(value):
    text = str(value or "").strip().lower().replace(" ", "_")
    text = re.sub(r"_+", "_", text).strip("_")
    if not text or attribute_state_service.is_undefined(text):
        return ""
    return text


def color_key_from_metadata(metadata):
    if not isinstance(metadata, dict):
        return ""
    classification = metadata.get("classification")
    color_state = classification.get("color") if isinstance(classification, dict) else {}
    canonical = normalize_color_key((color_state or {}).get("value"))
    if canonical:
        return canonical
    derived = metadata.get("derivedTags") if isinstance(metadata.get("derivedTags"), dict) else {}
    typed = metadata.get("typedTags") if isinstance(metadata.get("typedTags"), dict) else {}
    for raw in (
        derived.get("colorTag"),
        typed.get("colorTag"),
        metadata.get("colorTag"),
    ):
        key = normalize_color_key(raw)
        if key:
            return key
    defaults = metadata.get("defaultAttributes") if isinstance(metadata.get("defaultAttributes"), dict) else {}
    for raw in (
        defaults.get("colorName"),
        defaults.get("doorColorName"),
        metadata.get("colorName"),
    ):
        key = normalize_color_key(tag_metadata_editor.slug_color_tag(raw) or raw)
        if key:
            return key
    return ""


def color_key_from_record(record):
    if not isinstance(record, dict):
        return ""
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    key = color_key_from_metadata(metadata)
    if key:
        return key
    for raw in (
        record.get("colorTag"),
        (record.get("derivedTags") or {}).get("colorTag")
        if isinstance(record.get("derivedTags"), dict)
        else "",
        (record.get("typedTags") or {}).get("colorTag")
        if isinstance(record.get("typedTags"), dict)
        else "",
    ):
        key = normalize_color_key(raw)
        if key:
            return key
    return ""


def grain_mm_from_metadata(metadata):
    if not isinstance(metadata, dict):
        return ""
    return attribute_state_service.grain_along_mm_value(metadata) or ""


def grain_mm_from_record(record):
    if not isinstance(record, dict):
        return ""
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    value = grain_mm_from_metadata(metadata)
    if value != "":
        return value
    derived = record.get("derivedTags") if isinstance(record.get("derivedTags"), dict) else {}
    typed = record.get("typedTags") if isinstance(record.get("typedTags"), dict) else {}
    for raw in (derived.get("grainAlongMm"), typed.get("grainAlongMm"), record.get("grainAlongMm")):
        if raw in (None, ""):
            continue
        return raw
    return ""


def record_has_grain(record):
    return grain_mm_from_record(record) not in (None, "")


def summarize_color_grain(records):
    """Group scanned body records by colorTag for the grain tick list."""
    groups = {}
    for record in records or []:
        if "body" not in str((record or {}).get("entityKind") or "").lower():
            continue
        color = color_key_from_record(record)
        if not color:
            continue
        bucket = groups.setdefault(
            color,
            {"colorTag": color, "bodyCount": 0, "grainCount": 0},
        )
        bucket["bodyCount"] += 1
        if record_has_grain(record):
            bucket["grainCount"] += 1
    rows = []
    for color in sorted(groups):
        bucket = groups[color]
        grain_count = int(bucket["grainCount"])
        body_count = int(bucket["bodyCount"])
        rows.append(
            {
                **bucket,
                "hasGrain": grain_count > 0 and grain_count == body_count,
                "mixed": 0 < grain_count < body_count,
            }
        )
    return rows


def normalize_grain_color_tags(values):
    tags = []
    seen = set()
    for raw in values or []:
        key = normalize_color_key(raw)
        if not key or key in seen:
            continue
        seen.add(key)
        tags.append(key)
    return tags


def load_grain_color_tags(root_component):
    if not root_component:
        return []
    try:
        attr = root_component.attributes.itemByName(
            GRAIN_COLORS_ATTR_GROUP, GRAIN_COLORS_ATTR_NAME
        )
        if attr is None or not getattr(attr, "value", None):
            return []
        data = json.loads(attr.value)
        if isinstance(data, dict):
            data = data.get("tags") or data.get("grainColorTags") or []
        return normalize_grain_color_tags(data)
    except Exception:
        return []


def save_grain_color_tags(root_component, tags):
    cleaned = normalize_grain_color_tags(tags)
    if not root_component:
        return False, cleaned
    raw = json.dumps({"tags": cleaned}, separators=(",", ":"))
    try:
        attrs = root_component.attributes
        existing = attrs.itemByName(GRAIN_COLORS_ATTR_GROUP, GRAIN_COLORS_ATTR_NAME)
        if existing is not None:
            existing.value = raw
        else:
            attrs.add(GRAIN_COLORS_ATTR_GROUP, GRAIN_COLORS_ATTR_NAME, raw)
        return True, cleaned
    except Exception:
        return False, cleaned


def rename_grain_color_tag(tags, from_color, to_color):
    current = normalize_grain_color_tags(tags)
    source = normalize_color_key(from_color)
    dest = normalize_color_key(to_color)
    if not source or source not in current:
        return current
    next_tags = [dest if item == source else item for item in current]
    if dest and dest not in next_tags:
        next_tags.append(dest)
    return normalize_grain_color_tags(next_tags)


def color_is_grain_color(color_key, grain_color_tags):
    """True only when this color is in the design's ticked grain-color list."""
    key = normalize_color_key(color_key)
    if not key:
        return False
    return key in set(normalize_grain_color_tags(grain_color_tags))


def overlay_eligible(color_key, grain_mm, grain_color_tags):
    """Hatch only when grainAlongMm is set and the color is a grain color."""
    if grain_mm in (None, ""):
        return False
    try:
        number = float(grain_mm)
    except (TypeError, ValueError):
        return False
    if number <= 1e-6:
        return False
    return color_is_grain_color(color_key, grain_color_tags)


def metadata_without_grain_along(metadata):
    """Clear grainAlongMm everywhere it is mirrored on a panel payload."""
    working = metadata if isinstance(metadata, dict) else {}
    patched, _result = tag_metadata_editor.apply_grain_along_to_metadata(working, "")
    dims = patched.get("dimensions")
    if isinstance(dims, dict):
        dims.pop("grainAlongMm", None)
        dims.pop("grainAngleDeg", None)
    cache = patched.get("nestingFlatOutline")
    if isinstance(cache, dict):
        cache.pop("grainAlongMm", None)
        outline = cache.get("outline")
        if isinstance(outline, dict):
            outline.pop("grainAlongMm", None)
            outline.pop("grainAngleDeg", None)
    return patched


def record_missing_grain(record, grain_color_tags):
    """True when this board's color requires grain but grainAlongMm is empty."""
    tags = set(normalize_grain_color_tags(grain_color_tags))
    color = color_key_from_record(record)
    if not color or color not in tags:
        return False
    return grain_mm_from_record(record) in (None, "")


def apply_color_rename(metadata, new_color_name):
    """Rename canonical color + display name. Returns (metadata, color_tag, result)."""
    name = str(new_color_name or "").strip()
    color_tag = tag_metadata_editor.slug_color_tag(name)
    if not name or not color_tag:
        raise ValueError("A valid color name is required.")
    working = dict(metadata) if isinstance(metadata, dict) else {}
    defaults = working.get("defaultAttributes")
    if not isinstance(defaults, dict):
        defaults = {}
        working["defaultAttributes"] = defaults
    defaults["colorName"] = name
    if defaults.get("doorColorName"):
        defaults["doorColorName"] = name
    patched, result = attribute_state_service.apply_color(
        working,
        color_tag,
        source="manual",
        lock=True,
        force=True,
    )
    return patched, color_tag, result
