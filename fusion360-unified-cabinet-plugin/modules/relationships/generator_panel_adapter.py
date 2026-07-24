"""Convert generator board/panel output into relationship PanelSnapshot payloads."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional


def _bbox_dict(x0: float, y0: float, z0: float, x1: float, y1: float, z1: float) -> Dict[str, float]:
    return {
        "x0": float(x0),
        "x1": float(x1),
        "y0": float(y0),
        "y1": float(y1),
        "z0": float(z0),
        "z1": float(z1),
    }


def snapshot_dict_from_bbox_board(board: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """General Tall / Overhead / Kitchen boards with x0..z1 fields."""
    try:
        bbox = _bbox_dict(
            board["x0"],
            board["y0"],
            board["z0"],
            board["x1"],
            board["y1"],
            board["z1"],
        )
    except (KeyError, TypeError, ValueError):
        return None
    panel_id = str(board.get("id") or board.get("panelId") or "")
    if not panel_id:
        return None
    return {
        "panelId": panel_id,
        "bodyName": str(board.get("name") or panel_id),
        "boardType": board.get("boardType") or board.get("type") or board.get("category"),
        "role": board.get("category"),
        "sourceBoardId": panel_id,
        "bbox": bbox,
    }


def snapshot_dict_from_lounge_panel(panel: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Lounge panels with explicit 3D placement boxes."""
    panel_id = str(panel.get("id") or "")
    placement = panel.get("placement") or {}
    required = ("x0", "x1", "y0", "y1", "z0", "z1")
    if not panel_id or not all(key in placement for key in required):
        return None
    return {
        "panelId": panel_id,
        "bodyName": panel_id,
        "boardType": panel.get("kind") or panel.get("type"),
        "role": panel.get("kind"),
        "sourceBoardId": panel_id,
        "bbox": _bbox_dict(
            placement["x0"],
            placement["y0"],
            placement["z0"],
            placement["x1"],
            placement["y1"],
            placement["z1"],
        ),
    }


def apply_overhead_physical_bbox_shifts(
    snapshots: List[Dict[str, Any]],
    *,
    feature_width_mm: float = 15.0,
) -> List[Dict[str, Any]]:
    """Mirror Fusion OH postprocess Z moves onto design-space snapshots.

    Overhead generator bakes divider z0 = 2*FGw, then Fusion shifts BP/T1/T2
    (+FGw via OH_SUPPORT_Z) and front panels (+FGw via OH_FP_Z). Offline declare
    / scan must use the same physical bboxes or BP↔D0 looks like a 15mm gap.
    """
    fg = float(feature_width_mm or 15.0)
    if fg == 0:
        return snapshots
    support_ids = {"BP", "T1", "T2"}
    shifted: List[Dict[str, Any]] = []
    for item in snapshots or []:
        if not isinstance(item, dict):
            continue
        row = dict(item)
        bbox = dict(row.get("bbox") or {})
        panel_id = str(row.get("panelId") or "")
        suffix = panel_id.rsplit(".", 1)[-1] if panel_id else ""
        role = str(row.get("role") or row.get("boardType") or "").lower()
        dz = 0.0
        if suffix in support_ids:
            dz = fg
        elif role == "front_panel" or suffix.startswith("FP"):
            dz = fg
        if dz:
            try:
                bbox["z0"] = float(bbox.get("z0") or 0.0) + dz
                bbox["z1"] = float(bbox.get("z1") or 0.0) + dz
            except Exception:
                pass
            row["bbox"] = bbox
            row["bboxSource"] = "overhead_physical_z"
        shifted.append(row)
    return shifted


def snapshots_from_generator_result(generator: str, result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extract normalized snapshot dicts from a generator bridge result."""
    snapshots: List[Dict[str, Any]] = []
    generator_key = str(generator or "").strip().lower()

    if generator_key == "lounge":
        for panel in result.get("panels") or []:
            payload = snapshot_dict_from_lounge_panel(panel)
            if payload:
                snapshots.append(payload)
        return snapshots

    for board in result.get("boards") or []:
        payload = snapshot_dict_from_bbox_board(board)
        if payload:
            snapshots.append(payload)

    if generator_key == "overhead":
        params = result.get("params") if isinstance(result.get("params"), dict) else {}
        fg = params.get("featureWidth")
        if fg is None:
            fg = 15.0
        snapshots = apply_overhead_physical_bbox_shifts(
            snapshots, feature_width_mm=float(fg or 15.0)
        )
    return snapshots
