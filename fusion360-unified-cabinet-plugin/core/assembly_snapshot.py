"""Persist and recover generator params on Fusion assembly components.

New assemblies store generatorParams JSON. Older assemblies fall back to
geometry + board-attribute inference (see assembly_geometry_infer).
"""

import json

SUPPORTED_MODULES = ("overhead", "kitchen")
PARAMS_SCHEMA = {
    "overhead": "overhead.v1",
    "kitchen": "kitchen.v1",
}

# Read any known identity group; write the two groups adapters already use.
READ_ATTR_GROUPS = (
    "CabinetNC",
    "UnifiedCabinetPlugin",
    "UnifiedCabinet",
    "UnifiedCabinet.Panel",
)
WRITE_ATTR_GROUPS = ("CabinetNC", "UnifiedCabinetPlugin")

PARAMS_ATTR = "generatorParams"
SCHEMA_ATTR = "paramsSchema"
ORIGIN_ATTR = "originMm"
MODULE_ATTR = "module"
RUN_LABEL_ATTR = "runLabel"
ASSEMBLY_NAME_ATTR = "assemblyName"


def params_schema_for(module):
    return PARAMS_SCHEMA.get(str(module or ""), "")


def is_supported_module(module):
    return str(module or "") in SUPPORTED_MODULES


def set_entity_attribute(entity, name, value, groups=WRITE_ATTR_GROUPS):
    if not entity:
        return False
    try:
        attrs = entity.attributes
    except Exception:
        return False
    if not attrs:
        return False
    text = "" if value is None else str(value)
    wrote = False
    for group in groups:
        try:
            existing = attrs.itemByName(group, name) if attrs else None
            if existing:
                existing.value = text
            else:
                attrs.add(group, name, text)
            wrote = True
        except Exception:
            continue
    return wrote


def entity_attr(entity, name, groups=READ_ATTR_GROUPS):
    if not entity:
        return ""
    try:
        attrs = entity.attributes
    except Exception:
        return ""
    if not attrs:
        return ""
    for group in groups:
        try:
            attr = attrs.itemByName(group, name)
            if attr and attr.value:
                return str(attr.value).strip()
        except Exception:
            continue
    return ""


def _parse_json_attr(entity, name):
    raw = entity_attr(entity, name)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def origin_from_occurrence(occurrence):
    origin = {"x": 0.0, "y": 0.0, "z": 0.0, "rotationDeg": 0.0}
    if occurrence is None:
        return origin
    try:
        translation = occurrence.transform.translation
        origin["x"] = float(translation.x) * 10.0
        origin["y"] = float(translation.y) * 10.0
        origin["z"] = float(translation.z) * 10.0
    except Exception:
        stored = _parse_json_attr(getattr(occurrence, "component", None), ORIGIN_ATTR)
        if isinstance(stored, dict):
            return normalize_origin(stored)
    return origin


def normalize_origin(origin):
    data = origin if isinstance(origin, dict) else {}
    def _num(key, default=0.0):
        try:
            return float(data.get(key) if data.get(key) is not None else default)
        except Exception:
            return default
    return {
        "x": _num("x"),
        "y": _num("y"),
        "z": _num("z"),
        "rotationDeg": _num("rotationDeg"),
    }


def write_generator_snapshot(
    component,
    module,
    params,
    *,
    run_label=None,
    assembly_name=None,
    origin=None,
):
    """Stamp identity + params JSON onto the assembly component."""
    if not component or not is_supported_module(module):
        return False
    if not isinstance(params, dict):
        return False
    payload = json.dumps(params, ensure_ascii=False, separators=(",", ":"))
    origin_payload = json.dumps(normalize_origin(origin), ensure_ascii=False, separators=(",", ":"))
    ok = True
    ok = set_entity_attribute(component, MODULE_ATTR, module) and ok
    ok = set_entity_attribute(component, PARAMS_ATTR, payload) and ok
    ok = set_entity_attribute(component, SCHEMA_ATTR, params_schema_for(module)) and ok
    ok = set_entity_attribute(component, ORIGIN_ATTR, origin_payload) and ok
    if run_label:
        ok = set_entity_attribute(component, RUN_LABEL_ATTR, run_label) and ok
    if assembly_name:
        ok = set_entity_attribute(component, ASSEMBLY_NAME_ATTR, assembly_name) and ok
    return ok


def is_assembly_component(component):
    """True for a kitchen/overhead root, not a child panel that also has module=."""
    if not component:
        return False
    module = entity_attr(component, MODULE_ATTR)
    if not is_supported_module(module):
        return False
    if entity_attr(component, PARAMS_ATTR):
        return True
    if entity_attr(component, ASSEMBLY_NAME_ATTR) or entity_attr(component, RUN_LABEL_ATTR):
        return True
    if entity_attr(component, "boardId") or entity_attr(component, "panelId"):
        return False
    return True


def read_generator_snapshot(component):
    """Return a serializable snapshot dict, or None if this is not an assembly."""
    if not component:
        return None
    module = entity_attr(component, MODULE_ATTR)
    params = _parse_json_attr(component, PARAMS_ATTR)
    origin = _parse_json_attr(component, ORIGIN_ATTR)
    snapshot = {
        "module": module,
        "runLabel": entity_attr(component, RUN_LABEL_ATTR),
        "assemblyName": entity_attr(component, ASSEMBLY_NAME_ATTR) or str(getattr(component, "name", "") or ""),
        "params": params if isinstance(params, dict) else None,
        "paramsSchema": entity_attr(component, SCHEMA_ATTR),
        "origin": normalize_origin(origin) if isinstance(origin, dict) else normalize_origin({}),
        "supported": is_supported_module(module),
        "hasParams": isinstance(params, dict),
        "isAssembly": is_assembly_component(component),
    }
    if not module and not snapshot["assemblyName"] and not snapshot["hasParams"]:
        return None
    return snapshot


def _is_occurrence(entity):
    return (
        entity is not None
        and getattr(entity, "component", None) is not None
        and (
            getattr(entity, "transform", None) is not None
            or hasattr(entity, "assemblyContext")
        )
    )


def _occurrence_from_entity(entity):
    if entity is None:
        return None
    if _is_occurrence(entity):
        return entity
    body = getattr(entity, "body", None)
    if body is not None:
        occ = getattr(body, "assemblyContext", None)
        if occ is not None:
            return occ
    return getattr(entity, "assemblyContext", None)


def _occurrence_parent(occurrence):
    if occurrence is None:
        return None
    parent = getattr(occurrence, "parentOccurrence", None)
    if parent is not None and parent is not occurrence:
        return parent
    context = getattr(occurrence, "assemblyContext", None)
    if context is not None and context is not occurrence:
        return context
    return None


def _occurrence_chain(entity):
    occurrence = _occurrence_from_entity(entity)
    chain = []
    seen = set()
    current = occurrence
    while current is not None:
        marker = id(current)
        if marker in seen:
            break
        seen.add(marker)
        chain.append(current)
        current = _occurrence_parent(current)
    return chain


def root_occurrence(entity):
    """Nearest kitchen/overhead assembly occurrence, not a child panel."""
    chain = _occurrence_chain(entity)
    for occurrence in chain:
        if is_assembly_component(getattr(occurrence, "component", None)):
            return occurrence
    return chain[0] if chain else None


def resolve_assembly_from_entity(entity):
    """Map a selected body / face / occurrence to its generator assembly snapshot."""
    chain = _occurrence_chain(entity)
    occurrence = None
    component = None
    snapshot = None
    for item in chain:
        candidate = getattr(item, "component", None)
        candidate_snap = read_generator_snapshot(candidate)
        if not candidate_snap:
            continue
        if is_assembly_component(candidate):
            occurrence = item
            component = candidate
            snapshot = candidate_snap
            break
    if snapshot is None:
        occurrence = chain[0] if chain else None
        component = getattr(occurrence, "component", None) if occurrence is not None else None
        if component is None and entity is not None and getattr(entity, "attributes", None) is not None:
            component = entity
        snapshot = read_generator_snapshot(component)
    if snapshot and occurrence is not None and not snapshot.get("origin"):
        snapshot["origin"] = origin_from_occurrence(occurrence)
    elif snapshot and occurrence is not None:
        stored = snapshot.get("origin") or {}
        if stored.get("x") == 0.0 and stored.get("y") == 0.0 and stored.get("z") == 0.0:
            snapshot["origin"] = origin_from_occurrence(occurrence)
    return {
        "occurrence": occurrence,
        "component": component,
        "snapshot": snapshot,
    }


def load_from_selection(entities, supported_modules=SUPPORTED_MODULES):
    """Inspect Fusion selection and return a palette-safe payload."""
    items = list(entities or [])
    if not items:
        return {
            "ok": False,
            "action": "assemblies.loadFromSelection",
            "code": "empty_selection",
            "errors": ["Select a generated overhead or kitchen assembly (or any of its boards)."],
        }
    supported = tuple(supported_modules or SUPPORTED_MODULES)
    last_unsupported = ""
    last_legacy = ""
    for entity in items:
        resolved = resolve_assembly_from_entity(entity)
        snapshot = resolved.get("snapshot")
        if not snapshot:
            continue
        module = snapshot.get("module") or ""
        if module and module not in supported:
            last_unsupported = module
            continue
        if module not in supported:
            continue
        if not snapshot.get("hasParams"):
            last_legacy = snapshot.get("assemblyName") or module
            inferred = _infer_legacy_params(
                module,
                resolved.get("component"),
                resolved.get("occurrence"),
            )
            if inferred.get("ok") and inferred.get("params"):
                warnings = list(inferred.get("warnings") or [])
                warnings.insert(0, "Estimated from existing boards (no stored generatorParams).")
                return {
                    "ok": True,
                    "action": "assemblies.loadFromSelection",
                    "module": module,
                    "runLabel": snapshot.get("runLabel") or "",
                    "assemblyName": snapshot.get("assemblyName") or "",
                    "params": inferred.get("params"),
                    "paramsSchema": params_schema_for(module),
                    "origin": snapshot.get("origin") or normalize_origin({}),
                    "warnings": warnings,
                    "estimated": True,
                    "confidence": inferred.get("confidence") or "medium",
                    "boardCount": inferred.get("boardCount"),
                    "vCount": inferred.get("vCount"),
                    "frontCount": inferred.get("frontCount"),
                    "collectedBoards": inferred.get("collectedBoards") or [],
                }
            continue
        schema = snapshot.get("paramsSchema") or params_schema_for(module)
        expected = params_schema_for(module)
        warnings = []
        if expected and schema and schema != expected:
            warnings.append(
                "Stored params schema {} differs from {}; fields may need a review.".format(
                    schema, expected
                )
            )
        return {
            "ok": True,
            "action": "assemblies.loadFromSelection",
            "module": module,
            "runLabel": snapshot.get("runLabel") or "",
            "assemblyName": snapshot.get("assemblyName") or "",
            "params": snapshot.get("params"),
            "paramsSchema": schema,
            "origin": snapshot.get("origin") or normalize_origin({}),
            "warnings": warnings,
            "estimated": False,
        }
    if last_legacy:
        return {
            "ok": False,
            "action": "assemblies.loadFromSelection",
            "code": "legacy_infer_failed",
            "module": "",
            "errors": [
                "This assembly has no stored params and geometry analysis could not reconstruct them."
            ],
            "assemblyName": last_legacy,
        }
    if last_unsupported:
        return {
            "ok": False,
            "action": "assemblies.loadFromSelection",
            "code": "unsupported_module",
            "module": last_unsupported,
            "errors": [
                "Load-from-selection currently supports overhead and kitchen only (found {}).".format(
                    last_unsupported
                )
            ],
        }
    return {
        "ok": False,
        "action": "assemblies.loadFromSelection",
        "code": "not_generator_assembly",
        "errors": ["Selection is not a generated overhead or kitchen assembly."],
    }


def _infer_legacy_params(module, component, occurrence=None):
    try:
        from core.assembly_geometry_infer import infer_params_from_component
    except Exception:
        try:
            from assembly_geometry_infer import infer_params_from_component
        except Exception:
            return {"ok": False, "errors": ["Geometry infer module is unavailable."]}
    try:
        return infer_params_from_component(module, component, occurrence=occurrence)
    except Exception as ex:
        return {"ok": False, "errors": ["Geometry infer failed: {}".format(ex)]}


def find_root_occurrence_by_run_label(root_comp, module, run_label, assembly_name=None):
    if not root_comp or not module:
        return None
    try:
        occurrences = root_comp.occurrences
        count = occurrences.count
    except Exception:
        return None
    wanted_label = str(run_label or "").strip()
    wanted_name = str(assembly_name or "").strip()
    named_match = None
    for index in range(count):
        try:
            occurrence = occurrences.item(index)
            component = getattr(occurrence, "component", None)
            if entity_attr(component, MODULE_ATTR) != str(module):
                continue
            if wanted_label and entity_attr(component, RUN_LABEL_ATTR) == wanted_label:
                return occurrence
            if wanted_name and not named_match:
                found_name = entity_attr(component, ASSEMBLY_NAME_ATTR) or str(getattr(component, "name", "") or "")
                if found_name == wanted_name:
                    named_match = occurrence
        except Exception:
            continue
    return named_match


def delete_assembly_by_run_label(root_comp, module, run_label, assembly_name=None):
    """Delete the root occurrence matching module + runLabel, else assemblyName."""
    deleted = {"occurrences": 0}
    occurrence = find_root_occurrence_by_run_label(
        root_comp, module, run_label, assembly_name=assembly_name
    )
    if occurrence is None:
        return deleted
    try:
        occurrence.deleteMe()
        deleted["occurrences"] = 1
    except Exception:
        pass
    return deleted
