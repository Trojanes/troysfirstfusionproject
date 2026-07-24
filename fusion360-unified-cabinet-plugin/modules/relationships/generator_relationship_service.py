"""Evaluate generator-backed relationship golden cases."""

from __future__ import annotations

from typing import Any, Dict, List

from generator_bridge_runner import GENERATOR_RUNNERS, load_params_fixture
from generator_panel_adapter import snapshots_from_generator_result
from generator_relationship_cases import list_generator_relationship_scenarios
from relationship_geometry import classify_pair
from relationship_models import DETECTION_METHOD_BBOX_AABB
from relationship_service import build_panel_snapshot_from_dict, scan_relationships


def _run_generator_scenario(scenario: Dict[str, Any]) -> Dict[str, Any]:
    generator = str(scenario.get("generator") or "")
    runner = GENERATOR_RUNNERS.get(generator)
    if not runner:
        raise ValueError("Unknown generator: {}".format(generator))

    params_fixture = scenario.get("paramsFixture")
    params = load_params_fixture(str(params_fixture)) if params_fixture else None
    payload = params.get("params") if isinstance(params, dict) and isinstance(params.get("params"), dict) else params
    bridge_result = runner(payload)

    snapshot_dicts = snapshots_from_generator_result(generator, bridge_result)
    snapshots = [build_panel_snapshot_from_dict(item) for item in snapshot_dicts]
    panel_map = {snap.panelId: snap for snap in snapshots}
    return {
        "generator": generator,
        "scenarioId": scenario.get("scenarioId"),
        "bridgeResult": bridge_result,
        "snapshots": snapshots,
        "panelMap": panel_map,
    }


def _relationship_between(panel_map: Dict[str, Any], panel_a_id: str, panel_b_id: str):
    if panel_a_id not in panel_map:
        raise KeyError("Missing panelAId {}".format(panel_a_id))
    if panel_b_id not in panel_map:
        raise KeyError("Missing panelBId {}".format(panel_b_id))
    return classify_pair(panel_map[panel_a_id], panel_map[panel_b_id])


def _assert_bbox_candidate(relationship) -> List[str]:
    errors: List[str] = []
    verification = relationship.verification.to_dict() if relationship.verification else {}
    if relationship.detectionMethod != DETECTION_METHOD_BBOX_AABB:
        errors.append("detectionMethod expected bbox_aabb got {}".format(relationship.detectionMethod))
    if verification.get("level") != "bbox_candidate":
        errors.append("verification.level expected bbox_candidate got {}".format(verification.get("level")))
    if verification.get("safeForPreview") is not True:
        errors.append("safeForPreview expected true")
    if verification.get("safeForCut") is not False:
        errors.append("safeForCut expected false")
    if verification.get("requiresManualConfirmation") is not True:
        errors.append("requiresManualConfirmation expected true")
    return errors


def evaluate_generator_relationship_scenario(scenario: Dict[str, Any]) -> Dict[str, Any]:
    errors: List[str] = []
    pair_results: List[Dict[str, Any]] = []
    context = _run_generator_scenario(scenario)
    snapshots = context["snapshots"]
    panel_map = context["panelMap"]

    min_panel_count = int(scenario.get("minPanelCount") or 0)
    if len(snapshots) < min_panel_count:
        errors.append(
            "panelCount {} < minPanelCount {}".format(len(snapshots), min_panel_count)
        )

    _, non_none = scan_relationships(snapshots, include_none=False)
    min_non_none = int(scenario.get("minNonNoneRelationships") or 0)
    if len(non_none) < min_non_none:
        errors.append(
            "nonNoneRelationshipCount {} < minNonNoneRelationships {}".format(len(non_none), min_non_none)
        )

    for pair_case in scenario.get("pairs") or []:
        case_id = str(pair_case.get("caseId") or "")
        panel_a_id = str(pair_case.get("panelAId") or "")
        panel_b_id = str(pair_case.get("panelBId") or "")
        expected = str(pair_case.get("expectedGeometryType") or "")
        case_errors: List[str] = []
        try:
            relationship = _relationship_between(panel_map, panel_a_id, panel_b_id)
            actual = relationship.geometryType
            if actual != expected:
                case_errors.append(
                    "expected geometryType {} got {}".format(expected, actual)
                )
            case_errors.extend(_assert_bbox_candidate(relationship))
        except KeyError as ex:
            case_errors.append(str(ex))

        matched = not case_errors
        if case_errors:
            errors.extend(["{}: {}".format(case_id, item) for item in case_errors])
        pair_results.append(
            {
                "caseId": case_id,
                "panelAId": panel_a_id,
                "panelBId": panel_b_id,
                "expectedGeometryType": expected,
                "matched": matched,
                "errors": case_errors,
            }
        )

    return {
        "scenarioId": scenario.get("scenarioId"),
        "generator": scenario.get("generator"),
        "panelCount": len(snapshots),
        "nonNoneRelationshipCount": len(non_none),
        "pairResults": pair_results,
        "ok": not errors,
        "errors": errors,
    }


def evaluate_all_generator_relationship_scenarios() -> Dict[str, Any]:
    reports = [evaluate_generator_relationship_scenario(scenario) for scenario in list_generator_relationship_scenarios()]
    return {
        "ok": all(report.get("ok") for report in reports),
        "scenarioCount": len(reports),
        "reports": reports,
    }
