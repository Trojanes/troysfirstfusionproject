import time
import math

import adsk.core
import adsk.fusion

from geometry_ops import ATTRIBUTE_GROUP, MODEL_Z_OFFSET_MM, mm_to_cm, offset_matching_bodies_z_mm, sanitize_token

ADAPTER_REVISION = "loungeStagedInModelZComponent_v15"


def _num(value, fallback=0.0):
    try:
        return float(value)
    except Exception:
        return fallback


def _delete_previous_lounge_artifacts(root_comp):
    deleted = {"bodies": 0, "sketches": 0, "failed": 0}
    try:
        body_count = root_comp.bRepBodies.count
    except Exception:
        body_count = 0
    for idx in range(body_count - 1, -1, -1):
        try:
            body = root_comp.bRepBodies.item(idx)
            if str(getattr(body, "name", "") or "").startswith("LOUNGE_"):
                if body.deleteMe():
                    deleted["bodies"] += 1
                else:
                    deleted["failed"] += 1
        except Exception:
            deleted["failed"] += 1
    try:
        sketch_count = root_comp.sketches.count
    except Exception:
        sketch_count = 0
    for idx in range(sketch_count - 1, -1, -1):
        try:
            sketch = root_comp.sketches.item(idx)
            if str(getattr(sketch, "name", "") or "").startswith("LOUNGE_"):
                if sketch.deleteMe():
                    deleted["sketches"] += 1
                else:
                    deleted["failed"] += 1
        except Exception:
            deleted["failed"] += 1
    return deleted


def _new_lounge_component(root_comp, run_label, mode):
    name = "LOUNGE_{}_{}".format(
        sanitize_token(mode or "run", fallback="run", limit=24),
        sanitize_token(run_label or int(time.time() * 1000), fallback="run", limit=60),
    )
    try:
        transform = adsk.core.Matrix3D.create()
        transform.translation = adsk.core.Vector3D.create(0, 0, mm_to_cm(MODEL_Z_OFFSET_MM))
        occurrence = root_comp.occurrences.addNewComponent(transform)
        occurrence.name = name
        component = occurrence.component
        component.name = name
        try:
            component.attributes.add(ATTRIBUTE_GROUP, "module", "lounge")
            component.attributes.add(ATTRIBUTE_GROUP, "previewMode", str(mode or "run"))
            component.attributes.add(ATTRIBUTE_GROUP, "runLabel", str(run_label or ""))
        except Exception:
            pass
        return component, name, None
    except Exception as ex:
        return root_comp, None, "Could not create Lounge Z-offset component; using root component: {}".format(ex)


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


def _rounded_rect_points(x0, y0, x1, y1, radius, segments=10):
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


def _draw_loop(sketch, points, offset_x=0.0, offset_y=0.0):
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
        a = adsk.core.Point3D.create(mm_to_cm(_num(p0[0]) + offset_x), mm_to_cm(_num(p0[1]) + offset_y), 0)
        b = adsk.core.Point3D.create(mm_to_cm(_num(p1[0]) + offset_x), mm_to_cm(_num(p1[1]) + offset_y), 0)
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
    if item.get("kind") == "lid":
        width = _num(item.get("width"))
        depth = _num(item.get("depth"))
        return _rounded_rect_points(0, 0, width, depth, _num(item.get("radius"), 0.0))
    outer = item.get("outer")
    if isinstance(outer, list) and outer:
        return outer
    width = _num(item.get("width") or item.get("length"), 100)
    depth = _num(item.get("depth") or item.get("height"), 100)
    return [[0, 0], [width, 0], [width, depth], [0, depth], [0, 0]]


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
    loop = _rounded_rect_points(x0, y0, x1, y1, radius)
    if not _draw_loop(sketch, loop, offset_x, offset_y):
        return {"id": item_id, "status": "failed", "reason": "draw_loop_failed"}
    profile = _largest_profile(sketch)
    if profile is None:
        return {"id": item_id, "status": "failed", "reason": "no_profile"}
    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
    distance = mm_to_cm(thickness) if from_bottom else -mm_to_cm(thickness)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(distance))
    try:
        participants = adsk.core.ObjectCollection.create()
        participants.add(body)
        ext_input.participantBodies = participants
    except Exception:
        pass
    try:
        cut = extrudes.add(ext_input)
        cut.name = "LOUNGE_CUT_FEAT_{}".format(sanitize_token(item_id, limit=60))
        return {"id": item_id, "status": "created", "depth": depth, "face": face, "zPlane": plane_z}
    except Exception as ex:
        return {"id": item_id, "status": "failed", "reason": str(ex)}


def _cut_rounded_rect_ring_from_top(component, body, item_id, x0, y0, x1, y1, radius, inset, depth, offset_x=0.0, offset_y=0.0):
    if x1 <= x0 or y1 <= y0 or inset <= 0 or depth <= 0:
        return {"id": item_id, "status": "skipped", "reason": "invalid ring bounds"}
    ix0 = x0 + inset
    iy0 = y0 + inset
    ix1 = x1 - inset
    iy1 = y1 - inset
    if ix1 <= ix0 or iy1 <= iy0:
        return {"id": item_id, "status": "skipped", "reason": "inset consumes profile"}
    inner_radius = max(0.0, _num(radius) - inset)
    top_z = _num(body.boundingBox.maxPoint.z) * 10.0
    plane_input = component.constructionPlanes.createInput()
    plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(top_z)))
    plane = component.constructionPlanes.add(plane_input)
    sketch = component.sketches.add(plane)
    sketch.name = "LOUNGE_CUT_{}".format(sanitize_token(item_id, limit=60))
    if not _draw_loop(sketch, _rounded_rect_points(x0, y0, x1, y1, radius), offset_x, offset_y):
        return {"id": item_id, "status": "failed", "reason": "draw_outer_failed"}
    if not _draw_loop(sketch, _rounded_rect_points(ix0, iy0, ix1, iy1, inner_radius), offset_x, offset_y):
        return {"id": item_id, "status": "failed", "reason": "draw_inner_failed"}
    outer_area = _rounded_rect_area_mm2(x0, y0, x1, y1, radius)
    inner_area = _rounded_rect_area_mm2(ix0, iy0, ix1, iy1, inner_radius)
    profile = _profile_closest_to_area(sketch, outer_area - inner_area)
    if profile is None:
        return {"id": item_id, "status": "failed", "reason": "no_ring_profile"}
    ext_input = component.features.extrudeFeatures.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(depth)))
    try:
        participants = adsk.core.ObjectCollection.create()
        participants.add(body)
        ext_input.participantBodies = participants
    except Exception:
        pass
    try:
        cut = component.features.extrudeFeatures.add(ext_input)
        cut.name = "LOUNGE_CUT_FEAT_{}".format(sanitize_token(item_id, limit=60))
        return {"id": item_id, "status": "created", "depth": depth, "inset": inset, "zTop": top_z}
    except Exception as ex:
        return {"id": item_id, "status": "failed", "reason": str(ex)}


def _apply_flat_panel_cuts(component, body, item, offset_x, offset_y):
    audits = []
    thickness = max(0.1, _num(item.get("thickness"), 18))
    opening = item.get("opening") if isinstance(item.get("opening"), dict) else None
    if opening:
        step_w = _num(opening.get("stepWidth"), thickness / 2.0)
        step_h = _num(opening.get("stepHeight"), thickness / 2.0)
        # Outer rebate / shoulder.
        audits.append(_cut_rounded_rect_from_top(
            component, body, "{}_rebate".format(item.get("id")),
            _num(opening.get("x0")), _num(opening.get("y0")),
            _num(opening.get("x1")), _num(opening.get("y1")),
            _num(opening.get("radius"), 50),
            min(step_h, thickness),
            offset_x, offset_y,
        ))
        # Through opening inside the shoulder.
        audits.append(_cut_rounded_rect_from_top(
            component, body, "{}_through_opening".format(item.get("id")),
            _num(opening.get("x0")) + step_w, _num(opening.get("y0")) + step_w,
            _num(opening.get("x1")) - step_w, _num(opening.get("y1")) - step_w,
            max(0.0, _num(opening.get("radius"), 50) - step_w),
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


def _item_size(item):
    outer = _item_outer_points(item)
    xs = [_num(p[0]) for p in outer]
    ys = [_num(p[1]) for p in outer]
    return max(xs) - min(xs), max(ys) - min(ys)


def _add_flat_panel_body(component, item, offset_x, offset_y, preview_mode="flat_svg"):
    item_id = str(item.get("id") or "panel")
    thickness = max(0.1, _num(item.get("thickness"), 18))
    sketch = component.sketches.add(component.xYConstructionPlane)
    sketch.name = "LOUNGE_FLAT_SK_{}".format(sanitize_token(item_id, limit=60))
    if not _draw_loop(sketch, _item_outer_points(item), offset_x, offset_y):
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
        if item.get("kind") == "lid":
            y1 = _num(placement.get("y1"))
            z1 = _num(placement.get("z1"))
            # Flip lids over so the stepped face is on the opposite side after assembly.
            # Local flat axes: X=width, Y=depth, Z=thickness.
            # Assembly axes: X=width, Y=-depth, Z=-thickness.
            matrix.setCell(0, 0, 1)
            matrix.setCell(0, 1, 0)
            matrix.setCell(0, 2, 0)
            matrix.setCell(0, 3, mm_to_cm(x0 - ox))
            matrix.setCell(1, 0, 0)
            matrix.setCell(1, 1, -1)
            matrix.setCell(1, 2, 0)
            matrix.setCell(1, 3, mm_to_cm(y1 + oy))
            matrix.setCell(2, 0, 0)
            matrix.setCell(2, 1, 0)
            matrix.setCell(2, 2, -1)
            matrix.setCell(2, 3, mm_to_cm(z1))
            return matrix
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


def create_lounge_bodies(fusion_adapter, result, run_label=None):
    summary = {
        "ok": True,
        "module": "lounge",
        "action": "lounge.createFlatBodies",
        "createdBodies": 0,
        "createdIds": [],
        "skipped": [],
        "cutAudit": [],
        "errors": [],
        "warnings": ["Phase 1 Lounge flat bodies: SVG profiles only; stepped recess depths are not modeled yet."],
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
    component, component_name, component_warning = _new_lounge_component(root, summary["runLabel"], "flat")
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
        body, err = _add_flat_panel_body(component, item, cursor_x, row_y)
        if err:
            summary["skipped"].append({"id": item.get("id"), "reason": err})
            continue
        summary["cutAudit"].extend(_apply_flat_panel_cuts(component, body, item, cursor_x, row_y))
        summary["createdBodies"] += 1
        summary["createdIds"].append(item.get("id"))
        cursor_x += width + gap
        row_h = max(row_h, depth)
    summary["modelZOffset"] = {"offsetMm": MODEL_Z_OFFSET_MM, "movedBodies": 0, "failedBodies": 0, "mode": "componentAtModelZ"}
    return summary


def create_lounge_assembly_bodies(fusion_adapter, result, run_label=None):
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
        "warnings": ["Phase 1 Lounge assembly: bodies are created from flat profiles, then rigidly transformed by placement/profilePlane."],
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
    component, component_name, component_warning = _new_lounge_component(root, summary["runLabel"], "assembly")
    summary["assemblyComponentName"] = component_name
    if component_warning:
        summary["warnings"].append(component_warning)
    panels = result.get("panels") if isinstance(result.get("panels"), list) else []
    lids = result.get("lids") if isinstance(result.get("lids"), list) else []
    items = [item for item in panels + lids if isinstance(item, dict)]
    staged = []
    cursor_x = 0.0
    row_y = 0.0
    row_h = 0.0
    max_row_w = 3200.0
    gap = 160.0
    for item in items:
        item_id = item.get("id")
        width, depth = _item_size(item)
        if cursor_x > 0 and cursor_x + width > max_row_w:
            cursor_x = 0.0
            row_y += row_h + gap
            row_h = 0.0
        stage_x = cursor_x
        stage_y = row_y
        body, err = _add_flat_panel_body(component, item, stage_x, stage_y, preview_mode="assembly")
        if err:
            summary["skipped"].append({"id": item_id, "reason": err})
            cursor_x += width + gap
            row_h = max(row_h, depth)
            continue
        summary["cutAudit"].extend(_apply_flat_panel_cuts(component, body, item, stage_x, stage_y))
        staged.append({"item": item, "body": body, "offsetX": stage_x, "offsetY": stage_y})
        cursor_x += width + gap
        row_h = max(row_h, depth)

    for staged_item in staged:
        item = staged_item["item"]
        body = staged_item["body"]
        item_id = item.get("id")
        transform = _assembly_transform_for_item(item, staged_item["offsetX"], staged_item["offsetY"])
        if transform is None:
            summary["skipped"].append({"id": item_id, "reason": "unsupported profilePlane {}".format(item.get("profilePlane"))})
            continue
        try:
            _move_body_rigid_transform(component, body, transform, feature_prefix="LOUNGE_ASM_MOVE_")
            summary["transformAudit"].append({
                "id": item_id,
                "profilePlane": item.get("profilePlane"),
                "placement": item.get("placement"),
                "stagingOffset": {"x": staged_item["offsetX"], "y": staged_item["offsetY"]},
                "status": "moved",
            })
        except Exception as ex:
            summary["errors"].append("Move failed for {}: {}".format(item_id, ex))
            continue
        summary["createdBodies"] += 1
        summary["createdIds"].append(item_id)
    summary["modelZOffset"] = {"offsetMm": MODEL_Z_OFFSET_MM, "movedBodies": 0, "failedBodies": 0, "mode": "componentAtModelZ"}
    return summary
