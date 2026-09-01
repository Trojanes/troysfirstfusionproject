"""Offline tests for generator-assembly param snapshots (no Fusion runtime)."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT_PATH = PLUGIN_ROOT / "core" / "assembly_snapshot.py"


def _load_snapshot():
    spec = importlib.util.spec_from_file_location("assembly_snapshot_under_test", SNAPSHOT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


class _Transform:
    def __init__(self, x_mm=0.0, y_mm=0.0, z_mm=0.0):
        self.translation = type("T", (), {"x": x_mm / 10.0, "y": y_mm / 10.0, "z": z_mm / 10.0})()


class _Component:
    def __init__(self, name="OHC"):
        self.name = name
        self.attributes = _Attrs()


class _Occurrence:
    def __init__(self, component, parent=None, origin_mm=(0.0, 0.0, 0.0)):
        self.component = component
        self.assemblyContext = parent
        self.parentOccurrence = parent
        self.name = component.name
        self.transform = _Transform(*origin_mm)
        self._deleted = False

    def deleteMe(self):
        self._deleted = True


class _Body:
    def __init__(self, occurrence):
        self.assemblyContext = occurrence
        self.attributes = _Attrs()


class _Face:
    def __init__(self, body):
        self.body = body


class _Root:
    def __init__(self, occurrences):
        self.occurrences = _Collection(occurrences)


class _Collection:
    def __init__(self, items):
        self._items = list(items)
        self.count = len(self._items)

    def item(self, index):
        return self._items[index]


class AssemblySnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snap = _load_snapshot()

    def _oh_assembly(self, params=None, origin=(1200.0, 400.0, 0.0), run_label="OHC_1"):
        component = _Component("OHC")
        occ = _Occurrence(component, origin_mm=origin)
        self.snap.write_generator_snapshot(
            component,
            "overhead",
            params or {"cabinetWidth": 2000, "zones": [{"id": "z1", "type": "left_door", "width": 1000}]},
            run_label=run_label,
            assembly_name="OHC",
            origin={"x": origin[0], "y": origin[1], "z": origin[2]},
        )
        return occ, component

    def test_write_and_read_roundtrip(self):
        occ, component = self._oh_assembly()
        snapshot = self.snap.read_generator_snapshot(component)
        self.assertEqual(snapshot["module"], "overhead")
        self.assertEqual(snapshot["runLabel"], "OHC_1")
        self.assertEqual(snapshot["params"]["cabinetWidth"], 2000)
        self.assertEqual(snapshot["paramsSchema"], "overhead.v1")
        self.assertTrue(snapshot["hasParams"])
        self.assertEqual(snapshot["origin"]["x"], 1200.0)

    def test_load_from_child_body_selection(self):
        occ, component = self._oh_assembly()
        panel = _Component("OHC-D1")
        panel.attributes.add("CabinetNC", "module", "overhead")
        panel.attributes.add("CabinetNC", "boardId", "D1")
        panel_occ = _Occurrence(panel, parent=occ)
        body = _Body(panel_occ)
        result = self.snap.load_from_selection([body])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["module"], "overhead")
        self.assertEqual(result["runLabel"], "OHC_1")
        self.assertEqual(result["params"]["cabinetWidth"], 2000)

    def test_load_from_face_climbs_to_assembly(self):
        occ, _component = self._oh_assembly()
        panel = _Component("OHC-BP")
        panel_occ = _Occurrence(panel, parent=occ)
        face = _Face(_Body(panel_occ))
        result = self.snap.load_from_selection([face])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["assemblyName"], "OHC")

    def test_legacy_assembly_without_params_or_boards(self):
        component = _Component("Kitchen")
        component.attributes.add("CabinetNC", "module", "kitchen")
        component.attributes.add("CabinetNC", "assemblyName", "Kitchen")
        occ = _Occurrence(component)
        result = self.snap.load_from_selection([occ])
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "legacy_infer_failed")

    def test_unsupported_module(self):
        component = _Component("GT")
        component.attributes.add("CabinetNC", "module", "generalTall")
        component.attributes.add("CabinetNC", "generatorParams", '{"cabinetHeight": 2100}')
        occ = _Occurrence(component)
        result = self.snap.load_from_selection([occ])
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "unsupported_module")

    def test_empty_selection(self):
        result = self.snap.load_from_selection([])
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], "empty_selection")

    def test_kitchen_snapshot_schema(self):
        component = _Component("Kitchen")
        params = {
            "version": 1,
            "globalSettings": {"length": 900, "depth": 560, "height": 880},
            "columns": [{"id": "c1", "width": 900, "columnType": "left_door", "zones": []}],
            "wheelAvoidances": [],
        }
        self.snap.write_generator_snapshot(
            component, "kitchen", params, run_label="KITCHEN_1", assembly_name="Kitchen"
        )
        snapshot = self.snap.read_generator_snapshot(component)
        self.assertEqual(snapshot["paramsSchema"], "kitchen.v1")
        self.assertEqual(snapshot["params"]["globalSettings"]["length"], 900)

    def test_delete_by_run_label(self):
        occ, _component = self._oh_assembly(run_label="OHC_KEEP")
        other = _Component("OHC_2")
        self.snap.write_generator_snapshot(
            other, "overhead", {"cabinetWidth": 1}, run_label="OHC_OTHER", assembly_name="OHC_2"
        )
        other_occ = _Occurrence(other)
        root = _Root([occ, other_occ])
        deleted = self.snap.delete_assembly_by_run_label(root, "overhead", "OHC_KEEP")
        self.assertEqual(deleted["occurrences"], 1)
        self.assertTrue(occ._deleted)
        self.assertFalse(other_occ._deleted)

    def test_writes_both_attribute_groups(self):
        component = _Component("OHC")
        self.snap.write_generator_snapshot(
            component, "overhead", {"cabinetWidth": 12}, run_label="R", assembly_name="OHC"
        )
        self.assertTrue(component.attributes.itemByName("CabinetNC", "generatorParams"))
        self.assertTrue(component.attributes.itemByName("UnifiedCabinetPlugin", "generatorParams"))

    def test_panel_with_module_is_not_assembly(self):
        panel = _Component("Kitchen-V1")
        panel.attributes.add("CabinetNC", "module", "kitchen")
        panel.attributes.add("CabinetNC", "boardId", "V1")
        self.assertFalse(self.snap.is_assembly_component(panel))

    def test_load_from_panel_uses_parent_occurrence_not_assembly_context(self):
        occ, _component = self._oh_assembly()
        panel = _Component("OHC-D1")
        panel.attributes.add("CabinetNC", "module", "overhead")
        panel.attributes.add("CabinetNC", "boardId", "D1")
        panel_occ = _Occurrence(panel, parent=occ)
        panel_occ.assemblyContext = None
        result = self.snap.load_from_selection([panel_occ])
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["assemblyName"], "OHC")
        self.assertEqual(result["params"]["cabinetWidth"], 2000)


if __name__ == "__main__":
    unittest.main()
