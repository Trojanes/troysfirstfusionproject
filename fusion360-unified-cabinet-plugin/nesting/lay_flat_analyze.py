"""Pure manufacturing extraction for already-oriented LAY_FLAT bodies.

Analyze never changes roles or geometry.  Check Faces Up owns repair; this
stage re-validates MILLING +Z / HALF top-only, then persists outline/features.
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
    from nesting.lay_flat_face_up import (
        _assign_milling_and_colour,
        evaluate_body_faces_up,
    )
except Exception:
    try:
        from lay_flat_face_up import (  # type: ignore
            _assign_milling_and_colour,
            evaluate_body_faces_up,
        )
    except Exception:
        _assign_milling_and_colour = None
        evaluate_body_faces_up = None

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
        extract_dxf_projection_rings_mm,
        _floor_feature_rings_mm,
        _ring_bounds_key,
        loop_cad_segments_from_face,
    )
except Exception:
    try:
        from brep_loops import (  # type: ignore
            extract_flattened_rings_mm,
            extract_dxf_projection_rings_mm,
            _floor_feature_rings_mm,
            _ring_bounds_key,
            loop_cad_segments_from_face,
        )
    except Exception:
        extract_flattened_rings_mm = None
        extract_dxf_projection_rings_mm = None
        _floor_feature_rings_mm = None
        _ring_bounds_key = None
        loop_cad_segments_from_face = None

try:
    from nesting.cad_segments import translate_segments
except Exception:
    try:
        from cad_segments import translate_segments  # type: ignore
    except Exception:
        translate_segments = None

PANEL_GROUP = "UnifiedCabinet.Panel"
ANALYZED_STATE = "lay_flat_analyzed"

# Visual-only marker on the MILLING skin after Analyze. One design appearance
# is created/reused per batch; each body may paint several coplanar faces.
MILLING_TINT_APPEARANCE = "UC LayFlat Milling Tint"
MILLING_TINT_RGB = (255, 120, 0)  # orange — distinct from white/metallic boards
# Paint every planar face whose outward normal matches the milling broad face.
# Dados / edge-to-edge slots split the +Z skin into many BRep faces; tinting
# only the single largest face leaves the rest looking gray.
MILLING_TINT_ALIGN_DOT = 0.95


def _design_from_body(body):
    try:
        component = getattr(body, "parentComponent", None)
        design = getattr(component, "parentDesign", None) if component else None
        if design is not None:
            return design
    except Exception:
        pass
    try:
        import adsk.core  # noqa: F401
        import adsk.fusion

        app = adsk.core.Application.get()
        return adsk.fusion.Design.cast(app.activeProduct) if app else None
    except Exception:
        return None


def _find_appearance_library(app):
    try:
        libraries = app.materialLibraries
    except Exception:
        return None
    try:
        lib = libraries.itemByName("Fusion 360 Appearance Library")
        if lib is not None and getattr(lib, "appearances", None) and lib.appearances.count:
            return lib
    except Exception:
        pass
    try:
        for index in range(libraries.count):
            library = libraries.item(index)
            appearances = getattr(library, "appearances", None)
            if appearances and appearances.count:
                return library
    except Exception:
        pass
    return None


def _pick_base_appearance(library):
    appearances = library.appearances
    for name in (
        "Paint - Enamel Glossy (Orange)",
        "Paint - Enamel Glossy (Red)",
        "Plastic - Matte (Red)",
        "Paint - Enamel Glossy (Generic)",
        "Plastic - Matte (Generic)",
    ):
        try:
            appearance = appearances.itemByName(name)
            if appearance is not None:
                return appearance
        except Exception:
            continue
    try:
        return appearances.item(0)
    except Exception:
        return None


def _set_appearance_rgb(appearance, rgb):
    try:
        import adsk.core
    except Exception:
        return False
    color = adsk.core.Color.create(int(rgb[0]), int(rgb[1]), int(rgb[2]), 255)
    try:
        properties = appearance.appearanceProperties
    except Exception:
        return False
    set_any = False
    for prop_id in ("opaque_albedo", "surface_albedo", "generic_diffuse", "metal_f0"):
        try:
            prop = properties.itemById(prop_id)
        except Exception:
            prop = None
        if prop is None:
            continue
        try:
            prop.value = color
            set_any = True
        except Exception:
            pass
    if set_any:
        return True
    try:
        for index in range(properties.count):
            prop = properties.item(index)
            try:
                prop.value = color
                set_any = True
                break
            except Exception:
                continue
    except Exception:
        pass
    return set_any


def ensure_milling_tint_appearance(design, tint_ctx=None):
    """Return the shared milling-tint appearance (create once per design/batch)."""
    ctx = tint_ctx if isinstance(tint_ctx, dict) else None
    if ctx is not None and ctx.get("appearance") is not None:
        return ctx.get("appearance")
    if design is None:
        return None
    try:
        import adsk.core

        app = adsk.core.Application.get()
        appearances = design.appearances
        appearance = None
        try:
            appearance = appearances.itemByName(MILLING_TINT_APPEARANCE)
        except Exception:
            appearance = None
        if appearance is None:
            library = _find_appearance_library(app)
            if library is None:
                return None
            base = _pick_base_appearance(library)
            if base is None:
                return None
            appearance = appearances.addByCopy(base, MILLING_TINT_APPEARANCE)
        # Always refresh RGB — reused library copies can keep a gray base.
        _set_appearance_rgb(appearance, MILLING_TINT_RGB)
        if ctx is not None:
            ctx["appearance"] = appearance
        return appearance
    except Exception:
        return None


def tint_milling_face(face, body=None, tint_ctx=None):
    """Paint one milling face. Appearance is resolved once via ``tint_ctx``."""
    if face is None:
        return False
    ctx = tint_ctx if isinstance(tint_ctx, dict) else {}
    appearance = ctx.get("appearance")
    if appearance is None:
        design = _design_from_body(body) if body is not None else None
        if design is None:
            try:
                component = getattr(face, "body", None)
                design = _design_from_body(component)
            except Exception:
                design = None
        appearance = ensure_milling_tint_appearance(design, ctx)
    if appearance is None:
        ctx["failed"] = int(ctx.get("failed") or 0) + 1
        return False
    try:
        face.appearance = appearance
        ctx["applied"] = int(ctx.get("applied") or 0) + 1
        return True
    except Exception:
        ctx["failed"] = int(ctx.get("failed") or 0) + 1
        return False


def _iter_body_faces(body):
    try:
        from metadata.panel_face_initializer import iter_body_faces
    except Exception:
        try:
            from panel_face_initializer import iter_body_faces  # type: ignore
        except Exception:
            iter_body_faces = None
    if callable(iter_body_faces):
        try:
            return list(iter_body_faces(body) or [])
        except Exception:
            pass
    faces = []
    try:
        collection = getattr(body, "faces", None)
        count = int(getattr(collection, "count", 0) or 0)
        for index in range(count):
            try:
                faces.append(collection.item(index))
            except Exception:
                continue
    except Exception:
        return []
    return faces


def _dot3(left, right):
    return (
        float(left[0]) * float(right[0])
        + float(left[1]) * float(right[1])
        + float(left[2]) * float(right[2])
    )


def milling_side_faces(body, milling_face, min_dot=None):
    """Return milling broad face plus coplanar/+Z-aligned siblings on that skin."""
    faces = []
    seen = set()

    def _add(face):
        if face is None:
            return
        key = id(face)
        if key in seen:
            return
        seen.add(key)
        faces.append(face)

    _add(milling_face)
    if body is None or not callable(face_world_plane):
        return faces
    threshold = float(
        min_dot if min_dot is not None else MILLING_TINT_ALIGN_DOT
    )
    ref_normal = None
    try:
        ref_normal, _ = face_world_plane(milling_face)
    except Exception:
        ref_normal = None
    if not ref_normal:
        ref_normal = (0.0, 0.0, 1.0)
    for face in _iter_body_faces(body):
        if face is None or face is milling_face:
            continue
        try:
            normal, _ = face_world_plane(face)
        except Exception:
            normal = None
        if not normal:
            continue
        if _dot3(normal, ref_normal) < threshold:
            continue
        _add(face)
    return faces


def tint_milling_side(body, milling_face, tint_ctx=None):
    """Paint the whole machining skin (broad face + coplanar fragments)."""
    ctx = tint_ctx if isinstance(tint_ctx, dict) else {}
    painted = 0
    for face in milling_side_faces(body, milling_face):
        if tint_milling_face(face, body, ctx):
            painted += 1
    if painted > 0:
        ctx["bodies"] = int(ctx.get("bodies") or 0) + 1
    return painted > 0


def clear_face_appearance_override(face):
    """Return a non-milling face to its inherited body/component appearance."""
    if face is None:
        return False
    try:
        face.appearance = None
        return True
    except Exception:
        return False


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


def translate_evidence_rings(rings, dx, dy):
    """Map DXF/BRep evidence rings into the same panel-local frame as extract."""
    out = []
    for ring in rings or []:
        if not isinstance(ring, dict):
            continue
        cloned = dict(ring)
        cloned["points"] = _translate_points(ring.get("points") or [], dx, dy)
        out.append(cloned)
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


def _extract_features_for_body(
    body,
    milling_face,
    colour_face,
    dx,
    dy,
    raw_features=None,
    offset_a=None,
    offset_b=None,
):
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
        if offset_a is None:
            offset_a = _face_centroid_local_mm(
                milling_face, body, coordinate_mode="world"
            )[thickness_axis]
        if offset_b is None:
            offset_b = _face_centroid_local_mm(
                colour_face, body, coordinate_mode="world"
            )[thickness_axis]
        thickness_mm = abs(float(offset_a) - float(offset_b))
        raw = (
            list(raw_features)
            if raw_features is not None
            else extract_features(
                body,
                milling_face,
                colour_face,
                thickness_axis,
                offset_a,
                offset_b,
                thickness_mm,
                coordinate_mode="world",
            )
            or []
        )
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
        holes = []
        for ring in public.get("holes") or []:
            translated = _translate_points(ring, dx, dy)
            if len(translated) >= 3:
                holes.append(translated)
        if holes:
            public["holes"] = holes
        if public.get("profileSegments") and translate_segments is not None:
            public["profileSegments"] = translate_segments(
                public.get("profileSegments") or [], dx, dy
            )
        inner_segs = public.get("innerSegments") or []
        if inner_segs and translate_segments is not None:
            public["innerSegments"] = [
                translate_segments(ring, dx, dy) for ring in inner_segs
            ]
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
        # surface_a was milling (+Z) → A is the only supported blind opening.
        which = str(public.get("openSurfaceIs") or feature.get("openSurfaceIs") or "").upper()
        cut_type = str(public.get("cutType") or "").upper()
        if cut_type != "FULL":
            if which not in ("A", "B"):
                return [], "feature_face_unresolved"
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
    features = supplement_features_from_evidence_rings(
        features,
        translate_evidence_rings(_feature_evidence_rings(body), dx, dy),
        thickness_mm,
    )
    for index, feature in enumerate(features):
        if not feature.get("featureId"):
            feature["featureId"] = "FEAT-{:02d}".format(index + 1)
    return features, ""


def _feature_evidence_rings(body):
    if not callable(extract_dxf_projection_rings_mm):
        return []
    try:
        return list(extract_dxf_projection_rings_mm(body) or [])
    except Exception:
        return []


def feature_ring_evidence_count(rings):
    """Unique feature rings (holes + floors), outer outline excluded."""
    if not callable(_ring_bounds_key):
        return sum(
            1
            for ring in rings or []
            if isinstance(ring, dict) and str(ring.get("role") or "") == "feature"
        )
    seen = set()
    count = 0
    for ring in rings or []:
        if not isinstance(ring, dict) or str(ring.get("role") or "") != "feature":
            continue
        key = _ring_bounds_key(ring.get("points") or [])
        if key is not None and key in seen:
            continue
        if key is not None:
            seen.add(key)
        count += 1
    return count


def _feature_points(feature):
    if not isinstance(feature, dict):
        return []
    return list(feature.get("points") or feature.get("pointsLocal") or [])


def _extent_key(points, quantum_mm=0.5):
    """Bounds-only key so rebate rings still match after retessellation."""
    xs = []
    ys = []
    for point in points or []:
        if isinstance(point, dict):
            xs.append(float(point.get("x") or 0.0))
            ys.append(float(point.get("y") or 0.0))
        elif isinstance(point, (list, tuple)) and len(point) >= 2:
            xs.append(float(point[0]))
            ys.append(float(point[1]))
    if len(xs) < 3:
        if callable(_ring_bounds_key):
            return _ring_bounds_key(points)
        return None
    return (
        round(min(xs) / quantum_mm),
        round(min(ys) / quantum_mm),
        round(max(xs) / quantum_mm),
        round(max(ys) / quantum_mm),
    )


def supplement_features_from_evidence_rings(features, rings, thickness_mm):
    """Add BRep hole/floor rings that extract_features missed.

    Lounge lid openings (and similar rebate + through cuts) yield a HALF floor
    plus a smaller broad-face hole. Walls of that hole stop at the rebate
    floor, so extract_features never marks it FULL. The hole still has to go
    into the manufacturing payload as a closed pocket (not a circular hole).
    """
    working = list(features or [])
    existing = set()
    floor_keys = set()
    for feature in working:
        key = _extent_key(_feature_points(feature))
        if key is not None:
            existing.add(key)
    for ring in rings or []:
        if not isinstance(ring, dict) or str(ring.get("role") or "") != "feature":
            continue
        key = _extent_key(ring.get("points") or [])
        if key is not None and str(ring.get("source") or "") == "flatBodyFloor":
            floor_keys.add(key)
    next_index = len(working)
    try:
        thickness = float(thickness_mm or 0.0)
    except (TypeError, ValueError):
        thickness = 0.0
    half_depth = round(thickness / 2.0, 3) if thickness > 0 else 0.0
    for ring in rings or []:
        if not isinstance(ring, dict) or str(ring.get("role") or "") != "feature":
            continue
        points = list(ring.get("points") or [])
        key = _extent_key(points)
        if key is None or key in existing:
            continue
        source = str(ring.get("source") or "")
        cut = str(ring.get("cutType") or "HALF").upper()
        if source != "flatBodyFloor" and cut != "FULL" and key not in floor_keys:
            # Smaller opening inside a rebate: air on both skins.
            cut = "FULL"
        if source != "flatBodyFloor" and cut != "FULL":
            continue
        added = {
            "featureId": "FEAT-{:02d}".format(next_index + 1),
            "cutType": cut,
            "kind": "pocket",
            "depthMm": thickness if cut == "FULL" else half_depth,
            "hasArc": False,
            "points": points,
            "pointsLocal": points,
        }
        if cut != "FULL":
            added["openSurfaceIs"] = "A"
        working.append(added)
        existing.add(key)
        next_index += 1
    return working


def _brep_feature_ring_count(body):
    """Count unique hole/floor rings (same evidence as DXF projection)."""
    return feature_ring_evidence_count(_feature_evidence_rings(body))


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


def canonicalize_half_openings_for_plus_z(features, face_check):
    """Persist HALF as A when the smaller skin is already +Z.

    Floor topology often votes the intact underside after an overlay rebate
    is flipped up. Check Faces Up treats that as topHalf; Export Ready still
    reads ``openSurfaceIs``. Rewrite B → A only for that area gate.
    """
    check = face_check if isinstance(face_check, dict) else {}
    if not check.get("topOutlineNotched"):
        return list(features or [])
    if str(check.get("halfStatus") or "") == "doubleSide":
        return list(features or [])
    out = []
    for feature in features or []:
        if not isinstance(feature, dict):
            out.append(feature)
            continue
        cut_type = str(feature.get("cutType") or "").strip().upper()
        through = cut_type == "FULL" or bool(feature.get("through"))
        if through or cut_type != "HALF":
            out.append(feature)
            continue
        which = str(feature.get("openSurfaceIs") or "").strip().upper()
        if which != "B":
            out.append(feature)
            continue
        rewritten = dict(feature)
        rewritten["openSurfaceIs"] = "A"
        rewritten["openSurfaceCanonicalized"] = "rebate_on_plus_z"
        out.append(rewritten)
    return out


def features_are_canonical_single_side(features):
    """True when every blind feature has canonical machining opening A."""
    if not isinstance(features, list):
        return False
    for feature in features:
        if not isinstance(feature, dict):
            return False
        cut_type = str(feature.get("cutType") or "").strip().upper()
        through = cut_type == "FULL" or bool(feature.get("through"))
        if through:
            continue
        if str(feature.get("openSurfaceIs") or "").strip().upper() != "A":
            return False
    return True


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
    if str(cached.get("halfOpeningStatus") or "") not in ("topHalf", "none"):
        return False
    if int(cached.get("bottomHalfCount") or 0) != 0:
        return False
    features = meta.get("features")
    return features_are_canonical_single_side(features)


def analyze_lay_flat_body(body, force=False, tint_ctx=None):
    """Validate and extract one body without changing roles or geometry."""
    if body is None:
        return {"ok": False, "reason": "missing_body"}
    body_name = str(getattr(body, "name", "") or "")
    metadata = _read_metadata(body)
    signature = body_geometry_signature(body, detail=True)

    face_check = (
        evaluate_body_faces_up(body)
        if callable(evaluate_body_faces_up)
        else {"ok": False, "reasons": ["face_up_helpers_unavailable"]}
    )
    if not face_check.get("ok"):
        reasons = list(face_check.get("reasons") or ["manufacturing_orientation_invalid"])
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": reasons[0],
            "reasons": reasons,
            "halfStatus": face_check.get("halfStatus") or "",
            "topHalfCount": int(face_check.get("topHalfCount") or 0),
            "bottomHalfCount": int(face_check.get("bottomHalfCount") or 0),
        }

    if not force and cache_is_fresh(metadata, signature):
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
            "halfStatus": face_check.get("halfStatus") or "",
            "millingTintApplied": False,
        }

    dims = _bbox_dimensions_mm(body)
    milling_face = face_check.get("millingFace")
    colour_face = face_check.get("colourFace")
    if milling_face is None or colour_face is None:
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "broad_faces_not_found",
        }

    try:
        from nesting.brep_loops import _rings_from_broad_face
    except Exception:
        try:
            from brep_loops import _rings_from_broad_face  # type: ignore
        except Exception:
            _rings_from_broad_face = None

    # The colour / -Z skin is normally complete even when edge-open grooves
    # notch the machining skin, so it is the canonical outline source.
    raw_outer = []
    raw_segments = []
    outline_face_source = ""
    outline_face = None
    if callable(_rings_from_broad_face):
        try:
            raw_outer, _ = _rings_from_broad_face(
                colour_face,
                body,
                include_holes=False,
                through_only=True,
            )
        except Exception:
            raw_outer = []
        if len(raw_outer or []) >= 3:
            outline_face_source = "bottomFace"
            outline_face = colour_face
    if len(raw_outer or []) < 3 and callable(extract_flattened_rings_mm):
        try:
            raw_outer, _holes = extract_flattened_rings_mm(
                body, include_holes=False, through_only=True
            )
        except Exception:
            raw_outer = []
        if len(raw_outer or []) >= 3:
            outline_face_source = "trueOuter"
            outline_face = colour_face
    if len(raw_outer or []) < 3 and callable(_rings_from_broad_face):
        try:
            raw_outer, _ = _rings_from_broad_face(
                milling_face,
                body,
                include_holes=False,
                through_only=True,
            )
        except Exception:
            raw_outer = []
        if len(raw_outer or []) >= 3:
            outline_face_source = "millingFallback"
            outline_face = milling_face
    if len(raw_outer or []) < 3 and callable(_face_outer_loop_2d):
        for face, label in (
            (colour_face, "bottomFaceLoop"),
            (milling_face, "millingFaceLoop"),
        ):
            try:
                points, loop_segs, _has_arc = _face_outer_loop_2d(
                    face, body, thickness_axis=2, coordinate_mode="world"
                )
            except Exception:
                points = []
                loop_segs = []
            if len(points or []) >= 3:
                raw_outer = points
                outline_face_source = label
                outline_face = face
                try:
                    from metadata.panel_geometry import _cad_list_from_loop_segments
                except Exception:
                    try:
                        from panel_geometry import _cad_list_from_loop_segments
                    except Exception:
                        _cad_list_from_loop_segments = None
                if callable(_cad_list_from_loop_segments):
                    raw_segments = _cad_list_from_loop_segments(
                        loop_segs, body, 2, "world"
                    )
                break
    if len(raw_outer or []) < 3:
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "outline_extract_failed",
        }
    if not raw_segments and outline_face is not None and callable(loop_cad_segments_from_face):
        try:
            raw_segments = loop_cad_segments_from_face(outline_face) or []
        except Exception:
            raw_segments = []

    dx, dy = _origin_shift_mm(body, raw_outer)
    outline = build_outline_payload(
        raw_outer,
        "flatBody",
        float(dims.get("widthMm") or 0.0),
        float(dims.get("depthMm") or 0.0),
        segments=raw_segments,
    )
    if not isinstance(outline, dict) or not outline.get("points"):
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "outline_extract_failed",
        }
    if str(outline.get("source") or "") != "flatBody":
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "non_production_outline:{}".format(
                str(outline.get("source") or "missing")
            ),
        }
    outline["faceSource"] = outline_face_source

    half = face_check.get("halfInspection") or {}
    features, feature_error = _extract_features_for_body(
        body,
        milling_face,
        colour_face,
        dx,
        dy,
        raw_features=half.get("rawFeatures"),
        offset_a=half.get("topOffsetMm"),
        offset_b=half.get("bottomOffsetMm"),
    )
    if feature_error:
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": feature_error,
        }
    features = canonicalize_half_openings_for_plus_z(features, face_check)
    expected_feature_count = _brep_feature_ring_count(body)
    if not feature_evidence_complete(features, expected_feature_count):
        return {
            "ok": False,
            "bodyName": body_name,
            "reason": "feature_extract_incomplete:{}_of_{}".format(
                len(features), expected_feature_count
            ),
        }

    thickness = float(dims.get("heightMm") or 0.0)
    identity = (
        dict(metadata.get("identity") or {})
        if isinstance(metadata.get("identity"), dict)
        else {}
    )
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
        grain_along_mm=(
            (outline or {}).get("grainAlongMm")
            or (metadata.get("classification") or {}).get("grainAlongMm")
        ),
    )
    cache["analyzedAtMs"] = int(time.time() * 1000)
    cache["featureCount"] = len(features)
    cache["featureEvidenceCount"] = expected_feature_count
    cache["analyzeSource"] = "layFlatBody"
    cache["halfOpeningStatus"] = face_check.get("halfStatus") or ""
    cache["topHalfCount"] = int(face_check.get("topHalfCount") or 0)
    cache["bottomHalfCount"] = int(face_check.get("bottomHalfCount") or 0)
    cache["outlineFaceSource"] = outline_face_source

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
    _write_metadata(body, working, panel_id)
    clear_face_appearance_override(colour_face)
    tinted = tint_milling_side(body, milling_face, tint_ctx)
    return {
        "ok": True,
        "skipped": False,
        "bodyName": body_name,
        "panelId": panel_id,
        "featureCount": len(features),
        "pointCount": int(outline.get("pointCount") or len(outline.get("points") or [])),
        "outlineSource": str(outline.get("source") or ""),
        "outlineFaceSource": outline_face_source,
        "widthMm": cache.get("widthMm"),
        "depthMm": cache.get("depthMm"),
        "thicknessMm": thickness,
        "halfStatus": face_check.get("halfStatus") or "",
        "topHalfCount": int(face_check.get("topHalfCount") or 0),
        "bottomHalfCount": int(face_check.get("bottomHalfCount") or 0),
        "millingTintApplied": bool(tinted),
    }


def analyze_lay_flat_bodies(bodies, force=False, wait_callback=None):
    analyzed = []
    skipped = []
    failed = []
    tint_ctx = {"appearance": None, "applied": 0, "failed": 0, "bodies": 0}
    for index, body in enumerate(bodies or []):
        try:
            result = analyze_lay_flat_body(body, force=force, tint_ctx=tint_ctx)
        except Exception as ex:
            failed.append(
                {
                    "bodyName": str(getattr(body, "name", "") or ""),
                    "reason": str(ex),
                }
            )
            continue
        if not result.get("ok"):
            failed.append(
                {
                    "bodyName": result.get("bodyName") or "",
                    "reason": result.get("reason") or "analyze_failed",
                    "reasons": list(result.get("reasons") or []),
                    "halfStatus": result.get("halfStatus") or "",
                    "topHalfCount": int(result.get("topHalfCount") or 0),
                    "bottomHalfCount": int(result.get("bottomHalfCount") or 0),
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
        # Body-level count for the status line; face assigns can be much larger
        # when dados split the machining skin into coplanar fragments.
        "millingTintAppliedCount": int(tint_ctx.get("bodies") or 0),
        "millingTintFaceCount": int(tint_ctx.get("applied") or 0),
        "millingTintFailedCount": int(tint_ctx.get("failed") or 0),
        "analyzed": analyzed[:80],
        "skippedFresh": skipped[:40],
        "failed": failed[:40],
        "bodyCount": len(bodies or []),
    }
