#!/usr/bin/env python3
"""Offline smoke: ConnectHardwareOperation list/upsert/enrich."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (
    ROOT,
    os.path.join(ROOT, "modules", "hardware"),
    os.path.join(ROOT, "panel_attributes"),
):
    if path not in sys.path:
        sys.path.insert(0, path)


def _fail(step: str, detail) -> int:
    print("[FAIL] {} -> {}".format(step, detail))
    return 1


def main() -> int:
    from connect_hardware_operations import (
        STATUS_APPLIED,
        cut_feature_names_for_update,
        enrich_feature_as_operation,
        ensure_relationship_cut_safe_for_update,
        list_operations_from_panel_metadata_map,
        operation_from_feature_record,
        rule_from_feature_record,
        upsert_feature_record,
    )
    from panel_metadata_writeback import append_hardware_feature, build_panel_feature_record

    feature = {
        "featureId": "rel.bp_d0::screw_hole",
        "geometry": {
            "axis": "Y",
            "diameterMm": 4,
            "depthMm": 15,
            "positions": [{"x": 10, "y": 0, "z": 20}, {"x": 90, "y": 0, "z": 20}],
        },
        "sourceRelationshipId": "rel.bp_d0",
        "hostPanelId": "BP",
        "targetPanelId": "D0",
        "source": {"ruleId": "screw_hole_from_edge_to_surface_v1"},
    }
    cut_meta = {
        "operationType": "SCREW_HOLE_FROM_RELATIONSHIP",
        "sourceRelationshipId": "rel.bp_d0",
        "hostPanelId": "BP",
        "targetPanelId": "D0",
        "holeCount": 2,
        "diameterMm": 4,
        "depthMm": 15,
    }
    record = build_panel_feature_record(
        feature, cut_metadata=cut_meta, cut_feature_name="HW_REL_SCREW_HOLE_1"
    )
    relationship = {
        "relationshipId": "rel.bp_d0",
        "roles": {"hostPanelId": "BP", "targetPanelId": "D0"},
        "verification": {"level": "generator_declared", "safeForCut": True},
    }
    rule = {
        "type": "screw_hole",
        "diameterMm": 4,
        "edgeOffsetMm": 30,
        "minSpacingMm": 80,
        "depthMode": "host_thickness",
    }
    record = enrich_feature_as_operation(
        record,
        hardware_type="screw_hole",
        rule=rule,
        relationship=relationship,
    )
    if record.get("operationId") != "rel.bp_d0::screw_hole":
        return _fail("operationId", record.get("operationId"))
    if record.get("status") != STATUS_APPLIED:
        return _fail("status", record.get("status"))
    if record.get("hardwareType") != "screw_hole":
        return _fail("hardwareType", record.get("hardwareType"))
    if not isinstance(record.get("rule"), dict) or record["rule"].get("edgeOffsetMm") != 30:
        return _fail("rule", record.get("rule"))
    print("[PASS] enrich stamps operationId/status/rule")

    op = operation_from_feature_record(record)
    if not op or "BP" not in str(op.get("label") or ""):
        return _fail("operation_from_feature", op)
    print("[PASS] operation_from_feature_record")

    meta = {"schemaVersion": 1, "features": []}
    meta, written, skip = append_hardware_feature(meta, record)
    if not written or skip:
        return _fail("append", (written, skip))
    meta2, written2, skip2 = append_hardware_feature(meta, record)
    if written2 or skip2 != "duplicate_feature":
        return _fail("duplicate skip", (written2, skip2))
    print("[PASS] append skips duplicate without replace")

    updated_rule = dict(rule)
    updated_rule["diameterMm"] = 5
    updated_record = enrich_feature_as_operation(
        dict(record, diameterMm=5, cutFeatureName="HW_REL_SCREW_HOLE_2"),
        hardware_type="screw_hole",
        rule=updated_rule,
        relationship=relationship,
    )
    meta3, written3, skip3 = append_hardware_feature(
        meta2, updated_record, replace_existing=True
    )
    if not written3 or skip3:
        return _fail("replace", (written3, skip3))
    features = meta3.get("features") or []
    if len(features) != 1:
        return _fail("feature count after replace", len(features))
    if float(features[0].get("diameterMm") or 0) != 5:
        return _fail("diameter after replace", features[0].get("diameterMm"))
    if features[0].get("cutFeatureName") != "HW_REL_SCREW_HOLE_2":
        return _fail("cut name after replace", features[0].get("cutFeatureName"))
    print("[PASS] replace_existing upserts same operationId")

    meta4 = upsert_feature_record({"schemaVersion": 1, "features": []}, updated_record)
    six = enrich_feature_as_operation(
        dict(updated_record, diameterMm=6),
        hardware_type="screw_hole",
        rule=dict(updated_rule, diameterMm=6),
        relationship=relationship,
    )
    meta4 = upsert_feature_record(meta4, six)
    ops = list_operations_from_panel_metadata_map({"BP": meta4})
    if len(ops) != 1:
        return _fail("list ops count", ops)
    if float((ops[0].get("rule") or {}).get("diameterMm") or 0) != 6:
        return _fail("list ops diameter", ops[0])
    print("[PASS] list_operations_from_panel_metadata_map")

    unsafe = {
        "relationshipId": "rel.bp_d0",
        "verification": {"level": "bbox_candidate", "safeForCut": False},
    }
    safe = ensure_relationship_cut_safe_for_update(unsafe)
    if not (safe.get("verification") or {}).get("safeForCut"):
        return _fail("ensure cut-safe", safe)
    print("[PASS] ensure_relationship_cut_safe_for_update")

    names = cut_feature_names_for_update(
        {
            "cutFeatureName": "HW_GROOVE_1",
            "tongueFeatureName": "HW_TONGUE_1",
            "tongueFeatureNames": ["HW_TONGUE_1", "HW_TONGUE_2"],
            "featureRecord": {"cutFeatureName": "HW_GROOVE_1"},
        },
        {"tongueFeatureNames": ["HW_TONGUE_2", "HW_TONGUE_3"]},
    )
    if names != ["HW_GROOVE_1", "HW_TONGUE_1", "HW_TONGUE_2", "HW_TONGUE_3"]:
        return _fail("cut feature names", names)
    print("[PASS] cut_feature_names_for_update collects groove+tongue")

    tg_rule = rule_from_feature_record(
        {
            "hardwareType": "tongue_groove",
            "depthMm": 8,
            "widthMm": 4,
            "tongueProtrusionMm": 7,
        }
    )
    if tg_rule.get("grooveDepthMm") != 8 or tg_rule.get("grooveWidthMm") != 4:
        return _fail("tongue rule rebuild", tg_rule)
    print("[PASS] rule_from_feature_record tongue_groove dims")

    plugin = open(
        os.path.join(ROOT, "UnifiedCabinetPlugin.py"), encoding="utf-8"
    ).read()
    for route in (
        "hardware.listHardwareOperations",
        "hardware.updateHardwareOperation",
    ):
        if route not in plugin:
            return _fail("plugin route missing", route)
    print("[PASS] plugin routes registered")

    html = open(os.path.join(ROOT, "palette.html"), encoding="utf-8").read()
    for marker in (
        'data-connect-view="ops"',
        "connectOpsList",
        "connectOpsUpdateBtn",
        "function connectUiShowView(",
        "hardware.listHardwareOperations",
        "hardware.updateHardwareOperation",
    ):
        if marker not in html:
            return _fail("palette marker missing", marker)
    print("[PASS] Connect UI embeds ops tab")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
