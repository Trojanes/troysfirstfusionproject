"""Optional native Sparrow quality-engine adapter.

The packaged executable is a thin CabinetNC wrapper around Sparrow/jagua-rs.
It accepts ``--input``, ``--output`` and ``--time-limit`` and exchanges the
stable ``cabinetnc.sparrow.v1`` JSON contract produced here. No binary is
downloaded at runtime; absence/failure is handled by ``nesting.engine``.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile

from nesting import sheet_pack


ENGINE_NAME = "sparrow_native"
DEFAULT_TIME_LIMIT_SEC = 30.0
PROTOCOL = "cabinetnc.sparrow.v1"


class SparrowError(RuntimeError):
    pass


def binary_path():
    explicit = str(os.environ.get("CABINETNC_SPARROW_EXE") or "").strip()
    if explicit:
        return os.path.abspath(os.path.expandvars(explicit))
    return os.path.join(
        os.path.dirname(__file__),
        "sparrow_bridge",
        "sparrow-cabinetnc.exe",
    )


def is_available(path=None):
    return os.path.isfile(path or binary_path())


def _rotation_values(params):
    return [float(value) for value in sheet_pack.rotation_candidates(params)]


def build_request(items, sheet_params, origin_x_mm, origin_y_mm, time_limit_sec=None):
    params = sheet_pack.normalize_sheet_params(sheet_params)
    jobs = {}
    for index, raw in enumerate(items or []):
        item = dict(raw or {})
        outline = item.get("outline") if isinstance(item.get("outline"), dict) else {}
        points = outline.get("points") or sheet_pack.rectangle_polygon(
            item.get("widthMm"), item.get("depthMm")
        )
        if len(points) < 4:
            continue
        key = sheet_pack._job_key(item)
        jobs.setdefault(key, []).append(
            {
                "sourceId": str(item.get("id") or index),
                "panelId": str(item.get("panelId") or ""),
                "bodyName": str(item.get("bodyName") or ""),
                "boardTypeTag": key[0],
                "colorTag": key[1],
                "shape": {"type": "simple_polygon", "data": points},
                "holes": (outline.get("holes") or [])
                if params.get("allowPartsInPart")
                else [],
                "allowedOrientationsDeg": _rotation_values(params),
            }
        )
    payload_jobs = []
    for job_index, key in enumerate(sorted(jobs)):
        board_type, color = key
        sheet = sheet_pack.sheet_size_for_type(params, board_type)
        payload_jobs.append(
            {
                "jobIndex": job_index,
                "boardTypeTag": board_type,
                "colorTag": color,
                "sheet": {
                    "widthMm": float(sheet["widthMm"]),
                    "heightMm": float(sheet["heightMm"]),
                    "borderMm": float(params["borderMm"]),
                    "spacingMm": float(params["spacingMm"]),
                },
                "items": jobs[key],
                # Included for wrappers that invoke upstream Sparrow directly.
                "sparrowInstance": {
                    "name": "cabinetnc_job_{}".format(job_index),
                    "items": [
                        {
                            "id": item_index,
                            "demand": 1,
                            "allowed_orientations": [
                                value * 3.141592653589793 / 180.0
                                for value in item["allowedOrientationsDeg"]
                            ],
                            "shape": item["shape"],
                        }
                        for item_index, item in enumerate(jobs[key])
                    ],
                    "strip_height": max(
                        float(sheet["heightMm"]) - 2.0 * float(params["borderMm"]),
                        1.0,
                    ),
                },
            }
        )
    return {
        "protocol": PROTOCOL,
        "origin": {
            "xMm": float(origin_x_mm or 0.0),
            "yMm": float(origin_y_mm or 0.0),
        },
        "timeLimitSec": max(
            float(time_limit_sec or params.get("qualityTimeLimitSec") or DEFAULT_TIME_LIMIT_SEC),
            1.0,
        ),
        "sheetParams": params,
        "jobs": payload_jobs,
    }


def _startup_options():
    startup_info = None
    creation_flags = 0
    if os.name == "nt":
        startup_info = subprocess.STARTUPINFO()
        startup_info.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return startup_info, creation_flags


def run_bridge(request, executable=None, run=subprocess.run):
    executable = executable or binary_path()
    if not os.path.isfile(executable):
        raise SparrowError(
            "Sparrow quality engine is not installed (expected {}).".format(executable)
        )
    timeout = max(float(request.get("timeLimitSec") or DEFAULT_TIME_LIMIT_SEC), 1.0)
    startup_info, creation_flags = _startup_options()
    with tempfile.TemporaryDirectory(prefix="cabinetnc-sparrow-") as folder:
        input_path = os.path.join(folder, "request.json")
        output_path = os.path.join(folder, "result.json")
        with open(input_path, "w", encoding="utf-8") as handle:
            json.dump(request, handle, ensure_ascii=False)
        try:
            completed = run(
                [
                    executable,
                    "--input",
                    input_path,
                    "--output",
                    output_path,
                    "--time-limit",
                    str(timeout),
                ],
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=timeout + 5.0,
                startupinfo=startup_info,
                creationflags=creation_flags,
            )
        except subprocess.TimeoutExpired as ex:
            raise SparrowError(
                "Sparrow exceeded the {:.0f}s quality time limit.".format(timeout)
            ) from ex
        if int(completed.returncode or 0) != 0:
            detail = (completed.stderr or completed.stdout or "").strip()[:500]
            raise SparrowError(
                "Sparrow exited with code {}{}.".format(
                    completed.returncode,
                    ": " + detail if detail else "",
                )
            )
        try:
            with open(output_path, "r", encoding="utf-8") as handle:
                response = json.load(handle)
        except Exception as ex:
            raise SparrowError("Sparrow returned no valid result JSON.") from ex
    return response


def _validate_response(response):
    if not isinstance(response, dict):
        raise SparrowError("Sparrow response must be an object.")
    if response.get("protocol") not in (None, PROTOCOL):
        raise SparrowError("Unsupported Sparrow bridge protocol.")
    layout = response.get("layout") if isinstance(response.get("layout"), dict) else response
    required = ("placements", "sheets", "groups", "unplaced")
    if any(not isinstance(layout.get(key), list) for key in required):
        raise SparrowError("Sparrow response is missing normalized layout arrays.")
    for placement in layout.get("placements") or []:
        for key in ("id", "sheetIndex", "targetX", "targetY", "rotationDeg"):
            if key not in placement:
                raise SparrowError("Sparrow placement is missing '{}'.".format(key))
    return layout


def _compact_world_layout(result, params, origin_x, origin_y):
    """Reflow bridge sheets so quality mode cannot recreate the long strip."""
    sheets = sorted(
        list(result.get("sheets") or []),
        key=lambda sheet: int(sheet.get("sheetIndex") or 0),
    )
    if not sheets:
        return result
    gap = float(params.get("sheetGapMm") or 0.0)
    width_limit = float(params.get("layoutWidthMm") or 0.0)
    cursor_x = float(origin_x or 0.0)
    cursor_y = float(origin_y or 0.0)
    row_height = 0.0
    origins = {}
    max_x = cursor_x
    max_y = cursor_y
    for sheet in sheets:
        width = float(sheet.get("widthMm") or 0.0)
        height = float(sheet.get("heightMm") or 0.0)
        if (
            width_limit > 0.0
            and cursor_x > float(origin_x or 0.0) + 1e-9
            and cursor_x + width > float(origin_x or 0.0) + width_limit + 1e-9
        ):
            cursor_x = float(origin_x or 0.0)
            cursor_y += row_height + gap
            row_height = 0.0
        index = int(sheet.get("sheetIndex") or 0)
        sheet["originX"] = cursor_x
        sheet["originY"] = cursor_y
        origins[index] = (cursor_x, cursor_y, width, height)
        cursor_x += width + gap
        row_height = max(row_height, height)
        max_x = max(max_x, sheet["originX"] + width)
        max_y = max(max_y, sheet["originY"] + height)
    for placement in result.get("placements") or []:
        origin = origins.get(int(placement.get("sheetIndex") or 0))
        if origin is None:
            continue
        local_x = float(placement.get("localX") or 0.0)
        local_y = float(placement.get("localY") or 0.0)
        placement["sheetOriginX"] = origin[0]
        placement["sheetOriginY"] = origin[1]
        placement["sheetWidthMm"] = origin[2]
        placement["sheetHeightMm"] = origin[3]
        placement["targetX"] = origin[0] + local_x
        placement["targetY"] = origin[1] + local_y
    result["sheets"] = sheets
    result["requiredWidthMm"] = max(max_x - float(origin_x or 0.0), 0.0)
    result["requiredDepthMm"] = max(max_y - float(origin_y or 0.0), 0.0)
    return result


def layout(
    items,
    sheet_params,
    origin_x_mm,
    origin_y_mm,
    wait_callback=None,
    executable=None,
    runner=None,
):
    params = sheet_pack.normalize_sheet_params(sheet_params)
    request = build_request(
        items,
        params,
        origin_x_mm,
        origin_y_mm,
        time_limit_sec=params.get("qualityTimeLimitSec"),
    )
    if callable(wait_callback):
        wait_callback()
    response = (runner or run_bridge)(request, executable=executable)
    if callable(wait_callback):
        wait_callback()
    result = dict(_validate_response(response))
    result["engine"] = ENGINE_NAME
    result.setdefault("requestedEngine", ENGINE_NAME)
    result.setdefault("engineFallback", False)
    result.setdefault("engineFallbackReason", None)
    result.setdefault("borderMm", params["borderMm"])
    result.setdefault("spacingMm", params["spacingMm"])
    result.setdefault("sheetParams", params)
    result.setdefault("partsInPartApplied", False)
    result.setdefault("holeOutlineCount", 0)
    result.setdefault("nestedInHoleCount", 0)
    result.setdefault("requiredWidthMm", 0.0)
    result.setdefault("requiredDepthMm", 0.0)
    return _compact_world_layout(result, params, origin_x_mm, origin_y_mm)
