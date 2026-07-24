"""Golden relationship cases derived from generator output."""

from __future__ import annotations

from typing import Any, Dict, List


GENERATOR_RELATIONSHIP_SCENARIOS: List[Dict[str, Any]] = [
    {
        "scenarioId": "general_tall_base",
        "generator": "general_tall",
        "paramsFixture": "general_tall_base.json",
        "minPanelCount": 20,
        "minNonNoneRelationships": 50,
        "pairs": [
            {
                "caseId": "gt_b1_b3_bottom_rail_to_deck",
                "panelAId": "B1",
                "panelBId": "B3",
                "expectedGeometryType": "edge_to_surface",
            },
            {
                "caseId": "gt_b1_b2_rail_stack",
                "panelAId": "B1",
                "panelBId": "B2",
                "expectedGeometryType": "surface_to_surface",
            },
            {
                "caseId": "gt_t1_t3_top_rail_to_deck",
                "panelAId": "T1",
                "panelBId": "T3",
                "expectedGeometryType": "edge_to_surface",
            },
            {
                "caseId": "gt_t1_vd_door_gap",
                "panelAId": "T1",
                "panelBId": "VD_zone-3",
                "expectedGeometryType": "gap_parallel",
            },
            {
                "caseId": "gt_b3_h13_bottom_shelf",
                "panelAId": "B3",
                "panelBId": "H13_bottom",
                "expectedGeometryType": "surface_to_surface",
            },
        ],
    },
    {
        "scenarioId": "overhead_edge_only",
        "generator": "overhead",
        "paramsFixture": "overhead_edge_only.json",
        "minPanelCount": 8,
        "minNonNoneRelationships": 15,
        "pairs": [
            {
                "caseId": "oh_bp_d0_back_to_divider",
                "panelAId": "BP",
                "panelBId": "D0",
                "expectedGeometryType": "edge_to_surface",
            },
            {
                "caseId": "oh_t1_t2_top_rail_stack",
                "panelAId": "T1",
                "panelBId": "T2",
                "expectedGeometryType": "surface_to_surface",
            },
            {
                "caseId": "oh_bp_fp0_back_to_front",
                "panelAId": "BP",
                "panelBId": "FP0",
                "expectedGeometryType": "edge_to_surface",
            },
            {
                "caseId": "oh_d0_fp0_divider_to_front",
                "panelAId": "D0",
                "panelBId": "FP0",
                "expectedGeometryType": "edge_to_surface",
            },
        ],
    },
    {
        "scenarioId": "kitchen_base",
        "generator": "kitchen",
        "paramsFixture": "kitchen_base.json",
        "minPanelCount": 8,
        "minNonNoneRelationships": 7,
        "pairs": [
            {
                "caseId": "kt_b1_b3_bottom_to_deck",
                "panelAId": "B1",
                "panelBId": "B3",
                "expectedGeometryType": "edge_to_surface",
            },
            {
                "caseId": "kt_b1_b2_bottom_rail_stack",
                "panelAId": "B1",
                "panelBId": "B2",
                "expectedGeometryType": "surface_to_surface",
            },
            {
                "caseId": "kt_b1_strip_gap",
                "panelAId": "B1",
                "panelBId": "left-side-strengthening-strip-k-zone-left-door",
                "expectedGeometryType": "gap_parallel",
            },
            {
                "caseId": "kt_t1_strip_edge",
                "panelAId": "T1-1",
                "panelBId": "left-side-strengthening-strip-k-zone-left-door",
                "expectedGeometryType": "edge_to_surface",
            },
        ],
    },
    {
        "scenarioId": "lounge_l_shape",
        "generator": "lounge",
        "paramsFixture": "lounge_l_shape.json",
        "minPanelCount": 8,
        "minNonNoneRelationships": 10,
        "pairs": [
            {
                "caseId": "lg_l_front_side",
                "panelAId": "l_front",
                "panelBId": "l_side",
                "expectedGeometryType": "edge_to_surface",
            },
            {
                "caseId": "lg_main_top_front",
                "panelAId": "main_top",
                "panelBId": "main_front",
                "expectedGeometryType": "edge_to_surface",
            },
            {
                "caseId": "lg_l_front_top",
                "panelAId": "l_front",
                "panelBId": "l_top",
                "expectedGeometryType": "edge_to_surface",
            },
            {
                "caseId": "lg_main_top_l_top",
                "panelAId": "main_top",
                "panelBId": "l_top",
                "expectedGeometryType": "surface_to_surface",
            },
        ],
    },
]


def list_generator_relationship_scenarios() -> List[Dict[str, Any]]:
    return [dict(item) for item in GENERATOR_RELATIONSHIP_SCENARIOS]
