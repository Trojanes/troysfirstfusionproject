import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
if str(REL_DIR) not in sys.path:
    sys.path.insert(0, str(REL_DIR))

from relationship_fixtures import build_fixture_snapshots, evaluate_fixture_expectations, expected_fixture_cases  # noqa: E402
from relationship_geometry import calculate_confidence, classify_pair  # noqa: E402
from relationship_models import BBoxMm, PanelSnapshot  # noqa: E402


def _panel(panel_id, bbox, board_type=None, role=None, thickness_axis="UNKNOWN", thickness_mm=None):
    snapshot = PanelSnapshot(
        panelId=panel_id,
        bodyName=panel_id,
        bbox=bbox,
        boardType=board_type,
        role=role,
        sizeX=bbox.size_x,
        sizeY=bbox.size_y,
        sizeZ=bbox.size_z,
        thicknessAxis=thickness_axis,
        thicknessMm=thickness_mm,
    )
    return snapshot


class RelationshipClassificationTests(unittest.TestCase):
    def test_edge_to_surface_classification(self):
        z = 12000.0
        surface = _panel("REL_SURFACE_B", BBoxMm(0, 300, 0, 300, z, z + 16), board_type="carcass_panel", thickness_axis="Z", thickness_mm=16)
        edge = _panel("REL_EDGE_A", BBoxMm(0, 300, 300, 315, z, z + 300), board_type="structural_edge", thickness_axis="Y", thickness_mm=15)
        rel = classify_pair(edge, surface)
        self.assertEqual(rel.geometryType, "edge_to_surface")
        self.assertEqual(rel.relationshipType, "structural_butt_joint")
        self.assertEqual(rel.roles.hostPanelId, "REL_SURFACE_B")
        self.assertEqual(rel.roles.targetPanelId, "REL_EDGE_A")
        self.assertEqual(rel.detectionMethod, "bbox_aabb")
        self.assertEqual(rel.verification.level, "bbox_candidate")
        self.assertTrue(rel.verification.safeForPreview)
        self.assertFalse(rel.verification.safeForCut)
        self.assertTrue(rel.verification.requiresManualConfirmation)

    def test_all_classified_relationships_are_bbox_candidates(self):
        panels = {panel.panelId: panel for panel in build_fixture_snapshots()}
        for fixture in expected_fixture_cases():
            rel = classify_pair(panels[fixture["panelAId"]], panels[fixture["panelBId"]])
            self.assertEqual(rel.detectionMethod, "bbox_aabb")
            self.assertEqual(rel.verification.level, "bbox_candidate")
            self.assertTrue(rel.verification.safeForPreview)
            self.assertFalse(rel.verification.safeForCut)

    def test_surface_to_surface_classification(self):
        z = 12000.0
        a = _panel("REL_SURFACE_A", BBoxMm(500, 800, 0, 300, z, z + 16), thickness_axis="Z", thickness_mm=16)
        b = _panel("REL_SURFACE_B2", BBoxMm(500, 800, 0, 300, z + 16, z + 32), thickness_axis="Z", thickness_mm=16)
        rel = classify_pair(a, b)
        self.assertEqual(rel.geometryType, "surface_to_surface")
        self.assertEqual(rel.relationshipType, "face_contact")
        # Equal contact-plane areas → lexicographically smaller panelId is host.
        self.assertEqual(rel.roles.hostPanelId, "REL_SURFACE_A")
        self.assertEqual(rel.roles.targetPanelId, "REL_SURFACE_B2")

    def test_surface_to_surface_larger_face_is_host(self):
        z = 12000.0
        small = _panel("SMALL", BBoxMm(0, 100, 0, 100, z, z + 16), thickness_axis="Z", thickness_mm=16)
        large = _panel("LARGE", BBoxMm(0, 200, 0, 200, z + 16, z + 32), thickness_axis="Z", thickness_mm=16)
        rel = classify_pair(small, large)
        self.assertEqual(rel.geometryType, "surface_to_surface")
        self.assertEqual(rel.roles.hostPanelId, "LARGE")
        self.assertEqual(rel.roles.targetPanelId, "SMALL")

    def test_gap_parallel_classification(self):
        z = 12000.0
        door = _panel("REL_GAP_A", BBoxMm(1000, 1300, 0, 300, z, z + 16), board_type="door_panel", role="door", thickness_axis="Z", thickness_mm=16)
        carcass = _panel("REL_GAP_B", BBoxMm(1000, 1300, 0, 300, z + 20, z + 36), board_type="carcass_side", role="carcass", thickness_axis="Z", thickness_mm=16)
        rel = classify_pair(door, carcass)
        self.assertEqual(rel.geometryType, "gap_parallel")
        self.assertEqual(rel.relationshipType, "door_to_carcass_candidate")
        self.assertEqual(rel.roles.hostPanelId, "REL_GAP_A")
        self.assertEqual(rel.roles.targetPanelId, "REL_GAP_B")

    def test_near_contact_within_one_mm_is_contact(self):
        """Shop rule: separation <= 1mm counts as contact, not gap_parallel."""
        from relationship_geometry import CONTACT_TOLERANCE_MM

        self.assertEqual(CONTACT_TOLERANCE_MM, 1.0)
        z = 12000.0
        surface = _panel(
            "NEAR_SURFACE",
            BBoxMm(0, 300, 0, 300, z, z + 16),
            board_type="carcass_panel",
            thickness_axis="Z",
            thickness_mm=16,
        )
        # Edge board sits 1.0mm past the surface face (Y gap = 1.0).
        edge = _panel(
            "NEAR_EDGE",
            BBoxMm(0, 300, 301, 316, z, z + 300),
            board_type="structural_edge",
            thickness_axis="Y",
            thickness_mm=15,
        )
        rel = classify_pair(edge, surface)
        self.assertEqual(rel.geometryType, "edge_to_surface")
        self.assertLessEqual(rel.contact.distanceMm, CONTACT_TOLERANCE_MM)
        self.assertEqual(rel.contact.distanceMm, 1.0)

    def test_gap_just_over_one_mm_is_gap_parallel(self):
        z = 12000.0
        door = _panel(
            "GAP_A",
            BBoxMm(1000, 1300, 0, 300, z, z + 16),
            board_type="door_panel",
            role="door",
            thickness_axis="Z",
            thickness_mm=16,
        )
        # 1.01mm clearance — must remain gap, not contact.
        carcass = _panel(
            "GAP_B",
            BBoxMm(1000, 1300, 0, 300, z + 17.01, z + 33.01),
            board_type="carcass_side",
            role="carcass",
            thickness_axis="Z",
            thickness_mm=16,
        )
        rel = classify_pair(door, carcass)
        self.assertEqual(rel.geometryType, "gap_parallel")
        self.assertGreater(rel.contact.distanceMm, 1.0)

    def test_intersection_classification(self):
        z = 12000.0
        a = _panel("REL_COLLISION_A", BBoxMm(1500, 1800, 0, 300, z, z + 200))
        b = _panel("REL_COLLISION_B", BBoxMm(1600, 1900, 50, 250, z + 50, z + 150))
        rel = classify_pair(a, b)
        self.assertEqual(rel.geometryType, "intersection")
        self.assertEqual(rel.relationshipType, "collision")
        self.assertFalse(rel.validation.ok)

    def test_no_contact_classification(self):
        z = 12000.0
        a = _panel("REL_NONE_A", BBoxMm(2000, 2200, 0, 200, z, z + 16))
        b = _panel("REL_NONE_B", BBoxMm(2400, 2600, 0, 200, z, z + 16))
        rel = classify_pair(a, b)
        self.assertEqual(rel.geometryType, "none")

    def test_missing_metadata_warning(self):
        z = 12000.0
        a = _panel("A", BBoxMm(0, 100, 0, 100, z, z + 16), thickness_axis="Z", thickness_mm=16)
        b = _panel("B", BBoxMm(0, 100, 0, 100, z + 16, z + 32), thickness_axis="Z", thickness_mm=16)
        rel = classify_pair(a, b)
        self.assertTrue(any("Missing boardType metadata" in warning for warning in rel.validation.warnings))

    def test_confidence_calculation(self):
        confidence = calculate_confidence("edge_to_surface", 12000, [], False, False)
        self.assertGreaterEqual(confidence, 0.8)
        lowered = calculate_confidence("edge_to_surface", 50, ["warn"], True, True)
        self.assertLess(lowered, confidence)

    def test_fixture_expectations(self):
        report = evaluate_fixture_expectations(include_none=True)
        self.assertTrue(report["ok"], report)
        self.assertEqual(report["relationshipCount"], 5)
        matched = {item["caseId"]: item["matched"] for item in report["expectedFixtures"]}
        self.assertTrue(all(matched.values()), matched)

    def test_scan_relationships_filters_none_by_default(self):
        panels = build_fixture_snapshots()
        panel_map = {panel.panelId: panel for panel in panels}
        relationships = []
        for fixture in expected_fixture_cases():
            rel = classify_pair(panel_map[fixture["panelAId"]], panel_map[fixture["panelBId"]])
            if rel.geometryType != "none":
                relationships.append(rel)
        self.assertEqual(len(relationships), 4)


if __name__ == "__main__":
    unittest.main()
