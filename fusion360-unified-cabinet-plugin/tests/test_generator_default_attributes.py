import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "panel_attributes" / "generator_default_attributes.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generator_default_attributes_under_test", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class GeneratorDefaultAttributesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.mod = _load_module()

    def test_overhead_door_vs_carcass(self):
        boards = [{"id": "D1"}, {"id": "D2"}, {"id": "D3"}]
        t1 = self.mod.overhead_board_semantics({"id": "T1"}, boards)
        fp = self.mod.overhead_board_semantics({"id": "FP1", "boardType": "up_flap"}, boards)
        bp = self.mod.overhead_board_semantics({"id": "BP"}, boards)
        self.assertEqual(t1["panelClass"], "door")
        self.assertEqual(fp["panelClass"], "door")
        self.assertEqual(bp["panelClass"], "carcass")
        meta = self.mod.build_panel_metadata("overhead", {"id": "T1"}, all_boards=boards, run_label="r1")
        self.assertEqual(meta["classification"]["boardType"]["value"], "door")
        self.assertEqual(meta["classification"]["boardType"]["source"], "generator")
        self.assertTrue(meta["identity"]["panelId"].startswith("ohc.r1."))

    def test_overhead_milling_directions_xyz(self):
        cases = [
            ({"id": "BP"}, "+Z", "-Z", "MILLING"),
            ({"id": "T3"}, "+Z", "-Z", "MILLING"),
            ({"id": "RGHD_TOP", "boardType": "RGHD_TOP"}, "", "", "EITHER"),
            ({"id": "T1"}, "+Y", "-Y", "MILLING"),
            ({"id": "FP0", "boardType": "up_flap"}, "+Y", "-Y", "MILLING"),
            ({"id": "FP1", "boardType": "rangehood_flap"}, "+Y", "-Y", "MILLING"),
            ({"id": "FP1", "boardType": "fixed_panel"}, "+Y", "-Y", "MILLING"),
            ({"id": "zone_door", "boardType": "up_flap"}, "+Y", "-Y", "MILLING"),
            ({"id": "T2"}, "", "", "EITHER"),
            ({"id": "T4"}, "", "", "EITHER"),
            ({"id": "D1"}, "", "", "EITHER"),
        ]
        for board, milling_dir, colour_dir, cutting in cases:
            label = "{}/{}".format(board.get("id"), board.get("boardType") or "")
            milling = self.mod.overhead_milling_direction(board)
            self.assertEqual(milling["millingDirection"], milling_dir, label)
            self.assertEqual(milling["colourDirection"], colour_dir, label)
            self.assertEqual(milling["cuttingFace"], cutting, label)
            meta = self.mod.build_panel_metadata(
                "overhead",
                dict(board, profilePlane="XZ", thicknessAxis="Y"),
                run_label="oh1",
            )
            self.assertEqual(meta["classification"]["cuttingFace"]["value"], cutting, label)
            self.assertEqual(meta["classification"]["cuttingFace"]["source"], "generator", label)
            if milling_dir:
                self.assertEqual(meta["defaultAttributes"]["millingDirection"], milling_dir, label)
                self.assertEqual(meta["designGeometry"]["millingDirection"], milling_dir, label)
            else:
                self.assertNotIn("millingDirection", meta["defaultAttributes"])

    def test_overhead_rangehood_milling_uses_actual_groove_faces(self):
        features = [
            {
                "type": "rangehood_divider_side_groove",
                "targetBoardId": "D0",
                "face": "+X",
            },
            {
                "type": "rangehood_divider_side_groove",
                "targetBoardId": "D2",
                "face": "-X",
            },
            {
                "type": "rangehood_top_divider_groove",
                "targetBoardId": "RGHD_TOP",
                "face": "top",
            },
        ]
        cases = [
            ({"id": "D0"}, "+X", "-X", "MILLING"),
            ({"id": "D2"}, "-X", "+X", "MILLING"),
            ({"id": "D1"}, "", "", "EITHER"),
            ({"id": "RGHD_TOP", "boardType": "RGHD_TOP"}, "+Z", "-Z", "MILLING"),
        ]
        for board, milling_dir, colour_dir, cutting in cases:
            milling = self.mod.overhead_milling_direction(board, features=features)
            self.assertEqual(milling["millingDirection"], milling_dir, board["id"])
            self.assertEqual(milling["colourDirection"], colour_dir, board["id"])
            self.assertEqual(milling["cuttingFace"], cutting, board["id"])
            meta = self.mod.build_panel_metadata(
                "overhead",
                board,
                features=features,
                run_label="oh-rangehood",
            )
            self.assertEqual(meta["classification"]["cuttingFace"]["value"], cutting, board["id"])
            if milling_dir:
                self.assertEqual(meta["defaultAttributes"]["millingDirection"], milling_dir, board["id"])
            else:
                self.assertNotIn("millingDirection", meta["defaultAttributes"])

        both_faces = features + [{
            "type": "rangehood_divider_side_groove",
            "targetBoardId": "D0",
            "face": "-X",
        }]
        self.assertEqual(
            self.mod.overhead_milling_direction({"id": "D0"}, features=both_faces)["cuttingFace"],
            "EITHER",
        )

    def test_overhead_rangehood_semantics(self):
        boards = [
            {"id": "D0"}, {"id": "D1"},
            {"id": "RGHD_TOP", "boardType": "RGHD_TOP"},
            {"id": "RGHD_FRONT", "boardType": "RGHD_FRONT"},
            {"id": "RGHD_BACK", "boardType": "RGHD_BACK"},
            {"id": "FP0", "boardType": "rangehood_flap"},
        ]
        for board_id in ("RGHD_TOP", "RGHD_FRONT", "RGHD_BACK"):
            semantics = self.mod.overhead_board_semantics(
                next(board for board in boards if board["id"] == board_id),
                boards,
            )
            self.assertEqual(semantics["panelClass"], "carcass")
            self.assertIn("rangehood", semantics["tags"])
        flap = self.mod.overhead_board_semantics(boards[-1], boards)
        self.assertEqual(flap["panelClass"], "door")
        self.assertEqual(flap["boardType"], "rangehood_flap_door_panel")

    def test_u_shape_overhead_semantics_and_world_milling(self):
        connector = self.mod.overhead_board_semantics(
            {"id": "U_CONNECTOR", "boardType": "u_back_connector_panel"},
        )
        clearance = self.mod.overhead_board_semantics(
            {"id": "FP_CLEARANCE_SIDE", "boardType": "u_clearance_fixed_panel"},
        )
        self.assertEqual(connector["boardType"], "u_back_connector_panel")
        self.assertEqual(connector["panelClass"], "carcass")
        self.assertIn("connector", connector["tags"])
        self.assertEqual(clearance["boardType"], "u_clearance_fixed_front_panel")
        self.assertEqual(clearance["panelClass"], "door")
        self.assertIn("clearance", clearance["tags"])

        cases = [
            (90, "-X", "+X"),
            (180, "-Y", "+Y"),
            (-90, "+X", "-X"),
        ]
        for degrees, milling, colour in cases:
            direction = self.mod.overhead_milling_direction({
                "id": "FP0",
                "boardType": "up_flap",
                "worldRotationDeg": degrees,
            })
            self.assertEqual(direction["millingDirection"], milling)
            self.assertEqual(direction["colourDirection"], colour)
        self.assertEqual(
            self.mod.overhead_milling_direction({"id": "BP", "worldRotationDeg": 90})["millingDirection"],
            "+Z",
        )

    def test_kitchen_b1_door_t1_carcass_and_v_panel_door(self):
        b1 = self.mod.kitchen_board_semantics({"id": "B1", "type": "B1"})
        t1 = self.mod.kitchen_board_semantics({"id": "cab-T1", "type": "T1"})
        v_door = self.mod.kitchen_board_semantics(
            {"id": "V0", "kind": "vPanel", "sidePanelOptions": {"panelType": "door"}},
            v_panels=[{"id": "V0"}, {"id": "V1"}],
        )
        v_carcass = self.mod.kitchen_board_semantics(
            {"id": "V1", "kind": "vPanel", "sidePanelOptions": {"panelType": "panel"}},
            v_panels=[{"id": "V0"}, {"id": "V1"}],
        )
        stove_side = self.mod.kitchen_board_semantics(
            {"id": "stove-zone-stove-side-panel-left", "type": "stove_side_panel"}
        )
        self.assertEqual(b1["panelClass"], "door")
        self.assertEqual(t1["panelClass"], "carcass")
        self.assertEqual(v_door["panelClass"], "door")
        self.assertEqual(v_carcass["panelClass"], "carcass")
        self.assertEqual(stove_side["panelClass"], "door")
        self.assertEqual(stove_side["role"], "door")
        self.assertEqual(stove_side["doorColorSlot"], 1)
        self.assertIn("door", stove_side["tags"])

    def test_kitchen_milling_directions_xyz(self):
        left_half = [{
            "kind": "slot",
            "slotType": "half",
            "side": "left",
        }]
        right_half = [{
            "kind": "slot",
            "slotType": "half",
            "side": "right",
        }]
        both_halves = left_half + right_half
        cases = [
            ({"id": "B1", "type": "B1"}, "+Y", "-Y", "MILLING"),
            ({"id": "fp1", "kind": "frontPanel", "type": "left_door"}, "+Y", "-Y", "MILLING"),
            ({"id": "fp2", "kind": "frontPanel", "type": "drawer"}, "+Y", "-Y", "MILLING"),
            ({"id": "B3", "type": "B3"}, "-Z", "+Z", "MILLING"),
            (
                {"id": "V0", "kind": "vPanel", "sidePanelOptions": {"panelType": "door"}},
                "+X",
                "-X",
                "MILLING",
            ),
            (
                {"id": "V2", "kind": "vPanel", "sidePanelOptions": {"panelType": "door"}},
                "-X",
                "+X",
                "MILLING",
            ),
            (
                {"id": "V1", "kind": "vPanel", "halfGrooveVectors": left_half},
                "-X",
                "+X",
                "MILLING",
            ),
            (
                {"id": "V1", "kind": "vPanel", "halfGrooveVectors": right_half},
                "+X",
                "-X",
                "MILLING",
            ),
            (
                {"id": "V1", "kind": "vPanel", "halfGrooveVectors": both_halves},
                "",
                "",
                "EITHER",
            ),
            ({"id": "V1", "kind": "vPanel"}, "", "", "EITHER"),
            ({"id": "cab-T1", "type": "T1"}, "", "", "EITHER"),
            ({"id": "B2", "type": "B2"}, "", "", "EITHER"),
            ({"id": "T2", "type": "T2"}, "", "", "EITHER"),
            ({"id": "shelf-1", "type": "full_depth_shelf"}, "", "", "EITHER"),
            ({"id": "col-zone-appliance-floor", "type": "appliance_floor"}, "", "", "EITHER"),
            ({"id": "col-zone-underside-support-1", "type": "underside_support"}, "", "", "EITHER"),
            ({"id": "stove-zone-stove-side-panel-left", "type": "stove_side_panel"}, "+Y", "-Y", "MILLING"),
        ]
        v_panels = [{"id": "V0", "index": 0}, {"id": "V1", "index": 1}, {"id": "V2", "index": 2}]
        for board, milling_dir, colour_dir, cutting in cases:
            label = "{}/{}".format(board.get("id"), board.get("type") or board.get("kind") or "")
            milling = self.mod.kitchen_milling_direction(board, v_panels=v_panels)
            self.assertEqual(milling["millingDirection"], milling_dir, label)
            self.assertEqual(milling["colourDirection"], colour_dir, label)
            self.assertEqual(milling["cuttingFace"], cutting, label)
            meta = self.mod.build_panel_metadata("kitchen", board, run_label="k1", v_panels=v_panels)
            self.assertEqual(meta["classification"]["cuttingFace"]["value"], cutting, label)
            if milling_dir:
                self.assertEqual(meta["defaultAttributes"]["millingDirection"], milling_dir, label)
            else:
                self.assertNotIn("millingDirection", meta["defaultAttributes"])

    def test_general_tall_fronts_are_door(self):
        for board in (
            {"id": "T1"},
            {"id": "B1"},
            {"id": "FP_zone-1", "boardType": "cabinet_door", "category": "front_panel"},
            {"id": "FixedFrontPanel_1", "boardType": "style2_fixed_front_panel"},
        ):
            semantics = self.mod.general_tall_board_semantics(board)
            self.assertEqual(semantics["panelClass"], "door", board)
        shelf = self.mod.general_tall_board_semantics({"id": "shelf-1", "category": "shelf"})
        self.assertEqual(shelf["panelClass"], "carcass")

    def test_lounge_main_partition_middle_door(self):
        front = self.mod.lounge_board_semantics({"id": "main_front", "kind": "front_panel"})
        lid = self.mod.lounge_board_semantics({"id": "main_lid", "kind": "lid"})
        door = self.mod.lounge_board_semantics({"id": "MC_L_DR", "kind": "cabinet_door"})
        side = self.mod.lounge_board_semantics({"id": "MC_L", "kind": "cabinet_side"})
        self.assertEqual(front["panelClass"], "partition")
        self.assertEqual(lid["panelClass"], "partition")
        self.assertEqual(door["panelClass"], "door")
        self.assertEqual(side["panelClass"], "door")
        meta = self.mod.build_panel_metadata(
            "lounge",
            {"id": "main_front", "kind": "front_panel", "placement": {"x0": 0, "x1": 100, "y0": 0, "y1": 50, "z0": 0, "z1": 18}},
            run_label="lounge1",
        )
        self.assertEqual(meta["classification"]["boardType"]["value"], "partition")
        self.assertNotEqual(meta["classification"]["boardType"]["value"], "carcass")
        self.assertIn("lounge.lounge1.", meta["identity"]["panelId"])

    def test_small_cabinet_side_door_color_and_fronts(self):
        door = self.mod.small_cabinet_board_semantics({
            "id": "FP_1", "category": "front_panel", "boardType": "left_door",
        })
        drawer = self.mod.small_cabinet_board_semantics({
            "id": "FP_2", "category": "front_panel", "boardType": "drawer_front",
        })
        side_door = self.mod.small_cabinet_board_semantics({
            "id": "SIDE_L", "boardType": "left_side_panel", "useDoorColor": True,
        })
        side_carcass = self.mod.small_cabinet_board_semantics({
            "id": "SIDE_R", "boardType": "right_side_panel", "useDoorColor": False,
        })
        back = self.mod.small_cabinet_board_semantics({"id": "BACK", "boardType": "rear_vertical"})
        self.assertEqual(door["panelClass"], "door")
        self.assertEqual(door["doorColorSlot"], 1)
        self.assertEqual(drawer["panelClass"], "door")
        self.assertEqual(side_door["panelClass"], "door")
        self.assertEqual(side_door["doorColorSlot"], 1)
        self.assertEqual(side_carcass["panelClass"], "carcass")
        self.assertNotIn("doorColorSlot", side_carcass)
        self.assertEqual(back["panelClass"], "carcass")
        meta = self.mod.build_panel_metadata(
            "smallCabinet",
            {"id": "SIDE_L", "boardType": "left_side_panel", "useDoorColor": True,
             "x0": 0, "x1": 16, "y0": 0, "y1": 560, "z0": 0, "z1": 800},
            run_label="sc1",
        )
        self.assertEqual(meta["identity"]["generator"], "smallCabinet")
        self.assertIn("smallCabinet.sc1.", meta["identity"]["panelId"])
        self.assertEqual(meta["defaultAttributes"]["doorColorSlot"], 1)

    def test_small_cabinet_milling_directions(self):
        cases = [
            ({"id": "FP_1", "category": "front_panel", "boardType": "left_door"}, "+Y", "-Y", "MILLING"),
            ({"id": "SIDE_L", "boardType": "left_side_panel"}, "+X", "-X", "MILLING"),
            ({"id": "SIDE_R", "boardType": "right_side_panel"}, "-X", "+X", "MILLING"),
            ({"id": "TOP", "boardType": "top_panel"}, "-Z", "+Z", "MILLING"),
            ({"id": "BOTTOM", "boardType": "bottom_panel"}, "+Z", "-Z", "MILLING"),
            ({"id": "BACK", "boardType": "rear_vertical"}, "-Y", "+Y", "MILLING"),
            ({"id": "MID_1", "boardType": "middle_shelf"}, "+Z", "-Z", "MILLING"),
        ]
        for board, milling_dir, colour_dir, cutting in cases:
            milling = self.mod.small_cabinet_milling_direction(board)
            label = board["id"]
            self.assertEqual(milling["millingDirection"], milling_dir, label)
            self.assertEqual(milling["colourDirection"], colour_dir, label)
            self.assertEqual(milling["cuttingFace"], cutting, label)

    def test_lounge_milling_directions_xyz(self):
        cases = [
            ({"id": "MC_L_DR", "kind": "cabinet_door"}, "+Y", "-Y", "MILLING"),
            ({"id": "MC_R_DR", "kind": "cabinet_door"}, "+Y", "-Y", "MILLING"),
            ({"id": "MC_L", "kind": "cabinet_side"}, "+X", "-X", "MILLING"),
            ({"id": "MC_R", "kind": "cabinet_side"}, "-X", "+X", "MILLING"),
            ({"id": "MC_TOP", "kind": "cabinet_top"}, "-Z", "+Z", "MILLING"),
            ({"id": "MC_BOT", "kind": "cabinet_bottom"}, "+Z", "-Z", "MILLING"),
            ({"id": "main_top_lid", "kind": "lid"}, "-Z", "+Z", "MILLING"),
            (
                {
                    "id": "main_top",
                    "kind": "top_panel",
                    "opening": {"panelId": "main_top", "width": 100, "depth": 100},
                },
                "+Z",
                "-Z",
                "MILLING",
            ),
            ({"id": "main_top", "kind": "top_panel"}, "", "", "EITHER"),
            ({"id": "main_front", "kind": "front_panel"}, "", "", "EITHER"),
            ({"id": "l_side", "kind": "side_panel"}, "", "", "EITHER"),
            ({"id": "MC_MID", "kind": "cabinet_divider"}, "", "", "EITHER"),
            ({"id": "PA_FRONT", "kind": "avoidance_front"}, "", "", "EITHER"),
        ]
        for board, milling_dir, colour_dir, cutting in cases:
            label = "{}/{}".format(board.get("id"), board.get("kind") or "")
            milling = self.mod.lounge_milling_direction(board)
            self.assertEqual(milling["millingDirection"], milling_dir, label)
            self.assertEqual(milling["colourDirection"], colour_dir, label)
            self.assertEqual(milling["cuttingFace"], cutting, label)
            meta = self.mod.build_panel_metadata("lounge", board, run_label="lg1")
            self.assertEqual(meta["classification"]["cuttingFace"]["value"], cutting, label)
            if milling_dir:
                self.assertEqual(meta["defaultAttributes"]["millingDirection"], milling_dir, label)
            else:
                self.assertNotIn("millingDirection", meta["defaultAttributes"])

    def test_general_tall_milling_directions_xyz(self):
        cases = [
            ({"id": "T3"}, "+Z", "-Z", "MILLING"),
            ({"id": "B3"}, "-Z", "+Z", "MILLING"),
            ({"id": "T1"}, "+Y", "-Y", "MILLING"),
            ({"id": "B1"}, "+Y", "-Y", "MILLING"),
            ({"id": "FP_zone-1", "boardType": "cabinet_door", "category": "front_panel"}, "+Y", "-Y", "MILLING"),
            ({"id": "TopStyle2FixedFrontPanel", "boardType": "style2_fixed_front_panel"}, "+Y", "-Y", "MILLING"),
            ({"id": "T2"}, "", "", "EITHER"),
            ({"id": "B2"}, "", "", "EITHER"),
            ({"id": "V1"}, "", "", "EITHER"),
            ({"id": "SidePanel_L", "boardType": "side_panel", "category": "side_panel"}, "", "", "EITHER"),
            ({"id": "Zi1", "boardType": "full_zi", "category": "boundary_panel"}, "+Z", "-Z", "MILLING"),
        ]
        for board, milling_dir, colour_dir, cutting in cases:
            label = board.get("id")
            milling = self.mod.general_tall_milling_direction(board)
            self.assertEqual(milling["millingDirection"], milling_dir, label)
            self.assertEqual(milling["colourDirection"], colour_dir, label)
            self.assertEqual(milling["cuttingFace"], cutting, label)
            meta = self.mod.build_panel_metadata("generalTall", board, run_label="gt1")
            self.assertEqual(meta["classification"]["cuttingFace"]["value"], cutting, label)
            if milling_dir:
                self.assertEqual(meta["defaultAttributes"]["millingDirection"], milling_dir, label)

        zi = {"id": "Zi2", "boardType": "full_zi", "category": "boundary_panel"}
        bottom_groove = [{
            "type": "zi_groove",
            "targetBoardId": "Zi2",
            "dividerBoardId": "VD_zone-1",
            "face": "bottom",
        }]
        top_groove = [{
            "type": "zi_groove",
            "targetBoardId": "Zi2",
            "dividerBoardId": "VD_zone-1",
            "face": "top",
        }]
        both_grooves = bottom_groove + [{
            "type": "zi_groove",
            "targetBoardId": "Zi2",
            "dividerBoardId": "VD_zone-2",
            "face": "top",
        }]
        self.assertEqual(self.mod.general_tall_milling_direction(zi, features=bottom_groove)["millingDirection"], "-Z")
        self.assertEqual(self.mod.general_tall_milling_direction(zi, features=top_groove)["millingDirection"], "+Z")
        self.assertEqual(self.mod.general_tall_milling_direction(zi, features=both_grooves)["cuttingFace"], "EITHER")
        meta_bottom = self.mod.build_panel_metadata("generalTall", zi, run_label="gt1", features=bottom_groove)
        self.assertEqual(meta_bottom["defaultAttributes"]["millingDirection"], "-Z")

    def test_carcass_defaults_white_stipple_double_sided(self):
        bp = self.mod.build_panel_metadata("overhead", {"id": "BP"}, run_label="r1")
        self.assertEqual(bp["classification"]["color"]["value"], "white_stipple")
        self.assertEqual(bp["classification"]["color"]["source"], "generator")
        self.assertEqual(bp["defaultAttributes"]["surfaceMode"], "DOUBLE_SIDED")
        self.assertEqual(bp["defaultAttributes"]["colorName"], "White Stipple")

        custom = self.mod.build_panel_metadata(
            "kitchen",
            {"id": "B3", "type": "B3"},
            run_label="k1",
            carcass_color="Alpine White",
        )
        self.assertEqual(custom["classification"]["color"]["value"], "alpine_white")

        door = self.mod.build_panel_metadata(
            "overhead",
            {"id": "FP0", "boardType": "up_flap"},
            run_label="r1",
        )
        self.assertEqual(door["classification"]["color"]["value"], "")
        self.assertNotIn("surfaceMode", door["defaultAttributes"])

        lounge = self.mod.build_panel_metadata(
            "lounge",
            {"id": "main_front", "kind": "front_panel"},
            run_label="l1",
        )
        self.assertEqual(lounge["classification"]["color"]["value"], "white_stipple")
        self.assertEqual(lounge["defaultAttributes"]["surfaceMode"], "DOUBLE_SIDED")

    def test_kitchen_led_half_grooves_become_declared_cuts(self):
        board = {
            "id": "B3",
            "type": "B3",
            "halfGrooveVectors": [
                {
                    "sourceId": "B3_led_groove",
                    "kind": "slot",
                    "slotType": "half",
                    "side": "left",
                    "grooveDepth": 6.5,
                }
            ],
        }
        meta = self.mod.build_panel_metadata("kitchen", board, run_label="k1")
        declared = meta.get("declaredCuts") or []
        self.assertEqual(len(declared), 1)
        self.assertEqual(declared[0]["sourceId"], "B3_led_groove")
        self.assertEqual(declared[0]["purpose"], "led_groove")
        self.assertEqual(declared[0]["grooveDepth"], 6.5)


if __name__ == "__main__":
    unittest.main()
