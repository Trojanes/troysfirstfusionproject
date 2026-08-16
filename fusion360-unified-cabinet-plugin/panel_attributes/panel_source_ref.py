"""Canonical identity for one source body behind a LAY_FLAT copy.

``panelId`` is deliberately descriptive only: legacy designs contain many
duplicate values. Write-back and persisted overrides must use ``key()``.
"""

from __future__ import annotations

import json

from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR


MARKER_GROUP = "UnifiedCabinet"
SOURCE_REF_ATTR = "sourceRefJson"


def _text(value):
    return str(value or "").strip()


def _path(value):
    if not isinstance(value, (list, tuple)):
        return None
    try:
        return [int(item) for item in value]
    except Exception:
        return None


def normalize(value):
    """Normalize a SourceRef-like dict. Returns ``None`` without exact lineage."""
    if not isinstance(value, dict):
        return None
    nested = value.get("sourceRef")
    source = nested if isinstance(nested, dict) else value
    token = _text(
        source.get("entityToken")
        or source.get("sourceEntityToken")
        or value.get("sourceEntityToken")
    )
    body_name = _text(
        source.get("bodyName")
        or source.get("sourceBodyName")
        or value.get("sourceBodyName")
        or value.get("bodyName")
    )
    occurrence_path = _path(
        source.get("occurrencePath")
        if "occurrencePath" in source
        else source.get("sourceOccurrencePath")
    )
    if occurrence_path is None:
        occurrence_path = _path(
            value.get("sourceOccurrencePath")
            if "sourceOccurrencePath" in value
            else value.get("occurrencePath")
        )
    panel_id = _text(
        source.get("panelId")
        or source.get("sourcePanelId")
        or value.get("sourcePanelId")
        or value.get("panelId")
    )
    component_name = _text(
        source.get("componentName")
        or source.get("sourceComponentName")
        or value.get("sourceComponentName")
        or value.get("componentName")
    )
    assembly_name = _text(
        source.get("assemblyName")
        or source.get("sourceAssemblyName")
        or value.get("sourceAssemblyName")
        or value.get("assemblyName")
    )
    if not token and not (body_name and occurrence_path is not None):
        return None
    normalized = {
        "entityToken": token,
        "occurrencePath": occurrence_path,
        "bodyName": body_name,
        "componentName": component_name,
        "panelId": panel_id,
    }
    if assembly_name:
        normalized["assemblyName"] = assembly_name
    return normalized


def from_scan_record(record):
    return normalize(record)


def key(value):
    ref = normalize(value)
    if not ref:
        return ""
    if ref["entityToken"]:
        return "token:{}".format(ref["entityToken"])
    path_text = "/".join(str(item) for item in (ref["occurrencePath"] or []))
    return "path:{}|{}".format(path_text, ref["bodyName"])


def to_legacy_fields(value):
    """Compatibility fields for existing stamp/read code."""
    ref = normalize(value)
    if not ref:
        return {}
    return {
        "sourceEntityToken": ref["entityToken"],
        "sourceOccurrencePath": list(ref["occurrencePath"] or []),
        "sourceBodyName": ref["bodyName"],
        "sourceComponentName": ref["componentName"],
        "sourceAssemblyName": ref.get("assemblyName", ""),
        "sourcePanelId": ref["panelId"],
    }


def _attribute_entities(body):
    """Yield selected proxy and native object exactly once."""
    seen = set()
    for candidate in (body, getattr(body, "nativeObject", None) if body else None):
        if candidate is None:
            continue
        marker = id(candidate)
        if marker in seen:
            continue
        seen.add(marker)
        yield candidate


def _attr(entity, group, name):
    try:
        attrs = entity.attributes
        item = attrs.itemByName(group, name) if attrs else None
        return _text(item.value) if item else ""
    except Exception:
        return ""


def _metadata_refs(body):
    for entity in _attribute_entities(body):
        raw = _attr(entity, PANEL_ATTRIBUTE_GROUP, PANEL_METADATA_ATTR)
        if not raw:
            continue
        try:
            metadata = json.loads(raw)
        except Exception:
            continue
        identity = (
            metadata.get("identity")
            if isinstance(metadata, dict)
            and isinstance(metadata.get("identity"), dict)
            else {}
        )
        nested = identity.get("sourceRef")
        ref = normalize(nested) if isinstance(nested, dict) else normalize(identity)
        if ref:
            yield ref


def from_lay_flat_body(body):
    """Read canonical lineage across proxy/native attribute stores."""
    if body is None:
        return None
    # Canonical compact marker first.
    for entity in _attribute_entities(body):
        raw = _attr(entity, MARKER_GROUP, SOURCE_REF_ATTR)
        if raw:
            try:
                ref = normalize(json.loads(raw))
            except Exception:
                ref = None
            if ref:
                return ref
    # Canonical metadata next; inspect each entity rather than "richest" JSON.
    for ref in _metadata_refs(body):
        return ref
    # One-release compatibility with separate marker attributes.
    for entity in _attribute_entities(body):
        path_raw = _attr(entity, MARKER_GROUP, "sourceOccurrencePath")
        try:
            occurrence_path = json.loads(path_raw) if path_raw else None
        except Exception:
            occurrence_path = None
        ref = normalize(
            {
                "sourceEntityToken": _attr(
                    entity, MARKER_GROUP, "sourceEntityToken"
                ),
                "sourceOccurrencePath": occurrence_path,
                "sourceBodyName": _attr(entity, MARKER_GROUP, "sourceBodyName"),
                "sourceComponentName": _attr(
                    entity, MARKER_GROUP, "sourceComponentName"
                ),
                "sourceAssemblyName": _attr(
                    entity, MARKER_GROUP, "sourceAssemblyName"
                ),
                "sourcePanelId": _attr(entity, MARKER_GROUP, "sourcePanelId"),
            }
        )
        if ref:
            return ref
    return None


def stamp_payload(value):
    ref = normalize(value)
    return (
        json.dumps(ref, ensure_ascii=False, separators=(",", ":")) if ref else ""
    )
