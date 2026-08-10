import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

import lay_flat_tag_scan as tag_scan  # noqa: E402


class LayFlatTagScanTests(unittest.TestCase):
    def test_complete_tags_ok(self):
        result = tag_scan.evaluate_metadata_tags(
            {
                "identity": {"panelId": "P1"},
                "classification": {
                    "boardType": {"value": "carcass"},
                    "color": {"value": "white_stipple"},
                    "cuttingFace": {"value": "MILLING"},
                },
                "dimensions": {"thicknessMm": 15.0},
                "lifecycle": {"state": "lay_flat_analyzed"},
            },
            body_name="Body1",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["missing"], [])
        self.assertEqual(result["boardTypeTag"], "carcass")

    def test_missing_board_and_color(self):
        result = tag_scan.evaluate_metadata_tags(
            {
                "identity": {"panelId": "P2"},
                "classification": {"cuttingFace": {"value": "EITHER"}},
                "dimensions": {"thicknessMm": 16.0},
            },
            body_name="Door1",
        )
        self.assertFalse(result["ok"])
        self.assertIn("board_type", result["missing"])
        self.assertIn("color", result["missing"])

    def test_troubleshoot_merges_export_ready_without_duplicating_tags(self):
        class FakeBody:
            name = "PanelA"

            class attributes:
                @staticmethod
                def itemByName(*_args):
                    return None

        with mock.patch.object(
            tag_scan,
            "evaluate_export_ready_body",
            return_value={
                "ready": False,
                "reasons": ["board_type", "color", "groove_geometry", "analyze_stale"],
                "panelId": "P-A",
                "boardTypeTag": "",
                "colorTag": "",
                "cuttingFace": "MILLING",
                "thicknessMm": 15.0,
                "lifecycleState": "lay_flat",
                "featureCount": 1,
                "pointCount": 4,
                "outlineSource": "flatBody",
                "analyzed": False,
                "faceUp": {"ok": True, "reasons": []},
            },
        ):
            with mock.patch.object(
                tag_scan,
                "read_body_metadata",
                return_value={
                    "identity": {"panelId": "P-A", "sourcePanelId": "SRC-1"},
                    "classification": {
                        "boardType": {"value": "", "source": "missing", "locked": False},
                        "color": {"value": "", "source": "missing", "locked": False},
                        "cuttingFace": {"value": "MILLING", "source": "derived", "locked": False},
                    },
                    "dimensions": {"widthMm": 600, "depthMm": 300, "thicknessMm": 15.0},
                    "features": [
                        {"featureId": "f1", "cutType": "half", "kind": "groove", "depthMm": 6}
                    ],
                    "nestingFlatOutline": {
                        "source": "flatBody",
                        "outline": {"pointCount": 4, "widthMm": 600, "depthMm": 300},
                    },
                },
            ):
                item = tag_scan.evaluate_body(FakeBody())
        self.assertFalse(item["ok"])
        self.assertFalse(item["exportReady"])
        self.assertTrue(item["problem"])
        self.assertIn("board_type", item["missing"])
        self.assertIn("groove_geometry", item["troubleshoot"])
        self.assertIn("analyze_stale", item["troubleshoot"])
        self.assertNotIn("board_type", item["troubleshoot"])
        self.assertNotIn("color", item["troubleshoot"])
        detail = item.get("detail") or {}
        self.assertEqual(detail.get("identity", {}).get("sourcePanelId"), "SRC-1")
        self.assertEqual((detail.get("outline") or {}).get("pointCount"), 4)
        self.assertEqual((detail.get("featureSummary") or {}).get("total"), 1)
        public = tag_scan._public_record(item)
        self.assertIn("detail", public)
        self.assertEqual(public["detail"]["identity"]["panelId"], "P-A")

    def test_scan_bodies_counts_problems(self):
        class FakeBody:
            def __init__(self, name):
                self.name = name

            class attributes:
                @staticmethod
                def itemByName(*_args):
                    return None

        with mock.patch.object(
            tag_scan,
            "evaluate_export_ready_body",
            return_value={
                "ready": False,
                "reasons": ["not_analyzed", "board_type", "color", "cutting_face", "thickness"],
                "panelId": "",
                "featureCount": 0,
                "pointCount": 0,
                "outlineSource": "",
                "analyzed": False,
                "faceUp": None,
            },
        ):
            result = tag_scan.scan_bodies([FakeBody("A"), FakeBody("B")])
        self.assertEqual(result["bodyCount"], 2)
        self.assertEqual(result["problemCount"], 2)
        self.assertEqual(result["notExportReadyCount"], 2)
        self.assertFalse(result["ok"])
        self.assertGreater(result["reasonCounts"].get("not_analyzed", 0), 0)


if __name__ == "__main__":
    unittest.main()
