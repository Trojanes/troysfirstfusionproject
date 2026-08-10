import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL_ATTRIBUTES = ROOT / "panel_attributes"
if str(PANEL_ATTRIBUTES) not in sys.path:
    sys.path.insert(0, str(PANEL_ATTRIBUTES))

import panel_source_ref  # noqa: E402


class Attribute:
    def __init__(self, value):
        self.value = value


class Attributes:
    def __init__(self, values=None):
        self.values = values or {}

    def itemByName(self, group, name):
        value = self.values.get((group, name))
        return Attribute(value) if value is not None else None


class Entity:
    def __init__(self, values=None, native=None):
        self.attributes = Attributes(values)
        self.nativeObject = native


class PanelSourceRefTests(unittest.TestCase):
    def test_reads_canonical_marker_from_native_when_selection_is_proxy(self):
        expected = {
            "entityToken": "token-1",
            "occurrencePath": [1, 3],
            "bodyName": "Body1",
            "componentName": "Fridge",
            "panelId": "manual.Body1",
        }
        native = Entity(
            {
                (
                    "UnifiedCabinet",
                    "sourceRefJson",
                ): json.dumps(expected)
            }
        )
        proxy = Entity(native=native)
        self.assertEqual(panel_source_ref.from_lay_flat_body(proxy), expected)

    def test_path_key_is_exact_when_token_is_unavailable(self):
        ref = panel_source_ref.from_scan_record(
            {
                "entityToken": "",
                "occurrencePath": [2, 5],
                "bodyName": "OH_D1",
                "componentName": "OHC",
                "panelId": "overhead.D1",
            }
        )
        self.assertEqual(panel_source_ref.key(ref), "path:2/5|OH_D1")

    def test_panel_id_alone_is_not_a_source_ref(self):
        self.assertIsNone(
            panel_source_ref.normalize({"panelId": "manual.Body1"})
        )
        self.assertEqual(
            panel_source_ref.key({"panelId": "manual.Body1"}), ""
        )


if __name__ == "__main__":
    unittest.main()
