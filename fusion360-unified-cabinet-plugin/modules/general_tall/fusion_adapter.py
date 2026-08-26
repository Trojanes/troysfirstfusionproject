import json
import math
import os
import re
import time
import copy

import adsk.core
import adsk.fusion

from geometry_ops import ATTRIBUTE_GROUP, MODEL_Z_OFFSET_MM, avoid_existing_at_origin, capture_position_snapshot, entity_board_id, is_module_artifact, mm_to_cm, move_body_by_mm, offset_matching_bodies_z_mm, sanitize_token

try:
    from nesting.workpiece_names import board_component_label, resolve_assembly_name
except Exception:
    import sys

    _nesting_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "nesting")
    )
    if _nesting_dir not in sys.path:
        sys.path.insert(0, _nesting_dir)
    from workpiece_names import board_component_label, resolve_assembly_name

try:
    from generator_default_attributes import (
        PANEL_ATTRIBUTE_GROUP,
        PANEL_ID_ATTR,
        PANEL_METADATA_ATTR,
        build_panel_metadata,
        extract_carcass_color_from_result,
        general_tall_board_semantics,
        overhead_board_semantics,
        write_panel_metadata_to_body,
    )
except Exception:
    import os
    import sys

    _panel_attr_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "panel_attributes"))
    if _panel_attr_dir not in sys.path:
        sys.path.insert(0, _panel_attr_dir)
    from generator_default_attributes import (
        PANEL_ATTRIBUTE_GROUP,
        PANEL_ID_ATTR,
        PANEL_METADATA_ATTR,
        build_panel_metadata,
        extract_carcass_color_from_result,
        general_tall_board_semantics,
        overhead_board_semantics,
        write_panel_metadata_to_body,
    )

ADAPTER_BUILD = "2026-08-20-u-shape-ohc-23"
U_SHAPE_CASE_FINGERPRINT_KEYS = (
    "totalWidth",
    "leftArmLength",
    "rightArmLength",
    "cabinetDepth",
    "cabinetHeight",
    "topClearanceHeight",
    "frontPanelThickness",
    "featureWidth",
    "clearance",
    "sideClearance",
    "geometryRevision",
)


def _plugin_root_dir():
    return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _u_shape_case_fingerprint(params):
    source = params if isinstance(params, dict) else {}
    values = []
    for key in U_SHAPE_CASE_FINGERPRINT_KEYS:
        value = source.get(key)
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        values.append([key, value])
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _matrix_transform_point_cm(matrix, x_cm, y_cm, z_cm):
    point = adsk.core.Point3D.create(float(x_cm), float(y_cm), float(z_cm))
    point.transformBy(matrix)
    return point.x, point.y, point.z


def _occurrence_bbox_in_parent_mm(occurrence):
    try:
        bb = occurrence.boundingBox
    except Exception:
        return None
    return {
        "x0": bb.minPoint.x * 10.0,
        "y0": bb.minPoint.y * 10.0,
        "z0": bb.minPoint.z * 10.0,
        "x1": bb.maxPoint.x * 10.0,
        "y1": bb.maxPoint.y * 10.0,
        "z1": bb.maxPoint.z * 10.0,
    }


def _world_bbox_corners_mm(local_bbox_mm, *matrices):
    corners = []
    for x in (local_bbox_mm["x0"] / 10.0, local_bbox_mm["x1"] / 10.0):
        for y in (local_bbox_mm["y0"] / 10.0, local_bbox_mm["y1"] / 10.0):
            for z in (local_bbox_mm["z0"] / 10.0, local_bbox_mm["z1"] / 10.0):
                px, py, pz = x, y, z
                for matrix in matrices:
                    if matrix is None:
                        continue
                    px, py, pz = _matrix_transform_point_cm(matrix, px, py, pz)
                corners.append((px * 10.0, py * 10.0, pz * 10.0))
    xs = [c[0] for c in corners]
    ys = [c[1] for c in corners]
    zs = [c[2] for c in corners]
    return {
        "x0": min(xs), "x1": max(xs),
        "y0": min(ys), "y1": max(ys),
        "z0": min(zs), "z1": max(zs),
    }


def _infer_u_run_id(name):
    upper = str(name or "").upper()
    if upper.endswith("_LEFT") or ".LEFT" in upper or upper.endswith("LEFT"):
        return "LEFT"
    if upper.endswith("_BACK") or ".BACK" in upper or upper.endswith("BACK"):
        return "BACK"
    if upper.endswith("_RIGHT") or ".RIGHT" in upper or upper.endswith("RIGHT"):
        return "RIGHT"
    return None


def _board_id_from_entity(entity):
    board_id = entity_board_id(entity)
    if board_id:
        return board_id
    try:
        name = str(getattr(entity, "name", "") or "")
    except Exception:
        name = ""
    upper = name.upper().replace("-", "_")
    for token in ("U_CONNECTOR_LEFT", "U_CONNECTOR_RIGHT", "D_CORNER_LEFT", "D_CORNER_RIGHT", "U_CONNECTOR", "T4", "T3", "T2", "T1", "BP"):
        if token in upper:
            return token
    # Names like UOH_LEFT_D1 / U Shape OHC-LEFT-D1 / ..._FP2 / ..._G0
    match = re.search(r"(?:^|_)((?:D|G|FP|S|L|R)\d+|BP|T[1-5]|U_CONNECTOR)(?:$|_)", upper)
    if match:
        return match.group(1)
    return None


def _bbox_center_size(bbox):
    return {
        "centerMm": {
            "x": (bbox["x0"] + bbox["x1"]) * 0.5,
            "y": (bbox["y0"] + bbox["y1"]) * 0.5,
            "z": (bbox["z0"] + bbox["z1"]) * 0.5,
        },
        "sizeMm": {
            "x": abs(bbox["x1"] - bbox["x0"]),
            "y": abs(bbox["y1"] - bbox["y0"]),
            "z": abs(bbox["z1"] - bbox["z0"]),
        },
    }


def audit_board_contact_contracts(boards, contracts, tol_mm=2.5):
    """Generic final-AABB face-contact audit reusable by assembly modules."""
    by_id = {str(row.get("id") or ""): row for row in boards or []}
    contacts = []
    findings = []

    def _overlap(a, b, axis):
        return max(
            0.0,
            min(float(a.get(axis + "1") or 0.0), float(b.get(axis + "1") or 0.0))
            - max(float(a.get(axis + "0") or 0.0), float(b.get(axis + "0") or 0.0)),
        )

    for contract in contracts or []:
        a = by_id.get(str(contract.get("a") or ""))
        b = by_id.get(str(contract.get("b") or ""))
        contract_id = str(contract.get("id") or "contact")
        if not a or not b:
            missing = contract.get("a") if not a else contract.get("b")
            findings.append({
                "severity": "error",
                "code": "contact_missing_board",
                "contractId": contract_id,
                "detail": "{}: missing {}".format(contract_id, missing),
            })
            continue
        abb = a.get("bboxMm") or a
        bbb = b.get("bboxMm") or b
        a_face = str(contract.get("aFace") or "")
        b_face = str(contract.get("bFace") or "")
        av = float(abb.get(a_face) or 0.0)
        bv = float(bbb.get(b_face) or 0.0)
        delta = av - bv
        overlap_axes = contract.get("overlapAxes") or []
        overlaps = {axis: _overlap(abb, bbb, axis) for axis in overlap_axes}
        face_ok = abs(delta) <= float(contract.get("toleranceMm") or tol_mm)
        overlap_ok = all(value > float(contract.get("toleranceMm") or tol_mm) for value in overlaps.values())
        contacts.append({
            "id": contract_id,
            "a": contract.get("a"),
            "b": contract.get("b"),
            "aFace": a_face,
            "bFace": b_face,
            "deltaMm": round(delta, 3),
            "overlapMm": overlaps,
            "ok": face_ok and overlap_ok,
        })
        if not face_ok:
            findings.append({
                "severity": "error",
                "code": "contact_gap",
                "contractId": contract_id,
                "detail": "{}: {}.{}={:.2f} vs {}.{}={:.2f} (delta={:.2f} mm)".format(
                    contract_id,
                    contract.get("a"), a_face, av,
                    contract.get("b"), b_face, bv,
                    delta,
                ),
            })
        elif not overlap_ok:
            findings.append({
                "severity": "error",
                "code": "contact_no_face_overlap",
                "contractId": contract_id,
                "detail": "{}: aligned faces have insufficient overlap {}".format(contract_id, overlaps),
            })
    return {
        "ok": not findings,
        "contacts": contacts,
        "findings": findings,
    }


def audit_u_shape_top_contacts(boards, tol_mm=2.5):
    """Semantic Style-1 T1/T2 corner contracts on final Fusion geometry."""
    contracts = [
        {"id": "left_t1_to_back_t2", "a": "LEFT.T1", "b": "BACK.T2", "aFace": "y0", "bFace": "y1", "overlapAxes": ["x", "z"]},
        {"id": "right_t1_to_back_t2", "a": "RIGHT.T1", "b": "BACK.T2", "aFace": "y0", "bFace": "y1", "overlapAxes": ["x", "z"]},
        {"id": "left_t2_to_back_t2", "a": "LEFT.T2", "b": "BACK.T2", "aFace": "y0", "bFace": "y1", "overlapAxes": ["x", "z"]},
        {"id": "right_t2_to_back_t2", "a": "RIGHT.T2", "b": "BACK.T2", "aFace": "y0", "bFace": "y1", "overlapAxes": ["x", "z"]},
        {"id": "back_t1_to_left_t1", "a": "BACK.T1", "b": "LEFT.T1", "aFace": "x0", "bFace": "x1", "overlapAxes": ["y", "z"]},
        {"id": "back_t1_to_right_t1", "a": "BACK.T1", "b": "RIGHT.T1", "aFace": "x1", "bFace": "x0", "overlapAxes": ["y", "z"]},
    ]
    return audit_board_contact_contracts(boards, contracts, tol_mm=tol_mm)


def audit_u_shape_clearance_fronts(boards, params=None, tol_mm=2.5):
    """Independent final-BRep contract for the two side clearance fixed fronts."""
    params = params if isinstance(params, dict) else {}
    by_id = {str(row.get("id") or ""): row for row in (boards or []) if isinstance(row, dict)}
    required = (
        "BACK.BP",
        "LEFT.FP_CLEARANCE_SIDE",
        "RIGHT.FP_CLEARANCE_SIDE",
        "BACK.FP_CLEARANCE_LEFT",
        "BACK.FP_CLEARANCE_RIGHT",
    )
    missing = [board_id for board_id in required if board_id not in by_id]
    if missing:
        finding = {
            "severity": "error",
            "code": "clearance_front_missing",
            "detail": "Missing clearance-front measure(s): {}.".format(", ".join(missing)),
        }
        return {"ok": False, "findings": [finding], "checks": []}

    def _bb(board_id):
        return by_id[board_id].get("bboxMm") or {}

    def _span(bb, axis):
        return abs(float(bb.get(axis + "1", 0.0)) - float(bb.get(axis + "0", 0.0)))

    def _close(a, b):
        return abs(float(a) - float(b)) <= float(tol_mm)

    def _overlap_1d(a0, a1, b0, b1):
        return max(0.0, min(float(a1), float(b1)) - max(float(a0), float(b0)))

    back_bp = _bb("BACK.BP")
    left = _bb("LEFT.FP_CLEARANCE_SIDE")
    right = _bb("RIGHT.FP_CLEARANCE_SIDE")
    back_left_corner = _bb("BACK.FP_CLEARANCE_RIGHT")
    back_right_corner = _bb("BACK.FP_CLEARANCE_LEFT")
    fpt = float(params.get("frontPanelThickness") or 16.0)
    side_clearance = float(params.get("sideClearance") or 50.0)
    cabinet_depth = float(params.get("cabinetDepth") or 400.0)
    expected_y0 = float(back_bp["y1"]) + fpt
    expected_y1 = expected_y0 + side_clearance
    expected = {
        "LEFT": {
            "x0": float(back_bp["x0"]) + cabinet_depth,
            "x1": float(back_bp["x0"]) + cabinet_depth + fpt,
            "y0": expected_y0,
            "y1": expected_y1,
        },
        "RIGHT": {
            "x0": float(back_bp["x1"]) - cabinet_depth - fpt,
            "x1": float(back_bp["x1"]) - cabinet_depth,
            "y0": expected_y0,
            "y1": expected_y1,
        },
    }
    findings = []
    checks = []
    for run_id, actual in (("LEFT", left), ("RIGHT", right)):
        target = expected[run_id]
        checks.append({"runId": run_id, "bboxMm": actual, "expectedBboxXYMm": target})
        size_ok = _close(_span(actual, "x"), fpt) and _close(_span(actual, "y"), side_clearance)
        pose_ok = all(_close(actual.get(key), target[key]) for key in ("x0", "x1", "y0", "y1"))
        if not size_ok:
            findings.append({
                "severity": "error",
                "code": "clearance_front_size",
                "runId": run_id,
                "detail": "{} side clearance front is {:.2f}×{:.2f}; expected {:.2f}×{:.2f} mm.".format(
                    run_id, _span(actual, "y"), _span(actual, "x"), side_clearance, fpt
                ),
            })
        if not pose_ok:
            findings.append({
                "severity": "error",
                "code": "clearance_front_pose",
                "runId": run_id,
                "detail": "{} side clearance front XY {} expected {}.".format(run_id, actual, target),
            })

    for run_id, side_bb, back_bb in (
        ("LEFT", left, back_left_corner),
        ("RIGHT", right, back_right_corner),
    ):
        x_overlap = _overlap_1d(side_bb["x0"], side_bb["x1"], back_bb["x0"], back_bb["x1"])
        y_overlap = _overlap_1d(side_bb["y0"], side_bb["y1"], back_bb["y0"], back_bb["y1"])
        face_touch = _close(side_bb["y0"], back_bb["y1"]) and x_overlap > tol_mm
        if not face_touch or y_overlap > tol_mm:
            findings.append({
                "severity": "error",
                "code": "clearance_front_joint",
                "runId": run_id,
                "detail": "{} side/BACK clearance fronts must face-touch without volume overlap.".format(run_id),
            })

    for run_id, side_bb in (("LEFT", left), ("RIGHT", right)):
        for row in boards or []:
            if str(row.get("runId") or "") != run_id:
                continue
            if not re.match(r"^FP\d+$", str(row.get("localBoardId") or "")):
                continue
            front_bb = row.get("bboxMm") or {}
            if (
                _overlap_1d(side_bb["x0"], side_bb["x1"], front_bb["x0"], front_bb["x1"]) > tol_mm
                and _overlap_1d(side_bb["y0"], side_bb["y1"], front_bb["y0"], front_bb["y1"]) > tol_mm
            ):
                findings.append({
                    "severity": "error",
                    "code": "clearance_front_function_overlap",
                    "runId": run_id,
                    "detail": "{} side clearance front overlaps {}.".format(run_id, row.get("id")),
                })
                break
    return {"ok": not findings, "checks": checks, "findings": findings}


def audit_u_shape_corner_ownership(boards, params=None, tol_mm=2.5):
    """Final-world contract: BACK owns both depth×depth corner cells."""
    params = params if isinstance(params, dict) else {}
    by_id = {str(row.get("id") or ""): row for row in (boards or []) if isinstance(row, dict)}
    required = ("LEFT.BP", "BACK.BP", "RIGHT.BP")
    missing = [board_id for board_id in required if board_id not in by_id]
    if missing:
        finding = {
            "severity": "error",
            "code": "back_corner_ownership",
            "detail": "Corner ownership audit missing {}.".format(", ".join(missing)),
        }
        return {"ok": False, "checks": [], "findings": [finding]}

    left = by_id["LEFT.BP"].get("bboxMm") or {}
    back = by_id["BACK.BP"].get("bboxMm") or {}
    right = by_id["RIGHT.BP"].get("bboxMm") or {}
    depth = float(params.get("cabinetDepth") or 400.0)
    total_width = float(params.get("totalWidth") or (float(back["x1"]) - float(back["x0"])))
    left_length = float(params.get("leftArmLength") or 0.0)
    right_length = float(params.get("rightArmLength") or 0.0)

    def _close(a, b):
        return abs(float(a) - float(b)) <= float(tol_mm)

    def _overlap_volume(a, b):
        return (
            max(0.0, min(float(a["x1"]), float(b["x1"])) - max(float(a["x0"]), float(b["x0"])))
            * max(0.0, min(float(a["y1"]), float(b["y1"])) - max(float(a["y0"]), float(b["y0"])))
            * max(0.0, min(float(a["z1"]), float(b["z1"])) - max(float(a["z0"]), float(b["z0"])))
        )

    ox = float(back["x0"])
    oy = float(back["y0"])
    checks = [{
        "backBboxMm": back,
        "leftBboxMm": left,
        "rightBboxMm": right,
        "expectedBackSizeMm": {"x": total_width, "y": depth},
        "expectedSideStartY": oy + depth,
    }]
    findings = []
    if not (
        _close(float(back["x1"]) - float(back["x0"]), total_width)
        and _close(float(back["y1"]) - float(back["y0"]), depth)
    ):
        findings.append({
            "severity": "error",
            "code": "back_corner_ownership",
            "detail": "BACK.BP must be full width {:.2f}×{:.2f} mm.".format(total_width, depth),
        })
    side_contracts = (
        ("LEFT", left, ox, ox + depth, left_length - depth),
        ("RIGHT", right, ox + total_width - depth, ox + total_width, right_length - depth),
    )
    for run_id, bb, x0, x1, expected_length in side_contracts:
        if not (_close(bb["x0"], x0) and _close(bb["x1"], x1) and _close(bb["y0"], oy + depth)):
            findings.append({
                "severity": "error",
                "code": "{}_corner_not_side".format(run_id.lower()),
                "runId": run_id,
                "detail": "{}.BP must start at y=BACK.BP.y1 and stay outside BACK-owned corner.".format(run_id),
            })
        if expected_length > 0 and not _close(float(bb["y1"]) - float(bb["y0"]), expected_length):
            findings.append({
                "severity": "error",
                "code": "{}_arm_back_seam".format(run_id.lower()),
                "runId": run_id,
                "detail": "{}.BP length {:.2f} expected {:.2f}.".format(
                    run_id, float(bb["y1"]) - float(bb["y0"]), expected_length
                ),
            })
        if _overlap_volume(bb, back) > 1.0:
            findings.append({
                "severity": "error",
                "code": "corner_double_occupancy",
                "runId": run_id,
                "detail": "{}.BP positively overlaps BACK.BP in a corner.".format(run_id),
            })
    return {"ok": not findings, "checks": checks, "findings": findings}


def audit_u_shape_back_corner_closure(boards, params=None, tol_mm=2.5):
    """Corner closed by outer edge dividers + BACK connectors + side rear dividers (no D_CORNER)."""
    params = params if isinstance(params, dict) else {}
    by_id = {str(row.get("id") or ""): row for row in (boards or []) if isinstance(row, dict)}
    findings = []
    checks = []

    def _bb(board_id):
        row = by_id.get(board_id) or {}
        return row.get("bboxMm") or {}

    def _close(a, b):
        return abs(float(a) - float(b)) <= float(tol_mm)

    ownership = audit_u_shape_corner_ownership(boards, params=params, tol_mm=tol_mm)
    if not ownership.get("ok"):
        findings.extend(ownership.get("findings") or [])
        return {"ok": False, "checks": ownership.get("checks") or [], "findings": findings}

    back = _bb("BACK.BP")
    depth = float(params.get("cabinetDepth") or (float(back.get("y1", 0)) - float(back.get("y0", 0))))
    cpt = float(params.get("featureWidth") or 15.0)
    ox = float(back.get("x0", 0.0))
    oy = float(back.get("y0", 0.0))
    total_width = float(params.get("totalWidth") or (float(back.get("x1", 0)) - ox))

    back_dividers = sorted(
        [
            row for row in (boards or [])
            if isinstance(row, dict)
            and str(row.get("runId") or "") == "BACK"
            and str(row.get("localBoardId") or "").startswith("D")
            and str(row.get("localBoardId") or "").lstrip("D").isdigit()
        ],
        key=lambda row: float((row.get("bboxMm") or {}).get("x0") or 0.0),
    )
    if len(back_dividers) < 2:
        findings.append({
            "severity": "error",
            "code": "back_corner_closure",
            "detail": "BACK needs outer edge dividers to close both corners.",
        })
    else:
        left_d = back_dividers[0].get("bboxMm") or {}
        right_d = back_dividers[-1].get("bboxMm") or {}
        checks.append({"outerLeftDivider": left_d, "outerRightDivider": right_d})
        if not (_close(left_d.get("x0"), ox) and _close(left_d.get("x1"), ox + cpt)):
            findings.append({
                "severity": "error",
                "code": "back_corner_closure",
                "detail": "BACK left outer edge divider must sit at x=[{:.2f},{:.2f}].".format(ox, ox + cpt),
            })
        if not (_close(right_d.get("x0"), ox + total_width - cpt) and _close(right_d.get("x1"), ox + total_width)):
            findings.append({
                "severity": "error",
                "code": "back_corner_closure",
                "detail": "BACK right outer edge divider must sit at x=[{:.2f},{:.2f}].".format(
                    ox + total_width - cpt, ox + total_width
                ),
            })

    left_conn = _bb("BACK.U_CONNECTOR_LEFT")
    right_conn = _bb("BACK.U_CONNECTOR_RIGHT")
    if not left_conn or not right_conn:
        findings.append({
            "severity": "error",
            "code": "back_corner_closure",
            "detail": "Both BACK.U_CONNECTOR_LEFT and BACK.U_CONNECTOR_RIGHT are required for corner closure.",
        })
    else:
        checks.append({"leftConnector": left_conn, "rightConnector": right_conn})
        if not (
            _close(left_conn.get("x0"), ox + cpt)
            and _close(left_conn.get("x1"), ox + depth)
            and _close(left_conn.get("y1"), oy + depth)
        ):
            findings.append({
                "severity": "error",
                "code": "back_corner_closure",
                "detail": "BACK.U_CONNECTOR_LEFT must occupy the left D×D corner band.",
            })
        if not (
            _close(right_conn.get("x0"), ox + total_width - depth)
            and _close(right_conn.get("x1"), ox + total_width - cpt)
            and _close(right_conn.get("y1"), oy + depth)
        ):
            findings.append({
                "severity": "error",
                "code": "back_corner_closure",
                "detail": "BACK.U_CONNECTOR_RIGHT must occupy the right D×D corner band.",
            })

    side_rear = []
    for run_id in ("LEFT", "RIGHT"):
        candidates = sorted(
            [
                row for row in (boards or [])
                if isinstance(row, dict)
                and str(row.get("runId") or "") == run_id
                and str(row.get("localBoardId") or "").startswith("D")
            ],
            key=lambda row: float((row.get("bboxMm") or {}).get("y0") or 0.0),
        )
        if not candidates:
            findings.append({
                "severity": "error",
                "code": "back_corner_closure",
                "detail": "{} rear edge divider missing at y=D seam.".format(run_id),
            })
            continue
        rear = candidates[0].get("bboxMm") or {}
        side_rear.append(rear)
        if not _close(rear.get("y0"), oy + depth):
            findings.append({
                "severity": "error",
                "code": "back_corner_closure",
                "detail": "{}.{} must start at y=D for corner screw face.".format(
                    run_id, candidates[0].get("localBoardId")
                ),
            })
    checks.append({"sideRearDividers": side_rear})
    return {"ok": not findings, "checks": checks, "findings": findings}


def audit_u_shape_postprocess(run_summaries, params=None):
    """Require per-run T4/LED/connector postprocess counts for BACK-owned corners."""
    params = params if isinstance(params, dict) else {}
    findings = []
    checks = []
    runs = [row for row in (run_summaries or []) if isinstance(row, dict)]
    by_id = {str(row.get("runId") or "").upper(): row for row in runs}
    for run_id in ("LEFT", "BACK", "RIGHT"):
        row = by_id.get(run_id)
        if not row:
            findings.append({
                "severity": "error",
                "code": "postprocess_missing_run",
                "runId": run_id,
                "detail": "Postprocess audit missing {} run summary.".format(run_id),
            })
            continue
        post = row.get("overheadPostprocess") if isinstance(row.get("overheadPostprocess"), dict) else {}
        rotations = [item for item in (post.get("rotations") or []) if isinstance(item, dict) and item.get("status") == "created"]
        translations = [
            item for item in (post.get("topPanelTranslations") or [])
            if isinstance(item, dict) and item.get("status") == "created"
        ]
        led_cuts = [item for item in (post.get("ledGrooveCuts") or []) if isinstance(item, dict) and item.get("status") == "created"]
        bp_conn = [item for item in (post.get("uConnectorBpGrooves") or []) if isinstance(item, dict) and item.get("status") == "created"]
        t3_conn = [item for item in (post.get("uConnectorT3Grooves") or []) if isinstance(item, dict) and item.get("status") == "created"]
        check = {
            "runId": run_id,
            "t4Rotations": len(rotations),
            "topPanelTranslations": len(translations),
            "ledGrooveCuts": len(led_cuts),
            "uConnectorBpGrooves": len(bp_conn),
            "uConnectorT3Grooves": len(t3_conn),
        }
        checks.append(check)
        if len(rotations) < 1:
            findings.append({
                "severity": "error",
                "code": "postprocess_t4_rotation",
                "runId": run_id,
                "detail": "{} needs at least one T4 rotation in overhead postprocess.".format(run_id),
            })
        if run_id == "BACK":
            if len(bp_conn) < 2 or len(t3_conn) < 2:
                findings.append({
                    "severity": "error",
                    "code": "postprocess_connector_grooves",
                    "runId": run_id,
                    "detail": "BACK postprocess must create 2 BP + 2 T3 connector grooves (got {}/{}).".format(
                        len(bp_conn), len(t3_conn)
                    ),
                })
        elif len(bp_conn) or len(t3_conn):
            findings.append({
                "severity": "error",
                "code": "postprocess_connector_on_side",
                "runId": run_id,
                "detail": "{} must not own connector grooves after BACK migration.".format(run_id),
            })
        led_enabled = params.get("runLedGroove", {}).get(run_id) if isinstance(params.get("runLedGroove"), dict) else params.get("ledGroove")
        if led_enabled is not False and len(led_cuts) < 1:
            findings.append({
                "severity": "error",
                "code": "postprocess_led_cuts",
                "runId": run_id,
                "detail": "{} LED enabled but postprocess created no LED groove cuts.".format(run_id),
            })
    return {"ok": not findings, "checks": checks, "findings": findings}


def audit_u_shape_back_t3_profile(result, measured_boards=None, tol_mm=0.1):
    """Require every BACK divider notch to be present in generated T3/T4 outlines."""
    findings = []
    if not isinstance(result, dict):
        return {
            "ok": False,
            "findings": [{"severity": "error", "code": "back_t3_notch_expected_missing", "detail": "Missing generator result."}],
            "checks": [],
        }
    back_run = next(
        (run for run in (result.get("runs") or []) if isinstance(run, dict) and str(run.get("id") or "") == "BACK"),
        None,
    )
    run_result = back_run.get("result") if isinstance(back_run, dict) and isinstance(back_run.get("result"), dict) else {}
    boards = run_result.get("boards") or []
    t3 = next((board for board in boards if isinstance(board, dict) and board.get("id") == "T3"), None)
    t4 = next((board for board in boards if isinstance(board, dict) and board.get("id") == "T4"), None)
    notch_ranges = []
    for feature in run_result.get("features") or []:
        notch = feature.get("t3_notch") if isinstance(feature, dict) else None
        x_range = notch.get("x") if isinstance(notch, dict) else None
        if isinstance(x_range, list) and len(x_range) == 2:
            notch_ranges.append([float(x_range[0]), float(x_range[1])])

    def _profile_xs(board):
        return [
            float(point.get("x"))
            for point in (board.get("profileVector") or []) if isinstance(point, dict) and point.get("x") is not None
        ] if isinstance(board, dict) else []

    def _contains(xs, target):
        return any(abs(value - target) <= tol_mm for value in xs)

    t3_xs = _profile_xs(t3)
    t4_xs = _profile_xs(t4)
    for x0, x1 in notch_ranges:
        if not (_contains(t3_xs, x0) and _contains(t3_xs, x1)):
            findings.append({
                "severity": "error",
                "code": "back_t3_notch_profile",
                "detail": "BACK.T3 profile missing divider notch [{:.2f},{:.2f}].".format(x0, x1),
            })
        if not (_contains(t4_xs, x0) and _contains(t4_xs, x1)):
            findings.append({
                "severity": "error",
                "code": "back_t4_notch_profile",
                "detail": "BACK.T4 profile missing divider notch [{:.2f},{:.2f}].".format(x0, x1),
            })
    measured_ids = {str(row.get("id") or "") for row in (measured_boards or []) if isinstance(row, dict)}
    if measured_boards is not None and "BACK.T3" not in measured_ids:
        findings.append({"severity": "error", "code": "back_t3_missing_body", "detail": "Final BACK.T3 BRep body is missing."})
    return {
        "ok": bool(notch_ranges) and not findings,
        "checks": [{"notchRanges": notch_ranges, "t3ProfilePointCount": len(t3_xs), "t4ProfilePointCount": len(t4_xs)}],
        "findings": findings,
    }


def audit_u_shape_t4_geometry(boards, params=None, tol_mm=2.5):
    """Final BRep T4 must be a folded 50 mm strip, never a cabinet-depth slab."""
    params = params if isinstance(params, dict) else {}
    by_id = {str(row.get("id") or ""): row for row in (boards or []) if isinstance(row, dict)}
    feature_width = float(params.get("featureWidth") or 15.0)
    findings = []
    checks = []
    for run_id in ("LEFT", "BACK", "RIGHT"):
        row = by_id.get("{}.T4".format(run_id))
        if not row:
            findings.append({"severity": "error", "code": "t4_missing_body", "runId": run_id, "detail": "{}.T4 is missing.".format(run_id)})
            continue
        bb = row.get("bboxMm") or {}
        sizes = {
            "x": abs(float(bb["x1"]) - float(bb["x0"])),
            "y": abs(float(bb["y1"]) - float(bb["y0"])),
            "z": abs(float(bb["z1"]) - float(bb["z0"])),
        }
        checks.append({"runId": run_id, "sizeMm": sizes})
        thin_axis = sizes["x"] if run_id in ("LEFT", "RIGHT") else sizes["y"]
        if abs(sizes["z"] - 50.0) > tol_mm:
            findings.append({
                "severity": "error",
                "code": "t4_geometry_height",
                "runId": run_id,
                "detail": "{}.T4 final height {:.2f} mm expected 50 mm.".format(run_id, sizes["z"]),
            })
        if abs(thin_axis - feature_width) > tol_mm:
            findings.append({
                "severity": "error",
                "code": "t4_geometry_thickness",
                "runId": run_id,
                "detail": "{}.T4 folded thickness {:.2f} mm expected {:.2f}.".format(run_id, thin_axis, feature_width),
            })
    return {"ok": not findings, "checks": checks, "findings": findings}


def _expected_world_boards_from_result(result, origin_offset_mm=None):
    """Build expected final Adapter AABBs (+ assembly origin), not raw generator poses."""
    origin = origin_offset_mm if isinstance(origin_offset_mm, dict) else {}
    ox = float(origin.get("x") or 0.0)
    oy = float(origin.get("y") or 0.0)
    oz = float(origin.get("z") or 0.0)
    params = result.get("params") if isinstance(result, dict) and isinstance(result.get("params"), dict) else {}
    fg = float(params.get("featureWidth") or 15.0)
    top_clearance = float(params.get("topClearanceHeight") or 40.0)
    run_rotations = {}
    for run in (result.get("runs") or []) if isinstance(result, dict) else []:
        if not isinstance(run, dict):
            continue
        transform = run.get("transform") if isinstance(run.get("transform"), dict) else {}
        run_rotations[str(run.get("id") or "")] = float(transform.get("rotationDeg") or 0.0)
    rows = []
    world_boards = result.get("worldBoards") if isinstance(result, dict) else None
    if not isinstance(world_boards, list):
        return rows
    for board in world_boards:
        if not isinstance(board, dict):
            continue
        local_id = str(board.get("localBoardId") or board.get("id") or "")
        run_id = str(board.get("runId") or "")
        board_key = str(board.get("id") or "{}.{}".format(run_id, local_id))
        z0 = float(board.get("z0") or 0.0) + oz
        z1 = float(board.get("z1") or 0.0) + oz
        x_shift = 0.0
        y_shift = 0.0
        if local_id in ("T1", "T2"):
            # `_placement_offset_mm`: local +Y by TCH-1 before the run's Z pose.
            local_y_shift = top_clearance - 1.0
            rad = math.radians(run_rotations.get(run_id, 0.0))
            x_shift = -math.sin(rad) * local_y_shift
            y_shift = math.cos(rad) * local_y_shift
        # Style-1 Fusion support shift: BP/T1/T2 move +FGw in Z.
        if local_id in ("BP", "T1", "T2"):
            z0 += fg
            z1 += fg
        bbox = {
            "x0": float(board.get("x0") or 0.0) + ox + x_shift,
            "x1": float(board.get("x1") or 0.0) + ox + x_shift,
            "y0": float(board.get("y0") or 0.0) + oy + y_shift,
            "y1": float(board.get("y1") or 0.0) + oy + y_shift,
            "z0": z0,
            "z1": z1,
        }
        # Side clearance fronts require final XY certification; ignore only the
        # known global FP Z postprocess offset.
        # T1/T2 keep XY from generator (only Z shifts) — full AABB after Z bake.
        if local_id == "FP_CLEARANCE_SIDE":
            compare_mode = "xy_aabb"
        elif local_id in ("T3", "T4") or local_id.startswith("FP"):
            compare_mode = "height_band"
        else:
            compare_mode = "aabb"
        row = {
            "id": board_key,
            "runId": run_id,
            "localBoardId": local_id,
            "bboxMm": bbox,
            "compareMode": compare_mode,
            **_bbox_center_size(bbox),
        }
        rows.append(row)
    return rows


def compare_u_shape_board_poses(expected_boards, measured_boards, tol_mm=2.5, cabinet_height_mm=400.0):
    """Math pose audit: expected generator AABB vs Fusion-measured world AABB."""
    findings = []
    measured_by_id = {}
    for row in measured_boards or []:
        key = str(row.get("id") or "")
        if key:
            measured_by_id[key] = row
        # Also index local under run for attribute-only ids.
        run_id = str(row.get("runId") or "")
        local = str(row.get("localBoardId") or "")
        if run_id and local:
            measured_by_id.setdefault("{}.{}".format(run_id, local), row)

    matched = 0
    for expected in expected_boards or []:
        key = str(expected.get("id") or "")
        measured = measured_by_id.get(key)
        if measured is None:
            # Front panels / optional boards may be absent depending on zone type.
            if expected.get("compareMode") == "height_band":
                continue
            findings.append({
                "severity": "error",
                "code": "missing_board",
                "detail": "{} not found in Fusion measure".format(key),
            })
            continue
        matched += 1
        mode = expected.get("compareMode") or "aabb"
        e_bb = expected.get("bboxMm") or {}
        m_bb = measured.get("bboxMm") or {}
        if mode == "height_band":
            m_h = abs(float(m_bb.get("z1", 0.0)) - float(m_bb.get("z0", 0.0)))
            if m_h > float(cabinet_height_mm) + 120.0:
                findings.append({
                    "severity": "error",
                    "code": "postprocess_spike",
                    "detail": "{} measured Z span {:.2f} > cabinetHeight+120".format(key, m_h),
                })
            continue
        axis_rows = (
            (("x", "x0", "x1"), ("y", "y0", "y1"))
            if mode == "xy_aabb"
            else (("x", "x0", "x1"), ("y", "y0", "y1"), ("z", "z0", "z1"))
        )
        for axis, a0, a1 in axis_rows:
            for corner in (a0, a1):
                ev = float(e_bb.get(corner, 0.0))
                mv = float(m_bb.get(corner, 0.0))
                if abs(ev - mv) > tol_mm:
                    findings.append({
                        "severity": "error",
                        "code": "pose_mismatch",
                        "detail": "{} {} expected {:.2f} measured {:.2f} (tol={})".format(
                            key, corner, ev, mv, tol_mm
                        ),
                    })
                    break
            else:
                continue
            break
        # Size check (order-independent) as a second signal.
        e_size = expected.get("sizeMm") or _bbox_center_size(e_bb)["sizeMm"]
        m_size = measured.get("sizeMm") or _bbox_center_size(m_bb)["sizeMm"]
        size_axes = ("x", "y") if mode == "xy_aabb" else ("x", "y", "z")
        for axis in size_axes:
            if abs(float(e_size.get(axis, 0.0)) - float(m_size.get(axis, 0.0))) > tol_mm:
                findings.append({
                    "severity": "error",
                    "code": "size_mismatch",
                    "detail": "{} size.{} expected {:.2f} measured {:.2f}".format(
                        key, axis, float(e_size.get(axis, 0.0)), float(m_size.get(axis, 0.0))
                    ),
                })
    return {
        "ok": not any(row.get("severity") == "error" for row in findings),
        "matched": matched,
        "expectedCount": len(expected_boards or []),
        "measuredCount": len(measured_boards or []),
        "tolMm": tol_mm,
        "findings": findings,
    }


def write_u_shape_fusion_measure_log(payload, plugin_dir=None):
    """Persist Fusion AABB / spike measurements for the offline agent loop."""
    root = plugin_dir or _plugin_root_dir()
    log_dir = os.path.join(root, "logs")
    log_path = os.path.join(log_dir, "u_shape_ohc_fusion_measure.json")
    try:
        os.makedirs(log_dir, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False, default=str)
        return log_path
    except Exception as ex:
        return "write_failed:{}".format(ex)


def find_u_shape_assemblies(root_component):
    """Return [{component, occurrence, name, params, origin}] for module=u_shape_overhead."""
    rows = []
    if root_component is None:
        return rows
    try:
        occurrences = root_component.occurrences
    except Exception:
        return rows
    for index in range(occurrences.count):
        try:
            occurrence = occurrences.item(index)
            component = occurrence.component
            attrs = component.attributes
            module_attr = attrs.itemByName(ATTRIBUTE_GROUP, "module") if attrs else None
            if not module_attr or str(module_attr.value) != "u_shape_overhead":
                continue
            params = {}
            params_attr = attrs.itemByName(ATTRIBUTE_GROUP, "uShapeParams") if attrs else None
            if params_attr and params_attr.value:
                try:
                    params = json.loads(params_attr.value)
                except Exception:
                    params = {}
            revision_attr = attrs.itemByName(ATTRIBUTE_GROUP, "uShapeGeometryRevision") if attrs else None
            if isinstance(params, dict):
                params["geometryRevision"] = (
                    str(revision_attr.value)
                    if revision_attr and revision_attr.value
                    else "legacy_side_owns_corners"
                )
            origin = {}
            origin_attr = attrs.itemByName(ATTRIBUTE_GROUP, "uShapeOriginMm") if attrs else None
            if origin_attr and origin_attr.value:
                try:
                    origin = json.loads(origin_attr.value)
                except Exception:
                    origin = {}
            if not origin:
                try:
                    translation = occurrence.transform.translation
                    origin = {
                        "x": translation.x * 10.0,
                        "y": translation.y * 10.0,
                        "z": translation.z * 10.0,
                    }
                except Exception:
                    origin = {"x": 0.0, "y": 0.0, "z": 0.0}
            rows.append({
                "component": component,
                "occurrence": occurrence,
                "name": str(component.name or occurrence.name or "UOHC"),
                "params": params if isinstance(params, dict) else {},
                "origin": origin if isinstance(origin, dict) else {},
            })
        except Exception:
            continue
    return rows


def _bbox_volume_mm(bbox):
    if not bbox:
        return 0.0
    return abs(bbox["x1"] - bbox["x0"]) * abs(bbox["y1"] - bbox["y0"]) * abs(bbox["z1"] - bbox["z0"])


def _body_bbox_mm(body):
    try:
        body_bb = body.boundingBox
    except Exception:
        return None
    return {
        "x0": body_bb.minPoint.x * 10.0,
        "y0": body_bb.minPoint.y * 10.0,
        "z0": body_bb.minPoint.z * 10.0,
        "x1": body_bb.maxPoint.x * 10.0,
        "y1": body_bb.maxPoint.y * 10.0,
        "z1": body_bb.maxPoint.z * 10.0,
    }


def _brep_face_bbox_mm(face):
    try:
        bb = face.boundingBox
    except Exception:
        return None
    return {
        "x0": bb.minPoint.x * 10.0,
        "y0": bb.minPoint.y * 10.0,
        "z0": bb.minPoint.z * 10.0,
        "x1": bb.maxPoint.x * 10.0,
        "y1": bb.maxPoint.y * 10.0,
        "z1": bb.maxPoint.z * 10.0,
    }


def _union_bboxes_mm(boxes):
    boxes = [row for row in (boxes or []) if isinstance(row, dict)]
    if not boxes:
        return None
    return {
        "x0": min(row["x0"] for row in boxes),
        "y0": min(row["y0"] for row in boxes),
        "z0": min(row["z0"] for row in boxes),
        "x1": max(row["x1"] for row in boxes),
        "y1": max(row["y1"] for row in boxes),
        "z1": max(row["z1"] for row in boxes),
    }


def _led_segment_label_from_feature_name(name):
    token = str(name or "").lower()
    for label in ("main", "branch1", "branch2"):
        if token.endswith("_{}".format(label)):
            return label
    return None


def _measure_t3_led_cut_features(component, run_id, child_matrix=None, run_matrix=None, parent_matrix=None):
    """Measure actual BRep floor faces produced by named T3 LED cuts.

    Names identify segments only. Endpoint/depth values come from resulting
    end faces after body MoveFeatures, not from input groove rectangles.
    """
    rows = []
    try:
        extrudes = component.features.extrudeFeatures
        feature_count = extrudes.count
    except Exception:
        return rows
    for feature_index in range(feature_count):
        try:
            feature = extrudes.item(feature_index)
            feature_name = str(feature.name or "")
        except Exception:
            continue
        if not feature_name.upper().startswith("OH_T3_LED_CUT_"):
            continue
        label = _led_segment_label_from_feature_name(feature_name) or "unknown"
        feature_token = feature_name[len("OH_T3_LED_CUT_"):]
        feature_id = (
            feature_token[:-(len(label) + 1)]
            if label != "unknown" and feature_token.lower().endswith("_{}".format(label))
            else feature_token
        )
        face_boxes = []
        floor_area_mm2 = 0.0
        try:
            end_faces = feature.endFaces
            for face_index in range(end_faces.count):
                face = end_faces.item(face_index)
                local = _brep_face_bbox_mm(face)
                if local:
                    face_boxes.append(local)
                try:
                    floor_area_mm2 += float(face.area) * 100.0
                except Exception:
                    pass
        except Exception:
            pass
        if not face_boxes:
            # Fusion may drop `endFaces` references after downstream body MoveFeatures.
            # `feature.faces` still exposes the resulting planar groove floor; reject
            # vertical walls by requiring near-zero Z span and positive XY area.
            try:
                feature_faces = feature.faces
                for face_index in range(feature_faces.count):
                    face = feature_faces.item(face_index)
                    local = _brep_face_bbox_mm(face)
                    if not local:
                        continue
                    z_span = abs(float(local["z1"]) - float(local["z0"]))
                    xy_area = abs(float(local["x1"]) - float(local["x0"])) * abs(
                        float(local["y1"]) - float(local["y0"])
                    )
                    if z_span <= 0.1 and xy_area > 0.1:
                        face_boxes.append(local)
                        try:
                            floor_area_mm2 += float(face.area) * 100.0
                        except Exception:
                            pass
            except Exception:
                pass
        local_floor = _union_bboxes_mm(face_boxes)
        if not local_floor:
            rows.append({
                "runId": str(run_id),
                "segment": label,
                "featureId": feature_id,
                "featureName": feature_name,
                "status": "missing_end_face",
            })
            continue
        world_floor = _world_bbox_corners_mm(local_floor, child_matrix, run_matrix, parent_matrix)
        rows.append({
            "runId": str(run_id),
            "segment": label,
            "featureId": feature_id,
            "featureName": feature_name,
            "status": "measured",
            "source": "BRepExtrudeEndFace",
            "bboxMm": world_floor,
            "sizeMm": _bbox_center_size(world_floor)["sizeMm"],
            "floorAreaMm2": round(floor_area_mm2, 4),
        })
    return rows


def audit_u_shape_led_grooves(measurements, boards, result, tol_mm=2.0):
    """Audit final BRep LED cuts by feature and BACK-owned corner continuity."""
    findings = []
    checks = []
    if not isinstance(result, dict) or not isinstance(result.get("runs"), list):
        finding = {
            "severity": "error",
            "code": "led_expected_missing",
            "detail": "LED audit has no regenerated U Shape result; Fusion evidence cannot be certified.",
        }
        return {"ok": False, "measured": list(measurements or []), "checks": [], "findings": [finding]}

    expected_by_run = {}
    for run in result.get("runs") or []:
        if not isinstance(run, dict):
            continue
        run_id = str(run.get("id") or "").upper()
        run_result = run.get("result") if isinstance(run.get("result"), dict) else {}
        expected_by_run[run_id] = [
            row for row in (run_result.get("features") or [])
            if isinstance(row, dict) and row.get("type") == "t3_groove" and row.get("targetBoardId") == "T3"
        ]
    boards_by_id = {str(row.get("id") or "").upper(): row for row in (boards or []) if isinstance(row, dict)}

    def _error(code, detail, run_id, segment=None, feature_id=None):
        finding = {"severity": "error", "code": code, "runId": run_id, "detail": detail}
        if segment:
            finding["segment"] = segment
        if feature_id:
            finding["featureId"] = feature_id
        findings.append(finding)

    expected_keys = set()
    measured_main_by_run = {}
    for run_id in ("LEFT", "BACK", "RIGHT"):
        body_row = boards_by_id.get("{}.T3".format(run_id))
        body_bb = body_row.get("bboxMm") if isinstance(body_row, dict) else None
        features = expected_by_run.get(run_id) or []
        if features and not isinstance(body_bb, dict):
            _error("led_missing_cut", "{}.T3 body measure is missing.".format(run_id), run_id)
            continue
        for feature in features:
            feature_id = str(feature.get("id") or "T3_led_groove")
            feature_key = feature_id.lower()
            expected_keys.add((run_id, feature_key))
            feature_rows = [
                row for row in (measurements or [])
                if str(row.get("runId") or "").upper() == run_id
                and str(row.get("featureId") or "").lower() == feature_key
            ]
            required = []
            if isinstance(feature.get("main"), dict):
                required.append("main")
            required.extend(
                "branch{}".format(index + 1)
                for index, branch in enumerate(feature.get("branches") or [])
                if isinstance(branch, dict)
            )
            by_segment = {
                str(row.get("segment") or ""): row
                for row in feature_rows
                if row.get("status") == "measured" and isinstance(row.get("bboxMm"), dict)
            }
            missing = [segment for segment in required if segment not in by_segment]
            if missing:
                _error(
                    "led_missing_cut",
                    "{} {} missing final BRep segment(s): {}.".format(run_id, feature_id, ", ".join(missing)),
                    run_id,
                    feature_id=feature_id,
                )
                continue
            expected_depth = float(feature.get("depth") or 6.5)
            expected_width = float(feature.get("width") or 14.5)
            for segment in required:
                row = by_segment[segment]
                bb = row["bboxMm"]
                floor_z = (float(bb["z0"]) + float(bb["z1"])) / 2.0
                groove_depth = float(body_bb["z1"]) - floor_z
                size = _bbox_center_size(bb)["sizeMm"]
                planar_sizes = [float(size["x"]), float(size["y"])]
                width_value = min(value for value in planar_sizes if value > 0.05)
                row["floorZMm"] = round(floor_z, 4)
                row["floorDepthMm"] = round(groove_depth, 4)
                row["measuredWidthMm"] = round(width_value, 4)
                if float(row.get("floorAreaMm2") or 0.0) <= 0.1:
                    _error("led_wrong_face", "{} {} has no positive-area groove floor.".format(feature_id, segment), run_id, segment, feature_id)
                if abs(groove_depth - expected_depth) > tol_mm:
                    _error("led_wrong_face", "{} {} depth {:.2f} expected {:.2f}.".format(feature_id, segment, groove_depth, expected_depth), run_id, segment, feature_id)
                if abs(width_value - expected_width) > tol_mm:
                    _error("led_width", "{} {} width {:.2f} expected {:.2f}.".format(feature_id, segment, width_value, expected_width), run_id, segment, feature_id)

            role = str(feature.get("role") or "")
            if role == "u_corner_continuation":
                continuation_rows = [by_segment[name]["bboxMm"] for name in required]
                expected_span = float(result.get("params", {}).get("frontPanelThickness") or 16.0) \
                    + float(result.get("params", {}).get("featureWidth") or 15.0) + 10.0
                back_seam = float(body_bb["y1"])
                for bb in continuation_rows:
                    if abs(float(bb["y1"]) - back_seam) > tol_mm or abs((float(bb["y1"]) - float(bb["y0"])) - expected_span) > tol_mm:
                        _error(
                            "led_corner_continuation",
                            "BACK continuation Y [{:.2f},{:.2f}] must end at seam {:.2f} with span {:.2f}.".format(
                                float(bb["y0"]), float(bb["y1"]), back_seam, expected_span
                            ),
                            run_id,
                            feature_id=feature_id,
                        )
                checks.append({"runId": run_id, "featureId": feature_id, "role": role, "segmentCount": len(continuation_rows)})
                continue

            main_row = by_segment.get("main")
            if main_row:
                main_bb = main_row["bboxMm"]
                measured_main_by_run[run_id] = main_bb
                if run_id in ("LEFT", "RIGHT"):
                    rear_gap = float(main_bb["y0"]) - float(body_bb["y0"])
                    front_gap = float(body_bb["y1"]) - float(main_bb["y1"])
                    branch_centers = sorted(
                        (float(by_segment[name]["bboxMm"]["y0"]) + float(by_segment[name]["bboxMm"]["y1"])) / 2.0
                        for name in required if name.startswith("branch")
                    )
                    expected_centers = [float(body_bb["y0"]) + 80.0, float(body_bb["y1"]) - 80.0]
                    checks.append({"runId": run_id, "featureId": feature_id, "rearSeamGapMm": rear_gap, "frontLandMm": front_gap})
                    if abs(rear_gap) > tol_mm or abs(front_gap) > tol_mm:
                        _error("led_side_extent", "{} side LED must span seam to open tip.".format(run_id), run_id, "main", feature_id)
                    if len(branch_centers) != 2 or any(abs(a - b) > tol_mm for a, b in zip(branch_centers, expected_centers)):
                        _error("led_branch_offset", "{} branch centers {} expected {}.".format(run_id, branch_centers, expected_centers), run_id, feature_id=feature_id)
                else:
                    start_gap = float(main_bb["x0"]) - float(body_bb["x0"])
                    end_gap = float(body_bb["x1"]) - float(main_bb["x1"])
                    params_row = result.get("params") if isinstance(result.get("params"), dict) else {}
                    expected_inset = (
                        float(params_row.get("cabinetDepth") or 400.0)
                        - float(params_row.get("frontPanelThickness") or 16.0)
                        - float(params_row.get("featureWidth") or 15.0)
                        - (float(params_row.get("topClearanceHeight") or 40.0) - 1.0)
                        - 10.0
                    )
                    branch_centers = sorted(
                        (float(by_segment[name]["bboxMm"]["x0"]) + float(by_segment[name]["bboxMm"]["x1"])) / 2.0
                        for name in required if name.startswith("branch")
                    )
                    expected_centers = sorted(
                        float(body_bb["x1"]) - (
                            float(branch.get("x0", 0.0)) + float(branch.get("x1", 0.0))
                        ) / 2.0
                        for branch in (feature.get("branches") or []) if isinstance(branch, dict)
                    )
                    checks.append({
                        "runId": run_id,
                        "featureId": feature_id,
                        "startGapMm": start_gap,
                        "endGapMm": end_gap,
                        "expectedInsetMm": expected_inset,
                    })
                    if abs(start_gap - expected_inset) > tol_mm or abs(end_gap - expected_inset) > tol_mm:
                        _error("led_back_extent", "BACK LED must stop 10 mm past both side T2 faces.", run_id, "main", feature_id)
                    if len(branch_centers) != 2 or any(abs(a - b) > tol_mm for a, b in zip(branch_centers, expected_centers)):
                        _error("led_branch_offset", "BACK branch centers {} expected {}.".format(branch_centers, expected_centers), run_id, feature_id=feature_id)

    for row in measurements or []:
        key = (str(row.get("runId") or "").upper(), str(row.get("featureId") or "").lower())
        if key not in expected_keys:
            _error("led_extra_cut", "Unexpected measured LED feature {}.".format(row.get("featureName")), key[0], feature_id=row.get("featureId"))

    continuation_feature = next(
        (
            feature for feature in (expected_by_run.get("BACK") or [])
            if str(feature.get("role") or "") == "u_corner_continuation"
        ),
        None,
    )
    if continuation_feature:
        continuation_rows = [
            row for row in (measurements or [])
            if str(row.get("runId") or "").upper() == "BACK"
            and str(row.get("featureId") or "").lower() == str(continuation_feature.get("id") or "").lower()
            and isinstance(row.get("bboxMm"), dict)
        ]
        continuation_centers = sorted(
            (float(row["bboxMm"]["x0"]) + float(row["bboxMm"]["x1"])) / 2.0 for row in continuation_rows
        )
        side_centers = sorted(
            (float(bb["x0"]) + float(bb["x1"])) / 2.0
            for run_id, bb in measured_main_by_run.items() if run_id in ("LEFT", "RIGHT")
        )
        if len(continuation_centers) != len(side_centers) or any(
            abs(a - b) > tol_mm for a, b in zip(continuation_centers, side_centers)
        ):
            _error(
                "led_cross_run_gap",
                "BACK continuation X centers {} do not align with side mains {}.".format(continuation_centers, side_centers),
                "BACK",
                feature_id=continuation_feature.get("id"),
            )

    return {
        "ok": not any(row.get("severity") == "error" for row in findings),
        "toleranceMm": tol_mm,
        "measured": list(measurements or []),
        "checks": checks,
        "findings": findings,
    }


def _append_measured_board(measure, run_id, local_board_id, component_name, world_bb, board_index=None):
    if not world_bb or not local_board_id:
        return False
    if _bbox_volume_mm(world_bb) <= 1e-3:
        return False
    board_key = "{}.{}".format(run_id or "RUN", local_board_id)
    meta = _bbox_center_size(world_bb)
    height = meta["sizeMm"]["z"]
    row = {
        "id": board_key,
        "runId": run_id or "RUN",
        "localBoardId": local_board_id,
        "componentName": component_name,
        "bboxMm": world_bb,
        "heightMm": height,
        "spikeDetected": height > measure["spikeLimitMm"],
        **meta,
    }
    if board_index is not None and 0 <= board_index < len(measure["boards"]):
        measure["boards"][board_index] = row
    else:
        measure["boards"].append(row)
    if local_board_id == "T4":
        # Keep t4 list in sync with latest row.
        measure["t4Boards"] = [entry for entry in measure["t4Boards"] if entry.get("id") != board_key]
        measure["t4Boards"].append(row)
    if row["spikeDetected"]:
        measure["spikeDetected"] = True
        measure["ok"] = False
        measure["findings"].append(
            "{} height {:.1f} mm exceeds spike limit.".format(board_key, height)
        )
    return True


def measure_u_shape_assembly(
    parent_component,
    result=None,
    parent_occurrence=None,
    params=None,
    origin_offset_mm=None,
    tol_mm=2.5,
):
    """Measure every board's world XYZ AABB and math-compare to generator poses.

    Writes the basis for autonomous assembly checks — no viewport required.
    """
    resolved_params = {}
    expected_revision = None
    assembly_revision = params.get("geometryRevision") if isinstance(params, dict) else None
    if isinstance(result, dict) and isinstance(result.get("params"), dict):
        resolved_params.update(result.get("params"))
        meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        if meta.get("geometryRevision"):
            expected_revision = meta.get("geometryRevision")
            resolved_params["geometryRevision"] = expected_revision
    if isinstance(params, dict):
        resolved_params.update(params)
    cabinet_height = float(resolved_params.get("cabinetHeight") or 400.0)
    origin = origin_offset_mm if isinstance(origin_offset_mm, dict) else {}
    if not origin and parent_occurrence is not None:
        try:
            translation = parent_occurrence.transform.translation
            origin = {
                "x": translation.x * 10.0,
                "y": translation.y * 10.0,
                "z": translation.z * 10.0,
            }
        except Exception:
            origin = {"x": 0.0, "y": 0.0, "z": 0.0}
    measure = {
        "ok": True,
        "adapterBuild": ADAPTER_BUILD,
        "cabinetHeightMm": cabinet_height,
        "assemblyHeightMm": None,
        "spikeDetected": False,
        "spikeLimitMm": cabinet_height + 120.0,
        "originOffsetMm": origin or {"x": 0.0, "y": 0.0, "z": 0.0},
        "runs": [],
        "boards": [],
        "t4Boards": [],
        "ledGrooveMeasurements": [],
        "ledGrooveAudit": None,
        "clearanceFrontAudit": None,
        "cornerOwnershipAudit": None,
        "backCornerClosureAudit": None,
        "postprocessAudit": None,
        "backT3NotchAudit": None,
        "t4GeometryAudit": None,
        "expectedBoards": [],
        "poseCompare": None,
        "errors": [],
        "findings": [],
        "params": {
            "cabinetHeight": cabinet_height,
            "totalWidth": resolved_params.get("totalWidth"),
            "cabinetDepth": resolved_params.get("cabinetDepth"),
            "leftArmLength": resolved_params.get("leftArmLength"),
            "rightArmLength": resolved_params.get("rightArmLength"),
            "topClearanceHeight": resolved_params.get("topClearanceHeight"),
            "frontPanelThickness": resolved_params.get("frontPanelThickness"),
            "featureWidth": resolved_params.get("featureWidth"),
            "clearance": resolved_params.get("clearance"),
            "sideClearance": resolved_params.get("sideClearance"),
            "geometryRevision": resolved_params.get("geometryRevision"),
        },
    }
    if expected_revision and assembly_revision and str(expected_revision) != str(assembly_revision):
        detail = "Assembly geometry revision {} != expected {}.".format(assembly_revision, expected_revision)
        measure["ok"] = False
        measure["errors"].append(detail)
        measure["findings"].append({
            "severity": "error",
            "code": "geometry_revision_mismatch",
            "detail": detail,
        })
    measure["caseFingerprint"] = _u_shape_case_fingerprint(measure["params"])
    if parent_component is None:
        measure["ok"] = False
        measure["errors"].append("Missing parent assembly component.")
        return measure

    parent_matrix = None
    if parent_occurrence is not None:
        try:
            parent_matrix = parent_occurrence.transform
        except Exception:
            parent_matrix = None

    try:
        if parent_occurrence is not None:
            parent_bb = _occurrence_bbox_in_parent_mm(parent_occurrence)
            if parent_bb:
                measure["assemblyHeightMm"] = abs(parent_bb["z1"] - parent_bb["z0"])
                if measure["assemblyHeightMm"] > measure["spikeLimitMm"]:
                    measure["spikeDetected"] = True
                    measure["ok"] = False
                    measure["findings"].append(
                        "Assembly Z span {:.1f} mm exceeds spike limit {:.1f} mm.".format(
                            measure["assemblyHeightMm"], measure["spikeLimitMm"]
                        )
                    )
    except Exception as ex:
        measure["errors"].append("Assembly bbox failed: {}".format(ex))

    seen_board_keys = {}
    try:
        # Force bbox recompute — nested occurrence.boundingBox is often empty
        # until the design is computed after the final run pose snapshot.
        try:
            design = parent_component.parentDesign
            if design is not None:
                design.computeAll()
        except Exception:
            pass

        occurrences = parent_component.occurrences
        for index in range(occurrences.count):
            occurrence = occurrences.item(index)
            component = occurrence.component
            name = str(component.name or "")
            run_id = _infer_u_run_id(name)
            bb = _occurrence_bbox_in_parent_mm(occurrence)
            if bb is None:
                continue
            if parent_matrix is not None:
                bb = _world_bbox_corners_mm(bb, parent_matrix)
            height = abs(bb["z1"] - bb["z0"])
            row = {
                "runId": run_id or name,
                "componentName": name,
                "bboxMm": bb,
                "heightMm": height,
                "spikeDetected": height > measure["spikeLimitMm"],
                **_bbox_center_size(bb),
            }
            measure["runs"].append(row)
            if row["spikeDetected"]:
                measure["spikeDetected"] = True
                measure["ok"] = False
                measure["findings"].append(
                    "{} height {:.1f} mm looks like a T4 spike.".format(row["runId"], height)
                )

            run_matrix = occurrence.transform

            def _record_world_bb(local_board_id, component_name, world_bb):
                key = "{}.{}".format(run_id or "RUN", local_board_id)
                if _bbox_volume_mm(world_bb) <= 1e-3:
                    return
                if key in seen_board_keys:
                    existing_index = seen_board_keys[key]
                    existing = measure["boards"][existing_index]
                    if _bbox_volume_mm(existing.get("bboxMm")) >= _bbox_volume_mm(world_bb):
                        return
                    _append_measured_board(
                        measure, run_id, local_board_id, component_name, world_bb, board_index=existing_index
                    )
                    return
                if _append_measured_board(measure, run_id, local_board_id, component_name, world_bb):
                    seen_board_keys[key] = len(measure["boards"]) - 1

            # Prefer real BRep body boxes inside each board child component.
            # occurrence.boundingBox is frequently a zero-volume point for nested
            # board components right after transform — that previously locked T1/T2
            # (and every board) to size 0 and poisoned pose compare.
            try:
                child_occs = component.occurrences
                for child_index in range(child_occs.count):
                    child = child_occs.item(child_index)
                    child_comp = child.component
                    board_id = _board_id_from_entity(child_comp) or _board_id_from_entity(child)
                    if not board_id:
                        continue
                    child_matrix = child.transform
                    body_found = False
                    try:
                        bodies = child_comp.bRepBodies
                        for body_index in range(bodies.count):
                            local = _body_bbox_mm(bodies.item(body_index))
                            if not local or _bbox_volume_mm(local) <= 1e-3:
                                continue
                            world_bb = _world_bbox_corners_mm(local, child_matrix, run_matrix, parent_matrix)
                            _record_world_bb(board_id, str(child_comp.name or board_id), world_bb)
                            body_found = True
                    except Exception:
                        pass
                    if str(board_id).upper() == "T3":
                        measure["ledGrooveMeasurements"].extend(
                            _measure_t3_led_cut_features(
                                child_comp,
                                run_id,
                                child_matrix=child_matrix,
                                run_matrix=run_matrix,
                                parent_matrix=parent_matrix,
                            )
                        )
                    if body_found:
                        continue
                    child_bb = _occurrence_bbox_in_parent_mm(child)
                    if child_bb and _bbox_volume_mm(child_bb) > 1e-3:
                        world_bb = _world_bbox_corners_mm(child_bb, run_matrix, parent_matrix)
                        _record_world_bb(board_id, str(child_comp.name or board_id), world_bb)
            except Exception:
                pass

            try:
                bodies = component.bRepBodies
                for body_index in range(bodies.count):
                    body = bodies.item(body_index)
                    board_id = _board_id_from_entity(body)
                    if not board_id:
                        continue
                    local = _body_bbox_mm(body)
                    if not local:
                        continue
                    world_bb = _world_bbox_corners_mm(local, run_matrix, parent_matrix)
                    _record_world_bb(board_id, str(body.name or board_id), world_bb)
                    if str(board_id).upper() == "T3":
                        measure["ledGrooveMeasurements"].extend(
                            _measure_t3_led_cut_features(
                                component,
                                run_id,
                                run_matrix=run_matrix,
                                parent_matrix=parent_matrix,
                            )
                        )
            except Exception:
                pass
    except Exception as ex:
        measure["ok"] = False
        measure["errors"].append("Run measurement failed: {}".format(ex))

    if not measure["boards"]:
        measure["ok"] = False
        measure["errors"].append("No positive-volume board bboxes measured under U assembly.")

    footprint = audit_u_shape_footprint(measure.get("boards") or [], resolved_params)
    measure["footprint"] = footprint
    measure["findings"].extend(footprint.get("findings") or [])
    if not footprint.get("ok"):
        measure["ok"] = False
        measure["errors"].extend(footprint.get("errors") or [])

    corner_audit = audit_u_shape_corner_ownership(
        measure.get("boards") or [],
        resolved_params,
        tol_mm=tol_mm,
    )
    measure["cornerOwnershipAudit"] = corner_audit
    measure["findings"].extend(corner_audit.get("findings") or [])
    if not corner_audit.get("ok"):
        measure["ok"] = False
        measure["errors"].extend(
            [row.get("detail") for row in (corner_audit.get("findings") or []) if row.get("detail")]
        )

    corner_closure_audit = audit_u_shape_back_corner_closure(
        measure.get("boards") or [],
        resolved_params,
        tol_mm=tol_mm,
    )
    measure["backCornerClosureAudit"] = corner_closure_audit
    measure["findings"].extend(corner_closure_audit.get("findings") or [])
    if not corner_closure_audit.get("ok"):
        measure["ok"] = False
        measure["errors"].extend(
            [row.get("detail") for row in (corner_closure_audit.get("findings") or []) if row.get("detail")]
        )

    back_t3_notch_audit = audit_u_shape_back_t3_profile(
        result,
        measured_boards=measure.get("boards") or [],
    )
    measure["backT3NotchAudit"] = back_t3_notch_audit
    measure["findings"].extend(back_t3_notch_audit.get("findings") or [])
    if not back_t3_notch_audit.get("ok"):
        measure["ok"] = False
        measure["errors"].extend(
            [row.get("detail") for row in (back_t3_notch_audit.get("findings") or []) if row.get("detail")]
            or ["BACK.T3/T4 notch profile audit failed."]
        )

    t4_geometry_audit = audit_u_shape_t4_geometry(
        measure.get("boards") or [],
        resolved_params,
        tol_mm=tol_mm,
    )
    measure["t4GeometryAudit"] = t4_geometry_audit
    measure["findings"].extend(t4_geometry_audit.get("findings") or [])
    if not t4_geometry_audit.get("ok"):
        measure["ok"] = False
        measure["errors"].extend(
            [row.get("detail") for row in (t4_geometry_audit.get("findings") or []) if row.get("detail")]
        )

    contact_audit = audit_u_shape_top_contacts(measure.get("boards") or [], tol_mm=tol_mm)
    measure["contactAudit"] = contact_audit
    measure["findings"].extend(contact_audit.get("findings") or [])
    if not contact_audit.get("ok"):
        measure["ok"] = False
        measure["errors"].extend(
            [row.get("detail") for row in (contact_audit.get("findings") or []) if row.get("detail")]
        )

    clearance_front_audit = audit_u_shape_clearance_fronts(
        measure.get("boards") or [],
        resolved_params,
        tol_mm=tol_mm,
    )
    measure["clearanceFrontAudit"] = clearance_front_audit
    measure["findings"].extend(clearance_front_audit.get("findings") or [])
    if not clearance_front_audit.get("ok"):
        measure["ok"] = False
        measure["errors"].extend(
            [row.get("detail") for row in (clearance_front_audit.get("findings") or []) if row.get("detail")]
        )

    led_audit = audit_u_shape_led_grooves(
        measure.get("ledGrooveMeasurements") or [],
        measure.get("boards") or [],
        result,
        tol_mm=min(float(tol_mm), 2.0),
    )
    measure["ledGrooveAudit"] = led_audit
    measure["findings"].extend(led_audit.get("findings") or [])
    if not led_audit.get("ok"):
        measure["ok"] = False
        measure["errors"].extend(
            [row.get("detail") for row in (led_audit.get("findings") or []) if row.get("detail")]
        )

    # Math compare vs generator world poses when available.
    if isinstance(result, dict) and isinstance(result.get("worldBoards"), list):
        expected = _expected_world_boards_from_result(result, origin_offset_mm=measure["originOffsetMm"])
        measure["expectedBoards"] = expected
        pose = compare_u_shape_board_poses(
            expected,
            measure["boards"],
            tol_mm=tol_mm,
            cabinet_height_mm=cabinet_height,
        )
        measure["poseCompare"] = pose
        measure["findings"].extend(pose.get("findings") or [])
        if not pose.get("ok"):
            measure["ok"] = False

    # Self-check path: restore create-time postprocess audit from assembly attrs.
    if not isinstance(measure.get("postprocessAudit"), dict):
        try:
            attr = parent_component.attributes.itemByName(ATTRIBUTE_GROUP, "uShapePostprocessAudit")
            if attr and attr.value:
                stored = json.loads(attr.value)
                if isinstance(stored, dict) and isinstance(stored.get("ok"), bool):
                    measure["postprocessAudit"] = stored
                    if stored.get("ok") is False:
                        measure["ok"] = False
                        measure["findings"].extend(stored.get("findings") or [])
                        measure["errors"].extend(
                            [row.get("detail") for row in (stored.get("findings") or []) if row.get("detail")]
                        )
        except Exception:
            pass
    return measure


def audit_u_shape_footprint(boards, params=None):
    """Hard fail when measured BPs are still three parallel straight cabinets."""
    params = params if isinstance(params, dict) else {}
    depth = float(params.get("cabinetDepth") or 400.0)
    left_len = float(params.get("leftArmLength") or 0.0)
    right_len = float(params.get("rightArmLength") or 0.0)
    total_w = float(params.get("totalWidth") or 0.0)
    findings = []
    errors = []
    by_id = {str(row.get("id") or ""): row for row in boards or []}

    def _size(row):
        size = row.get("sizeMm") if isinstance(row, dict) else None
        if isinstance(size, dict):
            return float(size.get("x") or 0.0), float(size.get("y") or 0.0)
        bb = row.get("bboxMm") or {}
        return abs(float(bb.get("x1", 0.0)) - float(bb.get("x0", 0.0))), abs(
            float(bb.get("y1", 0.0)) - float(bb.get("y0", 0.0))
        )

    left = by_id.get("LEFT.BP")
    back = by_id.get("BACK.BP")
    right = by_id.get("RIGHT.BP")
    if not left or not back or not right:
        errors.append("U footprint audit missing LEFT/BACK/RIGHT BP measures.")
        return {"ok": False, "isUShape": False, "errors": errors, "findings": findings}

    lx, ly = _size(left)
    bx, by = _size(back)
    rx, ry = _size(right)

    # Straight/local pose: side BP long in X. U pose: side BP long in Y, depth in X.
    left_is_straight = lx > ly and lx > depth + 80
    right_is_straight = rx > ry and rx > depth + 80
    back_is_sideways = by > bx and by > depth + 80  # back wrongly rotated like a side

    if left_is_straight or right_is_straight:
        errors.append(
            "NOT_U_FOOTPRINT: side BP still long in X (LEFT {}x{}, RIGHT {}x{}). "
            "Runs look like parallel straight cabinets — occurrence Z pose did not apply.".format(
                round(lx, 1), round(ly, 1), round(rx, 1), round(ry, 1)
            )
        )
        findings.append({"severity": "error", "code": "not_u_footprint", "detail": errors[-1]})
    expected_left = max(0.0, left_len - depth)
    expected_right = max(0.0, right_len - depth)
    if left_len and not left_is_straight and abs(ly - expected_left) > 30:
        findings.append({
            "severity": "error",
            "code": "left_arm_length",
            "detail": "LEFT.BP Y span {:.1f} expected ~{:.1f}".format(ly, expected_left),
        })
    if right_len and not right_is_straight and abs(ry - expected_right) > 30:
        findings.append({
            "severity": "error",
            "code": "right_arm_length",
            "detail": "RIGHT.BP Y span {:.1f} expected ~{:.1f}".format(ry, expected_right),
        })
    if total_w and not left_is_straight and abs(bx - total_w) > 30:
        findings.append({
            "severity": "error",
            "code": "back_width",
            "detail": "BACK.BP X span {:.1f} expected ~{:.1f}".format(bx, total_w),
        })
    if back_is_sideways:
        errors.append("NOT_U_FOOTPRINT: BACK.BP is oriented like a side run.")
        findings.append({"severity": "error", "code": "back_wrong_orientation", "detail": errors[-1]})

    ok = not errors and not any(row.get("severity") == "error" for row in findings)
    return {
        "ok": ok,
        "isUShape": ok and not left_is_straight and not right_is_straight,
        "sizes": {
            "LEFT.BP": {"x": lx, "y": ly},
            "BACK.BP": {"x": bx, "y": by},
            "RIGHT.BP": {"x": rx, "y": ry},
        },
        "errors": errors,
        "findings": findings,
    }


def measure_and_log_u_shape_assemblies(
    root_component,
    source="runSelfCheck",
    cases=None,
    plugin_dir=None,
    expected_result=None,
    result_by_params=None,
):
    """Measure one or more U assemblies and write the Fusion measure log.

    expected_result: generator payload used for XYZ pose compare (create path).
    result_by_params: optional callable(params)->result for self-check regeneration.
    """
    measured_cases = list(cases or [])
    if not measured_cases:
        for row in find_u_shape_assemblies(root_component):
            result = None
            if callable(result_by_params) and row.get("params"):
                try:
                    result = result_by_params(row["params"])
                except Exception:
                    result = None
            if result is None:
                result = expected_result
            measure = measure_u_shape_assembly(
                row["component"],
                result=result,
                parent_occurrence=row["occurrence"],
                params=row.get("params"),
                origin_offset_mm=row.get("origin"),
            )
            measured_cases.append({
                "caseId": row["name"],
                "assemblyComponentName": row["name"],
                **measure,
            })
    findings = []
    errors = []
    ok = True
    not_u = False
    contact_failed = False
    led_groove_failed = False
    clearance_front_failed = False
    corner_ownership_failed = False
    back_t3_notch_failed = False
    t4_geometry_failed = False
    footprint_details = []
    for case in measured_cases:
        if case.get("ok") is False or case.get("spikeDetected"):
            ok = False
        pose = case.get("poseCompare") or {}
        if pose and pose.get("ok") is False:
            ok = False
        footprint = case.get("footprint") if isinstance(case.get("footprint"), dict) else {}
        if footprint.get("isUShape") is False or not footprint.get("ok", True):
            ok = False
            not_u = True
            for msg in footprint.get("errors") or ["NOT_U_FOOTPRINT"]:
                if msg not in errors:
                    errors.append(msg)
                footprint_details.append(msg)
        contact = case.get("contactAudit") if isinstance(case.get("contactAudit"), dict) else {}
        if contact and contact.get("ok") is False:
            ok = False
            contact_failed = True
        led_audit = case.get("ledGrooveAudit") if isinstance(case.get("ledGrooveAudit"), dict) else {}
        if not led_audit or led_audit.get("ok") is not True:
            ok = False
            led_groove_failed = True
        clearance_audit = case.get("clearanceFrontAudit") if isinstance(case.get("clearanceFrontAudit"), dict) else {}
        if not clearance_audit or clearance_audit.get("ok") is not True:
            ok = False
            clearance_front_failed = True
        corner_audit = case.get("cornerOwnershipAudit") if isinstance(case.get("cornerOwnershipAudit"), dict) else {}
        if not corner_audit or corner_audit.get("ok") is not True:
            ok = False
            corner_ownership_failed = True
        notch_audit = case.get("backT3NotchAudit") if isinstance(case.get("backT3NotchAudit"), dict) else {}
        if not notch_audit or notch_audit.get("ok") is not True:
            ok = False
            back_t3_notch_failed = True
        t4_audit = case.get("t4GeometryAudit") if isinstance(case.get("t4GeometryAudit"), dict) else {}
        if not t4_audit or t4_audit.get("ok") is not True:
            ok = False
            t4_geometry_failed = True
        findings.extend(case.get("findings") or [])
        errors.extend(case.get("errors") or [])
    # Dedupe errors while preserving order.
    deduped = []
    seen_err = set()
    for msg in errors:
        key = str(msg)
        if key in seen_err:
            continue
        seen_err.add(key)
        deduped.append(msg)
    errors = deduped
    if not_u:
        summary_line = "NOT_U_FOOTPRINT: measured assembly is not U-shaped (side runs still long in X)"
        if footprint_details:
            summary_line = str(footprint_details[0])
    elif contact_failed:
        contact_rows = [
            row.get("detail") for row in findings
            if isinstance(row, dict) and row.get("code") in ("contact_gap", "contact_no_face_overlap")
        ]
        summary_line = str(contact_rows[0]) if contact_rows else "Final board contact audit failed"
    elif led_groove_failed:
        led_rows = [
            row.get("detail") for row in findings
            if isinstance(row, dict) and str(row.get("code") or "").startswith("led_")
        ]
        summary_line = str(led_rows[0]) if led_rows else "Final LED BRep geometry audit failed"
    elif clearance_front_failed:
        clearance_rows = [
            row.get("detail") for row in findings
            if isinstance(row, dict) and str(row.get("code") or "").startswith("clearance_front_")
        ]
        summary_line = str(clearance_rows[0]) if clearance_rows else "Final clearance-front geometry audit failed"
    elif corner_ownership_failed:
        corner_rows = [
            row.get("detail") for row in findings
            if isinstance(row, dict) and (
                "corner" in str(row.get("code") or "") or str(row.get("code") or "").endswith("_arm_back_seam")
            )
        ]
        summary_line = str(corner_rows[0]) if corner_rows else "Final BACK corner-ownership audit failed"
    elif back_t3_notch_failed:
        notch_rows = [
            row.get("detail") for row in findings
            if isinstance(row, dict) and "notch" in str(row.get("code") or "")
        ]
        summary_line = str(notch_rows[0]) if notch_rows else "BACK.T3/T4 notch profile audit failed"
    elif t4_geometry_failed:
        t4_rows = [
            row.get("detail") for row in findings
            if isinstance(row, dict) and str(row.get("code") or "").startswith("t4_geometry_")
        ]
        summary_line = str(t4_rows[0]) if t4_rows else "Final T4 geometry audit failed"
    elif not ok:
        summary_line = str(errors[0]) if errors else "U Shape OHC self-check failed"
    else:
        summary_line = "U Shape OHC self-check OK"
    payload = {
        "ok": ok and not errors,
        "notUShape": not_u,
        "contactFailed": contact_failed,
        "ledGrooveFailed": led_groove_failed,
        "clearanceFrontFailed": clearance_front_failed,
        "cornerOwnershipFailed": corner_ownership_failed,
        "backT3NotchFailed": back_t3_notch_failed,
        "t4GeometryFailed": t4_geometry_failed,
        "summaryLine": summary_line,
        "adapterBuild": ADAPTER_BUILD,
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "source": source,
        "cases": measured_cases,
        "findings": findings,
        "errors": errors,
    }
    payload["logPath"] = write_u_shape_fusion_measure_log(payload, plugin_dir=plugin_dir)
    return payload


def _write_placement_debug(payload):
    """Dump the placement decision trail to <plugin>/placement_debug.json.

    Ground-truth tracing that works no matter which controller version is
    cached in Fusion (this adapter is reloaded from disk on every call).
    """
    try:
        debug_path = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "placement_debug.json")
        )
        with open(debug_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, default=str)
    except Exception:
        pass


def _is_number(value):
    return isinstance(value, (int, float)) and math.isfinite(value)


def _as_float(value):
    if _is_number(value):
        return float(value)
    return None


def _board_bbox(board):
    x0 = board.get("x0")
    x1 = board.get("x1")
    y0 = board.get("y0")
    y1 = board.get("y1")
    z0 = board.get("z0")
    z1 = board.get("z1")
    if not all(_is_number(v) for v in (x0, x1, y0, y1, z0, z1)):
        return None
    return {
        "x0": float(x0),
        "x1": float(x1),
        "y0": float(y0),
        "y1": float(y1),
        "z0": float(z0),
        "z1": float(z1),
    }


def _rough_size_mm(bbox):
    return (
        float(bbox["x1"] - bbox["x0"]),
        float(bbox["y1"] - bbox["y0"]),
        float(bbox["z1"] - bbox["z0"]),
    )


def _compose_occurrence_matrix(origin_x_mm=0.0, origin_y_mm=0.0, origin_z_mm=0.0, rotation_deg=0.0):
    """Build parent-space occurrence matrix: Z-rotate about origin, then translate.

    Cells are set explicitly so translation cannot drop the rotation (a failure
    mode that left U runs stacked as three parallel straight cabinets).
    """
    degrees = float(rotation_deg or 0.0)
    rad = math.radians(degrees)
    cos_a = math.cos(rad)
    sin_a = math.sin(rad)
    # Round near-90 multiples to exact 0/±1 to match generator integer trig.
    if abs(abs(degrees) % 90.0) < 1e-6 or abs(abs(degrees) % 90.0 - 90.0) < 1e-6:
        cos_a = float(round(cos_a))
        sin_a = float(round(sin_a))
    tx = mm_to_cm(float(origin_x_mm or 0.0))
    ty = mm_to_cm(float(origin_y_mm or 0.0))
    tz = mm_to_cm(float(origin_z_mm or 0.0))
    matrix = adsk.core.Matrix3D.create()
    # x' =  cos*x - sin*y + tx
    # y' =  sin*x + cos*y + ty
    matrix.setCell(0, 0, cos_a)
    matrix.setCell(0, 1, -sin_a)
    matrix.setCell(0, 2, 0.0)
    matrix.setCell(0, 3, tx)
    matrix.setCell(1, 0, sin_a)
    matrix.setCell(1, 1, cos_a)
    matrix.setCell(1, 2, 0.0)
    matrix.setCell(1, 3, ty)
    matrix.setCell(2, 0, 0.0)
    matrix.setCell(2, 1, 0.0)
    matrix.setCell(2, 2, 1.0)
    matrix.setCell(2, 3, tz)
    matrix.setCell(3, 0, 0.0)
    matrix.setCell(3, 1, 0.0)
    matrix.setCell(3, 2, 0.0)
    matrix.setCell(3, 3, 1.0)
    return matrix


def _matrix_z_rotation_deg(matrix):
    """Extract Z Euler angle (degrees) from an occurrence matrix."""
    try:
        cos_a = float(matrix.getCell(0, 0))
        sin_a = float(matrix.getCell(1, 0))
        return math.degrees(math.atan2(sin_a, cos_a))
    except Exception:
        return 0.0


def _angle_close(a, b, tol=1.0):
    return abs(((float(a) - float(b) + 180.0) % 360.0) - 180.0) <= tol


def _new_container_component(
    root_comp,
    run_label,
    module_name="generalTall",
    create_component=False,
    component_prefix=None,
    component_name=None,
    origin_x_mm=0.0,
    origin_y_mm=0.0,
    origin_z_mm=MODEL_Z_OFFSET_MM,
    origin_rotation_deg=0.0,
):
    resolved_component_name = resolve_assembly_name(
        component_name,
        run_label=run_label,
        default_name=component_prefix or module_name,
        include_human_run_label=True,
    )
    if not create_component:
        return root_comp, "Using root component container for {} rough bodies.".format(module_name), None

    try:
        # Work-zone placement uses real model coordinates: generation origin
        # lives on z=0. Legacy no-zone calls keep MODEL_Z_OFFSET_MM staging.
        # U-Shape OHC passes a non-zero Z rotation so each run is born already
        # oriented; post-hoc occurrence moves are too easy for the timeline to drop.
        transform = _compose_occurrence_matrix(
            origin_x_mm=origin_x_mm,
            origin_y_mm=origin_y_mm,
            origin_z_mm=origin_z_mm if origin_z_mm is not None else MODEL_Z_OFFSET_MM,
            rotation_deg=origin_rotation_deg,
        )
        occurrence = root_comp.occurrences.addNewComponent(transform)
        component = occurrence.component
    except Exception as ex:
        return root_comp, "Could not create {} assembly component; using root component instead: {}".format(module_name, ex), None

    # Parametric designs do NOT persist occurrence positions across timeline
    # recomputes unless a snapshot captures them; lock the placement now so the
    # feature work below cannot bounce the container back to the origin.
    _capture_position_snapshot(root_comp)

    # CRITICAL: naming must never abort the placed component. Fusion component
    # names are unique per design; assigning a duplicate (e.g. "OHC" on the
    # second run) RAISES, and previously that exception threw the whole
    # transformed container away, dumping bodies at the root origin.
    resolved_component_name = _assign_component_name(occurrence, component, resolved_component_name)
    try:
        component.attributes.add(ATTRIBUTE_GROUP, "module", module_name)
        component.attributes.add(ATTRIBUTE_GROUP, "runLabel", str(run_label))
        component.attributes.add(ATTRIBUTE_GROUP, "assemblyName", resolved_component_name)
    except Exception:
        pass
    return component, None, resolved_component_name


def _capture_position_snapshot(root_comp):
    capture_position_snapshot(root_comp)


def _delete_previous_module_assemblies(root_comp, module_name):
    """Remove earlier assemblies for this module so Replace (not Generate new) can reuse the origin."""
    deleted = {"occurrences": 0, "bodies": 0}
    if not root_comp or not module_name:
        return deleted
    try:
        for index in range(root_comp.occurrences.count - 1, -1, -1):
            occurrence = root_comp.occurrences.item(index)
            child = getattr(occurrence, "component", None)
            occ_name = str(getattr(occurrence, "name", "") or "")
            child_name = str(getattr(child, "name", "") or "") if child else ""
            if is_module_artifact(child, module_name, name=occ_name) or is_module_artifact(child, module_name, name=child_name):
                occurrence.deleteMe()
                deleted["occurrences"] += 1
    except Exception:
        pass
    try:
        for index in range(root_comp.bRepBodies.count - 1, -1, -1):
            body = root_comp.bRepBodies.item(index)
            name = str(getattr(body, "name", "") or "")
            if is_module_artifact(body, module_name, name=name):
                body.deleteMe()
                deleted["bodies"] += 1
    except Exception:
        pass
    return deleted


def _avoid_existing_at_origin(root_comp, origin_x_mm, origin_y_mm, footprint_mm):
    return avoid_existing_at_origin(root_comp, origin_x_mm, origin_y_mm, footprint_mm)


def _assign_component_name(occurrence, component, desired_name):
    """Rename occurrence+component, auto-suffixing on duplicate-name errors.

    Never raises: a failed rename keeps Fusion's auto name instead of aborting
    the (already placed) component.
    """
    base = sanitize_token(desired_name, fallback="assembly", limit=76)
    candidates = [base] + ["{}_{}".format(base, index) for index in range(2, 100)]
    for candidate in candidates:
        try:
            component.name = candidate
        except Exception:
            continue
        try:
            occurrence.name = candidate
        except Exception:
            pass
        return candidate
    try:
        return str(component.name)
    except Exception:
        return base


def _new_child_component(parent_component, component_name, module_name="overhead", board_id=None):
    transform = adsk.core.Matrix3D.create()
    occurrence = parent_component.occurrences.addNewComponent(transform)
    component = occurrence.component
    _assign_component_name(occurrence, component, component_name)
    try:
        component.attributes.add(ATTRIBUTE_GROUP, "module", module_name)
        if board_id is not None:
            component.attributes.add(ATTRIBUTE_GROUP, "boardId", str(board_id))
    except Exception:
        pass
    return component


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


def _oh_board_semantics(board, all_boards):
    return overhead_board_semantics(board, all_boards)


def _oh_panel_metadata(board, bbox, all_boards, run_label, features=None, carcass_color=None, carcass_color_name=None):
    return build_panel_metadata(
        "overhead",
        board,
        bbox=bbox,
        all_boards=all_boards,
        run_label=run_label,
        features=features,
        carcass_color=carcass_color,
        carcass_color_name=carcass_color_name,
    )


def _write_oh_panel_metadata(body, board, bbox, all_boards, run_label, features=None, carcass_color=None, carcass_color_name=None):
    metadata = _oh_panel_metadata(
        board, bbox, all_boards, run_label,
        features=features,
        carcass_color=carcass_color, carcass_color_name=carcass_color_name,
    )
    return metadata, write_panel_metadata_to_body(body, metadata)


def _gt_board_semantics(board):
    """Canonical material/role for General Tall boards."""
    return general_tall_board_semantics(board)


def _gt_panel_metadata(board, bbox, run_label, carcass_color=None, carcass_color_name=None, features=None):
    return build_panel_metadata(
        "generalTall",
        board,
        bbox=bbox,
        run_label=run_label,
        features=features,
        carcass_color=carcass_color,
        carcass_color_name=carcass_color_name,
    )


def _write_gt_panel_metadata(
    body, board, bbox, run_label, carcass_color=None, carcass_color_name=None, features=None,
):
    metadata = _gt_panel_metadata(
        board, bbox, run_label,
        carcass_color=carcass_color, carcass_color_name=carcass_color_name,
        features=features,
    )
    return metadata, write_panel_metadata_to_body(body, metadata)


def _update_oh_panel_metadata(body, panel_metadata):
    payload = json.dumps(panel_metadata, ensure_ascii=False, separators=(",", ":"))
    return _set_entity_attribute(body, PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR, payload)


def _run_oh_face_init(body, panel_metadata, board_id, summary):
    """Initialize face metadata for one OHC board and fold results into summary."""
    if not initialize_oh_panel_faces:
        return
    try:
        panel_metadata, face_init_result = initialize_oh_panel_faces(body, panel_metadata, board_id)
        if face_init_result.get("initialized"):
            if not _update_oh_panel_metadata(body, panel_metadata):
                summary["warnings"].append(
                    "Face metadata was initialized for {} but faceRegistry write-back failed.".format(board_id)
                )
            else:
                summary["faceInitSummary"]["initializedCount"] += 1
                summary["faceInitSummary"]["totalEdgeCount"] += int(face_init_result.get("edgeCount") or 0)
                summary["faceInitSummary"]["totalSurfaceCount"] += int(face_init_result.get("surfaceCount") or 0)
                summary["faceInitSummary"]["boards"].append(
                    {
                        "boardId": board_id,
                        "bodyName": getattr(body, "name", "") or "",
                        "surfaceCount": face_init_result.get("surfaceCount"),
                        "edgeCount": face_init_result.get("edgeCount"),
                        "faceCount": face_init_result.get("faceCount"),
                        "edgeGroupCount": face_init_result.get("edgeGroupCount"),
                    }
                )
        elif face_init_result.get("skipped"):
            summary["faceInitSummary"]["skippedCount"] += 1
        else:
            for warning in (face_init_result.get("warnings") or [])[:2]:
                summary["warnings"].append("Face skeleton skipped for {}: {}".format(board_id, warning))
    except Exception as ex:
        summary["warnings"].append("Face metadata initialization failed for {}: {}".format(board_id, ex))


try:
    import importlib
    import sys as _sys

    # Reload the whole face-metadata dependency chain in dependency order so a
    # stale cached module (for example face_models without newly added
    # constants) cannot break the import of panel_face_initializer.
    for _module_name in (
        "face_models",
        "face_geometry_signature",
        "face_attribute_store",
        "face_entity_resolver",
        "face_validation",
        "face_metadata_service",
        "panel_geometry",
        "panel_face_initializer",
    ):
        try:
            if _module_name in _sys.modules:
                importlib.reload(_sys.modules[_module_name])
            else:
                importlib.import_module(_module_name)
        except Exception:
            pass

    import panel_face_initializer as _panel_face_initializer_module

    initialize_oh_panel_faces = _panel_face_initializer_module.initialize_oh_panel_faces
except Exception:
    initialize_oh_panel_faces = None


def _body_axis_min_mm(body, axis):
    bbox = body.boundingBox
    if axis == "X":
        return bbox.minPoint.x * 10.0
    if axis == "Y":
        return bbox.minPoint.y * 10.0
    return bbox.minPoint.z * 10.0


def _axis_start_mm(bbox, axis):
    return bbox["x0"] if axis == "X" else bbox["y0"] if axis == "Y" else bbox["z0"]


def _axis_size_mm(bbox, axis):
    return (
        bbox["x1"] - bbox["x0"] if axis == "X"
        else bbox["y1"] - bbox["y0"] if axis == "Y"
        else bbox["z1"] - bbox["z0"]
    )


def _align_body_axis_min(component, body, axis, target_min_mm, feature_prefix="GT_ALIGN_"):
    current_min_mm = _body_axis_min_mm(body, axis)
    delta = float(target_min_mm) - float(current_min_mm)
    if abs(delta) <= 0.001:
        return
    dx = delta if axis == "X" else 0.0
    dy = delta if axis == "Y" else 0.0
    dz = delta if axis == "Z" else 0.0
    move_body_by_mm(component, body, dx, dy, dz, feature_prefix=feature_prefix)


def _add_box_body(component, board_id, bbox, body_prefix="GT", module_name="generalTall", move_prefix="GT_MOVE_", display_name=None):
    sketches = component.sketches
    sketch = sketches.add(component.xYConstructionPlane)
    p0 = adsk.core.Point3D.create(mm_to_cm(bbox["x0"]), mm_to_cm(bbox["y0"]), 0)
    p1 = adsk.core.Point3D.create(mm_to_cm(bbox["x1"]), mm_to_cm(bbox["y1"]), 0)
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
    if sketch.profiles.count < 1:
        return None, "No sketch profile generated for bbox rectangle."

    profile = sketch.profiles.item(0)
    height_mm = bbox["z1"] - bbox["z0"]
    extrudes = component.features.extrudeFeatures
    distance = adsk.core.ValueInput.createByReal(mm_to_cm(height_mm))
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, distance)
    extrude = extrudes.add(ext_input)
    if extrude.bodies.count < 1:
        return None, "Extrude created no body."

    body = extrude.bodies.item(0)
    body.name = display_name or board_component_label(body_prefix, board_id, fallback_assembly=body_prefix)
    if abs(bbox["z0"]) > 1e-6:
        move_body_by_mm(component, body, 0.0, 0.0, float(bbox["z0"]), feature_prefix=move_prefix)
    try:
        body.attributes.add(ATTRIBUTE_GROUP, "module", module_name)
        body.attributes.add(ATTRIBUTE_GROUP, "boardId", str(board_id))
    except Exception:
        pass
    return body, None


def _vector_source_for_board(board):
    if isinstance(board.get("cutProfileVector"), list) and len(board.get("cutProfileVector")) > 0:
        return "cutProfileVector", board.get("cutProfileVector")
    if isinstance(board.get("profileVector"), list) and len(board.get("profileVector")) > 0:
        return "profileVector", board.get("profileVector")
    return None, None


def _points_equal(a, b, tol=1e-6):
    return abs(a[0] - b[0]) <= tol and abs(a[1] - b[1]) <= tol


def _extract_local_profile_points(board, vector_source, raw_points):
    plane = str(board.get("profilePlane") or "")
    points = []
    for item in raw_points:
        if not isinstance(item, dict):
            return None, "Profile vector contains non-object points."
        if plane == "YZ":
            y = _as_float(item.get("y"))
            z = _as_float(item.get("z"))
            if y is None or z is None:
                return None, "YZ profile requires {y,z} points."
            points.append((y, z))
        elif plane == "XY":
            x = _as_float(item.get("x"))
            y = _as_float(item.get("y"))
            if x is None or y is None:
                return None, "XY profile requires {x,y} points."
            points.append((x, y))
        elif plane == "XZ":
            x = _as_float(item.get("x"))
            z = _as_float(item.get("z"))
            if x is None or z is None:
                return None, "XZ profile requires {x,z} points."
            points.append((x, z))
        else:
            return None, "Unsupported profilePlane: {!r}.".format(plane)

    if len(points) < 3:
        return None, "{} has fewer than 3 points.".format(vector_source)

    deduped = []
    for point in points:
        if not deduped or not _points_equal(point, deduped[-1]):
            deduped.append(point)
    if len(deduped) < 3:
        return None, "{} has fewer than 3 unique points.".format(vector_source)
    if not _points_equal(deduped[0], deduped[-1]):
        deduped.append(deduped[0])

    unique = []
    for point in deduped[:-1]:
        if not any(_points_equal(point, other) for other in unique):
            unique.append(point)
    if len(unique) < 3:
        return None, "{} has fewer than 3 unique points after cleanup.".format(vector_source)
    return deduped, None


def _axis_to_world(value, bbox_min, mode):
    return value if mode == "absolute" else bbox_min + value


def _profile_axis_modes(board, plane, vector_source, module_name="generalTall"):
    # Default contract: profile vectors are local profile coordinates.
    # General Tall VD cutProfileVector stores absolute Z values.
    board_type = str(board.get("boardType") or "").lower()
    board_category = str(board.get("category") or "").lower()
    if (
        plane == "YZ"
        and vector_source == "cutProfileVector"
        and (board_type == "vertical_divider" or board_type == "divider" or board_category == "divider")
    ):
        if module_name == "overhead":
            return {"a": "local", "b": "local"}
        return {"a": "local", "b": "absolute"}
    return {"a": "local", "b": "local"}


def _requires_xy_180_rotation(board, plane, module_name="generalTall"):
    if module_name != "generalTall":
        return False
    if plane != "XY":
        return False
    board_id = str(board.get("id") or "").upper()
    board_type = str(board.get("boardType") or "").upper()
    return board_id in ("T3", "B3") or board_type in ("T3", "B3")


def _rotate_world_points_xy_180(world_points, bbox):
    center_x = (bbox["x0"] + bbox["x1"]) / 2.0
    center_y = (bbox["y0"] + bbox["y1"]) / 2.0
    rotated = []
    for x, y, z in world_points:
        rotated.append((2.0 * center_x - x, 2.0 * center_y - y, z))
    return rotated


def _placement_offset_mm(board, result_debug=None, avoidance_z_shift_mm=0.0, module_name="generalTall", result_params=None):
    board_id = str(board.get("id") or "").upper()
    board_type = str(board.get("boardType") or "").upper()
    board_category = str(board.get("category") or "").lower()
    front_panel_thickness = _as_float((result_debug or {}).get("frontFaceAllowance")) if isinstance(result_debug, dict) else None
    front_panel_thickness = front_panel_thickness if front_panel_thickness is not None else 0.0

    if board_category == "side_panel" or board_id in ("SIDEPANEL_L", "SIDEPANEL_R"):
        # Generator now emits side panels with the front protrusion already in the bbox (y0 = -FPT).
        return 0.0, 0.0, 0.0

    if board_category == "avoidance_support" or board_id in ("AVOIDANCE_HORIZONTAL", "AVOIDANCE_VERTICAL"):
        return 0.0, -front_panel_thickness, 0.0

    if board_type == "STYLE2_FIXED_FRONT_PANEL" or board_id in ("TOPSTYLE2FIXEDFRONTPANEL", "BOTTOMSTYLE2FIXEDFRONTPANEL"):
        # Generator now emits style_2 fixed front panels at y -FPT..0 directly.
        return 0.0, 0.0, 0.0

    if board_id in ("T4", "T5") or board_type in ("T4", "T5"):
        return 0.0, -front_panel_thickness, 0.0

    if board_id in ("H13_BOTTOM", "H24_BOTTOM", "H34_BOTTOM"):
        return 0.0, 0.0, float(max(0.0, avoidance_z_shift_mm))

    needs_rear_notch_contact = board_id in ("T1", "T2", "B1", "B2") or board_type in ("T1", "T2", "B1", "B2")
    if needs_rear_notch_contact:
        if module_name == "overhead":
            top_clearance = _as_float((result_params or {}).get("topClearanceHeight"))
            if top_clearance is not None:
                return 0.0, top_clearance - 1.0, 0.0
        return 0.0, 39.0, 0.0
    return 0.0, 0.0, 0.0


def _world_point_from_local(bbox, plane, local_point, axis_modes):
    a, b = local_point
    if plane == "YZ":
        return (
            bbox["x0"],
            _axis_to_world(a, bbox["y0"], axis_modes["a"]),
            _axis_to_world(b, bbox["z0"], axis_modes["b"]),
        )
    if plane == "XY":
        return (
            _axis_to_world(a, bbox["x0"], axis_modes["a"]),
            _axis_to_world(b, bbox["y0"], axis_modes["b"]),
            bbox["z0"],
        )
    return (
        _axis_to_world(a, bbox["x0"], axis_modes["a"]),
        bbox["y0"],
        _axis_to_world(b, bbox["z0"], axis_modes["b"]),
    )


def _profile_plane_for_sketch(component, plane, bbox):
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    if plane == "YZ":
        plane_input.setByOffset(component.yZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(bbox["x0"])))
    elif plane == "XY":
        plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(bbox["z0"])))
    elif plane == "XZ":
        plane_input.setByOffset(component.xZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(bbox["y0"])))
    else:
        return None
    return construction.add(plane_input)


def _largest_profile(sketch):
    if sketch.profiles.count < 1:
        return None
    chosen = sketch.profiles.item(0)
    chosen_area = -1.0
    for idx in range(sketch.profiles.count):
        item = sketch.profiles.item(idx)
        try:
            area = abs(item.areaProperties().area)
        except Exception:
            area = 0.0
        if area >= chosen_area:
            chosen = item
            chosen_area = area
    return chosen


def _add_profile_body(
    component,
    board_id,
    board,
    bbox,
    vector_source,
    raw_points,
    body_prefix="GT",
    module_name="generalTall",
    align_prefix="GT_ALIGN_",
    display_name=None,
):
    plane = str(board.get("profilePlane") or "")
    axis = str(board.get("thicknessAxis") or "")
    if axis not in ("X", "Y", "Z"):
        return None, "Invalid thicknessAxis: {!r}.".format(axis)

    local_points, points_error = _extract_local_profile_points(board, vector_source, raw_points)
    if points_error:
        return None, points_error

    axis_modes = _profile_axis_modes(board, plane, vector_source, module_name=module_name)
    sketch_plane = _profile_plane_for_sketch(component, plane, bbox)
    if not sketch_plane:
        return None, "Unsupported profile plane mapping: {!r}.".format(plane)
    sketch = component.sketches.add(sketch_plane)
    sketch.name = "{}_{}_{}".format(body_prefix, sanitize_token(board_id, limit=60), vector_source)

    world_points = [_world_point_from_local(bbox, plane, point, axis_modes) for point in local_points]
    if _requires_xy_180_rotation(board, plane, module_name=module_name):
        world_points = _rotate_world_points_xy_180(world_points, bbox)
    for index in range(len(world_points) - 1):
        p0 = world_points[index]
        p1 = world_points[index + 1]
        if (
            abs(p0[0] - p1[0]) <= 1e-9
            and abs(p0[1] - p1[1]) <= 1e-9
            and abs(p0[2] - p1[2]) <= 1e-9
        ):
            continue
        m0 = adsk.core.Point3D.create(mm_to_cm(p0[0]), mm_to_cm(p0[1]), mm_to_cm(p0[2]))
        m1 = adsk.core.Point3D.create(mm_to_cm(p1[0]), mm_to_cm(p1[1]), mm_to_cm(p1[2]))
        s0 = sketch.modelToSketchSpace(m0)
        s1 = sketch.modelToSketchSpace(m1)
        sketch.sketchCurves.sketchLines.addByTwoPoints(s0, s1)

    profile = _largest_profile(sketch)
    if profile is None:
        return None, "No closed sketch profile available from {}.".format(vector_source)

    thickness_mm = _axis_size_mm(bbox, axis)
    if thickness_mm <= 0:
        return None, "Non-positive thickness along axis {}.".format(axis)

    extrudes = component.features.extrudeFeatures
    ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
    ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(thickness_mm)))
    extrude = extrudes.add(ext_input)
    if extrude.bodies.count < 1:
        return None, "Extrude created no body from {}.".format(vector_source)

    body = extrude.bodies.item(0)
    _align_body_axis_min(component, body, axis, _axis_start_mm(bbox, axis), feature_prefix=align_prefix)
    body.name = display_name or board_component_label(body_prefix, board_id, fallback_assembly=body_prefix)
    try:
        body.attributes.add(ATTRIBUTE_GROUP, "module", module_name)
        body.attributes.add(ATTRIBUTE_GROUP, "boardId", str(board_id))
        body.attributes.add(ATTRIBUTE_GROUP, "profileSource", vector_source)
    except Exception:
        pass
    return body, None


def _is_zi_board(board):
    board_id = str(board.get("id") or "")
    board_type = str(board.get("boardType") or "").lower()
    return board_id.startswith("Zi") or "zi" in board_type


def _as_world_range(board_bbox, local_0, local_1, axis):
    base = board_bbox["x0"] if axis == "x" else board_bbox["y0"]
    world_0 = base + float(local_0)
    world_1 = base + float(local_1)
    return min(world_0, world_1), max(world_0, world_1)


def _clamp_range(v0, v1, min_v, max_v):
    low = max(min(v0, v1), min_v)
    high = min(max(v0, v1), max_v)
    if high <= low:
        return None
    return low, high


def _find_board_by_id(boards_by_id, board_id):
    if not isinstance(board_id, str):
        return None
    return boards_by_id.get(board_id)


def _collect_zi_groove_features(result):
    features = result.get("features")
    if not isinstance(features, list):
        return {}
    by_target = {}
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "zi_groove":
            continue
        target_id = feature.get("targetBoardId")
        if not isinstance(target_id, str) or not target_id:
            continue
        by_target.setdefault(target_id, []).append(feature)
    return by_target


def _collect_led_groove_features(result):
    """B3/T3 LED grooves keyed by target board id."""
    features = result.get("features")
    if not isinstance(features, list):
        return {}
    by_target = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        if feature.get("type") not in ("b3_groove", "t3_groove"):
            continue
        target_id = feature.get("targetBoardId")
        if not isinstance(target_id, str) or not target_id:
            continue
        by_target.setdefault(target_id, []).append(feature)
    return by_target


def _set_single_body_participants(ext_input, body):
    """Restrict a cut extrude to one workpiece body only.

    Fusion's SWIG binding for participantBodies expects a Python list of
    BRepBody (std::vector), not ObjectCollection. Try list first, then
    ObjectCollection for older builds that accepted it.
    """
    if body is None:
        return "missing body"
    errors = []
    try:
        ext_input.participantBodies = [body]
        return None
    except Exception as ex:
        errors.append("list: {}".format(ex))
    try:
        participants = adsk.core.ObjectCollection.create()
        participants.add(body)
        ext_input.participantBodies = participants
        return None
    except Exception as ex:
        errors.append("ObjectCollection: {}".format(ex))
    return "; ".join(errors)


def _led_groove_segments(feature):
    segments = []
    main = feature.get("main") if isinstance(feature.get("main"), dict) else None
    if main:
        segments.append(("main", main))
    for index, branch in enumerate(feature.get("branches") or []):
        if isinstance(branch, dict):
            segments.append(("branch{}".format(index + 1), branch))
    return segments


def _mirror_led_segment_x(segment, board_width):
    """Mirror one LED segment in board-local X while preserving Y.

    Style-1 T3 profiles are corrected by 180 degrees during body creation.
    U-shape side grooves use semantic generator coordinates (apex/open end),
    so their pocket rectangles need this Adapter-space compensation.
    """
    if not isinstance(segment, dict):
        return segment
    x0 = _as_float(segment.get("x0"))
    x1 = _as_float(segment.get("x1"))
    width = _as_float(board_width)
    if x0 is None or x1 is None or width is None or width <= 0:
        return segment
    mirrored = dict(segment)
    mirrored["x0"] = width - max(x0, x1)
    mirrored["x1"] = width - min(x0, x1)
    return mirrored


def _led_segment_world_rect(target_bbox, segment):
    """Map LED segment local offsets -> assembly XY on the target board.

    Generator stores main/branches as offsets from the board origin (front =
    low Y / doors). Do NOT apply the B3/T3 profile 180° flip here: that flip
    only corrects the insert outline shape; pocket positions stay in cabinet
    space so the channel remains ~20 mm from the front edge.
    """
    local_x0 = _as_float(segment.get("x0"))
    local_x1 = _as_float(segment.get("x1"))
    local_y0 = _as_float(segment.get("y0"))
    local_y1 = _as_float(segment.get("y1"))
    if None in (local_x0, local_x1, local_y0, local_y1):
        return None
    world_x0, world_x1 = _as_world_range(target_bbox, local_x0, local_x1, "x")
    world_y0, world_y1 = _as_world_range(target_bbox, local_y0, local_y1, "y")
    clamped_x = _clamp_range(world_x0, world_x1, target_bbox["x0"], target_bbox["x1"])
    clamped_y = _clamp_range(world_y0, world_y1, target_bbox["y0"], target_bbox["y1"])
    if clamped_x is None or clamped_y is None:
        return None
    return (clamped_x[0], clamped_y[0], clamped_x[1], clamped_y[1])


def _led_cut_plane_and_direction(face, target_bbox, effective_depth):
    """Return (plane_z_mm, extent_direction, cut_signed_cm, opening).

    B3/BP bottom: sketch slightly below the bottom face and cut into +Z so the
    pocket opens downward. A tiny below-face offset avoids Fusion failing on
    coplanar cuts (common for BP where z0==0 and the body was also sketched on
    the XY construction plane). T3 top: sketch on the top face and cut into -Z.
    """
    depth_cm = mm_to_cm(effective_depth)
    if face == "bottom":
        plane_nudge_mm = 0.05
        return (
            target_bbox["z0"] - plane_nudge_mm,
            adsk.fusion.ExtentDirections.PositiveExtentDirection,
            depth_cm + mm_to_cm(plane_nudge_mm),
            "downward",
        )
    return (
        target_bbox["z1"],
        adsk.fusion.ExtentDirections.NegativeExtentDirection,
        -depth_cm,
        "downward_into_board_from_top",
    )


def _cut_led_groove_rect(component, body, plane_z, extent_direction, cut_signed, rect, sketch_name, cut_name):
    """Cut one rectangular pocket; returns (status, reason)."""
    x0, y0, x1, y1 = rect
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    plane_input.setByOffset(
        component.xYConstructionPlane,
        adsk.core.ValueInput.createByReal(mm_to_cm(plane_z)),
    )
    cut_plane = construction.add(plane_input)
    sketch = component.sketches.add(cut_plane)
    sketch.name = sketch_name
    p0 = sketch.modelToSketchSpace(
        adsk.core.Point3D.create(mm_to_cm(x0), mm_to_cm(y0), mm_to_cm(plane_z))
    )
    p1 = sketch.modelToSketchSpace(
        adsk.core.Point3D.create(mm_to_cm(x1), mm_to_cm(y1), mm_to_cm(plane_z))
    )
    sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
    profile = _largest_profile(sketch)
    if profile is None:
        return "failed", "no closed LED groove profile"

    extrudes = component.features.extrudeFeatures

    def _try_cut(direction, signed_distance, with_participants):
        ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
        try:
            extent = adsk.fusion.DistanceExtentDefinition.create(
                adsk.core.ValueInput.createByReal(abs(float(signed_distance)))
            )
            ext_input.setOneSideExtent(extent, direction)
        except Exception:
            ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(signed_distance))
        if with_participants:
            _set_single_body_participants(ext_input, body)
        cut = extrudes.add(ext_input)
        cut.name = cut_name
        return cut

    try:
        _try_cut(extent_direction, cut_signed, True)
        return "created", ""
    except Exception as first_ex:
        # Retry without participantBodies, then flip direction once in case the
        # construction-plane normal is inverted on this Fusion build.
        flip = (
            adsk.fusion.ExtentDirections.NegativeExtentDirection
            if extent_direction == adsk.fusion.ExtentDirections.PositiveExtentDirection
            else adsk.fusion.ExtentDirections.PositiveExtentDirection
        )
        for direction, signed, participants in (
            (extent_direction, cut_signed, False),
            (flip, -cut_signed, True),
            (flip, -cut_signed, False),
        ):
            try:
                _try_cut(direction, signed, participants)
                return "created", "recovered_with_fallback_direction" if direction == flip else ""
            except Exception:
                continue
        return "failed", "Fusion LED groove cut failed: {}".format(first_ex)


def _create_led_groove_cut(component, body, target_board, target_bbox, feature):
    """Cut LED groove pockets on one B3/T3 body only.

    GT carcass boards are built in assembly pose (no flat nest pass). Isolation is
    enforced by: (1) cutting inside the board's own child component, and
    (2) participantBodies=[this body] so neighboring workpieces are never cut.

    Each main/branch segment is cut as its own extrude so adjacent rectangles
    cannot collapse into an invalid multi-profile cut (which previously left a
    sketch with no pocket).
    """
    feature_id = str(feature.get("id") or "led_groove")
    target_board_id = str(target_board.get("id") or "")
    feature_type = str(feature.get("type") or "").strip().lower()
    # Hard-pin faces by feature type / board so B3/BP always open downward.
    if feature_type == "b3_groove" or target_board_id.upper() in ("B3", "BP"):
        face = "bottom"
    elif feature_type == "t3_groove" or target_board_id.upper() == "T3":
        face = "top"
    else:
        face = str(feature.get("face") or "").strip().lower()
    if face not in ("top", "bottom"):
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "status": "skipped",
            "reason": "face must be top or bottom",
        }
    if body is None or target_bbox is None:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "status": "skipped",
            "reason": "missing body or bbox",
        }

    depth = _as_float(feature.get("depth"))
    depth = depth if depth is not None and depth > 0 else 6.5
    thickness = max(0.0, target_bbox["z1"] - target_bbox["z0"])
    effective_depth = min(depth, max(0.0, thickness - 0.2))
    if effective_depth <= 0:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "status": "skipped",
            "reason": "non-positive groove depth",
        }

    segments = _led_groove_segments(feature)
    if not segments:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "status": "skipped",
            "reason": "no main/branch segments",
        }

    plane_z, extent_direction, cut_signed, opening = _led_cut_plane_and_direction(
        face, target_bbox, effective_depth
    )

    world_rects = []
    for label, segment in segments:
        rect = _led_segment_world_rect(target_bbox, segment)
        if rect is None:
            continue
        world_rects.append((label, rect))

    if not world_rects:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "status": "skipped",
            "reason": "segments outside board bbox",
        }

    created = 0
    failures = []
    recovered = False
    try:
        for label, rect in world_rects:
            sketch_name = "GT_{}_led_{}_{}".format(
                sanitize_token(target_board_id, limit=24),
                sanitize_token(feature_id, limit=28),
                sanitize_token(label, limit=16),
            )
            cut_name = "GT_LED_CUT_{}_{}".format(
                sanitize_token(feature_id, limit=40),
                sanitize_token(label, limit=16),
            )
            status, reason = _cut_led_groove_rect(
                component,
                body,
                plane_z,
                extent_direction,
                cut_signed,
                rect,
                sketch_name,
                cut_name,
            )
            if status == "created":
                created += 1
                if reason:
                    recovered = True
            else:
                failures.append("{}: {}".format(label, reason or "unknown"))
    except Exception as ex:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "status": "failed",
            "face": face,
            "opening": opening,
            "reason": "Fusion LED groove cut failed: {}".format(ex),
            "segmentCount": len(world_rects),
            "createdSegments": created,
        }

    if created == len(world_rects):
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "status": "created",
            "face": face,
            "opening": opening,
            "depth": effective_depth,
            "planeZMm": plane_z,
            "segmentCount": len(world_rects),
            "createdSegments": created,
            "isolatedBody": True,
            "reason": "recovered_with_fallback_direction" if recovered else "",
            "yRangeMm": [world_rects[0][1][1], world_rects[0][1][3]],
        }
    if created > 0:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "status": "failed",
            "face": face,
            "opening": opening,
            "depth": effective_depth,
            "segmentCount": len(world_rects),
            "createdSegments": created,
            "reason": "partial LED groove cut: {}".format("; ".join(failures)),
        }
    return {
        "featureId": feature_id,
        "targetBoardId": target_board_id,
        "status": "failed",
        "face": face,
        "opening": opening,
        "segmentCount": len(world_rects),
        "createdSegments": 0,
        "reason": "; ".join(failures) or "LED groove cut produced no pockets",
    }


def _create_zi_groove_cut(component, target_board, target_bbox, feature, boards_by_id, body=None):
    feature_id = str(feature.get("id") or "zi_groove")
    target_board_id = str(target_board.get("id") or "")
    divider_id = feature.get("dividerBoardId")
    divider = _find_board_by_id(boards_by_id, divider_id)
    divider_bbox = _board_bbox(divider) if isinstance(divider, dict) else None
    if divider_bbox is None:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "status": "skipped",
            "reason": "related VD board not found",
        }

    face = str(feature.get("face") or "")
    if face != "bottom":
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "status": "skipped",
            "reason": "only bottom-face Zi groove is enabled in Stage C1",
        }

    local_x0 = _as_float(feature.get("x0"))
    local_x1 = _as_float(feature.get("x1"))
    if local_x0 is not None and local_x1 is not None:
        world_x0, world_x1 = _as_world_range(target_bbox, local_x0, local_x1, "x")
    else:
        world_x0, world_x1 = divider_bbox["x0"], divider_bbox["x1"]

    local_y0 = _as_float(feature.get("y0"))
    local_y1 = _as_float(feature.get("y1"))
    if local_y0 is not None and local_y1 is not None:
        world_y0, world_y1 = _as_world_range(target_bbox, local_y0, local_y1, "y")
    else:
        mid_depth = target_bbox["y1"] - target_bbox["y0"]
        fallback_y0 = mid_depth / 3.0 - 5.0
        fallback_y1 = (mid_depth * 2.0) / 3.0 + 5.0
        world_y0, world_y1 = _as_world_range(target_bbox, fallback_y0, fallback_y1, "y")

    clamped_x = _clamp_range(world_x0, world_x1, target_bbox["x0"], target_bbox["x1"])
    clamped_y = _clamp_range(world_y0, world_y1, target_bbox["y0"], target_bbox["y1"])
    if clamped_x is None or clamped_y is None:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "xRange": [world_x0, world_x1],
            "yRange": [world_y0, world_y1],
            "status": "skipped",
            "reason": "groove range does not intersect target Zi board bbox",
        }

    x0, x1 = clamped_x
    y0, y1 = clamped_y
    depth = _as_float(feature.get("depth"))
    depth = depth if depth is not None and depth > 0 else 7.0
    world_z_top = target_bbox["z1"]
    world_z_bottom = max(target_bbox["z0"], target_bbox["z1"] - depth)
    effective_depth = world_z_top - world_z_bottom
    if effective_depth <= 0:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "xRange": [x0, x1],
            "yRange": [y0, y1],
            "zRange": [world_z_bottom, world_z_top],
            "depth": depth,
            "status": "skipped",
            "reason": "non-positive groove depth after clamp",
        }

    try:
        construction = component.constructionPlanes
        plane_input = construction.createInput()
        plane_input.setByOffset(
            component.xYConstructionPlane,
            adsk.core.ValueInput.createByReal(mm_to_cm(world_z_top)),
        )
        top_plane = construction.add(plane_input)
        sketch = component.sketches.add(top_plane)
        sketch.name = "GT_{}_groove_{}".format(sanitize_token(target_board_id, limit=40), sanitize_token(feature_id, limit=40))

        m0 = adsk.core.Point3D.create(mm_to_cm(x0), mm_to_cm(y0), mm_to_cm(world_z_top))
        m1 = adsk.core.Point3D.create(mm_to_cm(x1), mm_to_cm(y1), mm_to_cm(world_z_top))
        s0 = sketch.modelToSketchSpace(m0)
        s1 = sketch.modelToSketchSpace(m1)
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(s0, s1)

        profile = _largest_profile(sketch)
        if profile is None:
            return {
                "featureId": feature_id,
                "targetBoardId": target_board_id,
                "relatedVD": divider_id,
                "xRange": [x0, x1],
                "yRange": [y0, y1],
                "zRange": [world_z_bottom, world_z_top],
                "depth": depth,
                "status": "failed",
                "reason": "no closed profile for zi groove cut",
            }

        extrudes = component.features.extrudeFeatures
        ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(effective_depth)))
        if body is not None:
            _set_single_body_participants(ext_input, body)
        extrudes.add(ext_input)
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "xRange": [x0, x1],
            "yRange": [y0, y1],
            "zRange": [world_z_bottom, world_z_top],
            "depth": depth,
            "status": "created",
            "reason": "",
        }
    except Exception as ex:
        return {
            "featureId": feature_id,
            "targetBoardId": target_board_id,
            "relatedVD": divider_id,
            "xRange": [x0, x1],
            "yRange": [y0, y1],
            "zRange": [world_z_bottom, world_z_top],
            "depth": depth,
            "status": "failed",
            "reason": "Fusion groove cut failed: {}".format(ex),
        }


def _move_body_rigid_transform(component, body, transform, feature_prefix="UCP_RIGID_"):
    bodies = adsk.core.ObjectCollection.create()
    bodies.add(body)
    move_input = component.features.moveFeatures.createInput(bodies, transform)
    try:
        move_input.defineAsFreeMove(transform)
    except Exception:
        pass
    move_feature = component.features.moveFeatures.add(move_input)
    move_feature.name = "{}{}".format(feature_prefix, sanitize_token(getattr(body, "name", "body"), limit=40))
    return move_feature


def _body_center_point_cm(body):
    bbox = body.boundingBox
    return adsk.core.Point3D.create(
        (bbox.minPoint.x + bbox.maxPoint.x) / 2.0,
        (bbox.minPoint.y + bbox.maxPoint.y) / 2.0,
        (bbox.minPoint.z + bbox.maxPoint.z) / 2.0,
    )


def _rotate_body_about_world_x(component, body, degrees, feature_prefix="UCP_ROTATE_X_"):
    transform = adsk.core.Matrix3D.create()
    transform.setToRotation(
        math.radians(float(degrees)),
        adsk.core.Vector3D.create(1.0, 0.0, 0.0),
        _body_center_point_cm(body),
    )
    return _move_body_rigid_transform(component, body, transform, feature_prefix=feature_prefix)


def _rotate_body_about_world_axis(component, body, axis_name, degrees, feature_prefix="UCP_ROTATE_"):
    axis_name = str(axis_name or "").upper()
    if axis_name == "Y":
        axis = adsk.core.Vector3D.create(0.0, 1.0, 0.0)
    elif axis_name == "Z":
        axis = adsk.core.Vector3D.create(0.0, 0.0, 1.0)
    else:
        axis = adsk.core.Vector3D.create(1.0, 0.0, 0.0)
    transform = adsk.core.Matrix3D.create()
    transform.setToRotation(math.radians(float(degrees)), axis, _body_center_point_cm(body))
    return _move_body_rigid_transform(component, body, transform, feature_prefix=feature_prefix)


def _oh_collect_bp_grooves(result):
    features = result.get("features")
    if not isinstance(features, list):
        return []
    grooves = []
    for feature in features:
        if not isinstance(feature, dict):
            continue
        groove = feature.get("bp_groove")
        if isinstance(groove, dict):
            grooves.append((feature, groove))
    return grooves


def _oh_collect_hinge_holes_by_board(result):
    features = result.get("features")
    if not isinstance(features, list):
        return {}
    by_board = {}
    for feature in features:
        if not isinstance(feature, dict):
            continue
        if feature.get("purpose") != "hinge" or feature.get("axis") != "Y":
            continue
        board_id = feature.get("boardId")
        if not isinstance(board_id, str) or not board_id:
            continue
        by_board.setdefault(board_id, []).append(feature)
    return by_board


def _oh_collect_features_by_type(result, feature_type):
    features = result.get("features")
    if not isinstance(features, list):
        return []
    return [
        feature for feature in features
        if isinstance(feature, dict) and str(feature.get("type") or "") == feature_type
    ]


def _oh_cut_bp_grooves(component, bp_body, bp_board, result):
    bp_bbox = _board_bbox(bp_board)
    if not bp_body or not bp_bbox:
        return []
    rows = []
    top_z = bp_bbox["z1"]
    for feature, groove in _oh_collect_bp_grooves(result):
        groove_id = str(groove.get("id") or feature.get("id") or "bp_groove")
        try:
            x = groove.get("x")
            y = groove.get("y")
            z = groove.get("z")
            if not (isinstance(x, list) and isinstance(y, list) and len(x) >= 2 and len(y) >= 2):
                raise ValueError("missing groove x/y range")
            x0, x1 = float(x[0]), float(x[1])
            y0, y1 = float(y[0]), float(y[1])
            depth = abs(float(z[1]) - float(z[0])) if isinstance(z, list) and len(z) >= 2 else _as_float(groove.get("depth_z"))
            depth = depth if depth and depth > 0 else max(0.0, bp_bbox["z1"] - bp_bbox["z0"]) / 2.0
            clamped_x = _clamp_range(x0, x1, bp_bbox["x0"], bp_bbox["x1"])
            clamped_y = _clamp_range(y0, y1, bp_bbox["y0"], bp_bbox["y1"])
            if clamped_x is None or clamped_y is None:
                rows.append({"featureId": groove_id, "status": "skipped", "reason": "groove outside BP bbox"})
                continue
            x0, x1 = clamped_x
            y0, y1 = clamped_y
            effective_depth = min(depth, bp_bbox["z1"] - bp_bbox["z0"])
            construction = component.constructionPlanes
            plane_input = construction.createInput()
            plane_input.setByOffset(component.xYConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(top_z)))
            top_plane = construction.add(plane_input)
            sketch = component.sketches.add(top_plane)
            sketch.name = "OH_BP_GROOVE_{}".format(sanitize_token(groove_id, limit=50))
            p0 = sketch.modelToSketchSpace(adsk.core.Point3D.create(mm_to_cm(x0), mm_to_cm(y0), mm_to_cm(top_z)))
            p1 = sketch.modelToSketchSpace(adsk.core.Point3D.create(mm_to_cm(x1), mm_to_cm(y1), mm_to_cm(top_z)))
            sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
            profile = _largest_profile(sketch)
            if profile is None:
                rows.append({"featureId": groove_id, "status": "failed", "reason": "no closed BP groove profile"})
                continue
            extrudes = component.features.extrudeFeatures
            ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
            ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(effective_depth)))
            try:
                participants = adsk.core.ObjectCollection.create()
                participants.add(bp_body)
                ext_input.participantBodies = participants
            except Exception:
                pass
            cut = extrudes.add(ext_input)
            cut.name = "OH_BP_GROOVE_CUT_{}".format(sanitize_token(groove_id, limit=50))
            rows.append({"featureId": groove_id, "status": "created", "xRange": [x0, x1], "yRange": [y0, y1], "depth": effective_depth})
        except Exception as ex:
            rows.append({"featureId": groove_id, "status": "failed", "reason": str(ex)})
    return rows


def _oh_cut_xy_rect_features(component, body, board, features, cut_name):
    bbox = _board_bbox(board)
    if not body or not bbox:
        return []
    rows = []
    top_z = bbox["z1"]
    board_thickness = max(0.0, bbox["z1"] - bbox["z0"])
    for feature in features or []:
        feature_id = str(feature.get("id") or cut_name)
        try:
            x = feature.get("x")
            y = feature.get("y")
            if not (isinstance(x, list) and len(x) >= 2 and isinstance(y, list) and len(y) >= 2):
                raise ValueError("missing x/y range")
            clamped_x = _clamp_range(float(x[0]), float(x[1]), bbox["x0"], bbox["x1"])
            clamped_y = _clamp_range(float(y[0]), float(y[1]), bbox["y0"], bbox["y1"])
            if clamped_x is None or clamped_y is None:
                rows.append({"featureId": feature_id, "status": "skipped", "reason": "cut outside board bbox"})
                continue
            depth = board_thickness if feature.get("through") else _as_float(feature.get("depth"))
            effective_depth = min(board_thickness, depth if depth and depth > 0 else board_thickness)
            construction = component.constructionPlanes
            plane_input = construction.createInput()
            plane_input.setByOffset(
                component.xYConstructionPlane,
                adsk.core.ValueInput.createByReal(mm_to_cm(top_z)),
            )
            plane = construction.add(plane_input)
            sketch = component.sketches.add(plane)
            sketch.name = "{}_{}".format(cut_name, sanitize_token(feature_id, limit=50))
            p0 = sketch.modelToSketchSpace(adsk.core.Point3D.create(
                mm_to_cm(clamped_x[0]), mm_to_cm(clamped_y[0]), mm_to_cm(top_z),
            ))
            p1 = sketch.modelToSketchSpace(adsk.core.Point3D.create(
                mm_to_cm(clamped_x[1]), mm_to_cm(clamped_y[1]), mm_to_cm(top_z),
            ))
            sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
            profile = _largest_profile(sketch)
            if profile is None:
                raise ValueError("no closed cut profile")
            extrudes = component.features.extrudeFeatures
            ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
            ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(effective_depth)))
            participant_error = _set_single_body_participants(ext_input, body)
            if participant_error:
                raise RuntimeError("participantBodies isolation failed: {}".format(participant_error))
            cut = extrudes.add(ext_input)
            cut.name = "{}_FEAT_{}".format(cut_name, sanitize_token(feature_id, limit=50))
            rows.append({
                "featureId": feature_id,
                "status": "created",
                "xRange": list(clamped_x),
                "yRange": list(clamped_y),
                "depth": effective_depth,
            })
        except Exception as ex:
            rows.append({"featureId": feature_id, "status": "failed", "reason": str(ex)})
    return rows


def _oh_cut_divider_side_grooves(component, body, board, features):
    bbox = _board_bbox(board)
    if not body or not bbox:
        return []
    rows = []
    board_thickness = max(0.0, bbox["x1"] - bbox["x0"])
    for feature in features or []:
        feature_id = str(feature.get("id") or "rangehood_divider_side_groove")
        try:
            y = feature.get("y")
            z = feature.get("z")
            if not (isinstance(y, list) and len(y) >= 2 and isinstance(z, list) and len(z) >= 2):
                raise ValueError("missing y/z range")
            clamped_y = _clamp_range(float(y[0]), float(y[1]), bbox["y0"], bbox["y1"])
            clamped_z = _clamp_range(float(z[0]), float(z[1]), bbox["z0"], bbox["z1"])
            if clamped_y is None or clamped_z is None:
                rows.append({"featureId": feature_id, "status": "skipped", "reason": "groove outside divider bbox"})
                continue
            face = str(feature.get("face") or "+X").upper()
            from_positive_x = face == "+X"
            plane_x = bbox["x1"] if from_positive_x else bbox["x0"]
            requested_depth = _as_float(feature.get("depth"))
            effective_depth = min(
                board_thickness,
                requested_depth if requested_depth and requested_depth > 0 else board_thickness / 2.0,
            )
            construction = component.constructionPlanes
            plane_input = construction.createInput()
            plane_input.setByOffset(
                component.yZConstructionPlane,
                adsk.core.ValueInput.createByReal(mm_to_cm(plane_x)),
            )
            plane = construction.add(plane_input)
            sketch = component.sketches.add(plane)
            sketch.name = "OH_RGHD_D_GROOVE_{}".format(sanitize_token(feature_id, limit=50))
            p0 = sketch.modelToSketchSpace(adsk.core.Point3D.create(
                mm_to_cm(plane_x), mm_to_cm(clamped_y[0]), mm_to_cm(clamped_z[0]),
            ))
            p1 = sketch.modelToSketchSpace(adsk.core.Point3D.create(
                mm_to_cm(plane_x), mm_to_cm(clamped_y[1]), mm_to_cm(clamped_z[1]),
            ))
            sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
            profile = _largest_profile(sketch)
            if profile is None:
                raise ValueError("no closed side-groove profile")
            extrudes = component.features.extrudeFeatures
            ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
            signed_depth = -effective_depth if from_positive_x else effective_depth
            ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(signed_depth)))
            participant_error = _set_single_body_participants(ext_input, body)
            if participant_error:
                raise RuntimeError("participantBodies isolation failed: {}".format(participant_error))
            cut = extrudes.add(ext_input)
            cut.name = "OH_RGHD_D_GROOVE_FEAT_{}".format(sanitize_token(feature_id, limit=50))
            rows.append({
                "featureId": feature_id,
                "status": "created",
                "face": face,
                "yRange": list(clamped_y),
                "zRange": list(clamped_z),
                "depth": effective_depth,
            })
        except Exception as ex:
            rows.append({"featureId": feature_id, "status": "failed", "reason": str(ex)})
    return rows


def _oh_cut_hinge_holes(component, board, body, hinge_features):
    bbox = _board_bbox(board)
    if not bbox or not body:
        return []
    rows = []
    plane_y = bbox["y1"]
    for feature in hinge_features or []:
        feature_id = str(feature.get("id") or "hinge")
        try:
            center = feature.get("center")
            if not (isinstance(center, list) and len(center) >= 2):
                raise ValueError("missing hinge center")
            x = bbox["x0"] + float(center[0])
            z = bbox["z0"] + float(center[1])
            diameter = _as_float(feature.get("diameter")) or 35.0
            depth = _as_float(feature.get("depth")) or max(0.0, bbox["y1"] - bbox["y0"])
            depth = min(depth, max(0.0, bbox["y1"] - bbox["y0"]))
            construction = component.constructionPlanes
            plane_input = construction.createInput()
            plane_input.setByOffset(component.xZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(plane_y)))
            back_plane = construction.add(plane_input)
            sketch = component.sketches.add(back_plane)
            sketch.name = "OH_HINGE_{}".format(sanitize_token(feature_id, limit=50))
            center_model = adsk.core.Point3D.create(mm_to_cm(x), mm_to_cm(plane_y), mm_to_cm(z))
            center_sketch = sketch.modelToSketchSpace(center_model)
            sketch.sketchCurves.sketchCircles.addByCenterRadius(center_sketch, mm_to_cm(diameter / 2.0))
            profile = _largest_profile(sketch)
            if profile is None:
                rows.append({"featureId": feature_id, "status": "failed", "reason": "no closed hinge cup profile"})
                continue
            extrudes = component.features.extrudeFeatures
            ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
            ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(depth)))
            try:
                participants = adsk.core.ObjectCollection.create()
                participants.add(body)
                ext_input.participantBodies = participants
            except Exception:
                pass
            cut = extrudes.add(ext_input)
            cut.name = "OH_HINGE_CUP_CUT_{}".format(sanitize_token(feature_id, limit=50))
            rows.append({"featureId": feature_id, "status": "created", "faceY": plane_y, "direction": "-Y", "center": [x, z], "diameter": diameter, "depth": depth})
        except Exception as ex:
            rows.append({"featureId": feature_id, "status": "failed", "reason": str(ex)})
    return rows


def _oh_shift_dividers_z(component, bodies_by_id, boards_by_id, dz_mm=30.0, components_by_id=None):
    rows = []
    components_by_id = components_by_id or {}
    for board_id, board in boards_by_id.items():
        if str(board.get("category") or "").lower() != "divider":
            continue
        body = bodies_by_id.get(board_id)
        if not body:
            rows.append({"boardId": board_id, "status": "skipped", "reason": "body not found"})
            continue
        try:
            move_body_by_mm(components_by_id.get(board_id) or component, body, 0.0, 0.0, dz_mm, feature_prefix="OH_DIVIDER_Z_")
            rows.append({"boardId": board_id, "status": "created", "dz": dz_mm})
        except Exception as ex:
            rows.append({"boardId": board_id, "status": "failed", "dz": dz_mm, "reason": str(ex)})
    return rows


def _oh_shift_named_boards_z(component, bodies_by_id, board_ids, dz_mm, feature_prefix, components_by_id=None):
    rows = []
    components_by_id = components_by_id or {}
    for board_id in board_ids:
        body = bodies_by_id.get(board_id)
        if not body:
            rows.append({"boardId": board_id, "status": "skipped", "reason": "body not found"})
            continue
        try:
            move_body_by_mm(components_by_id.get(board_id) or component, body, 0.0, 0.0, dz_mm, feature_prefix=feature_prefix)
            rows.append({"boardId": board_id, "status": "created", "dz": dz_mm})
        except Exception as ex:
            rows.append({"boardId": board_id, "status": "failed", "dz": dz_mm, "reason": str(ex)})
    return rows


def _oh_shift_front_panels_z(component, bodies_by_id, boards_by_id, dz_mm=15.0, components_by_id=None):
    rows = []
    components_by_id = components_by_id or {}
    for board_id, board in boards_by_id.items():
        if str(board.get("category") or "").lower() != "front_panel":
            continue
        body = bodies_by_id.get(board_id)
        if not body:
            rows.append({"boardId": board_id, "status": "skipped", "reason": "body not found"})
            continue
        try:
            move_body_by_mm(components_by_id.get(board_id) or component, body, 0.0, 0.0, dz_mm, feature_prefix="OH_FP_Z_")
            rows.append({"boardId": board_id, "status": "created", "dz": dz_mm})
        except Exception as ex:
            rows.append({"boardId": board_id, "status": "failed", "dz": dz_mm, "reason": str(ex)})
    return rows


def _oh_result_params(result):
    params = result.get("params") if isinstance(result.get("params"), dict) else {}
    debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}
    legacy = debug.get("legacyGeometry") if isinstance(debug.get("legacyGeometry"), dict) else {}
    cabinet = legacy.get("cabinet") if isinstance(legacy.get("cabinet"), dict) else {}
    manufacturing = legacy.get("manufacturing") if isinstance(legacy.get("manufacturing"), dict) else {}
    cabinet_depth = _as_float(params.get("cabinetDepth"))
    if cabinet_depth is None:
        cabinet_depth = _as_float(cabinet.get("Cd")) or 0.0
    fg_width = _as_float(params.get("featureWidth"))
    if fg_width is None:
        fg_width = _as_float(manufacturing.get("FGw")) or 15.0
    top_clearance = _as_float(params.get("topClearanceHeight"))
    if top_clearance is None:
        top_clearance = _as_float(manufacturing.get("TCH")) or 40.0
    clearance = _as_float(params.get("clearance"))
    if clearance is None:
        clearance = _as_float(manufacturing.get("FitClearance")) or 2.5
    return {
        "cabinetDepth": cabinet_depth,
        "fgWidth": fg_width,
        "topClearanceHeight": top_clearance,
        "clearance": clearance,
    }


def _oh_placement_formula_summary(result):
    params = _oh_result_params(result)
    cd = params["cabinetDepth"]
    fg = params["fgWidth"]
    tch = params["topClearanceHeight"]
    clearance = params["clearance"]
    return {
        "units": "mm",
        "inputs": {
            "Cd": cd,
            "FGw": fg,
            "TCH": tch,
            "clearance": clearance,
        },
        "basePlacementOffsets": {
            "T1": {"dx": 0.0, "dy": tch - 1.0, "dz": 0.0, "formula": "dy=TCH-1"},
            "T2": {"dx": 0.0, "dy": tch - 1.0, "dz": 0.0, "formula": "dy=TCH-1"},
        },
        "postprocessOffsets": {
            "BP": {"dx": 0.0, "dy": 0.0, "dz": fg, "formula": "dz=FGw"},
            "T1": {"dx": 0.0, "dy": 0.0, "dz": fg, "formula": "dz=FGw"},
            "T2": {"dx": 0.0, "dy": 0.0, "dz": fg, "formula": "dz=FGw"},
            "Divider": {"dx": 0.0, "dy": 0.0, "dz": 0.0, "formula": "baked into board z0=2*FGw"},
            "FrontPanel": {"dx": 0.0, "dy": 0.0, "dz": fg, "formula": "dz=FGw"},
            "T3": {"dx": 0.0, "dy": 0.0, "dz": -(tch + fg - 14.0) + fg, "formula": "dy=0, dz=-(TCH+FGw-14)+FGw"},
            "T4": {"dx": 0.0, "dy": cd - (2.0 * fg + clearance), "dz": -clearance, "formula": "dy=Cd-(2*FGw+clearance), dz=-clearance"},
        },
        "rotations": {
            "T4": {"axis": "X", "degrees": 90.0},
        },
    }


def _oh_profile_axis_range(board, axis_key):
    vector = board.get("profileVector") if isinstance(board, dict) else None
    if not isinstance(vector, list):
        return None
    values = []
    for point in vector:
        if isinstance(point, dict) and _as_float(point.get(axis_key)) is not None:
            values.append(float(point.get(axis_key)))
    if not values:
        return None
    return min(values), max(values)


def _oh_t3_depth(board):
    y_range = _oh_profile_axis_range(board, "y")
    if y_range:
        return max(0.0, y_range[1] - y_range[0])
    bbox = _board_bbox(board)
    if bbox:
        return min(90.0, max(0.0, bbox["y1"] - bbox["y0"]))
    return 90.0


def _oh_top_panel_translation_specs(result, boards_by_id):
    params = _oh_result_params(result)
    cd = params["cabinetDepth"]
    fg = params["fgWidth"]
    tch = params["topClearanceHeight"]
    clearance = params["clearance"]
    t3_depth = _oh_t3_depth(boards_by_id.get("T3", {}))
    return (
        {
            "boardId": "T3",
            "dx": 0.0,
            "dy": 0.0,
            "dz": -(tch + fg - 14.0) + fg,
            "formula": "dy=0, dz=-(TCH+FGw-14)+FGw",
            "inputs": {"Cd": cd, "T3Depth": t3_depth, "TCH": tch, "FGw": fg},
        },
        {
            "boardId": "T4",
            "dx": 0.0,
            "dy": cd - (2.0 * fg + clearance),
            "dz": -clearance,
            "formula": "dy=Cd-(2*FGw+clearance), dz=-clearance",
            "inputs": {"Cd": cd, "FGw": fg, "clearance": clearance},
        },
    )


def _oh_cut_t3_led_grooves(component, t3_body, t3_board, result):
    """Cut LED T-groove on Overhead T3 top face (opens upward).

    Same Fusion recipe as `_oh_cut_bp_grooves`: construction-plane sketch +
    setDistanceExtent(-depth) from the top face + participantBodies.
    Runs before T3 postprocess translation while the body is still at design Z.
    """
    t3_bbox = _board_bbox(t3_board)
    if not t3_body or not t3_bbox:
        return [{
            "featureId": "T3_led_groove",
            "status": "skipped",
            "reason": "missing T3 body or bbox",
        }]

    features = _collect_led_groove_features(result).get("T3") or []
    if not features:
        feature_types = []
        for feature in (result.get("features") or []):
            if isinstance(feature, dict):
                feature_types.append({
                    "id": feature.get("id"),
                    "type": feature.get("type"),
                    "targetBoardId": feature.get("targetBoardId"),
                })
        return [{
            "featureId": "T3_led_groove",
            "status": "skipped",
            "reason": "no T3 LED features in result",
            "featureCount": len(result.get("features") or []),
            "featureTypesPreview": feature_types[:12],
        }]

    rows = []
    thickness = max(0.0, t3_bbox["z1"] - t3_bbox["z0"])
    top_z = t3_bbox["z1"]
    board_width = max(0.0, t3_bbox["x1"] - t3_bbox["x0"])

    for feature in features:
        feature_id = str(feature.get("id") or "T3_led_groove")
        depth = _as_float(feature.get("depth"))
        depth = depth if depth is not None and depth > 0 else 6.5
        effective_depth = min(depth, max(0.0, thickness - 0.2))
        if effective_depth <= 0:
            rows.append({
                "featureId": feature_id,
                "status": "skipped",
                "reason": "non-positive groove depth",
                "thickness": thickness,
            })
            continue

        segments = _led_groove_segments(feature)
        if not segments:
            rows.append({
                "featureId": feature_id,
                "status": "skipped",
                "reason": "no main/branch segments",
            })
            continue

        created = 0
        failures = []
        segment_rows = []
        for label, segment in segments:
            segment_id = "{}_{}".format(feature_id, label)
            try:
                cut_segment = (
                    _mirror_led_segment_x(segment, board_width)
                    if feature.get("adapterMirrorX") is True
                    else segment
                )
                rect = _led_segment_world_rect(t3_bbox, cut_segment)
                if rect is None:
                    failures.append("{}: outside bbox".format(label))
                    segment_rows.append({"id": segment_id, "status": "skipped", "reason": "outside bbox"})
                    continue
                x0, y0, x1, y1 = rect
                construction = component.constructionPlanes
                plane_input = construction.createInput()
                plane_input.setByOffset(
                    component.xYConstructionPlane,
                    adsk.core.ValueInput.createByReal(mm_to_cm(top_z)),
                )
                cut_plane = construction.add(plane_input)
                sketch = component.sketches.add(cut_plane)
                sketch.name = "OH_T3_LED_{}".format(sanitize_token(segment_id, limit=50))
                p0 = sketch.modelToSketchSpace(
                    adsk.core.Point3D.create(mm_to_cm(x0), mm_to_cm(y0), mm_to_cm(top_z))
                )
                p1 = sketch.modelToSketchSpace(
                    adsk.core.Point3D.create(mm_to_cm(x1), mm_to_cm(y1), mm_to_cm(top_z))
                )
                sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
                profile = _largest_profile(sketch)
                if profile is None:
                    failures.append("{}: no closed profile".format(label))
                    segment_rows.append({"id": segment_id, "status": "failed", "reason": "no closed profile"})
                    continue
                extrudes = component.features.extrudeFeatures
                ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
                # Negative distance: into the board from the top face (opens upward).
                ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(effective_depth)))
                participant_error = _set_single_body_participants(ext_input, t3_body)
                # T3 lives in its own child component, so a cut without
                # participants still cannot reach T1/T2. Prefer isolation, but
                # never leave an orphan sketch with zero material removed.
                used_participants = participant_error is None
                cut = extrudes.add(ext_input)
                cut.name = "OH_T3_LED_CUT_{}".format(sanitize_token(segment_id, limit=50))
                created += 1
                segment_rows.append({
                    "id": segment_id,
                    "status": "created",
                    "adapterMirrorX": feature.get("adapterMirrorX") is True,
                    "xRange": [x0, x1],
                    "yRange": [y0, y1],
                    "planeZ": top_z,
                    "depth": effective_depth,
                    "isolatedBody": used_participants,
                    **({"participantWarning": participant_error} if participant_error else {}),
                })
            except Exception as ex:
                # Direction fallback: some Fusion builds treat the construction
                # plane normal such that negative distance goes into empty space.
                try:
                    extrudes = component.features.extrudeFeatures
                    profile = _largest_profile(sketch) if "sketch" in locals() and sketch is not None else None
                    if profile is None:
                        raise ex
                    for signed in (-effective_depth, effective_depth):
                        try:
                            ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
                            ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(signed)))
                            _set_single_body_participants(ext_input, t3_body)
                            cut = extrudes.add(ext_input)
                            cut.name = "OH_T3_LED_CUT_{}".format(sanitize_token(segment_id, limit=50))
                            created += 1
                            segment_rows.append({
                                "id": segment_id,
                                "status": "created",
                                "reason": "recovered_signed_distance_{}".format(signed),
                                "xRange": [x0, x1],
                                "yRange": [y0, y1],
                                "planeZ": top_z,
                                "depth": effective_depth,
                            })
                            break
                        except Exception:
                            continue
                    else:
                        raise ex
                except Exception as ex2:
                    failures.append("{}: {}".format(label, ex2))
                    segment_rows.append({"id": segment_id, "status": "failed", "reason": str(ex2)})

        if created == len(segments):
            rows.append({
                "featureId": feature_id,
                "targetBoardId": "T3",
                "status": "created",
                "face": "top",
                "opening": "upward",
                "depth": effective_depth,
                "planeZMm": top_z,
                "segmentCount": len(segments),
                "createdSegments": created,
                "segments": segment_rows,
            })
        elif created > 0:
            rows.append({
                "featureId": feature_id,
                "targetBoardId": "T3",
                "status": "failed",
                "reason": "partial LED groove cut: {}".format("; ".join(failures)),
                "segmentCount": len(segments),
                "createdSegments": created,
                "segments": segment_rows,
            })
        else:
            rows.append({
                "featureId": feature_id,
                "targetBoardId": "T3",
                "status": "failed",
                "reason": "; ".join(failures) or "all LED segments failed",
                "segmentCount": len(segments),
                "createdSegments": 0,
                "segments": segment_rows,
            })
    return rows


def _oh_postprocess_bodies(component, result, bodies_by_id, boards_by_id, components_by_id=None):
    rows = {
        "bpGrooveCuts": [],
        "rangehoodBpCutouts": [],
        "rangehoodTopGrooves": [],
        "rangehoodDividerSideGrooves": [],
        "uConnectorBpGrooves": [],
        "uConnectorT3Grooves": [],
        "ledGrooveCuts": [],
        "hingeCuts": [],
        "rotations": [],
        "topPanelTranslations": [],
        "frontPanelZShifts": [],
        "dividerZShifts": [],
        "supportZShifts": [],
    }
    components_by_id = components_by_id or {}
    oh_params = _oh_result_params(result)
    fg_width = oh_params["fgWidth"]
    # Divider Z is baked into board z0 = 2*FGw in the overhead generator.
    rows["dividerZShifts"] = []
    bp_board = boards_by_id.get("BP")
    if bp_board:
        bp_component = components_by_id.get("BP") or component
        bp_body = bodies_by_id.get("BP")
        rows["bpGrooveCuts"] = _oh_cut_bp_grooves(bp_component, bp_body, bp_board, result)
        rows["rangehoodBpCutouts"] = _oh_cut_xy_rect_features(
            bp_component,
            bp_body,
            bp_board,
            _oh_collect_features_by_type(result, "rangehood_bp_cutout"),
            "OH_RGHD_BP_CUTOUT",
        )
        rows["uConnectorBpGrooves"] = _oh_cut_xy_rect_features(
            bp_component,
            bp_body,
            bp_board,
            _oh_collect_features_by_type(result, "u_connector_bp_groove"),
            "UOH_CONNECTOR_BP_GROOVE",
        )

    rangehood_top_board = boards_by_id.get("RGHD_TOP")
    if rangehood_top_board:
        rows["rangehoodTopGrooves"] = _oh_cut_xy_rect_features(
            components_by_id.get("RGHD_TOP") or component,
            bodies_by_id.get("RGHD_TOP"),
            rangehood_top_board,
            _oh_collect_features_by_type(result, "rangehood_top_divider_groove"),
            "OH_RGHD_TOP_GROOVE",
        )

    side_grooves_by_board = {}
    for feature in _oh_collect_features_by_type(result, "rangehood_divider_side_groove"):
        target_id = str(feature.get("targetBoardId") or "")
        if target_id:
            side_grooves_by_board.setdefault(target_id, []).append(feature)
    for board_id, features in side_grooves_by_board.items():
        rows["rangehoodDividerSideGrooves"].extend(_oh_cut_divider_side_grooves(
            components_by_id.get(board_id) or component,
            bodies_by_id.get(board_id),
            boards_by_id.get(board_id),
            features,
        ))

    t3_board = boards_by_id.get("T3")
    if t3_board:
        t3_component = components_by_id.get("T3") or component
        t3_body = bodies_by_id.get("T3")
        rows["uConnectorT3Grooves"] = _oh_cut_xy_rect_features(
            t3_component,
            t3_body,
            t3_board,
            _oh_collect_features_by_type(result, "u_connector_t3_through_groove"),
            "UOH_CONNECTOR_T3_GROOVE",
        )
        # Cut LED on T3 top face before the top-panel Z translation.
        rows["ledGrooveCuts"] = _oh_cut_t3_led_grooves(t3_component, t3_body, t3_board, result)

    hinge_by_board = _oh_collect_hinge_holes_by_board(result)
    for board_id, features in hinge_by_board.items():
        board = boards_by_id.get(board_id)
        body = bodies_by_id.get(board_id)
        rows["hingeCuts"].extend(_oh_cut_hinge_holes(components_by_id.get(board_id) or component, board, body, features))

    for board_id, axis_name, degrees in (("T4", "X", 90.0),):
        body = bodies_by_id.get(board_id)
        if not body:
            rows["rotations"].append({"boardId": board_id, "status": "skipped", "reason": "body not found"})
            continue
        try:
            _rotate_body_about_world_axis(components_by_id.get(board_id) or component, body, axis_name, degrees, feature_prefix="OH_ROTATE_{}_".format(axis_name))
            rows["rotations"].append({"boardId": board_id, "axis": axis_name, "degrees": degrees, "status": "created"})
        except Exception as ex:
            rows["rotations"].append({"boardId": board_id, "axis": axis_name, "degrees": degrees, "status": "failed", "reason": str(ex)})

    for spec in _oh_top_panel_translation_specs(result, boards_by_id):
        board_id = spec["boardId"]
        dx_mm = spec["dx"]
        dy_mm = spec["dy"]
        dz_mm = spec["dz"]
        body = bodies_by_id.get(board_id)
        if not body:
            rows["topPanelTranslations"].append({**spec, "status": "skipped", "reason": "body not found"})
            continue
        try:
            move_body_by_mm(components_by_id.get(board_id) or component, body, dx_mm, dy_mm, dz_mm, feature_prefix="OH_TOP_PANEL_PLACE_")
            rows["topPanelTranslations"].append({
                **spec,
                "status": "created",
            })
        except Exception as ex:
            rows["topPanelTranslations"].append({
                **spec,
                "status": "failed",
                "reason": str(ex),
            })
    rows["frontPanelZShifts"] = _oh_shift_front_panels_z(component, bodies_by_id, boards_by_id, dz_mm=fg_width, components_by_id=components_by_id)
    rows["supportZShifts"] = _oh_shift_named_boards_z(component, bodies_by_id, ("BP", "T1", "T2"), fg_width, "OH_SUPPORT_Z_", components_by_id=components_by_id)
    return rows


def create_rough_bodies_from_board_result(
    fusion_adapter,
    result,
    module_name="generalTall",
    body_prefix="GT",
    run_label=None,
    placement_feature_prefix="GT_PLACE_",
    move_feature_prefix="GT_MOVE_",
    align_feature_prefix="GT_ALIGN_",
    enable_zi_groove_cuts=False,
    enable_overhead_postprocess=False,
    avoidance_z_shift_mm=0.0,
    create_container_component=False,
    component_prefix=None,
    component_name=None,
    origin_x_mm=None,
    origin_y_mm=None,
    avoid_existing_origin=True,
    origin_rotation_deg=0.0,
    add_as_new=True,
):
    # None = "auto": place at the generation-zone centre from the saved layout.
    # This also covers callers that predate the origin parameters, because this
    # adapter is importlib.reload-ed on every call. When a work-zone or explicit
    # origin is used, z is real model z=0 instead of legacy MODEL_Z_OFFSET_MM.
    placement_debug = {
        "adapterBuild": ADAPTER_BUILD,
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "module": str(module_name),
        "originParam": [origin_x_mm, origin_y_mm],
        "createContainer": bool(create_container_component),
        "componentName": component_name,
        "addAsNewCabinet": bool(add_as_new),
    }
    origin_active = origin_x_mm is not None or origin_y_mm is not None
    if origin_x_mm is None and origin_y_mm is None:
        # Read the saved zone layout DIRECTLY (no work_zones import): Fusion's
        # module cache may hold a stale work_zones without the newer helpers,
        # and that stale import silently broke auto-centering before.
        try:
            root0 = fusion_adapter.get_root_component()
            attr = root0.attributes.itemByName("UnifiedCabinet", "workZoneLayout") if root0 else None
            placement_debug["layoutAttrFound"] = bool(attr and attr.value)
            if attr and attr.value:
                placement_debug["layoutRaw"] = str(attr.value)[:400]
                layout = json.loads(attr.value)
                rect = layout.get("generation") if isinstance(layout, dict) else None
                if isinstance(rect, dict):
                    origin_x_mm = (float(rect["x0"]) + float(rect["x1"])) / 2.0
                    origin_y_mm = (float(rect["y0"]) + float(rect["y1"])) / 2.0
                    origin_active = True
        except Exception as ex:
            placement_debug["layoutError"] = str(ex)
    origin_x_mm = float(origin_x_mm or 0.0)
    origin_y_mm = float(origin_y_mm or 0.0)
    origin_z_mm = 0.0 if origin_active else MODEL_Z_OFFSET_MM
    placement_debug["resolvedOrigin"] = [origin_x_mm, origin_y_mm, origin_z_mm]
    placement_debug["originActive"] = bool(origin_active)
    summary = {
        "createdBodies": 0,
        "skippedBoards": [],
        "createdBoardIds": [],
        "bodyAudit": [],
        "errors": [],
        "warnings": [],
        "runLabel": str(run_label or int(time.time() * 1000)),
        "adapterBuild": ADAPTER_BUILD,
        "sourceUsage": {"cutProfileVector": 0, "profileVector": 0, "bboxFallback": 0},
        "grooveCutsCreated": 0,
        "grooveCutsSkipped": 0,
        "grooveCutsFailed": 0,
        "ledGrooveCutsCreated": 0,
        "ledGrooveCutsSkipped": 0,
        "ledGrooveCutsFailed": 0,
        "bpGrooveCutsCreated": 0,
        "hingeCutsCreated": 0,
        "rotationOpsCreated": 0,
        "topPanelTranslationsCreated": 0,
        "frontPanelZShiftsCreated": 0,
        "dividerZShiftsCreated": 0,
        "supportZShiftsCreated": 0,
        "bodyComponentsCreated": 0,
        "bodyComponentNames": [],
        "avoidanceZShiftMm": float(max(0.0, avoidance_z_shift_mm)),
        "assemblyComponentName": None,
        "placementFormulas": _oh_placement_formula_summary(result) if enable_overhead_postprocess else {},
        "faceInitSummary": {
            "initializedCount": 0,
            "skippedCount": 0,
            "totalEdgeCount": 0,
            "totalSurfaceCount": 0,
            "boards": [],
        },
    }
    carcass_color_tag, carcass_color_name = extract_carcass_color_from_result(result)
    summary["carcassColor"] = carcass_color_tag
    summary["carcassColorName"] = carcass_color_name
    result_features = result.get("features") if isinstance(result.get("features"), list) else []
    root_comp = fusion_adapter.get_root_component()
    if not root_comp:
        summary["errors"].append("No active Fusion design/root component.")
        placement_debug["abort"] = "no_root_component"
        _write_placement_debug(placement_debug)
        return summary

    boards = result.get("boards")
    if not isinstance(boards, list):
        summary["errors"].append("{} result does not include boards list.".format(module_name))
        placement_debug["abort"] = "no_boards"
        _write_placement_debug(placement_debug)
        return summary
    boards_by_id = {str(board.get("id")): board for board in boards if isinstance(board, dict) and board.get("id")}
    bodies_by_id = {}
    components_by_id = {}
    panel_metadata_by_id = {}
    zi_grooves_by_target = _collect_zi_groove_features(result) if enable_zi_groove_cuts else {}
    led_grooves_by_target = (
        _collect_led_groove_features(result)
        if module_name in ("generalTall", "overhead")
        else {}
    )
    result_debug = result.get("debug") if isinstance(result.get("debug"), dict) else {}

    # Lock existing assemblies (Kitchen, Lounge, earlier OHC) before any
    # timeline edit. Without this, Fusion recomputes and those poses rewind.
    _capture_position_snapshot(root_comp)
    deleted_previous = {"occurrences": 0, "bodies": 0}
    if not add_as_new:
        deleted_previous = _delete_previous_module_assemblies(root_comp, module_name)
        _capture_position_snapshot(root_comp)
    summary["addAsNewCabinet"] = bool(add_as_new)
    summary["deletedPrevious"] = deleted_previous
    placement_debug["deletedPrevious"] = deleted_previous

    # Spawn avoidance: shift +X in furniture-sized slots when the target spot
    # already holds generated content.
    footprint = None
    try:
        bboxes = [_board_bbox(board) for board in boards if isinstance(board, dict)]
        bboxes = [bb for bb in bboxes if bb]
        if bboxes:
            footprint = (
                min(bb["x0"] for bb in bboxes),
                max(bb["x1"] for bb in bboxes),
                min(bb["y0"] for bb in bboxes),
                max(bb["y1"] for bb in bboxes),
            )
    except Exception:
        footprint = None
    if avoid_existing_origin:
        origin_x_mm, origin_y_mm, avoidance_info = _avoid_existing_at_origin(root_comp, origin_x_mm, origin_y_mm, footprint)
    else:
        avoidance_info = {"shifted": False, "disabled": True, "reason": "nested composite run"}
    summary["originAvoidance"] = avoidance_info
    placement_debug["avoidance"] = avoidance_info
    placement_debug["resolvedOrigin"] = [origin_x_mm, origin_y_mm, origin_z_mm]
    if avoidance_info.get("shifted"):
        summary["warnings"].append(
            "Generation spot was occupied; assembly shifted +X by {:.0f} mm (slot {}).".format(
                avoidance_info.get("shiftXMm", 0.0), avoidance_info.get("slots", 0)
            )
        )

    container, container_warning, assembly_component_name = _new_container_component(
        root_comp,
        summary["runLabel"],
        module_name=module_name,
        create_component=create_container_component,
        component_prefix=component_prefix,
        component_name=component_name,
        origin_x_mm=origin_x_mm,
        origin_y_mm=origin_y_mm,
        origin_z_mm=origin_z_mm,
        origin_rotation_deg=origin_rotation_deg,
    )
    summary["assemblyComponentName"] = assembly_component_name
    summary["originOffsetMm"] = {
        "x": float(origin_x_mm or 0.0),
        "y": float(origin_y_mm or 0.0),
        "z": float(origin_z_mm),
        "rotationDeg": float(origin_rotation_deg or 0.0),
    }
    placement_debug["assemblyComponentName"] = assembly_component_name
    placement_debug["containerWarning"] = container_warning
    placement_debug["containerIsRoot"] = container is root_comp
    try:
        occurrences0 = root_comp.allOccurrencesByComponent(container) if container is not root_comp else None
        occurrence0 = occurrences0.item(0) if occurrences0 and occurrences0.count else None
        if occurrence0 is not None:
            translation0 = occurrence0.transform.translation
            placement_debug["containerTransformAfterCreateMm"] = [
                round(translation0.x * 10.0, 2), round(translation0.y * 10.0, 2), round(translation0.z * 10.0, 2),
            ]
    except Exception as ex:
        placement_debug["containerTransformAfterCreateError"] = str(ex)
    summary["_containerComponent"] = container
    if container_warning:
        summary["warnings"].append(container_warning)
    declarations = result.get("relationshipDeclarations") if isinstance(result, dict) else None
    if isinstance(declarations, list) and declarations and container is not root_comp:
        try:
            container.attributes.add(
                ATTRIBUTE_GROUP,
                "relationshipDeclarations",
                json.dumps(declarations, ensure_ascii=False, separators=(",", ":")),
            )
            summary["relationshipDeclarationCount"] = len(declarations)
        except Exception as ex:
            summary["warnings"].append("Could not write relationshipDeclarations on assembly: {}".format(ex))
    for index, board in enumerate(boards):
        board_id = str(board.get("id") or "board-{}".format(index + 1))
        bbox = _board_bbox(board)
        if not bbox:
            summary["skippedBoards"].append({"boardId": board_id, "reason": "missing_or_invalid_bbox"})
            continue

        width_x, depth_y, height_z = _rough_size_mm(bbox)
        audit_row = {
            "boardId": board_id,
            "bbox": bbox,
            "profilePlane": board.get("profilePlane"),
            "thicknessAxis": board.get("thicknessAxis"),
            "size": {"x": width_x, "y": depth_y, "z": height_z, "widthX": width_x, "depthY": depth_y, "heightZ": height_z},
        }
        if width_x <= 0 or depth_y <= 0 or height_z <= 0:
            summary["skippedBoards"].append({"boardId": board_id, "reason": "non_positive_dimension", "audit": audit_row})
            summary["bodyAudit"].append({**audit_row, "status": "skipped"})
            continue

        vector_source, raw_points = _vector_source_for_board(board)
        chosen_source = vector_source or "bboxFallback"
        body = None
        err = None
        target_component = container
        board_component_name = None
        # One board = one child component (assembly semantics), for EVERY module
        # that has a real assembly container (not the Part-document fallback).
        if create_container_component and container is not root_comp:
            board_component_name = board_component_label(
                assembly_component_name or body_prefix,
                board_id,
                fallback_assembly=body_prefix,
            )
            try:
                target_component = _new_child_component(container, board_component_name, module_name=module_name, board_id=board_id)
                components_by_id[board_id] = target_component
            except Exception as ex:
                summary["warnings"].append("Could not create child component for {}: {}. Using assembly component.".format(board_id, ex))
                target_component = container
        if vector_source:
            body, err = _add_profile_body(
                target_component,
                board_id,
                board,
                bbox,
                vector_source,
                raw_points,
                body_prefix=body_prefix,
                module_name=module_name,
                align_prefix=align_feature_prefix,
                display_name=board_component_name or board_component_label(
                    assembly_component_name or body_prefix, board_id, fallback_assembly=body_prefix
                ),
            )
            if err:
                summary["warnings"].append(
                    "Board {} {} failed: {}. Falling back to bbox.".format(board_id, vector_source, err)
                )
                chosen_source = "bboxFallback"
                body, err = _add_box_body(
                    target_component,
                    board_id,
                    bbox,
                    body_prefix=body_prefix,
                    module_name=module_name,
                    move_prefix=move_feature_prefix,
                    display_name=board_component_name or board_component_label(
                        assembly_component_name or body_prefix, board_id, fallback_assembly=body_prefix
                    ),
                )
        else:
            body, err = _add_box_body(
                target_component,
                board_id,
                bbox,
                body_prefix=body_prefix,
                module_name=module_name,
                move_prefix=move_feature_prefix,
                display_name=board_component_name or board_component_label(
                    assembly_component_name or body_prefix, board_id, fallback_assembly=body_prefix
                ),
            )

        if err or not body:
            summary["skippedBoards"].append({"boardId": board_id, "reason": "fusion_box_create_failed", "error": err or "unknown"})
            summary["bodyAudit"].append({**audit_row, "source": chosen_source, "status": "failed", "error": err or "unknown"})
            continue

        oh_params = _oh_result_params(result) if enable_overhead_postprocess else None
        dx_mm, dy_mm, dz_mm = _placement_offset_mm(
            board,
            result_debug,
            avoidance_z_shift_mm=avoidance_z_shift_mm,
            module_name=module_name,
            result_params=oh_params,
        )
        if abs(dx_mm) > 1e-6 or abs(dy_mm) > 1e-6 or abs(dz_mm) > 1e-6:
            move_body_by_mm(target_component, body, dx_mm, dy_mm, dz_mm, feature_prefix=placement_feature_prefix)

        panel_metadata = None
        panel_metadata_written = None
        if module_name == "overhead":
            panel_metadata, panel_metadata_written = _write_oh_panel_metadata(
                body, board, bbox, boards, summary["runLabel"],
                features=result.get("features") if isinstance(result.get("features"), list) else [],
                carcass_color=carcass_color_tag, carcass_color_name=carcass_color_name,
            )
            if not panel_metadata_written:
                summary["warnings"].append("Could not write panel metadata for overhead board {}.".format(board_id))
            # Face metadata is initialized after post-processing (groove/hinge
            # cuts) so the surface/edge/milling classification sees the final
            # machined geometry instead of the plain box.
            if panel_metadata_written:
                panel_metadata_by_id[board_id] = panel_metadata
        elif module_name == "generalTall":
            panel_metadata, panel_metadata_written = _write_gt_panel_metadata(
                body, board, bbox, summary["runLabel"],
                carcass_color=carcass_color_tag, carcass_color_name=carcass_color_name,
                features=result_features,
            )
            if not panel_metadata_written:
                summary["warnings"].append("Could not write panel metadata for generalTall board {}.".format(board_id))
            if panel_metadata_written:
                panel_metadata_by_id[board_id] = panel_metadata
        elif module_name in ("smallCabinet", "small_cabinet"):
            try:
                panel_metadata = build_panel_metadata(
                    "smallCabinet",
                    board,
                    bbox=bbox,
                    run_label=summary["runLabel"],
                    carcass_color=carcass_color_tag,
                    carcass_color_name=carcass_color_name,
                )
                panel_metadata_written = write_panel_metadata_to_body(body, panel_metadata)
            except Exception as ex:
                panel_metadata = None
                panel_metadata_written = False
                summary["warnings"].append("Small Cabinet metadata failed for {}: {}".format(board_id, ex))
            if not panel_metadata_written:
                summary["warnings"].append("Could not write panel metadata for smallCabinet board {}.".format(board_id))
            if panel_metadata_written:
                panel_metadata_by_id[board_id] = panel_metadata

        summary["createdBodies"] += 1
        summary["createdBoardIds"].append(board_id)
        bodies_by_id[board_id] = body
        summary["sourceUsage"][chosen_source] = summary["sourceUsage"].get(chosen_source, 0) + 1
        groove_cuts = []
        board_cut_component = components_by_id.get(board_id) or container
        if enable_zi_groove_cuts and _is_zi_board(board):
            for groove_feature in zi_grooves_by_target.get(board_id, []):
                # Cut inside the board's own component so the feature reaches
                # the body that now lives there; participantBodies keeps the
                # cut off neighboring workpieces.
                groove_row = _create_zi_groove_cut(
                    board_cut_component, board, bbox, groove_feature, boards_by_id, body=body
                )
                groove_cuts.append(groove_row)
                status = groove_row.get("status")
                if status == "created":
                    summary["grooveCutsCreated"] += 1
                elif status == "failed":
                    summary["grooveCutsFailed"] += 1
                    summary["warnings"].append(
                        "Zi groove cut failed for {}: {}".format(
                            groove_row.get("featureId"),
                            groove_row.get("reason") or "unknown",
                        )
                    )
                else:
                    summary["grooveCutsSkipped"] += 1

        led_cuts = []
        # Overhead BP LED is cut in _oh_postprocess_bodies (with bp_groove).
        # General Tall B3/T3 LED cuts run here during body creation.
        if module_name == "generalTall" and (
            board_id in ("B3", "T3") or str(board.get("boardType") or "") in ("B3", "T3")
        ):
            for led_feature in led_grooves_by_target.get(board_id, []):
                led_row = _create_led_groove_cut(
                    board_cut_component, body, board, bbox, led_feature
                )
                led_cuts.append(led_row)
                status = led_row.get("status")
                if status == "created":
                    summary["ledGrooveCutsCreated"] += 1
                elif status == "failed":
                    summary["ledGrooveCutsFailed"] += 1
                    summary["warnings"].append(
                        "LED groove cut failed for {}: {}".format(
                            led_row.get("featureId"),
                            led_row.get("reason") or "unknown",
                        )
                    )
                else:
                    summary["ledGrooveCutsSkipped"] += 1

        summary["bodyAudit"].append({
            **audit_row,
            "source": chosen_source,
            "status": "created",
            "bodyName": body.name,
            "componentName": board_component_name,
            "placementOffset": {"x": dx_mm, "y": dy_mm, "z": dz_mm},
            "grooveCuts": groove_cuts,
            "ledGrooveCuts": led_cuts,
            "panelMetadataWritten": panel_metadata_written,
            "panelMetadata": panel_metadata,
        })

    if enable_overhead_postprocess:
        postprocess = _oh_postprocess_bodies(container, result, bodies_by_id, boards_by_id, components_by_id=components_by_id)
        summary["overheadPostprocess"] = postprocess
        summary["bpGrooveCutsCreated"] = len([row for row in postprocess.get("bpGrooveCuts", []) if row.get("status") == "created"])
        summary["rangehoodBpCutoutsCreated"] = len([row for row in postprocess.get("rangehoodBpCutouts", []) if row.get("status") == "created"])
        summary["rangehoodTopGroovesCreated"] = len([row for row in postprocess.get("rangehoodTopGrooves", []) if row.get("status") == "created"])
        summary["rangehoodDividerSideGroovesCreated"] = len([row for row in postprocess.get("rangehoodDividerSideGrooves", []) if row.get("status") == "created"])
        summary["uConnectorBpGroovesCreated"] = len([row for row in postprocess.get("uConnectorBpGrooves", []) if row.get("status") == "created"])
        summary["uConnectorT3GroovesCreated"] = len([row for row in postprocess.get("uConnectorT3Grooves", []) if row.get("status") == "created"])
        oh_led_rows = postprocess.get("ledGrooveCuts", [])
        summary["ledGrooveCutsCreated"] = len([row for row in oh_led_rows if row.get("status") == "created"])
        summary["ledGrooveCutsFailed"] = len([row for row in oh_led_rows if row.get("status") == "failed"])
        summary["ledGrooveCutsSkipped"] = len([row for row in oh_led_rows if row.get("status") == "skipped"])
        for led_row in oh_led_rows:
            if led_row.get("status") == "failed":
                summary["warnings"].append(
                    "LED groove cut failed for {}: {}".format(
                        led_row.get("featureId"),
                        led_row.get("reason") or "unknown",
                    )
                )
        summary["hingeCutsCreated"] = len([row for row in postprocess.get("hingeCuts", []) if row.get("status") == "created"])
        summary["rotationOpsCreated"] = len([row for row in postprocess.get("rotations", []) if row.get("status") == "created"])
        summary["topPanelTranslationsCreated"] = len([row for row in postprocess.get("topPanelTranslations", []) if row.get("status") == "created"])
        summary["frontPanelZShiftsCreated"] = len([row for row in postprocess.get("frontPanelZShifts", []) if row.get("status") == "created"])
        summary["dividerZShiftsCreated"] = len([row for row in postprocess.get("dividerZShifts", []) if row.get("status") == "created"])
        summary["supportZShiftsCreated"] = len([row for row in postprocess.get("supportZShifts", []) if row.get("status") == "created"])
        summary["bodyComponentsCreated"] = len(components_by_id)
        summary["bodyComponentNames"] = [
            str(getattr(comp, "name", "") or board_component_label(assembly_component_name or body_prefix, bid, fallback_assembly=body_prefix))
            for bid, comp in components_by_id.items()
        ]
        for group_name in (
            "bpGrooveCuts",
            "rangehoodBpCutouts",
            "rangehoodTopGrooves",
            "rangehoodDividerSideGrooves",
            "ledGrooveCuts",
            "hingeCuts",
            "rotations",
            "topPanelTranslations",
            "frontPanelZShifts",
            "dividerZShifts",
            "supportZShifts",
        ):
            for row in postprocess.get(group_name, []):
                if row.get("status") == "failed":
                    summary["warnings"].append("Overhead {} failed for {}: {}".format(group_name, row.get("featureId") or row.get("boardId"), row.get("reason") or "unknown"))

    # Initialize face metadata after post-processing so surface/edge/milling
    # classification reflects the final machined geometry (grooves, holes).
    if module_name == "overhead" and initialize_oh_panel_faces:
        for board_id, body in bodies_by_id.items():
            panel_metadata = panel_metadata_by_id.get(board_id)
            if not panel_metadata or body is None:
                continue
            _run_oh_face_init(body, panel_metadata, board_id, summary)

    if summary["createdBodies"] == 0 and not summary["errors"]:
        summary["warnings"].append("No {} rough bodies were created.".format(module_name))
    if assembly_component_name is None:
        if origin_active and bodies_by_id:
            # Part documents cannot contain components, so occurrence placement
            # is impossible; move ALL created bodies to the origin with ONE real
            # move feature instead (this REPLACES the legacy z=10km staging).
            moved = 0
            try:
                collection = adsk.core.ObjectCollection.create()
                for body in bodies_by_id.values():
                    if body is not None:
                        collection.add(body)
                if collection.count:
                    transform = adsk.core.Matrix3D.create()
                    transform.translation = adsk.core.Vector3D.create(
                        mm_to_cm(origin_x_mm), mm_to_cm(origin_y_mm), mm_to_cm(origin_z_mm)
                    )
                    move_input = container.features.moveFeatures.createInput(collection, transform)
                    try:
                        move_input.defineAsFreeMove(transform)
                    except Exception:
                        pass
                    move_feature = container.features.moveFeatures.add(move_input)
                    move_feature.name = "{}_ORIGIN_PLACE".format(sanitize_token(body_prefix, fallback="BODY", limit=20))
                    moved = collection.count
            except Exception as ex:
                summary["warnings"].append("Origin placement move failed: {}".format(ex))
            summary["modelZOffset"] = {
                "offsetMm": float(origin_z_mm),
                "mode": "bodyMoveOrigin",
                "movedBodies": moved,
                "originXMm": origin_x_mm,
                "originYMm": origin_y_mm,
            }
            summary["containerTransformMm"] = {"x": origin_x_mm, "y": origin_y_mm, "z": float(origin_z_mm)}
            summary["warnings"].append(
                "This document cannot contain components (Part document); bodies were moved to the origin directly. "
                "Open an Assembly/Design document to get the full component structure (assembly name, per-board components)."
            )
        else:
            summary["modelZOffset"] = offset_matching_bodies_z_mm(
                root_comp,
                name_prefixes=["{}_".format(body_prefix)],
                module=module_name,
                dz_mm=MODEL_Z_OFFSET_MM,
                feature_prefix="{}_MODEL_Z_OFFSET_".format(sanitize_token(body_prefix, fallback="BODY", limit=20)),
            )
    else:
        summary["modelZOffset"] = {"offsetMm": float(origin_z_mm), "mode": "componentOccurrence", "assemblyComponentName": assembly_component_name}

    # Re-assert + read back the container placement AFTER all features ran, so
    # the response proves whether the transform survived the recomputes.
    if assembly_component_name is not None and container is not root_comp:
        try:
            occurrences = root_comp.allOccurrencesByComponent(container)
            occurrence = occurrences.item(0) if occurrences and occurrences.count else None
            if occurrence is not None:
                expected_matrix = _compose_occurrence_matrix(
                    origin_x_mm=origin_x_mm,
                    origin_y_mm=origin_y_mm,
                    origin_z_mm=origin_z_mm,
                    rotation_deg=origin_rotation_deg,
                )
                translation = occurrence.transform.translation
                current = (translation.x * 10.0, translation.y * 10.0, translation.z * 10.0)
                expected = (origin_x_mm, origin_y_mm, float(origin_z_mm))
                # Always re-assert when a non-zero rotation is part of the pose.
                # Translation-only repair previously left U-Shape runs unrotated.
                needs_repair = (
                    abs(float(origin_rotation_deg or 0.0)) > 1e-9
                    or any(abs(current[i] - expected[i]) > 0.5 for i in range(3))
                )
                if needs_repair:
                    occurrence.transform = expected_matrix
                    _capture_position_snapshot(root_comp)
                    translation = occurrence.transform.translation
                    current = (translation.x * 10.0, translation.y * 10.0, translation.z * 10.0)
                summary["containerTransformMm"] = {
                    "x": round(current[0], 2),
                    "y": round(current[1], 2),
                    "z": round(current[2], 2),
                    "rotationDeg": float(origin_rotation_deg or 0.0),
                }
        except Exception as ex:
            summary["warnings"].append("Container placement read-back failed: {}".format(ex))
    placement_debug["containerTransformFinalMm"] = summary.get("containerTransformMm")
    placement_debug["createdBodies"] = summary.get("createdBodies")
    placement_debug["ledGrooveCutsCreated"] = summary.get("ledGrooveCutsCreated")
    placement_debug["ledGrooveCutsFailed"] = summary.get("ledGrooveCutsFailed")
    placement_debug["ledGrooveCutsSkipped"] = summary.get("ledGrooveCutsSkipped")
    placement_debug["overheadLedGrooveCuts"] = (
        (summary.get("overheadPostprocess") or {}).get("ledGrooveCuts")
        if enable_overhead_postprocess
        else None
    )
    placement_debug["warnings"] = list(summary.get("warnings") or [])[:10]
    summary["placementDebug"] = {k: v for k, v in placement_debug.items() if k != "layoutRaw"}
    _write_placement_debug(placement_debug)
    return summary


GT_FP_STAGE_OFFSET_X_MM = 100000.0
GT_FP_CAPSULE_ARC_SEGMENTS = 16


def _gt_capsule_outline_points(x0, x1, z0, z1):
    """Closed capsule outline (XZ plane, mm) approximated with line segments; avoids sketch arc direction pitfalls."""
    radius = min((x1 - x0) / 2.0, (z1 - z0) / 2.0)
    horizontal = (x1 - x0) >= (z1 - z0)
    points = []
    if horizontal:
        cz = (z0 + z1) / 2.0
        left_cx = x0 + radius
        right_cx = x1 - radius
        points.append((left_cx, z1))
        points.append((right_cx, z1))
        for step in range(1, GT_FP_CAPSULE_ARC_SEGMENTS):
            angle = math.pi / 2.0 - math.pi * step / GT_FP_CAPSULE_ARC_SEGMENTS
            points.append((right_cx + radius * math.cos(angle), cz + radius * math.sin(angle)))
        points.append((right_cx, z0))
        points.append((left_cx, z0))
        for step in range(1, GT_FP_CAPSULE_ARC_SEGMENTS):
            angle = -math.pi / 2.0 - math.pi * step / GT_FP_CAPSULE_ARC_SEGMENTS
            points.append((left_cx + radius * math.cos(angle), cz + radius * math.sin(angle)))
    else:
        cx = (x0 + x1) / 2.0
        bottom_cz = z0 + radius
        top_cz = z1 - radius
        points.append((x0, bottom_cz))
        points.append((x0, top_cz))
        for step in range(1, GT_FP_CAPSULE_ARC_SEGMENTS):
            angle = math.pi + math.pi * step / GT_FP_CAPSULE_ARC_SEGMENTS
            points.append((cx + radius * math.cos(angle), top_cz - radius * math.sin(angle)))
        points.append((x1, top_cz))
        points.append((x1, bottom_cz))
        for step in range(1, GT_FP_CAPSULE_ARC_SEGMENTS):
            angle = math.pi * step / GT_FP_CAPSULE_ARC_SEGMENTS
            points.append((cx + radius * math.cos(angle), bottom_cz - radius * math.sin(angle)))
    points.append(points[0])
    return points


def _gt_xz_sketch_at_y(component, y_mm, name):
    construction = component.constructionPlanes
    plane_input = construction.createInput()
    plane_input.setByOffset(component.xZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(y_mm)))
    plane = construction.add(plane_input)
    sketch = component.sketches.add(plane)
    sketch.name = name
    return sketch


def _gt_cut_fp_lock(component, body, panel, stage_x):
    cutout = panel.get("lockCutout")
    if not isinstance(cutout, dict):
        return []
    x0 = _as_float(cutout.get("x0"))
    x1 = _as_float(cutout.get("x1"))
    z0 = _as_float(cutout.get("z0"))
    z1 = _as_float(cutout.get("z1"))
    if None in (x0, x1, z0, z1) or x1 <= x0 or z1 <= z0:
        return [{"panelId": panel.get("id"), "kind": "lock_cutout", "status": "skipped", "reason": "invalid bounds"}]
    thickness = max(0.1, _as_float(panel.get("thickness")) or 16.0)
    rear_y = _as_float(panel.get("y1"))
    rear_y = rear_y if rear_y is not None else 0.0
    try:
        sketch = _gt_xz_sketch_at_y(component, rear_y, "GT_FP_LOCK_{}".format(sanitize_token(str(panel.get("id") or "FP"), limit=50)))
        outline = _gt_capsule_outline_points(x0 + stage_x, x1 + stage_x, z0, z1)
        lines = sketch.sketchCurves.sketchLines
        for index in range(len(outline) - 1):
            p0 = outline[index]
            p1 = outline[index + 1]
            m0 = adsk.core.Point3D.create(mm_to_cm(p0[0]), mm_to_cm(rear_y), mm_to_cm(p0[1]))
            m1 = adsk.core.Point3D.create(mm_to_cm(p1[0]), mm_to_cm(rear_y), mm_to_cm(p1[1]))
            lines.addByTwoPoints(sketch.modelToSketchSpace(m0), sketch.modelToSketchSpace(m1))
        profile = _largest_profile(sketch)
        if profile is None:
            return [{"panelId": panel.get("id"), "kind": "lock_cutout", "status": "failed", "reason": "no closed lock profile"}]
        extrudes = component.features.extrudeFeatures
        ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(thickness)))
        try:
            participants = adsk.core.ObjectCollection.create()
            participants.add(body)
            ext_input.participantBodies = participants
        except Exception:
            pass
        cut = extrudes.add(ext_input)
        cut.name = "GT_FP_LOCK_CUT_{}".format(sanitize_token(str(panel.get("id") or "FP"), limit=50))
        return [{
            "panelId": panel.get("id"),
            "kind": "lock_cutout",
            "status": "created",
            "orientation": cutout.get("orientation"),
            "depth": thickness,
            "stagedCut": True,
        }]
    except Exception as ex:
        return [{"panelId": panel.get("id"), "kind": "lock_cutout", "status": "failed", "reason": str(ex)}]


def _gt_cut_fp_hinges(component, body, panel, stage_x):
    holes = panel.get("hingeHoles")
    if not isinstance(holes, list) or not holes:
        return []
    thickness = max(0.1, _as_float(panel.get("thickness")) or 16.0)
    rear_y = _as_float(panel.get("y1"))
    rear_y = rear_y if rear_y is not None else 0.0
    audits = []
    max_depth = 0.1
    try:
        sketch = _gt_xz_sketch_at_y(component, rear_y, "GT_FP_HINGE_{}".format(sanitize_token(str(panel.get("id") or "FP"), limit=50)))
        circles = sketch.sketchCurves.sketchCircles
        drawn = 0
        for hole in holes:
            if not isinstance(hole, dict):
                continue
            cx = _as_float(hole.get("centerX"))
            cz = _as_float(hole.get("centerZ"))
            diameter = _as_float(hole.get("diameter")) or 35.0
            depth = min(thickness, max(0.1, _as_float(hole.get("depth")) or 12.5))
            if cx is None or cz is None or diameter <= 0:
                audits.append({"panelId": panel.get("id"), "id": hole.get("id"), "kind": "hinge_cup", "status": "skipped", "reason": "invalid hinge cup"})
                continue
            center = adsk.core.Point3D.create(mm_to_cm(cx + stage_x), mm_to_cm(rear_y), mm_to_cm(cz))
            circles.addByCenterRadius(sketch.modelToSketchSpace(center), mm_to_cm(diameter / 2.0))
            max_depth = max(max_depth, depth)
            drawn += 1
            audits.append({"panelId": panel.get("id"), "id": hole.get("id"), "kind": "hinge_cup", "status": "drawn", "diameter": diameter, "depth": depth})
        if drawn == 0:
            return audits
        profiles = adsk.core.ObjectCollection.create()
        for idx in range(sketch.profiles.count):
            profiles.add(sketch.profiles.item(idx))
        if profiles.count == 0:
            return [{**audit, "status": "failed", "reason": "no closed hinge profiles"} for audit in audits]
        extrudes = component.features.extrudeFeatures
        ext_input = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(-mm_to_cm(max_depth)))
        try:
            participants = adsk.core.ObjectCollection.create()
            participants.add(body)
            ext_input.participantBodies = participants
        except Exception:
            pass
        cut = extrudes.add(ext_input)
        cut.name = "GT_FP_HINGE_CUT_{}".format(sanitize_token(str(panel.get("id") or "FP"), limit=50))
        return [
            {**audit, "status": "created" if audit.get("status") == "drawn" else audit.get("status"), "stagedCut": True}
            for audit in audits
        ]
    except Exception as ex:
        return [{"panelId": panel.get("id"), "kind": "hinge_cup", "status": "failed", "reason": str(ex)}]


def _gt_create_front_panel_bodies(component, result, summary):
    front_panels = result.get("frontPanels")
    if not isinstance(front_panels, list) or not front_panels:
        return
    for panel in front_panels:
        if not isinstance(panel, dict):
            continue
        panel_id = str(panel.get("id") or "FP")
        bbox = _board_bbox(panel)
        if not bbox or bbox["x1"] <= bbox["x0"] or bbox["y1"] <= bbox["y0"] or bbox["z1"] <= bbox["z0"]:
            summary["skippedBoards"].append({"boardId": panel_id, "reason": "invalid_front_panel_bbox"})
            continue
        # One front panel = one child component (assembly semantics); fall back
        # to the container when children are unsupported (Part documents).
        target = component
        fp_name = board_component_label(
            summary.get("assemblyComponentName") or "GT",
            panel_id,
            fallback_assembly="GT",
        )
        try:
            target = _new_child_component(
                component,
                fp_name,
                module_name="generalTall",
                board_id=panel_id,
            )
        except Exception:
            target = component
        try:
            body, err = _add_box_body(
                target, panel_id, bbox, body_prefix="GT_FP", module_name="generalTall",
                move_prefix="GT_FP_MOVE_", display_name=fp_name,
            )
            if err or not body:
                summary["skippedBoards"].append({"boardId": panel_id, "reason": err or "front_panel_create_failed"})
                continue
            # Stage far away before cutting so hardware cuts can never touch structural boards.
            has_hardware = isinstance(panel.get("lockCutout"), dict) or (isinstance(panel.get("hingeHoles"), list) and panel.get("hingeHoles"))
            if has_hardware:
                move_body_by_mm(target, body, GT_FP_STAGE_OFFSET_X_MM, 0.0, 0.0, feature_prefix="GT_FP_STAGE_")
                try:
                    summary["frontPanelCutAudit"].extend(_gt_cut_fp_lock(target, body, panel, GT_FP_STAGE_OFFSET_X_MM))
                    summary["frontPanelCutAudit"].extend(_gt_cut_fp_hinges(target, body, panel, GT_FP_STAGE_OFFSET_X_MM))
                finally:
                    move_body_by_mm(target, body, -GT_FP_STAGE_OFFSET_X_MM, 0.0, 0.0, feature_prefix="GT_FP_UNSTAGE_")
            fp_board = {
                "id": panel_id,
                "boardType": "cabinet_door",
                "category": "front_panel",
                "materialThickness": panel.get("thickness") or abs(bbox["y1"] - bbox["y0"]),
                "profilePlane": "XZ",
                "thicknessAxis": "Y",
                "x0": bbox["x0"],
                "x1": bbox["x1"],
                "y0": bbox["y0"],
                "y1": bbox["y1"],
                "z0": bbox["z0"],
                "z1": bbox["z1"],
            }
            panel_metadata, panel_metadata_written = _write_gt_panel_metadata(
                body, fp_board, bbox, summary.get("runLabel"),
                carcass_color=summary.get("carcassColor"),
                carcass_color_name=summary.get("carcassColorName"),
                features=result.get("features") if isinstance(result.get("features"), list) else [],
            )
            if not panel_metadata_written:
                summary["warnings"].append("Could not write panel metadata for front panel {}.".format(panel_id))
            summary["createdBodies"] += 1
            summary["frontPanelsCreated"] += 1
            summary["createdBoardIds"].append(panel_id)
            summary["bodyAudit"].append({
                "boardId": panel_id,
                "bbox": bbox,
                "profilePlane": "XZ",
                "thicknessAxis": "Y",
                "source": "frontPanelMetadata",
                "status": "created",
                "bodyName": body.name,
                "resolvedType": panel.get("resolvedType"),
                "panelMetadataWritten": panel_metadata_written,
                "panelMetadata": panel_metadata,
            })
        except Exception as ex:
            summary["skippedBoards"].append({"boardId": panel_id, "reason": "front_panel_exception: {}".format(ex)})


def create_rough_bodies_from_general_tall_result(fusion_adapter, result, run_label=None, avoidance_z_shift_mm=0.0, component_name=None, origin_x_mm=None, origin_y_mm=None):
    summary = create_rough_bodies_from_board_result(
        fusion_adapter,
        result,
        module_name="generalTall",
        body_prefix="GT",
        run_label=run_label,
        placement_feature_prefix="GT_PLACE_",
        move_feature_prefix="GT_MOVE_",
        align_feature_prefix="GT_ALIGN_",
        enable_zi_groove_cuts=True,
        avoidance_z_shift_mm=avoidance_z_shift_mm,
        create_container_component=True,
        component_prefix="GT",
        component_name=component_name,
        origin_x_mm=origin_x_mm,
        origin_y_mm=origin_y_mm,
    )
    summary.setdefault("frontPanelsCreated", 0)
    summary.setdefault("frontPanelCutAudit", [])
    root_comp = fusion_adapter.get_root_component()
    if root_comp:
        fp_component = summary.get("_containerComponent") or root_comp
        _gt_create_front_panel_bodies(fp_component, result, summary)
        summary["frontPanelComponentName"] = summary.get("assemblyComponentName")
        summary["frontPanelModelZOffset"] = {
            "offsetMm": MODEL_Z_OFFSET_MM,
            "movedBodies": 0,
            "failedBodies": 0,
            "mode": "sameComponentAtModelZ" if summary.get("assemblyComponentName") else "rootFallback",
        }
        for row in summary["frontPanelCutAudit"]:
            if row.get("status") == "failed":
                summary["warnings"].append(
                    "GT front panel {} cut failed for {}: {}".format(
                        row.get("kind"), row.get("panelId"), row.get("reason") or "unknown"
                    )
                )
    return summary


class _NestedFusionAdapter:
    def __init__(self, root_component):
        self._root_component = root_component

    def get_root_component(self):
        return self._root_component


def _set_nested_occurrence_transform(parent_component, child_component, transform_spec):
    """Legacy occurrence-matrix pose (kept for contract/tests). Prefer body moves for U."""
    occurrences = parent_component.allOccurrencesByComponent(child_component)
    occurrence = occurrences.item(0) if occurrences and occurrences.count else None
    if occurrence is None:
        raise RuntimeError("nested run occurrence was not found")
    rotation_deg = float((transform_spec or {}).get("rotationDeg") or 0.0)
    tx = float((transform_spec or {}).get("translateX") or 0.0)
    ty = float((transform_spec or {}).get("translateY") or 0.0)
    matrix = _compose_occurrence_matrix(
        origin_x_mm=tx,
        origin_y_mm=ty,
        origin_z_mm=0.0,
        rotation_deg=rotation_deg,
    )
    # Grounded occurrences ignore transform writes — always unground first.
    try:
        if hasattr(occurrence, "isGroundToParent") and occurrence.isGroundToParent:
            occurrence.isGroundToParent = False
    except Exception:
        pass

    last_error = None
    for attempt in range(3):
        try:
            occurrence.transform = matrix
        except Exception as ex:
            last_error = str(ex)
            continue
        _capture_position_snapshot(parent_component)
        try:
            design = parent_component.parentDesign
            if design is not None:
                design.computeAll()
        except Exception:
            pass
        read_matrix = occurrence.transform
        translation = read_matrix.translation
        read_rot = _matrix_z_rotation_deg(read_matrix)
        read_x = translation.x * 10.0
        read_y = translation.y * 10.0
        if _angle_close(read_rot, rotation_deg, 1.0) and abs(read_x - tx) <= 1.0 and abs(read_y - ty) <= 1.0:
            return {
                "rotationDeg": rotation_deg,
                "translateX": tx,
                "translateY": ty,
                "readBackMm": {
                    "x": round(read_x, 2),
                    "y": round(read_y, 2),
                    "z": round(translation.z * 10.0, 2),
                },
                "readBackRotationDeg": round(read_rot, 2),
                "attempts": attempt + 1,
            }
        last_error = "readBack rot={:.1f} expected={:.1f} xy=({:.1f},{:.1f})".format(
            read_rot, rotation_deg, read_x, read_y
        )
    raise RuntimeError(
        "Run pose did not persist after retries ({})".format(last_error or "unknown")
    )


def _iter_run_bodies(run_component):
    """Yield (owning_component, body) for every BRep under a run, including board children."""
    components = [run_component]
    try:
        occurrences = run_component.allOccurrences
        for occurrence_index in range(occurrences.count):
            occurrence = occurrences.item(occurrence_index)
            child = occurrence.component
            if child is not None and child not in components:
                components.append(child)
    except Exception:
        pass
    seen = set()
    for component in components:
        try:
            bodies = component.bRepBodies
        except Exception:
            continue
        for index in range(bodies.count):
            body = bodies.item(index)
            token = getattr(body, "entityToken", None) or id(body)
            if token in seen:
                continue
            seen.add(token)
            yield component, body


def _pose_run_via_body_moves(run_component, transform_spec, feature_prefix="UOH_POSE_"):
    """Bake run Z-rotation + XY translation into board bodies via MoveFeature.

    Occurrence.transform after a long Style-1 postprocess timeline is unreliable
    in parametric designs (ohc-6 produced three stacked straight cabinets).
    Free-move features persist on the timeline and survive recompute.
    """
    rotation_deg = float((transform_spec or {}).get("rotationDeg") or 0.0)
    tx = float((transform_spec or {}).get("translateX") or 0.0)
    ty = float((transform_spec or {}).get("translateY") or 0.0)
    if abs(rotation_deg) < 1e-9 and abs(tx) < 1e-9 and abs(ty) < 1e-9:
        return {
            "mode": "identity",
            "movedBodies": 0,
            "rotationDeg": 0.0,
            "translateX": 0.0,
            "translateY": 0.0,
        }
    matrix = _compose_occurrence_matrix(
        origin_x_mm=tx,
        origin_y_mm=ty,
        origin_z_mm=0.0,
        rotation_deg=rotation_deg,
    )
    moved = 0
    errors = []
    for owner, body in _iter_run_bodies(run_component):
        try:
            _move_body_rigid_transform(owner, body, matrix, feature_prefix=feature_prefix)
            moved += 1
        except Exception as ex:
            errors.append("{}: {}".format(getattr(body, "name", "body"), ex))
    if moved <= 0:
        raise RuntimeError(
            "body-move pose moved 0 bodies ({})".format("; ".join(errors[:3]) or "no bodies")
        )
    return {
        "mode": "bodyMove",
        "movedBodies": moved,
        "rotationDeg": rotation_deg,
        "translateX": tx,
        "translateY": ty,
        "errors": errors[:5],
    }


def _rotate_cardinal_direction_z(direction, degrees):
    cycle = ["+X", "+Y", "-X", "-Y"]
    token = str(direction or "").upper()
    if token not in cycle:
        return token
    steps = int(round(float(degrees or 0.0) / 90.0)) % 4
    return cycle[(cycle.index(token) + steps) % 4]


def _update_run_body_metadata_to_world(run_component, run_id, rotation_deg):
    rows = []
    components = [run_component]
    try:
        occurrences = run_component.allOccurrences
        for occurrence_index in range(occurrences.count):
            occurrence = occurrences.item(occurrence_index)
            if occurrence.component not in components:
                components.append(occurrence.component)
    except Exception:
        pass
    seen = set()
    for component in components:
        bodies = component.bRepBodies
        for index in range(bodies.count):
            body = bodies.item(index)
            token = getattr(body, "entityToken", None) or id(body)
            if token in seen:
                continue
            seen.add(token)
            try:
                attrs = body.attributes
                metadata_attr = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR)
                if metadata_attr is None or not metadata_attr.value:
                    continue
                metadata = json.loads(metadata_attr.value)
                defaults = metadata.get("defaultAttributes") if isinstance(metadata.get("defaultAttributes"), dict) else {}
                geometry = metadata.get("designGeometry") if isinstance(metadata.get("designGeometry"), dict) else {}
                for host in (defaults, geometry):
                    if host.get("millingDirection"):
                        host["millingDirection"] = _rotate_cardinal_direction_z(host["millingDirection"], rotation_deg)
                    if host.get("colourDirection"):
                        host["colourDirection"] = _rotate_cardinal_direction_z(host["colourDirection"], rotation_deg)
                identity = metadata.get("identity") if isinstance(metadata.get("identity"), dict) else {}
                identity["uShapeRunId"] = str(run_id)
                identity["worldRotationDeg"] = float(rotation_deg)
                metadata_attr.value = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
                rows.append({"bodyName": body.name, "status": "updated"})
            except Exception as ex:
                rows.append({"bodyName": getattr(body, "name", "body"), "status": "failed", "reason": str(ex)})
    return rows


def create_u_shape_overhead_assembly(
    fusion_adapter,
    result,
    run_label=None,
    component_name=None,
    origin_x_mm=None,
    origin_y_mm=None,
):
    root = fusion_adapter.get_root_component()
    summary = {
        "createdBodies": 0,
        "createdBoardIds": [],
        "errors": [],
        "warnings": [],
        "runs": [],
        "assemblyComponentName": None,
        "uConnectorBpGroovesCreated": 0,
        "uConnectorT3GroovesCreated": 0,
        "ledGrooveCutsCreated": 0,
        "hingeCutsCreated": 0,
        "adapterBuild": ADAPTER_BUILD,
    }
    if root is None:
        summary["errors"].append("No active Fusion design/root component.")
        return summary
    runs = result.get("runs") if isinstance(result, dict) else None
    if not isinstance(runs, list) or not runs:
        summary["errors"].append("U Shape OHC result has no runs.")
        return summary

    params = result.get("params") if isinstance(result.get("params"), dict) else {}
    footprint = (
        0.0,
        float(params.get("totalWidth") or 0.0),
        0.0,
        max(float(params.get("leftArmLength") or 0.0), float(params.get("rightArmLength") or 0.0)),
    )
    resolved_x = float(origin_x_mm or 0.0)
    resolved_y = float(origin_y_mm or 0.0)
    resolved_x, resolved_y, avoidance = _avoid_existing_at_origin(root, resolved_x, resolved_y, footprint)
    parent, warning, resolved_name = _new_container_component(
        root,
        run_label or "UOHC",
        module_name="u_shape_overhead",
        create_component=True,
        component_prefix="UOHC",
        component_name=component_name or "U Shape OHC",
        origin_x_mm=resolved_x,
        origin_y_mm=resolved_y,
        origin_z_mm=0.0,
    )
    summary["assemblyComponentName"] = resolved_name
    summary["originOffsetMm"] = {"x": resolved_x, "y": resolved_y, "z": 0.0}
    summary["originAvoidance"] = avoidance
    if warning:
        summary["warnings"].append(warning)
    if parent is root:
        summary["errors"].append("U Shape OHC requires an Assembly/Design document with component support.")
        return summary
    try:
        result_meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
        geometry_revision = str(result_meta.get("geometryRevision") or "legacy_side_owns_corners")
        stored_params = dict(params)
        stored_params["geometryRevision"] = geometry_revision
        parent.attributes.add(ATTRIBUTE_GROUP, "module", "u_shape_overhead")
        parent.attributes.add(ATTRIBUTE_GROUP, "runLabel", str(run_label or "UOHC"))
        parent.attributes.add(ATTRIBUTE_GROUP, "uShapeParams", json.dumps(stored_params, ensure_ascii=False))
        parent.attributes.add(ATTRIBUTE_GROUP, "uShapeGeometryRevision", geometry_revision)
        parent.attributes.add(
            ATTRIBUTE_GROUP,
            "uShapeOriginMm",
            json.dumps({"x": resolved_x, "y": resolved_y, "z": 0.0}, ensure_ascii=False),
        )
        parent.attributes.add(ATTRIBUTE_GROUP, "adapterBuild", ADAPTER_BUILD)
    except Exception:
        pass

    nested_adapter = _NestedFusionAdapter(parent)
    posed_runs = []
    for run_entry in runs:
        if not isinstance(run_entry, dict):
            summary["errors"].append("Invalid U Shape OHC run entry.")
            continue
        run_id = str(run_entry.get("id") or "RUN").upper()
        run_result = run_entry.get("result")
        if not isinstance(run_result, dict):
            summary["errors"].append("{} run has no straight OHC result.".format(run_id))
            continue
        oriented_result = copy.deepcopy(run_result)
        transform_spec = run_entry.get("transform") if isinstance(run_entry.get("transform"), dict) else {}
        rotation_deg = float(transform_spec.get("rotationDeg") or 0.0)
        # Build each run in LOCAL identity first so Style-1 T4's 90° about X
        # (and BP/T3 cuts) stay in the straight-OHC frame. Creating the run
        # already Z-rotated made MoveFeature's "world X" tip T4's 1500 mm length
        # upright — the two corner spikes in the Fusion screenshot.
        run_summary = create_rough_bodies_from_board_result(
            nested_adapter,
            oriented_result,
            module_name="overhead",
            body_prefix="UOH_{}".format(run_id),
            run_label="{}.{}".format(run_label or "UOHC", run_id.lower()),
            placement_feature_prefix="UOH_{}_PLACE_".format(run_id),
            move_feature_prefix="UOH_{}_MOVE_".format(run_id),
            align_feature_prefix="UOH_{}_ALIGN_".format(run_id),
            enable_zi_groove_cuts=False,
            enable_overhead_postprocess=True,
            create_container_component=True,
            component_prefix="UOH",
            component_name=board_component_label(
                resolved_name or component_name or "U Shape OHC",
                run_id,
                fallback_assembly="U Shape OHC",
            ),
            origin_x_mm=0.0,
            origin_y_mm=0.0,
            avoid_existing_origin=False,
            origin_rotation_deg=0.0,
        )
        run_component = run_summary.get("_containerComponent")
        try:
            # Bake U footprint into bodies AFTER cuts/T4. Do not rely on
            # occurrence.transform — it often fails to persist (straight stack).
            applied_transform = _pose_run_via_body_moves(
                run_component,
                transform_spec,
                feature_prefix="UOH_{}_POSE_".format(run_id),
            )
            world_metadata = _update_run_body_metadata_to_world(run_component, run_id, rotation_deg)
        except Exception as ex:
            applied_transform = None
            world_metadata = []
            run_summary.setdefault("errors", []).append("Could not place {} run: {}".format(run_id, ex))
        public_run_summary = {key: value for key, value in run_summary.items() if not key.startswith("_")}
        public_run_summary["runId"] = run_id
        public_run_summary["worldTransform"] = applied_transform
        public_run_summary["worldMetadata"] = world_metadata
        summary["runs"].append(public_run_summary)
        posed_runs.append({
            "runId": run_id,
            "component": run_component,
            "transform": transform_spec,
            "summaryIndex": len(summary["runs"]) - 1,
            "applied": applied_transform,
        })
        summary["createdBodies"] += int(run_summary.get("createdBodies") or 0)
        summary["createdBoardIds"].extend(
            ["{}.{}".format(run_id, board_id) for board_id in (run_summary.get("createdBoardIds") or [])]
        )
        summary["uConnectorBpGroovesCreated"] += int(run_summary.get("uConnectorBpGroovesCreated") or 0)
        summary["uConnectorT3GroovesCreated"] += int(run_summary.get("uConnectorT3GroovesCreated") or 0)
        summary["ledGrooveCutsCreated"] += int(run_summary.get("ledGrooveCutsCreated") or 0)
        summary["hingeCutsCreated"] += int(run_summary.get("hingeCutsCreated") or 0)
        summary["warnings"].extend(["{}: {}".format(run_id, row) for row in (run_summary.get("warnings") or [])])
        summary["errors"].extend(["{}: {}".format(run_id, row) for row in (run_summary.get("errors") or [])])

    # Final pass: verify every run received a body-move pose (or identity).
    for posed in posed_runs:
        applied = posed.get("applied") if isinstance(posed.get("applied"), dict) else None
        if posed["component"] is None:
            summary["errors"].append("Final {} pose missing run component.".format(posed["runId"]))
            continue
        if applied is None:
            summary["errors"].append(
                "Final {} pose missing — body-move U footprint was not applied.".format(posed["runId"])
            )
            continue
        if applied.get("mode") == "bodyMove" and int(applied.get("movedBodies") or 0) <= 0:
            summary["errors"].append(
                "Final {} pose moved 0 bodies — footprint will not be U-shaped.".format(posed["runId"])
            )

    _capture_position_snapshot(root)
    try:
        design = root.parentDesign
        if design is not None:
            design.computeAll()
    except Exception:
        pass

    parent_occurrence = None
    try:
        occs = root.allOccurrencesByComponent(parent)
        if occs and occs.count:
            parent_occurrence = occs.item(0)
    except Exception:
        parent_occurrence = None
    measure = measure_u_shape_assembly(
        parent,
        result=result,
        parent_occurrence=parent_occurrence,
        origin_offset_mm={"x": resolved_x, "y": resolved_y, "z": 0.0},
    )
    postprocess_audit = audit_u_shape_postprocess(summary.get("runs") or [], params)
    measure["postprocessAudit"] = postprocess_audit
    measure.setdefault("findings", []).extend(postprocess_audit.get("findings") or [])
    if not postprocess_audit.get("ok"):
        measure["ok"] = False
        measure.setdefault("errors", []).extend(
            [row.get("detail") for row in (postprocess_audit.get("findings") or []) if row.get("detail")]
        )
    try:
        parent.attributes.add(
            ATTRIBUTE_GROUP,
            "uShapePostprocessAudit",
            json.dumps(postprocess_audit, ensure_ascii=False, separators=(",", ":")),
        )
    except Exception:
        pass
    summary["measure"] = measure
    summary["postprocessAudit"] = postprocess_audit
    footprint = measure.get("footprint") if isinstance(measure.get("footprint"), dict) else {}
    pose = measure.get("poseCompare") if isinstance(measure.get("poseCompare"), dict) else {}
    led_audit = measure.get("ledGrooveAudit") if isinstance(measure.get("ledGrooveAudit"), dict) else {}
    summary["ledGrooveAudit"] = led_audit
    summary["ledGrooveFailed"] = bool(led_audit and led_audit.get("ok") is False)
    corner_audit = measure.get("cornerOwnershipAudit") if isinstance(measure.get("cornerOwnershipAudit"), dict) else {}
    summary["cornerOwnershipAudit"] = corner_audit
    summary["cornerOwnershipFailed"] = bool(corner_audit and corner_audit.get("ok") is False)
    closure_audit = measure.get("backCornerClosureAudit") if isinstance(measure.get("backCornerClosureAudit"), dict) else {}
    summary["backCornerClosureAudit"] = closure_audit
    summary["backCornerClosureFailed"] = bool(closure_audit and closure_audit.get("ok") is False)
    summary["notUShape"] = footprint.get("isUShape") is False
    contact = measure.get("contactAudit") if isinstance(measure.get("contactAudit"), dict) else {}
    summary["contactFailed"] = bool(contact and contact.get("ok") is False)
    summary["summaryLine"] = None
    if not measure.get("ok") or footprint.get("isUShape") is False or pose.get("ok") is False:
        detail = "; ".join(
            list(measure.get("errors") or [])[:3]
            or list(footprint.get("errors") or [])[:2]
            or ["pose/footprint self-check failed"]
        )
        summary["summaryLine"] = detail
        summary["errors"].append("U self-check FAILED: {}".format(detail))
        summary["warnings"].append(
            "See logs/u_shape_ohc_fusion_measure.json (boards={}, findings={}).".format(
                len(measure.get("boards") or []),
                len(measure.get("findings") or []),
            )
        )
    try:
        summary["measureLog"] = measure_and_log_u_shape_assemblies(
            root,
            source="createFusionBodies",
            cases=[{
                "caseId": str(run_label or resolved_name or "UOHC"),
                "assemblyComponentName": resolved_name,
                **measure,
            }],
        ).get("logPath")
    except Exception as ex:
        summary["warnings"].append("Could not write Fusion measure log: {}".format(ex))
    return summary
