"""Lay Flat packing — board-type columns, machining face already +Z.

Fusion-free. Placement math only; body creation lives in ``lay_flat_fusion``.
"""

from __future__ import annotations


def _tag(value):
    text = str(value or "").strip()
    return text or "unknown"


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def group_items_by_board_type(items):
    """Stable groups: sorted boardTypeTag, items keep input order within group."""
    groups = {}
    order = []
    for item in items or []:
        board_type = _tag((item or {}).get("boardTypeTag"))
        if board_type not in groups:
            groups[board_type] = []
            order.append(board_type)
        groups[board_type].append(item)
    order.sort(key=lambda tag: tag.lower())
    return [(tag, groups[tag]) for tag in order]


def group_items_by_board_and_color(items):
    """Stable groups: sorted Board Type + Color; input order within each group."""
    groups = {}
    order = []
    for item in items or []:
        key = (
            _tag((item or {}).get("boardTypeTag")),
            _tag((item or {}).get("colorTag")),
        )
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)
    order.sort(key=lambda pair: (pair[0].lower(), pair[1].lower()))
    return [(key[0], key[1], groups[key]) for key in order]


def column_layout(
    items,
    origin_x_mm=0.0,
    origin_y_mm=0.0,
    part_gap_mm=50.0,
    column_gap_mm=200.0,
    group_by_color=False,
):
    """Pack items into columns by boardTypeTag and optionally colorTag.

    Within a column, parts stack in +Y. Columns advance in +X.
    Each item needs ``id``, ``widthMm``, ``depthMm`` (flat XY after orient).
    Returns ``{placements, groups, bounds}``.
    """
    gap = max(_num(part_gap_mm, 50.0), 0.0)
    col_gap = max(_num(column_gap_mm, 200.0), 0.0)
    ox = _num(origin_x_mm)
    oy = _num(origin_y_mm)

    placements = []
    groups_out = []
    cursor_x = ox
    max_x = ox
    max_y = oy

    grouped = (
        group_items_by_board_and_color(items)
        if group_by_color
        else [(tag, "", values) for tag, values in group_items_by_board_type(items)]
    )
    for group_index, (board_type, color, group_items) in enumerate(grouped):
        cursor_y = oy
        col_width = 0.0
        group_placements = []
        for item_index, item in enumerate(group_items):
            width = max(_num((item or {}).get("widthMm")), 1.0)
            depth = max(_num((item or {}).get("depthMm")), 1.0)
            placement = {
                "id": (item or {}).get("id"),
                "panelId": (item or {}).get("panelId") or "",
                "bodyName": (item or {}).get("bodyName") or "",
                "assemblyName": (item or {}).get("assemblyName") or "",
                "componentName": (item or {}).get("componentName") or "",
                "boardTypeTag": board_type,
                "colorTag": color if group_by_color else ((item or {}).get("colorTag") or ""),
                "groupIndex": group_index,
                "itemIndex": item_index,
                "targetX": cursor_x,
                "targetY": cursor_y,
                "rotationDeg": 0.0,
                "widthMm": width,
                "depthMm": depth,
            }
            placements.append(placement)
            group_placements.append(placement)
            col_width = max(col_width, width)
            cursor_y += depth + gap
            max_y = max(max_y, cursor_y - gap)
        groups_out.append(
            {
                "groupIndex": group_index,
                "boardTypeTag": board_type,
                "colorTag": color,
                "count": len(group_placements),
                "columnX": cursor_x,
                "columnWidthMm": col_width,
            }
        )
        cursor_x += col_width + col_gap
        max_x = max(max_x, cursor_x - col_gap)

    return {
        "engine": "lay_flat_columns",
        "placements": placements,
        "groups": groups_out,
        "bounds": {
            "x0": ox,
            "y0": oy,
            "x1": max_x,
            "y1": max_y,
        },
    }
