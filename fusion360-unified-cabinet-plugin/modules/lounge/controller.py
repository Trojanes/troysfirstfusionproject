import json
import os
import shutil
import subprocess


def _naming_args(payload, fusion=None):
    """assemblyName / origin from palette payload.

    Lounge placement coords start at cabinet corner (0,0), so auto origin uses
    the generation-zone min corner (x0, y0). Other modules keep zone centre.
    """
    data = payload if isinstance(payload, dict) else {}
    name = data.get("assemblyName")
    name = str(name).strip() if name else ""

    has_explicit = data.get("originXMm") is not None or data.get("originYMm") is not None
    try:
        import work_zones

        root = fusion.get_root_component() if fusion is not None else None
        if not has_explicit:
            origin = work_zones.generation_zone_origin_mm(root)
            if origin:
                return {
                    "component_name": name or None,
                    "origin_x_mm": origin[0],
                    "origin_y_mm": origin[1],
                }
        origin_x, origin_y = work_zones.resolve_origin_from_payload(data, root)
        if has_explicit:
            center = work_zones.generation_zone_center_mm(root)
            corner = work_zones.generation_zone_origin_mm(root)
            if center and corner:
                if abs(origin_x - center[0]) < 1.0 and abs(origin_y - center[1]) < 1.0:
                    origin_x, origin_y = corner
    except Exception:
        def _num(key):
            try:
                return float(data.get(key) or 0.0)
            except Exception:
                return 0.0

        origin_x, origin_y = _num("originXMm"), _num("originYMm")

    return {
        "component_name": name or None,
        "origin_x_mm": origin_x,
        "origin_y_mm": origin_y,
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
    candidates.extend([
        ("common", r"C:\Program Files\nodejs\node.exe"),
        ("common", r"C:\Program Files (x86)\nodejs\node.exe"),
        ("common", os.path.expandvars(r"%LOCALAPPDATA%\Programs\nodejs\node.exe")),
    ])
    return candidates


def _resolve_node_executable():
    checked = []
    for source, path in _candidate_node_paths():
        checked.append({"source": source, "path": path, "exists": os.path.isfile(path)})
        if os.path.isfile(path):
            return path, checked
    return None, checked


class LoungeController:
    def __init__(self, plugin_dir, fusion=None):
        self.plugin_dir = plugin_dir
        self.fusion = fusion

    def generate_geometry(self, payload, _palette):
        node_exe, checked_paths = _resolve_node_executable()
        params = payload.get("params") if isinstance(payload, dict) else None
        node_debug = {"nodeResolution": {"resolvedNodePath": node_exe, "checkedPaths": checked_paths}}
        if not isinstance(params, dict):
            return ("loungeGeometryResult", {
                "ok": False,
                "module": "lounge",
                "action": "lounge.generateGeometry",
                "errors": ["Missing Lounge params payload."],
                "debug": node_debug,
            })
        if not node_exe:
            return ("loungeGeometryResult", {
                "ok": False,
                "module": "lounge",
                "action": "lounge.generateGeometry",
                "errors": ["Node.js executable was not found."],
                "debug": node_debug,
            })
        script = os.path.join(self.plugin_dir, "scripts", "lounge_from_params.js")
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
            return ("loungeGeometryResult", {
                "ok": False,
                "module": "lounge",
                "action": "lounge.generateGeometry",
                "errors": ["Lounge generation bridge failed: {}".format(ex)],
                "debug": node_debug,
            })
        raw_stdout = proc.stdout or ""
        try:
            bridge_result = json.loads(raw_stdout)
        except Exception as ex:
            return ("loungeGeometryResult", {
                "ok": False,
                "module": "lounge",
                "action": "lounge.generateGeometry",
                "errors": ["Lounge bridge returned invalid JSON: {}".format(ex)],
                "stderrPreview": (proc.stderr or "")[:500],
                "stdoutPreview": raw_stdout[:500],
                "debug": node_debug,
            })
        if proc.returncode != 0 or not bridge_result.get("ok"):
            return ("loungeGeometryResult", {
                "ok": False,
                "module": "lounge",
                "action": "lounge.generateGeometry",
                "errors": list(bridge_result.get("errors") or ["Lounge generation failed."]),
                "stderrPreview": (proc.stderr or "")[:500],
                "debug": node_debug,
            })
        return ("loungeGeometryResult", {
            "ok": True,
            "module": "lounge",
            "action": "lounge.generateGeometry",
            "result": bridge_result.get("result"),
            "debug": node_debug,
        })

    def create_flat_bodies(self, payload, _palette):
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            return ("loungeFlatBodyResult", {
                "ok": False,
                "module": "lounge",
                "action": "lounge.createFlatBodies",
                "errors": ["Missing Lounge geometry result payload."],
            })
        if self.fusion is None:
            return ("loungeFlatBodyResult", {
                "ok": False,
                "module": "lounge",
                "action": "lounge.createFlatBodies",
                "errors": ["Fusion adapter is not available."],
            })
        run_label = payload.get("runLabel") if isinstance(payload, dict) else None
        # Fusion keeps imported modules cached; purge+restart can drop fusion_adapter
        # from sys.modules while this controller still holds a stale binding. Re-import
        # then reload so adapter edits always take effect.
        import importlib

        adapter_module = importlib.reload(importlib.import_module("modules.lounge.fusion_adapter"))
        summary = adapter_module.create_lounge_bodies(self.fusion, result, run_label=run_label, **_naming_args(payload, self.fusion))
        summary["ok"] = len(summary.get("errors") or []) == 0
        summary["action"] = "lounge.createFlatBodies"
        return ("loungeFlatBodyResult", summary)

    def create_assembly_bodies(self, payload, _palette):
        result = payload.get("result") if isinstance(payload, dict) else None
        if not isinstance(result, dict):
            return ("loungeAssemblyBodyResult", {
                "ok": False,
                "module": "lounge",
                "action": "lounge.createAssemblyBodies",
                "errors": ["Missing Lounge geometry result payload."],
            })
        if self.fusion is None:
            return ("loungeAssemblyBodyResult", {
                "ok": False,
                "module": "lounge",
                "action": "lounge.createAssemblyBodies",
                "errors": ["Fusion adapter is not available."],
            })
        run_label = payload.get("runLabel") if isinstance(payload, dict) else None
        import importlib

        adapter_module = importlib.reload(importlib.import_module("modules.lounge.fusion_adapter"))
        summary = adapter_module.create_lounge_assembly_bodies(self.fusion, result, run_label=run_label, **_naming_args(payload, self.fusion))
        summary["ok"] = len(summary.get("errors") or []) == 0
        summary["action"] = "lounge.createAssemblyBodies"
        return ("loungeAssemblyBodyResult", summary)
