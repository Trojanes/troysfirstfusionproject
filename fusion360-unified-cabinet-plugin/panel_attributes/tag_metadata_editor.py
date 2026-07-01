import copy
import json

from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, PANEL_METADATA_ATTR

try:
    from face_attribute_store import read_face_metadata, write_face_metadata
    from face_models import FACE_CLASS_SURFACE, generate_face_id
except Exception:
    read_face_metadata = None
    write_face_metadata = None
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
    "boardTypeTag": lambda metadata, value: _set_derived_tag(metadata, "boardTypeTag", value),
    "colorTag": lambda metadata, value: _set_derived_tag(metadata, "colorTag", value),
    "boardType": lambda metadata, value: _set_path(metadata, ["identity", "boardType"], value),
    "materialClass": lambda metadata, value: _set_path(metadata, ["defaultAttributes", "materialClass"], value),
    "role": lambda metadata, value: _set_path(metadata, ["defaultAttributes", "role"], value),
    "lifecycleState": lambda metadata, value: _set_path(metadata, ["lifecycle", "state"], value),
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
    patcher(updated, value)
    lifecycle = _ensure_dict(updated, "lifecycle")
    if field_key != "lifecycleState":
        lifecycle["state"] = "adjusted"
    lifecycle["reviewRequired"] = True
    return updated


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
