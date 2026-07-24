import json
import importlib
import os
import shutil
import subprocess

from modules.general_tall import fusion_adapter as board_fusion_adapter


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


class OverheadController:
    def __init__(self, plugin_dir, fusion=None):
        self.plugin_dir = plugin_dir
        self.fusion = fusion

    def status(self, _payload, _palette):
        return (
            "unifiedResult",
            {
                "ok": True,
                "module": "overhead",
                "status": "geometry_v1",
                "message": "Overhead Cabinet geometry port (TS) is active. Fusion body generation pending.",
            },
        )

    def _generate_result_from_params(self, params):
        node_exe, checked_paths = _resolve_node_executable()
        node_debug = {
            "nodeResolution": {
                "resolvedNodePath": node_exe,
                "checkedPaths": checked_paths,
            }
        }
        if not isinstance(params, dict):
            return None, ["Missing Overhead params payload."], node_debug
        if not node_exe:
            return None, [
                "Node.js executable was not found. Install Node.js or set NODE_EXE to the full path of node.exe."
            ], node_debug

        script = os.path.join(self.plugin_dir, "scripts", "overhead_from_params.js")
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
            return None, ["Overhead generation bridge failed: {}".format(ex)], node_debug

        raw_stdout = proc.stdout or ""
        try:
            bridge_result = json.loads(raw_stdout)
        except Exception as ex:
            return None, [
                "Overhead bridge returned invalid JSON: {}".format(ex),
                "stderr: {}".format((proc.stderr or "")[:500]),
                "stdout: {}".format(raw_stdout[:500]),
            ], node_debug

        if proc.returncode != 0 or not bridge_result.get("ok"):
            return None, list(bridge_result.get("errors") or ["Overhead generation failed."]), node_debug

        result = bridge_result.get("result")
        if not isinstance(result, dict):
            return None, ["Overhead bridge returned no result."], node_debug
        return result, [], node_debug

    def _bench_meta(self, payload):
        if not isinstance(payload, dict):
            return {}
        client_bench_id = payload.get("clientBenchId")
        if client_bench_id:
            return {"clientBenchId": client_bench_id}
        return {}

    def _with_bench(self, payload, body):
        merged = dict(body)
        merged.update(self._bench_meta(payload))
        return merged

    def create_fusion_rough_bodies(self, payload, _palette):
        params = payload.get("params") if isinstance(payload, dict) else None
        result = payload.get("result") if isinstance(payload, dict) else None
        node_debug = {}
        # Always rebuild from current params when available so UI toggles
        # (Style / LED groove) are applied instead of a stale cached result.
        if isinstance(params, dict):
            fresh, errors, node_debug = self._generate_result_from_params(params)
            if errors or not isinstance(fresh, dict):
                return (
                    "overheadFusionResult",
                    self._with_bench(
                        payload,
                        {
                            "ok": False,
                            "module": "overhead",
                            "action": "overhead.createFusionRoughBodies",
                            "errors": errors or ["Missing Overhead result payload."],
                            "debug": node_debug,
                        },
                    ),
                )
            result = fresh
        elif not isinstance(result, dict):
            return (
                "overheadFusionResult",
                self._with_bench(
                    payload,
                    {
                        "ok": False,
                        "module": "overhead",
                        "action": "overhead.createFusionRoughBodies",
                        "errors": ["Missing Overhead result payload."],
                        "debug": node_debug,
                    },
                ),
            )

        validation = result.get("validation") if isinstance(result.get("validation"), dict) else {}
        boards = result.get("boards") if isinstance(result.get("boards"), list) else []
        validation_errors = list(validation.get("errors") or [])
        invalid_boards = 0
        for board in boards:
            if not isinstance(board, dict):
                invalid_boards += 1
                continue
            try:
                dims = (
                    float(board.get("x1")) - float(board.get("x0")),
                    float(board.get("y1")) - float(board.get("y0")),
                    float(board.get("z1")) - float(board.get("z0")),
                )
            except Exception:
                invalid_boards += 1
                continue
            if any(dim <= 0 for dim in dims):
                invalid_boards += 1

        if validation_errors or invalid_boards > 0:
            return (
                "overheadFusionResult",
                self._with_bench(
                    payload,
                    {
                        "ok": False,
                        "module": "overhead",
                        "action": "overhead.createFusionRoughBodies",
                        "errors": ["Overhead cannot create Fusion bodies because validation failed."],
                        "status": "FAIL",
                        "invalidBoards": invalid_boards,
                        "validationErrors": validation_errors[:20],
                    },
                ),
            )

        if self.fusion is None:
            return (
                "overheadFusionResult",
                self._with_bench(
                    payload,
                    {
                        "ok": False,
                        "module": "overhead",
                        "action": "overhead.createFusionRoughBodies",
                        "errors": ["Fusion adapter is unavailable; reload the plugin and try again in an active Fusion design."],
                        "status": "FAIL",
                        "invalidBoards": invalid_boards,
                    },
                ),
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
            module_name="overhead",
            body_prefix="OH",
            run_label=run_label,
            placement_feature_prefix="OH_PLACE_",
            move_feature_prefix="OH_MOVE_",
            align_feature_prefix="OH_ALIGN_",
            enable_zi_groove_cuts=False,
            enable_overhead_postprocess=True,
            create_container_component=True,
            component_name=assembly_name or "OHC",
            origin_x_mm=origin_x_mm,
            origin_y_mm=origin_y_mm,
        )
        ok = len(rough.get("errors") or []) == 0
        if ok and self.fusion:
            self.fusion.refresh_viewport()
        return (
            "overheadFusionResult",
            self._with_bench(
                payload,
                {
                    "ok": ok,
                    "module": "overhead",
                    "action": "overhead.createFusionRoughBodies",
                    "status": "READY" if ok else "FAIL",
                    "invalidBoards": invalid_boards,
                    "canGenerate": ok,
                    "createdBodies": rough.get("createdBodies", 0),
                    "assemblyComponentName": rough.get("assemblyComponentName"),
                    "placementFormulas": rough.get("placementFormulas", {}),
                    "boardCount": len(boards),
                    "createdBoardIds": rough.get("createdBoardIds", []),
                    "skippedBoards": rough.get("skippedBoards", []),
                    "bodyAudit": rough.get("bodyAudit", []),
                    "overheadPostprocess": rough.get("overheadPostprocess", {}),
                    "bpGrooveCutsCreated": rough.get("bpGrooveCutsCreated", 0),
                    "ledGrooveCutsCreated": rough.get("ledGrooveCutsCreated", 0),
                    "ledGrooveCutsFailed": rough.get("ledGrooveCutsFailed", 0),
                    "ledGrooveCutsSkipped": rough.get("ledGrooveCutsSkipped", 0),
                    "adapterBuild": rough.get("adapterBuild"),
                    "hingeCutsCreated": rough.get("hingeCutsCreated", 0),
                    "rotationOpsCreated": rough.get("rotationOpsCreated", 0),
                    "topPanelTranslationsCreated": rough.get("topPanelTranslationsCreated", 0),
                    "frontPanelZShiftsCreated": rough.get("frontPanelZShiftsCreated", 0),
                    "dividerZShiftsCreated": rough.get("dividerZShiftsCreated", 0),
                    "supportZShiftsCreated": rough.get("supportZShiftsCreated", 0),
                    "bodyComponentsCreated": rough.get("bodyComponentsCreated", 0),
                    "bodyComponentNames": rough.get("bodyComponentNames", []),
                    "warnings": rough.get("warnings", []),
                    "errors": rough.get("errors", []),
                    "runLabel": rough.get("runLabel"),
                    "faceInitSummary": rough.get("faceInitSummary", {}),
                },
            ),
        )

    def generate(self, payload, _palette):
        params = payload.get("params") if isinstance(payload, dict) else None
        result, errors, node_debug = self._generate_result_from_params(params)
        if errors:
            return (
                "overheadResult",
                self._with_bench(
                    payload,
                    {
                        "ok": False,
                        "module": "overhead",
                        "action": "overhead.generate",
                        "errors": errors,
                        "debug": node_debug,
                    },
                ),
            )

        return (
            "overheadResult",
            self._with_bench(
                payload,
                {
                    "ok": True,
                    "module": "overhead",
                    "action": "overhead.generate",
                    "result": result,
                    "debug": node_debug,
                },
            ),
        )
