"""Auto-orient door panel faces from an observation point (two-vote model).

Locked rules:
1. Machining wins: hinge cups / half-slots decide the back (MILLING) face.
2. Assembly vote (primary): the broad face pointing away from the panel's
   owning root-level sub-assembly centre M (each GT_/OHC_/Lounge_/Fridge/…
   child of the design root — not the root design itself) is the colour
   face (NON_MILLING). M must sit on the opposite side of the panel from
   the observation point O; otherwise the centre is treated as a room/run
   void and the assembly vote abstains.
3. View-point vote (secondary): the broad face aimed at O (the "red dot")
   is the colour face; used when assembly is unavailable, or as a
   supporting check when it agrees.
4. Votes agree -> write. Votes conflict -> assembly wins (outward > view),
   but only when the assembly centre passed the behind-panel check.
5. Nothing decisive -> EITHER on both faces (symmetric boards can be flipped).
"""

VIEW_VOTE_MIN_MARGIN = 0.25

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
    from milling_surface_propagation import (
        classify_body_surfaces,
        detect_hinge_back_face,
        face_world_plane,
        normalize_vector,
        dot3,
    )
except Exception:
    try:
        from panel_attributes.milling_surface_propagation import (
            classify_body_surfaces,
            detect_hinge_back_face,
            face_world_plane,
            normalize_vector,
            dot3,
        )
    except Exception:
        classify_body_surfaces = None
        detect_hinge_back_face = None
        face_world_plane = None

        def normalize_vector(vector):
            values = [float(vector[0]), float(vector[1]), float(vector[2])]
            length = sum(value * value for value in values) ** 0.5
            if length <= 1e-9:
                return [0.0, 0.0, 1.0]
            return [value / length for value in values]

        def dot3(left, right):
            return sum(float(left[index]) * float(right[index]) for index in range(3))


# ---------------------------------------------------------------------------
# Pure geometry (unit-testable, no Fusion)
# ---------------------------------------------------------------------------

def face_view_score(normal, centroid, observation_point):
    """How directly this face aims at the observation point (-1..1)."""
    if not normal or not centroid or not observation_point:
        return None
    to_observer = [
        float(observation_point[0]) - float(centroid[0]),
        float(observation_point[1]) - float(centroid[1]),
        float(observation_point[2]) - float(centroid[2]),
    ]
    length = sum(value * value for value in to_observer) ** 0.5
    if length <= 1e-9:
        return None
    unit = [value / length for value in to_observer]
    return dot3(normalize_vector(normal), unit)


def vote_from_scores(score_a, score_b, min_margin=VIEW_VOTE_MIN_MARGIN):
    """Return "A" / "B" (colour face) or None when too close to call."""
    if score_a is None or score_b is None:
        return None
    if abs(score_a - score_b) < float(min_margin):
        return None
    return "A" if score_a > score_b else "B"


def view_point_vote(normal_a, centroid_a, normal_b, centroid_b, observation_point,
                    min_margin=VIEW_VOTE_MIN_MARGIN):
    """Colour-face vote from the observation point ("red dot")."""
    score_a = face_view_score(normal_a, centroid_a, observation_point)
    score_b = face_view_score(normal_b, centroid_b, observation_point)
    return vote_from_scores(score_a, score_b, min_margin)


def _panel_midpoint(centroid_a, centroid_b):
    if not centroid_a or not centroid_b:
        return None
    return [
        (float(centroid_a[0]) + float(centroid_b[0])) / 2.0,
        (float(centroid_a[1]) + float(centroid_b[1])) / 2.0,
        (float(centroid_a[2]) + float(centroid_b[2])) / 2.0,
    ]


def _panel_thickness_normal(normal_a, normal_b, centroid_a, centroid_b):
    """Unit normal along panel thickness (either broad-face direction).

    Prefer the vector between the two face centroids (stable even when one
    face normal is flipped). Fall back to ``normal_a``.
    """
    if centroid_a and centroid_b:
        delta = [
            float(centroid_b[0]) - float(centroid_a[0]),
            float(centroid_b[1]) - float(centroid_a[1]),
            float(centroid_b[2]) - float(centroid_a[2]),
        ]
        if sum(value * value for value in delta) > 1e-9:
            return normalize_vector(delta)
    if normal_a:
        return normalize_vector(normal_a)
    if normal_b:
        return normalize_vector(normal_b)
    return None


def assembly_center_behind_panel(centroid_a, centroid_b, assembly_center, observation_point,
                                 normal_a=None, normal_b=None):
    """True when M is on the opposite side of the panel from O (cabinet vs room).

    Large L-shaped / multi-cabinet runs often put the occurrence bbox centre in
    the open void. That point sits on the *same* side as the observation point,
    and "outward = away from M" then picks the interior face. Reject that case.

    Side-of-panel is measured along the **thickness normal only**. A full 3D
    ``dot(to_m, to_o)`` falsely abstains on wide cabinets: a door far from M in
    X/Z can make the raw vectors acute even when M is clearly behind the door
    in Y. Those doors then fall back to the view vote while neighbours still
    use assembly — coplanar boards flip relative to each other.
    """
    mid = _panel_midpoint(centroid_a, centroid_b)
    if not mid or not assembly_center or not observation_point:
        return None
    axis = _panel_thickness_normal(normal_a, normal_b, centroid_a, centroid_b)
    if not axis:
        return None
    to_m = [
        float(assembly_center[0]) - mid[0],
        float(assembly_center[1]) - mid[1],
        float(assembly_center[2]) - mid[2],
    ]
    to_o = [
        float(observation_point[0]) - mid[0],
        float(observation_point[1]) - mid[1],
        float(observation_point[2]) - mid[2],
    ]
    signed_m = dot3(axis, to_m)
    signed_o = dot3(axis, to_o)
    if abs(signed_m) <= 1e-9 or abs(signed_o) <= 1e-9:
        return None
    # Opposite half-spaces along thickness => M is behind the door.
    return (signed_m * signed_o) < 0.0


def assembly_vote(normal_a, centroid_a, normal_b, centroid_b, assembly_center,
                  min_margin=VIEW_VOTE_MIN_MARGIN, observation_point=None):
    """Colour-face vote from the panel's own assembly: outward face = colour.

    Outward = pointing AWAY from the assembly centre, so the score is the
    negative of the view score toward the centre.

    When ``observation_point`` is set, M must lie on the opposite side of the
    panel from O; otherwise the centre is treated as unreliable (room/run void)
    and this vote abstains so the view-point vote can stand.
    """
    score_a = face_view_score(normal_a, centroid_a, assembly_center)
    score_b = face_view_score(normal_b, centroid_b, assembly_center)
    if score_a is None or score_b is None:
        return None
    if observation_point is not None:
        behind = assembly_center_behind_panel(
            centroid_a, centroid_b, assembly_center, observation_point,
            normal_a=normal_a, normal_b=normal_b,
        )
        if behind is not True:
            return None
    return vote_from_scores(-score_a, -score_b, min_margin)


def combine_votes(view_vote_result, assembly_vote_result):
    """Merge the two votes. Assembly outward face outranks the view point.

    Returns one of: "A" / "B" (colour face), "either".
    When both votes exist and disagree, assembly wins.
    """
    if assembly_vote_result:
        return assembly_vote_result
    if view_vote_result:
        return view_vote_result
    return "either"


def bounding_center(points_min_max):
    """Center of a list of (min_xyz, max_xyz) boxes in mm. Returns None if empty."""
    boxes = [item for item in points_min_max or [] if item]
    if not boxes:
        return None
    mins = [min(box[0][axis] for box in boxes) for axis in range(3)]
    maxs = [max(box[1][axis] for box in boxes) for axis in range(3)]
    return [(mins[axis] + maxs[axis]) / 2.0 for axis in range(3)]


# ---------------------------------------------------------------------------
# Fusion-touching helpers
# ---------------------------------------------------------------------------

def _body_bbox_mm(body):
    """World bounding box of a body as (min_mm, max_mm), or None."""
    try:
        bbox = body.boundingBox
        if not bbox:
            return None
        min_pt = bbox.minPoint
        max_pt = bbox.maxPoint
        return (
            [min_pt.x * 10.0, min_pt.y * 10.0, min_pt.z * 10.0],
            [max_pt.x * 10.0, max_pt.y * 10.0, max_pt.z * 10.0],
        )
    except Exception:
        return None


def observation_point_from_bodies(bodies):
    """Auto observation point: centre of the union bbox of all bodies (mm)."""
    return bounding_center([_body_bbox_mm(body) for body in bodies or []])


def _bbox_center_mm(bbox):
    """Centre of a Fusion BoundingBox3D in mm, or None."""
    if not bbox:
        return None
    try:
        min_pt = bbox.minPoint
        max_pt = bbox.maxPoint
        return [
            (min_pt.x + max_pt.x) * 5.0,
            (min_pt.y + max_pt.y) * 5.0,
            (min_pt.z + max_pt.z) * 5.0,
        ]
    except Exception:
        return None


def _occurrence_for_assembly_center(body):
    """Root-level child occurrence whose bbox is the cabinet centre M.

    Browser hierarchy is typically::

        Root design  (e.g. "Bunk Bed and Bathroom")
          ├─ GT_xxx / OHC:1 / Fridge:1 / LOUNGE_…   ← M lives here
          │    └─ per-board leaf occurrence
          │         └─ door body
          └─ …

    Climb ``assemblyContext`` from the body until the occurrence whose parent
    is None — that is a direct child of the design root (one cabinet /
    sub-assembly). Do **not** use the root design bbox, and do **not** stop
    at the thin per-board leaf.
    """
    try:
        occurrence = getattr(body, "assemblyContext", None)
    except Exception:
        occurrence = None
    if occurrence is None:
        return None

    seen = set()
    while True:
        try:
            marker = id(occurrence)
        except Exception:
            marker = None
        if marker is not None:
            if marker in seen:
                return occurrence
            seen.add(marker)
        try:
            parent = getattr(occurrence, "assemblyContext", None)
        except Exception:
            parent = None
        if parent is None:
            # Direct child of root — the per-cabinet / sub-assembly unit.
            return occurrence
        occurrence = parent


def assembly_center_for_body(body):
    """World centre (mm) of the body's owning root-level cabinet occurrence.

    Resolves the occurrence that is a direct child of the design root (each
    GT_/OHC_/Lounge_/Fridge/… sub-assembly), not the root design and not the
    leaf door component. Falls back to the body's own world bbox when no
    occurrence is available.
    """
    occurrence = _occurrence_for_assembly_center(body)
    if occurrence is not None:
        try:
            center = _bbox_center_mm(occurrence.boundingBox)
            if center is not None:
                return center
        except Exception:
            pass
    return bounding_center([_body_bbox_mm(body)])


def _body_name(body):
    return str(getattr(body, "name", "") or "") or "body"


def _entity_token(entity):
    try:
        return str(getattr(entity, "entityToken", "") or "")
    except Exception:
        return ""


def _face_milling_role(face, registry_by_token=None):
    """Read millingSurface from face attrs, falling back to faceRegistry by token."""
    try:
        from face_attribute_store import read_face_metadata
    except Exception:
        try:
            from metadata.face_attribute_store import read_face_metadata
        except Exception:
            read_face_metadata = None
    if callable(read_face_metadata):
        try:
            metadata, _error = read_face_metadata(face)
            if isinstance(metadata, dict):
                role = str(metadata.get("millingSurface") or "").strip().upper()
                if role:
                    return role
        except Exception:
            pass
    token = _entity_token(face)
    if token and isinstance(registry_by_token, dict):
        entry = registry_by_token.get(token) or {}
        return str(entry.get("millingSurface") or "").strip().upper()
    return ""


def collect_door_colour_faces(bodies, is_door_body):
    """Return colour faces (NON_MILLING) for door panels in ``bodies``.

    ``is_door_body(body)`` should return True for door-panel material bodies.
    Bodies with only EITHER / missing roles are skipped (no clear front).
    """
    faces = []
    skipped = []
    warnings = []
    for body in bodies or []:
        name = _body_name(body)
        if not callable(is_door_body) or not is_door_body(body):
            skipped.append({"bodyName": name, "reason": "not_door"})
            continue

        registry_by_token = {}
        try:
            from tag_metadata_editor import _read_body_metadata_raw
        except Exception:
            try:
                from panel_attributes.tag_metadata_editor import _read_body_metadata_raw
            except Exception:
                _read_body_metadata_raw = None
        if callable(_read_body_metadata_raw):
            metadata, _err = _read_body_metadata_raw(body)
            registry = (metadata or {}).get("faceRegistry") if isinstance(metadata, dict) else {}
            for entry in (registry or {}).get("faces") or []:
                if not isinstance(entry, dict):
                    continue
                token = str(entry.get("entityToken") or "").strip()
                if token:
                    registry_by_token[token] = entry

        colour = []
        milling = []
        either = []
        try:
            from panel_face_initializer import iter_body_faces
        except Exception:
            try:
                from metadata.panel_face_initializer import iter_body_faces
            except Exception:
                iter_body_faces = None
        if not callable(iter_body_faces):
            skipped.append({"bodyName": name, "reason": "iter_faces_unavailable"})
            continue

        for face in iter_body_faces(body):
            role = _face_milling_role(face, registry_by_token)
            if role == NON_MILLING_SURFACE:
                colour.append(face)
            elif role == MILLING_SURFACE:
                milling.append(face)
            elif role == MILLING_SURFACE_EITHER:
                either.append(face)

        if colour:
            faces.extend(colour)
        elif milling and not either:
            # Oriented but colour face missing from attrs — skip with warning.
            skipped.append({"bodyName": name, "reason": "no_colour_face"})
            warnings.append("{}: has MILLING but no NON_MILLING colour face.".format(name))
        else:
            skipped.append({"bodyName": name, "reason": "either_or_unassigned"})
            warnings.append("{}: no clear colour face (EITHER / unassigned).".format(name))

    return {
        "faces": faces,
        "selectedCount": len(faces),
        "skipped": skipped,
        "warnings": warnings,
    }


def _half_slot_back_face(body, surface_a, surface_b):
    """Half-slot machining vote: face the slot opens onto = back (MILLING)."""
    try:
        from panel_face_initializer import detect_surface_milling_roles, classify_box_faces
    except Exception:
        try:
            from metadata.panel_face_initializer import detect_surface_milling_roles, classify_box_faces
        except Exception:
            return None, None
    try:
        panel_context = {"body": body, "bodyName": _body_name(body)}
        classified = classify_box_faces(body, panel_context)
        edge_faces = classified.get("edgeFaces") or []
        roles = detect_surface_milling_roles([surface_a, surface_b], edge_faces, panel_context)
    except Exception:
        return None, None
    if len(roles) < 2:
        return None, None
    if roles[0] == MILLING_SURFACE and roles[1] == NON_MILLING_SURFACE:
        return surface_a, surface_b
    if roles[1] == MILLING_SURFACE and roles[0] == NON_MILLING_SURFACE:
        return surface_b, surface_a
    return None, None


def orient_door_faces(body_entries, observation_point, write_roles, write_either=None,
                      min_margin=VIEW_VOTE_MIN_MARGIN):
    """Orient door panels using machining first, then the two-vote model.

    ``body_entries``: list of {"body": body, "assemblyCenter": [x,y,z]|None}.
    ``write_roles(body, milling_face, non_milling_face)`` writes MILLING/NON_MILLING.
    ``write_either(body, face_a, face_b)`` writes EITHER on both broad faces.
    """
    results = {
        "updated": [],       # written MILLING/NON_MILLING
        "machining": [],     # decided by hinge cups / half-slots
        "either": [],        # written or left as EITHER
        "conflicts": [],     # retained for API compat; assembly now wins on disagreement
        "skipped": [],       # classify failed / write failed
        "warnings": [],
    }

    for entry in body_entries or []:
        body = entry.get("body")
        name = _body_name(body)
        token = _entity_token(body)

        surface_a, surface_b, classify_warnings = (
            classify_body_surfaces(body) if callable(classify_body_surfaces) else (None, None, ["classify unavailable"])
        )
        results["warnings"].extend(classify_warnings or [])
        if surface_a is None or surface_b is None:
            results["skipped"].append({"bodyName": name, "entityToken": token, "reason": "no broad surfaces"})
            continue

        # --- Priority 1: machining (hinge cups, then half-slots) ---
        milling_face = None
        non_milling_face = None
        detected = detect_hinge_back_face(body) if callable(detect_hinge_back_face) else None
        if detected:
            milling_face = detected.get("millingFace")
            non_milling_face = detected.get("nonMillingFace")
            source = "hinge_cups"
        else:
            milling_face, non_milling_face = _half_slot_back_face(body, surface_a, surface_b)
            source = "half_slot"

        if milling_face is not None and non_milling_face is not None:
            try:
                try:
                    write_roles(
                        body,
                        milling_face,
                        non_milling_face,
                        source=source,
                    )
                except TypeError:
                    write_roles(body, milling_face, non_milling_face)
                results["machining"].append({"bodyName": name, "entityToken": token, "source": source})
            except Exception as ex:
                reason = str(ex)
                results["skipped"].append({
                    "bodyName": name,
                    "entityToken": token,
                    "reason": (
                        "manual face-up lock; automatic orientation skipped"
                        if reason == "manual_locked"
                        else reason
                    ),
                })
            continue

        # --- Priority 2: two-vote model ---
        n_a, c_a = face_world_plane(surface_a) if callable(face_world_plane) else (None, None)
        n_b, c_b = face_world_plane(surface_b) if callable(face_world_plane) else (None, None)
        if not n_a or not n_b:
            results["skipped"].append({"bodyName": name, "entityToken": token, "reason": "no world plane data"})
            continue

        view = view_point_vote(n_a, c_a, n_b, c_b, observation_point, min_margin) if observation_point else None
        assembly_center = entry.get("assemblyCenter")
        local = (
            assembly_vote(
                n_a, c_a, n_b, c_b, assembly_center,
                min_margin=min_margin,
                observation_point=observation_point,
            )
            if assembly_center
            else None
        )

        decision = combine_votes(view, local)

        if decision in ("A", "B"):
            colour_face = surface_a if decision == "A" else surface_b
            back_face = surface_b if decision == "A" else surface_a
            if view and local and view != local:
                vote_source = "assembly_over_view"
            elif view and local:
                vote_source = "both"
            elif local:
                vote_source = "assembly"
            else:
                vote_source = "view"
            try:
                try:
                    write_roles(
                        body,
                        back_face,
                        colour_face,
                        source="assembly",
                    )
                except TypeError:
                    write_roles(body, back_face, colour_face)
                results["updated"].append({
                    "bodyName": name,
                    "entityToken": token,
                    "votes": vote_source,
                    "viewVote": view,
                    "assemblyVote": local,
                })
            except Exception as ex:
                results["skipped"].append({"bodyName": name, "entityToken": token, "reason": str(ex)})
            continue

        # decision == "either"
        if callable(write_either):
            try:
                try:
                    write_either(body, surface_a, surface_b, source="assembly")
                except TypeError:
                    write_either(body, surface_a, surface_b)
            except Exception as ex:
                results["skipped"].append({"bodyName": name, "entityToken": token, "reason": str(ex)})
                continue
        results["either"].append({"bodyName": name, "entityToken": token})

    return results
