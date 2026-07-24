"""Fusion creation of Nesting Zone workpiece copies."""

from __future__ import annotations

import json
import math
import time

import adsk.core
import adsk.fusion

try:
    from nesting import collision_validate
    from nesting.layout import grouped_row_layout
    from nesting.sheet_pack import sheet_pack_layout
except Exception:
    import collision_validate
    from layout import grouped_row_layout
    from sheet_pack import sheet_pack_layout


OUTPUT_MARKER_GROUP = "UnifiedCabinet"
OUTPUT_MARKER_NAME = "systemRole"
OUTPUT_MARKER_VALUE = "nestingOutput"
INSTANCE_ROLE_NAME = "instanceRole"
INSTANCE_ROLE_NESTED = "nested"
WORKPIECE_GROUP = "UnifiedCabinet.NestingWorkpiece"
WORKPIECE_MANIFEST_NAME = "workpieceManifest"
LAYOUT_COMPONENT_NAME = "NESTING_LAYOUT"
SHEET_BOUNDARY_SKETCH_NAME = "NESTING_SHEETS"


class UnsafeNestingLayoutError(RuntimeError):
    """Raised before Fusion mutation when a supplied layout is unsafe."""

    def __init__(self, diagnostics):
        self.diagnostics = diagnostics
        super().__init__(
            "Unsafe nesting layout: {} collision(s), {} border violation(s).".format(
                int((diagnostics or {}).get("collisionCount") or 0),
                int((diagnostics or {}).get("borderViolationCount") or 0),
            )
        )


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
            try:
                component_name = str(component.name or "").strip().upper()
            except Exception:
                component_name = ""
            try:
                occurrence_name = str(occurrence.name or "").strip().upper()
            except Exception:
                occurrence_name = ""
            def is_reserved_layout_name(name):
                return (
                    name == LAYOUT_COMPONENT_NAME
                    or name.startswith(LAYOUT_COMPONENT_NAME + ":")
                    or name.startswith(LAYOUT_COMPONENT_NAME + " (")
                )

            reserved_name = is_reserved_layout_name(
                component_name
            ) or is_reserved_layout_name(occurrence_name)
            if not marked and not reserved_name:
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


def _matrix3_determinant(matrix):
    """Determinant of the 3x3 linear part (rotation/scale/reflection)."""
    cells = [
        [float(matrix.getCell(row, col)) for col in range(3)] for row in range(3)
    ]
    return (
        cells[0][0] * (cells[1][1] * cells[2][2] - cells[1][2] * cells[2][1])
        - cells[0][1] * (cells[1][0] * cells[2][2] - cells[1][2] * cells[2][0])
        + cells[0][2] * (cells[1][0] * cells[2][1] - cells[1][1] * cells[2][0])
    )


def _occurrence_world_matrix(occurrence):
    """Map occurrence-local coordinates into the design root."""
    if occurrence is None:
        return None
    chain = []
    current = occurrence
    seen = set()
    while current is not None:
        marker = id(current)
        if marker in seen:
            break
        seen.add(marker)
        try:
            chain.append(current.transform.copy())
        except Exception:
            try:
                chain.append(current.transform)
            except Exception:
                break
        try:
            current = current.assemblyContext
        except Exception:
            break
    if not chain:
        return None
    result = adsk.core.Matrix3D.create()
    # Root-most first so reflections on parent mirrors compose correctly.
    for matrix in reversed(chain):
        try:
            result.transformBy(matrix)
        except Exception:
            return None
    return result


def _body_has_reflection(body):
    """True when the body sits under an improper (mirrored) occurrence transform.

    Mirrored L/R door/panel twins often share one native MILLING face attribute.
    Detect reflection even when ``isProxy`` is unreliable by walking occurrence
    context and parent assemblyContext chain.
    """
    occurrence = None
    try:
        occurrence = getattr(body, "assemblyContext", None)
    except Exception:
        occurrence = None
    if occurrence is None:
        try:
            # Some temporary/proxy paths expose the owning occurrence this way.
            occurrence = getattr(body, "occurrence", None)
        except Exception:
            occurrence = None
    matrix = _occurrence_world_matrix(occurrence)
    if matrix is None:
        return False
    try:
        return _matrix3_determinant(matrix) < -1e-9
    except Exception:
        return False


def _mirror_x_matrix():
    """Reflection across the YZ plane (X → −X). Preserves +Z milling-up."""
    matrix = adsk.core.Matrix3D.create()
    matrix.setCell(0, 0, -1.0)
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


def _draw_sheet_boundaries(component, sheets):
    """One lightweight sketch makes physical stock sheets visible in Fusion."""
    if not sheets:
        return 0
    try:
        sketch = component.sketches.add(component.xYConstructionPlane)
        sketch.name = SHEET_BOUNDARY_SKETCH_NAME
        lines = sketch.sketchCurves.sketchLines
        count = 0
        for sheet in sheets:
            x0 = float(sheet.get("originX") or 0.0) / 10.0
            y0 = float(sheet.get("originY") or 0.0) / 10.0
            x1 = x0 + float(sheet.get("widthMm") or 0.0) / 10.0
            y1 = y0 + float(sheet.get("heightMm") or 0.0) / 10.0
            if x1 <= x0 or y1 <= y0:
                continue
            points = [
                adsk.core.Point3D.create(x0, y0, 0.0),
                adsk.core.Point3D.create(x1, y0, 0.0),
                adsk.core.Point3D.create(x1, y1, 0.0),
                adsk.core.Point3D.create(x0, y1, 0.0),
            ]
            for index in range(4):
                line = lines.addByTwoPoints(points[index], points[(index + 1) % 4])
                try:
                    line.isConstruction = True
                except Exception:
                    pass
            count += 1
        return count
    except Exception:
        return 0


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
    """Return source broad face and outward world normal.

    Live face ``millingSurface`` attrs win over a stale body ``faceRegistry``
    so Revert / Orient updates affect nest flattening immediately.
    """
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

    def _role(face):
        live = str(_current_milling_role(face) or "").upper()
        if live in ("MILLING", "NON_MILLING", "EITHER"):
            return live
        return str(_registry_role(face, metadata) or "").upper()

    target = None
    required = str(required_face_up or "").upper()
    if required == "MILLING":
        for face in (surface_a, surface_b):
            if _role(face) == "MILLING":
                target = face
                break
    elif required == "EITHER":
        # Prefer a definite live MILLING face when present (manual override of
        # a former EITHER panel); otherwise largest broad face.
        for face in (surface_a, surface_b):
            if _role(face) == "MILLING":
                target = face
                break
        if target is None:
            target = surface_a
    if target is None:
        return None, None
    normal, _centroid = face_world_plane(target)
    return target, normal


def extract_xy_outline_mm(body):
    """Project the largest +Z-facing outer loop into world XY millimetres."""
    try:
        from nesting.brep_loops import extract_xy_outline_mm as extract_outer
    except Exception:
        try:
            from brep_loops import extract_xy_outline_mm as extract_outer
        except Exception:
            return []
    try:
        return extract_outer(body)
    except Exception:
        return []


def _outline_matches_flat_body(payload, width_mm, depth_mm):
    """Reject unsafe outlines before they reach a true-shape nesting engine."""
    if not isinstance(payload, dict):
        return False
    try:
        from nesting.outline import is_simple_polygon
    except Exception:
        from outline import is_simple_polygon
    points = payload.get("points") or []
    if not is_simple_polygon(points):
        return False
    tolerance_mm = 0.25
    return (
        float(payload.get("widthMm") or 0.0)
        >= max(float(width_mm) - tolerance_mm, 0.0)
        and float(payload.get("depthMm") or 0.0)
        >= max(float(depth_mm) - tolerance_mm, 0.0)
    )


def _metadata_full_holes(metadata):
    """Read only stored FULL features carrying explicit local point rings."""
    meta = metadata if isinstance(metadata, dict) else {}
    candidates = meta.get("features")
    if not isinstance(candidates, list):
        geometry = meta.get("geometry")
        candidates = geometry.get("features") if isinstance(geometry, dict) else []
    holes = []
    for feature in candidates or []:
        if not isinstance(feature, dict):
            continue
        if str(feature.get("cutType") or "").upper() != "FULL":
            continue
        points = feature.get("pointsLocal")
        if not isinstance(points, list) or len(points) < 3:
            continue
        holes.append({
            "points": points,
            "source": "metadata",
            "cutType": "FULL",
            "kind": feature.get("kind"),
            "featureId": feature.get("featureId"),
        })
    return holes


def resolve_prepare_outline(temp_body, metadata, dimensions, allow_parts_in_part=False):
    """Build a nesting outline in the flattened body frame."""
    try:
        from nesting import outline as nesting_outline
    except Exception:
        import outline as nesting_outline

    width = float((dimensions or {}).get("widthMm") or 0.0)
    depth = float((dimensions or {}).get("depthMm") or 0.0)

    flat_points = []
    flat_holes = []
    try:
        from nesting.brep_loops import extract_flattened_rings_mm
    except Exception:
        try:
            from brep_loops import extract_flattened_rings_mm
        except Exception:
            extract_flattened_rings_mm = None
    if extract_flattened_rings_mm is not None:
        try:
            flat_points, flat_holes = extract_flattened_rings_mm(
                temp_body, include_holes=bool(allow_parts_in_part)
            )
        except Exception:
            flat_points, flat_holes = [], []
    if not flat_points:
        flat_points = extract_xy_outline_mm(temp_body)
    if flat_points:
        payload = nesting_outline.build_outline_payload(
            flat_points,
            "flatBody",
            width,
            depth,
            holes=flat_holes if allow_parts_in_part else None,
        )
        if (
            payload
            and payload.get("pointCount", 0) >= 3
            and _outline_matches_flat_body(payload, width, depth)
        ):
            return payload

    meta = metadata if isinstance(metadata, dict) else {}
    milling = meta.get("millingSurfaceSvg")
    if not isinstance(milling, dict):
        # Metadata may nest under stored copies.
        milling = ((meta.get("geometry") or {}) if isinstance(meta.get("geometry"), dict) else {}).get(
            "millingSurfaceSvg"
        )
    svg_points = nesting_outline.outline_from_milling_svg(milling)
    if svg_points:
        metadata_holes = _metadata_full_holes(meta) if allow_parts_in_part else []
        # Align metadata outline into the flattened bbox frame (min corner 0,0,
        # longest side already along +X from prepare_flat_copy).
        normalized, bounds = nesting_outline.normalize_polygon_to_origin(svg_points)
        if metadata_holes:
            metadata_holes = nesting_outline.translate_ring_set(
                metadata_holes, -bounds["minX"], -bounds["minY"]
            )
        if bounds["depthMm"] > bounds["widthMm"] + 1e-6:
            normalized, bounds = nesting_outline.oriented_outline(normalized, -90.0)
            metadata_holes = nesting_outline.rotate_ring_set(metadata_holes, -90.0)
            metadata_holes = nesting_outline.translate_ring_set(
                metadata_holes, -bounds["minX"], -bounds["minY"]
            )
        payload = nesting_outline.build_outline_payload(
            normalized,
            "metadataSvg",
            width,
            depth,
            holes=metadata_holes,
        )
        if (
            payload
            and payload.get("pointCount", 0) >= 3
            and _outline_matches_flat_body(payload, width, depth)
        ):
            return payload

    return nesting_outline.build_outline_payload(
        nesting_outline.rectangle_polygon(width, depth),
        "rectangle",
        width,
        depth,
    )


def prepare_flat_copy(
    source_body,
    metadata,
    required_face_up,
    allow_parts_in_part=False,
    outline_override=None,
):
    """Copy source proxy into a transient body and orient cutting face +Z.

    Mirrored L/R occurrences often share one native MILLING face attribute.
    Rotating that face's opposite world normals onto +Z cancels the occurrence
    reflection, so both twins flatten to the same chirality. When the source
    sits under an improper transform, re-apply an XY mirror after milling-up
    so nest outlines stay true left/right mirrors.

    When ``outline_override`` is a valid outline dict (from nestingFlatOutline
    cache), BRep outline extraction is skipped.
    """
    _face, normal = cutting_face_and_normal(
        source_body, metadata, required_face_up
    )
    if not normal:
        raise ValueError("Could not resolve cutting-face world normal.")
    temp_manager = adsk.fusion.TemporaryBRepManager.get()
    temp_body = temp_manager.copy(source_body)
    if temp_body is None:
        raise ValueError("TemporaryBRepManager.copy returned no body.")

    reflected = _body_has_reflection(source_body)
    temp_manager.transform(
        temp_body,
        _rotation_matrix(normal, [0.0, 0.0, 1.0]),
    )
    if reflected:
        temp_manager.transform(temp_body, _mirror_x_matrix())
    dims = _bbox_dimensions_mm(temp_body)
    # Deterministic in-plane orientation: longest bounding direction along +X.
    if dims["depthMm"] > dims["widthMm"] + 1e-6:
        temp_manager.transform(temp_body, _z_rotation_matrix(-90.0))
        dims = _bbox_dimensions_mm(temp_body)
    if isinstance(outline_override, dict) and outline_override.get("points"):
        outline = dict(outline_override)
    else:
        outline = resolve_prepare_outline(
            temp_body,
            metadata,
            dims,
            allow_parts_in_part=allow_parts_in_part,
        )
    if isinstance(outline, dict):
        outline = dict(outline)
        outline["reflectedSource"] = bool(reflected)
    return temp_body, dims, outline


def _strip_panel_attributes(body):
    # TemporaryBRep copies do not carry face custom attributes; only clear
    # body-level panel identity so Nesting workpieces stay isolated.
    _delete_attr(body, "UnifiedCabinet.Panel", "panelId")
    _delete_attr(body, "UnifiedCabinet.Panel", "metadata")


def _mark_workpiece(body, placement, run_id):
    _strip_panel_attributes(body)
    # One body marker keeps scanner/selection compatibility. Per-body placement
    # metadata lives once on the layout component to avoid 600+ Fusion attribute
    # writes on a 200-panel nest.
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
        "sheetIndex": placement.get("sheetIndex"),
        "rotationDeg": placement.get("rotationDeg"),
    }
    return details


def create_layout(
    root_component,
    prepared_items,
    nesting_rect,
    part_gap_mm=50.0,
    group_gap_mm=300.0,
    profiler=None,
    layout=None,
    sheet_params=None,
    wait_callback=None,
    prevalidated_validation=None,
):
    """Replace prior output and create one marked root-level layout component.

    Prefer a precomputed ``layout`` from ``sheet_pack_layout``. If omitted and
    ``sheet_params`` is provided, sheet packing runs here. Otherwise falls back
    to the legacy grouped-row layout.
    """
    import time as _time

    def _pump():
        if callable(wait_callback):
            try:
                wait_callback()
            except Exception:
                pass

    if not prepared_items:
        return {
            "created": 0,
            "deletedPrevious": 0,
            "groups": [],
            "placements": [],
            "sheets": [],
            "unplaced": [],
        }
    if not isinstance(nesting_rect, dict):
        raise ValueError("Nesting Zone is not configured.")

    layout_items = [
        {
            **item,
            "widthMm": item["dimensions"]["widthMm"],
            "depthMm": item["dimensions"]["depthMm"],
        }
        for item in prepared_items
    ]
    if layout is None:
        if sheet_params is not None:
            layout = sheet_pack_layout(
                layout_items,
                sheet_params,
                nesting_rect["x0"],
                nesting_rect["y0"],
            )
        else:
            layout = grouped_row_layout(
                layout_items,
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

    if sheet_params is not None:
        validation = (
            dict(prevalidated_validation)
            if isinstance(prevalidated_validation, dict)
            else None
        )
        if validation is None:
            validation = collision_validate.validate_layout(
                layout, prepared_items, sheet_params
            )
            validation = collision_validate.validate_fusion_exact(
                layout, prepared_items, sheet_params, validation
            )
        if not validation.get("ok"):
            raise UnsafeNestingLayoutError(validation)

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
    _set_attr(
        component,
        OUTPUT_MARKER_GROUP,
        "layoutEngine",
        str(layout.get("engine") or "grouped_row"),
    )

    by_id = {str(item["id"]): item for item in prepared_items}
    temp_manager = adsk.fusion.TemporaryBRepManager.get()
    created = []
    pending_marks = []
    workpiece_manifest = {}
    placements = list(layout.get("placements") or [])
    # Batch finishEdit — one base feature with 200+ bodies freezes Fusion for minutes.
    CREATE_BATCH = 40
    try:
        for batch_start in range(0, len(placements), CREATE_BATCH):
            batch = placements[batch_start : batch_start + CREATE_BATCH]
            base_feature = component.features.baseFeatures.add()
            base_feature.name = "NESTING_WORKPIECES_{}_{}".format(
                run_id, batch_start // CREATE_BATCH + 1
            )
            base_feature.startEdit()
            try:
                for offset, placement in enumerate(batch):
                    index = batch_start + offset
                    item_t0 = _time.perf_counter()
                    item = by_id[str(placement["id"])]
                    temp_body = item["tempBody"]
                    rotation_deg = float(placement.get("rotationDeg") or 0.0)
                    if abs(rotation_deg) > 1e-9:
                        temp_manager.transform(
                            temp_body, _z_rotation_matrix(rotation_deg)
                        )
                        dims = _bbox_dimensions_mm(temp_body)
                    else:
                        dims = item.get("dimensions") or _bbox_dimensions_mm(temp_body)
                    temp_manager.transform(
                        temp_body,
                        _translation_matrix(
                            placement["targetX"] - dims["minX"],
                            placement["targetY"] - dims["minY"],
                            -dims["minZ"],
                        ),
                    )
                    new_body = component.bRepBodies.add(temp_body, base_feature)
                    sheet_index = int(placement.get("sheetIndex") or 0) + 1
                    new_body.name = "NEST_S{:02d}_{:02d}_{:03d}_{}".format(
                        sheet_index,
                        int(placement.get("groupIndex") or 0) + 1,
                        int(placement.get("itemIndex") or 0) + 1,
                        str(placement.get("bodyName") or "panel"),
                    )
                    pending_marks.append((new_body, placement))
                    item_ms = int((_time.perf_counter() - item_t0) * 1000)
                    if profiler is not None:
                        profiler.add("createdBodies", 1)
                        if item_ms >= 250:
                            profiler.sample(
                                "createBody", item_ms, bodyName=new_body.name
                            )
                        if (index + 1) % 10 == 0:
                            profiler.mark("createProgress", created=index + 1)
            except Exception:
                try:
                    base_feature.finishEdit()
                except Exception:
                    pass
                raise
            if profiler is not None:
                profiler.begin("finishEditBatch")
            base_feature.finishEdit()
            if profiler is not None:
                profiler.end("finishEditBatch")
                profiler.mark(
                    "finishEditBatchDone",
                    created=min(batch_start + len(batch), len(placements)),
                )
            _pump()
    except Exception:
        try:
            occurrence.deleteMe()
        except Exception:
            pass
        raise

    if profiler is not None:
        profiler.begin("markWorkpieces")
        profiler.mark("markBegin", count=len(pending_marks))
    for mark_index, (new_body, placement) in enumerate(pending_marks):
        details = _mark_workpiece(new_body, placement, run_id)
        workpiece_manifest[str(new_body.name or "")] = details
        created.append(
            {
                "bodyName": new_body.name,
                "sourcePanelId": placement.get("panelId") or "",
                "boardTypeTag": placement.get("boardTypeTag") or "",
                "colorTag": placement.get("colorTag") or "",
                "groupIndex": placement.get("groupIndex"),
                "sheetIndex": placement.get("sheetIndex"),
                "rotationDeg": placement.get("rotationDeg") or 0.0,
                "targetX": placement["targetX"],
                "targetY": placement["targetY"],
            }
        )
        if (mark_index + 1) % 20 == 0:
            if profiler is not None:
                profiler.mark("markProgress", marked=mark_index + 1)
            _pump()
    _set_attr(
        component,
        WORKPIECE_GROUP,
        WORKPIECE_MANIFEST_NAME,
        json.dumps(
            {
                "version": 1,
                "runId": run_id,
                "workpieces": workpiece_manifest,
            },
            separators=(",", ":"),
        ),
    )
    sheet_boundary_count = _draw_sheet_boundaries(
        component, layout.get("sheets") or []
    )
    if profiler is not None:
        profiler.end("markWorkpieces")

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
        "engine": layout.get("engine") or "grouped_row",
        "requestedEngine": layout.get("requestedEngine"),
        "engineFallback": bool(layout.get("engineFallback")),
        "engineFallbackReason": layout.get("engineFallbackReason"),
        "groups": layout.get("groups") or [],
        "sheets": layout.get("sheets") or [],
        "unplaced": layout.get("unplaced") or [],
        "placements": created,
        "requiredWidthMm": layout["requiredWidthMm"],
        "requiredDepthMm": layout["requiredDepthMm"],
        "borderMm": layout.get("borderMm"),
        "spacingMm": layout.get("spacingMm"),
        "sheetBoundaryCount": sheet_boundary_count,
    }
