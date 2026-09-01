import os
import sys
import unittest


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
METADATA_DIR = os.path.join(PLUGIN_DIR, "metadata")
NESTING_DIR = os.path.join(PLUGIN_DIR, "nesting")
for path in (METADATA_DIR, NESTING_DIR):
    if path not in sys.path:
        sys.path.insert(0, path)

from cad_segments import (  # noqa: E402
    arc_segment,
    cw_from_samples,
    line_segment,
    reverse_segments,
    rotate_segments,
    segments_are_complete,
    translate_segments,
)
from outline import build_outline_payload  # noqa: E402


class CadSegmentTests(unittest.TestCase):
    def test_translate_and_rotate_arc_keeps_radius_and_flips_nothing(self):
        arc = arc_segment([10, 0], [0, 10], [0, 0], 10, cw=False)
        moved = translate_segments([arc], 5, -2)[0]
        self.assertEqual(moved["center"], [5.0, -2.0])
        self.assertEqual(moved["radiusMm"], 10.0)
        self.assertFalse(moved["cw"])
        spun = rotate_segments([moved], 90)[0]
        self.assertAlmostEqual(spun["center"][0], 2.0, places=3)
        self.assertAlmostEqual(spun["center"][1], 5.0, places=3)
        self.assertFalse(spun["cw"])

    def test_reverse_flips_arc_direction(self):
        segs = [
            line_segment([0, 0], [10, 0]),
            arc_segment([10, 0], [10, 10], [10, 5], 5, cw=False),
        ]
        rev = reverse_segments(segs)
        self.assertEqual(rev[0]["type"], "arc")
        self.assertTrue(rev[0]["cw"])
        self.assertEqual(rev[0]["start"], [10.0, 10.0])
        self.assertEqual(rev[1]["end"], [0.0, 0.0])

    def test_cw_from_samples(self):
        center = [0, 0]
        ccw = [[10, 0], [7, 7], [0, 10]]
        cw = [[10, 0], [7, -7], [0, -10]]
        self.assertFalse(cw_from_samples(center, ccw))
        self.assertTrue(cw_from_samples(center, cw))

    def test_outline_payload_translates_and_reverses_segments(self):
        segs = [
            line_segment([10, 50], [10, 20]),
            line_segment([10, 20], [60, 20]),
            line_segment([60, 20], [60, 50]),
            line_segment([60, 50], [10, 50]),
        ]
        payload = build_outline_payload(
            [[10, 20], [60, 20], [60, 50], [10, 50]],
            "flatBody",
            segments=segs,
        )
        self.assertAlmostEqual(payload["points"][0][0], 0.0)
        self.assertTrue(segments_are_complete(payload["segments"]))
        self.assertGreater(len(payload["segments"]), 3)
        starts = [s["start"] for s in payload["segments"]]
        self.assertTrue(any(abs(p[0]) < 1e-6 and abs(p[1]) < 1e-6 for p in starts))


if __name__ == "__main__":
    unittest.main()
