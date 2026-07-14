"""Canonical state, provenance, locks, and compatibility mirrors for panels.

This module is deliberately Fusion-free.  It accepts/returns metadata dicts so
all controller write paths can share the same precedence and migration rules.

Canonical state (same shape for all three Nesting attributes):
* classification.boardType:  {value, source, locked}
* classification.color:      {value, source, locked}
* classification.cuttingFace:{value: MILLING|EITHER|"", source, locked}

Face-level millingSurface roles remain geometry detail under faceRegistry /
face attributes. Writing those roles should also sync classification.cuttingFace.

Generator semantic identity (identity.boardType, e.g. B3 or front_panel) is
never replaced by the high-level board family.

derivedTags / typedTags are read-only compatibility mirrors only.
"""

from __future__ import annotations

import copy
import re


SCHEMA_VERSION = 2
UNDEFINED = frozenset({"", "unknown", "undefined", "unassigned", "none", "n/a"})
KNOWN_CUTTING_FACE = frozenset({"MILLING", "EITHER"})
SOURCE_PRIORITY = {
    "default": 0,
    "thickness": 10,
    "generator": 20,
    "legacy": 20,
    "assembly": 30,
    "geometry": 40,
    "hinge_cups": 50,
    "half_slot": 50,
    "manual": 100,
}

MATERIAL_FOR_TAG = {
    "carcass": "carcass_board",
    "partition": "partition_board",
    "door": "door_board",
}
ROLE_FOR_TAG = {
    "carcass": "carcass",
    "partition": "partition",
    "door": "door",
}


def _ensure_dict(parent, key):
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def _clean(value):
    return str(value or "").strip().lower()


def _clean_cutting_face(value):
    text = str(value or "").strip().upper()
    if text in KNOWN_CUTTING_FACE:
        return text
    if text in ("", "UNASSIGNED", "UNKNOWN", "UNDEFINED", "NONE", "N/A"):
        return ""
    return ""


def is_undefined(value):
    text = _clean(value)
    return (not text) or ("unknown" in text) or text in UNDEFINED


def slug(value, max_len=32):
    text = _clean(value).replace(" ", "_")
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text[: max(1, int(max_len))]


def _material_for_tag(tag):
    tag = _clean(tag)
    return MATERIAL_FOR_TAG.get(tag) or (tag if tag.endswith("_board") else "{}_board".format(tag))


def _role_for_tag(tag):
    tag = _clean(tag)
    return ROLE_FOR_TAG.get(tag) or (tag[:-6] if tag.endswith("_board") else tag)


def _legacy_board_tag(metadata):
    derived = metadata.get("derivedTags") if isinstance(metadata.get("derivedTags"), dict) else {}
    typed = metadata.get("typedTags") if isinstance(metadata.get("typedTags"), dict) else {}
    defaults = metadata.get("defaultAttributes") if isinstance(metadata.get("defaultAttributes"), dict) else {}
    tag = derived.get("boardTypeTag") or typed.get("boardTypeTag")
    if not is_undefined(tag):
        return _clean(tag)
    material = _clean(defaults.get("materialClass"))
    if material.endswith("_board") and len(material) > 6 and not is_undefined(material):
        return material[:-6]
    role = _clean(defaults.get("role"))
    if role in ("door", "front_visible"):
        return "door"
    if role == "partition":
        return "partition"
    if role in ("carcass", "carcass_rail"):
        return "carcass"
    return ""


def _legacy_color_tag(metadata):
    derived = metadata.get("derivedTags") if isinstance(metadata.get("derivedTags"), dict) else {}
    typed = metadata.get("typedTags") if isinstance(metadata.get("typedTags"), dict) else {}
    explicit = derived.get("colorTag") or typed.get("colorTag")
    if not is_undefined(explicit):
        return _clean(explicit)
    defaults = metadata.get("defaultAttributes") if isinstance(metadata.get("defaultAttributes"), dict) else {}
    name = defaults.get("colorName") or defaults.get("doorColorName")
    if name:
        return slug(name)
    if _clean(defaults.get("materialClass")) == "carcass_board":
        return "carcass_colour"
    return ""


def derive_cutting_face_from_registry(metadata):
    """Derive MILLING / EITHER / '' from faceRegistry surface roles."""
    registry = (
        metadata.get("faceRegistry") if isinstance(metadata, dict) else None
    )
    faces = (registry or {}).get("faces") if isinstance(registry, dict) else None
    if not isinstance(faces, list):
        faces = []
    surfaces = [
        face
        for face in faces
        if isinstance(face, dict)
        and (
            face.get("faceClass") == "SURFACE"
            or str(face.get("millingSurface") or "").upper()
            in ("MILLING", "NON_MILLING", "EITHER")
        )
    ]
    if any(
        str(face.get("millingSurface") or "").upper() == "MILLING"
        for face in surfaces
    ):
        return "MILLING"
    if (
        sum(
            1
            for face in surfaces
            if str(face.get("millingSurface") or "").upper() == "EITHER"
        )
        >= 2
    ):
        return "EITHER"
    return ""


def cutting_face_from_surface_roles(role_a, role_b):
    """Map a pair of broad-face milling roles to classification.cuttingFace."""
    roles = [
        str(role_a or "").strip().upper(),
        str(role_b or "").strip().upper(),
    ]
    if "MILLING" in roles:
        return "MILLING"
    if roles.count("EITHER") >= 2:
        return "EITHER"
    return ""


def _infer_legacy_source(metadata):
    if isinstance(metadata.get("_thicknessRule"), dict):
        return "thickness"
    lifecycle = metadata.get("lifecycle") if isinstance(metadata.get("lifecycle"), dict) else {}
    if _clean(lifecycle.get("state")) in ("generated", "module_scanned"):
        return "generator"
    return "legacy"


def _ensure_field_state(state, default_source="legacy"):
    if not isinstance(state, dict):
        state = {}
    state.setdefault("value", "")
    state.setdefault("source", default_source)
    state.setdefault("locked", False)
    return state


def migrate_metadata(metadata, inplace=False):
    """Return a v2-compatible copy without destroying generator semantics.

    Pass ``inplace=True`` when the caller already owns a disposable deep copy
    (e.g. Scan All after face overlay) to avoid a second deepcopy.
    """
    if inplace and isinstance(metadata, dict):
        working = metadata
    else:
        working = copy.deepcopy(metadata) if isinstance(metadata, dict) else {}
    working.setdefault("schemaVersion", 1)
    classification = _ensure_dict(working, "classification")

    board = classification.get("boardType")
    if not isinstance(board, dict):
        tag = _legacy_board_tag(working)
        source = _infer_legacy_source(working) if tag else "default"
        identity = working.get("identity") if isinstance(working.get("identity"), dict) else {}
        # The old Tag Edit synchronizer replaced identity.boardType with the
        # high-level tag. Generator metadata keeps semantic values instead.
        if (
            tag
            and source not in ("generator", "thickness")
            and _clean(identity.get("boardType")) == tag
        ):
            source = "manual"
        board = {
            "value": tag,
            "source": source,
            "locked": source == "manual",
        }
        classification["boardType"] = board
    else:
        board = _ensure_field_state(board)
        classification["boardType"] = board
        # Empty classification shells must not block legacy recovery — otherwise
        # normalize_mirrors strips derivedTags and Nesting/Attributes look
        # like previously-known Color/Board Type "vanished".
        if is_undefined(board.get("value")):
            recovered = _legacy_board_tag(working)
            if recovered:
                board["value"] = recovered
                if board.get("source") in ("", "legacy", "default"):
                    board["source"] = _infer_legacy_source(working)

    color = classification.get("color")
    if not isinstance(color, dict):
        color_tag = _legacy_color_tag(working)
        defaults = working.get("defaultAttributes") if isinstance(working.get("defaultAttributes"), dict) else {}
        source = _infer_legacy_source(working) if color_tag else "default"
        if defaults.get("colorName") or defaults.get("doorColorName"):
            source = "manual"
        color = {
            "value": color_tag,
            "source": source,
            "locked": source == "manual",
        }
        classification["color"] = color
    else:
        color = _ensure_field_state(color)
        classification["color"] = color
        if is_undefined(color.get("value")):
            recovered = _legacy_color_tag(working)
            if recovered:
                color["value"] = recovered
                defaults = working.get("defaultAttributes") if isinstance(working.get("defaultAttributes"), dict) else {}
                if color.get("source") in ("", "legacy", "default"):
                    if defaults.get("colorName") or defaults.get("doorColorName"):
                        color["source"] = "manual"
                    else:
                        color["source"] = _infer_legacy_source(working) if recovered else "legacy"

    registry = _ensure_dict(working, "faceRegistry")
    face_state = registry.get("faceUpState")
    if not isinstance(face_state, dict):
        faces = registry.get("faces") if isinstance(registry.get("faces"), list) else []
        sources = [
            _clean(face.get("millingSource"))
            for face in faces
            if isinstance(face, dict) and face.get("millingSource")
        ]
        locked = any(bool(face.get("millingLocked")) for face in faces if isinstance(face, dict))
        face_state = {
            "source": sources[0] if sources else ("legacy" if faces else "default"),
            "locked": locked,
        }
        registry["faceUpState"] = face_state
    else:
        face_state.setdefault("source", "legacy")
        face_state.setdefault("locked", False)

    cutting = classification.get("cuttingFace")
    if not isinstance(cutting, dict):
        cutting = {
            "value": "",
            "source": face_state.get("source") or "default",
            "locked": bool(face_state.get("locked")),
        }
        classification["cuttingFace"] = cutting
    else:
        cutting = _ensure_field_state(cutting, default_source=face_state.get("source") or "legacy")
        # Preserve lock/source from legacy faceUpState when cuttingFace is new.
        if "locked" not in cutting or cutting.get("source") in ("", "legacy", "default"):
            if face_state.get("locked"):
                cutting["locked"] = True
            if cutting.get("source") in ("", "legacy", "default") and face_state.get("source"):
                cutting["source"] = face_state.get("source")
        classification["cuttingFace"] = cutting

    if not _clean_cutting_face(cutting.get("value")):
        recovered = derive_cutting_face_from_registry(working)
        if recovered:
            cutting["value"] = recovered
            if cutting.get("source") in ("", "legacy", "default"):
                cutting["source"] = face_state.get("source") or "legacy"
    elif (
        _clean_cutting_face(cutting.get("value")) == "EITHER"
        and not bool(cutting.get("locked"))
    ):
        # Live face overlay may have replaced EITHER/EITHER with definite
        # MILLING/NON_MILLING; promote unlocked cuttingFace so nest face-up
        # follows the updated milling side.
        recovered = derive_cutting_face_from_registry(working)
        if recovered == "MILLING":
            cutting["value"] = "MILLING"
            if cutting.get("source") in ("", "legacy", "default", "geometry", "assembly"):
                cutting["source"] = face_state.get("source") or "geometry"

    # Keep faceUpState as a compatibility mirror of cuttingFace provenance.
    registry["faceUpState"] = {
        "source": cutting.get("source") or face_state.get("source") or "legacy",
        "locked": bool(cutting.get("locked")),
    }

    working["metadataSchemaVersion"] = SCHEMA_VERSION
    return normalize_mirrors(working)


def normalize_mirrors(metadata):
    """Synchronize compatibility mirrors from canonical classification."""
    working = copy.deepcopy(metadata) if isinstance(metadata, dict) else {}
    classification = _ensure_dict(working, "classification")
    board = classification.get("boardType") if isinstance(classification.get("boardType"), dict) else {}
    tag = _clean(board.get("value"))
    if tag and not is_undefined(tag):
        _ensure_dict(working, "derivedTags")["boardTypeTag"] = tag
        _ensure_dict(working, "typedTags")["boardTypeTag"] = tag
        defaults = _ensure_dict(working, "defaultAttributes")
        defaults["materialClass"] = _material_for_tag(tag)
        defaults["role"] = _role_for_tag(tag)
        defaults["category"] = _role_for_tag(tag)
    else:
        _ensure_dict(working, "derivedTags").pop("boardTypeTag", None)
        _ensure_dict(working, "typedTags").pop("boardTypeTag", None)

    color = classification.get("color") if isinstance(classification.get("color"), dict) else {}
    color_tag = _clean(color.get("value"))
    if color_tag and not is_undefined(color_tag):
        _ensure_dict(working, "derivedTags")["colorTag"] = color_tag
        _ensure_dict(working, "typedTags")["colorTag"] = color_tag
    else:
        _ensure_dict(working, "derivedTags").pop("colorTag", None)
        _ensure_dict(working, "typedTags").pop("colorTag", None)

    cutting = classification.get("cuttingFace") if isinstance(classification.get("cuttingFace"), dict) else {}
    cutting_value = _clean_cutting_face(cutting.get("value"))
    registry = _ensure_dict(working, "faceRegistry")
    registry["faceUpState"] = {
        "source": cutting.get("source") or "legacy",
        "locked": bool(cutting.get("locked")),
    }
    if cutting_value:
        _ensure_dict(working, "derivedTags")["requiredFaceUp"] = cutting_value
        _ensure_dict(working, "typedTags")["requiredFaceUp"] = cutting_value
    else:
        _ensure_dict(working, "derivedTags").pop("requiredFaceUp", None)
        _ensure_dict(working, "typedTags").pop("requiredFaceUp", None)
    return working


def board_type_state(metadata):
    migrated = migrate_metadata(metadata)
    return dict((migrated.get("classification") or {}).get("boardType") or {})


def color_state(metadata):
    migrated = migrate_metadata(metadata)
    return dict((migrated.get("classification") or {}).get("color") or {})


def cutting_face_state(metadata):
    migrated = migrate_metadata(metadata)
    return dict((migrated.get("classification") or {}).get("cuttingFace") or {})


def face_up_state(metadata):
    """Compatibility alias: provenance mirror of classification.cuttingFace."""
    state = cutting_face_state(metadata)
    return {
        "source": state.get("source") or "legacy",
        "locked": bool(state.get("locked")),
        "value": _clean_cutting_face(state.get("value")),
    }


def _can_apply(current, source, force=False):
    current = current if isinstance(current, dict) else {}
    source = _clean(source) or "default"
    if bool(current.get("locked")) and source != "manual":
        return False, "manual_locked"
    if force:
        return True, None
    current_value = current.get("value")
    if not str(current_value or "").strip() or is_undefined(current_value):
        return True, None
    current_source = _clean(current.get("source")) or "default"
    if SOURCE_PRIORITY.get(source, 0) < SOURCE_PRIORITY.get(current_source, 0):
        return False, "lower_priority"
    return True, None


def apply_board_type(metadata, value, source="manual", lock=None, force=False):
    """Apply a board family proposal and return (metadata, result)."""
    working = migrate_metadata(metadata)
    tag = _clean(value)
    current = ((working.get("classification") or {}).get("boardType") or {})
    allowed, reason = _can_apply(current, source, force=force)
    if not allowed:
        return working, {"changed": False, "status": "skipped_locked" if reason == "manual_locked" else "unchanged", "reason": reason}
    if is_undefined(tag):
        tag = ""
    manual = _clean(source) == "manual"
    next_state = {
        "value": tag,
        "source": _clean(source) or "default",
        "locked": manual if lock is None else bool(lock),
    }
    changed = current != next_state
    _ensure_dict(working, "classification")["boardType"] = next_state
    working = normalize_mirrors(working)
    return working, {"changed": changed, "status": "changed" if changed else "unchanged", "reason": None}


def apply_color(metadata, color_tag, source="manual", lock=None, force=False):
    """Apply a colour-pool proposal and return (metadata, result)."""
    working = migrate_metadata(metadata)
    value = _clean(color_tag)
    current = ((working.get("classification") or {}).get("color") or {})
    allowed, reason = _can_apply(current, source, force=force)
    if not allowed:
        return working, {"changed": False, "status": "skipped_locked" if reason == "manual_locked" else "unchanged", "reason": reason}
    manual = _clean(source) == "manual"
    next_state = {
        "value": "" if is_undefined(value) else value,
        "source": _clean(source) or "default",
        "locked": manual if lock is None else bool(lock),
    }
    changed = current != next_state
    _ensure_dict(working, "classification")["color"] = next_state
    working = normalize_mirrors(working)
    return working, {"changed": changed, "status": "changed" if changed else "unchanged", "reason": None}


def apply_cutting_face(metadata, value, source="geometry", lock=None, force=False):
    """Apply MILLING / EITHER cutting-face constraint; same shape as board/color."""
    working = migrate_metadata(metadata)
    cleaned = _clean_cutting_face(value)
    current = ((working.get("classification") or {}).get("cuttingFace") or {})
    allowed, reason = _can_apply(current, source, force=force)
    if not allowed:
        return working, {
            "changed": False,
            "status": "skipped_locked" if reason == "manual_locked" else "unchanged",
            "reason": reason,
        }
    manual = _clean(source) == "manual"
    next_state = {
        "value": cleaned,
        "source": _clean(source) or "default",
        "locked": manual if lock is None else bool(lock),
    }
    changed = dict(current) != next_state
    _ensure_dict(working, "classification")["cuttingFace"] = next_state
    # Keep surface provenance mirrors in sync when locking/unlocking.
    for face in (_ensure_dict(working, "faceRegistry").get("faces") or []):
        if isinstance(face, dict) and (
            face.get("faceClass") == "SURFACE"
            or str(face.get("millingSurface") or "").upper()
            in ("MILLING", "NON_MILLING", "EITHER")
        ):
            face["millingSource"] = next_state["source"]
            face["millingLocked"] = next_state["locked"]
    working = normalize_mirrors(working)
    return working, {
        "changed": changed,
        "status": "changed" if changed else "unchanged",
        "reason": None,
    }


def can_apply_face_up(metadata, source="geometry", force=False):
    state = cutting_face_state(metadata)
    return _can_apply(state, source, force=force)


def mark_face_up(metadata, source="geometry", lock=None, value=None):
    """Compatibility wrapper: sync cuttingFace (+ optional derived value)."""
    working = migrate_metadata(metadata)
    if value is None:
        value = (
            ((working.get("classification") or {}).get("cuttingFace") or {}).get("value")
            or derive_cutting_face_from_registry(working)
        )
    updated, _result = apply_cutting_face(
        working, value, source=source, lock=lock, force=True
    )
    return updated


def reset_to_auto(metadata, field):
    """Unlock boardType, color, or cuttingFace without changing its current value."""
    working = migrate_metadata(metadata)
    key = _clean(field)
    if key in ("boardtype", "board_type", "boardtypetag"):
        state = _ensure_dict(working, "classification").get("boardType") or {}
        state["locked"] = False
        state["source"] = "legacy"
        _ensure_dict(working, "classification")["boardType"] = state
    elif key in ("color", "colour", "colortag"):
        state = _ensure_dict(working, "classification").get("color") or {}
        state["locked"] = False
        state["source"] = "legacy"
        _ensure_dict(working, "classification")["color"] = state
    elif key in ("faceup", "face_up", "milling", "cuttingface", "cutting_face", "requiredfaceup"):
        state = _ensure_dict(working, "classification").get("cuttingFace") or {}
        state["locked"] = False
        state["source"] = "legacy"
        _ensure_dict(working, "classification")["cuttingFace"] = state
        for face in (_ensure_dict(working, "faceRegistry").get("faces") or []):
            if isinstance(face, dict) and face.get("faceClass") == "SURFACE":
                face["millingLocked"] = False
                face["millingSource"] = "legacy"
    else:
        raise ValueError("Unsupported auto-reset field: {}".format(field))
    return normalize_mirrors(working)
