import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from lay_flat_tag_overrides import (  # noqa: E402
    apply_override_to_metadata,
    apply_override_to_tags,
    filter_complete_manual_overrides,
    harvest_overrides_from_items,
    is_complete_manual_override,
    merge_override_maps,
    normalize_override,
    override_for_record,
    override_key,
)


class LayFlatTagOverridesTests(unittest.TestCase):
    def test_normalize_and_merge(self):
        self.assertEqual(
            normalize_override(
                {"boardTypeTag": "Carcass", "colorTag": "White_Stipple"}
            ),
            {
                "boardTypeTag": "carcass",
                "colorTag": "white_stipple",
                "source": "manual",
            },
        )
        merged = merge_override_maps(
            {"overhead.D1": {"boardTypeTag": "door", "colorTag": "metallic_white"}},
            {"overhead.D1": {"colorTag": "white_stipple"}},
        )
        self.assertEqual(merged["overhead.D1"]["boardTypeTag"], "door")
        self.assertEqual(merged["overhead.D1"]["colorTag"], "white_stipple")

    def test_harvest_uses_exact_source_token(self):
        harvested = harvest_overrides_from_items(
            [
                {
                    "sourcePanelId": "overhead.D1@layflat-2-0",
                    "sourceEntityToken": "source-token-d1",
                    "boardTypeTag": "carcass",
                    "colorTag": "white_stipple",
                }
            ]
        )
        key = override_key("source-token-d1")
        self.assertIn(key, harvested)
        self.assertEqual(harvested[key]["colorTag"], "white_stipple")

    def test_harvest_rejects_panel_id_only_item(self):
        harvested = harvest_overrides_from_items(
            [
                {
                    "sourcePanelId": "manual.Body1",
                    "boardTypeTag": "carcass",
                    "colorTag": "white_stipple",
                }
            ]
        )
        self.assertEqual(harvested, {})

    def test_record_lookup_does_not_fan_out_by_panel_id(self):
        overrides = {
            "token:token-a": {
                "boardTypeTag": "carcass",
                "colorTag": "white_stipple",
            }
        }
        self.assertIsNotNone(
            override_for_record(
                overrides,
                {"panelId": "manual.Body1", "entityToken": "token-a"},
            )
        )
        self.assertIsNone(
            override_for_record(
                overrides,
                {"panelId": "manual.Body1", "entityToken": "token-b"},
            )
        )

    def test_apply_override_to_tags_and_metadata(self):
        board, color = apply_override_to_tags(
            "door",
            "metallic_white",
            {"boardTypeTag": "carcass", "colorTag": "white_stipple"},
        )
        self.assertEqual(board, "carcass")
        self.assertEqual(color, "white_stipple")
        meta = apply_override_to_metadata(
            {"derivedTags": {"boardTypeTag": "door", "colorTag": "metallic_white"}},
            {"boardTypeTag": "carcass", "colorTag": "white_stipple"},
        )
        classification = meta.get("classification") or {}
        self.assertEqual(
            (classification.get("boardType") or {}).get("value"), "carcass"
        )
        self.assertEqual(
            (classification.get("color") or {}).get("value"), "white_stipple"
        )

    def test_filter_rejects_partial_overrides_that_collapse_columns(self):
        self.assertFalse(
            is_complete_manual_override({"boardTypeTag": "carcass"})
        )
        cleaned = filter_complete_manual_overrides(
            {
                "token:a": {
                    "boardTypeTag": "carcass",
                    "colorTag": "white_stipple",
                },
                "token:b": {"boardTypeTag": "door"},
                "token:c": {"colorTag": "metallic_white"},
                # Legacy panelId key must be purged even when complete.
                "manual.Body1": {
                    "boardTypeTag": "carcass",
                    "colorTag": "white_stipple",
                },
            }
        )
        self.assertEqual(list(cleaned.keys()), ["token:a"])


if __name__ == "__main__":
    unittest.main()
