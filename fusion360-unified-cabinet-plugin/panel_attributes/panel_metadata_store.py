import json

from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR, PANEL_METADATA_ATTR


def has_panel_metadata(component):
    if not component:
        return False
    try:
        attrs = component.attributes
        return bool(attrs and attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR))
    except Exception:
        return False


def read_panel_metadata(component):
    if not component:
        return None, "Missing component"
    try:
        attrs = component.attributes
        attr = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR) if attrs else None
        if not attr:
            return None, None
        raw = str(attr.value or "").strip()
        if not raw:
            return None, "Empty metadata attribute"
        return json.loads(raw), None
    except json.JSONDecodeError as ex:
        return None, "Invalid metadata JSON: {}".format(ex)
    except Exception as ex:
        return None, str(ex)


def read_panel_id(component):
    if not component:
        return ""
    try:
        attrs = component.attributes
        attr = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR) if attrs else None
        return str(attr.value).strip() if attr and attr.value else ""
    except Exception:
        return ""
