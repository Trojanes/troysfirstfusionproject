import time
import math

import adsk.core
import adsk.fusion

from geometry_ops import ATTRIBUTE_GROUP, MODEL_Z_OFFSET_MM, mm_to_cm, offset_matching_bodies_z_mm, sanitize_token

ADAPTER_REVISION = "loungeWorldAlignedAssembly_v26"


def _num(value, fallback=0.0):
    try:
        return float(value)
    except Exception:
        return fallback


def _delete_lounge_artifacts_in_component(component, deleted, seen_components):
    component_key = id(component)
    if component_key in seen_components:
        return
    seen_components.add(component_key)
    try:
        for index in range(component.bRepBodies.count - 1, -1, -1):
            body = component.bRepBodies.item(index)
            name = str(getattr(body, "name", "") or "")
            if name.startswith("LOUNGE_"):
                body.deleteMe()
                deleted["bodies"] += 1
    except Exception:
        pass
    try:
        for index in range(component.sketches.count - 1, -1, -1):
            sketch = component.sketches.item(index)
            name = str(getattr(sketch, "name", "") or "")
            if name.startswith("LOUNGE_"):
                sketch.deleteMe()
                deleted["sketches"] += 1
    except Exception:
        pass
    try:
        for index in range(component.occurrences.count - 1, -1, -1):
            occurrence = component.occurrences.item(index)
            name = str(getattr(occurrence, "name", "") or "")
            child_component = getattr(occurrence, "component", None)
            child_name = str(getattr(child_component, "name", "") or "") if child_component else ""
            if child_component:
                _delete_lounge_artifacts_in_component(child_component, deleted, seen_components)
            if name.startswith("LOUNGE_") or name.startswith("L_") or child_name.startswith("LOUNGE_") or child_name.startswith("L_"):
                occurrence.deleteMe()
                deleted["occurrences"] += 1
    except Exception:
        pass


def _delete_previous_lounge_artifacts(root_comp):
    deleted = {"occurrences": 0, "bodies": 0, "sketches": 0, "failed": 0}
    _delete_lounge_artifacts_in_component(root_comp, deleted, set())
    return deleted


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


def _world_translation_transform(origin_x_mm=0.0, origin_y_mm=0.0, origin_z_mm=0.0):
    """Pure translation with explicit world X/Y/Z axes (no accidental rotation)."""
    transform = adsk.core.Matrix3D.create()
    from_origin = adsk.core.Point3D.create(0, 0, 0)
    to_origin = adsk.core.Point3D.create(
        mm_to_cm(float(origin_x_mm or 0.0)),
        mm_to_cm(float(origin_y_mm or 0.0)),
        mm_to_cm(float(origin_z_mm or 0.0)),
    )
    x_axis = adsk.core.Vector3D.create(1, 0, 0)
    y_axis = adsk.core.Vector3D.create(0, 1, 0)
    z_axis = adsk.core.Vector3D.create(0, 0, 1)
    transform.setToAlignCoordinateSystems(
        from_origin, x_axis, y_axis, z_axis,
        to_origin, x_axis, y_axis, z_axis,
    )
    return transform


def _new_lounge_component(root_comp, run_label, mode, component_name=None, origin_x_mm=0.0, origin_y_mm=0.0, origin_z_mm=0.0):
    if component_name:
        name = sanitize_token(component_name, fallback="assembly", limit=80)
    else:
        name = "LOUNGE_{}_{}".format(
            sanitize_token(mode or "run", fallback="run", limit=24),
            sanitize_token(run_label or int(time.time() * 1000), fallback="run", limit=60),
        )
    occurrence = None
    try:
        transform = _world_translation_transform(origin_x_mm, origin_y_mm, origin_z_mm)
        occurrence = root_comp.occurrences.addNewComponent(transform)
        component = occurrence.component
    except Exception as ex:
        return root_comp, None, "Could not create Lounge Z-offset component; using root component: {}".format(ex)

    name = _assign_component_name(occurrence, component, name)
    try:
        component.attributes.add(ATTRIBUTE_GROUP, "module", "lounge")
        component.attributes.add(ATTRIBUTE_GROUP, "previewMode", str(mode or "run"))
        component.attributes.add(ATTRIBUTE_GROUP, "runLabel", str(run_label or ""))
    except Exception:
        pass
    return component, name, None


def _new_item_component(parent_component, item_id):
    """One lounge panel/lid = one child component (assembly semantics).

    Returns (component, occurrence). Occurrence transform is required for
    flat→assembly placement; body-level moveFeatures are unreliable inside
    per-panel child components.
    """
    transform = adsk.core.Matrix3D.create()
    occurrence = parent_component.occurrences.addNewComponent(transform)
    component = occurrence.component
    _assign_component_name(
        occurrence, component, "L_{}".format(sanitize_token(item_id, fallback="item", limit=60))
    )
    try:
        component.attributes.add(ATTRIBUTE_GROUP, "module", "lounge")
        component.attributes.add(ATTRIBUTE_GROUP, "boardId", str(item_id))
    except Exception:
        pass
    return component, occurrence


def _item_component_for_assembly(container, item_id):
    """Keep every assembly panel in the parent component so Fusion move axes stay world-aligned."""
    return container, None


def _item_component_or_fallback(container, root, item_id, warnings):
    if container is root:
        return container, None
    try:
        return _new_item_component(container, item_id)
    except Exception as ex:
        warnings.append("Could not create item component for {}: {}".format(item_id, ex))
        return container, None


def _add_box_body(component, body_id, x0, x1, y0, y1, z0, z1):
    if x1 <= x0 or y1 <= y0 or z1 <= z0:
        return None, "non_positive_dimension"
    sketch = component.sketches.add(component.xYConstructionPlane)
    sketch.name = "LOUNGE_SK_{}".format(sanitize_token(body_id, limit=60))
    p0 = adsk.core.Point3D.create(mm_to_cm(x0), mm_to_cm(y0), 0)
    p1 = adsk.core.Point3D.create(mm_to_cm(x1), mm_to_cm(y1), 0)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
    if sketch.profiles.count < 1:
        return None, "no_profile"
    profile = sketch.profiles.item(0)
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(z1 - z0)))
    feature = extrudes.add(ext_input)
    if feature.bodies.count < 1:
        return None, "no_body"
    body = feature.bodies.item(0)
    body.name = "LOUNGE_{}".format(sanitize_token(body_id, limit=90))
    if abs(z0) > 1e-6:
        bodies = adsk.core.ObjectCollection.create()
        bodies.add(body)
        transform = adsk.core.Matrix3D.create()
        transform.translation = adsk.core.Vector3D.create(0, 0, mm_to_cm(z0))
        move_input = component.features.moveFeatures.createInput(bodies, transform)
        try:
            move_input.defineAsFreeMove(transform)
        except Exception:
            pass
        component.features.moveFeatures.add(move_input)
    try:
        body.attributes.add(ATTRIBUTE_GROUP, "module", "lounge")
        body.attributes.add(ATTRIBUTE_GROUP, "bodyId", str(body_id))
    except Exception:
        pass
    return body, None


def _draw_model_loop_on_sketch(sketch, world_points):
    if not isinstance(world_points, list) or len(world_points) < 3:
        return False
    clean = [p for p in world_points if isinstance(p, (list, tuple)) and len(p) >= 3]
    if len(clean) < 3:
        return False
    if clean[0] != clean[-1]:
        clean.append(clean[0])
    lines = sketch.sketchCurves.sketchLines
    for idx in range(len(clean) - 1):
        w0 = clean[idx]
        w1 = clean[idx + 1]
        m0 = adsk.core.Point3D.create(mm_to_cm(w0[0]), mm_to_cm(w0[1]), mm_to_cm(w0[2]))
        m1 = adsk.core.Point3D.create(mm_to_cm(w1[0]), mm_to_cm(w1[1]), mm_to_cm(w1[2]))
        lines.addByTwoPoints(sketch.modelToSketchSpace(m0), sketch.modelToSketchSpace(m1))
    return True


def _tag_lounge_body(body, item_id, preview_mode, profile_source):
    prefix = "LOUNGE_ASM" if preview_mode == "assembly" else "LOUNGE_FLAT"
    body.name = "{}_{}".format(prefix, sanitize_token(item_id, limit=90))
    try:
        body.attributes.add(ATTRIBUTE_GROUP, "module", "lounge")
        body.attributes.add(ATTRIBUTE_GROUP, "bodyId", item_id)
        body.attributes.add(ATTRIBUTE_GROUP, "previewMode", preview_mode)
        body.attributes.add(ATTRIBUTE_GROUP, "profileSource", profile_source)
    except Exception:
        pass


def _extrude_new_body(component, sketch, profile, distance_mm, item_id, preview_mode, profile_source):
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(distance_mm)))
    feature = extrudes.add(ext_input)
    if feature.bodies.count < 1:
        return None, "no_body"
    body = feature.bodies.item(0)
    _tag_lounge_body(body, item_id, preview_mode, profile_source)
    return body, None


def _add_xz_box_body(component, item_id, x0, x1, y0, y1, z0, z1, preview_mode="assembly"):
    if x1 <= x0 or y1 <= y0 or z1 <= z0:
        return None, "non_positive_dimension"
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    plane_input.setByOffset(component.xZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(y0)))
    sketch_plane = construction.add(plane_input)
    sketch = component.sketches.add(sketch_plane)
    sketch.name = "LOUNGE_ORIENT_SK_{}".format(sanitize_token(item_id, limit=60))
    corners = [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1), (x0, y0, z0)]
    if not _draw_model_loop_on_sketch(sketch, corners):
        return None, "invalid_outer"
    profile = _largest_profile(sketch)
    if profile is None:
        return None, "no_profile"
    return _extrude_new_body(component, sketch, profile, y1 - y0, item_id, preview_mode, "placementBoxXZ")


def _add_yz_box_body(component, item_id, x0, x1, y0, y1, z0, z1, preview_mode="assembly", anchor_x1=False):
    if x1 <= x0 or y1 <= y0 or z1 <= z0:
        return None, "non_positive_dimension"
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    anchor = x1 if anchor_x1 else x0
    plane_input.setByOffset(component.yZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(anchor)))
    sketch_plane = construction.add(plane_input)
    sketch = component.sketches.add(sketch_plane)
    sketch.name = "LOUNGE_ORIENT_SK_{}".format(sanitize_token(item_id, limit=60))
    corners = [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1), (x0, y0, z0)]
    if not _draw_model_loop_on_sketch(sketch, corners):
        return None, "invalid_outer"
    profile = _largest_profile(sketch)
    if profile is None:
        return None, "no_profile"
    thickness = x1 - x0
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    if anchor_x1:
        # Sketch on x=x1; negative distance (non-symmetric) extrudes toward -X to x0.
        # isSymmetric=True would double the thickness (2 × PPT) — that was the L-piece bug.
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(thickness)))
    else:
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(thickness)))
    feature = extrudes.add(ext_input)
    if feature.bodies.count < 1:
        return None, "no_body"
    body = feature.bodies.item(0)
    _tag_lounge_body(body, item_id, preview_mode, "placementBoxYZ")
    return body, None


def _outer_is_axis_aligned_rectangle(item):
    outer = _item_outer_points(item)
    if len(outer) < 4:
        return False
    # Rounded lids are not simple rectangles.
    if item.get("kind") == "lid" and _num(item.get("radius"), 0.0) > 0:
        return False
    if len(outer) > 5:
        return False
    xs = [_num(p[0]) for p in outer]
    ys = [_num(p[1]) for p in outer]
    width = max(xs) - min(xs)
    depth = max(ys) - min(ys)
    if width <= 0 or depth <= 0:
        return False
    placement = _item_placement(item)
    plane = str(item.get("profilePlane") or "XY")
    if plane == "XY":
        return (
            abs(width - (_num(placement.get("x1")) - _num(placement.get("x0")))) < 1.0
            and abs(depth - (_num(placement.get("y1")) - _num(placement.get("y0")))) < 1.0
        )
    if plane == "XZ":
        return (
            abs(width - (_num(placement.get("x1")) - _num(placement.get("x0")))) < 1.0
            and abs(depth - (_num(placement.get("z1")) - _num(placement.get("z0")))) < 1.0
        )
    if plane == "YZ":
        return (
            abs(width - (_num(placement.get("y1")) - _num(placement.get("y0")))) < 1.0
            and abs(depth - (_num(placement.get("z1")) - _num(placement.get("z0")))) < 1.0
        )
    return False


def _add_placement_box_body(component, item, preview_mode="assembly"):
    placement = _item_placement(item)
    item_id = str(item.get("id") or "panel")
    plane = str(item.get("profilePlane") or "XY")
    x0 = _num(placement.get("x0"))
    x1 = _num(placement.get("x1"))
    y0 = _num(placement.get("y0"))
    y1 = _num(placement.get("y1"))
    z0 = _num(placement.get("z0"))
    z1 = _num(placement.get("z1"))
    if plane == "XY":
        body, err = _add_box_body(component, item_id, x0, x1, y0, y1, z0, z1)
        if body is not None:
            _tag_lounge_body(body, item_id, preview_mode, "placementBoxXY")
        return body, err
    if plane == "XZ":
        return _add_xz_box_body(component, item_id, x0, x1, y0, y1, z0, z1, preview_mode=preview_mode)
    if plane == "YZ":
        anchor_x1 = item_id in ("main_left_l_piece", "main_right_l_piece")
        return _add_yz_box_body(
            component, item_id, x0, x1, y0, y1, z0, z1,
            preview_mode=preview_mode, anchor_x1=anchor_x1,
        )
    return None, "unsupported_profile_plane"


def _rounded_rect_points(x0, y0, x1, y1, radius, segments=10):
    """Facetted fallback (tests / size helpers). Prefer `_draw_rounded_rect` for Fusion bodies."""
    r = max(0.0, min(float(radius or 0.0), (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    if r <= 0:
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    centers = [
        (x1 - r, y0 + r, -math.pi / 2, 0),
        (x1 - r, y1 - r, 0, math.pi / 2),
        (x0 + r, y1 - r, math.pi / 2, math.pi),
        (x0 + r, y0 + r, math.pi, math.pi * 3 / 2),
    ]
    pts = [[x1 - r, y0]]
    for cx, cy, a0, a1 in centers:
        for i in range(1, segments + 1):
            t = a0 + (a1 - a0) * i / segments
            pts.append([cx + r * math.cos(t), cy + r * math.sin(t)])
    pts.append(pts[0])
    return pts


def _sketch_xy_point(sketch, x, y, offset_x=0.0, offset_y=0.0, plane_z_mm=None):
    # Cut/body sketches on XY (or a Z-offset parallel plane) use 2D sketch coords
    # that match model X/Y. Do not route through modelToSketchSpace: that can flip
    # sketch axes and break arc↔line connectivity (no closed profile → no step cut).
    _ = sketch
    _ = plane_z_mm
    return adsk.core.Point3D.create(mm_to_cm(x + offset_x), mm_to_cm(y + offset_y), 0)


def _draw_rounded_rect(sketch, x0, y0, x1, y1, radius, offset_x=0.0, offset_y=0.0, plane_z_mm=None):
    """Closed rounded rectangle using true sketch arcs (CCW)."""
    if x1 <= x0 or y1 <= y0:
        return False
    r = max(0.0, min(float(radius or 0.0), (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    lines = sketch.sketchCurves.sketchLines
    pt = lambda x, y: _sketch_xy_point(sketch, x, y, offset_x, offset_y, plane_z_mm)

    def add_line(ax, ay, bx, by):
        if abs(ax - bx) < 1e-9 and abs(ay - by) < 1e-9:
            return
        lines.addByTwoPoints(pt(ax, ay), pt(bx, by))

    if r <= 1e-9:
        add_line(x0, y0, x1, y0)
        add_line(x1, y0, x1, y1)
        add_line(x1, y1, x0, y1)
        add_line(x0, y1, x0, y0)
        return True

    arcs = sketch.sketchCurves.sketchArcs
    quarter = math.pi / 2.0
    # Bottom → BR arc → right → TR arc → top → TL arc → left → BL arc
    add_line(x0 + r, y0, x1 - r, y0)
    arcs.addByCenterStartSweep(pt(x1 - r, y0 + r), pt(x1 - r, y0), quarter)
    add_line(x1, y0 + r, x1, y1 - r)
    arcs.addByCenterStartSweep(pt(x1 - r, y1 - r), pt(x1, y1 - r), quarter)
    add_line(x1 - r, y1, x0 + r, y1)
    arcs.addByCenterStartSweep(pt(x0 + r, y1 - r), pt(x0 + r, y1), quarter)
    add_line(x0, y1 - r, x0, y0 + r)
    arcs.addByCenterStartSweep(pt(x0 + r, y0 + r), pt(x0, y0 + r), quarter)
    return True


def _draw_loop(sketch, points, offset_x=0.0, offset_y=0.0, plane_z_mm=None):
    if not isinstance(points, list) or len(points) < 3:
        return False
    clean = [p for p in points if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(clean) < 3:
        return False
    if clean[0] != clean[-1]:
        clean.append(clean[0])
    lines = sketch.sketchCurves.sketchLines
    for idx in range(len(clean) - 1):
        p0 = clean[idx]
        p1 = clean[idx + 1]
        a = _sketch_xy_point(sketch, _num(p0[0]), _num(p0[1]), offset_x, offset_y, plane_z_mm)
        b = _sketch_xy_point(sketch, _num(p1[0]), _num(p1[1]), offset_x, offset_y, plane_z_mm)
        lines.addByTwoPoints(a, b)
    return True


def _largest_profile(sketch):
    best = None
    best_area = -1.0
    try:
        count = sketch.profiles.count
    except Exception:
        count = 0
    for idx in range(count):
        profile = sketch.profiles.item(idx)
        try:
            area = abs(profile.areaProperties().area)
        except Exception:
            area = 0.0
        if area > best_area:
            best = profile
            best_area = area
    return best


def _rounded_rect_area_mm2(x0, y0, x1, y1, radius):
    width = max(0.0, x1 - x0)
    depth = max(0.0, y1 - y0)
    r = max(0.0, min(float(radius or 0.0), width / 2.0, depth / 2.0))
    return width * depth - (4.0 - math.pi) * r * r


def _profile_closest_to_area(sketch, expected_area_mm2):
    best = None
    best_delta = None
    expected_cm2 = max(0.0, expected_area_mm2) / 100.0
    try:
        count = sketch.profiles.count
    except Exception:
        count = 0
    for idx in range(count):
        profile = sketch.profiles.item(idx)
        try:
            area = abs(profile.areaProperties().area)
        except Exception:
            continue
        delta = abs(area - expected_cm2)
        if best is None or delta < best_delta:
            best = profile
            best_delta = delta
    return best


def _item_outer_points(item):
    # Lid footprint is rectangular in the data model; Fusion draws true arcs via `_draw_rounded_rect`.
    if item.get("kind") == "lid":
        width = _num(item.get("width"))
        depth = _num(item.get("depth"))
        return [[0, 0], [width, 0], [width, depth], [0, depth], [0, 0]]
    outer = item.get("outer")
    if isinstance(outer, list) and outer:
        return outer
    width = _num(item.get("width") or item.get("length"), 100)
    depth = _num(item.get("depth") or item.get("height"), 100)
    return [[0, 0], [width, 0], [width, depth], [0, depth], [0, 0]]


def _lid_draw_bounds(item):
    if item.get("kind") != "lid":
        return None
    width = _num(item.get("width"))
    depth = _num(item.get("depth"))
    radius = _num(item.get("radius"), 0.0)
    if width <= 0 or depth <= 0:
        return None
    return (0.0, 0.0, width, depth, radius)


def _set_cut_participant_bodies(ext_input, body):
    """Restrict a cut extrude to one body; without this Fusion may cut every intersecting body."""
    try:
        # Fusion SWIG binding prefers a Python list (same as GT LED cuts).
        ext_input.participantBodies = [body]
        return None
    except Exception:
        pass
    try:
        participants = adsk.core.ObjectCollection.create()
        participants.add(body)
        ext_input.participantBodies = participants
        return None
    except Exception as ex:
        return str(ex)


def _item_cut_loops(item):
    # Openings, rebates, and finger holes are modeled as post-extrude cuts so stepped depths are visible.
    return []


def _cut_rounded_rect_from_top(component, body, item_id, x0, y0, x1, y1, radius, depth, offset_x=0.0, offset_y=0.0, face="top"):
    if x1 <= x0 or y1 <= y0 or depth <= 0:
        return {"id": item_id, "status": "skipped", "reason": "invalid cut bounds"}
    thickness = max(0.1, _num(depth))
    from_bottom = str(face or "top") == "bottom"
    if from_bottom:
        plane_z = _num(body.boundingBox.minPoint.z) * 10.0
    else:
        plane_z = _num(body.boundingBox.maxPoint.z) * 10.0
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(plane_z)))
    plane = construction.add(plane_input)
    sketch = component.sketches.add(plane)
    sketch.name = "LOUNGE_CUT_{}".format(sanitize_token(item_id, limit=60))
    if not _draw_rounded_rect(sketch, x0, y0, x1, y1, radius, offset_x, offset_y, plane_z_mm=plane_z):
        return {"id": item_id, "status": "failed", "reason": "draw_loop_failed"}
    profile = _largest_profile(sketch)
    if profile is None:
        return {"id": item_id, "status": "failed", "reason": "no_profile"}
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
    distance = mm_to_cm(thickness) if from_bottom else -mm_to_cm(thickness)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(distance))
    participant_error = _set_cut_participant_bodies(ext_input, body)
    if participant_error:
        return {"id": item_id, "status": "failed", "reason": "participantBodies: {}".format(participant_error)}
    try:
        cut = extrudes.add(ext_input)
        cut.name = "LOUNGE_CUT_FEAT_{}".format(sanitize_token(item_id, limit=60))
        return {"id": item_id, "status": "created", "depth": depth, "face": face, "zPlane": plane_z}
    except Exception as ex:
        return {"id": item_id, "status": "failed", "reason": str(ex)}


def _cut_rounded_rect_ring_from_top(component, body, item_id, x0, y0, x1, y1, radius, inset, depth, offset_x=0.0, offset_y=0.0, face="top"):
    if x1 <= x0 or y1 <= y0 or inset <= 0 or depth <= 0:
        return {"id": item_id, "status": "skipped", "reason": "invalid ring bounds"}
    ix0 = x0 + inset
    iy0 = y0 + inset
    ix1 = x1 - inset
    iy1 = y1 - inset
    if ix1 <= ix0 or iy1 <= iy0:
        return {"id": item_id, "status": "skipped", "reason": "inset consumes profile"}
    inner_radius = max(0.0, _num(radius) - inset)
    from_bottom = str(face or "top") == "bottom"
    if from_bottom:
        plane_z = _num(body.boundingBox.minPoint.z) * 10.0
        cut_distance = mm_to_cm(depth)
    else:
        plane_z = _num(body.boundingBox.maxPoint.z) * 10.0
        cut_distance = -mm_to_cm(depth)
    plane_input = component.constructionPlanes.createInput()
    plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(plane_z)))
    plane = component.constructionPlanes.add(plane_input)
    sketch = component.sketches.add(plane)
    sketch.name = "LOUNGE_CUT_{}".format(sanitize_token(item_id, limit=60))
    if not _draw_rounded_rect(sketch, x0, y0, x1, y1, radius, offset_x, offset_y, plane_z_mm=plane_z):
        return {"id": item_id, "status": "failed", "reason": "draw_outer_failed"}
    if not _draw_rounded_rect(sketch, ix0, iy0, ix1, iy1, inner_radius, offset_x, offset_y, plane_z_mm=plane_z):
        return {"id": item_id, "status": "failed", "reason": "draw_inner_failed"}
    outer_area = _rounded_rect_area_mm2(x0, y0, x1, y1, radius)
    inner_area = _rounded_rect_area_mm2(ix0, iy0, ix1, iy1, inner_radius)
    profile = _profile_closest_to_area(sketch, outer_area - inner_area)
    if profile is None:
        return {"id": item_id, "status": "failed", "reason": "no_ring_profile"}
    ext_input = component.features.extrudeFeatures.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(cut_distance))
    participant_error = _set_cut_participant_bodies(ext_input, body)
    if participant_error:
        return {"id": item_id, "status": "failed", "reason": "participantBodies: {}".format(participant_error)}
    try:
        cut = component.features.extrudeFeatures.add(ext_input)
        cut.name = "LOUNGE_CUT_FEAT_{}".format(sanitize_token(item_id, limit=60))
        return {"id": item_id, "status": "created", "depth": depth, "inset": inset, "face": face, "zPlane": plane_z}
    except Exception as ex:
        return {"id": item_id, "status": "failed", "reason": str(ex)}


def _apply_flat_panel_cuts(component, body, item, offset_x, offset_y, assembly_mode=False):
    audits = []
    thickness = max(0.1, _num(item.get("thickness"), 18))
    opening = item.get("opening") if isinstance(item.get("opening"), dict) else None
    if opening:
        step_w = _num(opening.get("stepWidth"), thickness / 2.0)
        step_h = _num(opening.get("stepHeight"), thickness / 2.0)
        ox0 = _num(opening.get("x0"))
        oy0 = _num(opening.get("y0"))
        ox1 = _num(opening.get("x1"))
        oy1 = _num(opening.get("y1"))
        radius = _num(opening.get("radius"), 50)
        # Explicit shoulder ring (outer − through), then through cut.
        if step_w > 0 and step_h > 0:
            audits.append(_cut_rounded_rect_ring_from_top(
                component, body, "{}_rebate_step".format(item.get("id")),
                ox0, oy0, ox1, oy1,
                radius,
                step_w,
                min(step_h, thickness),
                offset_x, offset_y,
            ))
        audits.append(_cut_rounded_rect_from_top(
            component, body, "{}_through_opening".format(item.get("id")),
            ox0 + step_w, oy0 + step_w,
            ox1 - step_w, oy1 - step_w,
            max(0.0, radius - step_w),
            thickness + 0.5,
            offset_x, offset_y,
        ))
    finger = item.get("fingerHole") if isinstance(item.get("fingerHole"), dict) else None
    if finger:
        d = _num(finger.get("diameter"), 40)
        cx = _num(finger.get("centerX"))
        cy = _num(finger.get("centerY"))
        audits.append(_cut_rounded_rect_from_top(
            component, body, "{}_finger_hole".format(item.get("id")),
            cx - d / 2.0, cy - d / 2.0,
            cx + d / 2.0, cy + d / 2.0,
            d / 2.0,
            thickness + 0.5,
            offset_x, offset_y,
        ))
    if item.get("kind") == "lid":
        step_w = _num(item.get("stepWidth"), thickness / 2.0)
        step_h = min(_num(item.get("stepHeight"), thickness / 2.0), thickness)
        width = _num(item.get("width"))
        depth = _num(item.get("depth"))
        if step_w > 0 and step_h > 0 and width > step_w * 2 and depth > step_w * 2:
            audits.append(_cut_rounded_rect_ring_from_top(
                component, body, "{}_offset_ring_step".format(item.get("id")),
                0, 0, width, depth,
                _num(item.get("radius"), 0.0),
                step_w,
                step_h,
                offset_x, offset_y,
                face="bottom" if assembly_mode else "top",
            ))
    for hole in item.get("hingeHoles") or []:
        if not isinstance(hole, dict):
            continue
        d = _num(hole.get("diameter"), 35)
        cx = _num(hole.get("centerX"))
        cy = _num(hole.get("centerY"))
        audits.append(_cut_rounded_rect_from_top(
            component, body, str(hole.get("id") or "{}_hinge".format(item.get("id"))),
            cx - d / 2.0, cy - d / 2.0,
            cx + d / 2.0, cy + d / 2.0,
            d / 2.0,
            min(_num(hole.get("depth"), 12.5), thickness),
            offset_x, offset_y,
            face=str(hole.get("face") or "top"),
        ))
    for lock in item.get("lockCutouts") or []:
        if not isinstance(lock, dict):
            continue
        lw = _num(lock.get("width"), 55)
        lh = _num(lock.get("height"), 15.5)
        cx = _num(lock.get("centerX"))
        cy = _num(lock.get("centerY"))
        audits.append(_cut_rounded_rect_from_top(
            component, body, str(lock.get("id") or "{}_lock".format(item.get("id"))),
            cx - lw / 2.0, cy - lh / 2.0,
            cx + lw / 2.0, cy + lh / 2.0,
            _num(lock.get("radius"), lh / 2.0),
            thickness + 0.5,
            offset_x, offset_y,
        ))
    for groove in item.get("grooves") or []:
        if not isinstance(groove, dict):
            continue
        audits.append(_cut_rounded_rect_from_top(
            component, body, str(groove.get("id") or "{}_groove".format(item.get("id"))),
            _num(groove.get("x0")), _num(groove.get("y0")),
            _num(groove.get("x1")), _num(groove.get("y1")),
            0,
            min(_num(groove.get("depth"), thickness / 2.0), thickness),
            offset_x, offset_y,
            face=str(groove.get("face") or "top"),
        ))
    return audits


def _cut_audit_warnings(audits):
    warnings = []
    for audit in audits or []:
        if not isinstance(audit, dict):
            continue
        status = str(audit.get("status") or "")
        if status in ("failed", "skipped") and audit.get("reason"):
            warnings.append("Cut {}: {} ({})".format(audit.get("id"), status, audit.get("reason")))
    return warnings


def _item_size(item):
    outer = _item_outer_points(item)
    xs = [_num(p[0]) for p in outer]
    ys = [_num(p[1]) for p in outer]
    return max(xs) - min(xs), max(ys) - min(ys)


def _item_placement(item):
    placement = item.get("placement") if isinstance(item.get("placement"), dict) else {}
    return placement


def _profile_world_point(plane, placement, point2d):
    a = _num(point2d[0])
    b = _num(point2d[1])
    x0 = _num(placement.get("x0"))
    y0 = _num(placement.get("y0"))
    z0 = _num(placement.get("z0"))
    if plane == "XY":
        return (x0 + a, y0 + b, z0)
    if plane == "XZ":
        return (x0 + a, y0, z0 + b)
    if plane == "YZ":
        return (x0, y0 + a, z0 + b)
    return None


def _lounge_profile_plane_for_sketch(component, plane, placement, item_id=""):
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    if plane == "YZ":
        anchor = _num(placement.get("x1")) if item_id in ("main_left_l_piece", "main_right_l_piece") else _num(placement.get("x0"))
        plane_input.setByOffset(component.yZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(anchor)))
    elif plane == "XY":
        plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(_num(placement.get("z0")))))
    elif plane == "XZ":
        plane_input.setByOffset(component.xZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(_num(placement.get("y0")))))
    else:
        return None
    return construction.add(plane_input)


def _placement_thickness_mm(plane, placement, item_id=""):
    if plane == "YZ":
        return max(0.1, _num(placement.get("x1")) - _num(placement.get("x0")))
    if plane == "XZ":
        return max(0.1, _num(placement.get("y1")) - _num(placement.get("y0")))
    return max(0.1, _num(placement.get("z1")) - _num(placement.get("z0")))


def _draw_loop_oriented(sketch, points, plane, placement):
    if not isinstance(points, list) or len(points) < 3:
        return False
    clean = [p for p in points if isinstance(p, (list, tuple)) and len(p) >= 2]
    if len(clean) < 3:
        return False
    if clean[0] != clean[-1]:
        clean.append(clean[0])
    lines = sketch.sketchCurves.sketchLines
    for idx in range(len(clean) - 1):
        w0 = _profile_world_point(plane, placement, clean[idx])
        w1 = _profile_world_point(plane, placement, clean[idx + 1])
        if w0 is None or w1 is None:
            return False
        m0 = adsk.core.Point3D.create(mm_to_cm(w0[0]), mm_to_cm(w0[1]), mm_to_cm(w0[2]))
        m1 = adsk.core.Point3D.create(mm_to_cm(w1[0]), mm_to_cm(w1[1]), mm_to_cm(w1[2]))
        s0 = sketch.modelToSketchSpace(m0)
        s1 = sketch.modelToSketchSpace(m1)
        lines.addByTwoPoints(s0, s1)
    return True


def _oriented_sketch_point(sketch, plane, placement, x, y):
    world = _profile_world_point(plane, placement, [x, y])
    if world is None:
        return None
    model = adsk.core.Point3D.create(mm_to_cm(world[0]), mm_to_cm(world[1]), mm_to_cm(world[2]))
    return sketch.modelToSketchSpace(model)


def _draw_rounded_rect_oriented(sketch, x0, y0, x1, y1, radius, plane, placement):
    """Closed rounded rectangle in assembly-oriented sketch space using true arcs."""
    if x1 <= x0 or y1 <= y0:
        return False
    r = max(0.0, min(float(radius or 0.0), (x1 - x0) / 2.0, (y1 - y0) / 2.0))
    lines = sketch.sketchCurves.sketchLines
    pt = lambda x, y: _oriented_sketch_point(sketch, plane, placement, x, y)

    def add_line(ax, ay, bx, by):
        if abs(ax - bx) < 1e-9 and abs(ay - by) < 1e-9:
            return True
        a = pt(ax, ay)
        b = pt(bx, by)
        if a is None or b is None:
            return False
        lines.addByTwoPoints(a, b)
        return True

    if r <= 1e-9:
        return (
            add_line(x0, y0, x1, y0)
            and add_line(x1, y0, x1, y1)
            and add_line(x1, y1, x0, y1)
            and add_line(x0, y1, x0, y0)
        )

    arcs = sketch.sketchCurves.sketchArcs
    quarter = math.pi / 2.0
    if not add_line(x0 + r, y0, x1 - r, y0):
        return False
    c = pt(x1 - r, y0 + r)
    s = pt(x1 - r, y0)
    if c is None or s is None:
        return False
    arcs.addByCenterStartSweep(c, s, quarter)
    if not add_line(x1, y0 + r, x1, y1 - r):
        return False
    c = pt(x1 - r, y1 - r)
    s = pt(x1, y1 - r)
    if c is None or s is None:
        return False
    arcs.addByCenterStartSweep(c, s, quarter)
    if not add_line(x1 - r, y1, x0 + r, y1):
        return False
    c = pt(x0 + r, y1 - r)
    s = pt(x0 + r, y1)
    if c is None or s is None:
        return False
    arcs.addByCenterStartSweep(c, s, quarter)
    if not add_line(x0, y1 - r, x0, y0 + r):
        return False
    c = pt(x0 + r, y0 + r)
    s = pt(x0, y0 + r)
    if c is None or s is None:
        return False
    arcs.addByCenterStartSweep(c, s, quarter)
    return True


def _add_oriented_panel_body(component, item, preview_mode="assembly"):
    """Create panels directly in assembly pose (no flat staging + rotation)."""
    item_id = str(item.get("id") or "panel")
    plane = str(item.get("profilePlane") or "XY")
    if plane not in ("XY", "XZ", "YZ"):
        return None, "oriented_plane_required"
    if _outer_is_axis_aligned_rectangle(item):
        return _add_placement_box_body(component, item, preview_mode=preview_mode)
    placement = _item_placement(item)
    sketch_plane = _lounge_profile_plane_for_sketch(component, plane, placement, item_id=item_id)
    if sketch_plane is None:
        return None, "unsupported_profile_plane"
    sketch = component.sketches.add(sketch_plane)
    sketch.name = "LOUNGE_ORIENT_SK_{}".format(sanitize_token(item_id, limit=60))
    # L pieces sketch on x=x1; draw profile on that plane (not x0) so extrude -X lands on x0..x1.
    draw_placement = placement
    if item_id in ("main_left_l_piece", "main_right_l_piece") and plane == "YZ":
        draw_placement = dict(placement)
        draw_placement["x0"] = _num(placement.get("x1"))
    lid_bounds = _lid_draw_bounds(item)
    if lid_bounds is not None:
        lx0, ly0, lx1, ly1, radius = lid_bounds
        if not _draw_rounded_rect_oriented(sketch, lx0, ly0, lx1, ly1, radius, plane, draw_placement):
            return None, "invalid_outer"
    elif not _draw_loop_oriented(sketch, _item_outer_points(item), plane, draw_placement):
        return None, "invalid_outer"
    profile = _largest_profile(sketch)
    if profile is None:
        return None, "no_profile"
    thickness = _placement_thickness_mm(plane, placement, item_id=item_id)
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    if item_id in ("main_left_l_piece", "main_right_l_piece"):
        # Plane is anchored at placement.x1; extrude -X by PPT only (not symmetric).
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(thickness)))
    else:
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(thickness)))
    feature = extrudes.add(ext_input)
    if feature.bodies.count < 1:
        return None, "no_body"
    body = feature.bodies.item(0)
    _tag_lounge_body(body, item_id, preview_mode, "orientedAssemblyProfile")
    return body, None


def _assembly_uses_oriented_body(item):
    return str(item.get("profilePlane") or "XY") in ("XY", "XZ", "YZ")


def _oriented_cut_offsets(item):
    """Panel-local cut coords need placement offset when the body was built in assembly pose."""
    placement = _item_placement(item)
    if str(item.get("profilePlane") or "XY") == "XY":
        return _num(placement.get("x0")), _num(placement.get("y0"))
    return 0.0, 0.0


def _item_needs_assembly_cuts(item):
    if item.get("opening") or item.get("kind") == "lid":
        return True
    if item.get("fingerHole") or item.get("hingeHoles") or item.get("lockCutouts") or item.get("grooves"):
        return True
    return False


def _add_flat_panel_body(component, item, offset_x, offset_y, preview_mode="flat_svg"):
    item_id = str(item.get("id") or "panel")
    thickness = max(0.1, _num(item.get("thickness"), 18))
    sketch = component.sketches.add(component.xYConstructionPlane)
    sketch.name = "LOUNGE_FLAT_SK_{}".format(sanitize_token(item_id, limit=60))
    lid_bounds = _lid_draw_bounds(item)
    if lid_bounds is not None:
        lx0, ly0, lx1, ly1, radius = lid_bounds
        if not _draw_rounded_rect(sketch, lx0, ly0, lx1, ly1, radius, offset_x, offset_y):
            return None, "invalid_outer"
    elif not _draw_loop(sketch, _item_outer_points(item), offset_x, offset_y):
        return None, "invalid_outer"
    for loop in _item_cut_loops(item):
        _draw_loop(sketch, loop, offset_x, offset_y)
    profile = _largest_profile(sketch)
    if profile is None:
        return None, "no_profile"
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(thickness)))
    feature = extrudes.add(ext_input)
    if feature.bodies.count < 1:
        return None, "no_body"
    body = feature.bodies.item(0)
    prefix = "LOUNGE_ASM" if preview_mode == "assembly" else "LOUNGE_FLAT"
    body.name = "{}_{}".format(prefix, sanitize_token(item_id, limit=90))
    try:
        body.attributes.add(ATTRIBUTE_GROUP, "module", "lounge")
        body.attributes.add(ATTRIBUTE_GROUP, "bodyId", item_id)
        body.attributes.add(ATTRIBUTE_GROUP, "previewMode", preview_mode)
    except Exception:
        pass
    return body, None


def _move_body_rigid_transform(component, body, transform, feature_prefix="LOUNGE_MOVE_"):
    bodies = adsk.core.ObjectCollection.create()
    bodies.add(body)
    move_input = component.features.moveFeatures.createInput(bodies, transform)
    try:
        move_input.defineAsFreeMove(transform)
    except Exception:
        pass
    move_feature = component.features.moveFeatures.add(move_input)
    move_feature.name = "{}{}".format(feature_prefix, sanitize_token(getattr(body, "name", "body"), limit=50))
    return move_feature


def _apply_occurrence_transform(occurrence, matrix):
    """Place a per-panel child occurrence with an exact rigid transform.

    Body-level moveFeatures silently apply no motion inside per-panel child
    components; the occurrence transform is exact for all planes (incl. YZ).
    """
    if matrix is None:
        return "No target transform."
    try:
        occurrence.transform = matrix
        return None
    except Exception as ex:
        return "Occurrence transform failed: {}".format(ex)


def _assembly_transform_for_item(item, staging_offset_x=0.0, staging_offset_y=0.0):
    placement = item.get("placement") if isinstance(item.get("placement"), dict) else {}
    x0 = _num(placement.get("x0"))
    y0 = _num(placement.get("y0"))
    z0 = _num(placement.get("z0"))
    ox = _num(staging_offset_x)
    oy = _num(staging_offset_y)
    plane = str(item.get("profilePlane") or "XY")
    item_id = str(item.get("id") or "")
    matrix = adsk.core.Matrix3D.create()
    if plane == "XY":
        matrix.translation = adsk.core.Vector3D.create(mm_to_cm(x0 - ox), mm_to_cm(y0 - oy), mm_to_cm(z0))
        return matrix
    if plane == "XZ":
        # Local flat axes: X=profile width, Y=profile height, Z=thickness.
        # Assembly axes: X=width, Y=thickness, Z=height.
        y1 = _num(placement.get("y1"))
        matrix.setCell(0, 0, 1)
        matrix.setCell(0, 1, 0)
        matrix.setCell(0, 2, 0)
        matrix.setCell(0, 3, mm_to_cm(x0 - ox))
        matrix.setCell(1, 0, 0)
        matrix.setCell(1, 1, 0)
        matrix.setCell(1, 2, -1)
        matrix.setCell(1, 3, mm_to_cm(y1))
        matrix.setCell(2, 0, 0)
        matrix.setCell(2, 1, 1)
        matrix.setCell(2, 2, 0)
        matrix.setCell(2, 3, mm_to_cm(z0 - oy))
        return matrix
    if plane == "YZ":
        y_shift = 0.0
        # Local flat axes: X=profile depth, Y=profile height, Z=thickness.
        # Assembly axes: X=thickness, Y=depth, Z=height.
        if item_id in ("main_left_l_piece", "main_right_l_piece"):
            x1 = _num(placement.get("x1"))
            y1 = _num(placement.get("y1"))
            matrix.setCell(0, 0, 0)
            matrix.setCell(0, 1, 0)
            matrix.setCell(0, 2, -1)
            matrix.setCell(0, 3, mm_to_cm(x1))
            matrix.setCell(1, 0, -1)
            matrix.setCell(1, 1, 0)
            matrix.setCell(1, 2, 0)
            matrix.setCell(1, 3, mm_to_cm(y1 + ox))
            matrix.setCell(2, 0, 0)
            matrix.setCell(2, 1, 1)
            matrix.setCell(2, 2, 0)
            matrix.setCell(2, 3, mm_to_cm(z0 - oy))
            return matrix
        matrix.setCell(0, 0, 0)
        matrix.setCell(0, 1, 0)
        matrix.setCell(0, 2, 1)
        matrix.setCell(0, 3, mm_to_cm(x0))
        matrix.setCell(1, 0, 1)
        matrix.setCell(1, 1, 0)
        matrix.setCell(1, 2, 0)
        matrix.setCell(1, 3, mm_to_cm(y0 - ox))
        matrix.setCell(2, 0, 0)
        matrix.setCell(2, 1, 1)
        matrix.setCell(2, 2, 0)
        matrix.setCell(2, 3, mm_to_cm(z0 - oy))
        return matrix
    return None


def _assembly_plane_sort_key(item):
    plane = str(item.get("profilePlane") or "XY")
    return {"XY": 0, "XZ": 1, "YZ": 2}.get(plane, 9)


def _auto_origin(root, origin_x_mm, origin_y_mm):
    """None = auto: use the generation-zone centre from the saved work zones.

    Returns (x, y, active). When active is True (explicit origin or work zones),
    assembly is placed on z=0 instead of legacy MODEL_Z_OFFSET_MM staging.
    """
    has_work_zones = False
    if origin_x_mm is None and origin_y_mm is None:
        try:
            import json as _json

            attr = root.attributes.itemByName("UnifiedCabinet", "workZoneLayout") if root else None
            if attr and attr.value:
                layout = _json.loads(attr.value)
                rect = layout.get("generation") if isinstance(layout, dict) else None
                if isinstance(rect, dict):
                    has_work_zones = True
                    return (
                        float(rect["x0"]),
                        float(rect["y0"]),
                        True,
                    )
        except Exception:
            pass
    explicit = origin_x_mm is not None or origin_y_mm is not None
    origin_active = bool(explicit or has_work_zones)
    return float(origin_x_mm or 0.0), float(origin_y_mm or 0.0), origin_active


def _resolve_assembly_origin(root, origin_x_mm, origin_y_mm):
    origin_x_mm, origin_y_mm, origin_active = _auto_origin(root, origin_x_mm, origin_y_mm)
    origin_z_mm = 0.0 if origin_active else MODEL_Z_OFFSET_MM
    return origin_x_mm, origin_y_mm, origin_z_mm, origin_active


def _capture_position_snapshot(root_comp):
    """Snapshot occurrence positions so parametric recomputes keep them."""
    try:
        design = root_comp.parentDesign
        if design and design.snapshots and design.snapshots.hasPendingSnapshot:
            design.snapshots.add()
    except Exception:
        pass


def create_lounge_bodies(fusion_adapter, result, run_label=None, component_name=None, origin_x_mm=None, origin_y_mm=None):
    summary = {
        "ok": True,
        "module": "lounge",
        "action": "lounge.createFlatBodies",
        "createdBodies": 0,
        "createdIds": [],
        "skipped": [],
        "cutAudit": [],
        "errors": [],
        "warnings": ["Lounge flat bodies: opening rebate + lid underside step are cut after extrude."],
        "previewMode": "flat_svg",
        "adapterRevision": ADAPTER_REVISION,
        "deletedPrevious": {"bodies": 0, "sketches": 0, "failed": 0},
        "runLabel": str(run_label or int(time.time() * 1000)),
    }
    root = fusion_adapter.get_root_component()
    if not root:
        summary["ok"] = False
        summary["errors"].append("No active Fusion root component.")
        return summary
    summary["deletedPrevious"] = _delete_previous_lounge_artifacts(root)
    origin_x_mm, origin_y_mm, origin_z_mm, origin_active = _resolve_assembly_origin(root, origin_x_mm, origin_y_mm)
    component, component_name, component_warning = _new_lounge_component(
        root, summary["runLabel"], "flat",
        component_name=component_name, origin_x_mm=origin_x_mm, origin_y_mm=origin_y_mm, origin_z_mm=origin_z_mm,
    )
    summary["resolvedOrigin"] = [origin_x_mm, origin_y_mm, origin_z_mm]
    summary["originActive"] = bool(origin_active)
    summary["assemblyComponentName"] = component_name
    if component_warning:
        summary["warnings"].append(component_warning)
    panels = result.get("panels") if isinstance(result.get("panels"), list) else []
    lids = result.get("lids") if isinstance(result.get("lids"), list) else []
    flat_items = [item for item in panels + lids if isinstance(item, dict)]
    cursor_x = 0.0
    row_y = 0.0
    row_h = 0.0
    max_row_w = 3200.0
    gap = 120.0
    for item in flat_items:
        width, depth = _item_size(item)
        if cursor_x > 0 and cursor_x + width > max_row_w:
            cursor_x = 0.0
            row_y += row_h + gap
            row_h = 0.0
        item_component, item_occurrence = _item_component_or_fallback(component, root, item.get("id"), summary["warnings"])
        body, err = _add_flat_panel_body(item_component, item, cursor_x, row_y)
        if err:
            summary["skipped"].append({"id": item.get("id"), "reason": err})
            continue
        summary["cutAudit"].extend(_apply_flat_panel_cuts(item_component, body, item, cursor_x, row_y))
        summary["createdBodies"] += 1
        summary["createdIds"].append(item.get("id"))
        cursor_x += width + gap
        row_h = max(row_h, depth)
    summary["warnings"].extend(_cut_audit_warnings(summary["cutAudit"]))
    _capture_position_snapshot(root)
    summary["modelZOffset"] = {
        "offsetMm": origin_z_mm,
        "movedBodies": 0,
        "failedBodies": 0,
        "mode": "componentAtModelZ" if not origin_active else "generationZoneZ0",
    }
    return summary


def create_lounge_assembly_bodies(fusion_adapter, result, run_label=None, component_name=None, origin_x_mm=None, origin_y_mm=None):
    summary = {
        "ok": True,
        "module": "lounge",
        "action": "lounge.createAssemblyBodies",
        "createdBodies": 0,
        "createdIds": [],
        "skipped": [],
        "cutAudit": [],
        "transformAudit": [],
        "errors": [],
        "warnings": ["Lounge assembly: world-aligned axes via placementBox/orientedAssemblyDirect (v26)."],
        "previewMode": "assembly",
        "adapterRevision": ADAPTER_REVISION,
        "deletedPrevious": {"bodies": 0, "sketches": 0, "failed": 0},
        "runLabel": str(run_label or int(time.time() * 1000)),
    }
    root = fusion_adapter.get_root_component()
    if not root:
        summary["ok"] = False
        summary["errors"].append("No active Fusion root component.")
        return summary
    summary["deletedPrevious"] = _delete_previous_lounge_artifacts(root)
    origin_x_mm, origin_y_mm, origin_z_mm, origin_active = _resolve_assembly_origin(root, origin_x_mm, origin_y_mm)
    component, component_name, component_warning = _new_lounge_component(
        root, summary["runLabel"], "assembly",
        component_name=component_name, origin_x_mm=origin_x_mm, origin_y_mm=origin_y_mm, origin_z_mm=origin_z_mm,
    )
    summary["resolvedOrigin"] = [origin_x_mm, origin_y_mm, origin_z_mm]
    summary["originActive"] = bool(origin_active)
    summary["assemblyComponentName"] = component_name
    if component_warning:
        summary["warnings"].append(component_warning)
    panels = result.get("panels") if isinstance(result.get("panels"), list) else []
    lids = result.get("lids") if isinstance(result.get("lids"), list) else []
    items = sorted(
        [item for item in panels + lids if isinstance(item, dict)],
        key=_assembly_plane_sort_key,
    )
    for item in items:
        item_id = item.get("id")
        item_component, _item_occurrence = _item_component_for_assembly(component, item_id)
        body, err = _add_oriented_panel_body(item_component, item, preview_mode="assembly")
        if err:
            summary["skipped"].append({"id": item_id, "reason": err})
            continue
        if _item_needs_assembly_cuts(item):
            cut_ox, cut_oy = _oriented_cut_offsets(item)
            summary["cutAudit"].extend(_apply_flat_panel_cuts(
                item_component, body, item, cut_ox, cut_oy, assembly_mode=True,
            ))
        summary["transformAudit"].append({
            "id": item_id,
            "profilePlane": item.get("profilePlane"),
            "placement": item.get("placement"),
            "transformSource": "orientedAssemblyDirect",
            "componentScope": "assemblyParent",
            "status": "placed",
        })
        summary["createdBodies"] += 1
        summary["createdIds"].append(item_id)
    summary["warnings"].extend(_cut_audit_warnings(summary["cutAudit"]))
    _capture_position_snapshot(root)
    summary["modelZOffset"] = {
        "offsetMm": origin_z_mm,
        "movedBodies": 0,
        "failedBodies": 0,
        "mode": "componentAtModelZ" if not origin_active else "generationZoneZ0",
    }
    return summary
