"""Relationship regression fixture definitions and Fusion body creation."""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from relationship_geometry import CONTACT_TOLERANCE_MM
from relationship_models import BBoxMm, PanelSnapshot
from relationship_service import build_panel_snapshot_from_dict, scan_relationships

try:
    import adsk.core as adsk_core
    import adsk.fusion as adsk_fusion
except Exception:
    adsk_core = None
    adsk_fusion = None

try:
    from geometry_ops import ATTRIBUTE_GROUP, mm_to_cm, sanitize_token
except Exception:
    ATTRIBUTE_GROUP = "UnifiedCabinetPlugin"

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

try:
    from modules.general_tall.fusion_adapter import _add_box_body
except Exception:
    _add_box_body = None

try:
    from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, PANEL_METADATA_ATTR
except Exception:
    PANEL_ATTRIBUTE_GROUP = "UnifiedCabinet.Panel"
    PANEL_ID_ATTR = "panelId"
    PANEL_METADATA_ATTR = "metadata"

FIXTURE_BASE_Z_MM = 12000.0
FIXTURE_PART_BASE_Z_MM = 0.0
FIXTURE_PART_X_OFFSET_MM = 3200.0
FIXTURE_PANEL_IDS = frozenset(
    {
        "REL_SURFACE_B",
        "REL_EDGE_A",
        "REL_SURFACE_A",
        "REL_SURFACE_B2",
        "REL_GAP_A",
        "REL_GAP_B",
        "REL_COLLISION_A",
        "REL_COLLISION_B",
        "REL_NONE_A",
        "REL_NONE_B",
    }
)
FIXTURE_SPACING_X_MM = 1200.0


def resolve_fixture_base_z_mm(flat_mode: bool) -> float:
    """Part designs place fixtures at ground level so bodies are visible in the viewport."""
    return FIXTURE_PART_BASE_Z_MM if flat_mode else FIXTURE_BASE_Z_MM


def resolve_fixture_base_x_mm(flat_mode: bool) -> float:
    """Shift part-mode fixtures away from typical cabinet geometry at the origin."""
    return FIXTURE_PART_X_OFFSET_MM if flat_mode else 0.0


def expected_fixture_cases() -> List[Dict[str, Any]]:
    return [
        {
            "caseId": "edge_to_surface_001",
            "panelAId": "REL_EDGE_A",
            "panelBId": "REL_SURFACE_B",
            "expectedGeometryType": "edge_to_surface",
        },
        {
            "caseId": "surface_to_surface_001",
            "panelAId": "REL_SURFACE_A",
            "panelBId": "REL_SURFACE_B2",
            "expectedGeometryType": "surface_to_surface",
        },
        {
            "caseId": "gap_parallel_001",
            "panelAId": "REL_GAP_A",
            "panelBId": "REL_GAP_B",
            "expectedGeometryType": "gap_parallel",
        },
        {
            "caseId": "intersection_collision_001",
            "panelAId": "REL_COLLISION_A",
            "panelBId": "REL_COLLISION_B",
            "expectedGeometryType": "intersection",
        },
        {
            "caseId": "no_contact_001",
            "panelAId": "REL_NONE_A",
            "panelBId": "REL_NONE_B",
            "expectedGeometryType": "none",
        },
    ]


def fixture_panel_definitions(
    base_z_mm: Optional[float] = None,
    base_x_mm: Optional[float] = None,
) -> List[Dict[str, Any]]:
    """Pure-data fixture layout used for offline tests and Fusion creation."""
    z = FIXTURE_BASE_Z_MM if base_z_mm is None else float(base_z_mm)
    ox = 0.0 if base_x_mm is None else float(base_x_mm)
    panels = _fixture_panel_definitions_at_z(z)
    if not ox:
        return panels
    shifted: List[Dict[str, Any]] = []
    for panel in panels:
        item = dict(panel)
        bbox = dict(item["bbox"])
        bbox["x0"] = float(bbox["x0"]) + ox
        bbox["x1"] = float(bbox["x1"]) + ox
        item["bbox"] = bbox
        shifted.append(item)
    return shifted


def _fixture_panel_definitions_at_z(z: float) -> List[Dict[str, Any]]:
    return [
        {
            "caseId": "edge_to_surface_001",
            "panelId": "REL_SURFACE_B",
            "bodyName": "REL_SURFACE_B",
            "boardType": "carcass_panel",
            "role": "surface",
            "bbox": {"x0": 0, "x1": 300, "y0": 0, "y1": 300, "z0": z, "z1": z + 16},
        },
        {
            "caseId": "edge_to_surface_001",
            "panelId": "REL_EDGE_A",
            "bodyName": "REL_EDGE_A",
            "boardType": "structural_edge",
            "role": "edge",
            "bbox": {"x0": 0, "x1": 300, "y0": 300, "y1": 315, "z0": z, "z1": z + 300},
        },
        {
            "caseId": "surface_to_surface_001",
            "panelId": "REL_SURFACE_A",
            "bodyName": "REL_SURFACE_A",
            "boardType": "face_panel",
            "role": "face",
            "bbox": {"x0": 500, "x1": 800, "y0": 0, "y1": 300, "z0": z, "z1": z + 16},
        },
        {
            "caseId": "surface_to_surface_001",
            "panelId": "REL_SURFACE_B2",
            "bodyName": "REL_SURFACE_B2",
            "boardType": "face_panel",
            "role": "face",
            "bbox": {"x0": 500, "x1": 800, "y0": 0, "y1": 300, "z0": z + 16, "z1": z + 32},
        },
        {
            "caseId": "gap_parallel_001",
            "panelId": "REL_GAP_A",
            "bodyName": "REL_GAP_A",
            "boardType": "door_panel",
            "role": "door",
            "bbox": {"x0": 1000, "x1": 1300, "y0": 0, "y1": 300, "z0": z, "z1": z + 16},
        },
        {
            "caseId": "gap_parallel_001",
            "panelId": "REL_GAP_B",
            "bodyName": "REL_GAP_B",
            "boardType": "carcass_side",
            "role": "carcass",
            "bbox": {"x0": 1000, "x1": 1300, "y0": 0, "y1": 300, "z0": z + 20, "z1": z + 36},
        },
        {
            "caseId": "intersection_collision_001",
            "panelId": "REL_COLLISION_A",
            "bodyName": "REL_COLLISION_A",
            "boardType": "panel",
            "role": "collision",
            "bbox": {"x0": 1500, "x1": 1800, "y0": 0, "y1": 300, "z0": z, "z1": z + 200},
        },
        {
            "caseId": "intersection_collision_001",
            "panelId": "REL_COLLISION_B",
            "bodyName": "REL_COLLISION_B",
            "boardType": "panel",
            "role": "collision",
            "bbox": {"x0": 1600, "x1": 1900, "y0": 50, "y1": 250, "z0": z + 50, "z1": z + 150},
        },
        {
            "caseId": "no_contact_001",
            "panelId": "REL_NONE_A",
            "bodyName": "REL_NONE_A",
            "boardType": "panel",
            "role": "isolated",
            "bbox": {"x0": 2000, "x1": 2200, "y0": 0, "y1": 200, "z0": z, "z1": z + 16},
        },
        {
            "caseId": "no_contact_001",
            "panelId": "REL_NONE_B",
            "bodyName": "REL_NONE_B",
            "boardType": "panel",
            "role": "isolated",
            "bbox": {"x0": 2400, "x1": 2600, "y0": 0, "y1": 200, "z0": z, "z1": z + 16},
        },
    ]


def build_fixture_snapshots() -> List[PanelSnapshot]:
    return [build_panel_snapshot_from_dict(item) for item in fixture_panel_definitions()]


def evaluate_fixture_expectations(
    *,
    tolerance_mm: float = CONTACT_TOLERANCE_MM,
    include_none: bool = True,
) -> Dict[str, Any]:
    panels = build_fixture_snapshots()
    panel_map = {panel.panelId: panel for panel in panels}
    relationships = []
    for fixture in expected_fixture_cases():
        panel_a = panel_map.get(fixture["panelAId"])
        panel_b = panel_map.get(fixture["panelBId"])
        if not panel_a or not panel_b:
            continue
        from relationship_geometry import classify_pair

        relationship = classify_pair(panel_a, panel_b, tolerance_mm=tolerance_mm)
        if include_none or relationship.geometryType != "none":
            relationships.append(relationship)
    from relationship_report import build_scan_report

    return build_scan_report(
        action="relationships.fixtureEvaluation",
        panels=panels,
        relationships=relationships,
        scope="fixture",
        tolerance_mm=tolerance_mm,
        expected_fixtures=expected_fixture_cases(),
    )


def _is_part_design(root_component) -> bool:
    """Fusion Part designs allow only one component — fixtures must use flat multi-body mode."""
    if not root_component:
        return True
    try:
        design = root_component.parentDesign
        if design is not None and adsk_fusion is not None:
            return design.designType == adsk_fusion.DesignTypes.PartDesignType
    except Exception:
        pass
    return False


def _new_component(parent_component, name):
    transform = adsk_core.Matrix3D.create()
    occurrence = parent_component.occurrences.addNewComponent(transform)
    component = occurrence.component
    component.name = name
    return component


def _resolve_fixture_container(root_component, assembly_name):
    """Return (container_component, flat_mode).

    Assembly designs get a dedicated child component. Part designs cannot add
    sub-components, so bodies are created directly on the root component.
    """
    if _is_part_design(root_component):
        return root_component, True
    try:
        return _new_component(root_component, assembly_name), False
    except Exception:
        return root_component, True


def _panel_metadata_payload(panel_id, panel_def):
    bbox = panel_def["bbox"]
    thickness_candidates = (
        abs(float(bbox["x1"]) - float(bbox["x0"])),
        abs(float(bbox["y1"]) - float(bbox["y0"])),
        abs(float(bbox["z1"]) - float(bbox["z0"])),
    )
    return {
        "schemaVersion": 1,
        "panelId": panel_id,
        "panelType": panel_def.get("boardType") or "PANEL",
        "description": "Relationship fixture {}".format(panel_def.get("caseId")),
        "tags": ["relationship-fixture", panel_def.get("role") or "panel"],
        "thicknessMm": min(thickness_candidates),
    }


def _write_panel_metadata(component, panel_id, panel_def):
    metadata = _panel_metadata_payload(panel_id, panel_def)
    payload = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    _set_attribute(component.attributes, PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, panel_id)
    _set_attribute(component.attributes, PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR, payload)


def _write_body_panel_metadata(body, panel_id, panel_def):
    metadata = _panel_metadata_payload(panel_id, panel_def)
    payload = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    _set_attribute(body.attributes, PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, panel_id)
    _set_attribute(body.attributes, PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR, payload)


def _set_attribute(attrs, group, name, value):
    existing = attrs.itemByName(group, name) if attrs else None
    if existing:
        existing.value = str(value)
    else:
        attrs.add(group, name, str(value))


def _body_is_relationship_fixture(body) -> bool:
    try:
        name = str(getattr(body, "name", "") or "")
        if name in FIXTURE_PANEL_IDS or name.startswith("REL_"):
            return True
        attrs = getattr(body, "attributes", None)
        if attrs is None:
            return False
        marker = attrs.itemByName(ATTRIBUTE_GROUP, "relationshipFixture")
        if marker is not None:
            return True
        panel_attr = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR)
        if panel_attr is not None and str(panel_attr.value or "") in FIXTURE_PANEL_IDS:
            return True
    except Exception:
        return False
    return False


def _delete_entity(entity) -> bool:
    try:
        if entity is not None:
            entity.deleteMe()
            return True
    except Exception:
        return False
    return False


def clear_relationship_test_fixtures(root_component) -> Dict[str, Any]:
    """Remove prior REL_* fixture bodies/occurrences so smokes do not hit stale geometry."""
    removed_bodies = 0
    removed_occurrences = 0
    errors: List[str] = []
    if not root_component:
        return {"ok": False, "removedBodies": 0, "removedOccurrences": 0, "errors": ["Missing root."]}

    def clear_component_bodies(component) -> None:
        nonlocal removed_bodies
        try:
            bodies = component.bRepBodies
            for index in range(bodies.count - 1, -1, -1):
                body = bodies.item(index)
                if _body_is_relationship_fixture(body) and _delete_entity(body):
                    removed_bodies += 1
        except Exception as ex:
            errors.append("body cleanup: {}".format(ex))

    clear_component_bodies(root_component)
    try:
        occurrences = root_component.occurrences
        for index in range(occurrences.count - 1, -1, -1):
            occ = occurrences.item(index)
            try:
                name = str(getattr(occ.component, "name", "") or "")
            except Exception:
                name = ""
            if name.startswith("REL_TEST_FIXTURE_") or name in FIXTURE_PANEL_IDS:
                if _delete_entity(occ):
                    removed_occurrences += 1
                    continue
            try:
                clear_component_bodies(occ.component)
            except Exception as ex:
                errors.append("occ body cleanup: {}".format(ex))
    except Exception as ex:
        errors.append("occurrence cleanup: {}".format(ex))

    return {
        "ok": not errors,
        "removedBodies": removed_bodies,
        "removedOccurrences": removed_occurrences,
        "errors": errors,
    }


def create_relationship_test_fixture(root_component) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[str], Dict[str, Any]]:
    if not root_component or _add_box_body is None or adsk_core is None:
        return [], "Fusion API or box-body helper is unavailable.", None

    cleanup = clear_relationship_test_fixtures(root_component)

    run_id = time.strftime("%H%M%S")
    assembly_name = "REL_TEST_FIXTURE_{}".format(run_id)
    assembly, flat_mode = _resolve_fixture_container(root_component, assembly_name)
    base_z_mm = resolve_fixture_base_z_mm(flat_mode)
    base_x_mm = resolve_fixture_base_x_mm(flat_mode)
    placement = {
        "baseZMm": base_z_mm,
        "baseXMm": base_x_mm,
        "flatMode": flat_mode,
        "cleanup": cleanup,
    }
    mode_note = None
    if flat_mode:
        mode_note = (
            "Part design detected: fixture bodies were created on the root component at "
            "Z={:.0f} mm, X+{:.0f} mm (visible near the model floor).".format(base_z_mm, base_x_mm)
        )
    if cleanup.get("removedBodies") or cleanup.get("removedOccurrences"):
        note = "Cleared prior relationship fixtures: bodies={} occurrences={}.".format(
            cleanup.get("removedBodies"),
            cleanup.get("removedOccurrences"),
        )
        mode_note = "{}; {}".format(mode_note, note) if mode_note else note
    created: List[Dict[str, Any]] = []

    for panel_def in fixture_panel_definitions(base_z_mm=base_z_mm, base_x_mm=base_x_mm):
        panel_id = panel_def["panelId"]
        if flat_mode:
            component = root_component
        else:
            try:
                component = _new_component(assembly, panel_id)
            except Exception as ex:
                hint = (
                    " Fusion 零件文档只能有一个零部件；请改用「部件 Assembly」文档，"
                    "或更新插件后在当前零件文档使用 flat 模式（测试板落在根零部件上）。"
                )
                message = "Failed to create fixture component {}: {}{}".format(panel_id, ex, hint)
                return created, message, mode_note
        body, error = _add_box_body(
            component,
            panel_id,
            panel_def["bbox"],
            body_prefix="REL",
            module_name="relationships",
            move_prefix="REL_MOVE_",
        )
        if error:
            return created, error, mode_note
        body.name = panel_def["bodyName"]
        if not flat_mode:
            _write_panel_metadata(component, panel_id, panel_def)
        _write_body_panel_metadata(body, panel_id, panel_def)
        try:
            body.attributes.add(ATTRIBUTE_GROUP, "module", "relationships")
            body.attributes.add(ATTRIBUTE_GROUP, "panelId", panel_id)
            body.attributes.add(ATTRIBUTE_GROUP, "relationshipFixture", panel_def["caseId"])
            body.attributes.add(ATTRIBUTE_GROUP, "boardType", panel_def.get("boardType") or "panel")
            if panel_def.get("role"):
                body.attributes.add(ATTRIBUTE_GROUP, "role", panel_def["role"])
        except Exception:
            pass
        created.append(
            {
                "caseId": panel_def["caseId"],
                "panelId": panel_id,
                "bodyName": body.name,
                "componentName": component.name,
                "bbox": panel_def["bbox"],
                "flatMode": flat_mode,
                "_fusionBody": body,
            }
        )

    try:
        marker_component = root_component if flat_mode else assembly
        marker_component.attributes.add(ATTRIBUTE_GROUP, "module", "relationships")
        marker_component.attributes.add(ATTRIBUTE_GROUP, "testFixture", "boardRelationship")
        if flat_mode:
            marker_component.attributes.add(ATTRIBUTE_GROUP, "relationshipFixtureMode", "partRootFlat")
    except Exception:
        pass

    return created, None, mode_note, placement
