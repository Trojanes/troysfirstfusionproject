import assert from "node:assert/strict";
import { generateKitchenCabinetGeometry } from "./generator.ts";
import type { KitchenLayoutState } from "./types.ts";

function washerBayState(overrides: Partial<KitchenLayoutState["globalSettings"]> = {}): KitchenLayoutState {
  return {
    globalSettings: {
      length: 700,
      depth: 500,
      height: 880,
      materialThickness: 15,
      frontThickness: 16,
      bottomClearanceHeight: 70,
      bottomClearanceStyle: "style_1",
      ledGroove: true,
      ...overrides,
    },
    columns: [
      {
        id: "k-col-1",
        width: 700,
        columnType: "left_door",
        zones: [
          {
            id: "k-zone-washer",
            height: 810,
            zoneType: "left_door",
            shelfEnabled: false,
            applianceFloorEnabled: true,
          },
        ],
      },
    ],
    wheelAvoidances: [],
  };
}

function testHappyPath() {
  const result = generateKitchenCabinetGeometry(washerBayState());
  assert.equal(result.errors.length, 0, result.errors.join("; "));
  const floor = result.boards.find((board) => board.type === "appliance_floor");
  assert.ok(floor, "appliance_floor missing");
  const b3 = result.boards.find((board) => board.id === "B3");
  assert.ok(b3, "B3 missing");
  assert.equal(floor!.z0, b3!.z0, "floor Z must flush with B3");
  assert.equal(floor!.z1, b3!.z1);
  assert.ok(Math.abs(floor!.y0 - 100) < 0.01, `floor should butt B3 rear at y=100, got ${floor!.y0}`);
  assert.ok(floor!.y1 < b3!.y1 + 50 || floor!.y0 >= b3!.y1 - 0.01, "floor starts at/behind B3 rear");
  const supports = result.boards.filter((board) => board.type === "underside_support");
  assert.ok(supports.length >= 1, "underside supports expected");
  for (const support of supports) {
    assert.equal(support.z0, 0);
    assert.equal(support.z1, 70);
    assert.ok(support.y0 >= floor!.y0 - 0.01);
    assert.ok(support.y1 <= floor!.y1 + 0.01);
  }
  const floorSlots = result.slotRequests.filter((slot) => slot.boardId === floor!.id);
  assert.equal(floorSlots.length, 2, "appliance_floor needs left/right V slots");
  assert.ok(floorSlots.every((slot) => slot.y0 >= floor!.y0 - 0.01 && slot.y1 <= floor!.y1 + 0.01));
  const relIds = (result.relationshipDeclarations || []).map((item) => item.declarationId);
  assert.ok(relIds.some((id) => id.includes(floor!.id) && id.includes("b3")), "B3 relationship missing");
  assert.ok(relIds.some((id) => id.includes("underside")), "support relationship missing");
}

function testAvoidanceHardGate() {
  const state = washerBayState();
  state.wheelAvoidances = [{ id: "wa-1", x0: 100, x1: 400, height: 200, depth: 150 }];
  const result = generateKitchenCabinetGeometry(state);
  assert.ok(result.errors.some((error) => /wheel avoidance/i.test(error)), result.errors.join("; "));
  assert.equal(result.boards.filter((board) => board.type === "appliance_floor").length, 0);
}

function testShallowDepthRejected() {
  const result = generateKitchenCabinetGeometry(washerBayState({ depth: 270 }));
  assert.ok(result.errors.some((error) => /structural depth/i.test(error)), result.errors.join("; "));
}

function testDoubleDoorRejected() {
  const state = washerBayState();
  state.columns[0].columnType = "double_door";
  state.columns[0].zones[0].zoneType = "double_door";
  const result = generateKitchenCabinetGeometry(state);
  assert.ok(result.errors.some((error) => /left_door or right_door/i.test(error)), result.errors.join("; "));
}

function testStyle2Rejected() {
  const result = generateKitchenCabinetGeometry(washerBayState({ bottomClearanceStyle: "style_2" }));
  assert.ok(result.errors.some((error) => /Style 1/i.test(error)), result.errors.join("; "));
}

function testNonBottomZoneRejected() {
  const state = washerBayState();
  state.columns[0].zones = [
    { id: "k-zone-door-top", height: 400, zoneType: "left_door", applianceFloorEnabled: true, shelfEnabled: false },
    { id: "k-zone-drawer", height: 410, zoneType: "drawer" },
  ];
  const result = generateKitchenCabinetGeometry(state);
  assert.ok(result.errors.some((error) => /bottom zone/i.test(error)), result.errors.join("; "));
}

testHappyPath();
testAvoidanceHardGate();
testShallowDepthRejected();
testDoubleDoorRejected();
testStyle2Rejected();
testNonBottomZoneRejected();
console.log("kitchen washer floor tests passed");
