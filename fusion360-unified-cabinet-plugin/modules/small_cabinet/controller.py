import json
import importlib
import os
import shutil
import subprocess

from modules.small_cabinet import fusion_adapter as board_fusion_adapter


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
    return candidates


def _resolve_node_executable():
    checked_paths = []
    for source, path in _candidate_node_paths():
        checked_paths.append({"source": source, "path": path, "exists": os.path.isfile(path)})
        if os.path.isfile(path):
            return path, checked_paths
    return None, checked_paths


class SmallCabinetController:
    def __init__(self, plugin_dir, fusion=None):
        self.plugin_dir = plugin_dir
        self.fusion = fusion

    def _generate_result_from_params(self, params):
        node_exe, checked_paths = _resolve_node_executable()
        node_debug = {
            "nodeResolution": {
                "resolvedNodePath": node_exe,
                "checkedPaths": checked_paths,
            }
        }
        if not isinstance(params, dict):
            return None, ["Missing Small Cabinet params payload."], node_debug
        if not node_exe:
            return None, [
                "Node.js executable was not found. Install Node.js or set NODE_EXE to the full path of node.exe."
            ], node_debug

        script = os.path.join(self.plugin_dir, "scripts", "small_cabinet_from_params.js")
        try:
            proc = subprocess.run(
                [node_exe, script],
                cwd=self.plugin_dir,
                input=json.dumps({"params": params}, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except Exception as ex:
            return None, ["Small Cabinet generation bridge failed: {}".format(ex)], node_debug

        raw_stdout = proc.stdout or ""
        try:
            bridge_result = json.loads(raw_stdout)
        except Exception as ex:
            return None, [
                "Small Cabinet bridge returned invalid JSON: {}".format(ex),
                "stderr: {}".format((proc.stderr or "")[:500]),
                "stdout: {}".format(raw_stdout[:500]),
            ], node_debug

        if proc.returncode != 0 or not bridge_result.get("ok"):
            return None, list(bridge_result.get("errors") or ["Small Cabinet generation failed."]), node_debug

        result = bridge_result.get("result")
        if not isinstance(result, dict):
            return None, ["Small Cabinet bridge returned no result."], node_debug
        return result, [], node_debug

    def generate(self, payload, _palette):
        params = payload.get("params") if isinstance(payload, dict) else None
        result, errors, node_debug = self._generate_result_from_params(params)
        if errors:
            return (
                "smallCabinetResult",
                {
                    "ok": False,
                    "module": "smallCabinet",
                    "action": "smallCabinet.generate",
                    "errors": errors,
                    "debug": node_debug,
                },
            )
        return (
            "smallCabinetResult",
            {
                "ok": True,
                "module": "smallCabinet",
                "action": "smallCabinet.generate",
                "result": result,
                "debug": node_debug,
            },
        )

    def create_fusion_rough_bodies(self, payload, _palette):
        params = payload.get("params") if isinstance(payload, dict) else None
        result = payload.get("result") if isinstance(payload, dict) else None
        node_debug = {}
        if isinstance(params, dict):
            fresh, errors, node_debug = self._generate_result_from_params(params)
            if errors or not isinstance(fresh, dict):
                return (
                    "smallCabinetFusionResult",
                    {
                        "ok": False,
                        "module": "smallCabinet",
                        "action": "smallCabinet.createFusionRoughBodies",
                        "errors": errors or ["Missing Small Cabinet result payload."],
                        "debug": node_debug,
                    },
                )
            result = fresh
        elif not isinstance(result, dict):
            return (
                "smallCabinetFusionResult",
                {
                    "ok": False,
                    "module": "smallCabinet",
                    "action": "smallCabinet.createFusionRoughBodies",
                    "errors": ["Missing Small Cabinet result payload."],
                    "debug": node_debug,
                },
            )

        validation = result.get("validation") if isinstance(result.get("validation"), dict) else {}
        boards = result.get("boards") if isinstance(result.get("boards"), list) else []
        validation_errors = list(validation.get("errors") or [])
        if validation_errors or not boards:
            return (
                "smallCabinetFusionResult",
                {
                    "ok": False,
                    "module": "smallCabinet",
                    "action": "smallCabinet.createFusionRoughBodies",
                    "errors": validation_errors or ["Small Cabinet has no boards to create."],
                    "status": "FAIL",
                },
            )

        if self.fusion is None:
            return (
                "smallCabinetFusionResult",
                {
                    "ok": False,
                    "module": "smallCabinet",
                    "action": "smallCabinet.createFusionRoughBodies",
                    "errors": [
                        "Fusion adapter is unavailable; reload the plugin and try again in an active Fusion design."
                    ],
                    "status": "FAIL",
                },
            )

        run_label = payload.get("caseName") if isinstance(payload, dict) else None
        assembly_name = payload.get("assemblyName") if isinstance(payload, dict) else None
        assembly_name = str(assembly_name).strip() if assembly_name else ""
        origin_x_mm = origin_y_mm = 0.0
        try:
            import work_zones

            root = self.fusion.get_root_component() if self.fusion else None
            origin_x_mm, origin_y_mm = work_zones.resolve_origin_from_payload(payload, root)
        except Exception:
            if isinstance(payload, dict):
                try:
                    origin_x_mm = float(payload.get("originXMm") or 0.0)
                except Exception:
                    origin_x_mm = 0.0
                try:
                    origin_y_mm = float(payload.get("originYMm") or 0.0)
                except Exception:
                    origin_y_mm = 0.0

        adapter_module = importlib.reload(board_fusion_adapter)
        rough = adapter_module.create_rough_bodies_from_board_result(
            self.fusion,
            result,
            module_name="smallCabinet",
            body_prefix="SC",
            run_label=run_label,
            placement_feature_prefix="SC_PLACE_",
            move_feature_prefix="SC_MOVE_",
            align_feature_prefix="SC_ALIGN_",
            enable_zi_groove_cuts=False,
            enable_overhead_postprocess=False,
            create_container_component=True,
            component_name=assembly_name or "SC",
            origin_x_mm=origin_x_mm,
            origin_y_mm=origin_y_mm,
        )
        ok = len(rough.get("errors") or []) == 0
        if ok and self.fusion:
            self.fusion.refresh_viewport()
        return (
            "smallCabinetFusionResult",
            {
                "ok": ok,
                "module": "smallCabinet",
                "action": "smallCabinet.createFusionRoughBodies",
                "status": "READY" if ok else "FAIL",
                "canGenerate": ok,
                "createdBodies": rough.get("createdBodies", 0),
                "assemblyComponentName": rough.get("assemblyComponentName"),
                "boardCount": len(boards),
                "createdBoardIds": rough.get("createdBoardIds", []),
                "skippedBoards": rough.get("skippedBoards", []),
                "bodyAudit": rough.get("bodyAudit", []),
                "adapterBuild": rough.get("adapterBuild"),
                "bodyComponentsCreated": rough.get("bodyComponentsCreated", 0),
                "bodyComponentNames": rough.get("bodyComponentNames", []),
                "warnings": rough.get("warnings", []),
                "errors": rough.get("errors", []),
                "runLabel": rough.get("runLabel"),
                "sideGrooveCutsCreated": rough.get("sideGrooveCutsCreated", 0),
                "lockCutsCreated": rough.get("lockCutsCreated", 0),
                "smallCabinetPostprocess": rough.get("smallCabinetPostprocess", {}),
                "result": result,
                "debug": node_debug,
            },
        )
