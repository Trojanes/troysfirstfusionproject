import sys
import math
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
for path in (ROOT, REL_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from relationship_fixtures import build_fixture_snapshots  # noqa: E402
from relationship_geometry import classify_pair  # noqa: E402
from relationship_visual_overlay import (  # noqa: E402
    OPERATION_TYPE,
    build_overlay_label_text,
    build_overlay_metadata,
    compute_segment_plane_normal,
    is_overlay_artifact_entity,
    is_overlay_sketch_name,
    is_protected_cleanup_name,
    list_overlay_cleanup_targets,
    overlay_metadata_json,
    resolve_overlay_relationship,
)


class _Attr:
    def __init__(self, value):
        self.value = value


class _Attrs:
    def __init__(self, mapping):
        self._mapping = mapping

    def itemByName(self, group, name):
        return _Attr(self._mapping.get((group, name)))


class _NamedEntity:
    def __init__(self, name, attrs=None):
        self.name = name
        self.attributes = _Attrs(attrs or {})


class _Collection:
    def __init__(self, items):
        self._items = items

    @property
    def count(self):
        return len(self._items)

    def item(self, index):
        return self._items[index]

    def itemByName(self, name):
        for item in self._items:
            if item.name == name:
                return item
        return None


def _fixture_relationship():
    panels = {panel.panelId: panel for panel in build_fixture_snapshots()}
    return classify_pair(panels["REL_EDGE_A"], panels["REL_SURFACE_B"]).to_dict()


class RelationshipVisualOverlayTests(unittest.TestCase):
    def test_overlay_label_includes_required_fields(self):
        rel = _fixture_relationship()
        label = build_overlay_label_text(rel)
        self.assertIn("structural_butt_joint", label)
        self.assertIn("edge_to_surface", label)
        self.assertIn("bbox_candidate", label)
        self.assertIn("safeForCut=false", label)

    def test_overlay_metadata_is_stable(self):
        rel = _fixture_relationship()
        metadata = build_overlay_metadata(rel)
        self.assertEqual(metadata["operationType"], OPERATION_TYPE)
        self.assertTrue(metadata["demoArtifact"])
        self.assertEqual(metadata["sourceRelationshipId"], rel["relationshipId"])
        self.assertEqual(metadata["geometryType"], "edge_to_surface")
        self.assertEqual(metadata["verificationLevel"], "bbox_candidate")
        self.assertFalse(metadata["safeForCut"])
        encoded = overlay_metadata_json(metadata)
        self.assertIn("RELATIONSHIP_VISUAL_OVERLAY", encoded)
        self.assertIn(rel["relationshipId"], encoded)

    def test_cleanup_targets_only_overlay_artifacts(self):
        overlay_sketch = _NamedEntity(
            "REL_OVERLAY_123_LINE",
            {
                ("UnifiedCabinetPlugin", "operationType"): OPERATION_TYPE,
                ("UnifiedCabinetPlugin", "demoArtifact"): "true",
            },
        )
        protected_sketch = _NamedEntity("WorkZoneSketch_assembly")
        cut_sketch = _NamedEntity("HW_REL_SCREW_HOLE_SKETCH")
        overlay_plane = _NamedEntity("REL_OVERLAY_PLANE_123_LINE")
        other_plane = _NamedEntity("WorkZoneTextPlane")

        targets = list_overlay_cleanup_targets(
            _Collection([overlay_sketch, protected_sketch, cut_sketch]),
            _Collection([overlay_plane, other_plane]),
        )
        self.assertEqual(targets["sketches"], ["REL_OVERLAY_123_LINE"])
        self.assertEqual(targets["planes"], ["REL_OVERLAY_PLANE_123_LINE"])
        self.assertTrue(is_overlay_artifact_entity(overlay_sketch))
        self.assertFalse(is_overlay_artifact_entity(protected_sketch))
        self.assertFalse(is_overlay_artifact_entity(cut_sketch))
        self.assertTrue(is_overlay_sketch_name("REL_OVERLAY_abc"))
        self.assertTrue(is_protected_cleanup_name("WorkZoneSketch_assembly"))
        self.assertTrue(is_protected_cleanup_name("HW_REL_SCREW_HOLE_123"))

    def test_resolve_overlay_relationship_from_scan(self):
        rel = _fixture_relationship()
        scan = {"relationships": [rel]}
        resolved = resolve_overlay_relationship(scan)
        self.assertEqual(resolved["relationshipId"], rel["relationshipId"])

    def test_resolve_overlay_relationship_selected(self):
        rel = _fixture_relationship()
        other = {"relationshipId": "rel.other", "geometryType": "gap_parallel"}
        scan = {"relationships": [other, rel]}
        resolved = resolve_overlay_relationship(scan, other, source="selected")
        self.assertEqual(resolved["relationshipId"], "rel.other")

    def test_compute_segment_plane_normal(self):
        dx, dy, dz = 0.0, 300.0, 150.0
        normal = compute_segment_plane_normal(dx, dy, dz)
        mag = math.sqrt(normal[0] ** 2 + normal[1] ** 2 + normal[2] ** 2)
        self.assertAlmostEqual(mag, 1.0, places=6)
        dir_mag = math.sqrt(dx * dx + dy * dy + dz * dz)
        dot = abs((normal[0] * dx + normal[1] * dy + normal[2] * dz) / dir_mag)
        self.assertLess(dot, 0.01)

    def test_ensure_distinct_overlay_endpoints(self):
        from relationship_visual_overlay import ensure_distinct_overlay_endpoints_mm

        same = (100.0, 200.0, 50.0)
        a, b = ensure_distinct_overlay_endpoints_mm(
            same,
            same,
            {"contact": {"axis": "Y"}},
        )
        self.assertGreater(abs(b[1] - a[1]), 0.0)


if __name__ == "__main__":
    unittest.main()
