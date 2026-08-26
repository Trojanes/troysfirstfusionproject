import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from lay_flat import column_layout, group_items_by_board_type  # noqa: E402


class LayFlatTests(unittest.TestCase):
    def test_groups_by_board_type_sorted(self):
        items = [
            {"id": "1", "boardTypeTag": "carcass", "widthMm": 10, "depthMm": 20},
            {"id": "2", "boardTypeTag": "door", "widthMm": 10, "depthMm": 20},
            {"id": "3", "boardTypeTag": "carcass", "widthMm": 10, "depthMm": 20},
        ]
        groups = group_items_by_board_type(items)
        self.assertEqual([tag for tag, _ in groups], ["carcass", "door"])
        self.assertEqual([item["id"] for item in groups[0][1]], ["1", "3"])

    def test_column_layout_stacks_and_advances(self):
        items = [
            {"id": "a", "boardTypeTag": "A", "widthMm": 100, "depthMm": 50},
            {"id": "b", "boardTypeTag": "A", "widthMm": 80, "depthMm": 40},
            {"id": "c", "boardTypeTag": "B", "widthMm": 60, "depthMm": 30},
        ]
        layout = column_layout(
            items, origin_x_mm=1000, origin_y_mm=200, part_gap_mm=10, column_gap_mm=50
        )
        self.assertEqual(layout["engine"], "lay_flat_columns")
        self.assertEqual(len(layout["placements"]), 3)
        self.assertEqual(len(layout["groups"]), 2)

        first = layout["placements"][0]
        second = layout["placements"][1]
        third = layout["placements"][2]
        self.assertEqual(first["targetX"], 1000)
        self.assertEqual(first["targetY"], 200)
        self.assertEqual(second["targetY"], 200 + 50 + 10)
        # Second column starts after max width of first column (100) + gap
        self.assertEqual(third["boardTypeTag"], "B")
        self.assertEqual(third["targetX"], 1000 + 100 + 50)
        self.assertEqual(third["targetY"], 200)

    def test_color_change_creates_a_different_column_when_enabled(self):
        items = [
            {
                "id": "a",
                "boardTypeTag": "door",
                "colorTag": "white",
                "widthMm": 100,
                "depthMm": 50,
            },
            {
                "id": "b",
                "boardTypeTag": "door",
                "colorTag": "black",
                "widthMm": 80,
                "depthMm": 40,
            },
        ]
        layout = column_layout(
            items,
            part_gap_mm=10,
            column_gap_mm=50,
            group_by_color=True,
        )
        self.assertEqual(len(layout["groups"]), 2)
        self.assertEqual(
            [(group["boardTypeTag"], group["colorTag"]) for group in layout["groups"]],
            [("door", "black"), ("door", "white")],
        )
        self.assertNotEqual(
            layout["placements"][0]["targetX"],
            layout["placements"][1]["targetX"],
        )

    def test_grain_does_not_split_color_columns(self):
        items = [
            {
                "id": "a",
                "boardTypeTag": "door",
                "colorTag": "oak",
                "widthMm": 720,
                "depthMm": 450,
                "grainAlongMm": 720,
            },
            {
                "id": "b",
                "boardTypeTag": "door",
                "colorTag": "oak",
                "widthMm": 800,
                "depthMm": 400,
            },
        ]
        layout = column_layout(items, group_by_color=True)
        self.assertEqual(len(layout["groups"]), 1)
        self.assertEqual(layout["groups"][0]["colorTag"], "oak")
        self.assertEqual(layout["groups"][0]["count"], 2)


if __name__ == "__main__":
    unittest.main()
