import importlib
import json
import os
import shutil
import subprocess

from modules.general_tall import fusion_adapter as board_fusion_adapter


def _resolve_node():
    candidates = [
        os.environ.get("NODE_EXE"),
        shutil.which("node"),
        r"C:\Program Files\nodejs\node.exe",
        r"C:\Program Files (x86)\nodejs\node.exe",
    ]
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


def _node_strip_types_args(node_exe):
    """Return the flag required by Node versions that gate native TypeScript."""
    try:
        version = subprocess.run(
            [node_exe, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip().lstrip("v")
        parts = version.split(".")
        major, minor = int(parts[0]), int(parts[1])
    except Exception:
        return None, "Unable to determine the Node.js version."
    if major < 22 or (major == 22 and minor < 6):
        return None, (
            "U Shape OHC requires Node.js 22.6+ because its bridge imports TypeScript (.ts) files; "
            "found v{}.".format(version)
        )
    # Node 22.6–22.17 supports TypeScript only behind this flag.  Node 22.18+
    # strips types by default, so avoid the deprecated flag and its warning.
    return (["--experimental-strip-types"] if major == 22 and minor < 18 else []), None


def _bridge_error(prefix, stderr):
    detail = (stderr or "").strip()
    if not detail:
        return [prefix]
    # Keep Fusion palette messages useful without flooding it with a full Node stack.
    return [prefix, "Node stderr: {}".format(detail[-2000:])]


class UShapeOverheadController:
    def __init__(self, plugin_dir, fusion=None):
        self.plugin_dir = plugin_dir
        self.fusion = fusion

    def _generate(self, params):
        if not isinstance(params, dict):
            return None, ["Missing U Shape OHC params payload."]
        node_exe = _resolve_node()
        if not node_exe:
            return None, ["Node.js executable was not found."]
        script = os.path.join(self.plugin_dir, "scripts", "u_shape_overhead_from_params.js")
        node_args, node_error = _node_strip_types_args(node_exe)
        if node_error:
            return None, [node_error]
        try:
            proc = subprocess.run(
                [node_exe] + node_args + [script],
                cwd=self.plugin_dir,
                input=json.dumps({"params": params}, ensure_ascii=False),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except Exception as ex:
            return None, ["U Shape OHC bridge failed: {}".format(ex)]
        stdout = (proc.stdout or "").strip()
        stderr = (proc.stderr or "").strip()
        try:
            response = json.loads(stdout) if stdout else {}
        except ValueError:
            return None, _bridge_error(
                "U Shape OHC bridge returned invalid JSON (exit code {}).".format(proc.returncode),
                stderr,
            )
        if proc.returncode != 0 or not response.get("ok"):
            errors = list(response.get("errors") or ["U Shape OHC generation failed."])
            if stderr:
                errors.extend(_bridge_error("", stderr)[1:])
            return None, errors
        result = response.get("result")
        if not isinstance(result, dict):
            return None, ["U Shape OHC bridge returned no result."]
        return result, []

    def generate(self, payload, _palette):
        params = payload.get("params") if isinstance(payload, dict) else None
        result, errors = self._generate(params)
        return (
            "uShapeOverheadResult",
            {
                "ok": not errors,
                "module": "u_shape_overhead",
                "action": "uShapeOverhead.generate",
                "result": result,
                "errors": errors,
            },
        )

    def create_fusion_bodies(self, payload, _palette):
        params = payload.get("params") if isinstance(payload, dict) else None
        result, errors = self._generate(params)
        if errors or not isinstance(result, dict):
            return (
                "uShapeOverheadFusionResult",
                {
                    "ok": False,
                    "module": "u_shape_overhead",
                    "action": "uShapeOverhead.createFusionBodies",
                    "errors": errors or ["Missing generated result."],
                },
            )
        validation = result.get("validation") if isinstance(result.get("validation"), dict) else {}
        validation_errors = list(validation.get("errors") or [])
        if validation_errors:
            return (
                "uShapeOverheadFusionResult",
                {
                    "ok": False,
                    "module": "u_shape_overhead",
                    "action": "uShapeOverhead.createFusionBodies",
                    "errors": validation_errors,
                },
            )
        if self.fusion is None:
            return (
                "uShapeOverheadFusionResult",
                {
                    "ok": False,
                    "module": "u_shape_overhead",
                    "action": "uShapeOverhead.createFusionBodies",
                    "errors": ["Fusion adapter is unavailable."],
                },
            )
        adapter = importlib.reload(board_fusion_adapter)
        summary = adapter.create_u_shape_overhead_assembly(
            self.fusion,
            result,
            run_label=str(payload.get("caseName") or "UOHC"),
            component_name=str(payload.get("assemblyName") or "U Shape OHC"),
            origin_x_mm=payload.get("originXMm"),
            origin_y_mm=payload.get("originYMm"),
        )
        ok = not summary.get("errors")
        if ok:
            self.fusion.refresh_viewport()
        return (
            "uShapeOverheadFusionResult",
            {
                "ok": ok,
                "module": "u_shape_overhead",
                "action": "uShapeOverhead.createFusionBodies",
                **summary,
            },
        )

    def run_self_check(self, payload, _palette):
        """Measure existing U assemblies (or create+measure) and write Fusion log."""
        if self.fusion is None:
            return (
                "uShapeOverheadSelfCheckResult",
                {
                    "ok": False,
                    "module": "u_shape_overhead",
                    "action": "uShapeOverhead.runSelfCheck",
                    "errors": ["Fusion adapter is unavailable."],
                },
            )
        adapter = importlib.reload(board_fusion_adapter)
        payload = payload if isinstance(payload, dict) else {}
        create_first = bool(payload.get("createFirst") or payload.get("createAndMeasure"))
        created = None
        if create_first:
            _, created = self.create_fusion_bodies(payload, _palette)
            if not created.get("ok"):
                return (
                    "uShapeOverheadSelfCheckResult",
                    {
                        "ok": False,
                        "module": "u_shape_overhead",
                        "action": "uShapeOverhead.runSelfCheck",
                        "errors": created.get("errors") or ["createFusionBodies failed before measure."],
                        "created": created,
                    },
                )
        root = self.fusion.get_root_component()

        def _result_from_params(params):
            generated, gen_errors = self._generate(params)
            if gen_errors or not isinstance(generated, dict):
                return None
            return generated

        # Prefer freshly generated expected poses from current UI params, else
        # regenerate from each assembly's stored uShapeParams attribute.
        preferred_result = None
        params = payload.get("params") if isinstance(payload.get("params"), dict) else None
        if params:
            preferred_result = _result_from_params(params)

        report = adapter.measure_and_log_u_shape_assemblies(
            root,
            source="runSelfCheck",
            plugin_dir=self.plugin_dir,
            expected_result=preferred_result,
            result_by_params=_result_from_params,
        )
        if not report.get("cases"):
            report["ok"] = False
            report.setdefault("errors", []).append(
                "No U Shape OHC assemblies found. Create bodies first, then click 自检."
            )
        return (
            "uShapeOverheadSelfCheckResult",
            {
                "ok": bool(report.get("ok")),
                "module": "u_shape_overhead",
                "action": "uShapeOverhead.runSelfCheck",
                "created": created,
                **report,
            },
        )
