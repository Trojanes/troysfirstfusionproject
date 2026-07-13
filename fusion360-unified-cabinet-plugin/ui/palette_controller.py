import json
import os
import traceback

import adsk.core


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
        data = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
        self.palette.sendInfoToHTML(event_id, data)

    def handle_action(self, html_args):
        html_args.returnData = ""
        action, payload = self._parse_html_args(html_args)
        if not action or action == "response":
            return

        handler = self.routes.get(action)
        if not handler:
            self.send(
                "unifiedResult",
                {
                    "ok": False,
                    "action": action,
                    "errors": ["No handler registered for action: {}".format(action)],
                },
            )
            return
        result = handler(payload, self)
        if isinstance(result, tuple):
            event_id, data = result
            self.send(event_id, data)
        elif result is not None:
            self.send("unifiedResult", result)

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
