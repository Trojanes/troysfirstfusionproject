"""Canonical manufacturing-orientation inspection for LAY_FLAT bodies.

Contract:

* world +Z is machining side A;
* world -Z is colour / underside B;
* HALF features may open on A only for single-sided manufacturing;
* HALF features on both sides are unsupported.

This module is read-only.  Role writes and geometry flips belong to the
controller transaction so a failed repair can be rolled back safely.
"""

from __future__ import annotations

try:
    from nesting.fusion_layout import _fast_broad_faces
except Exception:
    try:
        from fusion_layout import _fast_broad_faces  # type: ignore
    except Exception:
        _fast_broad_faces = None

try:
    from panel_attributes.milling_surface_propagation import face_world_plane
except Exception:
    try:
        from milling_surface_propagation import face_world_plane  # type: ignore
    except Exception:
        face_world_plane = None

try:
    from metadata.panel_geometry import (
        _face_centroid_local_mm,
        extract_features,
    )
except Exception:
    try:
        from panel_geometry import (  # type: ignore
            _face_centroid_local_mm,
            extract_features,
        )
    except Exception:
        _face_centroid_local_mm = None
        extract_features = None


HALF_TOP = "topHalf"
HALF_BOTTOM = "bottomHalf"
HALF_DOUBLE = "doubleSide"
HALF_NONE = "none"


def classify_half_openings(features):
    """Classify HALF feature openings when A=top and B=bottom."""
    top = []
    bottom = []
    unknown = []
    for feature in features or []:
        if not isinstance(feature, dict):
            continue
        cut_type = str(feature.get("cutType") or "").strip().upper()
        if cut_type == "FULL" or bool(feature.get("through")):
            continue
        if cut_type and cut_type != "HALF":
            continue
        side = str(feature.get("openSurfaceIs") or "").strip().upper()
        if side == "A":
            top.append(feature)
        elif side == "B":
            bottom.append(feature)
        else:
            unknown.append(feature)
    if top and bottom:
        status = HALF_DOUBLE
    elif bottom:
        status = HALF_BOTTOM
    elif top:
        status = HALF_TOP
    else:
        status = HALF_NONE
    return {
        "status": status,
        "topHalfCount": len(top),
        "bottomHalfCount": len(bottom),
        "unknownHalfCount": len(unknown),
        "topFeatures": top,
        "bottomFeatures": bottom,
        "unknownFeatures": unknown,
    }


def broad_faces_by_world_z(body):
    """Return broad faces ordered as top (+Z), bottom (-Z)."""
    if (
        body is None
        or not callable(_fast_broad_faces)
        or not callable(face_world_plane)
    ):
        return None
    try:
        face_a, face_b = _fast_broad_faces(body)
    except Exception:
        face_a = face_b = None
    if face_a is None or face_b is None:
        return None
    normal_a, _centroid_a = face_world_plane(face_a)
    normal_b, _centroid_b = face_world_plane(face_b)
    if not normal_a or not normal_b:
        return None
    if float(normal_a[2]) >= float(normal_b[2]):
        return {
            "topFace": face_a,
            "bottomFace": face_b,
            "topNormal": normal_a,
            "bottomNormal": normal_b,
        }
    return {
        "topFace": face_b,
        "bottomFace": face_a,
        "topNormal": normal_b,
        "bottomNormal": normal_a,
    }


def inspect_half_openings(body):
    """Extract HALF evidence in the final world-Z manufacturing frame."""
    faces = broad_faces_by_world_z(body)
    if not faces:
        return {
            "ok": False,
            "status": "unresolved",
            "reason": "broad_faces_not_found",
            "topHalfCount": 0,
            "bottomHalfCount": 0,
            "unknownHalfCount": 0,
            "rawFeatures": [],
        }
    if not callable(extract_features) or not callable(_face_centroid_local_mm):
        return {
            "ok": False,
            "status": "unresolved",
            "reason": "feature_helpers_unavailable",
            "topHalfCount": 0,
            "bottomHalfCount": 0,
            "unknownHalfCount": 0,
            "rawFeatures": [],
            **faces,
        }
    try:
        top_offset = _face_centroid_local_mm(
            faces["topFace"], body, coordinate_mode="world"
        )[2]
        bottom_offset = _face_centroid_local_mm(
            faces["bottomFace"], body, coordinate_mode="world"
        )[2]
        thickness = abs(float(top_offset) - float(bottom_offset))
        raw = extract_features(
            body,
            faces["topFace"],
            faces["bottomFace"],
            2,
            top_offset,
            bottom_offset,
            thickness,
            coordinate_mode="world",
        ) or []
    except Exception as ex:
        return {
            "ok": False,
            "status": "unresolved",
            "reason": "feature_extract_failed:{}".format(ex),
            "topHalfCount": 0,
            "bottomHalfCount": 0,
            "unknownHalfCount": 0,
            "rawFeatures": [],
            **faces,
        }
    result = classify_half_openings(raw)
    result.update(
        {
            "ok": not result.get("unknownHalfCount"),
            "reason": (
                ""
                if not result.get("unknownHalfCount")
                else "feature_face_unresolved"
            ),
            "rawFeatures": raw,
            "topOffsetMm": float(top_offset),
            "bottomOffsetMm": float(bottom_offset),
            "thicknessMm": float(thickness),
            **faces,
        }
    )
    return result
