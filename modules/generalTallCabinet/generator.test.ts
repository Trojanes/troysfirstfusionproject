import assert from "node:assert/strict";
import { generateGeneralTallCabinet } from "./generator.ts";
import type { BoardFeature, FunctionalZone, GeneralTallCabinetParams } from "./types.ts";

function zone(id: string, type: FunctionalZone["type"], height: number): FunctionalZone {
  return { id, type, height };
}

function baseParams(zones: FunctionalZone[]): GeneralTallCabinetParams {
  return {
    cabinetHeight: 2100,
    cabinetWidth: 664,
    cabinetDepth: 600,
    panelThickness: 16,
    frontFaceAllowance: 16,
    ziThickness: 15,
    hThickness: 15,
    sideClearance: 3,
    doorPanelThickness: 16,
    topSystem: { style: "style_1", frontRailHeight: 40, insertSlotThickness: 16 },
    bottomSystem: { style: "style_1", frontRailHeight: 53, insertSlotThickness: 16 },
    zones,
  };
}

function uiDefaultParams(): GeneralTallCabinetParams {
  return {
    cabinetHeight: 2000,
    cabinetWidth: 600,
    cabinetDepth: 584,
    panelThickness: 16,
    frontFaceAllowance: 16,
    sideClearance: 3,
    topSystem: { style: "style_1", frontRailHeight: 40 },
    bottomSystem: { style: "style_1", frontRailHeight: 53 },
    avoidance: { enabled: false, depth: 200, height: 400 },
    zones: [
      zone("zone-1", "side_door", 600),
      zone("zone-2", "drawer", 300),
      { ...zone("zone-3", "double_door", 945), verticalDivider: true },
    ],
  };
}

function boardTypes(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.boards.map((board) => board.boardType);
}

function ziSlotFeatures(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.features.filter((feature) => feature.type === "zi_slot");
}

function ziGrooveFeatures(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.features.filter((feature) => feature.type === "zi_groove");
}

function h34ClearanceSlotFeatures(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.features.filter((feature) => feature.type === "h34_clearance_slot");
}

function t3DrillHoleFeatures(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.features.filter(
    (feature): feature is Extract<BoardFeature, { type: "t3_drill_hole" }> => feature.type === "t3_drill_hole",
  );
}

function b3GrooveFeatures(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.features.filter(
    (feature): feature is Extract<BoardFeature, { type: "b3_groove" }> => feature.type === "b3_groove",
  );
}

function t3GrooveFeatures(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.features.filter(
    (feature): feature is Extract<BoardFeature, { type: "t3_groove" }> => feature.type === "t3_groove",
  );
}

function b3DrillHoleFeatures(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.features.filter(
    (feature): feature is Extract<BoardFeature, { type: "b3_drill_hole" }> => feature.type === "b3_drill_hole",
  );
}

function dividerTongueFeatures(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.features.filter(
    (feature): feature is Extract<BoardFeature, { type: "divider_tongue" }> => feature.type === "divider_tongue",
  );
}

function boundaryPanelBoards(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.boards.filter((board) => board.category === "boundary_panel");
}

function hSupportBoards(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.boards.filter((board) => board.category === "h_support");
}

function verticalDividerBoards(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.boards.filter((board) => board.category === "vertical_divider");
}

function vBoards(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.boards.filter((board) => ["V1", "V2", "V3", "V4"].includes(board.id));
}

function sidePanelBoards(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.boards.filter((board) => board.category === "side_panel");
}

function sidePanelProfile(cabinetDepth: number, cabinetHeight: number) {
  return [
    { y: 0, z: 0 },
    { y: cabinetDepth, z: 0 },
    { y: cabinetDepth, z: cabinetHeight },
    { y: 0, z: cabinetHeight },
    { y: 0, z: 0 },
  ];
}

function sidePanelNotchedProfile(cabinetDepth: number, cabinetHeight: number, avoidDepth: number, avoidHeight: number) {
  return [
    { y: 0, z: 0 },
    { y: cabinetDepth - avoidDepth, z: 0 },
    { y: cabinetDepth - avoidDepth, z: avoidHeight },
    { y: cabinetDepth, z: avoidHeight },
    { y: cabinetDepth, z: cabinetHeight },
    { y: 0, z: cabinetHeight },
    { y: 0, z: 0 },
  ];
}

function xyRectangle(board: { x0: number; x1: number; y0: number; y1: number }) {
  return [
    { x: board.x0, y: board.y0 },
    { x: board.x1, y: board.y0 },
    { x: board.x1, y: board.y1 },
    { x: board.x0, y: board.y1 },
    { x: board.x0, y: board.y0 },
  ];
}

function style1InsertProfile(midWidth: number) {
  return [
    { x: 16, y: 0 },
    { x: 16, y: 75 },
    { x: 0, y: 75 },
    { x: 0, y: 150 },
    { x: midWidth, y: 150 },
    { x: midWidth, y: 75 },
    { x: midWidth - 16, y: 75 },
    { x: midWidth - 16, y: 0 },
    { x: 16, y: 0 },
  ];
}

// Side notch width follows CPT (panelThickness = 16 in these test params).
function fullZiProfile(midWidth: number, midDepth: number, cpt = 16) {
  return [
    { x: cpt, y: 0 },
    { x: cpt, y: 105 },
    { x: 0, y: 105 },
    { x: 0, y: midDepth - 105 },
    { x: cpt, y: midDepth - 105 },
    { x: cpt, y: midDepth },
    { x: midWidth - cpt, y: midDepth },
    { x: midWidth - cpt, y: midDepth - 105 },
    { x: midWidth, y: midDepth - 105 },
    { x: midWidth, y: 105 },
    { x: midWidth - cpt, y: 105 },
    { x: midWidth - cpt, y: 0 },
    { x: cpt, y: 0 },
  ];
}

function halfZiProfile(midWidth: number) {
  return [
    { x: 0, y: 0 },
    { x: 0, y: 45 },
    { x: 16, y: 45 },
    { x: 16, y: 150 },
    { x: midWidth - 16, y: 150 },
    { x: midWidth - 16, y: 45 },
    { x: midWidth, y: 45 },
    { x: midWidth, y: 0 },
    { x: 0, y: 0 },
  ];
}

function shortenedZiProfile(midWidth: number, shortDepth: number, cpt = 16) {
  return [
    { x: cpt, y: 0 },
    { x: cpt, y: 105 },
    { x: 0, y: 105 },
    { x: 0, y: shortDepth },
    { x: midWidth, y: shortDepth },
    { x: midWidth, y: 105 },
    { x: midWidth - cpt, y: 105 },
    { x: midWidth - cpt, y: 0 },
    { x: cpt, y: 0 },
  ];
}


function hasPoint(points: Array<{ y: number; z: number }> | undefined, expected: { y: number; z: number }) {
  return points?.some((point) => point.y === expected.y && point.z === expected.z) ?? false;
}

function hasSegment(
  points: Array<{ y: number; z: number }> | undefined,
  start: { y: number; z: number },
  end: { y: number; z: number },
) {
  if (!points || points.length < 2) return false;
  for (let i = 1; i < points.length; i += 1) {
    const a = points[i - 1];
    const b = points[i];
    if (a.y === start.y && a.z === start.z && b.y === end.y && b.z === end.z) return true;
  }
  const first = points[0];
  const last = points[points.length - 1];
  return last.y === start.y && last.z === start.z && first.y === end.y && first.z === end.z;
}

function hasOrderedSequence(points: Array<{ y: number; z: number }> | undefined, expected: Array<{ y: number; z: number }>) {
  if (!points) return false;
  const startIndex = points.findIndex((point, index) =>
    expected.every((expectedPoint, offset) => {
      const candidate = points[index + offset];
      return candidate?.y === expectedPoint.y && candidate?.z === expectedPoint.z;
    }),
  );
  return startIndex >= 0;
}

function vectorRange(points: Array<{ y: number; z: number }>) {
  return {
    minY: Math.min(...points.map((point) => point.y)),
    maxY: Math.max(...points.map((point) => point.y)),
    minZ: Math.min(...points.map((point) => point.z)),
    maxZ: Math.max(...points.map((point) => point.z)),
  };
}

function expectedUiDefaultV12RealProfile() {
  return [
    { y: 70, z: 0 },
    { y: 150, z: 0 },
    { y: 150, z: 668.5 },
    { y: 100, z: 668.5 },
    { y: 100, z: 684.5 },
    { y: 150, z: 684.5 },
    { y: 150, z: 983.5 },
    { y: 100, z: 983.5 },
    { y: 100, z: 999.5 },
    { y: 150, z: 999.5 },
    { y: 150, z: 2000 },
    { y: 70, z: 2000 },
    { y: 70, z: 1960 },
    { y: 80, z: 1960 },
    { y: 80, z: 1944 },
    { y: 0, z: 1944 },
    { y: 0, z: 69 },
    { y: 80, z: 69 },
    { y: 80, z: 53 },
    { y: 70, z: 53 },
    { y: 70, z: 0 },
  ];
}

function expectedUiDefaultV34RearStileProfile() {
  return [
    { y: 0, z: 0 },
    { y: 150, z: 0 },
    { y: 150, z: 1895 },
    { y: 134, z: 1895 },
    { y: 134, z: 1984 },
    { y: 29, z: 1984 },
    { y: 29, z: 2000 },
    { y: 0, z: 2000 },
    { y: 0, z: 999.5 },
    { y: 50, z: 999.5 },
    { y: 50, z: 983.5 },
    { y: 0, z: 983.5 },
    { y: 0, z: 684.5 },
    { y: 50, z: 684.5 },
    { y: 50, z: 668.5 },
    { y: 0, z: 668.5 },
    { y: 0, z: 0 },
  ];
}

function expectedUiDefaultV34PartialAvoidanceProfile() {
  return [
    { y: 0, z: 0 },
    { y: 70, z: 0 },
    { y: 70, z: 400 },
    { y: 150, z: 400 },
    { y: 150, z: 1895 },
    { y: 134, z: 1895 },
    { y: 134, z: 1984 },
    { y: 29, z: 1984 },
    { y: 29, z: 2000 },
    { y: 0, z: 2000 },
    { y: 0, z: 999.5 },
    { y: 50, z: 999.5 },
    { y: 50, z: 983.5 },
    { y: 0, z: 983.5 },
    { y: 0, z: 684.5 },
    { y: 50, z: 684.5 },
    { y: 50, z: 668.5 },
    { y: 0, z: 668.5 },
    { y: 0, z: 0 },
  ];
}

function expectedUiDefaultV34FullAvoidanceProfile() {
  return [
    { y: 0, z: 400 },
    { y: 150, z: 400 },
    { y: 150, z: 1895 },
    { y: 134, z: 1895 },
    { y: 134, z: 1984 },
    { y: 29, z: 1984 },
    { y: 29, z: 2000 },
    { y: 0, z: 2000 },
    { y: 0, z: 999.5 },
    { y: 50, z: 999.5 },
    { y: 50, z: 983.5 },
    { y: 0, z: 983.5 },
    { y: 0, z: 684.5 },
    { y: 50, z: 684.5 },
    { y: 50, z: 668.5 },
    { y: 0, z: 668.5 },
    { y: 0, z: 400 },
  ];
}

function yzRectangle(board: { y0: number; y1: number; z0: number; z1: number }) {
  return [
    { y: board.y0, z: board.z0 },
    { y: board.y1, z: board.z0 },
    { y: board.y1, z: board.z1 },
    { y: board.y0, z: board.z1 },
    { y: board.y0, z: board.z0 },
  ];
}

function hMidZRanges(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return ["H13_mid", "H24_mid", "H34_mid"].map((id) => {
    const board = result.boards.find((candidate) => candidate.id === id);
    return [id, board?.z0, board?.z1];
  });
}

function testStyle1ExactFitSkeleton() {
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("side", "side_door", 600),
      zone("drawer-a", "drawer", 300),
      zone("drawer-b", "drawer", 300),
      zone("blank", "blank_panel", 400),
      zone("open", "open_space", 330),
    ]),
  );

  assert(result.boards.some((board) => board.id === "V1"));
  assert(result.boards.some((board) => board.id === "V2"));
  ["V1", "V2", "V3", "V4"].forEach((id) => {
    const verticalBoard = result.boards.find((board) => board.id === id);
    assert(verticalBoard, `missing ${id}`);
    assert.equal(verticalBoard.name, id);
    assert.equal(verticalBoard.boardType, id);
  });
  const v3 = result.boards.find((board) => board.id === "V3");
  const v4 = result.boards.find((board) => board.id === "V4");
  assert(v3?.notes?.includes("Style 1 rear-stile profile implemented; rear top/bottom L-slot refinements deferred."));
  assert(v4?.notes?.includes("Style 1 rear-stile profile implemented; rear top/bottom L-slot refinements deferred."));

  const boundaryBoards = result.boards.filter((board) => board.category === "boundary_panel");
  assert.deepEqual(
    boundaryBoards.map((board) => board.boardType),
    ["full_zi", "half_zi", "full_zi"],
  );
  assert.equal(boundaryBoards.length, 3);

  const slotFeatures = ziSlotFeatures(result);
  assert.equal(slotFeatures.length, 10);
  assert.deepEqual([...new Set(slotFeatures.map((feature) => feature.boundaryId))], [
    "boundary-side-drawer-a",
    "boundary-drawer-a-drawer-b",
    "boundary-drawer-b-blank",
  ]);
  assert.deepEqual([...new Set(slotFeatures.map((feature) => feature.targetBoardId))], ["V1", "V2", "V3", "V4"]);
  slotFeatures.forEach((feature) => {
    if (feature.targetBoardId === "V1" || feature.targetBoardId === "V2") {
      assert.equal(feature.y0, 100);
      assert.equal(feature.y1, 150);
    } else {
      assert.equal(feature.boundaryType, "full_zi");
      assert.equal(feature.y0, 0);
      assert.equal(feature.y1, 50);
    }
    assert.equal(feature.z0, feature.centerZ - 8);
    assert.equal(feature.z1, feature.centerZ + 8);
    assert(feature.boundaryType === "full_zi" || feature.boundaryType === "half_zi");
  });
  assert(!slotFeatures.some((feature) => feature.boundaryId === "boundary-blank-open"));

  const h12Boards = result.boards.filter((board) => board.boardType === "H12");
  assert.equal(h12Boards.length, 2);
  assert(h12Boards.every((board) => board.boardType === "H12"));
  assert(!boardTypes(result).includes("h12"));
  assert.deepEqual(
    h12Boards.map((board) => [board.id, board.z1 - board.z0]),
    [
      ["H12_blank_bottom", 100],
      ["H12_blank_top", 100],
    ],
  );

  const types = boardTypes(result);
  ["T1", "T2", "T3", "B1", "B2", "B3"].forEach((type) => {
    assert(types.includes(type), `missing ${type}`);
  });
  assert(!types.includes("top_system_placeholder"));
  assert(!types.includes("bottom_system_placeholder"));
  assert.equal(result.boards.find((board) => board.id === "T1")?.materialThickness, 16);
  assert.equal(result.boards.find((board) => board.id === "T2")?.materialThickness, 15);
  // Inserted boards follow CPT (baseParams panelThickness = 16).
  assert.equal(result.boards.find((board) => board.id === "T3")?.materialThickness, 16);
  assert.equal(result.boards.find((board) => board.id === "B1")?.materialThickness, 16);
  assert.equal(result.boards.find((board) => board.id === "B2")?.materialThickness, 15);
  assert.equal(result.boards.find((board) => board.id === "B3")?.materialThickness, 16);
  assert(!types.includes("side_door_panel"));
  assert(!types.includes("drawer_front"));
  assert(!types.includes("flap_front"));
  assert(!types.includes("blank_front_panel"));
  assert(!types.includes("drawer_box"));
  assert(!types.some((type) => type.includes("hinge") || type.includes("lock") || type.includes("slide")));
}

function testVBoardSideProfileSkeletonStyle1() {
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("side", "side_door", 600),
      zone("drawer-a", "drawer", 300),
      zone("drawer-b", "drawer", 300),
      zone("blank", "blank_panel", 400),
      zone("open", "open_space", 330),
    ]),
  );

  for (const vBoard of vBoards(result).filter((board) => board.id === "V1" || board.id === "V2")) {
    assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "zi_slot").length, 3);
    assert(vBoard.cutProfileVector);
    assert.deepEqual(vBoard.profileVector, vBoard.cutProfileVector);
    assert.equal(vBoard.cutProfileVector?.length, 25);
    assert(!vBoard.notes?.includes("Exact side profile cut vector deferred; profileFeatures contain slot/notch data"));
    assert(vBoard.notes?.includes("Style 1 real side profile implemented"));
    assert.deepEqual(vectorRange(vBoard.cutProfileVector!), { minY: 0, maxY: 150, minZ: 0, maxZ: 2100 });
    assert(hasPoint(vBoard.cutProfileVector, { y: 100, z: 668.5 }));
    assert(hasPoint(vBoard.cutProfileVector, { y: 100, z: 684.5 }));
    assert(hasPoint(vBoard.cutProfileVector, { y: 100, z: 983.5 }));
    assert(hasPoint(vBoard.cutProfileVector, { y: 100, z: 999.5 }));
    assert(hasPoint(vBoard.cutProfileVector, { y: 100, z: 1298.5 }));
    assert(hasPoint(vBoard.cutProfileVector, { y: 100, z: 1314.5 }));
    assert(!hasPoint(vBoard.cutProfileVector, { y: 534, z: 668.5 }));
    assert(hasOrderedSequence(vBoard.cutProfileVector, [
      { y: 70, z: 2060 },
      { y: 80, z: 2060 },
      { y: 80, z: 2044 },
      { y: 0, z: 2044 },
    ]));
    assert(hasOrderedSequence(vBoard.cutProfileVector, [
      { y: 0, z: 69 },
      { y: 80, z: 69 },
      { y: 80, z: 53 },
      { y: 70, z: 53 },
    ]));
    assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_top_insert_slot").length, 1);
    assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_bottom_insert_slot").length, 1);
    assert.deepEqual(
      vBoard.profileFeatures?.find((feature) => feature.type === "style1_top_insert_slot"),
      {
        type: "style1_top_insert_slot",
        y0: 0,
        y1: 150,
        z0: 2044,
        z1: 2060,
        source: "top_system",
        notes: ["Exact top style side notch vector deferred"],
      },
    );
    assert.deepEqual(
      vBoard.profileFeatures?.find((feature) => feature.type === "style1_bottom_insert_slot"),
      {
        type: "style1_bottom_insert_slot",
        y0: 0,
        y1: 150,
        z0: 53,
        z1: 69,
        source: "bottom_system",
        notes: ["Exact bottom style side notch vector deferred"],
      },
    );
  }

  for (const vBoard of vBoards(result).filter((board) => board.id === "V3" || board.id === "V4")) {
    assert.deepEqual(vBoard.profileVector, vBoard.cutProfileVector);
    assert(vBoard.notes?.includes("Style 1 rear-stile profile implemented; rear top/bottom L-slot refinements deferred."));
    assert(!vBoard.notes?.includes("V3/V4 exact geometry deferred"));
    assert(!vBoard.notes?.includes("Exact side profile cut vector deferred; profileFeatures contain slot/notch data"));
    assert.equal(vBoard.cutProfileVector?.length, 17);
    assert.deepEqual(vectorRange(vBoard.cutProfileVector!), { minY: 0, maxY: 150, minZ: 0, maxZ: 2100 });
    assert(hasPoint(vBoard.cutProfileVector, { y: 50, z: 668.5 }));
    assert(hasPoint(vBoard.cutProfileVector, { y: 50, z: 684.5 }));
    assert(!hasPoint(vBoard.cutProfileVector, { y: 534, z: 668.5 }));
    assert(!hasPoint(vBoard.cutProfileVector, { y: result.debug.midDepth, z: 668.5 }));
    assert(hasOrderedSequence(vBoard.cutProfileVector, [
      { y: 150, z: 1995 },
      { y: 134, z: 1995 },
      { y: 134, z: 2084 },
      { y: 29, z: 2084 },
      { y: 29, z: 2100 },
      { y: 0, z: 2100 },
    ]));
    assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_top_insert_slot").length, 0);
    assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_bottom_insert_slot").length, 0);
  }
}

function testVBoardCutProfileSingleZiSlot() {
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("side", "side_door", 600),
      zone("open", "open_space", 1400),
    ]),
  );
  const v1 = result.boards.find((board) => board.id === "V1");
  const slot = v1?.profileFeatures?.find((feature) => feature.type === "zi_slot");

  assert(v1);
  assert(slot);
  assert.deepEqual(v1.profileVector, [
    { y: 70, z: 0 },
    { y: 150, z: 0 },
    { y: 150, z: slot.z0 },
    { y: 100, z: slot.z0 },
    { y: 100, z: slot.z1 },
    { y: 150, z: slot.z1 },
    { y: 150, z: 2100 },
    { y: 70, z: 2100 },
    { y: 70, z: 2060 },
    { y: 80, z: 2060 },
    { y: 80, z: 2044 },
    { y: 0, z: 2044 },
    { y: 0, z: 69 },
    { y: 80, z: 69 },
    { y: 80, z: 53 },
    { y: 70, z: 53 },
    { y: 70, z: 0 },
  ]);
  assert.equal(slot.y0, 100);
  assert.equal(slot.y1, 150);
  assert(hasPoint(v1.cutProfileVector, { y: 150, z: slot.z0 }));
  assert(hasPoint(v1.cutProfileVector, { y: 100, z: slot.z0 }));
  assert(hasPoint(v1.cutProfileVector, { y: 100, z: slot.z1 }));
  assert(hasPoint(v1.cutProfileVector, { y: 150, z: slot.z1 }));
  assert(!hasPoint(v1.cutProfileVector, { y: result.debug.midDepth, z: slot.z0 }));
}

function testV12Style1RealProfileDefaultUiConfig() {
  const result = generateGeneralTallCabinet(uiDefaultParams());
  const expected = expectedUiDefaultV12RealProfile();

  for (const id of ["V1", "V2"]) {
    const board = result.boards.find((candidate) => candidate.id === id);
    assert(board, `${id} missing`);
    assert.deepEqual(board.cutProfileVector, expected);
    assert.deepEqual(board.profileVector, expected);
    assert.deepEqual(vectorRange(board.cutProfileVector!), { minY: 0, maxY: 150, minZ: 0, maxZ: 2000 });
    assert.deepEqual(board.cutProfileVector?.at(0), board.cutProfileVector?.at(-1));
    assert(board.notes?.includes("Style 1 real side profile implemented"));
    assert(!board.notes?.includes("Exact side profile cut vector deferred; profileFeatures contain slot/notch data"));
    assert(hasOrderedSequence(board.cutProfileVector, [
      { y: 150, z: 668.5 },
      { y: 100, z: 668.5 },
      { y: 100, z: 684.5 },
      { y: 150, z: 684.5 },
    ]));
    assert(hasOrderedSequence(board.cutProfileVector, [
      { y: 150, z: 983.5 },
      { y: 100, z: 983.5 },
      { y: 100, z: 999.5 },
      { y: 150, z: 999.5 },
    ]));
    assert(!hasPoint(board.cutProfileVector, { y: 518, z: 668.5 }));
    assert(!hasPoint(board.cutProfileVector, { y: 568, z: 668.5 }));
    assert(hasPoint(board.cutProfileVector, { y: 80, z: 1944 }));
    assert(hasPoint(board.cutProfileVector, { y: 80, z: 1960 }));
    assert(hasPoint(board.cutProfileVector, { y: 80, z: 53 }));
    assert(hasPoint(board.cutProfileVector, { y: 80, z: 69 }));
  }

}

function testV34Style1RearStileProfileDefaultUiConfig() {
  const result = generateGeneralTallCabinet(uiDefaultParams());
  const expected = expectedUiDefaultV34RearStileProfile();

  for (const id of ["V3", "V4"]) {
    const board = result.boards.find((candidate) => candidate.id === id);
    assert(board, `${id} missing`);
    assert.deepEqual(board.cutProfileVector, expected);
    assert.deepEqual(board.profileVector, expected);
    assert.deepEqual(vectorRange(board.cutProfileVector!), { minY: 0, maxY: 150, minZ: 0, maxZ: 2000 });
    assert.deepEqual(board.cutProfileVector?.at(0), board.cutProfileVector?.at(-1));
    assert(board.notes?.includes("Style 1 rear-stile profile implemented; rear top/bottom L-slot refinements deferred."));
    assert(!board.notes?.includes("V3/V4 exact geometry deferred"));
    assert(!board.notes?.includes("Exact side profile cut vector deferred; profileFeatures contain slot/notch data"));
    assert.equal(board.profileFeatures?.filter((feature) => feature.type === "style1_top_insert_slot").length, 0);
    assert.equal(board.profileFeatures?.filter((feature) => feature.type === "style1_bottom_insert_slot").length, 0);
    assert(hasOrderedSequence(board.cutProfileVector, [
      { y: 0, z: 999.5 },
      { y: 50, z: 999.5 },
      { y: 50, z: 983.5 },
      { y: 0, z: 983.5 },
    ]));
    assert(hasOrderedSequence(board.cutProfileVector, [
      { y: 0, z: 684.5 },
      { y: 50, z: 684.5 },
      { y: 50, z: 668.5 },
      { y: 0, z: 668.5 },
    ]));
    assert(!hasPoint(board.cutProfileVector, { y: 518, z: 668.5 }));
    assert(!hasPoint(board.cutProfileVector, { y: 568, z: 668.5 }));
    assert(!hasPoint(board.cutProfileVector, { y: 70, z: 1960 }));
    assert(!hasPoint(board.cutProfileVector, { y: 80, z: 1944 }));
  }

  const v34SlotFeatures = ziSlotFeatures(result).filter(
    (feature) => feature.targetBoardId === "V3" || feature.targetBoardId === "V4",
  );
  assert.equal(v34SlotFeatures.length, 4);
  assert(v34SlotFeatures.every((feature) => feature.boundaryType === "full_zi"));
  assert(v34SlotFeatures.every((feature) => feature.y0 === 0 && feature.y1 === 50));
}

function testV34RearAvoidanceCutoutPartialDepth() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    avoidance: { enabled: true, depth: 80, height: 400 },
  });
  const expected = expectedUiDefaultV34PartialAvoidanceProfile();

  for (const id of ["V3", "V4"]) {
    const board = result.boards.find((candidate) => candidate.id === id);
    assert(board, `${id} missing`);
    assert.deepEqual(board.cutProfileVector, expected);
    assert.deepEqual(board.profileVector, expected);
    assert.deepEqual(vectorRange(board.cutProfileVector!), { minY: 0, maxY: 150, minZ: 0, maxZ: 2000 });
    assert(board.notes?.includes("Rear avoidance cutout applied to V3/V4 rear-stile profile."));
    assert(hasOrderedSequence(board.cutProfileVector, [
      { y: 0, z: 0 },
      { y: 70, z: 0 },
      { y: 70, z: 400 },
      { y: 150, z: 400 },
    ]));
  }

  const v1 = result.boards.find((board) => board.id === "V1");
  assert.deepEqual(v1?.cutProfileVector, expectedUiDefaultV12RealProfile());
}

function testV34RearAvoidanceCutoutFullDepth() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    avoidance: { enabled: true, depth: 200, height: 400 },
  });
  const expected = expectedUiDefaultV34FullAvoidanceProfile();

  for (const id of ["V3", "V4"]) {
    const board = result.boards.find((candidate) => candidate.id === id);
    assert(board, `${id} missing`);
    assert.deepEqual(board.cutProfileVector, expected);
    assert.deepEqual(board.profileVector, expected);
    assert.deepEqual(board.cutProfileVector?.at(0), { y: 0, z: 400 });
    assert.deepEqual(board.cutProfileVector?.at(-1), { y: 0, z: 400 });
    assert(!hasPoint(board.cutProfileVector, { y: 0, z: 0 }));
    assert(board.notes?.includes("Rear avoidance cutout applied to V3/V4 rear-stile profile."));
  }
}

function testV34RearAvoidanceZeroHeightNoCutout() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    avoidance: { enabled: true, depth: 200, height: 0 },
  });
  const expected = expectedUiDefaultV34RearStileProfile();

  for (const id of ["V3", "V4"]) {
    const board = result.boards.find((candidate) => candidate.id === id);
    assert(board, `${id} missing`);
    assert.deepEqual(board.cutProfileVector, expected);
    assert(!board.notes?.includes("Rear avoidance cutout applied to V3/V4 rear-stile profile."));
  }
}

function testV34RearAvoidanceOmitsIntersectingSlot() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    avoidance: { enabled: true, depth: 200, height: 991.5 },
  });

  assert(result.validation.warnings.some((warning) =>
    warning.includes("V3/V4 Zi slot intersects avoidance cutout; slot omitted in V1.1."),
  ));
  for (const id of ["V3", "V4"]) {
    const board = result.boards.find((candidate) => candidate.id === id);
    assert(board, `${id} missing`);
    assert(!hasPoint(board.cutProfileVector, { y: 50, z: 983.5 }));
    assert(!hasPoint(board.cutProfileVector, { y: 50, z: 999.5 }));
    assert(board.profileFeatures?.some((feature) => feature.type === "zi_slot" && feature.z0 === 983.5));
  }
}

function testZiBoardProfileVectorsStyle1() {
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("side", "side_door", 600),
      zone("drawer-a", "drawer", 300),
      zone("drawer-b", "drawer", 300),
      zone("blank", "blank_panel", 400),
      zone("open", "open_space", 330),
    ]),
  );
  const ziBoards = boundaryPanelBoards(result);

  assert.equal(ziBoards.length, 3);
  for (const ziBoard of ziBoards) {
    assert.equal(ziBoard.profilePlane, "XY");
    assert.equal(ziBoard.thicknessAxis, "Z");
    if (ziBoard.boardType === "full_zi") {
      assert.equal(ziBoard.y1, result.debug.midDepth);
      assert.deepEqual(ziBoard.profileVector, fullZiProfile(result.debug.midWidth, result.debug.midDepth));
      assert(ziBoard.notes?.includes("Exact full_zi notched outer profile implemented; groove machining remains feature-only."));
      assert.notDeepEqual(ziBoard.profileVector, xyRectangle(ziBoard));
    } else if (ziBoard.boardType === "half_zi") {
      assert.deepEqual(ziBoard.profileVector, halfZiProfile(result.debug.midWidth));
      assert(ziBoard.notes?.includes("Exact half_zi outer profile implemented."));
      assert(!ziBoard.notes?.includes("Exact half Zi profile/vector deferred"));
      assert(!ziBoard.notes?.includes("Exact half Zi profile vector deferred"));
    }
  }
}

function testBlankHeight250GeneratesOneH12() {
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("side", "side_door", 600),
      zone("blank", "blank_panel", 250),
      zone("open", "open_space", 930),
    ]),
  );

  const h12Boards = result.boards.filter((board) => board.boardType === "H12");
  assert.equal(h12Boards.length, 1);
  assert.equal(h12Boards[0].id, "H12_blank");
  assert.equal(h12Boards[0].boardType, "H12");
  assert(!boardTypes(result).includes("h12"));
  assert.equal(h12Boards[0].z1 - h12Boards[0].z0, 250);
}

function testStyle2FixedFrontPanels() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 800),
      zone("blank", "blank_panel", 400),
      zone("drawer", "drawer", 705),
    ]),
    topSystem: { style: "style_2", height: 80 },
    bottomSystem: { style: "style_2", height: 100 },
  });

  const topPanel = result.boards.find((board) => board.id === "TopStyle2FixedFrontPanel");
  const bottomPanel = result.boards.find((board) => board.id === "BottomStyle2FixedFrontPanel");
  const th1 = result.boards.find((board) => board.id === "TH1");
  const bh1 = result.boards.find((board) => board.id === "BH1");
  const t4 = result.boards.find((board) => board.id === "T4");
  const t5 = result.boards.find((board) => board.id === "T5");
  const h34Top = result.boards.find((board) => board.id === "H34_top");
  assert(topPanel);
  assert(bottomPanel);
  assert(th1);
  assert(bh1);
  assert(t4);
  assert(t5);
  assert.equal(h34Top, undefined);
  assert.equal(topPanel?.boardType, "style2_fixed_front_panel");
  assert.equal(bottomPanel?.boardType, "style2_fixed_front_panel");
  assert.deepEqual([topPanel?.x0, topPanel?.x1, topPanel?.y0, topPanel?.y1, topPanel?.z0, topPanel?.z1], [
    3,
    661,
    -16,
    0,
    2020,
    2100,
  ]);
  assert.deepEqual([bottomPanel?.x0, bottomPanel?.x1, bottomPanel?.y0, bottomPanel?.y1, bottomPanel?.z0, bottomPanel?.z1], [
    3,
    661,
    -16,
    0,
    0,
    100,
  ]);
  assert.equal(t5?.boardType, "T5");
  assert.equal(t5?.profilePlane, "XZ");
  assert.equal(t5?.thicknessAxis, "Y");
  assert.deepEqual([t5?.x0, t5?.x1, t5?.y0, t5?.y1, t5?.z0, t5?.z1], [0, 664, 584, 599, 2000, 2100]);
  assert.equal(t4?.boardType, "T4");
  assert.equal(t4?.profilePlane, "XY");
  assert.equal(t4?.thicknessAxis, "Z");
  assert.deepEqual([t4?.x0, t4?.x1, t4?.y0, t4?.y1, t4?.z0, t4?.z1], [0, 664, 484, 584, 2084, 2099]);
  assert.equal(th1?.boardType, "TH1");
  assert.equal(th1?.profilePlane, "XY");
  assert.equal(th1?.thicknessAxis, "Z");
  assert.deepEqual([th1?.x0, th1?.x1, th1?.y0, th1?.y1, th1?.z0, th1?.z1], [0, 664, 0, 100, 2084, 2099]);
  assert.equal(bh1?.boardType, "BH1");
  assert.equal(bh1?.profilePlane, "XY");
  assert.equal(bh1?.thicknessAxis, "Z");
  assert.deepEqual([bh1?.x0, bh1?.x1, bh1?.y0, bh1?.y1, bh1?.z0, bh1?.z1], [0, 664, 0, 100, 1, 16]);
  const h12Boards = result.boards.filter((board) => board.boardType === "H12");
  assert(h12Boards.length > 0);
  assert(h12Boards.every((board) => board.source === "blank"));
  assert(h12Boards.every((board) => board.boardType === "H12"));
  assert(!boardTypes(result).includes("h12"));
}

function testHeightMismatchStillReturnsBoards() {
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("side", "side_door", 600),
      zone("drawer-a", "drawer", 300),
      zone("drawer-b", "drawer", 300),
      zone("blank", "blank_panel", 400),
      zone("open", "open_space", 300),
    ]),
  );

  assert(result.validation.warnings.some((warning) => warning.includes("Height mismatch")));
  assert(result.boards.length > 0);
  assert.equal(ziSlotFeatures(result).length, 10);
  assert.equal(result.stacking.calculatedHeight, 2070);
}

function testStyle1DefaultZRanges() {
  const result = generateGeneralTallCabinet(baseParams([zone("open", "open_space", 1975)]));

  assert.deepEqual(
    ["T1", "T2", "T3", "B1", "B2", "B3"].map((id) => {
      const b = result.boards.find((board) => board.id === id);
      return [id, b?.z0, b?.z1];
    }),
    [
      ["T1", 2060, 2100],
      ["T2", 2060, 2100],
      ["T3", 2044, 2060],
      ["B1", 0, 53],
      ["B2", 0, 53],
      ["B3", 53, 69],
    ],
  );
}

function testStyle1T3B3ExactNotchedProfileVectors() {
  const result = generateGeneralTallCabinet({
    ...baseParams([zone("open", "open_space", 1975)]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
  });
  const t3 = result.boards.find((board) => board.id === "T3");
  const b3 = result.boards.find((board) => board.id === "B3");

  assert.equal(result.debug.midWidth, 668);
  assert(t3);
  assert(b3);
  assert.deepEqual(t3.profileVector, style1InsertProfile(668));
  assert.deepEqual(b3.profileVector, style1InsertProfile(668));
  assert.deepEqual([t3.x0, t3.x1, t3.y0, t3.y1, t3.z0, t3.z1], [16, 684, 0, 150, 2044, 2060]);
  assert.deepEqual([b3.x0, b3.x1, b3.y0, b3.y1, b3.z0, b3.z1], [16, 684, 0, 150, 53, 69]);
  assert(t3.notes?.includes("Exact Style 1 T3 notched profileVector implemented"));
  assert(!t3.notes?.includes("Exact notched profile vector deferred"));
  assert(!t3.notes?.some((note) => note.toLowerCase().includes("drill")));
  assert(b3.notes?.includes("Exact Style 1 B3 notched profileVector implemented"));
  assert(!b3.notes?.includes("Exact notched profile vector deferred"));
  assert(b3.notes?.includes("B3 LED groove path implemented on bottom face"));
  assert(t3.notes?.includes("T3 LED groove path implemented on top face"));
  assert(!b3.notes?.some((note) => note.toLowerCase().includes("drill")));

  ["T1", "T2", "B1", "B2"].forEach((id) => {
    assert.equal(result.boards.find((board) => board.id === id)?.profileVector, undefined);
  });
}

function testStyle2DoesNotGenerateT3B3() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      zone("drawer", "drawer", 400),
      zone("open", "open_space", 900),
    ]),
    topSystem: { style: "style_2", height: 80 },
    bottomSystem: { style: "style_2", height: 100 },
  });

  assert(!result.boards.some((board) => board.id === "T3"));
  assert(!result.boards.some((board) => board.id === "B3"));
  assert.equal(t3DrillHoleFeatures(result).length, 0);
  assert.equal(b3GrooveFeatures(result).length, 0);
  assert.equal(b3DrillHoleFeatures(result).length, 0);
}

function testStyle1T3B3FeaturePlaceholders() {
  const result = generateGeneralTallCabinet({
    ...baseParams([zone("open", "open_space", 1975)]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
  });
  const b3Grooves = b3GrooveFeatures(result);

  assert(result.boards.some((board) => board.id === "T3"));
  assert(result.boards.some((board) => board.id === "B3"));
  assert.equal(result.debug.midWidth, 668);
  assert.equal(t3DrillHoleFeatures(result).length, 0);
  assert.equal(b3DrillHoleFeatures(result).length, 0);

  assert.equal(b3Grooves.length, 1);
  assert.deepEqual(
    {
      targetBoardId: b3Grooves[0].targetBoardId,
      face: b3Grooves[0].face,
      width: b3Grooves[0].width,
      depth: b3Grooves[0].depth,
      frontOffset: b3Grooves[0].frontOffset,
      branchCount: b3Grooves[0].branchCount,
      branchLength: b3Grooves[0].branchLength,
      branchEndInset: b3Grooves[0].branchEndInset,
      main: b3Grooves[0].main,
      branches: b3Grooves[0].branches,
    },
    {
      targetBoardId: "B3",
      face: "bottom",
      width: 14.5,
      depth: 6.5,
      frontOffset: 25.25,
      branchCount: 2,
      branchLength: 117.5,
      branchEndInset: 80,
      main: { x0: 0, x1: 668, y0: 18, y1: 32.5 },
      branches: [
        { x0: 72.75, x1: 87.25, y0: 32.5, y1: 150 },
        { x0: 580.75, x1: 595.25, y0: 32.5, y1: 150 },
      ],
    },
  );
  assert(b3Grooves[0].notes?.includes("B3 LED groove on bottom face"));

  const t3Grooves = t3GrooveFeatures(result);
  assert.equal(t3Grooves.length, 1);
  assert.equal(t3Grooves[0].face, "top");
  assert.deepEqual(t3Grooves[0].main, b3Grooves[0].main);
  assert.deepEqual(t3Grooves[0].branches, b3Grooves[0].branches);
  assert(t3Grooves[0].notes?.includes("T3 LED groove on top face"));

  const t3 = result.boards.find((board) => board.id === "T3");
  const b3 = result.boards.find((board) => board.id === "B3");
  assert.deepEqual(t3?.profileVector, style1InsertProfile(668));
  assert.deepEqual(b3?.profileVector, style1InsertProfile(668));
  assert(!t3?.notes?.some((note) => note.toLowerCase().includes("drill")));
  assert(!b3?.notes?.some((note) => note.toLowerCase().includes("drill")));
}

function testStyle1LedGrooveCanBeDisabled() {
  const result = generateGeneralTallCabinet({
    ...baseParams([zone("open", "open_space", 1975)]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    topSystem: { style: "style_1", frontRailHeight: 40, insertSlotThickness: 16, ledGroove: false },
    bottomSystem: { style: "style_1", frontRailHeight: 53, insertSlotThickness: 16, ledGroove: false },
  });
  assert.equal(b3GrooveFeatures(result).length, 0);
  assert.equal(t3GrooveFeatures(result).length, 0);
  assert(result.boards.some((board) => board.id === "T3"));
  assert(result.boards.some((board) => board.id === "B3"));
}

function testStyle1CustomHeights() {
  const result = generateGeneralTallCabinet({
    ...baseParams([zone("open", "open_space", 1903)]),
    topSystem: { style: "style_1", frontRailHeight: 70, insertSlotThickness: 16 },
    bottomSystem: { style: "style_1", frontRailHeight: 80, insertSlotThickness: 16 },
  });

  assert.equal(result.stacking.topSystemHeight, 86);
  assert.equal(result.stacking.bottomSystemHeight, 96);
  assert.deepEqual(
    ["T1", "T2", "T3", "B1", "B2", "B3"].map((id) => {
      const b = result.boards.find((board) => board.id === id);
      return [id, b?.z0, b?.z1];
    }),
    [
      ["T1", 2030, 2100],
      ["T2", 2030, 2100],
      ["T3", 2014, 2030],
      ["B1", 0, 80],
      ["B2", 0, 80],
      ["B3", 80, 96],
    ],
  );
}

function testStyle1InsertedBoardsFollowCpt() {
  // CPT 15 with the default 16 mm insert slot: boards are 15 mm solids,
  // top-flush (T3) / bottom-flush (B3) inside the 16 mm slot.
  const result = generateGeneralTallCabinet({
    ...baseParams([zone("open", "open_space", 1976)]),
    panelThickness: 15,
  });
  const t3 = result.boards.find((board) => board.id === "T3");
  const b3 = result.boards.find((board) => board.id === "B3");
  assert.equal(t3?.materialThickness, 15);
  assert.equal(b3?.materialThickness, 15);
  assert.deepEqual([t3?.z0, t3?.z1], [2045, 2060]);
  assert.deepEqual([b3?.z0, b3?.z1], [53, 68]);
  // Slot features keep the configured insertSlotThickness (16).
  const v1 = result.boards.find((board) => board.id === "V1");
  const topSlot = v1?.profileFeatures?.find((feature) => feature.type === "style1_top_insert_slot");
  const bottomSlot = v1?.profileFeatures?.find((feature) => feature.type === "style1_bottom_insert_slot");
  assert.deepEqual([topSlot?.z0, topSlot?.z1], [2044, 2060]);
  assert.deepEqual([bottomSlot?.z0, bottomSlot?.z1], [53, 69]);
}

function testHSupportBoardSkeletons() {
  const result = generateGeneralTallCabinet({
    ...baseParams([zone("open", "open_space", 1975)]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
  });
  const hBoards = hSupportBoards(result);

  assert.equal(result.debug.midWidth, 668);
  assert.equal(result.debug.midDepth, 584);
  assert.equal(hBoards.length, 8);
  assert.deepEqual(
    hBoards.map((board) => board.id).sort(),
    [
      "H13_bottom",
      "H13_mid",
      "H13_top",
      "H24_bottom",
      "H24_mid",
      "H24_top",
      "H34_bottom",
      "H34_mid",
    ],
  );

  const expected = new Map([
    ["H13_top", { boardType: "H13", profilePlane: "YZ", thicknessAxis: "X", x0: 16, x1: 31, y0: 150, y1: 434, z0: 2000, z1: 2100 }],
    ["H24_top", { boardType: "H24", profilePlane: "YZ", thicknessAxis: "X", x0: 669, x1: 684, y0: 150, y1: 434, z0: 2000, z1: 2100 }],
    ["H13_bottom", { boardType: "H13", profilePlane: "YZ", thicknessAxis: "X", x0: 16, x1: 31, y0: 150, y1: 434, z0: 0, z1: 100 }],
    ["H24_bottom", { boardType: "H24", profilePlane: "YZ", thicknessAxis: "X", x0: 669, x1: 684, y0: 150, y1: 434, z0: 0, z1: 100 }],
    ["H34_bottom", { boardType: "H34", profilePlane: "XZ", thicknessAxis: "Y", x0: 31, x1: 669, y0: 569, y1: 584, z0: 0, z1: 100 }],
    ["H13_mid", { boardType: "H13", profilePlane: "YZ", thicknessAxis: "X", x0: 16, x1: 31, y0: 150, y1: 434, z0: 1000, z1: 1100 }],
    ["H24_mid", { boardType: "H24", profilePlane: "YZ", thicknessAxis: "X", x0: 669, x1: 684, y0: 150, y1: 434, z0: 1000, z1: 1100 }],
    ["H34_mid", { boardType: "H34", profilePlane: "XZ", thicknessAxis: "Y", x0: 31, x1: 669, y0: 569, y1: 584, z0: 1000, z1: 1100 }],
  ]);

  for (const hBoard of hBoards) {
    const expectedBoard = expected.get(hBoard.id);
    assert(expectedBoard, `unexpected H support board ${hBoard.id}`);
    assert.equal(hBoard.name, hBoard.id.replace("_", " "));
    assert.equal(hBoard.category, "h_support");
    assert.equal(hBoard.materialThickness, 15);
    assert.deepEqual(
      {
        boardType: hBoard.boardType,
        profilePlane: hBoard.profilePlane,
        thicknessAxis: hBoard.thicknessAxis,
        x0: hBoard.x0,
        x1: hBoard.x1,
        y0: hBoard.y0,
        y1: hBoard.y1,
        z0: hBoard.z0,
        z1: hBoard.z1,
      },
      expectedBoard,
    );
    assert(hBoard.x1 > hBoard.x0);
    assert(hBoard.y1 > hBoard.y0);
    assert(hBoard.z1 > hBoard.z0);
  }

  assert(result.boards.every((board) => !["door_panel", "drawer_front", "hardware_hole", "toolpath"].includes(board.boardType)));
}

function testAvoidanceDisabledKeepsFullZiAndRearSlots() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      zone("drawer-a", "drawer", 300),
      zone("drawer-b", "drawer", 300),
      zone("blank", "blank_panel", 400),
      zone("open", "open_space", 330),
    ]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    avoidance: { enabled: false, depth: 200 },
  });

  assert.equal(boundaryPanelBoards(result).filter((board) => board.boardType === "shortened_zi").length, 0);
  assert.deepEqual(
    boundaryPanelBoards(result).map((board) => board.boardType),
    ["full_zi", "half_zi", "full_zi"],
  );
  assert(ziSlotFeatures(result).filter((feature) => feature.targetBoardId === "V1" || feature.targetBoardId === "V2").every(
    (feature) => feature.y0 === 100 && feature.y1 === 150,
  ));
  assert(ziSlotFeatures(result).filter((feature) => feature.targetBoardId === "V3" || feature.targetBoardId === "V4").every(
    (feature) => feature.boundaryType === "full_zi" && feature.y0 === 0 && feature.y1 === 50,
  ));
}

function testAvoidanceConvertsEligibleFullZiToShortenedZi() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      zone("drawer-a", "drawer", 300),
      zone("drawer-b", "drawer", 300),
      zone("blank", "blank_panel", 400),
      zone("open", "open_space", 330),
    ]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    avoidance: { enabled: true, depth: 200, height: 1400 },
  });
  const boundaryBoards = boundaryPanelBoards(result);
  const shortenedBoards = boundaryBoards.filter((board) => board.boardType === "shortened_zi");

  assert.equal(result.debug.midDepth, 584);
  assert.equal(shortenedBoards.length, 2);
  assert.deepEqual(
    boundaryBoards.map((board) => [board.source, board.boardType, board.y0, board.y1]),
    [
      ["boundary-side-drawer-a", "shortened_zi", 0, 384],
      ["boundary-drawer-a-drawer-b", "half_zi", 0, 584],
      ["boundary-drawer-b-blank", "shortened_zi", 0, 384],
    ],
  );
  assert(shortenedBoards.every((board) => board.materialThickness === 15));
  assert(shortenedBoards.every((board) => board.notes?.includes("V1 simplified avoidance shortening rule")));
  assert(shortenedBoards.every((board) => board.notes?.includes("Exact shortened_zi notched outer profile implemented; rear connection omitted.")));
  assert(shortenedBoards.every((board) =>
    board.profileVector && JSON.stringify(board.profileVector) === JSON.stringify(shortenedZiProfile(result.debug.midWidth, 384)),
  ));
  assert(shortenedBoards.every((board) => JSON.stringify(board.profileVector) !== JSON.stringify(xyRectangle(board))));

  const shortenedSlotFeatures = ziSlotFeatures(result).filter((feature) => feature.boundaryType === "shortened_zi");
  const halfSlotFeatures = ziSlotFeatures(result).filter((feature) => feature.boundaryType === "half_zi");
  assert.equal(shortenedSlotFeatures.length, 4);
  assert(shortenedSlotFeatures.filter((feature) => feature.targetBoardId === "V1" || feature.targetBoardId === "V2").every(
    (feature) => feature.y0 === 100 && feature.y1 === 150,
  ));
  assert.equal(shortenedSlotFeatures.filter((feature) => feature.targetBoardId === "V3" || feature.targetBoardId === "V4").length, 0);
  assert.equal(halfSlotFeatures.length, 2);
  assert(halfSlotFeatures.filter((feature) => feature.targetBoardId === "V1" || feature.targetBoardId === "V2").every(
    (feature) => feature.y0 === 100 && feature.y1 === 150,
  ));
  assert.equal(halfSlotFeatures.filter((feature) => feature.targetBoardId === "V3" || feature.targetBoardId === "V4").length, 0);

  for (const vBoard of vBoards(result)) {
    const shortenedProfileFeatures = vBoard.profileFeatures?.filter(
      (feature) => feature.type === "zi_slot" && feature.boundaryType === "shortened_zi",
    );
    if (vBoard.id === "V1" || vBoard.id === "V2") {
      assert.equal(shortenedProfileFeatures?.length, 2);
      assert(shortenedProfileFeatures?.every((feature) => feature.y0 === 100 && feature.y1 === 150));
      assert(shortenedProfileFeatures?.every((feature) => hasPoint(vBoard.cutProfileVector, { y: 150, z: feature.z0 })));
      assert(shortenedProfileFeatures?.every((feature) => hasPoint(vBoard.cutProfileVector, { y: 100, z: feature.z0 })));
      assert(shortenedProfileFeatures?.every((feature) => hasPoint(vBoard.cutProfileVector, { y: 100, z: feature.z1 })));
      assert(shortenedProfileFeatures?.every((feature) => hasPoint(vBoard.cutProfileVector, { y: 150, z: feature.z1 })));
    } else {
      assert.equal(shortenedProfileFeatures?.length, 0);
    }
  }
}

function testAvoidanceHeightRequiredAndZeroHeight() {
  const missingHeight = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      zone("drawer", "drawer", 500),
      zone("open", "open_space", 900),
    ]),
    avoidance: { enabled: true, depth: 200 },
  });

  assert(missingHeight.validation.errors.some((error) => error.includes("Avoidance height is required when avoidance is enabled.")));
  assert.equal(boundaryPanelBoards(missingHeight).filter((board) => board.boardType === "shortened_zi").length, 0);
  assert(boundaryPanelBoards(missingHeight).some((board) => board.boardType === "full_zi"));

  const zeroHeight = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      zone("drawer", "drawer", 500),
      zone("open", "open_space", 900),
    ]),
    avoidance: { enabled: true, depth: 200, height: 0 },
  });

  assert.equal(zeroHeight.validation.errors.filter((error) => error.includes("Avoidance height")).length, 0);
  assert.equal(boundaryPanelBoards(zeroHeight).filter((board) => board.boardType === "shortened_zi").length, 0);
  assert(boundaryPanelBoards(zeroHeight).every((board) => board.boardType !== "shortened_zi"));
}

function testAvoidanceAffectedZoneEligibility() {
  const aboveAvoidH = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      zone("drawer", "drawer", 500),
      zone("open", "open_space", 900),
    ]),
    avoidance: { enabled: true, depth: 200, height: 500 },
  });
  const aboveBoundary = boundaryPanelBoards(aboveAvoidH).find((board) => board.source === "boundary-side-drawer");
  assert.equal(aboveBoundary?.boardType, "full_zi");
  assert(ziSlotFeatures(aboveAvoidH).filter(
    (feature) => feature.boundaryId === "boundary-side-drawer" && (feature.targetBoardId === "V1" || feature.targetBoardId === "V2"),
  ).every((feature) => feature.y0 === 100 && feature.y1 === 150));
  assert(ziSlotFeatures(aboveAvoidH).filter(
    (feature) => feature.boundaryId === "boundary-side-drawer" && (feature.targetBoardId === "V3" || feature.targetBoardId === "V4"),
  ).every(
    (feature) => feature.boundaryType === "full_zi" && feature.y0 === 0 && feature.y1 === 50,
  ));

  const intersectsAvoidH = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      zone("drawer", "drawer", 500),
      zone("open", "open_space", 900),
    ]),
    avoidance: { enabled: true, depth: 200, height: 700 },
  });
  const intersectingBoundary = boundaryPanelBoards(intersectsAvoidH).find((board) => board.source === "boundary-side-drawer");
  assert.equal(intersectingBoundary?.boardType, "shortened_zi");
  assert.equal(intersectingBoundary?.y1, intersectsAvoidH.debug.midDepth - 200);
  assert(ziSlotFeatures(intersectsAvoidH).filter(
    (feature) => feature.boundaryId === "boundary-side-drawer" && (feature.targetBoardId === "V1" || feature.targetBoardId === "V2"),
  ).every((feature) => feature.y0 === 100 && feature.y1 === 150));
  assert.equal(ziSlotFeatures(intersectsAvoidH).filter(
    (feature) => feature.boundaryId === "boundary-side-drawer" && (feature.targetBoardId === "V3" || feature.targetBoardId === "V4"),
  ).length, 0);

  const partialCrossing = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      zone("drawer", "drawer", 500),
      zone("open", "open_space", 900),
    ]),
    avoidance: { enabled: true, depth: 200, height: 675 },
  });
  assert.equal(
    boundaryPanelBoards(partialCrossing).find((board) => board.source === "boundary-side-drawer")?.boardType,
    "shortened_zi",
  );
}

function testAvoidanceHeightValidationAndProtectedTypes() {
  const negativeHeight = generateGeneralTallCabinet({
    ...baseParams([zone("side", "side_door", 600), zone("drawer", "drawer", 500), zone("open", "open_space", 900)]),
    avoidance: { enabled: true, depth: 200, height: -1 },
  });
  assert(negativeHeight.validation.errors.some((error) => error.includes("Avoidance height must be >= 0.")));
  assert.equal(boundaryPanelBoards(negativeHeight).filter((board) => board.boardType === "shortened_zi").length, 0);

  const overflowHeight = generateGeneralTallCabinet({
    ...baseParams([zone("side", "side_door", 600), zone("drawer", "drawer", 500), zone("open", "open_space", 900)]),
    avoidance: { enabled: true, depth: 200, height: 3000 },
  });
  assert(overflowHeight.validation.warnings.some((warning) =>
    warning.includes("Avoidance height exceeds cabinet height; affected range capped to CH for overlap tests."),
  ));
  assert(boundaryPanelBoards(overflowHeight).some((board) => board.boardType === "shortened_zi"));

  const halfZi = generateGeneralTallCabinet({
    ...baseParams([zone("drawer-a", "drawer", 600), zone("drawer-b", "drawer", 500), zone("open", "open_space", 900)]),
    avoidance: { enabled: true, depth: 200, height: 700 },
  });
  assert.equal(boundaryPanelBoards(halfZi).find((board) => board.source === "boundary-drawer-a-drawer-b")?.boardType, "half_zi");
}

function testShortenedZiSmallDepthWarnsAndFallsBackSafely() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      zone("drawer", "drawer", 500),
      zone("open", "open_space", 900),
    ]),
    avoidance: { enabled: true, depth: 480, height: 700 },
  });
  const shortened = boundaryPanelBoards(result).find((board) => board.boardType === "shortened_zi");

  assert(shortened, "shortened_zi board missing");
  assert.equal(shortened.y1, result.debug.midDepth - 480);
  assert(result.validation.warnings.some((warning) =>
    warning.includes("shortened_zi ShortDepth below 150mm; exact notch geometry may be invalid."),
  ));
  assert.deepEqual(shortened.profileVector, xyRectangle(shortened));
  assert(shortened.notes?.includes("Exact shortened_zi notched outer profile implemented; rear connection omitted."));
}

function testOverlappingZiSlotsReportWarning() {
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("side", "side_door", 600),
      zone("drawer-a", "drawer", 0.5),
      zone("drawer-b", "drawer", 1200),
    ]),
  );

  assert(result.validation.warnings.some((warning) => warning.includes("Overlapping zi_slot profileFeatures")));
  assert(vBoards(result).every((board) => board.cutProfileVector));
}

function testAvoidanceDoesNotShortenDoubleDoorDividerSupportZi() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      { ...zone("double", "double_door", 600), verticalDivider: true },
      zone("drawer", "drawer", 400),
      zone("open", "open_space", 390),
    ]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    dividerThickness: 15,
    avoidance: { enabled: true, depth: 200, height: 2000 },
  });

  assert.deepEqual(
    boundaryPanelBoards(result).map((board) => [board.source, board.boardType]),
    [
      ["boundary-side-double", "full_zi"],
      ["boundary-double-drawer", "full_zi"],
      ["boundary-drawer-open", "shortened_zi"],
    ],
  );
  assert(ziGrooveFeatures(result).every((feature) => {
    const target = result.boards.find((board) => board.id === feature.targetBoardId);
    return target?.boardType === "full_zi";
  }));
  assert(ziGrooveFeatures(result).every((feature) => {
    const target = result.boards.find((board) => board.id === feature.targetBoardId);
    return target && JSON.stringify(target.profileVector) === JSON.stringify(fullZiProfile(result.debug.midWidth, result.debug.midDepth));
  }));
}

function testInvalidAvoidanceDepthReportsValidation() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      zone("drawer", "drawer", 500),
      zone("open", "open_space", 900),
    ]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    avoidance: { enabled: true, depth: 700 },
  });

  assert(result.validation.errors.some((error) => error.includes("Avoidance ShortDepth must be > 0")));
  assert.equal(boundaryPanelBoards(result).filter((board) => board.boardType === "shortened_zi").length, 0);
  assert(result.boards.length > 0);
}

function testVerticalDividerSkeletonDefaultCenter() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      { ...zone("double", "double_door", 600), verticalDivider: true },
      zone("drawer", "drawer", 400),
      zone("open", "open_space", 390),
    ]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    dividerThickness: 15,
  });
  const dividerBoards = verticalDividerBoards(result);
  const doubleZoneItem = result.stacking.items.find((item) => item.type === "functional_zone" && item.zoneId === "double");

  assert.equal(result.debug.midWidth, 668);
  assert.equal(result.debug.midDepth, 584);
  assert.equal(dividerBoards.length, 1);
  assert(doubleZoneItem);
  assert.deepEqual(
    {
      id: dividerBoards[0].id,
      name: dividerBoards[0].name,
      category: dividerBoards[0].category,
      boardType: dividerBoards[0].boardType,
      materialThickness: dividerBoards[0].materialThickness,
      profilePlane: dividerBoards[0].profilePlane,
      thicknessAxis: dividerBoards[0].thicknessAxis,
      x0: dividerBoards[0].x0,
      x1: dividerBoards[0].x1,
      y0: dividerBoards[0].y0,
      y1: dividerBoards[0].y1,
      z0: dividerBoards[0].z0,
      z1: dividerBoards[0].z1,
    },
    {
      id: "VD_double",
      name: "Vertical Divider double",
      category: "vertical_divider",
      boardType: "vertical_divider",
      materialThickness: 15,
      profilePlane: "YZ",
      thicknessAxis: "X",
      x0: 342.5,
      x1: 357.5,
      y0: 0,
      y1: 584,
      z0: doubleZoneItem.z0,
      z1: doubleZoneItem.z1,
    },
  );
  assert(dividerBoards[0].notes?.includes("Vertical divider skeleton"));
  assert(dividerBoards[0].notes?.includes("Tongue/groove features deferred"));
  assert(dividerBoards[0].notes?.includes("H34 clearance slot deferred"));
}

function testVerticalDividerCustomCenter() {
  const result = generateGeneralTallCabinet({
    ...baseParams([{ ...zone("double", "double_door", 1975), verticalDivider: true, dividerCenterX: 300 }]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    dividerThickness: 15,
  });
  const divider = verticalDividerBoards(result)[0];

  assert.equal(divider.x0, 308.5);
  assert.equal(divider.x1, 323.5);
}

function testVerticalDividerInvalidCenterValidation() {
  const result = generateGeneralTallCabinet({
    ...baseParams([{ ...zone("double", "double_door", 1975), verticalDivider: true, dividerCenterX: 3 }]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    dividerThickness: 15,
  });

  assert(result.validation.errors.some((error) => error.includes("outside MidWidth")));
}

function testDoubleDoorWithoutVerticalDividerGeneratesNoDivider() {
  const result = generateGeneralTallCabinet(baseParams([zone("double", "double_door", 1975)]));
  const types = boardTypes(result);

  assert.equal(verticalDividerBoards(result).length, 0);
  assert.equal(ziGrooveFeatures(result).length, 0);
  assert.equal(h34ClearanceSlotFeatures(result).length, 0);
  assert(!types.includes("door_panel"));
  assert(!types.includes("drawer_front"));
  assert(!types.includes("hardware_hole"));
  assert(!types.includes("zi_groove"));
  assert(!types.includes("h34_clearance_slot"));
}

function testVBoardSideProfileSingleZoneAndStyle2() {
  const singleZone = generateGeneralTallCabinet(baseParams([zone("open", "open_space", 1975)]));
  for (const vBoard of vBoards(singleZone)) {
    assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "zi_slot").length, 0);
    if (vBoard.id === "V1" || vBoard.id === "V2") {
      assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_top_insert_slot").length, 1);
      assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_bottom_insert_slot").length, 1);
    } else {
      assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_top_insert_slot").length, 0);
      assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_bottom_insert_slot").length, 0);
    }
  }

  const style2 = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      zone("drawer", "drawer", 400),
      zone("open", "open_space", 900),
    ]),
    topSystem: { style: "style_2", height: 80 },
    bottomSystem: { style: "style_2", height: 100 },
  });
  for (const vBoard of vBoards(style2)) {
    assert(vBoard.profileVector);
    if (vBoard.id === "V1" || vBoard.id === "V2") {
      assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_top_insert_slot").length, 1);
      assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_bottom_insert_slot").length, 1);
    } else {
      assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_top_insert_slot").length, 0);
      assert.equal(vBoard.profileFeatures?.filter((feature) => feature.type === "style1_bottom_insert_slot").length, 0);
    }
    assert((vBoard.profileFeatures?.filter((feature) => feature.type === "zi_slot").length ?? 0) > 0);
    if (vBoard.id === "V1" || vBoard.id === "V2") {
      assert(hasPoint(vBoard.cutProfileVector, { y: 105, z: 0 }));
      assert(hasPoint(vBoard.cutProfileVector, { y: 105, z: 16 }));
      assert(hasPoint(vBoard.cutProfileVector, { y: 105, z: 2100 }));
      assert(hasPoint(vBoard.cutProfileVector, { y: 105, z: 2100 - 16 }));
      assert(!hasSegment(vBoard.cutProfileVector, { y: 0, z: 0 }, { y: 105, z: 0 }));
      assert(!hasSegment(vBoard.cutProfileVector, { y: 0, z: 2100 }, { y: 105, z: 2100 }));
    } else {
      for (let i = 1; i < (vBoard.cutProfileVector?.length ?? 0); i += 1) {
        const prev = vBoard.cutProfileVector?.[i - 1];
        const curr = vBoard.cutProfileVector?.[i];
        assert(prev && curr);
        assert(prev.y === curr.y || prev.z === curr.z, `${vBoard.id} has non-orthogonal segment at ${i - 1}->${i}`);
      }
    }
  }
}

function testZiGroovesForDoubleDoorDivider() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      { ...zone("double", "double_door", 600), verticalDivider: true },
      zone("drawer", "drawer", 400),
      zone("open", "open_space", 390),
    ]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    dividerThickness: 15,
  });
  const grooves = ziGrooveFeatures(result);

  assert.equal(verticalDividerBoards(result).length, 1);
  assert.equal(grooves.length, 2);
  assert.deepEqual(
    grooves.map((feature) => [feature.boundaryId, feature.face]).sort(),
    [
      ["boundary-double-drawer", "top"],
      ["boundary-side-double", "bottom"],
    ],
  );
  assert(grooves.every((feature) => feature.type === "zi_groove"));
  assert(grooves.every((feature) => feature.dividerBoardId === "VD_double"));
  assert(grooves.every((feature) => feature.zoneId === "double"));
  assert(grooves.every((feature) => feature.depth === 8)); // CPT 16 / 2
  assert(grooves.every((feature) => feature.x0 === 326));
  assert(grooves.every((feature) => feature.x1 === 342));
  assert(grooves.every((feature) => feature.y0 === result.debug.midDepth / 3 - 5));
  assert(grooves.every((feature) => feature.y1 === (result.debug.midDepth * 2) / 3 + 5));
  assert(grooves.every((feature) => {
    const target = result.boards.find((board) => board.id === feature.targetBoardId);
    return target?.boardType === "full_zi";
  }));
  assert(!grooves.some((feature) => feature.targetBoardId.includes("half")));
  assert(!boardTypes(result).includes("door_panel"));
  assert(!boardTypes(result).includes("drawer_front"));
  assert(!boardTypes(result).includes("hardware_hole"));
}

function testDividerTongueFeaturePlaceholders() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      { ...zone("double", "double_door", 600), verticalDivider: true },
      zone("drawer", "drawer", 400),
      zone("open", "open_space", 390),
    ]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    dividerThickness: 15,
  });
  const divider = verticalDividerBoards(result)[0];
  const grooves = ziGrooveFeatures(result);
  const tongues = dividerTongueFeatures(result);
  const tongueY0 = result.debug.midDepth / 3;
  const tongueY1 = (result.debug.midDepth * 2) / 3;

  assert.equal(grooves.length, 2);
  assert.equal(tongues.length, 2);
  assert.deepEqual(tongues.map((feature) => feature.position).sort(), ["bottom", "top"]);
  assert(tongues.every((feature) => feature.targetBoardId === "VD_double"));
  assert(tongues.every((feature) => feature.y0 === tongueY0 && feature.y1 === tongueY1));
  assert(tongues.every((feature) => feature.insertionDepth === 7.5)); // CPT 16 / 2 - 0.5
  assert(tongues.every((feature) => feature.notes?.includes("Divider tongue placeholder generated from zi_groove")));
  assert(tongues.every((feature) => feature.notes?.includes("Exact tongue outline deferred")));
  assert(tongues.every((feature) => feature.notes?.includes("Zi groove real cutting deferred")));

  const topTongue = tongues.find((feature) => feature.position === "top");
  const bottomTongue = tongues.find((feature) => feature.position === "bottom");
  assert(topTongue);
  assert(bottomTongue);
  assert.deepEqual([topTongue.z0, topTongue.z1], [divider.z1 - 7.5, divider.z1]);
  assert.deepEqual([bottomTongue.z0, bottomTongue.z1], [divider.z0, divider.z0 + 7.5]);
  assert.equal(topTongue.relatedGrooveFeatureId, grooves.find((feature) => feature.face === "bottom")?.id);
  assert.equal(bottomTongue.relatedGrooveFeatureId, grooves.find((feature) => feature.face === "top")?.id);
  assert.equal(topTongue.relatedZiBoardId, grooves.find((feature) => feature.face === "bottom")?.targetBoardId);
  assert.equal(bottomTongue.relatedZiBoardId, grooves.find((feature) => feature.face === "top")?.targetBoardId);
  assert.equal(topTongue.zoneId, "double");
  assert.equal(bottomTongue.zoneId, "double");
  assert.equal(topTongue.boundaryId, "boundary-side-double");
  assert.equal(bottomTongue.boundaryId, "boundary-double-drawer");

  assert.equal(divider.profileFeatures?.some((feature) => feature.type === "divider_tongue"), true);
  assert(divider.cutProfileVector);
  assert(!hasPoint(divider.cutProfileVector, { y: tongueY0, z: divider.z0 + 7 }));
  for (const tongue of tongues) {
    const ziBoard = result.boards.find((board) => board.id === tongue.relatedZiBoardId);
    assert.equal(ziBoard?.boardType, "full_zi");
    assert.deepEqual(ziBoard?.profileVector, fullZiProfile(result.debug.midWidth, result.debug.midDepth));
  }
}

function testDefaultVerticalDividerBottomTongueCutProfile() {
  const result = generateGeneralTallCabinet(uiDefaultParams());
  const divider = verticalDividerBoards(result).find((board) => board.id === "VD_zone-3");
  const tongue = dividerTongueFeatures(result).find((feature) => feature.targetBoardId === "VD_zone-3");
  assert(divider, "VD_zone-3 missing");
  assert(tongue, "VD_zone-3 divider_tongue missing");
  const groove = ziGrooveFeatures(result).find((feature) => feature.id === tongue.relatedGrooveFeatureId);
  const relatedZi = result.boards.find((board) => board.id === tongue.relatedZiBoardId);
  assert(groove, "related zi_groove missing");
  assert(relatedZi, "related Zi board missing");
  assert.equal(relatedZi.z1, divider.z0);

  const tongueZ0 = divider.z0 - tongue.insertionDepth;
  assert.equal(tongueZ0, 991.5); // divider z0 999 - (CPT 16 / 2 - 0.5)
  assert.deepEqual(vectorRange(divider.cutProfileVector!), { minY: 0, maxY: 568, minZ: 991.5, maxZ: 1944 });
  assert(hasOrderedSequence(divider.cutProfileVector, [
    { y: 0, z: divider.z0 },
    { y: groove.y0, z: divider.z0 },
    { y: groove.y0, z: tongueZ0 },
    { y: groove.y1, z: tongueZ0 },
    { y: groove.y1, z: divider.z0 },
  ]));
  assert(divider.profileFeatures?.some((feature) =>
    feature.type === "divider_tongue" &&
    feature.y0 === groove.y0 &&
    feature.y1 === groove.y1 &&
    feature.z0 === tongueZ0 &&
    feature.z1 === divider.z0 &&
    feature.source === "divider_tongue_effective_cut"
  ));
  assert(divider.notes?.includes("Bottom divider tongue implemented in cutProfileVector; Zi groove remains face machining."));
  assert(hasOrderedSequence(divider.cutProfileVector, [
    { y: 552, z: 999 },
    { y: 552, z: 1104 },
    { y: 568, z: 1104 },
  ]));
  assert(divider.profileFeatures?.some((feature) =>
    feature.type === "h34_clearance_slot" &&
    feature.z0 === divider.z0 &&
    feature.z1 === 1104
  ));
  assert(!divider.profileFeatures?.some((feature) =>
    feature.type === "divider_tongue" &&
    feature.z0 >= divider.z1
  ));
}

function testDividerTongueBoundaryCases() {
  const first = generateGeneralTallCabinet(
    baseParams([
      { ...zone("double", "double_door", 700), verticalDivider: true },
      zone("drawer", "drawer", 500),
      zone("open", "open_space", 700),
    ]),
  );
  assert.equal(ziGrooveFeatures(first).length, 1);
  assert.equal(dividerTongueFeatures(first).length, 1);
  assert.equal(dividerTongueFeatures(first)[0].position, "bottom");

  const last = generateGeneralTallCabinet(
    baseParams([
      zone("drawer", "drawer", 500),
      { ...zone("double", "double_door", 700), verticalDivider: true },
    ]),
  );
  assert.equal(ziGrooveFeatures(last).length, 1);
  assert.equal(dividerTongueFeatures(last).length, 1);
  assert.equal(dividerTongueFeatures(last)[0].position, "top");

  const withoutDivider = generateGeneralTallCabinet(baseParams([zone("double", "double_door", 1975)]));
  assert.equal(ziGrooveFeatures(withoutDivider).length, 0);
  assert.equal(dividerTongueFeatures(withoutDivider).length, 0);
}

function testH34ClearanceSlotFeaturesForVerticalDivider() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 600),
      { ...zone("double", "double_door", 600), verticalDivider: true },
      zone("drawer", "drawer", 400),
      zone("open", "open_space", 390),
    ]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    dividerThickness: 15,
  });
  const slots = h34ClearanceSlotFeatures(result);

  assert.equal(verticalDividerBoards(result).length, 1);
  assert.equal(hSupportBoards(result).filter((board) => board.boardType === "H34").length, 2);
  assert.equal(slots.length, 2);
  assert.deepEqual(
    slots.map((feature) => feature.h34BoardId).sort(),
    ["H34_bottom", "H34_mid"],
  );
  assert(slots.every((feature) => feature.targetBoardId === "VD_double"));
  assert(slots.every((feature) => feature.y0 === 568));
  assert(slots.every((feature) => feature.y1 === 584));
  assert.deepEqual(
    slots.map((feature) => [feature.h34BoardId, feature.z0, feature.z1]).sort(),
    [
      ["H34_bottom", -5, 105],
      ["H34_mid", 995, 1105],
    ],
  );
  assert(!result.validation.warnings.some((warning) => warning.includes("H34 clearance slot extends outside divider Z range")));
  assert(result.debug.h34Clearance?.some((item) =>
    item.dividerBoardId === "VD_double" &&
    item.h34BoardId === "H34_bottom" &&
    item.action === "placeholder_outside_divider_range"
  ));
  assert(slots.every((feature) => feature.notes?.includes("Exact H34/divider interaction deferred")));

  const divider = verticalDividerBoards(result)[0];
  const effectiveCuts = divider.profileFeatures?.filter((feature) => feature.type === "h34_clearance_slot") ?? [];
  assert.deepEqual(divider.profileVector, yzRectangle(divider));
  assert(divider.cutProfileVector);
  assert.deepEqual(divider.cutProfileVector?.at(0), { y: 0, z: divider.z0 });
  assert.deepEqual(divider.cutProfileVector?.at(-1), { y: 0, z: divider.z0 });
  assert.equal(effectiveCuts.length, 1);
  assert(effectiveCuts.some((feature) =>
    feature.type === "h34_clearance_slot" &&
    feature.y0 === 568 &&
    feature.y1 === 584 &&
    feature.z0 === 995 &&
    feature.z1 === 1105 &&
    feature.source === "h34_clearance_slot_effective_cut" &&
    feature.h34BoardId === "H34_mid"
  ));
  assert(effectiveCuts[0].notes?.includes("Clamped effective H34 clearance cut on vertical divider"));
  assert(effectiveCuts[0].notes?.includes("Original placeholder remains in top-level features"));
  assert(
    hasOrderedSequence(divider.cutProfileVector, [
      { y: 584, z: 995 },
      { y: 568, z: 995 },
      { y: 568, z: 1105 },
      { y: 584, z: 1105 },
    ]),
  );
  assert(!hasPoint(divider.cutProfileVector, { y: 568, z: -5 }));
  assert(!hasPoint(divider.cutProfileVector, { y: 568, z: 2105 }));
  assert(!result.validation.warnings.some((warning) => warning.includes("H34 clearance slot has no intersection")));
  assert(result.debug.h34Clearance?.some((item) =>
    item.dividerBoardId === "VD_double" &&
    item.h34BoardId === "H34_bottom" &&
    item.action === "cut_skipped_no_intersection"
  ));
  for (const h34Board of hSupportBoards(result).filter((board) => board.boardType === "H34")) {
    assert.equal(h34Board.profileVector, undefined);
    assert.equal(h34Board.cutProfileVector, undefined);
    assert.equal(h34Board.profileFeatures, undefined);
  }
}

function testZiGrooveFirstDoubleDoorOnlyLowerBoundary() {
  const result = generateGeneralTallCabinet(
    baseParams([
      { ...zone("double", "double_door", 700), verticalDivider: true },
      zone("drawer", "drawer", 500),
      zone("open", "open_space", 700),
    ]),
  );
  const grooves = ziGrooveFeatures(result);

  assert.equal(grooves.length, 1);
  assert.equal(grooves[0].boundaryId, "boundary-double-drawer");
  assert.equal(grooves[0].face, "top");
}

function testZiGrooveLastDoubleDoorOnlyUpperBoundary() {
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("drawer", "drawer", 500),
      { ...zone("double", "double_door", 700), verticalDivider: true },
    ]),
  );
  const grooves = ziGrooveFeatures(result);

  assert.equal(grooves.length, 1);
  assert.equal(grooves[0].boundaryId, "boundary-drawer-double");
  assert.equal(grooves[0].face, "bottom");
}

function testSingleZoneGeneratesNoBoundarySlots() {
  const result = generateGeneralTallCabinet(baseParams([zone("open", "open_space", 1975)]));

  assert.equal(result.boards.filter((board) => board.category === "boundary_panel").length, 0);
  assert.equal(ziSlotFeatures(result).length, 0);
}

function testMergeCandidateDetectionOnly() {
  const noMerge = generateGeneralTallCabinet(baseParams([zone("open", "open_space", 1975)]));

  assert(noMerge.debug.mergeAndConflict);
  assert.equal(noMerge.debug.mergeAndConflict.topMergeCandidate, false);
  assert.equal(noMerge.debug.mergeAndConflict.bottomMergeCandidate, false);
  assert.equal(noMerge.debug.mergeAndConflict.depthGap, noMerge.debug.midDepth - 210);
  assert(!noMerge.validation.warnings.some((warning) => warning.includes("Top/bottom merge candidate detected")));

  const mergeCandidate = generateGeneralTallCabinet({
    ...baseParams([zone("open", "open_space", 1975)]),
    cabinetDepth: 260,
  });

  assert.equal(mergeCandidate.debug.midDepth, 244);
  assert.equal(mergeCandidate.debug.mergeAndConflict?.topMergeCandidate, true);
  assert.equal(mergeCandidate.debug.mergeAndConflict?.bottomMergeCandidate, true);
  assert.equal(mergeCandidate.debug.mergeAndConflict?.depthGap, 34);
  assert(
    mergeCandidate.validation.warnings.some((warning) =>
      warning.includes("Top/bottom merge candidate detected: MidDepth front/rear gap is below 50mm"),
    ),
  );
  assert(!boardTypes(mergeCandidate).includes("TopMergedBoard"));
  assert(!boardTypes(mergeCandidate).includes("BottomMergedBoard"));
  assert.deepEqual(
    ["H13_top", "H24_top"].map((id) => {
      const board = mergeCandidate.boards.find((candidate) => candidate.id === id);
      return [id, board?.z0, board?.z1];
    }),
    [
      ["H13_top", 2000, 2100],
      ["H24_top", 2000, 2100],
    ],
  );
}

function testHMidFullZiConflictMovement() {
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("side", "side_door", 930),
      zone("drawer", "drawer", 500),
      zone("open", "open_space", 600),
    ]),
  );

  assert(result.validation.warnings.some((warning) => warning.includes("H mid overlaps full_zi; Stage 2 movement evaluated.")));
  assert(result.debug.mergeAndConflict?.hZiConflicts.some((conflict) =>
    conflict.ziBoardType === "full_zi" &&
    conflict.hBoardId === "H13_mid" &&
    conflict.overlapZ0 === 1000 &&
    conflict.overlapZ1 === 1014 &&
    conflict.moved === true &&
    conflict.originalZ0 === 1000 &&
    conflict.originalZ1 === 1100 &&
    conflict.newZ0 === 899 &&
    conflict.newZ1 === 999 &&
    conflict.movementDirection === "below"
  ));
  assert.deepEqual(hMidZRanges(result), [
    ["H13_mid", 899, 999],
    ["H24_mid", 899, 999],
    ["H34_mid", 1014, 1114],
  ]);
  assert(result.boards.find((board) => board.id === "H13_mid")?.notes?.includes("Moved below Zi conflict by Stage 2 H conflict adjustment"));
  assert(result.boards.find((board) => board.id === "H24_mid")?.notes?.includes("Moved below Zi conflict by Stage 2 H conflict adjustment"));
  assert(result.boards.find((board) => board.id === "H34_mid")?.notes?.includes("Moved above Zi conflict by Stage 2 H conflict adjustment"));
}

function testHMidShortenedZiConflictMovement() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 930),
      zone("drawer", "drawer", 500),
      zone("open", "open_space", 600),
    ]),
    avoidance: { enabled: true, depth: 200, height: 1200 },
  });

  assert(result.validation.warnings.some((warning) => warning.includes("H mid overlaps shortened_zi; Stage 2 movement evaluated.")));
  assert(result.debug.mergeAndConflict?.hZiConflicts.some((conflict) => conflict.ziBoardType === "shortened_zi" && conflict.moved));
  assert.deepEqual(hMidZRanges(result), [
    ["H13_mid", 899, 999],
    ["H24_mid", 899, 999],
    ["H34_mid", 1014, 1114],
  ]);
}

function testHMidHalfZiConflictDetectionOnly() {
  const result = generateGeneralTallCabinet(
    baseParams([
      zone("drawer-a", "drawer", 930),
      zone("drawer-b", "drawer", 500),
      zone("open", "open_space", 600),
    ]),
  );

  assert(result.validation.warnings.some((warning) =>
    warning.includes("H mid overlaps half_zi; half Zi movement rule deferred."),
  ));
  assert(result.debug.mergeAndConflict?.hZiConflicts.some((conflict) =>
    conflict.ziBoardType === "half_zi" && conflict.action === "half_zi_rule_deferred"
  ));
  assert.deepEqual(hMidZRanges(result), [
    ["H13_mid", 1000, 1100],
    ["H24_mid", 1000, 1100],
    ["H34_mid", 1000, 1100],
  ]);
}

function testHMidMovementBelowBoundsSkipped() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 30),
      zone("drawer", "drawer", 100),
      zone("open", "open_space", 141),
    ]),
    cabinetHeight: 300,
  });

  assert(result.validation.warnings.some((warning) =>
    warning.includes("H mid movement below Zi would exceed cabinet bounds; movement skipped."),
  ));
  assert(result.debug.mergeAndConflict?.hZiConflicts.some((conflict) =>
    conflict.hBoardId === "H13_mid" &&
    conflict.moved === false &&
    conflict.newZ0 === -1 &&
    conflict.newZ1 === 99 &&
    conflict.skippedReason === "below_bounds"
  ));
  assert.deepEqual(hMidZRanges(result), [
    ["H13_mid", 100, 200],
    ["H24_mid", 100, 200],
    ["H34_mid", 114, 214],
  ]);
}

function testH34MidMovementAboveBoundsSkipped() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 117),
      zone("drawer", "drawer", 100),
      zone("open", "open_space", 54),
    ]),
    cabinetHeight: 300,
  });

  assert(result.validation.warnings.some((warning) =>
    warning.includes("H34 mid movement above Zi would exceed cabinet bounds; movement skipped."),
  ));
  assert(result.debug.mergeAndConflict?.hZiConflicts.some((conflict) =>
    conflict.hBoardId === "H34_mid" &&
    conflict.moved === false &&
    conflict.newZ0 === 201 &&
    conflict.newZ1 === 301 &&
    conflict.skippedReason === "above_bounds"
  ));
  assert.deepEqual(hMidZRanges(result), [
    ["H13_mid", 86, 186],
    ["H24_mid", 86, 186],
    ["H34_mid", 100, 200],
  ]);
}

function testH34ClearanceFollowsMovedH34Mid() {
  const result = generateGeneralTallCabinet({
    ...baseParams([
      zone("side", "side_door", 930),
      { ...zone("double", "double_door", 500), verticalDivider: true },
      zone("drawer", "drawer", 515),
    ]),
    cabinetWidth: 700,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    dividerThickness: 15,
  });
  const h34Mid = result.boards.find((board) => board.id === "H34_mid");
  const midSlot = h34ClearanceSlotFeatures(result).find((feature) => feature.h34BoardId === "H34_mid");
  const divider = verticalDividerBoards(result)[0];

  assert.deepEqual([h34Mid?.z0, h34Mid?.z1], [1014, 1114]);
  assert.deepEqual([midSlot?.z0, midSlot?.z1], [1009, 1119]);
  assert(
    hasOrderedSequence(divider.cutProfileVector, [
    { y: 568, z: 1014 },
    { y: 568, z: 1119 },
    { y: 584, z: 1119 },
    ]),
  );
  assert(divider.profileFeatures?.some((feature) =>
    feature.type === "h34_clearance_slot" &&
    feature.h34BoardId === "H34_mid"
  ));
  assert(!hasPoint(divider.cutProfileVector, { y: 568, z: 995 }));
  assert(!hasPoint(divider.cutProfileVector, { y: 568, z: 1105 }));
}

function testSidePanelsDisabledByDefaultAndZeroThickness() {
  const baseline = generateGeneralTallCabinet(uiDefaultParams());
  const explicitDisabled = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    leftSidePanelThickness: 0,
    rightSidePanelThickness: 0,
  });

  assert.equal(sidePanelBoards(baseline).length, 0);
  assert.equal(sidePanelBoards(explicitDisabled).length, 0);
  assert.equal(explicitDisabled.boards.length, baseline.boards.length);
}

function testSidePanelsBothEnabled() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
  });
  const left = result.boards.find((board) => board.id === "SidePanel_L");
  const right = result.boards.find((board) => board.id === "SidePanel_R");
  const disabledCount = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    leftSidePanelThickness: 0,
    rightSidePanelThickness: 0,
  }).boards.length;

  assert(left);
  assert(right);
  assert.equal(result.boards.length, disabledCount + 2);
  assert.deepEqual(
    {
      category: left.category,
      boardType: left.boardType,
      materialThickness: left.materialThickness,
      profilePlane: left.profilePlane,
      thicknessAxis: left.thicknessAxis,
      x0: left.x0,
      x1: left.x1,
      y0: left.y0,
      y1: left.y1,
      z0: left.z0,
      z1: left.z1,
      profileVector: left.profileVector,
    },
    {
      category: "side_panel",
      boardType: "side_panel",
      materialThickness: 16,
      profilePlane: "YZ",
      thicknessAxis: "X",
      x0: 0,
      x1: 16,
      y0: -16,
      y1: 568,
      z0: 0,
      z1: 2000,
      profileVector: sidePanelProfile(584, 2000),
    },
  );
  assert.deepEqual(
    {
      category: right.category,
      boardType: right.boardType,
      materialThickness: right.materialThickness,
      profilePlane: right.profilePlane,
      thicknessAxis: right.thicknessAxis,
      x0: right.x0,
      x1: right.x1,
      y0: right.y0,
      y1: right.y1,
      z0: right.z0,
      z1: right.z1,
      profileVector: right.profileVector,
    },
    {
      category: "side_panel",
      boardType: "side_panel",
      materialThickness: 16,
      profilePlane: "YZ",
      thicknessAxis: "X",
      x0: 584,
      x1: 600,
      y0: -16,
      y1: 568,
      z0: 0,
      z1: 2000,
      profileVector: sidePanelProfile(584, 2000),
    },
  );
  assert(left.notes?.includes("SidePanel_L generated from side panel thickness input."));
  assert(right.notes?.includes("SidePanel_R generated from side panel thickness input."));
  assert(result.debug.sidePanelOverlapAudit);
  assert(result.debug.sidePanelOverlapAudit.overlaps.every((item) => !item.overlaps));
  const v2 = result.boards.find((board) => board.id === "V2");
  assert(v2);
  // Middle-first: V sits inboard of the right skin (584..600), at 568..584.
  assert.equal(v2.x0, 568);
  assert.equal(v2.x1, 584);
  assert.equal(v2.y0, 16);
  assert.equal(v2.y1, 584);
  const v1 = result.boards.find((board) => board.id === "V1");
  assert(v1);
  assert.equal(v1.x0, 16);
  assert.equal(v1.x1, 32);
  assert.equal(v1.y0, 16);
  assert.equal(v1.y1, 584);
}

function testVCarcassYAlignsWithSidePanelWhenOnlyRightEnabled() {
  const result = generateGeneralTallCabinet({
    cabinetHeight: 1965,
    cabinetWidth: 370,
    cabinetDepth: 660,
    panelThickness: 16,
    frontPanelThickness: 16,
    sideClearance: 3,
    leftSidePanelThickness: 0,
    rightSidePanelThickness: 16,
    topSystem: { style: "style_1", frontRailHeight: 40 },
    bottomSystem: { style: "style_1", frontRailHeight: 53 },
    avoidance: { enabled: false },
    zones: [
      zone("zone-1", "left_side_door", 897),
      zone("zone-2", "left_side_door", 897),
    ],
  });
  const sidePanel = result.boards.find((board) => board.id === "SidePanel_R");
  const v2 = result.boards.find((board) => board.id === "V2");
  assert(sidePanel);
  assert(v2);
  assert.equal(sidePanel.y0, -16);
  assert.equal(v2.y0, 16);
  assert.equal(v2.y1, 660);
  assert.equal(v2.y0 - sidePanel.y0, 32);
  // Right skin at 354..370; V2 inboard at 338..354.
  assert.equal(sidePanel.x0, 354);
  assert.equal(sidePanel.x1, 370);
  assert.equal(v2.x0, 338);
  assert.equal(v2.x1, 354);
  assert(!(result.validation.warnings || []).some((warning) => warning.includes("differs from expected carcass start")));
}

function testSidePanelOneSideEnabled() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 0,
  });

  assert(result.boards.find((board) => board.id === "SidePanel_L"));
  assert.equal(result.boards.find((board) => board.id === "SidePanel_R"), undefined);
  const v1 = result.boards.find((board) => board.id === "V1");
  const v2 = result.boards.find((board) => board.id === "V2");
  const t3 = result.boards.find((board) => board.id === "T3");
  assert(v1);
  assert(v2);
  // Left skin outside; middle carcass insert-joins both V faces the same way.
  assert.equal(v1.x0, 16);
  assert.equal(v1.x1, 32);
  assert.equal(v2.x0, 584);
  assert.equal(v2.x1, 600);
  if (t3) {
    assert.equal(t3.x0, 16);
    assert.equal(t3.x1, 600);
    assert.equal(t3.x0, v1.x0);
    assert.equal(t3.x1, v2.x1);
  }
}

function testSidePanelAvoidanceNotchAppliedWhenAdaptEnabled() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    leftSidePanelAdaptAvoidance: true,
    rightSidePanelAdaptAvoidance: true,
    avoidance: { enabled: true, depth: 200, height: 400 },
  });
  const left = result.boards.find((board) => board.id === "SidePanel_L");
  const right = result.boards.find((board) => board.id === "SidePanel_R");
  assert(left);
  assert(right);
  assert.deepEqual(left.profileVector, sidePanelNotchedProfile(584, 2000, 200, 400));
  assert.deepEqual(right.profileVector, sidePanelNotchedProfile(584, 2000, 200, 400));
}

function testSidePanelAdaptAvoidancePerSide() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    leftSidePanelAdaptAvoidance: false,
    rightSidePanelAdaptAvoidance: true,
    avoidance: { enabled: true, depth: 200, height: 400 },
  });
  const left = result.boards.find((board) => board.id === "SidePanel_L");
  const right = result.boards.find((board) => board.id === "SidePanel_R");
  assert(left);
  assert(right);
  assert.deepEqual(left.profileVector, sidePanelProfile(584, 2000));
  assert.deepEqual(right.profileVector, sidePanelNotchedProfile(584, 2000, 200, 400));
}

function testAvoidanceSupportBoardsGenerated() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    avoidance: { enabled: true, depth: 200, height: 400 },
  });
  const horizontal = result.boards.find((board) => board.id === "avoidance_horizontal");
  const vertical = result.boards.find((board) => board.id === "Avoidance_Vertical");
  assert(horizontal);
  assert(vertical);
  assert.deepEqual(
    {
      category: horizontal.category,
      boardType: horizontal.boardType,
      profilePlane: horizontal.profilePlane,
      thicknessAxis: horizontal.thicknessAxis,
      bbox: [horizontal.x0, horizontal.x1, horizontal.y0, horizontal.y1, horizontal.z0, horizontal.z1],
    },
    {
      category: "avoidance_support",
      boardType: "avoidance_horizontal",
      profilePlane: "XY",
      thicknessAxis: "Z",
      bbox: [16, 584, 384, 584, 385, 400],
    },
  );
  assert.deepEqual(
    {
      category: vertical.category,
      boardType: vertical.boardType,
      profilePlane: vertical.profilePlane,
      thicknessAxis: vertical.thicknessAxis,
      bbox: [vertical.x0, vertical.x1, vertical.y0, vertical.y1, vertical.z0, vertical.z1],
    },
    {
      category: "avoidance_support",
      boardType: "avoidance_vertical",
      profilePlane: "XZ",
      thicknessAxis: "Y",
      bbox: [16, 584, 384, 399, 0, 385],
    },
  );
}

function testVBoardStyleSemanticConsistencyAcrossStyleCombos() {
  const combos = [
    { name: "A", topSystem: { style: "style_1" as const, frontRailHeight: 40 }, bottomSystem: { style: "style_1" as const, frontRailHeight: 53 } },
    { name: "B", topSystem: { style: "style_1" as const, frontRailHeight: 40 }, bottomSystem: { style: "style_2" as const, height: 100 } },
    { name: "C", topSystem: { style: "style_2" as const, height: 80 }, bottomSystem: { style: "style_1" as const, frontRailHeight: 53 } },
    { name: "D", topSystem: { style: "style_2" as const, height: 80 }, bottomSystem: { style: "style_2" as const, height: 100 } },
  ];

  for (const combo of combos) {
    const result = generateGeneralTallCabinet({
      ...uiDefaultParams(),
      topSystem: combo.topSystem,
      bottomSystem: combo.bottomSystem,
      leftSidePanelThickness: 16,
      rightSidePanelThickness: 16,
      zones: [
        zone("zone-1", "side_door", 600),
        zone("zone-2", "drawer", 500),
        { ...zone("zone-3", "double_door", 690), verticalDivider: true },
      ],
    });
    const v1 = result.boards.find((board) => board.id === "V1");
    const v2 = result.boards.find((board) => board.id === "V2");
    const v3 = result.boards.find((board) => board.id === "V3");
    const v4 = result.boards.find((board) => board.id === "V4");
    assert(v1 && v2 && v3 && v4, `missing V boards for case ${combo.name}`);

    const getYRange = (board: NonNullable<typeof v1>) => {
      const points = (board.cutProfileVector && board.cutProfileVector.length > 0)
        ? board.cutProfileVector
        : ((board.profileVector as Array<{ y: number; z: number }> | undefined) ?? []);
      const ys = points.map((point) => point.y);
      return [Math.min(...ys), Math.max(...ys)] as const;
    };

    const [v1YMin, v1YMax] = getYRange(v1);
    const [v2YMin, v2YMax] = getYRange(v2);
    const [v3YMin, v3YMax] = getYRange(v3);
    const [v4YMin, v4YMax] = getYRange(v4);

    assert.equal(v1YMin, 0, `V1 Y min mismatch in case ${combo.name}`);
    assert.equal(v2YMin, 0, `V2 Y min mismatch in case ${combo.name}`);
    assert.equal(v3YMin, 0, `V3 Y min mismatch in case ${combo.name}`);
    assert.equal(v4YMin, 0, `V4 Y min mismatch in case ${combo.name}`);
    assert.equal(v1YMax, 150, `V1 Y max mismatch in case ${combo.name}`);
    assert.equal(v2YMax, 150, `V2 Y max mismatch in case ${combo.name}`);
    assert.equal(v3YMax, 150, `V3 Y max mismatch in case ${combo.name}`);
    assert.equal(v4YMax, 150, `V4 Y max mismatch in case ${combo.name}`);
    assert.equal(v3.y1 - v3.y0, 150, `V3 bbox depth mismatch in case ${combo.name}`);
    assert.equal(v4.y1 - v4.y0, 150, `V4 bbox depth mismatch in case ${combo.name}`);
    const hasStyle2Top = combo.topSystem.style === "style_2";
    const hasStyle2Bottom = combo.bottomSystem.style === "style_2";
    if (hasStyle2Top) {
      assert(hasPoint(v1.cutProfileVector, { y: 105, z: 2000 }), `V1 top style_2 notch missing in case ${combo.name}`);
      assert(hasPoint(v2.cutProfileVector, { y: 105, z: 2000 }), `V2 top style_2 notch missing in case ${combo.name}`);
      assert(hasPoint(v1.cutProfileVector, { y: 105, z: 2000 - 16 }), `V1 top style_2 notch depth missing in case ${combo.name}`);
      assert(hasPoint(v2.cutProfileVector, { y: 105, z: 2000 - 16 }), `V2 top style_2 notch depth missing in case ${combo.name}`);
      assert(!hasSegment(v1.cutProfileVector, { y: 0, z: 2000 }, { y: 105, z: 2000 }), `V1 top base edge remained in case ${combo.name}`);
      assert(!hasSegment(v2.cutProfileVector, { y: 0, z: 2000 }, { y: 105, z: 2000 }), `V2 top base edge remained in case ${combo.name}`);
      const expectedV34TopNotch = [
        { y: 150, z: 2000 - 105 },
        { y: 134, z: 2000 - 105 },
        { y: 134, z: 2000 - 16 },
        { y: 29, z: 2000 - 16 },
        { y: 29, z: 2000 },
        { y: 0, z: 2000 },
      ];
      assert(hasOrderedSequence(v3.cutProfileVector, expectedV34TopNotch), `V3 top style_2 notch sequence missing in case ${combo.name}`);
      assert(hasOrderedSequence(v4.cutProfileVector, expectedV34TopNotch), `V4 top style_2 notch sequence missing in case ${combo.name}`);
    }
    if (hasStyle2Bottom) {
      assert(hasPoint(v1.cutProfileVector, { y: 105, z: 0 }), `V1 bottom style_2 notch missing in case ${combo.name}`);
      assert(hasPoint(v2.cutProfileVector, { y: 105, z: 0 }), `V2 bottom style_2 notch missing in case ${combo.name}`);
      assert(hasPoint(v1.cutProfileVector, { y: 105, z: 16 }), `V1 bottom style_2 notch depth missing in case ${combo.name}`);
      assert(hasPoint(v2.cutProfileVector, { y: 105, z: 16 }), `V2 bottom style_2 notch depth missing in case ${combo.name}`);
      assert(!hasSegment(v1.cutProfileVector, { y: 0, z: 0 }, { y: 105, z: 0 }), `V1 bottom base edge remained in case ${combo.name}`);
      assert(!hasSegment(v2.cutProfileVector, { y: 0, z: 0 }, { y: 105, z: 0 }), `V2 bottom base edge remained in case ${combo.name}`);
    }
    const hasRearSlotOnV3 = (v3.cutProfileVector ?? []).some((point) => point.y === 50);
    const hasRearSlotOnV4 = (v4.cutProfileVector ?? []).some((point) => point.y === 50);
    assert(hasRearSlotOnV3, `V3 rear Zi slot missing in case ${combo.name}`);
    assert(hasRearSlotOnV4, `V4 rear Zi slot missing in case ${combo.name}`);
  }
}

function testAvoidanceSupportWidthUsesMidWidthNotMidDepth() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    cabinetWidth: 600,
    cabinetDepth: 640,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    avoidance: { enabled: true, depth: 200, height: 400 },
  });
  const horizontal = result.boards.find((board) => board.id === "avoidance_horizontal");
  assert(horizontal);
  assert.equal(result.debug.midWidth, 568);
  assert.equal(result.debug.midDepth, 624);
  assert.equal(horizontal.x0, 16);
  assert.equal(horizontal.x1, 16 + result.debug.midWidth);
}

function testVerticalDividerT5ClearanceUsesContactHeightOnly() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    cabinetDepth: 640,
    topSystem: { style: "style_1", frontRailHeight: 40 },
    bottomSystem: { style: "style_2", height: 100 },
    zones: [
      zone("zone-1", "side_door", 600),
      zone("zone-2", "drawer", 500),
      { ...zone("zone-3", "double_door", 714), verticalDivider: true },
    ],
  });
  const divider = result.boards.find((board) => board.id === "VD_zone-3");
  assert(divider);
  const t5Cut = divider.profileFeatures?.find((feature) =>
    feature.type === "h34_clearance_slot" && feature.h34BoardId === "T5"
  );
  assert(t5Cut);
  assert.equal(result.debug.midDepth, 624);
  assert.deepEqual(
    { y0: t5Cut.y0, y1: t5Cut.y1, z0: t5Cut.z0, z1: t5Cut.z1 },
    { y0: 608, y1: 624, z0: 1895, z1: 1944 },
  );
  assert(hasOrderedSequence(divider.cutProfileVector, [
    { y: 624, z: 1895 },
    { y: 608, z: 1895 },
    { y: 608, z: 1944 },
    { y: 0, z: 1944 },
  ]));
  assert(!hasPoint(divider.cutProfileVector, { y: 608, z: 1839 }));
}

const LOCK_SURFACE_TO_CENTER = 30.5;

function frontPanelById(result: ReturnType<typeof generateGeneralTallCabinet>, id: string) {
  const panel = (result.frontPanels || []).find((item) => item.id === id);
  assert(panel, `missing front panel ${id}`);
  return panel;
}

function zoneStackingItem(result: ReturnType<typeof generateGeneralTallCabinet>, zoneId: string) {
  const item = result.stacking.items.find(
    (entry) => entry.type === "functional_zone" && entry.zoneId === zoneId,
  );
  assert(item, `missing stacking item for ${zoneId}`);
  return item;
}

function testDoorLockShelfTopMounting() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    zones: [
      { ...zone("zone-1", "side_door", 600), shelfEnabled: true, shelfHeight: 300, lockPosition: "shelf_top" },
      zone("zone-2", "drawer", 300),
      { ...zone("zone-3", "double_door", 945), verticalDivider: true },
    ],
  });
  const shelf = result.boards.find((board) => board.id === "DS_zone-1");
  assert(shelf, "door shelf board missing");
  const panel = frontPanelById(result, "FP_zone-1");
  const cut = panel.lockCutout;
  assert(cut, "shelf_top lock cutout missing");
  assert.equal(cut.orientation, "horizontal");
  assert.equal(cut.mountingBoardId, "DS_zone-1");
  assert.equal(cut.mountingFace, "top");
  assert.equal(cut.centerZ, shelf.z1 + LOCK_SURFACE_TO_CENTER);
  assert.equal(cut.fallbackApplied, undefined);
}

function testDoorLockShelfBottomMounting() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    zones: [
      { ...zone("zone-1", "side_door", 600), shelfEnabled: true, shelfHeight: 300, lockPosition: "shelf_bottom" },
      zone("zone-2", "drawer", 300),
      { ...zone("zone-3", "double_door", 945), verticalDivider: true },
    ],
  });
  const shelf = result.boards.find((board) => board.id === "DS_zone-1");
  assert(shelf, "door shelf board missing");
  const cut = frontPanelById(result, "FP_zone-1").lockCutout;
  assert(cut, "shelf_bottom lock cutout missing");
  assert.equal(cut.mountingBoardId, "DS_zone-1");
  assert.equal(cut.mountingFace, "bottom");
  assert.equal(cut.centerZ, shelf.z0 - LOCK_SURFACE_TO_CENTER);
}

function testDoorLockShelfFallbackWithoutShelf() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    zones: [
      { ...zone("zone-1", "side_door", 600), lockPosition: "shelf_top" },
      zone("zone-2", "drawer", 300),
      { ...zone("zone-3", "double_door", 945), verticalDivider: true },
    ],
  });
  const panel = frontPanelById(result, "FP_zone-1");
  const cut = panel.lockCutout;
  assert(cut, "fallback lock cutout missing");
  assert.equal(cut.fallbackApplied, true);
  assert.equal(cut.mountingFace, "bottom"); // top position = upper board's bottom face
  assert(panel.warnings.some((warning) => warning.includes("no horizontal shelf board found")));
}

function testDoubleDoorShelfLockUsesLeafSegments() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    zones: [
      zone("zone-1", "side_door", 600),
      zone("zone-2", "drawer", 300),
      {
        ...zone("zone-3", "double_door", 945),
        verticalDivider: true,
        shelfEnabled: true,
        shelfHeight: 400,
        lockPosition: "shelf_top",
      },
    ],
  });
  const shelfL = result.boards.find((board) => board.id === "DS_zone-3_L");
  const shelfR = result.boards.find((board) => board.id === "DS_zone-3_R");
  assert(shelfL && shelfR, "split shelf segments missing");
  const cutL = frontPanelById(result, "FP_zone-3_L").lockCutout;
  const cutR = frontPanelById(result, "FP_zone-3_R").lockCutout;
  assert(cutL && cutR, "double door shelf lock cutouts missing");
  assert.equal(cutL.mountingBoardId, "DS_zone-3_L");
  assert.equal(cutR.mountingBoardId, "DS_zone-3_R");
  assert.equal(cutL.centerZ, shelfL.z1 + LOCK_SURFACE_TO_CENTER);
  assert.equal(cutR.centerZ, shelfR.z1 + LOCK_SURFACE_TO_CENTER);
}

function testSideLockCustomHeight() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    zones: [
      zone("zone-1", "side_door", 600),
      zone("zone-2", "drawer", 300),
      {
        ...zone("zone-3", "double_door", 945),
        verticalDivider: true,
        lockPosition: "side",
        lockHeight: 500,
      },
    ],
  });
  const item = zoneStackingItem(result, "zone-3");
  const cut = frontPanelById(result, "FP_zone-3_L").lockCutout;
  assert(cut, "side lock cutout missing");
  assert.equal(cut.orientation, "vertical");
  assert.equal(cut.centerZ, item.z0 + 500);
  const divider = result.boards.find((board) => board.id === "VD_zone-3");
  assert(divider, "vertical divider missing");
  assert.equal(cut.mountingBoardId, "VD_zone-3");
}

function invalidBoardIds(result: ReturnType<typeof generateGeneralTallCabinet>) {
  return result.boards
    .filter((board) => {
      const dims = [
        Number(board.x1) - Number(board.x0),
        Number(board.y1) - Number(board.y0),
        Number(board.z1) - Number(board.z0),
      ];
      return dims.some((value) => !Number.isFinite(value) || value <= 0);
    })
    .map((board) => board.id);
}

function testMiddleBottomFlapFusionReady() {
  const params: GeneralTallCabinetParams = {
    cabinetHeight: 1965,
    cabinetWidth: 609,
    cabinetDepth: 600,
    panelThickness: 15,
    leftSidePanelThickness: 15,
    rightSidePanelThickness: 15,
    leftSidePanelAdaptAvoidance: true,
    rightSidePanelAdaptAvoidance: true,
    frontPanelThickness: 16,
    frontFaceAllowance: 16,
    doorPanelThickness: 16,
    frontClearance: 2,
    sideClearance: 3.5,
    frontHardware: {
      frontPanelsEnabled: true,
      frontClearance: 2,
      locksEnabled: true,
      lockPresetId: "razor_long_rounded_1",
      defaultHingeSettings: {
        cupDiameter: 35,
        cupDepth: 13,
        cupCenterFromEdge: 22.5,
        useThreeHinges: false,
        sideDistance: "auto",
      },
    },
    topSystem: { style: "style_1", frontRailHeight: 40 },
    bottomSystem: { style: "style_2", height: 100 },
    avoidance: { enabled: true, depth: 380, height: 220 },
    zones: [
      { id: "zone-3", type: "right_side_door", height: 599 },
      { id: "zone-2", type: "bottom_flap", height: 249 },
      { id: "zone-1", type: "double_door", height: 931, verticalDivider: true },
    ],
  };
  const result = generateGeneralTallCabinet(params);
  assert.equal(result.stacking.difference, 0);
  assert.deepEqual(result.validation.errors, []);
  assert.deepEqual(invalidBoardIds(result), []);
  assert(result.validation.warnings.some((warning) => warning.includes("Bottom flap is not the lowest functional zone")));
}

function testSideLockHeightOutOfRangeClamped() {
  const result = generateGeneralTallCabinet({
    ...uiDefaultParams(),
    zones: [
      zone("zone-1", "side_door", 600),
      zone("zone-2", "drawer", 300),
      {
        ...zone("zone-3", "double_door", 945),
        verticalDivider: true,
        lockPosition: "side",
        lockHeight: 99999,
      },
    ],
  });
  const panel = frontPanelById(result, "FP_zone-3_L");
  const cut = panel.lockCutout;
  assert(cut, "side lock cutout missing");
  assert(cut.centerZ <= panel.z1, "clamped center must stay within panel");
  assert(panel.warnings.some((warning) => warning.includes("outside panel Z")));
}

const tests = [
  testStyle1ExactFitSkeleton,
  testVBoardSideProfileSkeletonStyle1,
  testVBoardCutProfileSingleZiSlot,
  testV12Style1RealProfileDefaultUiConfig,
  testV34Style1RearStileProfileDefaultUiConfig,
  testV34RearAvoidanceCutoutPartialDepth,
  testV34RearAvoidanceCutoutFullDepth,
  testV34RearAvoidanceZeroHeightNoCutout,
  testV34RearAvoidanceOmitsIntersectingSlot,
  testZiBoardProfileVectorsStyle1,
  testBlankHeight250GeneratesOneH12,
  testStyle2FixedFrontPanels,
  testHeightMismatchStillReturnsBoards,
  testStyle1DefaultZRanges,
  testStyle1T3B3ExactNotchedProfileVectors,
  testStyle2DoesNotGenerateT3B3,
  testStyle1T3B3FeaturePlaceholders,
  testStyle1LedGrooveCanBeDisabled,
  testStyle1CustomHeights,
  testStyle1InsertedBoardsFollowCpt,
  testHSupportBoardSkeletons,
  testAvoidanceDisabledKeepsFullZiAndRearSlots,
  testAvoidanceConvertsEligibleFullZiToShortenedZi,
  testAvoidanceHeightRequiredAndZeroHeight,
  testAvoidanceAffectedZoneEligibility,
  testAvoidanceHeightValidationAndProtectedTypes,
  testShortenedZiSmallDepthWarnsAndFallsBackSafely,
  testAvoidanceDoesNotShortenDoubleDoorDividerSupportZi,
  testInvalidAvoidanceDepthReportsValidation,
  testOverlappingZiSlotsReportWarning,
  testVerticalDividerSkeletonDefaultCenter,
  testVerticalDividerCustomCenter,
  testVerticalDividerInvalidCenterValidation,
  testDoubleDoorWithoutVerticalDividerGeneratesNoDivider,
  testVBoardSideProfileSingleZoneAndStyle2,
  testZiGroovesForDoubleDoorDivider,
  testDividerTongueFeaturePlaceholders,
  testDefaultVerticalDividerBottomTongueCutProfile,
  testDividerTongueBoundaryCases,
  testH34ClearanceSlotFeaturesForVerticalDivider,
  testZiGrooveFirstDoubleDoorOnlyLowerBoundary,
  testZiGrooveLastDoubleDoorOnlyUpperBoundary,
  testSingleZoneGeneratesNoBoundarySlots,
  testMergeCandidateDetectionOnly,
  testHMidFullZiConflictMovement,
  testHMidShortenedZiConflictMovement,
  testHMidHalfZiConflictDetectionOnly,
  testHMidMovementBelowBoundsSkipped,
  testH34MidMovementAboveBoundsSkipped,
  testH34ClearanceFollowsMovedH34Mid,
  testSidePanelsDisabledByDefaultAndZeroThickness,
  testSidePanelsBothEnabled,
  testVCarcassYAlignsWithSidePanelWhenOnlyRightEnabled,
  testSidePanelOneSideEnabled,
  testSidePanelAvoidanceNotchAppliedWhenAdaptEnabled,
  testSidePanelAdaptAvoidancePerSide,
  testAvoidanceSupportBoardsGenerated,
  testAvoidanceSupportWidthUsesMidWidthNotMidDepth,
  testVerticalDividerT5ClearanceUsesContactHeightOnly,
  testVBoardStyleSemanticConsistencyAcrossStyleCombos,
  testDoorLockShelfTopMounting,
  testDoorLockShelfBottomMounting,
  testDoorLockShelfFallbackWithoutShelf,
  testDoubleDoorShelfLockUsesLeafSegments,
  testSideLockCustomHeight,
  testMiddleBottomFlapFusionReady,
  testSideLockHeightOutOfRangeClamped,
];

for (const test of tests) {
  test();
  console.log(`TEST ${test.name}: PASS`);
}
