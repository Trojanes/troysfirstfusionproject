"""Pure grouped row layout for Nesting Zone workpieces.

Each (boardTypeTag, colorTag) group occupies one Y row. Bodies within a row
extend in +X. The Fusion adapter supplies flattened bounding dimensions.
"""

from __future__ import annotations


DEFAULT_PART_GAP_MM = 50.0
DEFAULT_GROUP_GAP_MM = 300.0


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def group_key(item):
    return (
        str((item or {}).get("boardTypeTag") or "").strip().lower(),
        str((item or {}).get("colorTag") or "").strip().lower(),
    )


def grouped_row_layout(
    items,
    origin_x_mm,
    origin_y_mm,
    part_gap_mm=DEFAULT_PART_GAP_MM,
    group_gap_mm=DEFAULT_GROUP_GAP_MM,
):
    """Return deterministic placements and required XY size.

    Item fields: id, boardTypeTag, colorTag, widthMm, depthMm.
    Placement target is the flattened body's minimum XY corner.
    """
    part_gap = max(_num(part_gap_mm), 0.0)
    group_gap = max(_num(group_gap_mm), 0.0)
    origin_x = _num(origin_x_mm)
    origin_y = _num(origin_y_mm)

    grouped = {}
    for item in items or []:
        width = max(_num((item or {}).get("widthMm")), 0.0)
        depth = max(_num((item or {}).get("depthMm")), 0.0)
        if width <= 0.0 or depth <= 0.0:
            continue
        normalized = dict(item)
        normalized["widthMm"] = width
        normalized["depthMm"] = depth
        grouped.setdefault(group_key(normalized), []).append(normalized)

    placements = []
    groups = []
    cursor_y = origin_y
    max_x = origin_x

    for group_index, key in enumerate(sorted(grouped)):
        row_items = sorted(
            grouped[key],
            key=lambda item: str(
                item.get("panelId") or item.get("id") or item.get("bodyName") or ""
            ),
        )
        cursor_x = origin_x
        row_depth = max(item["depthMm"] for item in row_items)
        row_placements = []
        for item_index, item in enumerate(row_items):
            placement = {
                **item,
                "groupIndex": group_index,
                "itemIndex": item_index,
                "groupKey": {
                    "boardTypeTag": key[0],
                    "colorTag": key[1],
                },
                "targetX": cursor_x,
                "targetY": cursor_y,
                "targetZ": 0.0,
            }
            placements.append(placement)
            row_placements.append(placement)
            cursor_x += item["widthMm"] + part_gap
        row_end_x = cursor_x - part_gap if row_items else origin_x
        max_x = max(max_x, row_end_x)
        groups.append(
            {
                "groupIndex": group_index,
                "boardTypeTag": key[0],
                "colorTag": key[1],
                "originX": origin_x,
                "originY": cursor_y,
                "widthMm": max(row_end_x - origin_x, 0.0),
                "depthMm": row_depth,
                "count": len(row_items),
            }
        )
        cursor_y += row_depth + group_gap

    max_y = cursor_y - group_gap if groups else origin_y
    return {
        "placements": placements,
        "groups": groups,
        "requiredWidthMm": max(max_x - origin_x, 0.0),
        "requiredDepthMm": max(max_y - origin_y, 0.0),
        "partGapMm": part_gap,
        "groupGapMm": group_gap,
    }
