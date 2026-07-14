import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from outline_cache import (  # noqa: E402
    build_cache_record,
    cached_outline_for_prepare,
    outline_cache_status,
)


class OutlineCacheTests(unittest.TestCase):
    def test_fresh_then_stale_on_signature_change(self):
        outline = {
            "points": [[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]],
            "source": "flatBody",
            "pointCount": 4,
            "holeCount": 0,
            "reflectedSource": False,
        }
        cached = build_cache_record(
            outline,
            {"widthMm": 100, "depthMm": 50},
            "sig-a",
            "A",
            allow_parts_in_part=False,
            reflected_source=False,
        )
        metadata = {"nestingFlatOutline": cached}
        self.assertEqual(
            outline_cache_status(metadata, "sig-a", "A", False, reflected_source=False),
            "fresh",
        )
        self.assertEqual(
            outline_cache_status(metadata, "sig-b", "A", False, reflected_source=False),
            "stale",
        )
        self.assertEqual(
            outline_cache_status(metadata, "sig-a", "B", False, reflected_source=False),
            "stale",
        )
        self.assertEqual(
            outline_cache_status(metadata, "sig-a", "A", True, reflected_source=False),
            "stale",
        )
        ready, dims = cached_outline_for_prepare(
            metadata, "sig-a", "A", False, reflected_source=False
        )
        self.assertIsNotNone(ready)
        self.assertEqual(dims["widthMm"], 100.0)

    def test_reflected_mismatch_is_stale(self):
        outline = {
            "points": [[0, 0], [100, 0], [100, 50], [0, 50], [0, 0]],
            "source": "flatBody",
            "pointCount": 4,
            "reflectedSource": True,
        }
        cached = build_cache_record(
            outline,
            {"widthMm": 100, "depthMm": 50},
            "sig-a",
            "A",
            reflected_source=True,
        )
        metadata = {"nestingFlatOutline": cached}
        self.assertEqual(
            outline_cache_status(metadata, "sig-a", "A", False, reflected_source=True),
            "fresh",
        )
        self.assertEqual(
            outline_cache_status(metadata, "sig-a", "A", False, reflected_source=False),
            "stale",
        )

    def test_missing_without_cache(self):
        self.assertEqual(
            outline_cache_status({}, "sig", "A", False),
            "missing",
        )


if __name__ == "__main__":
    unittest.main()
