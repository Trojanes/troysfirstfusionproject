import json
import os
import shutil
import subprocess


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


class KitchenController:
    def __init__(self, plugin_dir, fusion=None):
        self.plugin_dir = plugin_dir
        self.fusion = fusion

    def generate_geometry(self, payload, _palette):
        node_exe, checked_paths = _resolve_node_executable()
        node_debug = {
            "nodeResolution": {
                "resolvedNodePath": node_exe,
                "checkedPaths": checked_paths,
            }
        }
        params = payload.get("params") if isinstance(payload, dict) else None
        if not isinstance(params, dict):
            return (
                "kitchenGeometryResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.generateGeometry",
                    "errors": ["Missing Kitchen layout state payload."],
                    "debug": node_debug,
                },
            )
        if not node_exe:
            return (
                "kitchenGeometryResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.generateGeometry",
                    "errors": ["Node.js executable was not found. Install Node.js or set NODE_EXE to the full path of node.exe."],
                    "debug": node_debug,
                },
            )

        script = os.path.join(self.plugin_dir, "scripts", "kitchen_from_params.js")
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
                "kitchenGeometryResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.generateGeometry",
                    "errors": ["Kitchen geometry bridge failed: {}".format(ex)],
                    "debug": node_debug,
                },
            )

        raw_stdout = proc.stdout or ""
        try:
            bridge_result = json.loads(raw_stdout)
        except Exception as ex:
            return (
                "kitchenGeometryResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.generateGeometry",
                    "errors": ["Kitchen geometry bridge returned invalid JSON: {}".format(ex)],
                    "stderrPreview": (proc.stderr or "")[:500],
                    "stdoutPreview": raw_stdout[:500],
                    "debug": node_debug,
                },
            )

        if proc.returncode != 0 or not bridge_result.get("ok"):
            return (
                "kitchenGeometryResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.generateGeometry",
                    "errors": list(bridge_result.get("errors") or ["Kitchen geometry generation failed."]),
                    "stderrPreview": (proc.stderr or "")[:500],
                    "debug": node_debug,
                },
            )

        result = bridge_result.get("result")
        return (
            "kitchenGeometryResult",
            {
                "ok": True,
                "module": "kitchen",
                "action": "kitchen.generateGeometry",
                "result": result,
                "debug": node_debug,
            },
        )

    def create_fusion_preview(self, payload, _palette):
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.createFusionPreview",
                    "errors": ["Missing Kitchen geometry result payload."],
                },
            )
        if self.fusion is None:
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.createFusionPreview",
                    "errors": ["Fusion adapter is unavailable; reload the plugin and try again in an active Fusion design."],
                },
            )
        try:
            import importlib
            from modules.kitchen import fusion_adapter as kitchen_fusion_adapter

            adapter_module = importlib.reload(kitchen_fusion_adapter)
            run_label = payload.get("caseName") if isinstance(payload, dict) else None
            add_as_new = payload.get("addAsNewCabinet") is not False if isinstance(payload, dict) else True
            created = adapter_module.create_flat_panel_bodies_from_kitchen_result(
                self.fusion,
                result,
                run_label=run_label,
                add_as_new=add_as_new,
            )
            ok = len(created.get("errors") or []) == 0
            if ok and self.fusion:
                self.fusion.refresh_viewport()
            return (
                "kitchenFusionResult",
                {
                    "ok": ok,
                    "module": "kitchen",
                    "action": "kitchen.createFusionPreview",
                    "status": "READY" if ok else "FAIL",
                    "createdBodies": created.get("createdBodies", 0),
                    "createdPanelIds": created.get("createdPanelIds", []),
                    "skippedPanels": created.get("skippedPanels", []),
                    "cutouts": created.get("cutouts", []),
                    "warnings": created.get("warnings", []),
                    "errors": created.get("errors", []),
                    "runLabel": created.get("runLabel"),
                    "assemblyComponentName": created.get("assemblyComponentName"),
                    "adapterRevision": created.get("adapterRevision"),
                    "cutoutMode": created.get("cutoutMode", "all"),
                    "deletedPreviousKitchenArtifacts": created.get("deletedPreviousKitchenArtifacts", {}),
                    "addAsNewCabinet": created.get("addAsNewCabinet"),
                    "modelZOffset": created.get("modelZOffset"),
                },
            )
        except Exception as ex:
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.createFusionPreview",
                    "status": "FAIL",
                    "createdBodies": 0,
                    "errors": ["Kitchen Fusion preview failed: {}".format(ex)],
                },
            )

    def create_flat_body_preview(self, payload, _palette):
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.createFlatBodyPreview",
                    "errors": ["Missing Kitchen geometry result payload."],
                },
            )
        if self.fusion is None:
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.createFlatBodyPreview",
                    "errors": ["Fusion adapter is unavailable; reload the plugin and try again in an active Fusion design."],
                },
            )
        try:
            import importlib
            from modules.kitchen import fusion_adapter as kitchen_fusion_adapter

            adapter_module = importlib.reload(kitchen_fusion_adapter)
            run_label = payload.get("caseName") if isinstance(payload, dict) else None
            add_as_new = payload.get("addAsNewCabinet") is not False if isinstance(payload, dict) else True
            created = adapter_module.create_flat_panel_bodies_from_kitchen_result(self.fusion, result, run_label=run_label, add_as_new=add_as_new)
            ok = len(created.get("errors") or []) == 0
            if ok and self.fusion:
                self.fusion.refresh_viewport()
            return (
                "kitchenFusionResult",
                {
                    "ok": ok,
                    "module": "kitchen",
                    "action": "kitchen.createFlatBodyPreview",
                    "status": "READY" if ok else "FAIL",
                    "createdBodies": created.get("createdBodies", 0),
                    "createdPanelIds": created.get("createdPanelIds", []),
                    "skippedPanels": created.get("skippedPanels", []),
                    "cutouts": created.get("cutouts", []),
                    "warnings": created.get("warnings", []),
                    "errors": created.get("errors", []),
                    "runLabel": created.get("runLabel"),
                    "assemblyComponentName": created.get("assemblyComponentName"),
                    "adapterRevision": created.get("adapterRevision"),
                    "mode": created.get("mode"),
                    "cutoutMode": created.get("cutoutMode", "all"),
                    "deletedPreviousKitchenArtifacts": created.get("deletedPreviousKitchenArtifacts", {}),
                    "addAsNewCabinet": created.get("addAsNewCabinet"),
                    "modelZOffset": created.get("modelZOffset"),
                },
            )
        except Exception as ex:
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.createFlatBodyPreview",
                    "status": "FAIL",
                    "createdBodies": 0,
                    "errors": ["Kitchen flat body preview failed: {}".format(ex)],
                },
            )

    def create_flat_transform_preview(self, payload, _palette):
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.createFlatTransformPreview",
                    "errors": ["Missing Kitchen geometry result payload."],
                },
            )
        if self.fusion is None:
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.createFlatTransformPreview",
                    "errors": ["Fusion adapter is unavailable; reload the plugin and try again in an active Fusion design."],
                },
            )
        try:
            import importlib
            from modules.kitchen import fusion_adapter as kitchen_fusion_adapter

            adapter_module = importlib.reload(kitchen_fusion_adapter)
            run_label = payload.get("caseName") if isinstance(payload, dict) else None
            add_as_new = payload.get("addAsNewCabinet") is not False if isinstance(payload, dict) else True
            created = adapter_module.create_flat_transformed_panel_bodies_from_kitchen_result(self.fusion, result, run_label=run_label, add_as_new=add_as_new)
            ok = len(created.get("errors") or []) == 0
            if ok and self.fusion:
                self.fusion.refresh_viewport()
            return (
                "kitchenFusionResult",
                {
                    "ok": ok,
                    "module": "kitchen",
                    "action": "kitchen.createFlatTransformPreview",
                    "status": "READY" if ok else "FAIL",
                    "createdBodies": created.get("createdBodies", 0),
                    "createdPanelIds": created.get("createdPanelIds", []),
                    "skippedPanels": created.get("skippedPanels", []),
                    "cutouts": created.get("cutouts", []),
                    "warnings": created.get("warnings", []),
                    "errors": created.get("errors", []),
                    "runLabel": created.get("runLabel"),
                    "assemblyComponentName": created.get("assemblyComponentName"),
                    "adapterRevision": created.get("adapterRevision"),
                    "mode": created.get("mode"),
                    "cutoutMode": created.get("cutoutMode", "all"),
                    "deletedPreviousKitchenArtifacts": created.get("deletedPreviousKitchenArtifacts", {}),
                    "addAsNewCabinet": created.get("addAsNewCabinet"),
                    "modelZOffset": created.get("modelZOffset"),
                },
            )
        except Exception as ex:
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.createFlatTransformPreview",
                    "status": "FAIL",
                    "createdBodies": 0,
                    "errors": ["Kitchen flat transform preview failed: {}".format(ex)],
                },
            )
        if self.fusion is None:
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.createFlatBodyPreview",
                    "errors": ["Fusion adapter is unavailable; reload the plugin and try again in an active Fusion design."],
                },
            )
        try:
            import importlib
            from modules.kitchen import fusion_adapter as kitchen_fusion_adapter

            adapter_module = importlib.reload(kitchen_fusion_adapter)
            run_label = payload.get("caseName") if isinstance(payload, dict) else None
            add_as_new = payload.get("addAsNewCabinet") is not False if isinstance(payload, dict) else True
            created = adapter_module.create_flat_panel_bodies_from_kitchen_result(self.fusion, result, run_label=run_label, add_as_new=add_as_new)
            ok = len(created.get("errors") or []) == 0
            if ok and self.fusion:
                self.fusion.refresh_viewport()
            return (
                "kitchenFusionResult",
                {
                    "ok": ok,
                    "module": "kitchen",
                    "action": "kitchen.createFlatBodyPreview",
                    "status": "READY" if ok else "FAIL",
                    "createdBodies": created.get("createdBodies", 0),
                    "createdPanelIds": created.get("createdPanelIds", []),
                    "skippedPanels": created.get("skippedPanels", []),
                    "cutouts": created.get("cutouts", []),
                    "warnings": created.get("warnings", []),
                    "errors": created.get("errors", []),
                    "runLabel": created.get("runLabel"),
                    "assemblyComponentName": created.get("assemblyComponentName"),
                    "adapterRevision": created.get("adapterRevision"),
                    "mode": created.get("mode"),
                    "cutoutMode": created.get("cutoutMode", "all"),
                    "deletedPreviousKitchenArtifacts": created.get("deletedPreviousKitchenArtifacts", {}),
                    "addAsNewCabinet": created.get("addAsNewCabinet"),
                    "modelZOffset": created.get("modelZOffset"),
                },
            )
        except Exception as ex:
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.createFlatBodyPreview",
                    "status": "FAIL",
                    "createdBodies": 0,
                    "errors": ["Kitchen flat body preview failed: {}".format(ex)],
                },
            )
