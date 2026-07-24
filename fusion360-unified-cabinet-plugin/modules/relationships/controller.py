"""Palette / Fusion routes for board relationship detection."""

from __future__ import annotations

import importlib
import traceback
from typing import Any, Dict

from relationship_fixtures import create_relationship_test_fixture, evaluate_fixture_expectations, expected_fixture_cases
from relationship_geometry import CONTACT_TOLERANCE_MM
from relationship_service import RelationshipService


class RelationshipsController:
    def __init__(self, fusion_adapter):
        self.fusion = fusion_adapter
        self.service = RelationshipService(fusion_adapter)

    def _float_param(self, payload: Dict[str, Any], key: str, default: float) -> float:
        if not isinstance(payload, dict):
            return default
        try:
            return float(payload.get(key, default))
        except Exception:
            return default

    def scan(self, payload, _palette):
        try:
            tolerance_mm = self._float_param(payload, "toleranceMm", CONTACT_TOLERANCE_MM)
            include_none = bool(payload.get("includeNone")) if isinstance(payload, dict) else False
            expected = payload.get("expectedFixtures") if isinstance(payload, dict) else None
            report = self.service.scan(
                scope=str((payload or {}).get("scope") or "all"),
                tolerance_mm=tolerance_mm,
                include_none=include_none,
                expected_fixtures=expected,
            )
            report = self._hydrate_scan_report_verifications(report)
            return "relationshipScanResult", report
        except Exception as ex:
            return "relationshipScanResult", {
                "ok": False,
                "action": "relationships.scan",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def scan_selected(self, payload, _palette):
        try:
            tolerance_mm = self._float_param(payload, "toleranceMm", CONTACT_TOLERANCE_MM)
            include_none = bool(payload.get("includeNone")) if isinstance(payload, dict) else False
            selected = self._selected_bodies()
            report = self.service.scan_selected(
                selected,
                tolerance_mm=tolerance_mm,
                include_none=include_none,
            )
            report = self._hydrate_scan_report_verifications(report)
            return "relationshipScanResult", report
        except Exception as ex:
            return "relationshipScanResult", {
                "ok": False,
                "action": "relationships.scanSelected",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def probe_selection(self, _payload, _palette):
        try:
            from relationship_service import build_panel_snapshot, is_panel_body

            selected = self._selected_bodies()
            panel_bodies = [body for body in (selected or []) if is_panel_body(body)]
            snapshots = [build_panel_snapshot(body) for body in panel_bodies[:8]]
            panel_ids = [snap.panelId for snap in snapshots if snap.panelId]
            return "relationshipSelectionResult", {
                "ok": True,
                "action": "relationships.probeSelection",
                "selectedPanelBodyCount": len(panel_bodies),
                "selectedPanelIds": panel_ids,
                "totalSelectedEntities": len(selected or []),
            }
        except Exception as ex:
            return "relationshipSelectionResult", {
                "ok": False,
                "action": "relationships.probeSelection",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def inspect_selected(self, payload, _palette):
        try:
            from relationship_service import build_panel_snapshot, is_panel_body

            tolerance_mm = self._float_param(payload, "toleranceMm", CONTACT_TOLERANCE_MM)
            include_none = bool(payload.get("includeNone")) if isinstance(payload, dict) else False
            selected = self._selected_bodies()
            panel_bodies = [body for body in (selected or []) if is_panel_body(body)]
            if len(panel_bodies) < 2:
                return "relationshipInspectResult", {
                    "ok": False,
                    "action": "relationships.inspectSelected",
                    "selectedPanelBodyCount": len(panel_bodies),
                    "errors": ["Select at least 2 panel bodies to inspect a relationship pair."],
                }
            if len(panel_bodies) == 2:
                panels = [build_panel_snapshot(body) for body in panel_bodies]
                report = self.service.inspect_pair_by_id(
                    panels,
                    panels[0].panelId,
                    panels[1].panelId,
                    tolerance_mm=tolerance_mm,
                )
                if isinstance(report, dict):
                    report["panels"] = [panel.to_dict() for panel in panels]
                    report["selectedPanelIds"] = [panels[0].panelId, panels[1].panelId]
                    self._attach_contact_patch(report, panels)
                return "relationshipInspectResult", report

            report = self.service.scan_selected(
                panel_bodies,
                tolerance_mm=tolerance_mm,
                include_none=include_none,
            )
            return "relationshipScanResult", report
        except Exception as ex:
            return "relationshipInspectResult", {
                "ok": False,
                "action": "relationships.inspectSelected",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def inspect_pair(self, payload, _palette):
        try:
            if not isinstance(payload, dict):
                return "relationshipInspectResult", {
                    "ok": False,
                    "action": "relationships.inspectPair",
                    "errors": ["Missing inspectPair payload."],
                }
            panel_a_id = str(payload.get("panelAId") or "").strip()
            panel_b_id = str(payload.get("panelBId") or "").strip()
            if not panel_a_id or not panel_b_id:
                return "relationshipInspectResult", {
                    "ok": False,
                    "action": "relationships.inspectPair",
                    "errors": ["panelAId and panelBId are required."],
                }
            tolerance_mm = self._float_param(payload, "toleranceMm", CONTACT_TOLERANCE_MM)
            report = self.service.inspect_pair_from_design(
                panel_a_id,
                panel_b_id,
                tolerance_mm=tolerance_mm,
            )
            return "relationshipInspectResult", report
        except Exception as ex:
            return "relationshipInspectResult", {
                "ok": False,
                "action": "relationships.inspectPair",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def _attach_contact_patch(self, report, panels):
        if not isinstance(report, dict):
            return
        relationship = report.get("relationship")
        if not isinstance(relationship, dict):
            return
        from contact_patch import build_contact_patch_from_relationship

        patch_result = build_contact_patch_from_relationship(
            relationship,
            panels[0].to_dict(),
            panels[1].to_dict(),
        )
        if patch_result.get("ok"):
            report["contactPatch"] = patch_result.get("contactPatch")
        else:
            report["contactPatchErrors"] = list(patch_result.get("errors") or [])

    def show_contact_patch_overlay_for_selected(self, payload, _palette):
        try:
            from contact_patch import build_contact_patch_from_relationship
            from contact_patch_overlay_fusion import CONTACT_PATCH_FUSION_BUILD, create_contact_patch_overlay
            from relationship_service import build_panel_snapshot, is_panel_body

            tolerance_mm = self._float_param(payload, "toleranceMm", CONTACT_TOLERANCE_MM)
            selected = self._selected_bodies()
            panel_bodies = [body for body in (selected or []) if is_panel_body(body)]
            if len(panel_bodies) != 2:
                return "contactPatchOverlayResult", {
                    "ok": False,
                    "action": "relationships.showContactPatchOverlayForSelected",
                    "selectedPanelBodyCount": len(panel_bodies),
                    "errors": ["请在 Fusion 中恰好选中 2 个板件实体，然后点击显示接触面。"],
                }

            panels = [build_panel_snapshot(body) for body in panel_bodies]
            inspect_report = self.service.inspect_pair_by_id(
                panels,
                panels[0].panelId,
                panels[1].panelId,
                tolerance_mm=tolerance_mm,
            )
            relationship = inspect_report.get("relationship") if isinstance(inspect_report, dict) else None
            if not isinstance(relationship, dict):
                return "contactPatchOverlayResult", {
                    "ok": False,
                    "action": "relationships.showContactPatchOverlayForSelected",
                    "inspect": inspect_report,
                    "errors": (inspect_report.get("errors") if isinstance(inspect_report, dict) else None)
                    or ["无法为选中板件对分类关系。"],
                }

            panel_dicts = [panel.to_dict() for panel in panels]
            patch_result = build_contact_patch_from_relationship(relationship, panel_dicts[0], panel_dicts[1])
            if not patch_result.get("ok"):
                return "contactPatchOverlayResult", {
                    "ok": False,
                    "action": "relationships.showContactPatchOverlayForSelected",
                    "inspect": inspect_report,
                    "errors": list(patch_result.get("errors") or ["ContactPatch 生成失败。"]),
                }

            contact_patch = patch_result.get("contactPatch") or {}
            panels_map = {panel["panelId"]: panel for panel in panel_dicts if panel.get("panelId")}
            root = self.fusion.get_root_component() if self.fusion else None
            report = create_contact_patch_overlay(
                root,
                relationship,
                contact_patch,
                panels_map,
                source="selected",
            )
            report["inspect"] = inspect_report
            report["selectedPanelIds"] = [panels[0].panelId, panels[1].panelId]
            report["panels"] = panel_dicts
            report["implVersion"] = CONTACT_PATCH_FUSION_BUILD
            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass
            return "contactPatchOverlayResult", report
        except Exception as ex:
            return "contactPatchOverlayResult", {
                "ok": False,
                "action": "relationships.showContactPatchOverlayForSelected",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def clear_contact_patch_overlays(self, _payload, _palette):
        try:
            from contact_patch_overlay_fusion import CONTACT_PATCH_FUSION_BUILD, clear_contact_patch_overlays

            root = self.fusion.get_root_component() if self.fusion else None
            report = clear_contact_patch_overlays(root)
            report["implVersion"] = CONTACT_PATCH_FUSION_BUILD
            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass
            return "contactPatchOverlayResult", report
        except Exception as ex:
            return "contactPatchOverlayResult", {
                "ok": False,
                "action": "relationships.clearContactPatchOverlays",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def show_relationship_overlay_for_selected(self, payload, _palette):
        try:
            from relationship_service import build_panel_snapshot, is_panel_body

            tolerance_mm = self._float_param(payload, "toleranceMm", CONTACT_TOLERANCE_MM)
            selected = self._selected_bodies()
            panel_bodies = [body for body in (selected or []) if is_panel_body(body)]
            if len(panel_bodies) != 2:
                return "relationshipOverlayResult", {
                    "ok": False,
                    "action": "relationships.showRelationshipOverlayForSelected",
                    "selectedPanelBodyCount": len(panel_bodies),
                    "errors": ["Select exactly 2 panel bodies in Fusion, then click Show Overlay For Selected Pair."],
                }

            panels = [build_panel_snapshot(body) for body in panel_bodies]
            inspect_report = self.service.inspect_pair_by_id(
                panels,
                panels[0].panelId,
                panels[1].panelId,
                tolerance_mm=tolerance_mm,
            )
            relationship = inspect_report.get("relationship") if isinstance(inspect_report, dict) else None
            if not isinstance(relationship, dict):
                return "relationshipOverlayResult", {
                    "ok": False,
                    "action": "relationships.showRelationshipOverlayForSelected",
                    "inspect": inspect_report,
                    "errors": (inspect_report.get("errors") if isinstance(inspect_report, dict) else None)
                    or ["Could not classify a relationship for the selected pair."],
                }

            panel_dicts = [panel.to_dict() for panel in panels]
            overlay_payload = {
                "source": "selected",
                "relationship": relationship,
                "scan": {
                    "ok": True,
                    "action": "relationships.inspectSelected",
                    "relationships": [relationship],
                    "panels": panel_dicts,
                    "relationshipCount": 1,
                },
            }
            report = self._show_relationship_overlay(
                overlay_payload,
                action="relationships.showRelationshipOverlayForSelected",
            )
            if isinstance(report, tuple):
                event, payload_out = report
                payload_out["inspect"] = inspect_report
                payload_out["selectedPanelIds"] = [panels[0].panelId, panels[1].panelId]
                payload_out["panels"] = panel_dicts
                return event, payload_out
            return report
        except Exception as ex:
            return "relationshipOverlayResult", {
                "ok": False,
                "action": "relationships.showRelationshipOverlayForSelected",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def verify_selected_pair_faces(self, payload, _palette):
        try:
            from face_verification import VERIFY_ACTION, apply_face_verification_to_relationship, verify_pair_faces
            from face_verification_fusion import extract_faces_for_panel
            from relationship_service import build_panel_snapshot, is_panel_body

            tolerance_mm = self._float_param(payload, "toleranceMm", CONTACT_TOLERANCE_MM)
            selected = self._selected_bodies()
            panel_bodies = [body for body in (selected or []) if is_panel_body(body)]
            if len(panel_bodies) != 2:
                return "relationshipFaceVerifyResult", {
                    "ok": False,
                    "action": VERIFY_ACTION,
                    "selectedPanelBodyCount": len(panel_bodies),
                    "errors": ["Select exactly 2 panel bodies, then click Verify Face Contact For Selected Pair."],
                }

            panels = [build_panel_snapshot(body) for body in panel_bodies]
            panel_dicts = [panel.to_dict() for panel in panels]
            inspect_report = self.service.inspect_pair_by_id(
                panels,
                panels[0].panelId,
                panels[1].panelId,
                tolerance_mm=tolerance_mm,
            )
            relationship = inspect_report.get("relationship") if isinstance(inspect_report, dict) else None
            if not isinstance(relationship, dict):
                return "relationshipFaceVerifyResult", {
                    "ok": False,
                    "action": VERIFY_ACTION,
                    "inspect": inspect_report,
                    "errors": (inspect_report.get("errors") if isinstance(inspect_report, dict) else None)
                    or ["Could not classify a relationship for the selected pair."],
                }

            faces_a = extract_faces_for_panel(panel_bodies[0], panel_dicts[0])
            faces_b = extract_faces_for_panel(panel_bodies[1], panel_dicts[1])
            verify_report = verify_pair_faces(
                relationship,
                panel_dicts[0],
                panel_dicts[1],
                faces_a,
                faces_b,
                tolerance_mm=tolerance_mm,
                gap_settings=(payload or {}).get("gapJoints"),
            )
            verify_report["inspect"] = inspect_report
            verify_report["selectedPanelIds"] = [panels[0].panelId, panels[1].panelId]
            verify_report["panels"] = panel_dicts
            verify_report["relationship"] = relationship

            if verify_report.get("ok"):
                verified_relationship = apply_face_verification_to_relationship(relationship, verify_report)
                verify_report["relationship"] = verified_relationship
                verify_report["verification"] = verified_relationship.get("verification")
                verify_report["faceMatch"] = verified_relationship.get("faceMatch")
                try:
                    from relationship_verification_store import persist_face_verification_to_pair_bodies

                    persist_report = persist_face_verification_to_pair_bodies(
                        panel_bodies[0],
                        panel_bodies[1],
                        verified_relationship,
                        face_match=verify_report.get("faceMatch"),
                        panel_a_id=panels[0].panelId,
                        panel_b_id=panels[1].panelId,
                    )
                    verify_report["verificationPersisted"] = persist_report.get("ok")
                    verify_report["verificationPersist"] = persist_report
                    if persist_report.get("errors"):
                        verify_report.setdefault("warnings", []).extend(persist_report["errors"])
                except Exception as persist_ex:
                    verify_report["verificationPersisted"] = False
                    verify_report.setdefault("warnings", []).append(
                        "Face verification persist failed: {}".format(persist_ex)
                    )

            return "relationshipFaceVerifyResult", verify_report
        except Exception as ex:
            return "relationshipFaceVerifyResult", {
                "ok": False,
                "action": "relationships.verifySelectedPairFaces",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def verify_all_bbox_candidates(self, payload, _palette):
        """Batch face-verify filtered bbox candidates; skip failures; never relax cut gate."""
        try:
            from face_verification import (
                BATCH_VERIFY_ACTION,
                DEFAULT_BATCH_MAX_PAIRS,
                verify_all_bbox_candidates as run_batch_verify,
            )
            from face_verification_fusion import extract_faces_for_panel
            from relationship_service import (
                build_panel_snapshot,
                collect_panel_bodies,
                collect_panel_bodies_under_assembly,
                scan_relationships,
            )
            from relationship_report import build_scan_report

            tolerance_mm = self._float_param(payload, "toleranceMm", CONTACT_TOLERANCE_MM)
            try:
                max_pairs = int((payload or {}).get("maxPairs", DEFAULT_BATCH_MAX_PAIRS))
            except Exception:
                max_pairs = DEFAULT_BATCH_MAX_PAIRS
            assembly_name = str((payload or {}).get("assemblyComponentName") or "").strip() or None
            # physical: face verify must match Fusion body space (designGeometry goes stale after moves)
            bbox_source = str((payload or {}).get("bboxSource") or "physical").strip() or "physical"

            root = self.service._root_component()
            if not root:
                return "relationshipFaceVerifyBatchResult", {
                    "ok": False,
                    "action": BATCH_VERIFY_ACTION,
                    "errors": ["No active Fusion design."],
                }

            if assembly_name:
                bodies = collect_panel_bodies_under_assembly(root, assembly_name)
            else:
                bodies = collect_panel_bodies(root)

            body_by_id = {}
            panels = []
            for body in bodies or []:
                snap = build_panel_snapshot(body, bbox_source=bbox_source)
                panel_id = str(getattr(snap, "panelId", "") or "").strip()
                if not panel_id or panel_id in body_by_id:
                    continue
                body_by_id[panel_id] = body
                panels.append(snap)

            if len(panels) < 2:
                return "relationshipFaceVerifyBatchResult", {
                    "ok": False,
                    "action": BATCH_VERIFY_ACTION,
                    "panelCount": len(panels),
                    "reminders": ["可扫描面板不足，无法批量面验证。请确认板件已挂面板元数据。"],
                    "errors": ["Need at least 2 panel bodies to batch face-verify."],
                }

            panel_list, relationships = scan_relationships(
                panels,
                tolerance_mm=tolerance_mm,
                include_none=False,
            )
            panel_map = {panel.panelId: panel.to_dict() for panel in panel_list}
            rel_dicts = [rel.to_dict() for rel in relationships]
            try:
                from relationship_verification_store import hydrate_relationships_from_panel_metadata
                from panel_metadata_writeback import read_panel_metadata_from_body

                meta_by_id = {}
                for panel_id, body in body_by_id.items():
                    meta, _err = read_panel_metadata_from_body(body)
                    if isinstance(meta, dict):
                        meta_by_id[panel_id] = meta
                if meta_by_id:
                    rel_dicts = hydrate_relationships_from_panel_metadata(rel_dicts, meta_by_id)
            except Exception:
                pass

            def extract_faces(panel_dict):
                panel_id = str((panel_dict or {}).get("panelId") or "").strip()
                body = body_by_id.get(panel_id)
                if body is None:
                    raise RuntimeError("body_not_found: {}".format(panel_id))
                return extract_faces_for_panel(body, panel_dict)

            report = run_batch_verify(
                rel_dicts,
                panel_map,
                tolerance_mm=tolerance_mm,
                max_pairs=max_pairs,
                extract_faces=extract_faces,
                gap_settings=(payload or {}).get("gapJoints"),
            )
            persisted = []
            try:
                from relationship_verification_store import persist_face_verification_to_pair_bodies

                for verified in report.get("verifiedRelationships") or []:
                    if not isinstance(verified, dict):
                        continue
                    panel_a_id = str((verified.get("panelA") or {}).get("panelId") or "").strip()
                    panel_b_id = str((verified.get("panelB") or {}).get("panelId") or "").strip()
                    persist_report = persist_face_verification_to_pair_bodies(
                        body_by_id.get(panel_a_id),
                        body_by_id.get(panel_b_id),
                        verified,
                        face_match=verified.get("faceMatch"),
                        panel_a_id=panel_a_id,
                        panel_b_id=panel_b_id,
                    )
                    persisted.append(persist_report)
            except Exception as persist_ex:
                report.setdefault("warnings", []).append(
                    "Batch verification persist failed: {}".format(persist_ex)
                )
            report["verificationPersistedCount"] = sum(
                1 for item in persisted if item.get("ok")
            )
            report["panelCount"] = len(panel_list)
            report["relationshipCount"] = len(rel_dicts)
            report["assemblyComponentName"] = assembly_name
            report["bboxSource"] = bbox_source
            report["scan"] = build_scan_report(
                action="relationships.scan",
                panels=panel_list,
                relationships=relationships,
                scope="assembly" if assembly_name else "all",
                tolerance_mm=tolerance_mm,
            )
            return "relationshipFaceVerifyBatchResult", report
        except Exception as ex:
            return "relationshipFaceVerifyBatchResult", {
                "ok": False,
                "action": "relationships.verifyAllBboxCandidates",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def reconcile_generator_declarations(self, payload, _palette):
        try:
            import importlib

            import generator_declared_relationships
            import generator_declared_service
            import general_tall_declared_relationships
            import kitchen_declared_relationships
            import lounge_declared_relationships
            import overhead_declared_relationships

            importlib.reload(overhead_declared_relationships)
            importlib.reload(general_tall_declared_relationships)
            importlib.reload(kitchen_declared_relationships)
            importlib.reload(lounge_declared_relationships)
            importlib.reload(generator_declared_relationships)
            importlib.reload(generator_declared_service)
            reconcile_fn = generator_declared_service.reconcile_generator_declarations

            tolerance_mm = self._float_param(payload, "toleranceMm", CONTACT_TOLERANCE_MM)
            generator = str((payload or {}).get("generator") or "").strip() or None
            preferred_run = str((payload or {}).get("runLabel") or (payload or {}).get("preferredRunToken") or "").strip() or None
            assembly_name = str((payload or {}).get("assemblyComponentName") or "").strip() or None
            bbox_source = str((payload or {}).get("bboxSource") or "design_preferred").strip() or "design_preferred"
            if assembly_name:
                panels = self.service.collect_panels_from_assembly(assembly_name, bbox_source=bbox_source)
            else:
                panels = self.service.collect_panels_from_design(bbox_source=bbox_source)
            if not panels:
                root = self.service._root_component()
                if not root:
                    return "relationshipDeclaredResult", {
                        "ok": False,
                        "action": "relationships.reconcileGeneratorDeclarations",
                        "generator": generator,
                        "errors": ["No active Fusion design."],
                    }
                return "relationshipDeclaredResult", {
                    "ok": False,
                    "action": "relationships.reconcileGeneratorDeclarations",
                    "generator": generator,
                    "errors": ["No panel bodies found in the active design."],
                }
            embedded_declarations = None
            if assembly_name:
                from relationship_service import find_component_by_name, read_relationship_declarations_from_component

                root = self.service._root_component()
                assembly_component = find_component_by_name(root, assembly_name) if root else None
                embedded_declarations = read_relationship_declarations_from_component(assembly_component)
            report = reconcile_fn(
                panels,
                generator=generator,
                tolerance_mm=tolerance_mm,
                preferred_run_token=preferred_run,
                embedded_declarations=embedded_declarations or None,
            )
            return "relationshipDeclaredResult", report
        except Exception as ex:
            return "relationshipDeclaredResult", {
                "ok": False,
                "action": "relationships.reconcileGeneratorDeclarations",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def connect_list(self, payload, _palette):
        try:
            import importlib

            import connect_formal_ui

            connect_formal_ui = importlib.reload(connect_formal_ui)
            tolerance_mm = self._float_param(payload, "toleranceMm", CONTACT_TOLERANCE_MM)
            include_none = bool((payload or {}).get("includeNone"))
            scan_result = (payload or {}).get("scanResult") if isinstance(payload, dict) else None
            if not isinstance(scan_result, dict):
                scan_result = self.service.scan(
                    scope=str((payload or {}).get("scope") or "all"),
                    tolerance_mm=tolerance_mm,
                    include_none=include_none,
                )
            declared_relationships = None
            if isinstance(payload, dict):
                reconcile_result = payload.get("reconcileResult")
                if isinstance(reconcile_result, dict):
                    declared_relationships = reconcile_result.get("declaredRelationships")
                if declared_relationships is None:
                    declared_relationships = payload.get("declaredRelationships")
            if declared_relationships:
                scan_result = connect_formal_ui.merge_declared_relationships_into_scan(
                    scan_result,
                    declared_relationships if isinstance(declared_relationships, list) else None,
                )
            filters = (payload or {}).get("filters") if isinstance(payload, dict) else None
            selected_id = str((payload or {}).get("selectedRelationshipId") or "").strip() or None
            view = connect_formal_ui.build_connect_view_model(
                scan_result,
                filters=filters if isinstance(filters, dict) else {},
                selected_relationship_id=selected_id,
            )
            view["scan"] = scan_result
            return "connectListResult", view
        except Exception as ex:
            return "connectListResult", {
                "ok": False,
                "action": "relationships.connectList",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def connect_execute(self, payload, _palette):
        try:
            import importlib

            import connect_formal_ui

            connect_formal_ui = importlib.reload(connect_formal_ui)
            action = str((payload or {}).get("action") or "").strip()
            relationship = (payload or {}).get("relationship") if isinstance(payload, dict) else None
            gap_settings = (payload or {}).get("gapJoints") if isinstance(payload, dict) else None
            gate = connect_formal_ui.evaluate_connect_action(action, relationship, gap_settings)
            result = dict(gate)
            result["action"] = "relationships.connectExecute"
            result["requestedAction"] = action
            if gate.get("ok") and action in ("confirm", "confirm_for_cut"):
                confirmed = gate.get("confirmedRelationship") or relationship
                result["confirmedRelationship"] = confirmed
                result["relationship"] = confirmed
            return "connectExecuteResult", result
        except Exception as ex:
            return "connectExecuteResult", {
                "ok": False,
                "action": "relationships.connectExecute",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def _show_relationship_overlay(self, payload, *, action: str):
        try:
            from relationship_visual_overlay_selfcheck import load_overlay_fusion_module

            fusion_mod, preflight = load_overlay_fusion_module(force_reload=True)
            if fusion_mod is None:
                return "relationshipOverlayResult", {
                    "ok": False,
                    "action": action,
                    "preflight": preflight,
                    "errors": preflight.get("errors") or ["Overlay preflight failed."],
                    "hint": preflight.get("hint"),
                }

            root = self.fusion.get_root_component() if self.fusion else None
            report = fusion_mod.show_overlay_from_payload(root, payload if isinstance(payload, dict) else {})
            report["action"] = action
            report["preflight"] = preflight
            report["implVersion"] = getattr(fusion_mod, "OVERLAY_FUSION_BUILD", None)
            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass
            return "relationshipOverlayResult", report
        except Exception as ex:
            return "relationshipOverlayResult", {
                "ok": False,
                "action": action,
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def clear_relationship_overlays(self, _payload, _palette):
        try:
            from relationship_visual_overlay_selfcheck import load_overlay_fusion_module

            fusion_mod, preflight = load_overlay_fusion_module(force_reload=True)
            if fusion_mod is None:
                return "relationshipOverlayResult", {
                    "ok": False,
                    "action": "relationships.clearRelationshipOverlays",
                    "preflight": preflight,
                    "errors": preflight.get("errors") or ["Overlay preflight failed."],
                    "hint": preflight.get("hint"),
                }

            root = self.fusion.get_root_component() if self.fusion else None
            report = fusion_mod.clear_relationship_overlays(root)
            report["preflight"] = preflight
            report["implVersion"] = getattr(fusion_mod, "OVERLAY_FUSION_BUILD", None)
            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass
            return "relationshipOverlayResult", report
        except Exception as ex:
            return "relationshipOverlayResult", {
                "ok": False,
                "action": "relationships.clearRelationshipOverlays",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def run_overlay_selfcheck(self, _payload, _palette):
        try:
            from relationship_visual_overlay_selfcheck import run_overlay_selfcheck

            report = run_overlay_selfcheck(force_reload=True)
            return "relationshipOverlayResult", {
                "ok": bool(report.get("ok")),
                "action": "relationships.runOverlaySelfCheck",
                **report,
            }
        except Exception as ex:
            return "relationshipOverlayResult", {
                "ok": False,
                "action": "relationships.runOverlaySelfCheck",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def create_test_fixture(self, payload, _palette):
        try:
            root = self.fusion.get_root_component() if self.fusion else None
            if not root:
                return "relationshipFixtureResult", {
                    "ok": False,
                    "action": "relationships.createTestFixture",
                    "errors": ["No active Fusion design."],
                }

            fixture_module = importlib.reload(importlib.import_module("modules.relationships.relationship_fixtures"))
            created, error, mode_note, placement = fixture_module.create_relationship_test_fixture(root)
            if error:
                return "relationshipFixtureResult", {
                    "ok": False,
                    "action": "relationships.createTestFixture",
                    "errors": [error],
                    "createdBodies": len(created),
                }

            warnings = []
            if mode_note:
                warnings.append(mode_note)
            flat_mode = any(item.get("flatMode") for item in created)

            fixture_bodies = []
            serializable_created = []
            for item in created:
                body = item.get("_fusionBody")
                if body is not None:
                    fixture_bodies.append(body)
                serializable = {key: value for key, value in item.items() if key != "_fusionBody"}
                serializable_created.append(serializable)

            selected_bodies = 0
            try:
                selected_bodies = self.fusion.select_bodies_and_fit(fixture_bodies)
            except Exception as ex:
                warnings.append("Fixture bodies were created, but automatic viewport fit failed: {}".format(ex))
            if selected_bodies:
                warnings.append("Viewport fitted to {} fixture body/bodies.".format(selected_bodies))
            tolerance_mm = self._float_param(payload, "toleranceMm", CONTACT_TOLERANCE_MM)
            created_panel_ids = {item["panelId"] for item in created}
            panels = [
                panel
                for panel in self.service.collect_panels_from_design()
                if panel.panelId in created_panel_ids
            ]
            from relationship_service import scan_relationships
            from relationship_report import build_scan_report

            _, relationships = scan_relationships(panels, tolerance_mm=tolerance_mm, include_none=True)
            scan_report = build_scan_report(
                action="relationships.scan",
                panels=panels,
                relationships=relationships,
                scope="fixture",
                tolerance_mm=tolerance_mm,
                expected_fixtures=expected_fixture_cases(),
            )

            try:
                self.fusion.refresh_viewport()
            except Exception:
                pass

            return "relationshipFixtureResult", {
                "ok": scan_report.get("ok", False),
                "action": "relationships.createTestFixture",
                "createdBodies": len(serializable_created),
                "flatMode": flat_mode,
                "fixtureOrigin": placement,
                "selectedBodies": selected_bodies,
                "fixtures": expected_fixture_cases(),
                "created": serializable_created,
                "scan": scan_report,
                "warnings": warnings,
            }
        except Exception as ex:
            return "relationshipFixtureResult", {
                "ok": False,
                "action": "relationships.createTestFixture",
                "errors": [str(ex)],
                "trace": traceback.format_exc(),
            }

    def _selected_bodies(self):
        getter = getattr(self.fusion, "get_selected_entities", None)
        if callable(getter):
            entities = getter()
        else:
            entities = []

        bodies = []
        for entity in entities or []:
            if entity is None:
                continue
            if hasattr(entity, "isSolid") and entity.isSolid:
                bodies.append(entity)
        return bodies

    def _hydrate_scan_report_verifications(self, report: Dict[str, Any]) -> Dict[str, Any]:
        """Restore face_verified marks from panel metadata onto scan relationships."""
        if not isinstance(report, dict):
            return report
        relationships = report.get("relationships")
        if not isinstance(relationships, list) or not relationships:
            return report
        try:
            from panel_metadata_writeback import read_panel_metadata_from_body
            from relationship_service import build_panel_snapshot, collect_panel_bodies
            from relationship_verification_store import hydrate_relationships_from_panel_metadata

            root = self.service._root_component()
            if not root:
                return report
            body_by_id = {}
            for body in collect_panel_bodies(root) or []:
                snap = build_panel_snapshot(body)
                panel_id = str(getattr(snap, "panelId", "") or "").strip()
                if panel_id and panel_id not in body_by_id:
                    body_by_id[panel_id] = body
            meta_by_id = {}
            for panel_id, body in body_by_id.items():
                meta, _err = read_panel_metadata_from_body(body)
                if isinstance(meta, dict):
                    meta_by_id[panel_id] = meta
            if not meta_by_id:
                return report
            hydrated = hydrate_relationships_from_panel_metadata(list(relationships), meta_by_id)
            updated = dict(report)
            updated["relationships"] = hydrated
            updated["verificationHydratedCount"] = sum(
                1
                for rel in hydrated
                if isinstance(rel, dict)
                and (rel.get("verification") or {}).get("level") == "face_verified"
                and any(
                    "Restored face_verified" in str(note)
                    for note in (rel.get("auditNotes") or [])
                )
            )
            return updated
        except Exception:
            return report
