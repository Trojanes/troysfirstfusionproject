"""CustomGraphics wood-grain arrows. One group, bbox only, no face walk."""

from __future__ import annotations

import grain_overlay
import metadata_inspector
import tag_metadata_editor
import attribute_state_service
import color_replace

try:
    import adsk.core as adsk_core
    import adsk.fusion as adsk_fusion
except Exception:
    adsk_core = None
    adsk_fusion = None

OVERLAY_RGB = (255, 214, 64)
OVERLAY_WEIGHT = 3.2
_SESSION_ITEMS = {}
GRAIN_MM_ATTR_GROUP = grain_overlay.OVERLAY_ATTR_GROUP
GRAIN_MM_ATTR_NAME = grain_overlay.GRAIN_MM_ATTR_NAME


def load_overlay_visible(root):
    if not root:
        return False
    try:
        attr = root.attributes.itemByName(
            grain_overlay.OVERLAY_ATTR_GROUP, grain_overlay.OVERLAY_ATTR_NAME
        )
        if attr is None or not getattr(attr, "value", None):
            return False
        return str(attr.value).strip().lower() in ("1", "true", "on", "yes")
    except Exception:
        return False


def save_overlay_visible(root, visible):
    if not root:
        return False
    raw = "1" if visible else "0"
    try:
        attrs = root.attributes
        existing = attrs.itemByName(
            grain_overlay.OVERLAY_ATTR_GROUP, grain_overlay.OVERLAY_ATTR_NAME
        )
        if existing is not None:
            existing.value = raw
        else:
            attrs.add(
                grain_overlay.OVERLAY_ATTR_GROUP, grain_overlay.OVERLAY_ATTR_NAME, raw
            )
        return True
    except Exception:
        return False


def clear_overlay(root):
    if not root:
        return 0
    removed = 0
    try:
        graphics = root.customGraphicsGroups
    except Exception:
        return 0
    try:
        for index in range(graphics.count - 1, -1, -1):
            group = graphics.item(index)
            if group is None:
                continue
            group_id = ""
            group_name = ""
            try:
                group_id = str(getattr(group, "id", "") or "")
            except Exception:
                group_id = ""
            try:
                group_name = str(getattr(group, "name", "") or "")
            except Exception:
                group_name = ""
            if group_id == grain_overlay.OVERLAY_GROUP_ID or group_name == grain_overlay.OVERLAY_GROUP_ID:
                group.deleteMe()
                removed += 1
    except Exception:
        return removed
    try:
        if adsk_core is not None:
            app = adsk_core.Application.get()
            viewport = app.activeViewport if app else None
            if viewport is not None:
                viewport.refresh()
    except Exception:
        pass
    return removed


def _body_bbox_mm(body):
    bbox = getattr(body, "boundingBox", None)
    if bbox is None:
        raise ValueError("Body has no bounding box.")
    min_pt = bbox.minPoint
    max_pt = bbox.maxPoint
    return (
        (float(min_pt.x) * 10.0, float(min_pt.y) * 10.0, float(min_pt.z) * 10.0),
        (float(max_pt.x) * 10.0, float(max_pt.y) * 10.0, float(max_pt.z) * 10.0),
    )


def _session_key(body):
    """Originals and LAY_FLAT copies must not share a roster slot."""
    prefix = ""
    try:
        if metadata_inspector._is_lay_flat_workpiece(body):
            prefix = "layflat:"
    except Exception:
        prefix = ""
    try:
        key = metadata_inspector._body_key(body)
    except Exception:
        key = ""
    return prefix + (key or str(id(body)))


def reset_session_items():
    _SESSION_ITEMS.clear()


def rebuild_overlay(root, extra_items=None):
    """Replace the hatch with boards that are ticked grain colors and have grainAlongMm.

    Catalog is the only source of truth. ``extra_items`` are boards this action
    just wrote or resolved from scan records — not a leftover session roster.
    """
    if not root:
        return {
            "ok": False,
            "visible": False,
            "drawnCount": 0,
            "skippedCount": 0,
            "errors": ["No active Fusion design."],
        }
    reset_session_items()
    tags = _grain_color_tags(root)
    if not tags:
        clear_overlay(root)
        save_overlay_visible(root, False)
        return {
            "ok": True,
            "visible": False,
            "drawnCount": 0,
            "skippedCount": 0,
            "warnings": [],
            "errors": [],
            "message": "Grain overlay hidden.",
        }
    segments, drawn, skipped, warnings = collect_overlay_segments(root)
    extra_segs, extra_drawn, extra_skip, extra_warn = _absorb_extra_items(
        extra_items, tags
    )
    segments.extend(extra_segs)
    drawn += extra_drawn
    skipped += extra_skip
    warnings.extend(extra_warn)
    clear_overlay(root)
    if segments:
        try:
            _draw_segments(root, segments)
        except Exception as ex:
            return {
                "ok": False,
                "visible": True,
                "drawnCount": 0,
                "skippedCount": skipped,
                "warnings": warnings,
                "errors": [str(ex)],
                "message": "Could not draw grain overlay.",
            }
    save_overlay_visible(root, True)
    message = "Grain overlay: {} panel(s).".format(drawn)
    if skipped:
        message += " Skipped {}.".format(skipped)
    if not drawn:
        message = "Grain overlay: no ticked grain-color boards with grainAlongMm."
    return {
        "ok": True,
        "visible": True,
        "drawnCount": drawn,
        "skippedCount": skipped,
        "warnings": warnings,
        "errors": [],
        "message": message,
    }


def _grain_color_tags(root):
    try:
        return color_replace.load_grain_color_tags(root)
    except Exception:
        return []


def _color_key_for_body(body):
    metadata, error = tag_metadata_editor._read_body_metadata_raw(body)
    if error or not metadata:
        return ""
    return color_replace.color_key_from_metadata(metadata)


def overlay_lay_flat_copies(root, force=False):
    """Rebuild hatch after Lay Flat. Same catalog rule as color-list ticks."""
    if not root:
        return {
            "ok": True,
            "visible": False,
            "drawnCount": 0,
            "skippedCount": 0,
            "warnings": [],
            "errors": [],
        }
    if not force and not load_overlay_visible(root):
        return {
            "ok": True,
            "visible": False,
            "drawnCount": 0,
            "skippedCount": 0,
            "warnings": [],
            "errors": [],
        }
    return rebuild_overlay(root)


def _collect_lay_flat_bodies(root):
    try:
        from nesting.lay_flat_face_up import collect_lay_flat_bodies
    except Exception:
        try:
            from lay_flat_face_up import collect_lay_flat_bodies
        except Exception:
            return []
    try:
        return collect_lay_flat_bodies(root) or []
    except Exception:
        return []


def _read_grain_attr(body):
    """Tiny UnifiedCabinet/grainAlongMm stamp — readable when JSON metadata is not."""
    if body is None:
        return ""
    candidates = [body]
    try:
        native = getattr(body, "nativeObject", None)
        if native is not None:
            candidates.append(native)
    except Exception:
        pass
    for entity in candidates:
        try:
            attrs = entity.attributes
            attr = attrs.itemByName(GRAIN_MM_ATTR_GROUP, GRAIN_MM_ATTR_NAME) if attrs else None
        except Exception:
            continue
        if attr is None:
            continue
        cleaned = grain_overlay.clean_grain_mm(getattr(attr, "value", None))
        if cleaned != "":
            return cleaned
    return ""


def _grain_mm_for_body(body):
    grain_mm, _color, error = _overlay_fields_for_body(body)
    return grain_mm, error


def _overlay_fields_for_body(body):
    """Return (grain_mm, color_key, error) from one metadata + stamp read."""
    stamped = _read_grain_attr(body)
    metadata, error = tag_metadata_editor._read_body_metadata_raw(body)
    if error:
        return stamped or "", "", error
    grain_mm = stamped or grain_overlay.grain_mm_from_any(metadata)
    if grain_mm in (None, ""):
        grain_mm = attribute_state_service.grain_along_mm_value(metadata)
    color = color_replace.color_key_from_metadata(metadata) if metadata else ""
    return grain_mm, color, None


def iter_overlay_bodies(root):
    """Yield world-space solids using the same occurrence walk as color scan."""
    if root is None:
        return
    sink = []
    seen = set()
    try:
        metadata_inspector._collect_bodies_under_component(
            root, [], root, sink, seen, include_lay_flat=False
        )
    except Exception:
        sink = []
    for body in sink:
        yield body


def segments_for_bodies(items):
    """Build overlay segments from bodies we already measured. No metadata walk."""
    segments = []
    drawn = 0
    skipped = 0
    warnings = []
    for item in items or []:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            body, grain_mm = item[0], item[1]
        elif isinstance(item, dict):
            body = item.get("body")
            grain_mm = item.get("grainAlongMm")
        else:
            continue
        name = str(getattr(body, "name", "") or "") or "body"
        if grain_mm in (None, ""):
            continue
        try:
            min_pt, max_pt = _body_bbox_mm(body)
            body_segments = grain_overlay.overlay_segments_mm(min_pt, max_pt, grain_mm)
        except Exception as ex:
            skipped += 1
            if len(warnings) < 8:
                warnings.append("{}: {}".format(name, ex))
            continue
        if not body_segments:
            skipped += 1
            continue
        segments.extend(body_segments)
        drawn += 1
    return segments, drawn, skipped, warnings


def show_overlay_for_bodies(root, items=None):
    """Compatibility wrapper. Overlay is rebuilt from the catalog plus ``items``."""
    return rebuild_overlay(root, extra_items=items)


def _absorb_extra_items(items, tags):
    """Add just-resolved boards that the assembly walk missed. Dedup by session key."""
    ready = []
    seen = set(_SESSION_ITEMS.keys())
    for item in items or []:
        if isinstance(item, (tuple, list)) and len(item) >= 2:
            body, grain_mm = item[0], item[1]
        elif isinstance(item, dict):
            body = item.get("body")
            grain_mm = item.get("grainAlongMm")
        else:
            continue
        if body is None or grain_mm in (None, ""):
            continue
        key = _session_key(body)
        if key in seen:
            continue
        color = _color_key_for_body(body)
        if color and not color_replace.color_is_grain_color(color, tags):
            continue
        if not color and not tags:
            continue
        seen.add(key)
        ready.append((body, grain_mm))
        _SESSION_ITEMS[key] = (body, grain_mm)
    return segments_for_bodies(ready)


def collect_overlay_segments(root):
    """Measure grained bodies. Returns (segments_cm_flat, drawn, skipped, warnings)."""
    segments = []
    drawn = 0
    skipped = 0
    warnings = []
    bodies = list(iter_overlay_bodies(root))
    seen = set()
    for body in bodies:
        key = _session_key(body)
        if key:
            seen.add(key)
    for body in _collect_lay_flat_bodies(root):
        key = _session_key(body)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        bodies.append(body)
    tags = _grain_color_tags(root)
    for body in bodies:
        name = str(getattr(body, "name", "") or "") or "body"
        grain_mm, color, error = _overlay_fields_for_body(body)
        if error:
            skipped += 1
            if len(warnings) < 8:
                warnings.append("{}: {}".format(name, error))
            continue
        if grain_mm in (None, "") or not color_replace.overlay_eligible(
            color, grain_mm, tags
        ):
            _SESSION_ITEMS.pop(_session_key(body), None)
            continue
        try:
            min_pt, max_pt = _body_bbox_mm(body)
            body_segments = grain_overlay.overlay_segments_mm(min_pt, max_pt, grain_mm)
        except Exception as ex:
            skipped += 1
            if len(warnings) < 8:
                warnings.append("{}: {}".format(name, ex))
            continue
        if not body_segments:
            skipped += 1
            continue
        segments.extend(body_segments)
        drawn += 1
        _SESSION_ITEMS[_session_key(body)] = (body, grain_mm)
    return segments, drawn, skipped, warnings


def _draw_segments(root, segments):
    if adsk_fusion is None or adsk_core is None:
        raise RuntimeError("Fusion API is not available.")
    graphics = root.customGraphicsGroups
    group = graphics.add()
    try:
        group.id = grain_overlay.OVERLAY_GROUP_ID
    except Exception:
        pass
    try:
        group.name = grain_overlay.OVERLAY_GROUP_ID
    except Exception:
        pass
    try:
        group.isSelectable = False
    except Exception:
        pass
    coords = grain_overlay.flatten_coords_cm(segments)
    if not coords:
        return group
    lines = group.addLines(adsk_fusion.CustomGraphicsCoordinates.create(coords), [], False)
    try:
        lines.weight = OVERLAY_WEIGHT
    except Exception:
        pass
    try:
        lines.isSelectable = False
    except Exception:
        pass
    try:
        lines.depthPriority = 10
    except Exception:
        pass
    try:
        color = adsk_core.Color.create(OVERLAY_RGB[0], OVERLAY_RGB[1], OVERLAY_RGB[2], 255)
        lines.color = adsk_fusion.CustomGraphicsSolidColorEffect.create(color)
    except Exception:
        pass
    try:
        app = adsk_core.Application.get()
        viewport = app.activeViewport if app else None
        if viewport is not None:
            viewport.refresh()
    except Exception:
        pass
    return group


def refresh_overlay(root):
    """Redraw from the ticked grain-color catalog."""
    return rebuild_overlay(root)


def refresh_if_visible(root):
    if not load_overlay_visible(root):
        return {
            "ok": True,
            "visible": False,
            "drawnCount": 0,
            "skippedCount": 0,
            "warnings": [],
            "errors": [],
        }
    return refresh_overlay(root)


def set_overlay_visible(root, visible):
    if not root:
        return {
            "ok": False,
            "visible": False,
            "drawnCount": 0,
            "skippedCount": 0,
            "errors": ["No active Fusion design."],
        }
    if not visible:
        reset_session_items()
        clear_overlay(root)
        save_overlay_visible(root, False)
        return {
            "ok": True,
            "visible": False,
            "drawnCount": 0,
            "skippedCount": 0,
            "warnings": [],
            "errors": [],
            "message": "Grain overlay hidden.",
        }
    save_overlay_visible(root, True)
    return rebuild_overlay(root)
