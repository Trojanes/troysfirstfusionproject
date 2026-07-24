"""Overhead generator-declared structural joints (M6 v1)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

GENERATOR_NAME = "overhead"

# Design-intent joints for standard OHC skeleton boards (edge_only fixture / typical run).
OVERHEAD_DECLARED_JOINTS: List[Dict[str, Any]] = [
    {
        "declarationId": "oh_bp_d0_back_to_divider",
        "generator": GENERATOR_NAME,
        "panelAId": "BP",
        "panelBId": "D0",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "BP",
        "targetPanelId": "D0",
        "ruleId": "overhead_back_divider_v1",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "oh_bp_fp0_back_to_front",
        "generator": GENERATOR_NAME,
        "panelAId": "BP",
        "panelBId": "FP0",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "BP",
        "targetPanelId": "FP0",
        "ruleId": "overhead_back_front_v1",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "oh_d0_fp0_divider_to_front",
        "generator": GENERATOR_NAME,
        "panelAId": "D0",
        "panelBId": "FP0",
        "relationshipType": "structural_butt_joint",
        "geometryType": "edge_to_surface",
        "hostPanelId": "D0",
        "targetPanelId": "FP0",
        "ruleId": "overhead_divider_front_v1",
        "allowedHardware": ["screw_hole"],
    },
    {
        "declarationId": "oh_t1_t2_top_rail_stack",
        "generator": GENERATOR_NAME,
        "panelAId": "T1",
        "panelBId": "T2",
        "relationshipType": "face_contact",
        "geometryType": "surface_to_surface",
        "hostPanelId": "T1",
        "targetPanelId": "T2",
        "ruleId": "overhead_top_rail_stack_v1",
        "allowedHardware": [],
    },
]


def extract_board_suffix(panel_id: str) -> str:
    """Return board token from bare ids (BP) or run-prefixed ids (ohc.run.BP)."""
    token = str(panel_id or "").strip()
    if not token:
        return ""
    if "." in token:
        return token.rsplit(".", 1)[-1]
    return token


def resolve_panel_id_for_board(
    panel_ids: Set[str],
    board_id: str,
    *,
    preferred_run_token: Optional[str] = None,
) -> Optional[str]:
    board_id = str(board_id or "").strip()
    if not board_id:
        return None
    if board_id in panel_ids:
        return board_id
    matches = sorted(pid for pid in panel_ids if extract_board_suffix(pid) == board_id)
    if not matches:
        return None
    if preferred_run_token:
        token = str(preferred_run_token).strip()
        preferred = [pid for pid in matches if f".{token}." in pid or pid.startswith(f"ohc.{token}.")]
        if preferred:
            return preferred[-1]
    return matches[-1]


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


def list_overhead_declarations_for_panel_ids(
    panel_ids: Set[str],
    *,
    preferred_run_token: Optional[str] = None,
    embedded_declarations: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    source = embedded_declarations if embedded_declarations is not None else OVERHEAD_DECLARED_JOINTS
    declarations: List[Dict[str, Any]] = []
    for item in source:
        resolved = _resolve_declaration_for_panels(item, panel_ids, preferred_run_token=preferred_run_token)
        if resolved:
            declarations.append(resolved)
    return declarations


def detect_overhead_generator(panel_ids: Set[str]) -> bool:
    """True when panel set looks like a standard overhead skeleton."""
    suffixes = {extract_board_suffix(panel_id) for panel_id in panel_ids}
    return {"BP", "FP0"}.issubset(suffixes)


def resolve_declarations_for_panels(
    panel_ids: Set[str],
    generator: Optional[str] = None,
    *,
    preferred_run_token: Optional[str] = None,
    embedded_declarations: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    if generator and generator != GENERATOR_NAME:
        return []
    if generator == GENERATOR_NAME or detect_overhead_generator(panel_ids):
        return list_overhead_declarations_for_panel_ids(
            panel_ids,
            preferred_run_token=preferred_run_token,
            embedded_declarations=embedded_declarations,
        )
    return []
