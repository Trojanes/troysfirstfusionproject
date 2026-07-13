"""Offline tests for optional auto hardware type suggestion (default off)."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HW_DIR = ROOT / "modules" / "hardware"
REL_DIR = ROOT / "modules" / "relationships"
for path in (HW_DIR, REL_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from suggest_hardware_from_relationship import (  # noqa: E402
    normalize_auto_hardware_settings,
    resolve_hardware_rule_for_relationship,
    suggest_hardware_type,
)


class SuggestHardwareTests(unittest.TestCase):
    def test_default_auto_off(self):
        self.assertFalse(normalize_auto_hardware_settings(None)["enabled"])

    def test_contact_suggests_screw(self):
        rel = {"geometryType": "edge_to_surface", "relationshipType": "structural_butt_joint"}
        suggestion = suggest_hardware_type(rel)
        self.assertEqual(suggestion["type"], "screw_hole")
        self.assertEqual(suggestion["source"], "geometry_rule")

    def test_gap_suggests_hinge(self):
        rel = {"geometryType": "gap_parallel", "relationshipType": "door_to_carcass_candidate"}
        suggestion = suggest_hardware_type(rel)
        self.assertEqual(suggestion["type"], "hinge_hole")

    def test_allowed_hardware_wins(self):
        rel = {
            "geometryType": "gap_parallel",
            "allowedHardware": ["tongue_groove", "hinge_hole"],
        }
        suggestion = suggest_hardware_type(rel)
        self.assertEqual(suggestion["type"], "tongue_groove")
        self.assertEqual(suggestion["source"], "declaration")

    def test_resolve_keeps_ui_type_when_off(self):
        rel = {"geometryType": "gap_parallel"}
        rule = resolve_hardware_rule_for_relationship(
            rel,
            {"type": "screw_hole", "diameterMm": 4},
            {"enabled": False},
        )
        self.assertEqual(rule["type"], "screw_hole")
        self.assertEqual(rule["diameterMm"], 4)

    def test_resolve_auto_uses_defaults_for_new_type(self):
        rel = {"geometryType": "gap_parallel"}
        rule = resolve_hardware_rule_for_relationship(
            rel,
            {"type": "screw_hole", "diameterMm": 4, "gapJoints": {"enabled": True}},
            {"enabled": True},
        )
        self.assertEqual(rule["type"], "hinge_hole")
        self.assertNotIn("diameterMm", rule)
        self.assertEqual(rule["gapJoints"]["enabled"], True)
        self.assertEqual(rule["autoSuggestion"]["type"], "hinge_hole")


if __name__ == "__main__":
    unittest.main()
