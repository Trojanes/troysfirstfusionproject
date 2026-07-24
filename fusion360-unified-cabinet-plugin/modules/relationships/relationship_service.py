"""Collect panel snapshots and compute pairwise board relationships."""

from __future__ import annotations

import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from relationship_geometry import CONTACT_TOLERANCE_MM, classify_pair, enrich_panel_snapshot
from relationship_models import BBoxMm, PanelSnapshot
from relationship_report import build_inspect_pair_report, build_scan_report

try:
    from panel_body_resolver import list_solid_bodies, read_body_panel_id
except Exception:
    list_solid_bodies = None
    read_body_panel_id = None

try:
    from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, PANEL_METADATA_ATTR
except Exception:
    PANEL_ATTRIBUTE_GROUP = "UnifiedCabinet.Panel"
    PANEL_ID_ATTR = "panelId"
    PANEL_METADATA_ATTR = "metadata"

LEGACY_ATTRIBUTE_GROUP = "UnifiedCabinetPlugin"
CABINETNC_ATTRIBUTE_GROUP = "CabinetNC"


def _attr_value(entity, group: str, name: str) -> str:
    if not entity:
        return ""
    try:
        attrs = entity.attributes
        attr = attrs.itemByName(group, name) if attrs else None
        return str(attr.value or "").strip() if attr and attr.value else ""
    except Exception:
        return ""


def _read_metadata_dict(entity) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    warnings: List[str] = []
    for owner in (entity, _parent_component(entity)):
        if not owner:
            continue
        raw = _attr_value(owner, PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR)
        if not raw:
            continue
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed, warnings
        except json.JSONDecodeError as ex:
            warnings.append("Invalid panel metadata JSON on {}: {}".format(getattr(entity, "name", "body"), ex))
    return None, warnings


def _parent_component(body):
    for attr_name in ("parentComponent", "component"):
        try:
            component = getattr(body, attr_name)
        except Exception:
            component = None
        if component:
            return component
    return None


def get_body_bbox_mm(body) -> BBoxMm:
    bbox = body.boundingBox
    min_pt = bbox.minPoint
    max_pt = bbox.maxPoint
    return BBoxMm(
        x0=min_pt.x * 10.0,
        x1=max_pt.x * 10.0,
        y0=min_pt.y * 10.0,
        y1=max_pt.y * 10.0,
        z0=min_pt.z * 10.0,
        z1=max_pt.z * 10.0,
    )


def read_panel_metadata(body) -> Dict[str, Any]:
    metadata, warnings = _read_metadata_dict(body)
    component = _parent_component(body)
    panel_id = (
        _attr_value(body, PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR)
        or _attr_value(component, PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR)
        or _attr_value(body, LEGACY_ATTRIBUTE_GROUP, "panelId")
        or _attr_value(body, CABINETNC_ATTRIBUTE_GROUP, "panelId")
        or _attr_value(body, LEGACY_ATTRIBUTE_GROUP, "boardId")
        or str(getattr(body, "name", "") or "")
    )
    board_type = (
        _attr_value(body, LEGACY_ATTRIBUTE_GROUP, "boardType")
        or _attr_value(body, CABINETNC_ATTRIBUTE_GROUP, "boardKind")
        or (metadata or {}).get("panelType")
        or (metadata or {}).get("boardType")
    )
    role = (
        _attr_value(body, LEGACY_ATTRIBUTE_GROUP, "hardwareTestRole")
        or (metadata or {}).get("role")
        or (metadata.get("tags", [None])[0] if isinstance(metadata, dict) and metadata.get("tags") else None)
    )
    source_board_id = _attr_value(body, LEGACY_ATTRIBUTE_GROUP, "boardId") or _attr_value(body, CABINETNC_ATTRIBUTE_GROUP, "boardId")
    material_class = (metadata or {}).get("materialClass") or (metadata or {}).get("material")
    return {
        "panelId": panel_id,
        "bodyName": str(getattr(body, "name", "") or ""),
        "boardType": board_type or None,
        "role": role or None,
        "sourceBoardId": source_board_id or None,
        "materialClass": material_class or None,
        "metadataWarnings": warnings,
    }


def is_panel_body(body) -> bool:
    if not body:
        return False
    try:
        if hasattr(body, "isSolid") and not body.isSolid:
            return False
        if hasattr(body, "isVisible") and not body.isVisible:
            return False
    except Exception:
        return False

    if _attr_value(body, PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR):
        return True
    if _attr_value(body, LEGACY_ATTRIBUTE_GROUP, "panelId"):
        return True
    if _attr_value(body, CABINETNC_ATTRIBUTE_GROUP, "panelId"):
        return True
    if _attr_value(body, LEGACY_ATTRIBUTE_GROUP, "boardId"):
        return True
    if _attr_value(body, CABINETNC_ATTRIBUTE_GROUP, "boardId"):
        return True
    if _attr_value(body, LEGACY_ATTRIBUTE_GROUP, "relationshipFixture"):
        return True
    component = _parent_component(body)
    if component and _attr_value(component, PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR):
        return True
    if component and _attr_value(component, PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR):
        return True
    if component and _attr_value(component, CABINETNC_ATTRIBUTE_GROUP, "boardId"):
        return True
    if component and _attr_value(component, CABINETNC_ATTRIBUTE_GROUP, "panelId"):
        return True
    return False


def design_bbox_from_body_metadata(body) -> Optional[BBoxMm]:
    component = _parent_component(body)
    for entity in (body, component):
        metadata, _ = _read_metadata_dict(entity)
        if not isinstance(metadata, dict):
            continue
        design = metadata.get("designGeometry")
        if not isinstance(design, dict):
            continue
        try:
            return BBoxMm(
                x0=float(design["x0"]),
                x1=float(design["x1"]),
                y0=float(design["y0"]),
                y1=float(design["y1"]),
                z0=float(design["z0"]),
                z1=float(design["z1"]),
            )
        except (KeyError, TypeError, ValueError):
            continue
    return None


def build_panel_snapshot(body, *, bbox_source: str = "physical") -> PanelSnapshot:
    meta = read_panel_metadata(body)
    physical_bbox = get_body_bbox_mm(body)
    bbox = physical_bbox
    if bbox_source in ("design", "design_preferred"):
        design_bbox = design_bbox_from_body_metadata(body)
        if design_bbox is not None:
            bbox = design_bbox
        elif bbox_source == "design":
            bbox = physical_bbox
    snapshot = PanelSnapshot(
        panelId=meta["panelId"],
        bodyName=meta["bodyName"],
        bbox=bbox,
        boardType=meta.get("boardType"),
        role=meta.get("role"),
        sourceBoardId=meta.get("sourceBoardId"),
        materialClass=meta.get("materialClass"),
        sizeX=bbox.size_x,
        sizeY=bbox.size_y,
        sizeZ=bbox.size_z,
        metadataWarnings=list(meta.get("metadataWarnings") or []),
    )
    return enrich_panel_snapshot(snapshot)


def build_panel_snapshot_from_dict(data: Dict[str, Any]) -> PanelSnapshot:
    bbox_data = data.get("bbox") or {}
    bbox = BBoxMm(
        x0=float(bbox_data.get("x0", 0.0)),
        x1=float(bbox_data.get("x1", 0.0)),
        y0=float(bbox_data.get("y0", 0.0)),
        y1=float(bbox_data.get("y1", 0.0)),
        z0=float(bbox_data.get("z0", 0.0)),
        z1=float(bbox_data.get("z1", 0.0)),
    )
    snapshot = PanelSnapshot(
        panelId=str(data.get("panelId") or "unknown"),
        bodyName=str(data.get("bodyName") or data.get("panelId") or "unknown"),
        bbox=bbox,
        boardType=data.get("boardType"),
        role=data.get("role"),
        sourceBoardId=data.get("sourceBoardId"),
        materialClass=data.get("materialClass"),
        sizeX=bbox.size_x,
        sizeY=bbox.size_y,
        sizeZ=bbox.size_z,
        metadataWarnings=list(data.get("metadataWarnings") or []),
    )
    return enrich_panel_snapshot(snapshot)


def _walk_component_bodies(component, sink: List[Any]):
    if not component:
        return
    if list_solid_bodies:
        for body in list_solid_bodies(component):
            sink.append(body)
    else:
        try:
            for index in range(component.bRepBodies.count):
                body = component.bRepBodies.item(index)
                if body and body.isSolid:
                    sink.append(body)
        except Exception:
            pass
    try:
        for index in range(component.occurrences.count):
            _walk_component_bodies(component.occurrences.item(index).component, sink)
    except Exception:
        pass


def collect_panel_bodies(root_component) -> List[Any]:
    bodies: List[Any] = []
    _walk_component_bodies(root_component, bodies)
    return [body for body in bodies if is_panel_body(body)]


def find_component_by_name(component, name: str):
    if not component or not name:
        return None
    try:
        if str(getattr(component, "name", "") or "") == name:
            return component
    except Exception:
        pass
    if _attr_value(component, LEGACY_ATTRIBUTE_GROUP, "assemblyName") == name:
        return component
    # Kitchen (and some adapters) store assemblyName under CabinetNC.
    if _attr_value(component, CABINETNC_ATTRIBUTE_GROUP, "assemblyName") == name:
        return component
    try:
        occurrences = component.occurrences
        count = occurrences.count if occurrences else 0
        for index in range(count):
            occurrence = occurrences.item(index)
            try:
                if str(getattr(occurrence, "name", "") or "") == name:
                    return occurrence.component
            except Exception:
                pass
            child = occurrence.component
            found = find_component_by_name(child, name)
            if found:
                return found
    except Exception:
        pass
    return None


def collect_panel_bodies_under_assembly(root_component, assembly_name: str) -> List[Any]:
    component = find_component_by_name(root_component, assembly_name)
    if not component:
        return []
    bodies: List[Any] = []
    _walk_component_bodies(component, bodies)
    return [body for body in bodies if is_panel_body(body)]


def dedupe_panel_snapshots(panels: Iterable[PanelSnapshot]) -> List[PanelSnapshot]:
    by_id: Dict[str, PanelSnapshot] = {}
    for panel in panels:
        panel_id = str(getattr(panel, "panelId", "") or "").strip()
        if panel_id:
            by_id[panel_id] = panel
    return list(by_id.values())


def read_relationship_declarations_from_component(component) -> List[Dict[str, Any]]:
    if not component:
        return []
    groups = (
        LEGACY_ATTRIBUTE_GROUP,
        CABINETNC_ATTRIBUTE_GROUP,
        PANEL_ATTRIBUTE_GROUP,
    )
    try:
        from geometry_ops import ATTRIBUTE_GROUP as GEOMETRY_OPS_GROUP

        groups = (GEOMETRY_OPS_GROUP,) + groups
    except Exception:
        pass
    raw = None
    for group in groups:
        raw = _attr_value(component, group, "relationshipDeclarations")
        if raw:
            break
    if not raw:
        return []
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def scan_relationships(
    panels: Iterable[PanelSnapshot],
    *,
    tolerance_mm: float = CONTACT_TOLERANCE_MM,
    include_none: bool = False,
):
    panel_list = list(panels)
    relationships = []
    for index_a in range(len(panel_list)):
        for index_b in range(index_a + 1, len(panel_list)):
            relationship = classify_pair(panel_list[index_a], panel_list[index_b], tolerance_mm=tolerance_mm)
            if include_none or relationship.geometryType != "none":
                relationships.append(relationship)
    return panel_list, relationships


def inspect_pair(
    panel_a: PanelSnapshot,
    panel_b: PanelSnapshot,
    *,
    tolerance_mm: float = CONTACT_TOLERANCE_MM,
):
    relationship = classify_pair(panel_a, panel_b, tolerance_mm=tolerance_mm)
    return build_inspect_pair_report(relationship=relationship, tolerance_mm=tolerance_mm)


class RelationshipService:
    def __init__(self, fusion_adapter=None):
        self.fusion = fusion_adapter

    def _root_component(self):
        if not self.fusion:
            return None
        getter = getattr(self.fusion, "get_root_component", None)
        if callable(getter):
            return getter()
        design = self.fusion.get_active_design() if hasattr(self.fusion, "get_active_design") else None
        return design.rootComponent if design else None

    def collect_panels_from_design(self, bodies: Optional[List[Any]] = None, *, bbox_source: str = "physical") -> List[PanelSnapshot]:
        if bodies is None:
            root = self._root_component()
            if not root:
                return []
            bodies = collect_panel_bodies(root)
        return dedupe_panel_snapshots([build_panel_snapshot(body, bbox_source=bbox_source) for body in bodies])

    def collect_panels_from_assembly(self, assembly_name: str, *, bbox_source: str = "physical") -> List[PanelSnapshot]:
        root = self._root_component()
        if not root or not assembly_name:
            return []
        bodies = collect_panel_bodies_under_assembly(root, assembly_name)
        return dedupe_panel_snapshots([build_panel_snapshot(body, bbox_source=bbox_source) for body in bodies])

    def scan(
        self,
        *,
        scope: str = "all",
        tolerance_mm: float = CONTACT_TOLERANCE_MM,
        include_none: bool = False,
        expected_fixtures: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        panels = self.collect_panels_from_design()
        panel_list, relationships = scan_relationships(
            panels,
            tolerance_mm=tolerance_mm,
            include_none=include_none,
        )
        return build_scan_report(
            action="relationships.scan",
            panels=panel_list,
            relationships=relationships,
            scope=scope,
            tolerance_mm=tolerance_mm,
            expected_fixtures=expected_fixtures,
        )

    def scan_selected(
        self,
        selected_bodies: List[Any],
        *,
        tolerance_mm: float = CONTACT_TOLERANCE_MM,
        include_none: bool = False,
    ) -> Dict[str, Any]:
        panel_bodies = [body for body in (selected_bodies or []) if is_panel_body(body)]
        if len(panel_bodies) < 2:
            return build_scan_report(
                action="relationships.scanSelected",
                panels=[build_panel_snapshot(body) for body in panel_bodies],
                relationships=[],
                scope="selected",
                tolerance_mm=tolerance_mm,
                errors=["Select at least 2 panel bodies for relationship scan."],
            )
        panels = [build_panel_snapshot(body) for body in panel_bodies]
        panel_list, relationships = scan_relationships(
            panels,
            tolerance_mm=tolerance_mm,
            include_none=include_none,
        )
        return build_scan_report(
            action="relationships.scanSelected",
            panels=panel_list,
            relationships=relationships,
            scope="selected",
            tolerance_mm=tolerance_mm,
        )

    def inspect_pair_by_id(
        self,
        panels: Iterable[PanelSnapshot],
        panel_a_id: str,
        panel_b_id: str,
        *,
        tolerance_mm: float = CONTACT_TOLERANCE_MM,
    ) -> Dict[str, Any]:
        panel_map = {panel.panelId: panel for panel in panels}
        panel_a = panel_map.get(panel_a_id)
        panel_b = panel_map.get(panel_b_id)
        if not panel_a or not panel_b:
            return {
                "ok": False,
                "action": "relationships.inspectPair",
                "errors": ["Could not find both panels by panelId: {} / {}".format(panel_a_id, panel_b_id)],
            }
        return inspect_pair(panel_a, panel_b, tolerance_mm=tolerance_mm)

    def inspect_pair_from_design(
        self,
        panel_a_id: str,
        panel_b_id: str,
        *,
        tolerance_mm: float = CONTACT_TOLERANCE_MM,
    ) -> Dict[str, Any]:
        panels = self.collect_panels_from_design()
        return self.inspect_pair_by_id(panels, panel_a_id, panel_b_id, tolerance_mm=tolerance_mm)
