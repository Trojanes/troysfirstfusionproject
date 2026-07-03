import importlib
import inspect
import os
import sys
import traceback

import adsk.core


_app = None


def _plugin_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _ensure_paths(plugin_dir):
    paths = [
        plugin_dir,
        os.path.join(plugin_dir, "fusion"),
        os.path.join(plugin_dir, "ui"),
        os.path.join(plugin_dir, "modules"),
        os.path.join(plugin_dir, "modules", "fridge"),
        os.path.join(plugin_dir, "modules", "general_tall"),
        os.path.join(plugin_dir, "modules", "overhead"),
        os.path.join(plugin_dir, "modules", "kitchen"),
        os.path.join(plugin_dir, "modules", "lounge"),
        os.path.join(plugin_dir, "modules", "tools"),
        os.path.join(plugin_dir, "modules", "hardware"),
        os.path.join(plugin_dir, "modules", "hardware"),
        os.path.join(plugin_dir, "modules", "relationships"),
        os.path.join(plugin_dir, "panel_attributes"),
        os.path.join(plugin_dir, "metadata"),
    ]
    for path in paths:
        if path not in sys.path:
            sys.path.insert(0, path)


class UnifiedCabinetPluginApp:
    CMD_ID = "unifiedCabinetPluginCommand"
    CMD_NAME = "CabinetNC"
    CMD_DESC = "Open the unified cabinet generator plugin."
    CONTROL_ID = "unifiedCabinetPluginControl"
    PANEL_ID = "unifiedCabinetPluginPanel"
    PANEL_NAME = "CabinetNC"
    FALLBACK_PANEL_ID = "SolidScriptsAddinsPanel"
    PALETTE_ID = "unifiedCabinetPluginPalette"
    PALETTE_NAME = "CabinetNC"

    def __init__(self, plugin_dir):
        self.plugin_dir = plugin_dir
        self.handlers = []
        self.command_definition = None
        self.control = None
        self.panel = None
        self.palette_controller = None
        self.fusion = None

    def start(self):
        from adapter import FusionAdapter
        from palette_controller import PaletteController

        fridge_module = importlib.reload(importlib.import_module("modules.fridge.controller"))
        general_tall_module = importlib.reload(importlib.import_module("modules.general_tall.controller"))
        overhead_module = importlib.reload(importlib.import_module("modules.overhead.controller"))
        kitchen_module = importlib.reload(importlib.import_module("modules.kitchen.controller"))
        lounge_module = importlib.reload(importlib.import_module("modules.lounge.controller"))
        tools_module = importlib.reload(importlib.import_module("modules.tools.controller"))
        hardware_module = importlib.reload(importlib.import_module("modules.hardware.controller"))
        relationships_module = importlib.reload(importlib.import_module("modules.relationships.controller"))
        panel_attributes_module = importlib.reload(importlib.import_module("panel_attributes.controller"))

        self.fusion = FusionAdapter()
        fridge = fridge_module.FridgeController(self.plugin_dir, self.fusion)
        gt_ctor = general_tall_module.GeneralTallController
        gt_arity = max(0, len(inspect.signature(gt_ctor.__init__).parameters) - 1)
        general_tall = gt_ctor(self.plugin_dir, self.fusion) if gt_arity >= 2 else gt_ctor(self.plugin_dir)
        overhead = overhead_module.OverheadController(self.plugin_dir, self.fusion)
        kitchen = kitchen_module.KitchenController(self.plugin_dir, self.fusion)
        lounge = lounge_module.LoungeController(self.plugin_dir, self.fusion)
        tools = tools_module.ToolsController()
        hardware = hardware_module.HardwareController(self.plugin_dir, self.fusion)
        relationships = relationships_module.RelationshipsController(self.fusion)
        panel_attributes = panel_attributes_module.PanelAttributesController(self.fusion)
        routes = {
            "fridge.calculate": fridge.calculate,
            "fridge.validate": fridge.validate,
            "fridge.generate": fridge.generate,
            "generalTall.generate": general_tall.generate,
            "generalTall.createFusionRoughBodies": general_tall.create_fusion_rough_bodies,
            "overhead.status": overhead.status,
            "overhead.generate": overhead.generate,
            "overhead.createFusionRoughBodies": overhead.create_fusion_rough_bodies,
            "kitchen.generateGeometry": kitchen.generate_geometry,
            "kitchen.createFusionPreview": kitchen.create_fusion_preview,
            "kitchen.createFlatBodyPreview": kitchen.create_flat_body_preview,
            "kitchen.createFlatTransformPreview": kitchen.create_flat_transform_preview,
            "lounge.generateGeometry": lounge.generate_geometry,
            "lounge.createFlatBodies": lounge.create_flat_bodies,
            "lounge.createAssemblyBodies": lounge.create_assembly_bodies,
            "tools.status": tools.status,
            "hardware.createSideContactTestBoards": hardware.create_side_contact_test_boards,
            "hardware.calculateSideContactPreview": hardware.calculate_side_contact_preview,
            "hardware.createSideContactHoles": hardware.create_side_contact_holes,
            "hardware.previewScrewHolesFromRelationship": hardware.preview_screw_holes_from_relationship,
            "hardware.createScrewHolesFromRelationship": hardware.create_screw_holes_from_relationship,
            "relationships.scan": relationships.scan,
            "relationships.scanSelected": relationships.scan_selected,
            "relationships.inspectSelected": relationships.inspect_selected,
            "relationships.inspectPair": relationships.inspect_pair,
            "relationships.createTestFixture": relationships.create_test_fixture,
            "panelAttributes.searchPanels": panel_attributes.search_panels,
            "panelAttributes.selectByTag": panel_attributes.select_by_tag,
            "panelAttributes.selectPanel": panel_attributes.select_panel,
            "panelAttributes.selectMetadataRecord": panel_attributes.select_metadata_record,
            "panelAttributes.selectMetadataRecords": panel_attributes.select_metadata_records,
            "panelAttributes.scanMetadata": panel_attributes.scan_metadata,
            "panelAttributes.scanSelectedMetadata": panel_attributes.scan_selected_metadata,
            "panelAttributes.tagScanSelected": panel_attributes.tag_scan_selected,
            "panelAttributes.applyTagScanDrafts": panel_attributes.apply_tag_scan_drafts,
            "panelAttributes.setWorkZones": panel_attributes.set_work_zones,
            "panelAttributes.setAssemblyZone": panel_attributes.set_work_zones,
            "panelAttributes.getWorkZones": panel_attributes.get_work_zones,
            "pingPython": self._ping,
        }
        self.palette_controller = PaletteController(
            self.fusion,
            self.handlers,
            self.PALETTE_ID,
            self.PALETTE_NAME,
            routes,
        )

        _app, ui = self.fusion.get_app_ui()
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
            self.panel = workspace.toolbarPanels.add(self.PANEL_ID, self.PANEL_NAME, self.FALLBACK_PANEL_ID, False)
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
        _app, ui = self.fusion.get_app_ui() if self.fusion else (None, None)
        try:
            if self.control:
                self.control.deleteMe()
                self.control = None
            if self.panel:
                self.panel.deleteMe()
                self.panel = None
            if self.palette_controller:
                self.palette_controller.hide()
                self.palette_controller = None
            if self.command_definition:
                self.command_definition.deleteMe()
                self.command_definition = None
            self.handlers.clear()
        except Exception:
            if ui:
                ui.messageBox("CabinetNC stop failed:\n{}".format(traceback.format_exc()))

    def show_palette(self):
        if self.palette_controller:
            self.palette_controller.show()

    def _ping(self, payload, _palette):
        return (
            "pythonPong",
            {
                "ok": True,
                "plugin": "CabinetNC",
                "received": payload,
                "pythonBuild": "unified-plugin-mvp-001",
            },
        )


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
        except Exception:
            app = adsk.core.Application.get()
            ui = app.userInterface if app else None
            if ui:
                ui.messageBox("CabinetNC command failed:\n{}".format(traceback.format_exc()))


class _ShowPaletteExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def notify(self, _args):
        self.app.show_palette()


def run(_context):
    global _app
    try:
        plugin_dir = _plugin_dir()
        _ensure_paths(plugin_dir)
        _app = UnifiedCabinetPluginApp(plugin_dir)
        _app.start()
    except Exception:
        app = adsk.core.Application.get()
        ui = app.userInterface if app else None
        if ui:
            ui.messageBox("CabinetNC start failed:\n{}".format(traceback.format_exc()))


def stop(_context):
    global _app
    if _app:
        _app.stop()
        _app = None
