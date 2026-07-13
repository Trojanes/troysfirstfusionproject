try:
    import adsk.core  # noqa: F401  (only present inside Fusion)
except ImportError:
    pass

from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR


def _body_volume(body):
    try:
        volume = getattr(body, "volume", None)
        if volume is not None and volume > 0:
            return float(volume)
    except Exception:
        pass
    try:
        bbox = body.boundingBox
        if not bbox:
            return 0.0
        min_pt = bbox.minPoint
        max_pt = bbox.maxPoint
        return abs((max_pt.x - min_pt.x) * (max_pt.y - min_pt.y) * (max_pt.z - min_pt.z))
    except Exception:
        return 0.0


def _is_solid_body(body):
    try:
        if not body or not body.isSolid:
            return False
        if hasattr(body, "isVisible") and not body.isVisible:
            return False
        return True
    except Exception:
        return False


def list_solid_bodies(component):
    bodies = []
    if not component:
        return bodies
    try:
        for index in range(component.bRepBodies.count):
            body = component.bRepBodies.item(index)
            if _is_solid_body(body):
                bodies.append(body)
    except Exception:
        pass
    return bodies


def resolve_main_body(component):
    bodies = list_solid_bodies(component)
    warning = None
    if not bodies:
        return None, "No solid body found"
    if len(bodies) == 1:
        return bodies[0], None
    bodies.sort(key=_body_volume, reverse=True)
    warning = "Multiple bodies detected; largest solid body selected."
    return bodies[0], warning


def _parent_component(body):
    for attr_name in ("parentComponent", "component"):
        try:
            component = getattr(body, attr_name)
        except Exception:
            component = None
        if component:
            return component
    return None


def read_body_panel_id(body):
    if not body:
        return ""
    try:
        attrs = body.attributes
        attr = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR) if attrs else None
        return str(attr.value or "").strip() if attr and attr.value else ""
    except Exception:
        return ""


def resolve_occurrence_path_for_component(root_component, component):
    if not root_component or not component:
        return []

    try:
        if component == root_component:
            return []
    except Exception:
        pass

    def walk(current, path):
        try:
            if current == component:
                return path
        except Exception:
            pass
        try:
            occurrences = current.occurrences
            count = occurrences.count if occurrences else 0
        except Exception:
            return None
        for index in range(count):
            child_component = occurrences.item(index).component
            found = walk(child_component, path + [index])
            if found is not None:
                return found
        return None

    resolved = walk(root_component, [])
    return resolved if resolved is not None else []


def resolve_occurrence_path_for_body(root_component, body):
    component = _parent_component(body)
    if not component:
        return []
    return resolve_occurrence_path_for_component(root_component, component)


def find_component_by_path(root_component, occurrence_path):
    component = root_component
    for index in occurrence_path or []:
        try:
            if not component.occurrences or index >= component.occurrences.count:
                return None
            component = component.occurrences.item(index).component
        except Exception:
            return None
    return component


def body_by_name(component, body_name):
    target_name = str(body_name or "").strip()
    if not component or not target_name:
        return None
    for body in list_solid_bodies(component):
        if str(getattr(body, "name", "") or "") == target_name:
            return body
    return None


def _safe_entity_token(entity):
    if not entity:
        return ""
    try:
        return str(getattr(entity, "entityToken", "") or "").strip()
    except Exception:
        return ""


def body_matches_record(body, body_record):
    if not body or not isinstance(body_record, dict):
        return False

    token = str(body_record.get("entityToken") or "").strip()
    body_token = _safe_entity_token(body)
    if token and body_token and token == body_token:
        return True

    body_name = str(body_record.get("bodyName") or "").strip()
    if body_name and str(getattr(body, "name", "") or "") != body_name:
        return False
    if not body_name:
        return False

    panel_id = str(body_record.get("panelId") or "").strip()
    if panel_id:
        return read_body_panel_id(body) == panel_id
    return True


def find_body_in_design(root_component, body_record):
    if not root_component or not isinstance(body_record, dict):
        return None

    token = str(body_record.get("entityToken") or "").strip()
    body_name = str(body_record.get("bodyName") or "").strip()
    panel_id = str(body_record.get("panelId") or "").strip()
    occurrence_path = body_record.get("occurrencePath") or []

    component = find_component_by_path(root_component, occurrence_path)
    if component and body_name:
        body = body_by_name(component, body_name)
        if body and body_matches_record(body, body_record):
            return body

    named_matches = []
    token_match = None

    def walk(component):
        nonlocal token_match
        for body in list_solid_bodies(component):
            body_token = _safe_entity_token(body)
            if token and body_token == token:
                token_match = body
                return
            if body_name and str(getattr(body, "name", "") or "") == body_name:
                named_matches.append(body)
        try:
            occurrences = component.occurrences
            count = occurrences.count if occurrences else 0
        except Exception:
            return
        for index in range(count):
            walk(occurrences.item(index).component)

    walk(root_component)
    if token_match:
        return token_match
    # Nested-instance copies (nesting layout output) duplicate the original's
    # panelId/name; write-backs must target the original whenever one exists.
    non_nested = [body for body in named_matches if not _is_nested_instance(body)]
    pool = non_nested or named_matches
    if panel_id:
        for body in pool:
            if read_body_panel_id(body) == panel_id:
                return body
    if len(pool) == 1:
        return pool[0]
    return None


def _is_nested_instance(body):
    try:
        attrs = body.attributes
        role = attrs.itemByName("UnifiedCabinet", "instanceRole")
        if role and str(role.value) == "nested":
            return True
        system_role = attrs.itemByName("UnifiedCabinet", "systemRole")
        return bool(
            system_role
            and str(system_role.value) == "nestingWorkpiece"
        )
    except Exception:
        return False
