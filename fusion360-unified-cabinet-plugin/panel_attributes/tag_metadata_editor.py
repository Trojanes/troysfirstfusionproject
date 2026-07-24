import copy
import json
import re

from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, PANEL_METADATA_ATTR
import attribute_state_service

try:
    from face_attribute_store import (
        read_face_metadata,
        write_face_metadata,
        remove_face_metadata,
    )
    from face_models import FACE_CLASS_SURFACE, generate_face_id
except Exception:
    read_face_metadata = None
    write_face_metadata = None
    remove_face_metadata = None
    FACE_CLASS_SURFACE = "SURFACE"
    generate_face_id = None

def _ensure_dict(parent, key):
    value = parent.get(key)
    if not isinstance(value, dict):
        value = {}
        parent[key] = value
    return value


def _set_path(metadata, path, value):
    if not path:
        return metadata
    cursor = metadata
    for key in path[:-1]:
        cursor = _ensure_dict(cursor, key)
    cursor[path[-1]] = value
    return metadata


def _set_derived_tag(metadata, key, value):
    _ensure_dict(metadata, "derivedTags")[key] = value
    _ensure_dict(metadata, "typedTags")[key] = value
    return metadata


def _sync_board_type_fields(metadata, board_type_tag):
    """Manual board-family edit; generator identity.boardType is preserved."""
    updated, _result = attribute_state_service.apply_board_type(
        metadata,
        board_type_tag,
        source="manual",
        lock=True,
        force=True,
    )
    return updated


def slug_color_tag(color_name, max_len=32):
    """Stable nesting colorTag from a user-entered display name."""
    text = str(color_name or "").strip().lower().replace(" ", "_")
    text = re.sub(r"[^a-z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    if not text:
        return ""
    return text[: max(1, int(max_len))]


def normalize_surface_mode_enum(value):
    """Return SINGLE_SIDED / DOUBLE_SIDED or empty string."""
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in ("single_sided", "singlesided", "single"):
        return "SINGLE_SIDED"
    if text in ("double_sided", "doublesided", "double"):
        return "DOUBLE_SIDED"
    upper = str(value or "").strip().upper().replace("-", "_").replace(" ", "_")
    if upper in ("SINGLE_SIDED", "DOUBLE_SIDED"):
        return upper
    return ""


def color_scope_allows(scope, is_door):
    """Pure scope rule used by Color Override."""
    normalized = str(scope or "doors").strip().lower()
    if normalized == "panels":
        return True
    if normalized == "doors":
        return bool(is_door)
    raise ValueError("scope must be doors or panels")


def apply_panel_color_to_metadata(metadata, color_name, surface_mode, is_door=False):
    """Write canonical panel color + manual lock.

    ``colorName`` is valid for every panel family. Door panels additionally
    mirror it to legacy ``doorColorName`` so older scans/nesting consumers keep
    working. Surface mode remains independent from the color tag.
    """
    updated = copy.deepcopy(metadata) if isinstance(metadata, dict) else {}
    updated.setdefault("schemaVersion", 1)
    defaults = _ensure_dict(updated, "defaultAttributes")
    name = str(color_name or "").strip()
    if not name:
        raise ValueError("Color name is required.")
    color_tag = slug_color_tag(name)
    if not color_tag:
        raise ValueError("Color name did not produce a valid colorTag slug.")
    mode = normalize_surface_mode_enum(surface_mode)
    if not mode:
        raise ValueError("surfaceMode must be single_sided or double_sided.")

    defaults["colorName"] = name
    if is_door:
        defaults["doorColorName"] = name
    defaults["surfaceMode"] = mode
    registry = _ensure_dict(updated, "faceRegistry")
    registry["surfaceMode"] = mode
    updated, _result = attribute_state_service.apply_color(
        updated,
        color_tag,
        source="manual",
        lock=True,
        force=True,
    )
    return updated, color_tag, mode


def apply_door_color_to_metadata(metadata, color_name, surface_mode):
    """Backward-compatible door-only color wrapper."""
    return apply_panel_color_to_metadata(
        metadata,
        color_name,
        surface_mode,
        is_door=True,
    )


def _safe_face_token(face):
    try:
        return str(getattr(face, "entityToken", "") or "")
    except Exception:
        return ""


def normalize_complementary_surface_roles(role_a, role_b, face_a=None, face_b=None,
                                          require_definite=False):
    """Enforce colour face ≠ milling face on the two broad surfaces.

    Hard rules:
    - The two faces must be distinct entities.
    - Never MILLING/MILLING or NON_MILLING/NON_MILLING.
    - Complementary MILLING + NON_MILLING (or EITHER + EITHER) only.
    - When ``require_definite`` (manual override), EITHER/EITHER becomes
      MILLING/NON_MILLING — hinge holes / symmetry are irrelevant.
    """
    ra = str(role_a or "").strip().upper()
    rb = str(role_b or "").strip().upper()
    token_a = _safe_face_token(face_a) if face_a is not None else ""
    token_b = _safe_face_token(face_b) if face_b is not None else ""
    if token_a and token_b and token_a == token_b:
        raise ValueError(
            "Colour face and milling face must be opposite broad faces, not the same face."
        )
    if face_a is not None and face_b is not None and face_a is face_b:
        raise ValueError(
            "Colour face and milling face must be opposite broad faces, not the same face."
        )
    if not ra or not rb:
        raise ValueError("Both face roles are required.")

    either = "EITHER"
    milling = "MILLING"
    non_milling = "NON_MILLING"

    if ra == either and rb == either:
        if require_definite:
            return milling, non_milling
        return either, either
    if ra == milling and rb == non_milling:
        return milling, non_milling
    if ra == non_milling and rb == milling:
        return non_milling, milling

    # Illegal same-role pairs: force complementary. Prefer keeping MILLING on A
    # when both were tagged MILLING so a colour (NON_MILLING) face always exists.
    if ra == milling and rb == milling:
        return milling, non_milling
    if ra == non_milling and rb == non_milling:
        return non_milling, milling

    if ra == milling or rb == non_milling:
        return milling, non_milling
    if rb == milling or ra == non_milling:
        return non_milling, milling
    if require_definite:
        return milling, non_milling
    return either, either


def _patch_face_milling_surface(face, role, body_metadata=None, source="geometry", locked=False):
    """Write millingSurface onto a face entity attribute."""
    if not face or not write_face_metadata:
        return None
    existing = None
    if read_face_metadata:
        existing, _error = read_face_metadata(face)
    working = copy.deepcopy(existing) if isinstance(existing, dict) else _bootstrap_face_metadata(body_metadata, face)
    working["faceClass"] = working.get("faceClass") or FACE_CLASS_SURFACE
    working["millingSurface"] = str(role or "").strip().upper() or "UNASSIGNED"
    working["millingSource"] = str(source or "geometry").strip().lower()
    working["millingLocked"] = bool(locked)
    write_face_metadata(face, working)
    return working


def _upsert_registry_surface(registry, face_metadata, milling_role, entity_token=""):
    faces = registry.get("faces")
    if not isinstance(faces, list):
        faces = []
        registry["faces"] = faces
    face_id = str((face_metadata or {}).get("faceId") or "").strip()
    entry = None
    if face_id:
        for item in faces:
            if isinstance(item, dict) and str(item.get("faceId") or "") == face_id:
                entry = item
                break
    if entry is None and entity_token:
        for item in faces:
            if isinstance(item, dict) and str(item.get("entityToken") or "") == entity_token:
                entry = item
                break
    if entry is None:
        entry = {
            "faceId": face_id or (generate_face_id() if callable(generate_face_id) else "FACE-MANUAL"),
            "faceClass": FACE_CLASS_SURFACE,
            "faceRole": str((face_metadata or {}).get("faceRole") or "surface"),
            "entityToken": entity_token,
        }
        faces.append(entry)
    entry["faceClass"] = FACE_CLASS_SURFACE
    entry["millingSurface"] = str(milling_role or "").strip().upper() or "UNASSIGNED"
    if entity_token:
        entry["entityToken"] = entity_token
    if face_id:
        entry["faceId"] = face_id
    face_ids = registry.get("faceIds")
    if not isinstance(face_ids, list):
        face_ids = []
        registry["faceIds"] = face_ids
    if entry["faceId"] not in face_ids:
        face_ids.append(entry["faceId"])
    return entry


def apply_surface_roles(body, face_a, role_a, face_b, role_b,
                        source="geometry", lock=False, force=False):
    """Write arbitrary milling roles on two broad faces and sync faceRegistry."""
    if not body:
        raise ValueError("Missing body")
    if face_a is None or face_b is None:
        raise ValueError("Both broad faces are required.")
    source_name = str(source or "").strip().lower()
    # Manual override always locks definite MILLING/NON_MILLING (never leaves EITHER).
    definite = bool(lock) or source_name == "manual"
    role_a, role_b = normalize_complementary_surface_roles(
        role_a, role_b, face_a, face_b, require_definite=definite
    )

    existing, read_error = _read_body_metadata_raw(body)
    if read_error:
        raise ValueError(read_error)
    metadata = _bootstrap_body_metadata(body, existing)
    allowed, reason = attribute_state_service.can_apply_face_up(
        metadata, source=source, force=force
    )
    if not allowed:
        raise ValueError(reason or "face_up_write_rejected")
    registry = _ensure_dict(metadata, "faceRegistry")

    locked = bool(lock or source_name == "manual")
    old_a, _old_a_error = read_face_metadata(face_a) if read_face_metadata else (None, None)
    old_b, _old_b_error = read_face_metadata(face_b) if read_face_metadata else (None, None)
    try:
        meta_a = _patch_face_milling_surface(
            face_a, role_a, metadata, source=source, locked=locked
        )
        meta_b = _patch_face_milling_surface(
            face_b, role_b, metadata, source=source, locked=locked
        )

        _upsert_registry_surface(registry, meta_a, role_a, _safe_face_token(face_a))
        _upsert_registry_surface(registry, meta_b, role_b, _safe_face_token(face_b))

        cutting_value = attribute_state_service.cutting_face_from_surface_roles(
            role_a, role_b
        )
        metadata, _result = attribute_state_service.apply_cutting_face(
            metadata,
            cutting_value,
            source=source,
            lock=locked,
            force=True,
        )
        _write_body_metadata(body, metadata)
    except Exception:
        for face, previous in ((face_a, old_a), (face_b, old_b)):
            try:
                if isinstance(previous, dict):
                    write_face_metadata(face, previous)
                elif callable(remove_face_metadata):
                    remove_face_metadata(face)
            except Exception:
                pass
        raise
    return metadata


def apply_surface_milling_roles(body, milling_face, non_milling_face,
                                source="geometry", lock=False, force=False):
    """Set MILLING / NON_MILLING on two broad faces and sync body faceRegistry."""
    try:
        from face_models import MILLING_SURFACE, NON_MILLING_SURFACE
    except Exception:
        try:
            from metadata.face_models import MILLING_SURFACE, NON_MILLING_SURFACE
        except Exception:
            MILLING_SURFACE = "MILLING"
            NON_MILLING_SURFACE = "NON_MILLING"
    if milling_face is not None and non_milling_face is not None and milling_face is non_milling_face:
        raise ValueError(
            "Colour face and milling face must be opposite broad faces, not the same face."
        )
    return apply_surface_roles(
        body,
        milling_face,
        MILLING_SURFACE,
        non_milling_face,
        NON_MILLING_SURFACE,
        source=source,
        lock=lock,
        force=force,
    )


def _parse_yes_no(value):
    text = str(value or "").strip().lower()
    if text in ("yes", "true", "1"):
        return True
    if text in ("no", "false", "0"):
        return False
    return None


def _set_finish(metadata, value):
    finish = _ensure_dict(metadata, "finish")
    text = str(value or "").strip()
    if not text or text.lower() == "unknown":
        finish["finishId"] = "UNASSIGNED"
        finish["finishName"] = "Unassigned"
    else:
        finish["finishId"] = text
        finish["finishName"] = text
    return metadata


def _set_edge_banding_required(metadata, value):
    required = _parse_yes_no(value)
    edge_banding = _ensure_dict(metadata, "edgeBanding")
    if required is None:
        edge_banding.pop("required", None)
    else:
        edge_banding["required"] = required
    return metadata


def _set_edge_banding_color(metadata, value):
    edge_banding = _ensure_dict(metadata, "edgeBanding")
    text = str(value or "").strip()
    if not text or text.lower() == "unknown":
        edge_banding["finishId"] = "UNASSIGNED"
        edge_banding["finishName"] = "Unassigned"
    else:
        edge_banding["finishId"] = text
        edge_banding["finishName"] = text
    return metadata


BODY_FIELD_PATCHERS = {
    "boardTypeTag": lambda metadata, value: _sync_board_type_fields(metadata, value),
    "colorTag": lambda metadata, value: attribute_state_service.apply_color(
        metadata, value, source="manual", lock=True, force=True
    )[0],
}

FACE_FIELD_PATCHERS = {
    "faceClass": lambda metadata, value: _set_path(metadata, ["faceClass"], value),
    "faceRole": lambda metadata, value: _set_path(metadata, ["faceRole"], value),
    "side": lambda metadata, value: _set_path(metadata, ["side"], value),
    "color": _set_finish,
    "edgeBandingRequired": _set_edge_banding_required,
    "edgeBandingColor": _set_edge_banding_color,
    "edgeKind": lambda metadata, value: _set_path(metadata, ["edgeKind"], value),
}


def _read_body_metadata_raw(body):
    if not body:
        return None, "Missing body"
    try:
        attrs = body.attributes
        attr = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR) if attrs else None
        if not attr:
            return None, None
        raw = str(attr.value or "").strip()
        if not raw:
            return None, "Empty metadata attribute"
        return json.loads(raw), None
    except json.JSONDecodeError as ex:
        return None, "Invalid metadata JSON: {}".format(ex)
    except Exception as ex:
        return None, str(ex)


def _bootstrap_body_metadata(body, existing_metadata=None):
    metadata = copy.deepcopy(existing_metadata) if isinstance(existing_metadata, dict) else {}
    panel_id = ""
    try:
        attrs = body.attributes
        attr = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR) if attrs else None
        panel_id = str(attr.value or "").strip() if attr and attr.value else ""
    except Exception:
        panel_id = ""

    metadata.setdefault("schemaVersion", 1)
    identity = _ensure_dict(metadata, "identity")
    if panel_id and not identity.get("panelId"):
        identity["panelId"] = panel_id
    identity.setdefault("panelId", "manual.{}".format(getattr(body, "name", "body") or "body"))
    metadata.setdefault("defaultAttributes", {})
    lifecycle = _ensure_dict(metadata, "lifecycle")
    lifecycle.setdefault("state", "adjusted")
    lifecycle["reviewRequired"] = True
    return metadata


def _write_body_metadata(body, metadata):
    metadata = attribute_state_service.migrate_metadata(metadata)
    payload = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    panel_id = str(_ensure_dict(metadata, "identity").get("panelId") or "").strip()
    attrs = body.attributes
    if panel_id:
        existing_id = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR) if attrs else None
        if existing_id:
            existing_id.value = panel_id
        else:
            attrs.add(PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, panel_id)
    existing_payload = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR) if attrs else None
    if existing_payload:
        existing_payload.value = payload
    else:
        attrs.add(PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR, payload)
    return metadata


def _bootstrap_face_metadata(body_metadata, face):
    panel_id = ""
    if isinstance(body_metadata, dict):
        identity = body_metadata.get("identity") or {}
        panel_id = str(identity.get("panelId") or body_metadata.get("panelId") or "").strip()
    face_id = generate_face_id() if callable(generate_face_id) else "FACE-MANUAL"
    return {
        "schemaVersion": 1,
        "panelId": panel_id or "unknown-panel",
        "faceId": face_id,
        "faceClass": FACE_CLASS_SURFACE,
        "finish": {"finishId": "UNASSIGNED", "finishName": "Unassigned"},
        "edgeBanding": None,
    }


def apply_body_field_patch(metadata, field_key, value):
    patcher = BODY_FIELD_PATCHERS.get(field_key)
    if not patcher:
        raise ValueError("Unsupported body field: {}".format(field_key))
    updated = copy.deepcopy(metadata) if isinstance(metadata, dict) else _bootstrap_body_metadata(None)
    patched = patcher(updated, value)
    if isinstance(patched, dict):
        updated = patched
    # Readiness is pure scan-time derivation. Body edits never persist it.
    lifecycle = _ensure_dict(updated, "lifecycle")
    lifecycle["state"] = "adjusted"
    lifecycle["reviewRequired"] = True
    return updated


def reset_field_to_auto(body, field_key):
    """Unlock a manually overridden canonical field on a Fusion body."""
    metadata, read_error = _read_body_metadata_raw(body)
    if read_error:
        raise ValueError(read_error)
    working = _bootstrap_body_metadata(body, metadata)
    working = attribute_state_service.reset_to_auto(working, field_key)
    if str(field_key or "").strip().lower() in (
        "faceup", "face_up", "milling", "cuttingface", "cutting_face", "requiredfaceup"
    ):
        try:
            faces = body.faces
            count = faces.count if faces else 0
        except Exception:
            count = 0
        for index in range(count):
            try:
                face = faces.item(index)
                face_metadata, _error = read_face_metadata(face) if read_face_metadata else (None, None)
                if not isinstance(face_metadata, dict) or not face_metadata.get("millingSurface"):
                    continue
                face_metadata = copy.deepcopy(face_metadata)
                face_metadata["millingLocked"] = False
                face_metadata["millingSource"] = "legacy"
                write_face_metadata(face, face_metadata)
            except Exception:
                continue
    _write_body_metadata(body, working)
    return working


def apply_face_field_patch(metadata, field_key, value):
    patcher = FACE_FIELD_PATCHERS.get(field_key)
    if not patcher:
        raise ValueError("Unsupported face field: {}".format(field_key))
    updated = copy.deepcopy(metadata) if isinstance(metadata, dict) else {}
    if not updated:
        updated = {
            "schemaVersion": 1,
            "faceClass": FACE_CLASS_SURFACE,
            "finish": {"finishId": "UNASSIGNED", "finishName": "Unassigned"},
        }
    patcher(updated, value)
    return updated


def group_drafts_by_result(drafts):
    grouped = {}
    for draft in drafts or []:
        result_key = str(draft.get("resultKey") or "").strip()
        if not result_key:
            continue
        grouped.setdefault(result_key, []).append(draft)
    return grouped


def find_scan_result(results, result_key):
    for index, result in enumerate(results or []):
        body = result.get("body") or {}
        token = str(body.get("entityToken") or "").strip()
        panel_id = str(body.get("panelId") or "").strip()
        body_name = str(body.get("bodyName") or "").strip()
        component = str(body.get("componentName") or "").strip()
        selection_type = result.get("selectionType") or (result.get("selection") or {}).get("selectionType") or "body"
        candidates = []
        if token:
            candidates.append("token:{}|{}".format(token, selection_type))
        if panel_id:
            candidates.append("panel:{}|{}".format(panel_id, selection_type))
        candidates.append("idx:{}|{}|{}|{}".format(index, component, body_name, selection_type))
        if result_key in candidates:
            return result
    return None


def apply_tag_scan_drafts(results, drafts, resolve_entity):
    applied = []
    failed = []
    grouped = group_drafts_by_result(drafts)

    for result_key, result_drafts in grouped.items():
        result = find_scan_result(results, result_key)
        if not result:
            failed.append({
                "resultKey": result_key,
                "fieldKey": "",
                "error": "Scan result not found for pending edit group.",
            })
            continue

        body_drafts = [draft for draft in result_drafts if draft.get("scope") == "body"]
        selection_drafts = [draft for draft in result_drafts if draft.get("scope") == "selection"]

        if body_drafts:
            body = resolve_entity((result.get("body") or {}).get("entityToken"), "body", result)
            if not body:
                selection = result.get("selection") or {}
                body = resolve_entity(selection.get("selectionEntityToken"), "body", result)
            if not body:
                for draft in body_drafts:
                    failed.append({
                        "resultKey": result_key,
                        "fieldKey": draft.get("fieldKey"),
                        "label": draft.get("label"),
                        "error": "Could not resolve Fusion body for write-back.",
                    })
                body_drafts = []

            metadata, read_error = _read_body_metadata_raw(body) if body else (None, "Missing body")
            if body and read_error:
                for draft in body_drafts:
                    failed.append({
                        "resultKey": result_key,
                        "fieldKey": draft.get("fieldKey"),
                        "label": draft.get("label"),
                        "error": read_error,
                    })
                body_drafts = []

            if body and body_drafts:
                working = _bootstrap_body_metadata(body, metadata)
                for draft in body_drafts:
                    field_key = str(draft.get("fieldKey") or "").strip()
                    try:
                        working = apply_body_field_patch(working, field_key, draft.get("draftValue"))
                        applied.append({
                            "resultKey": result_key,
                            "scope": "body",
                            "fieldKey": field_key,
                            "label": draft.get("label"),
                            "draftValue": draft.get("draftValue"),
                        })
                    except Exception as ex:
                        failed.append({
                            "resultKey": result_key,
                            "fieldKey": field_key,
                            "label": draft.get("label"),
                            "error": str(ex),
                        })
                try:
                    _write_body_metadata(body, working)
                except Exception as ex:
                    for item in list(applied):
                        if item.get("resultKey") == result_key and item.get("scope") == "body":
                            applied.remove(item)
                            failed.append({
                                "resultKey": result_key,
                                "fieldKey": item.get("fieldKey"),
                                "label": item.get("label"),
                                "error": "Write failed: {}".format(ex),
                            })

        if selection_drafts:
            if not write_face_metadata:
                for draft in selection_drafts:
                    failed.append({
                        "resultKey": result_key,
                        "fieldKey": draft.get("fieldKey"),
                        "label": draft.get("label"),
                        "error": "Face metadata writer is unavailable.",
                    })
                continue

            selection = result.get("selection") or {}
            selection_token = str(selection.get("selectionEntityToken") or "").strip()
            face = resolve_entity(selection_token, "face", result)
            if not face:
                for draft in selection_drafts:
                    failed.append({
                        "resultKey": result_key,
                        "fieldKey": draft.get("fieldKey"),
                        "label": draft.get("label"),
                        "error": "Could not resolve Fusion face/edge entity for write-back.",
                    })
                continue

            body = resolve_entity((result.get("body") or {}).get("entityToken"), "body", result)
            body_metadata, _read_error = _read_body_metadata_raw(body) if body else (None, None)
            face_metadata = None
            if read_face_metadata:
                face_metadata, _face_error = read_face_metadata(face)
            if not face_metadata:
                face_metadata = _bootstrap_face_metadata(body_metadata, face)

            working = copy.deepcopy(face_metadata)
            for draft in selection_drafts:
                field_key = str(draft.get("fieldKey") or "").strip()
                try:
                    working = apply_face_field_patch(working, field_key, draft.get("draftValue"))
                    applied.append({
                        "resultKey": result_key,
                        "scope": "selection",
                        "fieldKey": field_key,
                        "label": draft.get("label"),
                        "draftValue": draft.get("draftValue"),
                    })
                except Exception as ex:
                    failed.append({
                        "resultKey": result_key,
                        "fieldKey": field_key,
                        "label": draft.get("label"),
                        "error": str(ex),
                    })
            try:
                write_face_metadata(face, working)
            except Exception as ex:
                for item in list(applied):
                    if item.get("resultKey") == result_key and item.get("scope") == "selection":
                        applied.remove(item)
                        failed.append({
                            "resultKey": result_key,
                            "fieldKey": item.get("fieldKey"),
                            "label": item.get("label"),
                            "error": "Write failed: {}".format(ex),
                        })

    return applied, failed
