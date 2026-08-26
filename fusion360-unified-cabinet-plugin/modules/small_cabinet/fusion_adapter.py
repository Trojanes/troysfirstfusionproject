"""Small Cabinet Fusion body path.

Creates AABB/profile bodies via the shared board creator, then cuts:
  - side_groove pockets (through) for TOP/MID/BOTTOM/BACK tongues
  - door lock capsules on side-door front panels
"""

from __future__ import annotations

import adsk.core
import adsk.fusion

from modules.general_tall import fusion_adapter as board_fusion_adapter
from geometry_ops import entity_board_id, mm_to_cm, sanitize_token

ADAPTER_REVISION = "smallCabinetJoineryLocks_v1"


def _as_float(value, fallback=None):
    try:
        if value is None:
            return fallback
        return float(value)
    except Exception:
        return fallback


def _largest_profile(sketch):
    best = None
    best_area = -1.0
    try:
        for index in range(sketch.profiles.count):
            profile = sketch.profiles.item(index)
            try:
                area = abs(profile.areaProperties().area)
            except Exception:
                area = 0.0
            if area > best_area:
                best = profile
                best_area = area
    except Exception:
        return None
    return best


def _set_single_body_participants(ext_input, body):
    try:
        participants = adsk.core.ObjectCollection.create()
        participants.add(body)
        ext_input.participantBodies = participants
        return None
    except Exception as ex:
        return str(ex)


def _resolve_body_maps(summary, result, body_prefix="SC"):
    """Recover body/component maps from the assembly created by the shared creator."""
    bodies_by_id = {}
    components_by_id = {}
    container = summary.get("_containerComponent")
    boards = result.get("boards") if isinstance(result.get("boards"), list) else []
    board_ids = [str(b.get("id")) for b in boards if isinstance(b, dict) and b.get("id")]

    if container is None:
        return bodies_by_id, components_by_id, None

    try:
        for index in range(container.occurrences.count):
            occ = container.occurrences.item(index)
            child = getattr(occ, "component", None)
            if child is None:
                continue
            matched = entity_board_id(child)
            if matched not in board_ids:
                matched = None
                name = str(getattr(child, "name", "") or "")
                for board_id in board_ids:
                    token = "{}_{}".format(
                        sanitize_token(body_prefix, fallback="SC", limit=20),
                        sanitize_token(board_id, fallback="board", limit=60),
                    )
                    hyphen = "-{}".format(board_id)
                    if name == token or name.startswith(token) or name.endswith(hyphen) or name.endswith("_" + board_id):
                        matched = board_id
                        break
            if not matched:
                continue
            components_by_id[matched] = child
            try:
                if child.bRepBodies.count > 0:
                    bodies_by_id[matched] = child.bRepBodies.item(0)
            except Exception:
                pass
    except Exception:
        pass

    # Fallback: bodies directly on container
    try:
        for index in range(container.bRepBodies.count):
            body = container.bRepBodies.item(index)
            matched = entity_board_id(body)
            if matched in board_ids and matched not in bodies_by_id:
                bodies_by_id[matched] = body
                continue
            name = str(getattr(body, "name", "") or "")
            for board_id in board_ids:
                if board_id in name and board_id not in bodies_by_id:
                    bodies_by_id[board_id] = body
    except Exception:
        pass

    return bodies_by_id, components_by_id, container


def _cut_side_groove(component, body, board, feature):
    """Through rectangular pocket on a YZ side panel."""
    feature_id = str(feature.get("id") or "side_groove")
    if not body or not isinstance(board, dict):
        return {"featureId": feature_id, "status": "skipped", "reason": "missing body/board"}

    y0 = _as_float(feature.get("y0"))
    y1 = _as_float(feature.get("y1"))
    z0 = _as_float(feature.get("z0"))
    z1 = _as_float(feature.get("z1"))
    depth = _as_float(feature.get("depth"))
    bx0 = _as_float(board.get("x0"), 0.0)
    bx1 = _as_float(board.get("x1"), 0.0)
    thickness = abs(bx1 - bx0)
    if None in (y0, y1, z0, z1) or y1 <= y0 or z1 <= z0 or thickness <= 0:
        return {"featureId": feature_id, "status": "skipped", "reason": "invalid groove bounds"}

    effective_depth = min(thickness, depth if depth and depth > 0 else thickness)
    board_id = str(board.get("id") or "")
    # Cut from the outer face inward so the slot is visible on the exterior.
    if board_id == "SIDE_R" or (board_id != "SIDE_L" and bx1 > bx0 and bx0 > 0):
        plane_x = max(bx0, bx1)
        signed_depth = -effective_depth
        from_label = "maxX"
    else:
        plane_x = min(bx0, bx1)
        signed_depth = effective_depth
        from_label = "minX"

    try:
        construction = component.constructionPlanes
        plane_input = construction.createInput()
        plane_input.setByOffset(
            component.yZConstructionPlane,
            adsk.core.ValueInput.createByReal(mm_to_cm(plane_x)),
        )
        plane = construction.add(plane_input)
        sketch = component.sketches.add(plane)
        sketch.name = "SC_SIDE_GROOVE_{}".format(sanitize_token(feature_id, limit=50))
        p0 = sketch.modelToSketchSpace(adsk.core.Point3D.create(
            mm_to_cm(plane_x), mm_to_cm(y0), mm_to_cm(z0),
        ))
        p1 = sketch.modelToSketchSpace(adsk.core.Point3D.create(
            mm_to_cm(plane_x), mm_to_cm(y1), mm_to_cm(z1),
        ))
        sketch.sketchCurves.sketchLines.addTwoPointRectangle(p0, p1)
        profile = _largest_profile(sketch)
        if profile is None:
            return {"featureId": feature_id, "status": "failed", "reason": "no closed groove profile"}
        extrudes = component.features.extrudeFeatures
        ext_input = extrudes.createInput(profile, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(signed_depth)))
        _set_single_body_participants(ext_input, body)
        cut = extrudes.add(ext_input)
        cut.name = "SC_SIDE_GROOVE_CUT_{}".format(sanitize_token(feature_id, limit=50))
        return {
            "featureId": feature_id,
            "status": "created",
            "from": from_label,
            "depth": effective_depth,
            "y": [y0, y1],
            "z": [z0, z1],
        }
    except Exception as ex:
        return {"featureId": feature_id, "status": "failed", "reason": str(ex)}


def _cut_front_lock(component, body, board):
    """Reuse GT capsule lock cutter; map Small Cabinet board fields."""
    cutout = board.get("lockCutout")
    if not isinstance(cutout, dict) or not body:
        return []
    thickness = (
        _as_float(board.get("thickness"))
        or _as_float(board.get("materialThickness"))
        or abs((_as_float(board.get("y1"), 0.0) or 0.0) - (_as_float(board.get("y0"), 0.0) or 0.0))
        or 16.0
    )
    panel = {
        "id": board.get("id"),
        "lockCutout": cutout,
        "thickness": thickness,
        "y1": board.get("y1"),
    }
    try:
        return board_fusion_adapter._gt_cut_fp_lock(component, body, panel, 0.0)
    except Exception as ex:
        return [{"panelId": board.get("id"), "kind": "lock_cutout", "status": "failed", "reason": str(ex)}]


def _sc_postprocess(summary, result, body_prefix="SC"):
    boards = result.get("boards") if isinstance(result.get("boards"), list) else []
    features = result.get("features") if isinstance(result.get("features"), list) else []
    boards_by_id = {str(b.get("id")): b for b in boards if isinstance(b, dict) and b.get("id")}
    bodies_by_id, components_by_id, container = _resolve_body_maps(summary, result, body_prefix=body_prefix)
    if container is None:
        summary.setdefault("warnings", []).append("Small Cabinet postprocess skipped: no assembly container.")
        return

    groove_audit = []
    for feature in features:
        if not isinstance(feature, dict) or feature.get("type") != "side_groove":
            continue
        target_id = str(feature.get("targetBoardId") or "")
        board = boards_by_id.get(target_id)
        body = bodies_by_id.get(target_id)
        component = components_by_id.get(target_id) or container
        row = _cut_side_groove(component, body, board, feature)
        groove_audit.append(row)
        if row.get("status") == "failed":
            summary.setdefault("warnings", []).append(
                "Side groove cut failed for {}: {}".format(row.get("featureId"), row.get("reason"))
            )

    lock_audit = []
    for board in boards:
        if not isinstance(board, dict):
            continue
        if str(board.get("category") or "") != "front_panel":
            continue
        if not isinstance(board.get("lockCutout"), dict):
            continue
        board_id = str(board.get("id") or "")
        body = bodies_by_id.get(board_id)
        component = components_by_id.get(board_id) or container
        rows = _cut_front_lock(component, body, board)
        lock_audit.extend(rows)
        for row in rows:
            if row.get("status") == "failed":
                summary.setdefault("warnings", []).append(
                    "Door lock cut failed for {}: {}".format(row.get("panelId"), row.get("reason"))
                )

    summary["smallCabinetPostprocess"] = {
        "adapterRevision": ADAPTER_REVISION,
        "sideGrooveCuts": groove_audit,
        "lockCuts": lock_audit,
        "sideGrooveCutsCreated": len([r for r in groove_audit if r.get("status") == "created"]),
        "lockCutsCreated": len([r for r in lock_audit if r.get("status") == "created"]),
    }
    summary["sideGrooveCutsCreated"] = summary["smallCabinetPostprocess"]["sideGrooveCutsCreated"]
    summary["lockCutsCreated"] = summary["smallCabinetPostprocess"]["lockCutsCreated"]


def create_rough_bodies_from_board_result(fusion, result, **kwargs):
    kwargs = dict(kwargs or {})
    kwargs.setdefault("module_name", "smallCabinet")
    kwargs.setdefault("body_prefix", "SC")
    kwargs.setdefault("enable_zi_groove_cuts", False)
    kwargs.setdefault("enable_overhead_postprocess", False)
    kwargs.setdefault("create_container_component", True)
    summary = board_fusion_adapter.create_rough_bodies_from_board_result(fusion, result, **kwargs)
    try:
        _sc_postprocess(summary, result, body_prefix=kwargs.get("body_prefix") or "SC")
    except Exception as ex:
        summary.setdefault("warnings", []).append("Small Cabinet postprocess failed: {}".format(ex))
    summary["adapterBuild"] = ADAPTER_REVISION
    return summary


__all__ = ["create_rough_bodies_from_board_result", "ADAPTER_REVISION"]
