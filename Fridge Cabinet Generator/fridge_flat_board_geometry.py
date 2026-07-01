"""
Fusion v0.1: flat preview bodies from BoardPlan outerVector (no cabinet placement).

Sketch 2D coords follow solid_extrude_service convention:
  XY  -> sketch-local (u,v,0); on xYConstructionPlane → model X,Y; extrude +Z
  XZ  -> sketch-local (u,v,0); on xZConstructionPlane → model X,Z; extrude +Y
  YZ  -> sketch-local (u,v,0); on yZConstructionPlane → model Y,Z; extrude +X
flat_xy preview still maps every board onto root XY with offsets (special path).
All board dimensions are mm; Fusion internal units are cm.
"""

from __future__ import annotations

import math
import random
import re

import adsk.core
import adsk.fusion

ATTRIBUTE_GROUP = "FridgeCabinetGenerator"
FEATURE_PREFIX = "FCG_V01_"
GEOMETRY_BUILD = "flat-geometry-preview-017-front-panel-bodies"
MODEL_Z_OFFSET_MM = 10000.0

# Assembly 3D v0.3: T4/T5 + all HSet groups in board order; nothing skipped here (empty set).
ASSEMBLY_3D_SKIPPED_IDS = frozenset()

# Flat preview layout (readability only; does not change profile or extrusion depth).
FLAT_PREVIEW_ROW_ORDER = ("S", "B", "V", "Zi", "H", "T", "FP", "Other")
ROW_GAP_MM = 300.0
ROW_GAP_PAD_MM = 150.0
COL_GAP_MM = 100.0
PREVIEW_MODE = "flat_xy"


def _new_model_z_component(root_comp: adsk.fusion.Component, preview_mode: str, run_suffix: int):
    try:
        transform = adsk.core.Matrix3D.create()
        transform.translation = adsk.core.Vector3D.create(0, 0, _mm_to_cm(MODEL_Z_OFFSET_MM))
        occurrence = root_comp.occurrences.addNewComponent(transform)
        occurrence.name = "{}MODELZ_{}_{}".format(
            FEATURE_PREFIX,
            str(preview_mode or "preview"),
            int(run_suffix),
        )
        component = occurrence.component
        component.name = occurrence.name
        try:
            component.attributes.add(ATTRIBUTE_GROUP, "module", "fridge")
            component.attributes.add(ATTRIBUTE_GROUP, "previewMode", str(preview_mode or "preview"))
        except Exception:
            pass
        return component, occurrence.name, None
    except Exception as ex:
        return root_comp, None, "Could not create Fridge Z-offset component; using root component: {}".format(ex)

# assembly_3d only: temporary manual rigid orientation for V stiles (pivot = board local origin at model (0,0,0)
# after canonical flat_xy body). Order: rotate about local Y, then about local Z (world Z for 2nd move at origin).
ASSEMBLY_MANUAL_TRANSFORMS = {
    "V1": {
        "enabled": True,
        "rotateDeg": {"x": 0, "y": -90, "z": -90},
        "translateMm": {"x": 0, "y": 0, "z": 0},
    },
    "V2": {
        "enabled": True,
        "rotateDeg": {"x": 0, "y": -90, "z": -90},
        "translateMm": {"x": 0, "y": 0, "z": 0},
    },
    "V3": {
        "enabled": True,
        "rotateDeg": {"x": 0, "y": -90, "z": -90},
        "translateMm": {"x": 0, "y": 0, "z": 0},
    },
    "V4": {
        "enabled": True,
        "rotateDeg": {"x": 0, "y": -90, "z": -90},
        "translateMm": {"x": 0, "y": 0, "z": 0},
    },
    "V5": {
        "enabled": True,
        "rotateDeg": {"x": 0, "y": -90, "z": -90},
        "translateMm": {"x": 0, "y": 0, "z": 0},
    },
}


def _assembly_3d_v03_board_order(board_plan: dict) -> list:
    """Stable creation order: frame + T4/T5 + V + Zi + all HSet boards + avoidance tail if present."""
    boards = _boards_with_front_panels(board_plan)
    fixed = (
        "B1",
        "B2",
        "B3",
        "T1",
        "T2",
        "T3",
        "T4",
        "T5",
        "V1",
        "V2",
        "V3",
        "V4",
        "V5",
    )
    id_set = set()
    zi_ids = []
    h_ids = []
    for b in boards:
        if isinstance(b, dict) and b.get("id") is not None:
            id_set.add(str(b["id"]))
    for b in boards:
        if not isinstance(b, dict) or b.get("id") is None:
            continue
        sid = str(b["id"])
        if re.match(r"^Z\d+$", sid):
            zi_ids.append(sid)

    def _zi_key(zid: str) -> int:
        m = re.match(r"^Z(\d+)$", zid)
        return int(m.group(1)) if m else 0

    zi_ids.sort(key=_zi_key)
    for b in boards:
        if not isinstance(b, dict) or b.get("id") is None:
            continue
        sid = str(b["id"])
        if re.match(r"^HSet_.+_H(?:13|24|34)$", sid):
            h_ids.append(sid)
    h_ids.sort()
    tail = []
    if "AvoidanceFront" in id_set:
        tail.append("AvoidanceFront")
    if "AvoidanceTop" in id_set:
        tail.append("AvoidanceTop")
    prefix = []
    if "SidePanel" in id_set:
        prefix.append("SidePanel")
    fp_ids = []
    for b in boards:
        if not isinstance(b, dict) or b.get("id") is None:
            continue
        sid = str(b["id"])
        if sid.startswith("FP_"):
            fp_ids.append(sid)
    fp_ids.sort()
    return prefix + list(fixed) + zi_ids + h_ids + tail + fp_ids


def _flat_preview_row_name(series) -> str:
    if series is None:
        return "Other"
    s = str(series).strip()
    if not s:
        return "Other"
    su = s.upper()
    if su == "ZI":
        return "Zi"
    if su in ("B", "V", "H", "T", "S", "FP"):
        return su
    return "Other"


def _front_panel_to_board(panel: dict):
    if not isinstance(panel, dict):
        return None
    if panel.get("generatedAsNewBody") is False:
        return None
    try:
        width = float(panel.get("width"))
        height = float(panel.get("height"))
        thickness = float(panel.get("thickness"))
        x0 = float(panel.get("x0"))
        y0 = float(panel.get("y0"))
        z0 = float(panel.get("z0"))
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0 or thickness <= 0:
        return None
    pid = str(panel.get("id") or "FP")
    return {
        "id": pid,
        "name": "Front Panel {}".format(panel.get("sectionId") or pid),
        "series": "FP",
        "type": "front_panel",
        "thickness": thickness,
        "profilePlane": "XZ",
        "outerVector": [[0, 0], [width, 0], [width, height], [0, height], [0, 0]],
        "holes": [],
        "grooves": [],
        "source": {"frontPanel": panel},
        "placement": {
            "series": "FP",
            "id": pid,
            "sectionId": panel.get("sectionId"),
            "resolvedType": panel.get("resolvedType"),
            "x0": x0,
            "y0": y0,
            "z0": z0,
            "widthX": width,
            "heightZ": height,
            "thicknessY": thickness,
            "assembly": {
                "boardId": pid,
                "mode": "front_panel_assembly_v0_1",
                "originMm": {"x": x0, "y": y0, "z": z0},
                "orientation": {
                    "profilePlane": "XZ",
                    "thicknessAxis": "-Y",
                    "profileAxisU": "+X",
                    "profileAxisV": "+Z",
                },
                "notes": ["Fridge front panel body; hinge/lock cuts are applied in canonical flat frame before assembly transform."],
                "placementRuleUsed": "front_panel_metadata_v0_1",
            },
        },
        "notes": "Generated fridge front panel body from boardPlan.frontPanels.",
    }


def _boards_with_front_panels(board_plan: dict):
    boards = list(board_plan.get("boards") or [])
    front_panels = board_plan.get("frontPanels") or []
    for panel in front_panels:
        board = _front_panel_to_board(panel)
        if board:
            boards.append(board)
    return boards


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


def _expected_global_sizes_mm(profile_plane: str, ov_bbox: dict, thickness_mm: float):
    """
    Global axis-aligned extents after canonical XY (U,V,Z=thickness) + profilePlane remap.
    XY: sizeX=spanU, sizeY=spanV, sizeZ=thickness
    XZ: sizeX=spanU, sizeY=thickness, sizeZ=spanV
    YZ: sizeX=thickness, sizeY=spanU, sizeZ=spanV
    """
    wu = float(ov_bbox.get("widthU", 0) or 0.0)
    hv = float(ov_bbox.get("heightV", 0) or 0.0)
    t = float(thickness_mm)
    p = (profile_plane or "XY").upper()
    if p == "XZ":
        return {"sizeX": wu, "sizeY": t, "sizeZ": hv}
    if p == "YZ":
        return {"sizeX": t, "sizeY": wu, "sizeZ": hv}
    return {"sizeX": wu, "sizeY": hv, "sizeZ": t}


def _compute_assembly_geometry_ok_flag(report: dict) -> bool:
    """True when report has no errors and every assemblyBodyAudit row is ok, manual_orientation, or v0.1 skipped."""
    ok_statuses = frozenset({"ok", "skipped_v0_1_scope", "manual_orientation"})
    if report.get("errors"):
        return False
    rows = report.get("assemblyBodyAudit") or []
    return all(isinstance(r, dict) and r.get("status") in ok_statuses for r in rows)


def _assembly_audit_row_v2(
    bid: str,
    board: dict,
    origin_mm_dict,
    ov_bbox,
    thickness_mm: float,
    bbox_mm,
    status: str,
    manual_extra=None,
    placement_rule_used=None,
    profile_plane_override=None,
    assembly_audit_extra=None,
):
    """assembly_3d audit row: global axis sizes vs BoardPlan outerVector + thickness."""
    pp = board.get("profilePlane") if isinstance(board, dict) else None
    pp_exp = profile_plane_override if profile_plane_override else pp
    exp_g = None
    if isinstance(ov_bbox, dict):
        exp_g = _expected_global_sizes_mm(str(pp_exp or "XY"), ov_bbox, thickness_mm)
    created = None
    if isinstance(bbox_mm, dict):
        created = {
            "sizeX": bbox_mm.get("sizeX"),
            "sizeY": bbox_mm.get("sizeY"),
            "sizeZ": bbox_mm.get("sizeZ"),
        }
    row = {
        "boardId": bid,
        "profilePlane": pp,
        "originMm": origin_mm_dict,
        "expectedGlobalSizeMm": exp_g,
        "createdBodyBoundingBoxMm": created,
        "status": status,
        "placementRuleUsed": placement_rule_used,
        "manualTransformApplied": False,
        "manualRotateDeg": None,
        "manualTranslateMm": None,
        "pivotMode": None,
    }
    if isinstance(manual_extra, dict):
        row.update(manual_extra)
    if isinstance(assembly_audit_extra, dict):
        for _k, _v in assembly_audit_extra.items():
            if _v is not None:
                row[_k] = _v
    return row


def _audit_axis_sizes_ok(expected: dict, bbox_mm: dict, tol_mm: float = 3.0) -> bool:
    if not isinstance(expected, dict) or not isinstance(bbox_mm, dict):
        return False
    for k in ("sizeX", "sizeY", "sizeZ"):
        try:
            if abs(float(expected.get(k, 0)) - float(bbox_mm.get(k, 0))) > tol_mm:
                return False
        except (TypeError, ValueError):
            return False
    return True


def _orientation_matrix_for_profile_plane(profile_plane: str):
    """
    Maps canonical flat_xy body (Fusion +X=U, +Y=V, +Z=thickness) into cabinet axes per profilePlane.
    Uses setToAlignCoordinateSystems with right-handed target bases.
    """
    p = (profile_plane or "XY").upper()
    origin = adsk.core.Point3D.create(0.0, 0.0, 0.0)
    fx = adsk.core.Vector3D.create(1.0, 0.0, 0.0)
    fy = adsk.core.Vector3D.create(0.0, 1.0, 0.0)
    fz = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
    mat = adsk.core.Matrix3D.create()
    if p == "XY":
        mat.setToAlignCoordinateSystems(origin, fx, fy, fz, origin, fx, fy, fz)
        return mat
    if p == "XZ":
        # canonical X,Y,Z -> global X, Z, -Y (RH); matches (spanU, t, spanV) extents
        to_x = adsk.core.Vector3D.create(1.0, 0.0, 0.0)
        to_y = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
        to_z = adsk.core.Vector3D.create(0.0, -1.0, 0.0)
        mat.setToAlignCoordinateSystems(origin, fx, fy, fz, origin, to_x, to_y, to_z)
        return mat
    if p == "YZ":
        to_x = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
        to_y = adsk.core.Vector3D.create(1.0, 0.0, 0.0)
        to_z = adsk.core.Vector3D.create(0.0, 1.0, 0.0)
        mat.setToAlignCoordinateSystems(origin, fx, fy, fz, origin, to_x, to_y, to_z)
        return mat
    mat.setToAlignCoordinateSystems(origin, fx, fy, fz, origin, fx, fy, fz)
    return mat


def _move_body_rigid_transform(root_comp: adsk.fusion.Component, body: adsk.fusion.BRepBody, transform: adsk.core.Matrix3D):
    bodies = adsk.core.ObjectCollection.create()
    bodies.add(body)
    move_input = root_comp.features.moveFeatures.createInput(bodies, transform)
    try:
        move_input.defineAsFreeMove(transform)
    except Exception:
        pass
    move_feat = root_comp.features.moveFeatures.add(move_input)
    move_feat.name = "{}RIGID_{}".format(FEATURE_PREFIX, _sanitize_feature_token(str(body.name))[:40])


def _matrix_rotation_about_axis_at_point(axis: adsk.core.Vector3D, pivot_cm: adsk.core.Point3D, deg: float):
    """Right-hand rule rotation by deg (degrees) about axis through pivot (Fusion internal units = cm for point)."""
    m = adsk.core.Matrix3D.create()
    m.setToRotation(math.radians(float(deg)), axis, pivot_cm)
    return m


def _rotate_vector_about_world_y_deg(vx: float, vy: float, vz: float, deg: float):
    """Apply world +Y rotation (RH, deg in degrees) to vector (vx,vy,vz); used for intrinsic Z after Ry."""
    rad = math.radians(float(deg))
    c = math.cos(rad)
    s = math.sin(rad)
    return (c * vx + s * vz, vy, -s * vx + c * vz)


def _apply_side_panel_assembly_world_rotations(root_comp: adsk.fusion.Component, body: adsk.fusion.BRepBody):
    """
    SidePanel only, after _orientation_matrix_for_profile_plane("YZ"):
      1) +90° about world +Y (CCW viewed from +Y toward origin; RH +90°).
      2) +90° about world +Z (CCW viewed from +Z toward origin; RH +90°).
      3) +180° about world +X (RH; matches Fusion Move rotate about X).
      4) ±180° about world +Z (same rigid result as Fusion -180° about Z).
    Pivot: world origin (then bbox min → placement.assembly.originMm).
    """
    pivot_cm = adsk.core.Point3D.create(0.0, 0.0, 0.0)
    axis_y = adsk.core.Vector3D.create(0.0, 1.0, 0.0)
    axis_z = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
    axis_x = adsk.core.Vector3D.create(1.0, 0.0, 0.0)
    _move_body_rigid_transform(root_comp, body, _matrix_rotation_about_axis_at_point(axis_y, pivot_cm, 90.0))
    _move_body_rigid_transform(root_comp, body, _matrix_rotation_about_axis_at_point(axis_z, pivot_cm, 90.0))
    _move_body_rigid_transform(root_comp, body, _matrix_rotation_about_axis_at_point(axis_x, pivot_cm, 180.0))
    _move_body_rigid_transform(root_comp, body, _matrix_rotation_about_axis_at_point(axis_z, pivot_cm, 180.0))


def _apply_h13_h24_assembly_world_rotations(root_comp: adsk.fusion.Component, body: adsk.fusion.BRepBody):
    """
    H13 / H24 (all HSet groups): after _orientation_matrix_for_profile_plane("YZ"):
      1) +90° about world +Z (RH).
      2) +90° about world +X (RH).
    Pivot: world origin (then bbox min → placement.assembly.originMm).
    """
    pivot_cm = adsk.core.Point3D.create(0.0, 0.0, 0.0)
    axis_z = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
    axis_x = adsk.core.Vector3D.create(1.0, 0.0, 0.0)
    _move_body_rigid_transform(root_comp, body, _matrix_rotation_about_axis_at_point(axis_z, pivot_cm, 90.0))
    _move_body_rigid_transform(root_comp, body, _matrix_rotation_about_axis_at_point(axis_x, pivot_cm, 90.0))


def _apply_assembly_manual_v_orientation(root_comp: adsk.fusion.Component, body: adsk.fusion.BRepBody, cfg: dict):
    """
    Temporary assembly_3d override for V boards: pivot at board local origin = model origin after canonical
    flat_xy body (bbox min at 0,0,0 mm).

    Rotation order (intrinsic / body-fixed intent):
      A) rotate about world +Y by rotateDeg.y (typically -90°)
      B) rotate about the body's local +Z *after step A* — in world coords this is world +Y rotated by step A,
         i.e. rotate about axis R_y(rotateDeg.y) * (0,0,1), not world +Z (unless ydeg==0).

    Optional rotateDeg.x applies last about world +X (only if non-zero).
    translateMm from cfg is applied in model space after rotations (typically 0).
    """
    pivot_cm = adsk.core.Point3D.create(0.0, 0.0, 0.0)
    rd = cfg.get("rotateDeg") if isinstance(cfg.get("rotateDeg"), dict) else {}
    ydeg = float(rd.get("y", -90.0))
    zdeg = float(rd.get("z", -90.0))
    xdeg = float(rd.get("x", 0.0))
    axis_y = adsk.core.Vector3D.create(0.0, 1.0, 0.0)
    axis_x = adsk.core.Vector3D.create(1.0, 0.0, 0.0)

    if abs(ydeg) > 1e-9:
        _move_body_rigid_transform(root_comp, body, _matrix_rotation_about_axis_at_point(axis_y, pivot_cm, ydeg))

    if abs(zdeg) > 1e-9:
        zx, zy, zz = _rotate_vector_about_world_y_deg(0.0, 0.0, 1.0, ydeg)
        axis_z2 = adsk.core.Vector3D.create(zx, zy, zz)
        axis_z2.normalize()
        _move_body_rigid_transform(root_comp, body, _matrix_rotation_about_axis_at_point(axis_z2, pivot_cm, zdeg))

    if abs(xdeg) > 1e-9:
        _move_body_rigid_transform(root_comp, body, _matrix_rotation_about_axis_at_point(axis_x, pivot_cm, xdeg))

    tm = cfg.get("translateMm") if isinstance(cfg.get("translateMm"), dict) else {}
    try:
        tx = float(tm.get("x", 0) or 0)
        ty = float(tm.get("y", 0) or 0)
        tz = float(tm.get("z", 0) or 0)
    except (TypeError, ValueError):
        tx = ty = tz = 0.0
    _move_body_by_mm(root_comp, body, tx, ty, tz)


def _assembly_v_manual_config(board_id: str):
    if board_id is None:
        return None
    cfg = ASSEMBLY_MANUAL_TRANSFORMS.get(str(board_id))
    if isinstance(cfg, dict) and cfg.get("enabled"):
        return cfg
    return None


def _body_bbox_center_mm(body: adsk.fusion.BRepBody):
    mn = _body_min_mm(body)
    mx = _body_max_mm(body)
    return ((mn[0] + mx[0]) * 0.5, (mn[1] + mx[1]) * 0.5, (mn[2] + mx[2]) * 0.5)


def _assembly_board_flip_world_z_180(board_id: str, board: dict) -> bool:
    """Front/back correction: 180° about cabinet +Z through bbox center (assembly_3d only)."""
    bid = str(board_id).strip()
    if bid in ("V1", "V2", "V3", "V4", "V5", "B3", "T3"):
        return True
    if re.match(r"^Z\d+$", bid):
        typ = str(board.get("type") or "").lower()
        if typ == "zi_half":
            return True
        src = board.get("source") if isinstance(board.get("source"), dict) else {}
        if str(src.get("shape") or "").lower() == "half":
            return True
    return False


def _apply_assembly_flip_world_z_180_about_bbox_center(root_comp: adsk.fusion.Component, body: adsk.fusion.BRepBody):
    cx, cy, cz = _body_bbox_center_mm(body)
    pivot_cm = adsk.core.Point3D.create(_mm_to_cm(cx), _mm_to_cm(cy), _mm_to_cm(cz))
    axis_z = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
    _move_body_rigid_transform(root_comp, body, _matrix_rotation_about_axis_at_point(axis_z, pivot_cm, 180.0))


def _create_canonical_xy_body_at_origin(root_comp: adsk.fusion.Component, board: dict, run_suffix: int):
    """
    Build body in canonical local frame: outerVector U -> +X, V -> +Y, thickness -> +Z, profile min at origin.
    Returns (body, sketch, error_message).
    """
    if not _outer_vector_valid(board):
        return None, None, "invalid_outer_vector"
    ov_bbox = _outer_vector_bbox_mm(board)
    if not isinstance(ov_bbox, dict):
        return None, None, "no_bbox"
    mu = float(ov_bbox.get("minU", 0.0))
    mv = float(ov_bbox.get("minV", 0.0))
    sketch, err = create_sketch_from_outer_vector(
        root_comp,
        board,
        (0.0, 0.0, 0.0),
        run_suffix,
        preview_mode="flat_xy",
        profile_offset_u_mm=-mu,
        profile_offset_v_mm=-mv,
    )
    if not sketch:
        return None, None, err or "sketch_failed"
    body, _feat = extrude_board_profile(root_comp, board, sketch, run_suffix)
    if not body:
        try:
            sketch.deleteMe()
        except Exception:
            pass
        return None, None, "extrude_failed"
    try:
        _move_body_min_corner_to(root_comp, body, 0.0, 0.0, 0.0)
    except Exception:
        pass
    return body, sketch, None


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
        # Fusion: sketch on a construction plane uses sketch-local (x,y) with z=0 in sketch space.
        # outerVector U→sketch x, V→sketch y; the plane maps to global XY / XZ / YZ (see BoardPlan profilePlane).
        return adsk.core.Point3D.create(
            _mm_to_cm(float(u_mm)),
            _mm_to_cm(float(v_mm)),
            0.0,
        )

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


def _all_profiles(sketch: adsk.fusion.Sketch):
    try:
        count = sketch.profiles.count
    except Exception:
        count = 0
    if count <= 0:
        return None
    profiles = adsk.core.ObjectCollection.create()
    for i in range(count):
        try:
            profiles.add(sketch.profiles.item(i))
        except Exception:
            pass
    return profiles if profiles.count > 0 else None


def _front_panel_source(board: dict):
    src = board.get("source") if isinstance(board, dict) else None
    if not isinstance(src, dict):
        return None
    panel = src.get("frontPanel")
    return panel if isinstance(panel, dict) else None


def _cut_fp_lock_slot_canonical(
    root_comp: adsk.fusion.Component,
    body: adsk.fusion.BRepBody,
    board: dict,
    run_suffix: int,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
):
    panel = _front_panel_source(board)
    cutout = panel.get("lockCutout") if isinstance(panel, dict) and isinstance(panel.get("lockCutout"), dict) else None
    if not cutout:
        return []
    px0 = float(panel.get("x0") or 0.0)
    pz0 = float(panel.get("z0") or 0.0)
    thickness = max(0.1, _board_thickness_mm(board))
    try:
        x0 = float(cutout.get("x0")) - px0
        x1 = float(cutout.get("x1")) - px0
        z0 = float(cutout.get("z0")) - pz0
        z1 = float(cutout.get("z1")) - pz0
    except (TypeError, ValueError):
        return [{"id": cutout.get("id"), "kind": "lock_cutout", "status": "skipped", "reason": "invalid bounds"}]
    if x1 <= x0 or z1 <= z0:
        return [{"id": cutout.get("id"), "kind": "lock_cutout", "status": "skipped", "reason": "invalid bounds"}]
    radius = min((x1 - x0) / 2.0, (z1 - z0) / 2.0)
    cy = (z0 + z1) / 2.0
    sketch = root_comp.sketches.add(root_comp.xYConstructionPlane)
    sketch.name = "{}FP_LOCK_{}_{}".format(FEATURE_PREFIX, _sanitize_feature_token(str(board.get("id", "FP"))), int(run_suffix))
    lines = sketch.sketchCurves.sketchLines
    arcs = sketch.sketchCurves.sketchArcs
    ox = float(offset_x_mm)
    oy = float(offset_y_mm)
    top_left = adsk.core.Point3D.create(_mm_to_cm(x0 + radius + ox), _mm_to_cm(z1 + oy), 0)
    top_right = adsk.core.Point3D.create(_mm_to_cm(x1 - radius + ox), _mm_to_cm(z1 + oy), 0)
    right_center = adsk.core.Point3D.create(_mm_to_cm(x1 - radius + ox), _mm_to_cm(cy + oy), 0)
    bottom_right = adsk.core.Point3D.create(_mm_to_cm(x1 - radius + ox), _mm_to_cm(z0 + oy), 0)
    bottom_left = adsk.core.Point3D.create(_mm_to_cm(x0 + radius + ox), _mm_to_cm(z0 + oy), 0)
    left_center = adsk.core.Point3D.create(_mm_to_cm(x0 + radius + ox), _mm_to_cm(cy + oy), 0)
    lines.addByTwoPoints(top_left, top_right)
    arcs.addByCenterStartSweep(right_center, top_right, -math.pi)
    lines.addByTwoPoints(bottom_right, bottom_left)
    arcs.addByCenterStartSweep(left_center, bottom_left, -math.pi)
    profiles = _all_profiles(sketch)
    if profiles is None:
        return [{"id": cutout.get("id"), "kind": "lock_cutout", "status": "failed", "reason": "no closed profile"}]
    extrudes = root_comp.features.extrudeFeatures
    ext_input = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(_mm_to_cm(thickness)))
    try:
        participants = adsk.core.ObjectCollection.create()
        participants.add(body)
        ext_input.participantBodies = participants
    except Exception:
        pass
    try:
        feat = extrudes.add(ext_input)
        feat.name = "{}FP_LOCK_CUT_{}".format(FEATURE_PREFIX, _sanitize_feature_token(str(board.get("id", "FP"))))
    except Exception as ex:
        return [{"id": cutout.get("id"), "kind": "lock_cutout", "status": "failed", "reason": str(ex)}]
    return [{"id": cutout.get("id") or "{}_lock".format(board.get("id")), "kind": "lock_cutout", "status": "created", "depth": thickness, "shape": cutout.get("shape") or "rounded_slot"}]


def _cut_fp_hinge_cups_canonical(
    root_comp: adsk.fusion.Component,
    body: adsk.fusion.BRepBody,
    board: dict,
    run_suffix: int,
    offset_x_mm: float = 0.0,
    offset_y_mm: float = 0.0,
):
    panel = _front_panel_source(board)
    holes = panel.get("hingeHoles") if isinstance(panel, dict) and isinstance(panel.get("hingeHoles"), list) else []
    if not holes:
        return []
    px0 = float(panel.get("x0") or 0.0)
    pz0 = float(panel.get("z0") or 0.0)
    sketch = root_comp.sketches.add(root_comp.xYConstructionPlane)
    sketch.name = "{}FP_HINGE_{}_{}".format(FEATURE_PREFIX, _sanitize_feature_token(str(board.get("id", "FP"))), int(run_suffix))
    circles = sketch.sketchCurves.sketchCircles
    audits = []
    max_depth = 0.1
    for hole in holes:
        if not isinstance(hole, dict):
            continue
        try:
            cx = float(hole.get("centerX")) - px0
            cz = float(hole.get("centerZ")) - pz0
            diameter = float(hole.get("diameter") or 35.0)
            depth = min(_board_thickness_mm(board), max(0.1, float(hole.get("depth") or 12.5)))
        except (TypeError, ValueError):
            audits.append({"id": hole.get("id"), "kind": "hinge_cup", "status": "skipped", "reason": "invalid hinge cup"})
            continue
        circles.addByCenterRadius(
            adsk.core.Point3D.create(_mm_to_cm(cx + float(offset_x_mm)), _mm_to_cm(cz + float(offset_y_mm)), 0),
            _mm_to_cm(diameter / 2.0),
        )
        max_depth = max(max_depth, depth)
        audits.append({"id": hole.get("id"), "kind": "hinge_cup", "status": "drawn", "diameter": diameter, "depth": depth})
    profiles = _all_profiles(sketch)
    if profiles is None:
        return [{**audit, "status": "failed", "reason": "no closed profile"} for audit in audits]
    extrudes = root_comp.features.extrudeFeatures
    ext_input = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(_mm_to_cm(max_depth)))
    try:
        participants = adsk.core.ObjectCollection.create()
        participants.add(body)
        ext_input.participantBodies = participants
    except Exception:
        pass
    try:
        feat = extrudes.add(ext_input)
        feat.name = "{}FP_HINGE_CUT_{}".format(FEATURE_PREFIX, _sanitize_feature_token(str(board.get("id", "FP"))))
    except Exception as ex:
        return [{**audit, "status": "failed", "reason": str(ex)} for audit in audits]
    return [{**audit, "status": "created" if audit.get("status") == "drawn" else audit.get("status")} for audit in audits]


def _cut_front_panel_hardware_canonical(root_comp: adsk.fusion.Component, body: adsk.fusion.BRepBody, board: dict, run_suffix: int):
    if str(board.get("series") or "").upper() != "FP":
        return []
    panel = _front_panel_source(board)
    has_lock = isinstance(panel, dict) and isinstance(panel.get("lockCutout"), dict)
    has_hinges = isinstance(panel, dict) and isinstance(panel.get("hingeHoles"), list) and len(panel.get("hingeHoles") or []) > 0
    if not has_lock and not has_hinges:
        return []
    # Fusion cut participant scoping can be unreliable in complex timelines. Stage the FP body
    # far away while cutting so hinge/lock sketches cannot intersect structural bodies like B1.
    stage_x = 100000.0 + (int(run_suffix) % 1000) * 10.0
    stage_y = 100000.0 + (int(run_suffix) % 1000) * 10.0
    audits = []
    moved = False
    try:
        _move_body_by_mm(root_comp, body, stage_x, stage_y, 0.0)
        moved = True
        audits.extend(_cut_fp_lock_slot_canonical(root_comp, body, board, run_suffix, stage_x, stage_y))
        audits.extend(_cut_fp_hinge_cups_canonical(root_comp, body, board, run_suffix, stage_x, stage_y))
    finally:
        if moved:
            _move_body_by_mm(root_comp, body, -stage_x, -stage_y, 0.0)
    for audit in audits:
        audit["panelId"] = board.get("id")
        audit["stagedCut"] = True
    return audits


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


def _origin_mm_from_assembly(asm):
    if not isinstance(asm, dict):
        return None
    om = asm.get("originMm")
    if not isinstance(om, dict):
        return None
    try:
        return float(om.get("x", 0)), float(om.get("y", 0)), float(om.get("z", 0))
    except (TypeError, ValueError):
        return None


def _generate_assembly_3d_preview_bodies(board_plan: dict):
    """
    Cabinet-space preview (v0.1):
    1) Build each board as a canonical flat_xy solid at origin (Fusion +X=U, +Y=V, +Z=thickness).
    2) Non-V: rigid orientation from board.profilePlane, then optional 180° about world +Z through bbox center
       (V1–V5, B3, T3, Zi half only), then bbox min to placement.assembly.originMm.
    3) V1–V5: ASSEMBLY_MANUAL_TRANSFORMS (intrinsic Y then Z), then same optional world +Z 180° about bbox center,
       then bbox min to placement.assembly.originMm (same origin convention as JS).
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
        "assemblyBodyAudit": [],
        "frontPanelCutAudit": [],
        "flatPreviewRows": [],
        "previewMode": "assembly_3d",
    }

    try:
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

        boards = _boards_with_front_panels(board_plan)
        if not isinstance(boards, list):
            report["errors"].append("boardPlan.boards is not a list.")
            return report

        report["boardPlanBoardCount"] = len(boards)
        report["frontPanelCount"] = len(board_plan.get("frontPanels") or [])
        report["warnings"].append("Using geometry build: " + GEOMETRY_BUILD)
        report["warnings"].append("previewMode=assembly_3d (canonical local + axis remap + bbox placement).")
        report["warnings"].append(
            "assembly_3d: V1–V5 use ASSEMBLY_MANUAL_TRANSFORMS; V1–V5, B3, T3, Zi half also get +180° about world +Z through body bbox center (front/back)."
        )

        id_to_board = {}
        for b in boards:
            if isinstance(b, dict) and b.get("id") is not None:
                id_to_board[str(b["id"])] = b

        if ASSEMBLY_3D_SKIPPED_IDS:
            for bid in sorted(ASSEMBLY_3D_SKIPPED_IDS):
                if bid not in id_to_board:
                    continue
                brd = id_to_board[bid]
                report["skippedBoards"].append({"id": bid, "reason": "assembly_scope_skip"})
                report["skippedBoardIds"].append(bid)
                ov_bbox = _outer_vector_bbox_mm(brd) if _outer_vector_valid(brd) else None
                th = _board_thickness_mm(brd)
                report["assemblyBodyAudit"].append(
                    _assembly_audit_row_v2(
                        bid, brd, None, ov_bbox, th, None, "skipped_v0_1_scope", placement_rule_used=None
                    )
                )

        run_suffix = random.randint(100000, 9999999)
        root_comp, component_name, component_warning = _new_model_z_component(root_comp, "assembly_3d", run_suffix)
        report["modelZOffset"] = {"offsetMm": MODEL_Z_OFFSET_MM, "movedBodies": 0, "failedBodies": 0, "mode": "componentAtModelZ", "componentName": component_name}
        if component_warning:
            report["warnings"].append(component_warning)

        for bid in _assembly_3d_v03_board_order(board_plan):
            board = id_to_board.get(bid)
            if not board:
                continue

            placement = board.get("placement") or {}
            asm = placement.get("assembly")
            asm_extra = {}
            if isinstance(asm, dict):
                for _k in ("hSetGroupId", "hSetMember", "groupRole", "z0", "z1"):
                    if asm.get(_k) is not None:
                        asm_extra[_k] = asm.get(_k)
            pru = asm.get("placementRuleUsed") if isinstance(asm, dict) else None
            pp_override_audit = "XZ" if bid == "T5" else None
            origin = _origin_mm_from_assembly(asm) if isinstance(asm, dict) else None

            ov_bbox = _outer_vector_bbox_mm(board) if _outer_vector_valid(board) else None
            th_mm = _board_thickness_mm(board)

            if origin is None:
                report["skippedBoards"].append({"id": bid, "reason": "missing_assembly_placement"})
                report["assemblyBodyAudit"].append(
                    _assembly_audit_row_v2(
                        bid,
                        board,
                        None,
                        ov_bbox,
                        th_mm,
                        None,
                        "no_assembly_placement",
                        placement_rule_used=pru,
                        profile_plane_override=pp_override_audit,
                        assembly_audit_extra=asm_extra if asm_extra else None,
                    )
                )
                continue

            ox, oy, oz = origin

            if not _outer_vector_valid(board):
                report["skippedBoards"].append({"id": bid, "reason": "missing_or_invalid_outerVector"})
                report["assemblyBodyAudit"].append(
                    _assembly_audit_row_v2(
                        bid,
                        board,
                        {"x": ox, "y": oy, "z": oz},
                        ov_bbox,
                        th_mm,
                        None,
                        "missing_outer_vector",
                        placement_rule_used=pru,
                        profile_plane_override=pp_override_audit,
                        assembly_audit_extra=asm_extra if asm_extra else None,
                    )
                )
                continue

            body, _sketch, err = _create_canonical_xy_body_at_origin(root_comp, board, run_suffix)
            if not body:
                reason = err or "create_failed"
                report["skippedBoards"].append({"id": bid, "reason": reason})
                report["assemblyBodyAudit"].append(
                    _assembly_audit_row_v2(
                        bid,
                        board,
                        {"x": ox, "y": oy, "z": oz},
                        ov_bbox,
                        th_mm,
                        None,
                        reason,
                        placement_rule_used=pru,
                        profile_plane_override=pp_override_audit,
                        assembly_audit_extra=asm_extra if asm_extra else None,
                    )
                )
                continue

            try:
                report["frontPanelCutAudit"].extend(_cut_front_panel_hardware_canonical(root_comp, body, board, run_suffix))
            except Exception as ex:
                report["warnings"].append("{}: front panel hardware cuts failed: {}".format(bid, ex))

            pp_board = str(board.get("profilePlane") or "XY").strip().upper()
            if pp_board not in ("XY", "XZ", "YZ"):
                pp_board = "XY"
            orient_pp = "XZ" if bid == "T5" else pp_board

            orient_move_ok = True
            manual_extra = None
            audit_origin = {"x": ox, "y": oy, "z": oz}
            z_flip = _assembly_board_flip_world_z_180(bid, board)
            try:
                v_man = _assembly_v_manual_config(bid)
                if v_man is not None:
                    _apply_assembly_manual_v_orientation(root_comp, body, v_man)
                    if z_flip:
                        _apply_assembly_flip_world_z_180_about_bbox_center(root_comp, body)
                    _move_body_min_corner_to(root_comp, body, ox, oy, oz)
                    audit_origin = {"x": float(ox), "y": float(oy), "z": float(oz)}
                    rd = v_man.get("rotateDeg") if isinstance(v_man.get("rotateDeg"), dict) else {}
                    tm = v_man.get("translateMm") if isinstance(v_man.get("translateMm"), dict) else {}
                    manual_extra = {
                        "manualTransformApplied": True,
                        "manualRotateDeg": {
                            "x": float(rd.get("x", 0) or 0),
                            "y": float(rd.get("y", 0) or 0),
                            "z": float(rd.get("z", 0) or 0),
                        },
                        "manualTranslateMm": {
                            "x": float(tm.get("x", 0) or 0),
                            "y": float(tm.get("y", 0) or 0),
                            "z": float(tm.get("z", 0) or 0),
                        },
                        "pivotMode": "board_local_origin",
                    }
                    if z_flip:
                        manual_extra["assemblyWorldZFlip180Deg"] = 180.0
                        manual_extra["assemblyWorldZFlipPivot"] = "bbox_center_world_Z"
                else:
                    if orient_pp != "XY":
                        orient_mtx = _orientation_matrix_for_profile_plane(orient_pp)
                        _move_body_rigid_transform(root_comp, body, orient_mtx)
                    if bid == "SidePanel":
                        _apply_side_panel_assembly_world_rotations(root_comp, body)
                        manual_extra = {
                            "manualTransformApplied": True,
                            "sidePanelAssemblyWorldDeg": [
                                {"axis": "Y", "deg": 90.0, "sense": "ccw_viewed_from_plus_axis"},
                                {"axis": "Z", "deg": 90.0, "sense": "ccw_viewed_from_plus_axis"},
                                {"axis": "X", "deg": 180.0, "sense": "rh_flip_about_cabinet_x"},
                                {"axis": "Z", "deg": 180.0, "sense": "half_turn_fusion_equivalent_minus_180"},
                            ],
                            "pivotMode": "world_origin_after_profile_plane_orient",
                        }
                    elif re.match(r"^HSet_.+_H(?:13|24)$", bid):
                        _apply_h13_h24_assembly_world_rotations(root_comp, body)
                        manual_extra = {
                            "manualTransformApplied": True,
                            "h13h24AssemblyWorldDeg": [
                                {"axis": "Z", "deg": 90.0, "sense": "rh_about_world_plus_z"},
                                {"axis": "X", "deg": 90.0, "sense": "rh_about_world_plus_x"},
                            ],
                            "pivotMode": "world_origin_after_profile_plane_orient",
                        }
                    if z_flip:
                        _apply_assembly_flip_world_z_180_about_bbox_center(root_comp, body)
                    _move_body_min_corner_to(root_comp, body, ox, oy, oz)
                    if z_flip:
                        manual_extra = {
                            "manualTransformApplied": False,
                            "assemblyWorldZFlip180Deg": 180.0,
                            "assemblyWorldZFlipPivot": "bbox_center_world_Z",
                        }
            except Exception as ex:
                orient_move_ok = False
                report["warnings"].append("{}: assembly orient/move failed: {}".format(bid, ex))

            bbox_mm = _body_bbox_mm_dict(body)
            exp_sizes = (
                _expected_global_sizes_mm(orient_pp, ov_bbox, th_mm) if isinstance(ov_bbox, dict) else None
            )

            if not orient_move_ok:
                status = "orient_failed"
            elif manual_extra and manual_extra.get("manualTransformApplied"):
                status = "manual_orientation"
            elif not isinstance(bbox_mm, dict):
                status = "no_bbox"
            elif isinstance(exp_sizes, dict) and _audit_axis_sizes_ok(exp_sizes, bbox_mm):
                status = "ok"
            else:
                status = "axis_mismatch"

            report["assemblyBodyAudit"].append(
                _assembly_audit_row_v2(
                    bid,
                    board,
                    audit_origin,
                    ov_bbox,
                    th_mm,
                    bbox_mm,
                    status,
                    manual_extra=manual_extra,
                    placement_rule_used=pru,
                    profile_plane_override=pp_override_audit,
                    assembly_audit_extra=asm_extra if asm_extra else None,
                )
            )
            report["createdBodies"] += 1
            report["createdBoardIds"].append(bid)

        try:
            if app.activeViewport:
                app.activeViewport.refresh()
        except Exception:
            pass

        return report
    finally:
        report["assemblyGeometryOk"] = _compute_assembly_geometry_ok_flag(report)


def generate_flat_board_bodies(board_plan: dict, spacing_mm: float = 100.0, preview_mode=None):
    """
    For each board in boardPlan['boards'] with a valid outerVector, sketch + extrude + lay out
    in preview rows by series (B / V / Zi / H / T / Other).

    spacing_mm is kept for API compatibility; column gap uses COL_GAP_MM.

    Returns dict:
      createdBodies, skippedBoards, errors, warnings, geometryBuild,
      boardPlanBoardCount, createdBoardIds, skippedBoardIds, bodyAudit,
      flatPreviewRows, assemblyBodyAudit (empty for flat_xy), previewMode
    """
    pm = preview_mode if preview_mode is not None else PREVIEW_MODE
    if pm not in ("flat_xy", "assembly_3d"):
        pm = "flat_xy"
    if pm == "assembly_3d":
        return _generate_assembly_3d_preview_bodies(board_plan)

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
        "assemblyBodyAudit": [],
        "frontPanelCutAudit": [],
        "flatPreviewRows": [],
        "previewMode": "flat_xy",
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

    boards = _boards_with_front_panels(board_plan)
    if not isinstance(boards, list):
        report["errors"].append("boardPlan.boards is not a list.")
        return report

    report["boardPlanBoardCount"] = len(boards)
    report["frontPanelCount"] = len(board_plan.get("frontPanels") or [])

    run_suffix = random.randint(100000, 9999999)
    root_comp, component_name, component_warning = _new_model_z_component(root_comp, "flat_xy", run_suffix)
    report["modelZOffset"] = {"offsetMm": MODEL_Z_OFFSET_MM, "movedBodies": 0, "failedBodies": 0, "mode": "componentAtModelZ", "componentName": component_name}
    if component_warning:
        report["warnings"].append(component_warning)

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
            preview_mode=pm,
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
            report["frontPanelCutAudit"].extend(_cut_front_panel_hardware_canonical(root_comp, body, board, run_suffix))
        except Exception as ex:
            report["warnings"].append("{}: front panel hardware cuts failed: {}".format(bid, ex))

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
                "previewSketchPlane": "XY" if pm == "flat_xy" else (board.get("profilePlane") or "XY"),
                "previewMode": pm,
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
