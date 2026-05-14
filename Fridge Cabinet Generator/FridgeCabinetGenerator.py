import adsk.core
import importlib
import json
import os
import random
import shutil
import subprocess
import sys
import time
import traceback


_app = None

# Palette → Python contract (Generate):
#   { "type": "generateFridgeCabinet", "runId", "diagnosticsOnly", "params": <pureParams>,
#     "boardPlan"?: <from JS>, "vVerify"?: <from JS> }
#   When boardPlan is omitted, Python falls back to the Node bridge (if Node is available).
GENERATE_PAYLOAD_TYPE = "generateFridgeCabinet"


def _fcg_debug_log(message):
    """Temporary debug: Text Commands / stdout + Fusion log if available."""
    text = "[FridgeCabinetGenerator] " + str(message)
    try:
        print(text)
    except Exception:
        pass
    try:
        app = adsk.core.Application.get()
        log_fn = getattr(app, "log", None) if app else None
        if callable(log_fn):
            log_fn("FridgeCabinetGenerator", str(message)[:3500])
    except Exception:
        pass


def _action_string(html_args):
    a = getattr(html_args, "action", None)
    if isinstance(a, str):
        return a.strip()
    if a is None:
        return ""
    return str(a).strip()


def _iso_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_run_id():
    return "{}-{}".format(int(time.time() * 1000), random.randint(10000, 99999))


def _html_data_length(data_attr):
    try:
        if data_attr is None:
            return 0
        if isinstance(data_attr, str):
            return len(data_attr)
        if isinstance(data_attr, dict):
            return len(json.dumps(data_attr, ensure_ascii=False))
        return len(repr(data_attr))
    except Exception:
        return -1


def _data_preview_for_debug(data_attr, limit=500):
    try:
        if isinstance(data_attr, str):
            s = data_attr
            return (s[:limit] + "...") if len(s) > limit else s
        if isinstance(data_attr, dict):
            return json.dumps(data_attr, ensure_ascii=False)[:limit]
        return repr(data_attr)[:limit]
    except Exception:
        return "?"


def _dict_from_html_data_attr(data_attr):
    """Fusion may pass html_args.data as a JSON string or an already-parsed dict."""
    if data_attr is None:
        return None
    if isinstance(data_attr, dict):
        return dict(data_attr)
    if isinstance(data_attr, str):
        s = data_attr.strip().lstrip("\ufeff")
        if not s:
            return None
        try:
            val = json.loads(s)
            return val if isinstance(val, dict) else None
        except Exception:
            return None
    return None


def _parse_generate_payload_from_html_args(html_args):
    """
    Returns (payload_dict | None, debug_dict).
    Supports:
      - html_args.action == 'generateFridgeCabinet' and data is JSON string or dict body
      - html_args.action == 'response' and data is JSON string (or dict) with type + params
    """
    action_str = _action_string(html_args)
    data_attr = getattr(html_args, "data", None)
    debug = {
        "html_action": action_str,
        "html_data_type": type(data_attr).__name__,
        "html_data_preview": _data_preview_for_debug(data_attr, 500),
    }

    # Path A: action-based routing (palette sends fusionSendData("generateFridgeCabinet", payloadJson))
    if action_str == GENERATE_PAYLOAD_TYPE:
        obj = _dict_from_html_data_attr(data_attr)
        if isinstance(obj, dict) and obj.get("type") == GENERATE_PAYLOAD_TYPE:
            debug["payload_keys"] = sorted(obj.keys())
            debug["payload_type"] = obj.get("type")
            return obj, debug
        debug["path_a_note"] = "action matched but data did not yield a valid generateFridgeCabinet payload dict"
        return None, debug

    # Path B: legacy response + JSON envelope in data (string or dict)
    obj = _dict_from_html_data_attr(data_attr)
    if obj is None:
        if isinstance(data_attr, str) and not data_attr.strip():
            debug["note"] = "empty_data_string"
        return None, debug

    if not isinstance(obj, dict):
        debug["parsed_type"] = type(obj).__name__
        return None, debug

    obj = _unwrap_nested_json_payload(obj)
    if not isinstance(obj, dict):
        return None, debug
    debug["payload_keys"] = sorted(obj.keys())
    debug["payload_type"] = obj.get("type")
    return obj, debug


def _unwrap_nested_json_payload(obj, max_depth=5):
    """If Fusion wraps the palette JSON (e.g. { action, data: '<string>' }), unwrap to inner dict."""
    cur = obj
    for _ in range(max_depth):
        if not isinstance(cur, dict):
            return cur
        if cur.get("type") == GENERATE_PAYLOAD_TYPE:
            return cur
        inner = cur.get("data")
        if isinstance(inner, str):
            s = inner.strip().lstrip("\ufeff")
            if s.startswith("{") or s.startswith("["):
                try:
                    cur = json.loads(s)
                    continue
                except Exception:
                    return cur
        if isinstance(inner, dict):
            cur = inner
            continue
        return cur
    return cur


def _run_board_plan_bridge(plugin_dir, pure_params):
    """
    Run Node + fridge_logic.js to obtain boardPlan and verifyVSeriesVectors (single source of truth).

    Returns (data_dict | None, error_message | None, meta_dict).
    meta_dict always describes the bridge attempt (for diagnostics).
    """
    meta = {
        "nodeExecutableFound": False,
        "nodePath": None,
        "nodeExitCode": None,
        "boardPlanParsed": False,
        "boardCount": 0,
        "boardPlanValidationOk": None,
        "stderrPreview": "",
        "stdoutPreview": "",
    }
    script = os.path.join(plugin_dir, "scripts", "boardplan_from_pureparams.js")
    if not os.path.isfile(script):
        return None, "Bridge script not found: {}".format(script), meta
    node_exe = shutil.which("node")
    meta["nodeExecutableFound"] = node_exe is not None
    meta["nodePath"] = node_exe
    if not node_exe:
        return None, "Node.js is required for v0.1 boardPlan generation but was not found in PATH.", meta
    try:
        proc = subprocess.run(
            [node_exe, script],
            cwd=plugin_dir,
            input=json.dumps(pure_params, ensure_ascii=False),
            capture_output=True,
            text=True,
            timeout=120,
        )
    except FileNotFoundError:
        return None, "Node.js is required for v0.1 boardPlan generation but was not found in PATH.", meta
    except Exception as ex:
        return None, "BoardPlan bridge failed: {}".format(ex), meta
    meta["nodeExitCode"] = proc.returncode
    stderr = proc.stderr if proc.stderr is not None else ""
    meta["stderrPreview"] = stderr[:300] if stderr else ""
    raw_stdout = proc.stdout if proc.stdout is not None else ""
    meta["stdoutPreview"] = raw_stdout[:300] if raw_stdout else ""
    if proc.returncode != 0:
        stdout = raw_stdout
        out_head = stdout[:1000] if stdout else ""
        msg = (
            "Node bridge exited with code {code}. stderr: {err!r}. "
            "stdout (first 1000 chars): {out!r}"
        ).format(code=proc.returncode, err=stderr, out=out_head)
        return None, msg, meta
    try:
        data = json.loads(raw_stdout)
        meta["boardPlanParsed"] = isinstance(data, dict)
        if isinstance(data, dict):
            bp = data.get("boardPlan")
            if isinstance(bp, dict) and isinstance(bp.get("boards"), list):
                meta["boardCount"] = len(bp["boards"])
                meta["boardPlanValidationOk"] = _validation_ok_tri_state(bp.get("validation"))
        return data, None, meta
    except Exception as ex:
        head = raw_stdout[:1000]
        return None, "Node bridge JSON parse failed: {ex!r}. Raw stdout (first 1000 chars): {raw!r}".format(
            ex=ex,
            raw=head,
        ), meta


def _validation_ok(validation):
    return isinstance(validation, dict) and validation.get("ok") is True


def _validation_ok_tri_state(validation):
    """True / False if validation dict present; None if missing or not a dict."""
    if not isinstance(validation, dict) or "ok" not in validation:
        return None
    return True if validation.get("ok") is True else False


class FridgeCabinetGeneratorApp:
    CMD_ID = "fridgeCabinetGeneratorCommand"
    CMD_NAME = "Fridge Cabinet Generator"
    CMD_DESC = "Open the fridge cabinet stack layout editor."
    CONTROL_ID = "fridgeCabinetGeneratorControl"
    PANEL_ID = "fridgeCabinetGeneratorPanel"
    PANEL_NAME = "Fridge Cabinet Generator"
    FALLBACK_PANEL_ID = "SolidScriptsAddinsPanel"
    PALETTE_ID = "fridgeCabinetGeneratorPalette"
    PALETTE_NAME = "Fridge Cabinet Generator"

    def __init__(self, plugin_dir=None):
        self.plugin_dir = plugin_dir or os.path.dirname(os.path.abspath(__file__))
        self.handlers = []
        self.command_definition = None
        self.control = None
        self.panel = None
        self.palette = None
        # Last 10 incoming HTMLEvent actions (debug; Fusion may send "response" callbacks separately from Generate).
        self._html_event_log = []

    def _record_incoming_html_event(self, html_args, action_str, raw_data):
        """Append a lightweight row to the ring buffer (max 10)."""
        try:
            entry = {
                "action": action_str,
                "dataType": type(raw_data).__name__,
                "dataPreview": _data_preview_for_debug(raw_data, 160),
                "timestamp": _iso_now(),
            }
            self._html_event_log.append(entry)
            if len(self._html_event_log) > 10:
                self._html_event_log[:] = self._html_event_log[-10:]
        except Exception:
            pass

    def _last_html_events_snapshot(self):
        return list(self._html_event_log)

    def _attach_last_html_events(self, result):
        if isinstance(result, dict):
            result["lastHtmlEvents"] = self._last_html_events_snapshot()

    def start(self):
        app = adsk.core.Application.get()
        ui = app.userInterface if app else None
        if not ui:
            return

        cmd_defs = ui.commandDefinitions
        self.command_definition = cmd_defs.itemById(self.CMD_ID)
        if not self.command_definition:
            self.command_definition = cmd_defs.addButtonDefinition(
                self.CMD_ID,
                self.CMD_NAME,
                self.CMD_DESC,
                "",
            )

        on_created = _CommandCreatedHandler(self)
        self.command_definition.commandCreated.add(on_created)
        self.handlers.append(on_created)

        workspace = ui.workspaces.itemById("FusionSolidEnvironment")
        self.panel = workspace.toolbarPanels.itemById(self.PANEL_ID) if workspace else None
        if not self.panel and workspace:
            self.panel = workspace.toolbarPanels.add(
                self.PANEL_ID,
                self.PANEL_NAME,
                self.FALLBACK_PANEL_ID,
                False,
            )
        if self.panel:
            old_control = self.panel.controls.itemById(self.CONTROL_ID)
            if old_control:
                old_control.deleteMe()
            self.control = self.panel.controls.addCommand(self.command_definition, self.CONTROL_ID)
            self.control.isVisible = True
            self.control.isPromoted = True
            self.control.isPromotedByDefault = True

        self.show_palette()

    def stop(self):
        app = adsk.core.Application.get()
        ui = app.userInterface if app else None
        try:
            if self.control:
                self.control.deleteMe()
                self.control = None
            if self.panel:
                self.panel.deleteMe()
                self.panel = None
            if self.palette:
                try:
                    self.palette.isVisible = False
                    self.palette.deleteMe()
                except RuntimeError:
                    # Some Fusion palette instances cannot be deleted during
                    # add-in shutdown; hiding them is enough for this UI-only prototype.
                    pass
                self.palette = None
            if self.command_definition:
                self.command_definition.deleteMe()
                self.command_definition = None
            self.handlers.clear()
        except:
            if ui:
                ui.messageBox("Fridge Cabinet Generator stop failed:\n{}".format(traceback.format_exc()))

    def show_palette(self):
        app = adsk.core.Application.get()
        ui = app.userInterface if app else None
        if not ui:
            return
        palettes = ui.palettes
        self.palette = palettes.itemById(self.PALETTE_ID)
        if not self.palette:
            html_path = os.path.join(os.path.dirname(__file__), "palette.html")
            self.palette = palettes.add(
                self.PALETTE_ID,
                self.PALETTE_NAME,
                "file:///" + os.path.abspath(html_path).replace("\\", "/"),
                True,
                True,
                True,
                1500,
                1050,
                False,
            )
            incoming = _PaletteIncomingHandler(self)
            self.palette.incomingFromHTML.add(incoming)
            self.handlers.append(incoming)
        self.palette.isVisible = True

    def _send_generate_client_error(self, message, dbg, diagnostics, failed_step="python_extract_pureParams"):
        """Send fridgeCabinetResult when generate payload parsing fails; includes merged diagnostics."""
        if not self.palette:
            return
        if isinstance(diagnostics, dict):
            diagnostics["pythonFinishedAt"] = _iso_now()
        rid = diagnostics.get("runId") if isinstance(diagnostics, dict) else _new_run_id()
        result = {
            "finalStatus": "fail",
            "failedStep": failed_step,
            "generateRunId": rid,
            "diagnostics": diagnostics,
            "pureParamsValidationOk": None,
            "boardPlanValidationOk": None,
            "vVerifyOk": None,
            "createdBodies": 0,
            "skippedBoards": [],
            "errors": [message],
            "warnings": [],
            "generateDebug": dbg,
        }
        self._attach_last_html_events(result)
        try:
            self.palette.sendInfoToHTML("fridgeCabinetResult", json.dumps(result, ensure_ascii=False))
        except Exception:
            pass

    def handle_html_event(self, html_args):
        html_args.returnData = ""
        raw_data = getattr(html_args, "data", None)
        action_str = _action_string(html_args)
        self._record_incoming_html_event(html_args, action_str, raw_data)

        # Fusion host / sendInfoToHTML callback noise — never treat as Generate failure.
        if action_str == "response":
            return
        if action_str == "" or action_str.lower() == "undefined":
            return

        if action_str == "pingPython":
            if self.palette:
                result = {
                    "receivedAction": html_args.action,
                    "receivedData": html_args.data,
                    "receivedDataType": type(html_args.data).__name__,
                    "pythonBuild": "python-ping-debug-001",
                    "jsBuild": "js-ping-debug-001",
                }
                self.palette.sendInfoToHTML("pythonPong", json.dumps(result, ensure_ascii=False))
            return

        parsed_early = None
        json_parse_error = None
        if isinstance(raw_data, str) and raw_data.strip():
            try:
                parsed_early = json.loads(raw_data.strip().lstrip("\ufeff"))
            except Exception as ex:
                json_parse_error = repr(ex)
                parsed_early = None
        elif isinstance(raw_data, dict):
            parsed_early = dict(raw_data)

        run_id = None
        if isinstance(parsed_early, dict):
            run_id = parsed_early.get("runId")

        diagnostics = {
            "runId": str(run_id) if run_id else _new_run_id(),
            "pythonSteps": [],
            "pythonStartedAt": _iso_now(),
        }

        step5_details = {
            "html_action": action_str,
            "html_data_type": type(raw_data).__name__,
            "html_data_length": _html_data_length(raw_data),
            "html_data_preview": _data_preview_for_debug(raw_data, 300),
        }

        if action_str != GENERATE_PAYLOAD_TYPE:
            diagnostics["pythonSteps"].append(
                {
                    "id": "python_received_event",
                    "side": "Python",
                    "status": "fail",
                    "summary": "Expected action generateFridgeCabinet, received {!r}".format(action_str),
                    "details": step5_details,
                }
            )
            self._send_fridge_result(
                {
                    "finalStatus": "fail",
                    "failedStep": "python_received_event",
                    "generateRunId": diagnostics["runId"],
                    "diagnostics": diagnostics,
                    "pureParamsValidationOk": None,
                    "boardPlanValidationOk": None,
                    "vVerifyOk": None,
                    "createdBodies": 0,
                    "skippedBoards": [],
                    "errors": [
                        "Unexpected html_args.action: {!r} (expected generateFridgeCabinet).".format(
                            action_str
                        )
                    ],
                    "warnings": [],
                }
            )
            return

        diagnostics["pythonSteps"].append(
            {
                "id": "python_received_event",
                "side": "Python",
                "status": "pass",
                "summary": "action is generateFridgeCabinet",
                "details": step5_details,
            }
        )

        dbg = {
            "html_action": getattr(html_args, "action", None),
            "html_data_type": type(raw_data).__name__,
            "html_data_preview": _data_preview_for_debug(raw_data, 300),
            "parsed_keys": None,
            "found_params": False,
        }
        parsed = parsed_early if isinstance(parsed_early, dict) else None
        if parsed is None:
            dbg["json_error"] = json_parse_error or "parse_failed_or_empty"
            diagnostics["pythonSteps"].append(
                {
                    "id": "python_extract_pureParams",
                    "side": "Python",
                    "status": "fail",
                    "summary": "Could not parse html_args.data as JSON object",
                    "details": {
                        "parsedOk": False,
                        "parsedKeys": None,
                        "foundParams": False,
                        "paramsValidationOk": None,
                        "note": dbg.get("json_error"),
                    },
                }
            )
            self._send_generate_client_error(
                "generateFridgeCabinet: invalid or empty JSON in data",
                dbg,
                diagnostics,
                failed_step="python_extract_pureParams",
            )
            return

        dbg["parsed_keys"] = sorted(parsed.keys())
        pure_params = None
        if "params" in parsed:
            pure_params = parsed["params"]
            dbg["found_params"] = isinstance(pure_params, dict)
        elif "validation" in parsed and "layout" in parsed:
            pure_params = parsed
            dbg["found_params"] = True
        else:
            diagnostics["pythonSteps"].append(
                {
                    "id": "python_extract_pureParams",
                    "side": "Python",
                    "status": "fail",
                    "summary": "params key missing and body is not PureParams shape",
                    "details": {
                        "parsedOk": True,
                        "parsedKeys": dbg["parsed_keys"],
                        "foundParams": False,
                        "paramsValidationOk": None,
                    },
                }
            )
            self._send_generate_client_error(
                "generateFridgeCabinet received but params not found",
                dbg,
                diagnostics,
                failed_step="python_extract_pureParams",
            )
            return

        if not isinstance(pure_params, dict):
            dbg["found_params"] = False
            diagnostics["pythonSteps"].append(
                {
                    "id": "python_extract_pureParams",
                    "side": "Python",
                    "status": "fail",
                    "summary": "params is not an object",
                    "details": {
                        "parsedOk": True,
                        "parsedKeys": dbg["parsed_keys"],
                        "foundParams": False,
                        "paramsValidationOk": None,
                    },
                }
            )
            self._send_generate_client_error(
                "generateFridgeCabinet: params is not an object",
                dbg,
                diagnostics,
                failed_step="python_extract_pureParams",
            )
            return

        pv_ok = _validation_ok_tri_state(pure_params.get("validation"))
        diagnostics["pythonSteps"].append(
            {
                "id": "python_extract_pureParams",
                "side": "Python",
                "status": "pass",
                "summary": "extracted params; validation.ok = {}".format(pv_ok),
                "details": {
                    "parsedOk": True,
                    "parsedKeys": dbg["parsed_keys"],
                    "foundParams": True,
                    "paramsValidationOk": pv_ok,
                    "runIdFromPayload": parsed.get("runId"),
                },
            }
        )

        diagnostics_only = bool(parsed.get("diagnosticsOnly", True))

        received_board_plan = parsed.get("boardPlan") if isinstance(parsed, dict) else None
        received_v_verify = parsed.get("vVerify") if isinstance(parsed, dict) else None
        if not isinstance(received_board_plan, dict):
            received_board_plan = None
        if not isinstance(received_v_verify, dict):
            received_v_verify = None

        self._handle_generate_fridge_cabinet(
            pure_params,
            diagnostics,
            diagnostics_only,
            received_board_plan=received_board_plan,
            received_v_verify=received_v_verify,
        )

    def _send_fridge_result(self, result):
        if not self.palette:
            return
        d = result.get("diagnostics")
        if isinstance(d, dict):
            d["pythonFinishedAt"] = _iso_now()
        self._attach_last_html_events(result)
        try:
            self.palette.sendInfoToHTML("fridgeCabinetResult", json.dumps(result, ensure_ascii=False))
        except Exception:
            pass
        try:
            app = adsk.core.Application.get()
            log_fn = getattr(app, "log", None) if app else None
            if callable(log_fn):
                log_fn("FridgeCabinetGenerator", json.dumps(result, ensure_ascii=False)[:3000])
        except Exception:
            pass

    def _handle_generate_fridge_cabinet(
        self,
        pure_params,
        diagnostics,
        diagnostics_only=True,
        received_board_plan=None,
        received_v_verify=None,
    ):
        rid = diagnostics.get("runId") if isinstance(diagnostics, dict) else _new_run_id()
        result = {
            "finalStatus": "fail",
            "failedStep": None,
            "generateRunId": rid,
            "diagnostics": diagnostics,
            "diagnosticsOnly": diagnostics_only,
            "pureParamsValidationOk": _validation_ok_tri_state(pure_params.get("validation")),
            "boardPlanValidationOk": None,
            "vVerifyOk": None,
            "createdBodies": 0,
            "skippedBoards": [],
            "errors": [],
            "warnings": [],
        }

        v_verify_source = None
        data = None
        err = None
        bridge_meta = {}

        if isinstance(received_board_plan, dict) and received_board_plan:
            boards = received_board_plan.get("boards")
            board_count = len(boards) if isinstance(boards, list) else 0
            bp_val_ok = _validation_ok_tri_state(received_board_plan.get("validation"))
            diagnostics["pythonSteps"].append(
                {
                    "id": "python_build_boardPlan",
                    "side": "Python",
                    "status": "pass",
                    "summary": "Using boardPlan received from JS; Node bridge skipped",
                    "details": {
                        "source": "js_payload",
                        "boardCount": board_count,
                        "boardPlanValidationOk": bp_val_ok,
                        "nodeBridgeSkipped": True,
                    },
                }
            )
            data = {
                "boardPlan": received_board_plan,
                "vVerify": received_v_verify,
            }
            err = None
            v_verify_source = "js_payload" if isinstance(received_v_verify, dict) else None
        else:
            data, err, bridge_meta = _run_board_plan_bridge(self.plugin_dir, pure_params)
            step7_details = dict(bridge_meta)
            step7_details["errorMessage"] = (err or "")[:300]
            if err:
                diagnostics["pythonSteps"].append(
                    {
                        "id": "python_build_boardPlan",
                        "side": "Python",
                        "status": "fail",
                        "summary": "Node bridge failed: {}".format(err[:200] if err else ""),
                        "details": step7_details,
                    }
                )
                result["errors"].append(err)
                result["failedStep"] = "python_build_boardPlan"
                self._send_fridge_result(result)
                return

            diagnostics["pythonSteps"].append(
                {
                    "id": "python_build_boardPlan",
                    "side": "Python",
                    "status": "pass",
                    "summary": "boards={}; boardPlan.validation.ok={}".format(
                        bridge_meta.get("boardCount"),
                        bridge_meta.get("boardPlanValidationOk"),
                    ),
                    "details": step7_details,
                }
            )
            v_verify_source = "node_bridge"

        board_plan = data.get("boardPlan") if isinstance(data, dict) else None
        v_verify = data.get("vVerify") if isinstance(data, dict) else None
        if not isinstance(board_plan, dict):
            result["errors"].append("bridge_missing_boardPlan")
            if isinstance(v_verify, dict):
                result["vVerifyOk"] = _validation_ok_tri_state(v_verify)
            err_ct = len(result["errors"])
            warn_ct = 0
            diagnostics["pythonSteps"].append(
                {
                    "id": "python_build_boardPlan",
                    "side": "Python",
                    "status": "fail",
                    "summary": "bridge returned no boardPlan; errors={}".format(err_ct),
                    "details": {
                        "vVerifyOk": result["vVerifyOk"],
                        "errorsCount": err_ct,
                        "warningsCount": warn_ct,
                    },
                }
            )
            result["failedStep"] = "python_build_boardPlan"
            self._send_fridge_result(result)
            return

        result["boardPlanValidationOk"] = _validation_ok_tri_state(board_plan.get("validation"))
        result["vVerifyOk"] = _validation_ok_tri_state(v_verify) if isinstance(v_verify, dict) else None
        pv = pure_params.get("validation")
        bv = board_plan.get("validation")
        val_errors = []
        if not _validation_ok(pv):
            val_errors.append("pureParams.validation.ok is not true.")
            if isinstance(pv, dict) and isinstance(pv.get("errors"), list):
                val_errors.extend(str(x) for x in pv["errors"])
        if not _validation_ok(bv):
            val_errors.append("boardPlan.validation.ok is not true.")
            if isinstance(bv, dict) and isinstance(bv.get("errors"), list):
                val_errors.extend(str(x) for x in bv["errors"])
        if not isinstance(v_verify, dict) or v_verify.get("ok") is not True:
            val_errors.append("verifyVSeriesVectors.ok is not true.")
            if isinstance(v_verify, dict) and isinstance(v_verify.get("errors"), list):
                val_errors.extend(str(x) for x in v_verify["errors"])

        v_err_list = list(v_verify.get("errors", [])) if isinstance(v_verify, dict) else []
        v_warn_list = list(v_verify.get("warnings", [])) if isinstance(v_verify, dict) else []
        gate_err_sample = val_errors[:5]
        v_err_sample = v_err_list[:5]
        v_warn_sample = v_warn_list[:5]
        step8_ok = len(val_errors) == 0
        verify_details = {
            "vVerifyOk": result["vVerifyOk"],
            "vVerifySource": v_verify_source or "unknown",
            "errorsCount": len(v_err_list) + (len(val_errors) if not step8_ok else 0),
            "warningsCount": len(v_warn_list),
            "gateErrorsSample": gate_err_sample,
            "vVerifyErrorsSample": v_err_sample,
            "vVerifyWarningsSample": v_warn_sample,
        }
        if v_verify_source == "js_payload" and isinstance(v_verify, dict):
            verify_details["source"] = "js_payload"

        diagnostics["pythonSteps"].append(
            {
                "id": "python_verify_v_series",
                "side": "Python",
                "status": "pass" if step8_ok else "fail",
                "summary": "vVerify.ok={}; gate errors={}; source={!r}".format(
                    v_verify.get("ok") if isinstance(v_verify, dict) else None,
                    len(val_errors),
                    v_verify_source,
                ),
                "details": verify_details,
            }
        )

        if val_errors:
            result["errors"].extend(val_errors)
            result["failedStep"] = "python_verify_v_series"
            self._send_fridge_result(result)
            return

        if diagnostics_only:
            diagnostics["geometryStartedAt"] = None
            diagnostics["geometryFinishedAt"] = None
            diagnostics["pythonSteps"].append(
                {
                    "id": "python_create_fusion_bodies",
                    "side": "Python",
                    "status": "skipped",
                    "summary": "diagnosticsOnly=true; Fusion body creation skipped",
                    "details": {"attempted": False, "diagnosticsOnly": True},
                }
            )
            result["warnings"].append("diagnosticsOnly: Fusion flat bodies not created.")
            result["finalStatus"] = "pass"
            result["failedStep"] = None
            self._send_fridge_result(result)
            return

        step9_details = {"attempted": True, "createdBodies": 0, "skippedBoards": [], "geometryErrors": []}
        diagnostics["geometryStartedAt"] = _iso_now()
        geo = None
        try:
            import fridge_flat_board_geometry as fcg_geom

            importlib.reload(fcg_geom)
            step9_details["geometryBuild"] = getattr(fcg_geom, "GEOMETRY_BUILD", None)
            geo = fcg_geom.generate_flat_board_bodies(board_plan, 100.0)
            if isinstance(geo, dict):
                step9_details["geometryBuild"] = geo.get("geometryBuild", step9_details.get("geometryBuild"))
                result["geometryBuild"] = geo.get("geometryBuild")
            result["createdBodies"] = int(geo.get("createdBodies", 0))
            result["skippedBoards"] = geo.get("skippedBoards", [])
            result["errors"].extend(geo.get("errors", []))
            result["warnings"].extend(geo.get("warnings", []))
            result["boardPlanBoardCount"] = geo.get("boardPlanBoardCount")
            result["createdBoardIds"] = list(geo.get("createdBoardIds") or [])
            result["skippedBoardIds"] = list(geo.get("skippedBoardIds") or [])
            result["bodyAudit"] = list(geo.get("bodyAudit") or [])
            result["flatPreviewRows"] = list(geo.get("flatPreviewRows") or [])
            step9_details["createdBodies"] = result["createdBodies"]
            step9_details["skippedBoards"] = result["skippedBoards"]
            step9_details["geometryErrors"] = list(geo.get("errors", []))[:5]
            step9_details["boardPlanBoardCount"] = result.get("boardPlanBoardCount")
            step9_details["bodyAuditCount"] = len(result.get("bodyAudit") or [])
        except Exception:
            tb = traceback.format_exc()
            result["errors"].append(tb)
            step9_details["exception"] = tb[:300]
            try:
                import fridge_flat_board_geometry as fcg_geom

                step9_details["geometryBuild"] = getattr(fcg_geom, "GEOMETRY_BUILD", step9_details.get("geometryBuild"))
                result["geometryBuild"] = getattr(fcg_geom, "GEOMETRY_BUILD", None)
            except Exception:
                pass

        diagnostics["geometryFinishedAt"] = _iso_now()
        geo_only_errors = [e for e in result["errors"] if e]
        step9_ok = len(geo_only_errors) == 0
        diagnostics["pythonSteps"].append(
            {
                "id": "python_create_fusion_bodies",
                "side": "Python",
                "status": "pass" if step9_ok else "fail",
                "summary": "createdBodies={}; errors={}".format(
                    result["createdBodies"],
                    len(geo_only_errors),
                ),
                "details": step9_details,
            }
        )

        if geo_only_errors:
            result["failedStep"] = "python_create_fusion_bodies"
            result["finalStatus"] = "fail"
        else:
            result["finalStatus"] = "pass"
            result["failedStep"] = None
        self._send_fridge_result(result)


class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def notify(self, args):
        try:
            command = args.command
            on_execute = _ShowPaletteExecuteHandler(self.app)
            command.execute.add(on_execute)
            self.app.handlers.append(on_execute)
        except:
            app = adsk.core.Application.get()
            ui = app.userInterface if app else None
            if ui:
                ui.messageBox("Fridge Cabinet Generator command failed:\n{}".format(traceback.format_exc()))


class _ShowPaletteExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def notify(self, args):
        self.app.show_palette()


class _PaletteIncomingHandler(adsk.core.HTMLEventHandler):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def notify(self, args):
        try:
            html_args = adsk.core.HTMLEventArgs.cast(args)
            if html_args:
                self.app.handle_html_event(html_args)
        except:
            app = adsk.core.Application.get()
            ui = app.userInterface if app else None
            if ui:
                ui.messageBox("Fridge Cabinet Generator action failed:\n{}".format(traceback.format_exc()))


def run(context):
    global _app
    try:
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        if plugin_dir not in sys.path:
            sys.path.insert(0, plugin_dir)
        _app = FridgeCabinetGeneratorApp(plugin_dir)
        _app.start()
    except:
        app = adsk.core.Application.get()
        ui = app.userInterface if app else None
        if ui:
            ui.messageBox("Fridge Cabinet Generator start failed:\n{}".format(traceback.format_exc()))


def stop(context):
    global _app
    if _app:
        _app.stop()
        _app = None
