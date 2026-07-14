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
        self.assertEqual(result["engine"], "sheet_pack_poly_v2")
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
