import importlib
import inspect
import os
import sys
import traceback

import adsk.core


_app = None


def _plugin_dir():
    return os.path.dirname(os.path.abspath(__file__))


def _purge_plugin_modules(plugin_dir):
    """Drop every cached module that lives inside the plugin folder.

    ``importlib.reload`` on the controllers alone is not enough: their
    dependencies (panel_geometry, milling_surface_propagation, ...) stay
    cached in ``sys.modules``, so code edits never take effect until Fusion
    restarts. Purging first makes the fresh imports below load current code.
    """
    prefix = os.path.normcase(os.path.abspath(plugin_dir)) + os.sep
    for name, module in list(sys.modules.items()):
        if name == __name__:
            continue
        module_file = getattr(module, "__file__", None)
        if not module_file:
            continue
        try:
            if os.path.normcase(os.path.abspath(module_file)).startswith(prefix):
                sys.modules.pop(name, None)
        except Exception:
            continue


def _ensure_paths(plugin_dir):
    paths = [
        plugin_dir,
        os.path.join(plugin_dir, "fusion"),
        os.path.join(plugin_dir, "ui"),
        os.path.join(plugin_dir, "modules"),
        os.path.join(plugin_dir, "modules", "general_tall"),
        os.path.join(plugin_dir, "modules", "overhead"),
        os.path.join(plugin_dir, "modules", "kitchen"),
        os.path.join(plugin_dir, "modules", "lounge"),
        os.path.join(plugin_dir, "modules", "tools"),
        os.path.join(plugin_dir, "modules", "hardware"),
        os.path.join(plugin_dir, "modules", "relationships"),
        os.path.join(plugin_dir, "panel_attributes"),
        os.path.join(plugin_dir, "metadata"),
        os.path.join(plugin_dir, "presets"),
    ]
    for path in paths:
        if path not in sys.path:
            sys.path.insert(0, path)


class UnifiedCabinetPluginApp:
    CMD_ID = "unifiedCabinetPluginCommand"
    CMD_NAME = "CabinetNC"
    CMD_DESC = "Open the unified cabinet generator plugin."
    CONTROL_ID = "unifiedCabinetPluginControl"
    OPS_CMD_ID = "unifiedCabinetPluginOpsCommand"
    OPS_CMD_NAME = "Connect 已创建操作"
    OPS_CMD_DESC = "Open the Connect hardware operations editor palette."
    OPS_CONTROL_ID = "unifiedCabinetPluginOpsControl"
    PANEL_ID = "unifiedCabinetPluginPanel"
    PANEL_NAME = "CabinetNC"
    FALLBACK_PANEL_ID = "SolidScriptsAddinsPanel"
    PALETTE_ID = "unifiedCabinetPluginPalette"
    PALETTE_NAME = "CabinetNC"
    OPS_PALETTE_ID = "unifiedCabinetPluginOpsPalette"
    OPS_PALETTE_NAME = "Connect 已创建操作"

    def __init__(self, plugin_dir):
        self.plugin_dir = plugin_dir
        self.handlers = []
        self.command_definition = None
        self.ops_command_definition = None
        self.control = None
        self.ops_control = None
        self.panel = None
        self.palette_controller = None
        self.ops_palette_controller = None
        self.fusion = None

    def start(self):
        _purge_plugin_modules(self.plugin_dir)
        from adapter import FusionAdapter
        from palette_controller import PaletteController

        general_tall_module = importlib.reload(importlib.import_module("modules.general_tall.controller"))
        overhead_module = importlib.reload(importlib.import_module("modules.overhead.controller"))
        kitchen_module = importlib.reload(importlib.import_module("modules.kitchen.controller"))
        lounge_module = importlib.reload(importlib.import_module("modules.lounge.controller"))
        tools_module = importlib.reload(importlib.import_module("modules.tools.controller"))
        hardware_module = importlib.reload(importlib.import_module("modules.hardware.controller"))
        relationships_module = importlib.reload(importlib.import_module("modules.relationships.controller"))
        connect_demo_module = importlib.reload(importlib.import_module("modules.relationships.connect_demo_controller"))
        panel_attributes_module = importlib.reload(importlib.import_module("panel_attributes.controller"))

        self.fusion = FusionAdapter()
        gt_ctor = general_tall_module.GeneralTallController
        gt_arity = max(0, len(inspect.signature(gt_ctor.__init__).parameters) - 1)
        general_tall = gt_ctor(self.plugin_dir, self.fusion) if gt_arity >= 2 else gt_ctor(self.plugin_dir)
        overhead = overhead_module.OverheadController(self.plugin_dir, self.fusion)
        kitchen = kitchen_module.KitchenController(self.plugin_dir, self.fusion)
        lounge = lounge_module.LoungeController(self.plugin_dir, self.fusion)
        tools = tools_module.ToolsController()
        hardware = hardware_module.HardwareController(self.plugin_dir, self.fusion)
        relationships = relationships_module.RelationshipsController(self.fusion)
        connect_demo = connect_demo_module.ConnectDemoController(self.plugin_dir, self.fusion, relationships, hardware)
        panel_attributes = panel_attributes_module.PanelAttributesController(self.fusion)
        routes = {
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
            "hardware.previewScrewHolesFromRelationship": hardware.preview_screw_holes_from_relationship,
            "hardware.createScrewHolesFromRelationship": hardware.create_screw_holes_from_relationship,
            "hardware.listHardwareTypes": hardware.list_hardware_types,
            "hardware.previewHardwareFromRelationship": hardware.preview_hardware_from_relationship,
            "hardware.createHardwareFromRelationship": hardware.create_hardware_from_relationship,
            "hardware.createHardwareForCutSafeRelationships": hardware.create_hardware_for_cut_safe_relationships,
            "hardware.runConnectPipeline": hardware.run_connect_pipeline,
            "hardware.listHardwareOperations": hardware.list_hardware_operations,
            "hardware.updateHardwareOperation": hardware.update_hardware_operation,
            "hardware.previewHingeHolesFromRelationship": hardware.preview_hinge_holes_from_relationship,
            "hardware.createHingeHolesFromRelationship": hardware.create_hinge_holes_from_relationship,
            "hardware.previewDrawerRunnerHolesFromRelationship": hardware.preview_drawer_runner_holes_from_relationship,
            "hardware.createDrawerRunnerHolesFromRelationship": hardware.create_drawer_runner_holes_from_relationship,
            "hardware.previewLockCutoutFromRelationship": hardware.preview_lock_cutout_from_relationship,
            "hardware.createLockCutoutFromRelationship": hardware.create_lock_cutout_from_relationship,
            "hardware.previewTongueGrooveFromRelationship": hardware.preview_tongue_groove_from_relationship,
            "hardware.createTongueGrooveFromRelationship": hardware.create_tongue_groove_from_relationship,
            "relationships.scan": relationships.scan,
            "relationships.scanSelected": relationships.scan_selected,
            "relationships.inspectSelected": relationships.inspect_selected,
            "relationships.probeSelection": relationships.probe_selection,
            "relationships.inspectPair": relationships.inspect_pair,
            "relationships.createTestFixture": relationships.create_test_fixture,
            "relationships.showRelationshipOverlayForSelected": relationships.show_relationship_overlay_for_selected,
            "relationships.showContactPatchOverlayForSelected": relationships.show_contact_patch_overlay_for_selected,
            "relationships.clearContactPatchOverlays": relationships.clear_contact_patch_overlays,
            "relationships.verifySelectedPairFaces": relationships.verify_selected_pair_faces,
            "relationships.verifyAllBboxCandidates": relationships.verify_all_bbox_candidates,
            "relationships.reconcileGeneratorDeclarations": relationships.reconcile_generator_declarations,
            "relationships.connectList": relationships.connect_list,
            "relationships.connectExecute": relationships.connect_execute,
            "relationships.clearRelationshipOverlays": relationships.clear_relationship_overlays,
            "relationships.runOverlaySelfCheck": relationships.run_overlay_selfcheck,
            "relationships.runDay1Smoke": connect_demo.run_day1_smoke,
            "relationships.runDemoFixtureFlow": connect_demo.run_demo_fixture_flow,
            "relationships.runDemoNegativeReport": connect_demo.run_demo_negative_report,
            "relationships.runDemoPackOffline": connect_demo.run_demo_pack_offline,
            "presets.loadLibrary": tools.load_preset_library,
            "presets.saveLibrary": tools.save_preset_library,
            "panelAttributes.searchPanels": panel_attributes.search_panels,
            "panelAttributes.selectByTag": panel_attributes.select_by_tag,
            "panelAttributes.selectPanel": panel_attributes.select_panel,
            "panelAttributes.selectMetadataRecord": panel_attributes.select_metadata_record,
            "panelAttributes.selectMetadataRecords": panel_attributes.select_metadata_records,
            "panelAttributes.scanMetadata": panel_attributes.scan_metadata,
            "panelAttributes.scanSelectedMetadata": panel_attributes.scan_selected_metadata,
            "panelAttributes.checkNestingReady": panel_attributes.check_nesting_ready,
            "panelAttributes.buildNestingOutlines": panel_attributes.build_nesting_outlines,
            "panelAttributes.createNestingZoneLayout": panel_attributes.create_nesting_zone_layout,
            "panelAttributes.createNestingLayoutSketch": panel_attributes.create_nesting_layout_sketch,
            "panelAttributes.exportNestingLayoutDxf": panel_attributes.export_nesting_layout_dxf,
            "panelAttributes.tagScanSelected": panel_attributes.tag_scan_selected,
            "panelAttributes.applyTagScanDrafts": panel_attributes.apply_tag_scan_drafts,
            "panelAttributes.resetAttributeToAuto": panel_attributes.reset_attribute_to_auto,
            "panelAttributes.applyDoorColorToSelection": panel_attributes.apply_door_color_to_selection,
            "panelAttributes.propagateMillingFromHingeCups": panel_attributes.propagate_milling_from_hinge_cups,
            "panelAttributes.diagnoseHingeFaces": panel_attributes.diagnose_hinge_faces,
            "panelAttributes.revertDoorSurfaces": panel_attributes.revert_door_surfaces,
            "panelAttributes.analyzeMillingSurfaces": panel_attributes.analyze_milling_surfaces,
            "panelAttributes.selectMillingFaces": panel_attributes.select_milling_faces,
            "panelAttributes.orientDoorFaces": panel_attributes.orient_door_faces_from_view_point,
            "panelAttributes.captureObservationPoint": panel_attributes.capture_observation_point,
            "panelAttributes.previewObservationPoint": panel_attributes.preview_observation_point,
            "panelAttributes.selectDoorColourFaces": panel_attributes.select_door_colour_faces,
            "panelAttributes.setWorkZones": panel_attributes.set_work_zones,
            "panelAttributes.setAssemblyZone": panel_attributes.set_work_zones,
            "panelAttributes.getWorkZones": panel_attributes.get_work_zones,
            "panelAttributes.getThicknessRules": panel_attributes.get_thickness_rules,
            "panelAttributes.setThicknessRules": panel_attributes.set_thickness_rules,
            "panelAttributes.setThicknessRulesAsDefault": panel_attributes.set_thickness_rules_as_default,
            "panelAttributes.applyThicknessClassification": panel_attributes.apply_thickness_classification,
            "pingPython": self._ping,
            "ui.showConnectOperationsPalette": self._show_ops_palette,
            "palette.close": self._close_palette,
        }
        self.palette_controller = PaletteController(
            self.fusion,
            self.handlers,
            self.PALETTE_ID,
            self.PALETTE_NAME,
            routes,
            html_file="palette.html",
            width=1500,
            height=950,
        )
        self.ops_palette_controller = PaletteController(
            self.fusion,
            self.handlers,
            self.OPS_PALETTE_ID,
            self.OPS_PALETTE_NAME,
            routes,
            html_file="connect_operations_palette.html",
            width=440,
            height=680,
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
        self.ops_command_definition = cmd_defs.itemById(self.OPS_CMD_ID)
        if not self.ops_command_definition:
            self.ops_command_definition = cmd_defs.addButtonDefinition(
                self.OPS_CMD_ID,
                self.OPS_CMD_NAME,
                self.OPS_CMD_DESC,
                "",
            )
        # Purge retired side-contact trial command if a previous install left it behind.
        old_side_cmd = cmd_defs.itemById("unifiedCabinetPluginSideContactCommand")
        if old_side_cmd:
            old_side_cmd.deleteMe()

        on_created = _CommandCreatedHandler(self)
        self.command_definition.commandCreated.add(on_created)
        self.handlers.append(on_created)
        on_ops_created = _OpsCommandCreatedHandler(self)
        self.ops_command_definition.commandCreated.add(on_ops_created)
        self.handlers.append(on_ops_created)

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
            old_ops = self.panel.controls.itemById(self.OPS_CONTROL_ID)
            if old_ops:
                old_ops.deleteMe()
            self.ops_control = self.panel.controls.addCommand(
                self.ops_command_definition, self.OPS_CONTROL_ID
            )
            self.ops_control.isVisible = True
            self.ops_control.isPromoted = False
            self.ops_control.isPromotedByDefault = False
            old_side = self.panel.controls.itemById("unifiedCabinetPluginSideContactControl")
            if old_side:
                old_side.deleteMe()

        self.show_palette()

    def stop(self):
        _app, ui = self.fusion.get_app_ui() if self.fusion else (None, None)
        try:
            from nesting.engines.deepnest_bridge_client import shutdown_pool

            shutdown_pool()
        except Exception:
            pass
        try:
            if self.ops_control:
                self.ops_control.deleteMe()
                self.ops_control = None
            if self.control:
                self.control.deleteMe()
                self.control = None
            if self.panel:
                self.panel.deleteMe()
                self.panel = None
            if self.ops_palette_controller:
                self.ops_palette_controller.hide()
                self.ops_palette_controller = None
            if self.palette_controller:
                self.palette_controller.hide()
                self.palette_controller = None
            if self.ops_command_definition:
                self.ops_command_definition.deleteMe()
                self.ops_command_definition = None
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

    def show_ops_palette(self):
        if self.ops_palette_controller:
            self.ops_palette_controller.show()

    def _show_ops_palette(self, _payload, _palette):
        self.show_ops_palette()
        return "connectOperationsPaletteResult", {
            "ok": True,
            "action": "ui.showConnectOperationsPalette",
            "visible": True,
        }

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

    def _close_palette(self, _payload, palette_controller):
        # Hide only — avoid deleteMe() while still inside the HTML event handler.
        palette = getattr(palette_controller, "palette", None)
        if palette:
            try:
                palette.isVisible = False
            except Exception:
                pass
        return None


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


class _OpsCommandCreatedHandler(adsk.core.CommandCreatedEventHandler):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def notify(self, args):
        try:
            command = args.command
            on_execute = _ShowOpsPaletteExecuteHandler(self.app)
            command.execute.add(on_execute)
            self.app.handlers.append(on_execute)
        except Exception:
            app = adsk.core.Application.get()
            ui = app.userInterface if app else None
            if ui:
                ui.messageBox("CabinetNC ops command failed:\n{}".format(traceback.format_exc()))


class _ShowPaletteExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def notify(self, _args):
        self.app.show_palette()


class _ShowOpsPaletteExecuteHandler(adsk.core.CommandEventHandler):
    def __init__(self, app):
        super().__init__()
        self.app = app

    def notify(self, _args):
        self.app.show_ops_palette()


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
