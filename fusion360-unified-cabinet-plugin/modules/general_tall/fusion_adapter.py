import json
import math
import time

import adsk.core
import adsk.fusion

from geometry_ops import ATTRIBUTE_GROUP, MODEL_Z_OFFSET_MM, mm_to_cm, move_body_by_mm, offset_matching_bodies_z_mm, sanitize_token


PANEL_ATTRIBUTE_GROUP = "UnifiedCabinet.Panel"
PANEL_METADATA_ATTR = "metadata"
PANEL_ID_ATTR = "panelId"


def _is_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def _as_float(value):
    if _is_number(value):
        return float(value)
    return None


def _board_bbox(board):
    x0 = board.get("x0")
    x1 = board.get("x1")
    y0 = board.get("y0")
    y1 = board.get("y1")
    z0 = board.get("z0")
    z1 = board.get("z1")
    if not all(_is_number(v) for v in (x0, x1, y0, y1, z0, z1)):
        return None
    return {
        "x0": float(x0),
        "x1": float(x1),
        "y0": float(y0),
        "y1": float(y1),
        "z0": float(z0),
        "z1": float(z1),
    }


def _rough_size_mm(bbox):
    return (
        float(bbox["x1"] - bbox["x0"]),
        float(bbox["y1"] - bbox["y0"]),
        float(bbox["z1"] - bbox["z0"]),
    )


def _new_container_component(root_comp, run_label, module_name="generalTall", create_component=False, component_prefix=None, component_name=None):
    if component_name:
        resolved_component_name = sanitize_token(component_name, fallback="assembly", limit=80)
    else:
        resolved_component_name = "{}_{}".format(
            sanitize_token(component_prefix or module_name, fallback="assembly", limit=40),
            sanitize_token(run_label, fallback="run", limit=60),
        )
    if not create_component:
        return root_comp, "Using root component container for {} rough bodies.".format(module_name), None

    try:
        transform = adsk.core.Matrix3D.create()
        transform.translation = adsk.core.Vector3D.create(0, 0, mm_to_cm(MODEL_Z_OFFSET_MM))
        occurrence = root_comp.occurrences.addNewComponent(transform)
        occurrence.name = resolved_component_name
        component = occurrence.component
        component.name = resolved_component_name
        try:
            component.attributes.add(ATTRIBUTE_GROUP, "module", module_name)
            component.attributes.add(ATTRIBUTE_GROUP, "runLabel", str(run_label))
            component.attributes.add(ATTRIBUTE_GROUP, "assemblyName", resolved_component_name)
        except Exception:
            pass
        return component, None, resolved_component_name
    except Exception as ex:
        return root_comp, "Could not create {} assembly component; using root component instead: {}".format(module_name, ex), None


def _new_child_component(parent_component, component_name, module_name="overhead", board_id=None):
    transform = adsk.core.Matrix3D.create()
    occurrence = parent_component.occurrences.addNewComponent(transform)
    occurrence.name = component_name
    component = occurrence.component
    component.name = component_name
    try:
        component.attributes.add(ATTRIBUTE_GROUP, "module", module_name)
        if board_id is not None:
            component.attributes.add(ATTRIBUTE_GROUP, "boardId", str(board_id))
    except Exception:
        pass
    return component


def _set_entity_attribute(entity, group, name, value):
    try:
        attrs = entity.attributes
        existing = attrs.itemByName(group, name) if attrs else None
        if existing:
            existing.value = str(value)
        else:
            attrs.add(group, name, str(value))
        return True
    except Exception:
        return False


def _oh_divider_board_type(board_id, all_boards):
    divider_ids = []
    for board in all_boards or []:
        candidate_id = str(board.get("id") or "")
        if candidate_id.startswith("D") and candidate_id[1:].isdigit():
            divider_ids.append((int(candidate_id[1:]), candidate_id))
    if not divider_ids:
        return "vertical_divider"
    divider_ids.sort()
    first_id = divider_ids[0][1]
    last_id = divider_ids[-1][1]
    if board_id == first_id:
        return "left_side_panel"
    if board_id == last_id:
        return "right_side_panel"
    return "internal_vertical_divider"


def _oh_board_semantics(board, all_boards):
    board_id = str(board.get("id") or "")
    source_type = str(board.get("boardType") or "")
    if board_id == "BP":
        return {
            "boardType": "bottom_panel",
            "role": "carcass",
            "category": "structural",
            "materialClass": "carcass_board",
            "tags": ["overhead", "bottom", "carcass"],
        }
    if board_id == "T1":
        return {
            "boardType": "top_front_door_fascia",
            "role": "front_visible",
            "category": "front",
            "materialClass": "door_board",
            "doorColorSlot": 1,
            "tags": ["overhead", "front", "door-color", "top-fascia"],
        }
    if board_id == "T2":
        return {
            "boardType": "top_front_inner_rail",
            "role": "carcass_rail",
            "category": "structural",
            "materialClass": "carcass_board",
            "tags": ["overhead", "top", "rail", "carcass"],
        }
    if board_id == "T3":
        return {
            "boardType": "top_rear_panel",
            "role": "carcass",
            "category": "structural",
            "materialClass": "carcass_board",
            "tags": ["overhead", "top", "rear", "carcass"],
        }
    if board_id == "T4":
        return {
            "boardType": "top_front_panel",
            "role": "carcass",
            "category": "structural",
            "materialClass": "carcass_board",
            "tags": ["overhead", "top", "front", "carcass"],
        }
    if board_id.startswith("D"):
        canonical = _oh_divider_board_type(board_id, all_boards)
        role = "side_panel" if canonical in ("left_side_panel", "right_side_panel") else "divider"
        return {
            "boardType": canonical,
            "role": role,
            "category": "divider",
            "materialClass": "carcass_board",
            "tags": ["overhead", "divider", "carcass", canonical],
        }
    if board_id.startswith("FP"):
        if source_type == "up_flap":
            return {
                "boardType": "up_flap_door_panel",
                "role": "door",
                "category": "front",
                "materialClass": "door_board",
                "doorColorSlot": 1,
                "tags": ["overhead", "front", "door", "up-flap"],
            }
        if source_type == "fixed_panel":
            return {
                "boardType": "fixed_front_panel",
                "role": "front_visible",
                "category": "front",
                "materialClass": "door_board",
                "doorColorSlot": 1,
                "tags": ["overhead", "front", "fixed-panel", "door-color"],
            }
        return {
            "boardType": "front_panel",
            "role": "front_visible",
            "category": "front",
            "materialClass": "door_board",
            "doorColorSlot": 1,
            "tags": ["overhead", "front", source_type or "front-panel"],
        }
    return {
        "boardType": source_type or "unknown_board",
        "role": "unknown",
        "category": str(board.get("category") or "unknown"),
        "materialClass": "unknown",
        "tags": ["overhead", "unknown"],
    }


def _oh_design_geometry(board, bbox):
    return {
        "x0": bbox["x0"],
        "x1": bbox["x1"],
        "y0": bbox["y0"],
        "y1": bbox["y1"],
        "z0": bbox["z0"],
        "z1": bbox["z1"],
        "profilePlane": board.get("profilePlane"),
        "thicknessAxis": board.get("thicknessAxis"),
        "materialThickness": board.get("materialThickness"),
    }


def _oh_panel_metadata(board, bbox, all_boards, run_label):
    board_id = str(board.get("id") or "")
    semantics = _oh_board_semantics(board, all_boards)
    panel_id = "ohc.{}.{}".format(sanitize_token(run_label, fallback="run", limit=60), sanitize_token(board_id, fallback="board", limit=40))
    default_attributes = {
        "role": semantics["role"],
        "category": semantics["category"],
        "materialClass": semantics["materialClass"],
        "tags": semantics["tags"],
    }
    if semantics.get("doorColorSlot") is not None:
        default_attributes["doorColorSlot"] = semantics.get("doorColorSlot")
    return {
        "schemaVersion": 1,
        "identity": {
            "panelId": panel_id,
            "generator": "overhead",
            "module": "overhead",
            "cabinetType": "overhead",
            "sourceBoardId": board_id,
            "sourceBoardType": str(board.get("boardType") or ""),
            "boardType": semantics["boardType"],
            "runId": str(run_label or ""),
        },
        "defaultAttributes": default_attributes,
        "designGeometry": _oh_design_geometry(board, bbox),
        "lifecycle": {
            "state": "generated",
            "reviewRequired": False,
        },
    }


def _write_oh_panel_metadata(body, board, bbox, all_boards, run_label):
    metadata = _oh_panel_metadata(board, bbox, all_boards, run_label)
    payload = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    panel_id = metadata["identity"]["panelId"]
    ok_id = _set_entity_attribute(body, PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, panel_id)
    ok_payload = _set_entity_attribute(body, PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR, payload)
    return metadata, ok_id and ok_payload


def _update_oh_panel_metadata(body, panel_metadata):
    payload = json.dumps(panel_metadata, ensure_ascii=False, separators=(",", ":"))
    return _set_entity_attribute(body, PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR, payload)


def _run_oh_face_init(body, panel_metadata, board_id, summary):
    """Initialize face metadata for one OHC board and fold results into summary."""
    if not initialize_oh_panel_faces:
        return
    try:
        panel_metadata, face_init_result = initialize_oh_panel_faces(body, panel_metadata, board_id)
        if face_init_result.get("initialized"):
            if not _update_oh_panel_metadata(body, panel_metadata):
                summary["warnings"].append(
                    "Face metadata was initialized for {} but faceRegistry write-back failed.".format(board_id)
                )
            else:
                summary["faceInitSummary"]["initializedCount"] += 1
                summary["faceInitSummary"]["totalEdgeCount"] += int(face_init_result.get("edgeCount") or 0)
                summary["faceInitSummary"]["totalSurfaceCount"] += int(face_init_result.get("surfaceCount") or 0)
                summary["faceInitSummary"]["boards"].append(
                    {
                        "boardId": board_id,
                        "bodyName": getattr(body, "name", "") or "",
                        "surfaceCount": face_init_result.get("surfaceCount"),
                        "edgeCount": face_init_result.get("edgeCount"),
                        "faceCount": face_init_result.get("faceCount"),
                        "edgeGroupCount": face_init_result.get("edgeGroupCount"),
                    }
                )
        elif face_init_result.get("skipped"):
            summary["faceInitSummary"]["skippedCount"] += 1
        else:
            for warning in (face_init_result.get("warnings") or [])[:2]:
                summary["warnings"].append("Face skeleton skipped for {}: {}".format(board_id, warning))
    except Exception as ex:
        summary["warnings"].append("Face metadata initialization failed for {}: {}".format(board_id, ex))


try:
    import importlib
    import sys as _sys

    # Reload the whole face-metadata dependency chain in dependency order so a
    # stale cached module (for example face_models without newly added
    # constants) cannot break the import of panel_face_initializer.
    for _module_name in (
        "face_models",
        "face_geometry_signature",
        "face_attribute_store",
        "face_entity_resolver",
        "face_validation",
        "face_metadata_service",
        "panel_geometry",
        "panel_face_initializer",
    ):
        try:
            if _module_name in _sys.modules:
                importlib.reload(_sys.modules[_module_name])
            else:
                importlib.import_module(_module_name)
        except Exception:
            pass

    import panel_face_initializer as _panel_face_initializer_module

    initialize_oh_panel_faces = _panel_face_initializer_module.initialize_oh_panel_faces
except Exception:
    initialize_oh_panel_faces = None


def _body_axis_min_mm(body, axis):
    bbox = body.boundingBox
    if axis == "X":
        return bbox.minPoint.x * 10.0
    if axis == "Y":
        return bbox.minPoint.y * 10.0
    return bbox.minPoint.z * 10.0


def _axis_start_mm(bbox, axis):
    return bbox["x0"] if axis == "X" else bbox["y0"] if axis == "Y" else bbox["z0"]


def _axis_size_mm(bbox, axis):
    return (
        bbox["x1"] - bbox["x0"] if axis == "X"
        else bbox["y1"] - bbox["y0"] if axis == "Y"
        else bbox["z1"] - bbox["z0"]
    )


def _align_body_axis_min(component, body, axis, target_min_mm, feature_prefix="GT_ALIGN_"):
    current_min_mm = _body_axis_min_mm(body, axis)
    delta = float(target_min_mm) - float(current_min_mm)
    if abs(delta) <= 0.001:
        return
    dx = delta if axis == "X" else 0.0
    dy = delta if axis == "Y" else 0.0
    dz = delta if axis == "Z" else 0.0
    move_body_by_mm(component, body, dx, dy, dz, feature_prefix=feature_prefix)


def _add_box_body(component, board_id, bbox, body_prefix="GT", module_name="generalTall", move_prefix="GT_MOVE_"):
    sketches = component.sketches
    sketch = sketches.add(component.xYConstructionPlane)
    p0 = adsk.core.Point3D.create(mm_to_cm(bbox["x0"]), mm_to_cm(bbox["y0"]), 0)
    p1 = adsk.core.Point3D.create(mm_to_cm(bbox["x1"]), mm_to_cm(bbox["y1"]), 0)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
    if sketch.profiles.count < 1:
        return None, "No sketch profile generated for bbox rectangle."

    profile = sketch.profiles.item(0)
    height_mm = bbox["z1"] - bbox["z0"]
    extrudes = component.features.extrudeFeatures
    distance = adsk.core.ValueInput.createByReal(mm_to_cm(height_mm))
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, distance)
    extrude = extrudes.add(ext_input)
    if extrude.bodies.count < 1:
        return None, "Extrude created no body."

    body = extrude.bodies.item(0)
    body.name = "{}_{}".format(body_prefix, sanitize_token(board_id, fallback="board", limit=110))
    if abs(bbox["z0"]) > 1e-6:
        move_body_by_mm(component, body, 0.0, 0.0, float(bbox["z0"]), feature_prefix=move_prefix)
    try:
        body.attributes.add(ATTRIBUTE_GROUP, "module", module_name)
        body.attributes.add(ATTRIBUTE_GROUP, "boardId", str(board_id))
    except Exception:
        pass
    return body, None


def _vector_source_for_board(board):
    if isinstance(board.get("cutProfileVector"), list) and len(board.get("cutProfileVector")) > 0:
        return "cutProfileVector", board.get("cutProfileVector")
    if isinstance(board.get("profileVector"), list) and len(board.get("profileVector")) > 0:
        return "profileVector", board.get("profileVector")
    return None, None


def _points_equal(a, b, tol=1e-6):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _extract_local_profile_points(board, vector_source, raw_points):
    plane = str(board.get("profilePlane") or "")
    points = []
    for item in raw_points:
        if not isinstance(item, dict):
            return None, "Profile vector contains non-object points."
        if plane == "YZ":
            y = _as_float(item.get("y"))
            z = _as_float(item.get("z"))
            if y is None or z is None:
                return None, "YZ profile requires {y,z} points."
            points.append((y, z))
        elif plane == "XY":
            x = _as_float(item.get("x"))
            y = _as_float(item.get("y"))
            if x is None or y is None:
                return None, "XY profile requires {x,y} points."
            points.append((x, y))
        elif plane == "XZ":
            x = _as_float(item.get("x"))
            z = _as_float(item.get("z"))
            if x is None or z is None:
                return None, "XZ profile requires {x,z} points."
            points.append((x, z))
        else:
            return None, "Unsupported profilePlane: {!r}.".format(plane)

    if len(points) < 3:
        return None, "{} has fewer than 3 points.".format(vector_source)

    deduped = []
    for point in points:
        if not deduped or not _points_equal(point, deduped[-1]):
            deduped.append(point)
    if len(deduped) < 3:
        return None, "{} has fewer than 3 unique points.".format(vector_source)
    if not _points_equal(deduped[0], deduped[-1]):
        deduped.append(deduped[0])

    unique = []
    for point in deduped[:-1]:
        if not any(_points_equal(point, other) for other in unique):
            unique.append(point)
    if len(unique) < 3:
        return None, "{} has fewer than 3 unique points after cleanup.".format(vector_source)
    return deduped, None


def _axis_to_world(value, bbox_min, mode):
    return value if mode == "absolute" else bbox_min + value


def _profile_axis_modes(board, plane, vector_source):
    # Default contract: profile vectors are local profile coordinates.
    # Special case: current VD cutProfileVector stores absolute Z values.
    board_type = str(board.get("boardType") or "").lower()
    board_category = str(board.get("category") or "").lower()
    if (
        plane == "YZ"
        and vector_source == "cutProfileVector"
        and (board_type == "vertical_divider" or board_type == "divider" or board_category == "divider")
    ):
        return {"a": "local", "b": "absolute"}
    return {"a": "local", "b": "local"}


def _requires_xy_180_rotation(board, plane, module_name="generalTall"):
    if module_name != "generalTall":
        return False
    if plane != "XY":
        return False
    board_id = str(board.get("id") or "").upper()
    board_type = str(board.get("boardType") or "").upper()
    return board_id in ("T3", "B3") or board_type in ("T3", "B3")


def _rotate_world_points_xy_180(world_points, bbox):
    center_x = (bbox["x0"] + bbox["x1"]) / 2.0
    center_y = (bbox["y0"] + bbox["y1"]) / 2.0
    rotated = []
    for x, y, z in world_points:
        rotated.append((2.0 * center_x - x, 2.0 * center_y - y, z))
    return rotated


def _placement_offset_mm(board, result_debug=None, avoidance_z_shift_mm=0.0, module_name="generalTall", result_params=None):
    board_id = str(board.get("id") or "").upper()
    board_type = str(board.get("boardType") or "").upper()
    board_category = str(board.get("category") or "").lower()
    front_panel_thickness = _as_float((result_debug or {}).get("frontFaceAllowance")) if isinstance(result_debug, dict) else None
    front_panel_thickness = front_panel_thickness if front_panel_thickness is not None else 0.0

    if board_category == "side_panel" or board_id in ("SIDEPANEL_L", "SIDEPANEL_R"):
        # Generator now emits side panels with the front protrusion already in the bbox (y0 = -FPT).
        return 0.0, 0.0, 0.0

    if board_category == "avoidance_support" or board_id in ("AVOIDANCE_HORIZONTAL", "AVOIDANCE_VERTICAL"):
        return 0.0, -front_panel_thickness, 0.0

    if board_type == "STYLE2_FIXED_FRONT_PANEL" or board_id in ("TOPSTYLE2FIXEDFRONTPANEL", "BOTTOMSTYLE2FIXEDFRONTPANEL"):
        # Generator now emits style_2 fixed front panels at y -FPT..0 directly.
        return 0.0, 0.0, 0.0

    if board_id in ("T4", "T5") or board_type in ("T4", "T5"):
        return 0.0, -front_panel_thickness, 0.0

    if board_id in ("H13_BOTTOM", "H24_BOTTOM", "H34_BOTTOM"):
        return 0.0, 0.0, float(max(0.0, avoidance_z_shift_mm))

    needs_rear_notch_contact = board_id in ("T1", "T2", "B1", "B2") or board_type in ("T1", "T2", "B1", "B2")
    if needs_rear_notch_contact:
        if module_name == "overhead":
            top_clearance = _as_float((result_params or {}).get("topClearanceHeight"))
            if top_clearance is not None:
                return 0.0, top_clearance - 1.0, 0.0
        return 0.0, 39.0, 0.0
    return 0.0, 0.0, 0.0


def _world_point_from_local(bbox, plane, local_point, axis_modes):
    a, b = local_point
    if plane == "YZ":
        return (
            bbox["x0"],
            _axis_to_world(a, bbox["y0"], axis_modes["a"]),
            _axis_to_world(b, bbox["z0"], axis_modes["b"]),
        )
    if plane == "XY":
        return (
            _axis_to_world(a, bbox["x0"], axis_modes["a"]),
            _axis_to_world(b, bbox["y0"], axis_modes["b"]),
            bbox["z0"],
        )
    return (
        _axis_to_world(a, bbox["x0"], axis_modes["a"]),
        bbox["y0"],
        _axis_to_world(b, bbox["z0"], axis_modes["b"]),
    )


def _profile_plane_for_sketch(component, plane, bbox):
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    if plane == "YZ":
        plane_input.setByOffset(component.yZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(bbox["x0"])))
    elif plane == "XY":
        plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(bbox["z0"])))
    elif plane == "XZ":
        plane_input.setByOffset(component.xZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(bbox["y0"])))
    else:
        return None
    return construction.add(plane_input)


def _largest_profile(sketch):
    if sketch.profiles.count < 1:
        return None
    chosen = sketch.profiles.item(0)
    chosen_area = -1.0
    for idx in range(sketch.profiles.count):
        item = sketch.profiles.item(idx)
        try:
            area = abs(item.areaProperties().area)
        except Exception:
            area = 0.0
        if area >= chosen_area:
            chosen = item
            chosen_area = area
    return chosen


def _add_profile_body(
    component,
    board_id,
    board,
    bbox,
    vector_source,
    raw_points,
    body_prefix="GT",
    module_name="generalTall",
    align_prefix="GT_ALIGN_",
):
    plane = str(board.get("profilePlane") or "")
    axis = str(board.get("thicknessAxis") or "")
    if axis not in ("X", "Y", "Z"):
        return None, "Invalid thicknessAxis: {!r}.".format(axis)

    local_points, points_error = _extract_local_profile_points(board, vector_source, raw_points)
    if points_error:
        return None, points_error

    axis_modes = _profile_axis_modes(board, plane, vector_source)
    sketch_plane = _profile_plane_for_sketch(component, plane, bbox)
    if not sketch_plane:
        return None, "Unsupported profile plane mapping: {!r}.".format(plane)
    sketch = component.sketches.add(sketch_plane)
    sketch.name = "{}_{}_{}".format(body_prefix, sanitize_token(board_id, limit=60), vector_source)

    world_points = [_world_point_from_local(bbox, plane, point, axis_modes) for point in local_points]
    if _requires_xy_180_rotation(board, plane, module_name=module_name):
        world_points = _rotate_world_points_xy_180(world_points, bbox)
    for index in range(len(world_points) - 1):
        p0 = world_points[index]
        p1 = world_points[index + 1]
        if (
            abs(p0[0] - p1[0]) <= 1e-9
            and abs(p0[1] - p1[1]) <= 1e-9
            and abs(p0[2] - p1[2]) <= 1e-9
        ):
            continue
        m0 = adsk.core.Point3D.create(mm_to_cm(p0[0]), mm_to_cm(p0[1]), mm_to_cm(p0[2]))
        m1 = adsk.core.Point3D.create(mm_to_cm(p1[0]), mm_to_cm(p1[1]), mm_to_cm(p1[2]))
        s0 = sketch.modelToSketchSpace(m0)
        s1 = sketch.modelToSketchSpace(m1)
        sketch.sketchCurves.sketchLines.addByTwoPoints(s0, s1)

    profile = _largest_profile(sketch)
    if profile is None:
        return None, "No closed sketch profile available from {}.".format(vector_source)

    thickness_mm = _axis_size_mm(bbox, axis)
    if thickness_mm <= 0:
        return None, "Non-positive thickness along axis {}.".format(axis)

    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(thickness_mm)))
    extrude = extrudes.add(ext_input)
    if extrude.bodies.count < 1:
        return None, "Extrude created no body from {}.".format(vector_source)

    body = extrude.bodies.item(0)
    _align_body_axis_min(component, body, axis, _axis_start_mm(bbox, axis), feature_prefix=align_prefix)
    body.name = "{}_{}".format(body_prefix, sanitize_token(board_id, fallback="board", limit=110))
    try:
        body.attributes.add(ATTRIBUTE_GROUP, "module", module_name)
        body.attributes.add(ATTRIBUTE_GROUP, "boardId", str(board_id))
        body.attributes.add(ATTRIBUTE_GROUP, "profileSource", vector_source)
    except Exception:
        pass
    return body, None


def _is_zi_board(board):
    board_id = str(board.get("id") or "")
    board_type = str(board.get("boardType") or "").lower()
    return board_id.startswith("Zi") or "zi" in board_type


def _as_world_range(board_bbox, local_0, local_1, axis):
    base = board_bbox["x0"] if axis == "x" else board_bbox["y0"]
    world_0 = base + float(local_0)
    world_1 = base + float(local_1)
    return min(world_0, world_1), max(world_0, world_1)


def _clamp_range(v0, v1, min_v, max_v):
    low = max(min(v0, v1), min_v)
    high = min(max(v0, v1), max_v)
    if high <= low:
        return None
    return low, high


def _find_board_by_id(boards_by_id, board_id):
    if not isinstance(board_id, str):
        return None
    return boards_by_id.get(board_id)


def _collect_zi_groove_features(result):
    features = result.get("features")
    if not isinstance(features, list):
        return {}
    by_target = {}
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "zi_groove":
            continue
        target_id = feature.get("targetBoardId")
        if not isinstance(target_id, str) or not target_id:
            continue
        by_target.setdefault(target_id, []).append(feature)
    return by_target


def _create_zi_groove_cut(component, target_board, target_bbox, feature, boards_by_id):
    feature_id = str(feature.get("id") or "zi_groove")
    target_board_id = str(target_board.get("id") or "")
    divider_id = feature.get("dividerBoardId")
    divider = _find_board_by_id(boards_by_id, divider_id)
    divider_bbox = _board_bbox(divider) if isinstance(divider, dict) else None
    if divider_bbox is None:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "status": "skipped",
            "reason": "related VD board not found",
        }

    face = str(feature.get("face") or "")
    if face != "bottom":
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "status": "skipped",
            "reason": "only bottom-face Zi groove is enabled in Stage C1",
        }

    local_x0 = _as_float(feature.get("x0"))
    local_x1 = _as_float(feature.get("x1"))
    if local_x0 is not None and local_x1 is not None:
        world_x0, world_x1 = _as_world_range(target_bbox, local_x0, local_x1, "x")
    else:
        world_x0, world_x1 = divider_bbox["x0"], divider_bbox["x1"]

    local_y0 = _as_float(feature.get("y0"))
    local_y1 = _as_float(feature.get("y1"))
    if local_y0 is not None and local_y1 is not None:
        world_y0, world_y1 = _as_world_range(target_bbox, local_y0, local_y1, "y")
    else:
        mid_depth = target_bbox["y1"] - target_bbox["y0"]
        fallback_y0 = mid_depth / 3.0 - 5.0
        fallback_y1 = (mid_depth * 2.0) / 3.0 + 5.0
        world_y0, world_y1 = _as_world_range(target_bbox, fallback_y0, fallback_y1, "y")

    clamped_x = _clamp_range(world_x0, world_x1, target_bbox["x0"], target_bbox["x1"])
    clamped_y = _clamp_range(world_y0, world_y1, target_bbox["y0"], target_bbox["y1"])
    if clamped_x is None or clamped_y is None:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "xRange": [world_x0, world_x1],
            "yRange": [world_y0, world_y1],
            "status": "skipped",
            "reason": "groove range does not intersect target Zi board bbox",
        }

    x0, x1 = clamped_x
    y0, y1 = clamped_y
    depth = _as_float(feature.get("depth"))
    depth = depth if depth is not None and depth > 0 else 7.0
    world_z_top = target_bbox["z1"]
    world_z_bottom = max(target_bbox["z0"], target_bbox["z1"] - depth)
    effective_depth = world_z_top - world_z_bottom
    if effective_depth <= 0:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "xRange": [x0, x1],
            "yRange": [y0, y1],
            "zRange": [world_z_bottom, world_z_top],
            "depth": depth,
            "status": "skipped",
            "reason": "non-positive groove depth after clamp",
        }

    try:
        construction = component.constructionPlanes
        plane_input = construction.createInput()
        plane_input.setByOffset(
            component.xYConstructionPlane,
            adsk.core.ValueInput.createByReal(mm_to_cm(world_z_top)),
        )
        top_plane = construction.add(plane_input)
        sketch = component.sketches.add(top_plane)
        sketch.name = "GT_{}_groove_{}".format(sanitize_token(target_board_id, limit=40), sanitize_token(feature_id, limit=40))

        m0 = adsk.core.Point3D.create(mm_to_cm(x0), mm_to_cm(y0), mm_to_cm(world_z_top))
        m1 = adsk.core.Point3D.create(mm_to_cm(x1), mm_to_cm(y1), mm_to_cm(world_z_top))
        s0 = sketch.modelToSketchSpace(m0)
        s1 = sketch.modelToSketchSpace(m1)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(s0, s1)

        profile = _largest_profile(sketch)
        if profile is None:
            return {
                "featureId": feature_id,
                "targetBoardId": target_board_id,
                "relatedVD": divider_id,
                "xRange": [x0, x1],
                "yRange": [y0, y1],
                "zRange": [world_z_bottom, world_z_top],
                "depth": depth,
                "status": "failed",
                "reason": "no closed profile for zi groove cut",
            }

        extrudes = component.features.extrudeFeatures
        ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(effective_depth)))
        extrudes.add(ext_input)
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "xRange": [x0, x1],
            "yRange": [y0, y1],
            "zRange": [world_z_bottom, world_z_top],
            "depth": depth,
            "status": "created",
            "reason": "",
        }
    except Exception as ex:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "xRange": [x0, x1],
            "yRange": [y0, y1],
            "zRange": [world_z_bottom, world_z_top],
            "depth": depth,
            "status": "failed",
            "reason": "Fusion groove cut failed: {}".format(ex),
        }


def _move_body_rigid_transform(component, body, transform, feature_prefix="UCP_RIGID_"):
    bodies = adsk.core.ObjectCollection.create()
    bodies.add(body)
    move_input = component.features.moveFeatures.createInput(bodies, transform)
    try:
        move_input.defineAsFreeMove(transform)
    except Exception:
        pass
    move_feature = component.features.moveFeatures.add(move_input)
    move_feature.name = "{}{}".format(feature_prefix, sanitize_token(getattr(body, "name", "body"), limit=40))
    return move_feature


def _body_center_point_cm(body):
    bbox = body.boundingBox
    return adsk.core.Point3D.create(
        (bbox.minPoint.x + bbox.maxPoint.x) / 2.0,
        (bbox.minPoint.y + bbox.maxPoint.y) / 2.0,
        (bbox.minPoint.z + bbox.maxPoint.z) / 2.0,
    )


def _rotate_body_about_world_x(component, body, degrees, feature_prefix="UCP_ROTATE_X_"):
    transform = adsk.core.Matrix3D.create()
    transform.setToRotation(
        math.radians(float(degrees)),
        adsk.core.Vector3D.create(1.0, 0.0, 0.0),
        _body_center_point_cm(body),
    )
    return _move_body_rigid_transform(component, body, transform, feature_prefix=feature_prefix)


def _rotate_body_about_world_axis(component, body, axis_name, degrees, feature_prefix="UCP_ROTATE_"):
    axis_name = str(axis_name or "").upper()
    if axis_name == "Y":
        axis = adsk.core.Vector3D.create(0.0, 1.0, 0.0)
    elif axis_name == "Z":
        axis = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
    else:
        axis = adsk.core.Vector3D.create(1.0, 0.0, 0.0)
    transform = adsk.core.Matrix3D.create()
    transform.setToRotation(math.radians(float(degrees)), axis, _body_center_point_cm(body))
    return _move_body_rigid_transform(component, body, transform, feature_prefix=feature_prefix)


def _oh_collect_bp_grooves(result):
    features = result.get("features")
    if not isinstance(features, list):
        return []
    grooves = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        groove = feature.get("bp_groove")
        if isinstance(groove, dict):
            grooves.append((feature, groove))
    return grooves


def _oh_collect_hinge_holes_by_board(result):
    features = result.get("features")
    if not isinstance(features, list):
        return {}
    by_board = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        if feature.get("purpose") != "hinge" or feature.get("axis") != "Y":
            continue
        board_id = feature.get("boardId")
        if not isinstance(board_id, str) or not board_id:
            continue
        by_board.setdefault(board_id, []).append(feature)
    return by_board


def _oh_cut_bp_grooves(component, bp_body, bp_board, result):
    bp_bbox = _board_bbox(bp_board)
    if not bp_body or not bp_bbox:
        return []
    rows = []
    top_z = bp_bbox["z1"]
    for feature, groove in _oh_collect_bp_grooves(result):
        groove_id = str(groove.get("id") or feature.get("id") or "bp_groove")
        try:
            x = groove.get("x")
            y = groove.get("y")
            z = groove.get("z")
            if not (isinstance(x, list) and isinstance(y, list) and len(x) >= 2 and len(y) >= 2):
                raise ValueError("missing groove x/y range")
            x0, x1 = float(x[0]), float(x[1])
            y0, y1 = float(y[0]), float(y[1])
            depth = abs(float(z[1]) - float(z[0])) if isinstance(z, list) and len(z) >= 2 else _as_float(groove.get("depth_z"))
            depth = depth if depth and depth > 0 else max(0.0, bp_bbox["z1"] - bp_bbox["z0"]) / 2.0
            clamped_x = _clamp_range(x0, x1, bp_bbox["x0"], bp_bbox["x1"])
            clamped_y = _clamp_range(y0, y1, bp_bbox["y0"], bp_bbox["y1"])
            if clamped_x is None or clamped_y is None:
                rows.append({"featureId": groove_id, "status": "skipped", "reason": "groove outside BP bbox"})
                continue
            x0, x1 = clamped_x
            y0, y1 = clamped_y
            effective_depth = min(depth, bp_bbox["z1"] - bp_bbox["z0"])
            construction = component.constructionPlanes
            plane_input = construction.createInput()
            plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(top_z)))
            top_plane = construction.add(plane_input)
            sketch = component.sketches.add(top_plane)
            sketch.name = "OH_BP_GROOVE_{}".format(sanitize_token(groove_id, limit=50))
            p0 = sketch.modelToSketchSpace(adsk.core.Point3D.create(mm_to_cm(x0), mm_to_cm(y0), mm_to_cm(top_z)))
            p1 = sketch.modelToSketchSpace(adsk.core.Point3D.create(mm_to_cm(x1), mm_to_cm(y1), mm_to_cm(top_z)))
            sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
            profile = _largest_profile(sketch)
            if profile is None:
                rows.append({"featureId": groove_id, "status": "failed", "reason": "no closed BP groove profile"})
                continue
            extrudes = component.features.extrudeFeatures
            ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
            ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(effective_depth)))
            try:
                ext_input.participantBodies = [bp_body]
            except Exception:
                pass
            cut = extrudes.add(ext_input)
            cut.name = "OH_BP_GROOVE_CUT_{}".format(sanitize_token(groove_id, limit=50))
            rows.append({"featureId": groove_id, "status": "created", "xRange": [x0, x1], "yRange": [y0, y1], "depth": effective_depth})
        except Exception as ex:
            rows.append({"featureId": groove_id, "status": "failed", "reason": str(ex)})
    return rows


def _oh_cut_hinge_holes(component, board, body, hinge_features):
    bbox = _board_bbox(board)
    if not bbox or not body:
        return []
    rows = []
    plane_y = bbox["y1"]
    for feature in hinge_features or []:
        feature_id = str(feature.get("id") or "hinge")
        try:
            center = feature.get("center")
            if not (isinstance(center, list) and len(center) >= 2):
                raise ValueError("missing hinge center")
            x = bbox["x0"] + float(center[0])
            z = bbox["z0"] + float(center[1])
            diameter = _as_float(feature.get("diameter")) or 35.0
            depth = _as_float(feature.get("depth")) or max(0.0, bbox["y1"] - bbox["y0"])
            depth = min(depth, max(0.0, bbox["y1"] - bbox["y0"]))
            construction = component.constructionPlanes
            plane_input = construction.createInput()
            plane_input.setByOffset(component.xZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(plane_y)))
            back_plane = construction.add(plane_input)
            sketch = component.sketches.add(back_plane)
            sketch.name = "OH_HINGE_{}".format(sanitize_token(feature_id, limit=50))
            center_model = adsk.core.Point3D.create(mm_to_cm(x), mm_to_cm(plane_y), mm_to_cm(z))
            center_sketch = sketch.modelToSketchSpace(center_model)
            sketch.sketchCurves.sketchCircles.addByCenterRadius(center_sketch, mm_to_cm(diameter / 2.0))
            profile = _largest_profile(sketch)
            if profile is None:
                rows.append({"featureId": feature_id, "status": "failed", "reason": "no closed hinge cup profile"})
                continue
            extrudes = component.features.extrudeFeatures
            ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
            ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(depth)))
            try:
                ext_input.participantBodies = [body]
            except Exception:
                pass
            cut = extrudes.add(ext_input)
            cut.name = "OH_HINGE_CUP_CUT_{}".format(sanitize_token(feature_id, limit=50))
            rows.append({"featureId": feature_id, "status": "created", "faceY": plane_y, "direction": "-Y", "center": [x, z], "diameter": diameter, "depth": depth})
        except Exception as ex:
            rows.append({"featureId": feature_id, "status": "failed", "reason": str(ex)})
    return rows


def _oh_shift_dividers_z(component, bodies_by_id, boards_by_id, dz_mm=30.0, components_by_id=None):
    rows = []
    components_by_id = components_by_id or {}
    for board_id, board in boards_by_id.items():
        if str(board.get("category") or "").lower() != "divider":
            continue
        body = bodies_by_id.get(board_id)
        if not body:
            rows.append({"boardId": board_id, "status": "skipped", "reason": "body not found"})
            continue
        try:
            move_body_by_mm(components_by_id.get(board_id) or component, body, 0.0, 0.0, dz_mm, feature_prefix="OH_DIVIDER_Z_")
            rows.append({"boardId": board_id, "status": "created", "dz": dz_mm})
        except Exception as ex:
            rows.append({"boardId": board_id, "status": "failed", "dz": dz_mm, "reason": str(ex)})
    return rows


def _oh_shift_named_boards_z(component, bodies_by_id, board_ids, dz_mm, feature_prefix, components_by_id=None):
    rows = []
    components_by_id = components_by_id or {}
    for board_id in board_ids:
        body = bodies_by_id.get(board_id)
        if not body:
            rows.append({"boardId": board_id, "status": "skipped", "reason": "body not found"})
            continue
        try:
            move_body_by_mm(components_by_id.get(board_id) or component, body, 0.0, 0.0, dz_mm, feature_prefix=feature_prefix)
            rows.append({"boardId": board_id, "status": "created", "dz": dz_mm})
        except Exception as ex:
            rows.append({"boardId": board_id, "status": "failed", "dz": dz_mm, "reason": str(ex)})
    return rows


def _oh_shift_front_panels_z(component, bodies_by_id, boards_by_id, dz_mm=15.0, components_by_id=None):
    rows = []
    components_by_id = components_by_id or {}
    for board_id, board in boards_by_id.items():
        if str(board.get("category") or "").lower() != "front_panel":
            continue
        body = bodies_by_id.get(board_id)
        if not body:
            rows.append({"boardId": board_id, "status": "skipped", "reason": "body not found"})
            continue
        try:
            move_body_by_mm(components_by_id.get(board_id) or component, body, 0.0, 0.0, dz_mm, feature_prefix="OH_FP_Z_")
            rows.append({"boardId": board_id, "status": "created", "dz": dz_mm})
        except Exception as ex:
            rows.append({"boardId": board_id, "status": "failed", "dz": dz_mm, "reason": str(ex)})
    return rows


def _oh_result_params(result):
    params = result.get("params") if isinstance(result.get("params"), dict) else {}
    debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
    legacy = debug.get("legacyGeometry") if isinstance(debug.get("legacyGeometry"), dict) else {}
    cabinet = legacy.get("cabinet") if isinstance(legacy.get("cabinet"), dict) else {}
    manufacturing = legacy.get("manufacturing") if isinstance(legacy.get("manufacturing"), dict) else {}
    cabinet_depth = _as_float(params.get("cabinetDepth"))
    if cabinet_depth is None:
        cabinet_depth = _as_float(cabinet.get("Cd")) or 0.0
    fg_width = _as_float(params.get("featureWidth"))
    if fg_width is None:
        fg_width = _as_float(manufacturing.get("FGw")) or 15.0
    top_clearance = _as_float(params.get("topClearanceHeight"))
    if top_clearance is None:
        top_clearance = _as_float(manufacturing.get("TCH")) or 40.0
    clearance = _as_float(params.get("clearance"))
    if clearance is None:
        clearance = _as_float(manufacturing.get("FitClearance")) or 2.5
    return {
        "cabinetDepth": cabinet_depth,
        "fgWidth": fg_width,
        "topClearanceHeight": top_clearance,
        "clearance": clearance,
    }


def _oh_placement_formula_summary(result):
    params = _oh_result_params(result)
    cd = params["cabinetDepth"]
    fg = params["fgWidth"]
    tch = params["topClearanceHeight"]
    clearance = params["clearance"]
    return {
        "units": "mm",
        "inputs": {
            "Cd": cd,
            "FGw": fg,
            "TCH": tch,
            "clearance": clearance,
        },
        "basePlacementOffsets": {
            "T1": {"dx": 0.0, "dy": tch - 1.0, "dz": 0.0, "formula": "dy=TCH-1"},
            "T2": {"dx": 0.0, "dy": tch - 1.0, "dz": 0.0, "formula": "dy=TCH-1"},
        },
        "postprocessOffsets": {
            "BP": {"dx": 0.0, "dy": 0.0, "dz": fg, "formula": "dz=FGw"},
            "T1": {"dx": 0.0, "dy": 0.0, "dz": fg, "formula": "dz=FGw"},
            "T2": {"dx": 0.0, "dy": 0.0, "dz": fg, "formula": "dz=FGw"},
            "Divider": {"dx": 0.0, "dy": 0.0, "dz": 2.0 * fg, "formula": "dz=2*FGw"},
            "FrontPanel": {"dx": 0.0, "dy": 0.0, "dz": fg, "formula": "dz=FGw"},
            "T3": {"dx": 0.0, "dy": 0.0, "dz": -(tch + fg - 14.0) + fg, "formula": "dy=0, dz=-(TCH+FGw-14)+FGw"},
            "T4": {"dx": 0.0, "dy": cd - (2.0 * fg + clearance), "dz": -clearance, "formula": "dy=Cd-(2*FGw+clearance), dz=-clearance"},
        },
        "rotations": {
            "T4": {"axis": "X", "degrees": 90.0},
        },
    }


def _oh_profile_axis_range(board, axis_key):
    vector = board.get("profileVector") if isinstance(board, dict) else None
    if not isinstance(vector, list):
        return None
    values = []
    for point in vector:
        if isinstance(point, dict) and _as_float(point.get(axis_key)) is not None:
            values.append(float(point.get(axis_key)))
    if not values:
        return None
    return min(values), max(values)


def _oh_t3_depth(board):
    y_range = _oh_profile_axis_range(board, "y")
    if y_range:
        return max(0.0, y_range[1] - y_range[0])
    bbox = _board_bbox(board)
    if bbox:
        return min(90.0, max(0.0, bbox["y1"] - bbox["y0"]))
    return 90.0


def _oh_top_panel_translation_specs(result, boards_by_id):
    params = _oh_result_params(result)
    cd = params["cabinetDepth"]
    fg = params["fgWidth"]
    tch = params["topClearanceHeight"]
    clearance = params["clearance"]
    t3_depth = _oh_t3_depth(boards_by_id.get("T3", {}))
    return (
        {
            "boardId": "T3",
            "dx": 0.0,
            "dy": 0.0,
            "dz": -(tch + fg - 14.0) + fg,
            "formula": "dy=0, dz=-(TCH+FGw-14)+FGw",
            "inputs": {"Cd": cd, "T3Depth": t3_depth, "TCH": tch, "FGw": fg},
        },
        {
            "boardId": "T4",
            "dx": 0.0,
            "dy": cd - (2.0 * fg + clearance),
            "dz": -clearance,
            "formula": "dy=Cd-(2*FGw+clearance), dz=-clearance",
            "inputs": {"Cd": cd, "FGw": fg, "clearance": clearance},
        },
    )


def _oh_postprocess_bodies(component, result, bodies_by_id, boards_by_id, components_by_id=None):
    rows = {
        "bpGrooveCuts": [],
        "hingeCuts": [],
        "rotations": [],
        "topPanelTranslations": [],
        "frontPanelZShifts": [],
        "dividerZShifts": [],
        "supportZShifts": [],
    }
    components_by_id = components_by_id or {}
    oh_params = _oh_result_params(result)
    fg_width = oh_params["fgWidth"]
    rows["dividerZShifts"] = _oh_shift_dividers_z(component, bodies_by_id, boards_by_id, dz_mm=2.0 * fg_width)
    bp_board = boards_by_id.get("BP")
    if bp_board:
        rows["bpGrooveCuts"] = _oh_cut_bp_grooves(components_by_id.get("BP") or component, bodies_by_id.get("BP"), bp_board, result)

    hinge_by_board = _oh_collect_hinge_holes_by_board(result)
    for board_id, features in hinge_by_board.items():
        board = boards_by_id.get(board_id)
        body = bodies_by_id.get(board_id)
        rows["hingeCuts"].extend(_oh_cut_hinge_holes(components_by_id.get(board_id) or component, board, body, features))

    for board_id, axis_name, degrees in (("T4", "X", 90.0),):
        body = bodies_by_id.get(board_id)
        if not body:
            rows["rotations"].append({"boardId": board_id, "status": "skipped", "reason": "body not found"})
            continue
        try:
            _rotate_body_about_world_axis(components_by_id.get(board_id) or component, body, axis_name, degrees, feature_prefix="OH_ROTATE_{}_".format(axis_name))
            rows["rotations"].append({"boardId": board_id, "axis": axis_name, "degrees": degrees, "status": "created"})
        except Exception as ex:
            rows["rotations"].append({"boardId": board_id, "axis": axis_name, "degrees": degrees, "status": "failed", "reason": str(ex)})

    for spec in _oh_top_panel_translation_specs(result, boards_by_id):
        board_id = spec["boardId"]
        dx_mm = spec["dx"]
        dy_mm = spec["dy"]
        dz_mm = spec["dz"]
        body = bodies_by_id.get(board_id)
        if not body:
            rows["topPanelTranslations"].append({**spec, "status": "skipped", "reason": "body not found"})
            continue
        try:
            move_body_by_mm(components_by_id.get(board_id) or component, body, dx_mm, dy_mm, dz_mm, feature_prefix="OH_TOP_PANEL_PLACE_")
            rows["topPanelTranslations"].append({
                **spec,
                "status": "created",
            })
        except Exception as ex:
            rows["topPanelTranslations"].append({
                **spec,
                "status": "failed",
                "reason": str(ex),
            })
    rows["frontPanelZShifts"] = _oh_shift_front_panels_z(component, bodies_by_id, boards_by_id, dz_mm=fg_width, components_by_id=components_by_id)
    rows["supportZShifts"] = _oh_shift_named_boards_z(component, bodies_by_id, ("BP", "T1", "T2"), fg_width, "OH_SUPPORT_Z_", components_by_id=components_by_id)
    return rows


def create_rough_bodies_from_board_result(
    fusion_adapter,
    result,
    module_name="generalTall",
    body_prefix="GT",
    run_label=None,
    placement_feature_prefix="GT_PLACE_",
    move_feature_prefix="GT_MOVE_",
    align_feature_prefix="GT_ALIGN_",
    enable_zi_groove_cuts=False,
    enable_overhead_postprocess=False,
    avoidance_z_shift_mm=0.0,
    create_container_component=False,
    component_prefix=None,
    component_name=None,
):
    summary = {
        "createdBodies": 0,
        "skippedBoards": [],
        "createdBoardIds": [],
        "bodyAudit": [],
        "errors": [],
        "warnings": [],
        "runLabel": str(run_label or int(time.time() * 1000)),
        "sourceUsage": {"cutProfileVector": 0, "profileVector": 0, "bboxFallback": 0},
        "grooveCutsCreated": 0,
        "grooveCutsSkipped": 0,
        "grooveCutsFailed": 0,
        "bpGrooveCutsCreated": 0,
        "hingeCutsCreated": 0,
        "rotationOpsCreated": 0,
        "topPanelTranslationsCreated": 0,
        "frontPanelZShiftsCreated": 0,
        "dividerZShiftsCreated": 0,
        "supportZShiftsCreated": 0,
        "bodyComponentsCreated": 0,
        "bodyComponentNames": [],
        "avoidanceZShiftMm": float(max(0.0, avoidance_z_shift_mm)),
        "assemblyComponentName": None,
        "placementFormulas": _oh_placement_formula_summary(result) if enable_overhead_postprocess else {},
        "faceInitSummary": {
            "initializedCount": 0,
            "skippedCount": 0,
            "totalEdgeCount": 0,
            "totalSurfaceCount": 0,
            "boards": [],
        },
    }
    root_comp = fusion_adapter.get_root_component()
    if not root_comp:
        summary["errors"].append("No active Fusion design/root component.")
        return summary

    boards = result.get("boards")
    if not isinstance(boards, list):
        summary["errors"].append("{} result does not include boards list.".format(module_name))
        return summary
    boards_by_id = {str(board.get("id")): board for board in boards if isinstance(board, dict) and board.get("id")}
    bodies_by_id = {}
    components_by_id = {}
    panel_metadata_by_id = {}
    zi_grooves_by_target = _collect_zi_groove_features(result) if enable_zi_groove_cuts else {}
    result_debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}

    container, container_warning, assembly_component_name = _new_container_component(
        root_comp,
        summary["runLabel"],
        module_name=module_name,
        create_component=create_container_component,
        component_prefix=component_prefix,
        component_name=component_name,
    )
    summary["assemblyComponentName"] = assembly_component_name
    summary["_containerComponent"] = container
    if container_warning:
        summary["warnings"].append(container_warning)
    for index, board in enumerate(boards):
        board_id = str(board.get("id") or "board-{}".format(index + 1))
        bbox = _board_bbox(board)
        if not bbox:
            summary["skippedBoards"].append({"boardId": board_id, "reason": "missing_or_invalid_bbox"})
            continue

        width_x, depth_y, height_z = _rough_size_mm(bbox)
        audit_row = {
            "boardId": board_id,
            "bbox": bbox,
            "profilePlane": board.get("profilePlane"),
            "thicknessAxis": board.get("thicknessAxis"),
            "size": {"x": width_x, "y": depth_y, "z": height_z, "widthX": width_x, "depthY": depth_y, "heightZ": height_z},
        }
        if width_x <= 0 or depth_y <= 0 or height_z <= 0:
            summary["skippedBoards"].append({"boardId": board_id, "reason": "non_positive_dimension", "audit": audit_row})
            summary["bodyAudit"].append({**audit_row, "status": "skipped"})
            continue

        vector_source, raw_points = _vector_source_for_board(board)
        chosen_source = vector_source or "bboxFallback"
        body = None
        err = None
        target_component = container
        board_component_name = None
        if enable_overhead_postprocess and create_container_component:
            board_component_name = "OH_{}".format(sanitize_token(board_id, fallback="board", limit=60))
            try:
                target_component = _new_child_component(container, board_component_name, module_name=module_name, board_id=board_id)
                components_by_id[board_id] = target_component
            except Exception as ex:
                summary["warnings"].append("Could not create child component for {}: {}. Using assembly component.".format(board_id, ex))
                target_component = container
        if vector_source:
            body, err = _add_profile_body(
                target_component,
                board_id,
                board,
                bbox,
                vector_source,
                raw_points,
                body_prefix=body_prefix,
                module_name=module_name,
                align_prefix=align_feature_prefix,
            )
            if err:
                summary["warnings"].append(
                    "Board {} {} failed: {}. Falling back to bbox.".format(board_id, vector_source, err)
                )
                chosen_source = "bboxFallback"
                body, err = _add_box_body(
                    target_component,
                    board_id,
                    bbox,
                    body_prefix=body_prefix,
                    module_name=module_name,
                    move_prefix=move_feature_prefix,
                )
        else:
            body, err = _add_box_body(
                target_component,
                board_id,
                bbox,
                body_prefix=body_prefix,
                module_name=module_name,
                move_prefix=move_feature_prefix,
            )

        if err or not body:
            summary["skippedBoards"].append({"boardId": board_id, "reason": "fusion_box_create_failed", "error": err or "unknown"})
            summary["bodyAudit"].append({**audit_row, "source": chosen_source, "status": "failed", "error": err or "unknown"})
            continue

        oh_params = _oh_result_params(result) if enable_overhead_postprocess else None
        dx_mm, dy_mm, dz_mm = _placement_offset_mm(
            board,
            result_debug,
            avoidance_z_shift_mm=avoidance_z_shift_mm,
            module_name=module_name,
            result_params=oh_params,
        )
        if abs(dx_mm) > 1e-6 or abs(dy_mm) > 1e-6 or abs(dz_mm) > 1e-6:
            move_body_by_mm(target_component, body, dx_mm, dy_mm, dz_mm, feature_prefix=placement_feature_prefix)

        panel_metadata = None
        panel_metadata_written = None
        if module_name == "overhead":
            panel_metadata, panel_metadata_written = _write_oh_panel_metadata(body, board, bbox, boards, summary["runLabel"])
            if not panel_metadata_written:
                summary["warnings"].append("Could not write panel metadata for overhead board {}.".format(board_id))
            # Face metadata is initialized after post-processing (groove/hinge
            # cuts) so the surface/edge/milling classification sees the final
            # machined geometry instead of the plain box.
            if panel_metadata_written:
                panel_metadata_by_id[board_id] = panel_metadata

        summary["createdBodies"] += 1
        summary["createdBoardIds"].append(board_id)
        bodies_by_id[board_id] = body
        summary["sourceUsage"][chosen_source] = summary["sourceUsage"].get(chosen_source, 0) + 1
        groove_cuts = []
        if enable_zi_groove_cuts and _is_zi_board(board):
            for groove_feature in zi_grooves_by_target.get(board_id, []):
                groove_row = _create_zi_groove_cut(container, board, bbox, groove_feature, boards_by_id)
                groove_cuts.append(groove_row)
                status = groove_row.get("status")
                if status == "created":
                    summary["grooveCutsCreated"] += 1
                elif status == "failed":
                    summary["grooveCutsFailed"] += 1
                    summary["warnings"].append(
                        "Zi groove cut failed for {}: {}".format(
                            groove_row.get("featureId"),
                            groove_row.get("reason") or "unknown",
                        )
                    )
                else:
                    summary["grooveCutsSkipped"] += 1

        summary["bodyAudit"].append({
            **audit_row,
            "source": chosen_source,
            "status": "created",
            "bodyName": body.name,
            "componentName": board_component_name,
            "placementOffset": {"x": dx_mm, "y": dy_mm, "z": dz_mm},
            "grooveCuts": groove_cuts,
            "panelMetadataWritten": panel_metadata_written,
            "panelMetadata": panel_metadata,
        })

    if enable_overhead_postprocess:
        postprocess = _oh_postprocess_bodies(container, result, bodies_by_id, boards_by_id, components_by_id=components_by_id)
        summary["overheadPostprocess"] = postprocess
        summary["bpGrooveCutsCreated"] = len([row for row in postprocess.get("bpGrooveCuts", []) if row.get("status") == "created"])
        summary["hingeCutsCreated"] = len([row for row in postprocess.get("hingeCuts", []) if row.get("status") == "created"])
        summary["rotationOpsCreated"] = len([row for row in postprocess.get("rotations", []) if row.get("status") == "created"])
        summary["topPanelTranslationsCreated"] = len([row for row in postprocess.get("topPanelTranslations", []) if row.get("status") == "created"])
        summary["frontPanelZShiftsCreated"] = len([row for row in postprocess.get("frontPanelZShifts", []) if row.get("status") == "created"])
        summary["dividerZShiftsCreated"] = len([row for row in postprocess.get("dividerZShifts", []) if row.get("status") == "created"])
        summary["supportZShiftsCreated"] = len([row for row in postprocess.get("supportZShifts", []) if row.get("status") == "created"])
        summary["bodyComponentsCreated"] = len(components_by_id)
        summary["bodyComponentNames"] = ["OH_{}".format(sanitize_token(board_id, fallback="board", limit=60)) for board_id in components_by_id.keys()]
        for group_name in ("bpGrooveCuts", "hingeCuts", "rotations", "topPanelTranslations", "frontPanelZShifts", "dividerZShifts", "supportZShifts"):
            for row in postprocess.get(group_name, []):
                if row.get("status") == "failed":
                    summary["warnings"].append("Overhead {} failed for {}: {}".format(group_name, row.get("featureId") or row.get("boardId"), row.get("reason") or "unknown"))

    # Initialize face metadata after post-processing so surface/edge/milling
    # classification reflects the final machined geometry (grooves, holes).
    if module_name == "overhead" and initialize_oh_panel_faces:
        for board_id, body in bodies_by_id.items():
            panel_metadata = panel_metadata_by_id.get(board_id)
            if not panel_metadata or body is None:
                continue
            _run_oh_face_init(body, panel_metadata, board_id, summary)

    if summary["createdBodies"] == 0 and not summary["errors"]:
        summary["warnings"].append("No {} rough bodies were created.".format(module_name))
    if assembly_component_name is None:
        summary["modelZOffset"] = offset_matching_bodies_z_mm(
            root_comp,
            name_prefixes=["{}_".format(body_prefix)],
            module=module_name,
            dz_mm=MODEL_Z_OFFSET_MM,
            feature_prefix="{}_MODEL_Z_OFFSET_".format(sanitize_token(body_prefix, fallback="BODY", limit=20)),
        )
    else:
        summary["modelZOffset"] = {"offsetMm": MODEL_Z_OFFSET_MM, "mode": "componentOccurrence", "assemblyComponentName": assembly_component_name}
    return summary


GT_FP_STAGE_OFFSET_X_MM = 100000.0
GT_FP_CAPSULE_ARC_SEGMENTS = 16


def _gt_capsule_outline_points(x0, x1, z0, z1):
    """Closed capsule outline (XZ plane, mm) approximated with line segments; avoids sketch arc direction pitfalls."""
    radius = min((x1 - x0) / 2.0, (z1 - z0) / 2.0)
    horizontal = (x1 - x0) >= (z1 - z0)
    points = []
    if horizontal:
        cz = (z0 + z1) / 2.0
        left_cx = x0 + radius
        right_cx = x1 - radius
        points.append((left_cx, z1))
        points.append((right_cx, z1))
        for step in range(1, GT_FP_CAPSULE_ARC_SEGMENTS):
            angle = math.pi / 2.0 - math.pi * step / GT_FP_CAPSULE_ARC_SEGMENTS
            points.append((right_cx + radius * math.cos(angle), cz + radius * math.sin(angle)))
        points.append((right_cx, z0))
        points.append((left_cx, z0))
        for step in range(1, GT_FP_CAPSULE_ARC_SEGMENTS):
            angle = -math.pi / 2.0 - math.pi * step / GT_FP_CAPSULE_ARC_SEGMENTS
            points.append((left_cx + radius * math.cos(angle), cz + radius * math.sin(angle)))
    else:
        cx = (x0 + x1) / 2.0
        bottom_cz = z0 + radius
        top_cz = z1 - radius
        points.append((x0, bottom_cz))
        points.append((x0, top_cz))
        for step in range(1, GT_FP_CAPSULE_ARC_SEGMENTS):
            angle = math.pi + math.pi * step / GT_FP_CAPSULE_ARC_SEGMENTS
            points.append((cx + radius * math.cos(angle), top_cz - radius * math.sin(angle)))
        points.append((x1, top_cz))
        points.append((x1, bottom_cz))
        for step in range(1, GT_FP_CAPSULE_ARC_SEGMENTS):
            angle = math.pi * step / GT_FP_CAPSULE_ARC_SEGMENTS
            points.append((cx + radius * math.cos(angle), bottom_cz - radius * math.sin(angle)))
    points.append(points[0])
    return points


def _gt_xz_sketch_at_y(component, y_mm, name):
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    plane_input.setByOffset(component.xZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(y_mm)))
    plane = construction.add(plane_input)
    sketch = component.sketches.add(plane)
    sketch.name = name
    return sketch


def _gt_cut_fp_lock(component, body, panel, stage_x):
    cutout = panel.get("lockCutout")
    if not isinstance(cutout, dict):
        return []
    x0 = _as_float(cutout.get("x0"))
    x1 = _as_float(cutout.get("x1"))
    z0 = _as_float(cutout.get("z0"))
    z1 = _as_float(cutout.get("z1"))
    if None in (x0, x1, z0, z1) or x1 <= x0 or z1 <= z0:
        return [{"panelId": panel.get("id"), "kind": "lock_cutout", "status": "skipped", "reason": "invalid bounds"}]
    thickness = max(0.1, _as_float(panel.get("thickness")) or 16.0)
    rear_y = _as_float(panel.get("y1"))
    rear_y = rear_y if rear_y is not None else 0.0
    try:
        sketch = _gt_xz_sketch_at_y(component, rear_y, "GT_FP_LOCK_{}".format(sanitize_token(str(panel.get("id") or "FP"), limit=50)))
        outline = _gt_capsule_outline_points(x0 + stage_x, x1 + stage_x, z0, z1)
        lines = sketch.sketchCurves.sketchLines
        for index in range(len(outline) - 1):
            p0 = outline[index]
            p1 = outline[index + 1]
            m0 = adsk.core.Point3D.create(mm_to_cm(p0[0]), mm_to_cm(rear_y), mm_to_cm(p0[1]))
            m1 = adsk.core.Point3D.create(mm_to_cm(p1[0]), mm_to_cm(rear_y), mm_to_cm(p1[1]))
            lines.addByTwoPoints(sketch.modelToSketchSpace(m0), sketch.modelToSketchSpace(m1))
        profile = _largest_profile(sketch)
        if profile is None:
            return [{"panelId": panel.get("id"), "kind": "lock_cutout", "status": "failed", "reason": "no closed lock profile"}]
        extrudes = component.features.extrudeFeatures
        ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(thickness)))
        try:
            participants = adsk.core.ObjectCollection.create()
            participants.add(body)
            ext_input.participantBodies = participants
        except Exception:
            pass
        cut = extrudes.add(ext_input)
        cut.name = "GT_FP_LOCK_CUT_{}".format(sanitize_token(str(panel.get("id") or "FP"), limit=50))
        return [{
            "panelId": panel.get("id"),
            "kind": "lock_cutout",
            "status": "created",
            "orientation": cutout.get("orientation"),
            "depth": thickness,
            "stagedCut": True,
        }]
    except Exception as ex:
        return [{"panelId": panel.get("id"), "kind": "lock_cutout", "status": "failed", "reason": str(ex)}]


def _gt_cut_fp_hinges(component, body, panel, stage_x):
    holes = panel.get("hingeHoles")
    if not isinstance(holes, list) or not holes:
        return []
    thickness = max(0.1, _as_float(panel.get("thickness")) or 16.0)
    rear_y = _as_float(panel.get("y1"))
    rear_y = rear_y if rear_y is not None else 0.0
    audits = []
    max_depth = 0.1
    try:
        sketch = _gt_xz_sketch_at_y(component, rear_y, "GT_FP_HINGE_{}".format(sanitize_token(str(panel.get("id") or "FP"), limit=50)))
        circles = sketch.sketchCurves.sketchCircles
        drawn = 0
        for hole in holes:
            if not isinstance(hole, dict):
                continue
            cx = _as_float(hole.get("centerX"))
            cz = _as_float(hole.get("centerZ"))
            diameter = _as_float(hole.get("diameter")) or 35.0
            depth = min(thickness, max(0.1, _as_float(hole.get("depth")) or 12.5))
            if cx is None or cz is None or diameter <= 0:
                audits.append({"panelId": panel.get("id"), "id": hole.get("id"), "kind": "hinge_cup", "status": "skipped", "reason": "invalid hinge cup"})
                continue
            center = adsk.core.Point3D.create(mm_to_cm(cx + stage_x), mm_to_cm(rear_y), mm_to_cm(cz))
            circles.addByCenterRadius(sketch.modelToSketchSpace(center), mm_to_cm(diameter / 2.0))
            max_depth = max(max_depth, depth)
            drawn += 1
            audits.append({"panelId": panel.get("id"), "id": hole.get("id"), "kind": "hinge_cup", "status": "drawn", "diameter": diameter, "depth": depth})
        if drawn == 0:
            return audits
        profiles = adsk.core.ObjectCollection.create()
        for idx in range(sketch.profiles.count):
            profiles.add(sketch.profiles.item(idx))
        if profiles.count == 0:
            return [{**audit, "status": "failed", "reason": "no closed hinge profiles"} for audit in audits]
        extrudes = component.features.extrudeFeatures
        ext_input = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(max_depth)))
        try:
            participants = adsk.core.ObjectCollection.create()
            participants.add(body)
            ext_input.participantBodies = participants
        except Exception:
            pass
        cut = extrudes.add(ext_input)
        cut.name = "GT_FP_HINGE_CUT_{}".format(sanitize_token(str(panel.get("id") or "FP"), limit=50))
        return [
            {**audit, "status": "created" if audit.get("status") == "drawn" else audit.get("status"), "stagedCut": True}
            for audit in audits
        ]
    except Exception as ex:
        return [{"panelId": panel.get("id"), "kind": "hinge_cup", "status": "failed", "reason": str(ex)}]


def _gt_create_front_panel_bodies(component, result, summary):
    front_panels = result.get("frontPanels")
    if not isinstance(front_panels, list) or not front_panels:
        return
    for panel in front_panels:
        if not isinstance(panel, dict):
            continue
        panel_id = str(panel.get("id") or "FP")
        bbox = _board_bbox(panel)
        if not bbox or bbox["x1"] <= bbox["x0"] or bbox["y1"] <= bbox["y0"] or bbox["z1"] <= bbox["z0"]:
            summary["skippedBoards"].append({"boardId": panel_id, "reason": "invalid_front_panel_bbox"})
            continue
        try:
            body, err = _add_box_body(component, panel_id, bbox, body_prefix="GT_FP", module_name="generalTall", move_prefix="GT_FP_MOVE_")
            if err or not body:
                summary["skippedBoards"].append({"boardId": panel_id, "reason": err or "front_panel_create_failed"})
                continue
            # Stage far away before cutting so hardware cuts can never touch structural boards.
            has_hardware = isinstance(panel.get("lockCutout"), dict) or (isinstance(panel.get("hingeHoles"), list) and panel.get("hingeHoles"))
            if has_hardware:
                move_body_by_mm(component, body, GT_FP_STAGE_OFFSET_X_MM, 0.0, 0.0, feature_prefix="GT_FP_STAGE_")
                try:
                    summary["frontPanelCutAudit"].extend(_gt_cut_fp_lock(component, body, panel, GT_FP_STAGE_OFFSET_X_MM))
                    summary["frontPanelCutAudit"].extend(_gt_cut_fp_hinges(component, body, panel, GT_FP_STAGE_OFFSET_X_MM))
                finally:
                    move_body_by_mm(component, body, -GT_FP_STAGE_OFFSET_X_MM, 0.0, 0.0, feature_prefix="GT_FP_UNSTAGE_")
            summary["createdBodies"] += 1
            summary["frontPanelsCreated"] += 1
            summary["createdBoardIds"].append(panel_id)
            summary["bodyAudit"].append({
                "boardId": panel_id,
                "bbox": bbox,
                "profilePlane": "XZ",
                "thicknessAxis": "Y",
                "source": "frontPanelMetadata",
                "status": "created",
                "bodyName": body.name,
                "resolvedType": panel.get("resolvedType"),
            })
        except Exception as ex:
            summary["skippedBoards"].append({"boardId": panel_id, "reason": "front_panel_exception: {}".format(ex)})


def create_rough_bodies_from_general_tall_result(fusion_adapter, result, run_label=None, avoidance_z_shift_mm=0.0):
    summary = create_rough_bodies_from_board_result(
        fusion_adapter,
        result,
        module_name="generalTall",
        body_prefix="GT",
        run_label=run_label,
        placement_feature_prefix="GT_PLACE_",
        move_feature_prefix="GT_MOVE_",
        align_feature_prefix="GT_ALIGN_",
        enable_zi_groove_cuts=True,
        avoidance_z_shift_mm=avoidance_z_shift_mm,
        create_container_component=True,
        component_prefix="GT",
    )
    summary.setdefault("frontPanelsCreated", 0)
    summary.setdefault("frontPanelCutAudit", [])
    root_comp = fusion_adapter.get_root_component()
    if root_comp:
        fp_component = summary.get("_containerComponent") or root_comp
        _gt_create_front_panel_bodies(fp_component, result, summary)
        summary["frontPanelComponentName"] = summary.get("assemblyComponentName")
        summary["frontPanelModelZOffset"] = {
            "offsetMm": MODEL_Z_OFFSET_MM,
            "movedBodies": 0,
            "failedBodies": 0,
            "mode": "sameComponentAtModelZ" if summary.get("assemblyComponentName") else "rootFallback",
        }
        for row in summary["frontPanelCutAudit"]:
            if row.get("status") == "failed":
                summary["warnings"].append(
                    "GT front panel {} cut failed for {}: {}".format(
                        row.get("kind"), row.get("panelId"), row.get("reason") or "unknown"
                    )
                )
    return summary
