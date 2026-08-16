"""Fusion creation of Lay Flat manufacturing copies (machining face +Z)."""

from __future__ import annotations

import json
import math
import time

import adsk.core
import adsk.fusion

try:
    from nesting import lay_flat
    from nesting.fusion_layout import (
        _attr,
        _bbox_dimensions_mm,
        _set_attr,
        _translation_matrix,
        delete_previous_layouts,
        prepare_flat_copy,
    )
    from nesting.outline_cache import (
        CACHE_KEY,
        body_geometry_signature,
        build_cache_record,
    )
    from nesting.workpiece_names import nesting_workpiece_name
except Exception:
    import lay_flat
    from fusion_layout import (
        _attr,
        _bbox_dimensions_mm,
        _set_attr,
        _translation_matrix,
        delete_previous_layouts,
        prepare_flat_copy,
    )
    from outline_cache import CACHE_KEY, body_geometry_signature, build_cache_record
    from workpiece_names import nesting_workpiece_name


OUTPUT_MARKER_GROUP = "UnifiedCabinet"
OUTPUT_MARKER_NAME = "systemRole"
OUTPUT_MARKER_VALUE = "layFlatOutput"
WORKPIECE_ROLE = "layFlatWorkpiece"
INSTANCE_ROLE_GROUP = "UnifiedCabinet"
INSTANCE_ROLE_NAME = "instanceRole"
INSTANCE_ROLE_VALUE = "layFlat"
LAYOUT_COMPONENT_NAME = "LAY_FLAT"
PANEL_GROUP = "UnifiedCabinet.Panel"


def is_lay_flat_workpiece(body):
    try:
        attr = body.attributes.itemByName(OUTPUT_MARKER_GROUP, OUTPUT_MARKER_NAME)
        if attr and str(attr.value or "") == WORKPIECE_ROLE:
            return True
    except Exception:
        pass
    try:
        attr = body.attributes.itemByName(INSTANCE_ROLE_GROUP, INSTANCE_ROLE_NAME)
        return bool(attr and str(attr.value or "") == INSTANCE_ROLE_VALUE)
    except Exception:
        return False


def delete_previous_lay_flat(root_component, exclude_component=None):
    deleted = 0
    try:
        exclude_token = (
            str(exclude_component.entityToken or "")
            if exclude_component is not None
            else ""
        )
    except Exception:
        exclude_token = ""
    try:
        occurrences = root_component.occurrences
        count = occurrences.count
    except Exception:
        return 0
    for index in range(count - 1, -1, -1):
        try:
            occurrence = occurrences.item(index)
            component = occurrence.component
            try:
                component_token = str(component.entityToken or "")
            except Exception:
                component_token = ""
            if component is exclude_component or (
                exclude_token and component_token == exclude_token
            ):
                continue
            marked = (
                _attr(component, OUTPUT_MARKER_GROUP, OUTPUT_MARKER_NAME)
                == OUTPUT_MARKER_VALUE
            )
            try:
                component_name = str(component.name or "").strip().upper()
            except Exception:
                component_name = ""
            try:
                occurrence_name = str(occurrence.name or "").strip().upper()
            except Exception:
                occurrence_name = ""
            reserved = (
                component_name == LAYOUT_COMPONENT_NAME
                or component_name.startswith(LAYOUT_COMPONENT_NAME + ":")
                or component_name.startswith(LAYOUT_COMPONENT_NAME + " (")
                or occurrence_name == LAYOUT_COMPONENT_NAME
                or occurrence_name.startswith(LAYOUT_COMPONENT_NAME + ":")
                or occurrence_name.startswith(LAYOUT_COMPONENT_NAME + " (")
            )
            if not marked and not reserved:
                continue
            occurrence.deleteMe()
            deleted += 1
        except Exception:
            continue
    return deleted


def _write_panel_metadata(body, metadata, panel_id):
    payload = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    attrs = body.attributes
    if panel_id:
        existing_id = attrs.itemByName(PANEL_GROUP, "panelId")
        if existing_id:
            existing_id.value = str(panel_id)
        else:
            attrs.add(PANEL_GROUP, "panelId", str(panel_id))
    existing = attrs.itemByName(PANEL_GROUP, "metadata")
    if existing:
        existing.value = payload
    else:
        attrs.add(PANEL_GROUP, "metadata", payload)


def _slim_metadata_for_lay_flat(
    source_metadata, unique_id, source_panel_id, outline, dimensions, run_id
):
    """Keep export-critical fields; drop heavy SVG / faceRegistry payloads."""
    src = source_metadata if isinstance(source_metadata, dict) else {}
    identity = dict(src.get("identity") or {}) if isinstance(src.get("identity"), dict) else {}
    if source_panel_id:
        identity["sourcePanelId"] = source_panel_id
    identity["panelId"] = unique_id
    signature = "layflat|{}|{}".format(run_id, unique_id)
    cache = build_cache_record(
        outline if isinstance(outline, dict) else {},
        dimensions if isinstance(dimensions, dict) else {},
        signature,
        "MILLING",
        allow_parts_in_part=False,
        reflected_source=bool((outline or {}).get("reflectedSource")),
    )
    slim = {
        "schemaVersion": src.get("schemaVersion", 1),
        "identity": identity,
        "classification": src.get("classification"),
        "defaultAttributes": src.get("defaultAttributes"),
        "derivedTags": src.get("derivedTags"),
        "typedTags": src.get("typedTags"),
        "dimensions": src.get("dimensions") or dimensions,
        # Source features are in the source-body frame. Never attach them to a
        # moved LAY_FLAT copy; Analyze Lay Flat will write world-XY/panel-local
        # manufacturing features.
        "features": [],
        CACHE_KEY: cache,
        "lifecycle": {"state": "lay_flat"},
    }
    # Keep declared cut intents (e.g. LED half grooves) for manufacturing export.
    declared = src.get("declaredCuts")
    if isinstance(declared, list) and declared:
        slim["declaredCuts"] = declared
    return slim


def _stamp_lay_flat_body(body, placement, run_id, source_metadata, outline, dimensions):
    _set_attr(body, OUTPUT_MARKER_GROUP, OUTPUT_MARKER_NAME, WORKPIECE_ROLE)
    _set_attr(body, INSTANCE_ROLE_GROUP, INSTANCE_ROLE_NAME, INSTANCE_ROLE_VALUE)
    _set_attr(body, OUTPUT_MARKER_GROUP, "layFlatRunId", run_id)
    source_panel_id = str(placement.get("panelId") or "").strip()
    _set_attr(body, OUTPUT_MARKER_GROUP, "sourcePanelId", source_panel_id)
    # Exact lineage so Apply Tags writes the same source body Create copied.
    source_ref = placement.get("sourceRef")
    if not isinstance(source_ref, dict):
        source_ref = {
            "entityToken": placement.get("sourceEntityToken") or "",
            "occurrencePath": placement.get("sourceOccurrencePath"),
            "bodyName": placement.get("sourceBodyName")
            or placement.get("bodyName")
            or "",
            "componentName": placement.get("sourceComponentName")
            or placement.get("componentName")
            or "",
            "assemblyName": placement.get("sourceAssemblyName")
            or placement.get("assemblyName")
            or "",
            "panelId": source_panel_id,
        }
    source_token = str(source_ref.get("entityToken") or "").strip()
    source_body_name = str(source_ref.get("bodyName") or "").strip()
    source_path = source_ref.get("occurrencePath")
    if not source_token and not (
        source_body_name and isinstance(source_path, (list, tuple))
    ):
        raise RuntimeError(
            "missing_source_lineage: {}".format(
                source_panel_id or placement.get("bodyName") or "unknown"
            )
        )
    source_ref = {
        "entityToken": source_token,
        "occurrencePath": [int(value) for value in (source_path or [])],
        "bodyName": source_body_name,
        "componentName": str(source_ref.get("componentName") or "").strip(),
        "assemblyName": str(
            source_ref.get("assemblyName")
            or placement.get("assemblyName")
            or ""
        ).strip(),
        "panelId": str(source_ref.get("panelId") or source_panel_id).strip(),
    }
    _set_attr(
        body,
        OUTPUT_MARKER_GROUP,
        "sourceRefJson",
        json.dumps(source_ref, ensure_ascii=False, separators=(",", ":")),
    )
    if source_token:
        _set_attr(body, OUTPUT_MARKER_GROUP, "sourceEntityToken", source_token)
    if source_body_name:
        _set_attr(body, OUTPUT_MARKER_GROUP, "sourceBodyName", source_body_name)
    if source_ref.get("assemblyName"):
        _set_attr(
            body,
            OUTPUT_MARKER_GROUP,
            "sourceAssemblyName",
            source_ref["assemblyName"],
        )
    if isinstance(source_path, (list, tuple)):
        try:
            _set_attr(
                body,
                OUTPUT_MARKER_GROUP,
                "sourceOccurrencePath",
                json.dumps([int(v) for v in source_path], separators=(",", ":")),
            )
        except Exception:
            pass

    unique_id = source_panel_id or str(placement.get("id") or body.name or "panel")
    if placement.get("groupIndex") is not None:
        unique_id = "{}@layflat-{}-{}".format(
            unique_id,
            placement.get("groupIndex"),
            placement.get("itemIndex"),
        )
    meta = _slim_metadata_for_lay_flat(
        source_metadata, unique_id, source_panel_id, outline, dimensions, run_id
    )
    identity = meta.get("identity") if isinstance(meta.get("identity"), dict) else {}
    identity["sourceRef"] = source_ref
    if source_ref.get("assemblyName"):
        identity["sourceAssemblyName"] = source_ref["assemblyName"]
    if source_token:
        identity["sourceEntityToken"] = source_token
    if source_body_name:
        identity["sourceBodyName"] = source_body_name
    if isinstance(source_path, (list, tuple)):
        identity["sourceOccurrencePath"] = [int(v) for v in source_path]
    meta["identity"] = identity
    _write_panel_metadata(body, meta, unique_id)
    return unique_id


def _result_bodies_from_base_feature(base_feature, expected_count):
    """Return result bodies after finishEdit (prefer feature.bodies)."""
    bodies = []
    try:
        owned = base_feature.bodies
        count = int(owned.count or 0) if owned else 0
        for index in range(count):
            try:
                bodies.append(owned.item(index))
            except Exception:
                continue
    except Exception:
        bodies = []
    if expected_count and len(bodies) != expected_count:
        return []
    return bodies


def create_lay_flat_layout(
    root_component,
    prepared_items,
    origin_x_mm=0.0,
    origin_y_mm=0.0,
    part_gap_mm=50.0,
    column_gap_mm=200.0,
    wait_callback=None,
    clear_previous=True,
):
    """Create LAY_FLAT with named bodies (Assembly-Component), machining face +Z."""

    def _pump():
        if callable(wait_callback):
            try:
                wait_callback()
            except Exception:
                pass

    if not prepared_items:
        return {
            "created": 0,
            "deletedPrevious": 0,
            "groups": [],
            "placements": [],
            "runId": "",
            "componentName": "",
        }

    pack_items = []
    for item in prepared_items:
        dims = item.get("dimensions") or {}
        pack_items.append(
            {
                "id": item["id"],
                "panelId": item.get("panelId") or "",
                "bodyName": item.get("bodyName") or "",
                "assemblyName": item.get("assemblyName") or "",
                "componentName": item.get("componentName") or "",
                "boardTypeTag": item.get("boardTypeTag") or "",
                "colorTag": item.get("colorTag") or "",
                "widthMm": float(dims.get("widthMm") or 0.0),
                "depthMm": float(dims.get("depthMm") or 0.0),
            }
        )
    layout = lay_flat.column_layout(
        pack_items,
        origin_x_mm=origin_x_mm,
        origin_y_mm=origin_y_mm,
        part_gap_mm=part_gap_mm,
        column_gap_mm=column_gap_mm,
        group_by_color=True,
    )

    occurrence = root_component.occurrences.addNewComponent(
        adsk.core.Matrix3D.create()
    )
    component = occurrence.component
    try:
        occurrence.name = LAYOUT_COMPONENT_NAME
    except Exception:
        pass
    try:
        component.name = LAYOUT_COMPONENT_NAME
    except Exception:
        pass

    run_id = "layflat-{}".format(int(time.time() * 1000))
    _set_attr(component, OUTPUT_MARKER_GROUP, OUTPUT_MARKER_NAME, OUTPUT_MARKER_VALUE)
    _set_attr(component, OUTPUT_MARKER_GROUP, "runId", run_id)
    _set_attr(component, OUTPUT_MARKER_GROUP, "originXmm", origin_x_mm)
    _set_attr(component, OUTPUT_MARKER_GROUP, "originYmm", origin_y_mm)
    _set_attr(component, OUTPUT_MARKER_GROUP, "partGapMm", part_gap_mm)
    _set_attr(component, OUTPUT_MARKER_GROUP, "columnGapMm", column_gap_mm)
    _set_attr(component, OUTPUT_MARKER_GROUP, "groupByColor", "true")
    try:
        _set_attr(
            component,
            OUTPUT_MARKER_GROUP,
            "groupColumnsJson",
            json.dumps(
                [
                    {
                        "boardTypeTag": _norm_tag(group.get("boardTypeTag")),
                        "colorTag": _norm_tag(group.get("colorTag")),
                        "columnX": float(group.get("columnX") or 0.0),
                        "columnWidthMm": float(group.get("columnWidthMm") or 0.0),
                        "count": int(group.get("count") or 0),
                    }
                    for group in (layout.get("groups") or [])
                    if isinstance(group, dict)
                ],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        )
    except Exception:
        pass

    by_id = {str(item["id"]): item for item in prepared_items}
    temp_manager = adsk.fusion.TemporaryBRepManager.get()
    created = []
    used_names = set()
    placements = list(layout.get("placements") or [])
    CREATE_BATCH = 40

    try:
        pending = []
        for batch_start in range(0, len(placements), CREATE_BATCH):
            batch = placements[batch_start : batch_start + CREATE_BATCH]
            batch_meta = []
            base_feature = component.features.baseFeatures.add()
            base_feature.name = "LAY_FLAT_{}_{}".format(
                run_id, batch_start // CREATE_BATCH + 1
            )
            base_feature.startEdit()
            try:
                for placement in batch:
                    item = by_id[str(placement["id"])]
                    for key in (
                        "assemblyName",
                        "componentName",
                        "bodyName",
                        "panelId",
                        "sourceEntityToken",
                        "sourceBodyName",
                        "sourceOccurrencePath",
                        "sourceRef",
                        "sourceKey",
                        "occurrencePath",
                    ):
                        if placement.get(key) in (None, "", []) and item.get(key) not in (
                            None,
                            "",
                            [],
                        ):
                            placement[key] = item.get(key)
                    temp_body = item["tempBody"]
                    dims = item.get("dimensions") or _bbox_dimensions_mm(temp_body)
                    temp_manager.transform(
                        temp_body,
                        _translation_matrix(
                            placement["targetX"] - dims["minX"],
                            placement["targetY"] - dims["minY"],
                            -dims["minZ"],
                        ),
                    )
                    component.bRepBodies.add(temp_body, base_feature)
                    batch_meta.append((placement, item))
            except Exception:
                try:
                    base_feature.finishEdit()
                except Exception:
                    pass
                raise
            base_feature.finishEdit()

            result_bodies = _result_bodies_from_base_feature(
                base_feature, len(batch_meta)
            )
            if not result_bodies:
                try:
                    total = int(component.bRepBodies.count or 0)
                except Exception:
                    total = 0
                start = max(0, total - len(batch_meta))
                result_bodies = []
                for index in range(start, total):
                    try:
                        result_bodies.append(component.bRepBodies.item(index))
                    except Exception:
                        continue
            if len(result_bodies) != len(batch_meta):
                raise RuntimeError(
                    "lay_flat_batch_body_mismatch: got {} expected {}".format(
                        len(result_bodies), len(batch_meta)
                    )
                )
            for body, (placement, item) in zip(result_bodies, batch_meta):
                pending.append((body, placement, item))
            _pump()

        # Rename + stamp after finishEdit so names stick (not Body1…).
        for index, (body, placement, item) in enumerate(pending):
            for key in (
                "assemblyName",
                "componentName",
                "bodyName",
                "panelId",
                "sourceEntityToken",
                "sourceBodyName",
                "sourceOccurrencePath",
                "sourceRef",
                "sourceKey",
                "occurrencePath",
            ):
                if not placement.get(key) and item.get(key) not in (None, "", []):
                    placement[key] = item.get(key)
            part_name = nesting_workpiece_name(placement, used_names)
            try:
                body.name = part_name
            except Exception:
                pass
            unique_id = _stamp_lay_flat_body(
                body,
                placement,
                run_id,
                item.get("metadata"),
                item.get("outline"),
                item.get("dimensions"),
            )
            created.append(
                {
                    "bodyName": getattr(body, "name", "") or part_name,
                    "panelId": unique_id,
                    "sourcePanelId": placement.get("panelId") or "",
                    "boardTypeTag": placement.get("boardTypeTag") or "",
                    "groupIndex": placement.get("groupIndex"),
                    "targetX": placement["targetX"],
                    "targetY": placement["targetY"],
                }
            )
            if (index + 1) % 20 == 0:
                _pump()
    except Exception:
        try:
            occurrence.deleteMe()
        except Exception:
            pass
        raise

    deleted = 0
    if clear_previous:
        deleted = delete_previous_layouts(root_component, exclude_component=component)
        deleted += delete_previous_lay_flat(root_component, exclude_component=component)
    return {
        "created": len(created),
        "lineageStampedCount": len(created),
        "deletedPrevious": deleted,
        "runId": run_id,
        "componentName": component.name,
        "groups": layout.get("groups") or [],
        "placements": created,
        "bounds": layout.get("bounds") or {},
        "structure": "named_bodies",
        "createPath": "batch_named_bodies",
    }


def _native_body(body):
    try:
        native = getattr(body, "nativeObject", None)
        if native is not None:
            return native
    except Exception:
        pass
    return body


def _body_match_key(body):
    """Stable key for matching selected bodies against collected Lay Flat bodies.

    Fusion may return a new Python wrapper each time ``nativeObject`` is read, so
    ``id(body)`` is not reliable across collect vs selection lists.
    """
    body = _native_body(body)
    if body is None:
        return ""
    try:
        token = str(getattr(body, "entityToken", "") or "").strip()
        if token:
            return "token:{}".format(token)
    except Exception:
        pass
    try:
        name = str(getattr(body, "name", "") or "").strip()
        parent = getattr(body, "parentComponent", None)
        parent_name = str(getattr(parent, "name", "") or "").strip() if parent else ""
        if name:
            return "name:{}|{}".format(parent_name, name)
    except Exception:
        pass
    return "id:{}".format(id(body))


def _body_center_point_cm(body):
    bbox = body.boundingBox
    return adsk.core.Point3D.create(
        (bbox.minPoint.x + bbox.maxPoint.x) / 2.0,
        (bbox.minPoint.y + bbox.maxPoint.y) / 2.0,
        (bbox.minPoint.z + bbox.maxPoint.z) / 2.0,
    )


def _move_body_transform(component, body, transform, feature_prefix):
    bodies = adsk.core.ObjectCollection.create()
    bodies.add(body)
    move_input = component.features.moveFeatures.createInput(bodies, transform)
    try:
        move_input.defineAsFreeMove(transform)
    except Exception:
        pass
    move_feature = component.features.moveFeatures.add(move_input)
    name = str(getattr(body, "name", "") or "body")
    safe = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in name)[:40]
    try:
        move_feature.name = "{}{}".format(feature_prefix, safe or "body")
    except Exception:
        pass
    return move_feature


def _tag_metadata_helpers():
    try:
        from panel_attributes import tag_metadata_editor
    except Exception:
        import tag_metadata_editor  # type: ignore
    return tag_metadata_editor


def _read_lay_flat_metadata(body):
    return _tag_metadata_helpers()._read_body_metadata_raw(body)


def _write_lay_flat_metadata(body, metadata):
    return _tag_metadata_helpers()._write_body_metadata(body, metadata)


def _norm_tag(value):
    return str(value or "").strip().lower()


def _tag_pair(board_type_tag, color_tag):
    board = _norm_tag(board_type_tag) or "unknown"
    color = _norm_tag(color_tag) or "unknown"
    return board, color


def _best_column_key_for_color(color_tag, columns, anchors=None):
    """When Board Type is missing, pick the strongest existing column for Color."""
    color = _norm_tag(color_tag)
    if not color or color == "unknown":
        return None
    candidates = []
    for key, state in (columns or {}).items():
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        if key[1] != color or key[0] in ("", "unknown"):
            continue
        candidates.append(
            (
                int((state or {}).get("stationaryCount") or 0),
                key,
            )
        )
    if candidates:
        candidates.sort(reverse=True)
        return candidates[0][1]
    for key in anchors or {}:
        if not isinstance(key, tuple) or len(key) != 2:
            continue
        if key[1] == color and key[0] not in ("", "unknown"):
            return key
    return None


def _resolve_selected_column_key(key, columns, anchors=None):
    """Map a selected body tag pair onto an existing column when possible."""
    key = _tag_pair(key[0], key[1]) if isinstance(key, tuple) else _tag_pair("", "")
    if key in (columns or {}):
        return key, "tags"
    board, color = key
    if board in ("", "unknown") and color not in ("", "unknown"):
        matched = _best_column_key_for_color(color, columns, anchors=anchors)
        if matched:
            return matched, "color_fallback"
    if key in (anchors or {}):
        return key, "anchor"
    if board in ("", "unknown") and color not in ("", "unknown"):
        matched = _best_column_key_for_color(color, {}, anchors=anchors)
        if matched:
            return matched, "anchor_color"
    return key, "new"


def _cluster_stationary_columns(stationary, part_gap_mm, x_tol_mm=150.0):
    """Cluster stationary bodies by X, then majority-vote Board Type + Color.

    Physical columns stay correct even when some bodies fail tag reads: untagged
    bodies still contribute geometry, while tagged neighbours label the column.
    """
    ordered = sorted(stationary or [], key=lambda item: (item["minX"], item["minY"]))
    clusters = []
    for item in ordered:
        target = None
        for cluster in clusters:
            if abs(float(item["minX"]) - float(cluster["x"])) <= float(x_tol_mm):
                target = cluster
                break
        if target is None:
            target = {
                "x": float(item["minX"]),
                "nextY": float(item["maxY"]) + float(part_gap_mm),
                "maxX": float(item["maxX"]),
                "stationaryCount": 0,
                "appendedCount": 0,
                "votes": {},
                "source": "geometry",
            }
            clusters.append(target)
        target["x"] = min(float(target["x"]), float(item["minX"]))
        target["nextY"] = max(
            float(target["nextY"]), float(item["maxY"]) + float(part_gap_mm)
        )
        target["maxX"] = max(float(target["maxX"]), float(item["maxX"]))
        target["stationaryCount"] += 1
        key = _tag_pair(item.get("boardTypeTag"), item.get("colorTag"))
        if key != ("unknown", "unknown"):
            target["votes"][key] = int(target["votes"].get(key) or 0) + 1
    columns = {}
    for cluster in clusters:
        votes = cluster.get("votes") or {}
        if not votes:
            continue
        key = max(votes.items(), key=lambda pair: (pair[1], pair[0][0], pair[0][1]))[0]
        existing = columns.get(key)
        if existing is None or int(cluster["stationaryCount"]) > int(
            existing.get("stationaryCount") or 0
        ):
            columns[key] = {
                "x": float(cluster["x"]),
                "nextY": float(cluster["nextY"]),
                "maxX": float(cluster["maxX"]),
                "stationaryCount": int(cluster["stationaryCount"]),
                "appendedCount": 0,
                "source": "geometry",
            }
    return columns


def _read_column_anchors(root_component):
    """Return {(board, color): columnX} saved on the LAY_FLAT component."""
    if root_component is None:
        return {}
    try:
        occurrences = root_component.occurrences
        count = int(occurrences.count or 0)
    except Exception:
        return {}
    raw = ""
    for index in range(count):
        try:
            occurrence = occurrences.item(index)
            component = occurrence.component
        except Exception:
            continue
        try:
            role = _attr(component, OUTPUT_MARKER_GROUP, OUTPUT_MARKER_NAME)
        except Exception:
            role = ""
        name = ""
        try:
            name = str(getattr(component, "name", "") or "")
        except Exception:
            name = ""
        if str(role or "") != OUTPUT_MARKER_VALUE and str(name or "").upper() != "LAY_FLAT":
            continue
        try:
            raw = str(_attr(component, OUTPUT_MARKER_GROUP, "groupColumnsJson") or "")
        except Exception:
            raw = ""
        if raw:
            break
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    anchors = {}
    for item in payload if isinstance(payload, list) else []:
        if not isinstance(item, dict):
            continue
        key = _tag_pair(item.get("boardTypeTag"), item.get("colorTag"))
        if key == ("unknown", "unknown"):
            continue
        try:
            anchors[key] = float(item.get("columnX"))
        except Exception:
            continue
    return anchors


def _write_column_anchors(root_component, groups):
    if root_component is None:
        return
    payload = []
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        board = _norm_tag(group.get("boardTypeTag"))
        color = _norm_tag(group.get("colorTag"))
        if not board and not color:
            continue
        try:
            column_x = float(group.get("columnX"))
        except Exception:
            continue
        payload.append(
            {
                "boardTypeTag": board or "unknown",
                "colorTag": color or "unknown",
                "columnX": column_x,
                "columnWidthMm": float(group.get("columnWidthMm") or 0.0),
                "count": int(group.get("count") or 0),
            }
        )
    if not payload:
        return
    try:
        occurrences = root_component.occurrences
        count = int(occurrences.count or 0)
    except Exception:
        return
    text = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    for index in range(count):
        try:
            occurrence = occurrences.item(index)
            component = occurrence.component
        except Exception:
            continue
        try:
            role = _attr(component, OUTPUT_MARKER_GROUP, OUTPUT_MARKER_NAME)
        except Exception:
            role = ""
        name = ""
        try:
            name = str(getattr(component, "name", "") or "")
        except Exception:
            name = ""
        if str(role or "") != OUTPUT_MARKER_VALUE and str(name or "").upper() != "LAY_FLAT":
            continue
        try:
            _set_attr(component, OUTPUT_MARKER_GROUP, "groupColumnsJson", text)
        except Exception:
            pass
        return


def append_lay_flat_bodies_to_group_ends(
    items,
    selected_bodies,
    origin_x_mm=None,
    origin_y_mm=None,
    part_gap_mm=50.0,
    column_gap_mm=200.0,
    column_anchors=None,
):
    """Move only selected bodies to the end of their Board Type + Color columns.

    Unselected bodies never move. Column matching prefers geometric clusters with
    majority Board Type + Color votes, then saved Lay Flat column anchors, and
    only then creates a new rightmost column. Cached panel-local outline/features
    stay valid; only the geometry signature is refreshed after translation.
    """
    normalized = []
    min_x = None
    min_y = None
    selected_keys = {
        _body_match_key(body)
        for body in (selected_bodies or [])
        if _body_match_key(body)
    }
    for index, item in enumerate(items or []):
        body = _native_body((item or {}).get("body"))
        if body is None:
            continue
        try:
            bbox = body.boundingBox
            body_min_x = float(bbox.minPoint.x) * 10.0
            body_min_y = float(bbox.minPoint.y) * 10.0
            width_mm = (float(bbox.maxPoint.x) - float(bbox.minPoint.x)) * 10.0
            depth_mm = (float(bbox.maxPoint.y) - float(bbox.minPoint.y)) * 10.0
        except Exception:
            continue
        dims = (item or {}).get("dimensions")
        if isinstance(dims, dict):
            width_mm = float(dims.get("widthMm") or width_mm or 0.0)
            depth_mm = float(dims.get("depthMm") or depth_mm or 0.0)
        min_x = body_min_x if min_x is None else min(min_x, body_min_x)
        min_y = body_min_y if min_y is None else min(min_y, body_min_y)
        match_key = _body_match_key(body)
        board_tag, color_tag = _tag_pair(
            (item or {}).get("boardTypeTag"), (item or {}).get("colorTag")
        )
        normalized.append(
            {
                "id": str((item or {}).get("id") or index),
                "body": body,
                "bodyName": str(getattr(body, "name", "") or ""),
                "boardTypeTag": board_tag,
                "colorTag": color_tag,
                "widthMm": width_mm,
                "depthMm": depth_mm,
                "minX": body_min_x,
                "minY": body_min_y,
                "maxX": body_min_x + width_mm,
                "maxY": body_min_y + depth_mm,
                "selected": bool(match_key and match_key in selected_keys),
            }
        )
    selected = [item for item in normalized if item["selected"]]
    stationary = [item for item in normalized if not item["selected"]]
    if not selected:
        return {
            "ok": False,
            "movedCount": 0,
            "failedCount": 0,
            "reason": "no_selected_lay_flat_bodies",
            "placements": [],
            "groups": [],
        }

    ox = float(min_x or 0.0) if origin_x_mm is None else float(origin_x_mm)
    oy = float(min_y or 0.0) if origin_y_mm is None else float(origin_y_mm)
    part_gap = max(float(part_gap_mm), 0.0)
    column_gap = max(float(column_gap_mm), 0.0)
    x_tol = max(column_gap * 0.75, 150.0)
    columns = _cluster_stationary_columns(stationary, part_gap, x_tol_mm=x_tol)
    right_edge = ox
    for item in stationary:
        right_edge = max(right_edge, float(item["maxX"]))
    for state in columns.values():
        right_edge = max(right_edge, float(state.get("maxX") or right_edge))

    anchors = {}
    if isinstance(column_anchors, dict):
        for key, value in column_anchors.items():
            if isinstance(key, tuple) and len(key) == 2:
                anchors[_tag_pair(key[0], key[1])] = float(value)
            elif isinstance(key, str) and isinstance(value, (int, float)):
                # allow "board|color" strings
                parts = key.split("|", 1)
                if len(parts) == 2:
                    anchors[_tag_pair(parts[0], parts[1])] = float(value)
    for key, anchor_x in anchors.items():
        if key in columns:
            continue
        near = [
            item
            for item in stationary
            if abs(float(item["minX"]) - float(anchor_x)) <= x_tol
        ]
        if not near:
            continue
        columns[key] = {
            "x": min(float(item["minX"]) for item in near),
            "nextY": max(float(item["maxY"]) for item in near) + part_gap,
            "maxX": max(float(item["maxX"]) for item in near),
            "stationaryCount": len(near),
            "appendedCount": 0,
            "source": "anchor",
        }

    selected_by_group = {}
    group_order = []
    selected_key_meta = {}
    for item in selected:
        raw_key = _tag_pair(item["boardTypeTag"], item["colorTag"])
        key, resolve_source = _resolve_selected_column_key(
            raw_key, columns, anchors=anchors
        )
        # Keep selected body tags aligned with the column we actually target.
        item["boardTypeTag"], item["colorTag"] = key
        item["columnResolve"] = resolve_source
        selected_key_meta[key] = resolve_source
        if key not in selected_by_group:
            selected_by_group[key] = []
            group_order.append(key)
        selected_by_group[key].append(item)

    for key in group_order:
        if key in columns:
            if not columns[key].get("source"):
                columns[key]["source"] = selected_key_meta.get(key) or "tags"
            continue
        # Prefer saved anchor X before inventing a brand-new rightmost column.
        if key in anchors:
            anchor_x = float(anchors[key])
            near = [
                item
                for item in stationary
                if abs(float(item["minX"]) - anchor_x) <= x_tol
            ]
            if near:
                columns[key] = {
                    "x": min(float(item["minX"]) for item in near),
                    "nextY": max(float(item["maxY"]) for item in near) + part_gap,
                    "maxX": max(float(item["maxX"]) for item in near),
                    "stationaryCount": len(near),
                    "appendedCount": 0,
                    "source": "anchor",
                }
                continue
            group_width = max(item["widthMm"] for item in selected_by_group[key])
            columns[key] = {
                "x": anchor_x,
                "nextY": oy,
                "maxX": anchor_x + group_width,
                "stationaryCount": 0,
                "appendedCount": 0,
                "source": "anchor",
            }
            continue
        # Do not invent unknown/* columns — leave body unmoved if we cannot resolve.
        if key[0] in ("", "unknown"):
            columns[key] = {
                "x": None,
                "nextY": None,
                "maxX": None,
                "stationaryCount": 0,
                "appendedCount": 0,
                "source": "unresolved",
            }
            continue
        group_width = max(item["widthMm"] for item in selected_by_group[key])
        x = right_edge + (column_gap if columns or right_edge > ox else 0.0)
        columns[key] = {
            "x": x,
            "nextY": oy,
            "maxX": x + group_width,
            "stationaryCount": 0,
            "appendedCount": 0,
            "source": "new",
        }
        right_edge = x + group_width

    placements = []
    for item in selected:
        key = _tag_pair(item["boardTypeTag"], item["colorTag"])
        state = columns[key]
        if state.get("source") == "unresolved" or state.get("x") is None:
            placements.append(
                {
                    "id": item["id"],
                    "body": item["body"],
                    "bodyName": item["bodyName"],
                    "boardTypeTag": item["boardTypeTag"],
                    "colorTag": item["colorTag"],
                    "targetX": item["minX"],
                    "targetY": item["minY"],
                    "widthMm": item["widthMm"],
                    "depthMm": item["depthMm"],
                    "columnSource": "unresolved",
                    "skipMove": True,
                    "reason": "could_not_resolve_target_column",
                }
            )
            continue
        placements.append(
            {
                "id": item["id"],
                "body": item["body"],
                "bodyName": item["bodyName"],
                "boardTypeTag": item["boardTypeTag"],
                "colorTag": item["colorTag"],
                "targetX": state["x"],
                "targetY": state["nextY"],
                "widthMm": item["widthMm"],
                "depthMm": item["depthMm"],
                "columnSource": state.get("source")
                or item.get("columnResolve")
                or "",
            }
        )
        state["nextY"] += item["depthMm"] + part_gap
        state["maxX"] = max(state["maxX"], state["x"] + item["widthMm"])
        state["appendedCount"] += 1

    moved = []
    failed = []
    for placement in placements:
        body = placement.get("body")
        if body is None:
            continue
        if placement.get("skipMove"):
            failed.append(
                {
                    "bodyName": placement.get("bodyName") or "",
                    "reason": placement.get("reason")
                    or "could_not_resolve_target_column",
                }
            )
            continue
        snapshot = _snapshot_body_attributes(body)
        try:
            bbox = body.boundingBox
            dx_mm = float(placement.get("targetX") or 0.0) - float(bbox.minPoint.x) * 10.0
            dy_mm = float(placement.get("targetY") or 0.0) - float(bbox.minPoint.y) * 10.0
            if abs(dx_mm) > 0.001 or abs(dy_mm) > 0.001:
                matrix = adsk.core.Matrix3D.create()
                matrix.translation = adsk.core.Vector3D.create(
                    dx_mm / 10.0, dy_mm / 10.0, 0.0
                )
                component = getattr(body, "parentComponent", None)
                if component is None:
                    raise ValueError("missing_parent_component")
                _move_body_transform(component, body, matrix, "LAY_FLAT_APPEND_")
            restored = _restore_body_attributes(body, snapshot)
            metadata, read_error = _read_lay_flat_metadata(body)
            if read_error:
                raise ValueError(read_error)
            cached = (
                metadata.get(CACHE_KEY)
                if isinstance(metadata, dict)
                and isinstance(metadata.get(CACHE_KEY), dict)
                else None
            )
            if cached is not None:
                cached["geometrySignature"] = body_geometry_signature(
                    body, detail=True
                )
                _write_lay_flat_metadata(body, metadata)
            moved.append(
                {
                    "bodyName": placement.get("bodyName") or "",
                    "boardTypeTag": placement.get("boardTypeTag") or "",
                    "colorTag": placement.get("colorTag") or "",
                    "targetX": placement.get("targetX"),
                    "targetY": placement.get("targetY"),
                    "attributesRestored": int(restored or 0),
                }
            )
        except Exception as ex:
            try:
                _restore_body_attributes(body, snapshot)
            except Exception:
                pass
            failed.append(
                {
                    "bodyName": placement.get("bodyName") or "",
                    "reason": str(ex),
                }
            )
    groups = [
        {
            "boardTypeTag": key[0],
            "colorTag": key[1],
            "columnX": state["x"],
            "appendedCount": state["appendedCount"],
            "stationaryCount": int(state.get("stationaryCount") or 0),
            "source": state.get("source") or "",
        }
        for key, state in sorted(
            columns.items(), key=lambda pair: (pair[0][0].lower(), pair[0][1].lower())
        )
        if state["appendedCount"] and state.get("x") is not None
    ]
    moved_placements = [
        item for item in placements if not item.get("skipMove")
    ]
    max_x = max(
        [item["maxX"] for item in stationary]
        + [
            float(item["targetX"]) + float(item["widthMm"])
            for item in moved_placements
            if item.get("targetX") is not None
        ]
        + [ox]
    )
    max_y = max(
        [item["maxY"] for item in stationary]
        + [
            float(item["targetY"]) + float(item["depthMm"])
            for item in moved_placements
            if item.get("targetY") is not None
        ]
        + [oy]
    )
    return {
        "ok": bool(moved) and not failed,
        "movedCount": len(moved),
        "failedCount": len(failed),
        "moved": moved[:100],
        "failed": failed[:40],
        "placements": [
            {key: value for key, value in placement.items() if key not in ("body",)}
            for placement in placements
        ],
        "groups": groups,
        "columnStates": {
            key: {
                "x": state.get("x"),
                "maxX": state.get("maxX"),
                "nextY": state.get("nextY"),
                "stationaryCount": int(state.get("stationaryCount") or 0),
                "appendedCount": int(state.get("appendedCount") or 0),
                "source": state.get("source") or "",
            }
            for key, state in columns.items()
        },
        "bounds": {"x0": ox, "y0": oy, "x1": max_x, "y1": max_y},
        "originXmm": ox,
        "originYmm": oy,
        "partGapMm": part_gap,
        "columnGapMm": column_gap,
    }


def _classification_value(metadata, field):
    classification = (
        metadata.get("classification") if isinstance(metadata, dict) else {}
    )
    state = classification.get(field) if isinstance(classification, dict) else {}
    if isinstance(state, dict):
        return str(state.get("value") or "").strip()
    return str(state or "").strip()


def sync_lay_flat_classification_from_source(lay_flat_body, source_body):
    """Restore boardType/color on a LAY_FLAT body from the assembly source.

    Reverse / MoveFeature paths can overwrite Lay Flat metadata with a sparse
    shell that keeps outline/features but drops classification tags.
    """
    if lay_flat_body is None or source_body is None:
        return {"ok": False, "reason": "missing_body"}
    try:
        from panel_attributes import tag_metadata_editor, attribute_state_service
    except Exception:
        try:
            import tag_metadata_editor
            import attribute_state_service
        except Exception as ex:
            return {"ok": False, "reason": "helpers_unavailable:{}".format(ex)}

    lay_meta, _err = tag_metadata_editor._read_body_metadata_raw(lay_flat_body)
    src_meta, _src_err = tag_metadata_editor._read_body_metadata_raw(source_body)
    if not isinstance(src_meta, dict):
        return {"ok": False, "reason": "source_metadata_missing"}
    working = attribute_state_service.migrate_metadata(
        lay_meta if isinstance(lay_meta, dict) else {}
    )
    source = attribute_state_service.migrate_metadata(src_meta)
    changed = False
    for field in ("boardType", "color"):
        if _classification_value(working, field):
            continue
        src_state = ((source.get("classification") or {}).get(field) or {})
        if not isinstance(src_state, dict) or not str(src_state.get("value") or "").strip():
            continue
        _ensure = working.setdefault("classification", {})
        if not isinstance(_ensure, dict):
            working["classification"] = {}
            _ensure = working["classification"]
        _ensure[field] = dict(src_state)
        changed = True
    for key in ("defaultAttributes", "derivedTags", "typedTags"):
        if working.get(key):
            continue
        if source.get(key):
            working[key] = source.get(key)
            changed = True
    if not changed:
        return {
            "ok": True,
            "changed": False,
            "bodyName": str(getattr(lay_flat_body, "name", "") or ""),
        }
    try:
        tag_metadata_editor._write_body_metadata(lay_flat_body, working)
    except Exception as ex:
        return {"ok": False, "reason": "write_failed:{}".format(ex)}
    return {
        "ok": True,
        "changed": True,
        "bodyName": str(getattr(lay_flat_body, "name", "") or ""),
        "boardType": _classification_value(working, "boardType"),
        "color": _classification_value(working, "color"),
    }


def _snapshot_body_attributes(body):
    """Capture body-level custom attributes that MoveFeature may drop."""
    snapshot = []
    for entity in (body, _native_body(body)):
        if entity is None:
            continue
        try:
            attrs = entity.attributes
            count = int(attrs.count or 0) if attrs else 0
        except Exception:
            continue
        for index in range(count):
            try:
                attr = attrs.item(index)
                snapshot.append(
                    (
                        str(attr.groupName or ""),
                        str(attr.name or ""),
                        str(attr.value or ""),
                    )
                )
            except Exception:
                continue
    # De-dupe while preferring later (native) values.
    merged = {}
    for group, name, value in snapshot:
        if not group or not name:
            continue
        merged[(group, name)] = value
    return merged


def _restore_body_attributes(body, snapshot):
    if not body or not snapshot:
        return 0
    restored = 0
    targets = []
    for entity in (body, _native_body(body)):
        if entity is None:
            continue
        if id(entity) in {id(item) for item in targets}:
            continue
        targets.append(entity)
    for entity in targets:
        try:
            attrs = entity.attributes
        except Exception:
            continue
        for (group, name), value in snapshot.items():
            try:
                existing = attrs.itemByName(group, name)
                if existing:
                    if str(existing.value or "") != value:
                        existing.value = value
                        restored += 1
                else:
                    attrs.add(group, name, value)
                    restored += 1
            except Exception:
                continue
    return restored


def flip_lay_flat_body_thickness(body):
    """Rotate a LAY_FLAT body 180° about world X through its center, then reseat Z=0.

    Used after milling/colour role swap so MILLING returns to +Z and colour to −Z
    without regenerating the whole Lay Flat layout.
    """
    native = _native_body(body)
    if native is None:
        return {"ok": False, "reason": "missing_body"}
    try:
        component = getattr(native, "parentComponent", None)
    except Exception:
        component = None
    if component is None:
        return {
            "ok": False,
            "bodyName": str(getattr(native, "name", "") or ""),
            "reason": "missing_parent_component",
        }

    body_name = str(getattr(native, "name", "") or "")
    attr_snapshot = _snapshot_body_attributes(native)
    try:
        center = _body_center_point_cm(native)
        rotate = adsk.core.Matrix3D.create()
        rotate.setToRotation(
            math.pi,
            adsk.core.Vector3D.create(1.0, 0.0, 0.0),
            center,
        )
        _move_body_transform(component, native, rotate, "LAY_FLAT_FLIP_X_")

        # Keep the underside on the lay-flat table (min Z ≈ 0).
        bbox = native.boundingBox
        dz_cm = -float(bbox.minPoint.z)
        if abs(dz_cm) > 1e-6:
            translate = adsk.core.Matrix3D.create()
            translate.translation = adsk.core.Vector3D.create(0.0, 0.0, dz_cm)
            _move_body_transform(component, native, translate, "LAY_FLAT_RESEAT_Z_")
        restored = _restore_body_attributes(native, attr_snapshot)
    except Exception as ex:
        try:
            _restore_body_attributes(native, attr_snapshot)
        except Exception:
            pass
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "geometry_flip_failed:{}".format(ex),
        }
    return {
        "ok": True,
        "bodyName": body_name,
        "rotatedDeg": 180,
        "axis": "X",
        "attributesRestored": int(restored or 0),
    }


# Re-export for controller convenience
prepare_flat_copy = prepare_flat_copy
