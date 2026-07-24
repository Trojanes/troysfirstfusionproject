import assert from "node:assert/strict";
import { generateGeneralTallCabinet } from "./generator.ts";
import type { FunctionalZone, GeneralTallCabinetResult, GeneralTallCabinetParams } from "./types.ts";

function zone(id: string, type: FunctionalZone["type"], height: number): FunctionalZone {
  return { id, type, height };
}

function baseParams(zones: FunctionalZone[]): GeneralTallCabinetParams {
  return {
    cabinetHeight: 2100,
    cabinetWidth: 700,
    cabinetDepth: 600,
    panelThickness: 16,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    frontFaceAllowance: 16,
    ziThickness: 15,
    hThickness: 15,
    sideClearance: 3,
    doorPanelThickness: 16,
    dividerThickness: 15,
    topSystem: { style: "style_1", frontRailHeight: 40, insertSlotThickness: 16 },
    bottomSystem: { style: "style_1", frontRailHeight: 53, insertSlotThickness: 16 },
    zones,
  };
}

function style1ExactFitParams(): GeneralTallCabinetParams {
  return baseParams([
    zone("side", "side_door", 600),
    zone("drawer-a", "drawer", 300),
    zone("drawer-b", "drawer", 300),
    zone("blank", "blank_panel", 400),
    zone("open", "open_space", 330),
  ]);
}

function boardTypes(result: GeneralTallCabinetResult): string[] {
  return result.boards.map((board) => board.boardType);
}

function featureTypes(result: GeneralTallCabinetResult): string[] {
  return result.features.map((feature) => feature.type);
}

function boundaryBoards(result: GeneralTallCabinetResult) {
  return result.boards.filter((board) => board.category === "boundary_panel");
}

function vBoards(result: GeneralTallCabinetResult) {
  return result.boards.filter((board) => ["V1", "V2", "V3", "V4"].includes(board.id));
}

function validationMessages(result: GeneralTallCabinetResult): string[] {
  return [...result.validation.errors, ...result.validation.warnings];
}

function testV1ScopeRegression() {
  const allowedBoardTypes = new Set([
    "V1",
    "V2",
    "V3",
    "V4",
    "T1",
    "T2",
    "T3",
    "T4",
    "T5",
    "TH1",
    "BH1",
    "B1",
    "B2",
    "B3",
    "top_system_placeholder",
    "bottom_system_placeholder",
    "style2_fixed_front_panel",
    "full_zi",
    "half_zi",
    "shortened_zi",
    "H12",
    "H13",
    "H24",
    "H34",
    "vertical_divider",
    "side_panel",
    "avoidance_horizontal",
    "avoidance_vertical",
  ]);
  const disallowedBoardTypes = [
    "door_panel",
    "drawer_front",
    "flap_front",
    "blank_front_panel",
    "drawer_box",
    "hinge_hole",
    "lock_cutout",
    "slide_hole",
    "toolpath",
    "nesting",
  ];
  const cases = [
    generateGeneralTallCabinet(style1ExactFitParams()),
    generateGeneralTallCabinet({
      ...style1ExactFitParams(),
      topSystem: { style: "style_2", height: 80 },
      bottomSystem: { style: "style_2", height: 100 },
    }),
    generateGeneralTallCabinet({
      ...baseParams([
        zone("side", "side_door", 600),
        { ...zone("double", "double_door", 600), verticalDivider: true },
        zone("drawer", "drawer", 400),
        zone("open", "open_space", 390),
      ]),
      avoidance: { enabled: true, depth: 200, height: 2000 },
    }),
  ];

  for (const result of cases) {
    for (const type of boardTypes(result)) {
      assert(allowedBoardTypes.has(type), `unexpected boardType ${type}`);
    }
    for (const type of disallowedBoardTypes) {
      assert(!boardTypes(result).includes(type), `disallowed boardType ${type}`);
    }
  }
}

function testFeatureTypeRegression() {
  const allowedFeatureTypes = new Set([
    "zi_slot",
    "zi_groove",
    "h34_clearance_slot",
    "b3_groove",
    "t3_groove",
    "divider_tongue",
  ]);
  const disallowedFeatureTypes = ["hinge_hole", "lock_cutout", "drawer_slide_hole", "dogbone", "cnc_operation", "toolpath"];
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("side", "side_door", 600),
      { ...zone("double", "double_door", 600), verticalDivider: true },
      zone("drawer", "drawer", 400),
      zone("open", "open_space", 390),
    ]),
  );

  for (const type of featureTypes(result)) {
    assert(allowedFeatureTypes.has(type), `unexpected feature type ${type}`);
  }
  for (const type of disallowedFeatureTypes) {
    assert(!featureTypes(result).includes(type), `disallowed feature type ${type}`);
  }
}

function testStyle1FullSkeletonRegression() {
  const result = generateGeneralTallCabinet(style1ExactFitParams());
  const types = boardTypes(result);

  ["T1", "T2", "T3", "B1", "B2", "B3"].forEach((type) => assert(types.includes(type), `missing ${type}`));
  assert(!types.includes("top_system_placeholder"));
  assert(!types.includes("bottom_system_placeholder"));
  assert.equal(boundaryBoards(result).length, 3);
  assert.equal(result.boards.filter((board) => board.boardType === "H12").length, 2);
  assert.equal(result.boards.filter((board) => board.category === "h_support").length, 8);

  for (const board of vBoards(result)) {
    assert(board.profileVector, `${board.id} missing profileVector`);
    if (board.id === "V1" || board.id === "V2") {
      assert.equal(board.profileFeatures?.filter((feature) => feature.type === "style1_top_insert_slot").length, 1);
      assert.equal(board.profileFeatures?.filter((feature) => feature.type === "style1_bottom_insert_slot").length, 1);
      assert.equal(board.profileFeatures?.filter((feature) => feature.type === "zi_slot").length, 3);
    } else {
      assert.equal(board.profileFeatures?.filter((feature) => feature.type === "style1_top_insert_slot").length, 0);
      assert.equal(board.profileFeatures?.filter((feature) => feature.type === "style1_bottom_insert_slot").length, 0);
      assert.equal(board.profileFeatures?.filter((feature) => feature.type === "zi_slot").length, 2);
      assert(board.notes?.includes("Style 1 rear-stile profile implemented; rear top/bottom L-slot refinements deferred."));
    }
  }
}

function testStyle2Regression() {
  const result = generateGeneralTallCabinet({
    ...style1ExactFitParams(),
    topSystem: { style: "style_2", height: 80 },
    bottomSystem: { style: "style_2", height: 100 },
  });
  const style2Panels = result.boards.filter((board) => board.boardType === "style2_fixed_front_panel");

  assert.equal(style2Panels.length, 2);
  assert(style2Panels.every((board) => board.boardType !== "H12"));
  assert(result.boards.filter((board) => board.boardType === "H12").every((board) => board.source === "blank"));
  assert(!boardTypes(result).includes("top_system_placeholder"));
  assert(!boardTypes(result).includes("bottom_system_placeholder"));
  assert(boardTypes(result).includes("TH1"));
  assert(boardTypes(result).includes("BH1"));
  for (const board of vBoards(result)) {
    assert(board.profileVector, `${board.id} missing profileVector`);
    if (board.id === "V1" || board.id === "V2") {
      assert.equal(board.profileFeatures?.filter((feature) => feature.type === "style1_top_insert_slot").length, 1);
      assert.equal(board.profileFeatures?.filter((feature) => feature.type === "style1_bottom_insert_slot").length, 1);
    } else {
      assert.equal(board.profileFeatures?.filter((feature) => feature.type === "style1_top_insert_slot").length, 0);
      assert.equal(board.profileFeatures?.filter((feature) => feature.type === "style1_bottom_insert_slot").length, 0);
    }
  }
}

function testVerticalDividerRegression() {
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("side", "side_door", 600),
      { ...zone("double", "double_door", 600), verticalDivider: true },
      zone("drawer", "drawer", 400),
      zone("open", "open_space", 390),
    ]),
  );
  const divider = result.boards.find((board) => board.boardType === "vertical_divider");
  const boardById = new Map(result.boards.map((board) => [board.id, board]));

  assert(divider, "missing vertical_divider board");
  assert.equal(boundaryBoards(result).find((board) => board.source === "boundary-side-double")?.boardType, "full_zi");
  assert.equal(boundaryBoards(result).find((board) => board.source === "boundary-double-drawer")?.boardType, "full_zi");
  assert(result.features.filter((feature) => feature.type === "zi_groove").every((feature) => {
    const target = boardById.get(feature.targetBoardId);
    return target?.boardType === "full_zi";
  }));
  assert(result.features.filter((feature) => feature.type === "h34_clearance_slot").every((feature) => {
    const target = boardById.get(feature.targetBoardId);
    const h34Board = boardById.get(feature.h34BoardId);
    const isRearClearanceSource = h34Board?.boardType === "H34" || h34Board?.boardType === "T5";
    return target?.boardType === "vertical_divider" && isRearClearanceSource && target.id !== h34Board?.id;
  }));
}

function testAvoidanceShortenedZiRegression() {
  const result = generateGeneralTallCabinet({
    ...style1ExactFitParams(),
    avoidance: { enabled: true, depth: 200, height: 1400 },
  });
  const shortened = boundaryBoards(result).filter((board) => board.boardType === "shortened_zi");
  const half = boundaryBoards(result).filter((board) => board.boardType === "half_zi");
  const shortDepth = result.debug.midDepth - 200;

  assert.equal(shortened.length, 2);
  assert.equal(half.length, 1);
  assert(shortened.every((board) => board.y0 === 0 && board.y1 === shortDepth));
  assert(result.features.filter(
    (feature) =>
      feature.type === "zi_slot" &&
      feature.boundaryType === "shortened_zi" &&
      (feature.targetBoardId === "V1" || feature.targetBoardId === "V2"),
  ).every((feature) => feature.y0 === 100 && feature.y1 === 150));
  assert(result.features.filter(
    (feature) =>
      feature.type === "zi_slot" &&
      feature.boundaryType === "shortened_zi" &&
      (feature.targetBoardId === "V3" || feature.targetBoardId === "V4"),
  ).every(
    (feature) => feature.y0 === shortDepth - 50 && feature.y1 === shortDepth,
  ));

  const dividerResult = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      { ...zone("double", "double_door", 600), verticalDivider: true },
      zone("drawer", "drawer", 400),
      zone("open", "open_space", 390),
    ]),
    avoidance: { enabled: true, depth: 200, height: 2000 },
  });
  assert.equal(boundaryBoards(dividerResult).find((board) => board.source === "boundary-side-double")?.boardType, "full_zi");
  assert.equal(boundaryBoards(dividerResult).find((board) => board.source === "boundary-double-drawer")?.boardType, "full_zi");
}

function testValidationRegression() {
  const heightMismatch = generateGeneralTallCabinet({
    ...style1ExactFitParams(),
    zones: [
      zone("side", "side_door", 600),
      zone("drawer-a", "drawer", 300),
      zone("drawer-b", "drawer", 300),
      zone("blank", "blank_panel", 400),
      zone("open", "open_space", 300),
    ],
  });
  assert(validationMessages(heightMismatch).some((message) => message.includes("Height mismatch")));
  assert(heightMismatch.boards.length > 0);

  const invalidDivider = generateGeneralTallCabinet(
    baseParams([{ ...zone("double", "double_door", 1975), verticalDivider: true, dividerCenterX: 3 }]),
  );
  assert(validationMessages(invalidDivider).some((message) => message.includes("outside MidWidth")));
  assert(invalidDivider.boards.length > 0);

  const invalidAvoidance = generateGeneralTallCabinet({
    ...baseParams([zone("side", "side_door", 600), zone("drawer", "drawer", 500), zone("open", "open_space", 900)]),
    avoidance: { enabled: true, depth: 700 },
  });
  assert(validationMessages(invalidAvoidance).some((message) => message.includes("Avoidance ShortDepth")));
  assert(invalidAvoidance.boards.length > 0);

  const invalidTopFlap = generateGeneralTallCabinet(
    baseParams([zone("open", "open_space", 800), zone("top", "top_flap", 500), zone("drawer", "drawer", 645)]),
  );
  assert(validationMessages(invalidTopFlap).some((message) => message.toLowerCase().includes("top flap")));

  const invalidBottomFlap = generateGeneralTallCabinet(
    baseParams([zone("open", "open_space", 1000), zone("bottom", "bottom_flap", 975)]),
  );
  assert(validationMessages(invalidBottomFlap).some((message) => message.toLowerCase().includes("bottom flap")));
}

function testNamingContractRegression() {
  const result = generateGeneralTallCabinet(style1ExactFitParams());
  ["V1", "V2", "V3", "V4"].forEach((id) => {
    const board = result.boards.find((candidate) => candidate.id === id);
    assert(board, `missing ${id}`);
    assert.equal(board.boardType, id);
  });
  assert(result.boards.filter((board) => board.id.startsWith("H12_")).every((board) => board.boardType === "H12"));
  assert(result.boards.filter((board) => board.id.startsWith("H13_")).every((board) => board.boardType === "H13"));
  assert(result.boards.filter((board) => board.id.startsWith("H24_")).every((board) => board.boardType === "H24"));
  assert(result.boards.filter((board) => board.id.startsWith("H34_")).every((board) => board.boardType === "H34"));
  assert(!boardTypes(result).includes("h12"));
  assert(!boardTypes(result).includes("front_vertical"));
  assert(!boardTypes(result).includes("rear_vertical_placeholder"));
}

const tests = [
  testV1ScopeRegression,
  testFeatureTypeRegression,
  testStyle1FullSkeletonRegression,
  testStyle2Regression,
  testVerticalDividerRegression,
  testAvoidanceShortenedZiRegression,
  testValidationRegression,
  testNamingContractRegression,
];

for (const test of tests) {
  test();
  console.log(`TEST ${test.name}: PASS`);
}
