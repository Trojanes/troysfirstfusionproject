"""M7 Formal Connect UI — view-model, filters, and action gates (offline-testable)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

CUT_SAFE_LEVELS: Set[str] = {"manual_confirmed", "face_verified", "generator_declared", "cut_approved"}

# Contact joints eligible for hardware preview / confirm / batch verify+cut.
CONTACT_HARDWARE_PAIRS: Set[tuple] = {
    ("edge_to_surface", "structural_butt_joint"),
    ("surface_to_surface", "face_contact"),
}

GAP_GEOMETRY_TYPE = "gap_parallel"

# Session defaults: gap joints off until the user enables them.
DEFAULT_GAP_JOINTS: Dict[str, Any] = {
    "enabled": False,
    "minGapMm": 1.0,
    "maxGapMm": 20.0,
    "includeInBatch": True,
}


def normalize_gap_joints_settings(raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Normalize Connect gap-joint options; defaults keep gap hardware off."""
    base = dict(DEFAULT_GAP_JOINTS)
    if not isinstance(raw, dict):
        return {
            "enabled": False,
            "minGapMm": float(base["minGapMm"]),
            "maxGapMm": float(base["maxGapMm"]),
            "includeInBatch": False,
        }
    enabled = bool(raw.get("enabled", base["enabled"]))
    try:
        min_gap = float(raw.get("minGapMm", base["minGapMm"]))
    except Exception:
        min_gap = float(base["minGapMm"])
    try:
        max_gap = float(raw.get("maxGapMm", base["maxGapMm"]))
    except Exception:
        max_gap = float(base["maxGapMm"])
    if min_gap < 0:
        min_gap = 0.0
    if max_gap < min_gap:
        max_gap = min_gap
    include = raw.get("includeInBatch", base["includeInBatch"])
    return {
        "enabled": enabled,
        "minGapMm": min_gap,
        "maxGapMm": max_gap,
        "includeInBatch": bool(include) if enabled else False,
    }


def is_contact_hardware_pair(relationship: Optional[Dict[str, Any]]) -> bool:
    if not isinstance(relationship, dict):
        return False
    pair = (
        str(relationship.get("geometryType") or ""),
        str(relationship.get("relationshipType") or ""),
    )
    return pair in CONTACT_HARDWARE_PAIRS


def _gap_distance_mm(relationship: Dict[str, Any]) -> Optional[float]:
    contact = relationship.get("contact") or {}
    try:
        return float(contact.get("distanceMm"))
    except Exception:
        return None


def is_gap_hardware_pair(
    relationship: Optional[Dict[str, Any]],
    gap_settings: Optional[Dict[str, Any]] = None,
    *,
    for_batch: bool = False,
) -> bool:
    """True when gap_parallel is enabled and distance is inside the user band."""
    if not isinstance(relationship, dict):
        return False
    if str(relationship.get("geometryType") or "") != GAP_GEOMETRY_TYPE:
        return False
    settings = normalize_gap_joints_settings(gap_settings)
    if not settings["enabled"]:
        return False
    if for_batch and not settings["includeInBatch"]:
        return False
    roles = relationship.get("roles") or {}
    if not roles.get("hostPanelId") or not roles.get("targetPanelId"):
        return False
    distance = _gap_distance_mm(relationship)
    if distance is None:
        return False
    return settings["minGapMm"] <= distance <= settings["maxGapMm"]


def is_hardware_eligible(
    relationship: Optional[Dict[str, Any]],
    gap_settings: Optional[Dict[str, Any]] = None,
    *,
    for_batch: bool = False,
) -> bool:
    """Contact pairs always; gap_parallel only when gapJoints enabled (+ batch flag)."""
    if is_contact_hardware_pair(relationship):
        return True
    return is_gap_hardware_pair(relationship, gap_settings, for_batch=for_batch)


def gap_settings_from_rule(rule: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(rule, dict):
        return normalize_gap_joints_settings(None)
    return normalize_gap_joints_settings(rule.get("gapJoints"))


VERIFICATION_UI: Dict[str, Dict[str, Any]] = {
    "bbox_contact_patch": {
        "label": "BBox contact patch",
        "tone": "warn",
        "description": "Axis-aligned contact region — preview only, not safe for automatic cut.",
    },
    "bbox_candidate": {
        "label": "BBox candidate",
        "tone": "warn",
        "description": "Preview only — not safe for automatic cut.",
    },
    "manual_confirmed": {
        "label": "Manual confirmed",
        "tone": "ok",
        "description": "User approved for controlled cut testing.",
    },
    "face_verified": {
        "label": "Face verified",
        "tone": "ok",
        "description": "Selected pair verified against BRep faces.",
    },
    "generator_declared": {
        "label": "Generator declared",
        "tone": "ok",
        "description": "Design-intent joint reconciled with geometry.",
    },
    "cut_approved": {
        "label": "Cut approved",
        "tone": "ok",
        "description": "Final machining approval.",
    },
    "unknown": {
        "label": "Unknown",
        "tone": "warn",
        "description": "Verification level not set.",
    },
}


def _verification_meta(level: str) -> Dict[str, Any]:
    return dict(VERIFICATION_UI.get(level or "unknown") or VERIFICATION_UI["unknown"])


def relationship_verification_level(relationship: Dict[str, Any]) -> str:
    verification = relationship.get("verification") or {}
    return str(verification.get("level") or "unknown")


def is_preview_allowed(
    relationship: Dict[str, Any],
    gap_settings: Optional[Dict[str, Any]] = None,
) -> bool:
    verification = relationship.get("verification") or {}
    if verification.get("safeForPreview") is True:
        return True
    geometry_type = str(relationship.get("geometryType") or "")
    if geometry_type in ("edge_to_surface", "surface_to_surface"):
        return True
    if geometry_type == GAP_GEOMETRY_TYPE:
        return bool(normalize_gap_joints_settings(gap_settings)["enabled"])
    return False


def is_cut_allowed(relationship: Dict[str, Any]) -> bool:
    verification = relationship.get("verification") or {}
    level = relationship_verification_level(relationship)
    return bool(verification.get("safeForCut")) and level in CUT_SAFE_LEVELS


def apply_manual_confirm(relationship: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(relationship or {})
    notes = list(merged.get("auditNotes") or [])
    notes.append("Manual cut confirmation applied (Connect UI session).")
    merged["verification"] = {
        "level": "manual_confirmed",
        "safeForPreview": True,
        "safeForCut": True,
        "requiresManualConfirmation": False,
    }
    merged["auditNotes"] = notes
    return merged


def evaluate_connect_action(
    action: str,
    relationship: Optional[Dict[str, Any]],
    gap_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    action_key = str(action or "").strip().lower()
    if not relationship:
        return {"ok": False, "action": action_key, "errors": ["No relationship selected."]}
    settings = normalize_gap_joints_settings(gap_settings)

    if action_key in ("preview", "preview_screw_holes"):
        if not is_preview_allowed(relationship, settings):
            return {
                "ok": False,
                "action": action_key,
                "errors": ["Relationship is not eligible for hardware preview."],
            }
        if not is_hardware_eligible(relationship, settings):
            return {
                "ok": False,
                "action": action_key,
                "errors": [
                    "Only contact hardware pairs (or enabled gap joints) support preview."
                ],
            }
        roles = relationship.get("roles") or {}
        if not roles.get("hostPanelId") or not roles.get("targetPanelId"):
            return {"ok": False, "action": action_key, "errors": ["Missing host/target roles."]}
        return {"ok": True, "action": action_key, "relationshipId": relationship.get("relationshipId")}

    if action_key in ("confirm", "confirm_for_cut"):
        if not is_hardware_eligible(relationship, settings):
            return {
                "ok": False,
                "action": action_key,
                "errors": [
                    "Only contact hardware pairs (or enabled gap joints) can be confirmed for cut."
                ],
            }
        roles = relationship.get("roles") or {}
        if not roles.get("hostPanelId") or not roles.get("targetPanelId"):
            return {"ok": False, "action": action_key, "errors": ["Missing host/target roles."]}
        if is_cut_allowed(relationship):
            return {
                "ok": True,
                "action": action_key,
                "relationshipId": relationship.get("relationshipId"),
                "alreadyCutSafe": True,
            }
        return {
            "ok": True,
            "action": action_key,
            "relationshipId": relationship.get("relationshipId"),
            "alreadyCutSafe": False,
            "confirmedRelationship": apply_manual_confirm(relationship),
        }

    if action_key in ("cut", "create_cut", "create_screw_holes"):
        if relationship_verification_level(relationship) == "bbox_candidate":
            return {
                "ok": False,
                "action": action_key,
                "errors": ["BBox candidates cannot be cut directly. Confirm or verify first."],
            }
        if not is_cut_allowed(relationship):
            return {
                "ok": False,
                "action": action_key,
                "errors": ["Relationship is not cut-safe. Confirm manually, verify faces, or reconcile declarations."],
            }
        return {"ok": True, "action": action_key, "relationshipId": relationship.get("relationshipId")}

    return {"ok": False, "action": action_key, "errors": ["Unsupported Connect action: {}.".format(action)]}


def format_relationship_row(relationship: Dict[str, Any]) -> Dict[str, Any]:
    panel_a = relationship.get("panelA") or {}
    panel_b = relationship.get("panelB") or {}
    verification = relationship.get("verification") or {}
    level = relationship_verification_level(relationship)
    meta = _verification_meta(level)
    roles = relationship.get("roles") or {}
    source = relationship.get("source") or {}
    return {
        "relationshipId": relationship.get("relationshipId"),
        "panelAId": panel_a.get("panelId"),
        "panelBId": panel_b.get("panelId"),
        "geometryType": relationship.get("geometryType"),
        "relationshipType": relationship.get("relationshipType"),
        "verificationLevel": level,
        "verificationLabel": meta["label"],
        "verificationTone": meta["tone"],
        "verificationDescription": meta["description"],
        "safeForPreview": bool(verification.get("safeForPreview")),
        "safeForCut": bool(verification.get("safeForCut")),
        "confidence": source.get("confidence"),
        "hostPanelId": roles.get("hostPanelId"),
        "targetPanelId": roles.get("targetPanelId"),
        "warnings": list((relationship.get("validation") or {}).get("warnings") or []),
        "errors": list((relationship.get("validation") or {}).get("errors") or []),
    }


def merge_declared_relationships_into_scan(
    scan_result: Dict[str, Any],
    declared_relationships: Optional[List[Dict[str, Any]]],
) -> Dict[str, Any]:
    """Overlay reconciled / generator-declared relationships onto a scan payload."""
    merged = dict(scan_result or {})
    declared = [rel for rel in (declared_relationships or []) if isinstance(rel, dict)]
    if not declared:
        return merged

    declared_by_id = {
        str(rel.get("relationshipId") or ""): rel for rel in declared if rel.get("relationshipId")
    }
    declared_by_pair: Dict[tuple, Dict[str, Any]] = {}
    for rel in declared:
        panel_a = rel.get("panelA") or {}
        panel_b = rel.get("panelB") or {}
        key = (
            str(panel_a.get("panelId") or ""),
            str(panel_b.get("panelId") or ""),
        )
        if key[0] and key[1]:
            declared_by_pair[tuple(sorted(key))] = rel

    relationships: List[Dict[str, Any]] = []
    seen_ids: set = set()
    seen_pairs: set = set()
    for rel in merged.get("relationships") or []:
        if not isinstance(rel, dict):
            continue
        rel_id = str(rel.get("relationshipId") or "")
        panel_a = rel.get("panelA") or {}
        panel_b = rel.get("panelB") or {}
        pair_key = tuple(sorted((str(panel_a.get("panelId") or ""), str(panel_b.get("panelId") or ""))))
        replacement = declared_by_id.get(rel_id)
        if replacement is None and pair_key in declared_by_pair:
            replacement = declared_by_pair[pair_key]
        relationships.append(replacement or rel)
        if rel_id:
            seen_ids.add(rel_id)
        if pair_key[0] and pair_key[1]:
            seen_pairs.add(pair_key)

    for rel in declared:
        rel_id = str(rel.get("relationshipId") or "")
        panel_a = rel.get("panelA") or {}
        panel_b = rel.get("panelB") or {}
        pair_key = tuple(sorted((str(panel_a.get("panelId") or ""), str(panel_b.get("panelId") or ""))))
        if rel_id and rel_id in seen_ids:
            continue
        if pair_key in seen_pairs:
            continue
        relationships.append(rel)
        if rel_id:
            seen_ids.add(rel_id)
        if pair_key[0] and pair_key[1]:
            seen_pairs.add(pair_key)

    merged["relationships"] = relationships
    merged["relationshipCount"] = len(relationships)
    merged["declaredOverlayCount"] = len(declared)
    return merged


def filter_relationships(
    relationships: List[Dict[str, Any]],
    *,
    geometry_type: Optional[str] = None,
    verification_level: Optional[str] = None,
    relationship_type: Optional[str] = None,
    cut_safe_only: bool = False,
    preview_only: bool = False,
) -> List[Dict[str, Any]]:
    filtered: List[Dict[str, Any]] = []
    for rel in relationships or []:
        if geometry_type and str(rel.get("geometryType") or "") != geometry_type:
            continue
        if verification_level and relationship_verification_level(rel) != verification_level:
            continue
        if relationship_type and str(rel.get("relationshipType") or "") != relationship_type:
            continue
        if cut_safe_only and not is_cut_allowed(rel):
            continue
        if preview_only and not is_preview_allowed(rel):
            continue
        filtered.append(rel)
    return filtered


def _panel_ids_from_relationship(relationship: Dict[str, Any]) -> Set[str]:
    panel_a = relationship.get("panelA") or {}
    panel_b = relationship.get("panelB") or {}
    roles = relationship.get("roles") or {}
    ids = {
        str(panel_a.get("panelId") or ""),
        str(panel_b.get("panelId") or ""),
        str(roles.get("hostPanelId") or ""),
        str(roles.get("targetPanelId") or ""),
    }
    return {panel_id for panel_id in ids if panel_id}


def match_declared_relationship_for_pair(
    declared_relationships: Optional[List[Dict[str, Any]]],
    panel_ids: Optional[List[str]],
) -> Optional[Dict[str, Any]]:
    """Return a cut-safe generator_declared match for the selected panel pair, if any."""
    wanted = {str(panel_id or "") for panel_id in (panel_ids or []) if panel_id}
    if len(wanted) < 2:
        return None
    for rel in declared_relationships or []:
        if not isinstance(rel, dict):
            continue
        if relationship_verification_level(rel) != "generator_declared":
            continue
        if (rel.get("geometryValidation") or {}).get("ok") is False:
            continue
        if not is_cut_allowed(rel):
            continue
        panel_a = str((rel.get("panelA") or {}).get("panelId") or "")
        panel_b = str((rel.get("panelB") or {}).get("panelId") or "")
        if panel_a and panel_b and {panel_a, panel_b} == wanted:
            return rel
        if len(wanted & _panel_ids_from_relationship(rel)) >= 2:
            return rel
    return None


def preferred_verify_step(relationship: Optional[Dict[str, Any]]) -> str:
    """Product verify path: declared/face → cut_ready; else face_verify (manual is debug-only)."""
    if not relationship:
        return "inspect"
    if is_cut_allowed(relationship):
        return "cut_ready"
    return "face_verify"


def build_connect_view_model(
    scan_result: Dict[str, Any],
    *,
    filters: Optional[Dict[str, Any]] = None,
    selected_relationship_id: Optional[str] = None,
    gap_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    filters = dict(filters or {})
    settings = normalize_gap_joints_settings(gap_settings)
    relationships = list(scan_result.get("relationships") or [])
    scoped = filter_relationships(
        relationships,
        geometry_type=filters.get("geometryType") or None,
        verification_level=filters.get("verificationLevel") or None,
        relationship_type=filters.get("relationshipType") or None,
        cut_safe_only=bool(filters.get("cutSafeOnly")),
        preview_only=bool(filters.get("previewOnly")),
    )
    rows = [format_relationship_row(rel) for rel in scoped]
    selected = None
    selected_row = None
    if selected_relationship_id:
        for rel in relationships:
            if rel.get("relationshipId") == selected_relationship_id:
                selected = rel
                break
    if selected is None and rows:
        selected = next((rel for rel in scoped if rel.get("relationshipId") == rows[0]["relationshipId"]), None)
    if selected:
        selected_row = format_relationship_row(selected)

    geometry_types = sorted({str(rel.get("geometryType") or "unknown") for rel in relationships})
    verification_levels = sorted({relationship_verification_level(rel) for rel in relationships})

    actions = {
        "preview": evaluate_connect_action("preview", selected, settings),
        "confirm": evaluate_connect_action("confirm", selected, settings),
        "cut": evaluate_connect_action("cut", selected, settings),
    }

    return {
        "ok": bool(scan_result.get("ok", True)),
        "action": "relationships.connectList",
        "panelCount": len(scan_result.get("panels") or []),
        "relationshipCount": len(relationships),
        "filteredCount": len(rows),
        "filters": filters,
        "filterOptions": {
            "geometryTypes": geometry_types,
            "verificationLevels": verification_levels,
        },
        "rows": rows,
        "selectedRelationshipId": (selected or {}).get("relationshipId") if selected else None,
        "selected": selected_row,
        "selectedRelationship": selected,
        "actions": actions,
        "errors": list(scan_result.get("errors") or []),
        "warnings": list(scan_result.get("warnings") or []),
    }
