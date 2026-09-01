import os
import sys
import unittest
from unittest import mock


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PANEL_ATTR_DIR = os.path.join(ROOT, "panel_attributes")
if PANEL_ATTR_DIR not in sys.path:
    sys.path.insert(0, PANEL_ATTR_DIR)

import grain_overlay as overlay  # noqa: E402
import grain_overlay_fusion as overlay_fusion  # noqa: E402


class GrainOverlayGeometryTests(unittest.TestCase):
    def test_standing_door_vertical_axis_is_z(self):
        self.assertEqual(overlay.resolve_grain_axis(16, 450, 720, 720), "z")

    def test_standing_door_horizontal_axis_is_y(self):
        self.assertEqual(overlay.resolve_grain_axis(16, 450, 720, 450), "y")

    def test_lying_shelf_horizontal_axis_is_x(self):
        self.assertEqual(overlay.resolve_grain_axis(800, 350, 16, 800), "x")

    def test_lying_shelf_vertical_axis_is_y(self):
        self.assertEqual(overlay.resolve_grain_axis(800, 350, 16, 350), "y")

    def test_unset_grain_has_no_segments(self):
        self.assertEqual(overlay.overlay_segments_mm((0, 0, 0), (16, 450, 720), ""), [])
        self.assertEqual(overlay.overlay_segments_mm((0, 0, 0), (16, 450, 720), None), [])
        self.assertIsNone(overlay.resolve_grain_axis(16, 450, 720, 0))

    def test_standing_door_hatch_follows_z_on_thickness_faces(self):
        segments = overlay.overlay_segments_mm((0, 0, 0), (16, 450, 720), 720)
        self.assertEqual(len(segments), 10)
        xs = {round(point[0], 2) for start, tip in segments for point in (start, tip)}
        self.assertTrue(xs <= {-overlay._OUTWARD_MM, 16 + overlay._OUTWARD_TOP_MM})
        for start, tip in segments:
            self.assertAlmostEqual(start[0], tip[0], places=2)
            self.assertAlmostEqual(start[1], tip[1], places=2)
            self.assertGreater(abs(tip[2] - start[2]), 400)

    def test_lying_shelf_hatch_follows_x_on_top_and_bottom(self):
        segments = overlay.overlay_segments_mm((0, 0, 0), (800, 350, 16), 800)
        self.assertEqual(len(segments), 10)
        zs = {round(point[2], 2) for start, tip in segments for point in (start, tip)}
        self.assertTrue(zs <= {-overlay._OUTWARD_MM, 16 + overlay._OUTWARD_TOP_MM})
        for start, tip in segments:
            self.assertAlmostEqual(start[2], tip[2], places=2)
            self.assertAlmostEqual(start[1], tip[1], places=2)
            self.assertGreater(abs(tip[0] - start[0]), 500)

    def test_grain_mm_from_any_reads_dimensions_and_cache(self):
        self.assertEqual(
            overlay.grain_mm_from_any({"dimensions": {"grainAlongMm": 720}}),
            720.0,
        )
        self.assertEqual(
            overlay.grain_mm_from_any(
                {"nestingFlatOutline": {"grainAlongMm": 450}}
            ),
            450.0,
        )
        self.assertEqual(
            overlay.grain_mm_from_any(
                {
                    "classification": {
                        "grainAlongMm": {"value": 800, "source": "manual"}
                    }
                }
            ),
            800.0,
        )
        self.assertEqual(overlay.grain_mm_from_any({}), "")

    def test_flatten_coords_cm_is_line_pairs(self):
        segments = overlay.overlay_segments_mm((0, 0, 0), (16, 450, 720), 720)
        coords = overlay.flatten_coords_cm(segments)
        self.assertEqual(len(coords), 60)
        self.assertEqual(len(coords) % 6, 0)

    def test_merge_roster_keeps_other_boards(self):
        roster = overlay.merge_roster({"a": 720, "b": 450}, {"b": 800, "c": 350})
        self.assertEqual(roster, {"a": 720.0, "b": 800.0, "c": 350.0})
        cleared = overlay.merge_roster(roster, {"a": ""})
        self.assertNotIn("a", cleared)
        self.assertEqual(cleared["b"], 800.0)


class _Attr:
    def __init__(self, value=""):
        self.value = value


class _Attrs:
    def __init__(self):
        self.items = {}

    def itemByName(self, group, name):
        return self.items.get((group, name))

    def add(self, group, name, value):
        self.items[(group, name)] = _Attr(value)


class _Graphics:
    def __init__(self):
        self.groups = []

    @property
    def count(self):
        return len(self.groups)

    def item(self, index):
        return self.groups[index]

    def add(self):
        raise AssertionError("hide path must not create graphics")


class _Root:
    def __init__(self):
        self.attributes = _Attrs()
        self.customGraphicsGroups = _Graphics()


class _Point:
    def __init__(self, x, y, z):
        self.x, self.y, self.z = x, y, z


class _Box:
    def __init__(self):
        self.minPoint = _Point(0, 0, 0)
        self.maxPoint = _Point(1.6, 45.0, 72.0)


class _Body:
    def __init__(self, name="door"):
        self.name = name
        self.boundingBox = _Box()


class _LayFlatBody(_Body):
    def __init__(self, name="flat"):
        super().__init__(name)
        self.attributes = _Attrs()
        self.attributes.add("UnifiedCabinet", "systemRole", "layFlatWorkpiece")


class GrainOverlayBodySegmentsTests(unittest.TestCase):
    def setUp(self):
        overlay_fusion.reset_session_items()

    def test_session_key_keeps_lay_flat_copy_apart_from_original(self):
        original = _Body("door")
        copy = _LayFlatBody("door")
        with mock.patch.object(
            overlay_fusion.metadata_inspector, "_body_key", return_value="same-token"
        ):
            self.assertNotEqual(
                overlay_fusion._session_key(original),
                overlay_fusion._session_key(copy),
            )
            self.assertTrue(
                overlay_fusion._session_key(copy).startswith("layflat:")
            )

    def test_rebuild_draws_lay_flat_extra_items_beside_originals(self):
        original = _Body("oak")
        copy = _LayFlatBody("oak-flat")
        segs = overlay.overlay_segments_mm((0, 0, 0), (16, 450, 720), 720)

        def fake_collect(root):
            overlay_fusion._SESSION_ITEMS[
                overlay_fusion._session_key(original)
            ] = (original, 720)
            return list(segs), 1, 0, []

        with mock.patch.object(
            overlay_fusion, "_grain_color_tags", return_value=["wood_grain"]
        ), mock.patch.object(
            overlay_fusion, "collect_overlay_segments", side_effect=fake_collect
        ), mock.patch.object(
            overlay_fusion, "_color_key_for_body", return_value="wood_grain"
        ), mock.patch.object(
            overlay_fusion, "clear_overlay", return_value=0
        ), mock.patch.object(
            overlay_fusion, "_draw_segments", return_value=None
        ) as draw:
            result = overlay_fusion.rebuild_overlay(
                _Root(), extra_items=[(copy, 720)]
            )
        self.assertEqual(result["drawnCount"], 2)
        draw.assert_called_once()

    def test_segments_for_bodies_uses_given_length(self):
        segments, drawn, skipped, warnings = overlay_fusion.segments_for_bodies(
            [(_Body(), 720)]
        )
        self.assertEqual(drawn, 1)
        self.assertEqual(skipped, 0)
        self.assertEqual(warnings, [])
        self.assertEqual(len(segments), 10)

    def test_rebuild_hides_when_no_grain_colors_ticked(self):
        leftover = _Body("white")
        overlay_fusion._SESSION_ITEMS[overlay_fusion._session_key(leftover)] = (
            leftover,
            450,
        )
        with mock.patch.object(overlay_fusion, "_grain_color_tags", return_value=[]):
            result = overlay_fusion.rebuild_overlay(_Root())
        self.assertTrue(result["ok"])
        self.assertFalse(result["visible"])
        self.assertEqual(result["drawnCount"], 0)
        self.assertEqual(overlay_fusion._SESSION_ITEMS, {})

    def test_rebuild_draws_extra_items_when_collect_finds_nothing(self):
        oak = _Body("oak")
        segs = overlay.overlay_segments_mm((0, 0, 0), (16, 450, 720), 720)

        def fake_collect(root):
            return [], 0, 0, []

        with mock.patch.object(
            overlay_fusion, "_grain_color_tags", return_value=["wood_grain"]
        ), mock.patch.object(
            overlay_fusion, "collect_overlay_segments", side_effect=fake_collect
        ), mock.patch.object(
            overlay_fusion, "_color_key_for_body", return_value="wood_grain"
        ), mock.patch.object(
            overlay_fusion, "clear_overlay", return_value=0
        ), mock.patch.object(
            overlay_fusion, "_draw_segments", return_value=None
        ) as draw:
            result = overlay_fusion.rebuild_overlay(
                _Root(), extra_items=[(oak, 720)]
            )
        self.assertTrue(result["visible"])
        self.assertEqual(result["drawnCount"], 1)
        draw.assert_called_once()
        self.assertEqual(len(draw.call_args[0][1]), len(segs))

    def test_rebuild_replaces_session_and_draws_only_collect_hits(self):
        oak = _Body("oak")
        white = _Body("white")
        overlay_fusion._SESSION_ITEMS["stale-white"] = (white, 450)
        segs = overlay.overlay_segments_mm((0, 0, 0), (16, 450, 720), 720)

        def fake_collect(root):
            overlay_fusion.reset_session_items()
            overlay_fusion._SESSION_ITEMS[overlay_fusion._session_key(oak)] = (
                oak,
                720,
            )
            return segs, 1, 0, []

        with mock.patch.object(
            overlay_fusion, "_grain_color_tags", return_value=["wood_grain"]
        ), mock.patch.object(
            overlay_fusion, "collect_overlay_segments", side_effect=fake_collect
        ), mock.patch.object(
            overlay_fusion, "clear_overlay", return_value=0
        ), mock.patch.object(
            overlay_fusion, "_draw_segments", return_value=None
        ) as draw:
            result = overlay_fusion.rebuild_overlay(_Root())
        self.assertTrue(result["visible"])
        self.assertEqual(result["drawnCount"], 1)
        draw.assert_called_once()
        live_names = {
            body.name for body, _grain in overlay_fusion._SESSION_ITEMS.values()
        }
        self.assertEqual(live_names, {"oak"})


class _NamedGroup:
    def __init__(self, name="", gid=""):
        self.name = name
        self.id = gid
        self.deleted = False

    def deleteMe(self):
        self.deleted = True


class GrainOverlayPersistTests(unittest.TestCase):
    def test_hide_saves_flag_without_drawing(self):
        root = _Root()
        result = overlay_fusion.set_overlay_visible(root, False)
        self.assertTrue(result["ok"])
        self.assertFalse(result["visible"])
        self.assertFalse(overlay_fusion.load_overlay_visible(root))
        self.assertFalse(overlay_fusion.refresh_if_visible(root)["visible"])

    def test_clear_overlay_matches_group_name_when_id_empty(self):
        root = _Root()
        leftover = _NamedGroup(name=overlay.OVERLAY_GROUP_ID, gid="")
        other = _NamedGroup(name="Other", gid="")
        root.customGraphicsGroups.groups = [leftover, other]
        removed = overlay_fusion.clear_overlay(root)
        self.assertEqual(removed, 1)
        self.assertTrue(leftover.deleted)
        self.assertFalse(other.deleted)


if __name__ == "__main__":
    unittest.main()
