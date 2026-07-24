"""ContactPatch overlay — pure logic (offline-testable)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from contact_patch import build_contact_patch_label_text

OPERATION_TYPE = "CONTACT_PATCH_OVERLAY"
ARTIFACT_ATTR_GROUP = "UnifiedCabinetPlugin"
ARTIFACT_ATTR_OPERATION = "operationType"
ARTIFACT_ATTR_DEMO = "demoArtifact"
ARTIFACT_ATTR_RELATIONSHIP_ID = "sourceRelationshipId"
ARTIFACT_ATTR_CONTACT_PATCH_ID = "contactPatchId"
ARTIFACT_ATTR_OVERLAY_ROLE = "overlayRole"

PATCH_SKETCH_PREFIX = "CP_OVERLAY_"
PATCH_PLANE_PREFIX = "CP_OVERLAY_PLANE_"
PATCH_CUSTOM_GRAPHICS_PREFIX = "CP_OVERLAY_CG_"


def build_contact_patch_metadata(contact_patch: Dict[str, Any]) -> Dict[str, Any]:
    verification = contact_patch.get("verification") or {}
    return {
        "operationType": OPERATION_TYPE,
        "demoArtifact": True,
        "sourceRelationshipId": str(contact_patch.get("sourceRelationshipId") or ""),
        "contactPatchId": str(contact_patch.get("contactPatchId") or ""),
        "contactType": contact_patch.get("contactType"),
        "contactAxis": contact_patch.get("contactAxis"),
        "contactAreaMm2": contact_patch.get("contactAreaMm2"),
        "verificationLevel": verification.get("level"),
        "safeForCut": bool(verification.get("safeForCut")),
    }


def overlay_metadata_json(metadata: Dict[str, Any]) -> str:
    return json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def is_patch_sketch_name(name: str) -> bool:
    return str(name or "").startswith(PATCH_SKETCH_PREFIX)


def is_patch_plane_name(name: str) -> bool:
    return str(name or "").startswith(PATCH_PLANE_PREFIX)


def is_patch_custom_graphics_name(name: str) -> bool:
    return str(name or "").startswith(PATCH_CUSTOM_GRAPHICS_PREFIX)


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


def is_contact_patch_artifact_entity(entity) -> bool:
    if entity is None:
        return False
    name = str(getattr(entity, "name", "") or "")
    if is_patch_sketch_name(name) or is_patch_plane_name(name) or is_patch_custom_graphics_name(name):
        return True
    operation = _read_attr(entity, ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_OPERATION)
    demo = _read_attr(entity, ARTIFACT_ATTR_GROUP, ARTIFACT_ATTR_DEMO)
    return operation == OPERATION_TYPE and demo in ("true", "True", "1")


def list_contact_patch_cleanup_targets(sketches, construction_planes, custom_graphics_groups=None) -> Dict[str, List[str]]:
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
        if is_contact_patch_artifact_entity(sketch):
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
        if is_contact_patch_artifact_entity(plane):
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
        if is_contact_patch_artifact_entity(group):
            graphics_names.append(str(group.name))

    return {
        "sketches": sorted(sketch_names),
        "planes": sorted(plane_names),
        "customGraphics": sorted(graphics_names),
    }


def build_contact_patch_overlay_report(
    contact_patch: Dict[str, Any],
    relationship: Dict[str, Any],
    *,
    ok: bool,
    source: str = "selected",
    created: Optional[Dict[str, Any]] = None,
    errors: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "ok": bool(ok),
        "action": "relationships.showContactPatchOverlayForSelected",
        "operationType": OPERATION_TYPE,
        "source": source,
        "contactPatchId": contact_patch.get("contactPatchId"),
        "sourceRelationshipId": contact_patch.get("sourceRelationshipId"),
        "relationshipId": relationship.get("relationshipId"),
        "relationshipType": relationship.get("relationshipType"),
        "geometryType": relationship.get("geometryType"),
        "contactPatch": contact_patch,
        "labelText": build_contact_patch_label_text(contact_patch, relationship),
        "metadata": build_contact_patch_metadata(contact_patch),
        "created": created or {},
        "errors": list(errors or []),
        "warnings": list(warnings or []),
    }
