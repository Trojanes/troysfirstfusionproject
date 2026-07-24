import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
if str(REL_DIR) not in sys.path:
    sys.path.insert(0, str(REL_DIR))

from relationship_geometry import classify_pair  # noqa: E402
from relationship_models import BBoxMm, PanelSnapshot  # noqa: E402
from relationship_report import build_inspect_pair_report, build_scan_report, relationship_audit_row  # noqa: E402


class RelationshipReportTests(unittest.TestCase):
    def test_relationship_audit_row_contains_required_fields(self):
        panel_a = PanelSnapshot(
            panelId="A",
            bodyName="BODY_A",
            bbox=BBoxMm(0, 300, 0, 300, 0, 16),
            sizeX=300,
            sizeY=300,
            sizeZ=16,
            thicknessAxis="Z",
            thicknessMm=16,
        )
        panel_b = PanelSnapshot(
            panelId="B",
            bodyName="BODY_B",
            bbox=BBoxMm(0, 300, 0, 300, 16, 32),
            sizeX=300,
            sizeY=300,
            sizeZ=16,
            thicknessAxis="Z",
            thicknessMm=16,
        )
        relationship = classify_pair(panel_a, panel_b)
        row = relationship_audit_row(relationship)
        for key in (
            "panelAId",
            "panelBId",
            "geometryType",
            "relationshipType",
            "detectionMethod",
            "verificationLevel",
            "safeForPreview",
            "safeForCut",
            "requiresManualConfirmation",
            "axis",
            "distanceMm",
            "overlapX",
            "overlapY",
            "overlapZ",
            "contactAreaMm2",
            "contactLengthMm",
            "confidence",
            "warnings",
            "errors",
        ):
            self.assertIn(key, row)
        self.assertEqual(row["detectionMethod"], "bbox_aabb")
        self.assertEqual(row["verificationLevel"], "bbox_candidate")
        self.assertTrue(row["safeForPreview"])
        self.assertFalse(row["safeForCut"])
        self.assertTrue(row["requiresManualConfirmation"])

    def test_build_scan_report(self):
        panel_a = PanelSnapshot(
            panelId="A",
            bodyName="BODY_A",
            bbox=BBoxMm(0, 300, 0, 300, 0, 16),
            sizeX=300,
            sizeY=300,
            sizeZ=16,
        )
        panel_b = PanelSnapshot(
            panelId="B",
            bodyName="BODY_B",
            bbox=BBoxMm(0, 300, 0, 300, 16, 32),
            sizeX=300,
            sizeY=300,
            sizeZ=16,
        )
        relationship = classify_pair(panel_a, panel_b)
        report = build_scan_report(
            action="relationships.scan",
            panels=[panel_a, panel_b],
            relationships=[relationship],
            scope="test",
            tolerance_mm=0.5,
        )
        self.assertTrue(report["ok"])
        self.assertEqual(report["panelCount"], 2)
        self.assertEqual(report["relationshipCount"], 1)
        self.assertEqual(len(report["audit"]), 1)

    def test_build_inspect_pair_report(self):
        panel_a = PanelSnapshot(
            panelId="A",
            bodyName="BODY_A",
            bbox=BBoxMm(0, 300, 300, 315, 0, 300),
            sizeX=300,
            sizeY=15,
            sizeZ=300,
            thicknessAxis="Y",
            thicknessMm=15,
        )
        panel_b = PanelSnapshot(
            panelId="B",
            bodyName="BODY_B",
            bbox=BBoxMm(0, 300, 0, 300, 0, 16),
            sizeX=300,
            sizeY=300,
            sizeZ=16,
            thicknessAxis="Z",
            thicknessMm=16,
        )
        relationship = classify_pair(panel_a, panel_b)
        report = build_inspect_pair_report(relationship=relationship, tolerance_mm=0.5)
        self.assertEqual(report["action"], "relationships.inspectPair")
        self.assertIn("relationship", report)
        self.assertIn("audit", report)


if __name__ == "__main__":
    unittest.main()
