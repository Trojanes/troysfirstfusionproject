import adsk.core
import traceback

from fusion.api import app_and_ui


class CabinetAutomationCommand:
    CMD_ID = "fusionCabinetAutomationCommand"
    CMD_NAME = "Troy's Plugin"
    CMD_DESC = "Minimal plugin shell with a close button."
    WORKSPACE_ID = "FusionSolidEnvironment"
    PANEL_ID = "SolidScriptsAddinsPanel"
    CONTROL_ID = "fusionCabinetAutomationControl"

    def __init__(self):
        self._handlers = []
        self._command_definition = None
        self._control = None
        self._last_result_text = ""

    def start(self):
        app, ui = app_and_ui()
        if not app or not ui:
            return

        cmd_defs = ui.commandDefinitions
        self._command_definition = cmd_defs.itemById(self.CMD_ID)
        if not self._command_definition:
            self._command_definition = cmd_defs.addButtonDefinition(
                self.CMD_ID, self.CMD_NAME, self.CMD_DESC
            )

        on_created = _CommandCreatedHandler(self)
        self._command_definition.commandCreated.add(on_created)
        self._handlers.append(on_created)

        workspace = ui.workspaces.itemById(self.WORKSPACE_ID)
        panel = workspace.toolbarPanels.itemById(self.PANEL_ID) if workspace else None
        if panel:
            self._control = panel.controls.itemById(self.CONTROL_ID)
            if not self._control:
                self._control = panel.controls.addCommand(
                    self._command_definition, self.CONTROL_ID
                )
            self._control.isPromoted = True
            self._control.isPromotedByDefault = True

    def stop(self):
        if self._control:
            self._control.deleteMe()
            self._control = None
        if self._command_definition:
            self._command_definition.deleteMe()
            self._command_definition = None
        self._handlers = []


class _CommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, owner):
        super().__init__()
        self._owner = owner

    def notify(self, args):
        try:
            cmd = args.command
            cmd.okButtonText = "Close"
            cmd.isCancelButtonVisible = False

            on_execute = _ExecuteHandler()
            cmd.execute.add(on_execute)
            self._owner._handlers.append(on_execute)
        except:
            _, ui = app_and_ui()
            if ui:
                ui.messageBox("Command creation failed:\n{}".format(traceback.format_exc()))


class _ExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self):
        super().__init__()

    def notify(self, args):
        # Keep execute minimal for this setup milestone.
        return
