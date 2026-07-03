"""Pure bbox-based relationship geometry and classification."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from relationship_models import (
    SCHEMA_VERSION,
    BoardRelationship,
    BBoxMm,
    ContactMetrics,
    PanelRef,
    PanelSnapshot,
    RelationshipRoles,
    RelationshipSource,
    RelationshipValidation,
    make_relationship_id,
)

CONTACT_TOLERANCE_MM = 0.5
MIN_OVERLAP_MM = 1.0
GAP_PARALLEL_MAX_MM = 20.0
THICKNESS_RATIO_TOLERANCE = 0.35

AXIS_NAMES = ("X", "Y", "Z")


def bbox_gap_1d(a0: float, a1: float, b0: float, b1: float) -> float:
    """Return separation distance along one axis; 0 when overlapping or touching."""
    if a1 <= b0:
        return float(b0 - a1)
    if b1 <= a0:
        return float(a0 - b1)
    return 0.0


def bbox_overlap_1d(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def bbox_size(axis: str, bbox: BBoxMm) -> float:
    if axis == "X":
        return bbox.size_x
    if axis == "Y":
        return bbox.size_y
    if axis == "Z":
        return bbox.size_z
    raise ValueError("Unknown axis: {}".format(axis))


def infer_thickness_axis(snapshot: PanelSnapshot) -> Tuple[str, Optional[float], List[str]]:
    warnings: List[str] = []
    sizes = {
        "X": snapshot.sizeX,
        "Y": snapshot.sizeY,
        "Z": snapshot.sizeZ,
    }
    ordered = sorted(sizes.items(), key=lambda item: item[1])
    smallest_axis, smallest = ordered[0]
    middle = ordered[1][1]
    largest = ordered[2][1]

    if smallest <= 0:
        warnings.append("Non-positive bbox dimension on panel {}".format(snapshot.panelId))
        return "UNKNOWN", None, warnings

    if middle > 0 and (smallest / middle) > (1.0 - THICKNESS_RATIO_TOLERANCE):
        warnings.append(
            "Ambiguous thickness axis for panel {} (sizes X/Y/Z={:.2f}/{:.2f}/{:.2f})".format(
                snapshot.panelId,
                snapshot.sizeX,
                snapshot.sizeY,
                snapshot.sizeZ,
            )
        )
        return "UNKNOWN", smallest, warnings

    if largest > 0 and (smallest / largest) > 0.5:
        warnings.append(
            "Panel {} does not look like a flat board (smallest/largest={:.2f})".format(
                snapshot.panelId,
                smallest / largest,
            )
        )

    return smallest_axis, smallest, warnings


def axis_ranges(bbox: BBoxMm) -> Dict[str, Tuple[float, float]]:
    return {
        "X": (bbox.x0, bbox.x1),
        "Y": (bbox.y0, bbox.y1),
        "Z": (bbox.z0, bbox.z1),
    }


def compute_overlaps(a: PanelSnapshot, b: PanelSnapshot) -> Dict[str, float]:
    return {
        "X": bbox_overlap_1d(a.bbox.x0, a.bbox.x1, b.bbox.x0, b.bbox.x1),
        "Y": bbox_overlap_1d(a.bbox.y0, a.bbox.y1, b.bbox.y0, b.bbox.y1),
        "Z": bbox_overlap_1d(a.bbox.z0, a.bbox.z1, b.bbox.z0, b.bbox.z1),
    }


def compute_gaps(a: PanelSnapshot, b: PanelSnapshot) -> Dict[str, float]:
    ranges_a = axis_ranges(a.bbox)
    ranges_b = axis_ranges(b.bbox)
    return {
        axis: bbox_gap_1d(ranges_a[axis][0], ranges_a[axis][1], ranges_b[axis][0], ranges_b[axis][1])
        for axis in AXIS_NAMES
    }


def detect_contact_axis(
    a: PanelSnapshot,
    b: PanelSnapshot,
    tolerance_mm: float = CONTACT_TOLERANCE_MM,
    min_overlap_mm: float = MIN_OVERLAP_MM,
) -> Tuple[Optional[str], Dict[str, float], Dict[str, float]]:
    overlaps = compute_overlaps(a, b)
    gaps = compute_gaps(a, b)
    candidates: List[str] = []
    for axis in AXIS_NAMES:
        other_axes = [item for item in AXIS_NAMES if item != axis]
        if gaps[axis] <= tolerance_mm and all(overlaps[item] >= min_overlap_mm for item in other_axes):
            candidates.append(axis)
    if not candidates:
        return None, overlaps, gaps
    return candidates[0], overlaps, gaps


def _contact_length_mm(contact_axis: str, overlaps: Dict[str, float]) -> float:
    other_axes = [axis for axis in AXIS_NAMES if axis != contact_axis]
    return max(overlaps[other_axes[0]], overlaps[other_axes[1]])


def _contact_area_mm2(contact_axis: str, overlaps: Dict[str, float]) -> float:
    other_axes = [axis for axis in AXIS_NAMES if axis != contact_axis]
    return overlaps[other_axes[0]] * overlaps[other_axes[1]]


def _is_thickness_on_axis(snapshot: PanelSnapshot, axis: str, tolerance_mm: float = CONTACT_TOLERANCE_MM) -> bool:
    if snapshot.thicknessAxis == axis:
        return True
    if snapshot.thicknessAxis == "UNKNOWN" and snapshot.thicknessMm is not None:
        size = bbox_size(axis, snapshot.bbox)
        return abs(size - snapshot.thicknessMm) <= max(tolerance_mm, snapshot.thicknessMm * 0.15)
    if snapshot.thicknessAxis == "UNKNOWN":
        size = bbox_size(axis, snapshot.bbox)
        smallest = min(snapshot.sizeX, snapshot.sizeY, snapshot.sizeZ)
        return abs(size - smallest) <= max(tolerance_mm, smallest * 0.15)
    return False


def _looks_like_door(snapshot: PanelSnapshot) -> bool:
    tokens = " ".join(
        str(value or "")
        for value in (
            snapshot.boardType,
            snapshot.role,
            snapshot.sourceBoardId,
            snapshot.panelId,
        )
    ).lower()
    return any(token in tokens for token in ("door", "flap", "front_panel", "up_flap"))


def _looks_like_carcass(snapshot: PanelSnapshot) -> bool:
    tokens = " ".join(
        str(value or "")
        for value in (
            snapshot.boardType,
            snapshot.role,
            snapshot.sourceBoardId,
            snapshot.panelId,
        )
    ).lower()
    return any(
        token in tokens
        for token in (
            "carcass",
            "side",
            "divider",
            "bottom_panel",
            "rail",
            "panel",
            "bp",
            "surface",
        )
    )


def _has_volume_intersection(overlaps: Dict[str, float], min_overlap_mm: float = MIN_OVERLAP_MM) -> bool:
    return all(overlaps[axis] > min_overlap_mm for axis in AXIS_NAMES)


def _detect_gap_parallel_axis(
    a: PanelSnapshot,
    b: PanelSnapshot,
    tolerance_mm: float,
    min_overlap_mm: float,
    gap_parallel_max_mm: float,
) -> Tuple[Optional[str], Dict[str, float], Dict[str, float]]:
    overlaps = compute_overlaps(a, b)
    gaps = compute_gaps(a, b)
    for axis in AXIS_NAMES:
        other_axes = [item for item in AXIS_NAMES if item != axis]
        gap = gaps[axis]
        if tolerance_mm < gap <= gap_parallel_max_mm and all(overlaps[item] >= min_overlap_mm for item in other_axes):
            return axis, overlaps, gaps
    return None, overlaps, gaps


def calculate_confidence(
    geometry_type: str,
    contact_area_mm2: float,
    warnings: List[str],
    thickness_ambiguous: bool,
    metadata_missing: bool,
) -> float:
    base = {
        "edge_to_surface": 0.85,
        "surface_to_surface": 0.8,
        "gap_parallel": 0.55,
        "intersection": 0.9,
        "none": 1.0,
    }.get(geometry_type, 0.5)

    if geometry_type in ("edge_to_surface", "surface_to_surface") and contact_area_mm2 >= 10000:
        base = min(0.95, base + 0.05)
    elif geometry_type in ("edge_to_surface", "surface_to_surface") and contact_area_mm2 < 100:
        base -= 0.15

    if thickness_ambiguous:
        base -= 0.2
    if metadata_missing:
        base -= 0.1

    return max(0.0, min(1.0, round(base, 4)))


def classify_pair(
    panel_a: PanelSnapshot,
    panel_b: PanelSnapshot,
    tolerance_mm: float = CONTACT_TOLERANCE_MM,
    min_overlap_mm: float = MIN_OVERLAP_MM,
    gap_parallel_max_mm: float = GAP_PARALLEL_MAX_MM,
) -> BoardRelationship:
    warnings: List[str] = []
    errors: List[str] = []
    audit_notes: List[str] = []

    thickness_ambiguous = panel_a.thicknessAxis == "UNKNOWN" or panel_b.thicknessAxis == "UNKNOWN"
    metadata_missing = not panel_a.boardType and not panel_b.boardType
    if metadata_missing:
        warnings.append("Missing boardType metadata on one or both panels.")
    warnings.extend(panel_a.metadataWarnings)
    warnings.extend(panel_b.metadataWarnings)

    overlaps = compute_overlaps(panel_a, panel_b)
    gaps = compute_gaps(panel_a, panel_b)

    geometry_type = "none"
    relationship_type = "unknown"
    contact_axis = "NONE"
    distance_mm = min(gaps.values())
    roles = RelationshipRoles()
    rule_id = "none"

    if _has_volume_intersection(overlaps, min_overlap_mm):
        geometry_type = "intersection"
        relationship_type = "collision"
        contact_axis = "NONE"
        distance_mm = 0.0
        errors.append("Panels intersect in 3D bbox volume.")
        rule_id = "intersection.volume_overlap"
        audit_notes.append("All three bbox axes have positive overlap above min threshold.")
    else:
        contact_axis_detected, overlaps, gaps = detect_contact_axis(
            panel_a,
            panel_b,
            tolerance_mm=tolerance_mm,
            min_overlap_mm=min_overlap_mm,
        )
        if contact_axis_detected:
            contact_axis = contact_axis_detected
            distance_mm = gaps[contact_axis]
            a_is_edge = _is_thickness_on_axis(panel_a, contact_axis, tolerance_mm)
            b_is_edge = _is_thickness_on_axis(panel_b, contact_axis, tolerance_mm)

            if a_is_edge and b_is_edge:
                geometry_type = "surface_to_surface"
                relationship_type = "face_contact"
                rule_id = "contact.both_thickness_on_axis"
                audit_notes.append("Both panels expose thickness on contact axis.")
            elif a_is_edge ^ b_is_edge:
                geometry_type = "edge_to_surface"
                relationship_type = "structural_butt_joint"
                rule_id = "contact.single_thickness_on_axis"
                edge_panel = panel_a if a_is_edge else panel_b
                surface_panel = panel_b if a_is_edge else panel_a
                roles.hostPanelId = surface_panel.panelId
                roles.targetPanelId = edge_panel.panelId
                warnings.append("host/target inferred by bbox thickness-axis rule")
                audit_notes.append(
                    "Edge panel {} on axis {}; surface panel {}.".format(
                        edge_panel.panelId,
                        contact_axis,
                        surface_panel.panelId,
                    )
                )
            else:
                geometry_type = "surface_to_surface"
                relationship_type = "face_contact"
                rule_id = "contact.face_without_clear_thickness"
                warnings.append("Contact detected but thickness-axis edge rule was ambiguous.")
        else:
            gap_axis, overlaps, gaps = _detect_gap_parallel_axis(
                panel_a,
                panel_b,
                tolerance_mm,
                min_overlap_mm,
                gap_parallel_max_mm,
            )
            if gap_axis:
                geometry_type = "gap_parallel"
                contact_axis = gap_axis
                distance_mm = gaps[gap_axis]
                rule_id = "gap.parallel_within_range"
                door_a = _looks_like_door(panel_a)
                door_b = _looks_like_door(panel_b)
                carcass_a = _looks_like_carcass(panel_a)
                carcass_b = _looks_like_carcass(panel_b)
                if (door_a and carcass_b) or (door_b and carcass_a):
                    relationship_type = "door_to_carcass_candidate"
                    audit_notes.append("Semantic hint suggests door-to-carcass gap candidate.")
                else:
                    relationship_type = "unknown"
                    audit_notes.append("Parallel gap detected without strong semantic role hints.")
            else:
                geometry_type = "none"
                relationship_type = "unknown"
                contact_axis = "NONE"
                distance_mm = min(gaps.values())
                rule_id = "none.no_contact_or_gap"

    contact_length = _contact_length_mm(contact_axis, overlaps) if contact_axis != "NONE" else 0.0
    contact_area = _contact_area_mm2(contact_axis, overlaps) if contact_axis != "NONE" else 0.0

    confidence = calculate_confidence(
        geometry_type,
        contact_area,
        warnings,
        thickness_ambiguous,
        metadata_missing,
    )

    validation = RelationshipValidation(
        ok=geometry_type != "intersection",
        warnings=warnings,
        errors=errors,
    )

    relationship = BoardRelationship(
        schemaVersion=SCHEMA_VERSION,
        relationshipId=make_relationship_id(panel_a.panelId, panel_b.panelId),
        panelA=PanelRef(
            panelId=panel_a.panelId,
            bodyName=panel_a.bodyName,
            boardType=panel_a.boardType,
            role=panel_a.role,
            sourceBoardId=panel_a.sourceBoardId,
            materialClass=panel_a.materialClass,
        ),
        panelB=PanelRef(
            panelId=panel_b.panelId,
            bodyName=panel_b.bodyName,
            boardType=panel_b.boardType,
            role=panel_b.role,
            sourceBoardId=panel_b.sourceBoardId,
            materialClass=panel_b.materialClass,
        ),
        geometryType=geometry_type,
        relationshipType=relationship_type,
        contact=ContactMetrics(
            axis=contact_axis,
            distanceMm=round(float(distance_mm), 4),
            overlapX=round(overlaps["X"], 4),
            overlapY=round(overlaps["Y"], 4),
            overlapZ=round(overlaps["Z"], 4),
            contactLengthMm=round(contact_length, 4),
            contactAreaMm2=round(contact_area, 4),
        ),
        roles=roles,
        source=RelationshipSource(
            method="geometry_detected",
            confidence=confidence,
            ruleId=rule_id,
        ),
        validation=validation,
        auditNotes=audit_notes,
    )
    return relationship


def enrich_panel_snapshot(snapshot: PanelSnapshot) -> PanelSnapshot:
    axis, thickness, warnings = infer_thickness_axis(snapshot)
    snapshot.thicknessAxis = axis
    snapshot.thicknessMm = thickness
    snapshot.metadataWarnings.extend(warnings)
    return snapshot
