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
            "componentName": "K_V2",
            "bodyName": "KITCHEN_vPanel_V2",
        })
        self.assertEqual(name, "Kitchen-K_V2")

    def test_unique_suffix_on_collision(self):
        used = set()
        first = names.nesting_workpiece_name({
            "assemblyName": "GT",
            "componentName": "GT_B3",
            "bodyName": "GT_B3",
        }, used)
        second = names.nesting_workpiece_name({
            "assemblyName": "GT",
            "componentName": "GT_B3",
            "bodyName": "GT_B3",
        }, used)
        self.assertEqual(first, "GT-GT_B3")
        self.assertNotEqual(first, second)
        self.assertTrue(second.startswith("GT-GT_B3__"))

    def test_sanitizes_illegal_chars(self):
        name = names.nesting_workpiece_name({
            "assemblyName": "A/B:C",
            "componentName": "D*E",
        })
        self.assertEqual(name, "A_B_C-D_E")


if __name__ == "__main__":
    unittest.main()
