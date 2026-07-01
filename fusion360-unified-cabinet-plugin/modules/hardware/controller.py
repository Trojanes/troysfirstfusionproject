import json
import time
import traceback

import adsk.core
import adsk.fusion

from face_attribute_store import read_face_metadata
from face_metadata_service import FaceMetadataService
from face_models import FACE_CLASS_EDGE, FACE_CLASS_SURFACE
from face_models import SURFACE_MODE_DOUBLE_SIDED
from geometry_ops import ATTRIBUTE_GROUP, mm_to_cm, sanitize_token
from modules.general_tall.fusion_adapter import _add_box_body
from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, PANEL_METADATA_ATTR


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
