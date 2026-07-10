"""M9 — hardware type registry and relationship-based rule dispatch."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

HARDWARE_TYPE_SCREW_HOLE = "screw_hole"
HARDWARE_TYPE_TONGUE_GROOVE = "tongue_groove"
HARDWARE_TYPE_HINGE_HOLE = "hinge_hole"
HARDWARE_TYPE_LOCK_CUTOUT = "lock_cutout"
HARDWARE_TYPE_DRAWER_RUNNER_HOLE = "drawer_runner_hole"

IMPLEMENTED_TYPES = {
    HARDWARE_TYPE_SCREW_HOLE,
    HARDWARE_TYPE_TONGUE_GROOVE,
    HARDWARE_TYPE_HINGE_HOLE,
    HARDWARE_TYPE_LOCK_CUTOUT,
    HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
}
PREVIEW_READY_TYPES: set = set()
PREVIEW_ONLY_TYPES: set = set()

HARDWARE_TYPE_UI: Dict[str, Dict[str, Any]] = {
    HARDWARE_TYPE_SCREW_HOLE: {
        "label": "螺丝孔",
        "status": "implemented",
        "description": "边对面结构对接螺丝孔（可切削）。",
    },
    HARDWARE_TYPE_TONGUE_GROOVE: {
        "label": "榫槽",
        "status": "implemented",
        "description": "边对面榫槽：宿主开槽 + 目标榫肩（可切削）。",
    },
    HARDWARE_TYPE_HINGE_HOLE: {
        "label": "铰链杯孔",
        "status": "implemented",
        "description": "宿主板铰链杯孔（默认 Ø35×13，可切削）。",
    },
    HARDWARE_TYPE_LOCK_CUTOUT: {
        "label": "锁孔口袋",
        "status": "implemented",
        "description": "宿主板锁孔口袋（默认 22×40×12，可切削）。",
    },
    HARDWARE_TYPE_DRAWER_RUNNER_HOLE: {
        "label": "抽屉滑轨孔",
        "status": "implemented",
        "description": "宿主板滑轨安装孔（默认 Ø5×12，可切削）。",
    },
}

def normalize_hardware_type(rule: Optional[Dict[str, Any]]) -> str:
    if not isinstance(rule, dict):
        return HARDWARE_TYPE_SCREW_HOLE
    return str(rule.get("type") or HARDWARE_TYPE_SCREW_HOLE).strip().lower()


def list_hardware_types() -> List[Dict[str, Any]]:
    rows = []
    for key in (
        HARDWARE_TYPE_SCREW_HOLE,
        HARDWARE_TYPE_TONGUE_GROOVE,
        HARDWARE_TYPE_HINGE_HOLE,
        HARDWARE_TYPE_LOCK_CUTOUT,
        HARDWARE_TYPE_DRAWER_RUNNER_HOLE,
    ):
        meta = dict(HARDWARE_TYPE_UI.get(key) or {})
        meta["type"] = key
        meta["implemented"] = key in IMPLEMENTED_TYPES
        meta["previewOnly"] = key in PREVIEW_ONLY_TYPES or key in PREVIEW_READY_TYPES
        meta["previewReady"] = key in IMPLEMENTED_TYPES or key in PREVIEW_READY_TYPES
        meta["cutReady"] = key in IMPLEMENTED_TYPES
        rows.append(meta)
    return rows


def evaluate_hardware_rule(
    hardware_type: str,
    relationship: Optional[Dict[str, Any]],
    *,
    action: str = "preview",
) -> Dict[str, Any]:
    action_key = str(action or "preview").strip().lower()
    hw_type = str(hardware_type or HARDWARE_TYPE_SCREW_HOLE).strip().lower()
    if not relationship:
        return {"ok": False, "hardwareType": hw_type, "action": action_key, "errors": ["No relationship selected."]}

    if hw_type in IMPLEMENTED_TYPES:
        from connect_formal_ui import evaluate_connect_action

        mapped = "preview" if action_key in (
            "preview",
            "preview_screw_holes",
            "preview_tongue_groove",
            "preview_hinge_holes",
            "preview_lock_cutout",
            "preview_drawer_runner_holes",
        ) else action_key
        if action_key in (
            "cut",
            "create_cut",
            "create_screw_holes",
            "create_tongue_groove",
            "create_hinge_holes",
            "create_lock_cutout",
            "create_drawer_runner_holes",
        ):
            mapped = "cut"
        if action_key in ("confirm", "confirm_for_cut"):
            mapped = "confirm"
        gate = evaluate_connect_action(mapped, relationship)
        gate["hardwareType"] = hw_type
        return gate

    if hw_type in PREVIEW_ONLY_TYPES or hw_type in PREVIEW_READY_TYPES:
        if action_key in ("cut", "create_cut", "create_screw_holes", "create_tongue_groove"):
            return {
                "ok": False,
                "hardwareType": hw_type,
                "action": action_key,
                "errors": [
                    "Hardware type '{}' is not cut-ready (preview only).".format(hw_type)
                ],
                "previewOnly": True,
                "cutReady": False,
            }
        if hw_type in PREVIEW_READY_TYPES:
            from connect_formal_ui import evaluate_connect_action

            gate = evaluate_connect_action("preview", relationship)
            gate["hardwareType"] = hw_type
            gate["previewOnly"] = True
            gate["cutReady"] = False
            return gate
        return {
            "ok": False,
            "hardwareType": hw_type,
            "action": action_key,
            "errors": ["Hardware type '{}' preview is not implemented yet.".format(hw_type)],
            "previewOnly": True,
            "scaffold": True,
        }

    return {
        "ok": False,
        "hardwareType": hw_type,
        "action": action_key,
        "errors": ["Unsupported hardware type: {}.".format(hw_type)],
    }


def dispatch_hardware_preview(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    hw_type = normalize_hardware_type(rule)
    gate = evaluate_hardware_rule(hw_type, relationship, action="preview")
    if not gate.get("ok"):
        return {
            "ok": False,
            "hardwareType": hw_type,
            "errors": list(gate.get("errors") or ["Preview gate blocked."]),
            "gate": gate,
            "previewOnly": bool(gate.get("previewOnly")),
            "cutReady": False,
        }
    if hw_type == HARDWARE_TYPE_SCREW_HOLE:
        from screw_hole_from_relationship import preview_screw_holes_from_relationship

        report = preview_screw_holes_from_relationship(relationship, rule=rule, panel_snapshots=panel_snapshots)
        report["hardwareType"] = hw_type
        return report
    if hw_type == HARDWARE_TYPE_TONGUE_GROOVE:
        from tongue_groove_from_relationship import preview_tongue_groove_from_relationship

        report = preview_tongue_groove_from_relationship(relationship, rule=rule, panel_snapshots=panel_snapshots)
        report["hardwareType"] = hw_type
        return report
    if hw_type == HARDWARE_TYPE_HINGE_HOLE:
        from scaffold_hardware_from_relationship import preview_hinge_holes_from_relationship

        report = preview_hinge_holes_from_relationship(relationship, rule=rule, panel_snapshots=panel_snapshots)
        report["hardwareType"] = hw_type
        return report
    if hw_type == HARDWARE_TYPE_LOCK_CUTOUT:
        from scaffold_hardware_from_relationship import preview_lock_cutout_from_relationship

        report = preview_lock_cutout_from_relationship(relationship, rule=rule, panel_snapshots=panel_snapshots)
        report["hardwareType"] = hw_type
        return report
    if hw_type == HARDWARE_TYPE_DRAWER_RUNNER_HOLE:
        from scaffold_hardware_from_relationship import preview_drawer_runner_holes_from_relationship

        report = preview_drawer_runner_holes_from_relationship(relationship, rule=rule, panel_snapshots=panel_snapshots)
        report["hardwareType"] = hw_type
        return report
    return gate


def dispatch_hardware_cut_plan(
    relationship: Dict[str, Any],
    rule: Optional[Dict[str, Any]] = None,
    panel_snapshots: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    hw_type = normalize_hardware_type(rule)
    gate = evaluate_hardware_rule(hw_type, relationship, action="cut")
    if not gate.get("ok"):
        return {
            "ok": False,
            "hardwareType": hw_type,
            "errors": list(gate.get("errors") or ["Cut gate blocked."]),
            "gate": gate,
            "previewOnly": bool(gate.get("previewOnly")),
            "cutReady": False,
        }
    if hw_type == HARDWARE_TYPE_SCREW_HOLE:
        from screw_hole_from_relationship import plan_screw_hole_cut_from_relationship

        report = plan_screw_hole_cut_from_relationship(relationship, rule=rule, panel_snapshots=panel_snapshots)
        report["hardwareType"] = hw_type
        return report
    if hw_type == HARDWARE_TYPE_TONGUE_GROOVE:
        from tongue_groove_from_relationship import plan_tongue_groove_cut_from_relationship

        report = plan_tongue_groove_cut_from_relationship(relationship, rule=rule, panel_snapshots=panel_snapshots)
        report["hardwareType"] = hw_type
        return report
    if hw_type == HARDWARE_TYPE_HINGE_HOLE:
        from scaffold_hardware_from_relationship import plan_hinge_hole_cut_from_relationship

        report = plan_hinge_hole_cut_from_relationship(relationship, rule=rule, panel_snapshots=panel_snapshots)
        report["hardwareType"] = hw_type
        return report
    if hw_type == HARDWARE_TYPE_DRAWER_RUNNER_HOLE:
        from scaffold_hardware_from_relationship import plan_drawer_runner_hole_cut_from_relationship

        report = plan_drawer_runner_hole_cut_from_relationship(relationship, rule=rule, panel_snapshots=panel_snapshots)
        report["hardwareType"] = hw_type
        return report
    if hw_type == HARDWARE_TYPE_LOCK_CUTOUT:
        from scaffold_hardware_from_relationship import plan_lock_cutout_from_relationship

        report = plan_lock_cutout_from_relationship(relationship, rule=rule, panel_snapshots=panel_snapshots)
        report["hardwareType"] = hw_type
        return report
    return gate
