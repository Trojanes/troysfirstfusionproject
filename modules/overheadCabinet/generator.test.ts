import assert from "node:assert/strict";
import {
  calculateOverheadGeometry,
  generateOHCSvgPreview,
  generateOverheadCabinet,
} from "./generator.ts";

const baseParams = {
  style: "style_1",
  cabinetWidth: 2000,
  cabinetDepth: 400,
  cabinetHeight: 400,
  topClearanceHeight: 40,
  featureWidth: 15,
  frontPanelThickness: 16,
  clearance: 2.5,
  routerDiameter: 10,
  zones: [
    { id: "zone-1", type: "up_flap", width: 650 },
    { id: "zone-2", type: "fixed_panel", width: 750 },
    { id: "zone-3", type: "up_flap", width: 600 },
  ],
};

function testV7DividerCenterlinesFromZoneBoundaries() {
  const geometry = calculateOverheadGeometry(baseParams);
  assert.deepEqual(
    geometry.divider_features.map((feature) => feature.XDi),
    [7.5, 650, 1400, 1992.5],
  );
}

function testV7ManufacturingRules() {
  const geometry = calculateOverheadGeometry(baseParams);
  assert.equal(geometry.manufacturing.FGw, 15);
  assert.equal(geometry.manufacturing.FPt, 16);
  assert.equal(geometry.manufacturing.TCH, 40);
  assert.equal(geometry.manufacturing.FZH, 360);
  assert.equal(geometry.manufacturing.FeatureSlotWidth, 16);
  assert.equal(geometry.manufacturing.Dntg_h, 7);
  assert.equal(geometry.bottom_panel.size[2], 15);
}

function testV7GroovesUseSlotWidthAndClampEdges() {
  const geometry = calculateOverheadGeometry(baseParams);
  const features = geometry.divider_features;
  assert.deepEqual(features[0]?.bp_groove.x, [0, 15.5]);
  assert.deepEqual(features[1]?.bp_groove.x, [642, 658]);
  assert.deepEqual(features.at(-1)?.bp_groove.x, [1984.5, 2000]);
  assert.deepEqual(features[0]?.bp_groove.z, [0, -7.5]);
  assert.deepEqual(features[0]?.divider_tongue.y, [138.33333333333334, 261.6666666666667]);
  assert.equal(features[0]?.divider_tongue.length_y, 400 / 3 - 10);
  assert.deepEqual(features[0]?.divider_tongue.z, [-7, 0]);
}

function testV7DividerSideProfileStyle1() {
  const geometry = calculateOverheadGeometry(baseParams);
  assert.deepEqual(geometry.trimmed_vectors.DividerSide.slice(5, 14), [
    [400, 0],
    [400, 350],
    [384, 350],
    [384, 385],
    [70, 385],
    [70, 345],
    [80, 345],
    [80, 329],
    [0, 329],
  ]);
}

function testV7DividerSideProfileStyle2() {
  const geometry = calculateOverheadGeometry({ ...baseParams, style: "style_2" });
  assert.deepEqual(geometry.trimmed_vectors.DividerSide.slice(8, 13), [
    [384, 385],
    [31, 385],
    [31, 345],
    [80, 345],
    [80, 329],
  ]);
}

function testV7FrontPanelsAndHingeHoles() {
  const geometry = calculateOverheadGeometry(baseParams);
  assert.equal(geometry.front_panels.length, 3);
  assert.deepEqual(geometry.front_panels[0]?.opening.x, [15, 642.5]);
  assert.deepEqual(geometry.front_panels[0]?.x, [2.5, 648.75]);
  assert.deepEqual(geometry.front_panels[0]?.z, [-30, 359]);
  assert.equal(geometry.front_panels[0]?.width, 646.25);
  assert.equal(geometry.front_panels[0]?.height, 389);
  assert.equal(geometry.hinge_holes.length, 4);
  assert.deepEqual(geometry.hinge_holes[0]?.center, [100, 366.5]);
  assert.deepEqual(geometry.hinge_holes[1]?.center, [546.25, 366.5]);
}

function testFrontPanelXUsesOuterAndSharedClearance() {
  const geometry = calculateOverheadGeometry({
    ...baseParams,
    clearance: 4,
    zones: [
      { id: "zone-1", type: "up_flap", width: 1000 },
      { id: "zone-2", type: "up_flap", width: 1000 },
    ],
  });
  assert.deepEqual(geometry.front_panels[0]?.x, [4, 998]);
  assert.deepEqual(geometry.front_panels[1]?.x, [1002, 1996]);

  const threeZoneGeometry = calculateOverheadGeometry({
    ...baseParams,
    cabinetWidth: 1500,
    clearance: 4,
    zones: [
      { id: "zone-1", type: "up_flap", width: 500 },
      { id: "zone-2", type: "fixed_panel", width: 500 },
      { id: "zone-3", type: "up_flap", width: 500 },
    ],
  });
  assert.deepEqual(threeZoneGeometry.front_panels[0]?.x, [4, 498]);
  assert.deepEqual(threeZoneGeometry.front_panels[1]?.x, [502, 998]);
  assert.deepEqual(threeZoneGeometry.front_panels[2]?.x, [1002, 1496]);
}

function testOpenZoneDoesNotShiftFollowingPanelDividerIndices() {
  const geometry = calculateOverheadGeometry({
    ...baseParams,
    cabinetWidth: 1500,
    zones: [
      { id: "open", type: "open", width: 500 },
      { id: "rangehood", type: "rangehood_flap", width: 1000 },
    ],
  });
  assert.equal(geometry.front_panels.length, 1);
  assert.equal(geometry.front_panels[0]?.zoneIndex, 1);
  assert.deepEqual(geometry.front_panels[0]?.opening.x, [507.5, 1485]);
}

function testDividerZBaseSitsOnShiftedBottomPanel() {
  const result = generateOverheadCabinet({
    cabinetWidth: 994,
    cabinetDepth: 250,
    cabinetHeight: 250,
    featureWidth: 15,
    topClearanceHeight: 40,
    zones: [
      { id: "zone-1", type: "up_flap", width: 497 },
      { id: "zone-2", type: "up_flap", width: 497 },
    ],
  });
  const divider = result.boards.find((board) => board.id === "D1");
  assert.ok(divider, "expected internal divider D1");
  assert.equal(divider.z0, 30);
  assert.equal(divider.z1, 265);
  // Solid board thickness must equal CPT (featureWidth), not groove slot width.
  assert.equal(divider.materialThickness, 15);
  assert.equal(divider.x1 - divider.x0, 15);
}

function testDividerBoardThicknessUsesCptNotGrooveSlot() {
  const result = generateOverheadCabinet(baseParams);
  const dividers = result.boards.filter((board) => String(board.category) === "divider");
  assert.ok(dividers.length >= 2, "expected edge + internal dividers");
  for (const divider of dividers) {
    assert.equal(divider.materialThickness, 15, `${divider.id} materialThickness`);
    assert.equal(divider.x1 - divider.x0, 15, `${divider.id} solid X span must be CPT`);
  }
  // Groove features remain CPT + clearance (16 mm) for machining clearance.
  const geometry = calculateOverheadGeometry(baseParams);
  assert.equal(geometry.manufacturing.FeatureSlotWidth, 16);
  assert.deepEqual(geometry.divider_features[1]?.bp_groove.x, [642, 658]);
}

function testGenerateOverheadCabinetBoardsAndFeatures() {
  const result = generateOverheadCabinet(baseParams);
  assert.equal(result.validation.errors.length, 0);
  assert.equal(result.debug.phase, "geometry_v1");
  assert.deepEqual(result.debug.dividerCenterlines, [7.5, 650, 1400, 1992.5]);
  const boardIds = new Set(result.boards.map((board) => board.id));
  ["BP", "T1", "T2", "T3", "T4", "D0", "D1", "D2", "D3", "FP0", "FP1", "FP2"].forEach((id) => {
    assert.ok(boardIds.has(id), `expected board ${id}`);
  });
  assert.equal(result.features.length, 12);
  const led = result.features.find((feature) => feature && feature.type === "t3_groove" && feature.targetBoardId === "T3");
  assert.ok(led, "expected T3 LED groove feature");
  assert.equal(led.face, "top");
  assert.equal(led.depth, 6.5);
  assert.equal(led.width, 14.5);
  assert.equal(led.branches?.length, 2);
  const t3 = result.boards.find((board) => board.id === "T3");
  assert.ok(t3?.notes?.some((note) => /LED groove/i.test(note)));
  const fp0 = result.boards.find((board) => board.id === "FP0");
  assert.deepEqual(fp0?.profileVector, [
    { x: 0, z: 0 },
    { x: 646.25, z: 0 },
    { x: 646.25, z: 389 },
    { x: 0, z: 389 },
    { x: 0, z: 0 },
  ]);
  assert.ok(result.debug.svgPreview?.includes("OHC front elevation geometry preview"));
}

function testRelationshipDeclarationsEmbeddedInResult() {
  const result = generateOverheadCabinet({
    cabinetWidth: 900,
    cabinetDepth: 350,
    cabinetHeight: 720,
    zones: [{ id: "zone-1", type: "up_flap", width: 900 }],
  });
  assert.equal(result.relationshipDeclarations.length, 4);
  const ids = new Set(result.relationshipDeclarations.map((item) => item.declarationId));
  assert.ok(ids.has("oh_bp_d0_back_to_divider"));
  assert.ok(ids.has("oh_t1_t2_top_rail_stack"));
}

function testSvgPreviewUsesResolvedGeometry() {
  const geometry = calculateOverheadGeometry(baseParams);
  const svg = generateOHCSvgPreview(geometry, { selectedZoneIndex: 1 });
  assert.ok(svg.includes("BP 15 mm"));
  assert.ok(svg.includes("T1/T2 / TCH 40"));
  assert.ok(svg.includes("D1 15 mm"));
  assert.ok(svg.includes("FP0"));
  assert.ok(svg.includes("opening 627.5 mm"));
  assert.ok(svg.includes("<circle"));
}

function testInvalidWidthReportsError() {
  const result = generateOverheadCabinet({
    cabinetWidth: 0,
    cabinetDepth: 350,
  });
  assert.ok(result.validation.errors.some((error) => error.includes("cabinetWidth")));
  assert.equal(result.boards.length, 0);
}

function testT3LedGrooveOption() {
  const on = generateOverheadCabinet(baseParams);
  const onLed = on.features.filter((feature) => feature && feature.type === "t3_groove" && feature.targetBoardId === "T3");
  assert.equal(onLed.length, 1);
  assert.equal(onLed[0].face, "top");
  // Front land 18 mm → centerline 25.25 (= 20 + (18 - 12.75)).
  assert.equal(onLed[0].frontLand, 18);
  assert.equal(onLed[0].frontOffset, 18 + 14.5 / 2);
  assert.equal(onLed[0].main.y0, 18);
  assert.equal(onLed[0].main.y1, 18 + 14.5);
  assert.equal(onLed[0].branches[0].y1, 90);

  const off = generateOverheadCabinet({ ...baseParams, ledGroove: false });
  assert.equal(
    off.features.filter((feature) => feature && (feature.type === "t3_groove" || feature.type === "b3_groove")).length,
    0,
  );

  const style2 = generateOverheadCabinet({ ...baseParams, style: "style_2" });
  assert.equal(
    style2.features.filter((feature) => feature && feature.type === "t3_groove" && feature.targetBoardId === "T3").length,
    1,
    "Style 2 still has T3, so LED remains available when checkbox is on",
  );
}

function testNceSingleRangehoodZoneGeometry() {
  const result = generateOverheadCabinet({
    cabinetWidth: 1000,
    cabinetDepth: 400,
    cabinetHeight: 400,
    featureWidth: 15,
    topClearanceHeight: 40,
    rangehoodPreset: "NCE",
    rangehoodClearHeight: 75,
    rangehoodAlignment: "left",
    rangehoodEdgeOffsetX: 40,
    zones: [{ id: "rangehood", type: "rangehood_flap", width: 1000 }],
  });
  assert.deepEqual(result.validation.errors, []);
  const byId = new Map(result.boards.map((board) => [board.id, board]));
  const top = byId.get("RGHD_TOP");
  const front = byId.get("RGHD_FRONT");
  const back = byId.get("RGHD_BACK");
  assert.ok(top && front && back);
  assert.deepEqual([top.x0, top.x1, top.y0, top.y1, top.z0, top.z1], [8, 992, 0, 400, 105, 120]);
  assert.deepEqual([front.x0, front.x1, front.y0, front.y1, front.z0, front.z1], [15, 985, 0, 15, 30, 105]);
  assert.deepEqual([back.x0, back.x1, back.y0, back.y1, back.z0, back.z1], [15, 985, 385, 400, 30, 105]);
  const cutout = result.features.find((feature) => feature?.type === "rangehood_bp_cutout");
  assert.deepEqual(cutout?.x, [55, 610]);
  assert.deepEqual(cutout?.y, [57.5, 342.5]);
  const sideGrooves = result.features.filter((feature) => feature?.type === "rangehood_divider_side_groove");
  assert.equal(sideGrooves.length, 2);
  assert.deepEqual(sideGrooves[0]?.z, [105, 121]);
  assert.equal(result.features.filter((feature) => feature?.purpose === "hinge").length, 2);
}

function testAdjacentRangehoodZonesMergeAndMoveInternalDivider() {
  const result = generateOverheadCabinet({
    cabinetWidth: 1000,
    cabinetDepth: 400,
    cabinetHeight: 400,
    featureWidth: 15,
    topClearanceHeight: 40,
    rangehoodAlignment: "right",
    rangehoodEdgeOffsetX: 40,
    zones: [
      { id: "rangehood-left", type: "rangehood_flap", width: 500 },
      { id: "rangehood-right", type: "rangehood_flap", width: 500 },
    ],
  });
  assert.deepEqual(result.validation.errors, []);
  assert.equal(result.boards.filter((board) => board.id.startsWith("RGHD_")).length, 3);
  const middleDivider = result.boards.find((board) => board.id === "D1");
  assert.ok(middleDivider);
  assert.equal(middleDivider.z0, 120);
  assert.ok(middleDivider.notes?.some((note) => note.includes("BP groove suppressed")));
  const d1Feature = result.features.find((feature) => feature?.id === "D1");
  assert.equal(d1Feature?.bp_groove, undefined);
  const topGroove = result.features.find((feature) => feature?.type === "rangehood_top_divider_groove");
  assert.deepEqual(topGroove?.x, [492, 508]);
  assert.deepEqual(topGroove?.y, [400 / 3, 800 / 3]);
  const cutout = result.features.find((feature) => feature?.type === "rangehood_bp_cutout");
  assert.deepEqual(cutout?.x, [390, 945]);
  assert.equal(result.features.filter((feature) => feature?.purpose === "hinge").length, 4);
}

function testRangehoodValidation() {
  const exactMinimum = generateOverheadCabinet({
    cabinetWidth: 665, // Edge D inner faces are x=15 and x=650: exactly 635 clear.
    cabinetDepth: 365,
    cabinetHeight: 400,
    featureWidth: 15,
    rangehoodEdgeOffsetX: 40,
    zones: [{ type: "rangehood_flap", width: 665 }],
  });
  assert.deepEqual(exactMinimum.validation.errors, []);

  const exactMaximumHeight = generateOverheadCabinet({
    cabinetWidth: 1000,
    cabinetDepth: 400,
    cabinetHeight: 400,
    topClearanceHeight: 40,
    featureWidth: 15,
    rangehoodClearHeight: 315, // Ch - TCH - 3*CPT
    zones: [{ type: "rangehood_flap", width: 1000 }],
  });
  assert.deepEqual(exactMaximumHeight.validation.errors, []);
  const tooTall = generateOverheadCabinet({
    cabinetWidth: 1000,
    cabinetDepth: 400,
    cabinetHeight: 400,
    topClearanceHeight: 40,
    featureWidth: 15,
    rangehoodClearHeight: 316,
    zones: [{ type: "rangehood_flap", width: 1000 }],
  });
  assert.ok(tooTall.validation.errors.some((error) => error.includes("top-clearance")));

  const shallow = generateOverheadCabinet({
    cabinetWidth: 700,
    cabinetDepth: 360,
    cabinetHeight: 400,
    featureWidth: 15,
    zones: [{ type: "rangehood_flap", width: 700 }],
  });
  assert.ok(shallow.validation.errors.some((error) => error.includes("BP depth >= 365")));

  const nonContiguous = generateOverheadCabinet({
    cabinetWidth: 1800,
    cabinetDepth: 400,
    cabinetHeight: 400,
    featureWidth: 15,
    zones: [
      { type: "rangehood_flap", width: 700 },
      { type: "up_flap", width: 400 },
      { type: "rangehood_flap", width: 700 },
    ],
  });
  assert.ok(nonContiguous.validation.errors.some((error) => error.includes("one contiguous rangehood group")));
}

const tests = [
  testV7DividerCenterlinesFromZoneBoundaries,
  testV7ManufacturingRules,
  testV7GroovesUseSlotWidthAndClampEdges,
  testV7DividerSideProfileStyle1,
  testV7DividerSideProfileStyle2,
  testV7FrontPanelsAndHingeHoles,
  testFrontPanelXUsesOuterAndSharedClearance,
  testOpenZoneDoesNotShiftFollowingPanelDividerIndices,
  testDividerZBaseSitsOnShiftedBottomPanel,
  testDividerBoardThicknessUsesCptNotGrooveSlot,
  testGenerateOverheadCabinetBoardsAndFeatures,
  testRelationshipDeclarationsEmbeddedInResult,
  testSvgPreviewUsesResolvedGeometry,
  testInvalidWidthReportsError,
  testT3LedGrooveOption,
  testNceSingleRangehoodZoneGeometry,
  testAdjacentRangehoodZonesMergeAndMoveInternalDivider,
  testRangehoodValidation,
];

for (const test of tests) {
  test();
  console.log(`TEST ${test.name}: PASS`);
}
