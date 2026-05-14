"""
Fusion v0.1: flat preview bodies from BoardPlan outerVector (no cabinet placement).

Sketch 2D coords follow solid_extrude_service convention:
  XY  -> (profile[0], profile[1]) = model X, Y; extrude +Z
  XZ  -> (profile[0], profile[1]) = model X, Z; extrude +Y
  YZ  -> (profile[0], profile[1]) = model Y, Z; extrude +X
All board dimensions are mm; Fusion internal units are cm.
"""

from __future__ import annotations

import random

import adsk.core
import adsk.fusion

ATTRIBUTE_GROUP = "FridgeCabinetGenerator"
FEATURE_PREFIX = "FCG_V01_"
GEOMETRY_BUILD = "flat-geometry-flat-xy-preview-003"

# Flat preview layout (readability only; does not change profile or extrusion depth).
FLAT_PREVIEW_ROW_ORDER = ("B", "V", "Zi", "H", "T", "Other")
ROW_GAP_MM = 300.0
ROW_GAP_PAD_MM = 150.0
COL_GAP_MM = 100.0
PREVIEW_MODE = "flat_xy"


def _flat_preview_row_name(series) -> str:
    if series is None:
        return "Other"
    s = str(series).strip()
    if not s:
        return "Other"
    su = s.upper()
    if su == "ZI":
        return "Zi"
    if su in ("B", "V", "H", "T"):
        return su
    return "Other"


def _flat_preview_row_index(row_name: str) -> int:
    try:
        return FLAT_PREVIEW_ROW_ORDER.index(row_name)
    except ValueError:
        return FLAT_PREVIEW_ROW_ORDER.index("Other")


def _mm_to_cm(mm: float) -> float:
    return float(mm) / 10.0


def _plane_token(profile_plane: str) -> str:
    p = (profile_plane or "XY").upper()
    if p == "XZ":
        return "xz"
    if p == "YZ":
        return "yz"
    return "xy"


def _construction_plane(root: adsk.fusion.Component, profile_plane: str):
    p = (profile_plane or "XY").upper()
    if p == "XZ":
        return root.xZConstructionPlane
    if p == "YZ":
        return root.yZConstructionPlane
    return root.xYConstructionPlane


def _point_for_sketch_plane(a_mm: float, b_mm: float, plane_token: str) -> adsk.core.Point3D:
    # Same mapping as fusion360-cabinet-generator solid_extrude_service._point_for_plane
    return adsk.core.Point3D.create(_mm_to_cm(a_mm), _mm_to_cm(b_mm), 0.0)


def _outer_vector_valid(board: dict) -> bool:
    ov = board.get("outerVector")
    if not isinstance(ov, list) or len(ov) < 3:
        return False
    for p in ov:
        if not isinstance(p, (list, tuple)) or len(p) < 2:
            return False
        if not isinstance(p[0], (int, float)) or not isinstance(p[1], (int, float)):
            return False
    return True


def _sanitize_feature_token(board_id: str) -> str:
    out = []
    for ch in str(board_id or "board"):
        if ch.isalnum() or ch in ("_", "-"):
            out.append(ch)
        else:
            out.append("_")
    s = "".join(out) or "board"
    return s[:80]


def _draw_closed_profile(
    sketch: adsk.fusion.Sketch,
    points_mm,
    name_prefix: str,
    plane_token: str,
    flat_xy_preview: bool = False,
    flat_off_u_mm: float = 0.0,
    flat_off_v_mm: float = 0.0,
) -> bool:
    lines_api = sketch.sketchCurves.sketchLines
    clean = list(points_mm)
    if len(clean) > 1 and clean[0] == clean[-1]:
        clean = clean[:-1]
    if len(clean) < 3:
        return False

    def pt(u_mm: float, v_mm: float) -> adsk.core.Point3D:
        if flat_xy_preview:
            return adsk.core.Point3D.create(
                _mm_to_cm(float(u_mm) + flat_off_u_mm),
                _mm_to_cm(float(v_mm) + flat_off_v_mm),
                0.0,
            )
        return _point_for_sketch_plane(u_mm, v_mm, plane_token)

    first_pt = pt(clean[0][0], clean[0][1])
    second_pt = pt(clean[1][0], clean[1][1])
    first_line = lines_api.addByTwoPoints(first_pt, second_pt)
    first_line.name = "{}_E1".format(name_prefix)
    start_sketch_point = first_line.startSketchPoint
    previous_end = first_line.endSketchPoint

    edge_index = 2
    for point in clean[2:]:
        nxt = pt(point[0], point[1])
        line = lines_api.addByTwoPoints(previous_end, nxt)
        line.name = "{}_E{}".format(name_prefix, edge_index)
        previous_end = line.endSketchPoint
        edge_index += 1

    close_line = lines_api.addByTwoPoints(previous_end, start_sketch_point)
    close_line.name = "{}_E{}".format(name_prefix, edge_index)
    return True


def _largest_profile(sketch: adsk.fusion.Sketch):
    best = None
    best_area = -1.0
    try:
        n = sketch.profiles.count
    except Exception:
        n = 0
    for i in range(n):
        prof = sketch.profiles.item(i)
        try:
            ap = prof.areaProperties(adsk.fusion.CalculationAccuracy.LowCalculationAccuracy)
            area = float(ap.area)
        except Exception:
            area = 0.0
        if area > best_area:
            best_area = area
            best = prof
    return best


def create_sketch_from_outer_vector(
    root_comp: adsk.fusion.Component,
    board: dict,
    offset_mm=(0.0, 0.0, 0.0),
    run_suffix=0,
    preview_mode: str = PREVIEW_MODE,
    profile_offset_u_mm: float = 0.0,
    profile_offset_v_mm: float = 0.0,
):
    """
    Build a new sketch with the board's closed outerVector profile.

    When preview_mode == "flat_xy", always sketches on root XY plane: outerVector [u,v] -> model X/Y,
    thickness extrudes +Z. board.profilePlane is ignored for orientation (metadata only elsewhere).

    offset_mm: optional (du, dv, _) in mm — for flat_xy, prefer profile_offset_u_mm / profile_offset_v_mm.
    """
    _ = offset_mm
    if not _outer_vector_valid(board):
        return None, "invalid_outer_vector"

    plane_name_meta = board.get("profilePlane") or "XY"
    sketch_name = "{}SK_{}_{}".format(
        FEATURE_PREFIX, _sanitize_feature_token(str(board.get("id", "id"))), int(run_suffix)
    )

    if preview_mode == "flat_xy":
        base_plane = root_comp.xYConstructionPlane
        token = "xy"
        flat_xy = True
    else:
        token = _plane_token(plane_name_meta)
        base_plane = _construction_plane(root_comp, plane_name_meta)
        flat_xy = False

    sketch = root_comp.sketches.add(base_plane)
    sketch.name = sketch_name
    prof_name = "{}PROFILE_{}".format(FEATURE_PREFIX, _sanitize_feature_token(str(board.get("id", "id"))))
    ok = _draw_closed_profile(
        sketch,
        board["outerVector"],
        prof_name,
        token,
        flat_xy_preview=flat_xy,
        flat_off_u_mm=profile_offset_u_mm,
        flat_off_v_mm=profile_offset_v_mm,
    )
    if not ok:
        try:
            sketch.deleteMe()
        except Exception:
            pass
        return None, "draw_profile_failed"
    return sketch, None


def extrude_board_profile(root_comp: adsk.fusion.Component, board: dict, sketch: adsk.fusion.Sketch, run_suffix=0):
    """Extrude the primary closed profile by board.thickness (mm). Returns (body, feature) or (None, None)."""
    profile = _largest_profile(sketch)
    if not profile:
        return None, None
    thickness = board.get("thickness")
    if thickness is None:
        thickness = 15.0
    try:
        thickness = float(thickness)
    except Exception:
        thickness = 15.0

    extrudes = root_comp.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(_mm_to_cm(thickness)))
    feat_name = "{}EXTR_{}_{}".format(
        FEATURE_PREFIX, _sanitize_feature_token(str(board.get("id", "id"))), int(run_suffix)
    )
    try:
        feature = extrudes.add(ext_input)
        feature.name = feat_name
    except Exception:
        return None, None
    if feature.bodies.count < 1:
        return None, feature
    body = feature.bodies.item(0)
    bid = str(board.get("id", "")).strip()
    bname = str(board.get("name", "")).strip()
    if bname:
        body.name = "{} - {}".format(bid, bname) if bid else bname
    else:
        body.name = bid or "Board"
    try:
        body.attributes.add(ATTRIBUTE_GROUP, "fcg_v01", "1")
    except Exception:
        pass
    return body, feature


def _body_min_mm(body: adsk.fusion.BRepBody):
    mn = body.boundingBox.minPoint
    return mn.x * 10.0, mn.y * 10.0, mn.z * 10.0


def _body_max_mm(body: adsk.fusion.BRepBody):
    mx = body.boundingBox.maxPoint
    return mx.x * 10.0, mx.y * 10.0, mx.z * 10.0


def _outer_vector_bbox_mm(board: dict):
    """2D bounding box of outerVector in profile (u,v) mm."""
    ov = board.get("outerVector")
    if not isinstance(ov, list) or not ov:
        return None
    us, vs = [], []
    for p in ov:
        if isinstance(p, (list, tuple)) and len(p) >= 2:
            if isinstance(p[0], (int, float)) and isinstance(p[1], (int, float)):
                us.append(float(p[0]))
                vs.append(float(p[1]))
    if not us:
        return None
    mu, ma_u = min(us), max(us)
    mv, ma_v = min(vs), max(vs)
    return {
        "minU": mu,
        "maxU": ma_u,
        "minV": mv,
        "maxV": ma_v,
        "widthU": ma_u - mu,
        "heightV": ma_v - mv,
    }


def _board_thickness_mm(board: dict) -> float:
    t = board.get("thickness")
    if t is None:
        return 15.0
    try:
        return float(t)
    except Exception:
        return 15.0


def _expected_size_mm(board: dict, ov_bbox):
    """Nominal prism edge lengths: two profile spans + extrusion thickness (mm)."""
    th = _board_thickness_mm(board)
    plane = board.get("profilePlane") or "XY"
    if not isinstance(ov_bbox, dict):
        return {
            "profilePlane": plane,
            "profileSpanUMm": None,
            "profileSpanVMm": None,
            "extrudeThicknessMm": th,
            "sortedExtentsMm": None,
        }
    wu = float(ov_bbox.get("widthU", 0))
    hv = float(ov_bbox.get("heightV", 0))
    se = sorted([wu, hv, th])
    return {
        "profilePlane": plane,
        "profileSpanUMm": wu,
        "profileSpanVMm": hv,
        "extrudeThicknessMm": th,
        "sortedExtentsMm": se,
    }


def _body_bbox_mm_dict(body: adsk.fusion.BRepBody):
    mn = _body_min_mm(body)
    mx = _body_max_mm(body)
    sx = mx[0] - mn[0]
    sy = mx[1] - mn[1]
    sz = mx[2] - mn[2]
    return {
        "minX": round(mn[0], 3),
        "minY": round(mn[1], 3),
        "minZ": round(mn[2], 3),
        "maxX": round(mx[0], 3),
        "maxY": round(mx[1], 3),
        "maxZ": round(mx[2], 3),
        "sizeX": round(sx, 3),
        "sizeY": round(sy, 3),
        "sizeZ": round(sz, 3),
        "sortedSizesMm": sorted([sx, sy, sz]),
    }


def _audit_dimension_status(expected_sorted, actual_sorted, tol_mm=2.0):
    if not expected_sorted or len(expected_sorted) != 3:
        return "unknown"
    if not actual_sorted or len(actual_sorted) != 3:
        return "unknown"
    for exp_e, act_e in zip(expected_sorted, actual_sorted):
        if abs(float(exp_e) - float(act_e)) > tol_mm:
            return "size_mismatch"
    return "ok"


def _move_body_by_mm(root_comp: adsk.fusion.Component, body: adsk.fusion.BRepBody, dx_mm: float, dy_mm: float, dz_mm: float):
    if abs(dx_mm) < 0.001 and abs(dy_mm) < 0.001 and abs(dz_mm) < 0.001:
        return
    bodies = adsk.core.ObjectCollection.create()
    bodies.add(body)
    transform = adsk.core.Matrix3D.create()
    transform.translation = adsk.core.Vector3D.create(
        _mm_to_cm(dx_mm), _mm_to_cm(dy_mm), _mm_to_cm(dz_mm)
    )
    move_input = root_comp.features.moveFeatures.createInput(bodies, transform)
    try:
        move_input.defineAsFreeMove(transform)
    except Exception:
        pass
    move_feat = root_comp.features.moveFeatures.add(move_input)
    move_feat.name = "{}MOVE_{}".format(FEATURE_PREFIX, body.name[:40])


def _move_body_min_corner_to(root_comp: adsk.fusion.Component, body: adsk.fusion.BRepBody, tx: float, ty: float, tz: float):
    mn = _body_min_mm(body)
    _move_body_by_mm(root_comp, body, tx - mn[0], ty - mn[1], tz - mn[2])


def generate_flat_board_bodies(board_plan: dict, spacing_mm: float = 100.0):
    """
    For each board in boardPlan['boards'] with a valid outerVector, sketch + extrude + lay out
    in preview rows by series (B / V / Zi / H / T / Other).

    spacing_mm is kept for API compatibility; column gap uses COL_GAP_MM.

    Returns dict:
      createdBodies, skippedBoards, errors, warnings, geometryBuild,
      boardPlanBoardCount, createdBoardIds, skippedBoardIds, bodyAudit,
      flatPreviewRows
    """
    report = {
        "createdBodies": 0,
        "skippedBoards": [],
        "errors": [],
        "warnings": [],
        "geometryBuild": GEOMETRY_BUILD,
        "boardPlanBoardCount": 0,
        "createdBoardIds": [],
        "skippedBoardIds": [],
        "bodyAudit": [],
        "flatPreviewRows": [],
    }

    _ = spacing_mm

    app = adsk.core.Application.get()
    if not app:
        report["errors"].append("No Fusion Application found")
        return report

    product = app.activeProduct
    if not product:
        report["errors"].append("No active Fusion product found")
        return report

    design = adsk.fusion.Design.cast(product)
    if not design:
        report["errors"].append("No active Fusion design found")
        return report

    root_comp = design.rootComponent
    if not root_comp:
        report["errors"].append("No root component found")
        return report

    report["warnings"].append("Using geometry build: " + GEOMETRY_BUILD)

    boards = board_plan.get("boards") or []
    if not isinstance(boards, list):
        report["errors"].append("boardPlan.boards is not a list.")
        return report

    report["boardPlanBoardCount"] = len(boards)

    run_suffix = random.randint(100000, 9999999)

    row_max_height = {name: 0.0 for name in FLAT_PREVIEW_ROW_ORDER}
    row_has_boards = {name: False for name in FLAT_PREVIEW_ROW_ORDER}
    for board in boards:
        if not isinstance(board, dict):
            continue
        if not _outer_vector_valid(board):
            continue
        rn = _flat_preview_row_name(board.get("series"))
        row_has_boards[rn] = True
        bb = _outer_vector_bbox_mm(board)
        if bb:
            row_max_height[rn] = max(row_max_height[rn], float(bb["heightV"]))

    row_y0 = {name: 0.0 for name in FLAT_PREVIEW_ROW_ORDER}
    y_acc = 0.0
    for rn in FLAT_PREVIEW_ROW_ORDER:
        if not row_has_boards[rn]:
            continue
        row_y0[rn] = y_acc
        h = float(row_max_height.get(rn, 0.0) or 0.0)
        gap = max(ROW_GAP_MM, h + ROW_GAP_PAD_MM)
        y_acc += h + gap

    row_cursor_x = {name: 0.0 for name in FLAT_PREVIEW_ROW_ORDER}
    row_col_index = {name: 0 for name in FLAT_PREVIEW_ROW_ORDER}
    row_board_ids = {name: [] for name in FLAT_PREVIEW_ROW_ORDER}

    for board in boards:
        if not isinstance(board, dict):
            report["skippedBoards"].append({"id": None, "reason": "not_a_dict"})
            report["skippedBoardIds"].append("(not_a_dict)")
            continue
        bid = board.get("id", "?")
        bid_str = str(bid) if bid is not None else "?"
        if not _outer_vector_valid(board):
            report["skippedBoards"].append({"id": bid, "reason": "missing_or_invalid_outerVector"})
            report["skippedBoardIds"].append(bid_str)
            continue

        row_name = _flat_preview_row_name(board.get("series"))
        row_index = _flat_preview_row_index(row_name)
        col_index = row_col_index[row_name]
        x_off = row_cursor_x[row_name]
        y_off = float(row_y0[row_name])
        z_off = 0.0

        ov_bbox = _outer_vector_bbox_mm(board)

        sketch, err = create_sketch_from_outer_vector(
            root_comp,
            board,
            (0.0, 0.0, 0.0),
            run_suffix,
            preview_mode=PREVIEW_MODE,
            profile_offset_u_mm=0.0,
            profile_offset_v_mm=0.0,
        )
        if not sketch:
            report["skippedBoards"].append({"id": bid, "reason": err or "sketch_failed"})
            report["skippedBoardIds"].append(bid_str)
            continue
        body, _feat = extrude_board_profile(root_comp, board, sketch, run_suffix)
        if not body:
            report["skippedBoards"].append({"id": bid, "reason": "extrude_failed"})
            report["skippedBoardIds"].append(bid_str)
            try:
                sketch.deleteMe()
            except Exception:
                pass
            continue

        try:
            _move_body_min_corner_to(root_comp, body, x_off, y_off, z_off)
            wu = float(ov_bbox.get("widthU", 0) or 0.0) if isinstance(ov_bbox, dict) else 0.0
            if wu <= 1e-6:
                mn = _body_min_mm(body)
                mx = _body_max_mm(body)
                wu = max(mx[0] - mn[0], 1e-6)
            row_cursor_x[row_name] = x_off + wu + COL_GAP_MM
        except Exception as ex:
            report["warnings"].append("{}: layout move failed: {}".format(bid, ex))

        row_col_index[row_name] += 1
        row_board_ids[row_name].append(bid_str)

        report["createdBodies"] += 1

        thickness_mm = _board_thickness_mm(board)
        expected_size = _expected_size_mm(board, ov_bbox)
        bbox_mm = _body_bbox_mm_dict(body)
        exp_sorted = expected_size.get("sortedExtentsMm")
        act_sorted = bbox_mm.get("sortedSizesMm")
        status = _audit_dimension_status(exp_sorted, act_sorted)

        report["bodyAudit"].append(
            {
                "boardId": bid_str,
                "boardName": str(board.get("name", "") or ""),
                "series": board.get("series"),
                "type": board.get("type"),
                "profilePlane": board.get("profilePlane"),
                "previewSketchPlane": "XY" if PREVIEW_MODE == "flat_xy" else (board.get("profilePlane") or "XY"),
                "previewMode": PREVIEW_MODE,
                "thickness": thickness_mm,
                "outerVectorBBox": ov_bbox,
                "expectedSizeMm": expected_size,
                "createdBodyName": str(body.name) if body.name else "",
                "createdBodyBoundingBoxMm": bbox_mm,
                "status": status,
                "previewPlacementMm": {"x": x_off, "y": y_off, "z": z_off},
                "rowName": row_name,
                "rowIndex": row_index,
                "colIndex": col_index,
            }
        )
        report["createdBoardIds"].append(bid_str)

    try:
        if app.activeViewport:
            app.activeViewport.refresh()
    except Exception:
        pass

    report["flatPreviewRows"] = [
        {"rowName": name, "boardIds": list(row_board_ids[name]), "count": len(row_board_ids[name])}
        for name in FLAT_PREVIEW_ROW_ORDER
        if row_board_ids[name]
    ]

    return report
