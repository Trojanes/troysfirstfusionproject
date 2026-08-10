"""Re-extract manufacturing outline + features on Lay Flat bodies.

Before extract, orient the true outline face to −Z (geometry only — tags are
preserved via attribute snapshot/restore) so edge-open grooves face the camera
for visual inspection.
"""

from __future__ import annotations

import json
import time

try:
    from nesting.outline_cache import (
        CACHE_KEY,
        CACHE_SCHEMA,
        attribute_entities,
        build_cache_record,
        body_geometry_signature,
    )
    from nesting.outline import build_outline_payload, polygon_bounds
except Exception:
    from outline_cache import (  # type: ignore
        CACHE_KEY,
        CACHE_SCHEMA,
        attribute_entities,
        build_cache_record,
        body_geometry_signature,
    )
    from outline import build_outline_payload, polygon_bounds  # type: ignore

try:
    from nesting.fusion_layout import (
        _bbox_dimensions_mm,
        _fast_broad_faces,
    )
except Exception:
    try:
        from fusion_layout import (  # type: ignore
            _bbox_dimensions_mm,
            _fast_broad_faces,
        )
    except Exception:
        _bbox_dimensions_mm = None
        _fast_broad_faces = None

try:
    from panel_attributes.milling_surface_propagation import face_world_plane
except Exception:
    try:
        from milling_surface_propagation import face_world_plane
    except Exception:
        face_world_plane = None

try:
    from nesting.lay_flat_face_up import _assign_milling_and_colour
except Exception:
    try:
        from lay_flat_face_up import _assign_milling_and_colour  # type: ignore
    except Exception:
        _assign_milling_and_colour = None

try:
    from metadata.panel_geometry import (
        extract_features,
        _public_feature,
        _face_centroid_local_mm,
        thickness_axis_from_normal,
        _face_normal_local,
        _face_outer_loop_2d,
    )
except Exception:
    try:
        from panel_geometry import (
            extract_features,
            _public_feature,
            _face_centroid_local_mm,
            thickness_axis_from_normal,
            _face_normal_local,
            _face_outer_loop_2d,
        )
    except Exception:
        extract_features = None
        _public_feature = None
        _face_centroid_local_mm = None
        thickness_axis_from_normal = None
        _face_normal_local = None
        _face_outer_loop_2d = None

try:
    from nesting.brep_loops import (
        extract_flattened_rings_mm,
        _floor_feature_rings_mm,
        _face_normal_z,
        select_true_outer_face,
    )
except Exception:
    try:
        from brep_loops import (  # type: ignore
            extract_flattened_rings_mm,
            _floor_feature_rings_mm,
            _face_normal_z,
            select_true_outer_face,
        )
    except Exception:
        extract_flattened_rings_mm = None
        _floor_feature_rings_mm = None
        _face_normal_z = None
        select_true_outer_face = None

try:
    from nesting.lay_flat_fusion import flip_lay_flat_body_thickness
except Exception:
    try:
        from lay_flat_fusion import flip_lay_flat_body_thickness  # type: ignore
    except Exception:
        flip_lay_flat_body_thickness = None

PANEL_GROUP = "UnifiedCabinet.Panel"
ANALYZED_STATE = "lay_flat_analyzed"
_OUTLINE_DOWN_DOT = -0.7


def outline_extraction_face_is_down(body, min_dot=None):
    """True when the true outer/outline face already points toward −Z."""
    threshold = float(min_dot if min_dot is not None else _OUTLINE_DOWN_DOT)
    if body is None or not callable(select_true_outer_face) or not callable(_face_normal_z):
        return True
    try:
        face = select_true_outer_face(body)
    except Exception:
        face = None
    if face is None:
        return True
    try:
        normal_z = _face_normal_z(face)
    except Exception:
        normal_z = None
    if normal_z is None:
        return True
    return float(normal_z) <= float(threshold)


def orient_outline_face_down(body):
    """Flip LAY_FLAT geometry so the outline face is −Z without changing tags.

    Uses the existing 180° X flip + attribute restore. No-op when already down.
    """
    if body is None:
        return {"ok": False, "flipped": False, "reason": "missing_body"}
    if outline_extraction_face_is_down(body):
        return {"ok": True, "flipped": False, "reason": "already_down"}
    if not callable(flip_lay_flat_body_thickness):
        return {
            "ok": False,
            "flipped": False,
            "reason": "flip_helper_unavailable",
        }
    result = flip_lay_flat_body_thickness(body) or {}
    if not result.get("ok"):
        return {
            "ok": False,
            "flipped": False,
            "reason": result.get("reason") or "geometry_flip_failed",
            "bodyName": result.get("bodyName") or "",
        }
    return {
        "ok": True,
        "flipped": True,
        "reason": "flipped",
        "bodyName": result.get("bodyName") or "",
        "attributesRestored": int(result.get("attributesRestored") or 0),
    }


def _metadata_richness(metadata):
    if not isinstance(metadata, dict):
        return 0
    score = 0
    classification = metadata.get("classification")
    if isinstance(classification, dict):
        for field in ("boardType", "color", "cuttingFace"):
            state = classification.get(field)
            if isinstance(state, dict) and str(state.get("value") or "").strip():
                score += 2
    if metadata.get(CACHE_KEY):
        score += 1
    if metadata.get("features"):
        score += 1
    return score


def _read_metadata(body):
    best = None
    best_score = -1
    for entity in attribute_entities(body):
        try:
            attr = entity.attributes.itemByName(PANEL_GROUP, "metadata")
            raw = str(attr.value or "") if attr else ""
        except Exception:
            continue
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        score = _metadata_richness(data)
        if score > best_score:
            best = data
            best_score = score
    return best or {}


def _write_metadata(body, metadata, panel_id=""):
    payload = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    wrote = False
    for entity in attribute_entities(body):
        try:
            attrs = entity.attributes
            if panel_id:
                existing_id = attrs.itemByName(PANEL_GROUP, "panelId")
                if existing_id:
                    existing_id.value = str(panel_id)
                else:
                    attrs.add(PANEL_GROUP, "panelId", str(panel_id))
            existing = attrs.itemByName(PANEL_GROUP, "metadata")
            if existing:
                existing.value = payload
            else:
                attrs.add(PANEL_GROUP, "metadata", payload)
            wrote = True
        except Exception:
            continue
    return wrote


def _translate_points(points, dx, dy):
    out = []
    for point in points or []:
        if isinstance(point, dict):
            out.append(
                [
                    round(float(point.get("x") or 0.0) + dx, 3),
                    round(float(point.get("y") or 0.0) + dy, 3),
                ]
            )
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            out.append([round(float(point[0]) + dx, 3), round(float(point[1]) + dy, 3)])
    return out


def _milling_and_colour_faces(body):
    if not callable(_fast_broad_faces) or not callable(face_world_plane):
        return None, None
    face_a, face_b = _fast_broad_faces(body)
    if face_a is None or face_b is None:
        return None, None
    normal_a, _ = face_world_plane(face_a)
    normal_b, _ = face_world_plane(face_b)
    if not normal_a or not normal_b:
        return None, None
    if callable(_assign_milling_and_colour):
        assigned = _assign_milling_and_colour(
            face_a, face_b, normal_a, normal_b
        )
        return assigned[0], assigned[1]
    if float(normal_a[2]) >= float(normal_b[2]):
        return face_a, face_b
    return face_b, face_a


def _origin_shift_mm(body, outline_points=None):
    """Shift used to put panel min-corner at (0,0), matching outline payload."""
    if outline_points:
        try:
            bounds = polygon_bounds(outline_points)
            return -float(bounds["minX"]), -float(bounds["minY"])
        except Exception:
            pass
    dims = _bbox_dimensions_mm(body)
    return -float(dims.get("minX") or 0.0), -float(dims.get("minY") or 0.0)


def _extract_features_for_body(body, milling_face, colour_face, dx, dy):
    if (
        not callable(extract_features)
        or not callable(_public_feature)
        or not callable(_face_centroid_local_mm)
        or not callable(_face_normal_local)
        or not callable(thickness_axis_from_normal)
    ):
        return [], "feature_helpers_unavailable"
    try:
        # LAY_FLAT is already manufacturing-up, so world XY is the canonical
        # panel frame and world Z is thickness. This must match brep_loops.
        thickness_axis = 2
        offset_a = _face_centroid_local_mm(
            milling_face, body, coordinate_mode="world"
        )[thickness_axis]
        offset_b = _face_centroid_local_mm(
            colour_face, body, coordinate_mode="world"
        )[thickness_axis]
        thickness_mm = abs(float(offset_a) - float(offset_b))
        raw = extract_features(
            body,
            milling_face,
            colour_face,
            thickness_axis,
            offset_a,
            offset_b,
            thickness_mm,
            coordinate_mode="world",
        ) or []
    except Exception as ex:
        return [], "feature_extract_failed:{}".format(ex)

    features = []
    for index, feature in enumerate(raw):
        public = _public_feature(feature)
        # Entity tokens belong to the live BRep topology and can conflict with
        # the analyzed A/B convention after copying. Persist only stable A/B.
        public.pop("openSurfaceToken", None)
        points = _translate_points(public.get("pointsLocal") or [], dx, dy)
        public["pointsLocal"] = points
        public["points"] = points
        center = public.get("center2d")
        if isinstance(center, (list, tuple)) and len(center) >= 2:
            public["center2d"] = [
                round(float(center[0]) + dx, 3),
                round(float(center[1]) + dy, 3),
            ]
        if public.get("radiusMm") and not public.get("diameterMm"):
            try:
                public["diameterMm"] = round(float(public["radiusMm"]) * 2.0, 3)
            except Exception:
                pass
        # surface_a was milling → A is machining face after Lay Flat.
        which = str(public.get("openSurfaceIs") or feature.get("openSurfaceIs") or "").upper()
        cut_type = str(public.get("cutType") or "").upper()
        if cut_type != "FULL":
            if which not in ("A", "B"):
                return [], "feature_face_unresolved"
            # Topology sometimes tags top-face dados/cups as B when walls also
            # touch the colour skin. Floor nearer colour ⇒ opens to milling A.
            if which == "B":
                try:
                    floor_z = float(feature.get("floorOffsetMm"))
                    dist_a = abs(floor_z - float(offset_a))
                    dist_b = abs(floor_z - float(offset_b))
                except Exception:
                    floor_z = None
                    dist_a = dist_b = 0.0
                if floor_z is not None and dist_b + 0.5 < dist_a:
                    which = "A"
                    public["depthMm"] = round(dist_a, 3)
                    public["openRemap"] = "floor_near_colour_to_milling"
                if feature.get("floorOffsetMm") is not None:
                    try:
                        public["floorOffsetMm"] = round(
                            float(feature.get("floorOffsetMm")), 3
                        )
                    except Exception:
                        pass
            public["openSurfaceIs"] = which
        if not public.get("featureId"):
            public["featureId"] = "FEAT-{:02d}".format(index + 1)
        features.append(public)
    return features, ""


def _brep_feature_ring_count(body):
    """Count feature evidence without fabricating kind/depth/open-face data."""
    if not callable(extract_flattened_rings_mm):
        return 0
    try:
        _outer, holes = extract_flattened_rings_mm(
            body, include_holes=True, through_only=False
        )
    except Exception:
        holes = []
    floors = []
    if callable(_floor_feature_rings_mm):
        try:
            floors = _floor_feature_rings_mm(body) or []
        except Exception:
            floors = []
    return len(list(holes or [])) + len(list(floors or []))


def feature_evidence_complete(features, expected_count):
    """Pass when extraction did not miss BRep evidence.

    Fail only on under-extraction (fewer features than ring/floor evidence).
    Over-extraction is allowed: ``extract_features`` can see both skins and
    edge-open floors that the coarser ring counter under-counts (e.g. 3_of_2).
    """
    try:
        expected = int(expected_count)
    except Exception:
        return False
    return expected >= 0 and len(features or []) >= expected


def cache_is_fresh(metadata, geometry_signature):
    meta = metadata if isinstance(metadata, dict) else {}
    lifecycle = meta.get("lifecycle") if isinstance(meta.get("lifecycle"), dict) else {}
    if str(lifecycle.get("state") or "") != ANALYZED_STATE:
        return False
    cached = meta.get(CACHE_KEY) if isinstance(meta.get(CACHE_KEY), dict) else {}
    if int(cached.get("schemaVersion") or 0) != int(CACHE_SCHEMA):
        return False
    if str(cached.get("geometrySignature") or "") != str(geometry_signature or ""):
        return False
    outline = cached.get("outline") if isinstance(cached.get("outline"), dict) else {}
    if not outline.get("points"):
        return False
    if str(outline.get("source") or "") != "flatBody":
        return False
    if float(cached.get("widthMm") or 0.0) <= 0.0:
        return False
    if float(cached.get("depthMm") or 0.0) <= 0.0:
        return False
    features = meta.get("features")
    return isinstance(features, list)


def analyze_lay_flat_body(body, force=False):
    """Extract outline + features on one Lay Flat body and persist metadata."""
    if body is None:
        return {"ok": False, "reason": "missing_body"}
    body_name = str(getattr(body, "name", "") or "")
    metadata = _read_metadata(body)
    signature = body_geometry_signature(body, detail=True)
    already_down = outline_extraction_face_is_down(body)
    if not force and cache_is_fresh(metadata, signature) and already_down:
        return {
            "ok": True,
            "skipped": True,
            "reason": "fresh",
            "bodyName": body_name,
            "panelId": str((metadata.get("identity") or {}).get("panelId") or ""),
            "featureCount": len(metadata.get("features") or []),
            "pointCount": int(
                ((metadata.get(CACHE_KEY) or {}).get("outline") or {}).get("pointCount")
                or 0
            ),
            "flippedForView": False,
            "outlineFaceDown": True,
        }

    # View convention: outline/extraction skin on −Z so notched/groove side
    # faces the camera. Tags are restored after the MoveFeature flip.
    orient = orient_outline_face_down(body)
    if not orient.get("ok"):
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "orient_outline_down_failed:{}".format(
                orient.get("reason") or "unknown"
            ),
            "flippedForView": False,
            "outlineFaceDown": False,
        }
    flipped_for_view = bool(orient.get("flipped"))
    if flipped_for_view:
        # Geometry changed — refresh signature used for the analyze cache.
        signature = body_geometry_signature(body, detail=True)
        metadata = _read_metadata(body)

    dims = _bbox_dimensions_mm(body)
    milling_face, colour_face = _milling_and_colour_faces(body)
    if milling_face is None or colour_face is None:
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "broad_faces_not_found",
        }

    raw_outer = []
    if callable(extract_flattened_rings_mm):
        try:
            raw_outer, _holes = extract_flattened_rings_mm(
                body, include_holes=False, through_only=True
            )
        except Exception:
            raw_outer = []
    # Prefer BRep rings from already-resolved colour/milling skins when the
    # automatic true-outer walk failed (common on a few notched Ensuite parts).
    if len(raw_outer or []) < 3:
        try:
            from nesting.brep_loops import _rings_from_broad_face
        except Exception:
            try:
                from brep_loops import _rings_from_broad_face  # type: ignore
            except Exception:
                _rings_from_broad_face = None
        if callable(_rings_from_broad_face):
            for face in (colour_face, milling_face):
                try:
                    candidate, _ = _rings_from_broad_face(
                        face, body, include_holes=False, through_only=True
                    )
                except Exception:
                    candidate = []
                if len(candidate or []) >= 3:
                    raw_outer = candidate
                    break
    # Last BRep path: panel_geometry outer loop (tolerates micro-gaps / skips
    # unsampleable edges) in the same world-XY frame used for features.
    if len(raw_outer or []) < 3 and callable(_face_outer_loop_2d):
        for face in (colour_face, milling_face):
            try:
                points, _segments, _has_arc = _face_outer_loop_2d(
                    face, body, thickness_axis=2, coordinate_mode="world"
                )
            except Exception:
                points = []
            if len(points or []) >= 3:
                raw_outer = points
                break
    if len(raw_outer or []) < 3:
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "outline_extract_failed",
        }

    dx, dy = _origin_shift_mm(body, raw_outer)

    outline = build_outline_payload(
        raw_outer,
        "flatBody",
        float(dims.get("widthMm") or 0.0),
        float(dims.get("depthMm") or 0.0),
    )
    if not isinstance(outline, dict) or not outline.get("points"):
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "outline_extract_failed",
        }
    if str(outline.get("source") or "") != "flatBody":
        # build_outline_payload may invent a bbox rectangle when the ring is
        # degenerate — never accept that for manufacturing Analyze.
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "non_production_outline:{}".format(
                str(outline.get("source") or "missing")
            ),
        }

    thickness = float(dims.get("heightMm") or 0.0)
    features, feature_error = _extract_features_for_body(
        body, milling_face, colour_face, dx, dy
    )
    if feature_error:
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": feature_error,
        }
    expected_feature_count = _brep_feature_ring_count(body)
    if not feature_evidence_complete(features, expected_feature_count):
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "feature_extract_incomplete:{}_of_{}".format(
                len(features), expected_feature_count
            ),
        }

    identity = dict(metadata.get("identity") or {}) if isinstance(metadata.get("identity"), dict) else {}
    panel_id = str(identity.get("panelId") or body_name or "panel")
    cache = build_cache_record(
        outline,
        {
            "widthMm": float(outline.get("widthMm") or dims.get("widthMm") or 0.0),
            "depthMm": float(outline.get("depthMm") or dims.get("depthMm") or 0.0),
        },
        signature,
        "MILLING",
        allow_parts_in_part=False,
        reflected_source=bool(outline.get("reflectedSource")),
    )
    cache["analyzedAtMs"] = int(time.time() * 1000)
    cache["featureCount"] = len(features)
    cache["featureEvidenceCount"] = expected_feature_count
    cache["analyzeSource"] = "layFlatBody"

    working = dict(metadata)
    try:
        from panel_attributes import attribute_state_service as _attr_state
    except Exception:
        try:
            import attribute_state_service as _attr_state
        except Exception:
            _attr_state = None
    if _attr_state is not None:
        try:
            working = _attr_state.migrate_metadata(working)
        except Exception:
            pass
    working["identity"] = identity
    working["features"] = features
    working[CACHE_KEY] = cache
    working["dimensions"] = {
        "widthMm": float(cache.get("widthMm") or 0.0),
        "depthMm": float(cache.get("depthMm") or 0.0),
        "thicknessMm": thickness,
    }
    working["lifecycle"] = {
        "state": ANALYZED_STATE,
        "analyzedAtMs": cache["analyzedAtMs"],
    }
    cache["flippedForView"] = flipped_for_view
    cache["outlineFaceDown"] = True
    _write_metadata(body, working, panel_id)
    return {
        "ok": True,
        "skipped": False,
        "bodyName": body_name,
        "panelId": panel_id,
        "featureCount": len(features),
        "pointCount": int(outline.get("pointCount") or len(outline.get("points") or [])),
        "outlineSource": str(outline.get("source") or ""),
        "widthMm": cache.get("widthMm"),
        "depthMm": cache.get("depthMm"),
        "thicknessMm": thickness,
        "flippedForView": flipped_for_view,
        "outlineFaceDown": True,
    }


def analyze_lay_flat_bodies(bodies, force=False, wait_callback=None):
    analyzed = []
    skipped = []
    failed = []
    flipped_count = 0
    for index, body in enumerate(bodies or []):
        try:
            result = analyze_lay_flat_body(body, force=force)
        except Exception as ex:
            failed.append(
                {
                    "bodyName": str(getattr(body, "name", "") or ""),
                    "reason": str(ex),
                }
            )
            continue
        if result.get("flippedForView"):
            flipped_count += 1
        if not result.get("ok"):
            failed.append(
                {
                    "bodyName": result.get("bodyName") or "",
                    "reason": result.get("reason") or "analyze_failed",
                }
            )
        elif result.get("skipped"):
            skipped.append(result)
        else:
            analyzed.append(result)
        if callable(wait_callback) and (index + 1) % 10 == 0:
            try:
                wait_callback()
            except Exception:
                pass
    return {
        "ok": not failed,
        "analyzedCount": len(analyzed),
        "skippedFreshCount": len(skipped),
        "failedCount": len(failed),
        "flippedForViewCount": flipped_count,
        "analyzed": analyzed[:80],
        "skippedFresh": skipped[:40],
        "failed": failed[:40],
        "bodyCount": len(bodies or []),
    }
