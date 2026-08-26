import os
import sys
import unittest


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_ATTR_DIR = os.path.join(ROOT, "panel_attributes")
if PANEL_ATTR_DIR not in sys.path:
    sys.path.insert(0, PANEL_ATTR_DIR)

import grain_direction as grain  # noqa: E402
import metadata_inspector as inspector  # noqa: E402
import attribute_state_service as state  # noqa: E402


class GrainDirectionTests(unittest.TestCase):
    def test_standing_door_vertical_uses_z_span(self):
        # thickness X=16, width Y=450, height Z=720
        mm, detail = grain.resolve_grain_along_mm(16, 450, 720, "vertical")
        self.assertEqual(mm, 720.0)
        self.assertEqual(detail["acrossZMm"], 450.0)
        self.assertTrue(detail["standing"])

    def test_standing_door_horizontal_uses_other_face_edge(self):
        mm, detail = grain.resolve_grain_along_mm(16, 450, 720, "横")
        self.assertEqual(mm, 450.0)
        self.assertEqual(detail["alongZMm"], 720.0)

    def test_xz_door_horizontal_uses_x(self):
        mm, _detail = grain.resolve_grain_along_mm(600, 18, 800, "horizontal")
        self.assertEqual(mm, 600.0)

    def test_lying_shelf_uses_top_view_xy(self):
        # thickness Z=16, width X=800, depth Y=350
        vertical_mm, detail = grain.resolve_grain_along_mm(800, 350, 16, "vertical")
        horizontal_mm, _ = grain.resolve_grain_along_mm(800, 350, 16, "horizontal")
        self.assertFalse(detail["standing"])
        self.assertEqual(vertical_mm, 350.0)
        self.assertEqual(horizontal_mm, 800.0)

    def test_none_does_not_store_a_length(self):
        mm, detail = grain.resolve_grain_along_mm(16, 450, 720, "none")
        self.assertIsNone(mm)
        self.assertTrue(detail["standing"])

    def test_body_bbox_spans_mm(self):
        class Point:
            def __init__(self, x, y, z):
                self.x, self.y, self.z = x, y, z

        class Box:
            minPoint = Point(0, 0, 0)
            maxPoint = Point(1.6, 45.0, 72.0)  # Fusion cm

        class Body:
            boundingBox = Box()

        dx, dy, dz = grain.body_bbox_spans_mm(Body())
        self.assertAlmostEqual(dx, 16.0)
        self.assertAlmostEqual(dy, 450.0)
        self.assertAlmostEqual(dz, 720.0)
        mm, _detail = grain.grain_along_mm_for_body(Body(), "竖")
        self.assertEqual(mm, 720.0)

    def test_swap_standing_door_vertical_to_horizontal(self):
        self.assertEqual(grain.swapped_grain_along_mm(16, 450, 720, 720), 450.0)
        self.assertEqual(grain.swapped_grain_along_mm(16, 450, 720, 450), 720.0)

    def test_swap_lying_shelf_width_to_depth(self):
        self.assertEqual(grain.swapped_grain_along_mm(800, 350, 16, 800), 350.0)
        self.assertEqual(grain.swapped_grain_along_mm(800, 350, 16, 350), 800.0)

    def test_swap_rejects_unset_grain(self):
        with self.assertRaises(ValueError):
            grain.swapped_grain_along_mm(16, 450, 720, "")
        with self.assertRaises(ValueError):
            grain.swapped_grain_along_mm(16, 450, 720, None)

    def test_swap_square_face_returns_same_length(self):
        self.assertEqual(grain.swapped_grain_along_mm(16, 500, 500, 500), 500.0)


class GrainMetadataTests(unittest.TestCase):
    def test_apply_stores_length_not_orientation_words(self):
        updated, result = state.apply_grain_along_mm({}, 720, source="manual")
        self.assertTrue(result["changed"])
        self.assertEqual(
            updated["classification"]["grainAlongMm"],
            {"value": 720.0, "source": "manual", "locked": True},
        )
        self.assertEqual(updated["derivedTags"]["grainAlongMm"], 720.0)
        blob = str(updated).lower()
        self.assertNotIn("horizontal", blob)
        self.assertNotIn("vertical", blob)
        self.assertNotIn("\"横\"", str(updated))
        self.assertNotIn("\"竖\"", str(updated))

    def test_migrate_wraps_bare_number(self):
        migrated = state.migrate_metadata(
            {"classification": {"grainAlongMm": 450}}
        )
        self.assertEqual(migrated["classification"]["grainAlongMm"]["value"], 450.0)
        self.assertEqual(migrated["derivedTags"]["grainAlongMm"], 450.0)

    def test_clear_removes_mirror(self):
        filled, _ = state.apply_grain_along_mm({}, 720, source="manual")
        cleared, result = state.apply_grain_along_mm(
            filled, "", source="manual", force=True
        )
        self.assertTrue(result["changed"])
        self.assertEqual(cleared["classification"]["grainAlongMm"]["value"], "")
        self.assertNotIn("grainAlongMm", cleared.get("derivedTags") or {})

    def test_scan_summary_and_derived_tags_show_length(self):
        metadata = {
            "identity": {"panelId": "door-1"},
            "classification": {
                "boardType": {"value": "door", "source": "manual", "locked": True},
                "color": {"value": "oak", "source": "manual", "locked": True},
                "cuttingFace": {"value": "MILLING", "source": "manual", "locked": True},
                "grainAlongMm": {"value": 720, "source": "manual", "locked": True},
            },
        }
        summary = inspector._metadata_summary(metadata, "door-1")
        self.assertEqual(summary["grainAlongMm"], 720.0)
        derived = inspector._derived_tags(metadata, summary)
        self.assertEqual(derived["derivedTags"]["grainAlongMm"], 720.0)
        self.assertEqual(derived["typedTags"]["grainAlongMm"], 720.0)
        self.assertNotIn("horizontal", str(derived).lower())
        self.assertNotIn("vertical", str(derived).lower())

    def test_scan_summary_omits_unset_grain(self):
        summary = inspector._metadata_summary({"identity": {"panelId": "p1"}}, "p1")
        self.assertNotIn("grainAlongMm", summary)


if __name__ == "__main__":
    unittest.main()
