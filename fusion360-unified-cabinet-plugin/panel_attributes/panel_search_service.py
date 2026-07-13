import adsk.core

from panel_body_resolver import list_solid_bodies, resolve_main_body
from panel_metadata_store import has_panel_metadata, read_panel_id, read_panel_metadata


def _panel_matches_query(metadata, component, body_names, query):
    terms = [term for term in str(query or "").strip().lower().split() if term]
    if not terms:
        return True

    searchable_parts = []
    if metadata and isinstance(metadata, dict):
        searchable_parts.extend(
            [
                metadata.get("panelId"),
                metadata.get("panelType"),
                metadata.get("doorColorSlot"),
            ]
        )
        tags = metadata.get("tags") or []
        if isinstance(tags, list):
            searchable_parts.extend(tags)
    searchable_parts.append(getattr(component, "name", ""))
    searchable_parts.extend(body_names)
    searchable_text = " ".join(str(part) for part in searchable_parts if part is not None).lower()
    return all(term in searchable_text for term in terms)


def _find_component_by_path(root_component, occurrence_path):
    component = root_component
    if not component:
        return None
    for index in occurrence_path or []:
        if not component.occurrences or index >= component.occurrences.count:
            return None
        occurrence = component.occurrences.item(index)
        component = occurrence.component
    return component


def _component_record(component, occurrence_path):
    metadata, parse_error = read_panel_metadata(component)
    if not has_panel_metadata(component) and metadata is None and not parse_error:
        return None

    body_names = [str(getattr(body, "name", "") or "") for body in list_solid_bodies(component)]
    main_body, body_warning = resolve_main_body(component)
    status = "Defined"
    if parse_error:
        status = "Invalid"
    elif metadata is None:
        status = "Invalid"

    panel_id = ""
    panel_type = ""
    tags = []
    door_color_slot = None
    if metadata and isinstance(metadata, dict):
        panel_id = str(metadata.get("panelId") or read_panel_id(component) or "")
        panel_type = str(metadata.get("panelType") or "")
        raw_tags = metadata.get("tags") or []
        tags = [str(tag) for tag in raw_tags] if isinstance(raw_tags, list) else []
        door_color_slot = metadata.get("doorColorSlot")

    record = {
        "componentName": str(getattr(component, "name", "") or ""),
        "bodyName": str(getattr(main_body, "name", "") or "") if main_body else "",
        "panelId": panel_id,
        "panelType": panel_type,
        "tags": tags,
        "doorColorSlot": door_color_slot,
        "status": status,
        "parseError": parse_error,
        "bodyWarning": body_warning,
        "occurrencePath": occurrence_path,
        "entityToken": None,
    }
    if main_body:
        try:
            record["entityToken"] = getattr(main_body, "entityToken", None)
        except Exception:
            record["entityToken"] = None
    return record


def _walk_occurrences(occurrences, parent_path, sink):
    for index in range(occurrences.count):
        occurrence = occurrences.item(index)
        path = parent_path + [index]
        component = occurrence.component
        record = _component_record(component, path)
        if record:
            sink.append(record)
        if component and component.occurrences and component.occurrences.count:
            _walk_occurrences(component.occurrences, path, sink)


def collect_defined_panels(root_component):
    panels = []
    if not root_component:
        return panels

    record = _component_record(root_component, [])
    if record:
        panels.append(record)

    if root_component.occurrences and root_component.occurrences.count:
        _walk_occurrences(root_component.occurrences, [], panels)
    return panels


def search_panels(root_component, query):
    panels = collect_defined_panels(root_component)
    matched = []
    for panel in panels:
        component = _find_component_by_path(root_component, panel.get("occurrencePath") or [])
        metadata, _parse_error = read_panel_metadata(component)
        body_names = []
        if component:
            body_names = [str(getattr(body, "name", "") or "") for body in list_solid_bodies(component)]
        if _panel_matches_query(metadata, component, body_names, query):
            matched.append(panel)
    return matched


def collect_all_tags(root_component):
    tags = set()
    for panel in collect_defined_panels(root_component):
        for tag in panel.get("tags") or []:
            text = str(tag).strip()
            if text:
                tags.add(text)
    return sorted(tags, key=lambda value: value.lower())


def resolve_panel_targets(root_component, panels):
    targets = []
    warnings = []
    for panel in panels or []:
        occurrence_path = panel.get("occurrencePath") or []
        component = _find_component_by_path(root_component, occurrence_path)
        if not component:
            warnings.append("Component not found for {}".format(panel.get("componentName") or "panel"))
            continue
        main_body, body_warning = resolve_main_body(component)
        if body_warning:
            warnings.append("{}: {}".format(panel.get("componentName") or "panel", body_warning))
        if main_body:
            # Build a root-context occurrence proxy so selection.add works for
            # nested assemblies (Fusion rejects nested non-root proxies).
            occurrence = None
            path = list(occurrence_path or [])
            if path and root_component:
                try:
                    occ = None
                    current = root_component
                    for index in path:
                        child = current.occurrences.item(index)
                        occ = child if occ is None else child.createForAssemblyContext(occ)
                        if occ is None:
                            break
                        current = child.component
                    occurrence = occ
                except Exception:
                    occurrence = None
            if occurrence is not None:
                try:
                    proxy = main_body.createForAssemblyContext(occurrence)
                    if proxy is not None:
                        main_body = proxy
                except Exception:
                    pass
            targets.append(
                {
                    "body": main_body,
                    "componentName": panel.get("componentName"),
                    "bodyName": str(getattr(main_body, "name", "") or ""),
                    "panelId": panel.get("panelId"),
                }
            )
        else:
            warnings.append("No selectable body for {}".format(panel.get("componentName") or "panel"))
    return targets, warnings
