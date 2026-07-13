import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PANEL_ATTR_DIR = ROOT / "panel_attributes"
if str(PANEL_ATTR_DIR) not in sys.path:
    sys.path.insert(0, str(PANEL_ATTR_DIR))

import door_face_orientation as orient  # noqa: E402


class ViewScoreTests(unittest.TestCase):
    def test_face_aimed_at_observer_scores_high(self):
        # Face at origin, normal +Y, observer in front (+Y).
        score = orient.face_view_score([0, 1, 0], [0, 0, 0], [0, 1000, 0])
        self.assertAlmostEqual(score, 1.0, places=6)

    def test_face_back_to_observer_scores_low(self):
        score = orient.face_view_score([0, -1, 0], [0, 0, 0], [0, 1000, 0])
        self.assertAlmostEqual(score, -1.0, places=6)

    def test_side_on_face_scores_near_zero(self):
        # Normal +X, observer along +Y: sideways.
        score = orient.face_view_score([1, 0, 0], [0, 0, 0], [0, 1000, 0])
        self.assertAlmostEqual(score, 0.0, places=6)

    def test_degenerate_inputs(self):
        self.assertIsNone(orient.face_view_score(None, [0, 0, 0], [0, 1, 0]))
        self.assertIsNone(orient.face_view_score([0, 1, 0], [0, 0, 0], [0, 0, 0]))


class VoteTests(unittest.TestCase):
    def test_clear_margin_picks_face(self):
        self.assertEqual(orient.vote_from_scores(0.9, -0.9), "A")
        self.assertEqual(orient.vote_from_scores(-0.8, 0.7), "B")

    def test_too_close_returns_none(self):
        self.assertIsNone(orient.vote_from_scores(0.05, -0.05, min_margin=0.25))
        self.assertIsNone(orient.vote_from_scores(None, 0.5))

    def test_view_point_vote_front_door(self):
        # Door: face A outward (-Y), face B inward (+Y); observer in front (-Y side).
        vote = orient.view_point_vote(
            [0, -1, 0], [0, -16, 0],
            [0, 1, 0], [0, 0, 0],
            [0, -2000, 0],
        )
        self.assertEqual(vote, "A")

    def test_assembly_vote_outward_face_wins(self):
        # Assembly centre behind the panel (+Y side): outward face A (-Y) = colour.
        vote = orient.assembly_vote(
            [0, -1, 0], [0, -16, 0],
            [0, 1, 0], [0, 0, 0],
            [0, 300, 0],
        )
        self.assertEqual(vote, "A")

    def test_assembly_vote_abstains_when_center_in_room_void(self):
        # L-run bbox centre sits in the corridor (same side as observer).
        # Without the behind-panel check this would pick the interior face.
        vote = orient.assembly_vote(
            [0, 1, 0], [0, -484, 700],   # face A: toward corridor = true colour
            [0, -1, 0], [0, -500, 700],  # face B: into cabinet
            [0, 0, 700],                 # M in room void (same side as O)
            observation_point=[0, 200, 700],
        )
        self.assertIsNone(vote)

    def test_assembly_vote_accepts_center_behind_panel(self):
        vote = orient.assembly_vote(
            [0, 1, 0], [0, -484, 700],
            [0, -1, 0], [0, -500, 700],
            [0, -800, 700],              # M inside cabinet
            observation_point=[0, 200, 700],
        )
        self.assertEqual(vote, "A")

    def test_behind_panel_helper(self):
        self.assertTrue(orient.assembly_center_behind_panel(
            [0, -484, 700], [0, -500, 700], [0, -800, 700], [0, 200, 700],
            normal_a=[0, 1, 0], normal_b=[0, -1, 0],
        ))
        self.assertFalse(orient.assembly_center_behind_panel(
            [0, -484, 700], [0, -500, 700], [0, 0, 700], [0, 200, 700],
            normal_a=[0, 1, 0], normal_b=[0, -1, 0],
        ))

    def test_behind_panel_uses_thickness_axis_not_3d_dot(self):
        # Wide cabinet: door far left of M. Full 3D dot(to_m, to_o) is acute
        # (lateral X dominates) even though M is behind the door in Y.
        # Thickness-axis check must still accept assembly.
        mid_y_front, mid_y_back = -484.0, -500.0
        self.assertTrue(orient.assembly_center_behind_panel(
            [-600, mid_y_front, 700], [-600, mid_y_back, 700],
            [0, -800, 700],   # M inside cabinet, laterally offset
            [0, 200, 700],    # O in room
            normal_a=[0, 1, 0], normal_b=[0, -1, 0],
        ))
        # Same geometry: assembly vote must not abstain.
        vote = orient.assembly_vote(
            [0, 1, 0], [-600, mid_y_front, 700],
            [0, -1, 0], [-600, mid_y_back, 700],
            [0, -800, 700],
            observation_point=[0, 200, 700],
        )
        self.assertEqual(vote, "A")

    def test_behind_panel_rejects_void_even_with_lateral_offset(self):
        # M and O both in front of the panel (room side); lateral X offset must
        # not make the old 3D-dot check think they are opposite.
        self.assertFalse(orient.assembly_center_behind_panel(
            [0, -484, 700], [0, -500, 700],
            [800, 100, 700],   # M in room void, far right
            [-200, 200, 700],  # O also in room
            normal_a=[0, 1, 0], normal_b=[0, -1, 0],
        ))


class CombineVotesTests(unittest.TestCase):
    def test_agreement(self):
        self.assertEqual(orient.combine_votes("A", "A"), "A")
        self.assertEqual(orient.combine_votes("B", "B"), "B")

    def test_assembly_outranks_view_on_conflict(self):
        # Assembly outward face wins when the two votes disagree.
        self.assertEqual(orient.combine_votes("A", "B"), "B")
        self.assertEqual(orient.combine_votes("B", "A"), "A")

    def test_single_vote(self):
        self.assertEqual(orient.combine_votes("A", None), "A")
        self.assertEqual(orient.combine_votes(None, "B"), "B")

    def test_no_votes_is_either(self):
        self.assertEqual(orient.combine_votes(None, None), "either")


class BoundingCenterTests(unittest.TestCase):
    def test_center_of_boxes(self):
        boxes = [
            ([0, 0, 0], [100, 100, 100]),
            ([200, 0, 0], [300, 100, 100]),
        ]
        self.assertEqual(orient.bounding_center(boxes), [150.0, 50.0, 50.0])

    def test_empty_returns_none(self):
        self.assertIsNone(orient.bounding_center([]))
        self.assertIsNone(orient.bounding_center(None))


class OrientScenarioTests(unittest.TestCase):
    """End-to-end vote logic (geometry only, no Fusion faces)."""

    def test_room_scene_front_doors(self):
        # Two cabinets facing each other across a corridor; observer in middle.
        # Cabinet 1 door: outward face normal -Y at y=-500, inward +Y at y=-484.
        observer = [0, 0, 700]
        view = orient.view_point_vote(
            [0, 1, 0], [0, -484, 700],   # face A: toward corridor (+Y)
            [0, -1, 0], [0, -500, 700],  # face B: into cabinet (-Y)
            observer,
        )
        self.assertEqual(view, "A")
        # Assembly centre of cabinet 1 sits deeper at y=-800.
        local = orient.assembly_vote(
            [0, 1, 0], [0, -484, 700],
            [0, -1, 0], [0, -500, 700],
            [0, -800, 700],
            observation_point=observer,
        )
        self.assertEqual(local, "A")
        self.assertEqual(orient.combine_votes(view, local), "A")

    def test_bad_observer_assembly_wins(self):
        # Observer accidentally behind the cabinet: view vote flips to B,
        # assembly vote still says A -> assembly wins, write A as colour.
        # Pass a "good" observation_point for the behind-panel check so the
        # assembly vote is allowed to fire; the bad observer only affects view.
        view = orient.view_point_vote(
            [0, 1, 0], [0, -484, 700],
            [0, -1, 0], [0, -500, 700],
            [0, -2000, 700],
        )
        self.assertEqual(view, "B")
        local = orient.assembly_vote(
            [0, 1, 0], [0, -484, 700],
            [0, -1, 0], [0, -500, 700],
            [0, -800, 700],
            observation_point=[0, 200, 700],
        )
        self.assertEqual(local, "A")
        self.assertEqual(orient.combine_votes(view, local), "A")

    def test_room_void_center_falls_back_to_view(self):
        # Bad assembly centre in the corridor would reverse colour faces if it
        # outranked the view vote. Behind-panel check makes assembly abstain.
        observer = [0, 200, 700]
        view = orient.view_point_vote(
            [0, 1, 0], [0, -484, 700],
            [0, -1, 0], [0, -500, 700],
            observer,
        )
        self.assertEqual(view, "A")
        local = orient.assembly_vote(
            [0, 1, 0], [0, -484, 700],
            [0, -1, 0], [0, -500, 700],
            [0, 0, 700],
            observation_point=observer,
        )
        self.assertIsNone(local)
        self.assertEqual(orient.combine_votes(view, local), "A")


class _OccFixtures:
    """Minimal Fusion-like occurrence / body stubs for assembly-centre tests."""

    class Pt:
        def __init__(self, x, y, z):
            self.x, self.y, self.z = x, y, z

    class BBox:
        def __init__(self, xmin, ymin, zmin, xmax, ymax, zmax):
            self.minPoint = _OccFixtures.Pt(xmin, ymin, zmin)
            self.maxPoint = _OccFixtures.Pt(xmax, ymax, zmax)

    class Occ:
        def __init__(self, bbox, parent=None, name=""):
            self.boundingBox = bbox
            self.assemblyContext = parent
            self.name = name

    class Body:
        def __init__(self, occ, bbox=None):
            self.assemblyContext = occ
            self.boundingBox = bbox


class OccurrenceCenterTests(unittest.TestCase):
    def test_prefers_root_child_cabinet_over_leaf(self):
        # Root → GT_cabinet → board leaf → door body.
        # M = cabinet (root child), not the thin leaf.
        cabinet = _OccFixtures.Occ(
            _OccFixtures.BBox(0, -80, 0, 60, -48, 200), name="GT_CH1965:1"
        )
        leaf = _OccFixtures.Occ(
            _OccFixtures.BBox(0, -50, 0, 60, -48, 200), parent=cabinet, name="GT_FP_1:1"
        )
        body = _OccFixtures.Body(leaf)
        center = orient.assembly_center_for_body(body)
        # Cabinet centre: x=30cm→300mm, y=-64cm→-640mm, z=100cm→1000mm
        self.assertEqual(center, [300.0, -640.0, 1000.0])

    def test_climbs_past_nested_board_to_root_child(self):
        # Root → OHC:1 → mid group → board leaf. Stop at OHC, not mid/leaf.
        ohc = _OccFixtures.Occ(
            _OccFixtures.BBox(-10, -90, 0, 70, -40, 220), name="OHC:1"
        )
        mid = _OccFixtures.Occ(
            _OccFixtures.BBox(0, -70, 0, 60, -45, 200), parent=ohc, name="doors:1"
        )
        leaf = _OccFixtures.Occ(
            _OccFixtures.BBox(0, -50, 0, 60, -48, 200), parent=mid, name="door:1"
        )
        body = _OccFixtures.Body(leaf)
        center = orient.assembly_center_for_body(body)
        # OHC centre: x=30cm→300mm, y=-65cm→-650mm, z=110cm→1100mm
        self.assertEqual(center, [300.0, -650.0, 1100.0])

    def test_does_not_use_sibling_or_invent_root(self):
        # Body already on a root-level child (Fridge:1) — use that occurrence.
        fridge = _OccFixtures.Occ(
            _OccFixtures.BBox(100, -100, 0, 160, -40, 200), name="Fridge:1"
        )
        body = _OccFixtures.Body(fridge)
        center = orient.assembly_center_for_body(body)
        self.assertEqual(center, [1300.0, -700.0, 1000.0])

    def test_leaf_only_uses_leaf_bbox(self):
        # Occurrence is already a root child (no parent) — use its bbox.
        leaf = _OccFixtures.Occ(_OccFixtures.BBox(0, -50, 0, 60, -48, 200))
        body = _OccFixtures.Body(leaf)
        center = orient.assembly_center_for_body(body)
        self.assertEqual(center, [300.0, -490.0, 1000.0])

    def test_no_occurrence_falls_back_to_body_bbox(self):
        body = _OccFixtures.Body(
            None, bbox=_OccFixtures.BBox(0, -50, 0, 60, -48, 200)
        )
        center = orient.assembly_center_for_body(body)
        self.assertEqual(center, [300.0, -490.0, 1000.0])


if __name__ == "__main__":
    unittest.main()
