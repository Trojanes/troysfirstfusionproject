"""Load and reconcile generator-declared relationships."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

from generator_declared_relationships import build_reconcile_report, reconcile_declarations_with_geometry
from general_tall_declared_relationships import (
    GENERATOR_NAME as GENERAL_TALL_GENERATOR,
    detect_general_tall_generator,
    resolve_declarations_for_panels as resolve_general_tall_declarations,
)
from kitchen_declared_relationships import (
    GENERATOR_NAME as KITCHEN_GENERATOR,
    detect_kitchen_generator,
    resolve_declarations_for_panels as resolve_kitchen_declarations,
)
from lounge_declared_relationships import (
    GENERATOR_NAME as LOUNGE_GENERATOR,
    detect_lounge_generator,
    resolve_declarations_for_panels as resolve_lounge_declarations,
)
from overhead_declared_relationships import (
    GENERATOR_NAME as OVERHEAD_GENERATOR,
    detect_overhead_generator,
    resolve_declarations_for_panels as resolve_overhead_declarations,
)
from relationship_geometry import CONTACT_TOLERANCE_MM
from relationship_models import PanelSnapshot
from relationship_service import dedupe_panel_snapshots, scan_relationships


def panel_ids_from_snapshots(panels: List[PanelSnapshot]) -> Set[str]:
    return {panel.panelId for panel in panels if panel.panelId}


def load_declarations_for_panels(
    panels: List[PanelSnapshot],
    *,
    generator: Optional[str] = None,
    preferred_run_token: Optional[str] = None,
    embedded_declarations: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    panel_ids = panel_ids_from_snapshots(panels)
    if not panel_ids:
        return []
    resolved_generator = str(generator or "").strip() or None
    if not resolved_generator:
        if detect_overhead_generator(panel_ids):
            resolved_generator = OVERHEAD_GENERATOR
        elif detect_general_tall_generator(panel_ids):
            resolved_generator = GENERAL_TALL_GENERATOR
        elif detect_kitchen_generator(panel_ids):
            resolved_generator = KITCHEN_GENERATOR
        elif detect_lounge_generator(panel_ids):
            resolved_generator = LOUNGE_GENERATOR
    if resolved_generator == OVERHEAD_GENERATOR:
        return resolve_overhead_declarations(
            panel_ids,
            OVERHEAD_GENERATOR,
            preferred_run_token=preferred_run_token,
            embedded_declarations=embedded_declarations,
        )
    if resolved_generator == GENERAL_TALL_GENERATOR:
        return resolve_general_tall_declarations(
            panel_ids,
            GENERAL_TALL_GENERATOR,
            preferred_run_token=preferred_run_token,
            embedded_declarations=embedded_declarations,
        )
    if resolved_generator == KITCHEN_GENERATOR:
        return resolve_kitchen_declarations(
            panel_ids,
            KITCHEN_GENERATOR,
            preferred_run_token=preferred_run_token,
            embedded_declarations=embedded_declarations,
        )
    if resolved_generator == LOUNGE_GENERATOR:
        return resolve_lounge_declarations(
            panel_ids,
            LOUNGE_GENERATOR,
            preferred_run_token=preferred_run_token,
            embedded_declarations=embedded_declarations,
        )
    return []


def _scope_panels_to_run(
    panels: List[PanelSnapshot],
    preferred_run_token: Optional[str],
) -> List[PanelSnapshot]:
    token = str(preferred_run_token or "").strip()
    if not token:
        return dedupe_panel_snapshots(panels)
    # Overhead uses ohc.{run}.; General Tall may use gtc.{run}.; Kitchen may use kc.{run}.
    prefixes = (
        "ohc.{}.".format(token),
        "gtc.{}.".format(token),
        "kc.{}.".format(token),
    )
    scoped = [
        panel
        for panel in panels
        if any(str(panel.panelId or "").startswith(prefix) for prefix in prefixes)
    ]
    if not scoped:
        scoped = [panel for panel in panels if token in panel.panelId]
    if scoped:
        return dedupe_panel_snapshots(scoped)
    return dedupe_panel_snapshots(panels)


def reconcile_generator_declarations(
    panels: List[PanelSnapshot],
    *,
    generator: Optional[str] = None,
    tolerance_mm: float = CONTACT_TOLERANCE_MM,
    include_none: bool = False,
    preferred_run_token: Optional[str] = None,
    embedded_declarations: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    panels = _scope_panels_to_run(panels, preferred_run_token)
    declarations = load_declarations_for_panels(
        panels,
        generator=generator,
        preferred_run_token=preferred_run_token,
        embedded_declarations=embedded_declarations,
    )
    if not declarations:
        return build_reconcile_report(
            generator=generator or "unknown",
            panels=panels,
            reconcile_result={
                "ok": False,
                "declarationCount": 0,
                "geometryOkCount": 0,
                "reconciled": [],
                "relationships": [],
                "errors": ["No generator declarations matched the current panel set."],
                "warnings": [],
            },
            geometry_relationships=[],
        )

    _, geometry_relationships = scan_relationships(
        panels,
        tolerance_mm=tolerance_mm,
        include_none=include_none,
    )
    resolved_generator = str(declarations[0].get("generator") or generator or OVERHEAD_GENERATOR)
    reconcile_result = reconcile_declarations_with_geometry(declarations, geometry_relationships)
    return build_reconcile_report(
        generator=resolved_generator,
        panels=panels,
        reconcile_result=reconcile_result,
        geometry_relationships=geometry_relationships,
    )
