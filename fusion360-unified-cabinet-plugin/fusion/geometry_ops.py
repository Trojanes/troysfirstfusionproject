import adsk.core


ATTRIBUTE_GROUP = "UnifiedCabinetPlugin"
MODEL_Z_OFFSET_MM = 10000.0
IDENTITY_ATTR_GROUPS = (
    "CabinetNC",
    "UnifiedCabinetPlugin",
    "UnifiedCabinet",
    "UnifiedCabinet.Panel",
)
MODULE_NAME_PREFIXES = {
    "kitchen": ("KITCHEN_", "K_", "Kitchen-"),
    "lounge": ("LOUNGE_", "L_", "Lounge-"),
    "general_tall": ("GT_", "GT-"),
    "overhead": ("OH_", "OHC-", "OHC_"),
    "small_cabinet": ("SC_", "SC-"),
    "u_shape_overhead": ("UOH_", "U Shape OHC-"),
}


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


def entity_attr(entity, name):
    """Read an identity attribute from any known generator group."""
    if not entity:
        return ""
    try:
        attrs = entity.attributes
    except Exception:
        return ""
    if not attrs:
        return ""
    for group in IDENTITY_ATTR_GROUPS:
        try:
            attr = attrs.itemByName(group, name)
            if attr and attr.value:
                return str(attr.value).strip()
        except Exception:
            pass
    return ""


def entity_module(entity):
    return entity_attr(entity, "module")


def entity_board_id(entity):
    return entity_attr(entity, "boardId") or entity_attr(entity, "bodyId")


def entity_assembly_name(entity):
    return entity_attr(entity, "assemblyName")


def name_looks_like_module(name, module):
    """Legacy browser-name fallback. Display names are not identity."""
    text = str(name or "")
    if not text:
        return False
    for prefix in MODULE_NAME_PREFIXES.get(str(module or ""), ()):
        if text.startswith(prefix):
            return True
    return False


def is_module_artifact(entity, module, name=None):
    """True when entity belongs to ``module`` (attribute first, name last)."""
    found = entity_module(entity)
    if found:
        return found == str(module or "")
    if name is None:
        try:
            name = getattr(entity, "name", "") or ""
        except Exception:
            name = ""
    return name_looks_like_module(name, module)


def body_matches_module(body, name_prefixes=None, module=None, preview_mode=None):
    found_module = entity_module(body)
    if module is not None and found_module:
        if found_module != str(module):
            return False
        if preview_mode is None:
            return True
        return entity_attr(body, "previewMode") == str(preview_mode)
    name = str(getattr(body, "name", "") or "")
    if name_prefixes:
        for prefix in name_prefixes:
            if name.startswith(str(prefix)):
                return True
    if module is not None and name_looks_like_module(name, module):
        if preview_mode is None:
            return True
        return entity_attr(body, "previewMode") == str(preview_mode)
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


def _xy_rect_from_bbox_cm(bb):
    """Convert a Fusion bounding box (cm) to (minX, minY, maxX, maxY) mm."""
    try:
        z0 = bb.minPoint.z * 10.0
        if z0 > GENERATION_AVOID_Z_LIMIT_MM:
            return None
        x0 = bb.minPoint.x * 10.0
        y0 = bb.minPoint.y * 10.0
        x1 = bb.maxPoint.x * 10.0
        y1 = bb.maxPoint.y * 10.0
        if x1 <= x0 or y1 <= y0:
            return None
        return (x0, y0, x1, y1)
    except Exception:
        return None


def _world_rect_from_occurrence_mm(occurrence):
    """Root-occurrence XY box in model millimetres (not local child space)."""
    try:
        rect = _xy_rect_from_bbox_cm(occurrence.boundingBox)
        if rect is not None:
            return rect
    except Exception:
        pass
    try:
        bb = occurrence.component.boundingBox
        transform = occurrence.transform
        corners = []
        for x in (bb.minPoint.x, bb.maxPoint.x):
            for y in (bb.minPoint.y, bb.maxPoint.y):
                for z in (bb.minPoint.z, bb.maxPoint.z):
                    point = adsk.core.Point3D.create(x, y, z)
                    point.transformBy(transform)
                    corners.append(point)
        xs = [p.x * 10.0 for p in corners]
        ys = [p.y * 10.0 for p in corners]
        zs = [p.z * 10.0 for p in corners]
        if min(zs) > GENERATION_AVOID_Z_LIMIT_MM:
            return None
        if max(xs) <= min(xs) or max(ys) <= min(ys):
            return None
        return (min(xs), min(ys), max(xs), max(ys))
    except Exception:
        return None


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

    try:
        for index in range(root_comp.occurrences.count):
            occurrence = root_comp.occurrences.item(index)
            try:
                _append_rect(_world_rect_from_occurrence_mm(occurrence))
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
                _append_rect(_xy_rect_from_bbox_cm(body.boundingBox))
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
    info = {"shifted": False, "slots": 0, "existingCount": 0}
    if not footprint_mm:
        return origin_x_mm, origin_y_mm, info
    try:
        existing = collect_existing_ground_bboxes_mm(root_comp)
        info["existingCount"] = len(existing)
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
