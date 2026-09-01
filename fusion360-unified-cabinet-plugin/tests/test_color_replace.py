import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_ATTR_DIR = os.path.join(ROOT, "panel_attributes")
if PANEL_ATTR_DIR not in sys.path:
    sys.path.insert(0, PANEL_ATTR_DIR)

import color_replace  # noqa: E402


def _record(color, grain=None, entity="body"):
    classification = {
        "color": {"value": color, "source": "manual", "locked": True},
    }
    if grain is not None:
        classification["grainAlongMm"] = {
            "value": grain,
            "source": "manual",
            "locked": True,
        }
    return {
        "entityKind": entity,
        "colorTag": color,
        "metadata": {
            "classification": classification,
            "defaultAttributes": {"colorName": color},
        },
        "derivedTags": {"colorTag": color, **({"grainAlongMm": grain} if grain else {})},
    }


class ColorReplaceTests(unittest.TestCase):
    def test_normalize_treats_spaces_as_underscores(self):
        self.assertEqual(color_replace.normalize_color_key("Alpine White"), "alpine_white")
        self.assertEqual(color_replace.normalize_color_key("unknown"), "")

    def test_color_key_prefers_classification(self):
        record = _record("oak_veneer")
        record["colorTag"] = "stale"
        self.assertEqual(color_replace.color_key_from_record(record), "oak_veneer")

    def test_summarize_color_grain_marks_mixed(self):
        rows = color_replace.summarize_color_grain(
            [
                _record("oak", 720),
                _record("oak", None),
                _record("white_stipple"),
                _record("white_stipple", entity="component"),
            ]
        )
        by_tag = {row["colorTag"]: row for row in rows}
        self.assertEqual(by_tag["oak"]["bodyCount"], 2)
        self.assertEqual(by_tag["oak"]["grainCount"], 1)
        self.assertTrue(by_tag["oak"]["mixed"])
        self.assertFalse(by_tag["oak"]["hasGrain"])
        self.assertEqual(by_tag["white_stipple"]["bodyCount"], 1)
        self.assertFalse(by_tag["white_stipple"]["hasGrain"])

    def test_apply_color_rename_slugs_and_locks(self):
        patched, tag, result = color_replace.apply_color_rename(
            {
                "classification": {
                    "color": {"value": "old_white", "source": "generator", "locked": False},
                },
                "defaultAttributes": {"doorColorName": "Old White"},
            },
            "Alpine White",
        )
        self.assertEqual(tag, "alpine_white")
        self.assertTrue(result["changed"])
        self.assertEqual(patched["classification"]["color"]["value"], "alpine_white")
        self.assertTrue(patched["classification"]["color"]["locked"])
        self.assertEqual(patched["defaultAttributes"]["colorName"], "Alpine White")
        self.assertEqual(patched["defaultAttributes"]["doorColorName"], "Alpine White")
        self.assertEqual(patched["classification"]["color"]["value"], "alpine_white")

    def test_apply_color_rename_rejects_blank(self):
        with self.assertRaises(ValueError):
            color_replace.apply_color_rename({}, "   ")

    def test_normalize_grain_color_tags_dedupes(self):
        self.assertEqual(
            color_replace.normalize_grain_color_tags(["Oak Veneer", "oak_veneer", "", "unknown"]),
            ["oak_veneer"],
        )

    def test_rename_grain_color_tag_moves_membership(self):
        self.assertEqual(
            color_replace.rename_grain_color_tag(["oak", "white_stipple"], "oak", "alpine_white"),
            ["alpine_white", "white_stipple"],
        )
        self.assertEqual(
            color_replace.rename_grain_color_tag(["white_stipple"], "oak", "alpine_white"),
            ["white_stipple"],
        )

    def test_record_missing_grain_only_for_catalog_colors(self):
        oak = _record("oak")
        white = _record("white_stipple")
        oak_with_grain = _record("oak", 720)
        self.assertTrue(color_replace.record_missing_grain(oak, ["oak"]))
        self.assertFalse(color_replace.record_missing_grain(oak_with_grain, ["oak"]))
        self.assertFalse(color_replace.record_missing_grain(white, ["oak"]))
        self.assertFalse(color_replace.record_missing_grain(oak, []))

    def test_load_save_grain_color_tags_roundtrip(self):
        class _Attr:
            def __init__(self, value=""):
                self.value = value

        class _Attrs:
            def __init__(self):
                self._items = {}

            def itemByName(self, group, name):
                return self._items.get((group, name))

            def add(self, group, name, value):
                self._items[(group, name)] = _Attr(value)

        class _Root:
            def __init__(self):
                self.attributes = _Attrs()

        root = _Root()
        saved, tags = color_replace.save_grain_color_tags(root, ["Oak Veneer", "oak_veneer"])
        self.assertTrue(saved)
        self.assertEqual(tags, ["oak_veneer"])
        self.assertEqual(color_replace.load_grain_color_tags(root), ["oak_veneer"])


if __name__ == "__main__":
    unittest.main()
