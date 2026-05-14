const assert = require("assert");
const {
  buildPureParams,
  buildBoardPlan,
  cabinetWidthFromFridge,
  formatBoardPlacementSummary,
  getV12Profile,
  getV34Profile,
  dumpBoardVector,
  verifyVSeriesVectors,
  pointExists,
} = require("../fridge_logic");

function baseUi(overrides = {}) {
  const exteriorSide = overrides.exteriorSide || "left";
  const fridgeWidth = overrides.fridgeWidth || 550;
  const wheelAvoidance = overrides.wheelAvoidance || {
    enabled: true,
    height: 200,
    depth: 300,
  };
  return {
    cabinet: {
      width: cabinetWidthFromFridge(fridgeWidth, exteriorSide),
      depth: 600,
      height: 2100,
      panelThickness: 15,
      exteriorSide,
    },
    fridge: {
      width: fridgeWidth,
      depth: 580,
      height: overrides.fridgeHeight || 1500,
    },
    clearances: {
      top: 50,
      bottom: 50,
    },
    wheelAvoidance,
    stack: overrides.stack,
  };
}

function pickPanel(panel) {
  return {
    id: panel.id,
    z0: panel.z0,
    z1: panel.z1,
    centerZ: panel.centerZ,
    lowerType: panel.lowerType,
    upperType: panel.upperType,
    role: panel.role,
    shape: panel.shape,
    requiresHSet: panel.requiresHSet,
  };
}

function assertPanels(actual, expected) {
  assert.deepStrictEqual(actual.map(pickPanel), expected);
}

function assertZi(actual, expected) {
  assert.deepStrictEqual(actual, expected);
}

function assertHPlanes(actual, expected) {
  assert.deepStrictEqual(actual, expected);
}

function boardIds(boardPlan) {
  return boardPlan.boards.map((b) => b.id);
}

function hasPoint2D(vec, x, y, eps) {
  const e = eps != null ? eps : 1e-6;
  return vec.some((p) => Math.abs(p[0] - x) < e && Math.abs(p[1] - y) < e);
}

function testA() {
  const params = buildPureParams(baseUi({
    stack: [
      { id: "s1", type: "flap", height: 190 },
      { id: "s2", type: "drawer", height: 250 },
      { id: "s3", type: "fridge", height: 1500 },
    ],
  }));
  const boardPlan = buildBoardPlan(params);
  const ids = boardIds(boardPlan);
  assert.strictEqual(boardPlan.validation.ok, true);
  assert.strictEqual(boardPlan.boards.length, 20);
  ["T1", "T2", "T3", "T4", "T5", "B1", "B2", "B3", "AvoidanceFront", "AvoidanceTop", "V5", "V1", "V2", "V3", "V4"].forEach((id) => {
    assert(ids.includes(id), `missing board ${id}`);
  });
  assert.strictEqual(boardPlan.boards.filter((b) => b.series === "Zi").length, 2);
  assert.strictEqual(boardPlan.boards.filter((b) => b.type === "blank_panel").length, 0);
  assert.strictEqual(boardPlan.boards.filter((b) => b.series === "H").length, 3);
  assert(boardPlan.boards.some((b) => b.id === "HSet_P2_H13" && b.type === "h13"));
  assert(boardPlan.boards.some((b) => b.id === "HSet_P2_H24" && b.type === "h24"));
  assert(boardPlan.boards.some((b) => b.id === "HSet_P2_H34" && b.type === "h34"));
  assert(boardPlan.boards.every((b) => typeof formatBoardPlacementSummary(b.placement) === "string"));

  assert.strictEqual(params.layout.totalStackHeight, 2100);
  assertPanels(params.layout.panels, [
    { id: "P0", z0: 50, z1: 65, centerZ: 57.5, lowerType: "bottomClearance", upperType: "flap", role: "bottom_boundary", shape: "bottom_system", requiresHSet: false },
    { id: "P1", z0: 255, z1: 270, centerZ: 262.5, lowerType: "flap", upperType: "drawer", role: "flap_top", shape: "half", requiresHSet: false },
    { id: "P2", z0: 520, z1: 535, centerZ: 527.5, lowerType: "drawer", upperType: "fridge", role: "fridge_base", shape: "full", requiresHSet: true },
    { id: "P3", z0: 2035, z1: 2050, centerZ: 2042.5, lowerType: "fridge", upperType: "topClearance", role: "top_boundary", shape: "top_system", requiresHSet: false },
  ]);
  assertZi(params.layout.ziList, [
    { id: "Z1", panelId: "P1", centerZ: 262.5, z0: 255, z1: 270, role: "flap_top", shape: "half", requiresHSet: false },
    { id: "Z2", panelId: "P2", centerZ: 527.5, z0: 520, z1: 535, role: "fridge_base", shape: "full", requiresHSet: true },
  ]);
  assert.strictEqual(params.avoidance.fridgeBaseBottomZ, 520);
  assert.strictEqual(params.avoidance.fridgeGap, 320);
  assert.strictEqual(params.avoidance.finalMode, "normal");
  assert.strictEqual(params.avoidance.finalTopZ, 200);
  assert.strictEqual(params.avoidance.finalFrontBoardHeight, 185);
  assertHPlanes(params.layout.hPlanes, [
    { id: "HSet_P2", sourcePanelId: "P2", sourceRole: "fridge_base", z0: 420, z1: 520, mode: "below_panel", members: ["H13", "H24", "H34"] },
  ]);
  assert.strictEqual(params.validation.ok, true);
  assert.deepStrictEqual(params.validation.errors, []);
  assert(params.validation.infos.includes("Fridge/avoidance gap >= 105 mm: below-fridge HSet will be used."));
}

function testB() {
  const params = buildPureParams(baseUi({
    stack: [
      { id: "s1", type: "drawer", height: 250 },
      { id: "s2", type: "flap", height: 190 },
      { id: "s3", type: "fridge", height: 1500 },
    ],
  }));
  assert.strictEqual(params.layout.totalStackHeight, 2100);
  assertPanels(params.layout.panels, [
    { id: "P0", z0: 50, z1: 65, centerZ: 57.5, lowerType: "bottomClearance", upperType: "drawer", role: "bottom_boundary", shape: "bottom_system", requiresHSet: false },
    { id: "P1", z0: 315, z1: 330, centerZ: 322.5, lowerType: "drawer", upperType: "flap", role: "flap_bottom", shape: "full", requiresHSet: true },
    { id: "P2", z0: 520, z1: 535, centerZ: 527.5, lowerType: "flap", upperType: "fridge", role: "fridge_base", shape: "full", requiresHSet: true },
    { id: "P3", z0: 2035, z1: 2050, centerZ: 2042.5, lowerType: "fridge", upperType: "topClearance", role: "top_boundary", shape: "top_system", requiresHSet: false },
  ]);
  assertZi(params.layout.ziList, [
    { id: "Z1", panelId: "P1", centerZ: 322.5, z0: 315, z1: 330, role: "flap_bottom", shape: "full", requiresHSet: true },
    { id: "Z2", panelId: "P2", centerZ: 527.5, z0: 520, z1: 535, role: "fridge_base", shape: "full", requiresHSet: true },
  ]);
  assertHPlanes(params.layout.hPlanes, [
    { id: "HSet_P1", sourcePanelId: "P1", sourceRole: "flap_bottom", z0: 215, z1: 315, mode: "below_panel", members: ["H13", "H24", "H34"] },
    { id: "HSet_P2", sourcePanelId: "P2", sourceRole: "fridge_base", z0: 420, z1: 520, mode: "below_panel", members: ["H13", "H24", "H34"] },
  ]);
  assert.strictEqual(params.avoidance.fridgeBaseBottomZ, 520);
  assert.strictEqual(params.avoidance.fridgeGap, 320);
  assert.strictEqual(params.avoidance.finalMode, "normal");
  assert.strictEqual(params.validation.ok, true);
  assert.deepStrictEqual(params.validation.errors, []);
}

function testC() {
  const params = buildPureParams(baseUi({
    stack: [
      { id: "s1", type: "fridge", height: 1500 },
      { id: "s2", type: "flap", height: 190 },
      { id: "s3", type: "drawer", height: 250 },
    ],
  }));
  assert.strictEqual(params.layout.totalStackHeight, 2100);
  assertPanels(params.layout.panels, [
    { id: "P0", z0: 50, z1: 65, centerZ: 57.5, lowerType: "bottomClearance", upperType: "fridge", role: "bottom_boundary", shape: "bottom_system", requiresHSet: false },
    { id: "P1", z0: 1565, z1: 1580, centerZ: 1572.5, lowerType: "fridge", upperType: "flap", role: "fridge_top", shape: "full", requiresHSet: true },
    { id: "P2", z0: 1770, z1: 1785, centerZ: 1777.5, lowerType: "flap", upperType: "drawer", role: "flap_top", shape: "half", requiresHSet: false },
    { id: "P3", z0: 2035, z1: 2050, centerZ: 2042.5, lowerType: "drawer", upperType: "topClearance", role: "top_boundary", shape: "top_system", requiresHSet: false },
  ]);
  assertZi(params.layout.ziList, [
    { id: "Z1", panelId: "P1", centerZ: 1572.5, z0: 1565, z1: 1580, role: "fridge_top", shape: "full", requiresHSet: true },
    { id: "Z2", panelId: "P2", centerZ: 1777.5, z0: 1770, z1: 1785, role: "flap_top", shape: "half", requiresHSet: false },
  ]);
  assert.strictEqual(params.validation.ok, false);
  assert(params.validation.errors.includes("No fridge_base panel found."));
}

function testD() {
  const params = buildPureParams(baseUi({
    stack: [
      { id: "s1", type: "drawer", height: 250 },
      { id: "s2", type: "flap", height: 150 },
      { id: "s3", type: "empty", height: 25 },
      { id: "s4", type: "fridge", height: 1500 },
    ],
  }));
  assert.strictEqual(params.layout.totalStackHeight, 2100);
  assertPanels(params.layout.panels, [
    { id: "P0", z0: 50, z1: 65, centerZ: 57.5, lowerType: "bottomClearance", upperType: "drawer", role: "bottom_boundary", shape: "bottom_system", requiresHSet: false },
    { id: "P1", z0: 315, z1: 330, centerZ: 322.5, lowerType: "drawer", upperType: "flap", role: "flap_bottom", shape: "full", requiresHSet: true },
    { id: "P2", z0: 480, z1: 495, centerZ: 487.5, lowerType: "flap", upperType: "blankPanel", role: "flap_top", shape: "half", requiresHSet: false },
    { id: "P3", z0: 520, z1: 535, centerZ: 527.5, lowerType: "blankPanel", upperType: "fridge", role: "fridge_base", shape: "full", requiresHSet: true },
    { id: "P4", z0: 2035, z1: 2050, centerZ: 2042.5, lowerType: "fridge", upperType: "topClearance", role: "top_boundary", shape: "top_system", requiresHSet: false },
  ]);
  assertZi(params.layout.ziList, [
    { id: "Z1", panelId: "P1", centerZ: 322.5, z0: 315, z1: 330, role: "flap_bottom", shape: "full", requiresHSet: true },
    { id: "Z2", panelId: "P2", centerZ: 487.5, z0: 480, z1: 495, role: "flap_top", shape: "half", requiresHSet: false },
    { id: "Z3", panelId: "P3", centerZ: 527.5, z0: 520, z1: 535, role: "fridge_base", shape: "full", requiresHSet: true },
  ]);
  assertHPlanes(params.layout.hPlanes, [
    { id: "HSet_P1", sourcePanelId: "P1", sourceRole: "flap_bottom", z0: 215, z1: 315, mode: "below_panel", members: ["H13", "H24", "H34"] },
    { id: "HSet_P3", sourcePanelId: "P3", sourceRole: "fridge_base", z0: 420, z1: 520, mode: "below_panel", members: ["H13", "H24", "H34"] },
  ]);
  assert.strictEqual(params.avoidance.fridgeBaseBottomZ, 520);
  assert.strictEqual(params.avoidance.fridgeGap, 320);
  assert.strictEqual(params.avoidance.finalMode, "normal");
  assert.strictEqual(params.validation.ok, true);
  assert.deepStrictEqual(params.validation.errors, []);
}

function testH() {
  const params = buildPureParams(baseUi({
    stack: [
      { id: "s1", type: "drawer", height: 250 },
      { id: "s2", type: "blankPanel", height: 25 },
      { id: "s3", type: "flap", height: 165 },
      { id: "s4", type: "fridge", height: 1500 },
    ],
  }));
  const boardPlan = buildBoardPlan(params);
  const blankBoard = boardPlan.boards.find((b) => b.id === "BlankPanel_s2");
  assert(blankBoard);
  assert.strictEqual(blankBoard.type, "blank_panel");
  assert.strictEqual(blankBoard.thickness, 16);
  assert.strictEqual(blankBoard.placement.widthX, 550);
  assert.strictEqual(blankBoard.placement.heightZ, 25);
  assert.deepStrictEqual(blankBoard.source, { sectionId: "s2", sectionType: "blankPanel" });

  assert.strictEqual(params.layout.sections[1].type, "blankPanel");
  assert.strictEqual(params.layout.sections[1].height, 25);
  assertPanels(params.layout.panels.slice(1, 4), [
    { id: "P1", z0: 315, z1: 330, centerZ: 322.5, lowerType: "drawer", upperType: "blankPanel", role: "generic_separator", shape: "half", requiresHSet: false },
    { id: "P2", z0: 355, z1: 370, centerZ: 362.5, lowerType: "blankPanel", upperType: "flap", role: "flap_bottom", shape: "full", requiresHSet: true },
    { id: "P3", z0: 535, z1: 550, centerZ: 542.5, lowerType: "flap", upperType: "fridge", role: "fridge_base", shape: "full", requiresHSet: true },
  ]);
  assert.strictEqual(params.layout.ziList[0].role, "generic_separator");
  assert.strictEqual(params.layout.ziList[1].role, "flap_bottom");
  assert.strictEqual(params.layout.ziList[2].role, "fridge_base");
}

function testE() {
  const params = buildPureParams(baseUi({
    fridgeHeight: 1875,
    wheelAvoidance: { enabled: true, height: 120, depth: 300 },
    stack: [
      { id: "s1", type: "flap", height: 80 },
      { id: "s2", type: "fridge", height: 1875 },
    ],
  }));
  assert.strictEqual(params.layout.totalStackHeight, 2100);
  assertPanels(params.layout.panels, [
    { id: "P0", z0: 50, z1: 65, centerZ: 57.5, lowerType: "bottomClearance", upperType: "flap", role: "bottom_boundary", shape: "bottom_system", requiresHSet: false },
    { id: "P1", z0: 145, z1: 160, centerZ: 152.5, lowerType: "flap", upperType: "fridge", role: "fridge_base", shape: "full", requiresHSet: true },
    { id: "P2", z0: 2035, z1: 2050, centerZ: 2042.5, lowerType: "fridge", upperType: "topClearance", role: "top_boundary", shape: "top_system", requiresHSet: false },
  ]);
  assert.strictEqual(params.avoidance.fridgeBaseBottomZ, 145);
  assert.strictEqual(params.avoidance.fridgeGap, 25);
  assert.strictEqual(params.avoidance.finalMode, "raised");
  assert.strictEqual(params.avoidance.finalTopZ, 145);
  assert.strictEqual(params.avoidance.finalFrontBoardHeight, 130);
  assertZi(params.layout.ziList, [
    { id: "Z1", panelId: "P1", centerZ: 152.5, z0: 145, z1: 160, role: "fridge_base", shape: "full", requiresHSet: true },
  ]);
  assertHPlanes(params.layout.hPlanes, [
    { id: "HSet_P1", sourcePanelId: "P1", sourceRole: "fridge_base", z0: 160, z1: 260, mode: "above_panel", members: ["H13", "H24", "H34"] },
  ]);
  assert.strictEqual(params.validation.ok, true);
  assert.deepStrictEqual(params.validation.errors, []);
  assert(params.validation.infos.includes("Fridge/avoidance gap < 105 mm: raised avoidance mode and above-fridge HSet will be used."));
}

function testF() {
  const params = buildPureParams(baseUi({
    fridgeHeight: 1875,
    wheelAvoidance: { enabled: true, height: 140, depth: 300 },
    stack: [
      { id: "s1", type: "flap", height: 80 },
      { id: "s2", type: "fridge", height: 1875 },
    ],
  }));
  assert.strictEqual(params.validation.ok, false);
  assert(params.validation.errors.includes("Fridge base panel bottom must be >= Avoidance Height + panel thickness."));
}

function testG() {
  const params = buildPureParams(baseUi({
    exteriorSide: "none",
    stack: [
      { id: "s1", type: "flap", height: 190 },
      { id: "s2", type: "drawer", height: 250 },
      { id: "s3", type: "fridge", height: 1500 },
    ],
  }));
  const boardPlan = buildBoardPlan(params);
  const ids = boardIds(boardPlan);
  assert.strictEqual(params.base.Cw, 595);
  assert.strictEqual(params.base.Cd, 600);
  assert.strictEqual(params.base.FCh, 2100);
  assert.strictEqual(params.base.Pt, 15);
  assert.strictEqual(params.base.exteriorSide, "none");
  assert.strictEqual(params.base.hasSidePanel, false);
  assert.strictEqual(params.base.sidePanelSide, "none");
  assert.strictEqual(params.base.hasV5, false);
  assert.strictEqual(params.base.v5Side, "none");
  assert.strictEqual(params.base.fridgeW, 550);
  assert.strictEqual(params.base.fridgeD, 580);
  assert.strictEqual(params.base.fridgeH, 1500);
  assert.strictEqual(params.layout.ziList[1].shape, "full");
  assert(!ids.includes("V5"), "exterior none must not emit V5 board");
  assert(ids.includes("AvoidanceFront") && ids.includes("AvoidanceTop"));
  assert(ids.includes("V1") && ids.includes("V2") && ids.includes("V3") && ids.includes("V4"));
}

function testBoardPlanInvalidPure() {
  const params = buildPureParams(baseUi({
    stack: [
      { id: "s1", type: "fridge", height: 1500 },
      { id: "s2", type: "flap", height: 190 },
      { id: "s3", type: "drawer", height: 250 },
    ],
  }));
  assert.strictEqual(params.validation.ok, false);
  const boardPlan = buildBoardPlan(params);
  assert.strictEqual(boardPlan.validation.ok, false);
  assert(boardPlan.validation.errors.length > 0);
  const ids = boardIds(boardPlan);
  assert(ids.includes("T1") && ids.includes("B1"));
  assert(boardPlan.boards.length >= 20);
}

function testBoardPlanCoreBoards() {
  const params = buildPureParams(baseUi({
    stack: [
      { id: "s1", type: "flap", height: 190 },
      { id: "s2", type: "drawer", height: 250 },
      { id: "s3", type: "fridge", height: 1500 },
    ],
  }));
  assert.strictEqual(params.validation.ok, true);
  const boardPlan = buildBoardPlan(params);
  const ids = boardIds(boardPlan);
  ["T1", "T2", "T3", "T4", "T5", "B1", "B2", "B3", "AvoidanceFront", "AvoidanceTop", "V1", "V2", "V3", "V4"].forEach((id) => {
    assert(ids.includes(id), `BoardPlanCoreBoards missing ${id}`);
  });
  assert(ids.some((id) => id.endsWith("_H13") && id.indexOf("HSet_") === 0));
  assert(ids.some((id) => id.endsWith("_H24")));
  assert(ids.some((id) => id.endsWith("_H34")));
  assert(ids.includes("V5"));
}

function testBoardPlanVSeriesExists() {
  const params = buildPureParams(baseUi({
    stack: [
      { id: "s1", type: "flap", height: 190 },
      { id: "s2", type: "drawer", height: 250 },
      { id: "s3", type: "fridge", height: 1500 },
    ],
  }));
  assert.strictEqual(params.validation.ok, true);
  const ids = boardIds(buildBoardPlan(params));
  ["V1", "V2", "V3", "V4"].forEach((id) => assert(ids.includes(id), `missing ${id}`));
}

function testV12IncludesAllZiSlots() {
  const params = buildPureParams(baseUi({
    stack: [
      { id: "s1", type: "flap", height: 190 },
      { id: "s2", type: "drawer", height: 250 },
      { id: "s3", type: "fridge", height: 1500 },
    ],
  }));
  const v1 = buildBoardPlan(params).boards.find((b) => b.id === "V1");
  assert(v1);
  const ov = v1.outerVector;
  assert(hasPoint2D(ov, 100, 262.5 - 8));
  assert(hasPoint2D(ov, 100, 262.5 + 8));
  assert(hasPoint2D(ov, 100, 527.5 - 8));
  assert(hasPoint2D(ov, 100, 527.5 + 8));
  const ref = getV12Profile(2000, [
    { centerZ: 500, shape: "half" },
    { centerZ: 1000, shape: "full" },
  ]);
  assert(hasPoint2D(ref, 150, 492));
  assert(hasPoint2D(ref, 100, 992));
}

function testV34IncludesOnlyFullSlots() {
  const params = buildPureParams(baseUi({
    stack: [
      { id: "s1", type: "flap", height: 190 },
      { id: "s2", type: "drawer", height: 250 },
      { id: "s3", type: "fridge", height: 1500 },
    ],
  }));
  const finalTop = params.avoidance.finalTopZ;
  assert.strictEqual(finalTop, 200);
  const v3 = buildBoardPlan(params).boards.find((b) => b.id === "V3");
  const ov = v3.outerVector;
  const halfLocalTop = 262.5 - finalTop + 8;
  assert(!hasPoint2D(ov, 50, halfLocalTop));
  const fullLocalTop = 527.5 - finalTop + 8;
  assert(hasPoint2D(ov, 50, fullLocalTop));
}

function testV34UsesFinalAvoidanceTop() {
  const params = buildPureParams(baseUi({
    fridgeHeight: 1875,
    wheelAvoidance: { enabled: true, height: 120, depth: 300 },
    stack: [
      { id: "s1", type: "flap", height: 80 },
      { id: "s2", type: "fridge", height: 1875 },
    ],
  }));
  assert.strictEqual(params.avoidance.finalMode, "raised");
  assert.strictEqual(params.avoidance.finalTopZ, 145);
  const V34h = 2100 - 145;
  assert.strictEqual(V34h, 1955);
  const v3 = buildBoardPlan(params).boards.find((b) => b.id === "V3");
  assert.strictEqual(v3.placement.height, V34h);
  assert.strictEqual(v3.source.finalAvoidanceTopZ, 145);
  const maxZ = Math.max.apply(null, v3.outerVector.map((p) => p[1]));
  assert.strictEqual(maxZ, V34h);
}

function testV34TopLSlot() {
  const params = buildPureParams(baseUi({
    fridgeHeight: 1875,
    wheelAvoidance: { enabled: true, height: 120, depth: 300 },
    stack: [
      { id: "s1", type: "flap", height: 80 },
      { id: "s2", type: "fridge", height: 1875 },
    ],
  }));
  const FCh = 2100;
  const finalTop = 145;
  const V34h = FCh - finalTop;
  const ov = getV34Profile(FCh, finalTop, params.layout.ziList);
  assert(hasPoint2D(ov, 150, V34h - 121));
  assert(hasPoint2D(ov, 134, V34h - 121));
  assert(hasPoint2D(ov, 134, V34h - 16));
  assert(hasPoint2D(ov, 45, V34h - 16));
  assert(hasPoint2D(ov, 45, V34h));
}

function uiVSeriesStandard() {
  return {
    cabinet: {
      width: cabinetWidthFromFridge(550, "right"),
      depth: 600,
      height: 2100,
      panelThickness: 15,
      exteriorSide: "right",
    },
    fridge: {
      width: 550,
      depth: 580,
      height: 1500,
    },
    clearances: {
      top: 50,
      bottom: 50,
    },
    wheelAvoidance: {
      enabled: true,
      height: 200,
      depth: 300,
    },
    stack: [
      { id: "s1", type: "flap", height: 190 },
      { id: "s2", type: "drawer", height: 250 },
      { id: "s3", type: "fridge", height: 1500 },
    ],
  };
}

function testVSeriesVerifyNormalCase() {
  const params = buildPureParams(uiVSeriesStandard());
  assert.strictEqual(params.validation.ok, true);
  const boardPlan = buildBoardPlan(params);
  const result = verifyVSeriesVectors(params, boardPlan);
  assert.strictEqual(result.ok, true, result.errors.join("; "));
}

function testV12IncludesHalfAndFullZi() {
  const params = buildPureParams(uiVSeriesStandard());
  const boardPlan = buildBoardPlan(params);
  const v1 = boardPlan.boards.find((b) => b.id === "V1");
  const half = params.layout.ziList.find((z) => z.shape === "half");
  const full = params.layout.ziList.find((z) => z.shape === "full");
  assert(half && full);
  const zh = half.centerZ;
  const zf = full.centerZ;
  [[150, zh - 8], [100, zh - 8], [100, zh + 8], [150, zh + 8]].forEach((pt) => {
    assert(pointExists(v1.outerVector, pt), `V1 missing half Zi slot point ${JSON.stringify(pt)}`);
  });
  [[150, zf - 8], [100, zf - 8], [100, zf + 8], [150, zf + 8]].forEach((pt) => {
    assert(pointExists(v1.outerVector, pt), `V1 missing full Zi slot point ${JSON.stringify(pt)}`);
  });
}

function testV34OnlyFullZi() {
  const params = buildPureParams(uiVSeriesStandard());
  const boardPlan = buildBoardPlan(params);
  const result = verifyVSeriesVectors(params, boardPlan);
  assert.strictEqual(result.ok, true);
  const v3 = boardPlan.boards.find((b) => b.id === "V3");
  const finalTop = params.avoidance.finalTopZ;
  const full = params.layout.ziList.find((z) => z.shape === "full");
  const half = params.layout.ziList.find((z) => z.shape === "half");
  const lzFull = full.centerZ - finalTop;
  assert(
    [[0, lzFull - 8], [50, lzFull - 8], [50, lzFull + 8], [0, lzFull + 8]].every((pt) => pointExists(v3.outerVector, pt)),
  );
  const lzHalf = half.centerZ - finalTop;
  const quad = [
    [0, lzHalf - 8],
    [50, lzHalf - 8],
    [50, lzHalf + 8],
    [0, lzHalf + 8],
  ];
  const allHalf = quad.every((pt) => pointExists(v3.outerVector, pt));
  assert(!allHalf, "V3 must not contain full half-Zi front slot quad");
}

function testV34UsesFinalAvoidanceTopRaised() {
  const params = buildPureParams({
    cabinet: {
      width: cabinetWidthFromFridge(550, "left"),
      depth: 600,
      height: 2100,
      panelThickness: 15,
      exteriorSide: "left",
    },
    fridge: { width: 550, depth: 580, height: 1875 },
    clearances: { top: 50, bottom: 50 },
    wheelAvoidance: { enabled: true, height: 120, depth: 300 },
    stack: [
      { id: "s1", type: "flap", height: 80 },
      { id: "s2", type: "fridge", height: 1875 },
    ],
  });
  assert.strictEqual(params.avoidance.finalMode, "raised");
  const boardPlan = buildBoardPlan(params);
  const result = verifyVSeriesVectors(params, boardPlan);
  assert.strictEqual(result.ok, true, result.errors.join("; "));
  const V34h = 2100 - params.avoidance.finalTopZ;
  assert.strictEqual(V34h, 1955);
  assert.strictEqual(params.avoidance.finalTopZ, 145);
}

function testDumpBoardVectorWorks() {
  const params = buildPureParams(uiVSeriesStandard());
  const boardPlan = buildBoardPlan(params);
  const dump = dumpBoardVector(boardPlan, "V1");
  assert.strictEqual(dump.id, "V1");
  assert(dump.pointCount > 4);
  assert.strictEqual(dump.isClosed, true);
  assert(dump.bbox.width > 0);
  assert(dump.bbox.height > 0);
}

const tests = [
  ["A", testA],
  ["B", testB],
  ["C", testC],
  ["D", testD],
  ["E", testE],
  ["F", testF],
  ["G", testG],
  ["H", testH],
  ["BoardPlanInvalid", testBoardPlanInvalidPure],
  ["BoardPlanCoreBoards", testBoardPlanCoreBoards],
  ["BoardPlanVSeriesExists", testBoardPlanVSeriesExists],
  ["V12IncludesAllZiSlots", testV12IncludesAllZiSlots],
  ["V34IncludesOnlyFullSlots", testV34IncludesOnlyFullSlots],
  ["V34UsesFinalAvoidanceTop", testV34UsesFinalAvoidanceTop],
  ["V34TopLSlot", testV34TopLSlot],
  ["VSeriesVerifyNormalCase", testVSeriesVerifyNormalCase],
  ["V12IncludesHalfAndFullZi", testV12IncludesHalfAndFullZi],
  ["V34OnlyFullZi", testV34OnlyFullZi],
  ["V34UsesFinalAvoidanceTopRaised", testV34UsesFinalAvoidanceTopRaised],
  ["DumpBoardVectorWorks", testDumpBoardVectorWorks],
];

for (const [name, test] of tests) {
  test();
  console.log(`TEST ${name}: PASS`);
}
