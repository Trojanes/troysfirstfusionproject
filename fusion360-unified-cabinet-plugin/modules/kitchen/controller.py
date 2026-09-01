import json
import os
import shutil
import subprocess


def _naming_args(payload, fusion=None):
    """assemblyName / origin from a palette payload; origin falls back to the
    generation-zone centre when not explicitly provided."""
    data = payload if isinstance(payload, dict) else {}
    name = data.get("assemblyName")
    name = str(name).strip() if name else ""

    origin_x = origin_y = 0.0
    try:
        import work_zones

        root = fusion.get_root_component() if fusion is not None else None
        origin_x, origin_y = work_zones.resolve_origin_from_payload(data, root)
    except Exception:
        def _num(key):
            try:
                return float(data.get(key) or 0.0)
            except Exception:
                return 0.0

        origin_x, origin_y = _num("originXMm"), _num("originYMm")

    extra = {
        "component_name": name or None,
        "origin_x_mm": origin_x,
        "origin_y_mm": origin_y,
    }
    params = data.get("params")
    if isinstance(params, dict):
        extra["generator_params"] = params
    return extra


def _update_target_kwargs(payload, fusion=None):
    data = payload if isinstance(payload, dict) else {}
    target = data.get("target") if isinstance(data.get("target"), dict) else {}
    run_label = str(data.get("replaceRunLabel") or target.get("runLabel") or "").strip()
    origin = target.get("origin") if isinstance(target.get("origin"), dict) else {}
    kwargs = _naming_args(data, fusion)
    if run_label:
        kwargs["replace_run_label"] = run_label
        kwargs["avoid_existing_origin"] = False
    if origin:
        try:
            kwargs["origin_x_mm"] = float(origin.get("x") if origin.get("x") is not None else kwargs.get("origin_x_mm") or 0.0)
        except Exception:
            pass
        try:
            kwargs["origin_y_mm"] = float(origin.get("y") if origin.get("y") is not None else kwargs.get("origin_y_mm") or 0.0)
        except Exception:
            pass
        if origin.get("z") is not None:
            try:
                kwargs["origin_z_mm"] = float(origin.get("z"))
            except Exception:
                pass
    target_name = str(target.get("assemblyName") or "").strip()
    if target_name:
        kwargs["component_name"] = target_name
    return run_label, kwargs


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
                encoding="utf-8",
                errors="replace",
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
                **_naming_args(payload, self.fusion),
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
            created = adapter_module.create_flat_panel_bodies_from_kitchen_result(self.fusion, result, run_label=run_label, add_as_new=add_as_new, **_naming_args(payload, self.fusion))
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
            created = adapter_module.create_flat_transformed_panel_bodies_from_kitchen_result(self.fusion, result, run_label=run_label, add_as_new=add_as_new, **_naming_args(payload, self.fusion))
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
                    "placementDebug": created.get("placementDebug"),
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

    def update_target(self, payload, _palette):
        data = payload if isinstance(payload, dict) else {}
        run_label, kwargs = _update_target_kwargs(data, self.fusion)
        if not run_label:
            run_label = str((data.get("target") or {}).get("assemblyName") or kwargs.get("component_name") or "").strip()
            if run_label:
                kwargs["replace_run_label"] = run_label
                kwargs["avoid_existing_origin"] = False
        if not run_label:
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.updateTarget",
                    "errors": ["No target assembly runLabel. Load a selected kitchen first."],
                },
            )
        result = data.get("result")
        if not isinstance(result, dict):
            generated = self.generate_geometry(data, _palette)[1]
            if not generated.get("ok") or not isinstance(generated.get("result"), dict):
                return (
                    "kitchenFusionResult",
                    {
                        "ok": False,
                        "module": "kitchen",
                        "action": "kitchen.updateTarget",
                        "errors": generated.get("errors") or ["Kitchen geometry generation failed before update."],
                    },
                )
            result = generated.get("result")
        if self.fusion is None:
            return (
                "kitchenFusionResult",
                {
                    "ok": False,
                    "module": "kitchen",
                    "action": "kitchen.updateTarget",
                    "errors": ["Fusion adapter is unavailable; reload the plugin and try again in an active Fusion design."],
                },
            )
        try:
            import importlib
            from modules.kitchen import fusion_adapter as kitchen_fusion_adapter

            adapter_module = importlib.reload(kitchen_fusion_adapter)
            created = adapter_module.create_flat_transformed_panel_bodies_from_kitchen_result(
                self.fusion,
                result,
                run_label=run_label,
                add_as_new=True,
                **kwargs,
            )
            ok = len(created.get("errors") or []) == 0
            if ok and self.fusion:
                self.fusion.refresh_viewport()
            return (
                "kitchenFusionResult",
                {
                    "ok": ok,
                    "module": "kitchen",
                    "action": "kitchen.updateTarget",
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
                    "deletedTarget": created.get("deletedTarget"),
                    "replacedRunLabel": created.get("replacedRunLabel"),
                    "generatorParamsStored": created.get("generatorParamsStored"),
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
                    "action": "kitchen.updateTarget",
                    "status": "FAIL",
                    "createdBodies": 0,
                    "errors": ["Kitchen update target failed: {}".format(ex)],
                },
            )
