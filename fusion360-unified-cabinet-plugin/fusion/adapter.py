import adsk.core
import adsk.fusion


class FusionAdapter:
    """Small Fusion API wrapper shared by unified plugin modules."""

    @staticmethod
    def mm_to_cm(value_mm):
        return float(value_mm) / 10.0

    def get_app_ui(self):
        app = adsk.core.Application.get()
        return app, app.userInterface if app else None

    def get_active_design(self):
        app, _ui = self.get_app_ui()
        if not app or not app.activeProduct:
            return None
        return adsk.fusion.Design.cast(app.activeProduct)

    def get_root_component(self):
        design = self.get_active_design()
        return design.rootComponent if design else None

    def refresh_viewport(self):
        app, _ui = self.get_app_ui()
        try:
            if app and app.activeViewport:
                app.activeViewport.refresh()
        except Exception:
            pass

    def log(self, tag, message):
        app, _ui = self.get_app_ui()
        try:
            log_fn = getattr(app, "log", None) if app else None
            if callable(log_fn):
                log_fn(str(tag), str(message)[:3500])
        except Exception:
            pass

    def select_bodies_and_fit(self, bodies):
        app, ui = self.get_app_ui()
        if not app:
            return 0

        valid_bodies = [body for body in (bodies or []) if body]
        if not valid_bodies:
            return 0

        selection = self._active_selection_collection(app, ui)
        if selection is not None:
            try:
                selection.clear()
                for body in valid_bodies:
                    selection.add(body)
            except Exception:
                selection = None

        try:
            viewport = app.activeViewport
            if viewport:
                viewport.fit()
                viewport.refresh()
        except Exception:
            self.refresh_viewport()

        return len(valid_bodies)

    def get_selected_entities(self):
        app, ui = self.get_app_ui()
        if not app:
            return []

        selection = self._active_selection_collection(app, ui)
        if selection is None:
            return []

        entities = []
        try:
            count = selection.count
        except Exception:
            count = 0
        for index in range(count):
            try:
                item = selection.item(index)
                entity = getattr(item, "entity", item)
                if entity:
                    entities.append(entity)
            except Exception:
                continue
        return entities

    def _active_selection_collection(self, app, ui):
        for owner, attr_name in ((ui, "activeSelections"), (ui, "activeSelection"), (app, "activeSelections")):
            if not owner:
                continue
            try:
                selection = getattr(owner, attr_name)
            except Exception:
                selection = None
            if selection is not None:
                return selection
        return None
