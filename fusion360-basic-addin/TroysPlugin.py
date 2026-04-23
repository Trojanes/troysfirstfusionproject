import adsk.core
import adsk.fusion
import json
import os
import traceback

CMD_ID = "troysPluginCommand"
CMD_NAME = "Troy's Plugin"
CMD_DESC = "Open Troy's Plugin palette."
CONTROL_ID = "troysPluginControl"
PANEL_ID = "troysPluginPanel"
PANEL_NAME = "Troy's Plugin"
FALLBACK_PANEL_ID = "SolidScriptsAddinsPanel"
PALETTE_ID = "troysPluginPalette"
PALETTE_NAME = "Troy's Plugin"

_handlers = []
_command_definition = None
_control = None
_panel = None
_palette = None


def _get_app_ui():
    app = adsk.core.Application.get()
    if not app:
        return None, None
    return app, app.userInterface


def run(context):
    global _command_definition, _control, _panel
    app, ui = _get_app_ui()
    if not app or not ui:
        return
    try:
        cmd_defs = ui.commandDefinitions
        _command_definition = cmd_defs.itemById(CMD_ID)
        resource_dir = os.path.join(os.path.dirname(__file__), "resources")
        if not _command_definition:
            _command_definition = cmd_defs.addButtonDefinition(
                CMD_ID, CMD_NAME, CMD_DESC, resource_dir
            )

        on_created = _CommandCreatedHandler()
        _command_definition.commandCreated.add(on_created)
        _handlers.append(on_created)

        workspace = ui.workspaces.itemById("FusionSolidEnvironment")
        panel = workspace.toolbarPanels.itemById(PANEL_ID) if workspace else None
        if not panel and workspace:
            panel = workspace.toolbarPanels.add(PANEL_ID, PANEL_NAME, FALLBACK_PANEL_ID, False)
        _panel = panel

        if panel:
            old_control = panel.controls.itemById(CONTROL_ID)
            if old_control:
                old_control.deleteMe()
            _control = panel.controls.addCommand(_command_definition, CONTROL_ID)
            _control.isVisible = True
            _control.isPromoted = True
            _control.isPromotedByDefault = True

        _show_palette()
    except:
        if ui:
            ui.messageBox("Add-in start failed:\n{}".format(traceback.format_exc()))


def stop(context):
    global _command_definition, _control, _panel, _palette
    _, ui = _get_app_ui()
    try:
        if _control:
            _control.deleteMe()
            _control = None
        if _panel:
            _panel.deleteMe()
            _panel = None
        if _palette:
            _palette.deleteMe()
            _palette = None
        if _command_definition:
            _command_definition.deleteMe()
            _command_definition = None
        _handlers.clear()
    except:
        if ui:
            ui.messageBox("Add-in stop failed:\n{}".format(traceback.format_exc()))


class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            cmd = args.command
            on_execute = _ShowPaletteExecuteHandler()
            cmd.execute.add(on_execute)
            _handlers.append(on_execute)
        except:
            _, ui = _get_app_ui()
            if ui:
                ui.messageBox("Command creation failed:\n{}".format(traceback.format_exc()))


class _ShowPaletteExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        _show_palette()


class _PaletteIncomingHandler(adsk.core.HTMLEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        try:
            html_args = adsk.core.HTMLEventArgs.cast(args)
            if not html_args:
                return

            action = _resolve_action(html_args)
            if action == "scan":
                lines = _scan_bodies()
            else:
                lines = ["Coming soon: {}".format(action)]

            payload = json.dumps({"text": "\n".join(lines)})
            html_args.returnData = payload
            if _palette:
                _palette.sendInfoToHTML("scanResult", payload)
        except:
            _, ui = _get_app_ui()
            if ui:
                ui.messageBox("Palette action failed:\n{}".format(traceback.format_exc()))


def _resolve_action(html_args):
    action = html_args.action
    if action and action not in ("response",):
        return action
    if html_args.data:
        real_action = _extract_action_from_data(html_args.data)
        if real_action:
            return real_action
    return "scan"


def _extract_action_from_data(raw_data):
    try:
        parsed = json.loads(raw_data)
        if isinstance(parsed, dict):
            action = parsed.get("action")
            if isinstance(action, str):
                return action
            nested = parsed.get("data")
            if isinstance(nested, str) and nested:
                try:
                    nested_obj = json.loads(nested)
                    if isinstance(nested_obj, dict):
                        nested_action = nested_obj.get("action")
                        if isinstance(nested_action, str):
                            return nested_action
                except:
                    pass
    except:
        pass
    if isinstance(raw_data, str):
        text = raw_data.strip()
        if text and ("{" not in text and "}" not in text):
            return text
    return None


def _show_palette():
    global _palette
    _, ui = _get_app_ui()
    if not ui:
        return
    palettes = ui.palettes
    _palette = palettes.itemById(PALETTE_ID)
    if not _palette:
        html_path = os.path.join(os.path.dirname(__file__), "palette.html")
        _palette = palettes.add(
            PALETTE_ID,
            PALETTE_NAME,
            "file:///" + html_path.replace("\\", "/"),
            True,
            True,
            True,
            420,
            540,
            False,
        )
        on_incoming = _PaletteIncomingHandler()
        _palette.incomingFromHTML.add(on_incoming)
        _handlers.append(on_incoming)
    _palette.isVisible = True


def _scan_bodies():
    app, _ = _get_app_ui()
    design = adsk.fusion.Design.cast(app.activeProduct) if app else None
    if not design:
        return ["No active Fusion design."]

    selected = _selected_bodies_only()
    if selected:
        bodies = selected
        scope = "selected bodies"
    else:
        bodies = _all_project_bodies(design)
        scope = "all project bodies"

    if not bodies:
        return ["No bodies found."]

    lines = ["Bodies found: {} ({})".format(len(bodies), scope), ""]
    for owner, body in bodies:
        l, w, h = _dims_mm(body)
        lines.append(
            "{} | {} | LxWxH: {:.2f} x {:.2f} x {:.2f} mm".format(
                owner, body.name, l, w, h
            )
        )
    return lines


def _selected_bodies_only():
    _, ui = _get_app_ui()
    if not ui:
        return []
    sels = ui.activeSelections
    if sels is None or sels.count == 0:
        return []

    out = []
    seen = set()
    for i in range(sels.count):
        ent = sels.item(i).entity
        body = adsk.fusion.BRepBody.cast(ent)
        if not body:
            face = adsk.fusion.BRepFace.cast(ent)
            if face:
                body = face.body
        if not body:
            continue
        token = body.entityToken
        if token in seen:
            continue
        seen.add(token)
        out.append(("Selected", body))
    return out


def _all_project_bodies(design):
    root = design.rootComponent
    if not root:
        return []

    out = []
    seen = set()
    for i in range(root.bRepBodies.count):
        body = root.bRepBodies.item(i)
        token = body.entityToken
        if token in seen:
            continue
        seen.add(token)
        out.append(("Root", body))

    for i in range(root.allOccurrences.count):
        occ = root.allOccurrences.item(i)
        comp = occ.component
        if not comp:
            continue
        for j in range(comp.bRepBodies.count):
            native_body = comp.bRepBodies.item(j)
            body = native_body.createForAssemblyContext(occ) if occ else native_body
            if not body:
                continue
            token = body.entityToken
            if token in seen:
                continue
            seen.add(token)
            out.append((occ.name, body))
    return out


def _dims_mm(body):
    bbox = body.boundingBox
    min_pt = bbox.minPoint
    max_pt = bbox.maxPoint
    x_mm = abs(max_pt.x - min_pt.x) * 10.0
    y_mm = abs(max_pt.y - min_pt.y) * 10.0
    z_mm = abs(max_pt.z - min_pt.z) * 10.0
    return sorted([x_mm, y_mm, z_mm], reverse=True)
