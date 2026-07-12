"""Fusion creation of grouped Nesting Zone workpiece copies."""

from __future__ import annotations

import json
import math
import time

import adsk.core
import adsk.fusion

try:
    from nesting.layout import grouped_row_layout
except Exception:
    from layout import grouped_row_layout


OUTPUT_MARKER_GROUP = "UnifiedCabinet"
OUTPUT_MARKER_NAME = "systemRole"
OUTPUT_MARKER_VALUE = "nestingOutput"
INSTANCE_ROLE_NAME = "instanceRole"
INSTANCE_ROLE_NESTED = "nested"
WORKPIECE_GROUP = "UnifiedCabinet.NestingWorkpiece"
LAYOUT_COMPONENT_NAME = "NESTING_LAYOUT"


def _set_attr(entity, group, name, value):
    attrs = getattr(entity, "attributes", None)
    if attrs is None:
        return False
    existing = attrs.itemByName(group, name)
    if existing is not None:
        existing.value = str(value)
    else:
        attrs.add(group, name, str(value))
    return True


def _attr(entity, group, name):
    try:
        item = entity.attributes.itemByName(group, name)
        return str(item.value or "") if item else ""
    except Exception:
        return ""


def _delete_attr(entity, group, name):
    try:
        item = entity.attributes.itemByName(group, name)
        if item:
            item.deleteMe()
    except Exception:
        pass


def delete_previous_layouts(root_component, exclude_component=None):
    """Delete root occurrences created by previous layout runs."""
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
            if (
                component is exclude_component
                or (exclude_token and component_token == exclude_token)
            ):
                continue
            marked = (
                _attr(component, OUTPUT_MARKER_GROUP, OUTPUT_MARKER_NAME)
                == OUTPUT_MARKER_VALUE
            )
            if not marked:
                continue
            occurrence.deleteMe()
            deleted += 1
        except Exception:
            continue
    return deleted


def _vec_dot(a, b):
    return sum(float(a[i]) * float(b[i]) for i in range(3))


def _vec_cross(a, b):
    return [
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    ]


def _vec_length(a):
    return max(sum(float(v) * float(v) for v in a) ** 0.5, 0.0)


def _vec_unit(a):
    length = _vec_length(a)
    if length <= 1e-9:
        return [0.0, 0.0, 1.0]
    return [float(v) / length for v in a]


def rotation_from_to(from_vec, to_vec):
    """Return (angle_radians, unit_axis), including opposite vectors."""
    source = _vec_unit(from_vec)
    target = _vec_unit(to_vec)
    dot = max(-1.0, min(1.0, _vec_dot(source, target)))
    if dot >= 1.0 - 1e-9:
        return 0.0, [1.0, 0.0, 0.0]
    if dot <= -1.0 + 1e-9:
        ref = [1.0, 0.0, 0.0] if abs(source[0]) < 0.9 else [0.0, 1.0, 0.0]
        return math.pi, _vec_unit(_vec_cross(source, ref))
    return math.acos(dot), _vec_unit(_vec_cross(source, target))


def _rotation_matrix(from_vec, to_vec):
    angle, axis = rotation_from_to(from_vec, to_vec)
    matrix = adsk.core.Matrix3D.create()
    if abs(angle) <= 1e-9:
        return matrix
    matrix.setToRotation(
        angle,
        adsk.core.Vector3D.create(axis[0], axis[1], axis[2]),
        adsk.core.Point3D.create(0, 0, 0),
    )
    return matrix


def _z_rotation_matrix(degrees):
    matrix = adsk.core.Matrix3D.create()
    matrix.setToRotation(
        math.radians(float(degrees)),
        adsk.core.Vector3D.create(0, 0, 1),
        adsk.core.Point3D.create(0, 0, 0),
    )
    return matrix


def _translation_matrix(dx_mm, dy_mm, dz_mm):
    matrix = adsk.core.Matrix3D.create()
    matrix.translation = adsk.core.Vector3D.create(
        float(dx_mm) / 10.0,
        float(dy_mm) / 10.0,
        float(dz_mm) / 10.0,
    )
    return matrix


def _bbox_dimensions_mm(body):
    bbox = body.boundingBox
    return {
        "minX": bbox.minPoint.x * 10.0,
        "minY": bbox.minPoint.y * 10.0,
        "minZ": bbox.minPoint.z * 10.0,
        "widthMm": (bbox.maxPoint.x - bbox.minPoint.x) * 10.0,
        "depthMm": (bbox.maxPoint.y - bbox.minPoint.y) * 10.0,
        "heightMm": (bbox.maxPoint.z - bbox.minPoint.z) * 10.0,
    }


def _face_token(face):
    try:
        return str(face.entityToken or "")
    except Exception:
        return ""


def _registry_role(face, metadata):
    token = _face_token(face)
    registry = (metadata or {}).get("faceRegistry") or {}
    for entry in registry.get("faces") or []:
        if not isinstance(entry, dict):
            continue
        if token and str(entry.get("entityToken") or "") == token:
            return str(entry.get("millingSurface") or "").upper()
    return ""


def _fast_broad_faces(body):
    """Pick two broad faces without evaluating normals on every pocket face.

    Cost is O(faces) for area only, then normals on the top few area candidates.
    """
    try:
        from panel_face_initializer import face_area_mm2, iter_body_faces
        from milling_surface_propagation import face_world_plane
    except Exception:
        try:
            from metadata.panel_face_initializer import face_area_mm2, iter_body_faces
            from panel_attributes.milling_surface_propagation import face_world_plane
        except Exception:
            return None, None
    faces = list(iter_body_faces(body) or [])
    if len(faces) < 2:
        return None, None
    ranked = []
    for face in faces:
        try:
            ranked.append((float(face_area_mm2(face) or 0.0), face))
        except Exception:
            continue
    ranked.sort(key=lambda item: item[0], reverse=True)
    candidates = [face for _area, face in ranked[:8]]
    if len(candidates) < 2:
        return None, None
    primary = candidates[0]
    primary_normal, _ = face_world_plane(primary)
    if not primary_normal:
        return primary, candidates[1]
    opposite = None
    for face in candidates[1:]:
        normal, _ = face_world_plane(face)
        if not normal:
            continue
        dot = sum(float(primary_normal[i]) * float(normal[i]) for i in range(3))
        if dot <= -0.5:
            opposite = face
            break
    if opposite is None:
        opposite = candidates[1]
    return primary, opposite


def cutting_face_and_normal(body, metadata, required_face_up):
    """Return source broad face and outward world normal."""
    try:
        from milling_surface_propagation import (
            _current_milling_role,
            face_world_plane,
        )
    except Exception:
        return None, None
    surface_a, surface_b = _fast_broad_faces(body)
    if surface_a is None or surface_b is None:
        # Fallback to full classifier only if the fast path fails.
        try:
            from milling_surface_propagation import classify_body_surfaces
            surface_a, surface_b, _warnings = classify_body_surfaces(body)
        except Exception:
            return None, None
    if surface_a is None or surface_b is None:
        return None, None
    target = None
    if str(required_face_up or "").upper() == "MILLING":
        for face in (surface_a, surface_b):
            # Prefer stored registry — face attribute reads are expensive.
            role = _registry_role(face, metadata) or _current_milling_role(face)
            if str(role).upper() == "MILLING":
                target = face
                break
    elif str(required_face_up or "").upper() == "EITHER":
        target = surface_a
    if target is None:
        return None, None
    normal, _centroid = face_world_plane(target)
    return target, normal


def prepare_flat_copy(source_body, metadata, required_face_up):
    """Copy source proxy into a transient body and orient cutting face +Z."""
    _face, normal = cutting_face_and_normal(
        source_body, metadata, required_face_up
    )
    if not normal:
        raise ValueError("Could not resolve cutting-face world normal.")
    temp_manager = adsk.fusion.TemporaryBRepManager.get()
    temp_body = temp_manager.copy(source_body)
    if temp_body is None:
        raise ValueError("TemporaryBRepManager.copy returned no body.")

    temp_manager.transform(
        temp_body,
        _rotation_matrix(normal, [0.0, 0.0, 1.0]),
    )
    dims = _bbox_dimensions_mm(temp_body)
    # Deterministic in-plane orientation: longest bounding direction along +X.
    if dims["depthMm"] > dims["widthMm"] + 1e-6:
        temp_manager.transform(temp_body, _z_rotation_matrix(-90.0))
        dims = _bbox_dimensions_mm(temp_body)
    return temp_body, dims


def _strip_panel_attributes(body):
    # TemporaryBRep copies do not carry face custom attributes; only clear
    # body-level panel identity so Nesting workpieces stay isolated.
    _delete_attr(body, "UnifiedCabinet.Panel", "panelId")
    _delete_attr(body, "UnifiedCabinet.Panel", "metadata")


def _mark_workpiece(body, placement, run_id):
    _strip_panel_attributes(body)
    _set_attr(
        body,
        OUTPUT_MARKER_GROUP,
        INSTANCE_ROLE_NAME,
        INSTANCE_ROLE_NESTED,
    )
    _set_attr(
        body,
        OUTPUT_MARKER_GROUP,
        OUTPUT_MARKER_NAME,
        "nestingWorkpiece",
    )
    details = {
        "runId": run_id,
        "sourcePanelId": placement.get("panelId") or "",
        "sourceBodyName": placement.get("bodyName") or "",
        "boardTypeTag": placement.get("boardTypeTag") or "",
        "colorTag": placement.get("colorTag") or "",
        "groupIndex": placement.get("groupIndex"),
        "itemIndex": placement.get("itemIndex"),
    }
    for key, value in details.items():
        _set_attr(body, WORKPIECE_GROUP, key, value)
    _set_attr(body, WORKPIECE_GROUP, "metadata", json.dumps(details))


def create_layout(
    root_component,
    prepared_items,
    nesting_rect,
    part_gap_mm,
    group_gap_mm,
    profiler=None,
):
    """Replace prior output and create one marked root-level layout component."""
    import time as _time

    if not prepared_items:
        return {
            "created": 0,
            "deletedPrevious": 0,
            "groups": [],
            "placements": [],
        }
    if not isinstance(nesting_rect, dict):
        raise ValueError("Nesting Zone is not configured.")

    layout = grouped_row_layout(
        [
            {
                **item,
                "widthMm": item["dimensions"]["widthMm"],
                "depthMm": item["dimensions"]["depthMm"],
            }
            for item in prepared_items
        ],
        nesting_rect["x0"],
        nesting_rect["y0"],
        part_gap_mm,
        group_gap_mm,
    )
    zone_width = float(nesting_rect["x1"]) - float(nesting_rect["x0"])
    zone_depth = float(nesting_rect["y1"]) - float(nesting_rect["y0"])
    if (
        layout["requiredWidthMm"] > zone_width + 1e-6
        or layout["requiredDepthMm"] > zone_depth + 1e-6
    ):
        # Controller should expand Nesting Zone before calling create_layout.
        raise ValueError(
            "Layout needs {:.0f} x {:.0f} mm; Nesting Zone is still {:.0f} x {:.0f} mm "
            "after size check (zone should have been expanded first).".format(
                layout["requiredWidthMm"],
                layout["requiredDepthMm"],
                zone_width,
                zone_depth,
            )
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
    run_id = "nest-{}".format(int(time.time() * 1000))
    _set_attr(component, OUTPUT_MARKER_GROUP, OUTPUT_MARKER_NAME, OUTPUT_MARKER_VALUE)
    _set_attr(component, OUTPUT_MARKER_GROUP, "runId", run_id)

    by_id = {str(item["id"]): item for item in prepared_items}
    temp_manager = adsk.fusion.TemporaryBRepManager.get()
    created = []
    pending_marks = []
    base_feature = component.features.baseFeatures.add()
    base_feature.name = "NESTING_WORKPIECES_{}".format(run_id)
    base_feature.startEdit()
    try:
        for index, placement in enumerate(layout["placements"]):
            item_t0 = _time.perf_counter()
            item = by_id[str(placement["id"])]
            temp_body = item["tempBody"]
            dims = _bbox_dimensions_mm(temp_body)
            temp_manager.transform(
                temp_body,
                _translation_matrix(
                    placement["targetX"] - dims["minX"],
                    placement["targetY"] - dims["minY"],
                    -dims["minZ"],
                ),
            )
            new_body = component.bRepBodies.add(temp_body, base_feature)
            new_body.name = "NEST_{:02d}_{:03d}_{}".format(
                placement["groupIndex"] + 1,
                placement["itemIndex"] + 1,
                str(placement.get("bodyName") or "panel"),
            )
            pending_marks.append((new_body, placement))
            item_ms = int((_time.perf_counter() - item_t0) * 1000)
            if profiler is not None:
                profiler.add("createdBodies", 1)
                if item_ms >= 250:
                    profiler.sample("createBody", item_ms, bodyName=new_body.name)
                if (index + 1) % 10 == 0:
                    profiler.mark("createProgress", created=index + 1)
    except Exception:
        try:
            base_feature.finishEdit()
        except Exception:
            pass
        try:
            occurrence.deleteMe()
        except Exception:
            pass
        raise
    else:
        base_feature.finishEdit()

    for new_body, placement in pending_marks:
        _mark_workpiece(new_body, placement, run_id)
        created.append(
            {
                "bodyName": new_body.name,
                "sourcePanelId": placement.get("panelId") or "",
                "boardTypeTag": placement.get("boardTypeTag") or "",
                "colorTag": placement.get("colorTag") or "",
                "groupIndex": placement["groupIndex"],
                "targetX": placement["targetX"],
                "targetY": placement["targetY"],
            }
        )

    if profiler is not None:
        profiler.begin("deletePrevious")
    deleted = delete_previous_layouts(
        root_component, exclude_component=component
    )
    if profiler is not None:
        profiler.end("deletePrevious")
        profiler.mark("createDone", created=len(created), deleted=deleted)
    return {
        "created": len(created),
        "deletedPrevious": deleted,
        "runId": run_id,
        "componentName": component.name,
        "groups": layout["groups"],
        "placements": created,
        "requiredWidthMm": layout["requiredWidthMm"],
        "requiredDepthMm": layout["requiredDepthMm"],
    }
