"""Post-Lay Flat manufacturing check.

MILLING must face +Z and HALF features may open on +Z only.  A lock nick
does not fail the colour-area gate.  A colour skin that is materially
smaller than the milling face is a bottom rebate and is auto-flipped.
This module is read-only; controller orchestration owns exact-source
write-back and repair.
"""

from __future__ import annotations

MIN_DOT = 0.95
PLUS_Z = (0.0, 0.0, 1.0)
MINUS_Z = (0.0, 0.0, -1.0)

try:
    from panel_attributes.milling_surface_propagation import (
        MILLING_SURFACE,
        NON_MILLING_SURFACE,
        MILLING_SURFACE_EITHER,
        SAME_ORIENTATION_DOT,
        _current_milling_role,
        face_world_plane,
        normalize_vector,
        dot3,
    )
except Exception:
    try:
        from milling_surface_propagation import (
            MILLING_SURFACE,
            NON_MILLING_SURFACE,
            MILLING_SURFACE_EITHER,
            SAME_ORIENTATION_DOT,
            _current_milling_role,
            face_world_plane,
            normalize_vector,
            dot3,
        )
    except Exception:
        MILLING_SURFACE = "MILLING"
        NON_MILLING_SURFACE = "NON_MILLING"
        MILLING_SURFACE_EITHER = "EITHER"
        SAME_ORIENTATION_DOT = 0.95
        _current_milling_role = None
        face_world_plane = None

        def normalize_vector(vector):
            values = [float(vector[0]), float(vector[1]), float(vector[2])]
            length = sum(value * value for value in values) ** 0.5
            if length <= 1e-9:
                return [0.0, 0.0, 1.0]
            return [value / length for value in values]

        def dot3(left, right):
            return sum(float(left[i]) * float(right[i]) for i in range(3))

try:
    from nesting.fusion_layout import _fast_broad_faces
except Exception:
    try:
        from fusion_layout import _fast_broad_faces
    except Exception:
        _fast_broad_faces = None

try:
    from panel_attributes import work_zones
except Exception:
    try:
        import work_zones
    except Exception:
        work_zones = None

try:
    from nesting.lay_flat_orientation import (
        HALF_BOTTOM,
        HALF_DOUBLE,
        inspect_half_openings,
        refine_half_orientation,
    )
except Exception:
    try:
        from lay_flat_orientation import (  # type: ignore
            HALF_BOTTOM,
            HALF_DOUBLE,
            inspect_half_openings,
            refine_half_orientation,
        )
    except Exception:
        HALF_BOTTOM = "bottomHalf"
        HALF_DOUBLE = "doubleSide"
        inspect_half_openings = None
        refine_half_orientation = None


def evaluate_face_up_normals(
    milling_normal,
    colour_normal,
    cutting_face="MILLING",
    min_dot=MIN_DOT,
):
    """Pure check from two outward normals. No Fusion objects required."""
    threshold = float(min_dot if min_dot is not None else MIN_DOT)
    milling = normalize_vector(milling_normal) if milling_normal else None
    colour = normalize_vector(colour_normal) if colour_normal else None
    if not milling or not colour:
        return {
            "ok": False,
            "millingOk": False,
            "colourOk": False,
            "millingDotPlusZ": None,
            "colourDotMinusZ": None,
            "reasons": ["missing_normals"],
        }

    milling_dot = dot3(milling, PLUS_Z)
    colour_dot = dot3(colour, MINUS_Z)
    cutting = str(cutting_face or "MILLING").strip().upper()
    reasons = []
    # After Lay Flat: machining face up (+Z), single-sided colour down (−Z).
    milling_ok = milling_dot >= threshold
    colour_ok = colour_dot >= threshold
    if not milling_ok:
        reasons.append("milling_not_plus_z")
    if not colour_ok:
        reasons.append("colour_not_minus_z")
    # Upside-down board: colour is up and milling is down.
    if (
        not milling_ok
        and not colour_ok
        and dot3(milling, MINUS_Z) >= threshold
        and dot3(colour, PLUS_Z) >= threshold
    ):
        reasons.append("upside_down")

    return {
        "ok": bool(milling_ok and colour_ok),
        "millingOk": bool(milling_ok),
        "colourOk": bool(colour_ok),
        "millingDotPlusZ": round(float(milling_dot), 4),
        "colourDotMinusZ": round(float(colour_dot), 4),
        "reasons": reasons,
        "cuttingFace": cutting or "MILLING",
    }


def _body_name(body):
    try:
        return str(getattr(body, "name", "") or "")
    except Exception:
        return ""


def _cutting_face_from_body(body):
    raw = ""
    candidates = [body]
    try:
        native = getattr(body, "nativeObject", None)
        if native is not None:
            candidates.append(native)
    except Exception:
        pass
    for entity in candidates:
        if entity is None:
            continue
        try:
            attr = entity.attributes.itemByName("UnifiedCabinet.Panel", "metadata")
            raw = str(attr.value or "") if attr else ""
        except Exception:
            raw = ""
        if raw:
            break
    if not raw:
        return "MILLING"
    try:
        import json

        meta = json.loads(raw)
    except Exception:
        return "MILLING"
    classification = meta.get("classification") if isinstance(meta, dict) else None
    cutting = classification.get("cuttingFace") if isinstance(classification, dict) else None
    if isinstance(cutting, dict):
        value = str(cutting.get("value") or "").strip().upper()
        if value in (MILLING_SURFACE, MILLING_SURFACE_EITHER):
            return value
    return "MILLING"


def _assign_milling_and_colour(face_a, face_b, normal_a, normal_b):
    """Prefer live face roles; else larger +Z component = milling."""
    role_a = ""
    role_b = ""
    if callable(_current_milling_role):
        try:
            role_a = str(_current_milling_role(face_a) or "").strip().upper()
        except Exception:
            role_a = ""
        try:
            role_b = str(_current_milling_role(face_b) or "").strip().upper()
        except Exception:
            role_b = ""
    if role_a == MILLING_SURFACE and role_b != MILLING_SURFACE:
        return face_a, face_b, normal_a, normal_b, "role"
    if role_b == MILLING_SURFACE and role_a != MILLING_SURFACE:
        return face_b, face_a, normal_b, normal_a, "role"
    if float(normal_a[2]) >= float(normal_b[2]):
        return face_a, face_b, normal_a, normal_b, "normal"
    return face_b, face_a, normal_b, normal_a, "normal"


def evaluate_body_role_normals(body, min_dot=None):
    """Inspect MILLING/colour role normals without extracting features."""
    threshold = float(min_dot if min_dot is not None else SAME_ORIENTATION_DOT or MIN_DOT)
    name = _body_name(body)
    if body is None:
        return {
            "ok": False,
            "bodyName": name,
            "reasons": ["missing_body"],
        }
    if not callable(_fast_broad_faces) or not callable(face_world_plane):
        return {
            "ok": False,
            "bodyName": name,
            "reasons": ["helpers_unavailable"],
        }
    face_a, face_b = _fast_broad_faces(body)
    if face_a is None or face_b is None:
        return {
            "ok": False,
            "bodyName": name,
            "reasons": ["broad_faces_not_found"],
        }
    normal_a, _ = face_world_plane(face_a)
    normal_b, _ = face_world_plane(face_b)
    if not normal_a or not normal_b:
        return {
            "ok": False,
            "bodyName": name,
            "reasons": ["missing_normals"],
        }
    milling_face, colour_face, milling_n, colour_n, source = _assign_milling_and_colour(
        face_a, face_b, normal_a, normal_b
    )
    check = evaluate_face_up_normals(
        milling_n,
        colour_n,
        cutting_face=_cutting_face_from_body(body),
        min_dot=threshold,
    )
    check.update(
        {
            "bodyName": name,
            "assignment": source,
            "millingFace": milling_face,
            "colourFace": colour_face,
        }
    )
    return check


def evaluate_body_faces_up(body, min_dot=None):
    """Inspect role normals and HALF openings on one Lay Flat body."""
    check = evaluate_body_role_normals(body, min_dot=min_dot)
    if check.get("millingFace") is None or check.get("colourFace") is None:
        return check
    if callable(inspect_half_openings):
        half = inspect_half_openings(body) or {}
    else:
        half = {
            "ok": False,
            "status": "unresolved",
            "reason": "half_inspector_unavailable",
        }
    if callable(refine_half_orientation):
        half = refine_half_orientation(half) or half
    half_status = str(half.get("status") or "unresolved")
    reasons = list(check.get("reasons") or [])
    if not half.get("ok"):
        reasons.append(half.get("reason") or "half_feature_scan_failed")
    elif half_status == HALF_DOUBLE:
        reasons.append("double_side_unsupported")
    elif half_status == HALF_BOTTOM:
        reasons.append("feature_face_not_machining")
    check["ok"] = bool(check.get("ok")) and not reasons
    check["reasons"] = list(dict.fromkeys(reasons))
    check["halfStatus"] = half_status
    check["topHalfCount"] = int(half.get("topHalfCount") or 0)
    check["bottomHalfCount"] = int(half.get("bottomHalfCount") or 0)
    check["unknownHalfCount"] = int(half.get("unknownHalfCount") or 0)
    check["bottomOutlineNotched"] = bool(half.get("bottomOutlineNotched"))
    check["bottomOutlineNotchReason"] = str(
        half.get("bottomOutlineNotchReason") or ""
    )
    check["topOutlineNotched"] = bool(half.get("topOutlineNotched"))
    check["topOutlineNotchReason"] = str(half.get("topOutlineNotchReason") or "")
    check["orientationOverride"] = str(half.get("orientationOverride") or "")
    # Bottom-only HALF (including colour-skin rebate voted as top by
    # topology) is repaired by swapping roles and flipping this copy.
    check["autoFixRecommended"] = bool(
        half.get("ok") and half_status == HALF_BOTTOM
    )
    check["halfInspection"] = half
    return check


def collect_lay_flat_bodies(root_component):
    """Walk root occurrences named/marked LAY_FLAT and return workpiece bodies.

    Returns occurrence-proxy bodies when possible. Native bodies under nested
    assembly components cannot be added to Fusion ``activeSelections``.
    """
    bodies = []
    if root_component is None:
        return bodies
    try:
        occurrences = root_component.occurrences
        count = int(occurrences.count or 0)
    except Exception:
        return bodies

    def _is_lay_flat_component(component, occurrence=None):
        try:
            attr = component.attributes.itemByName("UnifiedCabinet", "systemRole")
            if attr and str(attr.value or "") == "layFlatOutput":
                return True
        except Exception:
            pass
        for entity in (component, occurrence):
            if entity is None:
                continue
            try:
                name = str(getattr(entity, "name", "") or "").strip().upper()
            except Exception:
                name = ""
            if name == "LAY_FLAT" or name.startswith("LAY_FLAT:") or name.startswith("LAY_FLAT ("):
                return True
        return False

    def _proxy_body(body, occurrence):
        if body is None:
            return None
        if occurrence is None:
            return body
        try:
            if bool(getattr(body, "isProxy", False)):
                return body
        except Exception:
            pass
        try:
            native = getattr(body, "nativeObject", None) or body
            return native.createForAssemblyContext(occurrence) or body
        except Exception:
            return body

    def _append_body(body):
        if body is None:
            return
        if work_zones is not None:
            try:
                if work_zones.is_lay_flat_workpiece(body):
                    bodies.append(body)
                    return
            except Exception:
                pass
        # Bodies under LAY_FLAT without marker still count (rename-only copies).
        bodies.append(body)

    def _walk_occurrence(occurrence):
        if occurrence is None:
            return
        # Prefer occurrence.bRepBodies — already selectable proxies.
        try:
            solid_count = int(occurrence.bRepBodies.count or 0)
        except Exception:
            solid_count = 0
        if solid_count:
            for index in range(solid_count):
                try:
                    _append_body(occurrence.bRepBodies.item(index))
                except Exception:
                    continue
        else:
            try:
                component = occurrence.component
                native_count = int(component.bRepBodies.count or 0)
            except Exception:
                component = None
                native_count = 0
            for index in range(native_count):
                try:
                    _append_body(_proxy_body(component.bRepBodies.item(index), occurrence))
                except Exception:
                    continue

        try:
            component = occurrence.component
            child_count = int(component.occurrences.count or 0)
        except Exception:
            child_count = 0
        for index in range(child_count):
            try:
                child = component.occurrences.item(index)
            except Exception:
                continue
            child_proxy = child
            try:
                child_proxy = child.createForAssemblyContext(occurrence) or child
            except Exception:
                child_proxy = child
            _walk_occurrence(child_proxy)

    for index in range(count):
        try:
            occurrence = occurrences.item(index)
            component = occurrence.component
        except Exception:
            continue
        if not _is_lay_flat_component(component, occurrence):
            continue
        _walk_occurrence(occurrence)
    return bodies


def check_bodies(bodies, min_dot=None):
    """Run face-up check on a list of bodies."""
    checked = []
    passed = []
    failed = []
    for body in bodies or []:
        result = evaluate_body_faces_up(body, min_dot=min_dot)
        slim = {
            "bodyName": result.get("bodyName") or "",
            "ok": bool(result.get("ok")),
            "millingOk": bool(result.get("millingOk")),
            "colourOk": bool(result.get("colourOk")),
            "millingDotPlusZ": result.get("millingDotPlusZ"),
            "colourDotMinusZ": result.get("colourDotMinusZ"),
            "reasons": list(result.get("reasons") or []),
            "assignment": result.get("assignment") or "",
            "cuttingFace": result.get("cuttingFace") or "",
            "halfStatus": result.get("halfStatus") or "",
            "topHalfCount": int(result.get("topHalfCount") or 0),
            "bottomHalfCount": int(result.get("bottomHalfCount") or 0),
            "unknownHalfCount": int(result.get("unknownHalfCount") or 0),
            "bottomOutlineNotched": bool(result.get("bottomOutlineNotched")),
            "bottomOutlineNotchReason": str(
                result.get("bottomOutlineNotchReason") or ""
            ),
            "topOutlineNotched": bool(result.get("topOutlineNotched")),
            "topOutlineNotchReason": str(result.get("topOutlineNotchReason") or ""),
            "orientationOverride": str(result.get("orientationOverride") or ""),
            "autoFixRecommended": bool(result.get("autoFixRecommended")),
        }
        # Keep face refs only in-process for optional selection.
        slim["_body"] = body
        slim["_millingFace"] = result.get("millingFace")
        slim["_colourFace"] = result.get("colourFace")
        slim["_halfInspection"] = result.get("halfInspection") or {}
        checked.append(slim)
        if slim["ok"]:
            passed.append(slim)
        else:
            failed.append(slim)
    return {
        "ok": not failed,
        "checkedCount": len(checked),
        "passedCount": len(passed),
        "failedCount": len(failed),
        "passed": passed,
        "failed": failed,
        "autoFixCount": sum(
            1 for item in failed if item.get("autoFixRecommended")
        ),
        "doubleSideCount": sum(
            1
            for item in failed
            if "double_side_unsupported" in (item.get("reasons") or [])
        ),
        "minDot": float(min_dot if min_dot is not None else SAME_ORIENTATION_DOT or MIN_DOT),
    }
