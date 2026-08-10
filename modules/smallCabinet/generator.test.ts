import assert from "node:assert/strict";
import { computeFrontPanelBounds } from "./frontPanelCalculator.ts";
import {
  generateSmallCabinet,
  GROOVE_LENGTH_OVERSIZE,
  GROOVE_THICKNESS_OVERSIZE,
  shelfTongueYRange,
} from "./generator.ts";

function boardById(result: ReturnType<typeof generateSmallCabinet>, id: string) {
  return result.boards.find((b) => b.id === id);
}

function testTwoZoneDoorDrawer(): void {
  const result = generateSmallCabinet({
    cabinetWidth: 600,
    cabinetDepth: 560,
    cabinetHeight: 800,
    panelThickness: 16,
    frontPanelThickness: 18,
    frontClearance: 2.5,
    leftSideDoorColor: true,
    rightSideDoorColor: false,
    zones: [
      { id: "upper", type: "left_door", height: 400 },
      { id: "lower", type: "drawer", height: 368 },
    ],
  });

  assert.equal(result.validation.errors.length, 0, result.validation.errors.join("; "));
  assert.equal(result.boards.length, 8);

  const left = boardById(result, "SIDE_L");
  const right = boardById(result, "SIDE_R");
  const back = boardById(result, "BACK");
  const top = boardById(result, "TOP");
  const bottom = boardById(result, "BOTTOM");
  const mid = boardById(result, "MID_1");
  const fp1 = boardById(result, "FP_1");
  const fp2 = boardById(result, "FP_2");

  assert.ok(left && right && back && top && bottom && mid && fp1 && fp2);

  // Through tongues: horizontal boards expand by full CPT on each side.
  assert.equal(mid.x0, 0);
  assert.equal(mid.x1, 600);
  assert.equal(top.x0, 0);
  assert.equal(top.x1, 600);
  assert.equal(bottom.x0, 0);
  assert.equal(bottom.x1, 600);
  assert.equal(back.x0, 0);
  assert.equal(back.x1, 600);

  const { tongueY0, tongueY1 } = shelfTongueYRange(0, 544);
  assert.ok(Math.abs(tongueY1 - tongueY0 - 544 / 3) < 0.15);

  // Front clearance + lock on side door only.
  assert.equal(fp1.z0, 385.3);
  assert.equal(fp1.z1, 781.5);
  assert.ok(fp1.lockCutout, "side door gets lock cutout");
  assert.ok(fp1.profileFeatures?.some((f) => f.type === "door_lock"));
  assert.equal(fp2.lockCutout, undefined);
  assert.equal(fp2.z0, 18.5);
  assert.equal(fp2.z1, 382.8);

  // Grooves: TOP + BOTTOM + MID + BACK → 4 boards × 2 sides = 8
  const grooves = result.features.filter((f) => f.type === "side_groove");
  assert.equal(grooves.length, 8);
  const midGrooves = grooves.filter((g) => g.relatedBoardId === "MID_1");
  assert.equal(midGrooves.length, 2);
  for (const groove of midGrooves) {
    assert.equal(groove.y0, tongueY0 - GROOVE_LENGTH_OVERSIZE);
    assert.equal(groove.y1, tongueY1 + GROOVE_LENGTH_OVERSIZE);
    assert.equal(groove.z0, 376 - GROOVE_THICKNESS_OVERSIZE);
    assert.equal(groove.z1, 392 + GROOVE_THICKNESS_OVERSIZE);
    assert.equal(groove.depth, 16);
  }

  const backGrooves = grooves.filter((g) => g.relatedBoardId === "BACK");
  assert.equal(backGrooves.length, 2);
  for (const groove of backGrooves) {
    assert.equal(groove.depth, 16);
    // thickness axis oversize on Y (back thickness)
    assert.equal(groove.y0, 544 - GROOVE_THICKNESS_OVERSIZE);
    assert.equal(groove.y1, 560 + GROOVE_THICKNESS_OVERSIZE);
  }

  assert.equal(result.features.filter((f) => f.type === "shelf_tongue").length, 6); // top/mid/bottom ×2
  assert.equal(result.features.filter((f) => f.type === "back_tongue").length, 2);
  assert.equal(result.features.filter((f) => f.type === "door_lock").length, 1);
  assert.equal(left.profileFeatures?.length, 4);
  assert.equal(right.profileFeatures?.length, 4);
}

function testFrontPanelCalculatorNeighborHalfClearance(): void {
  const zones = [
    {
      id: "a",
      type: "left_door" as const,
      height: 400,
      zTop: 784,
      zBottom: 384,
      clearZ0: 392,
      clearZ1: 784,
      lockEnabled: true,
      lockSideDistance: 80,
    },
    {
      id: "b",
      type: "right_door" as const,
      height: 368,
      zTop: 384,
      zBottom: 16,
      clearZ0: 16,
      clearZ1: 376,
      lockEnabled: true,
      lockSideDistance: 80,
    },
  ];
  const upper = computeFrontPanelBounds({
    cabinetWidth: 600,
    cabinetHeight: 800,
    panelThickness: 16,
    frontClearance: 2.5,
    zone: zones[0],
    zoneIndex: 0,
    zones,
  });
  const lower = computeFrontPanelBounds({
    cabinetWidth: 600,
    cabinetHeight: 800,
    panelThickness: 16,
    frontClearance: 2.5,
    zone: zones[1],
    zoneIndex: 1,
    zones,
  });
  assert.equal(Math.round((upper.z0 - lower.z1) * 10) / 10, 2.5);
}

function testSingleRightDoor(): void {
  const result = generateSmallCabinet({
    cabinetWidth: 450,
    cabinetDepth: 400,
    cabinetHeight: 720,
    panelThickness: 18,
    frontPanelThickness: 18,
    frontClearance: 2,
    zones: [{ type: "right_door", height: 684 }],
  });
  assert.equal(result.validation.errors.length, 0, result.validation.errors.join("; "));
  assert.equal(result.boards.filter((b) => b.id.startsWith("MID_")).length, 0);
  // TOP + BOTTOM + BACK → 6 side grooves
  assert.equal(result.features.filter((f) => f.type === "side_groove").length, 6);
  const fp = boardById(result, "FP_1");
  assert.ok(fp?.lockCutout);
  assert.equal((fp as { thickness?: number })?.thickness, 18);
}

function testLocksCanBeDisabled(): void {
  const result = generateSmallCabinet({
    cabinetWidth: 450,
    cabinetDepth: 400,
    cabinetHeight: 720,
    panelThickness: 18,
    locksEnabled: false,
    zones: [{ type: "left_door", height: 684 }],
  });
  assert.equal(result.validation.errors.length, 0);
  assert.equal(boardById(result, "FP_1")?.lockCutout, undefined);
  assert.equal(result.features.filter((f) => f.type === "door_lock").length, 0);
}

function testRejectsBadZoneTypeAndHeightSum(): void {
  const badType = generateSmallCabinet({
    cabinetWidth: 600,
    cabinetDepth: 500,
    cabinetHeight: 800,
    zones: [{ type: "double_door", height: 768 }],
  });
  assert.ok(badType.validation.errors.some((e) => e.includes("unsupported type")));

  const badSum = generateSmallCabinet({
    cabinetWidth: 600,
    cabinetDepth: 500,
    cabinetHeight: 800,
    panelThickness: 16,
    zones: [{ type: "drawer", height: 100 }],
  });
  assert.ok(badSum.validation.errors.some((e) => e.includes("interior height")));
}

function testThreeZonesBoardCount(): void {
  const result = generateSmallCabinet({
    cabinetWidth: 500,
    cabinetDepth: 450,
    cabinetHeight: 800,
    panelThickness: 16,
    zones: [
      { type: "left_door", height: 256 },
      { type: "drawer", height: 256 },
      { type: "right_door", height: 256 },
    ],
  });
  assert.equal(result.validation.errors.length, 0, result.validation.errors.join("; "));
  // TOP+BOTTOM+2×MID+BACK = 5 horiz/back × 2 sides = 10 grooves
  assert.equal(result.features.filter((f) => f.type === "side_groove").length, 10);
  assert.equal(result.features.filter((f) => f.type === "door_lock").length, 2);
}

const tests = [
  testTwoZoneDoorDrawer,
  testFrontPanelCalculatorNeighborHalfClearance,
  testSingleRightDoor,
  testLocksCanBeDisabled,
  testRejectsBadZoneTypeAndHeightSum,
  testThreeZonesBoardCount,
];

let failed = 0;
for (const test of tests) {
  try {
    test();
    console.log(`PASS ${test.name}`);
  } catch (error) {
    failed += 1;
    console.error(`FAIL ${test.name}`);
    console.error(error);
  }
}

if (failed > 0) {
  console.error(`${failed}/${tests.length} failed`);
  process.exitCode = 1;
} else {
  console.log(`OK ${tests.length}/${tests.length}`);
}
