"""Persist Lay Flat Board Type / Color overrides across Lay Flat rebuilds.

Re-running Lay Flat deletes LAY_FLAT copies and rebuilds from source panels.
Manual edits made on LAY_FLAT (or poorly synced sources) would otherwise vanish.
Overrides are keyed by exact source lineage (entity token, with occurrence-path
fallback), never by ``panelId``. Panel ids are not unique in legacy projects
(``manual.Body1`` is especially common), so panel-id keys can fan one edit out
to dozens of unrelated boards.
"""

from __future__ import annotations

import json

OVERRIDE_GROUP = "UnifiedCabinet"
OVERRIDE_ATTR = "layFlatTagOverridesJson"


def _clean(value):
    return str(value or "").strip().lower()


def override_key(
    source_entity_token="",
    source_occurrence_path=None,
    source_body_name="",
):
    """Return a collision-safe key for one source body, or ``""``."""
    token = str(source_entity_token or "").strip()
    if token:
        return "token:{}".format(token)
    name = str(source_body_name or "").strip()
    if name and isinstance(source_occurrence_path, (list, tuple)):
        try:
            path = "/".join(str(int(value)) for value in source_occurrence_path)
        except Exception:
            path = ""
        return "path:{}|{}".format(path, name)
    return ""


def override_key_from_item(item):
    if not isinstance(item, dict):
        return ""
    nested = item.get("sourceRef")
    source = nested if isinstance(nested, dict) else item
    return override_key(
        source.get("entityToken")
        or source.get("sourceEntityToken")
        or item.get("sourceEntityToken")
        or item.get("entityToken"),
        (
            source.get("occurrencePath")
            if "occurrencePath" in source
            else source.get("sourceOccurrencePath")
        )
        if (
            "occurrencePath" in source
            or "sourceOccurrencePath" in source
        )
        else (
            item.get("sourceOccurrencePath")
            if "sourceOccurrencePath" in item
            else item.get("occurrencePath")
        ),
        source.get("bodyName")
        or source.get("sourceBodyName")
        or item.get("sourceBodyName")
        or item.get("bodyName"),
    )


def override_for_record(overrides, record):
    """Return the exact override for a source scan record."""
    key = override_key_from_item(record)
    return (overrides or {}).get(key) if key else None


def is_lineage_key(key):
    text = str(key or "").strip()
    return text.startswith("token:") or text.startswith("path:")


def normalize_override(entry):
    if not isinstance(entry, dict):
        return None
    board = _clean(entry.get("boardTypeTag") or entry.get("boardType"))
    color = _clean(entry.get("colorTag") or entry.get("color"))
    if not board and not color:
        return None
    out = {}
    if board and board != "unknown":
        out["boardTypeTag"] = board
    if color and color != "unknown":
        out["colorTag"] = color
    if not out:
        return None
    source = _clean(entry.get("source")) or "manual"
    out["source"] = source
    return out


def is_complete_manual_override(entry):
    """True only for explicit Apply-Tags edits (both Board Type and Color).

    Partial / bulk-harvested rows are unsafe to re-apply on Lay Flat rebuild:
    they collapse color columns (e.g. everything → white_stipple).
    """
    normalized = normalize_override(entry)
    if not normalized:
        return False
    if normalized.get("source") not in ("manual", "apply", "apply_tags"):
        return False
    return bool(normalized.get("boardTypeTag") and normalized.get("colorTag"))


def filter_complete_manual_overrides(overrides):
    cleaned = {}
    for key, value in (overrides or {}).items():
        lineage_key = str(key or "").strip()
        if is_lineage_key(lineage_key) and is_complete_manual_override(value):
            cleaned[lineage_key] = normalize_override(value)
    return cleaned


def merge_override_maps(base, updates):
    """Return a new map with ``updates`` layered onto ``base``."""
    merged = {}
    for key, value in (base or {}).items():
        panel_id = str(key or "").strip()
        normalized = normalize_override(value)
        if panel_id and normalized:
            merged[panel_id] = normalized
    for key, value in (updates or {}).items():
        panel_id = str(key or "").strip()
        normalized = normalize_override(value)
        if not panel_id or not normalized:
            continue
        current = dict(merged.get(panel_id) or {})
        current.update(normalized)
        merged[panel_id] = current
    return merged


def harvest_overrides_from_items(items):
    """Build override map from iterable of tag dicts.

    Each item needs exact source lineage plus Board Type / Color. A panelId-only
    item is intentionally rejected because panel ids can collide.
    """
    updates = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        lineage_key = override_key_from_item(item)
        if not lineage_key:
            continue
        normalized = normalize_override(item)
        if normalized:
            updates[lineage_key] = normalized
    return updates


def apply_override_to_tags(board_type_tag, color_tag, override):
    """Return (board, color) with override values winning when present."""
    board = _clean(board_type_tag)
    color = _clean(color_tag)
    override = normalize_override(override) or {}
    if override.get("boardTypeTag"):
        board = override["boardTypeTag"]
    if override.get("colorTag"):
        color = override["colorTag"]
    return board, color


def apply_override_to_metadata(metadata, override):
    """Return metadata dict with classification tags forced from override."""
    try:
        from panel_attributes import attribute_state_service as attr_state
    except Exception:
        try:
            import attribute_state_service as attr_state  # type: ignore
        except Exception:
            attr_state = None
    override = normalize_override(override) or {}
    if not override:
        return metadata if isinstance(metadata, dict) else {}
    working = dict(metadata) if isinstance(metadata, dict) else {}
    if attr_state is not None:
        try:
            working = attr_state.migrate_metadata(working)
        except Exception:
            pass
        if override.get("boardTypeTag") and callable(
            getattr(attr_state, "apply_board_type", None)
        ):
            working, _ = attr_state.apply_board_type(
                working,
                override["boardTypeTag"],
                source="manual",
                lock=True,
                force=True,
            )
        if override.get("colorTag") and callable(
            getattr(attr_state, "apply_color", None)
        ):
            working, _ = attr_state.apply_color(
                working,
                override["colorTag"],
                source="manual",
                lock=True,
                force=True,
            )
        return working
    # Fusion-free fallback mirrors.
    classification = working.setdefault("classification", {})
    if not isinstance(classification, dict):
        classification = {}
        working["classification"] = classification
    if override.get("boardTypeTag"):
        classification["boardType"] = {
            "value": override["boardTypeTag"],
            "source": "manual",
            "locked": True,
        }
    if override.get("colorTag"):
        classification["color"] = {
            "value": override["colorTag"],
            "source": "manual",
            "locked": True,
        }
    derived = working.setdefault("derivedTags", {})
    if not isinstance(derived, dict):
        derived = {}
        working["derivedTags"] = derived
    if override.get("boardTypeTag"):
        derived["boardTypeTag"] = override["boardTypeTag"]
    if override.get("colorTag"):
        derived["colorTag"] = override["colorTag"]
    return working


def load_overrides(root_component):
    if root_component is None:
        return {}
    try:
        from nesting.fusion_layout import _attr
    except Exception:
        try:
            from fusion_layout import _attr  # type: ignore
        except Exception:
            return {}
    try:
        raw = str(_attr(root_component, OVERRIDE_GROUP, OVERRIDE_ATTR) or "")
    except Exception:
        raw = ""
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    return merge_override_maps({}, payload)


def save_overrides(root_component, overrides):
    if root_component is None:
        return False
    cleaned = merge_override_maps({}, overrides or {})
    try:
        from nesting.fusion_layout import _set_attr
    except Exception:
        try:
            from fusion_layout import _set_attr  # type: ignore
        except Exception:
            return False
    try:
        _set_attr(
            root_component,
            OVERRIDE_GROUP,
            OVERRIDE_ATTR,
            json.dumps(cleaned, ensure_ascii=False, separators=(",", ":")),
        )
        return True
    except Exception:
        return False
