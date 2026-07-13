"""General Tall generator-declared structural joints (v1)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from overhead_declared_relationships import extract_board_suffix, resolve_panel_id_for_board

GENERATOR_NAME = "general_tall"

# Design-intent joints for style_1 GT skeleton (general_tall_base fixture).
# Host/target match bbox classify on golden geometry (rail host, deck target).
GENERAL_TALL_DECLARED_JOINTS: List[Dict[str, Any]] = [
    {
        "declarationId": "gt_b1_b3_bottom_rail_to_deck",
        "generator": GENERATOR_NAME,
        "panelAId": "B1",
        "panelBId": "B3",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "B1",
        "targetPanelId": "B3",
        "ruleId": "general_tall_bottom_rail_deck_v1",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "gt_t1_t3_top_rail_to_deck",
        "generator": GENERATOR_NAME,
        "panelAId": "T1",
        "panelBId": "T3",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "T1",
        "targetPanelId": "T3",
        "ruleId": "general_tall_top_rail_deck_v1",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "gt_b2_b3_mid_rail_to_deck",
        "generator": GENERATOR_NAME,
        "panelAId": "B2",
        "panelBId": "B3",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "B2",
        "targetPanelId": "B3",
        "ruleId": "general_tall_mid_rail_deck_v1",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "gt_t2_t3_mid_rail_to_deck",
        "generator": GENERATOR_NAME,
        "panelAId": "T2",
        "panelBId": "T3",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "T2",
        "targetPanelId": "T3",
        "ruleId": "general_tall_mid_top_rail_deck_v1",
        "allowedHardware": ["screw_hole"],
    },
]

# Fridge stack extras (SidePanel / V5). V5 mate follows SidePanel presence:
# SidePanel_L → V5↔V2; else → V5↔V1 (exterior none or right).
GENERAL_TALL_FRIDGE_DECLARED_JOINTS: List[Dict[str, Any]] = [
    {
        "declarationId": "gt_sidepanel_l_v1",
        "generator": GENERATOR_NAME,
        "panelAId": "SidePanel_L",
        "panelBId": "V1",
        "relationshipType": "face_contact",
        "geometryType": "surface_to_surface",
        "hostPanelId": "SidePanel_L",
        "targetPanelId": "V1",
        "ruleId": "general_tall_fridge_sidepanel_l_v1",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "gt_sidepanel_r_v2",
        "generator": GENERATOR_NAME,
        "panelAId": "SidePanel_R",
        "panelBId": "V2",
        "relationshipType": "face_contact",
        "geometryType": "surface_to_surface",
        "hostPanelId": "SidePanel_R",
        "targetPanelId": "V2",
        "ruleId": "general_tall_fridge_sidepanel_r_v2",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "gt_v5_v1",
        "generator": GENERATOR_NAME,
        "panelAId": "V5",
        "panelBId": "V1",
        "relationshipType": "face_contact",
        "geometryType": "surface_to_surface",
        "hostPanelId": "V5",
        "targetPanelId": "V1",
        "ruleId": "general_tall_fridge_v5_v1",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "gt_v5_v2",
        "generator": GENERATOR_NAME,
        "panelAId": "V5",
        "panelBId": "V2",
        "relationshipType": "face_contact",
        "geometryType": "surface_to_surface",
        "hostPanelId": "V5",
        "targetPanelId": "V2",
        "ruleId": "general_tall_fridge_v5_v2",
        "allowedHardware": ["screw_hole"],
    },
]


def _fridge_joint_allowed(item: Dict[str, Any], panel_ids: Set[str]) -> bool:
    """Drop the V5 mate that does not match exterior SidePanel encoding."""
    decl_id = str(item.get("declarationId") or "")
    suffixes = {extract_board_suffix(panel_id) for panel_id in panel_ids}
    if decl_id == "gt_v5_v1":
        # SidePanel_L → V5 mates V2 only
        return "V5" in suffixes and "V1" in suffixes and "SidePanel_L" not in suffixes
    if decl_id == "gt_v5_v2":
        return "V5" in suffixes and "V2" in suffixes and "SidePanel_L" in suffixes
    return True


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


def list_general_tall_declarations_for_panel_ids(
    panel_ids: Set[str],
    *,
    preferred_run_token: Optional[str] = None,
    embedded_declarations: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if embedded_declarations is not None:
        source = embedded_declarations
    else:
        source = GENERAL_TALL_DECLARED_JOINTS + GENERAL_TALL_FRIDGE_DECLARED_JOINTS
    declarations: List[Dict[str, Any]] = []
    for item in source:
        if embedded_declarations is None and not _fridge_joint_allowed(item, panel_ids):
            continue
        resolved = _resolve_declaration_for_panels(item, panel_ids, preferred_run_token=preferred_run_token)
        if resolved:
            declarations.append(resolved)
    return declarations


def detect_general_tall_generator(panel_ids: Set[str]) -> bool:
    """True when panel set looks like a standard General Tall skeleton."""
    suffixes = {extract_board_suffix(panel_id) for panel_id in panel_ids}
    return {"B1", "B3", "V1"}.issubset(suffixes)


def resolve_declarations_for_panels(
    panel_ids: Set[str],
    generator: Optional[str] = None,
    *,
    preferred_run_token: Optional[str] = None,
    embedded_declarations: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if generator and generator != GENERATOR_NAME:
        return []
    if generator == GENERATOR_NAME or detect_general_tall_generator(panel_ids):
        return list_general_tall_declarations_for_panel_ids(
            panel_ids,
            preferred_run_token=preferred_run_token,
            embedded_declarations=embedded_declarations,
        )
    return []
