#!/usr/bin/env python3
"""Offline gate for Kitchen / GT / Lounge generator_declared (bridge → reconcile → preview)."""

from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for path in (
    ROOT,
    os.path.join(ROOT, "modules", "hardware"),
    os.path.join(ROOT, "modules", "relationships"),
):
    if path not in sys.path:
        sys.path.insert(0, path)


CASES = (
    ("kitchen", "kitchen_base.json", "kt_b1_b3_bottom_rail_to_deck", 2),
    ("general_tall", "general_tall_base.json", "gt_b1_b3_bottom_rail_to_deck", 4),
    ("lounge", "lounge_l_shape.json", "lg_main_front_to_top", 3),
)


def _fail(step: str, detail) -> int:
    print("[FAIL] {} -> {}".format(step, detail))
    return 1


def main() -> int:
    from generator_bridge_runner import GENERATOR_RUNNERS, load_params_fixture
    from generator_declared_service import reconcile_generator_declarations
    from generator_panel_adapter import snapshots_from_generator_result
    from relationship_service import build_panel_snapshot_from_dict
    from screw_hole_from_relationship import preview_screw_holes_from_relationship, validate_relationship_for_cut

    smoke_path = os.path.join(ROOT, "declared_generators_connect_smoke.py")
    runner_path = os.path.join(
        ROOT, "modules", "relationships", "declared_generators_fusion_smoke_runner.py",
    )
    if not os.path.isfile(smoke_path):
        return _fail("smoke wrapper missing", smoke_path)
    if not os.path.isfile(runner_path):
        return _fail("smoke runner missing", runner_path)
    print("[PASS] Fusion smoke files present")

    for generator, fixture, declaration_id, min_geom in CASES:
        bridge = GENERATOR_RUNNERS[generator](load_params_fixture(fixture))
        decls = bridge.get("relationshipDeclarations") or []
        ids = {item.get("declarationId") for item in decls if isinstance(item, dict)}
        if declaration_id not in ids:
            return _fail("{} bridge emit".format(generator), "missing {}".format(declaration_id))
        snapshots = [
            build_panel_snapshot_from_dict(item)
            for item in snapshots_from_generator_result(generator, bridge)
        ]
        report = reconcile_generator_declarations(snapshots, generator=generator)
        if not report.get("ok"):
            return _fail("{} reconcile".format(generator), report.get("errors"))
        if int(report.get("geometryOkCount") or 0) < min_geom:
            return _fail(
                "{} geometryOkCount".format(generator),
                "{} < {}".format(report.get("geometryOkCount"), min_geom),
            )
        rel = next(
            (
                item.get("relationship")
                for item in report.get("reconciled") or []
                if item.get("declarationId") == declaration_id
            ),
            None,
        )
        if not isinstance(rel, dict):
            return _fail("{} find declaration".format(generator), declaration_id)
        panel_map = {snap.panelId: snap.to_dict() for snap in snapshots}
        roles = rel.get("roles") or {}
        host_id = roles.get("hostPanelId")
        target_id = roles.get("targetPanelId")
        panel_snapshots = {host_id: panel_map[host_id], target_id: panel_map[target_id]}
        if validate_relationship_for_cut(rel) is not None:
            return _fail("{} cut gate".format(generator), validate_relationship_for_cut(rel))
        preview = preview_screw_holes_from_relationship(rel, panel_snapshots=panel_snapshots)
        if not preview.get("ok"):
            return _fail("{} preview".format(generator), preview)
        print("[PASS] {} emit+reconcile+preview ({})".format(generator, declaration_id))

    print()
    print("Declared generators offline: ALL PASS")
    print("Fusion Play: close Fusion, then:")
    print("  python scripts/manage_fusion_smokes.py install --batch declared")
    print("Prefer a blank / new design (leftover cabinets confuse assembly scope).")
    print("Restart Fusion → Shift+S → Play declared_generators_connect_smoke")
    print("After PASS: python scripts/manage_fusion_smokes.py remove --batch declared")
    return 0


if __name__ == "__main__":
    sys.exit(main())
