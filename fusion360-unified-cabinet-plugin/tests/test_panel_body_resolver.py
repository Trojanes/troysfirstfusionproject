import sys
import unittest
from pathlib import Path
from unittest import mock
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

    def test_find_original_body_by_panel_id_skips_lay_flat_copy(self):
        root = MagicMock()
        root.occurrences.count = 0

        original = MagicMock()
        original.name = "Door"
        original.isSolid = True
        original.isVisible = True
        original.attributes = MagicMock()

        def original_attr(group, name):
            if group == "UnifiedCabinet" and name == "panelId":
                return MagicMock(value="P-1")
            if group == "UnifiedCabinet" and name == "instanceRole":
                return None
            if group == "UnifiedCabinet" and name == "systemRole":
                return None
            return None

        original.attributes.itemByName.side_effect = original_attr

        lay_flat = MagicMock()
        lay_flat.name = "Assembly-Door"
        lay_flat.isSolid = True
        lay_flat.isVisible = True
        lay_flat.attributes = MagicMock()

        def lay_flat_attr(group, name):
            if group == "UnifiedCabinet" and name == "panelId":
                return MagicMock(value="P-1")
            if group == "UnifiedCabinet" and name == "instanceRole":
                return MagicMock(value="layFlat")
            if group == "UnifiedCabinet" and name == "systemRole":
                return MagicMock(value="layFlatWorkpiece")
            return None

        lay_flat.attributes.itemByName.side_effect = lay_flat_attr

        # read_body_panel_id uses PANEL_ATTRIBUTE_GROUP + PANEL_ID_ATTR
        from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR

        def original_attr2(group, name):
            if group == PANEL_ATTRIBUTE_GROUP and name == PANEL_ID_ATTR:
                return MagicMock(value="P-1")
            if group == "UnifiedCabinet" and name == "instanceRole":
                return None
            if group == "UnifiedCabinet" and name == "systemRole":
                return None
            return None

        def lay_flat_attr2(group, name):
            if group == PANEL_ATTRIBUTE_GROUP and name == PANEL_ID_ATTR:
                return MagicMock(value="P-1")
            if group == "UnifiedCabinet" and name == "instanceRole":
                return MagicMock(value="layFlat")
            if group == "UnifiedCabinet" and name == "systemRole":
                return MagicMock(value="layFlatWorkpiece")
            return None

        original.attributes.itemByName.side_effect = original_attr2
        lay_flat.attributes.itemByName.side_effect = lay_flat_attr2

        root.bRepBodies.count = 2
        root.bRepBodies.item.side_effect = lambda index: lay_flat if index == 0 else original

        found = resolver.find_original_body_by_panel_id(root, "P-1")
        self.assertIs(found, original)
        self.assertTrue(resolver._is_copy_instance(lay_flat))
        self.assertFalse(resolver._is_copy_instance(original))

    def test_find_original_body_uses_metadata_panel_id_and_prefers_oh_name(self):
        from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR

        root = MagicMock()
        root.occurrences.count = 0

        oh = MagicMock()
        oh.name = "OH_D1"
        oh.isSolid = True
        oh.isVisible = False  # hidden assembly board
        oh.parentComponent = MagicMock(name="OH_D1")
        oh.parentComponent.name = "OH_D1"
        oh.attributes = MagicMock()
        oh.attributes.itemByName.return_value = None
        oh.entityToken = "tok-oh"

        uoh = MagicMock()
        uoh.name = "UOH_LEFT_D1"
        uoh.isSolid = True
        uoh.isVisible = True
        uoh.parentComponent = MagicMock(name="UOH_LEFT_D1")
        uoh.parentComponent.name = "UOH_LEFT_D1"
        uoh.attributes = MagicMock()
        uoh.entityToken = "tok-uoh"

        def uoh_attr(group, name):
            if group == PANEL_ATTRIBUTE_GROUP and name == PANEL_ID_ATTR:
                return MagicMock(value="overhead.D1")
            return None

        uoh.attributes.itemByName.side_effect = uoh_attr

        root.bRepBodies.count = 2
        root.bRepBodies.item.side_effect = lambda index: oh if index == 0 else uoh

        with mock.patch.object(
            resolver,
            "_metadata_panel_id",
            side_effect=lambda body: "overhead.D1" if body is oh else "",
        ):
            found = resolver.find_original_body_by_panel_id(root, "overhead.D1")
        self.assertIs(found, oh)

    def test_find_original_body_name_fallback_for_oh_board(self):
        root = MagicMock()
        root.occurrences.count = 0

        oh = MagicMock()
        oh.name = "OH_D1"
        oh.isSolid = True
        oh.isVisible = True
        oh.parentComponent = MagicMock()
        oh.parentComponent.name = "OH_D1"
        oh.attributes = MagicMock()
        oh.attributes.itemByName.return_value = None
        oh.entityToken = "tok-oh"

        root.bRepBodies.count = 1
        root.bRepBodies.item.side_effect = lambda index: oh

        with mock.patch.object(resolver, "_metadata_panel_id", return_value=""):
            found = resolver.find_original_body_by_panel_id(root, "overhead.D1")
        self.assertIs(found, oh)

    def test_indexed_lookup_avoids_repeated_walks(self):
        root = MagicMock()
        root.occurrences.count = 0
        oh = MagicMock()
        oh.name = "OH_D1"
        oh.isSolid = True
        oh.isVisible = True
        oh.parentComponent = MagicMock()
        oh.parentComponent.name = "OH_D1"
        oh.attributes = MagicMock()
        oh.entityToken = "tok-oh"

        from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR

        def oh_attr(group, name):
            if group == PANEL_ATTRIBUTE_GROUP and name == PANEL_ID_ATTR:
                return MagicMock(value="overhead.D1")
            return None

        oh.attributes.itemByName.side_effect = oh_attr
        root.bRepBodies.count = 1
        root.bRepBodies.item.side_effect = lambda index: oh

        index = resolver.build_original_body_index_by_panel_id(root)
        self.assertIn("overhead.D1", index["by_id"])
        found = resolver.find_original_body_by_panel_id(
            root, "overhead.D1", index=index
        )
        self.assertIs(found, oh)

    def test_resolve_source_prefers_entity_token_over_panel_id_collision(self):
        root = MagicMock()
        root.occurrences.count = 0

        target = MagicMock()
        target.name = "Body1"
        target.isSolid = True
        target.isVisible = True
        target.entityToken = "tok-fridge-a"
        target.parentComponent = MagicMock()
        target.parentComponent.name = "Component603"
        target.attributes = MagicMock()
        target.attributes.itemByName.return_value = None

        other = MagicMock()
        other.name = "Body1"
        other.isSolid = True
        other.isVisible = True
        other.entityToken = "tok-fridge-b"
        other.parentComponent = MagicMock()
        other.parentComponent.name = "Component604"
        other.attributes = MagicMock()
        other.attributes.itemByName.return_value = None

        from panel_metadata_types import PANEL_ATTRIBUTE_GROUP, PANEL_ID_ATTR

        def panel_attr(value):
            def _attr(group, name):
                if group == PANEL_ATTRIBUTE_GROUP and name == PANEL_ID_ATTR:
                    return MagicMock(value=value)
                return None

            return _attr

        target.attributes.itemByName.side_effect = panel_attr("manual.Body1")
        other.attributes.itemByName.side_effect = panel_attr("manual.Body1")

        root.bRepBodies.count = 2
        root.bRepBodies.item.side_effect = lambda index: target if index == 0 else other

        lay_flat = MagicMock()

        def lay_attr(group, name):
            values = {
                ("UnifiedCabinet", "sourcePanelId"): "manual.Body1",
                ("UnifiedCabinet", "sourceEntityToken"): "tok-fridge-a",
                ("UnifiedCabinet", "sourceBodyName"): "Body1",
                ("UnifiedCabinet", "sourceOccurrencePath"): "[0,3]",
            }
            value = values.get((group, name))
            return MagicMock(value=value) if value is not None else None

        lay_flat.attributes.itemByName.side_effect = lay_attr

        bodies, ref, resolution = resolver.resolve_source_bodies_for_lay_flat(
            root, lay_flat
        )
        self.assertEqual(resolution, "entityToken")
        self.assertEqual(ref["sourcePanelId"], "manual.Body1")
        self.assertEqual(len(bodies), 1)
        self.assertIs(bodies[0], target)

    def test_resolve_source_rejects_ambiguous_panel_id_fallback(self):
        root = MagicMock()
        lay_flat = MagicMock()
        with mock.patch.object(
            resolver,
            "read_lay_flat_source_ref",
            return_value={
                "sourcePanelId": "manual.Body1",
                "sourceEntityToken": "",
                "sourceBodyName": "",
                "sourceOccurrencePath": [],
            },
        ), mock.patch.object(
            resolver,
            "find_original_bodies_by_panel_id",
            return_value=[MagicMock(), MagicMock()],
        ):
            bodies, _ref, resolution = (
                resolver.resolve_source_bodies_for_lay_flat(root, lay_flat)
            )
        self.assertEqual(bodies, [])
        self.assertEqual(resolution, "ambiguousPanelId")

    def test_write_resolution_never_uses_even_unique_panel_id_fallback(self):
        root = MagicMock()
        lay_flat = MagicMock()
        with mock.patch.object(
            resolver,
            "read_lay_flat_source_ref",
            return_value={
                "sourcePanelId": "overhead.D1",
                "sourceEntityToken": "",
                "sourceBodyName": "",
                "sourceOccurrencePath": [],
                "sourceKey": "",
                "sourceRef": None,
            },
        ), mock.patch.object(
            resolver,
            "find_original_bodies_by_panel_id",
            return_value=[MagicMock()],
        ) as panel_lookup:
            bodies, _ref, resolution = (
                resolver.resolve_source_bodies_for_lay_flat(
                    root,
                    lay_flat,
                    allow_panel_id_fallback=False,
                )
            )
        self.assertEqual(bodies, [])
        self.assertEqual(resolution, "missingLineage")
        panel_lookup.assert_not_called()

    def test_occurrence_path_resolution_returns_proxy_not_native_body(self):
        native = MagicMock()
        native.name = "OH_D1"
        native.isSolid = True
        native.isVisible = True
        native.isProxy = False

        proxy = MagicMock()
        proxy.name = "OH_D1"
        proxy.isSolid = True
        proxy.isVisible = True
        proxy.isProxy = True
        proxy.nativeObject = native
        native.createForAssemblyContext.return_value = proxy

        component = MagicMock()
        component.bRepBodies.count = 1
        component.bRepBodies.item.return_value = native
        component.occurrences.count = 0

        occurrence = MagicMock()
        occurrence.component = component
        root = MagicMock()
        root.occurrences.count = 1
        root.occurrences.item.return_value = occurrence

        lay_flat = MagicMock()
        with mock.patch.object(
            resolver,
            "read_lay_flat_source_ref",
            return_value={
                "sourcePanelId": "overhead.D1",
                "sourceEntityToken": "",
                "sourceBodyName": "OH_D1",
                "sourceOccurrencePath": [0],
                "sourceKey": "path:0|OH_D1",
                "sourceRef": {
                    "entityToken": "",
                    "occurrencePath": [0],
                    "bodyName": "OH_D1",
                    "panelId": "overhead.D1",
                },
            },
        ):
            bodies, _ref, resolution = (
                resolver.resolve_source_bodies_for_lay_flat(
                    root,
                    lay_flat,
                    allow_panel_id_fallback=False,
                )
            )
        self.assertEqual(resolution, "occurrencePath")
        self.assertEqual(bodies, [proxy])
        native.createForAssemblyContext.assert_called_once_with(occurrence)


if __name__ == "__main__":
    unittest.main()
