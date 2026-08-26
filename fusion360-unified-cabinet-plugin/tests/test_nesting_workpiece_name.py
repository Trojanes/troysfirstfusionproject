import os
import sys
import unittest


NESTING = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "nesting"))
if NESTING not in sys.path:
    sys.path.insert(0, NESTING)

import workpiece_names as names  # noqa: E402


class NestingWorkpieceNameTests(unittest.TestCase):
    def test_assembly_component_format(self):
        name = names.nesting_workpiece_name({
            "assemblyName": "Kitchen",
            "componentName": "Kitchen-V2",
            "bodyName": "Kitchen-V2",
        })
        self.assertEqual(name, "Kitchen-V2")

    def test_unique_suffix_on_collision(self):
        used = set()
        first = names.nesting_workpiece_name({
            "assemblyName": "GT",
            "componentName": "GT-B3",
            "bodyName": "GT-B3",
        }, used)
        second = names.nesting_workpiece_name({
            "assemblyName": "GT",
            "componentName": "GT-B3",
            "bodyName": "GT-B3",
        }, used)
        self.assertEqual(first, "GT-B3")
        self.assertNotEqual(first, second)
        self.assertTrue(second.startswith("GT-B3__"))

    def test_legacy_child_prefix_is_stripped(self):
        self.assertEqual(
            names.nesting_workpiece_name({
                "assemblyName": "GT",
                "componentName": "GT_B3",
                "bodyName": "GT_B3",
            }),
            "GT-B3",
        )
        self.assertEqual(
            names.nesting_workpiece_name({
                "assemblyName": "Kitchen",
                "componentName": "K_V2",
                "bodyName": "KITCHEN_vPanel_V2",
            }),
            "Kitchen-V2",
        )
        self.assertEqual(
            names.board_component_label("Island", "V1"),
            "Island-V1",
        )

    def test_sanitizes_illegal_chars(self):
        name = names.nesting_workpiece_name({
            "assemblyName": "A/B:C",
            "componentName": "D*E",
        })
        self.assertEqual(name, "A_B_C-D_E")

    def test_kitchen_blob_assembly_uses_body_part(self):
        name = names.nesting_workpiece_name({
            "assemblyName": "KITCHEN_KITCHEN_FLAT_ASSEMBLY_2026-07-07T12:34:56.789",
            "componentName": "KITCHEN_KITCHEN_FLAT_ASSEMBLY_2026-07-07T12:34:56.789",
            "bodyName": "KITCHEN_vPanel_V2",
        })
        self.assertEqual(name, "Kitchen-V2")

    def test_kitchen_blob_front_panel_keeps_id(self):
        name = names.nesting_workpiece_name({
            "assemblyName": "KITCHEN_KITCHEN_FLAT_ASSEMBLY_2026-07-07T12:34:56.789",
            "componentName": "KITCHEN_KITCHEN_FLAT_ASSEMBLY_2026-07-07T12:34:56.789",
            "bodyName": "KITCHEN_frontPanel_k-zone-left-door",
        })
        self.assertEqual(name, "Kitchen-k-zone-left-door")

    def test_kitchen_blob_names_stay_unique(self):
        used = set()
        a = names.nesting_workpiece_name({
            "assemblyName": "KITCHEN_FLAT_ASSEMBLY_2026-07-07T01:02:03",
            "componentName": "KITCHEN_FLAT_ASSEMBLY_2026-07-07T01:02:03",
            "bodyName": "KITCHEN_hPanel_H1",
        }, used)
        b = names.nesting_workpiece_name({
            "assemblyName": "KITCHEN_FLAT_ASSEMBLY_2026-07-07T01:02:03",
            "componentName": "KITCHEN_FLAT_ASSEMBLY_2026-07-07T01:02:03",
            "bodyName": "KITCHEN_hPanel_H2",
        }, used)
        self.assertEqual(a, "Kitchen-H1")
        self.assertEqual(b, "Kitchen-H2")

    def test_is_blob_label(self):
        self.assertTrue(names.is_blob_label(
            "KITCHEN_KITCHEN_FLAT_ASSEMBLY_2026-07-07T12:34:56"
        ))
        self.assertTrue(names.is_blob_label("1786501234567"))
        self.assertFalse(names.is_blob_label("Kitchen"))
        self.assertFalse(names.is_blob_label("OHC_1"))

    def test_generator_assembly_name_keeps_explicit_and_rejects_run_blob(self):
        self.assertEqual(
            names.resolve_assembly_name(
                "Bunk_Tall_Right_1",
                run_label="GT_2026-08-12T01-02-03",
                default_name="GT",
                include_human_run_label=True,
            ),
            "Bunk_Tall_Right_1",
        )
        self.assertEqual(
            names.resolve_assembly_name(
                "",
                run_label="KITCHEN_FLAT_ASSEMBLY_2026-08-12T01-02-03",
                default_name="Kitchen",
                include_human_run_label=True,
            ),
            "Kitchen",
        )
        self.assertEqual(
            names.resolve_assembly_name(
                "",
                run_label="Guest",
                default_name="Kitchen",
                include_human_run_label=True,
            ),
            "Kitchen_Guest",
        )

    def test_lay_flat_and_export_resolvers_are_identical(self):
        placement = {
            "panelId": "overhead.BP@layflat-1-24",
            "assemblyName": "OHC_1",
            "componentName": "OHC_1-BP",
            "bodyName": "OHC_1-BP",
        }
        browser_name = names.nesting_workpiece_name(placement)
        export_name = names.display_workpiece_name(
            {
                "bodyName": browser_name,
                "assemblyName": "LAY_FLAT:1",
                "componentName": "LAY_FLAT",
                "metadata": {
                    "identity": {
                        "sourceRef": {
                            "assemblyName": "OHC_1",
                            "componentName": "OHC_1-BP",
                            "bodyName": "OHC_1-BP",
                            "panelId": "overhead.BP",
                        }
                    }
                },
            },
            placement["panelId"],
        )
        self.assertEqual(browser_name, "OHC_1-BP")
        self.assertEqual(export_name, browser_name)

    def test_identity_suffix_is_not_part_of_display_name(self):
        self.assertEqual(
            names.resolve_shop_label(
                body_name="Body1",
                panel_id="manual.Body1@layflat-0-2",
            ),
            "manual.Body1",
        )


if __name__ == "__main__":
    unittest.main()
