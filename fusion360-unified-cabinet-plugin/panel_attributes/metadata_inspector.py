import json

from panel_body_resolver import list_solid_bodies, resolve_occurrence_path_for_body
from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, PANEL_METADATA_ATTR

try:
    from face_attribute_store import read_face_metadata
except Exception:
    read_face_metadata = None

try:
    from panel_face_initializer import list_body_face_records
except Exception:
    list_body_face_records = None

LEGACY_ATTRIBUTE_GROUP = "UnifiedCabinetPlugin"


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


def _metadata_surface_mode(metadata):
    value = _path_value(
        metadata,
        [
            ["defaultAttributes", "surfaceMode"],
            ["surfaceMode"],
            ["faceMetadata", "surfaceMode"],
            ["manufacturingDefaults", "surfaceMode"],
        ],
    )
    return str(value or "").strip()


def _metadata_door_color_slot(metadata):
    value = _path_value(
        metadata,
        [["defaultAttributes", "doorColorSlot"], ["doorColorSlot"]],
    )
    try:
        return int(value)
    except Exception:
        return None


def _derive_color_tag(metadata, material_class):
    explicit = _path_value(
        metadata,
        [["derivedTags", "colorTag"], ["typedTags", "colorTag"], ["colorTag"]],
    )
    if explicit == "white_stipple" or _contains_white_stipple(explicit):
        return "white_stipple"
    if _contains_white_stipple(metadata):
        return "white_stipple"

    if material_class == "carcass_board":
        return "carcass_colour"
    if material_class != "door_board":
        return ""

    slot = _metadata_door_color_slot(metadata)
    if slot not in (1, 2):
        return ""

    surface_mode = _metadata_surface_mode(metadata)
    if surface_mode == "single_sided":
        return "door_colour_{}_single_sided".format(slot)
    if surface_mode == "double_sided":
        return "door_colour_{}_double_sided".format(slot)
    return "door_colour_{}_unknown_surface_mode".format(slot)


def _derive_board_type_tag(metadata):
    explicit = _path_value(
        metadata,
        [["derivedTags", "boardTypeTag"], ["typedTags", "boardTypeTag"]],
    )
    if explicit in ("carcass", "partition", "door"):
        return str(explicit)

    material_class = str(_path_value(metadata, [["defaultAttributes", "materialClass"], ["materialClass"]]) or "")
    role = str(_path_value(metadata, [["defaultAttributes", "role"], ["role"], ["panelType"]]) or "").lower()
    category = str(_path_value(metadata, [["defaultAttributes", "category"], ["category"]]) or "").lower()
    panel_type = str(_path_value(metadata, [["panelType"]]) or "").lower()

    if material_class == "door_board" or role in ("door", "front_visible") or panel_type == "door":
        return "door"
    if role == "partition" or category == "partition" or panel_type == "partition":
        return "partition"
    if material_class == "carcass_board" or role in ("carcass", "carcass_rail") or panel_type == "carcass":
        return "carcass"
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


def _entity_record(entity, entity_kind, occurrence_path, component_name="", body_name="", include_missing=False):
    metadata, parse_error, raw_metadata = _read_metadata(entity)
    fallback_panel_id = _attr_value(entity, PANEL_ID_ATTR)
    legacy_metadata = None
    if metadata is None and not parse_error:
        legacy_metadata = _legacy_overhead_metadata(entity)
        if legacy_metadata:
            metadata = legacy_metadata
            fallback_panel_id = str(_path_value(metadata, [["identity", "panelId"]]) or fallback_panel_id or "")
    if metadata is None and not parse_error and not fallback_panel_id and not include_missing:
        return None

    status, warnings = _validate_metadata(metadata, parse_error, fallback_panel_id)
    if legacy_metadata:
        warnings = ["Derived from legacy UnifiedCabinetPlugin overhead body attributes."] + list(warnings or [])
        if status == "Valid":
            status = "Warning"
    summary = _metadata_summary(metadata, fallback_panel_id)
    record = {
        "entityKind": entity_kind,
        "componentName": str(component_name or ""),
        "bodyName": str(body_name or ""),
        "occurrencePath": occurrence_path,
        "entityToken": str(getattr(entity, "entityToken", "") or ""),
        "status": status,
        "warnings": warnings,
        "rawMetadata": raw_metadata,
        "metadata": metadata,
        **_derived_tags(metadata, summary),
        **summary,
    }
    if entity_kind in ("body", "selected_body") and callable(list_body_face_records):
        face_records = list_body_face_records(entity, metadata)
        if face_records:
            registry = (metadata or {}).get("faceRegistry") or {}
            record["faceSummary"] = {
                "surfaceMode": registry.get("surfaceMode") or "",
                "faceCount": len(face_records),
                "definedFaceCount": sum(1 for item in face_records if item.get("metadataStatus") == "defined"),
                "edgeCount": len(registry.get("edges") or []),
                "faces": face_records,
                "edges": registry.get("edges") or [],
                "edgeGroups": registry.get("edgeGroups") or [],
                "featureFaceCount": len(registry.get("featureFaces") or []),
                "featureFaces": registry.get("featureFaces") or [],
            }
    if entity_kind in ("body", "selected_body"):
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
            record["millingSurfaceSvg"] = {
                "viewBox": milling_svg.get("viewBox"),
                "widthMm": milling_svg.get("widthMm"),
                "heightMm": milling_svg.get("heightMm"),
                "svg": milling_svg.get("svg"),
            }
    return record


def _is_assembly_zone(body):
    """True for the Assembly Zone helper body so it is never treated as a panel."""
    try:
        attr = body.attributes.itemByName("UnifiedCabinet", "systemRole")
        if attr and str(attr.value) == "assemblyZone":
            return True
    except Exception:
        pass
    try:
        return str(getattr(body, "name", "") or "") == "AssemblyZone"
    except Exception:
        return False


def _walk_component(component, occurrence_path, sink):
    if not component:
        return

    component_record = _entity_record(
        component,
        "component",
        occurrence_path,
        component_name=getattr(component, "name", "") or "",
    )
    if component_record:
        sink.append(component_record)

    for body in list_solid_bodies(component):
        if _is_assembly_zone(body):
            continue
        body_record = _entity_record(
            body,
            "body",
            occurrence_path,
            component_name=getattr(component, "name", "") or "",
            body_name=getattr(body, "name", "") or "",
        )
        if body_record:
            sink.append(body_record)

    try:
        occurrences = component.occurrences
        count = occurrences.count if occurrences else 0
    except Exception:
        return
    for index in range(count):
        occurrence = occurrences.item(index)
        _walk_component(occurrence.component, occurrence_path + [index], sink)


def scan_panel_metadata(root_component):
    records = []
    _walk_component(root_component, [], records)
    return _finalize_records(records)


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
    try:
        token = getattr(body, "entityToken", None)
        if token:
            return str(token)
    except Exception:
        pass
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
    return object_type or type(entity).__name__


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
        "selectionEntityToken": str(getattr(face, "entityToken", "") or ""),
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
        "selectionEntityToken": str(getattr(edge, "entityToken", "") or ""),
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
            warnings.append("Skipped Assembly Zone helper body.")
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
                "selectionEntityToken": str(getattr(entity, "entityToken", "") or ""),
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
            skipped.append("Skipped Assembly Zone helper body.")
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
