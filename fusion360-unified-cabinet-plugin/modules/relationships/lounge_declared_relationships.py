"""Lounge generator-declared structural joints (v1)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from overhead_declared_relationships import extract_board_suffix, resolve_panel_id_for_board

GENERATOR_NAME = "lounge"

# L_SHAPE front→top/side joints (lounge_l_shape fixture).
LOUNGE_DECLARED_JOINTS: List[Dict[str, Any]] = [
    {
        "declarationId": "lg_main_front_to_top",
        "generator": GENERATOR_NAME,
        "panelAId": "main_front",
        "panelBId": "main_top",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "main_front",
        "targetPanelId": "main_top",
        "ruleId": "lounge_main_front_top_v1",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "lg_l_front_to_side",
        "generator": GENERATOR_NAME,
        "panelAId": "l_front",
        "panelBId": "l_side",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "l_front",
        "targetPanelId": "l_side",
        "ruleId": "lounge_l_front_side_v1",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "lg_l_front_to_top",
        "generator": GENERATOR_NAME,
        "panelAId": "l_front",
        "panelBId": "l_top",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "l_front",
        "targetPanelId": "l_top",
        "ruleId": "lounge_l_front_top_v1",
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


def list_lounge_declarations_for_panel_ids(
    panel_ids: Set[str],
    *,
    preferred_run_token: Optional[str] = None,
    embedded_declarations: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    source = embedded_declarations if embedded_declarations is not None else LOUNGE_DECLARED_JOINTS
    declarations: List[Dict[str, Any]] = []
    for item in source:
        resolved = _resolve_declaration_for_panels(item, panel_ids, preferred_run_token=preferred_run_token)
        if resolved:
            declarations.append(resolved)
    return declarations


def detect_lounge_generator(panel_ids: Set[str]) -> bool:
    """True when panel set looks like Lounge L_SHAPE carcass."""
    suffixes = {extract_board_suffix(panel_id) for panel_id in panel_ids}
    return {"main_front", "main_top"}.issubset(suffixes) or {"l_front", "l_side"}.issubset(suffixes)


def resolve_declarations_for_panels(
    panel_ids: Set[str],
    generator: Optional[str] = None,
    *,
    preferred_run_token: Optional[str] = None,
    embedded_declarations: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if generator and generator != GENERATOR_NAME:
        return []
    if generator == GENERATOR_NAME or detect_lounge_generator(panel_ids):
        return list_lounge_declarations_for_panel_ids(
            panel_ids,
            preferred_run_token=preferred_run_token,
            embedded_declarations=embedded_declarations,
        )
    return []
