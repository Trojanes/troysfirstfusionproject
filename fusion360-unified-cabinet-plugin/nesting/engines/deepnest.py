"""Deepnest-next adapter implementing CabinetNC's stable layout contract."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os

from nesting import outline as nesting_outline
from nesting import sheet_pack
from nesting.engines import deepnest_bridge_client


ENGINE_NAME = "deepnest_next_v1_5_6"
# Stop after this many GA placements; keep the best fitness. Not an optimality hunt.
FIXED_PLACEMENT_EVALS = 2
# Safety net only — normal jobs finish at FIXED_PLACEMENT_EVALS, not at this timer.
DEFAULT_TIME_BUDGET_MS = 90000
MAX_PARALLEL_JOBS = 2
# Deepnest GA rarely emits a first placement for 100+ true-shape parts in one
# shot. Chunk material groups so each bridge call stays tractable.
MAX_PARTS_PER_DEEPNEST_JOB = 40


class DeepnestError(RuntimeError):
    """Raised when the embedded Deepnest runtime cannot produce a layout."""


def time_budget_ms_for_parts(part_count):
    """Safety timeout if Deepnest never emits FIXED_PLACEMENT_EVALS results."""
    n = max(int(part_count or 0), 1)
    budget = 20000 + n * 400  # 20s + 0.4s/part
    return int(min(max(budget, 30000), 120000))  # 30s .. 2min ceiling


def search_options_for_parts(part_count):
    """Return (timeBudgetMs, maxResults, populationSize).

    Strategy: run a fixed number of placements, keep the best, stop immediately.
    Time budget is only a backstop when no placement arrives.
    """
    n = max(int(part_count or 0), 1)
    budget = time_budget_ms_for_parts(n)
    # Small population — we are not searching for a global optimum.
    population = 4 if n >= 20 else 6
    return budget, FIXED_PLACEMENT_EVALS, population


def _runtime_paths():
    nesting_dir = os.path.dirname(os.path.dirname(__file__))
    vendor_dir = os.path.join(nesting_dir, "vendor", "deepnest-next")
    bridge_main = os.path.join(
        nesting_dir, "engines", "deepnest_bridge", "main.cjs"
    )
    electron = os.path.join(
        vendor_dir, "node_modules", "electron", "dist", "electron.exe"
    )
    return vendor_dir, bridge_main, electron


def is_available():
    vendor_dir, bridge_main, electron = _runtime_paths()
    required = (
        bridge_main,
        electron,
        os.path.join(vendor_dir, "main", "deepnest.js"),
        os.path.join(vendor_dir, "main", "background.js"),
        os.path.join(vendor_dir, "build", "nfpDb.js"),
    )
    return all(os.path.isfile(path) for path in required)


def _run_bridge(job):
    if not is_available():
        raise DeepnestError("Embedded Deepnest runtime is incomplete.")
    try:
        return deepnest_bridge_client.run_job(job)
    except deepnest_bridge_client.BridgeClientError as ex:
        raise DeepnestError(str(ex)) from ex


def _geometry_signature(job):
    """Hash geometry-affecting input while excluding search duration controls."""
    options = {
        key: value
        for key, value in (job.get("options") or {}).items()
        if key not in ("timeBudgetMs", "maxResults")
    }
    payload = {
        "parts": job.get("parts") or [],
        "sheet": job.get("sheet") or {},
        "options": options,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _open_ring(points, clockwise=False):
    """Return a validated-winding polygon ring without its closing point."""
    winding = (
        nesting_outline.hole_cw(points)
        if clockwise
        else nesting_outline.outer_ccw(points)
    )
    if len(winding) > 1 and winding[0] == winding[-1]:
        winding = winding[:-1]
    return winding


def _outline_tree(item, include_holes=False):
    """Return an open CCW outer ring and validated open CW hole rings."""
    outline = item.get("outline") if isinstance(item.get("outline"), dict) else {}
    points = outline.get("points")
    if not isinstance(points, list) or len(points) < 4:
        points = nesting_outline.rectangle_polygon(
            item.get("widthMm"), item.get("depthMm")
        )
    outer = _open_ring(points, clockwise=False)
    holes = []
    if include_holes:
        accepted = []
        for value in outline.get("holes") or []:
            raw_points = (
                value.get("points") or value.get("pointsLocal") or []
                if isinstance(value, dict)
                else value
            )
            candidate = nesting_outline.hole_cw(raw_points)
            if not nesting_outline.hole_is_valid(candidate, outer, accepted):
                continue
            accepted.append(candidate)
            holes.append(_open_ring(candidate, clockwise=True))
    return outer, holes


def _outline_points(item):
    """Compatibility helper for callers that only need the outer ring."""
    return _outline_tree(item, include_holes=False)[0]


def _normalise_items(items):
    jobs = {}
    outline_counts = {"flatBody": 0, "metadataSvg": 0, "rectangle": 0, "other": 0}
    for source_index, item in enumerate(items or []):
        width = max(sheet_pack._num((item or {}).get("widthMm")), 0.0)
        depth = max(sheet_pack._num((item or {}).get("depthMm")), 0.0)
        if width <= 0.0 or depth <= 0.0:
            continue
        normalized = dict(item)
        normalized["widthMm"] = width
        normalized["depthMm"] = depth
        normalized["boardTypeTag"] = sheet_pack._tag(
            normalized.get("boardTypeTag")
        )
        normalized["colorTag"] = sheet_pack._tag(normalized.get("colorTag"))
        normalized["_deepnestSourceId"] = str(source_index)
        outline = normalized.get("outline")
        if not isinstance(outline, dict) or not outline.get("points"):
            outline = nesting_outline.build_outline_payload(
                nesting_outline.rectangle_polygon(width, depth),
                "rectangle",
                width,
                depth,
            )
            normalized["outline"] = outline
        source = str((outline or {}).get("source") or "other")
        outline_counts[source if source in outline_counts else "other"] += 1
        jobs.setdefault(sheet_pack._job_key(normalized), []).append(normalized)
    return jobs, outline_counts


def _pack_job_once(parts, sheet, params):
    by_source = {part["_deepnestSourceId"]: part for part in parts}
    include_holes = bool(params.get("allowPartsInPart"))
    outline_trees = {
        source_id: _outline_tree(part, include_holes=include_holes)
        for source_id, part in by_source.items()
    }
    hole_outline_count = sum(
        len(holes) for _outer, holes in outline_trees.values()
    )
    time_budget_ms, max_results, population_size = search_options_for_parts(
        len(parts)
    )
    job = {
        "schemaVersion": 1,
        "parts": [
            {
                "id": source_id,
                "points": outline_trees[source_id][0],
                "holes": outline_trees[source_id][1],
            }
            for source_id, part in by_source.items()
        ],
        "sheet": {
            "widthMm": float(sheet["widthMm"]),
            "heightMm": float(sheet["heightMm"]),
            "borderMm": float(params["borderMm"]),
            "quantity": max(len(parts), 1),
        },
        "options": {
            "spacingMm": float(params["spacingMm"]),
            "allowRotation": bool(params["allowRotation"]),
            "rotationIncrementDeg": float(
                params.get("rotationIncrementDeg") or 90.0
            ),
            "populationSize": population_size,
            "mutationRate": 10,
            "placementType": "gravity",
            "maxResults": max_results,
            "timeBudgetMs": time_budget_ms,
        },
    }
    job["geometrySignature"] = _geometry_signature(job)
    result = _run_bridge(job)
    packed_sheets = []
    placed_ids = set()
    nested_in_hole_count = 0
    sheet_w = float(sheet["widthMm"])
    sheet_h = float(sheet["heightMm"])
    border = float(params["borderMm"])
    inner_area = max(sheet_w - 2.0 * border, 0.0) * max(
        sheet_h - 2.0 * border, 0.0
    )

    for sheet_result in result.get("placements") or []:
        local_placements = []
        for raw in sheet_result.get("sheetplacements") or []:
            source_id = str(raw.get("filename"))
            item = by_source.get(source_id)
            if item is None:
                continue
            placed_ids.add(source_id)
            rotation = float(raw.get("rotation") or 0.0) % 360.0
            points, holes = outline_trees[source_id]
            rotated = nesting_outline.rotate_polygon(points, rotation)
            rotated_bounds = nesting_outline.polygon_bounds(rotated)
            normalized, _unused = nesting_outline.normalize_polygon_to_origin(rotated)
            normalized_holes = [
                nesting_outline.translate_polygon(
                    nesting_outline.rotate_polygon(hole, rotation),
                    -rotated_bounds["minX"],
                    -rotated_bounds["minY"],
                )
                for hole in holes
            ]
            local_x = float(raw.get("x") or 0.0) + rotated_bounds["minX"]
            local_y = float(raw.get("y") or 0.0) + rotated_bounds["minY"]
            world_outline = nesting_outline.translate_polygon(
                normalized, local_x, local_y
            )
            world_holes = [
                nesting_outline.translate_polygon(hole, local_x, local_y)
                for hole in normalized_holes
            ]
            placement = {
                **{
                    key: value
                    for key, value in item.items()
                    if key != "_deepnestSourceId"
                },
                "localX": local_x,
                "localY": local_y,
                "packedWidthMm": rotated_bounds["widthMm"],
                "packedDepthMm": rotated_bounds["depthMm"],
                "rotationDeg": rotation,
                "packedOutline": world_outline,
                "packedHoles": world_holes,
                "packedAreaMm2": nesting_outline.polygon_area(normalized),
            }
            if "inHole" in raw:
                placement["inHole"] = raw.get("inHole")
                if bool(raw.get("inHole")):
                    nested_in_hole_count += 1
            local_placements.append(placement)
        used_area = sum(
            float(entry.get("packedAreaMm2") or 0.0)
            for entry in local_placements
        )
        packed_sheets.append(
            {
                "sheetIndex": len(packed_sheets),
                "boardTypeTag": sheet["boardTypeTag"],
                "widthMm": sheet_w,
                "heightMm": sheet_h,
                "count": len(local_placements),
                "usedAreaMm2": used_area,
                "innerAreaMm2": inner_area,
                "utilization": used_area / inner_area if inner_area > 1e-9 else 0.0,
                "placements": local_placements,
            }
        )

    unplaced = [
        {
            **{key: value for key, value in part.items() if key != "_deepnestSourceId"},
            "reason": "Deepnest did not place this part.",
        }
        for source_id, part in by_source.items()
        if source_id not in placed_ids
    ]
    return packed_sheets, unplaced, {
        "fitness": result.get("fitness"),
        "evaluatedResults": result.get("evaluatedResults"),
        "requestedTimeBudgetMs": result.get("requestedTimeBudgetMs") or time_budget_ms,
        "holeOutlineCount": hole_outline_count,
        "nestedInHoleCount": nested_in_hole_count,
        "partCount": len(parts),
    }


def _pack_job(parts, sheet, params):
    """Pack a material group, chunking so Deepnest can finish each call."""
    parts = list(parts or [])
    if not parts:
        return [], [], {"partCount": 0, "chunkCount": 0}
    if len(parts) <= MAX_PARTS_PER_DEEPNEST_JOB:
        sheets, unplaced, diagnostics = _pack_job_once(parts, sheet, params)
        diagnostics = dict(diagnostics or {})
        diagnostics["chunkCount"] = 1
        return sheets, unplaced, diagnostics

    packed_sheets = []
    unplaced = []
    hole_outline_count = 0
    nested_in_hole_count = 0
    evaluated_results = 0
    chunk_count = 0
    for start in range(0, len(parts), MAX_PARTS_PER_DEEPNEST_JOB):
        chunk = parts[start : start + MAX_PARTS_PER_DEEPNEST_JOB]
        chunk_count += 1
        try:
            sheets, chunk_unplaced, diagnostics = _pack_job_once(
                chunk, sheet, params
            )
        except DeepnestError:
            # Keep remaining chunks / other materials alive: sheet_pack this chunk.
            sheets, chunk_unplaced = sheet_pack._pack_job(chunk, sheet, params)
            diagnostics = {
                "engine": sheet_pack.ENGINE_NAME,
                "chunkFallback": True,
                "partCount": len(chunk),
            }
        for local_sheet in sheets or []:
            packed = dict(local_sheet)
            packed["sheetIndex"] = len(packed_sheets)
            packed_sheets.append(packed)
        unplaced.extend(chunk_unplaced or [])
        hole_outline_count += int((diagnostics or {}).get("holeOutlineCount") or 0)
        nested_in_hole_count += int(
            (diagnostics or {}).get("nestedInHoleCount") or 0
        )
        evaluated_results += int((diagnostics or {}).get("evaluatedResults") or 0)

    return packed_sheets, unplaced, {
        "evaluatedResults": evaluated_results,
        "holeOutlineCount": hole_outline_count,
        "nestedInHoleCount": nested_in_hole_count,
        "partCount": len(parts),
        "chunkCount": chunk_count,
    }


def _pack_job_with_group_fallback(parts, sheet, params):
    """Deepnest a group; on total failure use sheet_pack for that group only."""
    try:
        return _pack_job(parts, sheet, params)
    except Exception as ex:
        sheets, unplaced = sheet_pack._pack_job(parts, sheet, params)
        return sheets, unplaced, {
            "engine": sheet_pack.ENGINE_NAME,
            "groupFallback": True,
            "fallbackReason": str(ex),
            "partCount": len(parts or []),
        }


def layout(
    items,
    sheet_params,
    origin_x_mm,
    origin_y_mm,
    wait_callback=None,
):
    """Return Deepnest placements in the same shape as sheet_pack_layout."""
    params = sheet_pack.normalize_sheet_params(sheet_params)
    origin_x = sheet_pack._num(origin_x_mm)
    origin_y = sheet_pack._num(origin_y_mm)
    sheet_gap = float(params["sheetGapMm"])
    jobs, outline_counts = _normalise_items(items)

    placements = []
    groups = []
    sheets_summary = []
    unplaced = []
    diagnostics = []
    type_cursor_y = origin_y
    max_x = origin_x
    max_y = origin_y
    global_group_index = 0
    hole_outline_count = 0
    nested_in_hole_count = 0

    ordered_keys = sorted(jobs)
    packed_by_key = {}
    if ordered_keys:
        worker_count = min(len(ordered_keys), MAX_PARALLEL_JOBS)
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=worker_count,
            thread_name_prefix="cabinetnc-deepnest",
        ) as executor:
            future_to_key = {
                executor.submit(
                    _pack_job_with_group_fallback,
                    jobs[key],
                    sheet_pack.sheet_size_for_type(params, key[0]),
                    params,
                ): key
                for key in ordered_keys
            }
            pending = set(future_to_key)
            while pending:
                done, pending = concurrent.futures.wait(
                    pending,
                    timeout=0.05,
                    return_when=concurrent.futures.FIRST_COMPLETED,
                )
                for future in done:
                    packed_by_key[future_to_key[future]] = future.result()
                if wait_callback is not None:
                    wait_callback()

    for job_index, key in enumerate(ordered_keys):
        board_type, color = key
        sheet = sheet_pack.sheet_size_for_type(params, board_type)
        packed_sheets, job_unplaced, job_diagnostics = packed_by_key[key]
        hole_outline_count += int(job_diagnostics.get("holeOutlineCount") or 0)
        nested_in_hole_count += int(job_diagnostics.get("nestedInHoleCount") or 0)
        diagnostics.append(
            {
                "boardTypeTag": board_type,
                "colorTag": color,
                **job_diagnostics,
            }
        )
        unplaced.extend(job_unplaced)

        sheet_cursor_x = origin_x
        sheet_cursor_y = type_cursor_y
        row_height = 0.0
        layout_width = float(params.get("layoutWidthMm") or 0.0)
        for local_sheet in packed_sheets:
            sheet_w = float(local_sheet["widthMm"])
            sheet_h = float(local_sheet["heightMm"])
            if (
                layout_width > 0.0
                and sheet_cursor_x > origin_x + 1e-9
                and sheet_cursor_x + sheet_w > origin_x + layout_width + 1e-9
            ):
                sheet_cursor_x = origin_x
                sheet_cursor_y += row_height + sheet_gap
                row_height = 0.0
            sheet_origin_x = sheet_cursor_x
            sheet_origin_y = sheet_cursor_y
            sheet_index_global = len(sheets_summary)
            for item_index, local in enumerate(local_sheet["placements"]):
                placements.append(
                    {
                        **local,
                        "groupIndex": global_group_index,
                        "itemIndex": item_index,
                        "sheetIndex": sheet_index_global,
                        "sheetLocalIndex": local_sheet["sheetIndex"],
                        "groupKey": {
                            "boardTypeTag": board_type,
                            "colorTag": color,
                        },
                        "sheetOriginX": sheet_origin_x,
                        "sheetOriginY": sheet_origin_y,
                        "sheetWidthMm": sheet_w,
                        "sheetHeightMm": sheet_h,
                        "targetX": sheet_origin_x + float(local["localX"]),
                        "targetY": sheet_origin_y + float(local["localY"]),
                        "targetZ": 0.0,
                    }
                )
            sheets_summary.append(
                {
                    **{
                        key: value
                        for key, value in local_sheet.items()
                        if key != "placements"
                    },
                    "sheetIndex": sheet_index_global,
                    "boardTypeTag": board_type,
                    "colorTag": color,
                    "originX": sheet_origin_x,
                    "originY": sheet_origin_y,
                    "jobIndex": job_index,
                }
            )
            groups.append(
                {
                    "groupIndex": global_group_index,
                    "boardTypeTag": board_type,
                    "colorTag": color,
                    "sheetIndex": sheet_index_global,
                    "originX": sheet_origin_x,
                    "originY": sheet_origin_y,
                    "widthMm": sheet_w,
                    "depthMm": sheet_h,
                    "count": local_sheet["count"],
                    "utilization": local_sheet["utilization"],
                }
            )
            global_group_index += 1
            sheet_cursor_x += sheet_w + sheet_gap
            row_height = max(row_height, sheet_h)
            max_x = max(max_x, sheet_origin_x + sheet_w)
            max_y = max(max_y, sheet_origin_y + sheet_h)
        if packed_sheets:
            type_cursor_y = sheet_cursor_y + row_height + sheet_gap

    true_shape_count = outline_counts["flatBody"] + outline_counts["metadataSvg"]
    group_fallbacks = [
        item for item in diagnostics if item.get("groupFallback") or item.get("chunkFallback")
    ]
    return {
        "engine": ENGINE_NAME,
        "engineFallback": bool(group_fallbacks),
        "engineFallbackReason": (
            "; ".join(
                str(item.get("fallbackReason") or "chunk/group sheet_pack fallback")
                for item in group_fallbacks[:3]
            )
            if group_fallbacks
            else None
        ),
        "placements": placements,
        "groups": groups,
        "sheets": sheets_summary,
        "unplaced": unplaced,
        "requiredWidthMm": max(max_x - origin_x, 0.0),
        "requiredDepthMm": max(max_y - origin_y, 0.0),
        "borderMm": params["borderMm"],
        "spacingMm": params["spacingMm"],
        "allowRotation": params["allowRotation"],
        "allowPartsInPart": params["allowPartsInPart"],
        "partsInPartApplied": bool(
            params["allowPartsInPart"] and hole_outline_count > 0
        ),
        "holeOutlineCount": hole_outline_count,
        "nestedInHoleCount": nested_in_hole_count,
        "sheetGapMm": params["sheetGapMm"],
        "sheetParams": params,
        "outlineCounts": outline_counts,
        "trueShapeCount": true_shape_count,
        "rectangleFallbackCount": outline_counts.get("rectangle", 0),
        "engineDiagnostics": diagnostics,
        "bridgeHealth": deepnest_bridge_client.health_diagnostics(),
    }
