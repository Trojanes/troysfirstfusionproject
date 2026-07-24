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

from nesting.collision_validate import (  # noqa: E402
    _broadphase_pairs_3d,
    validate_fusion_exact,
    validate_layout,
)
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


class _Point:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Box:
    def __init__(self, x0, y0, z0, x1, y1, z1):
        self.minPoint = _Point(x0, y0, z0)
        self.maxPoint = _Point(x1, y1, z1)


class _Body:
    def __init__(self, bounds):
        self.boundingBox = _Box(*bounds)
        self.volume = 1.0


class _Matrix:
    def __init__(self):
        self.translation = None

    def setToRotation(self, *_args):
        return None


class _Manager:
    def copy(self, body):
        box = body.boundingBox
        return _Body((
            box.minPoint.x, box.minPoint.y, box.minPoint.z,
            box.maxPoint.x, box.maxPoint.y, box.maxPoint.z,
        ))

    def transform(self, body, matrix):
        vector = matrix.translation
        if vector is None:
            return True
        box = body.boundingBox
        body.boundingBox = _Box(
            box.minPoint.x + vector.x,
            box.minPoint.y + vector.y,
            box.minPoint.z + vector.z,
            box.maxPoint.x + vector.x,
            box.maxPoint.y + vector.y,
            box.maxPoint.z + vector.z,
        )
        return True

    def booleanOperation(self, target, tool, _operation):
        a, b = target.boundingBox, tool.boundingBox
        dx = max(0.0, min(a.maxPoint.x, b.maxPoint.x) - max(a.minPoint.x, b.minPoint.x))
        dy = max(0.0, min(a.maxPoint.y, b.maxPoint.y) - max(a.minPoint.y, b.minPoint.y))
        dz = max(0.0, min(a.maxPoint.z, b.maxPoint.z) - max(a.minPoint.z, b.minPoint.z))
        target.volume = dx * dy * dz
        return True


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

    def test_overlapping_physical_sheets_are_unsafe(self):
        a, b = _rect("a"), _rect("b")
        layout = _layout([(a, 10, 10, 0), (b, 10, 10, 1)])
        # Force identical world coordinates to prove sheet grouping is primary.
        layout["placements"][1]["targetX"] = 10
        layout["placements"][1]["sheetOriginX"] = 0
        layout["sheets"][1]["originX"] = 0
        result = validate_layout(layout, [a, b], _params())
        self.assertFalse(result["ok"])
        self.assertEqual(result["sheetOverlapCount"], 1)
        self.assertEqual(result["checks"]["pairChecks"], 0)

    def test_border_violation_fails_beyond_slack(self):
        item = _rect("a")
        result = validate_layout(
            _layout([(item, 9.7, 10, 0)]), [item], _params(border=10)
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["borderViolations"][0]["sides"], ["left"])

    def test_mapping_drift_is_unsafe(self):
        item = _rect("a")
        layout = _layout([(item, 10, 10, 0)])
        layout["placements"][0]["packedOutline"] = [
            [20, 10], [40, 10], [40, 30], [20, 30], [20, 10]
        ]
        result = validate_layout(layout, [item], _params())
        self.assertFalse(result["ok"])
        self.assertEqual(result["mappingWarningCount"], 1)

    def test_simplified_packed_outline_is_not_mapping_drift(self):
        item = _item(
            "a",
            [
                [0, 0], [5, 0], [10, -0.8], [15, 0], [20, 0],
                [20, 5], [20, 10], [20, 15], [20, 20],
                [15, 20], [10, 20], [5, 20], [0, 20],
                [0, 15], [0, 10], [0, 5],
            ],
        )
        layout = _layout([(item, 10, 10, 0)])
        layout["placements"][0]["packedOutline"] = [
            [10, 10.8], [30, 10.8], [30, 30.8], [10, 30.8], [10, 10.8]
        ]
        result = validate_layout(layout, [item], _params())
        self.assertTrue(result["ok"])
        self.assertEqual(result["mappingWarningCount"], 0)

    def test_real_brep_broadphase_only_returns_3d_overlaps(self):
        bounds = {
            0: {"minX": 0, "minY": 0, "minZ": 0, "maxX": 20, "maxY": 20, "maxZ": 2},
            1: {"minX": 10, "minY": 10, "minZ": 0, "maxX": 30, "maxY": 30, "maxZ": 2},
            2: {"minX": 10, "minY": 10, "minZ": 3, "maxX": 30, "maxY": 30, "maxZ": 5},
            3: {"minX": 40, "minY": 40, "minZ": 0, "maxX": 50, "maxY": 50, "maxZ": 2},
        }
        self.assertEqual(_broadphase_pairs_3d(bounds), [(0, 1)])

    def test_real_brep_detects_overlap_missed_by_cached_outlines(self):
        a, b = _rect("a", 10, 10), _rect("b", 10, 10)
        # Actual bodies are 20x20 mm while stale cached outlines are 10x10 mm.
        a["tempBody"] = _Body((0, 0, 0, 2, 2, 1))
        b["tempBody"] = _Body((0, 0, 0, 2, 2, 1))
        layout = _layout([(a, 0, 0, 0), (b, 15, 0, 0)])
        polygon = validate_layout(layout, [a, b], _params())
        self.assertTrue(polygon["ok"])
        manager = _Manager()
        import adsk.core
        import adsk.fusion
        with patch.object(adsk.fusion.TemporaryBRepManager, "get", return_value=manager), \
             patch.object(adsk.core.Matrix3D, "create", side_effect=_Matrix), \
             patch.object(
                 adsk.core.Vector3D,
                 "create",
                 side_effect=lambda x, y, z: _Point(x, y, z),
             ):
            result = validate_fusion_exact(layout, [a, b], _params(), polygon)
        self.assertFalse(result["ok"])
        self.assertGreaterEqual(result["mappingWarningCount"], 2)
        self.assertTrue(
            any(collision.get("source") == "temporaryBRep" for collision in result["collisions"])
        )

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
