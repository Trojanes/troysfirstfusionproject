"""Fusion CAD operations for relationship-based screw hole cuts."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import adsk.core
import adsk.fusion

from geometry_ops import ATTRIBUTE_GROUP, mm_to_cm, sanitize_token


def _bbox_mm(body) -> Dict[str, float]:
    bbox = body.boundingBox
    min_pt = bbox.minPoint
    max_pt = bbox.maxPoint
    return {
        "x0": min_pt.x * 10.0,
        "x1": max_pt.x * 10.0,
        "y0": min_pt.y * 10.0,
        "y1": max_pt.y * 10.0,
        "z0": min_pt.z * 10.0,
        "z1": max_pt.z * 10.0,
    }


def _axis_bounds(bbox: Dict[str, float], axis: str) -> Tuple[float, float]:
    key0 = "{}0".format(axis.lower())
    key1 = "{}1".format(axis.lower())
    return bbox[key0], bbox[key1]


def _drill_is_negative(contact_axis: str, host_face_mm: float, host_bbox: Dict[str, float]) -> bool:
    axis_min, axis_max = _axis_bounds(host_bbox, contact_axis)
    center = (axis_min + axis_max) / 2.0
    if abs(host_face_mm - axis_max) <= abs(host_face_mm - axis_min):
        return center < host_face_mm
    return center > host_face_mm


def _plane_and_point(
    component,
    contact_axis: str,
    position: Dict[str, float],
):
    x = float(position["x"])
    y = float(position["y"])
    z = float(position["z"])
    if contact_axis == "X":
        return component.yZConstructionPlane, mm_to_cm(x), adsk.core.Point3D.create(mm_to_cm(x), mm_to_cm(y), mm_to_cm(z))
    if contact_axis == "Y":
        return component.xZConstructionPlane, mm_to_cm(y), adsk.core.Point3D.create(mm_to_cm(x), mm_to_cm(y), mm_to_cm(z))
    if contact_axis == "Z":
        return component.xYConstructionPlane, mm_to_cm(z), adsk.core.Point3D.create(mm_to_cm(x), mm_to_cm(y), mm_to_cm(z))
    raise ValueError("Unsupported contact axis: {}".format(contact_axis))


def _resolve_body_in_component(component, host_body):
    if not component or not host_body:
        return host_body
    try:
        for index in range(component.bRepBodies.count):
            body = component.bRepBodies.item(index)
            if body == host_body:
                return body
            if getattr(body, "name", None) and body.name == getattr(host_body, "name", None):
                return body
    except Exception:
        pass
    return host_body


def _set_host_participant_bodies(ext_input, host_body) -> None:
    """Match side-contact cut pattern: Fusion expects a list of BRepBody, not ObjectCollection."""
    try:
        ext_input.participantBodies = [host_body]
        return
    except Exception as first_error:
        last_error = first_error
    try:
        participants = adsk.core.ObjectCollection.create()
        participants.add(host_body)
        ext_input.participantBodies = participants
        return
    except Exception as second_error:
        last_error = second_error
    raise ValueError("HOST_ONLY_CUT_NOT_AVAILABLE: {}".format(last_error))


def create_host_screw_hole_cut(
    component,
    host_body,
    feature: Dict[str, Any],
    metadata: Dict[str, Any],
    *,
    name_prefix: str = "HW_REL_SCREW_HOLE",
) -> Tuple[Any, bool]:
    """Host-only circular hole cut. Same path for screw_hole and hinge_hole cups."""
    geometry = feature.get("geometry") or {}
    contact_axis = str(geometry.get("axis") or "Y")
    diameter_mm = float(geometry.get("diameterMm") or 4.0)
    depth_mm = float(geometry.get("depthMm") or 0.0)
    positions = geometry.get("positions") or []
    if not positions or depth_mm <= 0:
        raise ValueError("Feature geometry must include positions and positive depthMm.")

    prefix = str(name_prefix or "HW_REL_SCREW_HOLE").strip() or "HW_REL_SCREW_HOLE"
    host_body = _resolve_body_in_component(component, host_body)

    host_bbox = _bbox_mm(host_body)
    host_face_mm = float(positions[0][contact_axis.lower()])
    drill_negative = _drill_is_negative(contact_axis, host_face_mm, host_bbox)

    base_plane, plane_offset_cm, _ = _plane_and_point(component, contact_axis, positions[0])
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    plane_input.setByOffset(base_plane, adsk.core.ValueInput.createByReal(plane_offset_cm))
    plane = construction.add(plane_input)
    plane.name = "{}_PLANE".format(prefix)

    sketch = component.sketches.add(plane)
    sketch.name = "{}_SKETCH".format(prefix)
    circles = sketch.sketchCurves.sketchCircles
    radius_cm = mm_to_cm(max(0.1, diameter_mm / 2.0))
    for position in positions:
        _, _, center = _plane_and_point(component, contact_axis, position)
        circles.addByCenterRadius(sketch.modelToSketchSpace(center), radius_cm)

    profiles = adsk.core.ObjectCollection.create()
    for index in range(sketch.profiles.count):
        profiles.add(sketch.profiles.item(index))
    if profiles.count < 1:
        raise ValueError("No hole profiles were created for cut.")

    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
    signed_depth_cm = mm_to_cm(depth_mm) * (-1.0 if drill_negative else 1.0)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(signed_depth_cm))

    _set_host_participant_bodies(ext_input, host_body)

    cut = extrudes.add(ext_input)
    cut.name = "{}_{}".format(prefix, sanitize_token(str(int(time.time())), limit=40))

    metadata_written = _write_cut_metadata(cut, metadata)

    try:
        sketch.deleteMe()
    except Exception:
        pass
    try:
        plane.deleteMe()
    except Exception:
        pass

    return cut, metadata_written


def create_host_hinge_hole_cut(
    component,
    host_body,
    feature: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Tuple[Any, bool]:
    return create_host_screw_hole_cut(
        component,
        host_body,
        feature,
        metadata,
        name_prefix="HW_REL_HINGE_HOLE",
    )


def create_host_drawer_runner_hole_cut(
    component,
    host_body,
    feature: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Tuple[Any, bool]:
    return create_host_screw_hole_cut(
        component,
        host_body,
        feature,
        metadata,
        name_prefix="HW_REL_RUNNER_HOLE",
    )


def _write_cut_metadata(cut_feature, metadata: Dict[str, Any]) -> bool:
    if not cut_feature:
        return False
    try:
        for key, value in metadata.items():
            existing = cut_feature.attributes.itemByName(ATTRIBUTE_GROUP, key)
            if existing:
                existing.value = str(value)
            else:
                cut_feature.attributes.add(ATTRIBUTE_GROUP, key, str(value))
        return True
    except Exception:
        return False
