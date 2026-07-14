"""Propagate back-face (MILLING) from hinge-cup panels to coplanar neighbors.

Rule (locked):
- Blind circular HALF holes opening onto a broad face mark that face as the
  back = MILLING.
- Other selected panels that are coplanar and same-orientation inherit that
  back face (matched broad face = MILLING, opposite = NON_MILLING).
"""

from __future__ import annotations

SAME_ORIENTATION_DOT = 0.95
PLANE_OFFSET_TOLERANCE_MM = 0.5

try:
    from face_models import MILLING_SURFACE, NON_MILLING_SURFACE, MILLING_SURFACE_EITHER
except Exception:
    try:
        from metadata.face_models import MILLING_SURFACE, NON_MILLING_SURFACE, MILLING_SURFACE_EITHER
    except Exception:
        MILLING_SURFACE = "MILLING"
        NON_MILLING_SURFACE = "NON_MILLING"
        MILLING_SURFACE_EITHER = "EITHER"

try:
    from face_geometry_signature import _face_world_normal_vec, _face_world_point_mm
except Exception:
    try:
        from metadata.face_geometry_signature import _face_world_normal_vec, _face_world_point_mm
    except Exception:
        _face_world_normal_vec = None
        _face_world_point_mm = None

try:
    from panel_face_initializer import classify_box_faces
except Exception:
    try:
        from metadata.panel_face_initializer import classify_box_faces
    except Exception:
        classify_box_faces = None

try:
    from panel_geometry import (
        CUT_TYPE_HALF,
        FEATURE_KIND_HOLE,
        extract_features,
        thickness_axis_from_normal,
        _face_centroid_local_mm,
        _face_normal_local,
        _entity_token,
        _face_key,
    )
except Exception:
    try:
        from metadata.panel_geometry import (
            CUT_TYPE_HALF,
            FEATURE_KIND_HOLE,
            extract_features,
            thickness_axis_from_normal,
            _face_centroid_local_mm,
            _face_normal_local,
            _entity_token,
            _face_key,
        )
    except Exception:
        CUT_TYPE_HALF = "HALF"
        FEATURE_KIND_HOLE = "hole"
        extract_features = None
        thickness_axis_from_normal = None
        _face_centroid_local_mm = None
        _face_normal_local = None
        _entity_token = None
        _face_key = None


def normalize_vector(vector):
    values = [float(vector[0]), float(vector[1]), float(vector[2])]
    length = sum(value * value for value in values) ** 0.5
    if length <= 1e-9:
        return [0.0, 0.0, 1.0]
    return [value / length for value in values]


def dot3(left, right):
    return sum(float(left[index]) * float(right[index]) for index in range(3))


def is_hinge_cup_feature(feature):
    """True when a geometry feature looks like a blind circular hinge cup."""
    if not isinstance(feature, dict):
        return False
    if str(feature.get("cutType") or "") != CUT_TYPE_HALF:
        return False
    if not feature.get("isCircle"):
        return False
    kind = str(feature.get("kind") or "").strip().lower()
    return kind in ("", FEATURE_KIND_HOLE, "hole")


def planes_coplanar_same_orientation(normal_a, centroid_a, normal_b, centroid_b, tol_mm=PLANE_OFFSET_TOLERANCE_MM):
    """Pure geometry test: same plane + normals same direction (not opposite)."""
    if not normal_a or not normal_b or not centroid_a or not centroid_b:
        return False
    n_a = normalize_vector(normal_a)
    n_b = normalize_vector(normal_b)
    if dot3(n_a, n_b) < SAME_ORIENTATION_DOT:
        return False
    delta = [
        float(centroid_b[0]) - float(centroid_a[0]),
        float(centroid_b[1]) - float(centroid_a[1]),
        float(centroid_b[2]) - float(centroid_a[2]),
    ]
    return abs(dot3(n_a, delta)) <= float(tol_mm)


def face_world_plane(face):
    """Return (unit_normal, centroid_mm) in world space, or (None, None)."""
    if face is None or not callable(_face_world_normal_vec) or not callable(_face_world_point_mm):
        return None, None
    normal = _face_world_normal_vec(face)
    centroid = _face_world_point_mm(face)
    if not normal or not centroid:
        return None, None
    return normalize_vector(normal), [float(centroid[0]), float(centroid[1]), float(centroid[2])]


def faces_coplanar_same_orientation(face_a, face_b, tol_mm=PLANE_OFFSET_TOLERANCE_MM):
    n_a, c_a = face_world_plane(face_a)
    n_b, c_b = face_world_plane(face_b)
    return planes_coplanar_same_orientation(n_a, c_a, n_b, c_b, tol_mm=tol_mm)


def _safe_entity_token(entity):
    if callable(_entity_token):
        try:
            return str(_entity_token(entity) or "")
        except Exception:
            pass
    try:
        return str(getattr(entity, "entityToken", "") or "")
    except Exception:
        return ""


def _safe_face_key(face):
    if callable(_face_key):
        try:
            return _face_key(face)
        except Exception:
            pass
    return _safe_entity_token(face) or str(id(face))


def _body_name(body):
    return str(getattr(body, "name", "") or "") or "body"


def classify_body_surfaces(body):
    """Return (surface_a, surface_b, warnings) or (None, None, warnings)."""
    warnings = []
    if not callable(classify_box_faces):
        warnings.append("classify_box_faces unavailable.")
        return None, None, warnings
    panel_context = {"body": body, "bodyName": _body_name(body)}
    try:
        classified = classify_box_faces(body, panel_context)
    except Exception as ex:
        warnings.append("{}: classify failed ({})".format(_body_name(body), ex))
        return None, None, warnings
    surfaces = list(classified.get("surfaceFaces") or [])
    warnings.extend(classified.get("warnings") or [])
    if len(surfaces) < 2:
        warnings.append("{}: need two broad surfaces.".format(_body_name(body)))
        return None, None, warnings
    return surfaces[0], surfaces[1], warnings


def ensure_complementary_surface_roles(body, write_pair=None):
    """If both broad faces share MILLING or NON_MILLING, coerce to opposite roles.

    Colour face (NON_MILLING) and milling face must never be the same role.
    Returns ``{"repaired": bool, "warning": str|None, "roles": [...]}``.
    """
    name = _body_name(body)
    surface_a, surface_b, _warnings = classify_body_surfaces(body)
    if surface_a is None or surface_b is None:
        return {"repaired": False, "warning": None, "roles": []}
    role_a = _current_milling_role(surface_a)
    role_b = _current_milling_role(surface_b)
    if role_a == MILLING_SURFACE and role_b == MILLING_SURFACE:
        new_a, new_b = MILLING_SURFACE, NON_MILLING_SURFACE
    elif role_a == NON_MILLING_SURFACE and role_b == NON_MILLING_SURFACE:
        new_a, new_b = NON_MILLING_SURFACE, MILLING_SURFACE
    else:
        return {"repaired": False, "warning": None, "roles": [role_a, role_b]}
    if callable(write_pair):
        try:
            try:
                write_pair(
                    body,
                    surface_a,
                    new_a,
                    surface_b,
                    new_b,
                    source="repair_complementary",
                )
            except TypeError:
                write_pair(body, surface_a, new_a, surface_b, new_b)
        except Exception as ex:
            return {
                "repaired": False,
                "warning": "{}: complementary repair failed ({})".format(name, ex),
                "roles": [role_a, role_b],
            }
    return {
        "repaired": True,
        "warning": "{}: repaired {}/{} -> {}/{} (colour ≠ milling)".format(
            name, role_a, role_b, new_a, new_b
        ),
        "roles": [new_a, new_b],
    }


def _extract_half_features(body, surface_a, surface_b):
    if not callable(extract_features) or not callable(_face_normal_local) or not callable(_face_centroid_local_mm):
        return []
    if not callable(thickness_axis_from_normal):
        return []
    try:
        ref_normal = _face_normal_local(surface_a, body)
        thickness_axis = thickness_axis_from_normal(ref_normal)
        offset_a = _face_centroid_local_mm(surface_a, body)[thickness_axis]
        offset_b = _face_centroid_local_mm(surface_b, body)[thickness_axis]
        thickness_mm = abs(float(offset_a) - float(offset_b))
        return extract_features(
            body, surface_a, surface_b, thickness_axis, offset_a, offset_b, thickness_mm
        ) or []
    except Exception:
        return []


def detect_hinge_back_face(body):
    """Find the broad face that hinge cups open onto (back = MILLING).

    Returns dict with keys: body, millingFace, nonMillingFace, hingeCount, warnings
    or None when no hinge cups are found.
    """
    surface_a, surface_b, warnings = classify_body_surfaces(body)
    if surface_a is None:
        return None

    features = _extract_half_features(body, surface_a, surface_b)
    hinge_features = [f for f in features if is_hinge_cup_feature(f)]
    if not hinge_features:
        return None

    token_a = _safe_entity_token(surface_a)
    token_b = _safe_entity_token(surface_b)
    votes = {token_a: 0, token_b: 0}
    for feature in hinge_features:
        open_token = str(feature.get("openSurfaceToken") or "")
        if open_token and open_token in votes:
            votes[open_token] += 1

    if votes[token_a] == 0 and votes[token_b] == 0:
        # Fallback: majority open surface by proximity already encoded in features;
        # if tokens missing, prefer surface_a.
        milling_face, non_milling_face = surface_a, surface_b
    elif votes[token_a] >= votes[token_b]:
        milling_face, non_milling_face = surface_a, surface_b
    else:
        milling_face, non_milling_face = surface_b, surface_a

    return {
        "body": body,
        "millingFace": milling_face,
        "nonMillingFace": non_milling_face,
        "hingeCount": len(hinge_features),
        "warnings": warnings,
        "bodyName": _body_name(body),
    }


def _half_slot_surface_roles(body, surface_a, surface_b):
    """Roles for the two broad faces from half-slot / blind groove evidence.

    Prefer groove-floor open-surface votes (same topology as hinge cups). Plain
    wall-adjacency against only the largest SURFACE face often picks the wrong
    side after manual Extrude-Cuts split the milled skin, or after edge-open
    underside slots leave false one-sided perimeter remnants.
    """
    features = _extract_half_features(body, surface_a, surface_b)
    half_features = [
        feature
        for feature in (features or [])
        if str(feature.get("cutType") or "").upper() == "HALF"
    ]
    votes_a = 0
    votes_b = 0
    for feature in half_features:
        which = str(feature.get("openSurfaceIs") or "").upper()
        if which == "A":
            votes_a += 1
        elif which == "B":
            votes_b += 1
    if votes_a > votes_b:
        return [MILLING_SURFACE, NON_MILLING_SURFACE]
    if votes_b > votes_a:
        return [NON_MILLING_SURFACE, MILLING_SURFACE]

    try:
        from panel_face_initializer import detect_surface_milling_roles
    except Exception:
        try:
            from metadata.panel_face_initializer import detect_surface_milling_roles
        except Exception:
            return None
    if not callable(classify_box_faces) or not callable(detect_surface_milling_roles):
        return None
    panel_context = {"body": body, "bodyName": _body_name(body)}
    try:
        classified = classify_box_faces(body, panel_context)
        edge_faces = classified.get("edgeFaces") or []
        roles = detect_surface_milling_roles(
            [surface_a, surface_b], edge_faces, panel_context
        )
    except Exception:
        return None
    if len(roles) < 2:
        return None
    return [roles[0], roles[1]]


def analyze_milling_surfaces(bodies, write_pair):
    """Geometric milling-surface analysis for every body (any board type).

    Priority per body: hinge cups -> half-slots -> EITHER. Machining evidence
    always overwrites stored roles; without evidence, existing assigned roles
    are kept and only unassigned panels are stamped EITHER/EITHER.

    ``write_pair(body, face_a, role_a, face_b, role_b)`` performs write-back.
    """
    updated = []
    skipped = []
    warnings = []
    for body in bodies or []:
        name = _body_name(body)
        surface_a, surface_b, classify_warnings = classify_body_surfaces(body)
        warnings.extend(classify_warnings or [])
        if surface_a is None or surface_b is None:
            skipped.append({"bodyName": name, "reason": "no broad surfaces"})
            continue

        role_a = None
        role_b = None
        source = ""

        detected = detect_hinge_back_face(body)
        if detected:
            key_milling = _safe_face_key(detected["millingFace"])
            if key_milling == _safe_face_key(surface_a):
                role_a, role_b = MILLING_SURFACE, NON_MILLING_SURFACE
            else:
                role_a, role_b = NON_MILLING_SURFACE, MILLING_SURFACE
            source = "hinge_cups"
        else:
            slot_roles = _half_slot_surface_roles(body, surface_a, surface_b)
            if slot_roles and MILLING_SURFACE in slot_roles:
                role_a, role_b = slot_roles[0], slot_roles[1]
                source = "half_slot"

        # Colour (NON_MILLING) and milling must stay opposite — never same role.
        if role_a == MILLING_SURFACE and role_b == MILLING_SURFACE:
            role_b = NON_MILLING_SURFACE
            warnings.append(
                "{}: coerced dual-MILLING half-slots to MILLING/NON_MILLING "
                "(colour face must stay opposite milling).".format(name)
            )
        elif role_a == NON_MILLING_SURFACE and role_b == NON_MILLING_SURFACE:
            role_b = MILLING_SURFACE
            warnings.append(
                "{}: coerced dual-NON_MILLING to NON_MILLING/MILLING.".format(name)
            )

        if source == "":
            current_a = _current_milling_role(surface_a)
            current_b = _current_milling_role(surface_b)
            assigned = {MILLING_SURFACE, NON_MILLING_SURFACE}
            if current_a in assigned or current_b in assigned:
                # Repair illegal same-face / same-role pairs left from older runs.
                if (
                    current_a == MILLING_SURFACE and current_b == MILLING_SURFACE
                ) or (
                    current_a == NON_MILLING_SURFACE
                    and current_b == NON_MILLING_SURFACE
                ):
                    role_a = (
                        MILLING_SURFACE
                        if current_a == MILLING_SURFACE
                        else NON_MILLING_SURFACE
                    )
                    role_b = (
                        NON_MILLING_SURFACE
                        if role_a == MILLING_SURFACE
                        else MILLING_SURFACE
                    )
                    source = "repair_complementary"
                else:
                    skipped.append({
                        "bodyName": name,
                        "reason": "no machining evidence; kept existing roles ({}/{})".format(
                            current_a or "UNASSIGNED", current_b or "UNASSIGNED"
                        ),
                    })
                    continue
            else:
                role_a = role_b = MILLING_SURFACE_EITHER
                source = "either"

        if callable(write_pair):
            try:
                try:
                    write_pair(
                        body,
                        surface_a,
                        role_a,
                        surface_b,
                        role_b,
                        source=source,
                    )
                except TypeError:
                    # Backward-compatible callback signature used by pure tests.
                    write_pair(body, surface_a, role_a, surface_b, role_b)
            except Exception as ex:
                reason = str(ex)
                skipped.append({
                    "bodyName": name,
                    "reason": (
                        "manual face-up lock; automatic analysis skipped"
                        if reason == "manual_locked"
                        else reason
                    ),
                })
                warnings.append("{}: write failed ({})".format(name, ex))
                continue
        updated.append({"bodyName": name, "source": source, "roles": [role_a, role_b]})

    counts = {}
    for item in updated:
        counts[item["source"]] = counts.get(item["source"], 0) + 1
    message = "Milling analysis: updated {} (hinge {}, half-slot {}, EITHER {}), skipped {}.".format(
        len(updated),
        counts.get("hinge_cups", 0),
        counts.get("half_slot", 0),
        counts.get("either", 0),
        len(skipped),
    )
    return {
        "ok": len(updated) > 0,
        "updatedCount": len(updated),
        "skippedCount": len(skipped),
        "sourceCounts": counts,
        "updated": updated,
        "skipped": skipped,
        "warnings": warnings[:40],
        "message": message,
    }


def collect_colour_faces(bodies, is_door_body=None):
    """Collect faces to highlight as the colour / front side.

    Door-only by default when ``is_door_body`` is provided: non-door boards
    (carcass / partition) are skipped. Colour face is never MILLING.

    - Faces stored as NON_MILLING are included.
    - Door bodies whose broad faces are both EITHER contribute exactly one
      face, chosen at random (stand-in).
    """
    import random

    faces = []
    either_picked = []
    skipped = []
    warnings = []
    for body in bodies or []:
        name = _body_name(body)
        if callable(is_door_body) and not is_door_body(body):
            skipped.append({"bodyName": name, "reason": "not_door"})
            continue
        surface_a, surface_b, classify_warnings = classify_body_surfaces(body)
        warnings.extend(classify_warnings or [])
        if surface_a is None or surface_b is None:
            skipped.append({"bodyName": name, "reason": "no broad surfaces"})
            continue

        role_a = _current_milling_role(surface_a)
        role_b = _current_milling_role(surface_b)
        colour = []
        either = []
        milling_only = False
        for face, role in ((surface_a, role_a), (surface_b, role_b)):
            if role == NON_MILLING_SURFACE:
                colour.append(face)
            elif role == MILLING_SURFACE_EITHER:
                either.append(face)
            elif role == MILLING_SURFACE:
                milling_only = True

        if colour:
            faces.extend(colour)
            continue

        if either:
            pick = random.choice(either)
            faces.append(pick)
            either_picked.append({"bodyName": name})
            continue

        if milling_only:
            skipped.append({"bodyName": name, "reason": "has MILLING but no NON_MILLING colour face"})
        else:
            skipped.append({
                "bodyName": name,
                "reason": "no NON_MILLING/EITHER face stored (roles: {}/{})".format(
                    role_a or "UNASSIGNED", role_b or "UNASSIGNED"
                ),
            })
    return {
        "faces": faces,
        "eitherPicked": either_picked,
        "skipped": skipped,
        "warnings": warnings[:40],
    }


def collect_milling_faces(bodies):
    """Collect faces to highlight as the milling side.

    - Faces stored as MILLING are always included.
    - Bodies whose broad faces are both EITHER (or one EITHER + unassigned)
      contribute exactly one face, chosen at random — nesting can flip them,
      so either side is a valid stand-in for selection/preview.
    - Mirrored occurrence proxies that share one native MILLING attribute are
      flagged ``sharedMirrorOccurrence``: Select highlights the same native
      face on both twins; Nesting restores chirality via flatten reflection.
    """
    import random

    faces = []
    either_picked = []
    skipped = []
    warnings = []
    shared_mirror = []
    try:
        from nesting.fusion_layout import _body_has_reflection
    except Exception:
        try:
            from fusion_layout import _body_has_reflection
        except Exception:
            _body_has_reflection = None
    for body in bodies or []:
        name = _body_name(body)
        surface_a, surface_b, classify_warnings = classify_body_surfaces(body)
        warnings.extend(classify_warnings or [])
        if surface_a is None or surface_b is None:
            skipped.append({"bodyName": name, "reason": "no broad surfaces"})
            continue

        reflected = False
        if callable(_body_has_reflection):
            try:
                reflected = bool(_body_has_reflection(body))
            except Exception:
                reflected = False
        if reflected:
            shared_mirror.append({"bodyName": name})
            warnings.append(
                "{}: mirrored occurrence — Select highlights the shared native "
                "MILLING face; Nesting re-applies XY mirror for opposite chirality."
                .format(name)
            )

        role_a = _current_milling_role(surface_a)
        role_b = _current_milling_role(surface_b)
        milling = []
        either = []
        for face, role in ((surface_a, role_a), (surface_b, role_b)):
            if role == MILLING_SURFACE:
                milling.append(face)
            elif role == MILLING_SURFACE_EITHER:
                either.append(face)

        if milling:
            faces.extend(milling)
            continue

        if either:
            pick = random.choice(either)
            faces.append(pick)
            either_picked.append({"bodyName": name})
            continue

        skipped.append({
            "bodyName": name,
            "reason": "no MILLING/EITHER face stored (roles: {}/{})".format(
                role_a or "UNASSIGNED", role_b or "UNASSIGNED"
            ),
        })
    return {
        "faces": faces,
        "eitherPicked": either_picked,
        "skipped": skipped,
        "sharedMirrorOccurrence": shared_mirror,
        "warnings": warnings[:40],
    }


def swap_decision(role_a, role_b):
    """Which face becomes the new MILLING when swapping ("A"/"B"/None).

    Swappable when exactly one face currently holds MILLING — the opposite
    face takes it over. Ambiguous pairs (EITHER / dual / empty) return None;
    ``swap_surface_roles`` then commits a complementary pair instead of
    skipping.
    """
    role_a = str(role_a or "").strip().upper()
    role_b = str(role_b or "").strip().upper()
    a_milling = role_a == MILLING_SURFACE
    b_milling = role_b == MILLING_SURFACE
    if a_milling and not b_milling:
        return "B"
    if b_milling and not a_milling:
        return "A"
    return None


def _resolve_swap_faces(body, surface_a, surface_b, role_a, role_b, preferred_face=None):
    """Return ``(new_milling, new_non_milling)`` for Revert Panel Surface.

    Manual revert always yields definite MILLING/NON_MILLING. Hinge cups and
    centreline symmetry are never gates — any panel can be overridden.

    - Already complementary → flip
    - EITHER / unassigned / dual-same → commit complementary:
      * selected face (if any) becomes colour (NON_MILLING)
      * else soft-hint from hinge/half-slot (flipped = revert of auto)
      * else A=MILLING, B=NON_MILLING (second Revert flips)
    """
    decision = swap_decision(role_a, role_b)
    if decision == "A":
        return surface_a, surface_b
    if decision == "B":
        return surface_b, surface_a

    key_a = _safe_face_key(surface_a)
    key_b = _safe_face_key(surface_b)
    pref_key = _safe_face_key(preferred_face) if preferred_face is not None else ""
    if pref_key and pref_key in (key_a, key_b):
        # Explicit face pick: that face is the colour (show) side.
        if pref_key == key_a:
            return surface_b, surface_a
        return surface_a, surface_b

    # Soft hints only — missing hinge/slot must still commit definite roles.
    detected = detect_hinge_back_face(body) if callable(detect_hinge_back_face) else None
    if detected and detected.get("millingFace") is not None:
        auto_key = _safe_face_key(detected["millingFace"])
        if auto_key == key_a:
            return surface_b, surface_a
        if auto_key == key_b:
            return surface_a, surface_b

    try:
        slot_roles = _half_slot_surface_roles(body, surface_a, surface_b)
    except Exception:
        slot_roles = None
    if slot_roles and MILLING_SURFACE in slot_roles:
        if slot_roles[0] == MILLING_SURFACE and slot_roles[1] != MILLING_SURFACE:
            return surface_b, surface_a
        if slot_roles[1] == MILLING_SURFACE and slot_roles[0] != MILLING_SURFACE:
            return surface_a, surface_b

    # No machining evidence: still override EITHER → definite A/B.
    return surface_a, surface_b


def swap_surface_roles(bodies, write_roles, is_door_body=None, preferred_faces=None):
    """Manual front/back override on selected panels.

    Works for doors with or without hinge cups, symmetric or not, and for
    EITHER/EITHER — always writes definite MILLING/NON_MILLING via
    ``write_roles``. ``preferred_faces`` maps ``id(body)`` → selected face.
    """
    updated = []
    skipped = []
    warnings = []
    preferred_faces = preferred_faces or {}
    for body in bodies or []:
        name = _body_name(body)
        if callable(is_door_body) and not is_door_body(body):
            skipped.append({"bodyName": name, "reason": "not_door"})
            continue
        surface_a, surface_b, classify_warnings = classify_body_surfaces(body)
        warnings.extend(classify_warnings or [])
        if surface_a is None or surface_b is None:
            skipped.append({"bodyName": name, "reason": "no broad surfaces"})
            continue
        role_a = _current_milling_role(surface_a)
        role_b = _current_milling_role(surface_b)
        preferred = preferred_faces.get(id(body))
        new_milling, new_non = _resolve_swap_faces(
            body, surface_a, surface_b, role_a, role_b, preferred_face=preferred
        )
        if new_milling is None or new_non is None or new_milling is new_non:
            skipped.append({
                "bodyName": name,
                "reason": "could not resolve opposite broad faces (roles: {}/{})".format(
                    role_a or "UNASSIGNED", role_b or "UNASSIGNED"
                ),
            })
            continue
        if callable(write_roles):
            try:
                write_roles(body, new_milling, new_non)
            except Exception as ex:
                skipped.append({"bodyName": name, "reason": str(ex)})
                warnings.append("{}: write failed ({})".format(name, ex))
                continue
        updated.append({
            "bodyName": name,
            "fromRoles": [role_a or "UNASSIGNED", role_b or "UNASSIGNED"],
            "overrodeEither": (
                str(role_a or "").upper() == MILLING_SURFACE_EITHER
                and str(role_b or "").upper() == MILLING_SURFACE_EITHER
            ),
        })

    message = "Swapped door faces: updated {}, skipped {}.".format(len(updated), len(skipped))
    return {
        "ok": len(updated) > 0,
        "updatedCount": len(updated),
        "skippedCount": len(skipped),
        "updated": updated,
        "skipped": skipped,
        "warnings": warnings[:40],
        "message": message,
    }


def diagnose_hinge_faces(bodies):
    """Per-body report of how hinge-cup open faces and MILLING roles line up.

    Pure read-only: nothing is written. Used by the palette diagnostics card
    so the user can copy the report when orientation looks wrong.
    """
    reports = []
    for body in bodies or []:
        name = _body_name(body)
        report = {"bodyName": name}
        surface_a, surface_b, warnings = classify_body_surfaces(body)
        report["warnings"] = list(warnings or [])
        if surface_a is None or surface_b is None:
            report["error"] = "could not classify two broad surfaces"
            reports.append(report)
            continue

        token_a = _safe_entity_token(surface_a)
        token_b = _safe_entity_token(surface_b)
        role_a = _current_milling_role(surface_a) or "UNASSIGNED"
        role_b = _current_milling_role(surface_b) or "UNASSIGNED"
        report["surfaceA"] = {"token": token_a[-12:], "millingRole": role_a}
        report["surfaceB"] = {"token": token_b[-12:], "millingRole": role_b}

        features = _extract_half_features(body, surface_a, surface_b)
        hinge_features = [f for f in features if is_hinge_cup_feature(f)]
        report["halfFeatureCount"] = len(features)
        report["hingeCupCount"] = len(hinge_features)
        report["hingeCups"] = [
            {
                "depthMm": feature.get("depthMm"),
                "radiusMm": feature.get("radiusMm"),
                "floorOffsetMm": feature.get("floorOffsetMm"),
                "opensOnto": feature.get("openSurfaceIs") or "?",
                "decision": feature.get("openDecision") or {},
            }
            for feature in hinge_features[:10]
        ]

        detected = detect_hinge_back_face(body)
        if detected:
            det_milling_key = _safe_face_key(detected["millingFace"])
            expected = "A" if det_milling_key == _safe_face_key(surface_a) else "B"
            report["detectedBack"] = expected
            actual_milling = (
                "A" if role_a == MILLING_SURFACE else ("B" if role_b == MILLING_SURFACE else "none")
            )
            report["storedMilling"] = actual_milling
            report["rolesMatchDetection"] = (actual_milling == expected)
        else:
            report["detectedBack"] = None
            report["storedMilling"] = (
                "A" if role_a == MILLING_SURFACE else ("B" if role_b == MILLING_SURFACE else "none")
            )
            report["rolesMatchDetection"] = None
        reports.append(report)
    return reports


def _current_milling_role(face):
    try:
        from face_attribute_store import read_face_metadata
    except Exception:
        try:
            from metadata.face_attribute_store import read_face_metadata
        except Exception:
            return ""
    if not callable(read_face_metadata):
        return ""
    try:
        metadata, _error = read_face_metadata(face)
    except Exception:
        return ""
    if not isinstance(metadata, dict):
        return ""
    return str(metadata.get("millingSurface") or "").strip().upper()


def _manual_face_up_locked(body):
    try:
        import attribute_state_service
        from tag_metadata_editor import _read_body_metadata_raw
    except Exception:
        try:
            from panel_attributes import attribute_state_service
            from panel_attributes.tag_metadata_editor import _read_body_metadata_raw
        except Exception:
            return False
    try:
        metadata, _error = _read_body_metadata_raw(body)
        return bool(attribute_state_service.face_up_state(metadata).get("locked"))
    except Exception:
        return False


def _resolve_conflict(target_milling_face, target_non_milling_face):
    """Return (action, warning) where action is apply|skip_same|skip_conflict."""
    current_milling = _current_milling_role(target_milling_face)
    current_opposite = _current_milling_role(target_non_milling_face)
    if current_milling == MILLING_SURFACE and current_opposite in (
        NON_MILLING_SURFACE,
        "",
        MILLING_SURFACE_EITHER,
        "UNASSIGNED",
    ):
        return "skip_same", ""
    if current_opposite == MILLING_SURFACE and current_milling != MILLING_SURFACE:
        return "skip_conflict", "already has MILLING on the opposite face"
    return "apply", ""


def propagate_milling_from_hinge_cups(bodies, write_roles=None):
    """Detect hinge-cup backs and propagate to coplanar same-orientation panels.

    ``write_roles(body, milling_face, non_milling_face)`` performs Fusion write-back.
    Returns a result dict with counts and details.
    """
    bodies = list(bodies or [])
    warnings = []
    sources = []
    updated = []
    skipped = []

    # Build per-body surface pairs once.
    body_surfaces = {}
    for body in bodies:
        surface_a, surface_b, classify_warnings = classify_body_surfaces(body)
        warnings.extend(classify_warnings)
        if surface_a is None:
            continue
        body_surfaces[id(body)] = {
            "body": body,
            "surfaces": (surface_a, surface_b),
            "bodyName": _body_name(body),
        }

    # Detect sources.
    source_records = []
    for entry in body_surfaces.values():
        detected = detect_hinge_back_face(entry["body"])
        if not detected:
            continue
        warnings.extend(detected.get("warnings") or [])
        n_src, c_src = face_world_plane(detected["millingFace"])
        if not n_src or not c_src:
            warnings.append("{}: could not read world plane for hinge back face.".format(entry["bodyName"]))
            continue
        source_records.append({
            **detected,
            "normal": n_src,
            "centroid": c_src,
        })
        sources.append({
            "bodyName": entry["bodyName"],
            "hingeCount": detected.get("hingeCount") or 0,
        })

    if not source_records:
        return {
            "ok": False,
            "sourceCount": 0,
            "updatedCount": 0,
            "skippedCount": 0,
            "sources": [],
            "updated": [],
            "skipped": [],
            "warnings": warnings + ["No hinge-cup source panels found in selection."],
            "message": "No hinge-cup source panels found in selection.",
        }

    # Also apply roles on source panels themselves.
    touched_body_ids = set()
    for source in source_records:
        body = source["body"]
        body_id = id(body)
        if body_id in touched_body_ids:
            continue
        if _manual_face_up_locked(body):
            skipped.append({"bodyName": source["bodyName"], "reason": "manual face-up lock"})
            touched_body_ids.add(body_id)
            continue
        action, reason = _resolve_conflict(source["millingFace"], source["nonMillingFace"])
        if action == "skip_same":
            skipped.append({"bodyName": source["bodyName"], "reason": "already MILLING on hinge back"})
            touched_body_ids.add(body_id)
            continue
        if action == "skip_conflict":
            skipped.append({"bodyName": source["bodyName"], "reason": reason})
            warnings.append("{}: {}".format(source["bodyName"], reason))
            touched_body_ids.add(body_id)
            continue
        if callable(write_roles):
            try:
                write_roles(body, source["millingFace"], source["nonMillingFace"])
            except Exception as ex:
                skipped.append({"bodyName": source["bodyName"], "reason": str(ex)})
                warnings.append("{}: write failed ({})".format(source["bodyName"], ex))
                touched_body_ids.add(body_id)
                continue
        updated.append({"bodyName": source["bodyName"], "from": "hinge_source"})
        touched_body_ids.add(body_id)

    # Propagate to coplanar same-orientation targets.
    for entry in body_surfaces.values():
        body = entry["body"]
        body_id = id(body)
        if body_id in touched_body_ids:
            continue
        surface_a, surface_b = entry["surfaces"]
        matched_milling = None
        matched_non = None
        matched_source_name = ""
        for source in source_records:
            for candidate, opposite in ((surface_a, surface_b), (surface_b, surface_a)):
                n_tgt, c_tgt = face_world_plane(candidate)
                if planes_coplanar_same_orientation(
                    source["normal"], source["centroid"], n_tgt, c_tgt
                ):
                    matched_milling = candidate
                    matched_non = opposite
                    matched_source_name = source["bodyName"]
                    break
            if matched_milling is not None:
                break

        if matched_milling is None:
            skipped.append({"bodyName": entry["bodyName"], "reason": "no coplanar same-orientation hinge back"})
            continue

        if _manual_face_up_locked(body):
            skipped.append({"bodyName": entry["bodyName"], "reason": "manual face-up lock"})
            continue

        action, reason = _resolve_conflict(matched_milling, matched_non)
        if action == "skip_same":
            skipped.append({"bodyName": entry["bodyName"], "reason": "already matches propagated back"})
            continue
        if action == "skip_conflict":
            skipped.append({"bodyName": entry["bodyName"], "reason": reason})
            warnings.append("{}: {}".format(entry["bodyName"], reason))
            continue

        if callable(write_roles):
            try:
                write_roles(body, matched_milling, matched_non)
            except Exception as ex:
                skipped.append({"bodyName": entry["bodyName"], "reason": str(ex)})
                warnings.append("{}: write failed ({})".format(entry["bodyName"], ex))
                continue

        updated.append({
            "bodyName": entry["bodyName"],
            "from": "propagated",
            "sourceBodyName": matched_source_name,
        })
        touched_body_ids.add(body_id)

    message = (
        "Hinge back propagation: sources {}, updated {}, skipped {}."
        .format(len(sources), len(updated), len(skipped))
    )
    return {
        "ok": len(updated) > 0,
        "sourceCount": len(sources),
        "updatedCount": len(updated),
        "skippedCount": len(skipped),
        "sources": sources,
        "updated": updated,
        "skipped": skipped,
        "warnings": warnings[:40],
        "message": message,
    }
