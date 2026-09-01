"""Estimate generator params from an existing overhead/kitchen assembly.

Used when the component has no stored generatorParams snapshot (older runs).
Prefers UnifiedCabinet.Panel designGeometry (cabinet-local). Falls back to
occurrence / body bounding boxes in millimetres.
"""

import json
import re

from core.assembly_snapshot import entity_attr

PANEL_METADATA_GROUP = "UnifiedCabinet.Panel"
OH_ZONE_TYPES = (
    "up_flap",
    "rangehood_flap",
    "fixed_panel",
    "left_door",
    "right_door",
    "double_door",
    "left_side_door",
    "right_side_door",
    "drawer",
    "down_flap",
    "open",
)
KITCHEN_ZONE_TYPES = (
    "left_door",
    "right_door",
    "double_door",
    "drawer",
    "down_flap",
    "stove",
    "open",
    "custom",
    "unassigned",
)
BOARD_ID_RE = re.compile(
    r"(?:^|[.\-_])(BP|T\d+|D\d+|FP\d+|RGHD_[A-Z]+|U_CONNECTOR|V\d+|B\d+|SS_[LR]_\w+|[^.\-_]*avoidance[^.\-_]*)$",
    re.I,
)


def round1(value):
    try:
        return round(float(value) * 10.0) / 10.0
    except Exception:
        return 0.0


def _span(box, axis):
    return round1(box.get(axis + "1", 0) - box.get(axis + "0", 0))


def _center(box, axis):
    return round1((box.get(axis + "0", 0) + box.get(axis + "1", 0)) / 2.0)


def _thickness(box):
    spans = [abs(_span(box, axis)) for axis in ("x", "y", "z")]
    spans = [s for s in spans if s > 0.05]
    return round1(min(spans)) if spans else 0.0


def normalize_board_id(raw):
    text = str(raw or "").strip()
    if not text:
        return ""
    match = BOARD_ID_RE.search(text)
    if match:
        token = match.group(1)
        if token.upper().startswith("RGHD"):
            return token.upper()
        if token.upper() in ("BP", "U_CONNECTOR"):
            return token.upper()
        return token.upper() if re.fullmatch(r"[A-Z]+\d+", token.upper()) else token
    return text


def _cm_bbox_to_mm(bbox):
    try:
        mn = bbox.minPoint
        mx = bbox.maxPoint
    except Exception:
        return None
    return {
        "x0": round1(mn.x * 10.0),
        "y0": round1(mn.y * 10.0),
        "z0": round1(mn.z * 10.0),
        "x1": round1(mx.x * 10.0),
        "y1": round1(mx.y * 10.0),
        "z1": round1(mx.z * 10.0),
    }


def _parse_metadata(entity):
    raw = entity_attr(entity, "metadata", groups=(PANEL_METADATA_GROUP,))
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _design_bbox(metadata):
    geom = metadata.get("designGeometry") if isinstance(metadata, dict) else None
    if not isinstance(geom, dict):
        return None
    keys = ("x0", "x1", "y0", "y1", "z0", "z1")
    if any(geom.get(key) is None for key in keys):
        return None
    try:
        box = {key: round1(geom.get(key)) for key in keys}
    except Exception:
        return None
    if box["x1"] <= box["x0"] or box["y1"] <= box["y0"] or box["z1"] <= box["z0"]:
        return None
    return box


def _iter_child_occurrences(component):
    try:
        occurrences = component.occurrences
        count = occurrences.count
    except Exception:
        return
    for index in range(count):
        try:
            yield occurrences.item(index)
        except Exception:
            continue


def _iter_bodies(component):
    try:
        bodies = component.bRepBodies
        count = bodies.count
    except Exception:
        return
    for index in range(count):
        try:
            body = bodies.item(index)
        except Exception:
            continue
        try:
            if body and getattr(body, "isSolid", True):
                yield body
        except Exception:
            continue


def _iter_occurrence_children(occurrence):
    try:
        children = getattr(occurrence, "childOccurrences", None)
        count = children.count if children is not None else 0
    except Exception:
        children = None
        count = 0
    if children is None or count < 1:
        return
    for index in range(count):
        try:
            yield children.item(index)
        except Exception:
            continue


def _iter_occ_bodies(occurrence):
    try:
        bodies = getattr(occurrence, "bRepBodies", None)
        count = bodies.count if bodies is not None else 0
    except Exception:
        return
    for index in range(count):
        try:
            body = bodies.item(index)
        except Exception:
            continue
        try:
            if body and getattr(body, "isSolid", True):
                yield body
        except Exception:
            continue


def _row_key(board_id, box):
    if isinstance(box, dict):
        return (
            str(board_id or ""),
            box.get("x0"),
            box.get("x1"),
            box.get("y0"),
            box.get("y1"),
            box.get("z0"),
            box.get("z1"),
        )
    return (str(board_id or ""), None)


def collect_panel_records(component, occurrence=None):
    """Walk an assembly and return serializable panel rows."""
    rows = []
    if not component and occurrence is None:
        return rows
    seen = set()

    def add_row(entity, parent, occ=None):
        metadata = _parse_metadata(entity) or _parse_metadata(parent)
        identity = metadata.get("identity") if isinstance(metadata, dict) else {}
        board_id = (
            entity_attr(entity, "boardId")
            or entity_attr(entity, "panelId")
            or entity_attr(entity, "bodyId")
            or entity_attr(parent, "boardId")
            or entity_attr(parent, "panelId")
            or (identity or {}).get("sourceBoardId")
            or getattr(entity, "name", "")
            or getattr(parent, "name", "")
        )
        board_id = normalize_board_id(board_id)
        panel_type = (
            entity_attr(entity, "panelType")
            or entity_attr(entity, "boardType")
            or entity_attr(parent, "panelType")
            or entity_attr(parent, "boardType")
            or (identity or {}).get("sourceBoardType")
            or (identity or {}).get("boardType")
            or ""
        )
        panel_kind = entity_attr(entity, "panelKind") or entity_attr(parent, "panelKind") or ""
        box = _design_bbox(metadata)
        source = "designGeometry"
        if box is None:
            source = "occurrenceBbox"
            if occ is not None:
                box = _cm_bbox_to_mm(getattr(occ, "boundingBox", None))
            if box is None:
                source = "bodyBbox"
                box = _cm_bbox_to_mm(getattr(entity, "boundingBox", None))
        key = _row_key(board_id, box)
        if key in seen:
            return
        seen.add(key)
        if not board_id and not box:
            return
        rows.append({
            "boardId": board_id,
            "panelType": str(panel_type or ""),
            "panelKind": str(panel_kind or ""),
            "bbox": box,
            "source": source,
            "thickness": _thickness(box) if box else 0.0,
        })

    def walk(comp, occ, depth):
        if depth > 8:
            return
        if comp is not None:
            for body in _iter_bodies(comp):
                add_row(body, comp, occ)
            for child in _iter_child_occurrences(comp):
                walk(getattr(child, "component", None), child, depth + 1)
        if occ is not None:
            for body in _iter_occ_bodies(occ):
                add_row(body, getattr(occ, "component", None) or comp, occ)
            for child in _iter_occurrence_children(occ):
                walk(getattr(child, "component", None), child, depth + 1)

    walk(component, occurrence, 0)
    return rows


def _with_box(rows):
    return [row for row in rows if isinstance(row.get("bbox"), dict)]


def _envelope(rows):
    boxed = _with_box(rows)
    if not boxed:
        return None
    return {
        "x0": min(row["bbox"]["x0"] for row in boxed),
        "x1": max(row["bbox"]["x1"] for row in boxed),
        "y0": min(row["bbox"]["y0"] for row in boxed),
        "y1": max(row["bbox"]["y1"] for row in boxed),
        "z0": min(row["bbox"]["z0"] for row in boxed),
        "z1": max(row["bbox"]["z1"] for row in boxed),
    }


def _is_oh_divider(row):
    board_id = str(row.get("boardId") or "")
    return bool(re.fullmatch(r"D\d+", board_id, re.I))


def _is_oh_front(row):
    board_id = str(row.get("boardId") or "")
    kind = str(row.get("panelKind") or "").lower()
    return board_id.upper().startswith("FP") or kind == "frontpanel"


def _oh_zone_type(row):
    text = " ".join(
        [
            str(row.get("panelType") or ""),
            str(row.get("panelKind") or ""),
            str(row.get("boardId") or ""),
        ]
    ).lower()
    for zone_type in OH_ZONE_TYPES:
        if zone_type.replace("_", " ") in text or zone_type in text:
            return zone_type
    if "rangehood" in text:
        return "rangehood_flap"
    if "flap" in text:
        return "up_flap"
    if "fixed" in text:
        return "fixed_panel"
    if "double" in text:
        return "double_door"
    if "left" in text:
        return "left_door"
    if "right" in text:
        return "right_door"
    return "up_flap"


def infer_overhead_params(rows):
    boxed = _with_box(rows)
    env = _envelope(boxed)
    if not env:
        return {"ok": False, "errors": ["No measurable overhead boards found."]}
    bp = next((row for row in boxed if str(row.get("boardId") or "").upper() == "BP"), None)
    width = _span(bp["bbox"], "x") if bp else _span(env, "x")
    depth = _span(bp["bbox"], "y") if bp else _span(env, "y")
    height = _span(env, "z")
    if height < 20 and bp:
        height = max(_span(env, "z"), 400.0)
    dividers = [row for row in boxed if _is_oh_divider(row) and row.get("bbox")]
    dividers.sort(key=lambda row: _center(row["bbox"], "x"))
    feature_width = 15.0
    if dividers:
        feature_width = dividers[0]["thickness"] or _thickness(dividers[0]["bbox"]) or 15.0
    fronts = [row for row in boxed if _is_oh_front(row) and row.get("bbox")]
    fronts.sort(key=lambda row: _center(row["bbox"], "x"))
    front_thickness = 16.0
    if fronts:
        front_thickness = fronts[0]["thickness"] or 16.0
    internals = dividers[1:-1] if len(dividers) >= 2 else []
    if len(dividers) == 1:
        internals = []
    zones = []
    if internals:
        centers = [_center(row["bbox"], "x") - env["x0"] for row in internals]
        edges = [0.0] + centers + [width]
        for index in range(len(edges) - 1):
            zone_width = max(1.0, round1(edges[index + 1] - edges[index]))
            zone_type = "up_flap"
            if index < len(fronts):
                zone_type = _oh_zone_type(fronts[index])
            zones.append({"id": "oh-zone-{}".format(index + 1), "type": zone_type, "width": zone_width})
    else:
        zone_type = _oh_zone_type(fronts[0]) if fronts else "up_flap"
        zones.append({"id": "oh-zone-1", "type": zone_type, "width": max(1.0, round1(width))})
    zone_sum = round1(sum(zone["width"] for zone in zones))
    if zones and abs(zone_sum - round1(width)) > 0.15:
        zones[-1]["width"] = max(1.0, round1(zones[-1]["width"] + (round1(width) - zone_sum)))
    t3 = next((row for row in boxed if str(row.get("boardId") or "").upper() == "T3"), None)
    t4 = next((row for row in boxed if str(row.get("boardId") or "").upper() == "T4"), None)
    top_clearance = 40.0
    if t4 and env:
        top_clearance = max(1.0, round1(env["z1"] - t4["bbox"]["z0"]))
        if top_clearance > height * 0.4:
            top_clearance = 40.0
    has_rangehood = any(
        str(row.get("boardId") or "").upper().startswith("RGHD")
        or "rangehood" in str(row.get("panelType") or "").lower()
        or row.get("type") == "rangehood_flap"
        or _oh_zone_type(row) == "rangehood_flap"
        for row in boxed
    )
    geom_count = sum(1 for row in boxed if row.get("source") == "designGeometry")
    notes = []
    if geom_count:
        notes.append("Used designGeometry on {}/{} boards.".format(geom_count, len(boxed)))
    else:
        notes.append("No designGeometry; used measured bounding boxes.")
    notes.append("Clearance / hinge / colour kept at defaults.")
    params = {
        "style": "style_1",
        "cabinetWidth": max(1.0, round1(width)),
        "cabinetDepth": max(1.0, round1(depth)),
        "cabinetHeight": max(1.0, round1(height)),
        "topClearanceHeight": round1(top_clearance),
        "frontPanelThickness": max(0.1, round1(front_thickness)),
        "clearance": 2.5,
        "ledGroove": t3 is not None,
        "featureWidth": max(0.1, round1(feature_width)),
        "zones": zones,
        "selectedZoneIndex": 0,
        "rangehoodPreset": "NCE",
        "rangehoodClearHeight": 75,
        "rangehoodAlignment": "left",
        "rangehoodEdgeOffsetX": 40,
        "carcassColor": "white_stipple",
        "carcassColorName": "White Stipple",
    }
    return {
        "ok": True,
        "module": "overhead",
        "params": params,
        "estimated": True,
        "confidence": "high" if geom_count >= max(2, len(boxed) // 2) else "medium",
        "warnings": notes,
        "boardCount": len(boxed),
        "hasRangehood": has_rangehood,
    }


def _is_carcass_strip_id(board_id):
    text = str(board_id or "")
    return bool(re.fullmatch(r"(B\d+|T\d+(-\d+)?)", text, re.I))


def _is_kitchen_v(row, env=None):
    kind = str(row.get("panelKind") or "").lower()
    panel_type = str(row.get("panelType") or "").lower()
    board_id = str(row.get("boardId") or "")
    if kind == "vpanel" or panel_type == "vpanel":
        return True
    if re.fullmatch(r"V\d+", board_id, re.I):
        return True
    box = row.get("bbox")
    if not isinstance(box, dict):
        return False
    sx, sy, sz = _span(box, "x"), _span(box, "y"), _span(box, "z")
    height = _span(env, "z") if env else 0.0
    depth = _span(env, "y") if env else 0.0
    tall_enough = sz >= max(200.0, height * 0.45) if height else sz >= 200.0
    deep_enough = sy >= max(80.0, depth * 0.3) if depth else sy >= 80.0
    thin_x = 8.0 <= sx <= 25.0 and sx < sy and sx < sz
    return thin_x and tall_enough and deep_enough


def _is_kitchen_front(row, env=None):
    if _is_kitchen_v(row, env):
        return False
    board_id = str(row.get("boardId") or "")
    if _is_carcass_strip_id(board_id):
        return False
    kind = str(row.get("panelKind") or "").lower()
    panel_type = str(row.get("panelType") or "").lower()
    if kind == "frontpanel":
        return True
    if panel_type in KITCHEN_ZONE_TYPES:
        return True
    if re.search(r"(^|[-_])fp\d+|front[_-]?panel", board_id, re.I):
        return True
    box = row.get("bbox")
    if not isinstance(box, dict):
        return False
    sx, sy, sz = _span(box, "x"), _span(box, "y"), _span(box, "z")
    thin_y = 8.0 <= sy <= 22.0 and sy < sx and sy < sz
    if not (thin_y and sx >= 80.0 and sz >= 80.0):
        return False
    if env:
        return box["y0"] <= env["y0"] + 25.0 or box["y1"] <= 20.0
    return box["y0"] < 20.0 or box["y1"] <= 20.0


def _x_overlap(box_a, box_b):
    return max(0.0, min(box_a["x1"], box_b["x1"]) - max(box_a["x0"], box_b["x0"]))


def _fronts_share_column(row_a, row_b):
    box_a = row_a["bbox"]
    box_b = row_b["bbox"]
    overlap = _x_overlap(box_a, box_b)
    min_width = min(_span(box_a, "x"), _span(box_b, "x"))
    return overlap >= max(30.0, min_width * 0.4)


def _cluster_fronts_by_x(fronts):
    ordered = sorted(fronts, key=lambda row: row["bbox"]["x0"])
    clusters = []
    for row in ordered:
        box = row["bbox"]
        matched = next(
            (
                cluster
                for cluster in clusters
                if any(_fronts_share_column(row, existing) for existing in cluster["fronts"])
            ),
            None,
        )
        if matched is None:
            clusters.append({
                "x0": box["x0"],
                "x1": box["x1"],
                "fronts": [row],
            })
            continue
        matched["x1"] = max(matched["x1"], box["x1"])
        matched["x0"] = min(matched["x0"], box["x0"])
        matched["fronts"].append(row)
    return clusters


def _column_edges_from_vs(vs, length):
    origin_x = vs[0]["bbox"]["x0"]
    edges = [0.0]
    for row in vs[1:-1]:
        edges.append(round1(row["bbox"]["x0"] - origin_x))
    edges.append(round1(length))
    return edges, origin_x


def _column_edges_from_fronts(clusters, length, origin_x):
    if len(clusters) < 2:
        return None
    edges = [0.0]
    for index in range(len(clusters) - 1):
        mid = (clusters[index]["x1"] + clusters[index + 1]["x0"]) / 2.0
        edges.append(round1(mid - origin_x))
    edges.append(round1(length))
    return edges


def _zones_from_fronts(fronts, col_index, editable):
    zones = []
    ordered = sorted(fronts, key=lambda row: -row["bbox"]["z1"])
    for zone_index, row in enumerate(ordered):
        zones.append({
            "id": "k-zone-{}-{}".format(col_index + 1, zone_index + 1),
            "height": max(1.0, _span(row["bbox"], "z")),
            "zoneType": _kitchen_zone_type(row),
        })
    if not zones:
        return [{"id": "k-zone-{}".format(col_index + 1), "height": editable, "zoneType": "open"}]
    zone_sum = round1(sum(zone["height"] for zone in zones))
    if abs(zone_sum - editable) > 1.0:
        scale = editable / max(1.0, zone_sum)
        allocated = 0.0
        for zone_index, zone in enumerate(zones):
            if zone_index == len(zones) - 1:
                zone["height"] = max(1.0, round1(editable - allocated))
            else:
                zone["height"] = max(1.0, round1(zone["height"] * scale))
                allocated = round1(allocated + zone["height"])
    return zones


def _kitchen_zone_type(row):
    text = " ".join(
        [
            str(row.get("panelType") or ""),
            str(row.get("panelKind") or ""),
            str(row.get("boardId") or ""),
        ]
    ).lower()
    for zone_type in KITCHEN_ZONE_TYPES:
        if zone_type in text:
            return zone_type
    if "stove" in text:
        return "stove"
    if "drawer" in text:
        return "drawer"
    if "flap" in text:
        return "down_flap"
    if "double" in text:
        return "double_door"
    if "left" in text:
        return "left_door"
    if "right" in text:
        return "right_door"
    if "open" in text:
        return "open"
    return "custom"


def _kitchen_column_type(zones):
    types = [zone.get("zoneType") for zone in zones if zone.get("zoneType") and zone.get("zoneType") != "unassigned"]
    if not types:
        return "custom"
    if "stove" in types:
        return "stove"
    if all(item in ("drawer", "down_flap") for item in types):
        return "drawer"
    if len(set(types)) == 1 and types[0] in KITCHEN_ZONE_TYPES:
        return types[0]
    return "custom"


def infer_kitchen_params(rows):
    boxed = _with_box(rows)
    env = _envelope(boxed)
    if not env:
        return {"ok": False, "errors": ["No measurable kitchen boards found."]}
    vs = [row for row in boxed if _is_kitchen_v(row, env)]
    vs.sort(key=lambda row: row["bbox"]["x0"])
    fronts = [row for row in boxed if _is_kitchen_front(row, env)]
    fronts.sort(key=lambda row: (_center(row["bbox"], "x"), -row["bbox"]["z1"]))
    front_clusters = _cluster_fronts_by_x(fronts)
    length = _span(env, "x")
    if vs:
        length = max(length, round1(vs[-1]["bbox"]["x1"] - vs[0]["bbox"]["x0"]))
    depth = _span(env, "y")
    height = _span(env, "z")
    material = 15.0
    if vs:
        material = vs[0]["thickness"] or 15.0
    front_thickness = 16.0
    if fronts:
        front_thickness = fronts[0]["thickness"] or 16.0
    b3 = next((row for row in boxed if str(row.get("boardId") or "").upper() == "B3" or str(row.get("panelType") or "") == "B3"), None)
    bottom_h = 55.0
    if fronts:
        min_front_z = min(row["bbox"]["z0"] for row in fronts)
        if 10 <= min_front_z <= 120:
            bottom_h = round1(min_front_z)
    editable = max(1.0, round1(height - bottom_h))
    origin_x = env["x0"]
    edges = None
    if len(vs) >= 3 or (len(vs) >= 2 and len(front_clusters) < 2):
        edges, origin_x = _column_edges_from_vs(vs, length)
    elif len(front_clusters) >= 2:
        origin_x = env["x0"]
        edges = _column_edges_from_fronts(front_clusters, length, origin_x)
    columns = []
    if edges and len(edges) >= 2:
        for index in range(len(edges) - 1):
            width = max(1.0, round1(edges[index + 1] - edges[index]))
            x0 = origin_x + edges[index]
            x1 = origin_x + edges[index + 1]
            col_fronts = [
                row for row in fronts
                if _center(row["bbox"], "x") >= x0 - 1 and _center(row["bbox"], "x") <= x1 + 1
            ]
            zones = _zones_from_fronts(col_fronts, index, editable)
            columns.append({
                "id": "k-col-{}".format(index + 1),
                "width": width,
                "columnType": _kitchen_column_type(zones),
                "zones": zones,
            })
    if not columns:
        zones = _zones_from_fronts(fronts, 0, editable) if fronts else [
            {"id": "k-zone-1", "height": editable, "zoneType": "open"}
        ]
        if fronts and len(front_clusters) < 2:
            zones = _zones_from_fronts(fronts, 0, editable)
        columns = [{
            "id": "k-col-1",
            "width": max(1.0, round1(length)),
            "columnType": _kitchen_column_type(zones),
            "zones": zones,
        }]
    avoidances = []
    for row in boxed:
        board_id = str(row.get("boardId") or "").lower()
        panel_type = str(row.get("panelType") or "").lower()
        if "avoidance" not in board_id and "avoidance" not in panel_type and panel_type not in ("avoidance_top", "avoidance_front"):
            continue
        if "front" in board_id or panel_type == "avoidance_front":
            continue
        box = row["bbox"]
        avoidances.append({
            "id": "k-wheel-{}".format(len(avoidances) + 1),
            "x0": round1(box["x0"] - env["x0"]),
            "x1": round1(box["x1"] - env["x0"]),
            "height": max(1.0, _span(box, "z")),
            "depth": max(1.0, _span(box, "y")),
        })
    geom_count = sum(1 for row in boxed if row.get("source") == "designGeometry")
    notes = []
    if geom_count:
        notes.append("Used designGeometry on {}/{} boards.".format(geom_count, len(boxed)))
    else:
        notes.append("No designGeometry; used measured bounding boxes.")
    notes.append("Front clearance, lock style, and side-panel options kept at defaults.")
    if b3 is None:
        notes.append("B3 not found; bottom clearance estimated from front panels.")
    if len(vs) < 2 and len(front_clusters) < 2:
        notes.append("Only {} verticals and {} front groups found; partitions may be incomplete.".format(
            len(vs), len(front_clusters)
        ))
    if len(vs) >= 2 or len(front_clusters) >= 2:
        confidence = "high"
    elif fronts or vs:
        confidence = "medium"
    else:
        confidence = "low"
    params = {
        "version": 1,
        "globalSettings": {
            "length": max(1.0, round1(length)),
            "depth": max(1.0, round1(depth)),
            "height": max(1.0, round1(height)),
            "materialThickness": max(0.1, round1(material)),
            "frontThickness": max(0.1, round1(front_thickness)),
            "frontClearance": 2.5,
            "lockEnabled": True,
            "lockPresetId": "razor_long_rounded_1",
            "bottomClearanceHeight": round1(bottom_h),
            "bottomClearanceStyle": "style_1",
            "ledGroove": True,
            "carcassColor": "white_stipple",
            "carcassColorName": "White Stipple",
        },
        "columns": columns,
        "wheelAvoidances": avoidances,
        "vPanelMachiningPreferences": [],
    }
    return {
        "ok": True,
        "module": "kitchen",
        "params": params,
        "estimated": True,
        "confidence": confidence,
        "warnings": notes,
        "boardCount": len(boxed),
        "vCount": len(vs),
        "frontCount": len(fronts),
    }


def infer_params_from_rows(module, rows):
    if module == "overhead":
        return infer_overhead_params(rows)
    if module == "kitchen":
        return infer_kitchen_params(rows)
    return {"ok": False, "errors": ["Geometry infer supports overhead and kitchen only."]}


def infer_params_from_component(module, component, occurrence=None):
    rows = collect_panel_records(component, occurrence=occurrence)
    result = infer_params_from_rows(module, rows)
    result["collectedBoards"] = [
        {
            "boardId": row.get("boardId"),
            "panelType": row.get("panelType"),
            "panelKind": row.get("panelKind"),
            "source": row.get("source"),
            "bbox": row.get("bbox"),
        }
        for row in rows[:40]
    ]
    return result
