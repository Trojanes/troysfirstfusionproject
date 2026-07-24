import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
if str(REL_DIR) not in sys.path:
    sys.path.insert(0, str(REL_DIR))

from relationship_geometry import (  # noqa: E402
    bbox_gap_1d,
    bbox_overlap_1d,
    bbox_size,
    detect_contact_axis,
    infer_thickness_axis,
)
from relationship_models import BBoxMm, PanelSnapshot  # noqa: E402


class RelationshipGeometryTests(unittest.TestCase):
    def test_bbox_gap_when_separated(self):
        self.assertEqual(bbox_gap_1d(0, 10, 12, 20), 2.0)

    def test_bbox_gap_when_touching(self):
        self.assertEqual(bbox_gap_1d(0, 10, 10, 20), 0.0)

    def test_bbox_gap_when_overlapping(self):
        self.assertEqual(bbox_gap_1d(0, 15, 10, 20), 0.0)

    def test_bbox_overlap(self):
        self.assertEqual(bbox_overlap_1d(0, 10, 5, 15), 5.0)
        self.assertEqual(bbox_overlap_1d(0, 10, 20, 30), 0.0)

    def test_bbox_size(self):
        bbox = BBoxMm(x0=0, x1=300, y0=0, y1=15, z0=0, z1=400)
        self.assertEqual(bbox_size("Y", bbox), 15.0)

    def test_infer_thickness_axis(self):
        snapshot = PanelSnapshot(
            panelId="P1",
            bodyName="P1",
            bbox=BBoxMm(x0=0, x1=300, y0=0, y1=15, z0=0, z1=400),
            sizeX=300,
            sizeY=15,
            sizeZ=400,
        )
        axis, thickness, warnings = infer_thickness_axis(snapshot)
        self.assertEqual(axis, "Y")
        self.assertEqual(thickness, 15.0)
        self.assertEqual(warnings, [])

    def test_detect_contact_axis(self):
        panel_a = PanelSnapshot(
            panelId="A",
            bodyName="A",
            bbox=BBoxMm(x0=0, x1=300, y0=300, y1=315, z0=0, z1=300),
            sizeX=300,
            sizeY=15,
            sizeZ=300,
            thicknessAxis="Y",
            thicknessMm=15,
        )
        panel_b = PanelSnapshot(
            panelId="B",
            bodyName="B",
            bbox=BBoxMm(x0=0, x1=300, y0=0, y1=300, z0=0, z1=16),
            sizeX=300,
            sizeY=300,
            sizeZ=16,
            thicknessAxis="Z",
            thicknessMm=16,
        )
        axis, overlaps, gaps = detect_contact_axis(panel_a, panel_b)
        self.assertEqual(axis, "Y")
        self.assertEqual(gaps["Y"], 0.0)
        self.assertGreaterEqual(overlaps["X"], 1.0)
        self.assertGreaterEqual(overlaps["Z"], 1.0)


if __name__ == "__main__":
    unittest.main()
