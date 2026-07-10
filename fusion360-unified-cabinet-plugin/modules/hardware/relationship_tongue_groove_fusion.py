"""Fusion CAD operations for relationship-based tongue/groove cuts."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Tuple

import adsk.core
import adsk.fusion

from geometry_ops import mm_to_cm, sanitize_token
from relationship_screw_hole_fusion import (
    _bbox_mm,
    _resolve_body_in_component,
    _set_host_participant_bodies,
    _write_cut_metadata,
)


def _point_mm(contact_axis: str, plane_mm: float, u: float, v: float, length_axis: str, width_axis: str):
    values = {contact_axis: plane_mm, length_axis: u, width_axis: v}
    return adsk.core.Point3D.create(
        mm_to_cm(values["X"]),
        mm_to_cm(values["Y"]),
        mm_to_cm(values["Z"]),
    )


def _axis_bounds(bbox: Dict[str, float], axis: str) -> Tuple[float, float]:
    key0 = "{}0".format(axis.lower())
    key1 = "{}1".format(axis.lower())
    return bbox[key0], bbox[key1]


def _extrude_into_body_is_negative(face_mm: float, body_bbox: Dict[str, float], contact_axis: str) -> bool:
    """True when signed extrude depth should be negative to cut into the solid from face_mm."""
    axis_min, axis_max = _axis_bounds(body_bbox, contact_axis)
    return abs(face_mm - axis_max) <= abs(face_mm - axis_min)


def _base_plane(component, contact_axis: str):
    if contact_axis == "X":
        return component.yZConstructionPlane
    if contact_axis == "Y":
        return component.xZConstructionPlane
    if contact_axis == "Z":
        return component.xYConstructionPlane
    raise ValueError("Unsupported contact axis: {}".format(contact_axis))


def _largest_profile(sketch):
    if sketch.profiles.count < 1:
        return None
    profile = sketch.profiles.item(0)
    for index in range(1, sketch.profiles.count):
        candidate = sketch.profiles.item(index)
        if candidate.areaProperties().area > profile.areaProperties().area:
            profile = candidate
    return profile


def _cut_rect_on_body(
    component,
    body,
    *,
    contact_axis: str,
    plane_mm: float,
    depth_mm: float,
    length_axis: str,
    width_axis: str,
    u0: float,
    u1: float,
    v0: float,
    v1: float,
    name_prefix: str,
    metadata: Dict[str, Any],
) -> Tuple[Any, bool]:
    body = _resolve_body_in_component(component, body)
    body_bbox = _bbox_mm(body)
    cut_negative = _extrude_into_body_is_negative(plane_mm, body_bbox, contact_axis)

    construction = component.constructionPlanes
    plane_input = construction.createInput()
    plane_input.setByOffset(_base_plane(component, contact_axis), adsk.core.ValueInput.createByReal(mm_to_cm(plane_mm)))
    plane = construction.add(plane_input)
    plane.name = "{}_PLANE".format(name_prefix)

    sketch = component.sketches.add(plane)
    sketch.name = "{}_SKETCH".format(name_prefix)
    p0 = sketch.modelToSketchSpace(_point_mm(contact_axis, plane_mm, u0, v0, length_axis, width_axis))
    p1 = sketch.modelToSketchSpace(_point_mm(contact_axis, plane_mm, u1, v1, length_axis, width_axis))
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)

    profile = _largest_profile(sketch)
    if profile is None:
        raise ValueError("No closed profile for {} cut.".format(name_prefix))

    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
    signed_depth_cm = mm_to_cm(depth_mm) * (-1.0 if cut_negative else 1.0)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(signed_depth_cm))
    _set_host_participant_bodies(ext_input, body)

    cut = extrudes.add(ext_input)
    cut.name = "{}_{}".format(name_prefix, sanitize_token(str(int(time.time())), limit=40))
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


def create_host_groove_cut(
    component,
    host_body,
    feature: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Tuple[Any, bool]:
    geometry = feature.get("geometry") or {}
    groove = geometry.get("groove") or {}
    sketch_spec = groove.get("sketch") or {}
    contact_axis = str(geometry.get("contactAxis") or sketch_spec.get("planeAxis") or "Y")
    plane_mm = float(sketch_spec.get("planeMm") or geometry.get("hostContactFaceMm") or 0.0)
    depth_mm = float(sketch_spec.get("depthMm") or groove.get("depthMm") or 0.0)
    length_axis = str(sketch_spec.get("lengthAxis") or "")
    width_axis = str(sketch_spec.get("widthAxis") or "")
    u0 = float(sketch_spec.get("u0") or 0.0)
    u1 = float(sketch_spec.get("u1") or 0.0)
    v0 = float(sketch_spec.get("v0") or 0.0)
    v1 = float(sketch_spec.get("v1") or 0.0)
    if depth_mm <= 0 or not length_axis or not width_axis or abs(u1 - u0) <= 0 or abs(v1 - v0) <= 0:
        raise ValueError("Feature geometry must include groove.sketch with positive size and depth.")

    return _cut_rect_on_body(
        component,
        host_body,
        contact_axis=contact_axis,
        plane_mm=plane_mm,
        depth_mm=depth_mm,
        length_axis=length_axis,
        width_axis=width_axis,
        u0=u0,
        u1=u1,
        v0=v0,
        v1=v1,
        name_prefix="HW_REL_TONGUE_GROOVE",
        metadata=metadata,
    )


def create_host_lock_pocket_cut(
    component,
    host_body,
    feature: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Tuple[Any, bool]:
    """Host-only rectangular lock pocket; reuses tongue/groove rect cut CAD."""
    geometry = feature.get("geometry") or {}
    pocket = geometry.get("pocket") or {}
    contact_axis = str(geometry.get("contactAxis") or pocket.get("planeAxis") or "Y")
    plane_mm = float(pocket.get("planeMm") or 0.0)
    depth_mm = float(pocket.get("depthMm") or geometry.get("depthMm") or 0.0)
    length_axis = str(pocket.get("lengthAxis") or "")
    width_axis = str(pocket.get("widthAxis") or "")
    u0 = float(pocket.get("u0") or 0.0)
    u1 = float(pocket.get("u1") or 0.0)
    v0 = float(pocket.get("v0") or 0.0)
    v1 = float(pocket.get("v1") or 0.0)
    if depth_mm <= 0 or not length_axis or not width_axis or abs(u1 - u0) <= 0 or abs(v1 - v0) <= 0:
        raise ValueError("Feature geometry must include pocket with positive size and depth.")

    return _cut_rect_on_body(
        component,
        host_body,
        contact_axis=contact_axis,
        plane_mm=plane_mm,
        depth_mm=depth_mm,
        length_axis=length_axis,
        width_axis=width_axis,
        u0=u0,
        u1=u1,
        v0=v0,
        v1=v1,
        name_prefix="HW_REL_LOCK_POCKET",
        metadata=metadata,
    )


def create_target_tongue_cut(
    component,
    target_body,
    feature: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Tuple[List[Any], bool]:
    """Cut shoulder pockets on the target edge panel, leaving the tongue strip."""
    geometry = feature.get("geometry") or {}
    tongue = geometry.get("tongue") or {}
    sketch_spec = tongue.get("sketch") or {}
    contact_axis = str(geometry.get("contactAxis") or sketch_spec.get("planeAxis") or "Y")
    plane_mm = float(sketch_spec.get("planeMm") or geometry.get("hostContactFaceMm") or 0.0)
    depth_mm = float(sketch_spec.get("depthMm") or tongue.get("protrusionMm") or 0.0)
    length_axis = str(sketch_spec.get("lengthAxis") or "")
    width_axis = str(sketch_spec.get("widthAxis") or "")
    shoulders = sketch_spec.get("shoulders") or []
    if depth_mm <= 0 or not length_axis or not width_axis or not shoulders:
        raise ValueError("Feature geometry must include tongue.sketch.shoulders with positive depth.")

    cuts: List[Any] = []
    metadata_written = True
    for index, shoulder in enumerate(shoulders):
        if not isinstance(shoulder, dict):
            continue
        u0 = float(shoulder.get("u0") or 0.0)
        u1 = float(shoulder.get("u1") or 0.0)
        v0 = float(shoulder.get("v0") or 0.0)
        v1 = float(shoulder.get("v1") or 0.0)
        if abs(u1 - u0) <= 0 or abs(v1 - v0) <= 0:
            continue
        cut, written = _cut_rect_on_body(
            component,
            target_body,
            contact_axis=contact_axis,
            plane_mm=plane_mm,
            depth_mm=depth_mm,
            length_axis=length_axis,
            width_axis=width_axis,
            u0=u0,
            u1=u1,
            v0=v0,
            v1=v1,
            name_prefix="HW_REL_TONGUE_SHOULDER{}".format(index + 1),
            metadata=metadata,
        )
        cuts.append(cut)
        metadata_written = metadata_written and written
    if not cuts:
        raise ValueError("No tongue shoulder cuts were created.")
    return cuts, metadata_written
