"""Tests for batch auto face-verify (3a): skip failures, never relax bbox cut gate."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
HW_DIR = ROOT / "modules" / "hardware"
for path in (HW_DIR, REL_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from connect_formal_ui import evaluate_connect_action, is_cut_allowed  # noqa: E402
from face_verification import (  # noqa: E402
    DEFAULT_BATCH_MAX_PAIRS,
    filter_face_verifiable_candidates,
    verify_all_bbox_candidates,
)
from relationship_fixtures import build_fixture_snapshots  # noqa: E402
from relationship_service import scan_relationships  # noqa: E402
from screw_hole_from_relationship import assert_safe_for_cut, validate_relationship_for_cut  # noqa: E402


class FaceVerificationBatchTests(unittest.TestCase):
    def _fixture_scan(self):
        panels = build_fixture_snapshots()
        panel_list, relationships = scan_relationships(panels, include_none=False)
        panel_map = {panel.panelId: panel.to_dict() for panel in panel_list}
        rels = [rel.to_dict() for rel in relationships]
        return panel_map, rels

    def test_filter_keeps_contact_hardware_bbox_only(self):
        from connect_formal_ui import is_contact_hardware_pair

        _panels, rels = self._fixture_scan()
        accepted = filter_face_verifiable_candidates(rels)
        self.assertGreater(len(accepted), 0)
        for rel in accepted:
            self.assertTrue(is_contact_hardware_pair(rel), rel)
            self.assertEqual(rel["verification"]["level"], "bbox_candidate")
            self.assertFalse(rel["verification"]["safeForCut"])
        # gap / intersection must not enter the batch pool
        for rel in rels:
            if rel["geometryType"] in ("gap_parallel", "intersection"):
                self.assertNotIn(rel["relationshipId"], {item["relationshipId"] for item in accepted})
        # surface_to_surface face_contact must be included when present
        s2s = [rel for rel in rels if rel["geometryType"] == "surface_to_surface"]
        if s2s:
            accepted_ids = {item["relationshipId"] for item in accepted}
            for rel in s2s:
                if rel["relationshipType"] == "face_contact":
                    self.assertIn(rel["relationshipId"], accepted_ids)

    def test_batch_verifies_fixture_edge_pairs(self):
        panel_map, rels = self._fixture_scan()
        report = verify_all_bbox_candidates(rels, panel_map)
        self.assertTrue(report["ok"])
        self.assertTrue(report["cutGateUnchanged"])
        self.assertGreaterEqual(report["verifiedCount"], 1)
        self.assertEqual(report["action"], "relationships.verifyAllBboxCandidates")
        for rel in report["verifiedRelationships"]:
            self.assertEqual(rel["verification"]["level"], "face_verified")
            self.assertTrue(rel["verification"]["safeForCut"])
            self.assertIsNone(validate_relationship_for_cut(rel))
            self.assertTrue(is_cut_allowed(rel))
            cut_gate = evaluate_connect_action("cut", rel)
            self.assertTrue(cut_gate["ok"], cut_gate)

    def test_skipped_remain_not_cut_safe(self):
        panel_map, rels = self._fixture_scan()
        # Force skip by wiping panels for one candidate
        candidates = filter_face_verifiable_candidates(rels)
        self.assertGreater(len(candidates), 0)
        target = candidates[0]
        panel_a = (target.get("panelA") or {}).get("panelId")
        broken = dict(panel_map)
        if panel_a in broken:
            del broken[panel_a]
        report = verify_all_bbox_candidates([target], broken)
        self.assertEqual(report["verifiedCount"], 0)
        self.assertEqual(report["skippedCount"], 1)
        self.assertEqual(report["skipped"][0]["reason"], "panel_missing")
        self.assertTrue(any("跳过" in line for line in report["reminders"]))
        self.assertIsNotNone(assert_safe_for_cut(target))
        self.assertFalse(is_cut_allowed(target))
        cut_gate = evaluate_connect_action("cut", target)
        self.assertFalse(cut_gate["ok"])

    def test_max_pairs_cap_skips_overflow(self):
        panel_map, rels = self._fixture_scan()
        candidates = filter_face_verifiable_candidates(rels)
        if len(candidates) < 1:
            self.skipTest("fixture has no edge_to_surface candidates")
        # Duplicate the same candidate to force overflow without depending on fixture size
        padded = list(candidates) + [dict(candidates[0], relationshipId="rel.cap.extra")]
        report = verify_all_bbox_candidates(padded, panel_map, max_pairs=1)
        self.assertEqual(report["maxPairs"], 1)
        self.assertEqual(report["processedCount"], 1)
        self.assertGreaterEqual(report["skippedCount"], 1)
        self.assertTrue(any(item["reason"] == "cap_reached" for item in report["skipped"]))
        self.assertTrue(any("上限" in line for line in report["reminders"]))

    def test_body_not_found_reason_from_extractor(self):
        panel_map, rels = self._fixture_scan()
        candidates = filter_face_verifiable_candidates(rels)
        self.assertGreater(len(candidates), 0)

        def boom(_panel):
            raise RuntimeError("body_not_found: missing")

        report = verify_all_bbox_candidates(candidates[:1], panel_map, extract_faces=boom)
        self.assertEqual(report["verifiedCount"], 0)
        self.assertEqual(report["skipped"][0]["reason"], "body_not_found")

    def test_default_max_pairs_constant(self):
        self.assertEqual(DEFAULT_BATCH_MAX_PAIRS, 200)



if __name__ == "__main__":
    unittest.main()
