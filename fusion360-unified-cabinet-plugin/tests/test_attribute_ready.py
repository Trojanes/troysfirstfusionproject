import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "panel_attributes"))

from attribute_ready import (  # noqa: E402
    ATTRIBUTE_READY_STATE,
    NOT_ATTRIBUTE_READY_STATE,
    evaluate_attribute_ready,
)


def base_meta(**overrides):
    meta = {
        "identity": {
            "panelId": "ohc.run1.BP",
            "boardType": "carcass_bottom",
        },
        "defaultAttributes": {
            "materialClass": "carcass_board",
            "role": "carcass",
        },
        "faceRegistry": {
            "faces": [
                {"faceClass": "SURFACE", "millingSurface": "MILLING"},
                {
                    "faceClass": "SURFACE",
                    "millingSurface": "NON_MILLING",
                },
            ],
        },
    }
    meta.update(overrides)
    return meta


class AttributeReadyTests(unittest.TestCase):
    def test_ready_when_board_type_and_face_up_known(self):
        result = evaluate_attribute_ready(
            base_meta(), {"boardTypeTag": "carcass"}
        )
        self.assertTrue(result["ready"])
        self.assertEqual(result["state"], ATTRIBUTE_READY_STATE)
        self.assertEqual(result["requiredFaceUp"], "MILLING")
        self.assertEqual(result["missing"], [])

    def test_either_both_surfaces_is_known_face_up(self):
        meta = base_meta(
            faceRegistry={
                "faces": [
                    {"faceClass": "SURFACE", "millingSurface": "EITHER"},
                    {"faceClass": "SURFACE", "millingSurface": "EITHER"},
                ],
            }
        )
        result = evaluate_attribute_ready(meta, {"boardTypeTag": "door"})
        self.assertTrue(result["ready"])
        self.assertEqual(result["requiredFaceUp"], "EITHER")

    def test_not_ready_when_face_up_unassigned(self):
        meta = base_meta(
            faceRegistry={
                "faces": [
                    {"faceClass": "SURFACE", "millingSurface": "EITHER"},
                    {"faceClass": "SURFACE"},
                ],
            }
        )
        result = evaluate_attribute_ready(
            meta, {"boardTypeTag": "carcass"}
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["state"], NOT_ATTRIBUTE_READY_STATE)
        self.assertIn("face_up_unassigned", result["missing"])

    def test_not_ready_when_board_type_unknown(self):
        meta = {
            "identity": {"panelId": "x"},
            "defaultAttributes": {},
            "faceRegistry": {
                "faces": [
                    {"faceClass": "SURFACE", "millingSurface": "MILLING"},
                    {
                        "faceClass": "SURFACE",
                        "millingSurface": "NON_MILLING",
                    },
                ],
            },
        }
        result = evaluate_attribute_ready(meta, {"boardTypeTag": ""})
        self.assertFalse(result["ready"])
        self.assertIn("board_type_unknown", result["missing"])

    def test_not_ready_when_face_registry_missing(self):
        meta = {
            "identity": {"panelId": "x", "boardType": "door"},
            "defaultAttributes": {"materialClass": "door_board"},
        }
        result = evaluate_attribute_ready(meta, {"boardTypeTag": "door"})
        self.assertFalse(result["ready"])
        self.assertIn("face_registry_missing", result["missing"])

    def test_classification_cutting_face_is_authoritative(self):
        meta = {
            "classification": {
                "boardType": {"value": "door", "source": "manual", "locked": True},
                "cuttingFace": {
                    "value": "MILLING",
                    "source": "manual",
                    "locked": True,
                },
            },
            "faceRegistry": {"faces": []},
        }
        result = evaluate_attribute_ready(meta)
        self.assertTrue(result["ready"])
        self.assertEqual(result["requiredFaceUp"], "MILLING")
        self.assertEqual(result["cuttingFace"], "MILLING")

    def test_empty_classification_without_legacy_is_not_ready(self):
        """Ready must not invent Board Type / Cutting Face from thin air."""
        meta = {
            "identity": {"panelId": "x"},
            "defaultAttributes": {},
            "classification": {
                "boardType": {"value": "", "source": "legacy", "locked": False},
                "cuttingFace": {"value": "", "source": "legacy", "locked": False},
            },
            "derivedTags": {},
            "typedTags": {},
            "faceRegistry": {"faces": []},
        }
        result = evaluate_attribute_ready(meta)
        self.assertFalse(result["ready"])
        self.assertIn("board_type_unknown", result["missing"])


if __name__ == "__main__":
    unittest.main()
