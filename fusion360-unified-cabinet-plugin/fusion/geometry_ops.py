import adsk.core


ATTRIBUTE_GROUP = "UnifiedCabinetPlugin"
MODEL_Z_OFFSET_MM = 10000.0


def mm_to_cm(value_mm):
    return float(value_mm) / 10.0


def sanitize_token(value, fallback="item", limit=80):
    out = []
    for ch in str(value or fallback):
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
        else:
            out.append("_")
    return ("".join(out) or fallback)[:limit]


def move_body_by_mm(root_comp, body, dx_mm, dy_mm, dz_mm, feature_prefix="UCP_MOVE_"):
    if abs(dx_mm) < 0.001 and abs(dy_mm) < 0.001 and abs(dz_mm) < 0.001:
        return None
    bodies = adsk.core.ObjectCollection.create()
    bodies.add(body)
    transform = adsk.core.Matrix3D.create()
    transform.translation = adsk.core.Vector3D.create(mm_to_cm(dx_mm), mm_to_cm(dy_mm), mm_to_cm(dz_mm))
    move_input = root_comp.features.moveFeatures.createInput(bodies, transform)
    try:
        move_input.defineAsFreeMove(transform)
    except Exception:
        pass
    move_feature = root_comp.features.moveFeatures.add(move_input)
    move_feature.name = "{}{}".format(feature_prefix, sanitize_token(getattr(body, "name", "body"), limit=40))
    return move_feature


def body_min_mm(body):
    point = body.boundingBox.minPoint
    return point.x * 10.0, point.y * 10.0, point.z * 10.0


def move_body_min_corner_to(root_comp, body, target_x_mm, target_y_mm, target_z_mm, feature_prefix="UCP_MOVE_"):
    min_x, min_y, min_z = body_min_mm(body)
    return move_body_by_mm(
        root_comp,
        body,
        target_x_mm - min_x,
        target_y_mm - min_y,
        target_z_mm - min_z,
        feature_prefix=feature_prefix,
    )


def body_matches_module(body, name_prefixes=None, module=None, preview_mode=None):
    name = str(getattr(body, "name", "") or "")
    if name_prefixes:
        for prefix in name_prefixes:
            if name.startswith(str(prefix)):
                return True
    try:
        attrs = body.attributes
        if module is not None:
            attr = attrs.itemByName(ATTRIBUTE_GROUP, "module")
            if attr and str(attr.value) == str(module):
                if preview_mode is None:
                    return True
                mode_attr = attrs.itemByName(ATTRIBUTE_GROUP, "previewMode")
                return bool(mode_attr and str(mode_attr.value) == str(preview_mode))
    except Exception:
        pass
    return False


def offset_bodies_z_mm(root_comp, bodies, dz_mm=MODEL_Z_OFFSET_MM, feature_prefix="UCP_MODEL_Z_OFFSET_"):
    moved = 0
    failed = 0
    if not root_comp or not bodies or abs(dz_mm) < 0.001:
        return {"offsetMm": dz_mm, "movedBodies": 0, "failedBodies": 0}
    collection = adsk.core.ObjectCollection.create()
    for body in bodies:
        try:
            collection.add(body)
        except Exception:
            failed += 1
    if collection.count < 1:
        return {"offsetMm": dz_mm, "movedBodies": 0, "failedBodies": failed}
    transform = adsk.core.Matrix3D.create()
    transform.translation = adsk.core.Vector3D.create(0, 0, mm_to_cm(dz_mm))
    try:
        move_input = root_comp.features.moveFeatures.createInput(collection, transform)
        try:
            move_input.defineAsFreeMove(transform)
        except Exception:
            pass
        move_feature = root_comp.features.moveFeatures.add(move_input)
        move_feature.name = "{}{}mm".format(feature_prefix, int(dz_mm))
        moved = collection.count
    except Exception:
        failed += collection.count
    return {"offsetMm": dz_mm, "movedBodies": moved, "failedBodies": failed}


def offset_matching_bodies_z_mm(
    root_comp,
    name_prefixes=None,
    module=None,
    preview_mode=None,
    dz_mm=MODEL_Z_OFFSET_MM,
    feature_prefix="UCP_MODEL_Z_OFFSET_",
):
    bodies = []
    try:
        count = root_comp.bRepBodies.count
    except Exception:
        count = 0
    for idx in range(count):
        try:
            body = root_comp.bRepBodies.item(idx)
            if body_matches_module(body, name_prefixes=name_prefixes, module=module, preview_mode=preview_mode):
                bodies.append(body)
        except Exception:
            pass
    result = offset_bodies_z_mm(root_comp, bodies, dz_mm=dz_mm, feature_prefix=feature_prefix)
    result["matchedBodies"] = len(bodies)
    return result


# Generation-zone spawn avoidance (shared by fridge, general_tall, etc.)
GENERATION_AVOID_GAP_MM = 300.0
GENERATION_AVOID_MAX_SLOTS = 40
GENERATION_AVOID_Z_LIMIT_MM = 5000.0  # ignore legacy 10 km staging bodies


def capture_position_snapshot(root_comp):
    """Commit pending occurrence transforms so later timeline edits keep them."""
    try:
        design = root_comp.parentDesign
        if not design or not design.snapshots:
            return
        if design.snapshots.hasPendingSnapshot:
            design.snapshots.add()
            return
        # Some Fusion builds leave hasPendingSnapshot false after occurrence.transform=
        # even though the pose still needs committing. Try a forced add; ignore if empty.
        try:
            design.snapshots.add()
        except Exception:
            pass
    except Exception:
        pass


def collect_existing_ground_bboxes_mm(root_comp):
    """World-space XY bounding boxes of existing assemblies near the ground.

    Uses each root-level occurrence's bounding box (model space).  Scanning
    nested body.boundingBox without the occurrence chain leaves everything near
    local (0,0) and breaks spawn avoidance between fridge / kitchen / etc.
    """
    boxes = []
    seen = set()

    def _append_rect(rect):
        if rect is None:
            return
        key = tuple(round(float(v), 1) for v in rect)
        if key in seen:
            return
        seen.add(key)
        boxes.append(rect)

    def _rect_from_bounding_box(bb):
        try:
            z0 = bb.minPoint.z * 10.0
            if z0 > GENERATION_AVOID_Z_LIMIT_MM:
                return None
            return (
                bb.minPoint.x * 10.0, bb.minPoint.y * 10.0,
                bb.maxPoint.x * 10.0, bb.maxPoint.y * 10.0,
            )
        except Exception:
            return None

    try:
        for index in range(root_comp.occurrences.count):
            occurrence = root_comp.occurrences.item(index)
            try:
                _append_rect(_rect_from_bounding_box(occurrence.boundingBox))
            except Exception:
                continue
    except Exception:
        pass
    try:
        for index in range(root_comp.bRepBodies.count):
            body = root_comp.bRepBodies.item(index)
            try:
                if not body.isSolid:
                    continue
                _append_rect(_rect_from_bounding_box(body.boundingBox))
            except Exception:
                continue
    except Exception:
        pass
    return boxes


def rects_overlap_mm(rect_a, rect_b, gap_mm):
    return not (
        rect_a[2] + gap_mm <= rect_b[0] or rect_b[2] + gap_mm <= rect_a[0] or
        rect_a[3] + gap_mm <= rect_b[1] or rect_b[3] + gap_mm <= rect_a[1]
    )


def avoid_existing_at_origin(root_comp, origin_x_mm, origin_y_mm, footprint_mm):
    """Shift spawn origin +X in footprint-sized slots until clear.

    ``footprint_mm``: (min_x, max_x, min_y, max_y) of new content in design
    coordinates relative to the spawn origin. Returns (x, y, info-dict).
    """
    info = {"shifted": False, "slots": 0}
    if not footprint_mm:
        return origin_x_mm, origin_y_mm, info
    try:
        existing = collect_existing_ground_bboxes_mm(root_comp)
        if not existing:
            return origin_x_mm, origin_y_mm, info
        width = max(float(footprint_mm[1]) - float(footprint_mm[0]), 1.0)
        step = width + GENERATION_AVOID_GAP_MM
        for slot in range(GENERATION_AVOID_MAX_SLOTS):
            candidate_x = float(origin_x_mm) + slot * step
            rect = (
                candidate_x + float(footprint_mm[0]),
                float(origin_y_mm) + float(footprint_mm[2]),
                candidate_x + float(footprint_mm[1]),
                float(origin_y_mm) + float(footprint_mm[3]),
            )
            if not any(rects_overlap_mm(rect, box, GENERATION_AVOID_GAP_MM) for box in existing):
                info["shifted"] = slot > 0
                info["slots"] = slot
                info["shiftXMm"] = slot * step
                return candidate_x, float(origin_y_mm), info
        info["exhausted"] = True
    except Exception as ex:
        info["error"] = str(ex)
    return origin_x_mm, origin_y_mm, info
