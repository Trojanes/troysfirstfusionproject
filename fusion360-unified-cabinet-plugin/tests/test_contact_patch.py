import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REL_DIR = ROOT / "modules" / "relationships"
for path in (ROOT, REL_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from contact_patch import (  # noqa: E402
    build_contact_patch_from_relationship,
    build_contact_patch_label_text,
)
from contact_patch_overlay import (  # noqa: E402
    OPERATION_TYPE as PATCH_OPERATION_TYPE,
    build_contact_patch_metadata,
    is_contact_patch_artifact_entity,
    list_contact_patch_cleanup_targets,
)
from relationship_fixtures import build_fixture_snapshots  # noqa: E402
from relationship_geometry import classify_pair  # noqa: E402
from relationship_visual_overlay import (  # noqa: E402
    OPERATION_TYPE as REL_OPERATION_TYPE,
    is_overlay_artifact_entity,
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


def _fixture_relationship(panel_a_id, panel_b_id):
    panels = {panel.panelId: panel for panel in build_fixture_snapshots()}
    return classify_pair(panels[panel_a_id], panels[panel_b_id]).to_dict()


class ContactPatchTests(unittest.TestCase):
    def test_edge_to_surface_generates_contact_patch(self):
        rel = _fixture_relationship("REL_EDGE_A", "REL_SURFACE_B")
        pa = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_EDGE_A")
        pb = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_SURFACE_B")
        result = build_contact_patch_from_relationship(rel, pa, pb)
        self.assertTrue(result["ok"])
        patch = result["contactPatch"]
        self.assertEqual(patch["contactType"], "edge_to_surface")
        self.assertEqual(patch["contactAxis"], "Y")
        self.assertEqual(patch["verification"]["level"], "bbox_contact_patch")
        self.assertFalse(patch["verification"]["safeForCut"])

    def test_surface_to_surface_generates_contact_patch(self):
        rel = _fixture_relationship("REL_SURFACE_A", "REL_SURFACE_B2")
        pa = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_SURFACE_A")
        pb = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_SURFACE_B2")
        result = build_contact_patch_from_relationship(rel, pa, pb)
        self.assertTrue(result["ok"])
        patch = result["contactPatch"]
        self.assertEqual(patch["contactType"], "surface_to_surface")
        self.assertEqual(patch["contactAxis"], "Z")
        self.assertAlmostEqual(patch["contactAreaMm2"], 90000.0, places=1)

    def test_contact_patch_area_equals_bbox_overlap(self):
        rel = _fixture_relationship("REL_SURFACE_A", "REL_SURFACE_B2")
        pa = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_SURFACE_A")
        pb = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_SURFACE_B2")
        patch = build_contact_patch_from_relationship(rel, pa, pb)["contactPatch"]
        bounds = patch["boundsWorldMm"]
        expected = (bounds["x1"] - bounds["x0"]) * (bounds["y1"] - bounds["y0"])
        self.assertAlmostEqual(patch["contactAreaMm2"], expected, places=2)

    def test_center_world_mm_is_stable(self):
        rel = _fixture_relationship("REL_EDGE_A", "REL_SURFACE_B")
        pa = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_EDGE_A")
        pb = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_SURFACE_B")
        first = build_contact_patch_from_relationship(rel, pa, pb)["contactPatch"]["centerWorldMm"]
        second = build_contact_patch_from_relationship(rel, pa, pb)["contactPatch"]["centerWorldMm"]
        self.assertEqual(first, second)

    def test_missing_host_target_returns_error(self):
        rel = _fixture_relationship("REL_EDGE_A", "REL_SURFACE_B")
        rel["roles"] = {}
        pa = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_EDGE_A")
        pb = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_SURFACE_B")
        result = build_contact_patch_from_relationship(rel, pa, pb)
        self.assertFalse(result["ok"])
        self.assertTrue(any("hostPanelId" in err or "targetPanelId" in err for err in result["errors"]))

    def test_unsupported_geometry_returns_error(self):
        rel = _fixture_relationship("REL_GAP_A", "REL_GAP_B")
        pa = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_GAP_A")
        pb = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_GAP_B")
        result = build_contact_patch_from_relationship(rel, pa, pb)
        self.assertFalse(result["ok"])
        self.assertTrue(any("Unsupported geometryType" in err for err in result["errors"]))

    def test_label_includes_required_fields(self):
        rel = _fixture_relationship("REL_EDGE_A", "REL_SURFACE_B")
        pa = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_EDGE_A")
        pb = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_SURFACE_B")
        patch = build_contact_patch_from_relationship(rel, pa, pb)["contactPatch"]
        label = build_contact_patch_label_text(patch, rel)
        self.assertIn("structural_butt_joint", label)
        self.assertIn("edge_to_surface", label)
        self.assertIn("contactArea", label)
        self.assertIn("bbox_contact_patch", label)
        self.assertIn("safeForCut = false", label)

    def test_cleanup_targets_only_contact_patch_artifacts(self):
        patch_sketch = _NamedEntity(
            "CP_OVERLAY_123_LABEL",
            {
                ("UnifiedCabinetPlugin", "operationType"): PATCH_OPERATION_TYPE,
                ("UnifiedCabinetPlugin", "demoArtifact"): "true",
            },
        )
        rel_sketch = _NamedEntity(
            "REL_OVERLAY_123_LABEL",
            {
                ("UnifiedCabinetPlugin", "operationType"): REL_OPERATION_TYPE,
                ("UnifiedCabinetPlugin", "demoArtifact"): "true",
            },
        )
        targets = list_contact_patch_cleanup_targets(_Collection([patch_sketch, rel_sketch]), _Collection([]))
        self.assertEqual(targets["sketches"], ["CP_OVERLAY_123_LABEL"])
        self.assertTrue(is_contact_patch_artifact_entity(patch_sketch))
        self.assertFalse(is_contact_patch_artifact_entity(rel_sketch))
        self.assertTrue(is_overlay_artifact_entity(rel_sketch))

    def test_metadata_includes_contact_patch_id(self):
        rel = _fixture_relationship("REL_EDGE_A", "REL_SURFACE_B")
        pa = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_EDGE_A")
        pb = next(p.to_dict() for p in build_fixture_snapshots() if p.panelId == "REL_SURFACE_B")
        patch = build_contact_patch_from_relationship(rel, pa, pb)["contactPatch"]
        metadata = build_contact_patch_metadata(patch)
        self.assertEqual(metadata["operationType"], PATCH_OPERATION_TYPE)
        self.assertEqual(metadata["contactPatchId"], patch["contactPatchId"])


if __name__ == "__main__":
    unittest.main()
