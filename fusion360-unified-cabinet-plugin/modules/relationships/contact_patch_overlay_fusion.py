"""Fusion geometry for ContactPatch overlay."""

from __future__ import annotations

import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

try:
    import adsk.core as adsk_core
    import adsk.fusion as adsk_fusion
except Exception:
    adsk_core = None
    adsk_fusion = None

from contact_patch import build_contact_patch_label_text
from contact_patch_overlay import (
    ARTIFACT_ATTR_CONTACT_PATCH_ID,
    ARTIFACT_ATTR_DEMO,
    ARTIFACT_ATTR_GROUP,
    ARTIFACT_ATTR_OPERATION,
    ARTIFACT_ATTR_OVERLAY_ROLE,
    ARTIFACT_ATTR_RELATIONSHIP_ID,
    OPERATION_TYPE,
    PATCH_CUSTOM_GRAPHICS_PREFIX,
    PATCH_PLANE_PREFIX,
    PATCH_SKETCH_PREFIX,
    build_contact_patch_metadata,
    build_contact_patch_overlay_report,
    is_contact_patch_artifact_entity,
    overlay_metadata_json,
)
from relationship_visual_overlay import (
    bbox_center_mm,
)

try:
    from geometry_ops import mm_to_cm, sanitize_token
except Exception:

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


CONTACT_PATCH_FUSION_BUILD = "2026-07-05-contact-patch-v2-sketch"


def _tag_entity(entity, metadata: Dict[str, Any], overlay_role: str) -> None:
    if entity is None:
        return
    try:
        attrs = entity.attributes
        attrs.add(ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_OPERATION, OPERATION_TYPE)
        attrs.add(ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_DEMO, "true")
        attrs.add(ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_RELATIONSHIP_ID, str(metadata.get("sourceRelationshipId") or ""))
        attrs.add(ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_CONTACT_PATCH_ID, str(metadata.get("contactPatchId") or ""))
        attrs.add(ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_OVERLAY_ROLE, overlay_role)
        attrs.add(ARTIFACT_ATTR_GROUP, "overlayMetadata", overlay_metadata_json(metadata))
    except Exception:
        pass


def _add_xy_sketch_text(texts, content: str, x_mm: float, y_mm: float, height_mm: float) -> None:
    if texts is None:
        return
    height_cm = max(mm_to_cm(height_mm), 0.05)
    half_w_cm = height_cm * 5.0
    cx = mm_to_cm(x_mm)
    cy = mm_to_cm(y_mm)
    corner = adsk_core.Point3D.create(cx - half_w_cm, cy - height_cm / 2.0, 0.0)
    diagonal = adsk_core.Point3D.create(cx + half_w_cm, cy + height_cm / 2.0, 0.0)
    try:
        text_input = texts.createInput2(content, height_cm)
        text_input.setAsMultiLine(
            corner,
            diagonal,
            adsk_core.HorizontalAlignments.CenterHorizontalAlignment,
            adsk_core.VerticalAlignments.MiddleVerticalAlignment,
            0,
        )
        texts.add(text_input)
    except Exception:
        try:
            text_input = texts.createInput(content, height_cm)
            text_input.position = adsk_core.Point3D.create(cx, cy, 0.0)
            texts.add(text_input)
        except Exception:
            pass


def _create_contact_plane(root, contact_axis: str, plane_coord_mm: float):
    construction = root.constructionPlanes
    plane_input = construction.createInput()
    offset = adsk_core.ValueInput.createByReal(mm_to_cm(plane_coord_mm))
    axis = str(contact_axis or "Y").upper()
    if axis == "Y":
        plane_input.setByOffset(root.xZConstructionPlane, offset)
    elif axis == "X":
        plane_input.setByOffset(root.yZConstructionPlane, offset)
    else:
        plane_input.setByOffset(root.xYConstructionPlane, offset)
    return construction.add(plane_input)


def _sketch_line(sketch, lines, x0: float, y0: float, z0: float, x1: float, y1: float, z1: float):
    p0 = adsk_core.Point3D.create(mm_to_cm(x0), mm_to_cm(y0), mm_to_cm(z0))
    p1 = adsk_core.Point3D.create(mm_to_cm(x1), mm_to_cm(y1), mm_to_cm(z1))
    return lines.addByTwoPoints(sketch.modelToSketchSpace(p0), sketch.modelToSketchSpace(p1))


def _create_custom_graphics_polyline(root, points_mm: List[Tuple[float, float, float]], name: str, metadata: Dict[str, Any], role: str):
    groups = root.customGraphicsGroups
    group = groups.add()
    group.name = name
    _tag_entity(group, metadata, role)
    coords = []
    for point in points_mm:
        coords.extend([mm_to_cm(point[0]), mm_to_cm(point[1]), mm_to_cm(point[2])])
    lines = group.addLines(adsk_fusion.CustomGraphicsCoordinates.create(coords), [], False)
    lines.weight = 3
    try:
        color = adsk_fusion.CustomGraphicsSolidColorEffect.create(adsk_core.Color.create(0, 180, 255, 255))
        lines.color = color
    except Exception:
        pass
    return group


def _patch_rectangle_corners(contact_patch: Dict[str, Any]) -> List[Tuple[float, float, float]]:
    bounds = contact_patch.get("boundsWorldMm") or {}
    axis = str(contact_patch.get("contactAxis") or "Y").upper()
    x0 = float(bounds.get("x0", 0.0))
    x1 = float(bounds.get("x1", 0.0))
    y0 = float(bounds.get("y0", 0.0))
    y1 = float(bounds.get("y1", 0.0))
    z0 = float(bounds.get("z0", 0.0))
    z1 = float(bounds.get("z1", 0.0))
    center = contact_patch.get("centerWorldMm") or [0.0, 0.0, 0.0]
    plane = float(center[0 if axis == "X" else (1 if axis == "Y" else 2)])

    if axis == "Y":
        y = plane
        return [(x0, y, z0), (x1, y, z0), (x1, y, z1), (x0, y, z1), (x0, y, z0)]
    if axis == "X":
        x = plane
        return [(x, y0, z0), (x, y1, z0), (x, y1, z1), (x, y0, z1), (x, y0, z0)]
    z = plane
    return [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z), (x0, y0, z)]


def create_contact_patch_overlay(
    root,
    relationship: Dict[str, Any],
    contact_patch: Dict[str, Any],
    panels_map: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    source: str = "selected",
) -> Dict[str, Any]:
    metadata = build_contact_patch_metadata(contact_patch)
    run_token = sanitize_token(str(int(time.time())), limit=24)
    created = {"sketches": [], "planes": [], "customGraphics": []}
    warnings: List[str] = []
    errors: List[str] = []

    if root is None or adsk_core is None or adsk_fusion is None:
        return build_contact_patch_overlay_report(
            contact_patch,
            relationship,
            ok=False,
            source=source,
            errors=["Fusion root component unavailable."],
        )

    try:
        axis = str(contact_patch.get("contactAxis") or "Y").upper()
        center = contact_patch.get("centerWorldMm") or [0.0, 0.0, 0.0]
        plane_coord = float(center[0 if axis == "X" else (1 if axis == "Y" else 2)])

        plane_name = "{}{}".format(PATCH_PLANE_PREFIX, run_token)
        plane = _create_contact_plane(root, axis, plane_coord)
        plane.name = plane_name
        _tag_entity(plane, metadata, "patch_plane")
        created["planes"].append(plane_name)

        patch_sketch_name = "{}{}_PATCH".format(PATCH_SKETCH_PREFIX, run_token)
        patch_sketch = root.sketches.add(plane)
        patch_sketch.name = patch_sketch_name
        _tag_entity(patch_sketch, metadata, "patch_rectangle")
        created["sketches"].append(patch_sketch_name)

        lines = patch_sketch.sketchCurves.sketchLines
        corners = _patch_rectangle_corners(contact_patch)
        for index in range(len(corners) - 1):
            x0, y0, z0 = corners[index]
            x1, y1, z1 = corners[index + 1]
            _sketch_line(patch_sketch, lines, x0, y0, z0, x1, y1, z1)

        label_sketch = root.sketches.add(root.xYConstructionPlane)
        label_sketch.name = "{}{}_LABEL".format(PATCH_SKETCH_PREFIX, run_token)
        _tag_entity(label_sketch, metadata, "main_label")
        created["sketches"].append(label_sketch.name)

        label_height = max(min(float(contact_patch.get("contactLengthMm") or 50.0) * 0.08, 40.0), 8.0)
        _add_xy_sketch_text(
            label_sketch.sketchTexts,
            build_contact_patch_label_text(contact_patch, relationship),
            float(center[0]),
            float(center[1]),
            label_height,
        )
        warnings.append(
            "Contact patch rectangle is drawn on an offset construction-plane sketch (sketch cleanup is reliable in Fusion)."
        )

        return build_contact_patch_overlay_report(
            contact_patch,
            relationship,
            ok=True,
            source=source,
            created=created,
            warnings=warnings,
        )
    except Exception as ex:
        errors.append(str(ex))
        errors.append(traceback.format_exc())
        return build_contact_patch_overlay_report(
            contact_patch,
            relationship,
            ok=False,
            source=source,
            created=created,
            errors=errors,
            warnings=warnings,
        )


def _delete_artifact_entities(collection, predicate, errors: List[str], label: str) -> List[str]:
    removed: List[str] = []
    if collection is None:
        return removed
    try:
        count = collection.count
    except Exception:
        return removed
    for index in range(count - 1, -1, -1):
        try:
            entity = collection.item(index)
        except Exception:
            continue
        if not entity or not predicate(entity):
            continue
        name = str(getattr(entity, "name", "") or "")
        try:
            entity.deleteMe()
            removed.append(name)
        except Exception as ex:
            errors.append("Failed to delete {} {}: {}".format(label, name or index, ex))
    return removed


def clear_contact_patch_overlays(root) -> Dict[str, Any]:
    if root is None:
        return {
            "ok": False,
            "action": "relationships.clearContactPatchOverlays",
            "errors": ["Fusion root component unavailable."],
        }

    errors: List[str] = []
    removed_sketches = _delete_artifact_entities(
        root.sketches,
        is_contact_patch_artifact_entity,
        errors,
        "sketch",
    )
    removed_planes = _delete_artifact_entities(
        root.constructionPlanes,
        is_contact_patch_artifact_entity,
        errors,
        "plane",
    )
    # Legacy Custom Graphics overlays from v1 runs — best-effort cleanup.
    removed_graphics = _delete_artifact_entities(
        getattr(root, "customGraphicsGroups", None),
        is_contact_patch_artifact_entity,
        errors,
        "custom graphics",
    )

    return {
        "ok": not errors,
        "action": "relationships.clearContactPatchOverlays",
        "operationType": OPERATION_TYPE,
        "removedSketches": removed_sketches,
        "removedPlanes": removed_planes,
        "removedCustomGraphics": removed_graphics,
        "removedCount": len(removed_sketches) + len(removed_planes) + len(removed_graphics),
        "errors": errors,
    }
