import inspect
import json
import os
import threading
import time
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


PROGRESS_MIN_INTERVAL_MS = 200

# These actions show the bottom bar immediately. Fast lookups stay quiet.
_LONG_ACTIONS = frozenset(
    (
        "panelAttributes.buildNestingOutlines",
        "panelAttributes.createNestingZoneLayout",
        "panelAttributes.createNestingLayoutSketch",
        "panelAttributes.exportNestingLayoutDxf",
        "panelAttributes.exportManufacturingSnapshot",
        "panelAttributes.createLayFlatLayout",
        "panelAttributes.analyzeLayFlatManufacturing",
        "panelAttributes.checkLayFlatExportReady",
        "panelAttributes.scanMetadata",
        "panelAttributes.replaceColorTag",
        "panelAttributes.setColorGrain",
        "generalTall.createFusionRoughBodies",
        "overhead.createFusionRoughBodies",
        "uShapeOverhead.createFusionBodies",
        "kitchen.createFusionPreview",
        "kitchen.createFlatBodyPreview",
        "kitchen.createFlatTransformPreview",
        "lounge.createFlatBodies",
        "lounge.createAssemblyBodies",
        "smallCabinet.createFusionRoughBodies",
    )
)


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
        self._work_queue = []
        self._busy = False
        self._active_gen = None
        self._custom_event = None
        self._custom_event_handler = None
        self._custom_event_id = "CabinetNC_PaletteWork_{}".format(palette_id)
        self._progress_last_ms = 0.0
        self._html_mtime = None

    def _palette_html_url(self):
        html_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", self.html_file)
        )
        try:
            stamp = int(os.path.getmtime(html_path))
        except Exception:
            stamp = int(time.time())
        return "file:///" + html_path.replace("\\", "/") + "?v=" + str(stamp), stamp

    def show(self):
        _app, ui = self.fusion.get_app_ui()
        if not ui:
            return
        palettes = ui.palettes
        url, stamp = self._palette_html_url()
        existing = palettes.itemById(self.palette_id)
        # Fusion keeps the Chromium page after add-in reload. Recreate when this
        # controller has not loaded this HTML mtime yet, or the file changed.
        if existing is not None and self._html_mtime != stamp:
            try:
                existing.deleteMe()
                existing = None
            except Exception:
                try:
                    existing.htmlFileURL = url
                    self._html_mtime = stamp
                except Exception:
                    pass
        self.palette = existing
        if not self.palette:
            self.palette = palettes.add(
                self.palette_id,
                self.palette_name,
                url,
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
            self._html_mtime = stamp
        self._ensure_async_dispatch()
        self.palette.isVisible = True

    def hide(self):
        if self._active_gen is not None:
            try:
                self._active_gen[1].close()
            except Exception:
                pass
            self._active_gen = None
        self._teardown_async_dispatch()
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

    def send_progress(
        self,
        action="",
        phase="",
        label="",
        done=None,
        total=None,
        percent=None,
        force=False,
    ):
        """Push a throttled progress event. Do not call doEvents — it does not unfreeze Fusion."""
        now_ms = time.monotonic() * 1000.0
        if not force and (now_ms - self._progress_last_ms) < PROGRESS_MIN_INTERVAL_MS:
            return
        self._progress_last_ms = now_ms
        payload = {
            "action": action or "",
            "phase": phase or "",
            "label": label or "",
        }
        if done is not None:
            payload["done"] = done
        if total is not None:
            payload["total"] = total
        if percent is not None:
            try:
                payload["percent"] = max(0, min(100, int(percent)))
            except Exception:
                payload["percent"] = 0
        try:
            self.send("unifiedProgress", payload)
        except Exception:
            pass

    def handle_action(self, html_args):
        html_args.returnData = '{"accepted":true}'
        action, payload = self._parse_html_args(html_args)
        if not action or action == "response":
            return
        self.enqueue_action(action, payload)

    def enqueue_action(self, action, payload):
        self._work_queue.append((str(action), payload if isinstance(payload, dict) else {}))
        if str(action) in _LONG_ACTIONS:
            self.send_progress(action=action, phase="queued", percent=0, force=True)
        if self._custom_event is None:
            self._ensure_async_dispatch()
        if self._custom_event is not None:
            self._schedule_work(delay_ms=15)
        else:
            self._drain_work_queue()

    def _ensure_async_dispatch(self):
        if self._custom_event is not None:
            return
        app = adsk.core.Application.get()
        if not app:
            return
        try:
            try:
                app.unregisterCustomEvent(self._custom_event_id)
            except Exception:
                pass
            event = app.registerCustomEvent(self._custom_event_id)
            handler = _PaletteWorkHandler(self)
            event.add(handler)
            self._custom_event = event
            self._custom_event_handler = handler
            self.handlers_store.append(handler)
        except Exception:
            self._custom_event = None
            self._custom_event_handler = None

    def _teardown_async_dispatch(self):
        app = None
        try:
            app = adsk.core.Application.get()
        except Exception:
            app = None
        handler = self._custom_event_handler
        event = self._custom_event
        self._custom_event = None
        self._custom_event_handler = None
        if event is not None and handler is not None:
            try:
                event.remove(handler)
            except Exception:
                pass
        if app is not None:
            try:
                app.unregisterCustomEvent(self._custom_event_id)
            except Exception:
                pass

    def _fire_work_event(self):
        if self._custom_event is None:
            self._ensure_async_dispatch()
        app = adsk.core.Application.get()
        if not app or self._custom_event is None:
            return False
        try:
            app.fireCustomEvent(self._custom_event_id, "")
            return True
        except Exception:
            return False

    def _schedule_work(self, delay_ms=10):
        """Fire the work event from a worker thread after the current notify returns.

        fireCustomEvent from the HTML handler often runs the work immediately on
        the same stack, so Fusion stays frozen. A short thread bounce lets the
        palette return and the viewport paint between slices.
        """
        delay = max(0, int(delay_ms or 0))

        def _fire():
            if delay:
                time.sleep(delay / 1000.0)
            try:
                app = adsk.core.Application.get()
                if app and self._custom_event is not None:
                    app.fireCustomEvent(self._custom_event_id, "")
            except Exception:
                pass

        threading.Thread(target=_fire, daemon=True).start()

    def _drain_work_queue(self):
        if self._busy:
            return
        self._busy = True
        more = False
        delay_ms = 10
        try:
            if self._active_gen is not None:
                more, delay_ms = self._advance_generator()
            elif self._work_queue:
                action, payload = self._work_queue.pop(0)
                self._dispatch(action, payload)
                if self._active_gen is not None:
                    more, delay_ms = self._advance_generator()
        finally:
            self._busy = False
        if more or self._work_queue or self._active_gen is not None:
            self._schedule_work(delay_ms=delay_ms)

    def _advance_generator(self):
        action, gen = self._active_gen
        try:
            yielded = next(gen)
        except StopIteration as stop:
            self._active_gen = None
            self._emit_handler_result(action, stop.value)
            return False, 10
        except Exception as ex:
            self._active_gen = None
            try:
                gen.close()
            except Exception:
                pass
            self._emit_handler_exception(action, ex)
            return False, 10
        delay_ms = 10
        if isinstance(yielded, dict):
            delay_ms = int(yielded.get("delayMs") or 10)
            progress = {
                key: value
                for key, value in yielded.items()
                if key not in ("delayMs",)
            }
            if progress:
                self.send_progress(action=action, **progress)
        return True, max(0, delay_ms)

    def _dispatch(self, action, payload):
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
            self._emit_handler_exception(action, ex)
            return
        if inspect.isgenerator(result):
            self._active_gen = (action, result)
            return
        self._emit_handler_result(action, result)

    def _emit_handler_result(self, action, result):
        if isinstance(result, tuple):
            event_id, data = result
            self._log_action_result(action, data)
            self.send(event_id, data)
        elif result is not None:
            self._log_action_result(action, result)
            self.send("unifiedResult", result)

    def _emit_handler_exception(self, action, ex):
        log_event(
            "action_exception",
            action=action,
            error=ex,
            traceback=traceback.format_exc(),
        )
        self.send(
            "unifiedResult",
            {
                "ok": False,
                "action": action,
                "errors": [str(ex)],
            },
        )
        _app, ui = self.fusion.get_app_ui()
        if ui:
            ui.messageBox(
                "Unified Cabinet Plugin palette action failed:\n{}".format(
                    traceback.format_exc()
                )
            )

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
                ui.messageBox(
                    "Unified Cabinet Plugin palette action failed:\n{}".format(
                        traceback.format_exc()
                    )
                )


class _PaletteWorkHandler(adsk.core.CustomEventHandler):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller

    def notify(self, _args):
        try:
            self.controller._drain_work_queue()
        except Exception:
            _app, ui = self.controller.fusion.get_app_ui()
            if ui:
                ui.messageBox(
                    "Unified Cabinet Plugin deferred action failed:\n{}".format(
                        traceback.format_exc()
                    )
                )
