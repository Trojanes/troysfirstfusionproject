"""Export / sketch projection for the current Nesting Zone layout.

Looks at the live ``NESTING_LAYOUT`` component only (does not re-run nesting).
"""

from __future__ import annotations

import json
import os

try:
    import adsk.core
    import adsk.fusion
except Exception:  # pragma: no cover - Fusion-only
    adsk = None

try:
    from nesting import brep_loops
    from nesting import dxf_writer
    from nesting.fusion_layout import (
        LAYOUT_COMPONENT_NAME,
        OUTPUT_MARKER_GROUP,
        OUTPUT_MARKER_NAME,
        OUTPUT_MARKER_VALUE,
        WORKPIECE_GROUP,
        WORKPIECE_MANIFEST_NAME,
        _attr,
    )
except Exception:
    import brep_loops
    import dxf_writer
    from fusion_layout import (
        LAYOUT_COMPONENT_NAME,
        OUTPUT_MARKER_GROUP,
        OUTPUT_MARKER_NAME,
        OUTPUT_MARKER_VALUE,
        WORKPIECE_GROUP,
        WORKPIECE_MANIFEST_NAME,
        _attr,
    )


def _is_reserved_layout_name(name):
    value = str(name or "").strip().upper()
    return (
        value == LAYOUT_COMPONENT_NAME
        or value.startswith(LAYOUT_COMPONENT_NAME + ":")
        or value.startswith(LAYOUT_COMPONENT_NAME + " (")
    )


def find_nesting_layout_occurrence(root_component):
    """Return the newest root occurrence that holds the nesting layout."""
    try:
        occurrences = root_component.occurrences
        count = occurrences.count
    except Exception:
        return None
    found = None
    for index in range(count):
        try:
            occurrence = occurrences.item(index)
            component = occurrence.component
        except Exception:
            continue
        marked = (
            _attr(component, OUTPUT_MARKER_GROUP, OUTPUT_MARKER_NAME)
            == OUTPUT_MARKER_VALUE
        )
        try:
            component_name = str(component.name or "")
        except Exception:
            component_name = ""
        try:
            occurrence_name = str(occurrence.name or "")
        except Exception:
            occurrence_name = ""
        if marked or _is_reserved_layout_name(component_name) or _is_reserved_layout_name(
            occurrence_name
        ):
            found = occurrence
    return found


def _matrix_transform_xy_mm(x_mm, y_mm, matrix):
    if matrix is None or adsk is None:
        return float(x_mm), float(y_mm)
    try:
        point = adsk.core.Point3D.create(float(x_mm) / 10.0, float(y_mm) / 10.0, 0.0)
        point.transformBy(matrix)
        return float(point.x) * 10.0, float(point.y) * 10.0
    except Exception:
        return float(x_mm), float(y_mm)


def _transform_ring_mm(points, matrix):
    return [_matrix_transform_xy_mm(p[0], p[1], matrix) for p in (points or [])]


def _workpiece_manifest(component):
    raw = _attr(component, WORKPIECE_GROUP, WORKPIECE_MANIFEST_NAME)
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    records = payload.get("workpieces") if isinstance(payload, dict) else None
    return records if isinstance(records, dict) else {}


def collect_layout_polylines(root_component, apply_occurrence_transform=True):
    """Collect XY millimetre polylines from the current nesting layout."""
    occurrence = find_nesting_layout_occurrence(root_component)
    if occurrence is None:
        return {
            "ok": False,
            "error": "No NESTING_LAYOUT found. Create a Nesting Zone layout first.",
            "polylines": [],
            "bodyCount": 0,
            "ringCount": 0,
        }
    try:
        component = occurrence.component
        matrix = occurrence.transform if apply_occurrence_transform else None
    except Exception:
        return {
            "ok": False,
            "error": "Nesting layout occurrence is not readable.",
            "polylines": [],
            "bodyCount": 0,
            "ringCount": 0,
        }
    polylines = []
    bodies = []
    manifest = _workpiece_manifest(component)
    try:
        body_count = component.bRepBodies.count
    except Exception:
        body_count = 0
    for index in range(body_count):
        try:
            body = component.bRepBodies.item(index)
        except Exception:
            continue
        role = _attr(body, OUTPUT_MARKER_GROUP, "instanceRole")
        system_role = _attr(body, OUTPUT_MARKER_GROUP, "systemRole")
        if role and role != "nested" and system_role != "nestingWorkpiece":
            name = str(getattr(body, "name", "") or "")
            if not name.upper().startswith("NEST_"):
                continue
        rings = brep_loops.extract_dxf_projection_rings_mm(body)
        body_rings = 0
        for ring in rings:
            points = _transform_ring_mm(ring.get("points") or [], matrix)
            if len(points) >= 3:
                polylines.append(points)
                body_rings += 1
        if body_rings:
            body_name = str(getattr(body, "name", "") or "")
            details = manifest.get(body_name) if isinstance(manifest.get(body_name), dict) else {}
            legacy = {}
            raw_legacy = _attr(body, WORKPIECE_GROUP, "metadata")
            if raw_legacy:
                try:
                    legacy = json.loads(raw_legacy)
                except Exception:
                    legacy = {}
            bodies.append(
                {
                    "bodyName": body_name,
                    "sheetIndex": details.get("sheetIndex", legacy.get("sheetIndex")),
                    "sourcePanelId": details.get(
                        "sourcePanelId", legacy.get("sourcePanelId", "")
                    ),
                    "ringCount": body_rings,
                }
            )
    if not polylines:
        return {
            "ok": False,
            "error": "Nesting layout has no exportable outlines.",
            "polylines": [],
            "bodyCount": 0,
            "ringCount": 0,
            "bodies": bodies,
            "componentName": str(getattr(component, "name", "") or ""),
            "occurrence": occurrence,
            "component": component,
        }
    return {
        "ok": True,
        "polylines": polylines,
        "bodyCount": len(bodies),
        "ringCount": len(polylines),
        "bodies": bodies,
        "componentName": str(getattr(component, "name", "") or ""),
        "occurrence": occurrence,
        "component": component,
    }


def choose_dxf_save_path(ui, default_name="nesting_layout.dxf"):
    if ui is None:
        return ""
    dialog = ui.createFileDialog()
    dialog.isMultiSelectEnabled = False
    dialog.title = "Export Nesting Layout DXF"
    dialog.filter = "DXF files (*.dxf)"
    dialog.initialFilename = default_name
    if dialog.showSave() != adsk.core.DialogResults.DialogOK:
        return ""
    path = str(dialog.filename or "").strip()
    if path and not path.lower().endswith(".dxf"):
        path += ".dxf"
    return path


def export_nesting_layout_dxf(root_component, path, layer="0"):
    collected = collect_layout_polylines(root_component, apply_occurrence_transform=True)
    if not collected.get("ok"):
        return {
            "ok": False,
            "error": collected.get("error") or "DXF export failed.",
            "bodyCount": collected.get("bodyCount") or 0,
            "ringCount": collected.get("ringCount") or 0,
        }
    abs_path = os.path.abspath(path)
    parent = os.path.dirname(abs_path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    dxf_writer.write_dxf_file(abs_path, collected["polylines"], layer=layer)
    return {
        "ok": True,
        "path": abs_path,
        "bodyCount": collected.get("bodyCount") or 0,
        "ringCount": collected.get("ringCount") or 0,
        "componentName": collected.get("componentName") or "",
        "layer": layer,
    }


PROJECTION_SKETCH_NAME = "NESTING_DXF_PROJECTION"
PROJECTION_PLANE_NAME = "NESTING_DXF_CUT_PLANE"


def _delete_named_construction_planes(component, name):
    deleted = 0
    try:
        planes = component.constructionPlanes
        count = planes.count
    except Exception:
        return 0
    for index in range(count - 1, -1, -1):
        try:
            plane = planes.item(index)
            plane_name = str(plane.name or "")
        except Exception:
            continue
        if plane_name == name or plane_name.startswith(name + " "):
            try:
                plane.deleteMe()
                deleted += 1
            except Exception:
                continue
    return deleted


def _delete_projection_sketches(component):
    deleted = 0
    try:
        sketches = component.sketches
        count = sketches.count
    except Exception:
        return 0
    for index in range(count - 1, -1, -1):
        try:
            sketch = sketches.item(index)
            name = str(sketch.name or "")
        except Exception:
            continue
        if name == PROJECTION_SKETCH_NAME or name.startswith(PROJECTION_SKETCH_NAME + " "):
            try:
                sketch.deleteMe()
                deleted += 1
            except Exception:
                continue
    return deleted


def _is_nesting_workpiece_body(body):
    role = _attr(body, OUTPUT_MARKER_GROUP, "instanceRole")
    system_role = _attr(body, OUTPUT_MARKER_GROUP, "systemRole")
    if role == "nested" or system_role == "nestingWorkpiece":
        return True
    name = str(getattr(body, "name", "") or "")
    return name.upper().startswith("NEST_")


def _iter_nesting_bodies(component):
    try:
        count = component.bRepBodies.count
    except Exception:
        return
    for index in range(count):
        try:
            body = component.bRepBodies.item(index)
        except Exception:
            continue
        if _is_nesting_workpiece_body(body):
            yield body


def _bodies_z_stats_cm(bodies):
    min_z = None
    max_z = None
    lowest_top = None
    for body in bodies:
        try:
            bounds = body.boundingBox
            lo = float(bounds.minPoint.z)
            hi = float(bounds.maxPoint.z)
        except Exception:
            continue
        min_z = lo if min_z is None else min(min_z, lo)
        max_z = hi if max_z is None else max(max_z, hi)
        lowest_top = hi if lowest_top is None else min(lowest_top, hi)
    return min_z, max_z, lowest_top


def _choose_cut_z_cm(min_z, max_z, lowest_top):
    top = lowest_top if lowest_top is not None else max_z
    bottom = min_z if min_z is not None else 0.0
    thickness = max(top - bottom, 0.0)
    cut_z = top - max(0.02, min(0.08, thickness * 0.2))
    if cut_z <= bottom + 1e-4:
        cut_z = bottom + max(thickness * 0.5, 0.02)
    return cut_z


def _sketch_curve_count(sketch):
    try:
        return int(sketch.sketchCurves.count)
    except Exception:
        return 0


def _project_ok(sketch, entity):
    """Return (ok, error). ok means Fusion accepted the project call."""
    if entity is None:
        return False, "missing entity"
    try:
        sketch.project(entity)
        return True, ""
    except Exception as ex:
        return False, str(ex)


def _face_inner_loop_count(face):
    count = 0
    for loop in brep_loops._items(getattr(face, "loops", None)):
        try:
            if not bool(loop.isOuter):
                count += 1
        except Exception:
            continue
    return count


def _face_temp_id(face):
    try:
        return face.tempId
    except Exception:
        return id(face)


def select_milling_projection_face(body):
    """Broad face that carries openings (hinge cups). Prefer +Z, then most inners."""
    ranked = []
    for face in brep_loops._items(getattr(body, "faces", None)):
        normal_z = brep_loops._face_normal_z(face)
        if normal_z is None or abs(normal_z) < 0.7:
            continue
        try:
            area = float(face.area)
        except Exception:
            area = 0.0
        ranked.append(
            (1 if normal_z > 0 else 0, _face_inner_loop_count(face), area, face)
        )
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return ranked[0][3]


def _floor_faces_for_project(body, top_face):
    """Deprecated wrapper — prefer brep_loops.iter_feature_floor_faces."""
    return list(brep_loops.iter_feature_floor_faces(body, outer_face=top_face))


def _project_body_layout_curves(sketch, body):
    """Project true outer (from underside) then each groove/pocket floor.

    Edge-open grooves notch the milled-face outer loop. Projecting that face
    mixes the panel outline with the groove mouth. Instead:
    1. Project the true outer broad face (bottom preferred when larger).
    2. Project each mid-thickness floor face separately for enclosed vectors.
    """
    accepted = False
    last_error = ""
    method_parts = []

    outer_face = brep_loops.select_true_outer_face(body)
    if outer_face is not None:
        ok, err = _project_ok(sketch, outer_face)
        accepted = accepted or ok
        if ok:
            method_parts.append("outerFromUnderside")
        elif err:
            last_error = err

    floor_count = 0
    for floor in brep_loops.iter_feature_floor_faces(body, outer_face=outer_face):
        ok, err = _project_ok(sketch, floor)
        if ok:
            accepted = True
            floor_count += 1
        elif err and not last_error:
            last_error = err
    if floor_count:
        method_parts.append("grooveFloors:{}".format(floor_count))

    if not accepted:
        # Last resort only — cut edges often re-notch the outer silhouette.
        try:
            sketch.projectCutEdges(body)
            accepted = True
            method_parts.append("projectCutEdges")
        except Exception as ex:
            last_error = str(ex)
            ok, err = _project_ok(sketch, body)
            accepted = ok
            if err:
                last_error = err
            if accepted:
                method_parts.append("projectBody")

    method = "+".join(method_parts) if method_parts else "none"
    return accepted, last_error, method


def create_nesting_layout_sketch(root_component, progress_callback=None):
    """Create top-down sketch: true outer from underside + each groove floor."""
    if adsk is None:
        return {
            "ok": False,
            "error": "Fusion API is not available.",
            "bodyCount": 0,
            "projectedCount": 0,
        }
    occurrence = find_nesting_layout_occurrence(root_component)
    if occurrence is None:
        return {
            "ok": False,
            "error": "No NESTING_LAYOUT found. Create a Nesting Zone layout first.",
            "bodyCount": 0,
            "projectedCount": 0,
        }
    try:
        component = occurrence.component
    except Exception:
        return {
            "ok": False,
            "error": "Nesting layout occurrence is not readable.",
            "bodyCount": 0,
            "projectedCount": 0,
        }

    bodies = list(_iter_nesting_bodies(component))
    if not bodies:
        return {
            "ok": False,
            "error": "Nesting layout has no workpiece bodies to project.",
            "bodyCount": 0,
            "projectedCount": 0,
            "componentName": str(getattr(component, "name", "") or ""),
        }

    min_z, max_z, lowest_top = _bodies_z_stats_cm(bodies)
    if min_z is None or max_z is None or max_z - min_z < 1e-6:
        return {
            "ok": False,
            "error": "Could not read nesting body Z extents for the cut plane.",
            "bodyCount": len(bodies),
            "projectedCount": 0,
        }
    cut_z = _choose_cut_z_cm(min_z, max_z, lowest_top)

    deleted = _delete_projection_sketches(component)
    deleted += _delete_named_construction_planes(component, PROJECTION_PLANE_NAME)

    try:
        plane_input = component.constructionPlanes.createInput()
        plane_input.setByOffset(
            component.xYConstructionPlane,
            adsk.core.ValueInput.createByReal(float(cut_z)),
        )
        cut_plane = component.constructionPlanes.add(plane_input)
        try:
            cut_plane.name = PROJECTION_PLANE_NAME
        except Exception:
            pass
        sketch = component.sketches.add(cut_plane)
    except Exception as ex:
        return {
            "ok": False,
            "error": "Could not create cut-plane sketch: {}".format(ex),
            "bodyCount": len(bodies),
            "projectedCount": 0,
        }
    try:
        sketch.name = PROJECTION_SKETCH_NAME
    except Exception:
        pass

    # Never use isComputeDeferred around project(): result counts stay 0 and we
    # used to delete a sketch that actually had pending geometry.
    body_ok = 0
    errors = []
    method = "outerFromUnderside+grooveFloors"
    total = len(bodies)
    curves_before = _sketch_curve_count(sketch)
    methods_seen = []

    for index, body in enumerate(bodies):
        if progress_callback is not None and index % 2 == 0:
            try:
                progress_callback(index, total)
            except Exception:
                pass

        accepted, last_error, body_method = _project_body_layout_curves(sketch, body)
        if body_method and body_method not in methods_seen:
            methods_seen.append(body_method)

        if accepted:
            body_ok += 1
        else:
            errors.append(
                "{}{}".format(
                    str(getattr(body, "name", "") or "body"),
                    (" (" + last_error + ")") if last_error else "",
                )
            )

    if progress_callback is not None:
        try:
            progress_callback(total, total)
        except Exception:
            pass

    if methods_seen:
        method = methods_seen[0] if len(methods_seen) == 1 else "mixed"

    projected_count = max(0, _sketch_curve_count(sketch) - curves_before)

    if projected_count <= 0:
        try:
            sketch.deleteMe()
        except Exception:
            pass
        try:
            cut_plane.deleteMe()
        except Exception:
            pass
        return {
            "ok": False,
            "error": (
                "Fusion project created no curves (cutZ={:.2f}mm). Failed: {}"
            ).format(cut_z * 10.0, ", ".join(errors[:6]) or "?"),
            "bodyCount": len(bodies),
            "projectedCount": 0,
            "componentName": str(getattr(component, "name", "") or ""),
            "cutZmm": cut_z * 10.0,
            "method": method,
        }

    return {
        "ok": True,
        "sketchName": str(getattr(sketch, "name", "") or PROJECTION_SKETCH_NAME),
        "componentName": str(getattr(component, "name", "") or ""),
        "bodyCount": body_ok if body_ok else len(bodies),
        "bodyTotal": len(bodies),
        "projectedCount": projected_count,
        "ringCount": projected_count,
        "lineCount": projected_count,
        "deletedPrevious": deleted,
        "failedBodies": errors[:20],
        "method": method,
        "cutZmm": cut_z * 10.0,
    }
