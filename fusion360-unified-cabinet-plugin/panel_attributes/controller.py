import importlib

import adsk.core
import adsk.fusion

import panel_body_resolver
import panel_source_ref
import attribute_state_service

panel_body_resolver = importlib.reload(panel_body_resolver)
panel_source_ref = importlib.reload(panel_source_ref)
attribute_state_service = importlib.reload(attribute_state_service)

import door_face_orientation
import grain_direction
import metadata_inspector
import milling_surface_propagation
import tag_metadata_editor
import thickness_rules
import work_zones
import nesting.collision_validate as nesting_collision_validate
import nesting.dxf_export as nesting_dxf_export
import nesting.engine as nesting_engine
import nesting.fusion_layout as nesting_fusion_layout
import nesting.lay_flat as nesting_lay_flat
import nesting.lay_flat_analyze as nesting_lay_flat_analyze
import nesting.lay_flat_export_ready as nesting_lay_flat_export_ready
import nesting.lay_flat_face_up as nesting_lay_flat_face_up
import nesting.lay_flat_fusion as nesting_lay_flat_fusion
import nesting.lay_flat_tag_overrides as nesting_lay_flat_tag_overrides
import nesting.lay_flat_tag_scan as nesting_lay_flat_tag_scan
import nesting.layout as nesting_layout
import nesting.manufacturing_snapshot_export as manufacturing_snapshot_export
import nesting.outline_cache as nesting_outline_cache
import nesting.preflight as nesting_preflight
import nesting.runtime_profile as nesting_runtime_profile
import nesting.sheet_pack as nesting_sheet_pack
import nesting.workpiece_names as nesting_workpiece_names
from panel_search_service import collect_all_tags, collect_defined_panels, resolve_panel_targets, search_panels


door_face_orientation = importlib.reload(door_face_orientation)
grain_direction = importlib.reload(grain_direction)
metadata_inspector = importlib.reload(metadata_inspector)
milling_surface_propagation = importlib.reload(milling_surface_propagation)
tag_metadata_editor = importlib.reload(tag_metadata_editor)
thickness_rules = importlib.reload(thickness_rules)
work_zones = importlib.reload(work_zones)
nesting_collision_validate = importlib.reload(nesting_collision_validate)
nesting_dxf_export = importlib.reload(nesting_dxf_export)
nesting_engine = importlib.reload(nesting_engine)
nesting_fusion_layout = importlib.reload(nesting_fusion_layout)
nesting_lay_flat = importlib.reload(nesting_lay_flat)
nesting_lay_flat_analyze = importlib.reload(nesting_lay_flat_analyze)
nesting_lay_flat_export_ready = importlib.reload(nesting_lay_flat_export_ready)
nesting_lay_flat_face_up = importlib.reload(nesting_lay_flat_face_up)
nesting_lay_flat_fusion = importlib.reload(nesting_lay_flat_fusion)
nesting_lay_flat_tag_overrides = importlib.reload(nesting_lay_flat_tag_overrides)
nesting_lay_flat_tag_scan = importlib.reload(nesting_lay_flat_tag_scan)
nesting_layout = importlib.reload(nesting_layout)
manufacturing_snapshot_export = importlib.reload(manufacturing_snapshot_export)
nesting_outline_cache = importlib.reload(nesting_outline_cache)
nesting_preflight = importlib.reload(nesting_preflight)
nesting_runtime_profile = importlib.reload(nesting_runtime_profile)
nesting_sheet_pack = importlib.reload(nesting_sheet_pack)
nesting_workpiece_names = importlib.reload(nesting_workpiece_names)

body_matches_record = panel_body_resolver.body_matches_record
find_body_in_design = panel_body_resolver.find_body_in_design
find_original_body_by_panel_id = panel_body_resolver.find_original_body_by_panel_id
list_solid_bodies = panel_body_resolver.list_solid_bodies
resolve_main_body = panel_body_resolver.resolve_main_body


def _pump_fusion_events():
    """Keep Fusion responsive while external nesting workers are running."""
    try:
        adsk.doEvents()
    except Exception:
        pass


def _read_grain_along_from_body(body):
    """Return (grainAlongMm or '', error)."""
    metadata, read_error = tag_metadata_editor._read_body_metadata_raw(body)
    if read_error:
        return "", read_error
    return attribute_state_service.grain_along_mm_value(metadata), None


def _write_grain_along_on_body(body, grain_mm):
    """Write classification.grainAlongMm onto a Fusion body.

    Also stamps outline/dimension grain so Lay Flat cache goes stale.
    Returns (apply_result, error).
    """
    metadata, read_error = tag_metadata_editor._read_body_metadata_raw(body)
    if read_error:
        return None, read_error
    base = tag_metadata_editor._bootstrap_body_metadata(body, metadata)
    patched, result = tag_metadata_editor.apply_grain_along_to_metadata(base, grain_mm)
    dims = patched.get("dimensions")
    if isinstance(dims, dict):
        dims["grainAlongMm"] = grain_mm
    cache = patched.get("nestingFlatOutline")
    if isinstance(cache, dict):
        cache["grainAlongMm"] = grain_mm
        outline = cache.get("outline")
        if isinstance(outline, dict):
            outline["grainAlongMm"] = grain_mm
    tag_metadata_editor._write_body_metadata(body, patched)
    return result, None


def _strip_temp_bodies_for_json(value):
    """Drop Fusion ``tempBody`` handles so palette payloads stay JSON-safe."""
    if isinstance(value, list):
        return [_strip_temp_bodies_for_json(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _strip_temp_bodies_for_json(item)
            for key, item in value.items()
            if key != "tempBody"
        }
    return value


def _discard_prepared_temp_bodies(items):
    """Delete temporary nesting flat copies that will not be kept in the layout."""
    for item in items or []:
        if not isinstance(item, dict):
            continue
        body = item.get("tempBody")
        if body is None:
            continue
        try:
            body.deleteMe()
        except Exception:
            pass
        item["tempBody"] = None


def _assembly_name_for_record(root, record):
    """Resolve canonical assembly name, with occurrence names as legacy fallback."""
    record = record or {}
    metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
    identity = metadata.get("identity") if isinstance(metadata.get("identity"), dict) else {}
    source_ref = identity.get("sourceRef") if isinstance(identity.get("sourceRef"), dict) else {}

    candidates = [
        record.get("assemblyName"),
        record.get("sourceAssemblyName"),
        identity.get("assemblyName"),
        identity.get("sourceAssemblyName"),
        source_ref.get("assemblyName"),
    ]
    for candidate in candidates:
        name = str(candidate or "").strip()
        if (
            name
            and not nesting_workpiece_names.is_blob_label(name)
            and not nesting_workpiece_names.is_layout_container_label(name)
        ):
            return name

    path = list((record or {}).get("occurrencePath") or [])
    if root is not None and path:
        try:
            occurrence = root.occurrences.item(int(path[0]))
            component = getattr(occurrence, "component", None)
            for entity in (component, occurrence):
                if entity is None:
                    continue
                name = str(
                    metadata_inspector._module_attr_value(entity, "assemblyName")
                    or ""
                ).strip()
                if (
                    name
                    and not nesting_workpiece_names.is_blob_label(name)
                    and not nesting_workpiece_names.is_layout_container_label(name)
                ):
                    return name
            # Old designs may only have the browser occurrence/component name.
            for entity in (occurrence, component):
                name = str(getattr(entity, "name", "") or "").strip()
                if name:
                    return name
        except Exception:
            pass
    try:
        return str(getattr(root, "name", "") or "") if root is not None else ""
    except Exception:
        return ""


class PanelAttributesController:
    def __init__(self, fusion_adapter):
        self.fusion = fusion_adapter

    def _selected_entities(self):
        getter = getattr(self.fusion, "get_selected_entities", None)
        if callable(getter):
            return getter()

        selection = self._active_selection_collection()
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

    def _active_selection_collection(self):
        app = adsk.core.Application.get()
        ui = app.userInterface if app else None
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

    def _component_by_path(self, root, occurrence_path):
        component = root
        for index in occurrence_path or []:
            try:
                if not component.occurrences or index >= component.occurrences.count:
                    return None
                component = component.occurrences.item(index).component
            except Exception:
                return None
        return component

    def _entity_from_token(self, entity_token):
        if not entity_token:
            return None
        design = self.fusion.get_active_design()
        if not design:
            return None
        try:
            entity = design.findEntityByToken(str(entity_token))
        except Exception:
            return None
        if isinstance(entity, list):
            entity = entity[0] if entity else None
        return entity

    def _body_from_token(self, entity_token):
        entity = self._entity_from_token(entity_token)
        if not entity:
            return None
        object_type = str(getattr(entity, "objectType", "") or "")
        if "BRepBody" in object_type:
            return entity
        for attr_name in ("body", "parentBody"):
            try:
                body = getattr(entity, attr_name)
            except Exception:
                body = None
            if body:
                return body
        return None

    def _resolve_tag_scan_entity(self, entity_token, kind, result, selected_bodies=None):
        body_record = result.get("body") or {}
        selection = result.get("selection") or {}
        root = self.fusion.get_root_component()

        if kind == "body":
            for token in (
                entity_token,
                body_record.get("entityToken"),
                selection.get("selectionEntityToken"),
            ):
                body = self._body_from_token(token)
                if body:
                    return body

            if root:
                body = find_body_in_design(root, body_record)
                if body:
                    return body
                body, _warnings = self._body_from_metadata_record(root, body_record)
                if body:
                    return body

            for candidate in selected_bodies or []:
                if body_matches_record(candidate, body_record):
                    return candidate
            return None

        entity = self._entity_from_token(entity_token)
        if entity:
            object_type = str(getattr(entity, "objectType", "") or "")
            if "BRepFace" in object_type or "BRepEdge" in object_type:
                return entity

        selection_token = selection.get("selectionEntityToken")
        entity = self._entity_from_token(selection_token)
        if entity:
            object_type = str(getattr(entity, "objectType", "") or "")
            if "BRepFace" in object_type or "BRepEdge" in object_type:
                return entity
        return None

    def _selected_bodies(self):
        bodies = []
        seen = set()
        for entity in self._selected_entities():
            body, source_kind = metadata_inspector._selection_owner_body(entity)
            if not body:
                continue
            key = metadata_inspector._body_key(body)
            if key in seen:
                continue
            seen.add(key)
            bodies.append(body)
        return bodies

    def _source_bodies_from_ui_selection(self, root):
        """Resolve the current Fusion selection to original panel bodies.

        Cabinet occurrences expand to their solids. LAY_FLAT copies map back
        to the source body. Returns ``(bodies, warnings, error)``.
        """
        selected_entities = self._selected_entities()
        if not selected_entities:
            return [], [], (
                "Select one or more panels (or a cabinet occurrence), then Lay Flat Selected."
            )
        bodies, warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root
        )
        source_bodies = []
        seen = set()
        for body in bodies or []:
            candidates = [body]
            if work_zones.is_lay_flat_workpiece(body):
                resolved, _ref, _how = panel_body_resolver.resolve_source_bodies_for_lay_flat(
                    root, body
                )
                if not resolved:
                    warnings.append(
                        "Could not resolve source for LAY_FLAT body {}.".format(
                            getattr(body, "name", "") or "body"
                        )
                    )
                    continue
                candidates = list(resolved)
            for src in candidates:
                if metadata_inspector._is_assembly_zone(src):
                    continue
                key = metadata_inspector._body_key(src)
                if key in seen:
                    continue
                seen.add(key)
                source_bodies.append(src)
        if not source_bodies:
            return [], warnings, (
                "No panel bodies in the current selection."
            )
        return source_bodies, warnings, None

    def _records_for_selected_lay_flat(self, root, bodies):
        """Nesting-detail records for selected source bodies only (no full scan)."""
        records = []
        skipped = []
        for body in bodies or []:
            occurrence_path = []
            try:
                if root is not None:
                    occurrence_path = metadata_inspector.resolve_occurrence_path_for_body(
                        root, body
                    ) or []
            except Exception:
                occurrence_path = []
            record = metadata_inspector._entity_record(
                body,
                "selected_body",
                occurrence_path,
                component_name=metadata_inspector._component_name_for_body(body),
                body_name=getattr(body, "name", "") or "",
                include_missing=True,
                detail="nesting",
            )
            if not record:
                skipped.append(
                    "No panel metadata for {}".format(
                        getattr(body, "name", "") or "body"
                    )
                )
                continue
            record["entityKind"] = "body"
            try:
                token = str(getattr(body, "entityToken", "") or "")
            except Exception:
                token = ""
            if token:
                record["entityToken"] = token
            record["assemblyName"] = _assembly_name_for_record(root, record)
            records.append(record)
        return records, skipped

    def _body_by_name(self, component, body_name):
        target_name = str(body_name or "").strip()
        if not component or not target_name:
            return None
        for body in list_solid_bodies(component):
            if str(getattr(body, "name", "") or "") == target_name:
                return body
        return None

    def _occurrence_by_path(self, root, occurrence_path):
        """Return a root-context Occurrence proxy for the path, or None."""
        path = list(occurrence_path or [])
        if not path or not root:
            return None
        try:
            occ = None
            component = root
            for index in path:
                if not component.occurrences or index >= component.occurrences.count:
                    return None
                child = component.occurrences.item(index)
                # Nested leaf occurrences must be re-created in root context;
                # otherwise createForAssemblyContext / entityToken can fail.
                occ = child if occ is None else child.createForAssemblyContext(occ)
                if occ is None:
                    return None
                component = child.component
            return occ
        except Exception:
            return None

    def _proxy_body_for_occurrence(self, body, occurrence):
        if not body or occurrence is None:
            return body
        try:
            if bool(getattr(body, "isProxy", False)):
                return body
        except Exception:
            pass
        try:
            proxy = body.createForAssemblyContext(occurrence)
            return proxy or body
        except Exception:
            return body

    def _safe_body_key(self, body):
        try:
            return str(getattr(body, "entityToken", "") or id(body))
        except Exception:
            return str(id(body))

    def _body_from_metadata_record(self, root, record, prefer_path=False):
        warnings = []
        occurrence = self._occurrence_by_path(root, record.get("occurrencePath") or [])

        # Nesting layout resolves hundreds of panels — prefer O(path) lookup and
        # never fall into find_body_in_design's full-tree walk unless needed.
        if prefer_path:
            component = self._component_by_path(root, record.get("occurrencePath") or [])
            if component:
                body = self._body_by_name(component, record.get("bodyName"))
                if body:
                    return self._proxy_body_for_occurrence(body, occurrence), warnings
                body, warning = resolve_main_body(component)
                if warning:
                    warnings.append(warning)
                if body:
                    return self._proxy_body_for_occurrence(body, occurrence), warnings

        body = self._body_from_token(record.get("entityToken"))
        if body:
            return self._proxy_body_for_occurrence(body, occurrence), warnings

        # Prefer design-tree lookup so we can create an occurrence proxy.
        try:
            from panel_body_resolver import find_body_in_design
        except Exception:
            find_body_in_design = None
        if callable(find_body_in_design) and not prefer_path:
            found = find_body_in_design(root, record)
            if found:
                return self._proxy_body_for_occurrence(found, occurrence), warnings

        component = self._component_by_path(root, record.get("occurrencePath") or [])
        if component:
            body = self._body_by_name(component, record.get("bodyName"))
            if body:
                return self._proxy_body_for_occurrence(body, occurrence), warnings
            body, warning = resolve_main_body(component)
            if warning:
                warnings.append(warning)
            return self._proxy_body_for_occurrence(body, occurrence), warnings
        return None, warnings

    def _selectable_body(self, body):
        """Return an occurrence-proxy body Fusion can put in activeSelections."""
        if body is None:
            return None
        try:
            if bool(getattr(body, "isProxy", False)):
                return body
        except Exception:
            pass
        try:
            occurrence = getattr(body, "assemblyContext", None)
        except Exception:
            occurrence = None
        if occurrence is not None:
            try:
                native = getattr(body, "nativeObject", None) or body
                proxy = native.createForAssemblyContext(occurrence)
                if proxy is not None:
                    return proxy
            except Exception:
                pass
        return body

    def _select_bodies_and_fit(self, bodies):
        valid_bodies = [body for body in (bodies or []) if body]
        if not valid_bodies:
            return 0

        selection = self._active_selection_collection()
        selected = 0
        if selection is not None:
            try:
                selection.clear()
            except Exception:
                pass
            for body in valid_bodies:
                candidates = []
                proxied = self._selectable_body(body)
                for candidate in (proxied, body):
                    if candidate is not None:
                        candidates.append(candidate)
                try:
                    native = getattr(body, "nativeObject", None)
                    if native is not None:
                        candidates.append(native)
                except Exception:
                    pass
                for candidate in candidates:
                    try:
                        selection.add(candidate)
                        selected += 1
                        break
                    except Exception:
                        continue
            if selected > 0:
                try:
                    app = adsk.core.Application.get()
                    viewport = app.activeViewport if app else None
                    if viewport:
                        viewport.fit()
                        viewport.refresh()
                except Exception:
                    refresh = getattr(self.fusion, "refresh_viewport", None)
                    if callable(refresh):
                        refresh()
                return selected

        selector = getattr(self.fusion, "select_bodies_and_fit", None)
        if callable(selector):
            return selector([self._selectable_body(body) or body for body in valid_bodies])
        return 0

    def _proxy_face_for_selection(self, face):
        """Return a root/occurrence-context face proxy Fusion can select.

        Nested OHC / GT / Kitchen bodies live under occurrences. Fusion's
        ``selection.add`` needs a face proxy in that assembly context.
        ``createForAssemblyContext`` only works on the *native* face and
        returns null if called on an existing proxy — so we always start
        from ``nativeObject``, then either:
          1) match the face by tempId on the proxy body's ``faces``
             (faces traversed from a proxy body are already proxies), or
          2) createForAssemblyContext(occurrence), or
          3) re-bind via design.findEntityByToken.
        """
        if face is None:
            return None

        try:
            native = getattr(face, "nativeObject", None) or face
        except Exception:
            native = face

        body = None
        for candidate in (face, native):
            try:
                body = getattr(candidate, "body", None)
            except Exception:
                body = None
            if body is not None:
                break

        occurrence = None
        for candidate in (face, body):
            if candidate is None:
                continue
            try:
                occurrence = getattr(candidate, "assemblyContext", None)
            except Exception:
                occurrence = None
            if occurrence is not None:
                break

        # Prefer matching on a proxy body — Autodesk: faces from a proxy body
        # are already selectable proxies in that occurrence context.
        proxy_body = body
        try:
            body_is_proxy = bool(getattr(body, "isProxy", False)) if body is not None else False
        except Exception:
            body_is_proxy = False
        if body is not None and not body_is_proxy and occurrence is not None:
            try:
                proxy_body = body.createForAssemblyContext(occurrence) or body
            except Exception:
                proxy_body = body

        target_temp_id = None
        try:
            target_temp_id = getattr(native, "tempId", None)
        except Exception:
            target_temp_id = None
        if proxy_body is not None and target_temp_id not in (None, ""):
            try:
                for index in range(proxy_body.faces.count):
                    candidate = proxy_body.faces.item(index)
                    try:
                        cand_native = getattr(candidate, "nativeObject", None) or candidate
                        if getattr(cand_native, "tempId", None) == target_temp_id:
                            return candidate
                    except Exception:
                        continue
            except Exception:
                pass

        if occurrence is not None:
            try:
                proxy = native.createForAssemblyContext(occurrence)
                if proxy is not None:
                    return proxy
            except Exception:
                pass

        # Token re-bind: proxy entityTokens encode assembly context.
        try:
            token = str(getattr(face, "entityToken", "") or "") or str(getattr(native, "entityToken", "") or "")
        except Exception:
            token = ""
        if token:
            rebound = self._entity_from_token(token)
            if rebound is not None:
                return rebound
        return face

    def _select_faces_and_fit(self, faces):
        """Clear selection and add BRepFace entities (occurrence proxies preferred).

        Returns (selected_count, failure_messages).
        """
        valid_faces = [face for face in (faces or []) if face]
        if not valid_faces:
            return 0, []

        selection = self._active_selection_collection()
        selected = 0
        failures = []
        if selection is None:
            return 0, ["No activeSelections collection available."]

        try:
            selection.clear()
        except Exception as ex:
            failures.append("selection.clear failed: {}".format(ex))

        for face in valid_faces:
            proxied = self._proxy_face_for_selection(face)
            candidates = []
            for candidate in (proxied, face):
                if candidate is None:
                    continue
                # Avoid identity-based de-dupe on Fusion wrappers; allow retries.
                candidates.append(candidate)
            try:
                native = getattr(face, "nativeObject", None)
                if native is not None:
                    candidates.append(native)
            except Exception:
                pass

            added = False
            last_error = ""
            for candidate in candidates:
                try:
                    selection.add(candidate)
                    selected += 1
                    added = True
                    break
                except Exception as ex:
                    last_error = str(ex)
                    continue
            if not added:
                name = "?"
                try:
                    body = getattr(face, "body", None)
                    name = str(getattr(body, "name", "") or "") or "?"
                except Exception:
                    pass
                failures.append(
                    "{}: {}".format(name, last_error or "selection.add rejected all candidates")
                )

        if selected > 0:
            try:
                app = adsk.core.Application.get()
                viewport = app.activeViewport if app else None
                if viewport:
                    viewport.fit()
                    viewport.refresh()
            except Exception:
                refresh = getattr(self.fusion, "refresh_viewport", None)
                if callable(refresh):
                    refresh()
        return selected, failures[:20]

    def search_panels(self, payload, _palette):
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "searchPanels",
                "errors": ["No active Fusion design."],
            }

        query = str((payload or {}).get("query") or "").strip()
        panels = search_panels(root, query)
        serializable = []
        for panel in panels:
            item = dict(panel)
            item.pop("entityToken", None)
            serializable.append(item)

        return "panelAttributesResult", {
            "ok": True,
            "action": "searchPanels",
            "query": query,
            "panels": serializable,
            "tags": collect_all_tags(root),
            "count": len(serializable),
        }

    def select_by_tag(self, payload, palette):
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectByTag",
                "errors": ["No active Fusion design."],
            }

        query = str((payload or {}).get("query") or "").strip()
        if not query:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectByTag",
                "errors": ["Enter at least one tag or keyword."],
            }

        panels = search_panels(root, query)
        if not panels:
            return "panelAttributesResult", {
                "ok": True,
                "action": "selectByTag",
                "query": query,
                "selectedCount": 0,
                "panels": [],
                "warnings": ["No matching panels found."],
            }

        targets, warnings = resolve_panel_targets(root, panels)
        bodies = [target["body"] for target in targets if target.get("body")]
        selected_count = self.fusion.select_bodies_and_fit(bodies)

        serializable = []
        for panel in panels:
            item = dict(panel)
            item.pop("entityToken", None)
            serializable.append(item)

        if palette:
            palette.send(
                "panelAttributesSelectionChanged",
                {
                    "query": query,
                    "selectedCount": selected_count,
                    "panels": serializable,
                },
            )

        return "panelAttributesResult", {
            "ok": True,
            "action": "selectByTag",
            "query": query,
            "selectedCount": selected_count,
            "panels": serializable,
            "warnings": warnings,
        }

    def select_panel(self, payload, _palette):
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectPanel",
                "errors": ["No active Fusion design."],
            }

        occurrence_path = (payload or {}).get("occurrencePath") or []
        panels = collect_defined_panels(root)
        panel = None
        for candidate in panels:
            if list(candidate.get("occurrencePath") or []) == list(occurrence_path):
                panel = candidate
                break
        if not panel:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectPanel",
                "errors": ["Panel not found in current search results."],
            }

        targets, warnings = resolve_panel_targets(root, [panel])
        bodies = [target["body"] for target in targets if target.get("body")]
        selected_count = self.fusion.select_bodies_and_fit(bodies)
        item = dict(panel)
        item.pop("entityToken", None)

        return "panelAttributesResult", {
            "ok": True,
            "action": "selectPanel",
            "selectedCount": selected_count,
            "panel": item,
            "warnings": warnings,
        }

    def select_metadata_record(self, payload, _palette):
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectMetadataRecord",
                "errors": ["No active Fusion design."],
            }

        body, warnings = self._body_from_metadata_record(root, payload or {})
        if not body:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectMetadataRecord",
                "errors": ["Could not resolve scanned metadata record to a Fusion body."],
            }

        selected_count = self._select_bodies_and_fit([body])
        return "panelAttributesResult", {
            "ok": True,
            "action": "selectMetadataRecord",
            "selectedCount": selected_count,
            "panel": {
                "panelId": (payload or {}).get("panelId"),
                "bodyName": str(getattr(body, "name", "") or ""),
                "componentName": (payload or {}).get("componentName") or "",
            },
            "warnings": warnings,
        }

    def select_metadata_records(self, payload, _palette):
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectMetadataRecords",
                "errors": ["No active Fusion design."],
            }

        records = (payload or {}).get("records") or []
        bodies = []
        warnings = []
        seen = set()
        for record in records:
            body, record_warnings = self._body_from_metadata_record(root, record)
            for warning in record_warnings:
                warnings.append("{}: {}".format(record.get("panelId") or record.get("bodyName") or "metadata record", warning))
            if not body:
                warnings.append("Could not resolve {}".format(record.get("panelId") or "metadata record"))
                continue
            key = self._safe_body_key(body)
            if key in seen:
                continue
            seen.add(key)
            bodies.append(body)

        selected_count = self._select_bodies_and_fit(bodies)
        if selected_count == 0 and bodies:
            warnings.append(
                "Resolved {} bodies but Fusion selection.add failed (often needs occurrence proxy).".format(len(bodies))
            )
        elif selected_count < len(bodies):
            warnings.append("Selected {} of {} resolved bodies.".format(selected_count, len(bodies)))

        return "panelAttributesResult", {
            "ok": True,
            "action": "selectMetadataRecords",
            "selectedCount": selected_count,
            "resolvedCount": len(bodies),
            "query": (payload or {}).get("query") or "typed tags",
            "panels": [
                {
                    "panelId": record.get("panelId"),
                    "bodyName": record.get("bodyName"),
                    "componentName": record.get("componentName"),
                    "occurrencePath": record.get("occurrencePath") or [],
                    "entityToken": record.get("entityToken") or "",
                }
                for record in records
            ],
            "warnings": warnings[:20],
        }

    def scan_metadata(self, payload, _palette):
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "scanMetadata",
                "errors": ["No active Fusion design."],
            }

        zone_filter = str((payload or {}).get("zoneFilter") or "").strip().lower() or None
        records, counts, diagnostics = metadata_inspector.scan_panel_metadata(root, zone_filter=zone_filter)
        warnings = []
        solid = int((diagnostics or {}).get("solidBodies") or 0)
        scanned_bodies = int((diagnostics or {}).get("scannedBodies") or 0)
        missing_bodies = int((diagnostics or {}).get("missingBodies") or 0)
        without_attrs = int((diagnostics or {}).get("withoutAttrs") or 0)
        not_in_scan = int((diagnostics or {}).get("bodiesNotInScan") or 0)
        if solid:
            warnings.append(
                "Design solids: {} · scanned bodies: {} · missing attrs: {} · not in scan: {}."
                "{}".format(
                    solid,
                    scanned_bodies,
                    missing_bodies or without_attrs,
                    not_in_scan,
                    (
                        " Nesting-zone boards skipped: {}.".format(
                            int((diagnostics or {}).get("bodiesSkippedNestingZone") or 0)
                        )
                        if int((diagnostics or {}).get("bodiesSkippedNestingZone") or 0)
                        else ""
                    ),
                )
            )
        if missing_bodies or without_attrs:
            warnings.append(
                "Some boards have no generator/panel attributes (often older copies or non-plugin bodies). They now appear as Missing."
            )
        if (diagnostics or {}).get("workZonesPresent") and zone_filter == "nesting":
            warnings.append(
                "Scan zone is Nesting only (layout copies). Switch to All source zones for assembly/generation panels."
            )
        elif (diagnostics or {}).get("workZonesPresent") and zone_filter and zone_filter not in ("all", "nesting"):
            warnings.append(
                "Scan zone is '{}'. Switch to All source zones if boards sit outside this zone.".format(zone_filter)
            )
        elif (diagnostics or {}).get("workZonesPresent"):
            warnings.append(
                "Scan All excludes Nesting-zone layout copies by default (use zone filter Nesting to inspect them)."
            )
        return "panelAttributesResult", {
            "ok": True,
            "action": "scanMetadata",
            "records": records,
            "counts": counts,
            "count": len(records),
            "zoneFilter": zone_filter or "all",
            "diagnostics": diagnostics or {},
            "warnings": warnings,
        }

    def scan_selected_metadata(self, _payload, _palette):
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "scanSelectedMetadata",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": True,
                "action": "scanSelectedMetadata",
                "records": [],
                "counts": {"Valid": 0, "Warning": 0, "Invalid": 0, "Missing": 0},
                "count": 0,
                "warnings": ["No bodies or faces selected."],
            }

        records, counts, skipped = metadata_inspector.scan_selected_panel_metadata(selected_entities)
        warnings = skipped[:20]
        if not records and not warnings:
            warnings.append("No supported body or face selections found.")
        return "panelAttributesResult", {
            "ok": True,
            "action": "scanSelectedMetadata",
            "records": records,
            "counts": counts,
            "count": len(records),
            "warnings": warnings,
        }

    def check_nesting_ready(self, payload, _palette):
        """Fast Nesting Ready check: body attributes only, no per-face Fusion reads."""
        profiler = nesting_runtime_profile.NestingProfiler("checkNestingReady")
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "checkNestingReady",
                "errors": ["No active Fusion design."],
            }
        zone_filter = str((payload or {}).get("zoneFilter") or "all").strip().lower() or "all"
        records, _counts, diagnostics = metadata_inspector.scan_panel_metadata(
            root, zone_filter=zone_filter, detail="nesting", profiler=profiler
        )
        body_records = [
            record
            for record in records
            if "body" in str(record.get("entityKind") or "").lower()
        ]
        ready = []
        not_ready = []
        missing_counts = {"Board Type": 0, "Color": 0, "Cutting Face": 0}
        profiler.begin("evaluate")
        for record in body_records:
            check = nesting_preflight.evaluate_record(record)
            slim = {
                "panelId": record.get("panelId") or "",
                "bodyName": record.get("bodyName") or "",
                "componentName": record.get("componentName") or "",
                "occurrencePath": record.get("occurrencePath") or [],
                "entityToken": record.get("entityToken") or "",
                "zone": record.get("zone") or "",
                "boardTypeTag": check["boardTypeTag"],
                "colorTag": check["colorTag"],
                "cuttingFace": check["cuttingFace"],
                "missing": check["missing"],
                "ready": check["ready"],
                "metadataSource": record.get("metadataSource") or "",
            }
            if check["ready"]:
                ready.append(slim)
            else:
                not_ready.append(slim)
                for reason in check["missing"] or []:
                    if reason in missing_counts:
                        missing_counts[reason] += 1
        profiler.end("evaluate")
        profile = profiler.flush(status="done")
        # Persist a compact breakdown so we can inspect without UI scrolling.
        try:
            import json as _json
            import os as _os
            debug_path = _os.path.join(
                _os.path.dirname(_os.path.abspath(nesting_runtime_profile.__file__)),
                "nesting_not_ready_summary.json",
            )
            with open(debug_path, "w", encoding="utf-8") as handle:
                _json.dump(
                    {
                        "bodyCount": len(body_records),
                        "readyCount": len(ready),
                        "notReadyCount": len(not_ready),
                        "missingCounts": missing_counts,
                        "samples": not_ready[:40],
                    },
                    handle,
                    indent=2,
                    ensure_ascii=False,
                )
            profile["notReadySummaryPath"] = debug_path
        except Exception:
            debug_path = ""
        missing_bits = [
            "{} {}".format(count, name)
            for name, count in missing_counts.items()
            if count
        ]
        missing_msg = (
            " Missing among not-ready: {}.".format(", ".join(missing_bits))
            if missing_bits
            else ""
        )
        return "panelAttributesResult", {
            "ok": True,
            "action": "checkNestingReady",
            "bodyCount": len(body_records),
            "readyCount": len(ready),
            "notReadyCount": len(not_ready),
            "missingCounts": missing_counts,
            "ready": ready[:200],
            "notReady": not_ready[:200],
            "diagnostics": {
                **(diagnostics or {}),
                "elapsedMs": profile.get("elapsedMs"),
                "scanDetail": "nesting",
                "profilePath": profile.get("path"),
                "notReadySummaryPath": debug_path or profile.get("notReadySummaryPath"),
                "phasesMs": profile.get("phasesMs"),
                "missingCounts": missing_counts,
            },
            "profile": profile,
            "message": "Nesting Ready: {} / {} bodies.{}{}".format(
                len(ready),
                len(body_records),
                " {} not ready.".format(len(not_ready)) if not_ready else "",
                missing_msg,
            ),
        }

    def build_nesting_outlines(self, payload, _palette):
        """Step 1: flatten + extract outlines and write nestingFlatOutline cache."""
        import time as _time

        profiler = nesting_runtime_profile.NestingProfiler("buildNestingOutlines")
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "buildNestingOutlines",
                "errors": ["No active Fusion design."],
            }
        sheet_params = nesting_sheet_pack.normalize_sheet_params(
            (payload or {}).get("sheetParams") or {}
        )
        allow_parts_in_part = bool(sheet_params.get("allowPartsInPart"))
        records, _counts, diagnostics = metadata_inspector.scan_panel_metadata(
            root, zone_filter="all", detail="nesting", profiler=profiler
        )
        body_records = [
            record
            for record in records
            if "body" in str(record.get("entityKind") or "").lower()
        ]
        built = []
        skipped = []
        failed = []
        not_ready = []
        profiler.begin("buildOutlines")
        profiler.mark("buildBegin", candidates=len(body_records))
        for index, record in enumerate(body_records):
            check = nesting_preflight.evaluate_record(record)
            if not check["ready"]:
                not_ready.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "missing": check["missing"],
                })
                continue
            body, body_warnings = self._body_from_metadata_record(
                root, record, prefer_path=True
            )
            if not body:
                failed.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "reason": "Could not resolve source body.",
                    "warnings": body_warnings,
                })
                continue
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            signature = nesting_outline_cache.body_geometry_signature(body)
            reflected = bool(nesting_fusion_layout._body_has_reflection(body))
            status = nesting_outline_cache.outline_cache_status(
                metadata,
                signature,
                check["cuttingFace"],
                allow_parts_in_part=allow_parts_in_part,
                reflected_source=reflected,
            )
            force = bool((payload or {}).get("forceRebuild"))
            if status == "fresh" and not force:
                skipped.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "reason": "fresh",
                    "reflectedSource": reflected,
                })
                profiler.add("outlineCacheFresh", 1)
                if reflected:
                    profiler.add("reflectedFresh", 1)
                continue
            item_t0 = _time.perf_counter()
            try:
                temp_body, dimensions, outline = nesting_fusion_layout.prepare_flat_copy(
                    body,
                    metadata,
                    check["cuttingFace"],
                    allow_parts_in_part=allow_parts_in_part,
                )
                del temp_body
                reflected = bool((outline or {}).get("reflectedSource"))
                cache_record = nesting_outline_cache.build_cache_record(
                    outline,
                    dimensions,
                    signature,
                    check["cuttingFace"],
                    allow_parts_in_part=allow_parts_in_part,
                    reflected_source=reflected,
                    grain_along_mm=(dimensions or {}).get("grainAlongMm")
                    or (outline or {}).get("grainAlongMm"),
                )
                working = tag_metadata_editor._bootstrap_body_metadata(body, metadata)
                working[nesting_outline_cache.CACHE_KEY] = cache_record
                tag_metadata_editor._write_body_metadata(body, working)
                source = str((outline or {}).get("source") or "")
                built.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "source": source,
                    "pointCount": int((outline or {}).get("pointCount") or 0),
                    "previousStatus": status,
                    "reflectedSource": reflected,
                })
                profiler.add("outlineBuilt", 1)
                if reflected:
                    profiler.add("reflectedBuilt", 1)
                if source == "flatBody":
                    profiler.add("outlineFlatBody", 1)
                elif source == "metadataSvg":
                    profiler.add("outlineMetadataSvg", 1)
                else:
                    profiler.add("outlineRectangle", 1)
                item_ms = int((_time.perf_counter() - item_t0) * 1000)
                if item_ms >= 250:
                    profiler.sample(
                        "buildOutlineItem",
                        item_ms,
                        bodyName=record.get("bodyName") or "",
                    )
            except Exception as ex:
                failed.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "reason": str(ex),
                })
            if (len(built) + len(skipped)) % 10 == 0:
                profiler.mark(
                    "buildProgress",
                    built=len(built),
                    skipped=len(skipped),
                    failed=len(failed),
                )
            _pump_fusion_events()
        build_ms = profiler.end("buildOutlines")
        profile = profiler.flush(status="done")
        reflected_count = int(profiler.counters.get("reflectedBuilt") or 0) + int(
            profiler.counters.get("reflectedFresh") or 0
        )
        ok = bool(built) or (bool(skipped) and not failed)
        if not built and not skipped:
            ok = False
        message = (
            "Nesting outlines: built {} · reused fresh {} · mirrored {} · failed {} · not ready {}."
        ).format(
            len(built), len(skipped), reflected_count, len(failed), len(not_ready)
        )
        return "panelAttributesResult", {
            "ok": ok,
            "action": "buildNestingOutlines",
            "bodyCount": len(body_records),
            "builtCount": len(built),
            "skippedFreshCount": len(skipped),
            "reflectedCount": reflected_count,
            "failedCount": len(failed),
            "notReadyCount": len(not_ready),
            "built": built[:100],
            "skippedFresh": skipped[:100],
            "failed": failed[:100],
            "notReady": not_ready[:100],
            "allowPartsInPart": allow_parts_in_part,
            "diagnostics": {
                **(diagnostics or {}),
                "buildMs": build_ms,
                "profilePath": profile.get("path"),
                "phasesMs": profile.get("phasesMs"),
                "reflectedCount": reflected_count,
            },
            "profile": profile,
            "message": message,
            "errors": [] if ok else (
                ["No Nesting Ready panels to build outlines for."]
                if not built and not skipped
                else [entry.get("reason") or "Build failed." for entry in failed[:5]]
            ),
        }

    def create_nesting_zone_layout(self, payload, _palette):
        """Copy Nesting Ready source panels into sheet-packed Nesting Zone layout."""
        import time as _time

        profiler = nesting_runtime_profile.NestingProfiler("createNestingZoneLayout")
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "createNestingZoneLayout",
                "errors": ["No active Fusion design."],
            }
        zone_layout = work_zones.load_zone_layout(root)
        nesting_rect = (
            zone_layout.get(work_zones.ZONE_NESTING)
            if isinstance(zone_layout, dict)
            else None
        )
        if not isinstance(nesting_rect, dict):
            return "panelAttributesResult", {
                "ok": False,
                "action": "createNestingZoneLayout",
                "errors": ["Nesting Zone is not configured. Set Work Zones first."],
            }
        try:
            part_gap = max(float((payload or {}).get("partGapMm", 50.0)), 0.0)
            group_gap = max(float((payload or {}).get("groupGapMm", 300.0)), 0.0)
        except Exception:
            return "panelAttributesResult", {
                "ok": False,
                "action": "createNestingZoneLayout",
                "errors": ["Part gap and group gap must be valid non-negative numbers."],
            }
        sheet_params = nesting_sheet_pack.normalize_sheet_params(
            (payload or {}).get("sheetParams") or {}
        )
        # World sheet display wraps within the current Nesting Zone width instead
        # of expanding every material job into one unbounded horizontal strip.
        sheet_params["layoutWidthMm"] = max(
            float(nesting_rect["x1"]) - float(nesting_rect["x0"]),
            0.0,
        )

        records, _counts, diagnostics = metadata_inspector.scan_panel_metadata(
            root, zone_filter="all", detail="nesting", profiler=profiler
        )
        body_records = [
            record
            for record in records
            if "body" in str(record.get("entityKind") or "").lower()
        ]
        prepared = []
        not_ready = []
        failed = []
        outline_missing = []
        prepared_hole_outline_count = 0
        profiler.begin("prepare")
        profiler.mark("prepareBegin", candidates=len(body_records))
        for index, record in enumerate(body_records):
            check = nesting_preflight.evaluate_record(record)
            if not check["ready"]:
                not_ready.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "missing": check["missing"],
                })
                continue
            item_t0 = _time.perf_counter()
            resolve_t0 = _time.perf_counter()
            body, body_warnings = self._body_from_metadata_record(
                root, record, prefer_path=True
            )
            resolve_ms = int((_time.perf_counter() - resolve_t0) * 1000)
            if not body:
                failed.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "reason": "Could not resolve source body.",
                    "warnings": body_warnings,
                })
                continue
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            signature = nesting_outline_cache.body_geometry_signature(body)
            reflected = bool(nesting_fusion_layout._body_has_reflection(body))
            allow_pip = bool(sheet_params.get("allowPartsInPart"))
            cache_status = nesting_outline_cache.outline_cache_status(
                metadata,
                signature,
                check["cuttingFace"],
                allow_parts_in_part=allow_pip,
                reflected_source=reflected,
            )
            cached_outline, _cached_dims = nesting_outline_cache.cached_outline_for_prepare(
                metadata,
                signature,
                check["cuttingFace"],
                allow_parts_in_part=allow_pip,
                reflected_source=reflected,
            )
            if cache_status != "fresh" or not cached_outline:
                outline_missing.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "reason": cache_status or "missing",
                    "reflectedSource": reflected,
                })
                profiler.add("outlineCacheMiss", 1)
                continue
            try:
                copy_t0 = _time.perf_counter()
                temp_body, dimensions, outline = nesting_fusion_layout.prepare_flat_copy(
                    body,
                    metadata,
                    check["cuttingFace"],
                    allow_parts_in_part=bool(sheet_params.get("allowPartsInPart")),
                    outline_override=cached_outline,
                )
                copy_ms = int((_time.perf_counter() - copy_t0) * 1000)
                profiler.add("outlineCacheHit", 1)
                prepared.append({
                    "id": "{}|{}|{}".format(
                        record.get("entityToken") or record.get("panelId") or index,
                        "/".join(str(v) for v in (record.get("occurrencePath") or [])),
                        index,
                    ),
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "componentName": record.get("componentName") or "",
                    "assemblyName": _assembly_name_for_record(root, record),
                    "boardTypeTag": check["boardTypeTag"],
                    "colorTag": check["colorTag"],
                    "cuttingFace": check["cuttingFace"],
                    "tempBody": temp_body,
                    "dimensions": dimensions,
                    "outline": outline,
                })
                if isinstance(outline, dict):
                    hole_count = int(outline.get("holeCount") or 0)
                    prepared_hole_outline_count += hole_count
                    if hole_count:
                        profiler.add("preparedHoleOutlines", hole_count)
                    source = str(outline.get("source") or "")
                    if source == "flatBody":
                        profiler.add("outlineFlatBody", 1)
                    elif source == "metadataSvg":
                        profiler.add("outlineMetadataSvg", 1)
                    else:
                        profiler.add("outlineRectangle", 1)
                item_ms = int((_time.perf_counter() - item_t0) * 1000)
                profiler.add("preparedCount", 1)
                profiler.add("resolveMsTotal", resolve_ms)
                profiler.add("copyMsTotal", copy_ms)
                if item_ms >= 250:
                    profiler.sample(
                        "prepareItem",
                        item_ms,
                        bodyName=record.get("bodyName") or "",
                        resolveMs=resolve_ms,
                        copyMs=copy_ms,
                    )
                if len(prepared) % 10 == 0:
                    profiler.mark(
                        "prepareProgress",
                        prepared=len(prepared),
                        notReady=len(not_ready),
                        failed=len(failed),
                        outlineMissing=len(outline_missing),
                    )
            except Exception as ex:
                failed.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "reason": str(ex),
                })
        prepare_ms = profiler.end("prepare")

        if outline_missing:
            profile = profiler.flush(status="outlineCacheRequired")
            sample = ", ".join(
                str(item.get("bodyName") or item.get("panelId") or "?")
                for item in outline_missing[:5]
            )
            return "panelAttributesResult", {
                "ok": False,
                "action": "createNestingZoneLayout",
                "bodyCount": len(body_records),
                "readyCount": len(prepared),
                "outlineMissingCount": len(outline_missing),
                "outlineMissing": outline_missing[:100],
                "notReady": not_ready[:100],
                "failed": failed[:100],
                "diagnostics": {
                    **(diagnostics or {}),
                    "prepareMs": prepare_ms,
                    "profilePath": profile.get("path"),
                    "phasesMs": profile.get("phasesMs"),
                },
                "profile": profile,
                "errors": [
                    "Nesting outlines missing or stale for {} Ready panel(s). "
                    "Run Build Nesting Outlines first. Examples: {}.".format(
                        len(outline_missing),
                        sample or "—",
                    )
                ],
            }

        if not prepared:
            profile = profiler.flush(status="noPrepared")
            return "panelAttributesResult", {
                "ok": False,
                "action": "createNestingZoneLayout",
                "bodyCount": len(body_records),
                "readyCount": 0,
                "notReady": not_ready[:100],
                "failed": failed[:100],
                "diagnostics": {
                    **(diagnostics or {}),
                    "prepareMs": prepare_ms,
                    "profilePath": profile.get("path"),
                    "phasesMs": profile.get("phasesMs"),
                },
                "profile": profile,
                "errors": ["No Nesting Ready panel could be prepared."],
            }

        layout_items = [
            {
                **item,
                "widthMm": item["dimensions"]["widthMm"],
                "depthMm": item["dimensions"]["depthMm"],
                "outline": item.get("outline"),
            }
            for item in prepared
        ]
        profiler.begin("pack")
        profiler.mark("packBegin", parts=len(layout_items))
        _pump_fusion_events()
        measure = nesting_engine.create_layout(
            layout_items,
            sheet_params,
            nesting_rect["x0"],
            nesting_rect["y0"],
            engine_name=(payload or {}).get("nestingEngine"),
            wait_callback=_pump_fusion_events,
        )
        pack_ms = profiler.end("pack")
        profiler.mark("packDone", elapsedMs=pack_ms, engine=(measure or {}).get("engine"))
        _pump_fusion_events()
        profiler.begin("validate")
        collision_validation = nesting_collision_validate.validate_layout(
            measure, prepared, sheet_params
        )
        # Exact Fusion checks dominate large nests; Python outline check is enough.
        if len(prepared) < 80:
            collision_validation = nesting_collision_validate.validate_fusion_exact(
                measure, prepared, sheet_params, collision_validation
            )
        profiler.end("validate")
        primary_collision_validation = collision_validation
        validation_fallback = False
        validation_fallback_reason = ""
        if not collision_validation.get("ok"):
            validation_fallback = True
            validation_fallback_reason = (
                "Primary layout failed collision validation: {} collision(s), "
                "{} border violation(s), {} mapping error(s), "
                "{} sheet overlap(s), exact incomplete={}."
            ).format(
                int(collision_validation.get("collisionCount") or 0),
                int(collision_validation.get("borderViolationCount") or 0),
                int(collision_validation.get("mappingWarningCount") or 0),
                int(collision_validation.get("sheetOverlapCount") or 0),
                bool(collision_validation.get("exactValidationIncomplete")),
            )
            profiler.mark(
                "validationFallback",
                collisions=int(collision_validation.get("collisionCount") or 0),
                borderViolations=int(
                    collision_validation.get("borderViolationCount") or 0
                ),
                exactChecks=int(collision_validation.get("exactChecks") or 0),
            )
            try:
                import json as _json
                import os as _os

                dump_path = _os.path.join(
                    _os.path.dirname(
                        _os.path.abspath(nesting_runtime_profile.__file__)
                    ),
                    "nesting_primary_collision_dump.json",
                )
                with open(dump_path, "w", encoding="utf-8") as handle:
                    _json.dump(
                        {
                            "engine": measure.get("engine"),
                            "requestedEngine": measure.get("requestedEngine"),
                            "sheetCount": len(measure.get("sheets") or []),
                            "placementCount": len(measure.get("placements") or []),
                            "collisionValidation": {
                                "ok": collision_validation.get("ok"),
                                "status": collision_validation.get("status"),
                                "collisionCount": collision_validation.get(
                                    "collisionCount"
                                ),
                                "borderViolationCount": collision_validation.get(
                                    "borderViolationCount"
                                ),
                                "mappingWarningCount": collision_validation.get(
                                    "mappingWarningCount"
                                ),
                                "exactChecks": collision_validation.get("exactChecks"),
                                "checks": collision_validation.get("checks"),
                                "collisions": (
                                    collision_validation.get("collisions") or []
                                )[:100],
                                "mappingWarnings": (
                                    collision_validation.get("mappingWarnings") or []
                                )[:100],
                                "borderViolations": (
                                    collision_validation.get("borderViolations") or []
                                )[:50],
                            },
                        },
                        handle,
                        indent=2,
                        ensure_ascii=False,
                    )
                profiler.mark("primaryCollisionDump", path=dump_path)
            except Exception:
                pass
            primary_measure = measure
            fallback = nesting_sheet_pack.sheet_pack_layout(
                layout_items,
                sheet_params,
                nesting_rect["x0"],
                nesting_rect["y0"],
            )
            # Collision fallback is separate from an engine runtime fallback.
            # Carry the engine metadata without changing its meaning.
            for key in (
                "requestedEngine",
                "engineFallback",
                "engineFallbackReason",
            ):
                if key in primary_measure:
                    fallback[key] = primary_measure.get(key)
            fallback["validationFallback"] = True
            fallback["validationFallbackReason"] = validation_fallback_reason
            fallback_validation = nesting_collision_validate.validate_layout(
                fallback, prepared, sheet_params
            )
            fallback_validation = nesting_collision_validate.validate_fusion_exact(
                fallback, prepared, sheet_params, fallback_validation
            )
            if not fallback_validation.get("ok"):
                profile = profiler.flush(status="collisionValidationFailed")
                _discard_prepared_temp_bodies(prepared)
                return "panelAttributesResult", {
                    "ok": False,
                    "action": "createNestingZoneLayout",
                    "bodyCount": len(body_records),
                    "readyCount": len(prepared),
                    "sheetParams": sheet_params,
                    "collisionValidation": fallback_validation,
                    "collisionCount": int(
                        fallback_validation.get("collisionCount") or 0
                    ),
                    "collisions": (fallback_validation.get("collisions") or [])[:100],
                    "mappingWarnings": (
                        fallback_validation.get("mappingWarnings") or []
                    )[:100],
                    "mappingWarningCount": int(
                        fallback_validation.get("mappingWarningCount") or 0
                    ),
                    "sheetOverlaps": (
                        fallback_validation.get("sheetOverlaps") or []
                    )[:50],
                    "sheetOverlapCount": int(
                        fallback_validation.get("sheetOverlapCount") or 0
                    ),
                    "exactValidationIncomplete": bool(
                        fallback_validation.get("exactValidationIncomplete")
                    ),
                    "exactCheckWarnings": (
                        fallback_validation.get("exactCheckWarnings") or []
                    )[:50],
                    "validationFallback": True,
                    "validationFallbackReason": validation_fallback_reason,
                    "primaryCollisionValidation": collision_validation,
                    "profile": profile,
                    "errors": [
                        "Both the primary and fallback layouts failed collision validation; "
                        "the existing Nesting layout was preserved."
                    ],
                }
            measure = fallback
            collision_validation = fallback_validation
        required_w = float(measure.get("requiredWidthMm") or 0.0)
        required_d = float(measure.get("requiredDepthMm") or 0.0)
        unplaced = list(measure.get("unplaced") or [])
        if unplaced and not measure.get("placements"):
            profile = profiler.flush(status="unplacedOnly")
            _discard_prepared_temp_bodies(prepared)
            return "panelAttributesResult", {
                "ok": False,
                "action": "createNestingZoneLayout",
                "bodyCount": len(body_records),
                "readyCount": len(prepared),
                "unplacedCount": len(unplaced),
                "unplaced": _strip_temp_bodies_for_json(unplaced[:100]),
                "sheetParams": sheet_params,
                "profile": profile,
                "errors": [
                    "No parts fit on the configured sheets. "
                    "Check Sheet size / border, or enable rotation."
                ],
            }
        zone_w = float(nesting_rect["x1"]) - float(nesting_rect["x0"])
        zone_d = float(nesting_rect["y1"]) - float(nesting_rect["y0"])
        previous_nesting_size = (zone_w, zone_d)
        zone_grown = False
        grow_notes = []
        if required_w > zone_w + 1e-6 or required_d > zone_d + 1e-6:
            profiler.begin("growZone")
            grown_layout = work_zones.grow_nesting_zone(
                zone_layout, required_w, required_d
            )
            if work_zones.zones_overlap(grown_layout):
                profile = profiler.flush(status="growOverlap")
                _discard_prepared_temp_bodies(prepared)
                return "panelAttributesResult", {
                    "ok": False,
                    "action": "createNestingZoneLayout",
                    "bodyCount": len(body_records),
                    "readyCount": len(prepared),
                    "notReady": not_ready[:100],
                    "failed": failed[:100],
                    "requiredWidthMm": required_w,
                    "requiredDepthMm": required_d,
                    "sheetParams": sheet_params,
                    "profile": profile,
                    "errors": [
                        "Nesting Zone would overlap other zones after expanding "
                        "to {:.0f} x {:.0f} mm.".format(required_w, required_d)
                    ],
                }
            app = adsk.core.Application.get()
            design = app.activeProduct if app else None
            grow_notes = self._rebuild_work_zone_visuals(root, grown_layout, app, design)
            work_zones.save_zone_layout(root, grown_layout)
            zone_layout = grown_layout
            nesting_rect = grown_layout.get(work_zones.ZONE_NESTING)
            zone_grown = True
            profiler.end("growZone")

        profiler.begin("createBodies")
        profiler.mark("createBegin", prepared=len(prepared))
        try:
            result = nesting_fusion_layout.create_layout(
                root,
                prepared,
                nesting_rect,
                part_gap,
                group_gap,
                profiler=profiler,
                layout=measure,
                sheet_params=sheet_params,
                wait_callback=_pump_fusion_events,
                prevalidated_validation=collision_validation,
            )
        except Exception as ex:
            profile = profiler.flush(status="createFailed")
            _discard_prepared_temp_bodies(prepared)
            return "panelAttributesResult", {
                "ok": False,
                "action": "createNestingZoneLayout",
                "bodyCount": len(body_records),
                "readyCount": len(prepared),
                "notReady": not_ready[:100],
                "failed": failed[:100],
                "zoneGrown": zone_grown,
                "sheetParams": sheet_params,
                "diagnostics": {
                    "prepareMs": prepare_ms,
                    "profilePath": profile.get("path"),
                    "phasesMs": profile.get("phasesMs"),
                },
                "profile": profile,
                "errors": [str(ex)],
            }
        create_ms = profiler.end("createBodies")
        # Unplaced prepared copies were never promoted into NESTING_LAYOUT.
        _discard_prepared_temp_bodies(result.get("unplaced") or unplaced)
        try:
            app = adsk.core.Application.get()
            if app and app.activeViewport:
                app.activeViewport.fit()
                app.activeViewport.refresh()
        except Exception:
            pass
        final_w, final_d = work_zones.rect_size(nesting_rect)
        profile = profiler.flush(status="done")
        grow_msg = ""
        if zone_grown:
            grow_msg = (
                " Nesting Zone expanded from {:.0f}×{:.0f} to {:.0f}×{:.0f} mm "
                "(keeps at least the manual size)."
            ).format(
                previous_nesting_size[0],
                previous_nesting_size[1],
                final_w or 0.0,
                final_d or 0.0,
            )
        phases = profile.get("phasesMs") or {}
        counters = profile.get("counters") or {}
        skipped_no_attrs = int(counters.get("bodiesSkippedNoAttrs") or 0)
        sheet_count = len(result.get("sheets") or measure.get("sheets") or [])
        unplaced_count = len(result.get("unplaced") or unplaced)
        outline_counts = measure.get("outlineCounts") or {}
        true_shape = int(measure.get("trueShapeCount") or 0)
        rect_fallback = int(measure.get("rectangleFallbackCount") or 0)
        util_bits = []
        for sheet in (result.get("sheets") or measure.get("sheets") or [])[:8]:
            util_bits.append(
                "{}:{:.0f}%".format(
                    sheet.get("boardTypeTag") or "?",
                    100.0 * float(sheet.get("utilization") or 0.0),
                )
            )
        util_msg = (", sheets " + ", ".join(util_bits)) if util_bits else ""
        unplaced_msg = (
            " Unplaced {} (oversized for sheet).".format(unplaced_count)
            if unplaced_count
            else ""
        )
        outline_msg = " Outlines: {} true-shape · {} rectangle fallback.".format(
            true_shape,
            rect_fallback,
        )
        engine_fallback = bool(
            result.get("engineFallback") or measure.get("engineFallback")
        )
        engine_fallback_reason = (
            result.get("engineFallbackReason")
            or measure.get("engineFallbackReason")
            or ""
        )
        fallback_msg = (
            " Deepnest fallback used: {}.".format(engine_fallback_reason)
            if engine_fallback
            else ""
        )
        hole_outline_count = int(measure.get("holeOutlineCount") or 0)
        nested_in_hole_count = int(measure.get("nestedInHoleCount") or 0)
        parts_in_part_applied = bool(measure.get("partsInPartApplied"))
        holes_msg = (
            " Through holes: {} sent · {} nested inside.".format(
                hole_outline_count, nested_in_hole_count
            )
            if parts_in_part_applied
            else ""
        )
        validation_msg = (
            " Collision validation: {}{}.".format(
                collision_validation.get("status") or "unknown",
                " (sheet_pack safety fallback)"
                if validation_fallback
                else "",
            )
        )
        return "panelAttributesResult", {
            "ok": True,
            "action": "createNestingZoneLayout",
            "bodyCount": len(body_records),
            "readyCount": len(prepared),
            "createdCount": int(result.get("created") or 0),
            "groupCount": len(result.get("groups") or []),
            "sheetCount": sheet_count,
            "deletedPreviousCount": int(result.get("deletedPrevious") or 0),
            "notReadyCount": len(not_ready),
            "failedCount": len(failed),
            "unplacedCount": unplaced_count,
            "skippedNoAttrsCount": skipped_no_attrs,
            "trueShapeCount": true_shape,
            "rectangleFallbackCount": rect_fallback,
            "outlineCounts": outline_counts,
            "notReady": not_ready[:100],
            "failed": failed[:100],
            "unplaced": _strip_temp_bodies_for_json(
                (result.get("unplaced") or unplaced)[:100]
            ),
            "groups": result.get("groups") or [],
            "sheets": _strip_temp_bodies_for_json(
                result.get("sheets") or measure.get("sheets") or []
            ),
            "placements": _strip_temp_bodies_for_json(
                result.get("placements") or []
            ),
            "requiredWidthMm": result.get("requiredWidthMm"),
            "requiredDepthMm": result.get("requiredDepthMm"),
            "partGapMm": part_gap,
            "groupGapMm": group_gap,
            "sheetParams": sheet_params,
            "engine": result.get("engine") or measure.get("engine") or "sheet_pack_hybrid_v3",
            "requestedEngine": result.get("requestedEngine")
            or measure.get("requestedEngine"),
            "engineFallback": engine_fallback,
            "engineFallbackReason": engine_fallback_reason,
            "partsInPartApplied": parts_in_part_applied,
            "holeOutlineCount": hole_outline_count,
            "nestedInHoleCount": nested_in_hole_count,
            "bridgeHealth": measure.get("bridgeHealth") or {},
            "collisionValidation": collision_validation,
            "collisionCount": int(collision_validation.get("collisionCount") or 0),
            "collisions": (collision_validation.get("collisions") or [])[:100],
            "mappingWarnings": (
                collision_validation.get("mappingWarnings") or []
            )[:100],
            "mappingWarningCount": int(
                collision_validation.get("mappingWarningCount") or 0
            ),
            "sheetOverlaps": (
                collision_validation.get("sheetOverlaps") or []
            )[:50],
            "sheetOverlapCount": int(
                collision_validation.get("sheetOverlapCount") or 0
            ),
            "exactValidationIncomplete": bool(
                collision_validation.get("exactValidationIncomplete")
            ),
            "exactCheckWarnings": (
                collision_validation.get("exactCheckWarnings") or []
            )[:50],
            "validationFallback": validation_fallback,
            "validationFallbackReason": validation_fallback_reason,
            "primaryCollisionValidation": (
                primary_collision_validation if validation_fallback else None
            ),
            "zoneGrown": zone_grown,
            "previousNestingWidthMm": previous_nesting_size[0],
            "previousNestingDepthMm": previous_nesting_size[1],
            "nestingWidthMm": final_w,
            "nestingDepthMm": final_d,
            "layout": zone_layout,
            "growNotes": grow_notes,
            "diagnostics": {
                **(diagnostics or {}),
                "prepareMs": prepare_ms,
                "createMs": create_ms,
                "elapsedMs": profile.get("elapsedMs"),
                "scanDetail": "nesting",
                "profilePath": profile.get("path"),
                "phasesMs": phases,
                "bodiesSkippedNoAttrs": skipped_no_attrs,
                "layoutEngine": result.get("engine") or measure.get("engine") or "sheet_pack_hybrid_v3",
                "engineFallback": engine_fallback,
                "engineFallbackReason": engine_fallback_reason,
                "collisionValidation": collision_validation,
                "validationFallback": validation_fallback,
                "validationFallbackReason": validation_fallback_reason,
                "outlineCounts": outline_counts,
                "preparedHoleOutlineCount": prepared_hole_outline_count,
                "bridgeHealth": measure.get("bridgeHealth") or {},
            },
            "profile": profile,
            "message": (
                "Created {} Nesting workpiece(s) on {} sheet(s) "
                "from {} Nesting Ready panel(s) via {}; "
                "not ready {}, failed {}, unmarked solids skipped {}{}{}{}{}{}{}. "
                "Timing: scan {} ms · prepare {} ms · create {} ms · total {} ms."
                "{}"
            ).format(
                int(result.get("created") or 0),
                sheet_count,
                len(prepared),
                result.get("engine") or measure.get("engine") or "sheet_pack_hybrid_v3",
                len(not_ready),
                len(failed),
                skipped_no_attrs,
                util_msg,
                unplaced_msg,
                outline_msg,
                fallback_msg,
                holes_msg,
                validation_msg,
                int(phases.get("scanWalk") or 0),
                prepare_ms,
                create_ms,
                profile.get("elapsedMs"),
                grow_msg,
            ),
        }

    def create_nesting_layout_sketch(self, _payload, _palette):
        """Create a top-down projection sketch on NESTING_LAYOUT for manual DXF export."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "createNestingLayoutSketch",
                "errors": ["No active Fusion design."],
            }

        def _progress(done, total):
            _pump_fusion_events()

        result = nesting_dxf_export.create_nesting_layout_sketch(
            root, progress_callback=_progress
        )
        if not result.get("ok"):
            return "panelAttributesResult", {
                "ok": False,
                "action": "createNestingLayoutSketch",
                "errors": [result.get("error") or "Could not create nesting sketch."],
                "bodyCount": int(result.get("bodyCount") or 0),
                "ringCount": int(result.get("ringCount") or 0),
            }
        try:
            self.fusion.refresh_viewport()
        except Exception:
            pass
        return "panelAttributesResult", {
            "ok": True,
            "action": "createNestingLayoutSketch",
            "sketchName": result.get("sketchName") or "",
            "componentName": result.get("componentName") or "",
            "bodyCount": int(result.get("bodyCount") or 0),
            "ringCount": int(result.get("ringCount") or 0),
            "lineCount": int(result.get("lineCount") or 0),
            "deletedPrevious": int(result.get("deletedPrevious") or 0),
            "message": (
                "Intersect sketch {} on {} (cut {:.1f} mm): "
                "{} body(ies), {} curve(s) via {}. "
                "Right-click the sketch → Save as DXF."
            ).format(
                result.get("sketchName") or "NESTING_DXF_PROJECTION",
                result.get("componentName") or "NESTING_LAYOUT",
                float(result.get("cutZmm") or 0.0),
                int(result.get("bodyCount") or 0),
                int(result.get("projectedCount") or result.get("lineCount") or 0),
                result.get("method") or "projectMillingFace",
            ),
        }

    def export_nesting_layout_dxf(self, payload, _palette):
        """Export the current NESTING_LAYOUT as one top-down ArtCAM DXF (single layer)."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "exportNestingLayoutDxf",
                "errors": ["No active Fusion design."],
            }
        app = adsk.core.Application.get()
        ui = app.userInterface if app else None
        default_name = str((payload or {}).get("fileName") or "nesting_layout.dxf")
        path = nesting_dxf_export.choose_dxf_save_path(ui, default_name=default_name)
        if not path:
            return "panelAttributesResult", {
                "ok": False,
                "action": "exportNestingLayoutDxf",
                "cancelled": True,
                "errors": ["DXF export cancelled."],
            }
        result = nesting_dxf_export.export_nesting_layout_dxf(
            root,
            path,
            layer=str((payload or {}).get("layer") or "0"),
        )
        if not result.get("ok"):
            return "panelAttributesResult", {
                "ok": False,
                "action": "exportNestingLayoutDxf",
                "errors": [result.get("error") or "DXF export failed."],
                "bodyCount": int(result.get("bodyCount") or 0),
                "ringCount": int(result.get("ringCount") or 0),
            }
        return "panelAttributesResult", {
            "ok": True,
            "action": "exportNestingLayoutDxf",
            "path": result.get("path") or path,
            "bodyCount": int(result.get("bodyCount") or 0),
            "ringCount": int(result.get("ringCount") or 0),
            "componentName": result.get("componentName") or "",
            "layer": result.get("layer") or "0",
            "message": (
                "Exported nesting DXF: {} body(ies), {} polyline(s) → {}."
            ).format(
                int(result.get("bodyCount") or 0),
                int(result.get("ringCount") or 0),
                result.get("path") or path,
            ),
        }

    def export_manufacturing_snapshot(self, payload, _palette):
        """Export validated panels as one single-side .cnjob job list.

        ``scope=layflat`` is the production path and cannot bypass Analyze /
        Export Ready. ``selection`` and ``all`` remain source-geometry
        diagnostics for compatibility.
        """
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "exportManufacturingSnapshot",
                "errors": ["No active Fusion design."],
            }

        app = adsk.core.Application.get()
        ui = app.userInterface if app else None
        if ui is None:
            return "panelAttributesResult", {
                "ok": False,
                "action": "exportManufacturingSnapshot",
                "errors": ["Fusion file dialog is unavailable."],
            }

        scope = str((payload or {}).get("scope") or "selection").strip().lower() or "selection"
        if scope not in ("selection", "all", "layflat"):
            scope = "selection"

        body_records = []
        skipped = []
        scan_diagnostics = {}
        export_bodies = []
        if scope == "layflat":
            export_bodies = nesting_lay_flat_face_up.collect_lay_flat_bodies(root)
            if not export_bodies:
                return "panelAttributesResult", {
                    "ok": False,
                    "action": "exportManufacturingSnapshot",
                    "errors": ["No LAY_FLAT bodies found. Run Lay Flat first."],
                    "scope": scope,
                }
            ready_result = nesting_lay_flat_export_ready.check_bodies(
                export_bodies,
                wait_callback=_pump_fusion_events,
            )
            if int(ready_result.get("notReadyCount") or 0) > 0:
                not_ready = []
                for item in list(ready_result.get("notReady") or [])[:80]:
                    not_ready.append(
                        {
                            "bodyName": item.get("bodyName") or "",
                            "panelId": item.get("panelId") or "",
                            "reasons": list(item.get("reasons") or []),
                        }
                    )
                return "panelAttributesResult", {
                    "ok": False,
                    "action": "exportManufacturingSnapshot",
                    "errors": [
                        "Export blocked: {}/{} LAY_FLAT body(ies) are not Export Ready."
                        .format(
                            int(ready_result.get("notReadyCount") or 0),
                            int(ready_result.get("bodyCount") or 0),
                        )
                    ],
                    "notReady": not_ready,
                    "reasonCounts": ready_result.get("reasonCounts") or {},
                    "scope": scope,
                    "selectedBodyCount": len(export_bodies),
                }
            body_records, body_skips = self._records_for_manufacturing_export(
                root, export_bodies
            )
            skipped.extend(body_skips)
        elif scope == "all":
            records, _counts, scan_diagnostics = metadata_inspector.scan_panel_metadata(
                root, zone_filter="all", detail="full"
            )
            body_records = [
                record
                for record in records
                if "body" in str(record.get("entityKind") or "").lower()
            ]
        else:
            selected_entities = self._selected_entities()
            if not selected_entities:
                return "panelAttributesResult", {
                    "ok": False,
                    "action": "exportManufacturingSnapshot",
                    "errors": [
                        "Select one or more panel bodies (or a cabinet occurrence) first, "
                        "then Export Selected → .cnjob."
                    ],
                    "scope": scope,
                }
            bodies, expand_warnings = metadata_inspector.bodies_from_selected_entities(
                selected_entities, root
            )
            export_bodies = list(bodies or [])
            selected_lay_flat = [
                body
                for body in export_bodies
                if work_zones.is_lay_flat_workpiece(body)
            ]
            if selected_lay_flat:
                ready_result = nesting_lay_flat_export_ready.check_bodies(
                    selected_lay_flat,
                    wait_callback=_pump_fusion_events,
                )
                if int(ready_result.get("notReadyCount") or 0) > 0:
                    return "panelAttributesResult", {
                        "ok": False,
                        "action": "exportManufacturingSnapshot",
                        "errors": [
                            "Export blocked: selected LAY_FLAT bodies are not Export Ready."
                        ],
                        "notReady": [
                            {
                                "bodyName": item.get("bodyName") or "",
                                "panelId": item.get("panelId") or "",
                                "reasons": list(item.get("reasons") or []),
                            }
                            for item in list(ready_result.get("notReady") or [])[:80]
                        ],
                        "reasonCounts": ready_result.get("reasonCounts") or {},
                        "scope": scope,
                        "selectedBodyCount": len(export_bodies),
                    }
            skipped.extend(list(expand_warnings or []))
            body_records, body_skips = self._records_for_manufacturing_export(root, bodies)
            skipped.extend(body_skips)

        if not body_records:
            return "panelAttributesResult", {
                "ok": False,
                "action": "exportManufacturingSnapshot",
                "errors": [
                    "No exportable source panel bodies found under the current selection."
                    if scope == "selection"
                    else (
                        "No analyzed LAY_FLAT bodies found."
                        if scope == "layflat"
                        else "No exportable source panel bodies found in the design."
                    )
                ],
                "warnings": skipped[:20],
                "scope": scope,
                "selectedBodyCount": 0,
            }

        for record in body_records:
            if not str(record.get("assemblyName") or "").strip():
                record["assemblyName"] = _assembly_name_for_record(root, record)

        design_name = str(
            (payload or {}).get("designName")
            or getattr(getattr(app, "activeDocument", None), "name", "")
            or "cabinet_job"
        ).strip()
        job_id = str((payload or {}).get("jobId") or design_name).strip()
        default_name = str(
            (payload or {}).get("fileName") or "{}.cnjob".format(design_name)
        )
        if not default_name.lower().endswith(".cnjob"):
            default_name += ".cnjob"

        # Validate the exact snapshot before asking the user for a path. This is
        # the same builder used for the final write, so Ready cannot diverge
        # from the serialized contract.
        result = manufacturing_snapshot_export.build_snapshot(
            body_records,
            job_id,
            source={
                "cadApp": "Fusion 360",
                "pluginId": "fusion360-unified-cabinet-plugin",
                "pluginVersion": str((payload or {}).get("pluginVersion") or "development"),
                "designName": design_name,
                "exportScope": scope,
            },
        )
        warnings = list(skipped[:20]) + list(result.get("warnings") or [])
        if not result.get("ok"):
            messages = [
                "{}: {}".format(item.get("code") or "export", item.get("message") or "")
                for item in result.get("errors") or []
            ]
            return "panelAttributesResult", {
                "ok": False,
                "action": "exportManufacturingSnapshot",
                "errors": messages or ["Manufacturing snapshot validation failed."],
                "diagnostics": result.get("errors") or [],
                "scanDiagnostics": scan_diagnostics,
                "warnings": warnings,
                "scope": scope,
                "selectedBodyCount": len(body_records),
            }

        dialog = ui.createFileDialog()
        dialog.isMultiSelectEnabled = False
        dialog.title = (
            "Export Analyzed LAY_FLAT → CabinetNC Job"
            if scope == "layflat"
            else (
                "Export Selected Source Panels (Diagnostic)"
                if scope == "selection"
                else "Export All Source Panels (Diagnostic)"
            )
        )
        dialog.filter = "CabinetNC manufacturing job (*.cnjob)"
        dialog.initialFilename = default_name
        if dialog.showSave() != adsk.core.DialogResults.DialogOK:
            return "panelAttributesResult", {
                "ok": False,
                "action": "exportManufacturingSnapshot",
                "cancelled": True,
                "errors": ["Manufacturing snapshot export cancelled."],
                "scope": scope,
            }

        path = str(dialog.filename or "").strip()
        if path and not path.lower().endswith(".cnjob"):
            path += ".cnjob"

        try:
            result["path"] = manufacturing_snapshot_export.write_cnjob(
                path, result.get("snapshot") or {}
            )
        except Exception as ex:
            return "panelAttributesResult", {
                "ok": False,
                "action": "exportManufacturingSnapshot",
                "errors": ["write_failed: {}".format(ex)],
                "scanDiagnostics": scan_diagnostics,
                "warnings": warnings,
                "scope": scope,
                "selectedBodyCount": len(body_records),
            }

        snapshot = result.get("snapshot") or {}
        workpiece_count = len(snapshot.get("workpieces") or [])
        return "panelAttributesResult", {
            "ok": True,
            "action": "exportManufacturingSnapshot",
            "path": result.get("path") or path,
            "jobId": snapshot.get("jobId") or job_id,
            "workpieceCount": workpiece_count,
            "selectedBodyCount": len(body_records),
            "skippedCount": len(skipped),
            "warningCount": len(warnings),
            "warnings": warnings,
            "scope": scope,
            "message": (
                "Exported {} analyzed LAY_FLAT panel(s) → {}."
                if scope == "layflat"
                else (
                    "Exported {} selected source panel(s) (diagnostic) → {}."
                    if scope == "selection"
                    else "Exported {} source panel(s) (diagnostic) → {}."
                )
            ).format(workpiece_count, result.get("path") or path),
        }

    def create_lay_flat_layout(self, payload, _palette):
        """Lay Flat: copy Ready panels with machining face +Z, columns by board type."""
        import time as _time

        profiler = nesting_runtime_profile.NestingProfiler("createLayFlatLayout")
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "createLayFlatLayout",
                "errors": ["No active Fusion design."],
            }

        scope = str((payload or {}).get("scope") or "selection").strip().lower() or "selection"
        if scope not in ("selection", "all"):
            scope = "selection"

        selected_source_bodies = []
        selection_warnings = []
        if scope == "selection":
            selected_source_bodies, selection_warnings, selection_error = (
                self._source_bodies_from_ui_selection(root)
            )
            if selection_error:
                return "panelAttributesResult", {
                    "ok": False,
                    "action": "createLayFlatLayout",
                    "errors": [selection_error],
                    "warnings": selection_warnings[:20],
                    "scope": scope,
                    "selectedBodyCount": 0,
                }

        # Source metadata is the only classification authority. Overrides were
        # a compensation for failed source writes and caused panelId fan-out.
        # Transactional Apply now verifies source writes, so purge legacy maps.
        override_warnings = []
        harvested = {}
        synced_overrides = []
        sync_failed = []
        overrides = {}
        try:
            t_ov = _time.perf_counter()
            stored = nesting_lay_flat_tag_overrides.load_overrides(root)
            if stored:
                nesting_lay_flat_tag_overrides.save_overrides(root, {})
                override_warnings.append(
                    "Removed {} legacy Lay Flat override(s); source tags are authoritative."
                    .format(len(stored))
                )
            profiler.sample(
                "layFlatTagOverrides",
                int((_time.perf_counter() - t_ov) * 1000),
                harvested=0,
                stored=len(stored or {}),
                kept=0,
                synced=0,
                syncFailed=0,
            )
        except Exception as ex:
            override_warnings.append(
                "Lay Flat tag override cleanup failed: {}".format(ex)
            )

        # Speed path: clear Nesting Zone copies before scan so scanWalk does not
        # walk prior NESTING_LAYOUT / LAY_FLAT bodies (was ~95% of runtime).
        deleted_previous = 0
        try:
            t_del = _time.perf_counter()
            deleted_previous = int(
                nesting_fusion_layout.delete_previous_layouts(root) or 0
            )
            deleted_previous += int(
                nesting_lay_flat_fusion.delete_previous_lay_flat(root) or 0
            )
            profiler.sample(
                "deletePreviousLayouts",
                int((_time.perf_counter() - t_del) * 1000),
                deleted=deleted_previous,
            )
        except Exception:
            deleted_previous = 0

        # Light/nesting scan is enough for Ready + outline cache; full face
        # registry / SVG walk is the expensive path and unused here.
        zone_filter = str((payload or {}).get("zoneFilter") or "all").strip().lower() or "all"
        diagnostics = {}
        if scope == "selection":
            body_records, rec_skips = self._records_for_selected_lay_flat(
                root, selected_source_bodies
            )
            diagnostics = {
                "warnings": list(selection_warnings or []) + list(rec_skips or []),
            }
            profiler.sample(
                "selectedLayFlatRecords",
                0,
                selected=len(selected_source_bodies),
                records=len(body_records),
            )
        else:
            records, _counts, diagnostics = metadata_inspector.scan_panel_metadata(
                root, zone_filter=zone_filter, detail="nesting", profiler=profiler
            )
            body_records = [
                record
                for record in records
                if "body" in str(record.get("entityKind") or "").lower()
            ]

        prepared = []
        not_ready = []
        failed = []
        profiler.begin("prepareLayFlat")
        for index, record in enumerate(body_records):
            check = nesting_preflight.evaluate_record(record)
            if not check.get("ready"):
                not_ready.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "missing": check.get("missing") or [],
                })
                continue
            # Same resolver as Nesting Create Layout — find_body_in_design fails on
            # duplicate Body1 / manual.Body1 names without occurrencePath proxies.
            body, body_warnings = self._body_from_metadata_record(
                root, record, prefer_path=True
            )
            if body is None:
                failed.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "componentName": record.get("componentName") or "",
                    "occurrencePath": list(record.get("occurrencePath") or []),
                    "reason": "body_not_found",
                    "warnings": body_warnings,
                })
                continue
            metadata = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            panel_id = str(record.get("panelId") or "").strip()
            assembly_name = _assembly_name_for_record(root, record)
            source_record = dict(record)
            source_record["assemblyName"] = assembly_name
            source_ref = panel_source_ref.from_scan_record(source_record)
            if not source_ref:
                failed.append(
                    {
                        "panelId": panel_id,
                        "bodyName": record.get("bodyName") or "",
                        "componentName": record.get("componentName") or "",
                        "occurrencePath": list(
                            record.get("occurrencePath") or []
                        ),
                        "reason": "missing_source_lineage",
                    }
                )
                continue
            board_tag = check.get("boardTypeTag") or ""
            color_tag = check.get("colorTag") or ""
            try:
                item_t0 = _time.perf_counter()
                cached_outline, _cached_dims = nesting_outline_cache.cached_outline_for_prepare(
                    metadata,
                    nesting_outline_cache.body_geometry_signature(body),
                    check["cuttingFace"],
                    allow_parts_in_part=False,
                    reflected_source=bool(
                        nesting_fusion_layout._body_has_reflection(body)
                    ),
                )
                temp_body, dimensions, outline = nesting_fusion_layout.prepare_flat_copy(
                    body,
                    metadata,
                    check["cuttingFace"],
                    allow_parts_in_part=False,
                    outline_override=cached_outline,
                )
                source_fields = panel_source_ref.to_legacy_fields(source_ref)
                prepared.append({
                    "id": "{}|{}|{}".format(
                        record.get("entityToken") or record.get("panelId") or index,
                        "/".join(str(v) for v in (record.get("occurrencePath") or [])),
                        index,
                    ),
                    "panelId": panel_id,
                    "bodyName": record.get("bodyName") or "",
                    "componentName": record.get("componentName") or "",
                    "assemblyName": assembly_name,
                    "boardTypeTag": board_tag,
                    "colorTag": color_tag,
                    "cuttingFace": check["cuttingFace"],
                    "tempBody": temp_body,
                    "dimensions": dimensions,
                    "outline": outline,
                    "metadata": metadata,
                    "sourceRef": source_ref,
                    "sourceKey": panel_source_ref.key(source_ref),
                    # Compatibility fields for old consumers.
                    **source_fields,
                    "occurrencePath": list(record.get("occurrencePath") or []),
                })
                profiler.sample(
                    "prepareLayFlatItem",
                    int((_time.perf_counter() - item_t0) * 1000),
                    panelId=record.get("panelId") or "",
                )
            except Exception as ex:
                failed.append({
                    "panelId": record.get("panelId") or "",
                    "bodyName": record.get("bodyName") or "",
                    "reason": str(ex),
                })
        profiler.end("prepareLayFlat")

        if not prepared:
            profile = profiler.flush(status="noPrepared")
            no_ready_msg = (
                "No Nesting Ready panels in the current selection."
                if scope == "selection"
                else "No Nesting Ready panels to lay flat."
            )
            return "panelAttributesResult", {
                "ok": False,
                "action": "createLayFlatLayout",
                "errors": [
                    "{} failed={} notReady={} (see failed/notReady lists)."
                    .format(no_ready_msg, len(failed), len(not_ready))
                ],
                "scope": scope,
                "bodyCount": len(body_records),
                "notReadyCount": len(not_ready),
                "failedCount": len(failed),
                "notReady": not_ready[:50],
                "failed": failed[:50],
                "diagnostics": diagnostics,
                "profile": profile,
            }

        zone_layout = work_zones.load_zone_layout(root) or {}
        nesting_rect = zone_layout.get(work_zones.ZONE_NESTING)
        if not isinstance(nesting_rect, dict):
            return "panelAttributesResult", {
                "ok": False,
                "action": "createLayFlatLayout",
                "errors": ["Nesting Zone is not configured. Set Work Zones first."],
                "scope": scope,
                "preparedCount": len(prepared),
                "notReadyCount": len(not_ready),
                "failedCount": len(failed),
            }

        part_gap = float((payload or {}).get("partGapMm") or 50.0)
        column_gap = float((payload or {}).get("columnGapMm") or 200.0)
        # Same Nesting Zone as sheet nesting — Lay Flat replaces NESTING_LAYOUT.
        origin_x = float(nesting_rect.get("x0") or 0.0)
        origin_y = float(nesting_rect.get("y0") or 0.0)

        # Pre-measure column pack so the Nesting Zone can grow before body create.
        pack_preview = nesting_lay_flat.column_layout(
            [
                {
                    "id": item["id"],
                    "boardTypeTag": item.get("boardTypeTag") or "",
                    "colorTag": item.get("colorTag") or "",
                    "widthMm": float((item.get("dimensions") or {}).get("widthMm") or 0.0),
                    "depthMm": float((item.get("dimensions") or {}).get("depthMm") or 0.0),
                }
                for item in prepared
            ],
            origin_x_mm=origin_x,
            origin_y_mm=origin_y,
            part_gap_mm=part_gap,
            column_gap_mm=column_gap,
            group_by_color=True,
        )
        bounds = pack_preview.get("bounds") or {}
        required_w = max(
            float(bounds.get("x1") or origin_x) - origin_x,
            float(nesting_rect.get("x1") or 0.0) - origin_x,
        )
        required_d = max(
            float(bounds.get("y1") or origin_y) - origin_y,
            float(nesting_rect.get("y1") or 0.0) - origin_y,
        )
        zone_grown = False
        try:
            grown_layout = work_zones.grow_nesting_zone(
                zone_layout, required_w, required_d
            )
            if grown_layout and not work_zones.zones_overlap(grown_layout):
                old_w, old_d = work_zones.rect_size(nesting_rect)
                new_w, new_d = work_zones.rect_size(
                    grown_layout.get(work_zones.ZONE_NESTING)
                )
                if (new_w or 0) > (old_w or 0) + 0.5 or (new_d or 0) > (old_d or 0) + 0.5:
                    work_zones.save_zone_layout(root, grown_layout)
                    zone_layout = grown_layout
                    nesting_rect = grown_layout.get(work_zones.ZONE_NESTING) or nesting_rect
                    origin_x = float(nesting_rect.get("x0") or origin_x)
                    origin_y = float(nesting_rect.get("y0") or origin_y)
                    zone_grown = True
                    try:
                        app = adsk.core.Application.get()
                        design = app.activeProduct if app else None
                        self._rebuild_work_zone_visuals(root, grown_layout, app, design)
                    except Exception:
                        pass
        except Exception:
            pass

        try:
            profiler.begin("createLayFlatBodies")
            result = nesting_lay_flat_fusion.create_lay_flat_layout(
                root,
                prepared,
                origin_x_mm=origin_x,
                origin_y_mm=origin_y,
                part_gap_mm=part_gap,
                column_gap_mm=column_gap,
                wait_callback=_pump_fusion_events,
                # Already deleted NESTING/LAY_FLAT before scan.
                clear_previous=False,
            )
            profiler.end("createLayFlatBodies")
        except Exception as ex:
            profile = profiler.flush(status="createFailed")
            return "panelAttributesResult", {
                "ok": False,
                "action": "createLayFlatLayout",
                "errors": ["Lay Flat failed: {}".format(ex)],
                "scope": scope,
                "preparedCount": len(prepared),
                "notReadyCount": len(not_ready),
                "failedCount": len(failed),
                "profile": profile,
            }

        deleted_total = deleted_previous + int(result.get("deletedPrevious") or 0)
        profile = profiler.flush(status="done")
        created_n = int(result.get("created") or 0)
        scope_label = "Lay Flat Selected" if scope == "selection" else "Lay Flat All"
        message = (
            "{} → {} with {} named body(ies) "
            "(Assembly-Component), {}/{} panel(s) in {} column(s)."
            "{}{}{}"
        ).format(
            scope_label,
            result.get("componentName") or "LAY_FLAT",
            created_n,
            created_n,
            len(body_records),
            len(result.get("groups") or []),
            " · {} not ready".format(len(not_ready)) if not_ready else "",
            " · {} failed".format(len(failed)) if failed else "",
            (" · " + "; ".join(override_warnings[:2])) if override_warnings else "",
        )
        return "panelAttributesResult", {
            "ok": True,
            "action": "createLayFlatLayout",
            "scope": scope,
            "createdCount": created_n,
            "groupCount": len(result.get("groups") or []),
            "deletedPreviousCount": deleted_total,
            "preparedCount": len(prepared),
            "notReadyCount": len(not_ready),
            "failedCount": len(failed),
            "notReady": not_ready[:50],
            "failed": failed[:50],
            "groups": result.get("groups") or [],
            "componentName": result.get("componentName") or "LAY_FLAT",
            "runId": result.get("runId") or "",
            "scanDetail": "nesting",
            "structure": result.get("structure") or "named_bodies",
            "createPath": result.get("createPath") or "batch_named_bodies",
            "originXMm": origin_x,
            "originYMm": origin_y,
            "zoneGrown": zone_grown,
            "bodyCount": len(body_records),
            "lineageStampedCount": int(
                result.get("lineageStampedCount") or 0
            ),
            "tagOverrideCount": len(overrides or {}),
            "tagOverrideHarvestedCount": len(harvested or {}),
            "tagOverrideSyncedCount": len(synced_overrides or {}),
            "tagOverrideAppliedCount": 0,
            "tagOverrideSyncFailed": sync_failed[:20],
            "profile": profile,
            "warnings": override_warnings[:20],
            "message": message,
        }

    def _auto_fix_lay_flat_bottom_half(
        self,
        root,
        body,
        min_dot=None,
        source_fixed_keys=None,
    ):
        """Transactionally swap roles, write source, flip copy, then re-check."""
        source_fixed_keys = source_fixed_keys if isinstance(source_fixed_keys, set) else set()
        body_name = str(getattr(body, "name", "") or "")
        canonical_ref = panel_source_ref.from_lay_flat_body(body)
        source_key = panel_source_ref.key(canonical_ref)
        if not source_key:
            return {
                "ok": False,
                "bodyName": body_name,
                "reason": "missing exact source lineage",
                "sourceKey": "",
                "rollback": False,
            }
        source_bodies, _fields, resolved_via = (
            panel_body_resolver.resolve_source_bodies_for_lay_flat(
                root,
                body,
                index=None,
                allow_panel_id_fallback=False,
            )
        )
        if len(source_bodies) != 1:
            return {
                "ok": False,
                "bodyName": body_name,
                "reason": "exact source lineage did not resolve: {} ({})".format(
                    source_key, resolved_via or "none"
                ),
                "sourceKey": source_key,
                "resolvedVia": resolved_via,
                "rollback": False,
            }
        source_body = source_bodies[0]
        source_already_fixed = source_key in source_fixed_keys
        source_snapshot = None
        copy_snapshot = None
        geometry_flipped = False
        source_written = False
        rollback_errors = []

        precheck = nesting_lay_flat_face_up.evaluate_body_faces_up(
            body, min_dot=min_dot
        )
        half_inspection = precheck.get("halfInspection") or {}
        if (
            precheck.get("halfStatus") != "bottomHalf"
            or half_inspection.get("bottomFace") is None
            or half_inspection.get("topFace") is None
        ):
            return {
                "ok": False,
                "bodyName": body_name,
                "sourceKey": source_key,
                "resolvedVia": resolved_via,
                "reason": "repair requires bottom-only HALF evidence",
                "rollback": False,
            }

        def _write_half_roles(target, milling, non_milling):
            return tag_metadata_editor.apply_surface_milling_roles(
                target,
                milling,
                non_milling,
                source="half_feature",
                lock=False,
                force=True,
            )

        def _role_signature(metadata):
            registry = (
                metadata.get("faceRegistry")
                if isinstance(metadata, dict)
                and isinstance(metadata.get("faceRegistry"), dict)
                else {}
            )
            rows = []
            for face in registry.get("faces") or []:
                if not isinstance(face, dict):
                    continue
                role = str(face.get("millingSurface") or "").strip().upper()
                if role not in ("MILLING", "NON_MILLING", "EITHER"):
                    continue
                rows.append(
                    (
                        str(face.get("entityToken") or face.get("faceId") or ""),
                        role,
                        bool(face.get("millingLocked")),
                    )
                )
            return tuple(sorted(rows))

        try:
            copy_snapshot = tag_metadata_editor.snapshot_milling_state(body)
            if not source_already_fixed:
                source_snapshot = tag_metadata_editor.snapshot_milling_state(source_body)
                source_before = _role_signature(
                    source_snapshot.get("bodyMetadata") or {}
                )
                source_result = milling_surface_propagation.analyze_milling_surfaces(
                    [source_body],
                    write_pair=lambda target, face_a, role_a, face_b, role_b: (
                        tag_metadata_editor.apply_surface_roles(
                            target,
                            face_a,
                            role_a,
                            face_b,
                            role_b,
                            source="half_feature",
                            lock=False,
                            force=True,
                        )
                    ),
                )
                if int(source_result.get("updatedCount") or 0) != 1:
                    raise ValueError(
                        "source role swap failed: {}".format(
                            (source_result.get("skipped") or [{}])[0].get("reason")
                            or "unknown"
                        )
                    )
                source_evidence = str(
                    ((source_result.get("updated") or [{}])[0]).get("source")
                    or ""
                )
                if source_evidence not in ("hinge_cups", "half_slot"):
                    raise ValueError(
                        "source HALF evidence was not authoritative ({})".format(
                            source_evidence or "none"
                        )
                    )
                source_after_metadata, source_read_error = (
                    tag_metadata_editor._read_body_metadata_raw(source_body)
                )
                if source_read_error:
                    raise ValueError(source_read_error)
                source_after = _role_signature(source_after_metadata or {})
                if not source_after or source_after == source_before:
                    raise ValueError("source milling roles did not change after write")
                cutting = (
                    (
                        (source_after_metadata.get("classification") or {}).get(
                            "cuttingFace"
                        )
                        or {}
                    )
                    if isinstance(source_after_metadata, dict)
                    else {}
                )
                if bool(cutting.get("locked")):
                    raise ValueError("source cuttingFace remained locked after write")
                source_written = True

            _write_half_roles(
                body,
                half_inspection.get("bottomFace"),
                half_inspection.get("topFace"),
            )

            flip_result = nesting_lay_flat_fusion.flip_lay_flat_body_thickness(body)
            if not flip_result.get("ok"):
                raise ValueError(
                    "LAY_FLAT geometry flip failed: {}".format(
                        flip_result.get("reason") or "unknown"
                    )
                )
            geometry_flipped = True

            recheck = nesting_lay_flat_face_up.evaluate_body_faces_up(
                body, min_dot=min_dot
            )
            if not recheck.get("ok"):
                raise ValueError(
                    "post-fix check failed: {}".format(
                        ",".join(recheck.get("reasons") or ["unknown"])
                    )
                )

            copy_metadata, copy_read_error = (
                tag_metadata_editor._read_body_metadata_raw(body)
            )
            if copy_read_error:
                raise ValueError(copy_read_error)
            if isinstance(copy_metadata, dict):
                copy_metadata = dict(copy_metadata)
                copy_metadata.pop("nestingFlatOutline", None)
                copy_metadata["features"] = []
                copy_metadata["lifecycle"] = {"state": "lay_flat"}
                tag_metadata_editor._write_body_metadata(body, copy_metadata)
            if source_written:
                source_fixed_keys.add(source_key)
            return {
                "ok": True,
                "bodyName": body_name,
                "sourceBodyName": str(getattr(source_body, "name", "") or ""),
                "sourceKey": source_key,
                "resolvedVia": resolved_via,
                "sourceUpdated": bool(source_written),
                "geometryFlipped": True,
                "halfStatus": recheck.get("halfStatus") or "",
                "rollback": False,
            }
        except Exception as ex:
            if geometry_flipped:
                try:
                    flipped_back = (
                        nesting_lay_flat_fusion.flip_lay_flat_body_thickness(body)
                    )
                    if not flipped_back.get("ok"):
                        rollback_errors.append(
                            flipped_back.get("reason") or "geometry flip-back failed"
                        )
                except Exception as rollback_ex:
                    rollback_errors.append(str(rollback_ex))
            if isinstance(copy_snapshot, dict):
                try:
                    tag_metadata_editor.restore_milling_state(body, copy_snapshot)
                except Exception as rollback_ex:
                    rollback_errors.append("copy metadata: {}".format(rollback_ex))
            if source_written and isinstance(source_snapshot, dict):
                try:
                    tag_metadata_editor.restore_milling_state(
                        source_body, source_snapshot
                    )
                except Exception as rollback_ex:
                    rollback_errors.append("source metadata: {}".format(rollback_ex))
            return {
                "ok": False,
                "bodyName": body_name,
                "sourceKey": source_key,
                "resolvedVia": resolved_via,
                "reason": str(ex),
                "rollback": bool(
                    geometry_flipped or copy_snapshot or source_snapshot
                ),
                "rollbackErrors": rollback_errors,
            }

    def check_lay_flat_faces_up(self, payload, _palette):
        """Validate HALF openings; repair bottom-only HALF via exact SourceRef."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "checkLayFlatFacesUp",
                "errors": ["No active Fusion design."],
            }

        min_dot = (payload or {}).get("minDot")
        try:
            min_dot = float(min_dot) if min_dot is not None else None
        except Exception:
            min_dot = None
        select_failed = bool((payload or {}).get("selectFailed", True))

        selected_entities = self._selected_entities()
        warnings = []
        bodies = []
        if selected_entities:
            resolved, expand_warnings = metadata_inspector.bodies_from_selected_entities(
                selected_entities, root, include_lay_flat=True
            )
            warnings.extend(list(expand_warnings or [])[:20])
            for body in resolved or []:
                if work_zones.is_lay_flat_workpiece(body):
                    bodies.append(body)
            if resolved and not bodies:
                warnings.append(
                    "Selection had bodies but none were Lay Flat workpieces; "
                    "scanning LAY_FLAT instead."
                )
        if not bodies:
            bodies = nesting_lay_flat_face_up.collect_lay_flat_bodies(root)
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "checkLayFlatFacesUp",
                "errors": [
                    "No Lay Flat bodies found. Run Lay Flat first, or select LAY_FLAT."
                ],
                "warnings": warnings[:20],
            }

        first_pass = nesting_lay_flat_face_up.check_bodies(bodies, min_dot=min_dot)
        auto_fixed = []
        auto_fix_failed = []
        source_fixed_keys = set()
        for item in first_pass.get("failed") or []:
            if not item.get("autoFixRecommended"):
                continue
            target = item.get("_body")
            fix = self._auto_fix_lay_flat_bottom_half(
                root,
                target,
                min_dot=min_dot,
                source_fixed_keys=source_fixed_keys,
            )
            if fix.get("ok"):
                auto_fixed.append(fix)
            else:
                auto_fix_failed.append(fix)

        # Always report a fresh post-repair view of every body.
        result = nesting_lay_flat_face_up.check_bodies(bodies, min_dot=min_dot)
        failed = list(result.get("failed") or [])
        selected_count = 0
        select_failures = []
        faces = []
        if select_failed:
            for item in failed:
                face = item.get("_millingFace")
                if face is not None:
                    faces.append(face)
        for item in (result.get("passed") or []) + failed:
            item.pop("_body", None)
            item.pop("_millingFace", None)
            item.pop("_colourFace", None)
            item.pop("_halfInspection", None)
        if faces:
            selected_count, select_failures = self._select_faces_and_fit(faces)
            warnings.extend(select_failures or [])

        ok = bool(result.get("ok"))
        message = (
            "Check Faces Up: {}/{} Lay Flat body(ies) OK "
            "(MILLING +Z, HALF top-only, minDot={:.2f})."
            .format(
                int(result.get("passedCount") or 0),
                int(result.get("checkedCount") or 0),
                float(result.get("minDot") or 0.95),
            )
        )
        if auto_fixed:
            message += " Auto-fixed {} body(ies), wrote {} source(s).".format(
                len(auto_fixed),
                sum(1 for item in auto_fixed if item.get("sourceUpdated")),
            )
        if auto_fix_failed:
            message += " Auto-fix failed {}: {}.".format(
                len(auto_fix_failed),
                "; ".join(
                    "{} ({})".format(
                        item.get("bodyName") or "body",
                        item.get("reason") or "unknown",
                    )
                    for item in auto_fix_failed[:3]
                ),
            )
        double_side_n = int(result.get("doubleSideCount") or 0)
        if double_side_n:
            message += " Double-sided HALF blocked: {}.".format(double_side_n)
        outline_n = sum(
            1
            for item in failed
            if "bottom_outline_notched" in (item.get("reasons") or [])
        )
        if outline_n:
            message += " Colour outer notched by edge-open feature: {}.".format(
                outline_n
            )
        if not ok:
            message += " Failed: {}.".format(int(result.get("failedCount") or 0))
            if selected_count:
                message += " Selected {} face(s) to inspect.".format(selected_count)

        return "panelAttributesResult", {
            "ok": ok,
            "action": "checkLayFlatFacesUp",
            "checkedCount": int(result.get("checkedCount") or 0),
            "passedCount": int(result.get("passedCount") or 0),
            "failedCount": int(result.get("failedCount") or 0),
            "autoFixedCount": len(auto_fixed),
            "sourceUpdatedCount": sum(
                1 for item in auto_fixed if item.get("sourceUpdated")
            ),
            "geometryFlippedCount": sum(
                1 for item in auto_fixed if item.get("geometryFlipped")
            ),
            "doubleSideBlockedCount": double_side_n,
            "rollbackCount": sum(
                1 for item in auto_fix_failed if item.get("rollback")
            ),
            "autoFixed": auto_fixed[:80],
            "autoFixFailed": auto_fix_failed[:80],
            "minDot": result.get("minDot"),
            "failed": [
                {
                    "bodyName": item.get("bodyName") or "",
                    "millingOk": item.get("millingOk"),
                    "colourOk": item.get("colourOk"),
                    "millingDotPlusZ": item.get("millingDotPlusZ"),
                    "colourDotMinusZ": item.get("colourDotMinusZ"),
                    "reasons": item.get("reasons") or [],
                    "assignment": item.get("assignment") or "",
                    "halfStatus": item.get("halfStatus") or "",
                    "topHalfCount": int(item.get("topHalfCount") or 0),
                    "bottomHalfCount": int(item.get("bottomHalfCount") or 0),
                    "bottomOutlineNotched": bool(
                        item.get("bottomOutlineNotched")
                    ),
                    "bottomOutlineNotchReason": str(
                        item.get("bottomOutlineNotchReason") or ""
                    ),
                    "orientationOverride": str(
                        item.get("orientationOverride") or ""
                    ),
                }
                for item in failed[:80]
            ],
            "selectedFaceCount": selected_count,
            "warnings": warnings[:40],
            "errors": [] if ok else [message],
            "message": message,
        }

    def analyze_lay_flat_manufacturing(self, payload, _palette):
        """Re-extract outline + features on Lay Flat bodies (independent of Lay Flat)."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "analyzeLayFlatManufacturing",
                "errors": ["No active Fusion design."],
            }

        force = bool((payload or {}).get("forceRebuild"))
        warnings = []
        bodies = []
        selected_entities = self._selected_entities()
        if selected_entities:
            resolved, expand_warnings = metadata_inspector.bodies_from_selected_entities(
                selected_entities, root, include_lay_flat=True
            )
            warnings.extend(list(expand_warnings or [])[:20])
            for body in resolved or []:
                if work_zones.is_lay_flat_workpiece(body):
                    bodies.append(body)
            if resolved and not bodies:
                warnings.append(
                    "Selection had bodies but none were Lay Flat workpieces; "
                    "scanning LAY_FLAT instead."
                )
        if not bodies:
            bodies = nesting_lay_flat_face_up.collect_lay_flat_bodies(root)
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "analyzeLayFlatManufacturing",
                "errors": [
                    "No Lay Flat bodies found. Run Lay Flat first, or select LAY_FLAT."
                ],
                "warnings": warnings[:20],
            }

        result = nesting_lay_flat_analyze.analyze_lay_flat_bodies(
            bodies,
            force=force,
            wait_callback=_pump_fusion_events,
        )
        failed_n = int(result.get("failedCount") or 0)
        analyzed_n = int(result.get("analyzedCount") or 0)
        skipped_n = int(result.get("skippedFreshCount") or 0)
        tint_n = int(result.get("millingTintAppliedCount") or 0)
        ok = failed_n == 0 and (analyzed_n + skipped_n) > 0
        message = (
            "Analyze Lay Flat: built {} · reused fresh {} · milling tint {} · "
            "failed {} / {} body(ies)."
            .format(
                analyzed_n,
                skipped_n,
                tint_n,
                failed_n,
                int(result.get("bodyCount") or 0),
            )
        )
        return "panelAttributesResult", {
            "ok": ok,
            "action": "analyzeLayFlatManufacturing",
            "analyzedCount": analyzed_n,
            "skippedFreshCount": skipped_n,
            "millingTintAppliedCount": tint_n,
            "millingTintFailedCount": int(result.get("millingTintFailedCount") or 0),
            "failedCount": failed_n,
            "bodyCount": int(result.get("bodyCount") or 0),
            "forceRebuild": force,
            "analyzed": result.get("analyzed") or [],
            "skippedFresh": result.get("skippedFresh") or [],
            "failed": result.get("failed") or [],
            "warnings": warnings[:40],
            "errors": [] if ok else [message],
            "message": message,
        }

    def check_lay_flat_export_ready(self, payload, _palette):
        """Export Ready gate for Lay Flat bodies (before .cnjob export)."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "checkLayFlatExportReady",
                "errors": ["No active Fusion design."],
            }

        select_not_ready = bool((payload or {}).get("selectNotReady", False))
        min_dot = (payload or {}).get("minDot")
        try:
            min_dot = float(min_dot) if min_dot is not None else None
        except Exception:
            min_dot = None

        warnings = []
        bodies = []
        selected_entities = self._selected_entities()
        # Select Not Ready always rescans all LAY_FLAT bodies so selection is not
        # limited to a previous partial selection.
        if selected_entities and not select_not_ready:
            resolved, expand_warnings = metadata_inspector.bodies_from_selected_entities(
                selected_entities, root, include_lay_flat=True
            )
            warnings.extend(list(expand_warnings or [])[:20])
            for body in resolved or []:
                if work_zones.is_lay_flat_workpiece(body):
                    bodies.append(body)
            if resolved and not bodies:
                warnings.append(
                    "Selection had bodies but none were Lay Flat workpieces; "
                    "scanning LAY_FLAT instead."
                )
        if not bodies:
            bodies = nesting_lay_flat_face_up.collect_lay_flat_bodies(root)
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "checkLayFlatExportReady",
                "errors": [
                    "No Lay Flat bodies found. Run Lay Flat first, or select LAY_FLAT."
                ],
                "warnings": warnings[:20],
            }

        result = nesting_lay_flat_export_ready.check_bodies(
            bodies,
            min_dot=min_dot,
            wait_callback=_pump_fusion_events,
        )
        not_ready = list(result.get("notReady") or [])
        ready = list(result.get("ready") or [])
        selected_count = 0
        if select_not_ready:
            select_bodies = [
                item.get("_body") for item in not_ready if item.get("_body") is not None
            ]
            selected_count = self._select_bodies_and_fit(select_bodies)
            if selected_count == 0 and select_bodies:
                warnings.append(
                    "Select Not Ready resolved {} body(ies) but Fusion selection.add "
                    "failed (occurrence proxy required for nested LAY_FLAT parts).".format(
                        len(select_bodies)
                    )
                )
            elif 0 < selected_count < len(select_bodies):
                warnings.append(
                    "Selected {} of {} not-ready body(ies).".format(
                        selected_count, len(select_bodies)
                    )
                )

        def _public_item(item):
            return {
                "bodyName": item.get("bodyName") or "",
                "panelId": item.get("panelId") or "",
                "ready": bool(item.get("ready")),
                "reasons": list(item.get("reasons") or []),
                "boardTypeTag": item.get("boardTypeTag") or "",
                "colorTag": item.get("colorTag") or "",
                "cuttingFace": item.get("cuttingFace") or "",
                "thicknessMm": item.get("thicknessMm"),
                "featureCount": item.get("featureCount") or 0,
                "pointCount": item.get("pointCount") or 0,
                "outlineSource": item.get("outlineSource") or "",
                "lifecycleState": item.get("lifecycleState") or "",
                "analyzed": bool(item.get("analyzed")),
                "faceUp": item.get("faceUp"),
            }

        ready_n = int(result.get("readyCount") or 0)
        not_ready_n = int(result.get("notReadyCount") or 0)
        body_n = int(result.get("bodyCount") or 0)
        ok = not_ready_n == 0 and body_n > 0
        reason_counts = result.get("reasonCounts") or {}
        reason_bits = [
            "{} {}".format(count, name)
            for name, count in sorted(reason_counts.items(), key=lambda kv: (-kv[1], kv[0]))
            if count
        ]
        message = "Export Ready: {}/{} Lay Flat body(ies) ready.".format(ready_n, body_n)
        if not_ready_n:
            message += " {} not ready.".format(not_ready_n)
            if reason_bits:
                message += " Top reasons: {}.".format(", ".join(reason_bits[:6]))
        if select_not_ready:
            if selected_count:
                message += " Selected {} body(ies).".format(selected_count)
            elif not_ready_n:
                message += " Selection failed for {} not-ready body(ies).".format(
                    not_ready_n
                )

        return "panelAttributesResult", {
            "ok": ok,
            "action": "checkLayFlatExportReady",
            "bodyCount": body_n,
            "readyCount": ready_n,
            "notReadyCount": not_ready_n,
            "reasonCounts": reason_counts,
            "ready": [_public_item(item) for item in ready[:200]],
            "notReady": [_public_item(item) for item in not_ready[:200]],
            "selectedCount": selected_count,
            "selectNotReady": select_not_ready,
            "warnings": warnings[:40],
            "errors": [] if ok else [message],
            "message": message,
        }

    def _selected_lay_flat_bodies(self, root):
        warnings = []
        selected_entities = self._selected_entities()
        if not selected_entities:
            return [], ["Select one or more LAY_FLAT bodies or faces."]
        resolved, expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root, include_lay_flat=True
        )
        warnings.extend(list(expand_warnings or [])[:20])
        bodies = []
        seen = set()
        for body in resolved or []:
            if not work_zones.is_lay_flat_workpiece(body):
                continue
            key = metadata_inspector._body_key(body)
            if key in seen:
                continue
            seen.add(key)
            bodies.append(body)
        if not bodies:
            warnings.append(
                "Selection has no LAY_FLAT workpieces. Select bodies under LAY_FLAT."
            )
        return bodies, warnings

    def _lay_flat_project_tag_options(self, root, selected_bodies=None):
        board_types = set()
        colors = set()
        warnings = []
        try:
            rules_payload = thickness_rules.load_rules(root) or {}
            for rule in rules_payload.get("rules") or []:
                tag = str((rule or {}).get("boardTypeTag") or "").strip()
                if tag:
                    board_types.add(tag)
        except Exception as ex:
            warnings.append("Board Type rules could not be loaded: {}".format(ex))
        try:
            records, _counts, diagnostics = metadata_inspector.scan_panel_metadata(
                root, zone_filter="all", detail="nesting"
            )
            warnings.extend(list((diagnostics or {}).get("warnings") or [])[:10])
        except Exception as ex:
            records = []
            warnings.append("Project tag scan failed: {}".format(ex))
        for record in records or []:
            if "body" not in str(record.get("entityKind") or "").lower():
                continue
            board = str(record.get("boardTypeTag") or "").strip()
            color = str(record.get("colorTag") or "").strip()
            if board:
                board_types.add(board)
            if color:
                colors.add(color)
        for body in selected_bodies or []:
            metadata, _err = tag_metadata_editor._read_body_metadata_raw(body)
            metadata = attribute_state_service.migrate_metadata(
                metadata if isinstance(metadata, dict) else {}
            )
            classification = metadata.get("classification") or {}
            board = str(
                ((classification.get("boardType") or {}).get("value") or "")
            ).strip()
            color = str(
                ((classification.get("color") or {}).get("value") or "")
            ).strip()
            if board:
                board_types.add(board)
            if color:
                colors.add(color)
        return (
            sorted(board_types, key=lambda value: value.lower()),
            sorted(colors, key=lambda value: value.lower()),
            warnings,
        )

    def _lay_flat_effective_tags(self, body, root=None, allow_source_fallback=False):
        """Read tags from the LAY_FLAT copy; never guess a write source by panelId."""
        metadata, _err = tag_metadata_editor._read_body_metadata_raw(body)
        if not isinstance(metadata, dict):
            try:
                metadata = nesting_lay_flat_tag_scan.read_body_metadata(body) or {}
            except Exception:
                metadata = {}
        board = str(
            (attribute_state_service.board_type_state(metadata) or {}).get("value") or ""
        ).strip().lower()
        color = str(
            (attribute_state_service.color_state(metadata) or {}).get("value") or ""
        ).strip().lower()
        source_ref = panel_source_ref.from_lay_flat_body(body)
        source_panel_id = str(
            (source_ref or {}).get("panelId")
            or milling_surface_propagation.read_source_panel_id(body)
            or ""
        ).strip()
        return {
            "boardTypeTag": board,
            "colorTag": color,
            "sourcePanelId": source_panel_id,
            "sourceRef": source_ref,
            "sourceKey": panel_source_ref.key(source_ref),
            "metadata": metadata if isinstance(metadata, dict) else {},
        }

    def get_lay_flat_tag_editor(self, _payload, _palette):
        """Return project Board Type / Color values and selected LAY_FLAT state."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "getLayFlatTagEditor",
                "errors": ["No active Fusion design."],
            }
        bodies, selection_warnings = self._selected_lay_flat_bodies(root)
        board_types, colors, option_warnings = self._lay_flat_project_tag_options(
            root, selected_bodies=bodies
        )
        selected = []
        for body in bodies:
            tags = self._lay_flat_effective_tags(body, root=root)
            selected.append(
                {
                    "bodyName": str(getattr(body, "name", "") or ""),
                    "sourcePanelId": tags.get("sourcePanelId") or "",
                    "sourceKey": tags.get("sourceKey") or "",
                    "lineageComplete": bool(tags.get("sourceKey")),
                    "boardTypeTag": tags.get("boardTypeTag") or "",
                    "colorTag": tags.get("colorTag") or "",
                }
            )
        return "panelAttributesResult", {
            "ok": bool(bodies) and bool(board_types) and bool(colors),
            "action": "getLayFlatTagEditor",
            "selectedCount": len(bodies),
            "selected": selected[:100],
            "boardTypes": board_types,
            "colors": colors,
            "warnings": (selection_warnings + option_warnings)[:40],
            "errors": (
                []
                if bodies and board_types and colors
                else [
                    "Select LAY_FLAT bodies and ensure the project already has "
                    "at least one Board Type and Color."
                ]
            ),
        }

    def apply_lay_flat_tags(self, payload, _palette):
        """Apply tags to selected LAY_FLAT + sources now, then append selected.

        Primary path writes the source model immediately (no Lay Flat rebuild).
        Cost: O(N + k) with one source index (N originals, k selection), plus
        O(L) layout pass over Lay Flat bodies for the selected-only move.
        """
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyLayFlatTags",
                "errors": ["No active Fusion design."],
            }
        bodies, warnings = self._selected_lay_flat_bodies(root)
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyLayFlatTags",
                "errors": ["Select one or more LAY_FLAT bodies or faces."],
                "warnings": warnings[:20],
            }

        board_type = str((payload or {}).get("boardTypeTag") or "").strip()
        color = str((payload or {}).get("colorTag") or "").strip()
        if not board_type and not color:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyLayFlatTags",
                "errors": ["Choose a Board Type, a Color, or both."],
            }
        board_options, color_options, option_warnings = (
            self._lay_flat_project_tag_options(root, selected_bodies=bodies)
        )
        warnings.extend(option_warnings)
        if board_type and board_type not in board_options:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyLayFlatTags",
                "errors": ["Board Type is not an existing project value: {}".format(board_type)],
            }
        if color and color not in color_options:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyLayFlatTags",
                "errors": ["Color is not an existing project value: {}".format(color)],
            }

        updated = []
        source_updated = []
        failed = []
        source_seen = set()

        def _apply_tags(
            body,
            preserve_source_panel_id="",
            preserve_board="",
            preserve_color="",
        ):
            metadata, read_error = tag_metadata_editor._read_body_metadata_raw(body)
            if read_error:
                raise ValueError(read_error)
            if isinstance(metadata, dict):
                working = attribute_state_service.migrate_metadata(metadata)
            else:
                working = tag_metadata_editor._bootstrap_body_metadata(body)
            if preserve_source_panel_id:
                identity = working.setdefault("identity", {})
                if not isinstance(identity, dict):
                    identity = {}
                    working["identity"] = identity
                if not str(identity.get("sourcePanelId") or "").strip():
                    identity["sourcePanelId"] = preserve_source_panel_id
            # Keep-current must not wipe existing tags when the read path is sparse.
            if not board_type and preserve_board:
                current_board = str(
                    (attribute_state_service.board_type_state(working) or {}).get("value")
                    or ""
                ).strip()
                if attribute_state_service.is_undefined(current_board):
                    working, _ignored = attribute_state_service.apply_board_type(
                        working,
                        preserve_board,
                        source="legacy",
                        lock=False,
                        force=True,
                    )
            if not color and preserve_color:
                current_color = str(
                    (attribute_state_service.color_state(working) or {}).get("value")
                    or ""
                ).strip()
                if attribute_state_service.is_undefined(current_color):
                    working, _ignored = attribute_state_service.apply_color(
                        working,
                        preserve_color,
                        source="legacy",
                        lock=False,
                        force=True,
                    )
            changes = []
            if board_type:
                working, result = attribute_state_service.apply_board_type(
                    working,
                    board_type,
                    source="manual",
                    lock=True,
                    force=True,
                )
                if result.get("changed"):
                    changes.append("boardType")
            if color:
                working, result = attribute_state_service.apply_color(
                    working,
                    color,
                    source="manual",
                    lock=True,
                    force=True,
                )
                if result.get("changed"):
                    changes.append("color")
            tag_metadata_editor._write_body_metadata(body, working)
            if preserve_source_panel_id:
                try:
                    from nesting.lay_flat_fusion import _set_attr, OUTPUT_MARKER_GROUP
                except Exception:
                    try:
                        from lay_flat_fusion import _set_attr, OUTPUT_MARKER_GROUP  # type: ignore
                    except Exception:
                        _set_attr = None
                        OUTPUT_MARKER_GROUP = "UnifiedCabinet"
                if callable(_set_attr):
                    try:
                        _set_attr(
                            body,
                            OUTPUT_MARKER_GROUP,
                            "sourcePanelId",
                            preserve_source_panel_id,
                        )
                    except Exception:
                        pass
            return changes

        # Transactional path per selected copy:
        # resolve exact SourceRef -> write+verify source -> update LAY_FLAT.
        # Never authorize writes from panelId/name guesses.
        successful_bodies = []
        for body in bodies:
            body_name = str(getattr(body, "name", "") or "")
            before = self._lay_flat_effective_tags(
                body, root=root, allow_source_fallback=False
            )
            canonical_ref = panel_source_ref.from_lay_flat_body(body)
            source_key = panel_source_ref.key(canonical_ref)
            if not source_key:
                failed.append(
                    {
                        "bodyName": body_name,
                        "reason": (
                            "missing exact source lineage; run Create Lay Flat "
                            "with the current plugin"
                        ),
                    }
                )
                continue
            source_bodies, source_ref_fields, source_resolution = (
                panel_body_resolver.resolve_source_bodies_for_lay_flat(
                    root,
                    body,
                    index=None,
                    allow_panel_id_fallback=False,
                )
            )
            if len(source_bodies) != 1:
                failed.append(
                    {
                        "bodyName": body_name,
                        "reason": "exact source lineage did not resolve: {} ({})".format(
                            source_key, source_resolution or "none"
                        ),
                    }
                )
                continue
            source_body = source_bodies[0]
            source_panel_id = str(
                (canonical_ref or {}).get("panelId")
                or source_ref_fields.get("sourcePanelId")
                or ""
            ).strip()
            intended_board = str(board_type or before.get("boardTypeTag") or "").strip()
            intended_color = str(color or before.get("colorTag") or "").strip()
            source_body_key = metadata_inspector._body_key(source_body)
            wrote_source_now = source_body_key not in source_seen
            source_metadata_before = None
            source_update_item = None
            if wrote_source_now:
                try:
                    source_metadata_before, source_read_error = (
                        tag_metadata_editor._read_body_metadata_raw(source_body)
                    )
                    if source_read_error:
                        raise ValueError(source_read_error)
                    source_before = self._lay_flat_effective_tags(
                        source_body, root=root, allow_source_fallback=False
                    )
                    changes = _apply_tags(
                        source_body,
                        preserve_board=intended_board
                        or source_before.get("boardTypeTag")
                        or before.get("boardTypeTag")
                        or "",
                        preserve_color=intended_color
                        or source_before.get("colorTag")
                        or before.get("colorTag")
                        or "",
                    )
                    after = self._lay_flat_effective_tags(
                        source_body, root=root, allow_source_fallback=False
                    )
                    if board_type and str(after.get("boardTypeTag") or "") != str(
                        board_type
                    ).strip().lower():
                        raise ValueError(
                            "source boardType still {!r} after write".format(
                                after.get("boardTypeTag")
                            )
                        )
                    if color and str(after.get("colorTag") or "") != str(
                        color
                    ).strip().lower():
                        raise ValueError(
                            "source color still {!r} after write".format(
                                after.get("colorTag")
                            )
                        )
                    if board_type and str(
                        source_before.get("boardTypeTag") or ""
                    ) != str(board_type).strip().lower():
                        if "boardType" not in changes:
                            changes.append("boardType")
                    if color and str(source_before.get("colorTag") or "") != str(
                        color
                    ).strip().lower():
                        if "color" not in changes:
                            changes.append("color")
                    source_update_item = {
                        "bodyName": str(getattr(source_body, "name", "") or ""),
                        "panelId": source_panel_id,
                        "sourceKey": source_key,
                        "changed": changes,
                        "resolvedVia": source_resolution,
                    }
                    source_seen.add(source_body_key)
                except Exception as ex:
                    if isinstance(source_metadata_before, dict):
                        try:
                            tag_metadata_editor._write_body_metadata(
                                source_body, source_metadata_before
                            )
                        except Exception:
                            pass
                    failed.append(
                        {
                            "bodyName": body_name,
                            "reason": "source write failed: {}".format(ex),
                        }
                    )
                    continue

            try:
                copy_changes = _apply_tags(
                    body,
                    preserve_source_panel_id=source_panel_id,
                    preserve_board=before.get("boardTypeTag") or intended_board,
                    preserve_color=before.get("colorTag") or intended_color,
                )
            except Exception as ex:
                # Roll source back when this selection introduced the write but
                # the disposable copy could not be updated.
                if wrote_source_now and isinstance(source_metadata_before, dict):
                    try:
                        tag_metadata_editor._write_body_metadata(
                            source_body, source_metadata_before
                        )
                        source_seen.discard(source_body_key)
                    except Exception:
                        pass
                failed.append(
                    {
                        "bodyName": body_name,
                        "reason": "LAY_FLAT write failed: {}".format(ex),
                    }
                )
                continue

            if source_update_item is not None:
                source_updated.append(source_update_item)
            updated.append({"bodyName": body_name, "changed": copy_changes})
            successful_bodies.append(body)

        all_lay_flat = nesting_lay_flat_face_up.collect_lay_flat_bodies(root)
        layout_items = []
        for index, body in enumerate(all_lay_flat):
            tags = self._lay_flat_effective_tags(
                body, root=root, allow_source_fallback=False
            )
            layout_items.append(
                {
                    "id": "{}|{}".format(
                        tags.get("sourcePanelId")
                        or milling_surface_propagation.read_source_panel_id(body),
                        index,
                    ),
                    "body": body,
                    "boardTypeTag": tags.get("boardTypeTag") or "",
                    "colorTag": tags.get("colorTag") or "",
                }
            )

        zone_layout = work_zones.load_zone_layout(root) or {}
        nesting_rect = zone_layout.get(work_zones.ZONE_NESTING) or {}
        origin_x = float(nesting_rect.get("x0") or 0.0)
        origin_y = float(nesting_rect.get("y0") or 0.0)
        part_gap = float((payload or {}).get("partGapMm") or 50.0)
        column_gap = float((payload or {}).get("columnGapMm") or 200.0)
        column_anchors = nesting_lay_flat_fusion._read_column_anchors(root)
        move_result = (
            nesting_lay_flat_fusion.append_lay_flat_bodies_to_group_ends(
                layout_items,
                selected_bodies=successful_bodies,
                origin_x_mm=origin_x,
                origin_y_mm=origin_y,
                part_gap_mm=part_gap,
                column_gap_mm=column_gap,
                column_anchors=column_anchors,
            )
        )
        if move_result.get("failedCount"):
            failed.extend(list(move_result.get("failed") or []))
        try:
            # Persist resolved columns so later edits can find them even if some
            # bodies temporarily fail tag reads.
            anchor_groups = []
            for group in move_result.get("groups") or []:
                anchor_groups.append(group)
            # Also keep stationary-only columns discovered during clustering.
            for key, state in (move_result.get("columnStates") or {}).items():
                if not isinstance(key, tuple) or len(key) != 2:
                    continue
                if key[0] in ("", "unknown") or state.get("x") is None:
                    continue
                anchor_groups.append(
                    {
                        "boardTypeTag": key[0],
                        "colorTag": key[1],
                        "columnX": state.get("x"),
                        "columnWidthMm": max(
                            0.0,
                            float(state.get("maxX") or 0.0)
                            - float(state.get("x") or 0.0),
                        ),
                        "count": int(state.get("stationaryCount") or 0),
                    }
                )
            anchor_groups = [
                group
                for group in anchor_groups
                if str(group.get("boardTypeTag") or "").strip().lower()
                not in ("", "unknown")
                and group.get("columnX") is not None
            ]
            nesting_lay_flat_fusion._write_column_anchors(root, anchor_groups)
        except Exception:
            pass

        bounds = move_result.get("bounds") or {}
        required_w = max(
            float(bounds.get("x1") or origin_x) - origin_x,
            float(nesting_rect.get("x1") or 0.0) - origin_x,
        )
        required_d = max(
            float(bounds.get("y1") or origin_y) - origin_y,
            float(nesting_rect.get("y1") or 0.0) - origin_y,
        )
        try:
            grown_layout = work_zones.grow_nesting_zone(
                zone_layout, required_w, required_d
            )
            if grown_layout and not work_zones.zones_overlap(grown_layout):
                work_zones.save_zone_layout(root, grown_layout)
                try:
                    app = adsk.core.Application.get()
                    design = app.activeProduct if app else None
                    self._rebuild_work_zone_visuals(
                        root, grown_layout, app, design
                    )
                except Exception:
                    pass
        except Exception as ex:
            warnings.append(
                "Could not grow Nesting Zone for appended bodies: {}".format(ex)
            )

        ok = bool(updated) and not failed
        message = (
            "LAY_FLAT tags: updated {} selected · {} source model · "
            "moved {} selected to column ends · failed {}."
        ).format(
            len(updated),
            len(source_updated),
            int(move_result.get("movedCount") or 0),
            len(failed),
        )
        group_bits = []
        for group in (move_result.get("groups") or [])[:3]:
            group_bits.append(
                "{} / {} @ x={} ({}, stationary {})".format(
                    group.get("boardTypeTag") or "unknown",
                    group.get("colorTag") or "unknown",
                    int(round(float(group.get("columnX") or 0.0))),
                    group.get("source") or "?",
                    int(group.get("stationaryCount") or 0),
                )
            )
        if group_bits:
            message = "{} Columns: {}.".format(message, "; ".join(group_bits))
        if failed:
            reasons = []
            for item in failed[:3]:
                reasons.append(
                    "{} ({})".format(
                        item.get("bodyName") or "body",
                        item.get("reason") or "unknown",
                    )
                )
            message = "{} {}".format(message, "; ".join(reasons))
        return "panelAttributesResult", {
            "ok": ok,
            "action": "applyLayFlatTags",
            "updatedCount": len(updated),
            "sourceUpdatedCount": len(source_updated),
            "movedCount": int(move_result.get("movedCount") or 0),
            "groupCount": len(move_result.get("groups") or []),
            "failedCount": len(failed),
            "updated": updated[:100],
            "sourceUpdated": source_updated[:100],
            "groups": (move_result.get("groups") or [])[:100],
            "placements": (move_result.get("placements") or [])[:100],
            "failed": failed[:40],
            "warnings": warnings[:40],
            "errors": [] if ok else [message],
            "message": message,
        }

    def tag_scan_lay_flat(self, payload, _palette):
        """Scan tags + Export Ready troubleshoot on selected LAY_FLAT bodies only."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "tagScanLayFlat",
                "errors": ["No active Fusion design."],
            }

        select_problems = bool(
            (payload or {}).get("selectProblems")
            or (payload or {}).get("selectMissing", False)
        )
        min_dot = (payload or {}).get("minDot")
        try:
            min_dot = float(min_dot) if min_dot is not None else None
        except Exception:
            min_dot = None
        warnings = []
        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "tagScanLayFlat",
                "errors": [
                    "Select one or more LAY_FLAT bodies (or their parent occurrence), "
                    "then run Tag Scan + Troubleshoot."
                ],
                "warnings": warnings[:20],
            }

        resolved, expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root, include_lay_flat=True
        )
        warnings.extend(list(expand_warnings or [])[:20])
        bodies = []
        for body in resolved or []:
            if work_zones.is_lay_flat_workpiece(body):
                bodies.append(body)
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "tagScanLayFlat",
                "errors": [
                    "Selection has no Lay Flat workpieces. Select bodies under LAY_FLAT."
                ],
                "warnings": warnings[:20],
            }

        result = nesting_lay_flat_tag_scan.scan_bodies(bodies, min_dot=min_dot)
        problems = list(result.get("problems") or [])
        missing = list(result.get("missing") or [])
        not_export_ready = list(result.get("notExportReady") or [])
        records = list(result.get("records") or [])
        selected_count = 0
        if select_problems:
            select_bodies = [
                item.get("_body")
                for item in problems
                if item.get("_body") is not None
            ]
            selected_count = self._select_bodies_and_fit(select_bodies)
            if selected_count == 0 and select_bodies:
                warnings.append(
                    "Select Problems resolved {} body(ies) but Fusion selection.add failed.".format(
                        len(select_bodies)
                    )
                )

        def _public(item):
            return {
                "ok": bool(item.get("ok")),
                "exportReady": item.get("exportReady"),
                "problem": bool(item.get("problem")),
                "bodyName": item.get("bodyName") or "",
                "panelId": item.get("panelId") or "",
                "boardTypeTag": item.get("boardTypeTag") or "",
                "colorTag": item.get("colorTag") or "",
                "cuttingFace": item.get("cuttingFace") or "",
                "thicknessMm": item.get("thicknessMm"),
                "lifecycleState": item.get("lifecycleState") or "",
                "missing": list(item.get("missing") or []),
                "missingCount": int(item.get("missingCount") or 0),
                "troubleshoot": list(item.get("troubleshoot") or []),
                "troubleshootCount": int(item.get("troubleshootCount") or 0),
                "featureCount": int(item.get("featureCount") or 0),
                "pointCount": int(item.get("pointCount") or 0),
                "outlineSource": item.get("outlineSource") or "",
                "analyzed": bool(item.get("analyzed")),
                "faceUp": item.get("faceUp"),
                "detail": item.get("detail") if isinstance(item.get("detail"), dict) else {},
            }

        complete_n = int(result.get("completeCount") or 0)
        missing_n = int(result.get("missingCount") or 0)
        export_ready_n = int(result.get("exportReadyCount") or 0)
        not_export_n = int(result.get("notExportReadyCount") or 0)
        problem_n = int(result.get("problemCount") or 0)
        body_n = int(result.get("bodyCount") or 0)
        ok = problem_n == 0 and body_n > 0
        reason_counts = result.get("reasonCounts") or {}
        reason_bits = [
            "{} {}".format(count, name)
            for name, count in sorted(
                reason_counts.items(), key=lambda kv: (-kv[1], kv[0])
            )
            if count
        ]
        message = (
            "Lay Flat Tag Scan (selection): tags {}/{} · export-ready {}/{}.".format(
                complete_n, body_n, export_ready_n, body_n
            )
        )
        if problem_n:
            message += " {} problem body(ies).".format(problem_n)
            if reason_bits:
                message += " Top: {}.".format(", ".join(reason_bits[:8]))
        if select_problems:
            if selected_count:
                message += " Selected {} body(ies).".format(selected_count)
            elif problem_n:
                message += " Selection failed for {} body(ies).".format(problem_n)

        return "panelAttributesResult", {
            "ok": ok,
            "action": "tagScanLayFlat",
            "bodyCount": body_n,
            "completeCount": complete_n,
            "missingCount": missing_n,
            "exportReadyCount": export_ready_n,
            "notExportReadyCount": not_export_n,
            "problemCount": problem_n,
            "reasonCounts": reason_counts,
            "records": [_public(item) for item in records[:300]],
            "missing": [_public(item) for item in missing[:200]],
            "notExportReady": [_public(item) for item in not_export_ready[:200]],
            "problems": [_public(item) for item in problems[:200]],
            "selectedCount": selected_count,
            "selectProblems": select_problems,
            "selectMissing": select_problems,
            "scope": "selection",
            "warnings": warnings[:40],
            "errors": [] if ok else [message],
            "message": message,
        }

    def _records_for_manufacturing_export(self, root, bodies):
        """Build full-detail scan records for unique source / Lay Flat bodies."""
        records = []
        skipped = []
        seen = set()
        for body in bodies or []:
            if metadata_inspector._is_assembly_zone(body):
                skipped.append(
                    "Skipped work-zone helper: {}".format(
                        getattr(body, "name", "") or "body"
                    )
                )
                continue
            if metadata_inspector._is_nested_instance(body):
                # Lay Flat copies are exportable (machining-up + underside outline).
                if not work_zones.is_lay_flat_workpiece(body):
                    skipped.append(
                        "Skipped nested layout copy: {}".format(
                            getattr(body, "name", "") or "body"
                        )
                    )
                    continue
            key = metadata_inspector._body_key(body)
            if key in seen:
                continue
            seen.add(key)
            occurrence_path = []
            try:
                occurrence_path = (
                    metadata_inspector.resolve_occurrence_path_for_body(root, body)
                    if root is not None
                    else []
                )
            except Exception:
                occurrence_path = []
            record = metadata_inspector._entity_record(
                body,
                "selected_body",
                occurrence_path or [],
                component_name=metadata_inspector._component_name_for_body(body),
                body_name=getattr(body, "name", "") or "",
                include_missing=True,
                detail="full",
            )
            if record:
                record["assemblyName"] = _assembly_name_for_record(root, record)
                records.append(record)
            else:
                skipped.append(
                    "No panel metadata for {}".format(
                        getattr(body, "name", "") or "body"
                    )
                )
        return records, skipped

    def get_thickness_rules(self, _payload, _palette):
        root = self.fusion.get_root_component()
        payload = thickness_rules.load_rules(root)
        rules = payload.get("rules") or []
        return "panelAttributesResult", {
            "ok": True,
            "action": "getThicknessRules",
            "rules": rules,
            "toleranceMm": payload.get("toleranceMm"),
            "source": payload.get("source") or "builtin",
            "knownBoardTypes": [
                str(rule.get("boardTypeTag") or "").strip()
                for rule in rules
                if str(rule.get("boardTypeTag") or "").strip()
            ] or list(thickness_rules.KNOWN_BOARD_TYPE_TAGS),
        }

    def set_thickness_rules(self, payload, _palette):
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "setThicknessRules",
                "errors": ["No active Fusion design."],
            }
        ok, saved = thickness_rules.save_rules(root, payload or {})
        return "panelAttributesResult", {
            "ok": bool(ok),
            "action": "setThicknessRules",
            "rules": saved.get("rules") or [],
            "toleranceMm": saved.get("toleranceMm"),
            "source": "design",
            "warnings": [] if ok else ["Could not save thickness rules to the design."],
            "errors": [] if ok else ["Could not save thickness rules to the design."],
        }

    def set_thickness_rules_as_default(self, payload, _palette):
        """Save current rules as the user-wide default (all designs without saved rules)."""
        ok, saved = thickness_rules.save_user_defaults(payload or {})
        return "panelAttributesResult", {
            "ok": bool(ok),
            "action": "setThicknessRulesAsDefault",
            "rules": saved.get("rules") or [],
            "toleranceMm": saved.get("toleranceMm"),
            "source": "userDefault",
            "message": "Saved as default board-type thickness rules." if ok else None,
            "warnings": [] if ok else ["Could not write user default rules file."],
            "errors": [] if ok else ["Could not write user default rules file."],
        }

    def apply_thickness_classification(self, payload, _palette):
        """Measure thickness on scanned/selected bodies and write board-type attrs."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyThicknessClassification",
                "errors": ["No active Fusion design."],
            }

        rules_payload = thickness_rules.normalize_rules(
            (payload or {}).get("rules"),
            (payload or {}).get("toleranceMm"),
        )
        # Persist the rules the user just applied.
        thickness_rules.save_rules(root, rules_payload)
        overwrite = bool((payload or {}).get("overwrite"))

        zone_filter = str((payload or {}).get("zoneFilter") or "all").strip().lower() or "all"
        # Light scan (no face overlay) but keep unmarked solids — imported /
        # copied boards often have no module attrs and were previously dropped.
        records, counts, diagnostics = metadata_inspector.scan_panel_metadata(
            root, zone_filter=zone_filter, detail="thickness"
        )
        updated = 0
        skipped = 0
        warnings = []
        skipped_details = []

        def _skip(record, reason, measured=None):
            nonlocal skipped
            skipped += 1
            name = str(
                record.get("bodyName")
                or record.get("panelId")
                or record.get("componentName")
                or "unnamed"
            )
            entry = {
                "bodyName": record.get("bodyName") or "",
                "panelId": record.get("panelId") or "",
                "componentName": record.get("componentName") or "",
                "measuredThicknessMm": measured if measured is not None else record.get("measuredThicknessMm"),
                "reason": reason,
            }
            skipped_details.append(entry)
            thickness_note = ""
            if entry.get("measuredThicknessMm") is not None:
                thickness_note = " t={:.2f}mm".format(float(entry["measuredThicknessMm"]))
            warnings.append("{}{}: {}".format(name, thickness_note, reason))

        def _sync_record_board_type(record, working, match_tag, measured):
            """Refresh in-memory scan row so UI need not re-scan the design."""
            record["metadata"] = working
            record["boardTypeTag"] = match_tag
            record["measuredThicknessMm"] = measured
            derived = dict(record.get("derivedTags") or {})
            derived["boardTypeTag"] = match_tag
            record["derivedTags"] = derived
            typed = dict(record.get("typedTags") or {})
            typed["boardTypeTag"] = match_tag
            record["typedTags"] = typed

        for record in records:
            if "body" not in str(record.get("entityKind") or "").lower():
                continue
            # Always re-measure with current rules so we prefer candidates that
            # match (avoids stale 14.5 face/bbox under-reads when CPT is 15).
            body, measure_warnings = self._body_from_metadata_record(
                root, record, prefer_path=True
            )
            for warning in measure_warnings:
                warnings.append(warning)
            meta = record.get("metadata") if isinstance(record.get("metadata"), dict) else {}
            report = thickness_rules.measure_body_thickness_report(
                body,
                meta,
                rules_payload=rules_payload,
            )
            measured = report.get("thicknessMm")
            if measured is not None:
                record["measuredThicknessMm"] = measured
                record["thicknessMeasureSource"] = report.get("source")
                record["thicknessMeasureDebug"] = {
                    "declaredMm": report.get("declaredMm"),
                    "designSpanMm": report.get("designSpanMm"),
                    "bboxMm": report.get("bboxMm"),
                    "dimensionsMm": report.get("dimensionsMm"),
                    "source": report.get("source"),
                }
            if measured is None:
                _skip(record, "could not measure thickness (no bbox/designGeometry)")
                continue
            match = thickness_rules.match_thickness_rule(measured, rules_payload)
            if not match:
                rule_hint = ", ".join(
                    "{}={}".format(r.get("boardTypeTag"), r.get("thicknessMm"))
                    for r in (rules_payload.get("rules") or [])
                )
                dbg = record.get("thicknessMeasureDebug") or {}
                dbg_note = " src={} declared={} span={} bbox={} dims={}".format(
                    dbg.get("source") or "?",
                    dbg.get("declaredMm"),
                    dbg.get("designSpanMm"),
                    dbg.get("bboxMm"),
                    dbg.get("dimensionsMm"),
                )
                _skip(
                    record,
                    "thickness {:.2f} mm outside rules [{}] ±{}{}".format(
                        float(measured),
                        rule_hint or "none",
                        rules_payload.get("toleranceMm"),
                        dbg_note,
                    ),
                    measured=measured,
                )
                continue
            if not body:
                _skip(record, "could not resolve Fusion body", measured=measured)
                continue
            # Write against full stored metadata (nesting scan drops faceRegistry /
            # SVG). Never rewrite a slim scan copy back onto the body.
            stored, _read_err = tag_metadata_editor._read_body_metadata_raw(body)
            existing = stored if isinstance(stored, dict) else {}
            if not existing:
                existing = (
                    dict(record.get("metadata"))
                    if isinstance(record.get("metadata"), dict)
                    else {}
                )
            if not isinstance(existing, dict):
                existing = {}
            existing = dict(existing)
            identity = dict(existing.get("identity") or {})
            if not str(identity.get("panelId") or "").strip():
                identity["panelId"] = str(
                    record.get("panelId")
                    or metadata_inspector._unmarked_panel_id(
                        record.get("componentName"), record.get("bodyName")
                    )
                )
                identity["sourceBoardId"] = str(
                    record.get("sourceBoardId")
                    or record.get("bodyName")
                    or record.get("componentName")
                    or identity["panelId"]
                )
                identity["runId"] = identity.get("runId") or "thickness"
                existing["identity"] = identity
            if isinstance(record.get("derivedTags"), dict):
                existing["derivedTags"] = dict(record.get("derivedTags") or {})
            board_state = attribute_state_service.board_type_state(existing)
            if bool(board_state.get("locked")):
                _skip(
                    record,
                    "manual board-type lock; Reset to Auto before thickness classification",
                    measured=measured,
                )
                continue
            known_tag = thickness_rules.current_board_type_tag(existing)
            match_tag = str(match.get("boardTypeTag") or "").strip().lower()
            if (
                not overwrite
                and thickness_rules.has_known_board_type(existing)
                and known_tag == match_tag
            ):
                # Already correct — count as updated/kept, not a skip.
                updated += 1
                continue
            if (
                not overwrite
                and thickness_rules.has_known_board_type(existing)
                and known_tag != match_tag
            ):
                _skip(
                    record,
                    "already has known board type '{}' (enable Overwrite to replace with '{}')".format(
                        known_tag, match_tag
                    ),
                    measured=measured,
                )
                continue
            working, changed = thickness_rules.apply_rule_to_metadata(
                existing, match, overwrite=overwrite
            )
            if not changed:
                # Same values already present (including after filling unknowns).
                updated += 1
                continue
            try:
                tag_metadata_editor._write_body_metadata(body, working)
                _sync_record_board_type(record, working, match_tag, measured)
                updated += 1
            except Exception as ex:
                _skip(record, "write failed: {}".format(ex), measured=measured)

        # No second full scan — records above already reflect writes for the UI list.
        if isinstance(diagnostics, dict):
            diagnostics = dict(diagnostics)
            diagnostics["scanDetail"] = "thickness"
            diagnostics["rescanAfterWrite"] = False
        return "panelAttributesResult", {
            "ok": True,
            "action": "applyThicknessClassification",
            "updatedCount": updated,
            "skippedCount": skipped,
            "skipped": skipped_details[:50],
            "records": records,
            "counts": counts,
            "diagnostics": diagnostics or {},
            "zoneFilter": zone_filter,
            "scanDetail": "thickness",
            "rules": rules_payload.get("rules") or [],
            "toleranceMm": rules_payload.get("toleranceMm"),
            "warnings": warnings[:40],
        }

    ZONE_OPACITY = 0.35
    ZONE_SPECS = {
        "assembly": {"bodyName": "AssemblyZone", "label": "Assembly Zone", "rgb": (45, 110, 225)},
        "generation": {"bodyName": "GenerationZone", "label": "Generation Zone", "rgb": (60, 170, 90)},
        "nesting": {"bodyName": "NestingZone", "label": "Nesting Zone", "rgb": (235, 150, 50)},
    }
    ZONE_SKETCH_NAMES = (
        "AssemblyZoneSketch", "AssemblyZoneTextSketch",  # legacy single-zone names
        "WorkZoneSketch_assembly", "WorkZoneSketch_generation", "WorkZoneSketch_nesting",
        "WorkZoneText_assembly", "WorkZoneText_generation", "WorkZoneText_nesting",
    )

    def get_work_zones(self, _payload, _palette):
        """Return the work-zone layout saved in the active design (if any)."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "getWorkZones",
                "errors": ["No active Fusion design."],
            }
        layout = work_zones.load_zone_layout(root)
        return "panelAttributesResult", {
            "ok": True,
            "action": "getWorkZones",
            "found": bool(layout),
            "layout": layout,
        }

    def set_work_zones(self, payload, _palette):
        app = adsk.core.Application.get()
        design = app.activeProduct if app else None
        root = self.fusion.get_root_component()
        if not root or design is None:
            return "panelAttributesResult", {
                "ok": False,
                "action": "setWorkZones",
                "errors": ["No active Fusion design."],
            }

        data = payload or {}
        width_mm = max(float(data.get("widthMm") or 10000.0), 1.0)
        depth_mm = max(float(data.get("depthMm") or 10000.0), 1.0)

        def _optional_mm(key):
            try:
                value = float(data.get(key) or 0.0)
                return value if value > 0 else None
            except Exception:
                return None

        generation_w = _optional_mm("generationWidthMm")
        generation_d = _optional_mm("generationDepthMm")
        nesting_w = _optional_mm("nestingWidthMm")
        nesting_d = _optional_mm("nestingDepthMm")

        # Without explicit nesting sizes, preserve a previously grown nesting
        # zone; everything is repositioned around the new assembly size.
        if nesting_w is None and nesting_d is None:
            previous = work_zones.load_zone_layout(root) or {}
            nesting_w, nesting_d = work_zones.rect_size(previous.get(work_zones.ZONE_NESTING))

        layout = work_zones.compute_zone_layout(
            width_mm, depth_mm, nesting_w, nesting_d,
            generation_width_mm=generation_w, generation_depth_mm=generation_d,
        )
        if work_zones.zones_overlap(layout):
            return "panelAttributesResult", {
                "ok": False,
                "action": "setWorkZones",
                "errors": ["Zone layout would overlap; adjust sizes."],
            }

        try:
            notes = self._rebuild_work_zone_visuals(root, layout, app, design)
            work_zones.save_zone_layout(root, layout)
            try:
                viewport = app.activeViewport
                if viewport:
                    viewport.fit()
                    viewport.refresh()
            except Exception:
                pass
        except Exception as ex:
            return "panelAttributesResult", {
                "ok": False,
                "action": "setWorkZones",
                "errors": ["Could not create work zones: {}".format(ex)],
            }

        return "panelAttributesResult", {
            "ok": True,
            "action": "setWorkZones",
            "widthMm": round(width_mm, 1),
            "depthMm": round(depth_mm, 1),
            "layout": layout,
            "visualMode": "lockedPlane",
            "notes": notes,
            "message": (
                "Work zones set as fixed non-selectable planes "
                "(assembly {:.0f}×{:.0f} mm; generation +X; nesting +Y; gap {:.0f} mm)."
            ).format(width_mm, depth_mm, layout.get("gapMm", 0.0)),
        }

    def _rebuild_work_zone_visuals(self, root, layout, app=None, design=None):
        """Recreate locked zone planes/labels from a layout. Returns note strings."""
        if app is None:
            app = adsk.core.Application.get()
        if design is None and app is not None:
            design = app.activeProduct
        self._remove_existing_work_zones(root)
        self._clear_zone_custom_graphics(root)
        notes = []
        try:
            for zone_id in (
                work_zones.ZONE_ASSEMBLY,
                work_zones.ZONE_GENERATION,
                work_zones.ZONE_NESTING,
            ):
                rect = layout.get(zone_id) if isinstance(layout, dict) else None
                if not isinstance(rect, dict):
                    notes.append("{}: missing rect".format(zone_id))
                    continue
                spec = self.ZONE_SPECS[zone_id]
                body = self._create_zone_plane(root, zone_id, rect)
                if body is None:
                    notes.append("{}: create failed".format(zone_id))
                    continue
                body.name = spec["bodyName"]
                self._mark_zone_body(body, zone_id)
                self._lock_zone_body(body)
                status = self._apply_zone_appearance(app, design, body, zone_id, spec["rgb"])
                try:
                    body.opacity = self.ZONE_OPACITY
                except Exception:
                    pass
                label_ok = self._add_zone_custom_labels(
                    root, zone_id, spec["label"], rect, spec["rgb"]
                )
                notes.append("{}: locked, {}, labels={}".format(
                    zone_id, status, "ok" if label_ok else "failed"
                ))
        except Exception as ex:
            notes.append("rebuild failed: {}".format(ex))
        return notes

    def _create_zone_plane(self, root, zone_id, rect):
        try:
            sketch = root.sketches.add(root.xYConstructionPlane)
            sketch.name = "WorkZoneSketch_{}".format(zone_id)
            point = adsk.core.Point3D
            sketch.sketchCurves.sketchLines.addTwoPointRectangle(
                point.create(rect["x0"] / 10.0, rect["y0"] / 10.0, 0.0),
                point.create(rect["x1"] / 10.0, rect["y1"] / 10.0, 0.0),
            )
            profile = sketch.profiles.item(0)
            patches = root.features.patchFeatures
            patch_input = patches.createInput(
                profile, adsk.fusion.FeatureOperations.NewBodyFeatureOperation
            )
            patch = patches.add(patch_input)
            # Hide the construction sketch so its curves/text cannot be picked.
            try:
                sketch.isVisible = False
            except Exception:
                pass
            try:
                sketch.isLightBulbOn = False
            except Exception:
                pass
            return patch.bodies.item(0)
        except Exception:
            return None

    def _mark_zone_body(self, body, zone_id):
        try:
            body.attributes.add(
                work_zones.WORK_ZONE_MARKER_GROUP,
                work_zones.WORK_ZONE_MARKER_NAME,
                work_zones.WORK_ZONE_MARKER_VALUE,
            )
            body.attributes.add(work_zones.WORK_ZONE_MARKER_GROUP, "zoneId", str(zone_id))
        except Exception:
            pass

    def _lock_zone_body(self, body):
        """Keep the plane visible but prevent viewport selection / drag."""
        try:
            body.isSelectable = False
        except Exception:
            pass
        try:
            body.isLightBulbOn = True
        except Exception:
            pass

    def _zone_graphics_group(self, root):
        try:
            graphics = root.customGraphicsGroups
            for index in range(graphics.count):
                group = graphics.item(index)
                if group and group.id == "UC_WorkZoneLabels":
                    return group
            group = graphics.add()
            try:
                group.id = "UC_WorkZoneLabels"
            except Exception:
                pass
            try:
                group.isSelectable = False
            except Exception:
                pass
            return group
        except Exception:
            return None

    def _clear_zone_custom_graphics(self, root):
        try:
            graphics = root.customGraphicsGroups
            for index in range(graphics.count - 1, -1, -1):
                group = graphics.item(index)
                if group and group.id == "UC_WorkZoneLabels":
                    group.deleteMe()
        except Exception:
            pass

    def _add_zone_custom_labels(self, root, zone_id, label, rect, rgb):
        """Non-selectable CustomGraphics text — SketchText cannot be locked."""
        group = self._zone_graphics_group(root)
        if group is None:
            return False
        try:
            w_cm = (rect["x1"] - rect["x0"]) / 10.0
            d_cm = (rect["y1"] - rect["y0"]) / 10.0
            cx = (rect["x0"] + rect["x1"]) / 2.0 / 10.0
            height_cm = max(min(w_cm, d_cm) * 0.04, 0.5)
            margin = height_cm * 1.8
            z_cm = 0.02  # slightly above the plane to avoid z-fighting
            color = adsk.core.Color.create(int(rgb[0]), int(rgb[1]), int(rgb[2]), 255)
            try:
                text_color = adsk.fusion.CustomGraphicsSolidColorEffect.create(color)
            except Exception:
                text_color = None
            ok = True
            for y_center in (rect["y0"] / 10.0 + margin, rect["y1"] / 10.0 - margin):
                matrix = adsk.core.Matrix3D.create()
                # Center the label roughly under the text width estimate.
                approx_width = max(len(label) * height_cm * 0.55, height_cm)
                matrix.translation = adsk.core.Vector3D.create(
                    cx - approx_width / 2.0, y_center - height_cm / 2.0, z_cm
                )
                try:
                    graphics_text = group.addText(label, "Arial", height_cm, matrix)
                except Exception:
                    ok = False
                    continue
                try:
                    graphics_text.isSelectable = False
                except Exception:
                    pass
                if text_color is not None:
                    try:
                        graphics_text.color = text_color
                    except Exception:
                        pass
                try:
                    graphics_text.billBoarding = adsk.fusion.CustomGraphicsBillBoard.create(
                        adsk.core.Point3D.create(cx, y_center, z_cm)
                    )
                except Exception:
                    pass
            try:
                group.isSelectable = False
            except Exception:
                pass
            return ok
        except Exception:
            return False

    def _remove_existing_work_zones(self, root):
        zone_body_names = {spec["bodyName"] for spec in self.ZONE_SPECS.values()}
        try:
            bodies = root.bRepBodies
            for index in range(bodies.count - 1, -1, -1):
                body = bodies.item(index)
                if not body:
                    continue
                name = str(getattr(body, "name", "") or "")
                is_named = name in zone_body_names
                is_marked = False
                try:
                    attr = body.attributes.itemByName(
                        work_zones.WORK_ZONE_MARKER_GROUP,
                        work_zones.WORK_ZONE_MARKER_NAME,
                    )
                    is_marked = bool(attr and str(attr.value) == work_zones.WORK_ZONE_MARKER_VALUE)
                except Exception:
                    is_marked = False
                if is_named or is_marked:
                    body.deleteMe()
        except Exception:
            pass
        try:
            sketches = root.sketches
            for index in range(sketches.count - 1, -1, -1):
                sketch = sketches.item(index)
                if sketch and sketch.name in self.ZONE_SKETCH_NAMES:
                    sketch.deleteMe()
        except Exception:
            pass
        try:
            planes = root.constructionPlanes
            for index in range(planes.count - 1, -1, -1):
                plane = planes.item(index)
                if plane and plane.name in ("AssemblyZoneTextPlane", "WorkZoneTextPlane"):
                    plane.deleteMe()
        except Exception:
            pass
        self._clear_zone_custom_graphics(root)

    def _find_appearance_library(self, app):
        try:
            libraries = app.materialLibraries
        except Exception:
            return None
        try:
            lib = libraries.itemByName("Fusion 360 Appearance Library")
            if lib is not None and getattr(lib, "appearances", None) and lib.appearances.count:
                return lib
        except Exception:
            pass
        try:
            for index in range(libraries.count):
                library = libraries.item(index)
                lib_appearances = getattr(library, "appearances", None)
                if lib_appearances and lib_appearances.count:
                    return library
        except Exception:
            pass
        return None

    def _pick_base_appearance(self, library):
        appearances = library.appearances
        preferred = [
            "Paint - Enamel Glossy (Blue)",
            "Plastic - Matte (Blue)",
            "Plastic - Glossy (Blue)",
            "Paint - Enamel Glossy (Generic)",
            "Plastic - Matte (Generic)",
            "Powder Coat (Blue)",
        ]
        for name in preferred:
            try:
                appearance = appearances.itemByName(name)
                if appearance is not None:
                    return appearance
            except Exception:
                continue
        try:
            for index in range(appearances.count):
                candidate = appearances.item(index)
                if self._appearance_has_color(candidate):
                    return candidate
        except Exception:
            pass
        try:
            return appearances.item(0)
        except Exception:
            return None

    def _appearance_has_color(self, appearance):
        try:
            props = appearance.appearanceProperties
            for index in range(props.count):
                if isinstance(props.item(index), adsk.core.ColorProperty):
                    return True
        except Exception:
            pass
        return False

    def _apply_zone_appearance(self, app, design, body, zone_id, rgb):
        try:
            appearances = design.appearances
            name = "UC Work Zone {}".format(zone_id)
            appearance = None
            try:
                appearance = appearances.itemByName(name)
            except Exception:
                appearance = None
            if appearance is None:
                library = self._find_appearance_library(app)
                if library is None:
                    return "no appearance library found"
                base = self._pick_base_appearance(library)
                if base is None:
                    return "no base appearance found"
                appearance = appearances.addByCopy(base, name)
            if appearance is None:
                return "could not create appearance"
            colored = self._set_appearance_color(appearance, rgb[0], rgb[1], rgb[2])
            self._set_appearance_opacity(appearance, self.ZONE_OPACITY)
            body.appearance = appearance
            return "applied '{}', colorSet={}".format(appearance.name, colored)
        except Exception as ex:
            return "failed: {}".format(ex)

    def _set_appearance_color(self, appearance, red, green, blue):
        color = adsk.core.Color.create(red, green, blue, 0)
        properties = None
        try:
            properties = appearance.appearanceProperties
        except Exception:
            return False
        set_any = False
        for prop_id in ("opaque_albedo", "surface_albedo", "generic_diffuse", "metal_f0"):
            try:
                prop = properties.itemById(prop_id)
            except Exception:
                prop = None
            if isinstance(prop, adsk.core.ColorProperty):
                try:
                    prop.value = color
                    set_any = True
                except Exception:
                    pass
        if not set_any:
            try:
                for index in range(properties.count):
                    prop = properties.item(index)
                    if isinstance(prop, adsk.core.ColorProperty):
                        try:
                            prop.value = color
                            set_any = True
                        except Exception:
                            continue
            except Exception:
                pass
        return set_any

    def _set_appearance_opacity(self, appearance, opacity):
        try:
            properties = appearance.appearanceProperties
            for index in range(properties.count):
                prop = properties.item(index)
                name = ""
                try:
                    name = "{} {}".format(getattr(prop, "id", "") or "", getattr(prop, "name", "") or "").lower()
                except Exception:
                    name = ""
                if isinstance(prop, adsk.core.FloatProperty) and ("opacity" in name or "transparen" in name):
                    try:
                        prop.value = float(opacity)
                    except Exception:
                        continue
        except Exception:
            pass

    def tag_scan_selected(self, _payload, _palette):
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "tagScanSelected",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": True,
                "action": "tagScanSelected",
                "results": [],
                "warnings": ["No body, face, or edge selected."],
            }

        results, warnings = metadata_inspector.tag_scan_selected(selected_entities, root)
        return "panelAttributesResult", {
            "ok": True,
            "action": "tagScanSelected",
            "results": results,
            "count": len(results),
            "warnings": warnings[:20],
        }

    def apply_tag_scan_drafts(self, payload, _palette):
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyTagScanDrafts",
                "errors": ["No active Fusion design."],
            }

        drafts = (payload or {}).get("drafts") or []
        results = (payload or {}).get("results") or []
        if not drafts:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyTagScanDrafts",
                "errors": ["No pending tag edits to apply."],
            }
        if not results:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyTagScanDrafts",
                "errors": ["Tag scan context is missing. Scan selected entities again, then apply."],
            }

        applied, failed = tag_metadata_editor.apply_tag_scan_drafts(
            results,
            drafts,
            lambda token, kind, result: self._resolve_tag_scan_entity(
                token,
                kind,
                result,
                selected_bodies=self._selected_bodies(),
            ),
        )

        refreshed_results = results
        refreshed_warnings = []
        selected_entities = self._selected_entities()
        if selected_entities:
            refreshed_results, refreshed_warnings = metadata_inspector.tag_scan_selected(selected_entities, root)

        return "panelAttributesResult", {
            "ok": len(applied) > 0 and len(failed) == 0,
            "action": "applyTagScanDrafts",
            "applied": applied,
            "failed": failed,
            "appliedCount": len(applied),
            "failedCount": len(failed),
            "results": refreshed_results,
            "warnings": refreshed_warnings[:20],
            "errors": [item.get("error") for item in failed if item.get("error")][:20] if failed and not applied else [],
        }

    def reset_attribute_to_auto(self, payload, _palette):
        """Unlock a manual boardType/color/faceUp override on selected bodies."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "resetAttributeToAuto",
                "errors": ["No active Fusion design."],
            }
        field = str((payload or {}).get("field") or "").strip()
        if field not in ("boardType", "color", "faceUp", "cuttingFace"):
            return "panelAttributesResult", {
                "ok": False,
                "action": "resetAttributeToAuto",
                "errors": ["field must be boardType, color, faceUp, or cuttingFace."],
            }
        selected_entities = self._selected_entities()
        bodies, expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root
        ) if selected_entities else ([], [])
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "resetAttributeToAuto",
                "errors": ["Select one or more panel bodies first."],
                "warnings": list(expand_warnings or [])[:20],
            }

        updated = []
        failed = []
        for body in bodies:
            name = str(getattr(body, "name", "") or "") or "body"
            try:
                tag_metadata_editor.reset_field_to_auto(body, field)
                updated.append(name)
            except Exception as ex:
                failed.append({"bodyName": name, "reason": str(ex)})
        return "panelAttributesResult", {
            "ok": bool(updated),
            "action": "resetAttributeToAuto",
            "field": field,
            "bodyCount": len(bodies),
            "updatedCount": len(updated),
            "failedCount": len(failed),
            "updatedBodies": updated[:100],
            "failed": failed[:40],
            "warnings": list(expand_warnings or [])[:20],
            "errors": [] if updated else ["No selected panel could be unlocked."],
            "message": "Reset {} to Auto: updated {}, failed {}.".format(
                field, len(updated), len(failed)
            ),
        }

    def apply_door_color_to_selection(self, payload, _palette):
        """Apply a named color to doors only or every selected panel."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyDoorColorToSelection",
                "errors": ["No active Fusion design."],
            }

        color_name = str((payload or {}).get("colorName") or "").strip()
        surface_mode = str((payload or {}).get("surfaceMode") or "").strip()
        scope = str((payload or {}).get("scope") or "doors").strip().lower()
        if scope not in ("doors", "panels"):
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyDoorColorToSelection",
                "errors": ["scope must be doors or panels."],
            }
        if not color_name:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyDoorColorToSelection",
                "errors": ["Color name is required."],
            }
        try:
            _preview, color_tag, mode_enum = tag_metadata_editor.apply_panel_color_to_metadata(
                {}, color_name, surface_mode, is_door=(scope == "doors")
            )
        except ValueError as ex:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyDoorColorToSelection",
                "errors": [str(ex)],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyDoorColorToSelection",
                "errors": ["Select an assembly, component, or body first."],
                "colorTag": color_tag,
                "surfaceMode": mode_enum,
                "scope": scope,
            }

        bodies, expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root
        )
        updated = 0
        skipped_non_door = 0
        skipped_errors = 0
        warnings = list(expand_warnings or [])
        updated_names = []
        errors = []

        for body in bodies:
            is_door = metadata_inspector.body_looks_like_door(body)
            if not tag_metadata_editor.color_scope_allows(scope, is_door):
                skipped_non_door += 1
                continue
            try:
                metadata, read_error = tag_metadata_editor._read_body_metadata_raw(body)
                if read_error:
                    skipped_errors += 1
                    errors.append("{}: {}".format(getattr(body, "name", "body") or "body", read_error))
                    continue
                base = tag_metadata_editor._bootstrap_body_metadata(body, metadata)
                patched, _tag, _mode = tag_metadata_editor.apply_panel_color_to_metadata(
                    base,
                    color_name,
                    surface_mode,
                    is_door=is_door,
                )
                tag_metadata_editor._write_body_metadata(body, patched)
                if is_door:
                    repair = milling_surface_propagation.ensure_complementary_surface_roles(
                        body,
                        write_pair=lambda b, fa, ra, fb, rb, source="repair_complementary": (
                            tag_metadata_editor.apply_surface_roles(
                                b, fa, ra, fb, rb, source=source, lock=False, force=True
                            )
                        ),
                    )
                    if repair.get("warning"):
                        warnings.append(repair["warning"])
                updated += 1
                updated_names.append(str(getattr(body, "name", "") or "") or "body")
            except Exception as ex:
                skipped_errors += 1
                errors.append("{}: {}".format(getattr(body, "name", "body") or "body", ex))

        if not bodies:
            warnings.append("No solid panel bodies found under the current selection.")

        ok = updated > 0
        summary_bits = ["updated {}".format(updated)]
        if scope == "doors":
            summary_bits.append("skipped non-door {}".format(skipped_non_door))
        if skipped_errors:
            summary_bits.append("errors {}".format(skipped_errors))
        return "panelAttributesResult", {
            "ok": ok if bodies else False,
            "action": "applyDoorColorToSelection",
            "colorName": color_name,
            "colorTag": color_tag,
            "surfaceMode": mode_enum,
            "scope": scope,
            "updatedCount": updated,
            "skippedNonDoorCount": skipped_non_door,
            "skippedErrorCount": skipped_errors,
            "bodyCount": len(bodies),
            "updatedBodies": updated_names[:40],
            "warnings": warnings[:20],
            "errors": errors[:20] if (errors and not updated) else (errors[:10] if errors else []),
            "message": "Color '{}' [{}]: {}.".format(
                color_tag, scope, ", ".join(summary_bits)
            ),
        }

    def apply_grain_to_selection(self, payload, _palette):
        """Write grainAlongMm from UI 横/竖 (relative to world Z) onto selected bodies."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyGrainToSelection",
                "errors": ["No active Fusion design."],
            }

        try:
            orientation = grain_direction.normalize_orientation(
                (payload or {}).get("orientation")
            )
        except ValueError as ex:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyGrainToSelection",
                "errors": [str(ex)],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "applyGrainToSelection",
                "errors": ["Select a body, or a face/edge belonging to a body."],
                "orientation": orientation,
            }

        bodies, expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root
        )
        updated = 0
        skipped_errors = 0
        warnings = list(expand_warnings or [])
        updated_names = []
        applied = []
        errors = []

        for body in bodies:
            name = str(getattr(body, "name", "") or "") or "body"
            try:
                if orientation == grain_direction.ORIENT_NONE:
                    grain_mm = ""
                    detail = None
                else:
                    grain_mm, detail = grain_direction.grain_along_mm_for_body(
                        body, orientation
                    )
                metadata, read_error = tag_metadata_editor._read_body_metadata_raw(body)
                if read_error:
                    skipped_errors += 1
                    errors.append("{}: {}".format(name, read_error))
                    continue
                base = tag_metadata_editor._bootstrap_body_metadata(body, metadata)
                patched, result = tag_metadata_editor.apply_grain_along_to_metadata(
                    base, grain_mm
                )
                tag_metadata_editor._write_body_metadata(body, patched)
                updated += 1
                updated_names.append(name)
                item = {
                    "bodyName": name,
                    "grainAlongMm": grain_mm if grain_mm != "" else None,
                    "changed": bool((result or {}).get("changed")),
                }
                if isinstance(detail, dict):
                    item["faceEdgesMm"] = detail.get("faceEdgesMm")
                    item["thicknessMm"] = detail.get("thicknessMm")
                applied.append(item)
            except Exception as ex:
                skipped_errors += 1
                errors.append("{}: {}".format(name, ex))

        if not bodies:
            warnings.append("No solid panel bodies found under the current selection.")

        ok = updated > 0
        if orientation == grain_direction.ORIENT_NONE:
            summary = "cleared grainAlongMm on {}".format(updated)
        else:
            summary = "wrote grainAlongMm from {} on {}".format(orientation, updated)
        if skipped_errors:
            summary += ", errors {}".format(skipped_errors)
        return "panelAttributesResult", {
            "ok": ok if bodies else False,
            "action": "applyGrainToSelection",
            "orientation": orientation,
            "updatedCount": updated,
            "skippedErrorCount": skipped_errors,
            "bodyCount": len(bodies),
            "updatedBodies": updated_names[:40],
            "applied": applied[:40],
            "warnings": warnings[:20],
            "errors": errors[:20] if (errors and not updated) else (errors[:10] if errors else []),
            "message": "Wood grain: {}.".format(summary),
        }

    def propagate_milling_from_hinge_cups(self, _payload, _palette):
        """Propagate MILLING back-face from hinge-cup panels to coplanar neighbors."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "propagateMillingFromHingeCups",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "propagateMillingFromHingeCups",
                "errors": ["Select an assembly, component, or body first."],
            }

        bodies, expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root
        )
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "propagateMillingFromHingeCups",
                "errors": ["No solid panel bodies found under the current selection."],
                "warnings": list(expand_warnings or [])[:20],
            }

        result = milling_surface_propagation.propagate_milling_from_hinge_cups(
            bodies,
            write_roles=lambda body, milling, non_milling: (
                tag_metadata_editor.apply_surface_milling_roles(
                    body,
                    milling,
                    non_milling,
                    source="hinge_cups",
                    lock=False,
                )
            ),
        )
        warnings = list(expand_warnings or []) + list(result.get("warnings") or [])
        return "panelAttributesResult", {
            "ok": bool(result.get("ok")),
            "action": "propagateMillingFromHingeCups",
            "sourceCount": int(result.get("sourceCount") or 0),
            "updatedCount": int(result.get("updatedCount") or 0),
            "skippedCount": int(result.get("skippedCount") or 0),
            "bodyCount": len(bodies),
            "sources": result.get("sources") or [],
            "updated": result.get("updated") or [],
            "skipped": result.get("skipped") or [],
            "warnings": warnings[:40],
            "errors": [] if result.get("ok") else [result.get("message") or "Propagation failed."],
            "message": result.get("message") or "",
        }

    def revert_door_surfaces(self, _payload, _palette):
        """Manual front/back override → definite MILLING/NON_MILLING.

        Face / body / edge: fast path — only those bodies, pure role flip
        (no assembly expand, no hinge/half-slot scan). Cost is O(selection).
        Assembly / component: doors under the selection only (bulk path).
        Always locks face-up so Orient cannot write EITHER back over it.
        """
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "revertDoorSurfaces",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "revertDoorSurfaces",
                "errors": ["Select a face (or door / parent assembly) first."],
            }

        explicit_bodies = []
        preferred_faces = {}
        expand_warnings = []
        seen_explicit = set()
        for entity in selected_entities:
            kind = metadata_inspector._entity_kind(entity)
            if kind not in ("face", "body", "edge"):
                continue
            body, _source = metadata_inspector._selection_owner_body(entity)
            if not body:
                expand_warnings.append("Could not resolve body from selected {}.".format(kind))
                continue
            if metadata_inspector._is_assembly_zone(body):
                expand_warnings.append("Skipped work-zone helper body.")
                continue
            if metadata_inspector._is_nested_instance(body):
                expand_warnings.append("Skipped nested-instance copy (nesting output).")
                continue
            key = metadata_inspector._body_key(body)
            if key in seen_explicit:
                if kind == "face" and id(body) not in preferred_faces:
                    preferred_faces[id(body)] = entity
                continue
            seen_explicit.add(key)
            explicit_bodies.append(body)
            if kind == "face":
                preferred_faces[id(body)] = entity

        bulk_entities = [
            entity for entity in selected_entities
            if metadata_inspector._entity_kind(entity) not in ("face", "body", "edge")
        ]
        bulk_bodies = []
        if bulk_entities:
            expanded, bulk_warnings = metadata_inspector.bodies_from_selected_entities(
                bulk_entities, root
            )
            expand_warnings.extend(bulk_warnings or [])
            for body in expanded:
                key = metadata_inspector._body_key(body)
                if key in seen_explicit:
                    continue
                bulk_bodies.append(body)

        if not explicit_bodies and not bulk_bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "revertDoorSurfaces",
                "errors": ["No solid panel bodies found under the current selection."],
                "warnings": list(expand_warnings or [])[:20],
            }

        def _write(body, milling, non_milling):
            return tag_metadata_editor.apply_surface_milling_roles(
                body,
                milling,
                non_milling,
                source="manual",
                lock=False,
                force=True,
            )

        updated = []
        skipped = []
        warnings = list(expand_warnings or [])
        fast_path_count = 0

        # Explicit picks: O(selection) flip — never hinge/slot, never door filter.
        if explicit_bodies:
            fast = milling_surface_propagation.flip_selected_body_milling(
                explicit_bodies,
                write_roles=_write,
                preferred_faces=preferred_faces,
            )
            updated.extend(fast.get("updated") or [])
            skipped.extend(fast.get("skipped") or [])
            warnings.extend(fast.get("warnings") or [])
            fast_path_count = int(fast.get("updatedCount") or 0)

        # Assembly picks: doors only (may scan hinge/slot when roles are ambiguous).
        if bulk_bodies:
            bulk = milling_surface_propagation.swap_surface_roles(
                bulk_bodies,
                write_roles=_write,
                is_door_body=metadata_inspector.body_looks_like_door,
                preferred_faces={},
            )
            updated.extend(bulk.get("updated") or [])
            skipped.extend(bulk.get("skipped") or [])
            warnings.extend(bulk.get("warnings") or [])

        skipped_non_door = sum(1 for item in skipped if item.get("reason") == "not_door")
        updated_count = len(updated)
        body_count = len(explicit_bodies) + len(bulk_bodies)
        if updated_count:
            message = (
                "Swapped panel faces: updated {} (fast {}, assembly doors {}), skipped {}."
                .format(
                    updated_count,
                    fast_path_count,
                    max(0, updated_count - fast_path_count),
                    len(skipped),
                )
            )
        else:
            message = "No panel surface was swapped."

        return "panelAttributesResult", {
            "ok": updated_count > 0,
            "action": "revertDoorSurfaces",
            "bodyCount": body_count,
            "explicitCount": len(explicit_bodies),
            "bulkCount": len(bulk_bodies),
            "fastPathCount": fast_path_count,
            "updatedCount": updated_count,
            "skippedCount": len(skipped),
            "skippedNonDoorCount": skipped_non_door,
            "updated": updated,
            "skipped": skipped[:40],
            "warnings": warnings[:40],
            "errors": [] if updated_count else [message],
            "message": message,
        }

    def revert_selected_milling(self, _payload, _palette):
        """Fast flip: selected face/body only — milling moves to the other broad face.

        Explicitly ignores assemblies/components so cost stays O(selection), not
        O(design board count). No hinge-cup or half-slot geometry scan.
        """
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "revertSelectedMilling",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "revertSelectedMilling",
                "errors": ["Select a body or face first (not a whole assembly)."],
            }

        bodies = []
        preferred_faces = {}
        warnings = []
        seen = set()
        ignored_bulk = 0
        for entity in selected_entities:
            kind = metadata_inspector._entity_kind(entity)
            if kind not in ("face", "body", "edge"):
                ignored_bulk += 1
                continue
            body, _source = metadata_inspector._selection_owner_body(entity)
            if not body:
                warnings.append("Could not resolve body from selected {}.".format(kind))
                continue
            if metadata_inspector._is_assembly_zone(body):
                warnings.append("Skipped work-zone helper body.")
                continue
            if metadata_inspector._is_nested_instance(body):
                warnings.append("Skipped nested-instance copy (nesting output).")
                continue
            key = metadata_inspector._body_key(body)
            if key in seen:
                if kind == "face" and id(body) not in preferred_faces:
                    preferred_faces[id(body)] = entity
                continue
            seen.add(key)
            bodies.append(body)
            if kind == "face":
                preferred_faces[id(body)] = entity

        if ignored_bulk and not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "revertSelectedMilling",
                "errors": [
                    "Select a panel body or face. Whole assemblies are ignored "
                    "so this stays fast (O(selection), not O(all boards))."
                ],
                "warnings": warnings[:20],
            }
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "revertSelectedMilling",
                "errors": ["No solid panel body found under the current selection."],
                "warnings": warnings[:20],
            }
        if ignored_bulk:
            warnings.append(
                "Ignored {} assembly/component pick(s); only face/body/edge are flipped."
                .format(ignored_bulk)
            )

        result = milling_surface_propagation.flip_selected_body_milling(
            bodies,
            write_roles=lambda body, milling, non_milling: (
                tag_metadata_editor.apply_surface_milling_roles(
                    body,
                    milling,
                    non_milling,
                    source="manual",
                    lock=False,
                    force=True,
                )
            ),
            preferred_faces=preferred_faces,
        )
        warnings = warnings + list(result.get("warnings") or [])
        return "panelAttributesResult", {
            "ok": bool(result.get("ok")),
            "action": "revertSelectedMilling",
            "bodyCount": len(bodies),
            "updatedCount": int(result.get("updatedCount") or 0),
            "skippedCount": int(result.get("skippedCount") or 0),
            "updated": result.get("updated") or [],
            "skipped": (result.get("skipped") or [])[:40],
            "warnings": warnings[:40],
            "errors": [] if result.get("ok") else [result.get("message") or "No milling face was flipped."],
            "message": result.get("message") or "",
        }

    def reverse_milling_face(self, _payload, _palette):
        """Flip milling/colour on selection; sync source; flip LAY_FLAT geometry.

        - Body selection → complementary flip on that body.
        - Face selection → selected broad face becomes colour (NON_MILLING),
          opposite becomes MILLING.
        - Lay Flat copy → also write the original via ``sourcePanelId``, then
          rotate the LAY_FLAT body 180° about X so MILLING returns to +Z.
        - Always force Analyze on affected LAY_FLAT bodies afterward.
        """
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "reverseMillingFace",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "reverseMillingFace",
                "errors": ["Select a body or face first (not a whole assembly)."],
            }

        def _write_roles(body, milling, non_milling):
            return tag_metadata_editor.apply_surface_milling_roles(
                body,
                milling,
                non_milling,
                source="manual",
                lock=False,
                force=True,
            )

        bodies = []
        preferred_faces = {}
        warnings = []
        seen = set()
        ignored_bulk = 0
        for entity in selected_entities:
            kind = metadata_inspector._entity_kind(entity)
            if kind not in ("face", "body", "edge"):
                ignored_bulk += 1
                continue
            body, _source = metadata_inspector._selection_owner_body(entity)
            if not body:
                warnings.append("Could not resolve body from selected {}.".format(kind))
                continue
            if metadata_inspector._is_assembly_zone(body):
                warnings.append("Skipped work-zone helper body.")
                continue
            # Allow Lay Flat; still skip Nesting layout workpieces.
            if metadata_inspector._is_nested_instance(body) and not (
                metadata_inspector._is_lay_flat_workpiece(body)
            ):
                warnings.append("Skipped Nesting layout copy (not Lay Flat).")
                continue
            key = metadata_inspector._body_key(body)
            if key in seen:
                if kind == "face" and id(body) not in preferred_faces:
                    preferred_faces[id(body)] = entity
                continue
            seen.add(key)
            bodies.append(body)
            if kind == "face":
                preferred_faces[id(body)] = entity

        if ignored_bulk and not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "reverseMillingFace",
                "errors": [
                    "Select a panel body or face. Whole assemblies are ignored "
                    "so this stays fast (O(selection), not O(all boards))."
                ],
                "warnings": warnings[:20],
            }
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "reverseMillingFace",
                "errors": ["No solid panel body found under the current selection."],
                "warnings": warnings[:20],
            }
        if ignored_bulk:
            warnings.append(
                "Ignored {} assembly/component pick(s); only face/body/edge are flipped."
                .format(ignored_bulk)
            )

        primary = milling_surface_propagation.flip_selected_body_milling(
            bodies,
            write_roles=_write_roles,
            preferred_faces=preferred_faces,
        )
        warnings = warnings + list(primary.get("warnings") or [])

        # Exact SourceRef path: never authorize a source write from panelId.
        source_bodies = []
        source_seen = set()
        source_for_lay_flat = {}
        source_updated = []
        source_skipped = []
        for body in bodies:
            is_lay_flat = False
            try:
                is_lay_flat = bool(metadata_inspector._is_lay_flat_workpiece(body))
            except Exception:
                is_lay_flat = False
            if not is_lay_flat:
                # Selection already is (or includes) the assembly model body.
                continue
            canonical_ref = panel_source_ref.from_lay_flat_body(body)
            lineage_key = panel_source_ref.key(canonical_ref)
            if not lineage_key:
                source_skipped.append({
                    "bodyName": str(getattr(body, "name", "") or ""),
                    "reason": "missing exact source lineage",
                })
                continue
            resolved, _fields, resolution = (
                panel_body_resolver.resolve_source_bodies_for_lay_flat(
                    root,
                    body,
                    index=None,
                    allow_panel_id_fallback=False,
                )
            )
            if len(resolved) != 1:
                source_skipped.append({
                    "bodyName": str(getattr(body, "name", "") or ""),
                    "sourceKey": lineage_key,
                    "reason": "exact source lineage did not resolve ({})".format(
                        resolution or "none"
                    ),
                })
                continue
            source_body = resolved[0]
            source_key = metadata_inspector._body_key(source_body)
            source_for_lay_flat[metadata_inspector._body_key(body)] = source_body
            if source_key in source_seen:
                continue
            # Avoid double-writing if the original was also in the selection.
            if source_key in seen:
                continue
            source_seen.add(source_key)
            source_bodies.append(source_body)

        source_result = {"updated": [], "skipped": [], "updatedCount": 0, "skippedCount": 0}
        if source_bodies:
            # Complementary flip on the original (no preferred face — tokens differ).
            source_result = milling_surface_propagation.flip_selected_body_milling(
                source_bodies,
                write_roles=_write_roles,
                preferred_faces=None,
            )
            warnings = warnings + list(source_result.get("warnings") or [])
            source_updated = list(source_result.get("updated") or [])
            source_skipped = source_skipped + list(source_result.get("skipped") or [])

        updated_count = int(primary.get("updatedCount") or 0)
        source_updated_count = int(source_result.get("updatedCount") or 0)
        skipped_names = {
            str(item.get("bodyName") or "")
            for item in (primary.get("skipped") or [])
        }
        ok = updated_count > 0 or source_updated_count > 0

        # After role swap, physically flip LAY_FLAT copies 180° so MILLING
        # returns to +Z (tag-only reverse leaves the board upside_down).
        geometry_flipped = []
        geometry_failed = []
        analyze_targets = []
        analyze_seen = set()

        def _queue_analyze(body):
            if body is None:
                return
            key = metadata_inspector._body_key(body)
            if key in analyze_seen:
                return
            analyze_seen.add(key)
            analyze_targets.append(body)

        def _geometry_flip_lay_flat(body):
            result = nesting_lay_flat_fusion.flip_lay_flat_body_thickness(body)
            if result.get("ok"):
                geometry_flipped.append(result)
                _queue_analyze(body)
            else:
                geometry_failed.append(result)
                warnings.append(
                    "{}: {}".format(
                        result.get("bodyName") or "body",
                        result.get("reason") or "geometry_flip_failed",
                    )
                )

        if ok:
            flipped_source_keys = set()
            for body in bodies:
                body_name = str(getattr(body, "name", "") or "")
                if body_name and body_name in skipped_names:
                    continue
                is_lay_flat = False
                try:
                    is_lay_flat = bool(metadata_inspector._is_lay_flat_workpiece(body))
                except Exception:
                    is_lay_flat = False
                if is_lay_flat:
                    _geometry_flip_lay_flat(body)
                    continue
                flipped_source_keys.add(metadata_inspector._body_key(body))

            # Original-model selection: also role-flip + geometry-flip matching
            # LAY_FLAT copies so Export Ready faces_up stays consistent.
            if flipped_source_keys:
                linked_lay_flat = []
                for lay_flat_body in nesting_lay_flat_face_up.collect_lay_flat_bodies(root):
                    resolved, _fields, _resolution = (
                        panel_body_resolver.resolve_source_bodies_for_lay_flat(
                            root,
                            lay_flat_body,
                            index=None,
                            allow_panel_id_fallback=False,
                        )
                    )
                    if len(resolved) != 1:
                        continue
                    linked_source = resolved[0]
                    if (
                        metadata_inspector._body_key(linked_source)
                        not in flipped_source_keys
                    ):
                        continue
                    key = metadata_inspector._body_key(lay_flat_body)
                    source_for_lay_flat[key] = linked_source
                    if key in analyze_seen or key in seen:
                        # Already geometry-flipped as a direct selection.
                        if key in seen:
                            _queue_analyze(lay_flat_body)
                        continue
                    linked_lay_flat.append(lay_flat_body)
                if linked_lay_flat:
                    linked_result = milling_surface_propagation.flip_selected_body_milling(
                        linked_lay_flat,
                        write_roles=_write_roles,
                        preferred_faces=None,
                    )
                    warnings = warnings + list(linked_result.get("warnings") or [])
                    linked_skipped = {
                        str(item.get("bodyName") or "")
                        for item in (linked_result.get("skipped") or [])
                    }
                    for lay_flat_body in linked_lay_flat:
                        name = str(getattr(lay_flat_body, "name", "") or "")
                        if name and name in linked_skipped:
                            continue
                        _geometry_flip_lay_flat(lay_flat_body)

        # Re-stamp boardType/color from the assembly source when Reverse /
        # MoveFeature left a sparse Lay Flat metadata shell.
        classification_restored = []
        for lay_flat_body in analyze_targets:
            lay_flat_key = metadata_inspector._body_key(lay_flat_body)
            source_body = source_for_lay_flat.get(lay_flat_key)
            if source_body is None:
                resolved, _fields, resolution = (
                    panel_body_resolver.resolve_source_bodies_for_lay_flat(
                        root,
                        lay_flat_body,
                        index=None,
                        allow_panel_id_fallback=False,
                    )
                )
                source_body = resolved[0] if len(resolved) == 1 else None
            if source_body is None:
                warnings.append(
                    "{}: exact source lineage unavailable for classification restore".format(
                        str(getattr(lay_flat_body, "name", "") or "body")
                    )
                )
                continue
            restore = nesting_lay_flat_fusion.sync_lay_flat_classification_from_source(
                lay_flat_body, source_body
            )
            if restore.get("ok") and restore.get("changed"):
                classification_restored.append(restore)
            elif not restore.get("ok"):
                warnings.append(
                    "{}: classification restore {}".format(
                        restore.get("bodyName") or "body",
                        restore.get("reason") or "failed",
                    )
                )

        analyze_summary = {
            "analyzedCount": 0,
            "skippedFreshCount": 0,
            "failedCount": 0,
            "bodyCount": 0,
            "failed": [],
        }
        if ok and analyze_targets:
            try:
                analyze_result = nesting_lay_flat_analyze.analyze_lay_flat_bodies(
                    analyze_targets,
                    force=True,
                    wait_callback=_pump_fusion_events,
                )
                analyze_summary = {
                    "analyzedCount": int(analyze_result.get("analyzedCount") or 0),
                    "skippedFreshCount": int(
                        analyze_result.get("skippedFreshCount") or 0
                    ),
                    "failedCount": int(analyze_result.get("failedCount") or 0),
                    "bodyCount": int(analyze_result.get("bodyCount") or 0),
                    "failed": list(analyze_result.get("failed") or [])[:40],
                }
                warnings = warnings + list(analyze_result.get("warnings") or [])
            except Exception as ex:
                warnings.append("Analyze after reverse failed: {}".format(ex))
                analyze_summary["failedCount"] = len(analyze_targets)
                analyze_summary["bodyCount"] = len(analyze_targets)
        elif ok and (updated_count or source_updated_count):
            warnings.append(
                "Reversed roles but no LAY_FLAT body found to flip/Analyze. "
                "Run Lay Flat first, then Reverse again."
            )

        skipped_count = (
            int(primary.get("skippedCount") or 0)
            + len(source_skipped)
            + len(geometry_failed)
        )
        message = (
            "Reverse milling face: flipped {} selected · {} source · "
            "geometry {} · skipped {}."
            .format(
                updated_count,
                source_updated_count,
                len(geometry_flipped),
                skipped_count,
            )
        )
        if ok:
            message += " Analyze: built {} · failed {} / {}.".format(
                int(analyze_summary.get("analyzedCount") or 0),
                int(analyze_summary.get("failedCount") or 0),
                int(analyze_summary.get("bodyCount") or 0),
            )
            if classification_restored:
                message += " Restored tags on {} body(ies).".format(
                    len(classification_restored)
                )
            if int(analyze_summary.get("failedCount") or 0) or geometry_failed:
                ok = False
        return "panelAttributesResult", {
            "ok": ok,
            "action": "reverseMillingFace",
            "bodyCount": len(bodies),
            "updatedCount": updated_count,
            "sourceUpdatedCount": source_updated_count,
            "geometryFlippedCount": len(geometry_flipped),
            "geometryFailedCount": len(geometry_failed),
            "classificationRestoredCount": len(classification_restored),
            "skippedCount": skipped_count,
            "analyzedCount": int(analyze_summary.get("analyzedCount") or 0),
            "analyzeFailedCount": int(analyze_summary.get("failedCount") or 0),
            "analyzeBodyCount": int(analyze_summary.get("bodyCount") or 0),
            "analyzeFailed": analyze_summary.get("failed") or [],
            "geometryFlipped": geometry_flipped[:40],
            "geometryFailed": geometry_failed[:40],
            "classificationRestored": classification_restored[:40],
            "updated": primary.get("updated") or [],
            "sourceUpdated": source_updated[:40],
            "skipped": ((primary.get("skipped") or []) + source_skipped)[:40],
            "warnings": warnings[:40],
            "errors": [] if ok else [message if (skipped_count or analyze_summary.get("failedCount")) else "No milling face was flipped."],
            "message": message,
        }

    def rotate_grain_90(self, _payload, _palette):
        """Swap grainAlongMm 90° (横↔竖) on the selected pair only.

        LAY_FLAT selection → write that copy + its exact original.
        Original selection → write that body + matching LAY_FLAT copy(ies).
        Does not scan/resolve every LAY_FLAT board in the design.
        """
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "rotateGrain90",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "rotateGrain90",
                "errors": ["Select a body or face first (not a whole assembly)."],
            }

        bodies = []
        warnings = []
        seen = set()
        ignored_bulk = 0
        for entity in selected_entities:
            kind = metadata_inspector._entity_kind(entity)
            if kind not in ("face", "body", "edge"):
                ignored_bulk += 1
                continue
            body, _source = metadata_inspector._selection_owner_body(entity)
            if not body:
                warnings.append("Could not resolve body from selected {}.".format(kind))
                continue
            if metadata_inspector._is_assembly_zone(body):
                warnings.append("Skipped work-zone helper body.")
                continue
            if metadata_inspector._is_nested_instance(body) and not (
                metadata_inspector._is_lay_flat_workpiece(body)
            ):
                warnings.append("Skipped Nesting layout copy (not Lay Flat).")
                continue
            key = metadata_inspector._body_key(body)
            if key in seen:
                continue
            seen.add(key)
            bodies.append(body)

        if ignored_bulk and not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "rotateGrain90",
                "errors": [
                    "Select a panel body or face. Whole assemblies are ignored "
                    "so this stays fast (O(selection), not O(all boards))."
                ],
                "warnings": warnings[:20],
            }
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "rotateGrain90",
                "errors": ["No solid panel body found under the current selection."],
                "warnings": warnings[:20],
            }
        if ignored_bulk:
            warnings.append(
                "Ignored {} assembly/component pick(s); only face/body/edge are rotated."
                .format(ignored_bulk)
            )

        updated = []
        source_updated = []
        skipped = []
        source_for_lay_flat = {}
        written_keys = set()
        paired_lay_flats = []

        def _write_grain(body, grain_mm, dest):
            key = metadata_inspector._body_key(body)
            if key in written_keys:
                return True
            result, error = _write_grain_along_on_body(body, grain_mm)
            name = str(getattr(body, "name", "") or "") or "body"
            if error:
                skipped.append({"bodyName": name, "reason": str(error)})
                return False
            written_keys.add(key)
            dest.append({
                "bodyName": name,
                "grainAlongMm": grain_mm,
                "changed": bool((result or {}).get("changed")),
            })
            return True

        for body in bodies:
            name = str(getattr(body, "name", "") or "") or "body"
            is_lay_flat = False
            try:
                is_lay_flat = bool(metadata_inspector._is_lay_flat_workpiece(body))
            except Exception:
                is_lay_flat = False

            source_body = None
            lay_flat_targets = []
            if is_lay_flat:
                canonical_ref = panel_source_ref.from_lay_flat_body(body)
                lineage_key = panel_source_ref.key(canonical_ref)
                if not lineage_key:
                    skipped.append({
                        "bodyName": name,
                        "reason": "missing exact source lineage",
                    })
                    continue
                resolved, _fields, resolution = (
                    panel_body_resolver.resolve_source_bodies_for_lay_flat(
                        root,
                        body,
                        index=None,
                        allow_panel_id_fallback=False,
                    )
                )
                if len(resolved) != 1:
                    skipped.append({
                        "bodyName": name,
                        "sourceKey": lineage_key,
                        "reason": "exact source lineage did not resolve ({})".format(
                            resolution or "none"
                        ),
                    })
                    continue
                source_body = resolved[0]
                lay_flat_targets = [body]
                source_for_lay_flat[metadata_inspector._body_key(body)] = source_body
            else:
                source_body = body
                lay_flat_targets = list(
                    panel_body_resolver.find_lay_flat_bodies_for_source(root, body)
                )
                for lay_flat_body in lay_flat_targets:
                    source_for_lay_flat[
                        metadata_inspector._body_key(lay_flat_body)
                    ] = source_body
                if not lay_flat_targets:
                    warnings.append(
                        "{}: no matching LAY_FLAT copy (run Lay Flat first)."
                        .format(name)
                    )

            measure_body = source_body if source_body is not None else body
            current, read_error = _read_grain_along_from_body(measure_body)
            if (not current) and source_body is not None and source_body is not body:
                current, read_error = _read_grain_along_from_body(body)
            if read_error and not current:
                skipped.append({"bodyName": name, "reason": str(read_error)})
                continue
            if current == "":
                skipped.append({
                    "bodyName": name,
                    "reason": "No grainAlongMm to rotate 90°. Set wood grain in Tag Edit first.",
                })
                continue

            try:
                dx, dy, dz = grain_direction.body_bbox_spans_mm(measure_body)
                new_mm = grain_direction.swapped_grain_along_mm(dx, dy, dz, current)
            except ValueError as ex:
                skipped.append({"bodyName": name, "reason": str(ex)})
                continue

            if abs(float(new_mm) - float(current)) <= 1e-3:
                warnings.append(
                    "{}: square face (both edges {} mm) — grain 90° is a no-op."
                    .format(name, current)
                )
                skipped.append({
                    "bodyName": name,
                    "reason": "square face ({} mm)".format(current),
                    "grainAlongMm": current,
                })
                continue

            if is_lay_flat:
                _write_grain(source_body, new_mm, source_updated)
                _write_grain(body, new_mm, updated)
            else:
                _write_grain(body, new_mm, updated)
                for lay_flat_body in lay_flat_targets:
                    _write_grain(lay_flat_body, new_mm, updated)
            paired_lay_flats.extend(lay_flat_targets)

        ok = bool(updated or source_updated)

        geometry_rotated = []
        geometry_failed = []
        analyze_targets = []
        analyze_seen = set()

        def _queue_analyze(body):
            if body is None:
                return
            key = metadata_inspector._body_key(body)
            if key in analyze_seen:
                return
            analyze_seen.add(key)
            analyze_targets.append(body)

        def _geometry_rotate_lay_flat(body):
            result = nesting_lay_flat_fusion.rotate_lay_flat_body_in_plane(
                body, degrees=-90.0
            )
            if result.get("ok"):
                geometry_rotated.append(result)
                _queue_analyze(body)
            else:
                geometry_failed.append(result)
                warnings.append(
                    "{}: {}".format(
                        result.get("bodyName") or "body",
                        result.get("reason") or "grain_rotate_failed",
                    )
                )

        if ok:
            for lay_flat_body in paired_lay_flats:
                _geometry_rotate_lay_flat(lay_flat_body)

        classification_restored = []
        for lay_flat_body in analyze_targets:
            lay_flat_key = metadata_inspector._body_key(lay_flat_body)
            source_body = source_for_lay_flat.get(lay_flat_key)
            if source_body is None:
                resolved, _fields, _resolution = (
                    panel_body_resolver.resolve_source_bodies_for_lay_flat(
                        root,
                        lay_flat_body,
                        index=None,
                        allow_panel_id_fallback=False,
                    )
                )
                source_body = resolved[0] if len(resolved) == 1 else None
            if source_body is None:
                warnings.append(
                    "{}: exact source lineage unavailable for classification restore".format(
                        str(getattr(lay_flat_body, "name", "") or "body")
                    )
                )
                continue
            restore = nesting_lay_flat_fusion.sync_lay_flat_classification_from_source(
                lay_flat_body, source_body
            )
            if restore.get("ok") and restore.get("changed"):
                classification_restored.append(restore)
            elif not restore.get("ok"):
                warnings.append(
                    "{}: classification restore {}".format(
                        restore.get("bodyName") or "body",
                        restore.get("reason") or "failed",
                    )
                )

        analyze_summary = {
            "analyzedCount": 0,
            "skippedFreshCount": 0,
            "failedCount": 0,
            "bodyCount": 0,
            "failed": [],
        }
        if ok and analyze_targets:
            try:
                analyze_result = nesting_lay_flat_analyze.analyze_lay_flat_bodies(
                    analyze_targets,
                    force=True,
                    wait_callback=_pump_fusion_events,
                )
                analyze_summary = {
                    "analyzedCount": int(analyze_result.get("analyzedCount") or 0),
                    "skippedFreshCount": int(
                        analyze_result.get("skippedFreshCount") or 0
                    ),
                    "failedCount": int(analyze_result.get("failedCount") or 0),
                    "bodyCount": int(analyze_result.get("bodyCount") or 0),
                    "failed": list(analyze_result.get("failed") or [])[:40],
                }
                warnings = warnings + list(analyze_result.get("warnings") or [])
            except Exception as ex:
                warnings.append("Analyze after grain rotate failed: {}".format(ex))
                analyze_summary["failedCount"] = len(analyze_targets)
                analyze_summary["bodyCount"] = len(analyze_targets)
        elif ok and not analyze_targets:
            warnings.append(
                "Wrote grainAlongMm but no LAY_FLAT body found to rotate/Analyze. "
                "Run Lay Flat first, then rotate grain again."
            )

        skipped_count = len(skipped) + len(geometry_failed)
        message = (
            "Rotate grain 90°: wrote {} selected · {} source · "
            "geometry {} · skipped {}."
            .format(
                len(updated),
                len(source_updated),
                len(geometry_rotated),
                skipped_count,
            )
        )
        if ok:
            message += " Analyze: built {} · failed {} / {}.".format(
                int(analyze_summary.get("analyzedCount") or 0),
                int(analyze_summary.get("failedCount") or 0),
                int(analyze_summary.get("bodyCount") or 0),
            )
            if classification_restored:
                message += " Restored tags on {} body(ies).".format(
                    len(classification_restored)
                )
            if int(analyze_summary.get("failedCount") or 0) or geometry_failed:
                ok = False
        return "panelAttributesResult", {
            "ok": ok,
            "action": "rotateGrain90",
            "bodyCount": len(bodies),
            "updatedCount": len(updated),
            "sourceUpdatedCount": len(source_updated),
            "geometryRotatedCount": len(geometry_rotated),
            "geometryFailedCount": len(geometry_failed),
            "classificationRestoredCount": len(classification_restored),
            "skippedCount": skipped_count,
            "analyzedCount": int(analyze_summary.get("analyzedCount") or 0),
            "analyzeFailedCount": int(analyze_summary.get("failedCount") or 0),
            "analyzeBodyCount": int(analyze_summary.get("bodyCount") or 0),
            "analyzeFailed": analyze_summary.get("failed") or [],
            "geometryRotated": geometry_rotated[:40],
            "geometryFailed": geometry_failed[:40],
            "classificationRestored": classification_restored[:40],
            "updated": updated[:40],
            "sourceUpdated": source_updated[:40],
            "skipped": skipped[:40],
            "warnings": warnings[:40],
            "errors": [] if ok else [
                message if (skipped_count or analyze_summary.get("failedCount"))
                else "No wood grain was rotated 90°."
            ],
            "message": message,
        }

    def make_selected_faces_colour(self, _payload, _palette):
        """Fast explicit override: selected broad face becomes the colour side.

        Only face selections are accepted. Each selected body is classified
        once; no component expansion, hinge detection, or slot extraction.
        """
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "makeSelectedFacesColour",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        selected_faces = [
            entity for entity in selected_entities
            if metadata_inspector._entity_kind(entity) == "face"
        ]
        if not selected_faces:
            return "panelAttributesResult", {
                "ok": False,
                "action": "makeSelectedFacesColour",
                "errors": ["Select one or more panel faces first."],
            }

        entries_by_key = {}
        warnings = []
        for face in selected_faces:
            body, _source = metadata_inspector._selection_owner_body(face)
            if not body:
                warnings.append("Could not resolve body from a selected face.")
                continue
            if metadata_inspector._is_assembly_zone(body):
                warnings.append("Skipped work-zone helper body.")
                continue
            if metadata_inspector._is_nested_instance(body):
                warnings.append("Skipped nested-instance copy (nesting output).")
                continue
            key = metadata_inspector._body_key(body)
            entry = entries_by_key.get(key)
            if entry is None:
                metadata, read_error = tag_metadata_editor._read_body_metadata_raw(body)
                if read_error:
                    warnings.append(
                        "{}: metadata read failed ({}).".format(
                            getattr(body, "name", "body"), read_error
                        )
                    )
                    metadata = {}
                defaults = (
                    metadata.get("defaultAttributes")
                    if isinstance(metadata, dict)
                    and isinstance(metadata.get("defaultAttributes"), dict)
                    else {}
                )
                registry = (
                    metadata.get("faceRegistry")
                    if isinstance(metadata, dict)
                    and isinstance(metadata.get("faceRegistry"), dict)
                    else {}
                )
                surface_mode = tag_metadata_editor.normalize_surface_mode_enum(
                    defaults.get("surfaceMode")
                    or registry.get("surfaceMode")
                    or (metadata.get("surfaceMode") if isinstance(metadata, dict) else "")
                )
                entry = {
                    "body": body,
                    "faces": [],
                    "surfaceMode": surface_mode,
                }
                entries_by_key[key] = entry
            entry["faces"].append(face)

        entries = list(entries_by_key.values())
        result = milling_surface_propagation.make_selected_faces_colour(
            entries,
            write_roles=lambda body, milling, colour: (
                tag_metadata_editor.apply_surface_milling_roles(
                    body,
                    milling,
                    colour,
                    source="manual",
                    lock=False,
                    force=True,
                )
            ),
        )
        warnings.extend(result.get("warnings") or [])
        return "panelAttributesResult", {
            "ok": bool(result.get("ok")),
            "action": "makeSelectedFacesColour",
            "bodyCount": len(entries),
            "selectedFaceCount": len(selected_faces),
            "updatedCount": int(result.get("updatedCount") or 0),
            "doubleSidedCount": int(result.get("doubleSidedCount") or 0),
            "skippedCount": int(result.get("skippedCount") or 0),
            "updated": result.get("updated") or [],
            "doubleSided": result.get("doubleSided") or [],
            "skipped": (result.get("skipped") or [])[:40],
            "warnings": warnings[:40],
            "errors": [] if result.get("ok") else [
                result.get("message") or "No selected face was changed."
            ],
            "message": result.get("message") or "",
        }

    def analyze_milling_surfaces(self, _payload, _palette):
        """Geometric milling-surface analysis on every selected body (all board types)."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "analyzeMillingSurfaces",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "analyzeMillingSurfaces",
                "errors": ["Select assemblies, components, or bodies first."],
            }

        bodies, expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root
        )
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "analyzeMillingSurfaces",
                "errors": ["No solid panel bodies found under the current selection."],
                "warnings": list(expand_warnings or [])[:20],
            }

        result = milling_surface_propagation.analyze_milling_surfaces(
            bodies,
            write_pair=lambda body, face_a, role_a, face_b, role_b, source="geometry": (
                tag_metadata_editor.apply_surface_roles(
                    body,
                    face_a,
                    role_a,
                    face_b,
                    role_b,
                    source=source,
                    lock=False,
                )
            ),
        )
        counts = result.get("sourceCounts") or {}
        skipped_items = result.get("skipped") or []
        locked_count = sum(
            1 for item in skipped_items
            if "manual" in str(item.get("reason") or "").lower()
            and "lock" in str(item.get("reason") or "").lower()
        )
        warnings = list(expand_warnings or []) + list(result.get("warnings") or [])
        return "panelAttributesResult", {
            "ok": bool(result.get("ok")),
            "action": "analyzeMillingSurfaces",
            "bodyCount": len(bodies),
            "updatedCount": int(result.get("updatedCount") or 0),
            "skippedCount": int(result.get("skippedCount") or 0),
            "hingeCount": int(counts.get("hinge_cups") or 0),
            "halfSlotCount": int(counts.get("half_slot") or 0),
            "eitherCount": int(counts.get("either") or 0),
            "lockedCount": locked_count,
            "updated": (result.get("updated") or [])[:200],
            "skipped": skipped_items[:200],
            "warnings": warnings[:40],
            "errors": [] if result.get("ok") else [result.get("message") or "No panel was analyzed."],
            "message": result.get("message") or "",
        }

    def select_milling_faces(self, _payload, _palette):
        """Select all faces stored as MILLING under the current selection."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectMillingFaces",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectMillingFaces",
                "errors": ["Select assemblies, components, or bodies first."],
            }

        bodies, expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root
        )
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectMillingFaces",
                "errors": ["No solid panel bodies found under the current selection."],
                "warnings": list(expand_warnings or [])[:20],
            }

        collected = milling_surface_propagation.collect_milling_faces(bodies)
        faces = collected.get("faces") or []
        either_picked = collected.get("eitherPicked") or []
        skipped = collected.get("skipped") or []
        shared_mirror = collected.get("sharedMirrorOccurrence") or []
        no_role = len(skipped)
        selected_count, select_failures = self._select_faces_and_fit(faces)
        warnings = list(expand_warnings or []) + list(collected.get("warnings") or [])
        warnings.extend(select_failures or [])
        if shared_mirror:
            warnings.append(
                "{} mirrored occurrence(s): Select shows the shared native MILLING "
                "face; Nesting restores opposite chirality on flatten."
                .format(len(shared_mirror))
            )
        if faces and selected_count == 0:
            warnings.append(
                "Resolved {} milling faces but Fusion selection.add failed "
                "(nested OHC/GT faces need occurrence proxies)."
                .format(len(faces))
            )
            message = (
                "Found {} milling face(s) but could not select them in Fusion "
                "(EITHER stand-ins: {}, without role: {}). {}"
                .format(
                    len(faces),
                    len(either_picked),
                    no_role,
                    (select_failures or ["Try Stop→Run plugin and retry."])[0],
                )
            )
        else:
            if selected_count < len(faces):
                warnings.append("Selected {} of {} milling faces.".format(selected_count, len(faces)))
            message = (
                "Selected {} milling face(s) across {} bodies "
                "(EITHER stand-ins: {}, without role: {}, mirrored occurrences: {})."
                .format(
                    selected_count,
                    len(bodies),
                    len(either_picked),
                    no_role,
                    len(shared_mirror),
                )
            )
        return "panelAttributesResult", {
            "ok": selected_count > 0,
            "action": "selectMillingFaces",
            "selectedCount": selected_count,
            "resolvedFaceCount": len(faces),
            "eitherPickedCount": len(either_picked),
            "sharedMirrorOccurrenceCount": len(shared_mirror),
            "sharedMirrorOccurrence": shared_mirror[:40],
            "bodyCount": len(bodies),
            "skippedNoMillingCount": no_role,
            "skipped": skipped[:40],
            "selectFailures": list(select_failures or [])[:20],
            "warnings": warnings[:40],
            "errors": [] if selected_count else (
                [
                    "Found {} milling face(s) but Fusion could not select them. {}"
                    .format(len(faces), (select_failures or ["nested assembly proxy failed"])[0])
                ]
                if faces
                else ["No MILLING/EITHER faces found. Run Analyze Milling Surfaces first."]
            ),
            "message": message,
        }

    def diagnose_hinge_faces(self, _payload, _palette):
        """Read-only hinge-face diagnostics for the palette debug card."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "diagnoseHingeFaces",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "diagnoseHingeFaces",
                "errors": ["Select an assembly, component, or body first."],
            }

        bodies, expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root
        )
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "diagnoseHingeFaces",
                "errors": ["No solid panel bodies found under the current selection."],
                "warnings": list(expand_warnings or [])[:20],
            }

        code_info = {}
        try:
            import inspect as _inspect
            import panel_geometry as _pg
            code_info["panelGeometryFile"] = str(getattr(_pg, "__file__", "") or "")
            params = list(_inspect.signature(_pg._half_feature_open_surface).parameters)
            code_info["openSurfaceParams"] = params
            code_info["topologyFixLoaded"] = bool(params and params[0] == "floor_face")
        except Exception as ex:
            code_info["error"] = str(ex)

        reports = milling_surface_propagation.diagnose_hinge_faces(bodies[:60])
        mismatches = [r for r in reports if r.get("rolesMatchDetection") is False]
        with_cups = [r for r in reports if (r.get("hingeCupCount") or 0) > 0]
        summary = "Diagnosed {} bodies: {} with hinge cups, {} where stored MILLING disagrees with detection.".format(
            len(reports), len(with_cups), len(mismatches)
        )
        return "panelAttributesResult", {
            "ok": True,
            "action": "diagnoseHingeFaces",
            "bodyCount": len(bodies),
            "reportCount": len(reports),
            "hingeBodyCount": len(with_cups),
            "mismatchCount": len(mismatches),
            "codeInfo": code_info,
            "reports": reports,
            "warnings": list(expand_warnings or [])[:20],
            "message": summary,
        }

    OBSERVATION_POINT_NAME = "UC_ObservationPoint"

    def _resolve_observation_point(self, payload, bodies):
        """Return (point_mm, source, error). Manual point wins over auto."""
        mode = str((payload or {}).get("pointMode") or "auto").strip().lower()
        manual = (payload or {}).get("point")
        if mode == "manual":
            if isinstance(manual, dict):
                try:
                    return (
                        [float(manual.get("x")), float(manual.get("y")), float(manual.get("z"))],
                        "manual",
                        None,
                    )
                except Exception:
                    pass
            return None, "manual", "Manual mode selected but no valid point set. Use Set Observation Point first."
        point = door_face_orientation.observation_point_from_bodies(bodies)
        if point is None:
            return None, "auto", "Could not compute the centre of the selection."
        return point, "auto", None

    def orient_door_faces_from_view_point(self, payload, _palette):
        """Auto-orient door panel faces: machining first, then two-vote model."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "orientDoorFaces",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "orientDoorFaces",
                "errors": ["Select assemblies, components, or bodies first."],
            }

        bodies, expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root
        )
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "orientDoorFaces",
                "errors": ["No solid panel bodies found under the current selection."],
                "warnings": list(expand_warnings or [])[:20],
            }

        observation_point, point_source, point_error = self._resolve_observation_point(payload, bodies)
        if point_error:
            return "panelAttributesResult", {
                "ok": False,
                "action": "orientDoorFaces",
                "errors": [point_error],
            }

        entries = []
        skipped_non_door = 0
        for body in bodies:
            if not metadata_inspector.body_looks_like_door(body):
                skipped_non_door += 1
                continue
            entries.append({
                "body": body,
                "assemblyCenter": door_face_orientation.assembly_center_for_body(body),
            })

        if not entries:
            return "panelAttributesResult", {
                "ok": False,
                "action": "orientDoorFaces",
                "errors": ["No door panels found in the selection."],
                "skippedNonDoorCount": skipped_non_door,
                "warnings": list(expand_warnings or [])[:20],
            }

        def _write_either(body, face_a, face_b, source="assembly"):
            tag_metadata_editor.apply_surface_roles(
                body,
                face_a,
                "EITHER",
                face_b,
                "EITHER",
                source=source,
                lock=False,
            )

        def _write_oriented(body, milling_face, non_milling_face, source="assembly"):
            tag_metadata_editor.apply_surface_milling_roles(
                body,
                milling_face,
                non_milling_face,
                source=source,
                lock=False,
            )

        result = door_face_orientation.orient_door_faces(
            entries,
            observation_point,
            write_roles=_write_oriented,
            write_either=_write_either,
        )

        updated = result.get("updated") or []
        machining = result.get("machining") or []
        either = result.get("either") or []
        conflicts = result.get("conflicts") or []
        skipped = result.get("skipped") or []
        agree = sum(1 for item in updated if item.get("votes") == "both")
        single = len(updated) - agree
        warnings = list(expand_warnings or []) + list(result.get("warnings") or [])

        summary_bits = [
            "updated {} (both votes {}, single vote {})".format(len(updated), agree, single),
            "machining {}".format(len(machining)),
            "EITHER {}".format(len(either)),
        ]
        if conflicts:
            summary_bits.append("conflicts {}".format(len(conflicts)))
        if skipped_non_door or skipped:
            summary_bits.append("skipped {}".format(skipped_non_door + len(skipped)))

        return "panelAttributesResult", {
            "ok": bool(updated or machining or either),
            "action": "orientDoorFaces",
            "observationPoint": {
                "x": observation_point[0],
                "y": observation_point[1],
                "z": observation_point[2],
            },
            "pointSource": point_source,
            "doorCount": len(entries),
            "updatedCount": len(updated),
            "agreeCount": agree,
            "singleVoteCount": single,
            "machiningCount": len(machining),
            "eitherCount": len(either),
            "conflictCount": len(conflicts),
            "skippedNonDoorCount": skipped_non_door,
            "skippedErrorCount": len(skipped),
            "updated": updated[:40],
            "machining": machining[:40],
            "conflicts": conflicts[:40],
            "skipped": skipped[:20],
            "warnings": warnings[:40],
            "errors": [] if (updated or machining or either) else ["No door panel could be oriented."],
            "message": "Orient door faces: {}.".format(", ".join(summary_bits)),
        }

    def capture_observation_point(self, _payload, _palette):
        """Use the current Fusion selection as the manual observation point."""
        selected = self._selected_entities()
        if not selected:
            return "panelAttributesResult", {
                "ok": False,
                "action": "captureObservationPoint",
                "errors": ["Select a point, vertex, face, or body to use as the observation point."],
            }

        point_mm = None
        source = ""
        for entity in selected:
            # Point-like entities (vertex, sketch point, construction point).
            try:
                geometry = getattr(entity, "geometry", None)
                if geometry is not None and hasattr(geometry, "x"):
                    point_mm = [geometry.x * 10.0, geometry.y * 10.0, geometry.z * 10.0]
                    source = "point"
                    break
            except Exception:
                pass
            # Face: representative point on the face.
            try:
                point_on_face = getattr(entity, "pointOnFace", None)
                if point_on_face is not None:
                    point_mm = [point_on_face.x * 10.0, point_on_face.y * 10.0, point_on_face.z * 10.0]
                    source = "face"
                    break
            except Exception:
                pass
            # Body / anything with a bounding box: use its centre.
            try:
                bbox = getattr(entity, "boundingBox", None)
                if bbox is not None:
                    min_pt = bbox.minPoint
                    max_pt = bbox.maxPoint
                    point_mm = [
                        (min_pt.x + max_pt.x) * 5.0,
                        (min_pt.y + max_pt.y) * 5.0,
                        (min_pt.z + max_pt.z) * 5.0,
                    ]
                    source = "boundingBox"
                    break
            except Exception:
                pass

        if point_mm is None:
            return "panelAttributesResult", {
                "ok": False,
                "action": "captureObservationPoint",
                "errors": ["Could not derive a point from the selection."],
            }

        return "panelAttributesResult", {
            "ok": True,
            "action": "captureObservationPoint",
            "point": {"x": point_mm[0], "y": point_mm[1], "z": point_mm[2]},
            "source": source,
            "message": "Observation point set to ({:.1f}, {:.1f}, {:.1f}) mm.".format(*point_mm),
        }

    def preview_observation_point(self, payload, _palette):
        """Show the observation point in Fusion as a named construction point."""
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "previewObservationPoint",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        bodies, _expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root
        ) if selected_entities else ([], [])

        observation_point, point_source, point_error = self._resolve_observation_point(payload, bodies)
        if point_error:
            return "panelAttributesResult", {
                "ok": False,
                "action": "previewObservationPoint",
                "errors": [point_error],
            }

        created = False
        warning = ""
        try:
            construction_points = root.constructionPoints
            # Remove a stale preview point first.
            for index in range(construction_points.count - 1, -1, -1):
                item = construction_points.item(index)
                if str(getattr(item, "name", "") or "") == self.OBSERVATION_POINT_NAME:
                    item.deleteMe()
            point_input = construction_points.createInput()
            point_cm = adsk.core.Point3D.create(
                observation_point[0] / 10.0,
                observation_point[1] / 10.0,
                observation_point[2] / 10.0,
            )
            point_input.setByPoint(point_cm)
            created_point = construction_points.add(point_input)
            if created_point:
                created_point.name = self.OBSERVATION_POINT_NAME
                created = True
        except Exception as ex:
            warning = "Could not create a preview construction point: {}".format(ex)

        return "panelAttributesResult", {
            "ok": True,
            "action": "previewObservationPoint",
            "point": {
                "x": observation_point[0],
                "y": observation_point[1],
                "z": observation_point[2],
            },
            "pointSource": point_source,
            "previewCreated": created,
            "warnings": [warning] if warning else [],
            "message": "Observation point at ({:.1f}, {:.1f}, {:.1f}) mm{}.".format(
                observation_point[0], observation_point[1], observation_point[2],
                "" if created else " (marker not created; coordinates only)",
            ),
        }

    def select_door_colour_faces(self, _payload, _palette):
        """Select NON_MILLING colour faces of door panels only under selection.

        Carcass / partition boards are ignored. Colour face is never MILLING.
        Door boards marked EITHER contribute one random face as a stand-in.
        """
        root = self.fusion.get_root_component()
        if not root:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectDoorColourFaces",
                "errors": ["No active Fusion design."],
            }

        selected_entities = self._selected_entities()
        if not selected_entities:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectDoorColourFaces",
                "errors": ["Select assemblies, components, or bodies first."],
            }

        bodies, expand_warnings = metadata_inspector.bodies_from_selected_entities(
            selected_entities, root
        )
        if not bodies:
            return "panelAttributesResult", {
                "ok": False,
                "action": "selectDoorColourFaces",
                "errors": ["No solid panel bodies found under the current selection."],
                "warnings": list(expand_warnings or [])[:20],
            }

        collected = milling_surface_propagation.collect_colour_faces(
            bodies,
            is_door_body=metadata_inspector.body_looks_like_door,
        )
        faces = collected.get("faces") or []
        either_picked = collected.get("eitherPicked") or []
        skipped = collected.get("skipped") or []
        skipped_non_door = sum(1 for item in skipped if item.get("reason") == "not_door")
        skipped_no_colour = len(skipped) - skipped_non_door
        selected_count, select_failures = self._select_faces_and_fit(faces)
        warnings = list(expand_warnings or []) + list(collected.get("warnings") or [])
        warnings.extend(select_failures or [])
        if faces and selected_count == 0:
            warnings.append(
                "Resolved {} door colour faces but Fusion selection.add failed "
                "(nested OHC/GT faces need occurrence proxies)."
                .format(len(faces))
            )
            message = (
                "Found {} door colour face(s) but could not select them in Fusion "
                "(EITHER stand-ins: {}, non-door ignored: {}, without colour role: {}). {}"
                .format(
                    len(faces),
                    len(either_picked),
                    skipped_non_door,
                    skipped_no_colour,
                    (select_failures or ["Try Stop→Run plugin and retry."])[0],
                )
            )
        else:
            if selected_count < len(faces):
                warnings.append("Selected {} of {} door colour faces.".format(selected_count, len(faces)))
            message = (
                "Selected {} door colour face(s) (NON_MILLING) across {} bodies "
                "(EITHER stand-ins: {}, non-door ignored: {}, without colour role: {})."
                .format(
                    selected_count,
                    len(bodies),
                    len(either_picked),
                    skipped_non_door,
                    skipped_no_colour,
                )
            )
        return "panelAttributesResult", {
            "ok": selected_count > 0,
            "action": "selectDoorColourFaces",
            "selectedCount": selected_count,
            "resolvedFaceCount": len(faces),
            "eitherPickedCount": len(either_picked),
            "bodyCount": len(bodies),
            "skippedNonDoorCount": skipped_non_door,
            "skippedNoColourCount": skipped_no_colour,
            "skipped": skipped[:40],
            "selectFailures": list(select_failures or [])[:20],
            "warnings": warnings[:40],
            "errors": [] if selected_count else (
                [
                    "Found {} door colour face(s) but Fusion could not select them. {}"
                    .format(len(faces), (select_failures or ["nested assembly proxy failed"])[0])
                ]
                if faces
                else [
                    "No door colour faces found. "
                    "Run Orient Door Faces / Analyze first, or selection has no doors."
                ]
            ),
            "message": message,
        }
