"""Generator default panel attributes for all formal cabinet modules.

Produces UnifiedCabinet.Panel metadata written at Fusion body creation time.

classification.boardType is the nesting family only: carcass | partition | door.
identity.boardType keeps the detailed semantic board kind.

Milling defaults (OH / GT / Kitchen / Lounge) use design-world direction buckets
(+X/-X/+Y/-Y/+Z/-Z): the outward normal of the milling (cutting) face.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple


PANEL_ATTRIBUTE_GROUP = "UnifiedCabinet.Panel"
PANEL_METADATA_ATTR = "metadata"
PANEL_ID_ATTR = "panelId"

DEFAULT_CARCASS_COLOR_TAG = "white_stipple"
DEFAULT_CARCASS_COLOR_NAME = "White Stipple"
CARCASS_SURFACE_MODE = "DOUBLE_SIDED"

_MATERIAL_FOR_CLASS = {
    "carcass": "carcass_board",
    "partition": "partition_board",
    "door": "door_board",
}

_OPPOSITE_DIRECTION = {
    "+X": "-X",
    "-X": "+X",
    "+Y": "-Y",
    "-Y": "+Y",
    "+Z": "-Z",
    "-Z": "+Z",
}


def _sanitize_token(value, fallback="board", limit=60):
    token = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(value or fallback)).strip("_")
    return (token or fallback)[:limit]


def _pack(board_type, panel_class, role, category, tags, door_color_slot=None):
    payload = {
        "boardType": board_type,
        "panelClass": panel_class,
        "role": role,
        "category": category,
        "materialClass": _MATERIAL_FOR_CLASS.get(panel_class, "carcass_board"),
        "tags": list(tags or []),
    }
    if door_color_slot is not None:
        payload["doorColorSlot"] = door_color_slot
    return payload


def _oh_divider_board_type(board_id, all_boards):
    divider_ids = []
    for board in all_boards or []:
        candidate_id = str(board.get("id") or "")
        if candidate_id.startswith("D") and candidate_id[1:].isdigit():
            divider_ids.append((int(candidate_id[1:]), candidate_id))
    if not divider_ids:
        return "internal_vertical_divider"
    divider_ids.sort()
    first_id = divider_ids[0][1]
    last_id = divider_ids[-1][1]
    if board_id == first_id:
        return "left_side_panel"
    if board_id == last_id:
        return "right_side_panel"
    return "internal_vertical_divider"


def overhead_board_semantics(board, all_boards=None):
    board_id = str(board.get("id") or "")
    source_type = str(board.get("boardType") or "")
    if board_id == "BP":
        return _pack("bottom_panel", "carcass", "carcass", "structural", ["overhead", "bottom", "carcass"])
    if board_id == "T1":
        return _pack(
            "top_front_door_fascia",
            "door",
            "front_visible",
            "front",
            ["overhead", "front", "door-color", "top-fascia"],
            door_color_slot=1,
        )
    if board_id == "T2":
        return _pack("top_front_inner_rail", "carcass", "carcass_rail", "structural", ["overhead", "top", "rail", "carcass"])
    if board_id == "T3":
        return _pack("top_rear_panel", "carcass", "carcass", "structural", ["overhead", "top", "rear", "carcass"])
    if board_id == "T4":
        return _pack("top_front_panel", "carcass", "carcass", "structural", ["overhead", "top", "front", "carcass"])
    if board_id == "RGHD_TOP":
        return _pack("rangehood_top", "carcass", "carcass", "rangehood", ["overhead", "rangehood", "top", "carcass"])
    if board_id == "RGHD_FRONT":
        return _pack("rangehood_front", "carcass", "carcass", "rangehood", ["overhead", "rangehood", "front", "carcass"])
    if board_id == "RGHD_BACK":
        return _pack("rangehood_back", "carcass", "carcass", "rangehood", ["overhead", "rangehood", "back", "carcass"])
    if board_id == "U_CONNECTOR" or source_type == "u_back_connector_panel":
        return _pack(
            "u_back_connector_panel",
            "carcass",
            "connector",
            "structural",
            ["overhead", "u-shape", "connector", "carcass"],
        )
    if board_id.startswith("D"):
        canonical = _oh_divider_board_type(board_id, all_boards)
        role = "side_panel" if canonical in ("left_side_panel", "right_side_panel") else "divider"
        return _pack(canonical, "carcass", role, "divider", ["overhead", "divider", "carcass", canonical])
    if board_id.startswith("FP"):
        if source_type in ("up_flap", "rangehood_flap"):
            tags = ["overhead", "front", "door", "up-flap"]
            if source_type == "rangehood_flap":
                tags.append("rangehood")
            return _pack(
                "rangehood_flap_door_panel" if source_type == "rangehood_flap" else "up_flap_door_panel",
                "door",
                "door",
                "front",
                tags,
                door_color_slot=1,
            )
        if source_type in ("fixed_panel", "u_clearance_fixed_panel"):
            return _pack(
                "u_clearance_fixed_front_panel" if source_type == "u_clearance_fixed_panel" else "fixed_front_panel",
                "door",
                "front_visible",
                "front",
                ["overhead", "front", "fixed-panel", "door-color"] + (["u-shape", "clearance"] if source_type == "u_clearance_fixed_panel" else []),
                door_color_slot=1,
            )
        return _pack(
            "front_panel",
            "door",
            "front_visible",
            "front",
            ["overhead", "front", source_type or "front-panel"],
            door_color_slot=1,
        )
    return _pack(source_type or "unknown_board", "carcass", "unknown", str(board.get("category") or "unknown"), ["overhead", "unknown"])


def _direction_pair(milling_direction):
    milling = str(milling_direction or "").strip().upper()
    if milling not in _OPPOSITE_DIRECTION:
        return {
            "millingDirection": "",
            "colourDirection": "",
            "cuttingFace": "EITHER",
        }
    return {
        "millingDirection": milling,
        "colourDirection": _OPPOSITE_DIRECTION[milling],
        "cuttingFace": "MILLING",
    }


def _overhead_local_milling_direction(board, features=None):
    """Return OH milling / cutting face as a design-world ±axis bucket.

    Frame (generator / Fusion assembly before optional board moves):
      +X width right, +Y depth into cabinet, +Z up, cabinet front ≈ -Y.

    ``millingDirection`` is the outward normal of the cutting face (铣削/切割面).
    Evidence:
      BP  — divider grooves cut from top face (z1) into -Z → +Z
      T3  — LED groove opens on top face → +Z
      FP* / door / flap / T1 — cutting face is +Y (back / into cabinet);
                              colour / visible front is -Y
      Rangehood boundary D — follow its one-sided inner-face groove (+X / -X)
      RGHD_TOP — +Z only when it carries an internal-D top groove
      T2/T4/remaining D* — no stable one-sided machining in design pose → EITHER
                 (T4 is later rotated 90° about X; leave to face init / Analyze)
    """
    board_id = str(board.get("id") or "")
    board_type = str(board.get("boardType") or "").lower()
    if board_id in ("BP", "T3"):
        return _direction_pair("+Z")
    if board_id == "RGHD_TOP":
        has_top_groove = any(
            isinstance(feature, dict)
            and str(feature.get("type") or "") == "rangehood_top_divider_groove"
            and str(feature.get("targetBoardId") or "") == board_id
            for feature in (features or [])
        )
        return _direction_pair("+Z" if has_top_groove else "")
    # FP panels and door/flap fronts: default cutting face = +Y.
    if (
        board_id == "T1"
        or board_id.startswith("FP")
        or board_type in ("up_flap", "rangehood_flap", "door", "flap", "left_door", "right_door")
    ):
        return _direction_pair("+Y")
    if board_id.startswith("D") and (len(board_id) == 1 or board_id[1:].isdigit()):
        groove_faces = {
            str(feature.get("face") or "").upper()
            for feature in (features or [])
            if isinstance(feature, dict)
            and str(feature.get("type") or "") == "rangehood_divider_side_groove"
            and str(feature.get("targetBoardId") or "") == board_id
        }
        if groove_faces == {"+X"}:
            return _direction_pair("+X")
        if groove_faces == {"-X"}:
            return _direction_pair("-X")
        return _direction_pair("")
    return _direction_pair("")


def _rotate_direction_about_z(direction, degrees):
    direction = str(direction or "")
    steps = int(round(float(degrees or 0) / 90.0)) % 4
    cycle = ["+X", "+Y", "-X", "-Y"]
    if direction not in cycle:
        return direction
    return cycle[(cycle.index(direction) + steps) % 4]


def overhead_milling_direction(board, features=None):
    """Return world milling direction, rotating U-OHC run-local defaults."""
    local = _overhead_local_milling_direction(board, features=features)
    degrees = board.get("worldRotationDeg") if isinstance(board, dict) else 0
    if not degrees or not local.get("millingDirection"):
        return local
    world_direction = _rotate_direction_about_z(local["millingDirection"], degrees)
    return _direction_pair(world_direction)


def _is_gt_zi_board(board):
    board_id = str(board.get("id") or "")
    board_type = str(board.get("boardType") or "").lower()
    category = str(board.get("category") or "").lower()
    if category == "boundary_panel":
        return True
    if board_type in ("full_zi", "half_zi", "shortened_zi"):
        return True
    return board_id.startswith("Zi") and len(board_id) > 2 and board_id[2:].isdigit()


def _gt_zi_groove_faces(board, features=None):
    """Return {'top','bottom'} faces that have a vertical-divider zi_groove on this Zi."""
    board_id = str(board.get("id") or "")
    faces = set()
    for feature in features or []:
        if not isinstance(feature, dict):
            continue
        if str(feature.get("type") or "") != "zi_groove":
            continue
        if str(feature.get("targetBoardId") or "") != board_id:
            continue
        # Grooves are only meaningful when a vertical divider is present.
        if not feature.get("dividerBoardId"):
            continue
        face = str(feature.get("face") or "").strip().lower()
        if face in ("top", "bottom"):
            faces.add(face)
    return faces


def general_tall_milling_direction(board, features=None):
    """Return GT milling / cutting face as a design-world ±axis bucket.

    Frame matches Overhead:
      +X width right, +Y depth into cabinet, +Z up, cabinet front ≈ -Y.

    ``millingDirection`` is the outward normal of the cutting face (铣削/切割面).
    Evidence:
      T1/B1 — door-colour fascias; cutting face +Y (back / into cabinet)
      Front panels / style2 fixed fronts — hinge cups from y1 → +Y
      T3 — LED groove on top face → +Z
      B3 — LED groove on bottom face (opens downward) → -Z
      Zi* — default +Z; if a vertical divider groove exists, follow that face
            (top → +Z, bottom → -Z, both → EITHER)
      Remaining carcass (T2/B2/V*/VD/SidePanel/H*/shelves/…) → EITHER
    """
    board_id = str(board.get("id") or "")
    board_type = str(board.get("boardType") or "").lower()
    category = str(board.get("category") or "").lower()

    if board_id == "T3":
        return _direction_pair("+Z")
    if board_id == "B3":
        return _direction_pair("-Z")
    if board_id in ("T1", "B1"):
        return _direction_pair("+Y")
    if (
        board_id.startswith("FP")
        or category in ("front_panel", "front")
        or board_type in (
            "cabinet_door",
            "style2_fixed_front_panel",
            "left_door",
            "right_door",
            "up_flap",
            "down_flap",
            "drawer",
        )
        or "FixedFrontPanel" in board_id
    ):
        return _direction_pair("+Y")
    if _is_gt_zi_board(board):
        faces = _gt_zi_groove_faces(board, features)
        if faces == {"top", "bottom"}:
            return _direction_pair("")
        if faces == {"bottom"}:
            return _direction_pair("-Z")
        # Default +Z, and top-only VD groove also +Z.
        return _direction_pair("+Z")
    return _direction_pair("")


def _kitchen_v_index(board, v_panels=None):
    board_id = str(board.get("id") or board.get("panelId") or "")
    for panel in list(v_panels or []):
        if not isinstance(panel, dict):
            continue
        if str(panel.get("id") or "") == board_id:
            try:
                return int(panel.get("index"))
            except Exception:
                break
    match = re.fullmatch(r"V(\d+)", board_id, flags=re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None


def _kitchen_half_slot_sides(board, features=None):
    """Collect half-groove open sides for a Kitchen panel: left | right.

    For YZ V panels: left → −X face, right → +X face (see assembly_cut_face).
    """
    sides = set()
    board_id = str(board.get("id") or board.get("panelId") or "")

    def _add(side):
        token = str(side or "").strip().lower()
        if token in ("left", "right"):
            sides.add(token)

    def _is_half(cut):
        if not isinstance(cut, dict):
            return False
        kind = str(cut.get("kind") or "").strip().lower()
        slot_type = str(cut.get("slotType") or cut.get("resolvedSlotType") or "").strip().lower()
        return kind == "slot" and slot_type == "half"

    for cut in list(board.get("halfGrooveVectors") or []) + list(board.get("cutouts") or []):
        if _is_half(cut):
            _add(cut.get("side"))

    body = board.get("body") if isinstance(board.get("body"), dict) else {}
    for cut in list(body.get("cutouts") or []):
        if _is_half(cut):
            _add(cut.get("side"))

    for feature in list(features or []):
        if not isinstance(feature, dict):
            continue
        if not _is_half(feature):
            continue
        target = str(feature.get("targetBoardId") or feature.get("boardId") or feature.get("vPanelId") or "")
        if target and target != board_id:
            continue
        _add(feature.get("side"))

    return sides


def kitchen_milling_direction(board, *, v_panels=None, features=None):
    """Return Kitchen milling / cutting face as a design-world ±axis bucket.

    Frame matches Overhead / General Tall:
      +X width right, +Y depth into cabinet, +Z up, cabinet front ≈ −Y.

    ``millingDirection`` is the outward normal of the cutting face (铣削/切割面).
    Evidence:
      B1 / frontPanels / stove_side_panel — door boards; cutting face +Y
            (back / into cabinet), colour −Y (front / outward)
      B3 — Style 1 LED T-groove opens on bottom face → −Z
      Outer door-side V — colour on outer face; milling on inner face
            (V0 → +X, right outer → −X)
      Carcass V with one-sided half grooves — follow open face
            (left → −X, right → +X, both/through/none → EITHER)
      Kitchen T1 = carcass support strip (not OH door rail) → EITHER
      B2/T2/T3/B4/shelves/dividers/avoidance → EITHER
    """
    board_id = str(board.get("id") or board.get("panelId") or "")
    board_type = str(
        board.get("type") or board.get("panelType") or board.get("boardType") or ""
    ).strip().lower()
    kind = str(board.get("kind") or board.get("panelKind") or "").strip().lower()

    if board_id == "B1" or board_type == "b1":
        return _direction_pair("+Y")
    if kind == "frontpanel" or board_type in (
        "left_door",
        "right_door",
        "drawer",
        "down_flap",
        "front_panel",
        "stove_side_panel",
    ):
        # Stove left/right fronts are door boards: colour out (−Y), milling in (+Y).
        return _direction_pair("+Y")
    if board_id == "B3" or board_type == "b3":
        return _direction_pair("-Z")

    is_v = (
        kind == "vpanel"
        or board_type == "vpanel"
        or bool(re.fullmatch(r"V\d+", board_id, flags=re.IGNORECASE))
    )
    if is_v:
        options = board.get("sidePanelOptions") if isinstance(board.get("sidePanelOptions"), dict) else {}
        if not options and v_panels:
            for panel in v_panels:
                if isinstance(panel, dict) and str(panel.get("id") or "") == board_id:
                    options = panel.get("sidePanelOptions") if isinstance(panel.get("sidePanelOptions"), dict) else {}
                    break
        panel_type = str(options.get("panelType") or "carcass").strip().lower()
        index = _kitchen_v_index(board, v_panels)
        # Outer door-side V: colour on outer face; milling on inner face.
        if panel_type == "door" and index is not None:
            if index == 0:
                return _direction_pair("+X")
            return _direction_pair("-X")

        sides = _kitchen_half_slot_sides(board, features=features)
        if sides == {"left"}:
            return _direction_pair("-X")
        if sides == {"right"}:
            return _direction_pair("+X")
        return _direction_pair("")

    return _direction_pair("")


def general_tall_board_semantics(board):
    board_id = str(board.get("id") or "")
    source_type = str(board.get("boardType") or board_id)
    category = str(board.get("category") or "")

    if board_id in ("T1", "B1"):
        return _pack(
            "top_front_door_fascia" if board_id == "T1" else "bottom_front_door_fascia",
            "door",
            "front_visible",
            "front",
            ["generalTall", "front", "door-color", board_id],
            door_color_slot=1,
        )
    if board_id in ("T2", "B2"):
        return _pack(
            "top_front_inner_rail" if board_id == "T2" else "bottom_front_inner_rail",
            "carcass",
            "carcass_rail",
            "structural",
            ["generalTall", "rail", "carcass", board_id],
        )
    if board_id in ("T3", "B3"):
        return _pack(
            "top_inserted_board" if board_id == "T3" else "bottom_inserted_board",
            "carcass",
            "carcass",
            "structural",
            ["generalTall", "inserted", "carcass", board_id],
        )
    if board_id.startswith("V") and board_id[1:].isdigit():
        return _pack("vertical_stile", "carcass", "carcass", "structural", ["generalTall", "vertical", "carcass", board_id])
    if source_type in ("full_zi", "half_zi", "shortened_zi") or category == "boundary_panel":
        return _pack(source_type or "boundary_panel", "carcass", "carcass", "structural", ["generalTall", "zi", "carcass", board_id])
    if category == "h_support" or board_id.startswith("H") or board_id == "T5":
        return _pack(source_type or "h_support", "carcass", "carcass", "structural", ["generalTall", "h_support", "carcass", board_id])
    if board_id in ("TH1", "BH1"):
        return _pack(
            "top_style2_system_panel" if board_id == "TH1" else "bottom_style2_system_panel",
            "carcass",
            "carcass",
            "structural",
            ["generalTall", "style2", "carcass", board_id],
        )
    if source_type == "style2_fixed_front_panel" or "FixedFrontPanel" in board_id:
        return _pack(
            "fixed_front_panel",
            "door",
            "front_visible",
            "front",
            ["generalTall", "front", "fixed-panel", "door-color", board_id],
            door_color_slot=1,
        )
    if board_id.startswith("FP") or category in ("front_panel", "front"):
        return _pack(
            "cabinet_door",
            "door",
            "door",
            "front",
            ["generalTall", "front", "door", board_id],
            door_color_slot=1,
        )
    if category in ("shelf", "shelves", "door_shelf") or "shelf" in board_id.lower():
        return _pack("door_shelf" if "shelf" in source_type or "shelf" in board_id.lower() else "shelf", "carcass", "carcass", "structural", ["generalTall", "shelf", "carcass", board_id])
    if "side_panel" in source_type or "SidePanel" in board_id:
        side = "left_side_panel" if "L" in board_id else "right_side_panel" if "R" in board_id else "side_panel"
        return _pack(side, "carcass", "carcass", "structural", ["generalTall", "side", "carcass", board_id])
    if "divider" in source_type.lower() or board_id.startswith("VD_"):
        return _pack("vertical_divider", "carcass", "divider", "divider", ["generalTall", "divider", "carcass", board_id])
    if category == "avoidance_support" or "avoidance" in board_id.lower():
        return _pack(source_type or "wheel_avoidance", "carcass", "carcass", "structural", ["generalTall", "avoidance", "carcass", board_id])
    return _pack(source_type or "unknown_board", "carcass", "carcass", category or "structural", ["generalTall", "carcass", board_id or "board"])


def _kitchen_base_type(entry):
    panel_type = str(entry.get("type") or entry.get("panelType") or "")
    board_id = str(entry.get("id") or entry.get("panelId") or "")
    kind = str(entry.get("kind") or entry.get("panelKind") or "")
    if panel_type:
        return panel_type
    if board_id.startswith("T1"):
        return "T1"
    if board_id.startswith("T2"):
        return "T2"
    if board_id.startswith("T3"):
        return "T3"
    if board_id.startswith("B4"):
        return "B4"
    if board_id in ("B1", "B2", "B3"):
        return board_id
    if kind:
        return kind
    return board_id


def kitchen_board_semantics(entry, v_panels=None):
    board_id = str(entry.get("id") or entry.get("panelId") or "")
    kind = str(entry.get("kind") or entry.get("panelKind") or "")
    panel_type = _kitchen_base_type(entry)

    if kind == "frontPanel" or panel_type in ("left_door", "right_door", "drawer", "down_flap"):
        identity = {
            "left_door": "left_door_panel",
            "right_door": "right_door_panel",
            "drawer": "drawer_front_panel",
            "down_flap": "down_flap_door_panel",
        }.get(panel_type, "front_panel")
        return _pack(identity, "door", "door", "front", ["kitchen", "front", "door", board_id], door_color_slot=1)

    if panel_type == "B1" or board_id == "B1":
        return _pack("bottom_front_door_fascia", "door", "front_visible", "front", ["kitchen", "front", "door-color", "B1"], door_color_slot=1)

    if panel_type == "stove_side_panel":
        identity = "stove_left_side_panel" if board_id.endswith("-left") else "stove_right_side_panel"
        return _pack(
            identity,
            "door",
            "door",
            "front",
            ["kitchen", "stove", "front", "door", board_id],
            door_color_slot=1,
        )

    if kind == "vPanel" or panel_type == "VPanel" or re.fullmatch(r"V\d+", board_id):
        options = entry.get("sidePanelOptions")
        if not isinstance(options, dict) and v_panels:
            for panel in v_panels:
                if str(panel.get("id") or "") == board_id:
                    options = panel.get("sidePanelOptions") if isinstance(panel.get("sidePanelOptions"), dict) else {}
                    break
        options = options if isinstance(options, dict) else {}
        is_door_side = str(options.get("panelType") or "") == "door"
        index_match = re.fullmatch(r"V(\d+)", board_id)
        index = int(index_match.group(1)) if index_match else None
        if is_door_side:
            identity = "left_side_door_panel" if index == 0 else "right_side_door_panel"
            return _pack(identity, "door", "door", "front", ["kitchen", "side", "door", board_id], door_color_slot=1)
        if index == 0:
            identity = "left_side_panel"
        elif v_panels and index is not None and index == len(v_panels) - 1:
            identity = "right_side_panel"
        elif index is not None and index > 0:
            identity = "internal_vertical_panel"
        else:
            identity = "vertical_panel"
        return _pack(identity, "carcass", "carcass", "structural", ["kitchen", "vertical", "carcass", board_id])

    mapping = {
        "B2": ("bottom_front_carcass_rail", "carcass_rail"),
        "B3": ("bottom_deck", "carcass"),
        "B4": ("rear_bottom_vertical_strip", "carcass"),
        "T1": ("top_front_support_strip", "carcass"),
        "T2": ("top_rear_support_strip", "carcass"),
        "T3": ("rear_top_vertical_strip", "carcass"),
        "drawer_divider": ("drawer_divider", "carcass"),
        "full_depth_shelf": ("full_depth_shelf", "carcass"),
        "door_shelf": ("door_shelf", "carcass"),
        "appliance_floor": ("appliance_floor", "carcass"),
        "underside_support": ("underside_support", "carcass"),
        "avoidance_top": ("wheel_avoidance_top", "carcass"),
        "avoidance_front": ("wheel_avoidance_front", "carcass"),
        "side_strengthening_strip": ("side_strengthening_strip", "carcass"),
    }
    if panel_type in mapping:
        identity, role = mapping[panel_type]
        return _pack(identity, "carcass", role, "structural", ["kitchen", "carcass", board_id])
    if "avoidance-top" in board_id or board_id.endswith("-avoidance-top") or board_id.endswith("-AT"):
        return _pack("wheel_avoidance_top", "carcass", "carcass", "structural", ["kitchen", "avoidance", "carcass", board_id])
    if "avoidance-front" in board_id or board_id.endswith("-avoidance-front") or board_id.endswith("-AF"):
        return _pack("wheel_avoidance_front", "carcass", "carcass", "structural", ["kitchen", "avoidance", "carcass", board_id])
    if board_id.endswith("-B4") or "-B4" in board_id:
        return _pack("wheel_avoidance_raised_b4", "carcass", "carcass", "structural", ["kitchen", "avoidance", "carcass", board_id])
    if "side-strengthening-strip" in board_id or board_id.startswith("SS_L_") or board_id.startswith("SS_R_"):
        return _pack("side_strengthening_strip", "carcass", "carcass", "structural", ["kitchen", "carcass", board_id])
    return _pack(panel_type or "unknown_board", "carcass", "carcass", "structural", ["kitchen", "carcass", board_id or "board"])


def lounge_milling_direction(board):
    """Return Lounge milling / cutting face as a design-world ±axis bucket.

    Design frame (generator placement before optional board moves):
      +X width right, +Y depth, +Z up.

    Note: Lounge front placement differs by style (parallel fronts near y≈0;
    I/L fronts near y≈depth), but middle-cabinet doors always sit on the
    cabinet front with interior toward +Y.

    ``millingDirection`` is the outward normal of the cutting face (铣削/切割面).
    Evidence:
      middle_cabinet_*_door — hinge cups on flat bottom face → interior +Y
      middle_cabinet_left — divider groove on inner face (world +X / flat top)
      middle_cabinet_right — divider groove on inner face (world -X / flat bottom)
      middle_cabinet_top — lock bases mount on underside → -Z
      middle_cabinet_bottom — cabinet-interior face is the top of the board → +Z
      lid — assembly offset-ring step cut from bottom → -Z
      top_panel with opening — rebate/through opening cut from top → +Z
      Remaining partition / MC divider / avoidance / strips → EITHER
    """
    board_id = str(board.get("id") or "")
    kind = str(board.get("kind") or "").strip().lower()

    if kind == "cabinet_door" or board_id.endswith("_door") or board_id.endswith("_DR"):
        return _direction_pair("+Y")

    if kind == "cabinet_side" or board_id in ("middle_cabinet_left", "middle_cabinet_right", "MC_L", "MC_R"):
        if board_id.endswith("_left") or board_id in ("middle_cabinet_left", "MC_L"):
            return _direction_pair("+X")
        if board_id.endswith("_right") or board_id in ("middle_cabinet_right", "MC_R"):
            return _direction_pair("-X")
        return _direction_pair("")

    if kind == "cabinet_top" or board_id in ("middle_cabinet_top", "MC_TOP"):
        return _direction_pair("-Z")

    if kind == "cabinet_bottom" or board_id in ("middle_cabinet_bottom", "MC_BOT"):
        return _direction_pair("+Z")

    if kind == "lid" or board_id.endswith("_lid"):
        return _direction_pair("-Z")

    if kind == "top_panel" and isinstance(board.get("opening"), dict):
        return _direction_pair("+Z")

    return _direction_pair("")


def small_cabinet_milling_direction(board):
    """Small Cabinet milling defaults in design-world ±axis buckets.

    Frame: +X right, +Y depth (front carcass at y=0, fronts at y=-FPT..0), +Z up.
    Fronts / door-colored sides: milling face toward cabinet interior.
    """
    board_id = str(board.get("id") or "")
    board_type = str(board.get("boardType") or "").strip().lower()
    category = str(board.get("category") or "").strip().lower()

    if category == "front_panel" or board_type in ("left_door", "right_door", "drawer_front"):
        return _direction_pair("+Y")
    if board_id == "SIDE_L" or board_type == "left_side_panel":
        return _direction_pair("+X")
    if board_id == "SIDE_R" or board_type == "right_side_panel":
        return _direction_pair("-X")
    if board_id == "TOP" or board_type == "top_panel":
        return _direction_pair("-Z")
    if board_id == "BOTTOM" or board_type == "bottom_panel":
        return _direction_pair("+Z")
    if board_id == "BACK" or board_type == "rear_vertical":
        return _direction_pair("-Y")
    if board_type == "middle_shelf" or board_id.startswith("MID_"):
        return _direction_pair("+Z")
    return _direction_pair("")


def small_cabinet_board_semantics(board):
    board_id = str(board.get("id") or "")
    board_type = str(board.get("boardType") or "").strip().lower()
    category = str(board.get("category") or "").strip().lower()
    use_door_color = bool(board.get("useDoorColor"))

    if category == "front_panel" or board_type in ("left_door", "right_door", "drawer_front"):
        identity = board_type or "front_panel"
        return _pack(
            identity,
            "door",
            "door" if board_type in ("left_door", "right_door") else "front_visible",
            "front",
            ["smallCabinet", "front", identity, board_id],
            door_color_slot=1,
        )

    if board_id == "SIDE_L" or board_type == "left_side_panel":
        if use_door_color:
            return _pack(
                "left_side_panel",
                "door",
                "front_visible",
                "side",
                ["smallCabinet", "side", "door-color", board_id],
                door_color_slot=1,
            )
        return _pack(
            "left_side_panel",
            "carcass",
            "carcass",
            "side",
            ["smallCabinet", "side", "carcass", board_id],
        )

    if board_id == "SIDE_R" or board_type == "right_side_panel":
        if use_door_color:
            return _pack(
                "right_side_panel",
                "door",
                "front_visible",
                "side",
                ["smallCabinet", "side", "door-color", board_id],
                door_color_slot=1,
            )
        return _pack(
            "right_side_panel",
            "carcass",
            "carcass",
            "side",
            ["smallCabinet", "side", "carcass", board_id],
        )

    if board_id == "BACK" or board_type == "rear_vertical":
        return _pack("rear_vertical", "carcass", "carcass", "back", ["smallCabinet", "back", "carcass", board_id])
    if board_id == "TOP" or board_type == "top_panel":
        return _pack("top_panel", "carcass", "carcass", "top", ["smallCabinet", "horizontal", "carcass", board_id])
    if board_id == "BOTTOM" or board_type == "bottom_panel":
        return _pack("bottom_panel", "carcass", "carcass", "bottom", ["smallCabinet", "horizontal", "carcass", board_id])
    if board_type == "middle_shelf" or board_id.startswith("MID_"):
        return _pack("middle_shelf", "carcass", "carcass", "shelf", ["smallCabinet", "horizontal", "shelf", board_id])

    return _pack(board_type or "unknown_board", "carcass", "carcass", "structural", ["smallCabinet", "carcass", board_id or "board"])


def lounge_board_semantics(item):
    board_id = str(item.get("id") or "")
    kind = str(item.get("kind") or "")

    if board_id.startswith("middle_cabinet_") or board_id.startswith("MC_") or kind.startswith("cabinet_"):
        identity_map = {
            "cabinet_bottom": "cabinet_bottom",
            "cabinet_top": "cabinet_top",
            "cabinet_side": "cabinet_side",
            "cabinet_divider": "cabinet_divider",
            "cabinet_door": "cabinet_door",
        }
        if board_id.endswith("_left_door") or board_id in ("middle_cabinet_left_door", "MC_L_DR"):
            identity = "left_door_panel"
        elif board_id.endswith("_right_door") or board_id in ("middle_cabinet_right_door", "MC_R_DR"):
            identity = "right_door_panel"
        elif board_id.endswith("_left") or board_id in ("middle_cabinet_left", "MC_L"):
            identity = "cabinet_left_side"
        elif board_id.endswith("_right") or board_id in ("middle_cabinet_right", "MC_R"):
            identity = "cabinet_right_side"
        else:
            identity = identity_map.get(kind, kind or "cabinet_panel")
        role = "door" if identity.endswith("door_panel") or kind == "cabinet_door" else "front_visible"
        return _pack(identity, "door", role, "front", ["lounge", "middle_cabinet", "door", board_id], door_color_slot=1)

    if kind == "lid" or board_id.endswith("_lid"):
        return _pack("lounge_top_lid", "partition", "partition", "top", ["lounge", "partition", "lid", board_id])

    identity_map = {
        "front_panel": "lounge_front_panel",
        "top_panel": "lounge_top_panel",
        "side_panel": "lounge_side_panel",
        "l_support_profile": "lounge_l_support",
        "support_strip": "lounge_support_strip",
        "avoidance_top": "wheel_avoidance_top",
        "avoidance_front": "wheel_avoidance_front",
    }
    if board_id.endswith("_side_strip") or board_id == "l_side_strip":
        identity = "lounge_side_strip"
    else:
        identity = identity_map.get(kind, kind or "lounge_panel")
    return _pack(identity, "partition", "partition", kind or "structural", ["lounge", "partition", board_id])


def normalize_color_tag(value, fallback=DEFAULT_CARCASS_COLOR_TAG):
    token = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().lower().replace(" ", "_"))
    token = re.sub(r"_+", "_", token).strip("_")
    return (token or fallback)[:60]


def resolve_carcass_color(carcass_color=None, carcass_color_name=None):
    """Return (colorTag, displayName) for carcass / partition boards."""
    name = str(carcass_color_name or "").strip()
    raw = str(carcass_color or "").strip()
    if not raw and name:
        raw = name
    if not raw:
        return DEFAULT_CARCASS_COLOR_TAG, DEFAULT_CARCASS_COLOR_NAME
    tag = normalize_color_tag(raw)
    if not name:
        if tag == DEFAULT_CARCASS_COLOR_TAG:
            name = DEFAULT_CARCASS_COLOR_NAME
        else:
            name = str(carcass_color or tag).replace("_", " ").strip().title()
    return tag, name


def extract_carcass_color_from_result(result, params=None):
    """Pull carcassColor from generator result / payload params."""
    bags = []
    if isinstance(params, dict):
        bags.append(params)
    if isinstance(result, dict):
        bags.append(result)
        for key in ("params", "state", "globalSettings"):
            nested = result.get(key)
            if isinstance(nested, dict):
                bags.append(nested)
                nested_global = nested.get("globalSettings")
                if isinstance(nested_global, dict):
                    bags.append(nested_global)
    for bag in bags:
        color = bag.get("carcassColor")
        if color is None:
            color = bag.get("carcass_color")
        name = bag.get("carcassColorName")
        if name is None:
            name = bag.get("carcass_color_name")
        if color or name:
            return resolve_carcass_color(color, name)
    return resolve_carcass_color(None, None)


def uses_carcass_color(panel_class):
    return str(panel_class or "") in ("carcass", "partition")


def design_geometry_from_board(board, bbox=None):
    source = bbox if isinstance(bbox, dict) else board
    placement = board.get("placement") if isinstance(board.get("placement"), dict) else None
    if placement and not bbox:
        source = placement
    return {
        "x0": source.get("x0"),
        "x1": source.get("x1"),
        "y0": source.get("y0"),
        "y1": source.get("y1"),
        "z0": source.get("z0"),
        "z1": source.get("z1"),
        "profilePlane": board.get("profilePlane") or board.get("plane"),
        "thicknessAxis": board.get("thicknessAxis"),
        "materialThickness": board.get("materialThickness") or board.get("thickness"),
    }


def build_panel_metadata(
    module_name,
    board,
    *,
    bbox=None,
    all_boards=None,
    run_label=None,
    v_panels=None,
    features=None,
    carcass_color=None,
    carcass_color_name=None,
):
    module = str(module_name or "").strip()
    board_id = str(board.get("id") or board.get("panelId") or "board")
    milling = None

    if module in ("overhead", "ohc"):
        semantics = overhead_board_semantics(board, all_boards)
        generator = "overhead"
        panel_id = "ohc.{}.{}".format(
            _sanitize_token(run_label, fallback="run", limit=60),
            _sanitize_token(board_id, fallback="board", limit=40),
        )
        source_board_type = str(board.get("boardType") or "")
        milling = overhead_milling_direction(board, features=features)
    elif module in ("generalTall", "general_tall", "gt"):
        semantics = general_tall_board_semantics(board)
        generator = "generalTall"
        if run_label:
            panel_id = "generalTall.{}.{}".format(
                _sanitize_token(run_label, fallback="run", limit=40),
                _sanitize_token(board_id, fallback="board", limit=40),
            )
        else:
            panel_id = "generalTall.{}".format(_sanitize_token(board_id, fallback="board", limit=60))
        source_board_type = str(board.get("boardType") or "")
        milling = general_tall_milling_direction(board, features=features)
    elif module == "kitchen":
        semantics = kitchen_board_semantics(board, v_panels=v_panels)
        generator = "kitchen"
        panel_id = "kitchen.{}.{}".format(
            _sanitize_token(run_label, fallback="run", limit=40),
            _sanitize_token(board_id, fallback="board", limit=40),
        ) if run_label else "kitchen.{}".format(_sanitize_token(board_id, fallback="board", limit=60))
        source_board_type = str(board.get("type") or board.get("panelType") or "")
        milling = kitchen_milling_direction(board, v_panels=v_panels, features=features)
    elif module == "lounge":
        semantics = lounge_board_semantics(board)
        generator = "lounge"
        panel_id = "lounge.{}.{}".format(
            _sanitize_token(run_label, fallback="run", limit=40),
            _sanitize_token(board_id, fallback="board", limit=40),
        ) if run_label else "lounge.{}".format(_sanitize_token(board_id, fallback="board", limit=60))
        source_board_type = str(board.get("kind") or "")
        milling = lounge_milling_direction(board)
    elif module in ("smallCabinet", "small_cabinet", "sc"):
        semantics = small_cabinet_board_semantics(board)
        generator = "smallCabinet"
        panel_id = "smallCabinet.{}.{}".format(
            _sanitize_token(run_label, fallback="run", limit=40),
            _sanitize_token(board_id, fallback="board", limit=40),
        ) if run_label else "smallCabinet.{}".format(_sanitize_token(board_id, fallback="board", limit=60))
        source_board_type = str(board.get("boardType") or "")
        milling = small_cabinet_milling_direction(board)
    else:
        raise ValueError("Unsupported generator module: {!r}".format(module_name))

    default_attributes = {
        "role": semantics["role"],
        "category": semantics["category"],
        "materialClass": semantics["materialClass"],
        "tags": semantics["tags"],
    }
    if semantics.get("doorColorSlot") is not None:
        default_attributes["doorColorSlot"] = semantics["doorColorSlot"]

    classification = {
        "boardType": {
            "value": semantics["panelClass"],
            "source": "generator",
            "locked": False,
        },
        "color": {
            "value": "",
            "source": "default",
            "locked": False,
        },
    }
    design_geometry = design_geometry_from_board(board, bbox=bbox)
    if isinstance(milling, dict):
        cutting_value = str(milling.get("cuttingFace") or "EITHER")
        classification["cuttingFace"] = {
            "value": cutting_value,
            "source": "generator",
            "locked": False,
        }
        if milling.get("millingDirection"):
            default_attributes["millingDirection"] = milling["millingDirection"]
            default_attributes["colourDirection"] = milling.get("colourDirection") or ""
            design_geometry["millingDirection"] = milling["millingDirection"]
            design_geometry["colourDirection"] = milling.get("colourDirection") or ""

    # Carcass (+ Lounge partition) defaults: double-sided White Stipple,
    # overridable via each generator's carcassColor input.
    if uses_carcass_color(semantics["panelClass"]):
        color_tag, color_name = resolve_carcass_color(carcass_color, carcass_color_name)
        classification["color"] = {
            "value": color_tag,
            "source": "generator",
            "locked": False,
        }
        default_attributes["colorName"] = color_name
        default_attributes["surfaceMode"] = CARCASS_SURFACE_MODE

    metadata = {
        "schemaVersion": 1,
        "identity": {
            "panelId": panel_id,
            "generator": generator,
            "module": generator,
            "cabinetType": generator,
            "sourceBoardId": board_id,
            "sourceBoardType": source_board_type,
            "boardType": semantics["boardType"],
            "runId": str(run_label or ""),
        },
        "defaultAttributes": default_attributes,
        "classification": classification,
        "designGeometry": design_geometry,
        "lifecycle": {
            "state": "generated",
            "reviewRequired": False,
        },
    }
    declared_cuts = declared_cuts_from_board(board)
    if declared_cuts:
        metadata["declaredCuts"] = declared_cuts
    return metadata


def declared_cuts_from_board(board):
    """Slim cut declarations for later feature-intent stamping (LED, half grooves)."""
    if not isinstance(board, dict):
        return []
    cuts = []
    seen = set()
    body = board.get("body") if isinstance(board.get("body"), dict) else {}
    sources = (
        list(board.get("halfGrooveVectors") or [])
        + list(board.get("cutouts") or [])
        + list(body.get("cutouts") or [])
    )
    for cut in sources:
        if not isinstance(cut, dict):
            continue
        source_id = str(cut.get("sourceId") or cut.get("id") or "").strip()
        kind = str(cut.get("kind") or "").strip()
        slot_type = str(cut.get("slotType") or cut.get("resolvedSlotType") or "").strip()
        purpose = str(cut.get("purpose") or cut.get("operationType") or "").strip()
        sid_lower = source_id.lower()
        if not purpose and "led" in sid_lower:
            purpose = "led_groove"
        key = (source_id, kind, slot_type, purpose, str(cut.get("grooveDepth") or ""))
        if key in seen:
            continue
        if not source_id and not kind and not purpose:
            continue
        seen.add(key)
        row = {
            "sourceId": source_id,
            "kind": kind,
            "slotType": slot_type,
            "purpose": purpose,
        }
        depth = cut.get("grooveDepth")
        if depth is not None:
            try:
                row["grooveDepth"] = round(float(depth), 3)
            except Exception:
                pass
        cuts.append(row)
    return cuts


def _set_entity_attribute(entity, group, name, value):
    try:
        attrs = entity.attributes
        existing = attrs.itemByName(group, name) if attrs else None
        if existing:
            existing.value = str(value)
        else:
            attrs.add(group, name, str(value))
        return True
    except Exception:
        return False


def write_panel_metadata_to_body(body, metadata):
    if not body or not isinstance(metadata, dict):
        return False
    panel_id = str(((metadata.get("identity") or {}).get("panelId")) or "")
    payload = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    ok_id = _set_entity_attribute(body, PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, panel_id) if panel_id else True
    ok_payload = _set_entity_attribute(body, PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR, payload)
    _set_entity_attribute(body, "UnifiedCabinet", "instanceRole", "generated")
    return bool(ok_id and ok_payload)


def write_generator_panel_metadata(
    body,
    module_name,
    board,
    *,
    bbox=None,
    all_boards=None,
    run_label=None,
    v_panels=None,
    features=None,
    carcass_color=None,
    carcass_color_name=None,
):
    metadata = build_panel_metadata(
        module_name,
        board,
        bbox=bbox,
        all_boards=all_boards,
        run_label=run_label,
        v_panels=v_panels,
        features=features,
        carcass_color=carcass_color,
        carcass_color_name=carcass_color_name,
    )
    return metadata, write_panel_metadata_to_body(body, metadata)
