import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from layout import grouped_row_layout  # noqa: E402


class NestingLayoutTests(unittest.TestCase):
    def test_groups_by_board_type_and_color(self):
        result = grouped_row_layout(
            [
                {
                    "id": "b",
                    "panelId": "b",
                    "boardTypeTag": "door",
                    "colorTag": "white",
                    "widthMm": 500,
                    "depthMm": 200,
                },
                {
                    "id": "a",
                    "panelId": "a",
                    "boardTypeTag": "door",
                    "colorTag": "white",
                    "widthMm": 300,
                    "depthMm": 100,
                },
                {
                    "id": "c",
                    "panelId": "c",
                    "boardTypeTag": "carcass",
                    "colorTag": "oak",
                    "widthMm": 400,
                    "depthMm": 250,
                },
            ],
            1000,
            2000,
            part_gap_mm=50,
            group_gap_mm=300,
        )
        self.assertEqual(len(result["groups"]), 2)
        self.assertEqual(len(result["placements"]), 3)
        # Lexicographic group order: carcass/oak first, door/white second.
        self.assertEqual(result["groups"][0]["boardTypeTag"], "carcass")
        self.assertEqual(result["groups"][1]["boardTypeTag"], "door")

    def test_parts_extend_positive_x_and_groups_positive_y(self):
        result = grouped_row_layout(
            [
                {
                    "panelId": "a",
                    "boardTypeTag": "door",
                    "colorTag": "white",
                    "widthMm": 300,
                    "depthMm": 100,
                },
                {
                    "panelId": "b",
                    "boardTypeTag": "door",
                    "colorTag": "white",
                    "widthMm": 500,
                    "depthMm": 200,
                },
                {
                    "panelId": "c",
                    "boardTypeTag": "partition",
                    "colorTag": "white",
                    "widthMm": 400,
                    "depthMm": 150,
                },
            ],
            0,
            1000,
            part_gap_mm=50,
            group_gap_mm=300,
        )
        first_group = [
            p for p in result["placements"] if p["groupIndex"] == 0
        ]
        self.assertGreater(first_group[1]["targetX"], first_group[0]["targetX"])
        self.assertGreater(
            result["groups"][1]["originY"], result["groups"][0]["originY"]
        )

    def test_required_size_excludes_trailing_gaps(self):
        result = grouped_row_layout(
            [
                {
                    "panelId": "a",
                    "boardTypeTag": "door",
                    "colorTag": "white",
                    "widthMm": 300,
                    "depthMm": 100,
                },
                {
                    "panelId": "b",
                    "boardTypeTag": "door",
                    "colorTag": "white",
                    "widthMm": 500,
                    "depthMm": 200,
                },
            ],
            -500,
            200,
            part_gap_mm=50,
            group_gap_mm=300,
        )
        self.assertEqual(result["requiredWidthMm"], 850)
        self.assertEqual(result["requiredDepthMm"], 200)

    def test_invalid_items_are_skipped(self):
        result = grouped_row_layout(
            [
                {
                    "panelId": "bad",
                    "boardTypeTag": "door",
                    "colorTag": "white",
                    "widthMm": 0,
                    "depthMm": 100,
                }
            ],
            0,
            0,
        )
        self.assertEqual(result["placements"], [])
        self.assertEqual(result["groups"], [])


if __name__ == "__main__":
    unittest.main()
