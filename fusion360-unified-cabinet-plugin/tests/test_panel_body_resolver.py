import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock


ROOT = Path(__file__).resolve().parents[1]
PANEL_ATTR_DIR = ROOT / "panel_attributes"
if str(PANEL_ATTR_DIR) not in sys.path:
    sys.path.insert(0, str(PANEL_ATTR_DIR))

import panel_body_resolver as resolver  # noqa: E402


class PanelBodyResolverTests(unittest.TestCase):
    def test_body_matches_record_uses_panel_id_for_disambiguation(self):
        body_a = MagicMock()
        body_a.entityToken = "token-a"
        body_a.name = "OH_D3"
        body_a.attributes = MagicMock()
        body_a.attributes.itemByName.return_value = MagicMock(value="panel-a")

        body_b = MagicMock()
        body_b.entityToken = "token-b"
        body_b.name = "OH_D3"
        body_b.attributes = MagicMock()
        body_b.attributes.itemByName.return_value = MagicMock(value="panel-b")

        record = {
            "entityToken": "",
            "bodyName": "OH_D3",
            "panelId": "panel-b",
        }

        self.assertFalse(resolver.body_matches_record(body_a, record))
        self.assertTrue(resolver.body_matches_record(body_b, record))

    def test_find_body_in_design_prefers_panel_id_when_names_duplicate(self):
        root = MagicMock()
        root.occurrences.count = 0

        body_a = MagicMock()
        body_a.entityToken = "token-a"
        body_a.name = "OH_D3"
        body_a.isSolid = True
        body_a.isVisible = True
        body_a.attributes = MagicMock()
        body_a.attributes.itemByName.return_value = MagicMock(value="panel-a")

        body_b = MagicMock()
        body_b.entityToken = "token-b"
        body_b.name = "OH_D3"
        body_b.isSolid = True
        body_b.isVisible = True
        body_b.attributes = MagicMock()
        body_b.attributes.itemByName.return_value = MagicMock(value="panel-b")

        root.bRepBodies.count = 2
        root.bRepBodies.item.side_effect = lambda index: body_a if index == 0 else body_b

        found = resolver.find_body_in_design(
            root,
            {"bodyName": "OH_D3", "panelId": "panel-b", "occurrencePath": []},
        )
        self.assertIs(found, body_b)

    def test_nesting_workpiece_is_excluded_by_system_role(self):
        body = MagicMock()

        def attr(group, name):
            if group == "UnifiedCabinet" and name == "systemRole":
                return MagicMock(value="nestingWorkpiece")
            return None

        body.attributes.itemByName.side_effect = attr
        self.assertTrue(resolver._is_nested_instance(body))


if __name__ == "__main__":
    unittest.main()
