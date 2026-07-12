import assert from "node:assert";
import { generateLoungeGeometry } from "./generator.ts";

function testDefaultLShape(): void {
  const result = generateLoungeGeometry({
    style: "L_SHAPE",
    height: 420,
    partitionPanelThickness: 18,
    mainWidth: 2000,
    mainDepth: 600,
    lWidth: 1600,
    lDepth: 800,
    lPosition: "RIGHT",
    topLidEnabled: true,
    lFrontAccess: "NONE",
  });
  assert.equal(result.validation.errors.length, 0);
  assert.equal(result.panels.length, 8);
  assert.equal(result.lids.length, 2);
  assert.equal(result.openings.length, 2);
  assert.deepEqual(result.footprint.l, { x0: 400, x1: 2000, y0: 0, y1: 800 });
  const mainFront = result.panels.find((panel) => panel.id === "main_front");
  assert.equal(mainFront?.width, 400);
  assert.deepEqual(mainFront?.placement, { x0: 0, x1: 400, y0: 582, y1: 600, z0: 0, z1: 402 });
  const lFront = result.panels.find((panel) => panel.id === "l_front");
  assert.equal(lFront?.width, 1582);
  assert.equal(lFront?.height, 402);
  assert.deepEqual(lFront?.placement, { x0: 418, x1: 2000, y0: 782, y1: 800, z0: 0, z1: 402 });
  const lPiece = result.panels.find((panel) => panel.id === "main_left_l_piece");
  assert.equal(lPiece?.length, 582);
  assert.deepEqual(lPiece?.placement, { x0: 0, x1: 18, y0: 18, y1: 600, z0: 0, z1: 402 });
  assert.deepEqual(lPiece?.outer, [[0, 0], [0, 402], [582, 402], [582, 302], [100, 302], [100, 0], [0, 0]]);
  const rightLPiece = result.panels.find((panel) => panel.id === "main_right_l_piece");
  assert.deepEqual(rightLPiece?.outer, [[0, 0], [0, 402], [582, 402], [582, 302], [100, 302], [100, 0], [0, 0]]);
  const lSide = result.panels.find((panel) => panel.id === "l_side");
  assert.deepEqual(lSide?.placement, { x0: 400, x1: 418, y0: 0, y1: 800, z0: 0, z1: 402 });
  const lSideStrip = result.panels.find((panel) => panel.id === "l_side_strip");
  assert.equal(lSideStrip?.height, 100);
  assert.deepEqual(lSideStrip?.placement, { x0: 1982, x1: 2000, y0: 0, y1: 782, z0: 302, z1: 402 });
  assert.deepEqual(lSideStrip?.outer, [[0, 0], [782, 0], [782, 100], [0, 100], [0, 0]]);
  const mainOpening = result.openings.find((opening) => opening.panelId === "main_top");
  assert.equal(mainOpening?.width, 200);
  assert.equal(mainOpening?.depth, 300);
  const mainLid = result.lids.find((lid) => lid.id === "main_top_lid");
  assert.equal(mainLid?.width, 197);
  assert.equal(mainLid?.depth, 297);
  assert.equal(mainLid?.fingerHole.diameter, 40);
}

function testLeftPositionAndNoLid(): void {
  const result = generateLoungeGeometry({
    style: "L_SHAPE",
    height: 450,
    partitionPanelThickness: 20,
    mainWidth: 2100,
    mainDepth: 650,
    lWidth: 700,
    lDepth: 900,
    lPosition: "LEFT",
    topLidEnabled: false,
    lFrontAccess: "DRAWER",
  });
  assert.deepEqual(result.footprint.l, { x0: 0, x1: 700, y0: 0, y1: 900 });
  assert.equal(result.openings.length, 0);
  assert.equal(result.lids.length, 0);
  assert(result.validation.warnings.some((warning) => warning.includes("placeholder")));
}

function testParallelLounge(): void {
  const result = generateLoungeGeometry({
    style: "PARALLEL",
    height: 420,
    partitionPanelThickness: 18,
    wheelAvoidanceEnabled: true,
    totalWidth: 4000,
    singleLoungeWidth: 1500,
    depth: 800,
    avoidanceDepth: 300,
    avoidanceHeight: 250,
    hasMiddleCabinet: true,
    middleCabinet: { width: 600, depth: 350, height: 500, startHeight: 300, doorPanelThickness: 15, doorClearance: 2 },
    topLidEnabled: true,
    lFrontAccess: "NONE",
  });
  assert.equal(result.meta.style, "PARALLEL");
  assert.equal(result.validation.errors.length, 0);
  assert.equal(result.panels.length, 17);
  assert.equal(result.openings.length, 2);
  assert.equal(result.lids.length, 2);
  assert.deepEqual(result.footprint.left, { x0: 0, x1: 1500, y0: 0, y1: 800 });
  assert.deepEqual(result.footprint.right, { x0: 2500, x1: 4000, y0: 0, y1: 800 });
  assert.equal(result.footprint.middleGap, 1000);
  const leftFront = result.panels.find((panel) => panel.id === "left_front");
  assert.deepEqual(leftFront?.placement, { x0: 0, x1: 1482, y0: 0, y1: 18, z0: 0, z1: 402 });
  const leftSide = result.panels.find((panel) => panel.id === "left_side");
  assert.deepEqual(leftSide?.placement, { x0: 1482, x1: 1500, y0: 0, y1: 800, z0: 0, z1: 402 });
  assert.deepEqual(leftSide?.outer, [[0, 0], [500, 0], [500, 250], [800, 250], [800, 402], [0, 402], [0, 0]]);
  const rightSide = result.panels.find((panel) => panel.id === "right_side");
  assert.deepEqual(rightSide?.placement, { x0: 2500, x1: 2518, y0: 0, y1: 800, z0: 0, z1: 402 });
  const rightFront = result.panels.find((panel) => panel.id === "right_front");
  assert.deepEqual(rightFront?.placement, { x0: 2518, x1: 4000, y0: 0, y1: 18, z0: 0, z1: 402 });
  const leftStrip = result.panels.find((panel) => panel.id === "left_support_strip");
  assert.deepEqual(leftStrip?.placement, { x0: 0, x1: 18, y0: 18, y1: 800, z0: 302, z1: 402 });
  assert.deepEqual(leftStrip?.outer, [[0, 0], [782, 0], [782, 100], [0, 100], [0, 0]]);
  const rightStrip = result.panels.find((panel) => panel.id === "right_support_strip");
  assert.deepEqual(rightStrip?.placement, { x0: 3982, x1: 4000, y0: 18, y1: 800, z0: 302, z1: 402 });
  const avTop = result.panels.find((panel) => panel.id === "parallel_avoidance_top");
  assert.deepEqual(avTop?.placement, { x0: 0, x1: 4000, y0: 500, y1: 800, z0: 232, z1: 250 });
  assert.deepEqual(avTop?.outer, [[0, 0], [4000, 0], [4000, 300], [0, 300], [0, 0]]);
  const avFront = result.panels.find((panel) => panel.id === "parallel_avoidance_front");
  assert.deepEqual(avFront?.placement, { x0: 0, x1: 4000, y0: 500, y1: 518, z0: 0, z1: 232 });
  assert.deepEqual(avFront?.outer, [[0, 0], [4000, 0], [4000, 232], [0, 232], [0, 0]]);
  const leftOpening = result.openings.find((opening) => opening.panelId === "left_top");
  assert.equal(leftOpening?.width, 750);
  assert.equal(leftOpening?.depth, 400);
  const leftLid = result.lids.find((lid) => lid.id === "left_top_lid");
  assert.equal(leftLid?.width, 747);
  assert.equal(leftLid?.depth, 397);
  const mcTop = result.panels.find((panel) => panel.id === "middle_cabinet_top");
  assert.deepEqual(mcTop?.placement, { x0: 1700, x1: 2300, y0: 450, y1: 800, z0: 785, z1: 800 });
  const mcDivider = result.panels.find((panel) => panel.id === "middle_cabinet_mid_divider");
  assert.deepEqual(mcDivider?.outer, [
    [0, 0],
    [570, 0],
    [570, 167.5],
    [577, 167.5],
    [577, 335],
    [-7, 335],
    [-7, 167.5],
    [0, 167.5],
    [0, 0],
  ]);
  const leftDoor = result.panels.find((panel) => panel.id === "middle_cabinet_left_door");
  assert.equal(leftDoor?.width, 282);
  assert.equal(leftDoor?.height, 466);
  assert.deepEqual(leftDoor?.placement, { x0: 1717, x1: 1999, y0: 450, y1: 465, z0: 317, z1: 783 });
  assert.deepEqual(leftDoor?.hingeHoles, [
    { id: "middle_cabinet_left_door_hinge_bottom", centerX: 22.5, centerY: 80, diameter: 35, depth: 12.5, face: "bottom" },
    { id: "middle_cabinet_left_door_hinge_top", centerX: 22.5, centerY: 386, diameter: 35, depth: 12.5, face: "bottom" },
  ]);
  assert.deepEqual(leftDoor?.lockCutouts, [{
    id: "middle_cabinet_left_door_lock",
    presetId: "razor_long_rounded_1",
    shape: "rounded_slot",
    centerX: 252,
    centerY: 437.5,
    width: 55,
    height: 15.5,
    radius: 7.75,
    through: true,
  }]);
  const rightDoor = result.panels.find((panel) => panel.id === "middle_cabinet_right_door");
  assert.deepEqual(rightDoor?.placement, { x0: 2001, x1: 2283, y0: 450, y1: 465, z0: 317, z1: 783 });
  assert.equal(rightDoor?.hingeHoles?.[0]?.centerX, 259.5);
  assert.equal(rightDoor?.lockCutouts?.[0]?.centerX, 30);
  const mcLeft = result.panels.find((panel) => panel.id === "middle_cabinet_left");
  assert.deepEqual(mcLeft?.grooves, [{ id: "middle_cabinet_left_groove", x0: 177.5, y0: 227, x1: 350, y1: 243, depth: 7.5, face: "top" }]);
  const mcRight = result.panels.find((panel) => panel.id === "middle_cabinet_right");
  assert.deepEqual(mcRight?.grooves, [{ id: "middle_cabinet_right_groove", x0: 177.5, y0: 227, x1: 350, y1: 243, depth: 7.5, face: "bottom" }]);
  const noLock = generateLoungeGeometry({
    style: "PARALLEL",
    hasMiddleCabinet: true,
    middleCabinet: { width: 600, depth: 350, height: 500, startHeight: 300, doorPanelThickness: 15, doorClearance: 2, doorLockStyle: "NONE" },
  });
  const noLockDoor = noLock.panels.find((panel) => panel.id === "middle_cabinet_left_door");
  assert.equal(noLockDoor?.lockCutouts?.length, 0);
  assert.equal(noLockDoor?.hingeHoles?.length, 2);
}

function testIShapeLounge(): void {
  const result = generateLoungeGeometry({
    style: "I_SHAPE",
    height: 420,
    partitionPanelThickness: 18,
    mainWidth: 2000,
    mainDepth: 600,
    topLidEnabled: true,
  });
  assert.equal(result.meta.style, "I_SHAPE");
  assert.equal(result.validation.errors.length, 0);
  assert.equal(result.validation.warnings.length, 0);
  assert.equal(result.panels.length, 4);
  assert.equal(result.openings.length, 1);
  assert.equal(result.lids.length, 1);
  assert.deepEqual(result.footprint.i, { x0: 0, x1: 2000, y0: 0, y1: 600 });
  const front = result.panels.find((panel) => panel.id === "i_front");
  assert.equal(front?.width, 2000);
  assert.deepEqual(front?.placement, { x0: 0, x1: 2000, y0: 582, y1: 600, z0: 0, z1: 402 });
  const left = result.panels.find((panel) => panel.id === "i_left_side");
  assert.deepEqual(left?.placement, { x0: 0, x1: 18, y0: 0, y1: 582, z0: 0, z1: 402 });
  assert.deepEqual(left?.outer, [[0, 0], [582, 0], [582, 402], [0, 402], [0, 0]]);
  const right = result.panels.find((panel) => panel.id === "i_right_side");
  assert.deepEqual(right?.placement, { x0: 1982, x1: 2000, y0: 0, y1: 582, z0: 0, z1: 402 });
  const top = result.panels.find((panel) => panel.id === "i_top");
  assert.deepEqual(top?.placement, { x0: 0, x1: 2000, y0: 0, y1: 600, z0: 402, z1: 420 });
  const opening = result.openings[0];
  assert.equal(opening.width, 1000);
  assert.equal(opening.depth, 300);
  const lid = result.lids[0];
  assert.equal(lid.id, "i_top_lid");
  assert.equal(lid.width, 997);
  assert.equal(lid.depth, 297);
  assert.equal(lid.fingerHole.diameter, 40);
}

function testIShapeLoungeWithAvoidance(): void {
  const result = generateLoungeGeometry({
    style: "I_SHAPE",
    height: 420,
    partitionPanelThickness: 18,
    wheelAvoidanceEnabled: true,
    mainWidth: 2000,
    mainDepth: 600,
    avoidanceDepth: 300,
    avoidanceHeight: 250,
    topLidEnabled: false,
  });
  assert.equal(result.validation.errors.length, 0);
  assert.equal(result.validation.warnings.length, 0);
  assert.equal(result.panels.length, 6);
  assert.equal(result.openings.length, 0);
  assert.equal(result.lids.length, 0);
  const left = result.panels.find((panel) => panel.id === "i_left_side");
  assert.deepEqual(left?.outer, [[300, 0], [582, 0], [582, 402], [0, 402], [0, 250], [300, 250], [300, 0]]);
  assert.equal(left?.note, "Rear-lower wheel avoidance cutout applied.");
  const right = result.panels.find((panel) => panel.id === "i_right_side");
  assert.deepEqual(right?.outer, [[300, 0], [582, 0], [582, 402], [0, 402], [0, 250], [300, 250], [300, 0]]);
  const avTop = result.panels.find((panel) => panel.id === "i_avoidance_top");
  assert.deepEqual(avTop?.placement, { x0: 0, x1: 2000, y0: 0, y1: 300, z0: 232, z1: 250 });
  const avFront = result.panels.find((panel) => panel.id === "i_avoidance_front");
  assert.deepEqual(avFront?.placement, { x0: 0, x1: 2000, y0: 282, y1: 300, z0: 0, z1: 232 });
}

function testIShapeWarnings(): void {
  const result = generateLoungeGeometry({
    style: "I_SHAPE",
    height: 420,
    partitionPanelThickness: 18,
    wheelAvoidanceEnabled: true,
    mainWidth: 2000,
    mainDepth: 600,
    avoidanceDepth: 700,
    avoidanceHeight: 500,
  });
  assert(result.validation.warnings.some((warning) => warning.includes("Avoidance Depth")));
  assert(result.validation.warnings.some((warning) => warning.includes("Avoidance Height")));
  assert(!result.panels.some((panel) => panel.id === "i_avoidance_top"));
}

testDefaultLShape();
testLeftPositionAndNoLid();
testParallelLounge();
testIShapeLounge();
testIShapeLoungeWithAvoidance();
testIShapeWarnings();
console.log("OK lounge generator tests");
