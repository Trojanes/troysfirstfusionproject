"""Configurable gap joints (default off) — eligibility, batch filters, face verify band."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
HW_DIR = ROOT / "modules" / "hardware"
for path in (HW_DIR, REL_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from batch_hardware_from_relationships import filter_cut_safe_hardware_candidates  # noqa: E402
from connect_formal_ui import (  # noqa: E402
    evaluate_connect_action,
    is_hardware_eligible,
    normalize_gap_joints_settings,
)
from face_verification import (  # noqa: E402
    filter_face_verifiable_candidates,
    verify_fixture_pair_offline,
)
from relationship_fixtures import build_fixture_snapshots  # noqa: E402
from relationship_geometry import classify_pair  # noqa: E402
from relationship_service import scan_relationships  # noqa: E402


def _gap_enabled(**overrides):
    settings = {
        "enabled": True,
        "minGapMm": 1.0,
        "maxGapMm": 20.0,
        "includeInBatch": True,
    }
    settings.update(overrides)
    return normalize_gap_joints_settings(settings)


class GapJointsTests(unittest.TestCase):
    def _fixture_scan(self):
        panels = build_fixture_snapshots()
        panel_list, relationships = scan_relationships(panels, include_none=False)
        panel_map = {panel.panelId: panel.to_dict() for panel in panel_list}
        rels = [rel.to_dict() for rel in relationships]
        return panel_map, rels

    def _gap_rel(self, rels):
        return next(rel for rel in rels if rel.get("geometryType") == "gap_parallel")

    def test_default_gap_settings_disabled(self):
        settings = normalize_gap_joints_settings(None)
        self.assertFalse(settings["enabled"])
        self.assertEqual(settings["minGapMm"], 1.0)
        self.assertEqual(settings["maxGapMm"], 20.0)
        self.assertFalse(settings["includeInBatch"])

    def test_gap_roles_assigned_on_scan(self):
        panels = {panel.panelId: panel for panel in build_fixture_snapshots()}
        door = panels["REL_GAP_A"]
        carcass = panels["REL_GAP_B"]
        rel = classify_pair(door, carcass)
        self.assertEqual(rel.geometryType, "gap_parallel")
        self.assertTrue(rel.roles.hostPanelId)
        self.assertTrue(rel.roles.targetPanelId)
        self.assertEqual(rel.roles.hostPanelId, "REL_GAP_A")
        self.assertEqual(rel.roles.targetPanelId, "REL_GAP_B")

    def test_default_off_excludes_gap_from_batch_verify(self):
        _panels, rels = self._fixture_scan()
        accepted = filter_face_verifiable_candidates(rels)
        self.assertTrue(any(rel["geometryType"] != "gap_parallel" for rel in accepted) or accepted)
        self.assertFalse(any(rel["geometryType"] == "gap_parallel" for rel in accepted))
        gap = self._gap_rel(rels)
        self.assertFalse(is_hardware_eligible(gap))
        self.assertFalse(evaluate_connect_action("preview", gap)["ok"])
        self.assertFalse(evaluate_connect_action("confirm", gap)["ok"])

    def test_enabled_includes_gap_in_batch_verify(self):
        _panels, rels = self._fixture_scan()
        settings = _gap_enabled()
        accepted = filter_face_verifiable_candidates(rels, settings)
        gap_ids = {rel["relationshipId"] for rel in accepted if rel["geometryType"] == "gap_parallel"}
        self.assertGreater(len(gap_ids), 0)
        gap = self._gap_rel(rels)
        self.assertTrue(is_hardware_eligible(gap, settings))
        self.assertTrue(evaluate_connect_action("preview", gap, settings)["ok"])
        self.assertTrue(evaluate_connect_action("confirm", gap, settings)["ok"])

    def test_enabled_but_exclude_batch_keeps_single_pair(self):
        _panels, rels = self._fixture_scan()
        settings = _gap_enabled(includeInBatch=False)
        gap = self._gap_rel(rels)
        self.assertTrue(is_hardware_eligible(gap, settings, for_batch=False))
        self.assertFalse(is_hardware_eligible(gap, settings, for_batch=True))
        accepted = filter_face_verifiable_candidates(rels, settings)
        self.assertFalse(any(rel["geometryType"] == "gap_parallel" for rel in accepted))

    def test_gap_face_verify_band_offline(self):
        panel_map, rels = self._fixture_scan()
        gap = self._gap_rel(rels)
        panel_a = panel_map[(gap.get("panelA") or {}).get("panelId")]
        panel_b = panel_map[(gap.get("panelB") or {}).get("panelId")]
        blocked = verify_fixture_pair_offline(panel_a, panel_b, gap)
        self.assertFalse(blocked["ok"])
        enabled = _gap_enabled()
        report = verify_fixture_pair_offline(panel_a, panel_b, gap, gap_settings=enabled)
        self.assertTrue(report["ok"], report)
        out_of_band = _gap_enabled(minGapMm=50.0, maxGapMm=60.0)
        miss = verify_fixture_pair_offline(panel_a, panel_b, gap, gap_settings=out_of_band)
        self.assertFalse(miss["ok"])

    def test_cut_safe_batch_respects_gap_flag(self):
        _panels, rels = self._fixture_scan()
        gap = self._gap_rel(rels)
        gap = dict(gap)
        gap["verification"] = {
            "level": "face_verified",
            "safeForPreview": True,
            "safeForCut": True,
            "requiresManualConfirmation": False,
        }
        self.assertEqual(filter_cut_safe_hardware_candidates([gap]), [])
        accepted = filter_cut_safe_hardware_candidates([gap], _gap_enabled())
        self.assertEqual(len(accepted), 1)


if __name__ == "__main__":
    unittest.main()
