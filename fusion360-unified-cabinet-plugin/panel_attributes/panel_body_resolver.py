try:
    import adsk.core  # noqa: F401  (only present inside Fusion)
except ImportError:
    pass

from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR
import panel_source_ref


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


def _is_solid_body(body, include_hidden=False):
    try:
        if not body or not body.isSolid:
            return False
        if (
            not include_hidden
            and hasattr(body, "isVisible")
            and not body.isVisible
        ):
            return False
        return True
    except Exception:
        return False


def list_solid_bodies(component, include_hidden=False):
    bodies = []
    if not component:
        return bodies
    try:
        for index in range(component.bRepBodies.count):
            body = component.bRepBodies.item(index)
            if _is_solid_body(body, include_hidden=include_hidden):
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
    """Return the body panelId attribute when present (not metadata fallback)."""
    if not body:
        return ""
    try:
        attrs = body.attributes
        attr = attrs.itemByName(PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR) if attrs else None
        value = str(attr.value or "").strip() if attr and attr.value else ""
        if value:
            return value
    except Exception:
        pass
    try:
        attrs = body.attributes
        attr = attrs.itemByName("UnifiedCabinet", "panelId") if attrs else None
        return str(attr.value or "").strip() if attr and attr.value else ""
    except Exception:
        return ""


def _metadata_panel_id(body):
    if not body:
        return ""
    try:
        from tag_metadata_editor import _read_body_metadata_raw
    except Exception:
        try:
            from panel_attributes.tag_metadata_editor import _read_body_metadata_raw
        except Exception:
            return ""
    try:
        metadata, _err = _read_body_metadata_raw(body)
    except Exception:
        return ""
    if not isinstance(metadata, dict):
        return ""
    identity = (
        metadata.get("identity") if isinstance(metadata.get("identity"), dict) else {}
    )
    return str(identity.get("panelId") or metadata.get("panelId") or "").strip()


def resolve_body_panel_id(body):
    """Best-effort panelId from attributes or metadata identity."""
    value = read_body_panel_id(body)
    if value:
        return value
    return _metadata_panel_id(body)


def _strip_layflat_suffix(panel_id):
    text = str(panel_id or "").strip()
    marker = "@layflat"
    idx = text.lower().find(marker)
    if idx > 0:
        return text[:idx].strip()
    return text


def _panel_id_name_hints(panel_id):
    text = _strip_layflat_suffix(panel_id)
    if not text:
        return set()
    board = text.split(".")[-1].strip()
    hints = {text, text.replace(".", "_"), text.replace(".", "-")}
    if board:
        hints.update(
            {
                board,
                "OH_{}".format(board),
                "OH-{}".format(board),
                "OH{}".format(board),
            }
        )
    return {hint for hint in hints if hint}


def _body_name_score(body, panel_id):
    hints = {hint.lower() for hint in _panel_id_name_hints(panel_id)}
    if not hints:
        return 0
    board = _strip_layflat_suffix(panel_id).split(".")[-1].strip().lower()
    try:
        name = str(getattr(body, "name", "") or "").strip()
    except Exception:
        name = ""
    parent_name = ""
    try:
        parent = getattr(body, "parentComponent", None)
        parent_name = str(getattr(parent, "name", "") or "").strip() if parent else ""
    except Exception:
        parent_name = ""
    score = 0
    for candidate in (name, parent_name):
        lower = candidate.lower()
        if not lower:
            continue
        if lower in hints:
            score = max(score, 100)
        elif board and (
            lower.endswith("_{}".format(board))
            or lower.endswith("-{}".format(board))
            or lower.endswith(board)
        ):
            score = max(score, 70)
        elif board and board in lower:
            score = max(score, 20)
        # Prefer exact OH_* board names over UOH_* collisions on the same id.
        if lower.startswith("uoh") and "oh_{}".format(board) in hints:
            score -= 30
    return score


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


def find_occurrence_by_path(root_component, occurrence_path):
    """Return the leaf occurrence in root assembly context."""
    path = list(occurrence_path or [])
    if not root_component or not path:
        return None
    try:
        context = None
        component = root_component
        for index in path:
            if not component.occurrences or index >= component.occurrences.count:
                return None
            child = component.occurrences.item(index)
            context = (
                child
                if context is None
                else child.createForAssemblyContext(context)
            )
            if context is None:
                return None
            component = child.component
        return context
    except Exception:
        return None


def body_proxy_by_path(root_component, occurrence_path, body_name):
    """Resolve the named body in the exact occurrence context."""
    component = find_component_by_path(root_component, occurrence_path)
    body = body_by_name(component, body_name) if component else None
    if body is None:
        return None
    occurrence = find_occurrence_by_path(root_component, occurrence_path)
    if occurrence is None:
        return body
    try:
        proxy = body.createForAssemblyContext(occurrence)
        return proxy or body
    except Exception:
        return body


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


def _is_copy_instance(body):
    """True for Nesting / Lay Flat manufacturing copies (not assembly originals)."""
    try:
        attrs = body.attributes
        role = attrs.itemByName("UnifiedCabinet", "instanceRole")
        if role and str(role.value or "") in ("nested", "layFlat"):
            return True
        system_role = attrs.itemByName("UnifiedCabinet", "systemRole")
        return bool(
            system_role
            and str(system_role.value or "") in ("nestingWorkpiece", "layFlatWorkpiece")
        )
    except Exception:
        return False


def _pick_original_body(pool, panel_id):
    if not pool:
        return None
    if len(pool) == 1:
        return pool[0]
    ranked = sorted(
        pool,
        key=lambda body: (
            _body_name_score(body, panel_id),
            str(getattr(body, "name", "") or ""),
        ),
        reverse=True,
    )
    best = ranked[0]
    # If several share the same panelId (data collision), require a name hint
    # winner so we don't write the wrong UOH_* body for overhead.D1.
    if _body_name_score(best, panel_id) <= 0 and len(ranked) > 1:
        return None
    return best


def iter_original_bodies(root_component):
    """Yield non-copy solid bodies once (includes hidden). Cost: O(N)."""
    if root_component is None:
        return
    seen = set()

    def consider(body):
        if body is None or _is_copy_instance(body):
            return None
        token = _safe_entity_token(body)
        try:
            name = str(getattr(body, "name", "") or "")
            parent = getattr(body, "parentComponent", None)
            parent_name = str(getattr(parent, "name", "") or "") if parent else ""
        except Exception:
            name = ""
            parent_name = ""
        key = token or "{}|{}|{}".format(parent_name, name, id(body))
        if key in seen:
            return None
        seen.add(key)
        return body

    def walk(component):
        for body in list_solid_bodies(component, include_hidden=True):
            chosen = consider(body)
            if chosen is not None:
                yield chosen
        try:
            occurrences = component.occurrences
            count = occurrences.count if occurrences else 0
        except Exception:
            return
        for index in range(count):
            try:
                occurrence = occurrences.item(index)
            except Exception:
                continue
            try:
                solid_count = int(occurrence.bRepBodies.count or 0)
            except Exception:
                solid_count = 0
            if solid_count:
                for body_index in range(solid_count):
                    try:
                        body = occurrence.bRepBodies.item(body_index)
                    except Exception:
                        continue
                    if _is_solid_body(body, include_hidden=True):
                        chosen = consider(body)
                        if chosen is not None:
                            yield chosen
            for child in walk(occurrence.component):
                yield child

    for body in walk(root_component):
        yield body


def build_original_body_index_by_panel_id(root_component):
    """One design walk → ``panelId → [bodies]`` plus flat originals list.

    Cost: O(N) bodies. Use with :func:`find_original_body_by_panel_id` so k
    lookups are O(N + k) total instead of O(k·N).
    """
    by_id = {}
    originals = []
    for body in iter_original_bodies(root_component):
        originals.append(body)
        panel_id = _strip_layflat_suffix(resolve_body_panel_id(body))
        if not panel_id:
            continue
        by_id.setdefault(panel_id, []).append(body)
    return {"by_id": by_id, "originals": originals}


def _read_attr_value(body, group, name):
    if body is None:
        return ""
    try:
        attrs = body.attributes
        attr = attrs.itemByName(group, name) if attrs else None
        return str(attr.value or "").strip() if attr and attr.value else ""
    except Exception:
        return ""


def read_lay_flat_source_ref(body):
    """Return compatibility fields backed by the canonical SourceRef reader."""
    canonical = panel_source_ref.from_lay_flat_body(body)
    fields = panel_source_ref.to_legacy_fields(canonical)
    if not fields:
        fields = {
            "sourcePanelId": "",
            "sourceEntityToken": "",
            "sourceBodyName": "",
            "sourceComponentName": "",
            "sourceOccurrencePath": [],
        }
        # Diagnostic only. This value must never authorize a write.
        try:
            from milling_surface_propagation import read_source_panel_id
        except Exception:
            read_source_panel_id = None
        if callable(read_source_panel_id):
            fields["sourcePanelId"] = str(
                read_source_panel_id(body) or ""
            ).strip()
    fields["sourceRef"] = canonical
    fields["sourceKey"] = panel_source_ref.key(canonical)
    return fields


def _body_from_entity_token(root_component, entity_token):
    token = str(entity_token or "").strip()
    if not token:
        return None
    try:
        import adsk.core

        app = adsk.core.Application.get()
        product = app.activeProduct if app else None
        design = product
        if product is not None and hasattr(product, "findEntityByToken"):
            entities = product.findEntityByToken(token)
        else:
            entities = None
        body = None
        if entities is not None:
            try:
                count = int(entities.count or 0)
            except Exception:
                count = len(entities) if isinstance(entities, (list, tuple)) else 0
            if count:
                try:
                    body = entities.item(0)
                except Exception:
                    body = entities[0]
        if body is not None and (
            getattr(body, "objectType", "").endswith("BRepBody")
            or hasattr(body, "faces")
        ):
            return body
    except Exception:
        pass
    # Offline / test fallback: scan originals for matching token.
    if root_component is not None:
        for body in iter_original_bodies(root_component):
            if _safe_entity_token(body) == token:
                return body
    return None


def resolve_source_bodies_for_lay_flat(
    root_component,
    lay_flat_body,
    index=None,
    allow_panel_id_fallback=True,
):
    """Resolve the assembly body(ies) that a LAY_FLAT copy was built from.

    Prefer exact lineage (entityToken / occurrencePath+name). Fall back to
    high-confidence panelId matches. Returns ``(bodies, ref, resolution)``.
    """
    ref = read_lay_flat_source_ref(lay_flat_body)
    bodies = []
    resolution = "none"

    token = ref.get("sourceEntityToken") or ""
    if token:
        found = _body_from_entity_token(root_component, token)
        if found is not None and not _is_copy_instance(found):
            bodies = [found]
            resolution = "entityToken"

    if not bodies:
        path = ref.get("sourceOccurrencePath") or []
        name = str(ref.get("sourceBodyName") or "").strip()
        if name:
            found = body_proxy_by_path(root_component, path, name)
            if found is not None and not _is_copy_instance(found):
                bodies = [found]
                resolution = "occurrencePath"

    if not bodies and allow_panel_id_fallback and ref.get("sourcePanelId"):
        candidates = find_original_bodies_by_panel_id(
            root_component, ref["sourcePanelId"], index=index
        )
        # A panelId-only fallback is safe only when it identifies one body.
        # Never fan one Apply action out across duplicate manual.Body1/OH ids.
        if len(candidates) == 1:
            bodies = candidates
            resolution = "uniquePanelId"
        elif len(candidates) > 1:
            bodies = []
            resolution = "ambiguousPanelId"
    elif not bodies and not allow_panel_id_fallback:
        resolution = "lineageNotResolved" if ref.get("sourceKey") else "missingLineage"

    return bodies, ref, resolution


def find_original_bodies_by_panel_id(root_component, panel_id, index=None):
    """Return high-confidence original bodies for ``panel_id`` (may be several).

    Duplicate panelIds (OH vs UOH) are filtered by name score: keep bodies at
    the best score tier (minimum 70), so tag writes hit every plausible source
    that Lay Flat might rebuild from.
    """
    panel_id = _strip_layflat_suffix(panel_id)
    if not root_component or not panel_id:
        return []

    if index is not None:
        by_id = index.get("by_id") if isinstance(index, dict) else None
        id_matches = list((by_id or {}).get(panel_id) or [])
        name_matches = [
            body
            for body in (index.get("originals") or [])
            if _body_name_score(body, panel_id) >= 70
        ]
    else:
        id_matches = []
        name_matches = []
        for body in iter_original_bodies(root_component):
            resolved = _strip_layflat_suffix(resolve_body_panel_id(body))
            if resolved == panel_id:
                id_matches.append(body)
            elif _body_name_score(body, panel_id) >= 70:
                name_matches.append(body)

    pool = id_matches or name_matches
    if not pool:
        return []
    scored = [
        (body, _body_name_score(body, panel_id))
        for body in pool
    ]
    best = max(score for _body, score in scored)
    if best < 70 and len(scored) > 1:
        # Ambiguous collision with no name winner — do not guess.
        return []
    min_keep = best if best >= 70 else 0
    winners = [body for body, score in scored if score >= min_keep]
    # Stable unique by entity token / identity.
    seen = set()
    unique = []
    for body in winners:
        token = _safe_entity_token(body) or str(id(body))
        if token in seen:
            continue
        seen.add(token)
        unique.append(body)
    return unique


def find_original_body_by_panel_id(root_component, panel_id, index=None):
    """Find the assembly-zone body for ``panel_id``, skipping Nesting/Lay Flat copies.

    Without ``index``: O(N) walk per call.
    With ``index`` from :func:`build_original_body_index_by_panel_id`: O(1) id
    lookup (+ O(N) name fallback only on miss).
    """
    bodies = find_original_bodies_by_panel_id(
        root_component, panel_id, index=index
    )
    if not bodies:
        return None
    return _pick_original_body(bodies, panel_id) or bodies[0]


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
