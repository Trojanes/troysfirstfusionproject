import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
PANEL_ATTR_DIR = ROOT / "panel_attributes"
if str(PANEL_ATTR_DIR) not in sys.path:
    sys.path.insert(0, str(PANEL_ATTR_DIR))

import thickness_rules as tr  # noqa: E402


class ThicknessMeasureTests(unittest.TestCase):
    def test_prefers_bbox_over_declared_when_classifying(self):
        """Real 24 mm bunk must not stay carcass just because CPT metadata says 15."""
        body = MagicMock()
        body.boundingBox = MagicMock(
            minPoint=MagicMock(x=0, y=0, z=0),
            maxPoint=MagicMock(x=2.4, y=40, z=40),  # 24 mm in X
        )
        meta = {
            "designGeometry": {
                "materialThickness": 15,
                "thicknessAxis": "X",
                "x0": 0,
                "x1": 15,
                "y0": 0,
                "y1": 400,
                "z0": 0,
                "z1": 400,
            },
            "dimensions": {"thicknessMm": 15},
        }
        rules = tr.normalize_rules(
            [
                {"boardTypeTag": "carcass", "thicknessMm": 15},
                {"boardTypeTag": "partition", "thicknessMm": 18},
                {"boardTypeTag": "door", "thicknessMm": 16},
                {"boardTypeTag": "bunk_bed", "thicknessMm": 24},
            ],
            0.2,
        )
        report = tr.measure_body_thickness_report(body, meta, rules_payload=rules)
        self.assertEqual(report["thicknessMm"], 24.0)
        self.assertIn("bbox", report["source"])
        match = tr.match_thickness_rule(report["thicknessMm"], rules)
        self.assertEqual(match["boardTypeTag"], "bunk_bed")

    def test_recovers_half_mm_underread_when_rules_match(self):
        body = MagicMock()
        body.boundingBox = MagicMock(
            minPoint=MagicMock(x=0, y=0, z=0),
            maxPoint=MagicMock(x=1.45, y=40, z=40),  # 14.5 mm
        )
        meta = {"dimensions": {"thicknessMm": 14.5}}
        rules = tr.normalize_rules(
            [
                {"boardTypeTag": "carcass", "thicknessMm": 15},
                {"boardTypeTag": "partition", "thicknessMm": 18},
                {"boardTypeTag": "door", "thicknessMm": 16},
            ],
            0.2,
        )
        report = tr.measure_body_thickness_report(body, meta, rules_payload=rules)
        self.assertEqual(report["thicknessMm"], 15.0)
        self.assertIn("0.5recover", report["source"])

    def test_apply_rule_never_fills_tags_over_known_board_type(self):
        """A generator-identified carcass board (e.g. GT B3) must not get a
        'door' derived tag stamped just because its thickness matched the
        door rule and its derivedTags were still empty."""
        meta = {
            "schemaVersion": 1,
            "identity": {"panelId": "generalTall.B3", "boardType": "B3"},
            "defaultAttributes": {"materialClass": "carcass_board"},
        }
        rules = tr.normalize_rules(tr.DEFAULT_RULES, 0.6)
        match = tr.match_thickness_rule(16.0, rules)
        self.assertEqual(match["boardTypeTag"], "door")
        updated, changed = tr.apply_rule_to_metadata(meta, match, overwrite=False)
        self.assertFalse(changed)
        self.assertNotIn("derivedTags", updated if isinstance(updated, dict) else {})
        self.assertEqual(updated["defaultAttributes"]["materialClass"], "carcass_board")

    def test_apply_rule_fills_unknown_and_overwrite_replaces(self):
        unknown_meta = {"identity": {}, "defaultAttributes": {"materialClass": "unknown"}}
        rules = tr.normalize_rules(tr.DEFAULT_RULES, 0.6)
        match = tr.match_thickness_rule(15.0, rules)
        updated, changed = tr.apply_rule_to_metadata(unknown_meta, match, overwrite=False)
        self.assertTrue(changed)
        self.assertEqual(updated["derivedTags"]["boardTypeTag"], "carcass")
        self.assertEqual(updated["defaultAttributes"]["materialClass"], "carcass_board")

        known_meta = {
            "identity": {"boardType": "B3"},
            "defaultAttributes": {"materialClass": "carcass_board"},
        }
        door_match = tr.match_thickness_rule(16.0, rules)
        forced, changed = tr.apply_rule_to_metadata(known_meta, door_match, overwrite=True)
        self.assertTrue(changed)
        self.assertEqual(forced["derivedTags"]["boardTypeTag"], "door")
        self.assertEqual(forced["defaultAttributes"]["materialClass"], "door_board")

    def test_design_span_used_when_bbox_missing(self):
        meta = {
            "designGeometry": {
                "thicknessAxis": "X",
                "x0": 0,
                "x1": 15,
                "y0": 0,
                "y1": 400,
                "z0": 30,
                "z1": 430,
            }
        }
        rules = tr.normalize_rules(tr.DEFAULT_RULES, 0.2)
        report = tr.measure_body_thickness_report(None, meta, rules_payload=rules)
        self.assertEqual(report["thicknessMm"], 15.0)


if __name__ == "__main__":
    unittest.main()
