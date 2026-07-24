"""Tests for M5 face-level relationship verification."""

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HW_DIR = ROOT / "modules" / "hardware"
REL_DIR = ROOT / "modules" / "relationships"
for path in (HW_DIR, REL_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from relationship_fixtures import build_fixture_snapshots, expected_fixture_cases  # noqa: E402
from relationship_geometry import classify_pair  # noqa: E402
from relationship_models import upgrade_relationship_with_face_verification  # noqa: E402
from face_verification import (  # noqa: E402
    apply_face_verification_to_relationship,
    extract_axis_aligned_faces_from_panel,
    verify_fixture_pair_offline,
    verify_pair_faces,
)
from screw_hole_from_relationship import (  # noqa: E402
    assert_safe_for_cut,
    validate_relationship_for_cut,
)


class FaceVerificationTests(unittest.TestCase):
    def _fixture_relationship(self, case_id: str):
        panels = build_fixture_snapshots()
        panel_map = {panel.panelId: panel for panel in panels}
        case = next(item for item in expected_fixture_cases() if item["caseId"] == case_id)
        return classify_pair(panel_map[case["panelAId"]], panel_map[case["panelBId"]]).to_dict()

    def _fixture_panel_dict(self, panel_id: str):
        panels = build_fixture_snapshots()
        panel = next(item for item in panels if item.panelId == panel_id)
        return panel.to_dict()

    def test_extract_axis_aligned_faces_count(self):
        panel = self._fixture_panel_dict("REL_SURFACE_B")
        faces = extract_axis_aligned_faces_from_panel(panel)
        self.assertEqual(len(faces), 6)
        classes = {face["faceClass"] for face in faces}
        self.assertIn("SURFACE", classes)
        self.assertIn("EDGE", classes)

    def test_edge_to_surface_fixture_passes_face_verification(self):
        rel = self._fixture_relationship("edge_to_surface_001")
        panel_a = self._fixture_panel_dict("REL_EDGE_A")
        panel_b = self._fixture_panel_dict("REL_SURFACE_B")
        report = verify_fixture_pair_offline(panel_a, panel_b, rel)
        self.assertTrue(report["ok"], report.get("errors"))
        self.assertEqual(report["faceMatch"]["matchedFaceAId"], "REL_EDGE_A::-Y")
        self.assertEqual(report["faceMatch"]["matchedFaceBId"], "REL_SURFACE_B::+Y")

    def test_surface_to_surface_fixture_passes_face_verification(self):
        rel = self._fixture_relationship("surface_to_surface_001")
        panel_a = self._fixture_panel_dict("REL_SURFACE_A")
        panel_b = self._fixture_panel_dict("REL_SURFACE_B2")
        report = verify_fixture_pair_offline(panel_a, panel_b, rel)
        self.assertTrue(report["ok"], report.get("errors"))
        self.assertEqual(
            {report["faceMatch"]["matchedFaceAClass"], report["faceMatch"]["matchedFaceBClass"]},
            {"SURFACE", "SURFACE"},
        )

    def test_gap_parallel_fixture_rejected(self):
        rel = self._fixture_relationship("gap_parallel_001")
        panel_a = self._fixture_panel_dict("REL_GAP_A")
        panel_b = self._fixture_panel_dict("REL_GAP_B")
        report = verify_fixture_pair_offline(panel_a, panel_b, rel)
        self.assertFalse(report["ok"])

    def test_near_contact_one_mm_passes_face_verification(self):
        """Face verify uses the same shop contact tolerance (≤1mm)."""
        from relationship_geometry import CONTACT_TOLERANCE_MM
        from relationship_models import BBoxMm, PanelSnapshot

        z = 12000.0
        surface = PanelSnapshot(
            panelId="NEAR_SURFACE",
            bodyName="NEAR_SURFACE",
            bbox=BBoxMm(0, 300, 0, 300, z, z + 16),
            boardType="carcass_panel",
            sizeX=300,
            sizeY=300,
            sizeZ=16,
            thicknessAxis="Z",
            thicknessMm=16,
        )
        edge = PanelSnapshot(
            panelId="NEAR_EDGE",
            bodyName="NEAR_EDGE",
            bbox=BBoxMm(0, 300, 301, 316, z, z + 300),
            boardType="structural_edge",
            sizeX=300,
            sizeY=15,
            sizeZ=300,
            thicknessAxis="Y",
            thicknessMm=15,
        )
        rel = classify_pair(edge, surface).to_dict()
        self.assertEqual(rel["geometryType"], "edge_to_surface")
        report = verify_fixture_pair_offline(edge.to_dict(), surface.to_dict(), rel)
        self.assertTrue(report["ok"], report.get("errors"))
        self.assertLessEqual(float(report["faceMatch"]["planeDistanceMm"]), CONTACT_TOLERANCE_MM)

    def test_intersection_fixture_rejected(self):
        rel = self._fixture_relationship("intersection_collision_001")
        panel_a = self._fixture_panel_dict("REL_COLLISION_A")
        panel_b = self._fixture_panel_dict("REL_COLLISION_B")
        report = verify_fixture_pair_offline(panel_a, panel_b, rel)
        self.assertFalse(report["ok"])

    def test_apply_face_verification_upgrades_relationship(self):
        rel = self._fixture_relationship("edge_to_surface_001")
        panel_a = self._fixture_panel_dict("REL_EDGE_A")
        panel_b = self._fixture_panel_dict("REL_SURFACE_B")
        report = verify_fixture_pair_offline(panel_a, panel_b, rel)
        upgraded = apply_face_verification_to_relationship(rel, report)
        self.assertEqual(upgraded["verification"]["level"], "face_verified")
        self.assertTrue(upgraded["verification"]["safeForCut"])
        self.assertEqual(upgraded["faceMatch"]["matchedFaceAId"], report["faceMatch"]["matchedFaceAId"])

    def test_face_verified_relationship_is_cut_safe(self):
        rel = self._fixture_relationship("edge_to_surface_001")
        panel_a = self._fixture_panel_dict("REL_EDGE_A")
        panel_b = self._fixture_panel_dict("REL_SURFACE_B")
        report = verify_fixture_pair_offline(panel_a, panel_b, rel)
        upgraded = upgrade_relationship_with_face_verification(rel, report["faceMatch"])
        self.assertIsNone(validate_relationship_for_cut(upgraded))
        self.assertIsNone(assert_safe_for_cut(upgraded))

    def test_bbox_candidate_still_blocked_for_cut(self):
        rel = self._fixture_relationship("edge_to_surface_001")
        self.assertIsNotNone(validate_relationship_for_cut(rel))
        self.assertIsNotNone(assert_safe_for_cut(rel))

    def test_brep_bounds_helpers_clamp_and_aabb(self):
        from face_verification_fusion import bounds_mm_from_points, clamp_bounds_to_panel

        bounds = bounds_mm_from_points([(0, 0, 0), (100, 40, 5), (20, 10, 2)])
        self.assertEqual(bounds["x0"], 0)
        self.assertEqual(bounds["x1"], 100)
        self.assertEqual(bounds["y0"], 0)
        self.assertEqual(bounds["y1"], 40)
        panel = {"x0": 10, "x1": 90, "y0": 5, "y1": 50, "z0": 0, "z1": 10}
        clamped = clamp_bounds_to_panel(bounds, panel)
        self.assertEqual(clamped["x0"], 10)
        self.assertEqual(clamped["x1"], 90)
        self.assertEqual(clamped["y0"], 5)
        self.assertEqual(clamped["y1"], 40)

    def test_prefer_outer_loop_vertices_for_face_bounds(self):
        from face_verification_fusion import select_face_bound_points

        vertices = [(0, 0, 0), (100, 0, 0), (100, 40, 0), (0, 40, 0)]
        samples = [(10, 10, 0), (90, 30, 0)]
        points, source = select_face_bound_points(vertices, samples)
        self.assertEqual(source, "outer_loop_vertices")
        self.assertEqual(points, vertices)

        points, source = select_face_bound_points([], samples)
        self.assertEqual(source, "edge_sample_aabb")
        self.assertEqual(points, samples)

        points, source = select_face_bound_points([(0, 0, 0)], [])
        self.assertEqual(source, "none")
        self.assertEqual(points, [])


if __name__ == "__main__":
    unittest.main()
