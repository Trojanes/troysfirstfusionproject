import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_ATTR_DIR = os.path.join(ROOT, "panel_attributes")
sys.path.insert(0, ROOT)
sys.path.insert(0, PANEL_ATTR_DIR)

from nesting.preflight import evaluate_record  # noqa: E402


class NestingPreflightTests(unittest.TestCase):
    def test_ready_record(self):
        result = evaluate_record({
            "metadata": {
                "classification": {
                    "boardType": {"value": "door"},
                    "color": {"value": "white"},
                    "cuttingFace": {"value": "MILLING"},
                },
            },
        })
        self.assertTrue(result["ready"])
        self.assertEqual(result["cuttingFace"], "MILLING")

    def test_all_missing_reasons(self):
        result = evaluate_record({
            "requiredFaceUp": "UNASSIGNED",
            "derivedTags": {},
            "metadata": {},
        })
        self.assertEqual(
            result["missing"],
            ["Board Type", "Color", "Cutting Face"],
        )

    def test_canonical_values_win(self):
        result = evaluate_record({
            "requiredFaceUp": "EITHER",
            "derivedTags": {
                "boardTypeTag": "stale",
                "colorTag": "stale",
            },
            "metadata": {
                "classification": {
                    "boardType": {"value": "carcass"},
                    "color": {"value": "oak"},
                    "cuttingFace": {"value": "EITHER"},
                },
            },
        })
        self.assertTrue(result["ready"])
        self.assertEqual(result["boardTypeTag"], "carcass")
        self.assertEqual(result["colorTag"], "oak")
        self.assertEqual(result["cuttingFace"], "EITHER")

    def test_migrate_fills_cutting_face_from_registry(self):
        result = evaluate_record({
            "metadata": {
                "classification": {
                    "boardType": {"value": "carcass"},
                    "color": {"value": "carcass_colour"},
                },
                "faceRegistry": {
                    "faces": [
                        {"faceClass": "SURFACE", "millingSurface": "MILLING"},
                        {"faceClass": "SURFACE", "millingSurface": "NON_MILLING"},
                    ],
                },
            },
        })
        self.assertTrue(result["ready"])
        self.assertEqual(result["cuttingFace"], "MILLING")

    def test_grain_catalog_does_not_affect_default_ready(self):
        result = evaluate_record({
            "metadata": {
                "classification": {
                    "boardType": {"value": "door"},
                    "color": {"value": "oak"},
                    "cuttingFace": {"value": "MILLING"},
                },
            },
        })
        self.assertTrue(result["ready"])
        self.assertNotIn("Grain", result["missing"])

    def test_grain_catalog_marks_missing_direction(self):
        record = {
            "colorTag": "oak",
            "metadata": {
                "classification": {
                    "boardType": {"value": "door"},
                    "color": {"value": "oak"},
                    "cuttingFace": {"value": "MILLING"},
                },
            },
        }
        missing = evaluate_record(record, grain_color_tags=["oak"])
        self.assertFalse(missing["ready"])
        self.assertIn("Grain", missing["missing"])
        ready = evaluate_record(
            {
                **record,
                "metadata": {
                    **record["metadata"],
                    "classification": {
                        **record["metadata"]["classification"],
                        "grainAlongMm": {"value": 720, "source": "manual", "locked": True},
                    },
                },
            },
            grain_color_tags=["oak"],
        )
        self.assertTrue(ready["ready"])
        self.assertNotIn("Grain", ready["missing"])


if __name__ == "__main__":
    unittest.main()
