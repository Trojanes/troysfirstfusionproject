import os
import sys
import unittest
from unittest.mock import MagicMock, patch


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

if "adsk" not in sys.modules:
    adsk = MagicMock()
    adsk.core = MagicMock()
    adsk.fusion = MagicMock()
    sys.modules["adsk"] = adsk
    sys.modules["adsk.core"] = adsk.core
    sys.modules["adsk.fusion"] = adsk.fusion

from nesting.collision_validate import validate_layout  # noqa: E402
from nesting.fusion_layout import (  # noqa: E402
    UnsafeNestingLayoutError,
    create_layout,
)
from nesting.outline import build_outline_payload, close_ring  # noqa: E402


def _item(pid, points, holes=None):
    outline = build_outline_payload(
        close_ring(points), "flatBody", holes=holes or []
    )
    return {
        "id": pid,
        "panelId": pid,
        "bodyName": "body-" + pid,
        "boardTypeTag": "door",
        "colorTag": "white",
        "dimensions": {
            "widthMm": outline["widthMm"],
            "depthMm": outline["depthMm"],
        },
        "outline": outline,
        "tempBody": object(),
    }


def _rect(pid, width=20, height=20):
    return _item(pid, [[0, 0], [width, 0], [width, height], [0, height]])


def _layout(placements, parts_in_part=False):
    output = []
    for index, value in enumerate(placements):
        item, x, y, sheet = value[:4]
        rotation = value[4] if len(value) > 4 else 0
        output.append({
            "id": item["id"],
            "panelId": item["panelId"],
            "bodyName": item["bodyName"],
            "boardTypeTag": "door",
            "sheetIndex": sheet,
            "sheetOriginX": sheet * 200,
            "sheetOriginY": 0,
            "sheetWidthMm": 200,
            "sheetHeightMm": 200,
            "targetX": x + sheet * 200,
            "targetY": y,
            "rotationDeg": rotation,
        })
    return {
        "engine": "test",
        "placements": output,
        "sheets": [
            {
                "sheetIndex": index,
                "originX": index * 200,
                "originY": 0,
                "widthMm": 200,
                "heightMm": 200,
                "boardTypeTag": "door",
            }
            for index in sorted({entry[3] for entry in placements})
        ],
        "partsInPartApplied": parts_in_part,
        "requiredWidthMm": 200 * len({entry[3] for entry in placements}),
        "requiredDepthMm": 200,
    }


def _params(spacing=0, border=0, allow_parts=False):
    return {
        "sheets": [{"boardTypeTag": "door", "widthMm": 200, "heightMm": 200}],
        "spacingMm": spacing,
        "borderMm": border,
        "allowPartsInPart": allow_parts,
    }


class CollisionValidationTests(unittest.TestCase):
    def test_overlap_fails(self):
        a, b = _rect("a"), _rect("b")
        result = validate_layout(
            _layout([(a, 10, 10, 0), (b, 20, 20, 0)]),
            [a, b],
            _params(),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["collisions"][0]["type"], "overlap")

    def test_spacing_boundary_is_legal(self):
        a, b = _rect("a"), _rect("b")
        result = validate_layout(
            _layout([(a, 10, 10, 0), (b, 40, 10, 0)]),
            [a, b],
            _params(spacing=10),
        )
        self.assertTrue(result["ok"])

    def test_spacing_float_near_miss_is_legal(self):
        """Deepnest often lands ~1e-8 below spacingMm; that must not fail."""
        a, b = _rect("a"), _rect("b")
        result = validate_layout(
            _layout([(a, 10, 10, 0), (b, 39.99999999, 10, 0)]),
            [a, b],
            _params(spacing=10),
        )
        self.assertTrue(result["ok"])

    def test_l_notch_overlap_is_legal(self):
        ell = _item(
            "L", [[0, 0], [100, 0], [100, 40], [40, 40], [40, 100], [0, 100]]
        )
        small = _rect("small", 30, 30)
        result = validate_layout(
            _layout([(ell, 0, 0, 0), (small, 50, 50, 0)]),
            [ell, small],
            _params(),
        )
        self.assertTrue(result["ok"])
        self.assertEqual(len(result["exactCandidates"]), 1)

    def test_different_sheets_do_not_collide(self):
        a, b = _rect("a"), _rect("b")
        layout = _layout([(a, 10, 10, 0), (b, 10, 10, 1)])
        # Force identical world coordinates to prove sheet grouping is primary.
        layout["placements"][1]["targetX"] = 10
        layout["placements"][1]["sheetOriginX"] = 0
        layout["sheets"][1]["originX"] = 0
        result = validate_layout(layout, [a, b], _params())
        self.assertTrue(result["ok"])
        self.assertEqual(result["checks"]["pairChecks"], 0)

    def test_border_violation_fails_beyond_slack(self):
        item = _rect("a")
        result = validate_layout(
            _layout([(item, 9.7, 10, 0)]), [item], _params(border=10)
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["borderViolations"][0]["sides"], ["left"])

    def test_mapping_drift_warns(self):
        item = _rect("a")
        layout = _layout([(item, 10, 10, 0)])
        layout["placements"][0]["packedOutline"] = [
            [20, 10], [40, 10], [40, 30], [20, 30], [20, 10]
        ]
        result = validate_layout(layout, [item], _params())
        self.assertTrue(result["ok"])
        self.assertEqual(result["mappingWarningCount"], 1)

    def test_child_in_hole_with_spacing_is_legal(self):
        parent = _item(
            "parent",
            [[0, 0], [100, 0], [100, 100], [0, 100]],
            holes=[{"points": [[20, 20], [80, 20], [80, 80], [20, 80]]}],
        )
        child = _rect("child", 40, 40)
        result = validate_layout(
            _layout(
                [(parent, 0, 0, 0), (child, 30, 30, 0)],
                parts_in_part=True,
            ),
            [parent, child],
            _params(spacing=10, allow_parts=True),
        )
        self.assertTrue(result["ok"])

    def test_child_over_solid_fails(self):
        parent = _item(
            "parent",
            [[0, 0], [100, 0], [100, 100], [0, 100]],
            holes=[{"points": [[20, 20], [80, 20], [80, 80], [20, 80]]}],
        )
        child = _rect("child", 40, 40)
        result = validate_layout(
            _layout(
                [(parent, 0, 0, 0), (child, 10, 30, 0)],
                parts_in_part=True,
            ),
            [parent, child],
            _params(allow_parts=True),
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["collisions"][0]["type"], "overlap")

    @patch("nesting.fusion_layout.collision_validate.validate_fusion_exact")
    @patch("nesting.fusion_layout.collision_validate.validate_layout")
    def test_defense_rejects_before_component_creation(self, polygon, exact):
        unsafe = {
            "ok": False,
            "collisionCount": 1,
            "borderViolationCount": 0,
            "collisions": [{}],
        }
        polygon.return_value = unsafe
        exact.return_value = unsafe
        root = MagicMock()
        item = _rect("a")
        layout = _layout([(item, 10, 10, 0)])
        with self.assertRaises(UnsafeNestingLayoutError):
            create_layout(
                root,
                [item],
                {"x0": 0, "y0": 0, "x1": 200, "y1": 200},
                layout=layout,
                sheet_params=_params(),
            )
        root.occurrences.addNewComponent.assert_not_called()


if __name__ == "__main__":
    unittest.main()
