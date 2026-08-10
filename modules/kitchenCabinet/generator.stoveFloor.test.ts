import assert from "node:assert/strict";
import { generateKitchenCabinetGeometry } from "./generator.ts";
import type { KitchenLayoutState, KitchenZoneType } from "./types.ts";

const CPT = 15;
const CLEARANCE = 2.5;

function stoveState(belowType?: KitchenZoneType): KitchenLayoutState {
  const zones: KitchenLayoutState["columns"][number]["zones"] = belowType
    ? [
        { id: "stove-zone", height: 450, zoneType: "stove" },
        {
          id: "below-zone",
          height: 375,
          zoneType: belowType,
          ...(belowType === "left_door" || belowType === "right_door" || belowType === "double_door"
            ? { shelfEnabled: false }
            : {}),
        },
      ]
    : [{ id: "stove-zone", height: 825, zoneType: "stove" }];
  return {
    globalSettings: {
      length: 700,
      depth: 500,
      height: 880,
      materialThickness: CPT,
      frontThickness: 16,
      frontClearance: CLEARANCE,
      bottomClearanceHeight: 55,
      bottomClearanceStyle: "style_1",
      ledGroove: true,
    },
    columns: [{ id: "stove-column", width: 700, columnType: "stove", zones }],
    wheelAvoidances: [],
  };
}

function assertStovePair(belowType: "drawer" | "down_flap" | "left_door" | "right_door" | "double_door"): void {
  const result = generateKitchenCabinetGeometry(stoveState(belowType));
  assert.deepEqual(result.errors, [], `${belowType}: ${result.errors.join("; ")}`);

  const full = result.boards.find((board) => board.id === "stove-column-stove-zone-bottom");
  const half = result.boards.find((board) => board.id === "stove-column-stove-zone-stove-half-divider");
  assert.ok(full, `${belowType}: stove full-depth shelf missing`);
  assert.equal(full.type, "full_depth_shelf");
  assert.ok(half, `${belowType}: stove half divider missing`);
  assert.equal(half.type, "drawer_divider");
  assert.equal(half.y0, 0);
  assert.equal(half.y1, result.constants.b3Depth);
  assert.equal(half.z1, full.z0, `${belowType}: half top must touch full underside`);
  assert.equal(half.z0, full.z0 - CPT);

  const belowFronts = result.frontPanels.filter((panel) => panel.zoneId === "below-zone");
  const expectedLeaves = belowType === "double_door" ? 2 : 1;
  assert.equal(belowFronts.length, expectedLeaves, `${belowType}: lower front count`);
  const halfCenterZ = (half.z0 + half.z1) / 2;
  for (const panel of belowFronts) {
    assert.equal(
      panel.z1,
      halfCenterZ - CLEARANCE,
      `${belowType}: front top must stop at half-strip mid-plane minus clearance`,
    );
    if (panel.lockCutout) {
      const expectedLockCenterZ = halfCenterZ - CPT / 2 - 30.5;
      assert.equal(
        panel.lockCutout.centerZ,
        expectedLockCenterZ,
        `${belowType}: lock must sit below half-strip underside`,
      );
    }
  }

  assert.equal(result.slotRequests.filter((slot) => slot.boardId === full.id).length, 2);
  assert.equal(result.slotRequests.filter((slot) => slot.boardId === half.id).length, 2);

  const leftPanel = result.boards.find((board) => board.id.endsWith("-stove-side-panel-left"));
  const rightPanel = result.boards.find((board) => board.id.endsWith("-stove-side-panel-right"));
  assert.ok(leftPanel, `${belowType}: left stove side panel missing`);
  assert.ok(rightPanel, `${belowType}: right stove side panel missing`);
  for (const panel of [leftPanel, rightPanel]) {
    assert.equal(panel.type, "stove_side_panel");
    assert.equal(panel.profilePlane, "XZ");
    assert.equal(panel.thicknessAxis, "Y");
    assert.equal(panel.materialThickness, 16);
    assert.equal(panel.y0, -16);
    assert.equal(panel.y1, 0);
    assert.equal(panel.x1 - panel.x0, 100);
    assert.equal(panel.z0, halfCenterZ, `${belowType}: stove side panel must reach half-strip mid-plane`);
    assert.equal(panel.z1, 880 - CLEARANCE);
    assert.equal(panel.notches?.length, 1);
    const notch = panel.notches![0];
    assert.equal(notch.x1! - notch.x0!, 20);
    assert.equal(notch.z1! - notch.z0!, 30);
    assert.equal(panel.body?.cutouts.length, 0, "top edge notch should be folded into the outer profile");
  }
  assert.equal(leftPanel.x0 + rightPanel.x1, 700, "outer edges must mirror around the column centerline");
  assert.equal(leftPanel.x1 + rightPanel.x0, 700, "inner edges must mirror around the column centerline");
  assert.equal(leftPanel.notches![0].x1, leftPanel.x1, "left notch must face center");
  assert.equal(rightPanel.notches![0].x0, rightPanel.x0, "right notch must face center");
}

for (const type of ["drawer", "down_flap", "left_door", "right_door", "double_door"] as const) {
  assertStovePair(type);
}

{
  const result = generateKitchenCabinetGeometry(stoveState());
  assert.deepEqual(result.errors, [], result.errors.join("; "));
  assert.equal(result.boards.some((board) => board.id.includes("stove-half-divider")), false);
  const extension = result.boards.find((board) => board.id === "stove-column-stove-zone-bottom-full-extension");
  const b3 = result.boards.find((board) => board.id === "B3");
  assert.ok(extension, "lone bottom stove rear full-depth extension missing");
  assert.ok(b3, "B3 missing");
  assert.equal(result.boards.some((board) => board.type === "stove_side_panel"), false);
  assert.equal(extension.type, "full_depth_shelf");
  assert.equal(extension.y0, result.constants.supportStripWidth);
  assert.equal(extension.y1, 500 - 16);
  assert.equal(extension.z0, b3.z0);
  assert.equal(extension.z1, b3.z1);
}

{
  const result = generateKitchenCabinetGeometry(stoveState("open"));
  assert.equal(result.boards.some((board) => board.id.includes("stove-half-divider")), false);
  assert.equal(result.boards.some((board) => board.type === "stove_side_panel"), false);
}

{
  const state = stoveState("drawer");
  state.columns[0].zones = [
    { id: "drawer-above", height: 200, zoneType: "drawer" },
    { id: "stove-not-top", height: 450, zoneType: "stove" },
    { id: "drawer-below", height: 175, zoneType: "drawer" },
  ];
  const result = generateKitchenCabinetGeometry(state);
  assert.ok(
    result.errors.some((error) => error.includes("Stove zone stove-not-top must be the top zone")),
    result.errors.join("; "),
  );
}

console.log("kitchen stove full + half floor tests passed");
