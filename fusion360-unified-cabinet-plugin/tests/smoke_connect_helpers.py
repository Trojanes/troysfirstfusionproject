"""Shared helpers for M3/M4 Connect pipeline smoke tests."""

from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_REPO_PLUGIN_DIR = r"d:\project\troysfirstfusionproject-main\fusion360-unified-cabinet-plugin"

HW_REL_DEBUG_RULE = {
    "type": "screw_hole",
    "diameterMm": 4,
    "edgeOffsetMm": 30,
    "minSpacingMm": 80,
    "depthMode": "host_thickness",
}
HW_REL_MANUAL_CONFIRMED = {
    "level": "manual_confirmed",
    "safeForPreview": True,
    "safeForCut": True,
    "requiresManualConfirmation": False,
}


def resolve_plugin_dir(script_file: str) -> str:
    script_dir = os.path.dirname(os.path.abspath(script_file))
    candidates = [
        script_dir,
        os.path.dirname(script_dir),
        os.environ.get("CABINETNC_PLUGIN_DIR") or "",
        DEFAULT_REPO_PLUGIN_DIR,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        if os.path.isfile(os.path.join(candidate, "UnifiedCabinetPlugin.py")):
            return candidate
    return os.path.dirname(os.path.dirname(script_dir))


def ensure_plugin_paths(plugin_dir: str) -> None:
    paths = [
        plugin_dir,
        os.path.join(plugin_dir, "fusion"),
        os.path.join(plugin_dir, "ui"),
        os.path.join(plugin_dir, "modules"),
        os.path.join(plugin_dir, "modules", "hardware"),
        os.path.join(plugin_dir, "modules", "relationships"),
        os.path.join(plugin_dir, "panel_attributes"),
        os.path.join(plugin_dir, "metadata"),
    ]
    for path in reversed(paths):
        if path in sys.path:
            sys.path.remove(path)
        sys.path.insert(0, path)


def purge_stale_plugin_modules() -> None:
    stale_prefixes = (
        "adapter",
        "modules.",
        "relationship_",
        "screw_hole_from_relationship",
        "relationship_screw_hole_fusion",
        "hardware_models",
        "geometry_ops",
        "face_attribute_store",
        "face_metadata_service",
        "face_models",
        "panel_metadata_types",
    )
    for key in list(sys.modules.keys()):
        if key == "adapter" or any(key.startswith(prefix) for prefix in stale_prefixes):
            del sys.modules[key]


def import_plugin_modules(plugin_dir: str):
    import importlib

    purge_stale_plugin_modules()
    ensure_plugin_paths(plugin_dir)

    adapter_mod = importlib.import_module("adapter")
    screw_mod = importlib.import_module("screw_hole_from_relationship")
    rel_ctrl_mod = importlib.import_module("modules.relationships.controller")
    hw_ctrl_mod = importlib.import_module("modules.hardware.controller")

    fusion = adapter_mod.FusionAdapter()
    rel_ctrl = rel_ctrl_mod.RelationshipsController(fusion)
    hw_ctrl = hw_ctrl_mod.HardwareController(plugin_dir, fusion)
    import_meta = {
        "pluginDir": plugin_dir,
        "hardwareControllerFile": getattr(hw_ctrl_mod, "__file__", ""),
        "hasPreviewRoute": hasattr(hw_ctrl, "preview_screw_holes_from_relationship"),
        "hasCutRoute": hasattr(hw_ctrl, "create_screw_holes_from_relationship"),
    }
    if not import_meta["hasCutRoute"]:
        raise RuntimeError(
            "Loaded HardwareController from {} lacks create_screw_holes_from_relationship. "
            "Reload CabinetNC add-in from repo: {}".format(
                import_meta["hardwareControllerFile"], plugin_dir
            )
        )
    return fusion, rel_ctrl, hw_ctrl, screw_mod, import_meta


def load_json_fixture(plugin_dir: str, *parts: str) -> Dict[str, Any]:
    path = os.path.join(plugin_dir, *parts)
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def panels_map(scan_payload: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {p["panelId"]: p for p in (scan_payload.get("panels") or []) if p.get("panelId")}


def relationship_panel_ids(rel: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    panel_a = (rel.get("panelA") or {}).get("panelId")
    panel_b = (rel.get("panelB") or {}).get("panelId")
    if panel_a and panel_b:
        return str(panel_a), str(panel_b)
    roles = rel.get("roles") or {}
    host_id = roles.get("hostPanelId")
    target_id = roles.get("targetPanelId")
    if host_id and target_id:
        return str(host_id), str(target_id)
    return None, None


def matches_panel_pair(rel: Dict[str, Any], panel_a_id: str, panel_b_id: str) -> bool:
    ids = set(filter(None, relationship_panel_ids(rel)))
    return ids == {panel_a_id, panel_b_id}


def is_previewable_edge_joint(rel: Dict[str, Any]) -> bool:
    if rel.get("geometryType") != "edge_to_surface":
        return False
    if rel.get("relationshipType") != "structural_butt_joint":
        return False
    roles = rel.get("roles") or {}
    return bool(roles.get("hostPanelId")) and bool(roles.get("targetPanelId"))


def find_preview_relationship(
    scan_payload: Dict[str, Any],
    preferred_pairs: Optional[List[Tuple[str, str]]] = None,
) -> Optional[Dict[str, Any]]:
    relationships = scan_payload.get("relationships") or []
    if preferred_pairs:
        for panel_a_id, panel_b_id in preferred_pairs:
            for rel in relationships:
                if not matches_panel_pair(rel, panel_a_id, panel_b_id):
                    continue
                if is_previewable_edge_joint(rel):
                    return rel
    for rel in relationships:
        if is_previewable_edge_joint(rel):
            return rel
    return None


def audit_row_for_relationship(scan_payload: Dict[str, Any], relationship_id: Optional[str]) -> Dict[str, Any]:
    if not relationship_id:
        return {}
    for row in scan_payload.get("audit") or []:
        if row.get("relationshipId") == relationship_id:
            return row
    return {}


def resolve_verification(rel: Dict[str, Any], scan_payload: Dict[str, Any]) -> Dict[str, Any]:
    raw = rel.get("verification") if isinstance(rel, dict) else None
    if isinstance(raw, dict) and raw.get("level"):
        return raw

    row = audit_row_for_relationship(scan_payload, rel.get("relationshipId"))
    if row.get("verificationLevel"):
        return {
            "level": row.get("verificationLevel"),
            "safeForPreview": bool(row.get("safeForPreview", True)),
            "safeForCut": bool(row.get("safeForCut", False)),
            "requiresManualConfirmation": bool(row.get("requiresManualConfirmation", True)),
        }

    return {
        "level": "bbox_candidate",
        "safeForPreview": True,
        "safeForCut": False,
        "requiresManualConfirmation": True,
    }


def confirm_for_cut(relationship: Dict[str, Any]) -> Dict[str, Any]:
    notes = list(relationship.get("auditNotes") or [])
    notes.append("Manual cut confirmation applied (debug session only).")
    return {**relationship, "verification": dict(HW_REL_MANUAL_CONFIRMED), "auditNotes": notes}


def build_cut_payload(confirmed: Dict[str, Any], scan_payload: Dict[str, Any]) -> Dict[str, Any]:
    panel_map = panels_map(scan_payload)
    host_id = (confirmed.get("roles") or {}).get("hostPanelId")
    target_id = (confirmed.get("roles") or {}).get("targetPanelId")
    payload = {"relationship": confirmed, "rule": HW_REL_DEBUG_RULE}
    if host_id and target_id and host_id in panel_map and target_id in panel_map:
        payload["panels"] = {host_id: panel_map[host_id], target_id: panel_map[target_id]}
    return payload


def cut_feature_exists(root, feature_name: Optional[str]) -> bool:
    if not root or not feature_name:
        return False

    def scan_component(comp) -> bool:
        for index in range(comp.features.count):
            try:
                if comp.features.item(index).name == feature_name:
                    return True
            except Exception:
                continue
        return False

    if scan_component(root):
        return True
    for index in range(root.allOccurrences.count):
        try:
            if scan_component(root.allOccurrences.item(index).component):
                return True
        except Exception:
            continue
    return False


def write_smoke_results(plugin_dir: str, script_file: str, filename: str, result: Dict[str, Any]) -> str:
    out_paths = []
    for out_dir in (
        os.path.join(plugin_dir, "tests", "output"),
        os.path.join(os.path.dirname(os.path.abspath(script_file)), "output"),
    ):
        try:
            out_dir = os.path.normpath(out_dir)
            os.makedirs(out_dir, exist_ok=True)
            out_path = os.path.join(out_dir, filename)
            with open(out_path, "w", encoding="utf-8") as handle:
                json.dump(result, handle, indent=2, ensure_ascii=False)
            out_paths.append(out_path)
        except Exception:
            continue
    return out_paths[0] if out_paths else "(write failed)"
