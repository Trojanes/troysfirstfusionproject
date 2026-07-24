"""Tests for persisted face_verified relationship marks on panel metadata."""

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
from relationship_fixtures import build_fixture_snapshots  # noqa: E402
from relationship_service import scan_relationships  # noqa: E402
from relationship_verification_store import (  # noqa: E402
    apply_persisted_verification_to_relationship,
    build_persisted_verification_record,
    hydrate_relationships_from_panel_metadata,
    upsert_relationship_verification,
)
from screw_hole_from_relationship import assert_safe_for_cut  # noqa: E402


class RelationshipVerificationStoreTests(unittest.TestCase):
    def _edge_rel(self):
        panels = build_fixture_snapshots()
        _plist, relationships = scan_relationships(panels, include_none=False)
        for rel in relationships:
            data = rel.to_dict()
            if data.get("geometryType") == "edge_to_surface":
                return data
        self.fail("no edge_to_surface fixture relationship")

    def test_upsert_and_hydrate_restores_face_verified(self):
        rel = self._edge_rel()
        self.assertEqual(rel["verification"]["level"], "bbox_candidate")
        self.assertIsNotNone(assert_safe_for_cut(rel))

        rid = rel["relationshipId"]
        panel_a = (rel.get("panelA") or {}).get("panelId")
        record = build_persisted_verification_record(
            rel,
            face_match={"matchedFaceAId": "A", "matchedFaceBId": "B", "method": "test"},
            for_panel_id=panel_a,
        )
        meta_a = upsert_relationship_verification({"schemaVersion": 1, "features": []}, rid, record)
        hydrated = hydrate_relationships_from_panel_metadata([rel], {panel_a: meta_a})
        self.assertEqual(len(hydrated), 1)
        upgraded = hydrated[0]
        self.assertEqual(upgraded["verification"]["level"], "face_verified")
        self.assertTrue(upgraded["verification"]["safeForCut"])
        self.assertTrue(is_cut_allowed(upgraded))
        self.assertTrue(evaluate_connect_action("cut", upgraded).get("ok"))
        self.assertEqual(upgraded["faceMatch"]["matchedFaceAId"], "A")

    def test_does_not_overwrite_generator_declared(self):
        rel = self._edge_rel()
        rel = dict(rel)
        rel["verification"] = {
            "level": "generator_declared",
            "safeForPreview": True,
            "safeForCut": True,
            "requiresManualConfirmation": False,
        }
        record = build_persisted_verification_record(rel, for_panel_id="x")
        out = apply_persisted_verification_to_relationship(rel, record)
        self.assertEqual(out["verification"]["level"], "generator_declared")

    def test_bbox_still_blocked_without_persist(self):
        rel = self._edge_rel()
        hydrated = hydrate_relationships_from_panel_metadata([rel], {})
        self.assertFalse(is_cut_allowed(hydrated[0]))


if __name__ == "__main__":
    unittest.main()
