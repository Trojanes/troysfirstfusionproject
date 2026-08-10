import json
import os
import traceback

import adsk.core

try:
    from core.usage_log import log_event, summarize_nesting_result
except Exception:
    try:
        import sys

        _root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        if _root not in sys.path:
            sys.path.insert(0, _root)
        from core.usage_log import log_event, summarize_nesting_result
    except Exception:
        def log_event(*_args, **_kwargs):
            return None

        def summarize_nesting_result(data):
            return data if isinstance(data, dict) else {}


class PaletteController:
    def __init__(
        self,
        fusion_adapter,
        handlers_store,
        palette_id,
        palette_name,
        routes,
        *,
        html_file="palette.html",
        width=1500,
        height=950,
    ):
        self.fusion = fusion_adapter
        self.handlers_store = handlers_store
        self.palette_id = palette_id
        self.palette_name = palette_name
        self.routes = routes
        self.html_file = html_file
        self.width = int(width)
        self.height = int(height)
        self.palette = None

    def show(self):
        _app, ui = self.fusion.get_app_ui()
        if not ui:
            return
        palettes = ui.palettes
        self.palette = palettes.itemById(self.palette_id)
        if not self.palette:
            html_path = os.path.join(os.path.dirname(__file__), "..", self.html_file)
            self.palette = palettes.add(
                self.palette_id,
                self.palette_name,
                "file:///" + os.path.abspath(html_path).replace("\\", "/"),
                True,
                True,
                True,
                self.width,
                self.height,
                False,
            )
            incoming = _PaletteIncomingHandler(self)
            self.palette.incomingFromHTML.add(incoming)
            self.handlers_store.append(incoming)
        self.palette.isVisible = True

    def hide(self):
        if not self.palette:
            return
        try:
            self.palette.isVisible = False
            self.palette.deleteMe()
        except RuntimeError:
            pass
        self.palette = None

    def send(self, event_id, payload):
        if not self.palette:
            return
        try:
            data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        except Exception as ex:
            log_event(
                "send_serialize_error",
                action=str((payload or {}).get("action") if isinstance(payload, dict) else ""),
                error=ex,
                eventId=event_id,
                payload=payload,
            )
            raise
        self.palette.sendInfoToHTML(event_id, data)

    def handle_action(self, html_args):
        html_args.returnData = ""
        action, payload = self._parse_html_args(html_args)
        if not action or action == "response":
            return

        log_event("action_start", action=action, payload=payload)
        handler = self.routes.get(action)
        if not handler:
            data = {
                "ok": False,
                "action": action,
                "errors": ["No handler registered for action: {}".format(action)],
            }
            log_event("action_result", action=action, payload=data)
            self.send("unifiedResult", data)
            return
        try:
            result = handler(payload, self)
        except Exception as ex:
            log_event(
                "action_exception",
                action=action,
                error=ex,
                traceback=traceback.format_exc(),
                payload=payload,
            )
            raise
        if isinstance(result, tuple):
            event_id, data = result
            self._log_action_result(action, data)
            self.send(event_id, data)
        elif result is not None:
            self._log_action_result(action, result)
            self.send("unifiedResult", result)

    def _log_action_result(self, action, data):
        summary = None
        if str(action or "").startswith("panelAttributes.createNesting") or (
            isinstance(data, dict)
            and str(data.get("action") or "").startswith("createNesting")
        ):
            summary = summarize_nesting_result(data if isinstance(data, dict) else {})
        log_event(
            "action_result",
            action=action,
            payload=summary if summary is not None else data,
            summary=summary,
        )

    def _parse_html_args(self, html_args):
        action = getattr(html_args, "action", "") or ""
        raw_data = getattr(html_args, "data", None)
        payload = {}
        if isinstance(raw_data, dict):
            payload = dict(raw_data)
        elif isinstance(raw_data, str) and raw_data.strip():
            try:
                parsed = json.loads(raw_data.strip().lstrip("\ufeff"))
                if isinstance(parsed, dict):
                    payload = parsed
            except Exception:
                payload = {"raw": raw_data}

        if action == "response" and isinstance(payload, dict):
            nested_action = payload.get("action")
            if isinstance(nested_action, str) and nested_action:
                action = nested_action
        if not action and isinstance(payload, dict):
            action = payload.get("action", "")
        return str(action), payload


class _PaletteIncomingHandler(adsk.core.HTMLEventHandler):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

    def notify(self, args):
        try:
            html_args = adsk.core.HTMLEventArgs.cast(args)
            if html_args:
                self.controller.handle_action(html_args)
        except Exception:
            _app, ui = self.controller.fusion.get_app_ui()
            if ui:
                ui.messageBox("Unified Cabinet Plugin palette action failed:\n{}".format(traceback.format_exc()))
