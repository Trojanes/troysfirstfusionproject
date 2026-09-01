"""Offline tests for legacy overhead/kitchen param inference."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from core import assembly_geometry_infer as infer  # noqa: E402
from core import assembly_snapshot as snap  # noqa: E402


def _box(x0, x1, y0, y1, z0, z1, board_id, panel_type="", kind=""):
    bbox = {"x0": x0, "x1": x1, "y0": y0, "y1": y1, "z0": z0, "z1": z1}
    return {
        "boardId": board_id,
        "panelType": panel_type,
        "panelKind": kind,
        "bbox": bbox,
        "source": "designGeometry",
        "thickness": min(x1 - x0, y1 - y0, z1 - z0),
    }


class GeometryInferTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.infer = infer
        cls.snap = snap

    def test_normalize_board_id(self):
        self.assertEqual(self.infer.normalize_board_id("OHC-D1"), "D1")
        self.assertEqual(self.infer.normalize_board_id("kitchen.V0"), "V0")
        self.assertEqual(self.infer.normalize_board_id("ohc.BP"), "BP")

    def test_overhead_zones_from_dividers_and_fronts(self):
        rows = [
            _box(0, 2000, 0, 400, 0, 15, "BP"),
            _box(0, 16, 0, 400, 0, 400, "D0"),
            _box(642, 658, 0, 400, 0, 400, "D1"),
            _box(1392, 1408, 0, 400, 0, 400, "D2"),
            _box(1984, 2000, 0, 400, 0, 400, "D3"),
            _box(20, 630, 384, 400, 40, 400, "FP1", "up_flap", "frontPanel"),
            _box(670, 1380, 384, 400, 40, 400, "FP2", "fixed_panel", "frontPanel"),
            _box(1420, 1980, 384, 400, 40, 400, "FP3", "up_flap", "frontPanel"),
            _box(0, 2000, 0, 400, 385, 400, "T3"),
        ]
        result = self.infer.infer_overhead_params(rows)
        self.assertTrue(result["ok"], result)
        params = result["params"]
        self.assertEqual(params["cabinetWidth"], 2000)
        self.assertEqual(params["cabinetDepth"], 400)
        self.assertEqual([zone["width"] for zone in params["zones"]], [650.0, 750.0, 600.0])
        self.assertEqual([zone["type"] for zone in params["zones"]], ["up_flap", "fixed_panel", "up_flap"])
        self.assertEqual(params["featureWidth"], 16.0)
        self.assertTrue(result["estimated"])

    def test_kitchen_columns_from_v_panels(self):
        rows = [
            _box(0, 15, 0, 254, 0, 880, "V0"),
            _box(444, 459, 0, 254, 0, 880, "V1"),
            _box(872, 887, 0, 254, 0, 880, "V2"),
            _box(20, 430, 254, 270, 55, 880, "FP-L", "left_door", "frontPanel"),
            _box(470, 860, 254, 270, 580, 880, "FP-D", "drawer", "frontPanel"),
            _box(470, 860, 254, 270, 55, 580, "FP-R", "right_door", "frontPanel"),
            _box(15, 872, 0, 254, 0, 15, "B3", "B3"),
        ]
        result = self.infer.infer_kitchen_params(rows)
        self.assertTrue(result["ok"], result)
        params = result["params"]
        self.assertEqual(params["globalSettings"]["length"], 887)
        self.assertEqual(len(params["columns"]), 2)
        self.assertEqual(params["columns"][0]["width"], 444)
        self.assertEqual(params["columns"][1]["width"], 443)
        self.assertEqual(params["columns"][0]["columnType"], "left_door")
        self.assertEqual(params["columns"][1]["columnType"], "custom")
        self.assertEqual([z["zoneType"] for z in params["columns"][1]["zones"]], ["drawer", "right_door"])
        self.assertEqual(params["globalSettings"]["bottomClearanceHeight"], 55)

    def test_kitchen_three_bays_from_side_by_side_fronts(self):
        rows = [
            _box(0, 1792, 0, 100, 55, 70, "B3", "B3"),
            _box(0, 1792, 39, 55, 0, 55, "B1", "B1"),
            _box(2.5, 595, -16, 0, 55, 887.5, "Kitchen-FP1", "left_door", "frontPanel"),
            _box(600, 1190, -16, 0, 55, 887.5, "Kitchen-FP2", "left_door", "frontPanel"),
            _box(1195, 1789, -16, 0, 55, 887.5, "Kitchen-FP3", "right_door", "frontPanel"),
        ]
        result = self.infer.infer_kitchen_params(rows)
        self.assertTrue(result["ok"], result)
        columns = result["params"]["columns"]
        self.assertEqual(len(columns), 3)
        self.assertEqual([col["columnType"] for col in columns], ["left_door", "left_door", "right_door"])
        self.assertGreater(columns[0]["width"], 500)
        self.assertGreater(columns[1]["width"], 500)
        self.assertGreater(columns[2]["width"], 500)
        self.assertEqual(result["frontCount"], 3)

    def test_kitchen_three_bays_from_geometry_without_ids(self):
        rows = [
            _box(0, 15, 0, 588, 0, 890, "", "", ""),
            _box(589, 604, 0, 588, 0, 890, "", "", ""),
            _box(1189, 1204, 0, 588, 0, 890, "", "", ""),
            _box(1777, 1792, 0, 588, 0, 890, "", "", ""),
            _box(20, 580, -16, 0, 55, 887, "", "left_door", ""),
            _box(620, 1170, -16, 0, 55, 887, "", "left_door", ""),
            _box(1220, 1770, -16, 0, 55, 887, "", "right_door", ""),
        ]
        result = self.infer.infer_kitchen_params(rows)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["vCount"], 4)
        self.assertEqual(len(result["params"]["columns"]), 3)
        self.assertEqual(result["params"]["globalSettings"]["length"], 1792)

    def test_bottom_front_strip_is_not_a_door(self):
        rows = [
            _box(0, 1792, 39, 55, 0, 55, "Bottom front panel", "B1"),
            _box(0, 15, 0, 588, 0, 890, "Kitchen-V0", "VPanel", "vPanel"),
            _box(1777, 1792, 0, 588, 0, 890, "Kitchen-V1", "VPanel", "vPanel"),
        ]
        result = self.infer.infer_kitchen_params(rows)
        self.assertEqual(result["frontCount"], 0)
        self.assertEqual(result["vCount"], 2)
        self.assertEqual(len(result["params"]["columns"]), 1)
        self.assertEqual(result["params"]["columns"][0]["columnType"], "open")

    def test_load_from_selection_infers_legacy_overhead(self):
        class _Attr:
            def __init__(self, value):
                self.value = value

        class _Attrs:
            def __init__(self):
                self._items = {}

            def itemByName(self, group, name):
                return self._items.get((group, name))

            def add(self, group, name, value):
                self._items[(group, name)] = _Attr(value)

        class _BBox:
            def __init__(self, box):
                self.minPoint = type("P", (), {"x": box["x0"] / 10, "y": box["y0"] / 10, "z": box["z0"] / 10})()
                self.maxPoint = type("P", (), {"x": box["x1"] / 10, "y": box["y1"] / 10, "z": box["z1"] / 10})()

        class _Bodies:
            def __init__(self, items):
                self._items = items
                self.count = len(items)

            def item(self, index):
                return self._items[index]

        class _Body:
            def __init__(self, name, box, board_id):
                self.name = name
                self.isSolid = True
                self.boundingBox = _BBox(box)
                self.attributes = _Attrs()
                self.attributes.add("CabinetNC", "module", "overhead")
                self.attributes.add("CabinetNC", "boardId", board_id)

        class _Occs:
            def __init__(self):
                self._items = []
                self.count = 0

            def item(self, index):
                return self._items[index]

        class _Component:
            def __init__(self, name="OHC"):
                self.name = name
                self.attributes = _Attrs()
                self.bRepBodies = _Bodies([])
                self.occurrences = _Occs()

        assembly = _Component("OHC")
        assembly.attributes.add("CabinetNC", "module", "overhead")
        assembly.attributes.add("CabinetNC", "assemblyName", "OHC")
        assembly.bRepBodies = _Bodies([
            _Body("BP", {"x0": 0, "x1": 2000, "y0": 0, "y1": 400, "z0": 0, "z1": 15}, "BP"),
            _Body("D0", {"x0": 0, "x1": 16, "y0": 0, "y1": 400, "z0": 0, "z1": 400}, "D0"),
            _Body("D1", {"x0": 1984, "x1": 2000, "y0": 0, "y1": 400, "z0": 0, "z1": 400}, "D1"),
            _Body("FP1", {"x0": 20, "x1": 1980, "y0": 384, "y1": 400, "z0": 40, "z1": 400}, "FP1"),
        ])
        assembly.bRepBodies._items[3].attributes.add("CabinetNC", "panelType", "up_flap")
        assembly.bRepBodies._items[3].attributes.add("CabinetNC", "panelKind", "frontPanel")

        class _Occ:
            def __init__(self, component, parent=None):
                self.component = component
                self.assemblyContext = parent
                self.parentOccurrence = parent
                self.name = component.name
                self.transform = type("T", (), {"translation": type("V", (), {"x": 0, "y": 0, "z": 0})()})()

        result = self.snap.load_from_selection([_Occ(assembly)])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result.get("estimated"))
        self.assertEqual(result["params"]["cabinetWidth"], 2000)
        self.assertEqual(result["params"]["zones"][0]["type"], "up_flap")

    def test_load_from_kitchen_panel_reads_sibling_partitions(self):
        class _Attr:
            def __init__(self, value):
                self.value = value

        class _Attrs:
            def __init__(self):
                self._items = {}

            def itemByName(self, group, name):
                return self._items.get((group, name))

            def add(self, group, name, value):
                self._items[(group, name)] = _Attr(value)

        class _BBox:
            def __init__(self, box):
                self.minPoint = type("P", (), {"x": box["x0"] / 10, "y": box["y0"] / 10, "z": box["z0"] / 10})()
                self.maxPoint = type("P", (), {"x": box["x1"] / 10, "y": box["y1"] / 10, "z": box["z1"] / 10})()

        class _Bodies:
            def __init__(self, items):
                self._items = items
                self.count = len(items)

            def item(self, index):
                return self._items[index]

        class _Occs:
            def __init__(self, items=None):
                self._items = list(items or [])
                self.count = len(self._items)

            def item(self, index):
                return self._items[index]

        class _Component:
            def __init__(self, name):
                self.name = name
                self.attributes = _Attrs()
                self.bRepBodies = _Bodies([])
                self.occurrences = _Occs()

        class _Body:
            def __init__(self, name, box, board_id, panel_type="", kind=""):
                self.name = name
                self.isSolid = True
                self.boundingBox = _BBox(box)
                self.attributes = _Attrs()
                self.attributes.add("CabinetNC", "module", "kitchen")
                self.attributes.add("CabinetNC", "boardId", board_id)
                if panel_type:
                    self.attributes.add("CabinetNC", "panelType", panel_type)
                if kind:
                    self.attributes.add("CabinetNC", "panelKind", kind)

        class _Occ:
            def __init__(self, component, parent=None, box=None):
                self.component = component
                self.assemblyContext = parent
                self.parentOccurrence = parent
                self.name = component.name
                self.boundingBox = _BBox(box) if box else None
                self.bRepBodies = component.bRepBodies
                self.childOccurrences = _Occs()
                self.transform = type("T", (), {"translation": type("V", (), {"x": 0, "y": 0, "z": 0})()})()

        kitchen = _Component("Kitchen")
        kitchen.attributes.add("CabinetNC", "module", "kitchen")
        kitchen.attributes.add("CabinetNC", "assemblyName", "Kitchen")
        kitchen_occ = _Occ(kitchen, box={"x0": 0, "x1": 1792, "y0": -16, "y1": 588, "z0": 0, "z1": 890})
        children = [
            ("Kitchen-V0", {"x0": 0, "x1": 15, "y0": 0, "y1": 588, "z0": 0, "z1": 890}, "V0", "VPanel", "vPanel"),
            ("Kitchen-V1", {"x0": 589, "x1": 604, "y0": 0, "y1": 588, "z0": 0, "z1": 890}, "V1", "VPanel", "vPanel"),
            ("Kitchen-V2", {"x0": 1189, "x1": 1204, "y0": 0, "y1": 588, "z0": 0, "z1": 890}, "V2", "VPanel", "vPanel"),
            ("Kitchen-V3", {"x0": 1777, "x1": 1792, "y0": 0, "y1": 588, "z0": 0, "z1": 890}, "V3", "VPanel", "vPanel"),
            ("Kitchen-FP1", {"x0": 20, "x1": 580, "y0": -16, "y1": 0, "z0": 55, "z1": 887}, "FP1", "left_door", "frontPanel"),
            ("Kitchen-FP2", {"x0": 620, "x1": 1170, "y0": -16, "y1": 0, "z0": 55, "z1": 887}, "FP2", "left_door", "frontPanel"),
            ("Kitchen-FP3", {"x0": 1220, "x1": 1770, "y0": -16, "y1": 0, "z0": 55, "z1": 887}, "FP3", "right_door", "frontPanel"),
            ("Kitchen-B3", {"x0": 0, "x1": 1792, "y0": 0, "y1": 100, "z0": 55, "z1": 70}, "B3", "B3", "board"),
        ]
        child_occs = []
        for name, box, board_id, panel_type, kind in children:
            child = _Component(name)
            child.attributes.add("CabinetNC", "module", "kitchen")
            child.attributes.add("CabinetNC", "boardId", board_id)
            child.attributes.add("CabinetNC", "panelType", panel_type)
            child.attributes.add("CabinetNC", "panelKind", kind)
            child.bRepBodies = _Bodies([_Body(name, box, board_id, panel_type, kind)])
            child_occs.append(_Occ(child, parent=kitchen_occ, box=box))
        kitchen.occurrences = _Occs(child_occs)
        kitchen_occ.childOccurrences = _Occs(child_occs)

        result = self.snap.load_from_selection([child_occs[0]])
        self.assertTrue(result["ok"], result)
        self.assertTrue(result.get("estimated"))
        self.assertEqual(result["assemblyName"], "Kitchen")
        self.assertEqual(len(result["params"]["columns"]), 3)
        self.assertEqual(result["vCount"], 4)
        self.assertEqual(result["frontCount"], 3)
        self.assertGreaterEqual(result["boardCount"], 7)


if __name__ == "__main__":
    unittest.main()
