"""M4.6A relationship visual overlay — pure logic (offline-testable)."""

from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional, Tuple

try:
    from screw_hole_from_relationship import resolve_relationship_verification
except Exception:

    def resolve_relationship_verification(relationship):  # type: ignore
        raw = (relationship or {}).get("verification") or {}
        return {
            "level": str(raw.get("level") or "bbox_candidate"),
            "safeForPreview": bool(raw.get("safeForPreview", True)),
            "safeForCut": bool(raw.get("safeForCut", False)),
            "requiresManualConfirmation": bool(raw.get("requiresManualConfirmation", True)),
        }


OPERATION_TYPE = "RELATIONSHIP_VISUAL_OVERLAY"
ARTIFACT_ATTR_GROUP = "UnifiedCabinetPlugin"
ARTIFACT_ATTR_OPERATION = "operationType"
ARTIFACT_ATTR_DEMO = "demoArtifact"
ARTIFACT_ATTR_RELATIONSHIP_ID = "sourceRelationshipId"
ARTIFACT_ATTR_OVERLAY_ROLE = "overlayRole"

OVERLAY_SKETCH_PREFIX = "REL_OVERLAY_"
OVERLAY_PLANE_PREFIX = "REL_OVERLAY_PLANE_"
OVERLAY_CUSTOM_GRAPHICS_PREFIX = "REL_OVERLAY_CG_"

MIN_OVERLAY_SEGMENT_MM = 10.0


def _cross(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> Tuple[float, float, float]:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _normalize(vec: Tuple[float, float, float]) -> Optional[Tuple[float, float, float]]:
    mag = math.sqrt(vec[0] ** 2 + vec[1] ** 2 + vec[2] ** 2)
    if mag <= 1e-9:
        return None
    return (vec[0] / mag, vec[1] / mag, vec[2] / mag)


def compute_segment_plane_normal(
    dx: float,
    dy: float,
    dz: float,
) -> Tuple[float, float, float]:
    """Return a unit normal for the plane containing segment (dx, dy, dz)."""
    direction = _normalize((dx, dy, dz))
    if direction is None:
        raise ValueError("Relationship overlay segment length is zero.")

    for ref in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)):
        normal = _normalize(_cross(direction, ref))
        if normal is not None:
            return normal
    raise ValueError("Could not derive overlay plane normal.")


def bbox_center_mm(bbox: Dict[str, Any]) -> Tuple[float, float, float]:
    return (
        (float(bbox.get("x0", 0.0)) + float(bbox.get("x1", 0.0))) / 2.0,
        (float(bbox.get("y0", 0.0)) + float(bbox.get("y1", 0.0))) / 2.0,
        (float(bbox.get("z0", 0.0)) + float(bbox.get("z1", 0.0))) / 2.0,
    )


def panel_center_from_dict(panel: Dict[str, Any]) -> Tuple[float, float, float]:
    bbox = panel.get("bbox") or {}
    return bbox_center_mm(bbox)


def resolve_panel_centers_mm(
    relationship: Dict[str, Any],
    panels_map: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    panel_a = relationship.get("panelA") or {}
    panel_b = relationship.get("panelB") or {}
    roles = relationship.get("roles") or {}
    host_id = roles.get("hostPanelId")
    target_id = roles.get("targetPanelId")
    panel_a_id = panel_a.get("panelId")
    panel_b_id = panel_b.get("panelId")

    centers: Dict[str, Tuple[float, float, float]] = {}
    if panels_map:
        if panel_a_id and panel_a_id in panels_map:
            centers[panel_a_id] = panel_center_from_dict(panels_map[panel_a_id])
        if panel_b_id and panel_b_id in panels_map:
            centers[panel_b_id] = panel_center_from_dict(panels_map[panel_b_id])

    result = {
        "panelAId": panel_a_id,
        "panelBId": panel_b_id,
        "hostPanelId": host_id,
        "targetPanelId": target_id,
        "panelA": centers.get(panel_a_id),
        "panelB": centers.get(panel_b_id),
        "host": centers.get(host_id) if host_id else None,
        "target": centers.get(target_id) if target_id else None,
    }
    if result["panelA"] and result["panelB"]:
        mid = (
            (result["panelA"][0] + result["panelB"][0]) / 2.0,
            (result["panelA"][1] + result["panelB"][1]) / 2.0,
            (result["panelA"][2] + result["panelB"][2]) / 2.0,
        )
        result["midpoint"] = mid
    return result


def build_overlay_label_text(relationship: Dict[str, Any]) -> str:
    verification = resolve_relationship_verification(relationship)
    lines = [
        str(relationship.get("relationshipType") or "unknown"),
        str(relationship.get("geometryType") or "none"),
        str(verification.get("level") or "bbox_candidate"),
        "safeForCut={}".format(str(bool(verification.get("safeForCut"))).lower()),
    ]
    return "\n".join(lines)


def build_host_target_label_text(role: str, panel_id: Optional[str]) -> str:
    token = str(panel_id or "unknown")
    return "{}: {}".format(role, token)


def build_overlay_metadata(relationship: Dict[str, Any]) -> Dict[str, Any]:
    rel_id = str(relationship.get("relationshipId") or "")
    verification = resolve_relationship_verification(relationship)
    return {
        "operationType": OPERATION_TYPE,
        "demoArtifact": True,
        "sourceRelationshipId": rel_id,
        "relationshipType": relationship.get("relationshipType"),
        "geometryType": relationship.get("geometryType"),
        "verificationLevel": verification.get("level"),
        "safeForCut": bool(verification.get("safeForCut")),
    }


def overlay_metadata_json(metadata: Dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def is_overlay_custom_graphics_name(name: str) -> bool:
    return str(name or "").startswith(OVERLAY_CUSTOM_GRAPHICS_PREFIX)


def _distance_mm(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return math.sqrt((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2)


def _axis_unit_vector(axis: str) -> Tuple[float, float, float]:
    token = str(axis or "Y").upper()
    if token == "X":
        return (1.0, 0.0, 0.0)
    if token == "Z":
        return (0.0, 0.0, 1.0)
    return (0.0, 1.0, 0.0)


def ensure_distinct_overlay_endpoints_mm(
    panel_a: Tuple[float, float, float],
    panel_b: Tuple[float, float, float],
    relationship: Optional[Dict[str, Any]] = None,
    *,
    min_span_mm: float = MIN_OVERLAY_SEGMENT_MM,
) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    """Guarantee two distinct overlay endpoints even when panel centers coincide."""
    if _distance_mm(panel_a, panel_b) >= min_span_mm:
        return panel_a, panel_b

    contact = (relationship or {}).get("contact") or {}
    axis = _axis_unit_vector(str(contact.get("axis") or "Y"))
    half = max(min_span_mm / 2.0, 5.0)
    mid = (
        (panel_a[0] + panel_b[0]) / 2.0,
        (panel_a[1] + panel_b[1]) / 2.0,
        (panel_a[2] + panel_b[2]) / 2.0,
    )
    return (
        (
            mid[0] - axis[0] * half,
            mid[1] - axis[1] * half,
            mid[2] - axis[2] * half,
        ),
        (
            mid[0] + axis[0] * half,
            mid[1] + axis[1] * half,
            mid[2] + axis[2] * half,
        ),
    )


def is_overlay_sketch_name(name: str) -> bool:
    return str(name or "").startswith(OVERLAY_SKETCH_PREFIX)


def is_overlay_plane_name(name: str) -> bool:
    return str(name or "").startswith(OVERLAY_PLANE_PREFIX)


def _read_attr(entity, group: str, name: str) -> Optional[str]:
    if entity is None:
        return None
    attrs = getattr(entity, "attributes", None)
    if not attrs:
        return None
    try:
        item = attrs.itemByName(group, name)
        if item:
            return str(item.value)
    except Exception:
        return None
    return None


def is_overlay_artifact_entity(entity) -> bool:
    if entity is None:
        return False
    name = str(getattr(entity, "name", "") or "")
    if is_overlay_sketch_name(name) or is_overlay_plane_name(name) or is_overlay_custom_graphics_name(name):
        return True
    operation = _read_attr(entity, ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_OPERATION)
    demo = _read_attr(entity, ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_DEMO)
    return operation == OPERATION_TYPE and demo in ("true", "True", "1")


def list_overlay_cleanup_targets(sketches, construction_planes, custom_graphics_groups=None) -> Dict[str, List[str]]:
    sketch_names: List[str] = []
    plane_names: List[str] = []
    graphics_names: List[str] = []

    try:
        count = sketches.count if sketches else 0
    except Exception:
        count = 0
    for index in range(count):
        try:
            sketch = sketches.item(index)
        except Exception:
            continue
        if is_overlay_artifact_entity(sketch):
            sketch_names.append(str(sketch.name))

    try:
        plane_count = construction_planes.count if construction_planes else 0
    except Exception:
        plane_count = 0
    for index in range(plane_count):
        try:
            plane = construction_planes.item(index)
        except Exception:
            continue
        if is_overlay_artifact_entity(plane):
            plane_names.append(str(plane.name))

    try:
        graphics_count = custom_graphics_groups.count if custom_graphics_groups else 0
    except Exception:
        graphics_count = 0
    for index in range(graphics_count):
        try:
            group = custom_graphics_groups.item(index)
        except Exception:
            continue
        if is_overlay_artifact_entity(group):
            graphics_names.append(str(group.name))

    return {
        "sketches": sorted(sketch_names),
        "planes": sorted(plane_names),
        "customGraphics": sorted(graphics_names),
    }


def is_protected_cleanup_name(name: str) -> bool:
    token = str(name or "")
    protected_prefixes = (
        "WorkZone",
        "HW_REL_SCREW_HOLE",
        "HW_SIDE_CONTACT",
        "REL_TEST_FIXTURE",
    )
    return any(token.startswith(prefix) for prefix in protected_prefixes)


def resolve_overlay_relationship(
    scan_result: Optional[Dict[str, Any]],
    relationship: Optional[Dict[str, Any]] = None,
    *,
    source: str = "selected",
) -> Optional[Dict[str, Any]]:
    if isinstance(relationship, dict):
        return relationship
    if not isinstance(scan_result, dict):
        return None
    relationships = scan_result.get("relationships") or []
    if len(relationships) == 1 and isinstance(relationships[0], dict):
        return relationships[0]
    return None


def build_overlay_report(
    relationship: Dict[str, Any],
    *,
    ok: bool,
    source: str,
    created: Optional[Dict[str, Any]] = None,
    errors: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    verification = resolve_relationship_verification(relationship)
    return {
        "ok": bool(ok),
        "action": "relationships.showRelationshipOverlayForSelected",
        "operationType": OPERATION_TYPE,
        "source": source,
        "relationshipId": relationship.get("relationshipId"),
        "relationshipType": relationship.get("relationshipType"),
        "geometryType": relationship.get("geometryType"),
        "verification": verification,
        "labelText": build_overlay_label_text(relationship),
        "metadata": build_overlay_metadata(relationship),
        "created": created or {},
        "errors": list(errors or []),
        "warnings": list(warnings or []),
    }
