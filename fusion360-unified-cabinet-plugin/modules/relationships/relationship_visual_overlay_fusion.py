"""Fusion geometry for M4.6A relationship visual overlay."""

from __future__ import annotations

import math
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple

try:
    import adsk.core as adsk_core
    import adsk.fusion as adsk_fusion
except Exception:
    adsk_core = None
    adsk_fusion = None

from relationship_visual_overlay import (
    ARTIFACT_ATTR_DEMO,
    ARTIFACT_ATTR_GROUP,
    ARTIFACT_ATTR_OPERATION,
    ARTIFACT_ATTR_OVERLAY_ROLE,
    ARTIFACT_ATTR_RELATIONSHIP_ID,
    OPERATION_TYPE,
    OVERLAY_CUSTOM_GRAPHICS_PREFIX,
    OVERLAY_SKETCH_PREFIX,
    build_host_target_label_text,
    build_overlay_label_text,
    build_overlay_metadata,
    build_overlay_report,
    ensure_distinct_overlay_endpoints_mm,
    is_overlay_artifact_entity,
    list_overlay_cleanup_targets,
    overlay_metadata_json,
    panel_center_from_dict,
    resolve_overlay_relationship,
    resolve_panel_centers_mm,
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


OVERLAY_FUSION_BUILD = "2026-07-03-custom-graphics-v3"


def _point_cm(x_mm: float, y_mm: float, z_mm: float):
    return adsk_core.Point3D.create(mm_to_cm(x_mm), mm_to_cm(y_mm), mm_to_cm(z_mm))


def _body_center_mm(body) -> Tuple[float, float, float]:
    bbox = body.boundingBox
    return (
        (bbox.minPoint.x + bbox.maxPoint.x) * 5.0,
        (bbox.minPoint.y + bbox.maxPoint.y) * 5.0,
        (bbox.minPoint.z + bbox.maxPoint.z) * 5.0,
    )


def find_body_by_panel_id(root, panel_id: str):
    panel_id = str(panel_id or "").strip()
    if not panel_id or not root:
        return None
    try:
        from panel_body_resolver import list_solid_bodies
    except Exception:
        return None

    def walk(component):
        for body in list_solid_bodies(component):
            try:
                from relationship_service import read_panel_metadata

                if str(read_panel_metadata(body).get("panelId") or "").strip() == panel_id:
                    return body
            except Exception:
                continue
        try:
            occurrences = component.occurrences
            count = occurrences.count if occurrences else 0
        except Exception:
            return None
        for index in range(count):
            found = walk(occurrences.item(index).component)
            if found:
                return found
        return None

    return walk(root)


def _tag_entity(entity, metadata: Dict[str, Any], overlay_role: str) -> None:
    if entity is None:
        return
    try:
        attrs = entity.attributes
        attrs.add(ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_OPERATION, OPERATION_TYPE)
        attrs.add(ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_DEMO, "true")
        attrs.add(ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_RELATIONSHIP_ID, str(metadata.get("sourceRelationshipId") or ""))
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
        return
    except Exception:
        pass
    try:
        text_input = texts.createInput(content, height_cm)
        text_input.position = adsk_core.Point3D.create(cx, cy, 0.0)
        texts.add(text_input)
    except Exception:
        pass


def _create_custom_graphics_line(root, p0_mm: Tuple[float, float, float], p1_mm: Tuple[float, float, float], name: str, metadata: Dict[str, Any]):
    groups = root.customGraphicsGroups
    group = groups.add()
    group.name = name
    _tag_entity(group, metadata, "line")

    coords = adsk_fusion.CustomGraphicsCoordinates.create(
        [
            mm_to_cm(p0_mm[0]),
            mm_to_cm(p0_mm[1]),
            mm_to_cm(p0_mm[2]),
            mm_to_cm(p1_mm[0]),
            mm_to_cm(p1_mm[1]),
            mm_to_cm(p1_mm[2]),
        ]
    )
    lines = group.addLines(coords, [], False)
    lines.weight = 3
    try:
        solid_color = adsk_fusion.CustomGraphicsSolidColorEffect.create(
            adsk_core.Color.create(255, 140, 0, 255)
        )
        lines.color = solid_color
    except Exception:
        pass
    return group


def _resolve_centers(root, relationship, panels_map) -> Dict[str, Tuple[float, float, float]]:
    centers = resolve_panel_centers_mm(relationship, panels_map)
    resolved: Dict[str, Tuple[float, float, float]] = {}

    def _center_for(panel_id: Optional[str], fallback):
        if not panel_id:
            return fallback
        body = find_body_by_panel_id(root, panel_id)
        if body:
            return _body_center_mm(body)
        if panels_map and panel_id in panels_map:
            return panel_center_from_dict(panels_map[panel_id])
        return fallback

    panel_a_id = centers.get("panelAId")
    panel_b_id = centers.get("panelBId")
    host_id = centers.get("hostPanelId")
    target_id = centers.get("targetPanelId")

    if panel_a_id:
        resolved["panelA"] = _center_for(panel_a_id, centers.get("panelA"))
    if panel_b_id:
        resolved["panelB"] = _center_for(panel_b_id, centers.get("panelB"))
    if host_id:
        resolved["host"] = _center_for(host_id, centers.get("host"))
    if target_id:
        resolved["target"] = _center_for(target_id, centers.get("target"))

    if resolved.get("panelA") and resolved.get("panelB"):
        a, b = ensure_distinct_overlay_endpoints_mm(
            resolved["panelA"],
            resolved["panelB"],
            relationship,
        )
        resolved["panelA"] = a
        resolved["panelB"] = b
        resolved["midpoint"] = ((a[0] + b[0]) / 2.0, (a[1] + b[1]) / 2.0, (a[2] + b[2]) / 2.0)
    return resolved


def create_relationship_overlay(
    root,
    relationship: Dict[str, Any],
    panels_map: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    source: str = "selected",
) -> Dict[str, Any]:
    metadata = build_overlay_metadata(relationship)
    run_token = sanitize_token(str(int(time.time())), limit=24)
    created = {"sketches": [], "planes": [], "customGraphics": []}
    errors: List[str] = []
    warnings: List[str] = []

    if root is None or adsk_core is None or adsk_fusion is None:
        return build_overlay_report(
            relationship,
            ok=False,
            source=source,
            errors=["Fusion root component unavailable."],
        )

    centers = _resolve_centers(root, relationship, panels_map or {})
    if not centers.get("panelA") or not centers.get("panelB"):
        return build_overlay_report(
            relationship,
            ok=False,
            source=source,
            errors=["Could not resolve panel centers for overlay line."],
        )

    p0_mm = centers["panelA"]
    p1_mm = centers["panelB"]
    span_mm = max(
        abs(p1_mm[0] - p0_mm[0]),
        abs(p1_mm[1] - p0_mm[1]),
        abs(p1_mm[2] - p0_mm[2]),
        50.0,
    )
    label_height_mm = max(min(span_mm * 0.08, 40.0), 8.0)
    role_height_mm = max(label_height_mm * 0.65, 6.0)

    try:
        cg_name = "{}{}_LINE".format(OVERLAY_CUSTOM_GRAPHICS_PREFIX, run_token)
        _create_custom_graphics_line(root, p0_mm, p1_mm, cg_name, metadata)
        created["customGraphics"].append(cg_name)

        label_sketch = root.sketches.add(root.xYConstructionPlane)
        label_sketch.name = "{}{}_LABEL".format(OVERLAY_SKETCH_PREFIX, run_token)
        _tag_entity(label_sketch, metadata, "main_label")
        created["sketches"].append(label_sketch.name)

        midpoint = centers.get("midpoint") or (
            (p0_mm[0] + p1_mm[0]) / 2.0,
            (p0_mm[1] + p1_mm[1]) / 2.0,
            (p0_mm[2] + p1_mm[2]) / 2.0,
        )
        texts = label_sketch.sketchTexts
        _add_xy_sketch_text(
            texts,
            build_overlay_label_text(relationship),
            midpoint[0],
            midpoint[1],
            label_height_mm,
        )

        roles = relationship.get("roles") or {}
        host_id = roles.get("hostPanelId")
        target_id = roles.get("targetPanelId")
        if host_id and centers.get("host"):
            _add_xy_sketch_text(
                texts,
                build_host_target_label_text("host", host_id),
                centers["host"][0],
                centers["host"][1],
                role_height_mm,
            )
        if target_id and centers.get("target"):
            _add_xy_sketch_text(
                texts,
                build_host_target_label_text("target", target_id),
                centers["target"][0],
                centers["target"][1],
                role_height_mm,
            )

        warnings.append(
            "Overlay line uses Custom Graphics in 3D; labels are drawn on the root XY sketch plane for debug readability."
        )

        return build_overlay_report(
            relationship,
            ok=True,
            source=source,
            created=created,
            warnings=warnings,
        )
    except Exception as ex:
        errors.append(str(ex))
        errors.append(traceback.format_exc())
        return build_overlay_report(
            relationship,
            ok=False,
            source=source,
            created=created,
            errors=errors,
            warnings=warnings,
        )


def clear_relationship_overlays(root) -> Dict[str, Any]:
    if root is None:
        return {
            "ok": False,
            "action": "relationships.clearRelationshipOverlays",
            "errors": ["Fusion root component unavailable."],
        }

    targets = list_overlay_cleanup_targets(
        root.sketches,
        root.constructionPlanes,
        getattr(root, "customGraphicsGroups", None),
    )
    removed_sketches: List[str] = []
    removed_planes: List[str] = []
    removed_graphics: List[str] = []
    errors: List[str] = []

    for sketch_name in targets.get("sketches") or []:
        try:
            sketch = root.sketches.itemByName(sketch_name)
            if sketch and is_overlay_artifact_entity(sketch):
                sketch.deleteMe()
                removed_sketches.append(sketch_name)
        except Exception as ex:
            errors.append("Failed to delete sketch {}: {}".format(sketch_name, ex))

    for plane_name in targets.get("planes") or []:
        try:
            plane = root.constructionPlanes.itemByName(plane_name)
            if plane and is_overlay_artifact_entity(plane):
                plane.deleteMe()
                removed_planes.append(plane_name)
        except Exception as ex:
            errors.append("Failed to delete plane {}: {}".format(plane_name, ex))

    for group_name in targets.get("customGraphics") or []:
        try:
            groups = root.customGraphicsGroups
            group = groups.itemByName(group_name) if groups else None
            if group and is_overlay_artifact_entity(group):
                group.deleteMe()
                removed_graphics.append(group_name)
        except Exception as ex:
            errors.append("Failed to delete custom graphics {}: {}".format(group_name, ex))

    return {
        "ok": not errors,
        "action": "relationships.clearRelationshipOverlays",
        "operationType": OPERATION_TYPE,
        "removedSketches": removed_sketches,
        "removedPlanes": removed_planes,
        "removedCustomGraphics": removed_graphics,
        "removedCount": len(removed_sketches) + len(removed_planes) + len(removed_graphics),
        "errors": errors,
    }


def show_overlay_from_payload(root, payload: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    payload = payload if isinstance(payload, dict) else {}
    source = str(payload.get("source") or "selected")
    relationship = payload.get("relationship") if isinstance(payload.get("relationship"), dict) else None
    scan = payload.get("scan") if isinstance(payload.get("scan"), dict) else None
    panels_map = None
    if scan:
        panels_map = {p["panelId"]: p for p in (scan.get("panels") or []) if p.get("panelId")}

    resolved = resolve_overlay_relationship(scan, relationship, source=source)
    if not resolved:
        return {
            "ok": False,
            "action": "relationships.showRelationshipOverlayForSelected",
            "operationType": OPERATION_TYPE,
            "source": source,
            "errors": ["No relationship available for overlay. Select two panel bodies first."],
        }
    return create_relationship_overlay(root, resolved, panels_map, source=source)
