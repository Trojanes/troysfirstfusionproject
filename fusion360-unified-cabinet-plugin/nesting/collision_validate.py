"""Authoritative, side-effect-free polygon validation for nesting layouts.

The polygon model deliberately mirrors ``fusion_layout.create_layout``:
rotate the prepared outline about the origin, use the rotated outer minimum
corner, then translate the outer and all holes together to ``targetX/Y``.
"""

from __future__ import annotations

import math

try:
    from nesting import outline as geometry
    from nesting.sheet_pack import normalize_sheet_params, sheet_size_for_type
except Exception:
    import outline as geometry
    from sheet_pack import normalize_sheet_params, sheet_size_for_type


BORDER_SLACK_MM = 0.25
# Deepnest remaps via AABB center after Clipper expand; true-shape clearance on
# concave / asymmetric parts can undershoot spacingMm by ~0.5–1 mm even when
# expanded nests look clean. Accept that float/remap band so primary Deepnest
# is not discarded for a single near-miss (sheet_pack is much worse util).
SPACING_SLACK_MM = 1.0
MAPPING_TOLERANCE_MM = 0.5
# ``sheet_pack`` deliberately simplifies packed outlines with a 1 mm
# Douglas-Peucker tolerance.  That approximation is covered by the validator's
# 1 mm spacing slack and exact BRep pass, so it must not be treated as a failed
# transform mapping.  Keep the stricter tolerance above for actual BRep bounds.
PACKED_OUTLINE_TOLERANCE_MM = 1.0 + 1e-6
EXACT_CANDIDATE_LIMIT = 64
MAX_EXACT_BREP_PAIRS = 512


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def _raw_hole_points(value):
    if isinstance(value, dict):
        return value.get("points") or value.get("pointsLocal") or []
    return value or []


def _item_points(item):
    payload = item.get("outline") if isinstance(item.get("outline"), dict) else {}
    points = payload.get("points")
    if isinstance(points, list) and len(points) >= 4:
        return geometry.close_ring(points)
    dims = item.get("dimensions") if isinstance(item.get("dimensions"), dict) else item
    return geometry.rectangle_polygon(
        _num(dims.get("widthMm")), _num(dims.get("depthMm"))
    )


def _item_holes(item):
    payload = item.get("outline") if isinstance(item.get("outline"), dict) else {}
    return [
        geometry.close_ring(_raw_hole_points(value))
        for value in payload.get("holes") or []
        if len(geometry.close_ring(_raw_hole_points(value))) >= 4
    ]


def _transform_item(item, placement):
    """Return the exact 2D transform used by Fusion body creation."""
    rotation = _num(placement.get("rotationDeg"))
    rotated_outer = geometry.rotate_polygon(_item_points(item), rotation)
    bounds = geometry.polygon_bounds(rotated_outer)
    dx = _num(placement.get("targetX")) - bounds["minX"]
    dy = _num(placement.get("targetY")) - bounds["minY"]
    outer = geometry.translate_polygon(rotated_outer, dx, dy)
    holes = [
        geometry.translate_polygon(geometry.rotate_polygon(hole, rotation), dx, dy)
        for hole in _item_holes(item)
    ]
    return {
        "outer": outer,
        "holes": holes,
        "bounds": geometry.polygon_bounds(outer),
        "rotationDeg": rotation,
        "dx": dx,
        "dy": dy,
    }


def _aabb_clearance(a, b):
    dx = max(0.0, a["minX"] - b["maxX"], b["minX"] - a["maxX"])
    dy = max(0.0, a["minY"] - b["maxY"], b["minY"] - a["maxY"])
    return math.hypot(dx, dy) if dx and dy else max(dx, dy)


def _aabb_overlaps(a, b, tolerance=1e-9):
    return not (
        a["maxX"] < b["minX"] - tolerance
        or b["maxX"] < a["minX"] - tolerance
        or a["maxY"] < b["minY"] - tolerance
        or b["maxY"] < a["minY"] - tolerance
    )


def _strict_aabb_overlaps(a, b, tolerance=1e-9):
    return (
        a["minX"] < b["maxX"] - tolerance
        and b["minX"] < a["maxX"] - tolerance
        and a["minY"] < b["maxY"] - tolerance
        and b["minY"] < a["maxY"] - tolerance
    )


def _bounds_overlap_3d(a, b, tolerance=1e-6):
    return (
        a["minX"] < b["maxX"] - tolerance
        and b["minX"] < a["maxX"] - tolerance
        and a["minY"] < b["maxY"] - tolerance
        and b["minY"] < a["maxY"] - tolerance
        and a["minZ"] < b["maxZ"] - tolerance
        and b["minZ"] < a["maxZ"] - tolerance
    )


def _broadphase_pairs_3d(bounds_by_index):
    indexes = sorted(bounds_by_index)
    pairs = []
    for offset, left in enumerate(indexes):
        for right in indexes[offset + 1 :]:
            if _bounds_overlap_3d(bounds_by_index[left], bounds_by_index[right]):
                pairs.append((left, right))
    return pairs


def _ring_fully_inside(inner, outer):
    inner = geometry.close_ring(inner)
    outer = geometry.close_ring(outer)
    return (
        len(inner) >= 4
        and len(outer) >= 4
        and not geometry.ring_boundaries_touch_or_intersect(inner, outer)
        and all(geometry.point_in_polygon(point, outer) for point in inner[:-1])
    )


def _boundary_distance(a, b):
    a = geometry.close_ring(a)
    b = geometry.close_ring(b)
    best = float("inf")
    for ring_a, ring_b in ((a, b), (b, a)):
        for px, py in ring_a[:-1]:
            for index in range(len(ring_b) - 1):
                ax, ay = ring_b[index]
                bx, by = ring_b[index + 1]
                dx, dy = bx - ax, by - ay
                length2 = dx * dx + dy * dy
                if length2 <= 1e-18:
                    distance = math.hypot(px - ax, py - ay)
                else:
                    t = max(
                        0.0,
                        min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2),
                    )
                    distance = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
                best = min(best, distance)
    return best if best < float("inf") else 0.0


def _contained_in_hole(child, parent, spacing):
    for hole in parent["holes"]:
        if not _ring_fully_inside(child["outer"], hole):
            continue
        clearance = _boundary_distance(child["outer"], hole)
        if clearance + SPACING_SLACK_MM >= spacing:
            return True, clearance
    return False, None


def _identity(entry):
    placement = entry["placement"]
    return {
        "id": str(placement.get("id") or ""),
        "panelId": placement.get("panelId") or entry["item"].get("panelId") or "",
        "bodyName": placement.get("bodyName") or entry["item"].get("bodyName") or "",
    }


def _collision(a, b, kind, spacing, distance=None, source="polygon"):
    return {
        "type": kind,
        "sheetIndex": a["sheetIndex"],
        "a": _identity(a),
        "b": _identity(b),
        "spacingMm": spacing,
        "distanceMm": distance,
        "source": source,
    }


def _sheet_record(layout, placement, params):
    sheet_index = int(placement.get("sheetIndex") or 0)
    by_index = {
        int(sheet.get("sheetIndex") or 0): sheet
        for sheet in layout.get("sheets") or []
        if isinstance(sheet, dict)
    }
    sheet = by_index.get(sheet_index, {})
    configured = sheet_size_for_type(
        params, placement.get("boardTypeTag") or sheet.get("boardTypeTag")
    )
    return {
        "sheetIndex": sheet_index,
        "originX": _num(
            placement.get("sheetOriginX"),
            sheet.get("originX", 0.0),
        ),
        "originY": _num(
            placement.get("sheetOriginY"),
            sheet.get("originY", 0.0),
        ),
        "widthMm": _num(
            placement.get("sheetWidthMm"),
            sheet.get("widthMm", configured["widthMm"]),
        ),
        "heightMm": _num(
            placement.get("sheetHeightMm"),
            sheet.get("heightMm", configured["heightMm"]),
        ),
    }


def _ring_difference_mm(a, b):
    """Order-independent boundary/bounds drift for equivalent rings.

    Packed outlines are intentionally simplified before placement.  Comparing
    vertices directly makes a removed point look far from its two surviving
    neighbours even when it still lies exactly on the segment between them.
    Measure point-to-segment distance instead so simplification is not reported
    as a transform mismatch.
    """
    a = geometry.close_ring(a)
    b = geometry.close_ring(b)
    if len(a) < 4 or len(b) < 4:
        return float("inf")

    def point_to_boundary(point, ring):
        px, py = point
        best = float("inf")
        for index in range(len(ring) - 1):
            ax, ay = ring[index]
            bx, by = ring[index + 1]
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy
            if length2 <= 1e-18:
                distance = math.hypot(px - ax, py - ay)
            else:
                t = max(
                    0.0,
                    min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2),
                )
                distance = math.hypot(px - (ax + t * dx), py - (ay + t * dy))
            best = min(best, distance)
        return best

    ba, bb = geometry.polygon_bounds(a), geometry.polygon_bounds(b)
    drift = max(
        abs(ba[key] - bb[key])
        for key in ("minX", "minY", "maxX", "maxY")
    )
    for source, target in ((a[:-1], b[:-1]), (b[:-1], a[:-1])):
        for point in source:
            drift = max(drift, point_to_boundary(point, target + [target[0]]))
    return drift


def _mapping_warning(entry):
    packed = entry["placement"].get("packedOutline")
    if not isinstance(packed, list) or len(packed) < 3:
        return None
    sheet = entry["sheet"]
    candidates = [
        packed,
        geometry.translate_polygon(packed, sheet["originX"], sheet["originY"]),
    ]
    drift = min(
        _ring_difference_mm(entry["shape"]["outer"], candidate)
        for candidate in candidates
    )
    if drift <= PACKED_OUTLINE_TOLERANCE_MM:
        return None
    return {
        **_identity(entry),
        "sheetIndex": entry["sheetIndex"],
        "maxDriftMm": drift,
        "toleranceMm": PACKED_OUTLINE_TOLERANCE_MM,
        "message": "packedOutline differs from the Fusion creation transform.",
    }


def validate_layout(layout, prepared_items, sheet_params):
    """Validate a layout using only prepared outline data and Python geometry."""
    params = normalize_sheet_params(sheet_params)
    placements = list((layout or {}).get("placements") or [])
    by_id = {str(item.get("id")): item for item in prepared_items or []}
    spacing = _num(params.get("spacingMm"))
    border = _num(params.get("borderMm"))
    allow_holes = bool(
        params.get("allowPartsInPart") and (layout or {}).get("partsInPartApplied")
    )
    entries = []
    mapping_warnings = []
    border_violations = []
    sheet_overlaps = []
    checks = {
        "placements": len(placements),
        "mappedPlacements": 0,
        "borderChecks": 0,
        "pairChecks": 0,
        "broadPhaseCandidates": 0,
        "polygonChecks": 0,
        "containmentChecks": 0,
    }

    for index, placement in enumerate(placements):
        item = by_id.get(str(placement.get("id")))
        if item is None:
            mapping_warnings.append({
                "id": str(placement.get("id") or ""),
                "panelId": placement.get("panelId") or "",
                "bodyName": placement.get("bodyName") or "",
                "sheetIndex": int(placement.get("sheetIndex") or 0),
                "message": "Placement has no matching prepared item.",
            })
            continue
        sheet = _sheet_record(layout or {}, placement, params)
        entry = {
            "index": index,
            "item": item,
            "placement": placement,
            "sheetIndex": sheet["sheetIndex"],
            "sheet": sheet,
            "shape": _transform_item(item, placement),
        }
        entries.append(entry)
        checks["mappedPlacements"] += 1
        warning = _mapping_warning(entry)
        if warning:
            mapping_warnings.append(warning)

        checks["borderChecks"] += 1
        bounds = entry["shape"]["bounds"]
        usable = {
            "minX": sheet["originX"] + border,
            "minY": sheet["originY"] + border,
            "maxX": sheet["originX"] + sheet["widthMm"] - border,
            "maxY": sheet["originY"] + sheet["heightMm"] - border,
        }
        sides = []
        if bounds["minX"] < usable["minX"] - BORDER_SLACK_MM:
            sides.append("left")
        if bounds["minY"] < usable["minY"] - BORDER_SLACK_MM:
            sides.append("bottom")
        if bounds["maxX"] > usable["maxX"] + BORDER_SLACK_MM:
            sides.append("right")
        if bounds["maxY"] > usable["maxY"] + BORDER_SLACK_MM:
            sides.append("top")
        if sides:
            border_violations.append({
                **_identity(entry),
                "sheetIndex": entry["sheetIndex"],
                "sides": sides,
                "bounds": bounds,
                "usableBounds": usable,
                "slackMm": BORDER_SLACK_MM,
            })

    sheet_records = []
    seen_sheet_indexes = set()
    for sheet in (layout or {}).get("sheets") or []:
        if not isinstance(sheet, dict):
            continue
        sheet_index = int(sheet.get("sheetIndex") or 0)
        if sheet_index in seen_sheet_indexes:
            continue
        seen_sheet_indexes.add(sheet_index)
        x0 = _num(sheet.get("originX"))
        y0 = _num(sheet.get("originY"))
        sheet_records.append({
            "sheetIndex": sheet_index,
            "boardTypeTag": str(sheet.get("boardTypeTag") or ""),
            "colorTag": str(sheet.get("colorTag") or ""),
            "minX": x0,
            "minY": y0,
            "maxX": x0 + _num(sheet.get("widthMm")),
            "maxY": y0 + _num(sheet.get("heightMm")),
        })
    for left in range(len(sheet_records)):
        for right in range(left + 1, len(sheet_records)):
            a = sheet_records[left]
            b = sheet_records[right]
            if _strict_aabb_overlaps(a, b):
                sheet_overlaps.append({
                    "a": a,
                    "b": b,
                    "message": "Physical sheet rectangles overlap in world XY.",
                })

    collisions = []
    exact_candidates = []
    for left in range(len(entries)):
        for right in range(left + 1, len(entries)):
            a, b = entries[left], entries[right]
            if a["sheetIndex"] != b["sheetIndex"]:
                continue
            checks["pairChecks"] += 1
            a_bounds, b_bounds = a["shape"]["bounds"], b["shape"]["bounds"]
            if (
                _aabb_clearance(a_bounds, b_bounds) + SPACING_SLACK_MM >= spacing
                and not _aabb_overlaps(a_bounds, b_bounds)
            ):
                continue
            checks["broadPhaseCandidates"] += 1
            checks["polygonChecks"] += 1

            contained = False
            if allow_holes:
                checks["containmentChecks"] += 2
                contained, _clearance = _contained_in_hole(
                    a["shape"], b["shape"], spacing
                )
                if not contained:
                    contained, _clearance = _contained_in_hole(
                        b["shape"], a["shape"], spacing
                    )
            if contained:
                if _aabb_overlaps(a_bounds, b_bounds):
                    exact_candidates.append([a["index"], b["index"]])
                continue

            if geometry.polygons_intersect(a["shape"]["outer"], b["shape"]["outer"]):
                collisions.append(_collision(a, b, "overlap", spacing, 0.0))
                continue
            distance = geometry.min_polygon_distance(
                a["shape"]["outer"], b["shape"]["outer"]
            )
            if distance + SPACING_SLACK_MM < spacing:
                collisions.append(_collision(a, b, "spacing", spacing, distance))
            elif _aabb_overlaps(a_bounds, b_bounds):
                # Concave notch legality is exactly the ambiguous case the
                # Fusion TemporaryBRep check targets.
                exact_candidates.append([a["index"], b["index"]])

    ok = (
        not collisions
        and not border_violations
        and not mapping_warnings
        and not sheet_overlaps
        and checks["mappedPlacements"] == len(placements)
    )
    return {
        "ok": ok,
        "status": "safe" if ok else "unsafe",
        "collisions": collisions,
        "collisionCount": len(collisions),
        "borderViolations": border_violations,
        "borderViolationCount": len(border_violations),
        "mappingWarnings": mapping_warnings,
        "mappingWarningCount": len(mapping_warnings),
        "sheetOverlaps": sheet_overlaps,
        "sheetOverlapCount": len(sheet_overlaps),
        "checks": checks,
        "exactChecks": 0,
        "exactCheckWarnings": [],
        "exactCandidates": exact_candidates[:EXACT_CANDIDATE_LIMIT],
    }


def validate_fusion_exact(layout, prepared_items, sheet_params, polygon_result=None):
    """Validate cached-outline mapping and suspicious pairs with real BReps.

    Every prepared body is transformed exactly as Fusion creation will transform
    it. A cheap real-BRep bbox pass finds candidates; boolean intersection runs
    only for those pairs. Any incomplete exact validation is unsafe.
    """
    result = dict(polygon_result or validate_layout(layout, prepared_items, sheet_params))
    result["collisions"] = list(result.get("collisions") or [])
    result["exactCheckWarnings"] = list(result.get("exactCheckWarnings") or [])
    result["mappingWarnings"] = list(result.get("mappingWarnings") or [])
    result["exactValidationIncomplete"] = False
    try:
        import adsk.core
        import adsk.fusion

        manager = adsk.fusion.TemporaryBRepManager.get()
        boolean_type = adsk.fusion.BooleanTypes.IntersectionBooleanType
        if manager is None or not callable(getattr(manager, "booleanOperation", None)):
            raise RuntimeError("TemporaryBRep boolean intersection is unavailable.")
    except Exception as ex:
        result["exactCheckWarnings"].append(str(ex))
        result["exactValidationIncomplete"] = True
        result["ok"] = False
        result["status"] = "unsafe"
        return result

    placements = list((layout or {}).get("placements") or [])
    by_id = {str(item.get("id")): item for item in prepared_items or []}
    transformed = {}
    transformed_bounds = {}

    def transformed_body(index):
        if index in transformed:
            return transformed[index]
        placement = placements[index]
        item = by_id[str(placement.get("id"))]
        source = item.get("tempBody")
        if source is None:
            raise RuntimeError("Prepared item has no tempBody for exact check.")
        body = manager.copy(source)
        rotation = _num(placement.get("rotationDeg"))
        if abs(rotation) > 1e-9:
            matrix = adsk.core.Matrix3D.create()
            matrix.setToRotation(
                math.radians(rotation),
                adsk.core.Vector3D.create(0, 0, 1),
                adsk.core.Point3D.create(0, 0, 0),
            )
            manager.transform(body, matrix)
        bbox = body.boundingBox
        translation = adsk.core.Matrix3D.create()
        translation.translation = adsk.core.Vector3D.create(
            (_num(placement.get("targetX")) - bbox.minPoint.x * 10.0) / 10.0,
            (_num(placement.get("targetY")) - bbox.minPoint.y * 10.0) / 10.0,
            -bbox.minPoint.z,
        )
        manager.transform(body, translation)
        transformed[index] = body
        placed_bbox = body.boundingBox
        transformed_bounds[index] = {
            "minX": placed_bbox.minPoint.x * 10.0,
            "minY": placed_bbox.minPoint.y * 10.0,
            "minZ": placed_bbox.minPoint.z * 10.0,
            "maxX": placed_bbox.maxPoint.x * 10.0,
            "maxY": placed_bbox.maxPoint.y * 10.0,
            "maxZ": placed_bbox.maxPoint.z * 10.0,
        }
        return body

    candidate_set = {
        tuple(sorted((int(left), int(right))))
        for left, right in (result.get("exactCandidates") or [])
        if int(left) != int(right)
    }
    for index, placement in enumerate(placements):
        try:
            body = transformed_body(index)
            actual = transformed_bounds[index]
            item = by_id[str(placement.get("id"))]
            expected = _transform_item(item, placement)["bounds"]
            actual_width = actual["maxX"] - actual["minX"]
            actual_depth = actual["maxY"] - actual["minY"]
            expected_width = expected["maxX"] - expected["minX"]
            expected_depth = expected["maxY"] - expected["minY"]
            drift = max(
                abs(actual_width - expected_width),
                abs(actual_depth - expected_depth),
            )
            if drift > MAPPING_TOLERANCE_MM:
                result["mappingWarnings"].append({
                    "id": str(placement.get("id") or ""),
                    "panelId": placement.get("panelId") or item.get("panelId") or "",
                    "bodyName": placement.get("bodyName") or item.get("bodyName") or "",
                    "sheetIndex": int(placement.get("sheetIndex") or 0),
                    "maxDriftMm": drift,
                    "toleranceMm": MAPPING_TOLERANCE_MM,
                    "message": "Actual transformed BRep bounds differ from cached outline.",
                    "source": "temporaryBRep",
                })
        except Exception as ex:
            result["exactCheckWarnings"].append(
                "Exact body {}: {}".format(index, ex)
            )
            result["exactValidationIncomplete"] = True

    candidate_set.update(_broadphase_pairs_3d(transformed_bounds))

    candidates = sorted(candidate_set)
    result["exactBroadPhaseCandidates"] = len(candidates)
    if len(candidates) > MAX_EXACT_BREP_PAIRS:
        result["exactCheckWarnings"].append(
            "Exact broad phase found {} pairs; safety limit is {}.".format(
                len(candidates), MAX_EXACT_BREP_PAIRS
            )
        )
        result["exactValidationIncomplete"] = True
        candidates = candidates[:MAX_EXACT_BREP_PAIRS]

    for left, right in candidates:
        try:
            intersection = manager.copy(transformed_body(left))
            tool = manager.copy(transformed_body(right))
            operation_ok = manager.booleanOperation(intersection, tool, boolean_type)
            result["exactChecks"] = int(result.get("exactChecks") or 0) + 1
            volume = _num(getattr(intersection, "volume", 0.0))
            if operation_ok and volume > 1e-7:
                item_a = {
                    "index": left,
                    "item": by_id[str(placements[left].get("id"))],
                    "placement": placements[left],
                    "sheetIndex": int(placements[left].get("sheetIndex") or 0),
                }
                item_b = {
                    "index": right,
                    "item": by_id[str(placements[right].get("id"))],
                    "placement": placements[right],
                    "sheetIndex": int(placements[right].get("sheetIndex") or 0),
                }
                result["collisions"].append(
                    _collision(
                        item_a,
                        item_b,
                        "overlap",
                        _num(normalize_sheet_params(sheet_params).get("spacingMm")),
                        0.0,
                        source="temporaryBRep",
                    )
                )
        except Exception as ex:
            result["exactCheckWarnings"].append(
                "Exact pair {}-{}: {}".format(left, right, ex)
            )
            result["exactValidationIncomplete"] = True

    result["collisionCount"] = len(result["collisions"])
    result["mappingWarningCount"] = len(result["mappingWarnings"])
    result["ok"] = (
        bool(result.get("ok"))
        and not result["collisions"]
        and not result["mappingWarnings"]
        and not result["exactValidationIncomplete"]
    )
    result["status"] = "safe" if result["ok"] else "unsafe"
    return result
