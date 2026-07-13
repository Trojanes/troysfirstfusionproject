"""Suggest hardware type from a BoardRelationship (optional auto-select; default off)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from hardware_rule_engine import (
    HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
    HARDWARE_TYPE_HINGE_HOLE,
    HARDWARE_TYPE_LOCK_CUTOUT,
    HARDWARE_TYPE_SCREW_HOLE,
    HARDWARE_TYPE_TONGUE_GROOVE,
    IMPLEMENTED_TYPES,
    normalize_hardware_type,
)

DEFAULT_AUTO_HARDWARE: Dict[str, Any] = {
    "enabled": False,
}

GAP_GEOMETRY_TYPE = "gap_parallel"
CONTACT_GEOMETRY_TYPES = ("edge_to_surface", "surface_to_surface")


def normalize_auto_hardware_settings(raw: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return dict(DEFAULT_AUTO_HARDWARE)
    return {"enabled": bool(raw.get("enabled", False))}


def _first_implemented(allowed: Optional[List[Any]]) -> Optional[str]:
    for item in allowed or []:
        key = str(item or "").strip().lower()
        if key in IMPLEMENTED_TYPES:
            return key
    return None


def suggest_hardware_type(relationship: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Return {type, reason, source} for a relationship. Always returns an implemented type."""
    if not isinstance(relationship, dict):
        return {
            "type": HARDWARE_TYPE_SCREW_HOLE,
            "reason": "missing_relationship",
            "source": "default",
        }

    declared = _first_implemented(relationship.get("allowedHardware"))
    if declared:
        return {
            "type": declared,
            "reason": "generator_allowedHardware",
            "source": "declaration",
        }

    geometry = str(relationship.get("geometryType") or "")
    if geometry == GAP_GEOMETRY_TYPE:
        return {
            "type": HARDWARE_TYPE_HINGE_HOLE,
            "reason": "gap_parallel_default_hinge",
            "source": "geometry_rule",
        }

    if geometry in CONTACT_GEOMETRY_TYPES:
        return {
            "type": HARDWARE_TYPE_SCREW_HOLE,
            "reason": "contact_default_screw",
            "source": "geometry_rule",
        }

    return {
        "type": HARDWARE_TYPE_SCREW_HOLE,
        "reason": "fallback_screw",
        "source": "default",
    }


def resolve_hardware_rule_for_relationship(
    relationship: Optional[Dict[str, Any]],
    base_rule: Optional[Dict[str, Any]] = None,
    auto_settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Merge base UI rule with auto type when enabled; otherwise keep UI type.

    When auto picks a different type, drop UI numeric params so planners use type defaults.
    """
    base = dict(base_rule or {})
    settings = normalize_auto_hardware_settings(
        auto_settings if auto_settings is not None else base.get("autoHardware")
    )
    if not settings["enabled"]:
        base["type"] = normalize_hardware_type(base)
        return base

    suggestion = suggest_hardware_type(relationship)
    resolved: Dict[str, Any] = {
        "type": suggestion["type"],
        "autoHardware": settings,
        "autoSuggestion": suggestion,
    }
    if "gapJoints" in base:
        resolved["gapJoints"] = base["gapJoints"]
    return resolved


# Keep type list referenced for offline tests / docs.
AUTO_SELECTABLE_TYPES = (
    HARDWARE_TYPE_SCREW_HOLE,
    HARDWARE_TYPE_TONGUE_GROOVE,
    HARDWARE_TYPE_HINGE_HOLE,
    HARDWARE_TYPE_LOCK_CUTOUT,
    HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
)
