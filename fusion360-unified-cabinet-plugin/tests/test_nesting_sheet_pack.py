import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "nesting"))

from sheet_pack import (  # noqa: E402
    normalize_sheet_params,
    rotation_candidates,
    sheet_pack_layout,
)
from outline import build_outline_payload, close_ring  # noqa: E402
import engine as nesting_engine  # noqa: E402
from collision_validate import validate_layout  # noqa: E402


def _part(pid, board, color, w, d, outline=None):
    item = {
        "id": pid,
        "panelId": pid,
        "boardTypeTag": board,
        "colorTag": color,
        "widthMm": w,
        "depthMm": d,
    }
    if outline is not None:
        item["outline"] = outline
    return item


class SheetPackTests(unittest.TestCase):
    def test_normalize_defaults(self):
        params = normalize_sheet_params({})
        self.assertEqual(params["borderMm"], 15.0)
        self.assertEqual(params["spacingMm"], 12.0)
        self.assertFalse(params["allowRotation"])
        self.assertEqual(params["sheets"], {})

    def test_rotation_candidates_phase_a(self):
        self.assertEqual(
            rotation_candidates({"allowRotation": False}),
            (0.0,),
        )
        self.assertEqual(
            rotation_candidates({"allowRotation": True, "rotationIncrementDeg": 90}),
            (0.0, 90.0, 180.0, 270.0),
        )

    def test_packs_onto_multiple_sheets(self):
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 1000, "heightMm": 500}],
            "borderMm": 10,
            "spacingMm": 10,
            "allowRotation": False,
            "sheetGapMm": 50,
        }
        result = sheet_pack_layout(
            [
                _part("a", "door", "white", 600, 400),
                _part("b", "door", "white", 600, 400),
            ],
            params,
            0,
            0,
        )
        self.assertEqual(result["engine"], "sheet_pack_hybrid_v3")
        self.assertEqual(len(result["placements"]), 2)
        self.assertEqual(len(result["sheets"]), 2)
        self.assertEqual(result["sheets"][0]["count"], 1)
        self.assertEqual(result["sheets"][1]["count"], 1)
        self.assertAlmostEqual(result["placements"][1]["sheetOriginX"], 1050.0)
        self.assertAlmostEqual(result["requiredWidthMm"], 1000 + 50 + 1000)
        self.assertAlmostEqual(result["requiredDepthMm"], 500)

    def test_board_types_stack_in_y(self):
        params = {
            "sheets": [
                {"boardTypeTag": "carcass", "widthMm": 800, "heightMm": 400},
                {"boardTypeTag": "door", "widthMm": 800, "heightMm": 400},
            ],
            "borderMm": 0,
            "spacingMm": 0,
            "allowRotation": False,
            "sheetGapMm": 100,
        }
        result = sheet_pack_layout(
            [
                _part("c", "carcass", "oak", 100, 100),
                _part("d", "door", "white", 100, 100),
            ],
            params,
            1000,
            2000,
        )
        self.assertEqual(len(result["sheets"]), 2)
        carcass = next(s for s in result["sheets"] if s["boardTypeTag"] == "carcass")
        door = next(s for s in result["sheets"] if s["boardTypeTag"] == "door")
        self.assertAlmostEqual(carcass["originY"], 2000)
        self.assertAlmostEqual(door["originY"], 2000 + 400 + 100)

    def test_same_board_type_different_colors_use_separate_rows(self):
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 800, "heightMm": 400}],
            "borderMm": 0,
            "spacingMm": 0,
            "allowRotation": False,
            "sheetGapMm": 100,
        }
        result = sheet_pack_layout(
            [
                _part("white", "door", "white", 100, 100),
                _part("oak", "door", "oak", 100, 100),
            ],
            params,
            0,
            0,
        )
        self.assertEqual(len(result["sheets"]), 2)
        self.assertNotEqual(result["sheets"][0]["colorTag"], result["sheets"][1]["colorTag"])
        self.assertEqual({sheet["originY"] for sheet in result["sheets"]}, {0.0, 500.0})

    def test_rotation_allows_fit(self):
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 500, "heightMm": 300}],
            "borderMm": 0,
            "spacingMm": 0,
            "allowRotation": True,
            "rotationIncrementDeg": 90,
        }
        result = sheet_pack_layout(
            [_part("a", "door", "white", 290, 480)],
            params,
            0,
            0,
        )
        self.assertEqual(len(result["placements"]), 1)
        self.assertAlmostEqual(result["placements"][0]["rotationDeg"], 90.0)
        self.assertAlmostEqual(result["placements"][0]["packedWidthMm"], 480.0)
        self.assertAlmostEqual(result["placements"][0]["packedDepthMm"], 290.0)

    def test_oversized_goes_unplaced(self):
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 500, "heightMm": 500}],
            "borderMm": 15,
            "spacingMm": 12,
            "allowRotation": True,
            "rotationIncrementDeg": 90,
        }
        result = sheet_pack_layout(
            [_part("huge", "door", "white", 2000, 2000)],
            params,
            0,
            0,
        )
        self.assertEqual(result["placements"], [])
        self.assertEqual(len(result["unplaced"]), 1)

    def test_spacing_keeps_gap(self):
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 1000, "heightMm": 1000}],
            "borderMm": 0,
            "spacingMm": 20,
            "allowRotation": False,
        }
        result = sheet_pack_layout(
            [
                _part("a", "door", "white", 100, 100),
                _part("b", "door", "white", 100, 100),
            ],
            params,
            0,
            0,
        )
        self.assertEqual(len(result["placements"]), 2)
        by_id = {p["id"]: p for p in result["placements"]}
        self.assertAlmostEqual(by_id["a"]["localX"], 0.0)
        self.assertAlmostEqual(by_id["b"]["localX"], 120.0)

    def test_border_insets_first_placement(self):
        result = sheet_pack_layout(
            [_part("a", "door", "white", 100, 100)],
            {
                "sheets": [{"boardTypeTag": "door", "widthMm": 500, "heightMm": 500}],
                "borderMm": 20,
                "spacingMm": 0,
                "allowRotation": False,
            },
            0,
            0,
        )
        self.assertGreaterEqual(result["placements"][0]["localX"], 20)
        self.assertGreaterEqual(result["placements"][0]["localY"], 20)

    def test_true_shape_nests_into_l_notch(self):
        """Polygon pack can place a small rect into an L notch; AABB would not."""
        ell_points = close_ring(
            [[0, 0], [100, 0], [100, 40], [40, 40], [40, 100], [0, 100]]
        )
        small_points = close_ring([[0, 0], [30, 0], [30, 30], [0, 30]])
        ell = _part(
            "L",
            "door",
            "white",
            100,
            100,
            outline=build_outline_payload(ell_points, "flatBody", 100, 100),
        )
        small = _part(
            "s",
            "door",
            "white",
            30,
            30,
            outline=build_outline_payload(small_points, "flatBody", 30, 30),
        )
        # Sheet is only as wide as the L, so the small part cannot sit to the
        # right; polygon collision must use the notch (AABB packing needs sheet 2).
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 100, "heightMm": 150}],
            "borderMm": 0,
            "spacingMm": 0,
            "allowRotation": False,
        }
        result = sheet_pack_layout([ell, small], params, 0, 0)
        self.assertEqual(len(result["placements"]), 2)
        self.assertEqual(len(result["sheets"]), 1)
        by_id = {p["id"]: p for p in result["placements"]}
        self.assertGreaterEqual(by_id["s"]["localX"], 40.0 - 1e-6)
        self.assertGreaterEqual(by_id["s"]["localY"], 40.0 - 1e-6)
        self.assertEqual(result["trueShapeCount"], 2)

    def test_blf_fills_rectangular_hole_better_than_two_sheets(self):
        """Pairwise BLF corners should nest three panels onto one sheet.

        Layout intent (sheet 400x300, border 0, spacing 0):
          A 200x200 at bottom-left, B 200x100 to its right bottom, C 200x100
          above B into the remaining hole. Without hole candidates C often
          forces a second sheet.
        """
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 400, "heightMm": 300}],
            "borderMm": 0,
            "spacingMm": 0,
            "allowRotation": False,
        }
        parts = [
            _part("A", "door", "white", 200, 200),
            _part("B", "door", "white", 200, 100),
            _part("C", "door", "white", 200, 100),
        ]
        result = sheet_pack_layout(parts, params, 0, 0)
        self.assertEqual(len(result["placements"]), 3)
        self.assertEqual(len(result["sheets"]), 1)
        self.assertEqual(result["unplaced"], [])

    def test_large_job_completes_quickly_on_sheet_pack(self):
        """~120 rectangles must finish without Deepnest-style timeouts."""
        import time

        params = {
            "sheets": [{"boardTypeTag": "carcass", "widthMm": 2440, "heightMm": 1220}],
            "borderMm": 15,
            "spacingMm": 12,
            "allowRotation": True,
        }
        parts = [
            _part("p{}".format(i), "carcass", "oak", 400 + (i % 5) * 20, 300 + (i % 3) * 30)
            for i in range(120)
        ]
        started = time.perf_counter()
        result = sheet_pack_layout(parts, params, 0, 0)
        elapsed = time.perf_counter() - started
        self.assertEqual(len(result["placements"]), 120)
        self.assertEqual(result["unplaced"], [])
        self.assertGreaterEqual(len(result["sheets"]), 1)
        self.assertLess(elapsed, 30.0, "sheet_pack too slow: {:.1f}s".format(elapsed))

    def test_200_part_hybrid_is_fast_safe_and_compact(self):
        import time

        params = {
            "sheets": [{"boardTypeTag": "carcass", "widthMm": 2440, "heightMm": 1220}],
            "borderMm": 15,
            "spacingMm": 12,
            "allowRotation": True,
            "rotationIncrementDeg": 90,
            "layoutWidthMm": 10000,
        }
        parts = [
            _part(
                "p{}".format(index),
                "carcass",
                "white",
                300 + (index % 7) * 35,
                120 + (index % 5) * 40,
            )
            for index in range(200)
        ]
        started = time.perf_counter()
        result = sheet_pack_layout(parts, params, 0, 0)
        elapsed = time.perf_counter() - started
        validation = validate_layout(result, parts, params)
        self.assertEqual(len(result["placements"]), 200)
        self.assertEqual(result["unplaced"], [])
        self.assertTrue(validation["ok"], validation)
        self.assertLess(elapsed, 5.0, "200-part hybrid too slow: {:.2f}s".format(elapsed))
        self.assertLessEqual(result["requiredWidthMm"], 10000)
        self.assertLess(result["requiredWidthMm"] / result["requiredDepthMm"], 4.0)

    def test_compact_sheet_rows_wrap_at_layout_width(self):
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 1000, "heightMm": 500}],
            "borderMm": 0,
            "spacingMm": 0,
            "allowRotation": False,
            "sheetGapMm": 50,
            "layoutWidthMm": 2050,
        }
        parts = [
            _part("p{}".format(index), "door", "white", 900, 450)
            for index in range(3)
        ]
        result = sheet_pack_layout(parts, params, 0, 0)
        self.assertEqual(len(result["sheets"]), 3)
        self.assertEqual(result["sheets"][0]["originX"], 0)
        self.assertEqual(result["sheets"][1]["originX"], 1050)
        self.assertEqual(result["sheets"][2]["originX"], 0)
        self.assertEqual(result["sheets"][2]["originY"], 550)
        self.assertEqual(result["requiredWidthMm"], 2050)
        self.assertEqual(result["requiredDepthMm"], 1050)

    def test_hybrid_layout_is_deterministic(self):
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 800, "heightMm": 500}],
            "borderMm": 10,
            "spacingMm": 8,
            "allowRotation": True,
            "rotationIncrementDeg": 90,
        }
        parts = [
            _part("p{}".format(index), "door", "white", 90 + index * 7, 60 + (index % 3) * 20)
            for index in range(12)
        ]
        first = sheet_pack_layout(parts, params, 0, 0)
        second = sheet_pack_layout(parts, params, 0, 0)
        fields = lambda result: [
            (
                placement["id"],
                placement["sheetIndex"],
                placement["localX"],
                placement["localY"],
                placement["rotationDeg"],
            )
            for placement in result["placements"]
        ]
        self.assertEqual(fields(first), fields(second))

    def test_parts_in_validated_through_hole(self):
        parent_outline = build_outline_payload(
            [[0, 0], [100, 0], [100, 100], [0, 100]],
            "flatBody",
            100,
            100,
            holes=[{
                "points": [[20, 20], [80, 20], [80, 80], [20, 80]],
                "cutType": "FULL",
                "kind": "HOLE",
            }],
        )
        child_outline = build_outline_payload(
            [[0, 0], [30, 0], [30, 30], [0, 30]],
            "flatBody",
            30,
            30,
        )
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 100, "heightMm": 100}],
            "borderMm": 0,
            "spacingMm": 1,
            "allowRotation": False,
            "allowPartsInPart": True,
        }
        result = sheet_pack_layout(
            [
                _part("parent", "door", "white", 100, 100, parent_outline),
                _part("child", "door", "white", 30, 30, child_outline),
            ],
            params,
            0,
            0,
        )
        self.assertEqual(len(result["sheets"]), 1)
        self.assertEqual(len(result["placements"]), 2)
        self.assertTrue(result["partsInPartApplied"])
        self.assertEqual(result["nestedInHoleCount"], 1)

    def test_consolidate_merges_sparse_tail_sheet(self):
        """A leftover singleton sheet should backfill into earlier free space."""
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 1000, "heightMm": 600}],
            "borderMm": 10,
            "spacingMm": 10,
            "allowRotation": False,
            "sheetGapMm": 50,
        }
        # Three 400x400 panels: sheet fits two; third opens a new sheet; consolidate
        # cannot merge if no space — use sizes where third fits beside on sheet 1
        # after order leaves a hole. Two large + one small that fits the leftover.
        parts = [
            _part("a", "door", "white", 450, 500),
            _part("b", "door", "white", 450, 500),
            _part("c", "door", "white", 80, 80),
        ]
        result = sheet_pack_layout(parts, params, 0, 0)
        self.assertEqual(len(result["placements"]), 3)
        # With consolidate, the 80x80 should not need its own sheet when 1000x600
        # has room beside/above the large panels.
        self.assertLessEqual(len(result["sheets"]), 2)
        self.assertEqual(result["unplaced"], [])
        self.assertEqual(nesting_engine.DEFAULT_ENGINE, "sheet_pack")
        params = {
            "sheets": [{"boardTypeTag": "door", "widthMm": 2440, "heightMm": 1220}],
            "borderMm": 15,
            "spacingMm": 12,
            "allowRotation": False,
        }
        parts = [
            _part("p{}".format(i), "door", "w", 200, 200)
            for i in range(nesting_engine.DEEPNEST_SMALL_JOB_LIMIT + 5)
        ]
        result = nesting_engine.create_layout(
            parts, params, 0, 0, engine_name="deepnest"
        )
        self.assertTrue(str(result.get("engine") or "").startswith("sheet_pack"))
        self.assertTrue(result.get("engineFallback"))
        self.assertIn("limit", str(result.get("engineFallbackReason") or "").lower())


if __name__ == "__main__":
    unittest.main()
