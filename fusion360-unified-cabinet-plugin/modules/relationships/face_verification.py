"""M5 face-level relationship verification — pure logic (offline-testable)."""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

from relationship_models import (
    upgrade_relationship_with_face_verification,
)
from relationship_geometry import CONTACT_TOLERANCE_MM

FACE_CLASS_SURFACE = "SURFACE"
FACE_CLASS_EDGE = "EDGE"

SUPPORTED_GEOMETRY_TYPES = ("edge_to_surface", "surface_to_surface", "gap_parallel")
MIN_PROJECTED_OVERLAP_MM = 1.0
MIN_CONTACT_AREA_MM2 = 1.0
NORMAL_AXIS_DOT = 0.99
NORMAL_OPPOSITE_DOT = -0.99

VERIFY_ACTION = "relationships.verifySelectedPairFaces"


def _bbox_value(bbox: Dict[str, Any], axis: str, bound: str) -> float:
    key = "{}{}".format(axis.lower(), "0" if bound == "min" else "1")
    return float(bbox.get(key, 0.0))


def _bbox_size(bbox: Dict[str, Any], axis: str) -> float:
    return abs(_bbox_value(bbox, axis, "max") - _bbox_value(bbox, axis, "min"))


def infer_thickness_axis_from_bbox(bbox: Dict[str, Any]) -> str:
    sizes = {axis: _bbox_size(bbox, axis) for axis in ("X", "Y", "Z")}
    return min(sizes.items(), key=lambda item: item[1])[0]


def _axis_vector(axis: str, sign: int) -> Tuple[float, float, float]:
    if axis == "X":
        return (float(sign), 0.0, 0.0)
    if axis == "Y":
        return (0.0, float(sign), 0.0)
    if axis == "Z":
        return (0.0, 0.0, float(sign))
    raise ValueError("Unknown axis: {}".format(axis))


def _dominant_axis(normal: Tuple[float, float, float]) -> Tuple[str, int]:
    ax, ay, az = normal
    comps = [("X", ax), ("Y", ay), ("Z", az)]
    axis, value = max(comps, key=lambda item: abs(item[1]))
    if abs(value) < NORMAL_AXIS_DOT:
        raise ValueError("Face normal is not axis-aligned.")
    return axis, 1 if value >= 0 else -1


def _classify_face(normal: Tuple[float, float, float], thickness_axis: str) -> str:
    axis, _sign = _dominant_axis(normal)
    if thickness_axis in ("X", "Y", "Z") and axis == thickness_axis:
        return FACE_CLASS_SURFACE
    return FACE_CLASS_EDGE


def extract_axis_aligned_faces_from_panel(panel: Dict[str, Any]) -> List[Dict[str, Any]]:
    panel_id = str(panel.get("panelId") or "panel")
    bbox = panel.get("bbox") or {}
    thickness_axis = (
        (panel.get("inferred") or {}).get("thicknessAxis")
        or infer_thickness_axis_from_bbox(bbox)
    )
    x0, x1 = _bbox_value(bbox, "X", "min"), _bbox_value(bbox, "X", "max")
    y0, y1 = _bbox_value(bbox, "Y", "min"), _bbox_value(bbox, "Y", "max")
    z0, z1 = _bbox_value(bbox, "Z", "min"), _bbox_value(bbox, "Z", "max")

    faces: List[Dict[str, Any]] = []
    specs = (
        ("X", 1, x1, y0, y1, z0, z1, y1 - y0, z1 - z0),
        ("X", -1, x0, y0, y1, z0, z1, y1 - y0, z1 - z0),
        ("Y", 1, y1, x0, x1, z0, z1, x1 - x0, z1 - z0),
        ("Y", -1, y0, x0, x1, z0, z1, x1 - x0, z1 - z0),
        ("Z", 1, z1, x0, x1, y0, y1, x1 - x0, y1 - y0),
        ("Z", -1, z0, x0, x1, y0, y1, x1 - x0, y1 - y0),
    )
    for axis, sign, plane_pos, a0, a1, b0, b1, span_a, span_b in specs:
        normal = _axis_vector(axis, sign)
        if axis == "X":
            origin = (plane_pos, (a0 + a1) / 2.0, (b0 + b1) / 2.0)
            bounds = {"x0": plane_pos, "x1": plane_pos, "y0": a0, "y1": a1, "z0": b0, "z1": b1}
        elif axis == "Y":
            origin = ((a0 + a1) / 2.0, plane_pos, (b0 + b1) / 2.0)
            bounds = {"x0": a0, "x1": a1, "y0": plane_pos, "y1": plane_pos, "z0": b0, "z1": b1}
        else:
            origin = ((a0 + a1) / 2.0, (b0 + b1) / 2.0, plane_pos)
            bounds = {"x0": a0, "x1": a1, "y0": b0, "y1": b1, "z0": plane_pos, "z1": plane_pos}
        area_mm2 = max(0.0, span_a) * max(0.0, span_b)
        face_id = "{}::{}{}".format(panel_id, "+" if sign > 0 else "-", axis)
        faces.append(
            {
                "faceId": face_id,
                "panelId": panel_id,
                "faceClass": _classify_face(normal, thickness_axis),
                "normal": list(normal),
                "planeOriginMm": list(origin),
                "boundsMm": bounds,
                "areaMm2": round(area_mm2, 4),
                "source": "bbox_axis_aligned",
            }
        )
    return faces


def _dot(a: Tuple[float, float, float], b: Tuple[float, float, float]) -> float:
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _projected_overlap_1d(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def _projected_overlap_mm(face_a: Dict[str, Any], face_b: Dict[str, Any], contact_axis: str) -> Tuple[float, float, float]:
    ba = face_a.get("boundsMm") or {}
    bb = face_b.get("boundsMm") or {}
    axes = [item for item in ("X", "Y", "Z") if item != contact_axis]
    overlaps = []
    for axis in axes:
        key0 = "{}{}".format(axis.lower(), "0")
        key1 = "{}{}".format(axis.lower(), "1")
        overlaps.append(
            _projected_overlap_1d(
                float(ba.get(key0, 0.0)),
                float(ba.get(key1, 0.0)),
                float(bb.get(key0, 0.0)),
                float(bb.get(key1, 0.0)),
            )
        )
    overlap_a, overlap_b = overlaps[0], overlaps[1]
    return overlap_a, overlap_b, overlap_a * overlap_b


def _plane_distance_mm(face_a: Dict[str, Any], face_b: Dict[str, Any]) -> float:
    na = tuple(face_a.get("normal") or (0.0, 0.0, 0.0))
    nb = tuple(face_b.get("normal") or (0.0, 0.0, 0.0))
    oa = tuple(face_a.get("planeOriginMm") or (0.0, 0.0, 0.0))
    ob = tuple(face_b.get("planeOriginMm") or (0.0, 0.0, 0.0))
    if _dot(na, nb) > -NORMAL_OPPOSITE_DOT:
        return float("inf")
    delta = (ob[0] - oa[0], ob[1] - oa[1], ob[2] - oa[2])
    return abs(_dot(na, delta))


def _face_classes_allowed(geometry_type: str) -> Optional[Tuple[str, str]]:
    if geometry_type == "edge_to_surface":
        return (FACE_CLASS_EDGE, FACE_CLASS_SURFACE)
    if geometry_type in ("surface_to_surface", "gap_parallel"):
        return (FACE_CLASS_SURFACE, FACE_CLASS_SURFACE)
    return None


def _classes_match(geometry_type: str, class_a: str, class_b: str) -> bool:
    allowed = _face_classes_allowed(geometry_type)
    if not allowed:
        return False
    return {class_a, class_b} == set(allowed)


def _contact_faces_for_axis(faces: List[Dict[str, Any]], contact_axis: str) -> List[Dict[str, Any]]:
    matched = []
    for face in faces:
        axis, _sign = _dominant_axis(tuple(face.get("normal") or (0.0, 0.0, 0.0)))
        if axis == contact_axis:
            matched.append(face)
    return matched


def verify_pair_faces(
    relationship: Dict[str, Any],
    panel_a: Dict[str, Any],
    panel_b: Dict[str, Any],
    faces_a: List[Dict[str, Any]],
    faces_b: List[Dict[str, Any]],
    *,
    tolerance_mm: float = CONTACT_TOLERANCE_MM,
    min_projected_overlap_mm: float = MIN_PROJECTED_OVERLAP_MM,
    min_contact_area_mm2: float = MIN_CONTACT_AREA_MM2,
    gap_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from connect_formal_ui import normalize_gap_joints_settings

    geometry_type = str(relationship.get("geometryType") or "none")
    relationship_id = str(relationship.get("relationshipId") or "")
    contact = relationship.get("contact") or {}
    contact_axis = str(contact.get("axis") or "NONE")
    gap = normalize_gap_joints_settings(gap_settings)

    errors: List[str] = []
    warnings: List[str] = []

    if geometry_type == "gap_parallel" and not gap["enabled"]:
        errors.append("Gap joint face verification is disabled (enable Connect gap joints).")
        return _build_verify_report(False, relationship_id, geometry_type, contact_axis, errors=errors)

    if geometry_type not in SUPPORTED_GEOMETRY_TYPES:
        errors.append(
            "Face verification v1 supports {} only; got {}.".format(
                ", ".join(SUPPORTED_GEOMETRY_TYPES),
                geometry_type,
            )
        )
        return _build_verify_report(False, relationship_id, geometry_type, contact_axis, errors=errors)

    if contact_axis not in ("X", "Y", "Z"):
        errors.append("Relationship contact axis is missing or invalid for face verification.")
        return _build_verify_report(False, relationship_id, geometry_type, contact_axis, errors=errors)

    candidates_a = _contact_faces_for_axis(faces_a, contact_axis)
    candidates_b = _contact_faces_for_axis(faces_b, contact_axis)
    if not candidates_a or not candidates_b:
        errors.append("Could not find contact-axis faces on one or both panels.")
        return _build_verify_report(False, relationship_id, geometry_type, contact_axis, errors=errors)

    is_gap = geometry_type == "gap_parallel"
    min_distance = float(gap["minGapMm"]) if is_gap else 0.0
    max_distance = float(gap["maxGapMm"]) if is_gap else float(tolerance_mm)

    best: Optional[Dict[str, Any]] = None
    for face_a in candidates_a:
        for face_b in candidates_b:
            distance_mm = _plane_distance_mm(face_a, face_b)
            if is_gap:
                if distance_mm < min_distance or distance_mm > max_distance:
                    continue
            elif distance_mm > max_distance:
                continue
            overlap_a, overlap_b, overlap_area = _projected_overlap_mm(face_a, face_b, contact_axis)
            if overlap_a < min_projected_overlap_mm or overlap_b < min_projected_overlap_mm:
                continue
            if overlap_area < min_contact_area_mm2:
                continue
            class_a = str(face_a.get("faceClass") or "")
            class_b = str(face_b.get("faceClass") or "")
            if not _classes_match(geometry_type, class_a, class_b):
                continue
            score = overlap_area - abs(distance_mm)
            if best is None or score > best["score"]:
                best = {
                    "score": score,
                    "faceA": face_a,
                    "faceB": face_b,
                    "distanceMm": distance_mm,
                    "overlapAreaMm2": overlap_area,
                    "overlapA": overlap_a,
                    "overlapB": overlap_b,
                }

    if best is None:
        errors.append("No opposing contact face pair satisfied distance, overlap, and face-class checks.")
        return _build_verify_report(
            False,
            relationship_id,
            geometry_type,
            contact_axis,
            errors=errors,
            warnings=warnings,
        )

    face_a = best["faceA"]
    face_b = best["faceB"]
    face_match = {
        "matchedFaceAId": face_a.get("faceId"),
        "matchedFaceBId": face_b.get("faceId"),
        "matchedFaceAClass": face_a.get("faceClass"),
        "matchedFaceBClass": face_b.get("faceClass"),
        "planeDistanceMm": round(best["distanceMm"], 4),
        "projectedOverlapAreaMm2": round(best["overlapAreaMm2"], 4),
        "projectedOverlapA": round(best["overlapA"], 4),
        "projectedOverlapB": round(best["overlapB"], 4),
        "contactAxis": contact_axis,
        "method": "axis_aligned_planar_faces_v1",
    }
    return _build_verify_report(
        True,
        relationship_id,
        geometry_type,
        contact_axis,
        face_match=face_match,
        warnings=warnings,
    )


def _build_verify_report(
    ok: bool,
    relationship_id: str,
    geometry_type: str,
    contact_axis: str,
    *,
    face_match: Optional[Dict[str, Any]] = None,
    errors: Optional[List[str]] = None,
    warnings: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return {
        "ok": bool(ok),
        "action": VERIFY_ACTION,
        "relationshipId": relationship_id,
        "geometryType": geometry_type,
        "contactAxis": contact_axis,
        "faceMatch": face_match or {},
        "errors": list(errors or []),
        "warnings": list(warnings or []),
    }


def apply_face_verification_to_relationship(
    relationship: Dict[str, Any],
    verify_report: Dict[str, Any],
) -> Dict[str, Any]:
    if not verify_report.get("ok"):
        raise ValueError("Cannot apply face verification to a failed verify report.")
    return upgrade_relationship_with_face_verification(relationship, verify_report.get("faceMatch") or {})


def verify_fixture_pair_offline(
    panel_a: Dict[str, Any],
    panel_b: Dict[str, Any],
    relationship: Dict[str, Any],
    *,
    tolerance_mm: float = CONTACT_TOLERANCE_MM,
    gap_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    faces_a = extract_axis_aligned_faces_from_panel(panel_a)
    faces_b = extract_axis_aligned_faces_from_panel(panel_b)
    return verify_pair_faces(
        relationship,
        panel_a,
        panel_b,
        faces_a,
        faces_b,
        tolerance_mm=tolerance_mm,
        gap_settings=gap_settings,
    )


# --- Batch auto face-verify (3a): bbox_candidate → face_verified; skip + remind ---

BATCH_VERIFY_ACTION = "relationships.verifyAllBboxCandidates"
DEFAULT_BATCH_MAX_PAIRS = 200


def _relationship_panel_ids(relationship: Dict[str, Any]) -> Tuple[str, str]:
    panel_a = relationship.get("panelA") or {}
    panel_b = relationship.get("panelB") or {}
    return (
        str(panel_a.get("panelId") or "").strip(),
        str(panel_b.get("panelId") or "").strip(),
    )


def filter_face_verifiable_candidates(
    relationships: List[Dict[str, Any]],
    gap_settings: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Phase-1 batch filter: bbox_candidate + contact pairs (+ optional gap joints)."""
    from connect_formal_ui import is_hardware_eligible

    accepted: List[Dict[str, Any]] = []
    for relationship in relationships or []:
        if not isinstance(relationship, dict):
            continue
        verification = relationship.get("verification") or {}
        level = str(verification.get("level") or "bbox_candidate")
        if level != "bbox_candidate":
            continue
        if not is_hardware_eligible(relationship, gap_settings, for_batch=True):
            continue
        accepted.append(relationship)
    return accepted


def _skip_reason_from_verify_errors(errors: List[str]) -> str:
    text = " ".join(errors).lower()
    if "body_not_found" in text or "body not found" in text:
        return "body_not_found"
    if "geometry type" in text or "supports" in text:
        return "geometry_not_supported"
    if "contact-axis faces" in text:
        return "face_extract_failed"
    if "opposing contact face" in text or "overlap" in text:
        return "no_opposing_faces"
    if "face-class" in text or "class" in text:
        return "class_mismatch"
    if "contact axis" in text:
        return "geometry_not_supported"
    return "no_opposing_faces"


def _reminder_lines(verified_count: int, skipped: List[Dict[str, Any]], *, capped: bool) -> List[str]:
    lines: List[str] = []
    if verified_count:
        lines.append("已自动验证 {} 对接头，可切削。".format(verified_count))
    if skipped:
        lines.append("跳过 {} 对（见列表），请检查或改选手动面验证。".format(len(skipped)))
    if capped:
        lines.append("已达本批上限，请缩小装配范围后重试。")
    if not verified_count and not skipped:
        lines.append("没有可自动面验证的 bbox 候选（需接触类接头，或已启用缝隙接头）。")
    return lines


def verify_all_bbox_candidates(
    relationships: List[Dict[str, Any]],
    panel_snapshots: Dict[str, Dict[str, Any]],
    *,
    tolerance_mm: float = CONTACT_TOLERANCE_MM,
    max_pairs: int = DEFAULT_BATCH_MAX_PAIRS,
    extract_faces=None,
    gap_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Offline/batch core: verify filtered bbox candidates; skip failures; never relax cut gate.

    extract_faces(panel_dict) -> faces[]; defaults to axis-aligned bbox faces (offline).
    Fusion controller injects BRep extraction later.
    """
    extract = extract_faces or extract_axis_aligned_faces_from_panel
    panels = panel_snapshots if isinstance(panel_snapshots, dict) else {}
    candidates = filter_face_verifiable_candidates(list(relationships or []), gap_settings)
    limit = max(0, int(max_pairs if max_pairs is not None else DEFAULT_BATCH_MAX_PAIRS))
    capped = len(candidates) > limit
    to_process = candidates[:limit] if limit else []
    overflow = candidates[limit:] if capped else []

    verified: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    def _skip(rel: Dict[str, Any], reason: str, errors: Optional[List[str]] = None) -> None:
        panel_a_id, panel_b_id = _relationship_panel_ids(rel)
        skipped.append(
            {
                "relationshipId": str(rel.get("relationshipId") or ""),
                "panelA": panel_a_id,
                "panelB": panel_b_id,
                "reason": reason,
                "errors": list(errors or []),
            }
        )

    for rel in overflow:
        _skip(rel, "cap_reached", ["Batch maxPairs={} exceeded.".format(limit)])

    for rel in to_process:
        panel_a_id, panel_b_id = _relationship_panel_ids(rel)
        if not panel_a_id or not panel_b_id:
            _skip(rel, "panel_missing", ["Relationship panel ids are incomplete."])
            continue
        panel_a = panels.get(panel_a_id)
        panel_b = panels.get(panel_b_id)
        if not isinstance(panel_a, dict) or not isinstance(panel_b, dict):
            _skip(
                rel,
                "panel_missing",
                ["Missing panel snapshot for {} / {}.".format(panel_a_id, panel_b_id)],
            )
            continue
        try:
            faces_a = list(extract(panel_a) or [])
            faces_b = list(extract(panel_b) or [])
        except Exception as ex:
            errors = [str(ex)]
            _skip(rel, _skip_reason_from_verify_errors(errors), errors)
            continue
        if not faces_a or not faces_b:
            _skip(rel, "face_extract_failed", ["No faces extracted for one or both panels."])
            continue
        report = verify_pair_faces(
            rel,
            panel_a,
            panel_b,
            faces_a,
            faces_b,
            tolerance_mm=tolerance_mm,
            gap_settings=gap_settings,
        )
        if not report.get("ok"):
            errors = list(report.get("errors") or [])
            _skip(rel, _skip_reason_from_verify_errors(errors), errors)
            continue
        try:
            upgraded = apply_face_verification_to_relationship(rel, report)
        except Exception as ex:
            _skip(rel, "no_opposing_faces", [str(ex)])
            continue
        verified.append(upgraded)

    return {
        "ok": True,
        "action": BATCH_VERIFY_ACTION,
        "cutGateUnchanged": True,
        "toleranceMm": float(tolerance_mm),
        "maxPairs": limit,
        "candidateCount": len(candidates),
        "processedCount": len(to_process),
        "verifiedCount": len(verified),
        "skippedCount": len(skipped),
        "verifiedRelationships": verified,
        "skipped": skipped,
        "reminders": _reminder_lines(len(verified), skipped, capped=capped),
        "errors": [],
        "warnings": [],
    }
