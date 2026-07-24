import json
import os
import re
import time

import adsk.core
import adsk.fusion

from geometry_ops import avoid_existing_at_origin
from assembly_cut_face import assembly_cut_face

ADAPTER_REVISION = "yzHalfCutSide_v39"
ATTRIBUTE_GROUP = "CabinetNC"
MODEL_Z_OFFSET_MM = 10000.0
# Flat bodies are modelled at z=0 inside each panel component (same as Lounge).
# MODEL_Z_OFFSET_MM is only used for legacy runs without a work-zone origin.
FLAT_STAGING_Z_MM = 0.0


def _flat_staging_z_mm():
    return FLAT_STAGING_Z_MM


def mm_to_cm(value_mm):
    return float(value_mm) / 10.0


def sanitize_token(value, fallback="panel", limit=80):
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or fallback)).strip("_")
    return (token or fallback)[:limit]


def _num(value, fallback=None):
    try:
        parsed = float(value)
        return parsed
    except Exception:
        return fallback


def _largest_profile(sketch):
    if sketch.profiles.count < 1:
        return None
    chosen = sketch.profiles.item(0)
    chosen_area = -1.0
    for idx in range(sketch.profiles.count):
        profile = sketch.profiles.item(idx)
        try:
            area = abs(profile.areaProperties().area)
        except Exception:
            area = 0.0
        if area >= chosen_area:
            chosen = profile
            chosen_area = area
    return chosen


def _profile_bbox_area(profile):
    try:
        bbox = profile.boundingBox
        return abs((bbox.maxPoint.x - bbox.minPoint.x) * (bbox.maxPoint.y - bbox.minPoint.y) * (bbox.maxPoint.z - bbox.minPoint.z))
    except Exception:
        return 0.0


def _widest_profile(sketch):
    if sketch.profiles.count < 1:
        return None
    chosen = sketch.profiles.item(0)
    chosen_score = -1.0
    for idx in range(sketch.profiles.count):
        profile = sketch.profiles.item(idx)
        score = _profile_bbox_area(profile)
        try:
            score += abs(profile.areaProperties().area) * 0.001
        except Exception:
            pass
        if score >= chosen_score:
            chosen = profile
            chosen_score = score
    return chosen


def _all_profiles(sketch):
    if sketch.profiles.count < 1:
        return None
    profiles = adsk.core.ObjectCollection.create()
    for idx in range(sketch.profiles.count):
        profiles.add(sketch.profiles.item(idx))
    return profiles


def _close_points(points):
    clean = []
    for point in points or []:
        if not isinstance(point, (list, tuple)) or len(point) < 2:
            continue
        a = _num(point[0], None)
        b = _num(point[1], None)
        if a is None or b is None:
            continue
        if clean and abs(clean[-1][0] - a) < 1e-6 and abs(clean[-1][1] - b) < 1e-6:
            continue
        clean.append((a, b))
    if len(clean) >= 2 and (abs(clean[0][0] - clean[-1][0]) > 1e-6 or abs(clean[0][1] - clean[-1][1]) > 1e-6):
        clean.append(clean[0])
    return clean


def _bounds(points):
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), max(xs), min(ys), max(ys)


def _board_bbox(board):
    values = [_num(board.get(key)) for key in ("x0", "x1", "y0", "y1", "z0", "z1")]
    if any(value is None for value in values):
        return None
    return {
        "x0": values[0],
        "x1": values[1],
        "y0": values[2],
        "y1": values[3],
        "z0": values[4],
        "z1": values[5],
    }


def _v_panel_bbox(panel, outer_points):
    min_a, max_a, min_b, max_b = _bounds(outer_points)
    x0 = _num(panel.get("x0"))
    x1 = _num(panel.get("x1"))
    if x0 is None or x1 is None:
        return None
    return {
        "x0": x0,
        "x1": x1,
        "y0": min_a,
        "y1": max_a,
        "z0": min_b,
        "z1": max_b,
    }


def _thickness_mm(bbox, thickness_axis):
    if thickness_axis == "X":
        return bbox["x1"] - bbox["x0"]
    if thickness_axis == "Y":
        return bbox["y1"] - bbox["y0"]
    return bbox["z1"] - bbox["z0"]


def _world_point_from_profile(plane, bbox, point2d):
    a, b = point2d
    if plane == "XY":
        return (a, b, bbox["z0"])
    if plane == "XZ":
        return (a, bbox["y0"], b)
    return (bbox["x0"], a, b)


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


def _cut_face_plane_for_sketch(component, plane, bbox, cutout=None):
    """Sketch plane on the face the cut enters.

    Half grooves respect cutout.side (left=-min axis, right=+max axis).
    Through / notches keep the legacy +max face.
    """
    face = assembly_cut_face(plane, bbox, cutout or {})
    origin_mm = face.get("originMm")
    if origin_mm is None:
        return None
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    if plane == "YZ":
        plane_input.setByOffset(
            component.yZConstructionPlane,
            adsk.core.ValueInput.createByReal(mm_to_cm(origin_mm)),
        )
    elif plane == "XY":
        plane_input.setByOffset(
            component.xYConstructionPlane,
            adsk.core.ValueInput.createByReal(mm_to_cm(origin_mm)),
        )
    elif plane == "XZ":
        plane_input.setByOffset(
            component.xZConstructionPlane,
            adsk.core.ValueInput.createByReal(mm_to_cm(origin_mm)),
        )
    else:
        return None
    return construction.add(plane_input)


def _panel_entries(result):
    panel_dxf = result.get("panelDxf") if isinstance(result.get("panelDxf"), list) else None
    if panel_dxf is not None:
        entries = []
        for panel in panel_dxf:
            if not isinstance(panel, dict):
                continue
            bbox = panel.get("bbox") if isinstance(panel.get("bbox"), dict) else None
            body = {
                "outer": panel.get("outer"),
                "cutouts": list(panel.get("notchVectors") or []) + list(panel.get("throughVectors") or []) + list(panel.get("halfGrooveVectors") or []),
            }
            points = _close_points(panel.get("outer"))
            if len(points) < 4 or not bbox:
                continue
            entries.append({
                "kind": str(panel.get("panelKind") or "board"),
                "id": str(panel.get("panelId") or "panel"),
                "type": str(panel.get("panelType") or "panel"),
                "materialThickness": _num(panel.get("materialThickness"), 15.0),
                "plane": str(panel.get("plane") or "XY"),
                "thicknessAxis": str(panel.get("thicknessAxis") or "Z"),
                "bbox": {
                    "x0": _num(bbox.get("x0"), 0.0),
                    "x1": _num(bbox.get("x1"), 0.0),
                    "y0": _num(bbox.get("y0"), 0.0),
                    "y1": _num(bbox.get("y1"), 0.0),
                    "z0": _num(bbox.get("z0"), 0.0),
                    "z1": _num(bbox.get("z1"), 0.0),
                },
                "body": body,
                "points": points,
                "notchVectors": list(panel.get("notchVectors") or []),
                "throughVectors": list(panel.get("throughVectors") or []),
                "halfGrooveVectors": list(panel.get("halfGrooveVectors") or []),
            })
        for front_panel in result.get("frontPanels") or []:
            if not isinstance(front_panel, dict):
                continue
            x0 = _num(front_panel.get("x0"), None)
            x1 = _num(front_panel.get("x1"), None)
            y0 = _num(front_panel.get("y0"), None)
            y1 = _num(front_panel.get("y1"), None)
            z0 = _num(front_panel.get("z0"), None)
            z1 = _num(front_panel.get("z1"), None)
            if None in (x0, x1, y0, y1, z0, z1) or x1 <= x0 or y1 <= y0 or z1 <= z0:
                continue
            points = _close_points([[x0, z0], [x1, z0], [x1, z1], [x0, z1]])
            lock_cutout = front_panel.get("lockCutout") if isinstance(front_panel.get("lockCutout"), dict) else None
            hinge_holes = front_panel.get("hingeHoles") if isinstance(front_panel.get("hingeHoles"), list) else []
            entries.append({
                "kind": "frontPanel",
                "id": str(front_panel.get("id") or "front_panel"),
                "type": str(front_panel.get("type") or "front_panel"),
                "materialThickness": max(0.1, y1 - y0),
                "plane": "XZ",
                "thicknessAxis": "Y",
                "bbox": {
                    "x0": x0,
                    "x1": x1,
                    "y0": y0,
                    "y1": y1,
                    "z0": z0,
                    "z1": z1,
                },
                "body": {"outer": points, "cutouts": []},
                "points": points,
                "throughVectors": [],
                "halfGrooveVectors": [],
                "lockCutouts": [lock_cutout] if lock_cutout else [],
                "hingeHoles": [hole for hole in hinge_holes if isinstance(hole, dict)],
            })
        return entries

    entries = []
    for board in result.get("boards") or []:
        if not isinstance(board, dict):
            continue
        body = board.get("body") if isinstance(board.get("body"), dict) else {}
        points = _close_points(body.get("outer"))
        bbox = _board_bbox(board)
        if len(points) < 4 or bbox is None:
            continue
        entries.append({
            "kind": "board",
            "id": str(board.get("id") or "board"),
            "type": str(board.get("type") or "board"),
            "materialThickness": _num(board.get("materialThickness"), 15.0),
            "plane": str(board.get("profilePlane") or "XY"),
            "thicknessAxis": str(board.get("thicknessAxis") or "Z"),
            "bbox": bbox,
            "body": body,
            "points": points,
        })
    default_thickness = _num(((result.get("params") or {}).get("globalSettings") or {}).get("materialThickness"), 15.0)
    for panel in result.get("vPanels") or []:
        if not isinstance(panel, dict):
            continue
        body = panel.get("body") if isinstance(panel.get("body"), dict) else {}
        points = _close_points(body.get("outer") or panel.get("yzProfile"))
        bbox = _v_panel_bbox(panel, points)
        if len(points) < 4 or bbox is None:
            continue
        entries.append({
            "kind": "vPanel",
            "id": str(panel.get("id") or "V"),
            "type": "VPanel",
            "materialThickness": bbox["x1"] - bbox["x0"],
            "plane": "YZ",
            "thicknessAxis": "X",
            "bbox": bbox,
            "body": body,
            "points": points,
        })
    return entries


def _apply_flat_layout(entries, row_width=2200.0, gap=80.0):
    cursor_x = 0.0
    cursor_y = 0.0
    row_height = 0.0
    for entry in entries:
        # YZ (V-panels) are built directly in assembly pose; no flat spread.
        if entry.get("plane") == "YZ":
            entry["flatOffset"] = {"x": 0.0, "y": 0.0}
            continue
        points = entry.get("points") or []
        if not points:
            entry["flatOffset"] = {"x": cursor_x, "y": cursor_y}
            continue
        min_x, max_x, min_y, max_y = _bounds(points)
        width = max(1.0, max_x - min_x)
        height = max(1.0, max_y - min_y)
        if cursor_x > 0 and cursor_x + width > row_width:
            cursor_x = 0.0
            cursor_y += row_height + gap
            row_height = 0.0
        entry["flatOffset"] = {
            "x": cursor_x - min_x,
            "y": cursor_y - min_y,
        }
        cursor_x += width + gap
        row_height = max(row_height, height)


def _assign_component_name(occurrence, component, desired_name):
    """Rename occurrence+component, auto-suffixing on duplicate-name errors.

    Fusion component names are unique per design; assigning a duplicate RAISES.
    Naming must never abort an already placed component.
    """
    base = sanitize_token(desired_name, fallback="assembly", limit=76)
    candidates = [base] + ["{}_{}".format(base, index) for index in range(2, 100)]
    for candidate in candidates:
        try:
            component.name = candidate
        except Exception:
            continue
        try:
            occurrence.name = candidate
        except Exception:
            pass
        return candidate
    try:
        return str(component.name)
    except Exception:
        return base


def _new_panel_component(parent_component, panel_id):
    """One kitchen panel = one child component (assembly semantics).

    Returns (component, occurrence).  The occurrence is needed to apply the
    flat→assembly rigid transform; body-level moveFeatures are unreliable
    inside per-panel child components.
    """
    transform = adsk.core.Matrix3D.create()
    occurrence = parent_component.occurrences.addNewComponent(transform)
    component = occurrence.component
    _assign_component_name(
        occurrence, component, "K_{}".format(sanitize_token(panel_id, fallback="panel", limit=60))
    )
    try:
        component.attributes.add(ATTRIBUTE_GROUP, "module", "kitchen")
        component.attributes.add(ATTRIBUTE_GROUP, "boardId", str(panel_id))
    except Exception:
        pass
    return component, occurrence


def _write_placement_debug(payload):
    try:
        path = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "placement_debug.json")
        )
        payload = dict(payload)
        payload["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
    except Exception:
        pass


def _new_assembly_component(root_comp, run_label, component_name=None, origin_x_mm=0.0, origin_y_mm=0.0, origin_z_mm=0.0):
    if component_name:
        component_name = sanitize_token(component_name, fallback="assembly", limit=80)
    else:
        component_name = "KITCHEN_{}".format(sanitize_token(run_label or int(time.time() * 1000), fallback="assembly", limit=60))
    try:
        transform = adsk.core.Matrix3D.create()
        transform.translation = adsk.core.Vector3D.create(
            mm_to_cm(float(origin_x_mm or 0.0)), mm_to_cm(float(origin_y_mm or 0.0)), mm_to_cm(float(origin_z_mm or 0.0))
        )
        occurrence = root_comp.occurrences.addNewComponent(transform)
        component = occurrence.component
    except Exception as ex:
        return root_comp, None, "Could not create Kitchen assembly component; using root component instead: {}".format(ex)

    _capture_position_snapshot(root_comp)
    component_name = _assign_component_name(occurrence, component, component_name)
    try:
        component.attributes.add(ATTRIBUTE_GROUP, "module", "kitchen")
        component.attributes.add(ATTRIBUTE_GROUP, "assemblyName", component_name)
        # Connect collect also looks up UnifiedCabinetPlugin.assemblyName.
        component.attributes.add("UnifiedCabinetPlugin", "module", "kitchen")
        component.attributes.add("UnifiedCabinetPlugin", "assemblyName", component_name)
    except Exception:
        pass
    return component, component_name, None


def _offset_kitchen_root_bodies(root_comp, dz_mm=MODEL_Z_OFFSET_MM):
    bodies = adsk.core.ObjectCollection.create()
    failed = 0
    try:
        count = root_comp.bRepBodies.count
    except Exception:
        count = 0
    for idx in range(count):
        try:
            body = root_comp.bRepBodies.item(idx)
            attr = body.attributes.itemByName(ATTRIBUTE_GROUP, "module")
            if attr and str(attr.value) == "kitchen":
                bodies.add(body)
        except Exception:
            failed += 1
    if bodies.count < 1:
        return {"offsetMm": dz_mm, "matchedBodies": 0, "movedBodies": 0, "failedBodies": failed}
    transform = adsk.core.Matrix3D.create()
    transform.translation = adsk.core.Vector3D.create(0, 0, mm_to_cm(dz_mm))
    try:
        move_input = root_comp.features.moveFeatures.createInput(bodies, transform)
        try:
            move_input.defineAsFreeMove(transform)
        except Exception:
            pass
        move = root_comp.features.moveFeatures.add(move_input)
        move.name = "KITCHEN_MODEL_Z_OFFSET_{}mm".format(int(dz_mm))
        return {"offsetMm": dz_mm, "matchedBodies": bodies.count, "movedBodies": bodies.count, "failedBodies": failed}
    except Exception:
        return {"offsetMm": dz_mm, "matchedBodies": bodies.count, "movedBodies": 0, "failedBodies": failed + bodies.count}


def _offset_created_kitchen_bodies(component, bodies, dz_mm=MODEL_Z_OFFSET_MM):
    collection = adsk.core.ObjectCollection.create()
    failed = 0
    seen = set()
    for body in bodies or []:
        try:
            token = getattr(body, "entityToken", None) or str(id(body))
            if token in seen:
                continue
            seen.add(token)
            collection.add(body)
        except Exception:
            failed += 1
    if collection.count < 1:
        return {"offsetMm": dz_mm, "movedBodies": 0, "failedBodies": failed}
    transform = adsk.core.Matrix3D.create()
    transform.translation = adsk.core.Vector3D.create(0, 0, mm_to_cm(dz_mm))
    try:
        move_input = component.features.moveFeatures.createInput(collection, transform)
        try:
            move_input.defineAsFreeMove(transform)
        except Exception:
            pass
        move = component.features.moveFeatures.add(move_input)
        move.name = "KITCHEN_CREATED_MODEL_Z_OFFSET_{}mm".format(int(dz_mm))
        return {"offsetMm": dz_mm, "movedBodies": collection.count, "failedBodies": failed, "mode": "createdBodiesMove"}
    except Exception as ex:
        return {"offsetMm": dz_mm, "movedBodies": 0, "failedBodies": failed + collection.count, "mode": "createdBodiesMove", "error": str(ex)}


def _delete_kitchen_artifacts_in_component(component, deleted, seen_components, run_prefix=None):
    component_key = id(component)
    if component_key in seen_components:
        return
    seen_components.add(component_key)
    try:
        for index in range(component.bRepBodies.count - 1, -1, -1):
            body = component.bRepBodies.item(index)
            name = str(getattr(body, "name", "") or "")
            if name.startswith("KITCHEN_") and (run_prefix is None or name.startswith(run_prefix)):
                body.deleteMe()
                deleted["bodies"] += 1
    except Exception:
        pass
    try:
        for index in range(component.sketches.count - 1, -1, -1):
            sketch = component.sketches.item(index)
            name = str(getattr(sketch, "name", "") or "")
            if name.startswith("KITCHEN_") and (run_prefix is None or name.startswith(run_prefix)):
                sketch.deleteMe()
                deleted["sketches"] += 1
    except Exception:
        pass
    try:
        for index in range(component.occurrences.count - 1, -1, -1):
            occurrence = component.occurrences.item(index)
            name = str(getattr(occurrence, "name", "") or "")
            component_name = str(getattr(getattr(occurrence, "component", None), "name", "") or "")
            child_component = getattr(occurrence, "component", None)
            if child_component:
                _delete_kitchen_artifacts_in_component(child_component, deleted, seen_components, run_prefix=run_prefix)
            if (
                (name.startswith("KITCHEN_") or component_name.startswith("KITCHEN_")) and
                (run_prefix is None or name.startswith(run_prefix) or component_name.startswith(run_prefix))
            ):
                occurrence.deleteMe()
                deleted["occurrences"] += 1
    except Exception:
        pass


def _delete_previous_kitchen_artifacts(root_comp, run_prefix=None):
    deleted = {"occurrences": 0, "bodies": 0, "sketches": 0}
    _delete_kitchen_artifacts_in_component(root_comp, deleted, set(), run_prefix=run_prefix)
    try:
        for index in range(root_comp.bRepBodies.count - 1, -1, -1):
            body = root_comp.bRepBodies.item(index)
            name = str(getattr(body, "name", "") or "")
            if name.startswith("KITCHEN_") and (run_prefix is None or name.startswith(run_prefix)):
                body.deleteMe()
                deleted["bodies"] += 1
    except Exception:
        pass
    try:
        for index in range(root_comp.sketches.count - 1, -1, -1):
            sketch = root_comp.sketches.item(index)
            name = str(getattr(sketch, "name", "") or "")
            if name.startswith("KITCHEN_") and (run_prefix is None or name.startswith(run_prefix)):
                sketch.deleteMe()
                deleted["sketches"] += 1
    except Exception:
        pass
    return deleted


def _draw_profile_sketch(component, entry):
    plane = entry["plane"]
    bbox = entry["bbox"]
    sketch_plane = _profile_plane_for_sketch(component, plane, bbox)
    if not sketch_plane:
        return None, "Unsupported profile plane: {!r}.".format(plane)
    sketch = component.sketches.add(sketch_plane)
    sketch.name = "KITCHEN_{}_outline".format(sanitize_token(entry["id"], limit=50))
    lines = sketch.sketchCurves.sketchLines
    world_points = [_world_point_from_profile(plane, bbox, point) for point in entry["points"]]
    for idx in range(len(world_points) - 1):
        p0 = world_points[idx]
        p1 = world_points[idx + 1]
        if abs(p0[0] - p1[0]) < 1e-6 and abs(p0[1] - p1[1]) < 1e-6 and abs(p0[2] - p1[2]) < 1e-6:
            continue
        m0 = adsk.core.Point3D.create(mm_to_cm(p0[0]), mm_to_cm(p0[1]), mm_to_cm(p0[2]))
        m1 = adsk.core.Point3D.create(mm_to_cm(p1[0]), mm_to_cm(p1[1]), mm_to_cm(p1[2]))
        s0 = sketch.modelToSketchSpace(m0)
        s1 = sketch.modelToSketchSpace(m1)
        lines.addByTwoPoints(s0, s1)
    profile = _widest_profile(sketch)
    if profile is None:
        return None, "No closed outer profile."
    return profile, None


def _draw_flat_profile_sketch(component, entry):
    staging_z = _flat_staging_z_mm()
    if staging_z <= 1e-6:
        sketch = component.sketches.add(component.xYConstructionPlane)
    else:
        construction = component.constructionPlanes
        plane_input = construction.createInput()
        plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(staging_z)))
        sketch = component.sketches.add(construction.add(plane_input))
    sketch.name = "KITCHEN_{}_flat_outline".format(sanitize_token(entry["id"], limit=45))
    lines = sketch.sketchCurves.sketchLines
    flat_offset = entry.get("flatOffset") or {}
    offset_x = _num(flat_offset.get("x"), 0.0)
    offset_y = _num(flat_offset.get("y"), 0.0)
    for idx in range(len(entry["points"]) - 1):
        p0 = entry["points"][idx]
        p1 = entry["points"][idx + 1]
        if abs(p0[0] - p1[0]) < 1e-6 and abs(p0[1] - p1[1]) < 1e-6:
            continue
        m0 = adsk.core.Point3D.create(mm_to_cm(p0[0] + offset_x), mm_to_cm(p0[1] + offset_y), mm_to_cm(staging_z))
        m1 = adsk.core.Point3D.create(mm_to_cm(p1[0] + offset_x), mm_to_cm(p1[1] + offset_y), mm_to_cm(staging_z))
        lines.addByTwoPoints(sketch.modelToSketchSpace(m0), sketch.modelToSketchSpace(m1))
    profile = _widest_profile(sketch)
    if profile is None:
        return None, "No closed flat outer profile."
    return profile, None


def _add_flat_body(component, entry):
    profile, error = _draw_flat_profile_sketch(component, entry)
    if error:
        return None, error

    thickness = max(0.1, _thickness_mm(entry["bbox"], entry["thicknessAxis"]))
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(thickness)))
    extrude = extrudes.add(ext_input)
    if extrude.bodies.count < 1:
        return None, "Extrude created no body."

    bodies = [extrude.bodies.item(index) for index in range(extrude.bodies.count)]
    body = bodies[0]
    base_name = "KITCHEN_{}_{}".format(entry["kind"], sanitize_token(entry["id"], limit=80))
    for index, created_body in enumerate(bodies):
        created_body.name = base_name if index == 0 else "{}_part{}".format(base_name, index + 1)
        try:
            created_body.attributes.add(ATTRIBUTE_GROUP, "module", "kitchen")
            created_body.attributes.add(ATTRIBUTE_GROUP, "panelKind", entry["kind"])
            created_body.attributes.add(ATTRIBUTE_GROUP, "panelId", entry["id"])
            created_body.attributes.add(ATTRIBUTE_GROUP, "panelType", entry["type"])
            created_body.attributes.add(ATTRIBUTE_GROUP, "profileSource", "flatXYPreview")
        except Exception:
            pass
    entry["fusionProfileSource"] = "flatXYPreview"
    entry["createdFlatBodies"] = bodies
    return body, None


def _add_oriented_panel_body(component, entry):
    """Create a panel already in its assembly plane/pose (used for YZ V-panels).

    Fusion moveFeatures with YZ rotation matrices are unreliable; drawing on
    the YZ construction plane at bbox x0 avoids flat staging + rigid move.
    """
    profile, error = _draw_profile_sketch(component, entry)
    if error:
        return None, error

    thickness = max(0.1, _thickness_mm(entry["bbox"], entry["thicknessAxis"]))
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(thickness)))
    extrude = extrudes.add(ext_input)
    if extrude.bodies.count < 1:
        return None, "Extrude created no body."

    bodies = [extrude.bodies.item(index) for index in range(extrude.bodies.count)]
    body = bodies[0]
    base_name = "KITCHEN_{}_{}".format(entry["kind"], sanitize_token(entry["id"], limit=80))
    for index, created_body in enumerate(bodies):
        created_body.name = base_name if index == 0 else "{}_part{}".format(base_name, index + 1)
        try:
            created_body.attributes.add(ATTRIBUTE_GROUP, "module", "kitchen")
            created_body.attributes.add(ATTRIBUTE_GROUP, "panelKind", entry["kind"])
            created_body.attributes.add(ATTRIBUTE_GROUP, "panelId", entry["id"])
            created_body.attributes.add(ATTRIBUTE_GROUP, "panelType", entry["type"])
            created_body.attributes.add(ATTRIBUTE_GROUP, "profileSource", "orientedAssemblyProfile")
        except Exception:
            pass
    entry["fusionProfileSource"] = "orientedAssemblyProfile"
    entry["fusionTransformSource"] = "orientedAssemblyDirect"
    entry["createdFlatBodies"] = bodies
    return body, None


def _cut_panel_vectors_assembly(component, body, entry, cutouts):
    audits = []
    for cutout in cutouts or []:
        audit = _cut_panel_cutout(component, body, entry, cutout)
        audit["panelId"] = entry["id"]
        audits.append(audit)
    return audits


def _flat_to_target_matrix(entry):
    """Rigid flat→assembly transform.

    Panels are cut in a dispersed flat layout (_apply_flat_layout).  The matrix
    must cancel flatOffset and rotate into cabinet pose — it must NOT also
    subtract bbox x0/y0/z0 on top of flatOffset, because flatOffset already
    positions the profile min corner at (cursor_x, cursor_y) and profile
    coordinates are absolute cabinet mm values.
    """
    plane = entry["plane"]
    bbox = entry["bbox"]
    flat_offset = entry.get("flatOffset") or {}
    offset_x = _num(flat_offset.get("x"), 0.0)
    offset_y = _num(flat_offset.get("y"), 0.0)
    matrix = adsk.core.Matrix3D.create()
    if plane == "XY":
        y_offset = -16.0 if entry.get("type") == "T2" else 0.0
        matrix.translation = adsk.core.Vector3D.create(
            mm_to_cm(-offset_x),
            mm_to_cm(y_offset - offset_y),
            mm_to_cm(bbox["z0"]),
        )
        return matrix
    if plane == "XZ":
        matrix.setCell(0, 0, 1)
        matrix.setCell(0, 1, 0)
        matrix.setCell(0, 2, 0)
        matrix.setCell(0, 3, mm_to_cm(-offset_x))
        matrix.setCell(1, 0, 0)
        matrix.setCell(1, 1, 0)
        matrix.setCell(1, 2, -1)
        matrix.setCell(1, 3, mm_to_cm(bbox["y1"]))
        matrix.setCell(2, 0, 0)
        matrix.setCell(2, 1, 1)
        matrix.setCell(2, 2, 0)
        matrix.setCell(2, 3, mm_to_cm(-offset_y))
        return matrix
    if plane == "YZ":
        matrix.setCell(0, 0, 0)
        matrix.setCell(0, 1, 0)
        matrix.setCell(0, 2, 1)
        matrix.setCell(0, 3, mm_to_cm(bbox["x0"]))
        matrix.setCell(1, 0, 1)
        matrix.setCell(1, 1, 0)
        matrix.setCell(1, 2, 0)
        matrix.setCell(1, 3, mm_to_cm(-offset_x))
        matrix.setCell(2, 0, 0)
        matrix.setCell(2, 1, 1)
        matrix.setCell(2, 2, 0)
        matrix.setCell(2, 3, mm_to_cm(-offset_y))
        return matrix
    return None


def _move_bodies_to_target(component, bodies, matrix):
    if matrix is None:
        return "No target transform."
    try:
        collection = adsk.core.ObjectCollection.create()
        for body in bodies:
            collection.add(body)
        if collection.count < 1:
            return "No flat bodies to move."
        move_input = component.features.moveFeatures.createInput(collection, matrix)
        # REQUIRED: without an explicit free-move definition the move feature
        # can be created successfully yet apply no motion when the body lives
        # in a per-panel child component (every other working move path in the
        # plugin calls defineAsFreeMove).
        try:
            move_input.defineAsFreeMove(matrix)
        except Exception:
            pass
        component.features.moveFeatures.add(move_input)
        return None
    except Exception as ex:
        return "Move flat body to target failed: {}".format(ex)


def _add_assembly_body(component, entry):
    return _add_flat_body(component, entry)


def _body_bbox_mm(body):
    try:
        bb = body.boundingBox
        return {
            "min": [round(bb.minPoint.x * 10.0, 1), round(bb.minPoint.y * 10.0, 1), round(bb.minPoint.z * 10.0, 1)],
            "max": [round(bb.maxPoint.x * 10.0, 1), round(bb.maxPoint.y * 10.0, 1), round(bb.maxPoint.z * 10.0, 1)],
        }
    except Exception:
        return None


def _expected_target_bbox_mm(entry):
    """Target panel bbox in assembly-local coordinates (no zone-origin offset)."""
    try:
        bbox = entry["bbox"]
        return {
            "min": [round(float(bbox["x0"]), 1), round(float(bbox["y0"]), 1), round(float(bbox["z0"]), 1)],
            "max": [round(float(bbox["x1"]), 1), round(float(bbox["y1"]), 1), round(float(bbox["z1"]), 1)],
        }
    except Exception:
        return None


def _occurrence_bbox_mm(body, occurrence):
    """Body bbox in the parent-assembly frame: local bbox corners mapped
    through the occurrence transform (body.boundingBox alone is local and
    ignores the occurrence placement)."""
    try:
        transform = occurrence.transform
        bb = body.boundingBox
        xs, ys, zs = [], [], []
        for x in (bb.minPoint.x, bb.maxPoint.x):
            for y in (bb.minPoint.y, bb.maxPoint.y):
                for z in (bb.minPoint.z, bb.maxPoint.z):
                    point = adsk.core.Point3D.create(x, y, z)
                    point.transformBy(transform)
                    xs.append(point.x)
                    ys.append(point.y)
                    zs.append(point.z)
        return {
            "min": [round(min(xs) * 10.0, 1), round(min(ys) * 10.0, 1), round(min(zs) * 10.0, 1)],
            "max": [round(max(xs) * 10.0, 1), round(max(ys) * 10.0, 1), round(max(zs) * 10.0, 1)],
        }
    except Exception:
        return None


def _apply_occurrence_transform(occurrence, matrix):
    """Place a per-panel child occurrence with an exact rigid transform.

    Body-level moveFeatures silently apply no motion inside per-panel child
    components; the occurrence transform is exact for all planes (incl. YZ).
    A design snapshot is captured at the end of the run so parametric
    recomputes keep the position.
    """
    if matrix is None:
        return "No target transform."
    try:
        occurrence.transform = matrix
        return None
    except Exception as ex:
        return "Occurrence transform failed: {}".format(ex)


def _move_entry_flat_bodies_to_target(component, entry, body):
    """Move flat-staged bodies into cabinet pose via moveFeatures (original path)."""
    if entry.get("fusionTransformSource") == "orientedAssemblyDirect":
        return None
    flat_bodies = entry.get("createdFlatBodies") or [body]
    move_error = _move_bodies_to_target(component, flat_bodies, _flat_to_target_matrix(entry))
    if move_error:
        return move_error
    entry["fusionProfileSource"] = "flatXYPreview"
    entry["fusionTransformSource"] = "flatXYBodyRigidTransform"
    try:
        for flat_body in flat_bodies:
            flat_body.attributes.add(ATTRIBUTE_GROUP, "profileSource", "flatXYBodyRigidTransform")
    except Exception:
        pass
    return None


def _cutout_world_points(plane, bbox, cutout):
    a0 = _num(cutout.get("x0"))
    a1 = _num(cutout.get("x1"))
    b0 = _num(cutout.get("y0"))
    b1 = _num(cutout.get("y1"))
    if None in (a0, a1, b0, b1):
        return None
    a0, a1 = min(a0, a1), max(a0, a1)
    b0, b1 = min(b0, b1), max(b0, b1)
    face = assembly_cut_face(plane, bbox, cutout)
    origin_mm = face.get("originMm")
    if origin_mm is None:
        return None
    if plane == "XY":
        return (
            adsk.core.Point3D.create(mm_to_cm(a0), mm_to_cm(b0), mm_to_cm(origin_mm)),
            adsk.core.Point3D.create(mm_to_cm(a1), mm_to_cm(b1), mm_to_cm(origin_mm)),
        )
    if plane == "XZ":
        return (
            adsk.core.Point3D.create(mm_to_cm(a0), mm_to_cm(origin_mm), mm_to_cm(b0)),
            adsk.core.Point3D.create(mm_to_cm(a1), mm_to_cm(origin_mm), mm_to_cm(b1)),
        )
    return (
        adsk.core.Point3D.create(mm_to_cm(origin_mm), mm_to_cm(a0), mm_to_cm(b0)),
        adsk.core.Point3D.create(mm_to_cm(origin_mm), mm_to_cm(a1), mm_to_cm(b1)),
    )


def _cut_panel_cutout(component, body, entry, cutout):
    plane = entry["plane"]
    bbox = entry["bbox"]
    face = assembly_cut_face(plane, bbox, cutout)
    points = _cutout_world_points(plane, bbox, cutout)
    if points is None:
        return {"id": cutout.get("id"), "status": "skipped", "reason": "invalid cutout bounds"}

    thickness = max(0.1, _thickness_mm(bbox, entry["thicknessAxis"]))
    is_half_groove = cutout.get("kind") == "slot" and cutout.get("slotType") == "half"
    half_groove_depth = _num(cutout.get("grooveDepth"), None)
    half_groove_depth = max(0.1, half_groove_depth) if half_groove_depth is not None else max(0.1, thickness / 2.0 - 0.5)
    cut_depth = min(thickness, half_groove_depth) if is_half_groove else thickness

    cut_plane = _cut_face_plane_for_sketch(component, plane, bbox, cutout=cutout)
    if not cut_plane:
        return {"id": cutout.get("id"), "status": "failed", "reason": "unsupported cut plane"}

    sketch = component.sketches.add(cut_plane)
    sketch.name = "KITCHEN_{}_{}".format(
        sanitize_token(entry["id"], limit=35),
        sanitize_token(cutout.get("id") or cutout.get("sourceId") or "cutout", limit=35),
    )
    p0, p1 = points
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(
        sketch.modelToSketchSpace(p0),
        sketch.modelToSketchSpace(p1),
    )
    profile = _largest_profile(sketch)
    if profile is None:
        return {"id": cutout.get("id"), "status": "failed", "reason": "no closed cut profile"}

    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
    extrude_sign = int(face.get("extrudeSign") or -1)
    ext_input.setDistanceExtent(
        False,
        adsk.core.ValueInput.createByReal(mm_to_cm(cut_depth) * extrude_sign),
    )
    try:
        participants = adsk.core.ObjectCollection.create()
        for participant_body in entry.get("createdFlatBodies") or [body]:
            participants.add(participant_body)
        ext_input.participantBodies = participants
    except Exception:
        pass
    extrudes.add(ext_input)
    return {
        "id": cutout.get("id"),
        "sourceId": cutout.get("sourceId"),
        "kind": "groove" if is_half_groove else cutout.get("kind"),
        "slotType": cutout.get("slotType"),
        "side": face.get("side"),
        "cutFace": face.get("side") if is_half_groove else "through",
        "cutOriginMm": face.get("originMm"),
        "extrudeSign": extrude_sign,
        "status": "created",
        "depth": cut_depth,
    }


def _flat_cut_sketch(component, thickness, side):
    base_z = _flat_staging_z_mm()
    if side == "right":
        construction = component.constructionPlanes
        plane_input = construction.createInput()
        plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(base_z + thickness)))
        return component.sketches.add(construction.add(plane_input)), base_z + thickness, -1
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(base_z)))
    return component.sketches.add(construction.add(plane_input)), base_z, 1


def _cut_panel_vectors_batch(component, body, entry, cutouts, slot_type, label, cut_side=None):
    grooves = [
        cutout for cutout in cutouts
        if cutout.get("kind") == "slot" and
        cutout.get("slotType") == slot_type and
        (cut_side is None or cutout.get("side") == cut_side)
    ]
    if not grooves:
        return []
    bbox = entry["bbox"]
    thickness = max(0.1, _thickness_mm(bbox, entry["thicknessAxis"]))
    if slot_type == "half":
        requested_depths = [_num(cutout.get("grooveDepth")) for cutout in grooves]
        requested_depths = [depth for depth in requested_depths if depth is not None and depth > 0]
        cut_depth = min(thickness, max(requested_depths) if requested_depths else max(0.1, thickness / 2.0 - 0.5))
    else:
        cut_depth = thickness
    flat_offset = entry.get("flatOffset") or {}
    offset_x = _num(flat_offset.get("x"), 0.0)
    offset_y = _num(flat_offset.get("y"), 0.0)
    active_side = cut_side if slot_type == "half" else "left"
    sketch, sketch_z, cut_direction = _flat_cut_sketch(component, thickness, active_side)
    sketch.name = "KITCHEN_{}_{}".format(sanitize_token(entry["id"], limit=45), label)
    valid_grooves = []
    for cutout in grooves:
        a0 = _num(cutout.get("x0"))
        a1 = _num(cutout.get("x1"))
        b0 = _num(cutout.get("y0"))
        b1 = _num(cutout.get("y1"))
        if None in (a0, a1, b0, b1):
            valid_grooves.append((cutout, "invalid"))
            continue
        a0, a1 = min(a0, a1), max(a0, a1)
        b0, b1 = min(b0, b1), max(b0, b1)
        p0 = adsk.core.Point3D.create(mm_to_cm(a0 + offset_x), mm_to_cm(b0 + offset_y), mm_to_cm(sketch_z))
        p1 = adsk.core.Point3D.create(mm_to_cm(a1 + offset_x), mm_to_cm(b1 + offset_y), mm_to_cm(sketch_z))
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(
            sketch.modelToSketchSpace(p0),
            sketch.modelToSketchSpace(p1),
        )
        valid_grooves.append((cutout, "drawn"))

    profiles = _all_profiles(sketch)
    if profiles is None:
        return [{"id": cutout.get("id"), "status": "failed", "reason": "no closed groove profiles"} for cutout, _status in valid_grooves]
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(cut_depth) * cut_direction))
    try:
        participants = adsk.core.ObjectCollection.create()
        participants.add(body)
        ext_input.participantBodies = participants
    except Exception:
        pass
    extrudes.add(ext_input)
    return [
        {
            "id": cutout.get("id"),
            "sourceId": cutout.get("sourceId"),
            "kind": "groove" if slot_type == "half" else "slot",
            "slotType": cutout.get("slotType"),
            "side": cutout.get("side"),
            "cutFace": active_side if slot_type == "half" else "through",
            "status": "created" if status == "drawn" else "skipped",
            "depth": cut_depth,
            **({"reason": "invalid cutout bounds"} if status != "drawn" else {}),
        }
        for cutout, status in valid_grooves
    ]


def _cut_panel_notches_batch(component, body, entry, cutouts):
    notches = [cutout for cutout in cutouts if cutout.get("kind") == "notch"]
    if not notches:
        return []
    bbox = entry["bbox"]
    thickness = max(0.1, _thickness_mm(bbox, entry["thicknessAxis"]))
    flat_offset = entry.get("flatOffset") or {}
    offset_x = _num(flat_offset.get("x"), 0.0)
    offset_y = _num(flat_offset.get("y"), 0.0)
    staging_z = _flat_staging_z_mm()
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    if staging_z <= 1e-6:
        sketch = component.sketches.add(component.xYConstructionPlane)
    else:
        plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(staging_z)))
        sketch = component.sketches.add(construction.add(plane_input))
    sketch.name = "KITCHEN_{}_notches".format(sanitize_token(entry["id"], limit=45))
    valid = []
    for cutout in notches:
        a0 = _num(cutout.get("x0"))
        a1 = _num(cutout.get("x1"))
        b0 = _num(cutout.get("y0"))
        b1 = _num(cutout.get("y1"))
        if None in (a0, a1, b0, b1):
            valid.append((cutout, "invalid"))
            continue
        a0, a1 = min(a0, a1), max(a0, a1)
        b0, b1 = min(b0, b1), max(b0, b1)
        p0 = adsk.core.Point3D.create(mm_to_cm(a0 + offset_x), mm_to_cm(b0 + offset_y), mm_to_cm(staging_z))
        p1 = adsk.core.Point3D.create(mm_to_cm(a1 + offset_x), mm_to_cm(b1 + offset_y), mm_to_cm(staging_z))
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(
            sketch.modelToSketchSpace(p0),
            sketch.modelToSketchSpace(p1),
        )
        valid.append((cutout, "drawn"))
    profiles = _all_profiles(sketch)
    if profiles is None:
        return [{"id": cutout.get("id"), "status": "failed", "reason": "no closed notch profiles"} for cutout, _status in valid]
    ext_input = component.features.extrudeFeatures.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(thickness)))
    try:
        participants = adsk.core.ObjectCollection.create()
        participants.add(body)
        ext_input.participantBodies = participants
    except Exception:
        pass
    component.features.extrudeFeatures.add(ext_input)
    return [
        {
            "id": cutout.get("id"),
            "sourceId": cutout.get("sourceId"),
            "kind": "notch",
            "status": "created" if status == "drawn" else "skipped",
            "depth": thickness,
            **({"reason": "invalid notch bounds"} if status != "drawn" else {}),
        }
        for cutout, status in valid
    ]


def _cut_panel_grooves_batch(component, body, entry, cutouts):
    audits = []
    for side in ("left", "right"):
        audits.extend(_cut_panel_vectors_batch(component, body, entry, cutouts, "half", "half_grooves_{}".format(side), cut_side=side))
    missing_side = [cutout for cutout in cutouts if cutout.get("kind") == "slot" and cutout.get("slotType") == "half" and cutout.get("side") not in ("left", "right")]
    if missing_side:
        audits.extend(_cut_panel_vectors_batch(component, body, entry, missing_side, "half", "half_grooves_unknown", cut_side=None))
    return audits


def _cut_panel_through_batch(component, body, entry, cutouts):
    return _cut_panel_vectors_batch(component, body, entry, cutouts, "through", "through_slots")


def _flat_staging_sketch(component, name):
    """Sketch on the flat staging plane (z=0 by default)."""
    staging_z = _flat_staging_z_mm()
    if staging_z <= 1e-6:
        sketch = component.sketches.add(component.xYConstructionPlane)
    else:
        construction = component.constructionPlanes
        plane_input = construction.createInput()
        plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(staging_z)))
        sketch = component.sketches.add(construction.add(plane_input))
    sketch.name = name
    return sketch, staging_z


def _cut_front_panel_lock_cutouts(component, body, entry):
    cutouts = entry.get("lockCutouts") or []
    if not cutouts:
        return []
    thickness = max(0.1, _thickness_mm(entry["bbox"], entry["thicknessAxis"]))
    flat_offset = entry.get("flatOffset") or {}
    offset_x = _num(flat_offset.get("x"), 0.0)
    offset_y = _num(flat_offset.get("y"), 0.0)
    sketch, staging_z = _flat_staging_sketch(
        component, "KITCHEN_{}_lock_cutouts".format(sanitize_token(entry["id"], limit=45))
    )
    lines = sketch.sketchCurves.sketchLines
    arcs = sketch.sketchCurves.sketchArcs
    audits = []
    for cutout in cutouts:
        x0 = _num(cutout.get("x0"), None)
        x1 = _num(cutout.get("x1"), None)
        z0 = _num(cutout.get("z0"), None)
        z1 = _num(cutout.get("z1"), None)
        if None in (x0, x1, z0, z1) or x1 <= x0 or z1 <= z0:
            audits.append({"id": cutout.get("id"), "kind": "lock_cutout", "status": "skipped", "reason": "invalid lock cutout bounds"})
            continue
        radius = min((x1 - x0) / 2.0, (z1 - z0) / 2.0)
        cy = (z0 + z1) / 2.0
        left_center = adsk.core.Point3D.create(mm_to_cm(x0 + radius + offset_x), mm_to_cm(cy + offset_y), mm_to_cm(staging_z))
        right_center = adsk.core.Point3D.create(mm_to_cm(x1 - radius + offset_x), mm_to_cm(cy + offset_y), mm_to_cm(staging_z))
        top_left = adsk.core.Point3D.create(mm_to_cm(x0 + radius + offset_x), mm_to_cm(z1 + offset_y), mm_to_cm(staging_z))
        top_right = adsk.core.Point3D.create(mm_to_cm(x1 - radius + offset_x), mm_to_cm(z1 + offset_y), mm_to_cm(staging_z))
        bottom_left = adsk.core.Point3D.create(mm_to_cm(x0 + radius + offset_x), mm_to_cm(z0 + offset_y), mm_to_cm(staging_z))
        bottom_right = adsk.core.Point3D.create(mm_to_cm(x1 - radius + offset_x), mm_to_cm(z0 + offset_y), mm_to_cm(staging_z))
        lines.addByTwoPoints(sketch.modelToSketchSpace(top_left), sketch.modelToSketchSpace(top_right))
        arcs.addByCenterStartSweep(sketch.modelToSketchSpace(right_center), sketch.modelToSketchSpace(top_right), -3.141592653589793)
        lines.addByTwoPoints(sketch.modelToSketchSpace(bottom_right), sketch.modelToSketchSpace(bottom_left))
        arcs.addByCenterStartSweep(sketch.modelToSketchSpace(left_center), sketch.modelToSketchSpace(bottom_left), -3.141592653589793)
        audits.append({"id": cutout.get("id"), "kind": "lock_cutout", "status": "drawn", "shape": cutout.get("shape") or "rounded_slot"})
    profiles = _all_profiles(sketch)
    if profiles is None:
        return [{**audit, "status": "failed", "reason": "no closed lock cutout profiles"} for audit in audits]
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(thickness)))
    try:
        participants = adsk.core.ObjectCollection.create()
        for participant_body in entry.get("createdFlatBodies") or [body]:
            participants.add(participant_body)
        ext_input.participantBodies = participants
    except Exception:
        pass
    extrudes.add(ext_input)
    return [{**audit, "status": "created" if audit.get("status") == "drawn" else audit.get("status"), "depth": thickness} for audit in audits]


def _cut_front_panel_hinge_cups(component, body, entry):
    holes = entry.get("hingeHoles") or []
    if not holes:
        return []
    thickness = max(0.1, _thickness_mm(entry["bbox"], entry["thicknessAxis"]))
    flat_offset = entry.get("flatOffset") or {}
    offset_x = _num(flat_offset.get("x"), 0.0)
    offset_y = _num(flat_offset.get("y"), 0.0)
    sketch, staging_z = _flat_staging_sketch(
        component, "KITCHEN_{}_hinge_cups".format(sanitize_token(entry["id"], limit=45))
    )
    circles = sketch.sketchCurves.sketchCircles
    audits = []
    for hole in holes:
        center_x = _num(hole.get("centerX"), None)
        center_z = _num(hole.get("centerZ"), None)
        diameter = _num(hole.get("diameter"), 35.0)
        depth = min(thickness, max(0.1, _num(hole.get("depth"), 12.5)))
        if center_x is None or center_z is None or diameter <= 0:
            audits.append({"id": hole.get("id"), "kind": "hinge_cup", "status": "skipped", "reason": "invalid hinge cup"})
            continue
        center = adsk.core.Point3D.create(mm_to_cm(center_x + offset_x), mm_to_cm(center_z + offset_y), mm_to_cm(staging_z))
        circles.addByCenterRadius(sketch.modelToSketchSpace(center), mm_to_cm(diameter / 2.0))
        audits.append({"id": hole.get("id"), "kind": "hinge_cup", "status": "drawn", "diameter": diameter, "depth": depth})
    profiles = _all_profiles(sketch)
    if profiles is None:
        return [{**audit, "status": "failed", "reason": "no closed hinge cup profiles"} for audit in audits]
    max_depth = max([audit.get("depth", 0.1) for audit in audits if audit.get("status") == "drawn"] or [0.1])
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(max_depth)))
    try:
        participants = adsk.core.ObjectCollection.create()
        for participant_body in entry.get("createdFlatBodies") or [body]:
            participants.add(participant_body)
        ext_input.participantBodies = participants
    except Exception:
        pass
    extrudes.add(ext_input)
    return [{**audit, "status": "created" if audit.get("status") == "drawn" else audit.get("status")} for audit in audits]


def _cutouts_for_entry(entry):
    return list((entry.get("body") or {}).get("cutouts") or [])


def _visible_cutouts_for_fast_assembly(entry):
    return [cutout for cutout in _cutouts_for_entry(entry) if cutout.get("kind") == "notch"]


def _auto_origin(root, origin_x_mm, origin_y_mm):
    """None = auto: use the generation-zone centre from the saved work zones.

    Reads the saved layout attribute directly (no work_zones import) to stay
    immune to Fusion's stale module cache.

    Returns (x, y, active): active is True when an explicit origin was given
    or a work-zone layout exists — in that case the assembly is dropped to
    z=0 on the generation plane instead of floating at the legacy staging
    height.
    """
    has_work_zones = False
    try:
        attr = root.attributes.itemByName("UnifiedCabinet", "workZoneLayout") if root else None
        if attr and attr.value:
            layout = json.loads(attr.value)
            rect = layout.get("generation") if isinstance(layout, dict) else None
            if isinstance(rect, dict):
                has_work_zones = True
                if origin_x_mm is None and origin_y_mm is None:
                    return (
                        (float(rect["x0"]) + float(rect["x1"])) / 2.0,
                        (float(rect["y0"]) + float(rect["y1"])) / 2.0,
                        True,
                    )
    except Exception:
        pass
    explicit = origin_x_mm is not None or origin_y_mm is not None
    origin_active = bool(explicit or has_work_zones)
    return float(origin_x_mm or 0.0), float(origin_y_mm or 0.0), origin_active


def _kitchen_spawn_footprint_mm(entries):
    """Assembly-local XY footprint for spawn avoidance (min_x, max_x, min_y, max_y)."""
    rects = []
    for entry in entries or []:
        bbox = entry.get("bbox") if isinstance(entry, dict) else None
        if not isinstance(bbox, dict):
            continue
        try:
            x0 = float(bbox["x0"])
            x1 = float(bbox["x1"])
            y0 = float(bbox["y0"])
            y1 = float(bbox["y1"])
        except (TypeError, ValueError, KeyError):
            continue
        if x1 <= x0 or y1 <= y0:
            continue
        rects.append((x0, x1, y0, y1))
    if not rects:
        return None
    return (
        min(r[0] for r in rects),
        max(r[1] for r in rects),
        min(r[2] for r in rects),
        max(r[3] for r in rects),
    )


def _capture_position_snapshot(root_comp):
    """Snapshot occurrence positions so parametric recomputes keep them."""
    try:
        design = root_comp.parentDesign
        if design and design.snapshots and design.snapshots.hasPendingSnapshot:
            design.snapshots.add()
    except Exception:
        pass


def create_assembly_panel_bodies_from_kitchen_result(fusion, result, run_label=None, create_cutouts=False, mode="flat", add_as_new=True, component_name=None, origin_x_mm=None, origin_y_mm=None):
    root = fusion.get_root_component() if fusion else None
    if root is None:
        return {
            "createdBodies": 0,
            "createdPanelIds": [],
            "skippedPanels": [],
            "cutouts": [],
            "warnings": [],
            "errors": ["No active Fusion design/root component."],
            "runLabel": run_label,
            "assemblyComponentName": None,
            "mode": mode,
            "adapterRevision": ADAPTER_REVISION,
        }

    resolved_run_label = str(run_label or int(time.time() * 1000))
    run_component_prefix = "KITCHEN_{}".format(sanitize_token(resolved_run_label, fallback="assembly", limit=60))
    deleted_previous = _delete_previous_kitchen_artifacts(root, run_prefix=run_component_prefix if add_as_new else None)
    origin_x_mm, origin_y_mm, origin_active = _auto_origin(root, origin_x_mm, origin_y_mm)
    entries = _panel_entries(result)
    avoidance_info = {"shifted": False, "slots": 0}
    footprint = _kitchen_spawn_footprint_mm(entries)
    if origin_active:
        origin_x_mm, origin_y_mm, avoidance_info = avoid_existing_at_origin(
            root, origin_x_mm, origin_y_mm, footprint
        )
        if avoidance_info.get("shifted"):
            warnings_pre = []
            warnings_pre.append(
                "Generation spot was occupied; kitchen assembly shifted +X by {:.0f} mm (slot {}).".format(
                    avoidance_info.get("shiftXMm", 0.0), avoidance_info.get("slots", 0)
                )
            )
        else:
            warnings_pre = []
    else:
        warnings_pre = []
    # Generation zone: assembly sits on z=0.  Legacy (no zone): lift to z=10000.
    origin_z_mm = 0.0 if origin_active else MODEL_Z_OFFSET_MM
    component, assembly_name, container_warning = _new_assembly_component(
        root, resolved_run_label, component_name=component_name,
        origin_x_mm=origin_x_mm, origin_y_mm=origin_y_mm, origin_z_mm=origin_z_mm,
    )
    # Always cut in a dispersed staging layout. Some Fusion cut operations can
    # otherwise reach neighboring bodies when cabinet panels overlap in assembly.
    _apply_flat_layout(entries)
    created_ids = []
    skipped = []
    cutout_audit = []
    errors = []
    warnings = list(warnings_pre)
    created_bodies = []
    placement_debug = {
        "adapterBuild": ADAPTER_REVISION,
        "module": "kitchen",
        "mode": mode,
        "resolvedOrigin": [origin_x_mm, origin_y_mm, origin_z_mm],
        "originActive": bool(origin_active),
        "avoidance": avoidance_info,
        "spawnFootprintMm": (
            {"minX": footprint[0], "maxX": footprint[1], "minY": footprint[2], "maxY": footprint[3]}
            if footprint else None
        ),
        "assemblyComponentName": None,
        "panels": [],
    }
    if container_warning:
        warnings.append(container_warning)
    declarations = result.get("relationshipDeclarations") if isinstance(result, dict) else None
    if isinstance(declarations, list) and declarations and component is not root:
        try:
            component.attributes.add(
                ATTRIBUTE_GROUP,
                "relationshipDeclarations",
                json.dumps(declarations, ensure_ascii=False, separators=(",", ":")),
            )
            placement_debug["relationshipDeclarationCount"] = len(declarations)
        except Exception as ex:
            warnings.append("Could not write relationshipDeclarations on assembly: {}".format(ex))

    for entry in entries:
        try:
            # One panel = one child component inside the assembly component.
            # flat_transform placement: YZ panels are built directly in pose
            # (occurrence stays at identity); XY/XZ panels are built flat, cut,
            # then placed by setting the occurrence transform (moveFeatures are
            # unreliable inside child components).
            panel_component = component
            panel_occurrence = None
            if component is not root:
                try:
                    panel_component, panel_occurrence = _new_panel_component(component, entry["id"])
                except Exception as ex:
                    warnings.append("Could not create panel component for {}: {}".format(entry["id"], ex))
                    panel_component = component
                    panel_occurrence = None
            use_direct_assembly = mode == "flat_transform" and entry.get("plane") == "YZ"
            if use_direct_assembly:
                body, error = _add_oriented_panel_body(panel_component, entry)
            elif mode == "flat_transform":
                body, error = _add_flat_body(panel_component, entry)
            else:
                body, error = _add_assembly_body(panel_component, entry)
            if error or body is None:
                skipped.append({"id": entry["id"], "reason": error or "unknown body creation failure"})
                continue
            created_bodies.extend(entry.get("createdFlatBodies") or [body])
            created_ids.append(entry["id"])
            if create_cutouts:
                try:
                    if use_direct_assembly:
                        assembly_vectors = (
                            list(entry.get("notchVectors") or [])
                            + list(entry.get("throughVectors") or [])
                            + list(entry.get("halfGrooveVectors") or [])
                        )
                        cutout_audit.extend(_cut_panel_vectors_assembly(panel_component, body, entry, assembly_vectors))
                    else:
                        for audit in _cut_panel_notches_batch(panel_component, body, entry, entry.get("notchVectors") or []):
                            audit["panelId"] = entry["id"]
                            cutout_audit.append(audit)
                        for audit in _cut_panel_through_batch(panel_component, body, entry, entry.get("throughVectors") or []):
                            audit["panelId"] = entry["id"]
                            cutout_audit.append(audit)
                        for audit in _cut_panel_grooves_batch(panel_component, body, entry, entry.get("halfGrooveVectors") or []):
                            audit["panelId"] = entry["id"]
                            cutout_audit.append(audit)
                        for audit in _cut_front_panel_lock_cutouts(panel_component, body, entry):
                            audit["panelId"] = entry["id"]
                            cutout_audit.append(audit)
                        for audit in _cut_front_panel_hinge_cups(panel_component, body, entry):
                            audit["panelId"] = entry["id"]
                            cutout_audit.append(audit)
                except Exception as ex:
                    cutout_audit.append({
                        "panelId": entry["id"],
                        "id": "panel_vectors",
                        "status": "failed",
                        "reason": str(ex),
                    })
            if mode == "flat_transform":
                # Placement is deferred: setting occurrence transforms while
                # later panels still create features lets the recompute revert
                # un-snapshotted positions back to identity (panels lie flat).
                entry["_body"] = body
                entry["_occurrence"] = panel_occurrence
            elif entry.get("fusionProfileSource"):
                cutout_audit.append({
                    "panelId": entry["id"],
                    "id": "outer_profile",
                    "kind": "outer_profile",
                    "status": "created",
                    "profileSource": entry.get("fusionProfileSource"),
                    "transformSource": entry.get("fusionTransformSource"),
                    "plane": entry.get("plane"),
                    "thicknessAxis": entry.get("thicknessAxis"),
                    "bbox": entry.get("bbox"),
                    "flatOffset": entry.get("flatOffset"),
                })
        except Exception as ex:
            errors.append("Panel {} failed: {}".format(entry["id"], ex))

    if mode == "flat_transform":
        # Phase 2: all features exist now — place every panel, then snapshot
        # IMMEDIATELY so nothing recomputes the positions away.
        placed = []
        for entry in entries:
            body = entry.pop("_body", None)
            occurrence = entry.pop("_occurrence", None)
            if body is None:
                continue
            try:
                if entry.get("fusionTransformSource") == "orientedAssemblyDirect":
                    move_error = None
                elif occurrence is not None:
                    move_error = _apply_occurrence_transform(occurrence, _flat_to_target_matrix(entry))
                    if move_error is None:
                        entry["fusionTransformSource"] = "occurrenceRigidTransform"
                else:
                    move_error = _move_entry_flat_bodies_to_target(component, entry, body)
            except Exception as ex:
                move_error = "Placement failed: {}".format(ex)
            placed.append((entry, body, occurrence, move_error))
        _capture_position_snapshot(root)

        for entry, body, occurrence, move_error in placed:
            panel_debug = {
                "id": entry["id"],
                "plane": entry.get("plane"),
                "transformSource": entry.get("fusionTransformSource"),
                "hasOccurrence": occurrence is not None,
                "flatOffset": entry.get("flatOffset"),
                "bbox": entry.get("bbox"),
                "moveError": move_error,
            }
            if move_error:
                placement_debug["panels"].append(panel_debug)
                skipped.append({"id": entry["id"], "reason": move_error})
                continue
            audit_row = {
                "panelId": entry["id"],
                "id": "outer_profile",
                "kind": "outer_profile",
                "status": "created",
                "profileSource": entry.get("fusionProfileSource"),
                "transformSource": entry.get("fusionTransformSource"),
                "plane": entry.get("plane"),
                "thicknessAxis": entry.get("thicknessAxis"),
                "bbox": entry.get("bbox"),
                "flatOffset": entry.get("flatOffset"),
            }
            # Ground-truth position audit (after snapshot).  Occurrence-placed
            # panels: local bbox is still the flat pose, so map corners
            # through the occurrence transform.
            if entry.get("fusionTransformSource") == "occurrenceRigidTransform" and occurrence is not None:
                final_bbox = _occurrence_bbox_mm(body, occurrence)
            else:
                final_bbox = _body_bbox_mm(body)
            expected_bbox = _expected_target_bbox_mm(entry)
            audit_row["finalBBoxMm"] = final_bbox
            audit_row["expectedBBoxMm"] = expected_bbox
            position_ok = None
            if final_bbox and expected_bbox:
                deltas = [
                    abs(final_bbox["min"][axis] - expected_bbox["min"][axis])
                    for axis in range(3)
                ]
                position_ok = all(delta <= 1.0 for delta in deltas)
                audit_row["positionDeltaMm"] = [round(d, 1) for d in deltas]
            audit_row["positionOk"] = position_ok
            if position_ok is False:
                warnings.append(
                    "Panel {} landed off-target by {} mm (min-corner delta).".format(
                        entry["id"], audit_row["positionDeltaMm"]
                    )
                )
            panel_debug["positionOk"] = position_ok
            panel_debug["positionDeltaMm"] = audit_row.get("positionDeltaMm")
            placement_debug["panels"].append(panel_debug)
            cutout_audit.append(audit_row)

    if mode == "flat_transform":
        placement_debug["assemblyComponentName"] = assembly_name
        placement_debug["createdBodies"] = len(created_ids)
        placement_debug["skippedPanels"] = len(skipped)
        placement_debug["positionOkCount"] = sum(
            1 for row in placement_debug["panels"] if row.get("positionOk") is True
        )
        placement_debug["positionFailCount"] = sum(
            1 for row in placement_debug["panels"] if row.get("positionOk") is False
        )
        _write_placement_debug(placement_debug)
        _capture_position_snapshot(root)

    model_z_offset = {
        "offsetMm": MODEL_Z_OFFSET_MM,
        "movedBodies": 0,
        "failedBodies": 0,
        "mode": "stagingAlreadyAtModelZ",
    }
    return {
        "createdBodies": len(created_ids),
        "createdPanelIds": created_ids,
        "skippedPanels": skipped,
        "cutouts": cutout_audit,
        "warnings": warnings,
        "errors": errors,
        "runLabel": resolved_run_label,
        "assemblyComponentName": assembly_name,
        "mode": mode,
        "adapterRevision": ADAPTER_REVISION,
        "cutoutsEnabled": bool(create_cutouts),
        "cutoutMode": "through_and_half_grooves" if create_cutouts else "outer_only",
        "deletedPreviousKitchenArtifacts": deleted_previous,
        "addAsNewCabinet": bool(add_as_new),
        "modelZOffset": model_z_offset,
        "placementDebug": {
            "adapterBuild": placement_debug.get("adapterBuild"),
            "resolvedOrigin": placement_debug.get("resolvedOrigin"),
            "originActive": placement_debug.get("originActive"),
            "avoidance": placement_debug.get("avoidance"),
            "spawnFootprintMm": placement_debug.get("spawnFootprintMm"),
            "positionOkCount": placement_debug.get("positionOkCount"),
            "positionFailCount": placement_debug.get("positionFailCount"),
            "panels": placement_debug.get("panels") if mode == "flat_transform" else [],
            "debugFile": "fusion360-unified-cabinet-plugin/placement_debug.json",
        },
        "originAvoidance": avoidance_info,
    }


def create_flat_panel_bodies_from_kitchen_result(fusion, result, run_label=None, add_as_new=True, component_name=None, origin_x_mm=None, origin_y_mm=None):
    return create_assembly_panel_bodies_from_kitchen_result(fusion, result, run_label=run_label, create_cutouts=True, mode="flat", add_as_new=add_as_new, component_name=component_name, origin_x_mm=origin_x_mm, origin_y_mm=origin_y_mm)


def create_flat_transformed_panel_bodies_from_kitchen_result(fusion, result, run_label=None, add_as_new=True, component_name=None, origin_x_mm=None, origin_y_mm=None):
    return create_assembly_panel_bodies_from_kitchen_result(fusion, result, run_label=run_label, create_cutouts=True, mode="flat_transform", add_as_new=add_as_new, component_name=component_name, origin_x_mm=origin_x_mm, origin_y_mm=origin_y_mm)
