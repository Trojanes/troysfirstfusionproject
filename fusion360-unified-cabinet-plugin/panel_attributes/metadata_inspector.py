import copy
import json

from panel_body_resolver import list_solid_bodies, resolve_occurrence_path_for_body
from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, PANEL_METADATA_ATTR
import attribute_state_service

try:
    from face_attribute_store import read_face_metadata
except Exception:
    read_face_metadata = None

try:
    from panel_face_initializer import list_body_face_records
except Exception:
    list_body_face_records = None

try:
    import work_zones
except Exception:
    work_zones = None

try:
    from attribute_ready import evaluate_attribute_ready
except Exception:
    try:
        from panel_attributes.attribute_ready import evaluate_attribute_ready
    except Exception:
        evaluate_attribute_ready = None

try:
    import thickness_rules
except Exception:
    try:
        from panel_attributes import thickness_rules
    except Exception:
        thickness_rules = None

LEGACY_ATTRIBUTE_GROUP = "UnifiedCabinetPlugin"
CABINETNC_ATTRIBUTE_GROUP = "CabinetNC"
MODULE_ATTR_GROUPS = (PANEL_ATTRIBUTE_GROUP, LEGACY_ATTRIBUTE_GROUP, CABINETNC_ATTRIBUTE_GROUP, "UnifiedCabinet")


def _attr_group_value(entity, group, name):
    if not entity:
        return ""
    try:
        attrs = entity.attributes
        attr = attrs.itemByName(group, name) if attrs else None
        return str(attr.value or "").strip() if attr else ""
    except Exception:
        return ""


def _attr_value(entity, name):
    return _attr_group_value(entity, PANEL_ATTRIBUTE_GROUP, name)


def _legacy_attr_value(entity, name):
    return _attr_group_value(entity, LEGACY_ATTRIBUTE_GROUP, name)


def _module_attr_value(entity, name):
    """Read a module attribute from any known generator attribute group."""
    for group in MODULE_ATTR_GROUPS:
        value = _attr_group_value(entity, group, name)
        if value:
            return value
    return ""


def _read_metadata(entity):
    raw = _attr_value(entity, PANEL_METADATA_ATTR)
    if not raw:
        return None, None, ""
    try:
        return json.loads(raw), None, raw
    except json.JSONDecodeError as ex:
        return None, "Invalid metadata JSON: {}".format(ex), raw[:1200]
    except Exception as ex:
        return None, str(ex), raw[:1200]


def _infer_material_class(module, board_type, panel_type, panel_kind):
    text = " ".join(
        [
            str(module or "").lower(),
            str(board_type or "").lower(),
            str(panel_type or "").lower(),
            str(panel_kind or "").lower(),
        ]
    )
    board_id = str(board_type or "").strip().upper()
    # General Tall / Fridge style-1 inserted boards are carcass, even when CPT
    # equals the door thickness rule (e.g. both 16 mm).
    if board_id in ("T3", "B3", "T2", "B2", "T4", "T5"):
        return "carcass_board"
    if board_id in ("T1", "B1") or board_id.startswith("FP"):
        return "door_board"
    # Kitchen / Lounge front panels are doors even when named frontPanel (camelCase).
    if any(
        token in text
        for token in (
            "door",
            "flap",
            "fascia",
            "front_visible",
            "frontpanel",
            "front_panel",
            "front-panel",
        )
    ):
        return "door_board"
    if "partition" in text or "divider" in text:
        return "partition_board"
    return "carcass_board"


def _synthesize_module_metadata(entity, component=None):
    """Build a scan-time metadata stub for Kitchen/Lounge/OHC bodies that only
    have generator attributes (CabinetNC / UnifiedCabinetPlugin), not full
    UnifiedCabinet.Panel payloads yet.
    """
    module = _module_attr_value(entity, "module") or _module_attr_value(component, "module")
    if not module:
        return None

    board_id = (
        _module_attr_value(entity, "boardId")
        or _module_attr_value(entity, "bodyId")
        or _module_attr_value(entity, "panelId")
        or _module_attr_value(component, "boardId")
        or _module_attr_value(component, "bodyId")
        or _module_attr_value(component, "panelId")
        or str(getattr(entity, "name", "") or "")
    )
    if not board_id:
        return None

    board_type = (
        _module_attr_value(entity, "boardType")
        or _module_attr_value(entity, "panelType")
        or _module_attr_value(entity, "panelKind")
        or _module_attr_value(component, "boardType")
        or _module_attr_value(component, "panelType")
        or board_id
    )
    panel_type = _module_attr_value(entity, "panelType") or _module_attr_value(component, "panelType")
    panel_kind = _module_attr_value(entity, "panelKind") or _module_attr_value(component, "panelKind")
    material_class = _infer_material_class(module, board_type, panel_type, panel_kind)
    role = "door" if material_class == "door_board" else ("partition" if material_class == "partition_board" else "carcass")
    panel_id = "{}.{}".format(module, board_id)
    return {
        "schemaVersion": 1,
        "identity": {
            "panelId": panel_id,
            "generator": module,
            "module": module,
            "cabinetType": module,
            "sourceBoardId": board_id,
            "sourceBoardType": board_type,
            "boardType": board_type,
            "runId": _module_attr_value(entity, "runLabel")
            or _module_attr_value(component, "runLabel")
            or "scan",
        },
        "defaultAttributes": {
            "role": role,
            "category": role,
            "materialClass": material_class,
            "tags": [module, board_type],
        },
        "classification": {
            "boardType": {
                "value": role,
                "source": "generator",
                "locked": False,
            },
            "color": {
                "value": "",
                "source": "default",
                "locked": False,
            },
        },
        "lifecycle": {
            "state": "module_scanned",
            "reviewRequired": True,
        },
        "_synthesizedFromModuleAttrs": True,
    }


def _legacy_overhead_board_type(board_id, source_type=""):
    board_id = str(board_id or "")
    source_type = str(source_type or "")
    if board_id == "BP":
        return "bottom_panel"
    if board_id == "T1":
        return "top_front_door_fascia"
    if board_id == "T2":
        return "top_front_inner_rail"
    if board_id == "T3":
        return "top_rear_panel"
    if board_id == "T4":
        return "top_front_panel"
    if board_id.startswith("D"):
        return "internal_vertical_divider"
    if board_id.startswith("FP"):
        if source_type == "up_flap":
            return "up_flap_door_panel"
        if source_type == "fixed_panel":
            return "fixed_front_panel"
        return "front_panel"
    return source_type or board_id


def _legacy_overhead_metadata(entity):
    module = _legacy_attr_value(entity, "module")
    board_id = _legacy_attr_value(entity, "boardId")
    if module != "overhead" or not board_id:
        return None

    source_type = _legacy_attr_value(entity, "boardType")
    board_type = _legacy_overhead_board_type(board_id, source_type)
    is_door_material = board_type in (
        "top_front_door_fascia",
        "up_flap_door_panel",
        "fixed_front_panel",
        "front_panel",
    )
    material_class = "door_board" if is_door_material else "carcass_board"
    role = "door" if board_type == "up_flap_door_panel" else "front_visible" if is_door_material else "carcass"
    default_attributes = {
        "role": role,
        "category": "front" if is_door_material else "structural",
        "materialClass": material_class,
        "tags": ["overhead", board_type],
    }
    if is_door_material:
        default_attributes["doorColorSlot"] = 1

    return {
        "schemaVersion": 1,
        "identity": {
            "panelId": "legacy.overhead.{}".format(board_id),
            "generator": "overhead",
            "module": "overhead",
            "cabinetType": "overhead",
            "sourceBoardId": board_id,
            "sourceBoardType": source_type or board_id,
            "boardType": board_type,
            "runId": "legacy",
        },
        "defaultAttributes": default_attributes,
        "lifecycle": {
            "state": "legacy_scanned",
            "reviewRequired": True,
        },
    }


def _path_value(metadata, paths):
    if not isinstance(metadata, dict):
        return None
    for path in paths:
        cursor = metadata
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                cursor = None
                break
            cursor = cursor.get(key)
        if cursor not in (None, ""):
            return cursor
    return None


def _list_value(value):
    if isinstance(value, list):
        return [str(item) for item in value if item not in (None, "")]
    if value in (None, ""):
        return []
    return [str(value)]


def _metadata_summary(metadata, fallback_panel_id):
    panel_id = _path_value(metadata, [["identity", "panelId"], ["panelId"]]) or fallback_panel_id
    board_type = _path_value(
        metadata,
        [["identity", "boardType"], ["identity", "sourceBoardType"], ["boardType"], ["panelType"]],
    )
    source_board_id = _path_value(
        metadata,
        [["identity", "sourceBoardId"], ["sourceBoardId"], ["boardId"]],
    )
    role = _path_value(
        metadata,
        [["defaultAttributes", "role"], ["role"], ["panelType"]],
    )
    material_class = _path_value(
        metadata,
        [["defaultAttributes", "materialClass"], ["materialClass"]],
    )
    tags = _path_value(metadata, [["defaultAttributes", "tags"], ["tags"]])
    return {
        "panelId": str(panel_id or ""),
        "boardType": str(board_type or ""),
        "sourceBoardId": str(source_board_id or ""),
        "role": str(role or ""),
        "materialClass": str(material_class or ""),
        "tags": _list_value(tags),
    }


def _contains_white_stipple(value):
    if isinstance(value, str):
        return value == "white_stipple"
    if isinstance(value, list):
        return any(_contains_white_stipple(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_white_stipple(item) for item in value.values())
    return False


def _normalize_surface_mode_key(value):
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if text in ("single_sided", "singlesided", "single"):
        return "single_sided"
    if text in ("double_sided", "doublesided", "double"):
        return "double_sided"
    return text


def _metadata_surface_mode(metadata):
    value = _path_value(
        metadata,
        [
            ["defaultAttributes", "surfaceMode"],
            ["faceRegistry", "surfaceMode"],
            ["surfaceMode"],
            ["faceMetadata", "surfaceMode"],
            ["manufacturingDefaults", "surfaceMode"],
        ],
    )
    return _normalize_surface_mode_key(value)


def _metadata_door_color_slot(metadata):
    value = _path_value(
        metadata,
        [["defaultAttributes", "doorColorSlot"], ["doorColorSlot"]],
    )
    try:
        return int(value)
    except Exception:
        return None


def _is_undefined_tag_text(value):
    text = str(value or "").strip().lower()
    if not text:
        return True
    return "unknown" in text or text in ("undefined", "unassigned", "none", "n/a")


def _slug_color_tag(color_name, max_len=32):
    try:
        from tag_metadata_editor import slug_color_tag
        return slug_color_tag(color_name, max_len=max_len)
    except Exception:
        import re
        text = str(color_name or "").strip().lower().replace(" ", "_")
        text = re.sub(r"[^a-z0-9_]+", "_", text)
        text = re.sub(r"_+", "_", text).strip("_")
        return text[:max_len] if text else ""


def _derive_color_tag(metadata, material_class):
    classification = metadata.get("classification") if isinstance(metadata, dict) else {}
    color_state = classification.get("color") if isinstance(classification, dict) else {}
    canonical = str((color_state or {}).get("value") or "").strip().lower()
    if canonical and not attribute_state_service.is_undefined(canonical):
        return canonical
    explicit = _path_value(
        metadata,
        [["derivedTags", "colorTag"], ["typedTags", "colorTag"], ["colorTag"]],
    )
    explicit_text = str(explicit or "").strip()
    if explicit_text == "white_stipple" or _contains_white_stipple(explicit):
        return "white_stipple"
    if _contains_white_stipple(metadata):
        return "white_stipple"

    # Prefer explicit custom / stored colorTag (same pattern as boardTypeTag).
    # Do not keep legacy slot tags that bake sidedness into the name when a
    # doorColorName exists — those are rebuilt below from the display name.
    if explicit_text and not _is_undefined_tag_text(explicit_text):
        lower = explicit_text.lower()
        if lower not in ("carcass_colour",) and not lower.startswith("door_colour_"):
            return lower

    color_name = _path_value(
        metadata,
        [
            ["defaultAttributes", "colorName"],
            ["defaultAttributes", "doorColorName"],
            ["colorName"],
            ["doorColorName"],
        ],
    )
    color_name = str(color_name or "").strip()
    if color_name:
        slug = _slug_color_tag(color_name)
        if slug:
            return slug

    if material_class == "carcass_board":
        return "carcass_colour"
    if material_class != "door_board":
        return ""

    # Legacy slot-based tags still encode sidedness for old panels.
    if explicit_text and not _is_undefined_tag_text(explicit_text):
        return explicit_text.lower()

    slot = _metadata_door_color_slot(metadata)
    if slot not in (1, 2):
        return ""

    surface_mode = _metadata_surface_mode(metadata)
    if surface_mode == "single_sided":
        return "door_colour_{}_single_sided".format(slot)
    if surface_mode == "double_sided":
        return "door_colour_{}_double_sided".format(slot)
    # Unknown / missing surface mode is not a real color — treat as undefined.
    return ""


def _derive_board_type_tag(metadata):
    classification = metadata.get("classification") if isinstance(metadata, dict) else {}
    board_state = classification.get("boardType") if isinstance(classification, dict) else {}
    canonical = str((board_state or {}).get("value") or "").strip().lower()
    if canonical and not attribute_state_service.is_undefined(canonical):
        return canonical
    explicit = _path_value(
        metadata,
        [["derivedTags", "boardTypeTag"], ["typedTags", "boardTypeTag"]],
    )
    explicit_text = str(explicit or "").strip().lower()
    # Keep any explicit tag (built-in or custom like bunk_bed). Only fall through
    # to materialClass/role heuristics when the tag is empty/unknown.
    if explicit_text and "unknown" not in explicit_text and explicit_text not in (
        "undefined",
        "unassigned",
        "none",
        "n/a",
    ):
        return explicit_text

    material_class = str(_path_value(metadata, [["defaultAttributes", "materialClass"], ["materialClass"]]) or "")
    role = str(_path_value(metadata, [["defaultAttributes", "role"], ["role"], ["panelType"]]) or "").lower()
    category = str(_path_value(metadata, [["defaultAttributes", "category"], ["category"]]) or "").lower()
    panel_type = str(_path_value(metadata, [["panelType"]]) or "").lower()
    identity_type = str(
        _path_value(metadata, [["identity", "boardType"], ["identity", "sourceBoardType"], ["boardType"]]) or ""
    ).strip().lower()

    if material_class == "door_board" or role in ("door", "front_visible") or panel_type == "door":
        return "door"
    if material_class == "partition_board" or role == "partition" or category == "partition" or panel_type == "partition":
        return "partition"
    if material_class == "carcass_board" or role in ("carcass", "carcass_rail") or panel_type == "carcass":
        return "carcass"
    # Free-form tags list (legacy / quick tags) — only accept exact board-type words.
    free_tags = [
        str(item).strip().lower()
        for item in _list_value(_path_value(metadata, [["defaultAttributes", "tags"], ["tags"]]))
    ]
    for candidate in ("partition", "door", "carcass"):
        if candidate in free_tags:
            return candidate
    # Custom materialClass "bunk_bed_board" → bunk_bed
    if material_class.endswith("_board") and len(material_class) > 6:
        mapped = material_class[:-6]
        if mapped and mapped not in ("door", "carcass", "partition"):
            return mapped
    if identity_type and "unknown" not in identity_type and identity_type not in (
        "undefined",
        "unassigned",
        "none",
        "n/a",
    ):
        # Prefer high-level tags; skip long semantic names like up_flap_door_panel
        # unless they already look like a board-type slug.
        if identity_type in ("carcass", "partition", "door") or (
            "_" in identity_type and len(identity_type) <= 32 and "panel" not in identity_type
        ):
            return identity_type
    return ""


def _derived_tags(metadata, summary):
    material_class = summary.get("materialClass") or ""
    color_tag = _derive_color_tag(metadata, material_class)
    board_type_tag = _derive_board_type_tag(metadata)
    return {
        "derivedTags": {
            "colorTag": color_tag,
            "boardTypeTag": board_type_tag,
        },
        "typedTags": {
            "colorTag": color_tag,
            "boardTypeTag": board_type_tag,
        },
    }


def _overlay_face_registry_from_entities(body, metadata, collect_face_records=False):
    """Read-only reconciliation: face attributes are canonical, registry is index.

    No Fusion attributes are written. This keeps Attribute Ready stable even
    for legacy bodies whose face payloads were updated without a registry sync.

    When ``collect_face_records`` is True, also build the face-summary rows in
    the same pass so Scan All does not call ``read_face_metadata`` twice.
    Returns ``(metadata, face_records_or_None)``. Does not migrate — callers
    should migrate once afterward.
    """
    if body is None or not isinstance(metadata, dict) or not callable(read_face_metadata):
        return metadata, ([] if collect_face_records else None)
    # Caller may pass a disposable copy; only clone when we still share the
    # original stored dict (identity check via collect path always clones once
    # upstream).
    working = metadata
    registry = working.get("faceRegistry")
    if not isinstance(registry, dict):
        registry = {}
        working["faceRegistry"] = registry
    entries = registry.get("faces")
    if not isinstance(entries, list):
        entries = []
        registry["faces"] = entries
    by_id = {
        str(item.get("faceId") or ""): item
        for item in entries
        if isinstance(item, dict) and item.get("faceId")
    }
    by_token = {
        str(item.get("entityToken") or ""): item
        for item in entries
        if isinstance(item, dict) and item.get("entityToken")
    }
    face_records = [] if collect_face_records else None
    try:
        faces = body.faces
        count = faces.count if faces else 0
    except Exception:
        count = 0
    for index in range(count):
        try:
            face = faces.item(index)
            payload, error = read_face_metadata(face)
        except Exception:
            continue
        token = _safe_entity_token(face)
        if collect_face_records:
            face_id = str((payload or {}).get("faceId") or "") if isinstance(payload, dict) else ""
            registry_entry = by_id.get(face_id) or {}
            finish = (
                (payload or {}).get("finish")
                if isinstance((payload or {}).get("finish"), dict)
                else {}
            )
            edge_banding = (
                (payload or {}).get("edgeBanding")
                if isinstance((payload or {}).get("edgeBanding"), dict)
                else {}
            )
            face_records.append(
                {
                    "faceId": face_id,
                    "entityToken": token,
                    "faceClass": str(
                        (payload or {}).get("faceClass")
                        or registry_entry.get("faceClass")
                        or "unknown"
                    ),
                    "faceRole": str(
                        (payload or {}).get("faceRole")
                        or registry_entry.get("faceRole")
                        or "unknown"
                    ),
                    "millingSurface": str(
                        (payload or {}).get("millingSurface")
                        or registry_entry.get("millingSurface")
                        or "UNASSIGNED"
                    ),
                    "millingSource": str(
                        (payload or {}).get("millingSource")
                        or registry_entry.get("millingSource")
                        or "legacy"
                    ),
                    "millingLocked": bool(
                        (payload or {}).get(
                            "millingLocked",
                            registry_entry.get("millingLocked", False),
                        )
                    ),
                    "edgeGroupId": str(
                        (payload or {}).get("edgeGroupId")
                        or registry_entry.get("edgeGroupId")
                        or ""
                    ),
                    "edgeId": str(
                        (payload or {}).get("edgeId") or registry_entry.get("edgeId") or ""
                    ),
                    "classificationStatus": str(
                        (payload or {}).get("classificationStatus")
                        or registry_entry.get("classificationStatus")
                        or ""
                    ),
                    "finishId": finish.get("finishId") or "",
                    "finishName": finish.get("finishName") or "",
                    "edgeBandingRequired": edge_banding.get("required"),
                    "metadataStatus": "defined" if payload else "missing",
                    "warnings": [error] if error else [],
                }
            )
        if not isinstance(payload, dict):
            continue
        if str(payload.get("faceClass") or "").upper() != "SURFACE":
            continue
        role = str(payload.get("millingSurface") or "").upper()
        if not role:
            continue
        face_id = str(payload.get("faceId") or "")
        entry = by_id.get(face_id) or by_token.get(token)
        if entry is None:
            entry = {
                "faceId": face_id,
                "entityToken": token,
                "faceClass": "SURFACE",
                "faceRole": str(payload.get("faceRole") or "surface"),
            }
            entries.append(entry)
            if face_id:
                by_id[face_id] = entry
            if token:
                by_token[token] = entry
        entry["millingSurface"] = role
        entry["millingSource"] = str(
            payload.get("millingSource") or entry.get("millingSource") or "legacy"
        )
        entry["millingLocked"] = bool(
            payload.get("millingLocked", entry.get("millingLocked", False))
        )
        # Keep face-summary milling columns in sync with the registry overlay.
        if face_records is not None and face_records:
            last = face_records[-1]
            if last.get("entityToken") == token or last.get("faceId") == face_id:
                last["millingSurface"] = role
                last["millingSource"] = entry["millingSource"]
                last["millingLocked"] = entry["millingLocked"]
                last["faceClass"] = "SURFACE"
    return working, face_records


def _validate_metadata(metadata, parse_error, fallback_panel_id):
    warnings = []
    if parse_error:
        return "Invalid", [parse_error]
    if not isinstance(metadata, dict):
        return "Missing", ["Panel metadata attribute is missing."]

    summary = _metadata_summary(metadata, fallback_panel_id)
    if not metadata.get("schemaVersion"):
        warnings.append("schemaVersion is missing.")
    if not summary["panelId"]:
        warnings.append("panelId is missing.")
    if not summary["boardType"]:
        warnings.append("boardType/panelType is missing.")
    if not summary["role"]:
        warnings.append("role is missing.")
    if not summary["materialClass"]:
        warnings.append("materialClass is missing.")
    if not isinstance(metadata.get("designGeometry"), dict):
        warnings.append("designGeometry is missing.")

    if any(text.endswith("is missing.") and text.startswith(("panelId", "boardType")) for text in warnings):
        return "Invalid", warnings
    if warnings:
        return "Warning", warnings
    return "Valid", []


def _synthesize_from_ancestors(component, body_name=""):
    """Walk parentComponent chain for generator attrs when the body itself has none."""
    current = component
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        synthesized = _synthesize_module_metadata(current, current)
        if synthesized:
            if body_name:
                identity = dict(synthesized.get("identity") or {})
                identity["sourceBoardId"] = body_name
                identity["panelId"] = "{}.{}".format(identity.get("module") or "panel", body_name)
                synthesized["identity"] = identity
            return synthesized
        try:
            current = getattr(current, "parentComponent", None)
        except Exception:
            break
    return None


def _entity_record(entity, entity_kind, occurrence_path, component_name="", body_name="", include_missing=False, parent_component=None, thickness_rules_payload=None, detail="full"):
    detail_mode = str(detail or "full").strip().lower() or "full"
    light = detail_mode in ("light", "nesting", "preflight")

    metadata, parse_error, raw_metadata = _read_metadata(entity)
    fallback_panel_id = _attr_value(entity, PANEL_ID_ATTR)
    legacy_metadata = None
    synthesized = False
    # Nesting/light must still synthesize from generator/component attrs so
    # Kitchen/Lounge/GT/OHC boards without persisted Panel metadata are counted
    # (usually as Not Nesting Ready) instead of silently dropped.
    if metadata is None and not parse_error:
        # Prefer cheap parent-component Panel metadata before full synthesis.
        if parent_component is not None and entity is not parent_component:
            parent_meta, parent_err, _parent_raw = _read_metadata(parent_component)
            if isinstance(parent_meta, dict) and not parent_err:
                metadata = json.loads(json.dumps(parent_meta))
                if body_name:
                    identity = dict(metadata.get("identity") or {})
                    identity["sourceBoardId"] = body_name
                    if not identity.get("panelId"):
                        identity["panelId"] = "{}.{}".format(
                            identity.get("module") or "panel", body_name
                        )
                    metadata["identity"] = identity
                fallback_panel_id = str(
                    _path_value(metadata, [["identity", "panelId"]])
                    or fallback_panel_id
                    or ""
                )
                synthesized = True
        if metadata is None:
            legacy_metadata = _legacy_overhead_metadata(entity)
            if legacy_metadata:
                metadata = legacy_metadata
                fallback_panel_id = str(_path_value(metadata, [["identity", "panelId"]]) or fallback_panel_id or "")
            else:
                synthesized_metadata = _synthesize_module_metadata(entity, parent_component)
                if synthesized_metadata is None and parent_component is not None:
                    # Some Kitchen/Lounge boards only keep module attrs on the
                    # owning component (or an ancestor), not on every solid body.
                    synthesized_metadata = _synthesize_module_metadata(parent_component, parent_component)
                    if synthesized_metadata is None:
                        synthesized_metadata = _synthesize_from_ancestors(parent_component, body_name)
                    elif body_name:
                        identity = dict(synthesized_metadata.get("identity") or {})
                        identity["sourceBoardId"] = body_name
                        identity["panelId"] = "{}.{}".format(identity.get("module") or "panel", body_name)
                        synthesized_metadata["identity"] = identity
                if synthesized_metadata:
                    metadata = synthesized_metadata
                    synthesized = True
                    fallback_panel_id = str(_path_value(metadata, [["identity", "panelId"]]) or fallback_panel_id or "")
    if metadata is None and not parse_error and not fallback_panel_id and not include_missing:
        return None
    if light and metadata is None and not fallback_panel_id:
        # Truly unmarked solids (not generator panels) stay skipped.
        return None
    if metadata is None and include_missing and not parse_error and not fallback_panel_id:
        # Still emit a Missing row so unscanned boards are visible in the list.
        fallback_panel_id = str(body_name or component_name or "unnamed_body")

    status, warnings = _validate_metadata(metadata, parse_error, fallback_panel_id)
    if legacy_metadata:
        warnings = ["Derived from legacy UnifiedCabinetPlugin overhead body attributes."] + list(warnings or [])
        if status == "Valid":
            status = "Warning"
    if synthesized:
        warnings = [
            "Synthesized from generator attributes (no UnifiedCabinet.Panel metadata yet)."
        ] + list(warnings or [])
        if status == "Valid":
            status = "Warning"
    if status == "Missing" and entity_kind in ("body", "selected_body"):
        warnings = list(warnings or [])
        if not any("no generator" in str(w).lower() for w in warnings):
            warnings.append(
                "No UnifiedCabinet.Panel metadata and no generator module attrs on this body/component."
            )

    # Measure thickness on bodies; rule matching happens in the walk with
    # design-level rules from zone_context. Light/nesting scans skip this.
    measured = None
    if (
        not light
        and entity_kind in ("body", "selected_body")
        and thickness_rules is not None
    ):
        try:
            measured = thickness_rules.measure_body_thickness_mm(
                entity, metadata, rules_payload=thickness_rules_payload
            )
        except Exception:
            measured = None

    stored_metadata = metadata
    legacy_needs_migration = (
        isinstance(stored_metadata, dict)
        and not isinstance(stored_metadata.get("classification"), dict)
    )
    face_records = None
    if isinstance(metadata, dict):
        # One disposable copy → live face overlay → single migrate.
        working = copy.deepcopy(metadata)
        if entity_kind in ("body", "selected_body"):
            working, face_records = _overlay_face_registry_from_entities(
                entity,
                working,
                collect_face_records=not light,
            )
        normalized_metadata = attribute_state_service.migrate_metadata(
            working, inplace=True
        )
    else:
        normalized_metadata = metadata
    summary = _metadata_summary(normalized_metadata, fallback_panel_id)
    derived = _derived_tags(normalized_metadata, summary)
    attribute_readiness = None
    if callable(evaluate_attribute_ready) and isinstance(normalized_metadata, dict):
        try:
            attribute_readiness = evaluate_attribute_ready(
                normalized_metadata, derived.get("derivedTags")
            )
        except Exception:
            attribute_readiness = None
    record = {
        "entityKind": entity_kind,
        "componentName": str(component_name or ""),
        "bodyName": str(body_name or ""),
        "occurrencePath": occurrence_path,
        "entityToken": _safe_entity_token(entity),
        "status": status,
        "warnings": warnings if not light else [],
        # Full scan used to ship raw+stored+normalized (often with large SVG).
        # Palette never reads raw/stored; keep only normalized metadata.
        "rawMetadata": None,
        "storedMetadata": None,
        "metadata": normalized_metadata,
        "metadataSource": "synthesized" if synthesized else ("stored" if stored_metadata else "missing"),
        "scanDetail": detail_mode,
        **derived,
        **summary,
    }
    if legacy_needs_migration and not light:
        record["warnings"] = list(record.get("warnings") or []) + [
            "Legacy metadata normalized read-only; the next explicit write will persist canonical source/lock fields."
        ]
        if record.get("status") == "Valid":
            record["status"] = "Warning"
    if measured is not None:
        record["measuredThicknessMm"] = measured
    if attribute_readiness:
        record["attributeReady"] = bool(attribute_readiness.get("ready"))
        record["attributeReadyState"] = attribute_readiness.get("state")
        record["attributeReadyMissing"] = list(
            attribute_readiness.get("missing") or []
        )
        record["requiredFaceUp"] = attribute_readiness.get("requiredFaceUp")
        record["cuttingFace"] = attribute_readiness.get("cuttingFace") or (
            attribute_readiness.get("requiredFaceUp")
        )
    # Prefer canonical classification values on the scan record itself so
    # Nesting / UI do not need to dig through deprecated derivedTags.
    if isinstance(normalized_metadata, dict):
        classification = normalized_metadata.get("classification") or {}
        if isinstance(classification, dict):
            board_state = classification.get("boardType") or {}
            color_state = classification.get("color") or {}
            cutting_state = classification.get("cuttingFace") or {}
            if isinstance(board_state, dict) and board_state.get("value"):
                record["boardTypeTag"] = str(board_state.get("value") or "").strip()
            if isinstance(color_state, dict) and color_state.get("value"):
                record["colorTag"] = str(color_state.get("value") or "").strip()
            if isinstance(cutting_state, dict) and cutting_state.get("value"):
                cutting_value = str(cutting_state.get("value") or "").strip().upper()
                if cutting_value in ("MILLING", "EITHER"):
                    record["cuttingFace"] = cutting_value
                    record["requiredFaceUp"] = cutting_value
    if light:
        return record
    return _attach_geometry_fields(
        record, entity_kind, entity, normalized_metadata, face_records=face_records
    )


def _apply_thickness_classification(record, rules_payload):
    """Attach a read-only thickness suggestion; never mutate scanned metadata."""
    if not record or thickness_rules is None:
        return record
    measured = record.get("measuredThicknessMm")
    if measured is None:
        return record
    match = thickness_rules.match_thickness_rule(measured, rules_payload)
    if not match:
        record.setdefault("warnings", []).append(
            "Thickness {:.1f} mm did not match any configured board-type rule.".format(measured)
        )
        return record

    current_metadata = record.get("metadata")
    current_tag = thickness_rules.current_board_type_tag(current_metadata)
    record["thicknessSuggestion"] = {
        "boardTypeTag": match.get("boardTypeTag"),
        "thicknessMm": match.get("thicknessMm"),
        "deltaMm": match.get("deltaMm"),
        "wouldChange": (
            not thickness_rules.has_known_board_type(current_metadata)
            or current_tag != str(match.get("boardTypeTag") or "").strip().lower()
        ),
    }
    if record["thicknessSuggestion"]["wouldChange"]:
        record.setdefault("warnings", []).append(
            "Thickness suggestion only (not written): {:.1f} mm → {} (rule {:.1f} mm).".format(
                measured,
                match.get("boardTypeTag"),
                float(match.get("thicknessMm") or 0),
            )
        )
    return record


def _attach_geometry_fields(record, entity_kind, entity, metadata, face_records=None):
    if entity_kind not in ("body", "selected_body"):
        return record
    if face_records is None and callable(list_body_face_records):
        face_records = list_body_face_records(entity, metadata)
    if face_records:
        registry = (metadata or {}).get("faceRegistry") or {}
        record["faceSummary"] = {
            "surfaceMode": registry.get("surfaceMode") or "",
            "faceCount": len(face_records),
            "definedFaceCount": sum(
                1 for item in face_records if item.get("metadataStatus") == "defined"
            ),
            "edgeCount": len(registry.get("edges") or []),
            "faces": face_records,
            "edges": registry.get("edges") or [],
            "edgeGroups": registry.get("edgeGroups") or [],
            "featureFaceCount": len(registry.get("featureFaces") or []),
            "featureFaces": registry.get("featureFaces") or [],
        }
    meta = metadata or {}
    dimensions = meta.get("dimensions")
    if isinstance(dimensions, dict):
        record["dimensions"] = dimensions
    feature_summary = meta.get("featureSummary")
    if isinstance(feature_summary, dict):
        record["featureSummary"] = feature_summary
    features = meta.get("features")
    if isinstance(features, list):
        record["features"] = features
    milling_svg = meta.get("millingSurfaceSvg")
    if isinstance(milling_svg, dict):
        # Keep SVG preview for detail pane; avoid shipping duplicate raw/stored.
        record["millingSurfaceSvg"] = {
            "viewBox": milling_svg.get("viewBox"),
            "widthMm": milling_svg.get("widthMm"),
            "heightMm": milling_svg.get("heightMm"),
            "svg": milling_svg.get("svg"),
        }
    return record


WORK_ZONE_BODY_NAMES = {"AssemblyZone", "GenerationZone", "NestingZone"}


def _is_assembly_zone(body):
    """True for work-zone helper planes so they are never treated as panels."""
    try:
        attr = body.attributes.itemByName("UnifiedCabinet", "systemRole")
        if attr and str(attr.value) in ("assemblyZone", "workZone"):
            return True
    except Exception:
        pass
    try:
        return str(getattr(body, "name", "") or "") in WORK_ZONE_BODY_NAMES
    except Exception:
        return False


def _is_nested_instance(body):
    if work_zones is not None:
        try:
            return work_zones.is_nested_instance(body)
        except Exception:
            return False
    try:
        attr = body.attributes.itemByName("UnifiedCabinet", "instanceRole")
        return bool(attr and str(attr.value) == "nested")
    except Exception:
        return False


def _safe_entity_token(entity):
    """entityToken raises on nested proxies whose top parent is not root."""
    if not entity:
        return ""
    try:
        return str(getattr(entity, "entityToken", "") or "")
    except Exception:
        return ""


def _occurrence_proxy_in_root(root_component, occurrence_path):
    """Build an occurrence proxy whose assembly context is the root component.

    Fusion only allows entityToken on proxies whose top-level parent is root.
    Nested leaf occurrences must be re-created via createForAssemblyContext
    along the path; a bare nested Occurrence will crash on .entityToken.
    """
    path = list(occurrence_path or [])
    if not root_component or not path:
        return None
    try:
        occ = None
        component = root_component
        for index in path:
            if not component.occurrences or index >= component.occurrences.count:
                return None
            child = component.occurrences.item(index)
            occ = child if occ is None else child.createForAssemblyContext(occ)
            if occ is None:
                return None
            component = child.component
        return occ
    except Exception:
        return None


def _body_proxy_in_root(body, root_component, occurrence_path):
    if not body:
        return None
    occ = _occurrence_proxy_in_root(root_component, occurrence_path)
    if occ is None:
        return body
    try:
        proxy = body.createForAssemblyContext(occ)
        return proxy or body
    except Exception:
        return body


def _walk_component(component, occurrence_path, sink, zone_context=None, root_component=None, detail="full"):
    if not component:
        return
    root = root_component or component
    detail_mode = str(detail or "full").strip().lower() or "full"
    light = detail_mode in ("light", "nesting", "preflight")

    if not light:
        component_record = _entity_record(
            component,
            "component",
            occurrence_path,
            component_name=getattr(component, "name", "") or "",
            parent_component=component,
            detail=detail_mode,
        )
        if component_record:
            sink.append(component_record)

    for body in list_solid_bodies(component):
        if _is_assembly_zone(body):
            continue
        # Nested copies (nesting layout output) are never scanned as panels:
        # they duplicate the panelId of the assembly-zone original.
        if _is_nested_instance(body):
            continue

        profiler = (zone_context or {}).get("profiler")
        # Always resolve an occurrence proxy when the body lives under an
        # occurrence path. Light/nesting scans used to skip this for speed, but
        # then:
        # 1) body attributes written via selection proxies were often invisible
        #    on the bare component body → false "unmarked solids skipped"
        # 2) Nesting-zone exclusion used wrong world centres without the
        #    assembly transform → assembly boards could be misclassified.
        # Scan All (full) already used proxies; Nesting Ready must match.
        if occurrence_path:
            scan_body = _body_proxy_in_root(body, root, occurrence_path) or body
        else:
            scan_body = body

        body_t0 = None
        if profiler is not None:
            try:
                import time as _time
                body_t0 = _time.perf_counter()
            except Exception:
                body_t0 = None

        body_record = _entity_record(
            scan_body,
            "body",
            occurrence_path,
            component_name=getattr(component, "name", "") or "",
            body_name=getattr(body, "name", "") or "",
            parent_component=component,
            include_missing=not light,
            thickness_rules_payload=(zone_context or {}).get("thicknessRules"),
            detail=detail_mode,
        )
        if not body_record:
            if profiler is not None:
                profiler.add("bodiesSkippedNoAttrs", 1)
            continue
        # Accumulate solid diagnostics during the main walk so Scan All does not
        # pay for a second full-tree metadata pass via _count_solid_bodies.
        diag = None
        if isinstance(zone_context, dict) and not light:
            diag = zone_context.setdefault(
                "solidDiag",
                {
                    "solidBodies": 0,
                    "withModuleOrPanelId": 0,
                    "withPanelMetadata": 0,
                    "withoutAttrs": 0,
                },
            )
            diag["solidBodies"] = int(diag.get("solidBodies") or 0) + 1
            if body_record.get("metadata"):
                diag["withPanelMetadata"] = int(diag.get("withPanelMetadata") or 0) + 1
            if str(body_record.get("metadataSource") or "") in ("stored", "synthesized"):
                diag["withModuleOrPanelId"] = int(diag.get("withModuleOrPanelId") or 0) + 1
            else:
                diag["withoutAttrs"] = int(diag.get("withoutAttrs") or 0) + 1
        if profiler is not None:
            profiler.add("bodiesRecorded", 1)
            if body_t0 is not None:
                try:
                    import time as _time
                    elapsed = int((_time.perf_counter() - body_t0) * 1000)
                    if elapsed >= 200:
                        profiler.sample(
                            "scanBody",
                            elapsed,
                            bodyName=body_record.get("bodyName") or "",
                            componentName=body_record.get("componentName") or "",
                        )
                    if profiler.counters.get("bodiesRecorded", 0) % 25 == 0:
                        profiler.mark(
                            "scanProgress",
                            bodies=profiler.counters.get("bodiesRecorded", 0),
                        )
                except Exception:
                    pass
        rules_payload = (zone_context or {}).get("thicknessRules")
        if rules_payload and not light:
            body_record = _apply_thickness_classification(body_record, rules_payload)
        if scan_body is not body:
            token = _safe_entity_token(scan_body)
            if token:
                body_record["entityToken"] = token
            body_record["selectionProxy"] = True
        layout = (zone_context or {}).get("layout")
        zone_filter = (zone_context or {}).get("filter") if layout is not None else None
        # When work zones exist, classify every body so Nesting-zone workpieces
        # can be excluded from source scans (Scan All / Ready / layout sources).
        need_zone = bool(layout is not None and work_zones is not None)
        if need_zone:
            zone = work_zones.zone_of_body(scan_body, layout)
            body_record["zone"] = zone
            role = work_zones.instance_role_of_body(scan_body) or work_zones.instance_role_of_body(body)
            if role:
                body_record["instanceRole"] = role
            # Nesting Zone holds layout copies. Never treat them as source panels
            # unless the user explicitly chose the Nesting zone filter.
            if zone == work_zones.ZONE_NESTING and zone_filter != work_zones.ZONE_NESTING:
                if isinstance(zone_context, dict):
                    zone_context["skippedNestingZone"] = int(
                        zone_context.get("skippedNestingZone") or 0
                    ) + 1
                if profiler is not None:
                    profiler.add("bodiesSkippedNestingZone", 1)
                continue
            if zone == work_zones.ZONE_NESTING and not light:
                body_record.setdefault("warnings", []).append(
                    "Body sits in the Nesting zone (explicit Nesting-zone scan)."
                )
            if zone_filter and zone_filter != "all" and zone != zone_filter:
                continue
        sink.append(body_record)

    try:
        occurrences = component.occurrences
        count = occurrences.count if occurrences else 0
    except Exception:
        return
    for index in range(count):
        child = occurrences.item(index)
        _walk_component(
            child.component,
            occurrence_path + [index],
            sink,
            zone_context,
            root_component=root,
            detail=detail_mode,
        )


def _count_solid_bodies(root_component):
    """Count solid bodies that are not work-zone helpers / nested copies."""
    total = 0
    with_module_attr = 0
    with_panel_metadata = 0
    without_attrs = 0

    def _walk(component):
        nonlocal total, with_module_attr, with_panel_metadata, without_attrs
        if not component:
            return
        for body in list_solid_bodies(component):
            if _is_assembly_zone(body) or _is_nested_instance(body):
                continue
            total += 1
            has_module = bool(_module_attr_value(body, "module") or _attr_value(body, PANEL_ID_ATTR))
            if not has_module:
                # Also count component-level generator attrs as "known".
                try:
                    parent = getattr(body, "parentComponent", None) or getattr(body, "component", None)
                except Exception:
                    parent = None
                has_module = bool(_module_attr_value(parent, "module"))
            if has_module:
                with_module_attr += 1
            else:
                without_attrs += 1
            metadata, _err, _raw = _read_metadata(body)
            if metadata is not None:
                with_panel_metadata += 1
        try:
            occurrences = component.occurrences
            count = occurrences.count if occurrences else 0
        except Exception:
            return
        for index in range(count):
            try:
                _walk(occurrences.item(index).component)
            except Exception:
                continue

    _walk(root_component)
    return {
        "solidBodies": total,
        "withModuleOrPanelId": with_module_attr,
        "withPanelMetadata": with_panel_metadata,
        "withoutAttrs": without_attrs,
    }


def scan_panel_metadata(root_component, zone_filter=None, detail="full", profiler=None):
    import time as _time

    started = _time.perf_counter()
    records = []
    layout = None
    detail_mode = str(detail or "full").strip().lower() or "full"
    light = detail_mode in ("light", "nesting", "preflight")
    if profiler is not None:
        profiler.begin("scanWalk")
        profiler.mark("scanBegin", detail=detail_mode)
    if work_zones is not None:
        try:
            layout = work_zones.load_zone_layout(root_component)
        except Exception:
            layout = None
    # The zone filter only applies when work zones exist in the design;
    # without zones every body is scanned (safe default).
    zone_context = {
        "layout": layout,
        "filter": zone_filter if layout else None,
        "profiler": profiler,
        "skippedNestingZone": 0,
    }
    if not light and thickness_rules is not None:
        try:
            zone_context["thicknessRules"] = thickness_rules.load_rules(root_component)
        except Exception:
            zone_context["thicknessRules"] = thickness_rules.normalize_rules(thickness_rules.DEFAULT_RULES)
    _walk_component(
        root_component,
        [],
        records,
        zone_context,
        root_component=root_component,
        detail=detail_mode,
    )
    if profiler is not None:
        profiler.end("scanWalk")
        profiler.begin("scanFinalize")
    records, counts = _finalize_records(records)
    # Prefer walk-time solid counts (full scan). Fall back to a second walk only
    # when diagnostics were not collected (should not happen for detail=full).
    walk_diag = zone_context.get("solidDiag") if isinstance(zone_context, dict) else None
    if light:
        diagnostics = {}
    elif isinstance(walk_diag, dict) and int(walk_diag.get("solidBodies") or 0) > 0:
        diagnostics = {
            "solidBodies": int(walk_diag.get("solidBodies") or 0),
            "withModuleOrPanelId": int(walk_diag.get("withModuleOrPanelId") or 0),
            "withPanelMetadata": int(walk_diag.get("withPanelMetadata") or 0),
            "withoutAttrs": int(walk_diag.get("withoutAttrs") or 0),
        }
    else:
        diagnostics = _count_solid_bodies(root_component)
    body_records = [r for r in records if "body" in str(r.get("entityKind") or "").lower()]
    diagnostics["scannedRecords"] = len(records)
    diagnostics["scannedBodies"] = len(body_records)
    diagnostics["zoneFilter"] = zone_filter if layout else None
    diagnostics["workZonesPresent"] = bool(layout)
    diagnostics["scanDetail"] = detail_mode
    diagnostics["elapsedMs"] = int((_time.perf_counter() - started) * 1000)
    skipped_nesting = int(zone_context.get("skippedNestingZone") or 0)
    if profiler is not None:
        skipped_nesting = max(
            skipped_nesting,
            int(profiler.counters.get("bodiesSkippedNestingZone") or 0),
        )
    diagnostics["bodiesSkippedNestingZone"] = skipped_nesting
    if profiler is not None:
        profiler.end("scanFinalize")
        profiler.add("scannedBodies", len(body_records))
        profiler.mark(
            "scanDone",
            bodies=len(body_records),
            skippedNestingZone=skipped_nesting,
            elapsedMs=diagnostics["elapsedMs"],
        )
    if not light:
        diagnostics["missingBodies"] = sum(1 for r in body_records if r.get("status") == "Missing")
        if layout and zone_filter and zone_filter != "all":
            zone_counts = {}
            for record in body_records:
                zone = str(record.get("zone") or "unknown")
                zone_counts[zone] = zone_counts.get(zone, 0) + 1
            diagnostics["zoneCountsInResult"] = zone_counts
        skipped = max(0, int(diagnostics.get("solidBodies") or 0) - len(body_records))
        diagnostics["bodiesNotInScan"] = skipped
    return records, counts, diagnostics


def _component_name_for_body(body):
    for attr_name in ("parentComponent", "component"):
        try:
            component = getattr(body, attr_name)
        except Exception:
            component = None
        if component:
            return str(getattr(component, "name", "") or "")
    return ""


def _body_key(body):
    token = _safe_entity_token(body)
    if token:
        return token
    return str(id(body))


def _selection_body(entity):
    if not entity:
        return None, "unknown"

    object_type = ""
    try:
        object_type = str(getattr(entity, "objectType", "") or "")
    except Exception:
        object_type = ""

    if "BRepBody" in object_type:
        return entity, "body"

    for attr_name in ("body", "parentBody"):
        try:
            body = getattr(entity, attr_name)
        except Exception:
            body = None
        if body:
            return body, "face" if "BRepFace" in object_type else "selection"

    # Fallback for body-like objects if objectType is unavailable.
    if hasattr(entity, "bRepFaces") or hasattr(entity, "faces"):
        return entity, "body"

    return None, object_type or type(entity).__name__


def _entity_object_type(entity):
    try:
        return str(getattr(entity, "objectType", "") or "")
    except Exception:
        return ""


def _entity_kind(entity):
    object_type = _entity_object_type(entity)
    if "BRepBody" in object_type:
        return "body"
    if "BRepFace" in object_type:
        return "face"
    if "BRepEdge" in object_type:
        return "edge"
    if "Occurrence" in object_type:
        return "occurrence"
    if "Component" in object_type:
        return "component"
    # Fallbacks when objectType is missing (unit tests / stubs).
    if hasattr(entity, "component") and hasattr(entity, "occurrencePath"):
        return "occurrence"
    if hasattr(entity, "bRepBodies") and hasattr(entity, "occurrences"):
        return "component"
    return object_type or type(entity).__name__


def _occurrence_path_indices(occurrence):
    """Best-effort path of occurrence indices from root (may be empty)."""
    path = []
    try:
        raw = getattr(occurrence, "occurrencePath", None)
        if raw is not None:
            try:
                count = raw.count
            except Exception:
                count = len(raw) if hasattr(raw, "__len__") else 0
            for index in range(count):
                try:
                    item = raw.item(index) if hasattr(raw, "item") else raw[index]
                except Exception:
                    item = None
                if item is None:
                    continue
                try:
                    path.append(int(getattr(item, "index", index)))
                except Exception:
                    path.append(index)
            if path:
                return path
    except Exception:
        pass
    return path


def _collect_bodies_under_occurrence(occurrence, root_component, sink, seen):
    """Append unique solid panel bodies under an occurrence as selectable proxies.

    Prefer ``occurrence.bRepBodies`` — Fusion returns body proxies already in
    that assembly context, which ``selection.add`` accepts. Falling back to
    native component bodies (empty occurrencePath) is what made Select Colour /
    Milling Faces report "Found N faces but could not select them".
    """
    if occurrence is None:
        return
    try:
        bodies = occurrence.bRepBodies
        count = bodies.count if bodies else 0
    except Exception:
        count = 0
    for index in range(count):
        try:
            body = bodies.item(index)
        except Exception:
            continue
        if not body:
            continue
        try:
            if not bool(getattr(body, "isSolid", True)):
                continue
        except Exception:
            pass
        if _is_assembly_zone(body):
            continue
        if _is_nested_instance(body):
            continue
        key = _body_key(body)
        if key in seen:
            continue
        seen.add(key)
        sink.append(body)

    try:
        children = occurrence.childOccurrences
        child_count = children.count if children else 0
    except Exception:
        return
    for index in range(child_count):
        try:
            child = children.item(index)
        except Exception:
            continue
        _collect_bodies_under_occurrence(child, root_component, sink, seen)


def _collect_bodies_under_component(component, occurrence_path, root_component, sink, seen):
    """Append unique solid panel bodies under component (skip zones / nested copies)."""
    if not component:
        return
    root = root_component or component
    for body in list_solid_bodies(component):
        if _is_assembly_zone(body):
            continue
        if _is_nested_instance(body):
            continue
        scan_body = _body_proxy_in_root(body, root, occurrence_path)
        key = _body_key(scan_body)
        if key in seen:
            continue
        seen.add(key)
        sink.append(scan_body)

    try:
        occurrences = component.occurrences
        count = occurrences.count if occurrences else 0
    except Exception:
        return
    for index in range(count):
        child = occurrences.item(index)
        # Prefer walking the occurrence itself so collected bodies are proxies.
        try:
            child_proxy = child
            if occurrence_path:
                # Rebuild nested occurrence in root context when we have a path.
                parent_occ = _occurrence_proxy_in_root(root, occurrence_path)
                if parent_occ is not None:
                    try:
                        child_proxy = child.createForAssemblyContext(parent_occ) or child
                    except Exception:
                        child_proxy = child
            _collect_bodies_under_occurrence(child_proxy, root, sink, seen)
            continue
        except Exception:
            pass
        _collect_bodies_under_component(
            child.component,
            list(occurrence_path or []) + [index],
            root,
            sink,
            seen,
        )


def bodies_from_selected_entities(selected_entities, root_component=None):
    """Expand Fusion selection to unique solid bodies (assemblies included).

    Supports Occurrence / Component / BRepBody / BRepFace / BRepEdge.
    Returns (bodies, warnings).
    """
    bodies = []
    warnings = []
    seen = set()

    for entity in selected_entities or []:
        kind = _entity_kind(entity)
        if kind == "occurrence":
            before = len(bodies)
            _collect_bodies_under_occurrence(entity, root_component, bodies, seen)
            if len(bodies) == before:
                # Fallback: path-based walk if occurrence.bRepBodies was empty.
                try:
                    component = entity.component
                except Exception:
                    component = None
                if component:
                    path = _occurrence_path_indices(entity)
                    _collect_bodies_under_component(component, path, root_component, bodies, seen)
            if len(bodies) == before:
                warnings.append("No solid panel bodies under selected occurrence.")
            continue

        if kind == "component":
            before = len(bodies)
            _collect_bodies_under_component(entity, [], root_component or entity, bodies, seen)
            if len(bodies) == before:
                warnings.append("No solid panel bodies under selected component.")
            continue

        body, source_kind = _selection_owner_body(entity)
        if not body:
            warnings.append("Unsupported selection: {}".format(kind or source_kind))
            continue
        if _is_assembly_zone(body):
            warnings.append("Skipped work-zone helper body.")
            continue
        if _is_nested_instance(body):
            warnings.append("Skipped nested-instance copy (nesting output).")
            continue
        key = _body_key(body)
        if key in seen:
            continue
        seen.add(key)
        bodies.append(body)

    return bodies, warnings


def metadata_looks_like_door(metadata):
    """True when body metadata is already classified as a door panel."""
    if not isinstance(metadata, dict):
        return False
    board_tag = str(
        _path_value(metadata, [["derivedTags", "boardTypeTag"], ["typedTags", "boardTypeTag"]]) or ""
    ).strip().lower()
    if board_tag == "door":
        return True
    material_class = str(
        _path_value(metadata, [["defaultAttributes", "materialClass"], ["materialClass"]]) or ""
    ).strip()
    if material_class == "door_board":
        return True
    role = str(
        _path_value(metadata, [["defaultAttributes", "role"], ["role"], ["panelType"]]) or ""
    ).strip().lower()
    if role in ("door", "front_visible"):
        return True
    # Fall back to derived board type heuristics.
    return _derive_board_type_tag(metadata) == "door"


def _body_name_looks_like_door(name):
    """Heuristic for generator body names when formal metadata is missing."""
    text = str(name or "").strip().lower().replace("-", "_")
    if not text:
        return False
    if "frontpanel" in text or "front_panel" in text:
        return True
    if "_fp_" in text or text.startswith("gt_fp") or text.startswith("oh_fp") or text.startswith("fp_"):
        return True
    if "door" in text and "board" not in text:
        return True
    if "flap" in text or "fascia" in text:
        return True
    return False


def body_looks_like_door(body):
    """True when a Fusion body is a door / front panel.

    Checks formal Panel metadata first, then synthesizes from CabinetNC /
    generator attributes (Kitchen frontPanel, GT FP*, …), then body-name
    heuristics. This is what Orient / door-color / door filters must use —
    raw ``_read_body_metadata_raw`` alone misses Kitchen doors that only
    carry ``CabinetNC`` attrs.
    """
    if body is None:
        return False

    # 1) Formal UnifiedCabinet.Panel payload.
    try:
        from tag_metadata_editor import _read_body_metadata_raw
    except Exception:
        try:
            from panel_attributes.tag_metadata_editor import _read_body_metadata_raw
        except Exception:
            _read_body_metadata_raw = None
    if callable(_read_body_metadata_raw):
        try:
            metadata, _err = _read_body_metadata_raw(body)
        except Exception:
            metadata = None
        if isinstance(metadata, dict):
            classification = metadata.get("classification")
            board_state = (
                classification.get("boardType")
                if isinstance(classification, dict)
                else None
            )
            canonical = str((board_state or {}).get("value") or "").strip().lower()
            if canonical and not attribute_state_service.is_undefined(canonical):
                return canonical == "door"
            if metadata_looks_like_door(metadata):
                return True

    # 2) Generator attrs on body / owning component (Kitchen, Lounge, …).
    try:
        component = None
        try:
            assembly = getattr(body, "assemblyContext", None)
            component = getattr(assembly, "component", None) if assembly else None
        except Exception:
            component = None
        synthesized = _synthesize_module_metadata(body, component)
        if isinstance(synthesized, dict) and metadata_looks_like_door(synthesized):
            return True
    except Exception:
        pass

    # 3) Body name fallback (e.g. KITCHEN_frontPanel_…, GT_FP_…).
    try:
        if _body_name_looks_like_door(getattr(body, "name", "") or ""):
            return True
    except Exception:
        pass
    return False


def _edge_body(edge):
    for attr_name in ("body", "parentBody"):
        try:
            body = getattr(edge, attr_name)
        except Exception:
            body = None
        if body:
            return body
    try:
        faces = edge.faces
        if faces and faces.count:
            first_face = faces.item(0)
            body = getattr(first_face, "body", None)
            if body:
                return body
    except Exception:
        pass
    return None


def _selection_owner_body(entity):
    kind = _entity_kind(entity)
    if kind == "edge":
        return _edge_body(entity), kind
    body, source_kind = _selection_body(entity)
    return body, kind if kind in ("body", "face") else source_kind


def _face_scan(face):
    metadata = None
    error = None
    if read_face_metadata:
        metadata, error = read_face_metadata(face)
    face_class = str((metadata or {}).get("faceClass") or "unknown")
    finish = (metadata or {}).get("finish") if isinstance((metadata or {}).get("finish"), dict) else {}
    edge_banding = (metadata or {}).get("edgeBanding")
    edge_banding_color = "unknown"
    if isinstance(edge_banding, dict):
        edge_banding_color = edge_banding.get("finishId") or edge_banding.get("finishName") or "unknown"
    milling_surface = (metadata or {}).get("millingSurface")
    return {
        "selectionType": "face",
        "selectionEntityToken": _safe_entity_token(face),
        "faceClass": face_class,
        "faceRole": str((metadata or {}).get("faceRole") or "unknown"),
        "millingSurface": str(milling_surface) if milling_surface else "unknown",
        "side": "unknown",
        "color": finish.get("finishId") or finish.get("finishName") or "unknown",
        "edgeBandingRequired": edge_banding.get("required") if isinstance(edge_banding, dict) else None,
        "edgeBandingColor": edge_banding_color,
        "metadataStatus": "defined" if metadata else "missing",
        "metadata": metadata,
        "warnings": [error] if error else [],
    }


def _edge_scan(edge):
    adjacent_faces = 0
    try:
        adjacent_faces = edge.faces.count if edge.faces else 0
    except Exception:
        adjacent_faces = 0
    return {
        "selectionType": "edge",
        "selectionEntityToken": _safe_entity_token(edge),
        "edgeKind": "unresolved",
        "adjacentFaceCount": adjacent_faces,
        "edgeBandingRequired": "unknown",
        "edgeBandingColor": "unknown",
        "warnings": ["Edge manufacturing semantics are not implemented yet."],
    }


def tag_scan_selected(selected_entities, root_component=None):
    results = []
    warnings = []
    selected_body_keys = set()
    for entity in selected_entities or []:
        selection_type = _entity_kind(entity)
        if selection_type != "body":
            continue
        body, _source_kind = _selection_owner_body(entity)
        if body:
            selected_body_keys.add(_body_key(body))

    for entity in selected_entities or []:
        selection_type = _entity_kind(entity)
        body, _source_kind = _selection_owner_body(entity)
        if not body:
            warnings.append("Unsupported selection: {}".format(selection_type))
            continue
        if _is_assembly_zone(body):
            warnings.append("Skipped work-zone helper body.")
            continue
        if _is_nested_instance(body):
            warnings.append("Skipped nested-instance copy (nesting output).")
            continue
        if selection_type in ("face", "edge") and _body_key(body) in selected_body_keys:
            continue

        occurrence_path = resolve_occurrence_path_for_body(root_component, body) if root_component else []
        body_record = _entity_record(
            body,
            "selected_body",
            occurrence_path,
            component_name=_component_name_for_body(body),
            body_name=getattr(body, "name", "") or "",
            include_missing=True,
        )
        selection_detail = {"selectionType": selection_type}
        if selection_type == "face":
            selection_detail = _face_scan(entity)
        elif selection_type == "edge":
            selection_detail = _edge_scan(entity)
        elif selection_type == "body":
            selection_detail = {
                "selectionType": "body",
                "selectionEntityToken": _safe_entity_token(entity),
                "metadataStatus": "defined" if body_record.get("metadata") else "missing",
            }

        results.append(
            {
                "selectionType": selection_type,
                "body": body_record,
                "selection": selection_detail,
            }
        )
    return results, warnings


def scan_selected_panel_metadata(selected_entities):
    records = []
    skipped = []
    seen = set()

    for entity in selected_entities or []:
        body, source_kind = _selection_body(entity)
        if not body:
            skipped.append("Unsupported selection: {}".format(source_kind))
            continue
        if _is_assembly_zone(body):
            skipped.append("Skipped work-zone helper body.")
            continue
        if _is_nested_instance(body):
            skipped.append("Skipped nested-instance copy (nesting output).")
            continue
        key = _body_key(body)
        if key in seen:
            continue
        seen.add(key)
        record = _entity_record(
            body,
            "selected_body",
            [],
            component_name=_component_name_for_body(body),
            body_name=getattr(body, "name", "") or "",
            include_missing=True,
        )
        if record:
            record["selectionSource"] = source_kind
            records.append(record)

    records, counts = _finalize_records(records)
    return records, counts, skipped


def _finalize_records(records):

    panel_id_counts = {}
    for record in records:
        panel_id = str(record.get("panelId") or "").strip()
        if panel_id:
            panel_id_counts[panel_id] = panel_id_counts.get(panel_id, 0) + 1

    for record in records:
        panel_id = str(record.get("panelId") or "").strip()
        if panel_id and panel_id_counts.get(panel_id, 0) > 1:
            record.setdefault("warnings", []).append("Duplicate panelId appears {} times.".format(panel_id_counts[panel_id]))
            if record.get("status") == "Valid":
                record["status"] = "Warning"

    counts = {"Valid": 0, "Warning": 0, "Invalid": 0, "Missing": 0}
    for record in records:
        status = record.get("status") or "Missing"
        counts[status] = counts.get(status, 0) + 1

    return records, counts
