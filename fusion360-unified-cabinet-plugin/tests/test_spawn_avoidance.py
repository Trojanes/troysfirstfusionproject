"""Kitchen/OHC spawn avoidance (no Fusion runtime required)."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
GEOMETRY_PATH = PLUGIN_ROOT / "fusion" / "geometry_ops.py"


def _load_geometry_ops():
    if "adsk" not in sys.modules:
        adsk = types.ModuleType("adsk")
        adsk.core = types.ModuleType("adsk.core")
        sys.modules["adsk"] = adsk
        sys.modules["adsk.core"] = adsk.core
    spec = importlib.util.spec_from_file_location("geometry_ops_avoid_test", GEOMETRY_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _Point:
    def __init__(self, x, y, z):
        self.x = x
        self.y = y
        self.z = z


class _BBox:
    def __init__(self, x0, y0, z0, x1, y1, z1):
        self.minPoint = _Point(x0 / 10.0, y0 / 10.0, z0 / 10.0)
        self.maxPoint = _Point(x1 / 10.0, y1 / 10.0, z1 / 10.0)


class _Collection:
    def __init__(self, items):
        self._items = items
        self.count = len(items)

    def item(self, index):
        return self._items[index]


class _Occurrence:
    def __init__(self, bbox_mm):
        self.boundingBox = _BBox(*bbox_mm)


class _Body:
    def __init__(self, bbox_mm, solid=True):
        self.boundingBox = _BBox(*bbox_mm)
        self.isSolid = solid


class _Root:
    def __init__(self, occurrences=None, bodies=None):
        self.occurrences = _Collection(occurrences or [])
        self.bRepBodies = _Collection(bodies or [])


class SpawnAvoidanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ops = _load_geometry_ops()

    def test_kitchen_shifts_when_lounge_ohc_occupies_origin(self):
        ohc = _Occurrence((0, 0, 0, 1898, 400, 425))
        root = _Root(occurrences=[ohc])
        origin_x, origin_y, info = self.ops.avoid_existing_at_origin(
            root, 0.0, 0.0, (0.0, 1792.0, -16.0, 604.0)
        )
        self.assertEqual(info["existingCount"], 1)
        self.assertTrue(info["shifted"])
        self.assertGreater(origin_x, 1792.0)
        self.assertEqual(origin_y, 0.0)

    def test_empty_design_stays_at_origin(self):
        origin_x, origin_y, info = self.ops.avoid_existing_at_origin(
            _Root(), 0.0, 0.0, (0.0, 1792.0, -16.0, 604.0)
        )
        self.assertEqual(info["existingCount"], 0)
        self.assertFalse(info["shifted"])
        self.assertEqual(origin_x, 0.0)
        self.assertEqual(origin_y, 0.0)

    def test_legacy_high_z_staging_is_ignored(self):
        staged = _Occurrence((0, 0, 10000, 1800, 400, 10425))
        origin_x, _origin_y, info = self.ops.avoid_existing_at_origin(
            _Root(occurrences=[staged]), 0.0, 0.0, (0.0, 1792.0, 0.0, 600.0)
        )
        self.assertEqual(info["existingCount"], 0)
        self.assertFalse(info["shifted"])
        self.assertEqual(origin_x, 0.0)


if __name__ == "__main__":
    unittest.main()
