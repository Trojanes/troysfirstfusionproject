import os
import sys
import unittest


PLUGIN_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
PA_DIR = os.path.join(PLUGIN_DIR, "panel_attributes")
if PA_DIR not in sys.path:
    sys.path.insert(0, PA_DIR)

import json  # noqa: E402

from work_zones import (  # noqa: E402
    ZONE_ASSEMBLY,
    ZONE_GENERATION,
    ZONE_LAYOUT_ATTR_GROUP,
    ZONE_LAYOUT_ATTR_NAME,
    ZONE_NESTING,
    ZONE_NONE,
    compute_zone_layout,
    generation_zone_center_mm,
    grow_nesting_zone,
    is_nested_instance,
    mark_instance_role,
    resolve_origin_from_payload,
    zone_of_point,
    zones_overlap,
)


class _FakeAttr:
    def __init__(self, value):
        self.value = value


class _FakeAttrs:
    def __init__(self, layout):
        self._payload = json.dumps(layout)

    def itemByName(self, group, name):
        if group == ZONE_LAYOUT_ATTR_GROUP and name == ZONE_LAYOUT_ATTR_NAME:
            return _FakeAttr(self._payload)
        return None


class _FakeRoot:
    def __init__(self, layout):
        self.attributes = _FakeAttrs(layout)


class _RoleAttrs:
    def __init__(self):
        self.items = {}

    def itemByName(self, group, name):
        return self.items.get((group, name))

    def add(self, group, name, value):
        self.items[(group, name)] = _FakeAttr(value)


class _RoleBody:
    def __init__(self):
        self.attributes = _RoleAttrs()


class WorkZoneLayoutTests(unittest.TestCase):
    def test_layout_positions_follow_agreed_rules(self):
        layout = compute_zone_layout(10000, 8000)
        assembly = layout[ZONE_ASSEMBLY]
        generation = layout[ZONE_GENERATION]
        nesting = layout[ZONE_NESTING]

        # Assembly centred at origin.
        self.assertEqual((assembly["x0"], assembly["x1"]), (-5000, 5000))
        self.assertEqual((assembly["y0"], assembly["y1"]), (-4000, 4000))
        # Generation +X with a 1 m gap, same size.
        self.assertEqual(generation["x0"], assembly["x1"] + 1000)
        self.assertEqual(generation["x1"] - generation["x0"], 10000)
        self.assertEqual((generation["y0"], generation["y1"]), (-4000, 4000))
        # Nesting +Y with a 1 m gap above the tallest lower zone.
        self.assertEqual(nesting["y0"], assembly["y1"] + 1000)
        self.assertEqual(nesting["y1"] - nesting["y0"], 8000)

    def test_custom_generation_and_nesting_sizes(self):
        layout = compute_zone_layout(
            10000, 8000, nesting_width_mm=20000, nesting_depth_mm=5000,
            generation_width_mm=6000, generation_depth_mm=4000,
        )
        generation = layout[ZONE_GENERATION]
        nesting = layout[ZONE_NESTING]
        self.assertEqual(generation["x0"], 6000)  # assembly x1 + 1 m gap
        self.assertEqual(generation["x1"] - generation["x0"], 6000)
        # Generation top edge is anchored to the assembly top; depth grows -Y.
        self.assertEqual((generation["y0"], generation["y1"]), (0, 4000))
        self.assertEqual(nesting["x1"] - nesting["x0"], 20000)
        self.assertEqual(nesting["y1"] - nesting["y0"], 5000)
        # Nesting still clears the tallest lower zone (assembly y1=4000).
        self.assertEqual(nesting["y0"], 5000)
        self.assertFalse(zones_overlap(layout))

    def test_generation_resize_never_moves_nesting_zone(self):
        base = compute_zone_layout(10000, 8000)
        deeper_generation = compute_zone_layout(
            10000, 8000, generation_width_mm=30000, generation_depth_mm=25000,
        )
        # Growth directions: +X for width, -Y for depth; top edge fixed.
        gen = deeper_generation[ZONE_GENERATION]
        self.assertEqual(gen["y1"], base[ZONE_GENERATION]["y1"])
        self.assertEqual(gen["y0"], gen["y1"] - 25000)
        # The nesting zone must not move when only the generation zone grows.
        self.assertEqual(deeper_generation[ZONE_NESTING], base[ZONE_NESTING])
        self.assertFalse(zones_overlap(deeper_generation))

    def test_zones_never_overlap(self):
        layout = compute_zone_layout(10000, 10000)
        self.assertFalse(zones_overlap(layout))
        grown = grow_nesting_zone(layout, 40000, 25000)
        self.assertFalse(zones_overlap(grown))

    def test_zone_of_point_classification(self):
        layout = compute_zone_layout(10000, 10000)
        self.assertEqual(zone_of_point(layout, 0, 0), ZONE_ASSEMBLY)
        self.assertEqual(zone_of_point(layout, 7000, 0), ZONE_GENERATION)
        self.assertEqual(zone_of_point(layout, 0, 7000), ZONE_NESTING)
        # Inside the 1 m gap → unzoned.
        self.assertEqual(zone_of_point(layout, 5500, 0), ZONE_NONE)
        self.assertEqual(zone_of_point(layout, 0, 5500), ZONE_NONE)
        self.assertEqual(zone_of_point(layout, -20000, -20000), ZONE_NONE)

    def test_grow_nesting_zone_extends_x_both_and_y_plus(self):
        layout = compute_zone_layout(10000, 10000)
        grown = grow_nesting_zone(layout, 30000, 20000)
        nesting = grown[ZONE_NESTING]
        self.assertEqual(nesting["x1"] - nesting["x0"], 30000)
        self.assertEqual(nesting["y1"] - nesting["y0"], 20000)
        # X growth is symmetric around x=0; Y growth only upward from the base.
        self.assertEqual(nesting["x0"], -15000)
        self.assertEqual(nesting["y0"], layout[ZONE_NESTING]["y0"])
        self.assertFalse(zones_overlap(grown))

    def test_resolve_origin_prefers_explicit_payload(self):
        root = _FakeRoot(compute_zone_layout(10000, 10000))
        x, y = resolve_origin_from_payload({"originXMm": 123, "originYMm": -45}, root)
        self.assertEqual((x, y), (123.0, -45.0))

    def test_resolve_origin_defaults_to_generation_center(self):
        layout = compute_zone_layout(10000, 10000)
        root = _FakeRoot(layout)
        center = generation_zone_center_mm(root)
        gen = layout[ZONE_GENERATION]
        self.assertEqual(center[0], (gen["x0"] + gen["x1"]) / 2.0)
        self.assertEqual(center[1], (gen["y0"] + gen["y1"]) / 2.0)
        x, y = resolve_origin_from_payload({}, root)
        self.assertEqual((x, y), center)

    def test_resolve_origin_without_layout_is_origin(self):
        self.assertEqual(resolve_origin_from_payload({}, None), (0.0, 0.0))

    def test_grow_never_shrinks(self):
        layout = compute_zone_layout(10000, 10000)
        grown = grow_nesting_zone(layout, 2000, 2000)
        nesting = grown[ZONE_NESTING]
        self.assertEqual(nesting["x1"] - nesting["x0"], 10000)
        self.assertEqual(nesting["y1"] - nesting["y0"], 10000)

    def test_grow_to_layout_required_size_keeps_manual_floor(self):
        """Nesting zone expands to fit layout; never below the manual size."""
        layout = compute_zone_layout(10000, 10000, nesting_width_mm=10000, nesting_depth_mm=10000)
        nesting = layout[ZONE_NESTING]
        required_w, required_d = 106293.0, 7025.0
        self.assertGreater(required_w, nesting["x1"] - nesting["x0"])
        grown = grow_nesting_zone(layout, required_w, required_d)
        grown_nesting = grown[ZONE_NESTING]
        self.assertAlmostEqual(grown_nesting["x1"] - grown_nesting["x0"], required_w)
        self.assertEqual(grown_nesting["y1"] - grown_nesting["y0"], 10000)  # depth floor
        self.assertEqual(grown_nesting["y0"], nesting["y0"])
        self.assertFalse(zones_overlap(grown))
        # Smaller follow-up layout must not shrink the expanded zone.
        again = grow_nesting_zone(grown, 8000, 5000)
        again_nesting = again[ZONE_NESTING]
        self.assertAlmostEqual(again_nesting["x1"] - again_nesting["x0"], required_w)
        self.assertEqual(again_nesting["y1"] - again_nesting["y0"], 10000)

    def test_nested_instance_marker_is_deterministic(self):
        body = _RoleBody()
        self.assertFalse(is_nested_instance(body))
        self.assertTrue(mark_instance_role(body, "nested"))
        self.assertTrue(is_nested_instance(body))

    def test_nesting_workpiece_system_role_is_also_excluded(self):
        body = _RoleBody()
        body.attributes.add(
            "UnifiedCabinet", "systemRole", "nestingWorkpiece"
        )
        self.assertTrue(is_nested_instance(body))


if __name__ == "__main__":
    unittest.main()
