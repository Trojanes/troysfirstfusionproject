import json
import importlib
import os
import shutil
import subprocess

from modules.general_tall import fusion_adapter as general_tall_fusion_adapter


def _node_resolution_debug(resolved_node_path, checked_paths):
    return {
        "nodeResolution": {
            "resolvedNodePath": resolved_node_path,
            "checkedPaths": checked_paths,
        }
    }


def _candidate_node_paths():
    candidates = []
    env_node_exe = os.environ.get("NODE_EXE")
    if env_node_exe:
        candidates.append(("NODE_EXE", os.path.expandvars(env_node_exe)))

    path_node = shutil.which("node")
    if path_node:
        candidates.append(("PATH", path_node))
    else:
        candidates.append(("PATH", "node"))

    candidates.extend(
        [
            ("common", r"C:\Program Files\nodejs\node.exe"),
            ("common", r"C:\Program Files (x86)\nodejs\node.exe"),
            ("common", os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs\node.exe")),
        ]
    )

    env_node_path = os.environ.get("NODE_PATH")
    if env_node_path:
        candidates.append(("NODE_PATH", os.path.expandvars(env_node_path)))
    return candidates


def _resolve_node_executable():
    checked_paths = []
    for source, path in _candidate_node_paths():
        checked_paths.append({"source": source, "path": path, "exists": os.path.isfile(path)})
        if os.path.isfile(path):
            return path, checked_paths
    return None, checked_paths


class GeneralTallController:
    def __init__(self, plugin_dir, fusion=None):
        self.plugin_dir = plugin_dir
        self.fusion = fusion

    def generate(self, payload, _palette):
        node_exe, checked_paths = _resolve_node_executable()
        node_debug = _node_resolution_debug(node_exe, checked_paths)

        params = payload.get("params") if isinstance(payload, dict) else None
        if not isinstance(params, dict):
            return (
                "generalTallResult",
                {
                    "ok": False,
                    "module": "generalTall",
                    "action": "generalTall.generate",
                    "errors": ["Missing General Tall params payload."],
                    "debug": node_debug,
                },
            )

        if not node_exe:
            return (
                "generalTallResult",
                {
                    "ok": False,
                    "module": "generalTall",
                    "action": "generalTall.generate",
                    "errors": [
                        "Node.js executable was not found. Install Node.js or set NODE_EXE to the full path of node.exe."
                    ],
                    "debug": node_debug,
                },
            )

        script = os.path.join(self.plugin_dir, "scripts", "general_tall_from_params.js")
        try:
            proc = subprocess.run(
                [node_exe, script],
                cwd=self.plugin_dir,
                input=json.dumps({"params": params}, ensure_ascii=False),
                capture_output=True,
                text=True,
                timeout=120,
            )
        except Exception as ex:
            return (
                "generalTallResult",
                {
                    "ok": False,
                    "module": "generalTall",
                    "action": "generalTall.generate",
                    "errors": ["General Tall generation bridge failed: {}".format(ex)],
                    "debug": node_debug,
                },
            )

        raw_stdout = proc.stdout or ""
        try:
            bridge_result = json.loads(raw_stdout)
        except Exception as ex:
            return (
                "generalTallResult",
                {
                    "ok": False,
                    "module": "generalTall",
                    "action": "generalTall.generate",
                    "errors": ["General Tall bridge returned invalid JSON: {}".format(ex)],
                    "stderrPreview": (proc.stderr or "")[:500],
                    "stdoutPreview": raw_stdout[:500],
                    "debug": node_debug,
                },
            )

        if proc.returncode != 0 or not bridge_result.get("ok"):
            return (
                "generalTallResult",
                {
                    "ok": False,
                    "module": "generalTall",
                    "action": "generalTall.generate",
                    "errors": list(bridge_result.get("errors") or ["General Tall generation failed."]),
                    "stderrPreview": (proc.stderr or "")[:500],
                    "debug": node_debug,
                },
            )

        return (
            "generalTallResult",
            {
                "ok": True,
                "module": "generalTall",
                "action": "generalTall.generate",
                "result": bridge_result.get("result"),
                "debug": node_debug,
            },
        )

    def create_fusion_rough_bodies(self, payload, _palette):
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            return (
                "generalTallFusionResult",
                {
                    "ok": False,
                    "module": "generalTall",
                    "action": "generalTall.createFusionRoughBodies",
                    "errors": ["Missing General Tall result payload."],
                },
            )

        stacking = result.get("stacking") if isinstance(result.get("stacking"), dict) else {}
        validation = result.get("validation") if isinstance(result.get("validation"), dict) else {}
        boards = result.get("boards") if isinstance(result.get("boards"), list) else []
        validation_errors = list(validation.get("errors") or [])
        height_diff = stacking.get("difference")
        height_diff = float(height_diff) if isinstance(height_diff, (int, float)) else None
        invalid_boards = 0
        for board in boards:
            if not isinstance(board, dict):
                invalid_boards += 1
                continue
            try:
                x0 = float(board.get("x0"))
                x1 = float(board.get("x1"))
                y0 = float(board.get("y0"))
                y1 = float(board.get("y1"))
                z0 = float(board.get("z0"))
                z1 = float(board.get("z1"))
            except Exception:
                invalid_boards += 1
                continue
            dims = (
                x1 - x0,
                y1 - y0,
                z1 - z0,
            )
            if any((not isinstance(dim, (int, float)) or dim <= 0) for dim in dims):
                invalid_boards += 1

        if height_diff is not None and height_diff != 0:
            return (
                "generalTallFusionResult",
                {
                    "ok": False,
                    "module": "generalTall",
                    "action": "generalTall.createFusionRoughBodies",
                    "errors": ["General Tall cannot create Fusion bodies because cabinet height mismatch is unresolved."],
                    "status": "BLOCKED",
                    "heightDiff": height_diff,
                    "invalidBoards": invalid_boards,
                },
            )

        if validation_errors or invalid_boards > 0:
            return (
                "generalTallFusionResult",
                {
                    "ok": False,
                    "module": "generalTall",
                    "action": "generalTall.createFusionRoughBodies",
                    "errors": ["General Tall cannot create Fusion bodies because validation failed."],
                    "status": "FAIL",
                    "heightDiff": height_diff,
                    "invalidBoards": invalid_boards,
                    "validationErrors": validation_errors[:20],
                },
            )

        if self.fusion is None:
            return (
                "generalTallFusionResult",
                {
                    "ok": False,
                    "module": "generalTall",
                    "action": "generalTall.createFusionRoughBodies",
                    "errors": ["Fusion adapter is unavailable; reload the plugin and try again in an active Fusion design."],
                    "status": "FAIL",
                    "heightDiff": height_diff if height_diff is not None else 0,
                    "invalidBoards": invalid_boards,
                },
            )

        run_label = payload.get("caseName") if isinstance(payload, dict) else None
        params = payload.get("params") if isinstance(payload, dict) else None
        avoidance_z_shift_mm = 0.0
        if isinstance(params, dict):
            avoidance = params.get("avoidance")
            if isinstance(avoidance, dict) and avoidance.get("enabled") is True:
                try:
                    avoidance_z_shift_mm = float(avoidance.get("height") or 0.0)
                except Exception:
                    avoidance_z_shift_mm = 0.0
                if avoidance_z_shift_mm < 0:
                    avoidance_z_shift_mm = 0.0
        adapter_module = importlib.reload(general_tall_fusion_adapter)
        rough = adapter_module.create_rough_bodies_from_general_tall_result(
            self.fusion,
            result,
            run_label=run_label,
            avoidance_z_shift_mm=avoidance_z_shift_mm,
        )
        ok = len(rough.get("errors") or []) == 0
        if ok and self.fusion:
            self.fusion.refresh_viewport()
        return (
            "generalTallFusionResult",
            {
                "ok": ok,
                "module": "generalTall",
                "action": "generalTall.createFusionRoughBodies",
                "status": "READY" if ok else "FAIL",
                "heightDiff": height_diff if height_diff is not None else 0,
                "invalidBoards": invalid_boards,
                "canGenerate": ok,
                "createdBodies": rough.get("createdBodies", 0),
                "frontPanelsCreated": rough.get("frontPanelsCreated", 0),
                "frontPanelComponentName": rough.get("frontPanelComponentName"),
                "frontPanelModelZOffset": rough.get("frontPanelModelZOffset"),
                "boardCount": len(boards),
                "createdBoardIds": rough.get("createdBoardIds", []),
                "skippedBoards": rough.get("skippedBoards", []),
                "bodyAudit": rough.get("bodyAudit", []),
                "warnings": rough.get("warnings", []),
                "errors": rough.get("errors", []),
                "runLabel": rough.get("runLabel"),
            },
        )
