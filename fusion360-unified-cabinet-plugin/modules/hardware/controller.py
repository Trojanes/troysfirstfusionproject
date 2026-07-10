import json
import time
import traceback
from typing import Any, Dict

import adsk.core
import adsk.fusion

from face_attribute_store import read_face_metadata
from face_metadata_service import FaceMetadataService
from face_models import FACE_CLASS_EDGE, FACE_CLASS_SURFACE
from face_models import SURFACE_MODE_DOUBLE_SIDED
from geometry_ops import ATTRIBUTE_GROUP, mm_to_cm, sanitize_token
from modules.general_tall.fusion_adapter import _add_box_body
from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, PANEL_METADATA_ATTR

from screw_hole_from_relationship import (
    build_cut_success_report,
    plan_screw_hole_cut_from_relationship,
    preview_screw_holes_from_relationship,
)
from relationship_screw_hole_fusion import (
    create_host_drawer_runner_hole_cut,
    create_host_hinge_hole_cut,
    create_host_screw_hole_cut,
)
from relationship_tongue_groove_fusion import (
    create_host_groove_cut,
    create_host_lock_pocket_cut,
    create_target_tongue_cut,
)
from hardware_rule_engine import (
    HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
    HARDWARE_TYPE_HINGE_HOLE,
    HARDWARE_TYPE_LOCK_CUTOUT,
    HARDWARE_TYPE_SCREW_HOLE,
    HARDWARE_TYPE_TONGUE_GROOVE,
    dispatch_hardware_cut_plan,
    dispatch_hardware_preview,
    list_hardware_types,
    normalize_hardware_type,
)
from scaffold_hardware_from_relationship import (
    build_hinge_cut_success_report,
    build_lock_cut_success_report,
    build_runner_cut_success_report,
    plan_drawer_runner_hole_cut_from_relationship,
    plan_hinge_hole_cut_from_relationship,
    plan_lock_cutout_from_relationship,
    preview_drawer_runner_holes_from_relationship,
    preview_hinge_holes_from_relationship,
    preview_lock_cutout_from_relationship,
)
from tongue_groove_from_relationship import (
    build_cut_success_report as build_tongue_groove_cut_success_report,
    plan_tongue_groove_cut_from_relationship,
    preview_tongue_groove_from_relationship,
)


class HardwareController:
    def __init__(self, plugin_dir, fusion):
        self.plugin_dir = plugin_dir
        self.fusion = fusion
        self.face_metadata = FaceMetadataService()

    def create_side_contact_holes(self, payload, _palette):
        try:
            root = self.fusion.get_root_component() if self.fusion else None
            if not root:
                return "hardwareCreateHolesResult", {
                    "ok": False,
                    "action": "hardware.createSideContactHoles",
                    "errors": ["No active Fusion design."],
                }

            host_body, target_body, pair_error = self._latest_hardware_test_pair(root)
            if pair_error:
                return "hardwareCreateHolesResult", {
                    "ok": False,
                    "action": "hardware.createSideContactHoles",
                    "errors": [pair_error],
                }

            metadata_errors = self._validate_body_face_metadata(host_body, "Host") + self._validate_body_face_metadata(target_body, "Target")
            if metadata_errors:
                return "hardwareCreateHolesResult", {
                    "ok": False,
                    "action": "hardware.createSideContactHoles",
                    "errors": metadata_errors,
                }

            result = self._calculate_test_side_contact(host_body, target_body, payload or {})
            cut = self._create_host_only_hole_cut(root, host_body, result)
            self.fusion.refresh_viewport()

            return "hardwareCreateHolesResult", {
                "ok": True,
                "action": "hardware.createSideContactHoles",
                "hostBody": host_body.name,
                "targetBody": target_body.name,
                "holeCount": len(result["holes"]),
                "cutFeatureName": getattr(cut, "name", "HW_SIDE_CONTACT_HOLE_CUT"),
                "depthMm": result["cutDepthMm"],
                "warnings": result.get("warnings", []) + ["CUT_DEPTH_OVERSHOOT_APPLIED"],
                "message": "Created host-only drill holes on the Host body.",
            }
        except Exception as ex:
            return "hardwareCreateHolesResult", {
                "ok": False,
                "action": "hardware.createSideContactHoles",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def calculate_side_contact_preview(self, payload, _palette):
        try:
            root = self.fusion.get_root_component() if self.fusion else None
            if not root:
                return "hardwarePreviewResult", {
                    "ok": False,
                    "action": "hardware.calculateSideContactPreview",
                    "errors": ["No active Fusion design."],
                }

            host_body, target_body, pair_error = self._latest_hardware_test_pair(root)
            if pair_error:
                return "hardwarePreviewResult", {
                    "ok": False,
                    "action": "hardware.calculateSideContactPreview",
                    "errors": [pair_error],
                }

            metadata_errors = self._validate_body_face_metadata(host_body, "Host") + self._validate_body_face_metadata(target_body, "Target")
            if metadata_errors:
                return "hardwarePreviewResult", {
                    "ok": False,
                    "action": "hardware.calculateSideContactPreview",
                    "errors": metadata_errors,
                }

            result = self._calculate_test_side_contact(host_body, target_body, payload or {})
            self._draw_side_contact_preview(root, result)
            self.fusion.refresh_viewport()

            return "hardwarePreviewResult", {
                "ok": True,
                "action": "hardware.calculateSideContactPreview",
                "contactType": "DIRECT_SIDE_CONTACT",
                "hostBody": host_body.name,
                "targetBody": target_body.name,
                "projectedWidthMm": result["projectedWidthMm"],
                "contactPathLengthMm": result["contactPathLengthMm"],
                "holeCount": len(result["holes"]),
                "holes": result["holes"],
                "warnings": result.get("warnings", []),
                "message": "Fusion preview sketch created on the Host entry face.",
            }
        except Exception as ex:
            return "hardwarePreviewResult", {
                "ok": False,
                "action": "hardware.calculateSideContactPreview",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def preview_screw_holes_from_relationship(self, payload, _palette):
        try:
            if not isinstance(payload, dict):
                return "hardwareRelationshipPreviewResult", {
                    "ok": False,
                    "action": "hardware.previewScrewHolesFromRelationship",
                    "errors": ["Missing preview payload."],
                    "features": [],
                }

            relationship = payload.get("relationship")
            if not isinstance(relationship, dict):
                return "hardwareRelationshipPreviewResult", {
                    "ok": False,
                    "action": "hardware.previewScrewHolesFromRelationship",
                    "errors": ["Missing relationship object."],
                    "features": [],
                }

            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            panel_snapshots = payload.get("panels") if isinstance(payload.get("panels"), dict) else None

            if panel_snapshots is None:
                panel_snapshots = self._panel_snapshots_from_design(payload, relationship)

            report = preview_screw_holes_from_relationship(
                relationship,
                rule=rule,
                panel_snapshots=panel_snapshots,
            )
            return "hardwareRelationshipPreviewResult", report
        except Exception as ex:
            return "hardwareRelationshipPreviewResult", {
                "ok": False,
                "action": "hardware.previewScrewHolesFromRelationship",
                "errors": [str(ex)],
                "features": [],
                "trace": traceback.format_exc(),
            }

    def create_screw_holes_from_relationship(self, payload, _palette):
        try:
            root = self.fusion.get_root_component() if self.fusion else None
            if not root:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createScrewHolesFromRelationship",
                    "errors": ["No active Fusion design."],
                    "features": [],
                }

            if not isinstance(payload, dict):
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createScrewHolesFromRelationship",
                    "errors": ["Missing create payload."],
                }

            relationship = payload.get("relationship")
            if not isinstance(relationship, dict):
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createScrewHolesFromRelationship",
                    "errors": ["Missing relationship object."],
                }

            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            panel_snapshots = payload.get("panels") if isinstance(payload.get("panels"), dict) else None
            if panel_snapshots is None:
                panel_snapshots = self._panel_snapshots_from_design(payload, relationship)

            plan = plan_screw_hole_cut_from_relationship(
                relationship,
                rule=rule,
                panel_snapshots=panel_snapshots,
            )
            if not plan.get("ok"):
                return "hardwareRelationshipCutResult", plan

            host_panel_id = plan["hostPanelId"]
            target_panel_id = plan["targetPanelId"]
            panels_for_match = panel_snapshots if isinstance(panel_snapshots, dict) else {}
            host_body = self._find_body_by_panel_id(
                root, host_panel_id, panels_for_match.get(host_panel_id)
            )
            target_body = self._find_body_by_panel_id(
                root, target_panel_id, panels_for_match.get(target_panel_id)
            )
            if host_body is None:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createScrewHolesFromRelationship",
                    "errors": ["Host body not found for panelId: {}.".format(host_panel_id)],
                }
            if target_body is None:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createScrewHolesFromRelationship",
                    "errors": ["Target body not found for panelId: {}.".format(target_panel_id)],
                }

            target_volume_before = self._safe_body_volume(target_body)
            host_component = self._body_component(host_body) or root
            cut, metadata_written = create_host_screw_hole_cut(
                host_component,
                host_body,
                plan["feature"],
                plan["metadata"],
            )
            target_volume_after = self._safe_body_volume(target_body)
            target_modified = abs(target_volume_after - target_volume_before) > 0.01

            warnings = []
            if target_modified:
                warnings.append("Target body volume changed unexpectedly after host-only cut.")

            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass

            report = build_cut_success_report(
                relationship_id=plan["relationshipId"],
                host_panel_id=host_panel_id,
                target_panel_id=target_panel_id,
                host_body_name=str(getattr(host_body, "name", "") or ""),
                target_body_name=str(getattr(target_body, "name", "") or ""),
                cut_feature_name=str(getattr(cut, "name", "") or "HW_REL_SCREW_HOLE"),
                metadata=plan["metadata"],
                metadata_written=metadata_written,
                warnings=warnings,
            )
            writeback_report: Dict[str, Any] = {}
            try:
                import importlib

                import panel_metadata_writeback

                panel_metadata_writeback = importlib.reload(panel_metadata_writeback)
                writeback_report = panel_metadata_writeback.writeback_screw_hole_feature(
                    host_body,
                    plan.get("feature") or {},
                    plan.get("metadata") or {},
                    cut_feature_name=str(getattr(cut, "name", "") or ""),
                )
                report["panelWriteback"] = writeback_report.get("panelWriteback")
                report["panelFeatureCount"] = writeback_report.get("featureCount")
                report["panelWritebackSkipped"] = writeback_report.get("skipped")
                if writeback_report.get("errors"):
                    report.setdefault("warnings", []).extend(writeback_report["errors"])
            except Exception as ex:
                report.setdefault("warnings", []).append("Panel metadata writeback failed: {}".format(ex))
                report["panelWriteback"] = False
            report["writeback"] = writeback_report
            if target_modified:
                report["ok"] = False
                report["errors"] = ["Target body was modified during host-only screw-hole cut."]
                report["audit"]["errors"] = report["errors"]
            report["targetBodyModified"] = target_modified
            report["audit"]["targetBodyModified"] = target_modified
            return "hardwareRelationshipCutResult", report
        except Exception as ex:
            return "hardwareRelationshipCutResult", {
                "ok": False,
                "action": "hardware.createScrewHolesFromRelationship",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def list_hardware_types(self, _payload, _palette):
        try:
            return "hardwareTypesResult", {
                "ok": True,
                "action": "hardware.listHardwareTypes",
                "types": list_hardware_types(),
            }
        except Exception as ex:
            return "hardwareTypesResult", {
                "ok": False,
                "action": "hardware.listHardwareTypes",
                "errors": [str(ex)],
                "types": [],
                "trace": traceback.format_exc(),
            }

    def preview_hardware_from_relationship(self, payload, palette):
        """Route preview by rule.type (Connect UI hardware-type selector)."""
        try:
            if not isinstance(payload, dict):
                return "hardwareRelationshipPreviewResult", {
                    "ok": False,
                    "action": "hardware.previewHardwareFromRelationship",
                    "errors": ["Missing preview payload."],
                    "features": [],
                }
            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            hw_type = normalize_hardware_type(rule)
            if hw_type == HARDWARE_TYPE_SCREW_HOLE:
                event, report = self.preview_screw_holes_from_relationship(payload, palette)
                if isinstance(report, dict):
                    report["hardwareType"] = hw_type
                return event, report
            if hw_type == HARDWARE_TYPE_TONGUE_GROOVE:
                event, report = self.preview_tongue_groove_from_relationship(payload, palette)
                if isinstance(report, dict):
                    report["hardwareType"] = hw_type
                return event, report
            if hw_type == HARDWARE_TYPE_HINGE_HOLE:
                event, report = self.preview_hinge_holes_from_relationship(payload, palette)
                if isinstance(report, dict):
                    report["hardwareType"] = hw_type
                return event, report
            if hw_type == HARDWARE_TYPE_LOCK_CUTOUT:
                event, report = self.preview_lock_cutout_from_relationship(payload, palette)
                if isinstance(report, dict):
                    report["hardwareType"] = hw_type
                return event, report
            if hw_type == HARDWARE_TYPE_DRAWER_RUNNER_HOLE:
                event, report = self.preview_drawer_runner_holes_from_relationship(payload, palette)
                if isinstance(report, dict):
                    report["hardwareType"] = hw_type
                return event, report
            return "hardwareRelationshipPreviewResult", {
                "ok": False,
                "action": "hardware.previewHardwareFromRelationship",
                "errors": ["Unsupported hardware type: {}.".format(hw_type)],
                "features": [],
            }
        except Exception as ex:
            return "hardwareRelationshipPreviewResult", {
                "ok": False,
                "action": "hardware.previewHardwareFromRelationship",
                "errors": [str(ex)],
                "features": [],
                "trace": traceback.format_exc(),
            }

    def create_hardware_from_relationship(self, payload, palette):
        """Route cut by rule.type (Connect UI hardware-type selector)."""
        try:
            if not isinstance(payload, dict):
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createHardwareFromRelationship",
                    "errors": ["Missing create payload."],
                }
            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            hw_type = normalize_hardware_type(rule)
            if hw_type == HARDWARE_TYPE_SCREW_HOLE:
                event, report = self.create_screw_holes_from_relationship(payload, palette)
                if isinstance(report, dict):
                    report["hardwareType"] = hw_type
                return event, report
            if hw_type == HARDWARE_TYPE_TONGUE_GROOVE:
                event, report = self.create_tongue_groove_from_relationship(payload, palette)
                if isinstance(report, dict):
                    report["hardwareType"] = hw_type
                return event, report
            if hw_type == HARDWARE_TYPE_HINGE_HOLE:
                event, report = self.create_hinge_holes_from_relationship(payload, palette)
                if isinstance(report, dict):
                    report["hardwareType"] = hw_type
                return event, report
            if hw_type == HARDWARE_TYPE_LOCK_CUTOUT:
                event, report = self.create_lock_cutout_from_relationship(payload, palette)
                if isinstance(report, dict):
                    report["hardwareType"] = hw_type
                return event, report
            if hw_type == HARDWARE_TYPE_DRAWER_RUNNER_HOLE:
                event, report = self.create_drawer_runner_holes_from_relationship(payload, palette)
                if isinstance(report, dict):
                    report["hardwareType"] = hw_type
                return event, report
            relationship = payload.get("relationship") if isinstance(payload.get("relationship"), dict) else {}
            panel_snapshots = payload.get("panels") if isinstance(payload.get("panels"), dict) else None
            blocked = dispatch_hardware_cut_plan(
                relationship, rule=rule, panel_snapshots=panel_snapshots
            )
            blocked["action"] = "hardware.createHardwareFromRelationship"
            return "hardwareRelationshipCutResult", blocked
        except Exception as ex:
            return "hardwareRelationshipCutResult", {
                "ok": False,
                "action": "hardware.createHardwareFromRelationship",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def preview_hinge_holes_from_relationship(self, payload, _palette):
        try:
            if not isinstance(payload, dict):
                return "hardwareRelationshipPreviewResult", {
                    "ok": False,
                    "action": "hardware.previewHingeHolesFromRelationship",
                    "errors": ["Missing preview payload."],
                    "features": [],
                }
            relationship = payload.get("relationship")
            if not isinstance(relationship, dict):
                return "hardwareRelationshipPreviewResult", {
                    "ok": False,
                    "action": "hardware.previewHingeHolesFromRelationship",
                    "errors": ["Missing relationship object."],
                    "features": [],
                }
            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            panel_snapshots = payload.get("panels") if isinstance(payload.get("panels"), dict) else None
            if panel_snapshots is None:
                panel_snapshots = self._panel_snapshots_from_design(payload, relationship)
            report = preview_hinge_holes_from_relationship(
                relationship,
                rule=rule,
                panel_snapshots=panel_snapshots,
            )
            return "hardwareRelationshipPreviewResult", report
        except Exception as ex:
            return "hardwareRelationshipPreviewResult", {
                "ok": False,
                "action": "hardware.previewHingeHolesFromRelationship",
                "errors": [str(ex)],
                "features": [],
                "trace": traceback.format_exc(),
            }

    def create_hinge_holes_from_relationship(self, payload, _palette):
        try:
            root = self.fusion.get_root_component() if self.fusion else None
            if not root:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createHingeHolesFromRelationship",
                    "errors": ["No active Fusion design."],
                    "features": [],
                }

            if not isinstance(payload, dict):
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createHingeHolesFromRelationship",
                    "errors": ["Missing create payload."],
                }

            relationship = payload.get("relationship")
            if not isinstance(relationship, dict):
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createHingeHolesFromRelationship",
                    "errors": ["Missing relationship object."],
                }

            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            panel_snapshots = payload.get("panels") if isinstance(payload.get("panels"), dict) else None
            if panel_snapshots is None:
                panel_snapshots = self._panel_snapshots_from_design(payload, relationship)

            plan = plan_hinge_hole_cut_from_relationship(
                relationship,
                rule=rule,
                panel_snapshots=panel_snapshots,
            )
            if not plan.get("ok"):
                return "hardwareRelationshipCutResult", plan

            host_panel_id = plan["hostPanelId"]
            target_panel_id = plan["targetPanelId"]
            panels_for_match = panel_snapshots if isinstance(panel_snapshots, dict) else {}
            host_body = self._find_body_by_panel_id(
                root, host_panel_id, panels_for_match.get(host_panel_id)
            )
            target_body = self._find_body_by_panel_id(
                root, target_panel_id, panels_for_match.get(target_panel_id)
            )
            if host_body is None:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createHingeHolesFromRelationship",
                    "errors": ["Host body not found for panelId: {}.".format(host_panel_id)],
                }
            if target_body is None:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createHingeHolesFromRelationship",
                    "errors": ["Target body not found for panelId: {}.".format(target_panel_id)],
                }

            target_volume_before = self._safe_body_volume(target_body)
            host_component = self._body_component(host_body) or root
            cut, metadata_written = create_host_hinge_hole_cut(
                host_component,
                host_body,
                plan["feature"],
                plan["metadata"],
            )
            target_volume_after = self._safe_body_volume(target_body)
            target_modified = abs(target_volume_after - target_volume_before) > 0.01

            warnings = []
            if target_modified:
                warnings.append("Target body volume changed unexpectedly after host-only cut.")

            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass

            report = build_hinge_cut_success_report(
                relationship_id=plan["relationshipId"],
                host_panel_id=host_panel_id,
                target_panel_id=target_panel_id,
                host_body_name=str(getattr(host_body, "name", "") or ""),
                target_body_name=str(getattr(target_body, "name", "") or ""),
                cut_feature_name=str(getattr(cut, "name", "") or "HW_REL_HINGE_HOLE"),
                metadata=plan["metadata"],
                metadata_written=metadata_written,
                warnings=warnings,
            )
            writeback_report: Dict[str, Any] = {}
            try:
                import importlib

                import panel_metadata_writeback

                panel_metadata_writeback = importlib.reload(panel_metadata_writeback)
                writeback_report = panel_metadata_writeback.writeback_hinge_hole_feature(
                    host_body,
                    plan.get("feature") or {},
                    plan.get("metadata") or {},
                    cut_feature_name=str(getattr(cut, "name", "") or ""),
                )
                report["panelWriteback"] = writeback_report.get("panelWriteback")
                report["panelFeatureCount"] = writeback_report.get("featureCount")
                report["panelWritebackSkipped"] = writeback_report.get("skipped")
                if writeback_report.get("errors"):
                    report.setdefault("warnings", []).extend(writeback_report["errors"])
            except Exception as ex:
                report.setdefault("warnings", []).append("Panel metadata writeback failed: {}".format(ex))
                report["panelWriteback"] = False
            report["writeback"] = writeback_report
            if target_modified:
                report["ok"] = False
                report["errors"] = ["Target body was modified during host-only hinge-hole cut."]
                report["audit"]["errors"] = report["errors"]
            report["targetBodyModified"] = target_modified
            report["audit"]["targetBodyModified"] = target_modified
            return "hardwareRelationshipCutResult", report
        except Exception as ex:
            return "hardwareRelationshipCutResult", {
                "ok": False,
                "action": "hardware.createHingeHolesFromRelationship",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def preview_lock_cutout_from_relationship(self, payload, _palette):
        try:
            if not isinstance(payload, dict):
                return "hardwareRelationshipPreviewResult", {
                    "ok": False,
                    "action": "hardware.previewLockCutoutFromRelationship",
                    "errors": ["Missing preview payload."],
                    "features": [],
                }
            relationship = payload.get("relationship")
            if not isinstance(relationship, dict):
                return "hardwareRelationshipPreviewResult", {
                    "ok": False,
                    "action": "hardware.previewLockCutoutFromRelationship",
                    "errors": ["Missing relationship object."],
                    "features": [],
                }
            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            panel_snapshots = payload.get("panels") if isinstance(payload.get("panels"), dict) else None
            if panel_snapshots is None:
                panel_snapshots = self._panel_snapshots_from_design(payload, relationship)
            report = preview_lock_cutout_from_relationship(
                relationship,
                rule=rule,
                panel_snapshots=panel_snapshots,
            )
            return "hardwareRelationshipPreviewResult", report
        except Exception as ex:
            return "hardwareRelationshipPreviewResult", {
                "ok": False,
                "action": "hardware.previewLockCutoutFromRelationship",
                "errors": [str(ex)],
                "features": [],
                "trace": traceback.format_exc(),
            }

    def create_lock_cutout_from_relationship(self, payload, _palette):
        try:
            root = self.fusion.get_root_component() if self.fusion else None
            if not root:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createLockCutoutFromRelationship",
                    "errors": ["No active Fusion design."],
                    "features": [],
                }

            if not isinstance(payload, dict):
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createLockCutoutFromRelationship",
                    "errors": ["Missing create payload."],
                }

            relationship = payload.get("relationship")
            if not isinstance(relationship, dict):
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createLockCutoutFromRelationship",
                    "errors": ["Missing relationship object."],
                }

            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            panel_snapshots = payload.get("panels") if isinstance(payload.get("panels"), dict) else None
            if panel_snapshots is None:
                panel_snapshots = self._panel_snapshots_from_design(payload, relationship)

            plan = plan_lock_cutout_from_relationship(
                relationship,
                rule=rule,
                panel_snapshots=panel_snapshots,
            )
            if not plan.get("ok"):
                return "hardwareRelationshipCutResult", plan

            host_panel_id = plan["hostPanelId"]
            target_panel_id = plan["targetPanelId"]
            panels_for_match = panel_snapshots if isinstance(panel_snapshots, dict) else {}
            host_body = self._find_body_by_panel_id(
                root, host_panel_id, panels_for_match.get(host_panel_id)
            )
            target_body = self._find_body_by_panel_id(
                root, target_panel_id, panels_for_match.get(target_panel_id)
            )
            if host_body is None:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createLockCutoutFromRelationship",
                    "errors": ["Host body not found for panelId: {}.".format(host_panel_id)],
                }
            if target_body is None:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createLockCutoutFromRelationship",
                    "errors": ["Target body not found for panelId: {}.".format(target_panel_id)],
                }

            target_volume_before = self._safe_body_volume(target_body)
            host_component = self._body_component(host_body) or root
            cut, metadata_written = create_host_lock_pocket_cut(
                host_component,
                host_body,
                plan["feature"],
                plan["metadata"],
            )
            target_volume_after = self._safe_body_volume(target_body)
            target_modified = abs(target_volume_after - target_volume_before) > 0.01

            warnings = []
            if target_modified:
                warnings.append("Target body volume changed unexpectedly after host-only cut.")

            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass

            report = build_lock_cut_success_report(
                relationship_id=plan["relationshipId"],
                host_panel_id=host_panel_id,
                target_panel_id=target_panel_id,
                host_body_name=str(getattr(host_body, "name", "") or ""),
                target_body_name=str(getattr(target_body, "name", "") or ""),
                cut_feature_name=str(getattr(cut, "name", "") or "HW_REL_LOCK_POCKET"),
                metadata=plan["metadata"],
                metadata_written=metadata_written,
                warnings=warnings,
            )
            writeback_report: Dict[str, Any] = {}
            try:
                import importlib

                import panel_metadata_writeback

                panel_metadata_writeback = importlib.reload(panel_metadata_writeback)
                writeback_report = panel_metadata_writeback.writeback_lock_cutout_feature(
                    host_body,
                    plan.get("feature") or {},
                    plan.get("metadata") or {},
                    cut_feature_name=str(getattr(cut, "name", "") or ""),
                )
                report["panelWriteback"] = writeback_report.get("panelWriteback")
                report["panelFeatureCount"] = writeback_report.get("featureCount")
                report["panelWritebackSkipped"] = writeback_report.get("skipped")
                if writeback_report.get("errors"):
                    report.setdefault("warnings", []).extend(writeback_report["errors"])
            except Exception as ex:
                report.setdefault("warnings", []).append("Panel metadata writeback failed: {}".format(ex))
                report["panelWriteback"] = False
            report["writeback"] = writeback_report
            if target_modified:
                report["ok"] = False
                report["errors"] = ["Target body was modified during host-only lock-cutout cut."]
                report["audit"]["errors"] = report["errors"]
            report["targetBodyModified"] = target_modified
            report["audit"]["targetBodyModified"] = target_modified
            return "hardwareRelationshipCutResult", report
        except Exception as ex:
            return "hardwareRelationshipCutResult", {
                "ok": False,
                "action": "hardware.createLockCutoutFromRelationship",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def preview_drawer_runner_holes_from_relationship(self, payload, _palette):
        try:
            if not isinstance(payload, dict):
                return "hardwareRelationshipPreviewResult", {
                    "ok": False,
                    "action": "hardware.previewDrawerRunnerHolesFromRelationship",
                    "errors": ["Missing preview payload."],
                    "features": [],
                }
            relationship = payload.get("relationship")
            if not isinstance(relationship, dict):
                return "hardwareRelationshipPreviewResult", {
                    "ok": False,
                    "action": "hardware.previewDrawerRunnerHolesFromRelationship",
                    "errors": ["Missing relationship object."],
                    "features": [],
                }
            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            panel_snapshots = payload.get("panels") if isinstance(payload.get("panels"), dict) else None
            if panel_snapshots is None:
                panel_snapshots = self._panel_snapshots_from_design(payload, relationship)
            report = preview_drawer_runner_holes_from_relationship(
                relationship,
                rule=rule,
                panel_snapshots=panel_snapshots,
            )
            return "hardwareRelationshipPreviewResult", report
        except Exception as ex:
            return "hardwareRelationshipPreviewResult", {
                "ok": False,
                "action": "hardware.previewDrawerRunnerHolesFromRelationship",
                "errors": [str(ex)],
                "features": [],
                "trace": traceback.format_exc(),
            }

    def create_drawer_runner_holes_from_relationship(self, payload, _palette):
        try:
            root = self.fusion.get_root_component() if self.fusion else None
            if not root:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createDrawerRunnerHolesFromRelationship",
                    "errors": ["No active Fusion design."],
                    "features": [],
                }

            if not isinstance(payload, dict):
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createDrawerRunnerHolesFromRelationship",
                    "errors": ["Missing create payload."],
                }

            relationship = payload.get("relationship")
            if not isinstance(relationship, dict):
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createDrawerRunnerHolesFromRelationship",
                    "errors": ["Missing relationship object."],
                }

            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            panel_snapshots = payload.get("panels") if isinstance(payload.get("panels"), dict) else None
            if panel_snapshots is None:
                panel_snapshots = self._panel_snapshots_from_design(payload, relationship)

            plan = plan_drawer_runner_hole_cut_from_relationship(
                relationship,
                rule=rule,
                panel_snapshots=panel_snapshots,
            )
            if not plan.get("ok"):
                return "hardwareRelationshipCutResult", plan

            host_panel_id = plan["hostPanelId"]
            target_panel_id = plan["targetPanelId"]
            panels_for_match = panel_snapshots if isinstance(panel_snapshots, dict) else {}
            host_body = self._find_body_by_panel_id(
                root, host_panel_id, panels_for_match.get(host_panel_id)
            )
            target_body = self._find_body_by_panel_id(
                root, target_panel_id, panels_for_match.get(target_panel_id)
            )
            if host_body is None:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createDrawerRunnerHolesFromRelationship",
                    "errors": ["Host body not found for panelId: {}.".format(host_panel_id)],
                }
            if target_body is None:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createDrawerRunnerHolesFromRelationship",
                    "errors": ["Target body not found for panelId: {}.".format(target_panel_id)],
                }

            target_volume_before = self._safe_body_volume(target_body)
            host_component = self._body_component(host_body) or root
            cut, metadata_written = create_host_drawer_runner_hole_cut(
                host_component,
                host_body,
                plan["feature"],
                plan["metadata"],
            )
            target_volume_after = self._safe_body_volume(target_body)
            target_modified = abs(target_volume_after - target_volume_before) > 0.01

            warnings = []
            if target_modified:
                warnings.append("Target body volume changed unexpectedly after host-only cut.")

            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass

            report = build_runner_cut_success_report(
                relationship_id=plan["relationshipId"],
                host_panel_id=host_panel_id,
                target_panel_id=target_panel_id,
                host_body_name=str(getattr(host_body, "name", "") or ""),
                target_body_name=str(getattr(target_body, "name", "") or ""),
                cut_feature_name=str(getattr(cut, "name", "") or "HW_REL_RUNNER_HOLE"),
                metadata=plan["metadata"],
                metadata_written=metadata_written,
                warnings=warnings,
            )
            writeback_report: Dict[str, Any] = {}
            try:
                import importlib

                import panel_metadata_writeback

                panel_metadata_writeback = importlib.reload(panel_metadata_writeback)
                writeback_report = panel_metadata_writeback.writeback_drawer_runner_hole_feature(
                    host_body,
                    plan.get("feature") or {},
                    plan.get("metadata") or {},
                    cut_feature_name=str(getattr(cut, "name", "") or ""),
                )
                report["panelWriteback"] = writeback_report.get("panelWriteback")
                report["panelFeatureCount"] = writeback_report.get("featureCount")
                report["panelWritebackSkipped"] = writeback_report.get("skipped")
                if writeback_report.get("errors"):
                    report.setdefault("warnings", []).extend(writeback_report["errors"])
            except Exception as ex:
                report.setdefault("warnings", []).append("Panel metadata writeback failed: {}".format(ex))
                report["panelWriteback"] = False
            report["writeback"] = writeback_report
            if target_modified:
                report["ok"] = False
                report["errors"] = ["Target body was modified during host-only drawer-runner-hole cut."]
                report["audit"]["errors"] = report["errors"]
            report["targetBodyModified"] = target_modified
            report["audit"]["targetBodyModified"] = target_modified
            return "hardwareRelationshipCutResult", report
        except Exception as ex:
            return "hardwareRelationshipCutResult", {
                "ok": False,
                "action": "hardware.createDrawerRunnerHolesFromRelationship",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def preview_tongue_groove_from_relationship(self, payload, _palette):
        try:
            if not isinstance(payload, dict):
                return "hardwareRelationshipPreviewResult", {
                    "ok": False,
                    "action": "hardware.previewTongueGrooveFromRelationship",
                    "errors": ["Missing preview payload."],
                    "features": [],
                }
            relationship = payload.get("relationship")
            if not isinstance(relationship, dict):
                return "hardwareRelationshipPreviewResult", {
                    "ok": False,
                    "action": "hardware.previewTongueGrooveFromRelationship",
                    "errors": ["Missing relationship object."],
                    "features": [],
                }
            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            panel_snapshots = payload.get("panels") if isinstance(payload.get("panels"), dict) else None
            if panel_snapshots is None:
                panel_snapshots = self._panel_snapshots_from_design(payload, relationship)
            report = preview_tongue_groove_from_relationship(
                relationship,
                rule=rule,
                panel_snapshots=panel_snapshots,
            )
            return "hardwareRelationshipPreviewResult", report
        except Exception as ex:
            return "hardwareRelationshipPreviewResult", {
                "ok": False,
                "action": "hardware.previewTongueGrooveFromRelationship",
                "errors": [str(ex)],
                "features": [],
                "trace": traceback.format_exc(),
            }

    def create_tongue_groove_from_relationship(self, payload, _palette):
        try:
            root = self.fusion.get_root_component() if self.fusion else None
            if not root:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createTongueGrooveFromRelationship",
                    "errors": ["No active Fusion design."],
                    "features": [],
                }

            if not isinstance(payload, dict):
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createTongueGrooveFromRelationship",
                    "errors": ["Missing create payload."],
                }

            relationship = payload.get("relationship")
            if not isinstance(relationship, dict):
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createTongueGrooveFromRelationship",
                    "errors": ["Missing relationship object."],
                }

            rule = payload.get("rule") if isinstance(payload.get("rule"), dict) else {}
            panel_snapshots = payload.get("panels") if isinstance(payload.get("panels"), dict) else None
            if panel_snapshots is None:
                panel_snapshots = self._panel_snapshots_from_design(payload, relationship)

            plan = plan_tongue_groove_cut_from_relationship(
                relationship,
                rule=rule,
                panel_snapshots=panel_snapshots,
            )
            if not plan.get("ok"):
                return "hardwareRelationshipCutResult", plan

            host_panel_id = plan["hostPanelId"]
            target_panel_id = plan["targetPanelId"]
            panels_for_match = panel_snapshots if isinstance(panel_snapshots, dict) else {}
            host_body = self._find_body_by_panel_id(
                root, host_panel_id, panels_for_match.get(host_panel_id)
            )
            target_body = self._find_body_by_panel_id(
                root, target_panel_id, panels_for_match.get(target_panel_id)
            )
            if host_body is None:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createTongueGrooveFromRelationship",
                    "errors": ["Host body not found for panelId: {}.".format(host_panel_id)],
                }
            if target_body is None:
                return "hardwareRelationshipCutResult", {
                    "ok": False,
                    "action": "hardware.createTongueGrooveFromRelationship",
                    "errors": ["Target body not found for panelId: {}.".format(target_panel_id)],
                }

            host_volume_before = self._safe_body_volume(host_body)
            target_volume_before = self._safe_body_volume(target_body)
            host_component = self._body_component(host_body) or root
            target_component = self._body_component(target_body) or root
            groove_cut, groove_metadata_written = create_host_groove_cut(
                host_component,
                host_body,
                plan["feature"],
                plan["metadata"],
            )
            tongue_cuts, tongue_metadata_written = create_target_tongue_cut(
                target_component,
                target_body,
                plan["feature"],
                plan["metadata"],
            )
            host_volume_after = self._safe_body_volume(host_body)
            target_volume_after = self._safe_body_volume(target_body)
            host_modified = abs(host_volume_after - host_volume_before) > 0.01
            target_modified = abs(target_volume_after - target_volume_before) > 0.01
            metadata_written = bool(groove_metadata_written and tongue_metadata_written)
            tongue_feature_name = str(getattr(tongue_cuts[0], "name", "") or "") if tongue_cuts else ""

            warnings = list(plan.get("warnings") or [])
            if not host_modified:
                warnings.append("Host body volume did not change after groove cut.")
            if not target_modified:
                warnings.append("Target body volume did not change after tongue shoulder cuts.")

            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass

            report = build_tongue_groove_cut_success_report(
                relationship_id=plan["relationshipId"],
                host_panel_id=host_panel_id,
                target_panel_id=target_panel_id,
                host_body_name=str(getattr(host_body, "name", "") or ""),
                target_body_name=str(getattr(target_body, "name", "") or ""),
                cut_feature_name=str(getattr(groove_cut, "name", "") or "HW_REL_TONGUE_GROOVE"),
                metadata=plan["metadata"],
                metadata_written=metadata_written,
                warnings=warnings,
                tongue_feature_name=tongue_feature_name,
                host_body_modified=host_modified,
                target_body_modified=target_modified,
            )
            report["tongueFeatureNames"] = [str(getattr(cut, "name", "") or "") for cut in tongue_cuts]
            writeback_report: Dict[str, Any] = {}
            target_writeback_report: Dict[str, Any] = {}
            try:
                import importlib

                import panel_metadata_writeback

                panel_metadata_writeback = importlib.reload(panel_metadata_writeback)
                writeback_report = panel_metadata_writeback.writeback_tongue_groove_feature(
                    host_body,
                    plan.get("feature") or {},
                    plan.get("metadata") or {},
                    cut_feature_name=str(getattr(groove_cut, "name", "") or ""),
                    role="groove",
                )
                target_writeback_report = panel_metadata_writeback.writeback_tongue_groove_feature(
                    target_body,
                    plan.get("feature") or {},
                    plan.get("metadata") or {},
                    cut_feature_name=tongue_feature_name,
                    role="tongue",
                )
                report["panelWriteback"] = writeback_report.get("panelWriteback")
                report["panelFeatureCount"] = writeback_report.get("featureCount")
                report["panelWritebackSkipped"] = writeback_report.get("skipped")
                report["targetPanelWriteback"] = target_writeback_report.get("panelWriteback")
                report["targetPanelFeatureCount"] = target_writeback_report.get("featureCount")
                report["targetPanelWritebackSkipped"] = target_writeback_report.get("skipped")
                for wb in (writeback_report, target_writeback_report):
                    if wb.get("errors"):
                        report.setdefault("warnings", []).extend(wb["errors"])
            except Exception as ex:
                report.setdefault("warnings", []).append("Panel metadata writeback failed: {}".format(ex))
                report["panelWriteback"] = False
                report["targetPanelWriteback"] = False
            report["writeback"] = writeback_report
            report["targetWriteback"] = target_writeback_report
            if not host_modified or not target_modified:
                report["ok"] = False
                report["errors"] = [
                    "Expected both host groove and target tongue volume changes; hostModified={} targetModified={}.".format(
                        host_modified, target_modified
                    )
                ]
                report["audit"]["errors"] = report["errors"]
            return "hardwareRelationshipCutResult", report
        except Exception as ex:
            return "hardwareRelationshipCutResult", {
                "ok": False,
                "action": "hardware.createTongueGrooveFromRelationship",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def _panel_snapshots_from_design(self, payload, relationship):
        if not self.fusion:
            return None
        roles = relationship.get("roles") or {}
        host_id = str(roles.get("hostPanelId") or "").strip()
        target_id = str(roles.get("targetPanelId") or "").strip()
        if not host_id or not target_id:
            return None

        try:
            import importlib
            from modules.relationships import relationship_service as rel_service_module

            rel_service_module = importlib.reload(rel_service_module)
            service = rel_service_module.RelationshipService(self.fusion)
            snapshots = service.collect_panels_from_design()
            panel_map = {item.panelId: item.to_dict() for item in snapshots}
            if host_id in panel_map and target_id in panel_map:
                return {host_id: panel_map[host_id], target_id: panel_map[target_id]}
        except Exception:
            return None
        return None

    def create_side_contact_test_boards(self, _payload, _palette):
        try:
            root = self.fusion.get_root_component() if self.fusion else None
            if not root:
                return "hardwareResult", {
                    "ok": False,
                    "action": "hardware.createSideContactTestBoards",
                    "errors": ["No active Fusion design."],
                }

            run_id = time.strftime("%H%M%S")
            assembly_name = "HW_SIDE_CONTACT_TEST_{}".format(run_id)
            assembly = self._new_component(root, assembly_name)
            created = []

            host_component = self._new_component(assembly, "HW_TEST_HOST_PANEL")
            host_body, host_error = _add_box_body(
                host_component,
                "HOST_300x300x15",
                {"x0": 0.0, "x1": 300.0, "y0": 0.0, "y1": 15.0, "z0": 0.0, "z1": 300.0},
                body_prefix="HWTEST",
                module_name="hardware",
                move_prefix="HW_TEST_MOVE_",
            )
            if host_error:
                raise RuntimeError(host_error)
            created.append(self._initialize_panel_metadata(host_component, host_body, "HW-HOST-{}".format(run_id), "Host side-contact test panel"))

            target_component = self._new_component(assembly, "HW_TEST_TARGET_PANEL")
            target_body, target_error = _add_box_body(
                target_component,
                "TARGET_300x300x15",
                {"x0": 142.5, "x1": 157.5, "y0": 15.0, "y1": 315.0, "z0": 0.0, "z1": 300.0},
                body_prefix="HWTEST",
                module_name="hardware",
                move_prefix="HW_TEST_MOVE_",
            )
            if target_error:
                raise RuntimeError(target_error)
            created.append(self._initialize_panel_metadata(target_component, target_body, "HW-TARGET-{}".format(run_id), "Target side-contact test panel"))

            try:
                assembly.attributes.add(ATTRIBUTE_GROUP, "module", "hardware")
                assembly.attributes.add(ATTRIBUTE_GROUP, "testFixture", "sideContactDrillHole")
            except Exception:
                pass

            warnings = []
            try:
                selected_count = self.fusion.select_bodies_and_fit([item["body"] for item in created])
            except Exception as ex:
                selected_count = 0
                warnings.append("Test boards were created, but automatic body selection failed: {}".format(ex))
            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass

            return "hardwareResult", {
                "ok": True,
                "action": "hardware.createSideContactTestBoards",
                "assemblyComponentName": assembly.name,
                "createdBodies": len(created),
                "selectedBodies": selected_count,
                "boards": [
                    {
                        "role": item["role"],
                        "componentName": item["componentName"],
                        "bodyName": item["bodyName"],
                        "panelId": item["panelId"],
                        "surfaceFaceCount": item["surfaceFaceCount"],
                        "edgeFaceCount": item["edgeFaceCount"],
                    }
                    for item in created
                ],
                "warnings": warnings,
                "message": "Created two 300 x 300 x 15 mm side-contact test boards with face metadata.",
            }
        except Exception as ex:
            return "hardwareResult", {
                "ok": False,
                "action": "hardware.createSideContactTestBoards",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def _new_component(self, parent_component, name):
        transform = adsk.core.Matrix3D.create()
        occurrence = parent_component.occurrences.addNewComponent(transform)
        component = occurrence.component
        component.name = name
        return component

    def _latest_hardware_test_pair(self, root):
        bodies = []
        self._walk_bodies(root, bodies)
        test_bodies = []
        for component, body in bodies:
            role = self._body_attr(body, "hardwareTestRole")
            panel_id = self._body_attr(body, "panelId")
            if role in ("HOST", "TARGET") and panel_id:
                test_bodies.append({"component": component, "body": body, "role": role, "panelId": panel_id})
        if not test_bodies:
            return None, None, "No hardware test bodies found. Click Create 2 Test Boards first."

        suffixes = sorted({item["panelId"].split("-")[-1] for item in test_bodies}, reverse=True)
        for suffix in suffixes:
            host = next((item for item in test_bodies if item["role"] == "HOST" and item["panelId"].endswith(suffix)), None)
            target = next((item for item in test_bodies if item["role"] == "TARGET" and item["panelId"].endswith(suffix)), None)
            if host and target:
                return host["body"], target["body"], None
        return None, None, "Could not find a matching HOST/TARGET hardware test pair."

    def _walk_bodies(self, component, sink):
        if not component:
            return
        try:
            for index in range(component.bRepBodies.count):
                sink.append((component, component.bRepBodies.item(index)))
        except Exception:
            pass
        try:
            for index in range(component.occurrences.count):
                self._walk_bodies(component.occurrences.item(index).component, sink)
        except Exception:
            pass

    def _body_attr(self, body, name):
        try:
            attr = body.attributes.itemByName(ATTRIBUTE_GROUP, name)
            return str(attr.value) if attr and attr.value is not None else ""
        except Exception:
            return ""

    def _validate_body_face_metadata(self, body, label):
        surface_count = 0
        edge_count = 0
        errors = []
        for face in self._body_faces(body):
            metadata, error = read_face_metadata(face)
            if error:
                errors.append("{} face metadata error: {}".format(label, error))
                continue
            if not metadata:
                errors.append("{} has a face without metadata.".format(label))
                continue
            face_class = metadata.get("faceClass")
            if face_class == FACE_CLASS_SURFACE:
                surface_count += 1
            elif face_class == FACE_CLASS_EDGE:
                edge_count += 1
            else:
                errors.append("{} has a face with invalid faceClass: {}".format(label, face_class))
        if surface_count < 2:
            errors.append("{} requires at least two SURFACE faces; found {}.".format(label, surface_count))
        if edge_count < 4:
            errors.append("{} requires at least four EDGE faces; found {}.".format(label, edge_count))
        return errors

    def _calculate_test_side_contact(self, host_body, target_body, payload):
        host = self._bbox_mm(host_body)
        target = self._bbox_mm(target_body)
        gap = target["y0"] - host["y1"]
        if abs(gap) > 1.0:
            raise ValueError("NO_VALID_SIDE_CONTACT: expected Target y0 to contact Host y1; gap is {:.3f} mm.".format(gap))

        x0 = max(host["x0"], target["x0"])
        x1 = min(host["x1"], target["x1"])
        z0 = max(host["z0"], target["z0"])
        z1 = min(host["z1"], target["z1"])
        if x1 <= x0 or z1 <= z0:
            raise ValueError("NO_VALID_SIDE_CONTACT: projected target footprint does not overlap host entry face.")

        center_x = (x0 + x1) / 2.0
        start_z = z0
        end_z = z1
        holes = self._hole_positions(center_x, start_z, end_z, payload)
        return {
            "hostEntryY": host["y0"],
            "hostContactY": host["y1"],
            "projectedX0": x0,
            "projectedX1": x1,
            "projectedZ0": z0,
            "projectedZ1": z1,
            "centerX": center_x,
            "projectedWidthMm": round(x1 - x0, 3),
            "contactPathLengthMm": round(end_z - start_z, 3),
            "holes": holes,
            "holeDiameterMm": float(payload.get("holeDiameter") or 3.0),
            "cutDepthMm": self._hole_depth_mm(host, payload),
            "warnings": ["CONTACT_GAP_WITHIN_TOLERANCE"] if abs(gap) > 0.001 else [],
        }

    def _hole_depth_mm(self, host_bbox, payload):
        if bool(payload.get("throughHost", True)):
            return round(abs(host_bbox["y1"] - host_bbox["y0"]) + 0.2, 3)
        custom = float(payload.get("customHoleDepth") or 0.0)
        if custom <= 0:
            raise ValueError("Custom Hole Depth must be greater than zero.")
        return round(custom, 3)

    def _hole_positions(self, center_x, start_z, end_z, payload):
        mode = str(payload.get("patternMode") or "EVEN_DISTRIBUTION")
        length = end_z - start_z
        if length <= 0:
            raise ValueError("Contact path length must be greater than zero.")
        holes = []
        if mode == "SIDE_DISTANCE_HOLE_DISTANCE":
            side_distance = max(0.0, float(payload.get("sideDistance") or 50.0))
            hole_distance = max(0.1, float(payload.get("holeDistance") or 200.0))
            reverse = bool(payload.get("startSideReversed"))
            z = start_z + side_distance
            while z <= end_z + 1e-6:
                holes.append(z)
                z += hole_distance
            if reverse:
                holes = [end_z - (z - start_z) for z in holes]
                holes.sort()
        else:
            hole_number = max(1, int(float(payload.get("holeNumber") or 2)))
            side_distance = max(0.0, float(payload.get("sideDistance") or 50.0))
            if hole_number == 1:
                holes = [(start_z + end_z) / 2.0]
            else:
                usable_start = start_z + side_distance
                usable_end = end_z - side_distance
                if usable_end < usable_start:
                    raise ValueError("SIDE_DISTANCE_TOO_LARGE")
                step = (usable_end - usable_start) / float(hole_number - 1)
                holes = [usable_start + step * index for index in range(hole_number)]
        if not holes:
            raise ValueError("SIDE_DISTANCE_TOO_LARGE")
        return [
            {"index": index + 1, "center": [round(center_x, 3), round(z, 3)], "xMm": round(center_x, 3), "zMm": round(z, 3)}
            for index, z in enumerate(holes)
        ]

    def _draw_side_contact_preview(self, component, result):
        self._delete_hardware_preview_sketches(component)
        construction = component.constructionPlanes
        plane_input = construction.createInput()
        plane_input.setByOffset(component.xZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(result["hostEntryY"])))
        plane = construction.add(plane_input)
        plane.name = "HW_SIDE_CONTACT_PREVIEW_PLANE"
        sketch = component.sketches.add(plane)
        sketch.name = "HW_SIDE_CONTACT_PREVIEW"
        lines = sketch.sketchCurves.sketchLines
        circles = sketch.sketchCurves.sketchCircles
        y = result["hostEntryY"]
        x0 = result["projectedX0"]
        x1 = result["projectedX1"]
        z0 = result["projectedZ0"]
        z1 = result["projectedZ1"]
        self._sketch_line(sketch, lines, x0, y, z0, x1, y, z0)
        self._sketch_line(sketch, lines, x1, y, z0, x1, y, z1)
        self._sketch_line(sketch, lines, x1, y, z1, x0, y, z1)
        self._sketch_line(sketch, lines, x0, y, z1, x0, y, z0)
        self._sketch_line(sketch, lines, result["centerX"], y, z0, result["centerX"], y, z1)
        radius = max(0.1, result["holeDiameterMm"] / 2.0)
        for hole in result["holes"]:
            center = adsk.core.Point3D.create(mm_to_cm(hole["xMm"]), mm_to_cm(y), mm_to_cm(hole["zMm"]))
            circles.addByCenterRadius(sketch.modelToSketchSpace(center), mm_to_cm(radius))

    def _create_host_only_hole_cut(self, component, host_body, result):
        sketch, plane = self._create_hole_circle_sketch(component, result, "HW_SIDE_CONTACT_HOLE_CUT_SKETCH")
        profiles = adsk.core.ObjectCollection.create()
        for index in range(sketch.profiles.count):
            profiles.add(sketch.profiles.item(index))
        if profiles.count < 1:
            raise ValueError("No hole profiles were created for cut.")

        extrudes = component.features.extrudeFeatures
        ext_input = extrudes.createInput(profiles, adsk.fusion.FeatureOperations.CutFeatureOperation)
        ext_input.setDistanceExtent(False, adsk.core.ValueInput.createByReal(mm_to_cm(result["cutDepthMm"])))

        try:
            ext_input.participantBodies = [host_body]
        except Exception as ex:
            try:
                participants = adsk.core.ObjectCollection.create()
                participants.add(host_body)
                ext_input.participantBodies = participants
            except Exception:
                raise ValueError("HOST_ONLY_CUT_NOT_AVAILABLE: {}".format(ex))

        cut = extrudes.add(ext_input)
        cut.name = "HW_SIDE_CONTACT_HOLE_CUT_{}".format(sanitize_token(str(int(time.time())), limit=40))
        try:
            cut.attributes.add(ATTRIBUTE_GROUP, "operationType", "DRILL_HOLE_SIDE_CONTACT")
            cut.attributes.add(ATTRIBUTE_GROUP, "hostBodyName", host_body.name)
            cut.attributes.add(ATTRIBUTE_GROUP, "holeCount", str(len(result["holes"])))
        except Exception:
            pass
        self._delete_entity(sketch)
        self._delete_entity(plane)
        self._delete_hardware_preview_sketches(component)
        return cut

    def _create_hole_circle_sketch(self, component, result, name):
        construction = component.constructionPlanes
        plane_input = construction.createInput()
        plane_input.setByOffset(component.xZConstructionPlane, adsk.core.ValueInput.createByReal(mm_to_cm(result["hostEntryY"])))
        plane = construction.add(plane_input)
        plane.name = "{}_PLANE".format(name)
        sketch = component.sketches.add(plane)
        sketch.name = name
        circles = sketch.sketchCurves.sketchCircles
        y = result["hostEntryY"]
        radius = max(0.1, result["holeDiameterMm"] / 2.0)
        for hole in result["holes"]:
            center = adsk.core.Point3D.create(mm_to_cm(hole["xMm"]), mm_to_cm(y), mm_to_cm(hole["zMm"]))
            circles.addByCenterRadius(sketch.modelToSketchSpace(center), mm_to_cm(radius))
        return sketch, plane

    def _delete_hardware_preview_sketches(self, component):
        try:
            for index in range(component.sketches.count - 1, -1, -1):
                sketch = component.sketches.item(index)
                if str(getattr(sketch, "name", "") or "").startswith("HW_SIDE_CONTACT_PREVIEW"):
                    sketch.deleteMe()
        except Exception:
            pass

    def _delete_entity(self, entity):
        try:
            if entity:
                entity.deleteMe()
        except Exception:
            pass
        try:
            for index in range(component.constructionPlanes.count - 1, -1, -1):
                plane = component.constructionPlanes.item(index)
                if str(getattr(plane, "name", "") or "").startswith("HW_SIDE_CONTACT_PREVIEW"):
                    plane.deleteMe()
        except Exception:
            pass

    def _sketch_line(self, sketch, lines, x0, y0, z0, x1, y1, z1):
        p0 = adsk.core.Point3D.create(mm_to_cm(x0), mm_to_cm(y0), mm_to_cm(z0))
        p1 = adsk.core.Point3D.create(mm_to_cm(x1), mm_to_cm(y1), mm_to_cm(z1))
        return lines.addByTwoPoints(sketch.modelToSketchSpace(p0), sketch.modelToSketchSpace(p1))

    def _bbox_mm(self, body):
        bbox = body.boundingBox
        return {
            "x0": bbox.minPoint.x * 10.0,
            "x1": bbox.maxPoint.x * 10.0,
            "y0": bbox.minPoint.y * 10.0,
            "y1": bbox.maxPoint.y * 10.0,
            "z0": bbox.minPoint.z * 10.0,
            "z1": bbox.maxPoint.z * 10.0,
        }

    def _initialize_panel_metadata(self, component, body, panel_id, description):
        if not component or not body:
            raise ValueError("Missing test component or body")

        role = "HOST" if "HOST" in str(panel_id).upper() else "TARGET"
        faces = self._body_faces(body)
        if len(faces) < 6:
            raise ValueError("{} expected at least 6 faces, found {}".format(body.name, len(faces)))

        ranked = sorted(faces, key=self._face_area, reverse=True)
        surface_faces = ranked[:2]
        edge_faces = [face for face in faces if face not in surface_faces]
        panel_context = {
            "panelId": panel_id,
            "componentName": component.name,
            "bodyName": body.name,
            "body": body,
        }

        created_face_ids = []
        surface_result = self.face_metadata.initialize_carcass_surfaces(
            surface_faces,
            panel_id,
            panel_context=panel_context,
        )
        for metadata in surface_result.get("surfaceFaces") or []:
            created_face_ids.append(metadata["faceId"])

        for face in edge_faces:
            metadata = self.face_metadata.initialize_edge_face(
                face,
                panel_id,
                {
                    "required": False,
                    "bandingCode": 0,
                    "finishId": "raw-core",
                    "finishName": "Raw Core",
                },
                panel_context=panel_context,
            )
            created_face_ids.append(metadata["faceId"])

        registry = self.face_metadata.build_panel_face_registry(SURFACE_MODE_DOUBLE_SIDED, created_face_ids)
        panel_metadata = {
            "schemaVersion": 1,
            "panelId": panel_id,
            "panelType": "CARCASS",
            "description": description,
            "tags": ["hardware-test", "side-contact", role.lower()],
            "thicknessMm": 15.0,
            **registry,
        }

        self._write_panel_metadata(component, panel_id, panel_metadata)
        try:
            body.attributes.add(ATTRIBUTE_GROUP, "panelId", panel_id)
            body.attributes.add(ATTRIBUTE_GROUP, "hardwareTestRole", role)
        except Exception:
            pass

        return {
            "role": role,
            "componentName": component.name,
            "bodyName": body.name,
            "panelId": panel_id,
            "surfaceFaceCount": len(surface_faces),
            "edgeFaceCount": len(edge_faces),
            "body": body,
        }

    def _write_panel_metadata(self, component, panel_id, panel_metadata):
        payload = json.dumps(panel_metadata, ensure_ascii=False, separators=(",", ":"))
        attrs = component.attributes
        self._set_attribute(attrs, PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, panel_id)
        self._set_attribute(attrs, PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR, payload)

    def _set_attribute(self, attrs, group, name, value):
        existing = attrs.itemByName(group, name) if attrs else None
        if existing:
            existing.value = str(value)
        else:
            attrs.add(group, name, str(value))

    def _body_faces(self, body):
        faces = []
        for index in range(body.faces.count):
            faces.append(body.faces.item(index))
        return faces

    def _face_area(self, face):
        try:
            return float(face.area)
        except Exception:
            return 0.0

    def _find_body_by_panel_id(self, root, panel_id, panel_snapshot=None):
        panel_id = str(panel_id or "").strip()
        if not panel_id or not root:
            return None

        try:
            from panel_body_resolver import list_solid_bodies
        except Exception:
            return None

        matches = []

        def walk(component):
            for body in list_solid_bodies(component):
                if self._body_matches_panel_id(body, panel_id):
                    matches.append(body)
            try:
                occurrences = component.occurrences
                count = occurrences.count if occurrences else 0
            except Exception:
                return
            for index in range(count):
                walk(occurrences.item(index).component)

        walk(root)
        if not matches:
            return None
        if isinstance(panel_snapshot, dict) and isinstance(panel_snapshot.get("bbox"), dict):
            return self._pick_body_matching_snapshot(matches, panel_snapshot) or matches[-1]
        return matches[-1]

    def _pick_body_matching_snapshot(self, bodies, panel_snapshot):
        expected = panel_snapshot.get("bbox") if isinstance(panel_snapshot, dict) else None
        if not isinstance(expected, dict):
            return None
        best = None
        best_score = None
        for body in bodies:
            try:
                actual = self._bbox_mm(body)
            except Exception:
                continue
            score = 0.0
            for key in ("x0", "x1", "y0", "y1", "z0", "z1"):
                try:
                    score += abs(float(actual.get(key, 0.0)) - float(expected.get(key, 0.0)))
                except Exception:
                    score += 1e9
            if best_score is None or score < best_score:
                best_score = score
                best = body
        return best

    def _body_matches_panel_id(self, body, panel_id: str) -> bool:
        if not body or not panel_id:
            return False
        try:
            if str(getattr(body, "name", "") or "") == panel_id:
                return True
        except Exception:
            pass
        if self._body_panel_id(body) == panel_id:
            return True
        try:
            attrs = getattr(body, "attributes", None)
            if attrs is None:
                return False
            for group, name in (
                ("UnifiedCabinet.Panel", "panelId"),
                ("UnifiedCabinetPlugin", "panelId"),
                ("UnifiedCabinetPlugin", "boardId"),
            ):
                attr = attrs.itemByName(group, name)
                if attr is not None and str(getattr(attr, "value", "") or "") == panel_id:
                    return True
        except Exception:
            return False
        return False

    def _body_panel_id(self, body):
        try:
            from modules.relationships.relationship_service import read_panel_metadata

            return str(read_panel_metadata(body).get("panelId") or "").strip()
        except Exception:
            return ""

    def _body_component(self, body):
        for attr_name in ("parentComponent", "component"):
            try:
                component = getattr(body, attr_name)
            except Exception:
                component = None
            if component:
                return component
        return None

    def _safe_body_volume(self, body):
        try:
            volume = getattr(body, "volume", None)
            if volume is not None:
                return float(volume)
        except Exception:
            pass
        try:
            bbox = body.boundingBox
            min_pt = bbox.minPoint
            max_pt = bbox.maxPoint
            return abs((max_pt.x - min_pt.x) * (max_pt.y - min_pt.y) * (max_pt.z - min_pt.z))
        except Exception:
            return 0.0
