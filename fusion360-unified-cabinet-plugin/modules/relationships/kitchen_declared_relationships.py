"""Kitchen generator-declared structural joints (v1)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from overhead_declared_relationships import extract_board_suffix, resolve_panel_id_for_board

GENERATOR_NAME = "kitchen"

# Bottom rail→deck joints for style_1 kitchen skeleton (kitchen_base fixture).
# Top strip→deck is not declared: T2/T3 classify as intersection on current geometry.
KITCHEN_DECLARED_JOINTS: List[Dict[str, Any]] = [
    {
        "declarationId": "kt_b1_b3_bottom_rail_to_deck",
        "generator": GENERATOR_NAME,
        "panelAId": "B1",
        "panelBId": "B3",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "B1",
        "targetPanelId": "B3",
        "ruleId": "kitchen_bottom_rail_deck_v1",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "kt_b2_b3_carcass_rail_to_deck",
        "generator": GENERATOR_NAME,
        "panelAId": "B2",
        "panelBId": "B3",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "B2",
        "targetPanelId": "B3",
        "ruleId": "kitchen_carcass_rail_deck_v1",
        "allowedHardware": ["screw_hole"],
    },
]


def _resolve_declaration_for_panels(
    item: Dict[str, Any],
    panel_ids: Set[str],
    *,
    preferred_run_token: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    panel_a = resolve_panel_id_for_board(panel_ids, str(item.get("panelAId") or ""), preferred_run_token=preferred_run_token)
    panel_b = resolve_panel_id_for_board(panel_ids, str(item.get("panelBId") or ""), preferred_run_token=preferred_run_token)
    if not panel_a or not panel_b:
        return None
    host_id = (
        resolve_panel_id_for_board(panel_ids, str(item.get("hostPanelId") or ""), preferred_run_token=preferred_run_token)
        or panel_a
    )
    target_id = (
        resolve_panel_id_for_board(panel_ids, str(item.get("targetPanelId") or ""), preferred_run_token=preferred_run_token)
        or panel_b
    )
    resolved = dict(item)
    resolved["boardPanelAId"] = item.get("panelAId")
    resolved["boardPanelBId"] = item.get("panelBId")
    resolved["boardHostPanelId"] = item.get("hostPanelId")
    resolved["boardTargetPanelId"] = item.get("targetPanelId")
    resolved["panelAId"] = panel_a
    resolved["panelBId"] = panel_b
    resolved["hostPanelId"] = host_id
    resolved["targetPanelId"] = target_id
    return resolved


def list_kitchen_declarations_for_panel_ids(
    panel_ids: Set[str],
    *,
    preferred_run_token: Optional[str] = None,
    embedded_declarations: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    source = embedded_declarations if embedded_declarations is not None else KITCHEN_DECLARED_JOINTS
    declarations: List[Dict[str, Any]] = []
    for item in source:
        resolved = _resolve_declaration_for_panels(item, panel_ids, preferred_run_token=preferred_run_token)
        if resolved:
            declarations.append(resolved)
    return declarations


def detect_kitchen_generator(panel_ids: Set[str]) -> bool:
    """True for Kitchen skeleton panels (distinct from GT which includes V1)."""
    suffixes = {extract_board_suffix(panel_id) for panel_id in panel_ids}
    if not {"B1", "B3"}.issubset(suffixes):
        return False
    if "V1" in suffixes:
        return False
    if "T1-1" in suffixes or any("k-zone" in str(panel_id) for panel_id in panel_ids):
        return True
    return "B2" in suffixes and "T1" not in suffixes


def resolve_declarations_for_panels(
    panel_ids: Set[str],
    generator: Optional[str] = None,
    *,
    preferred_run_token: Optional[str] = None,
    embedded_declarations: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if generator and generator != GENERATOR_NAME:
        return []
    if generator == GENERATOR_NAME or detect_kitchen_generator(panel_ids):
        return list_kitchen_declarations_for_panel_ids(
            panel_ids,
            preferred_run_token=preferred_run_token,
            embedded_declarations=embedded_declarations,
        )
    return []
