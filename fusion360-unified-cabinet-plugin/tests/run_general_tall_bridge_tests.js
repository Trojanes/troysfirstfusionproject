const assert = require("assert");
const path = require("path");
const { spawnSync } = require("child_process");

const bridgeScript = path.resolve(__dirname, "..", "scripts", "general_tall_from_params.js");

const baseParams = {
    cabinetHeight: 2000,
    cabinetWidth: 600,
    cabinetDepth: 584,
    panelThickness: 16,
    frontFaceAllowance: 16,
    sideClearance: 3,
    ziThickness: 15,
    hThickness: 15,
    topSystem: { style: "style_1", frontRailHeight: 40 },
    bottomSystem: { style: "style_1", frontRailHeight: 53 },
    avoidance: { enabled: false, depth: 200, height: 400 },
    zones: [
      { id: "zone-1", type: "side_door", height: 550 },
      { id: "zone-2", type: "drawer", height: 300 },
      { id: "zone-3", type: "double_door", height: 995, verticalDivider: true },
    ],
};

function runBridge(params) {
  const proc = spawnSync(process.execPath, [bridgeScript], {
    input: JSON.stringify({ params }),
    encoding: "utf8",
  });
  assert.strictEqual(proc.status, 0, proc.stderr);
  const data = JSON.parse(proc.stdout);
  assert.strictEqual(data.ok, true, "bridge should return ok");
  return data.result || {};
}

const result = runBridge(baseParams);
const validation = result.validation || {};
const stacking = result.stacking || {};
const boards = result.boards || [];
assert.strictEqual(Array.isArray(boards), true, "boards should be an array");
assert.strictEqual((validation.errors || []).length, 0, "default case should have no validation errors");
assert.strictEqual(stacking.difference, 0, "default case should have zero height difference");

const boardIds = new Set(boards.map((board) => board.id));
[
  "V1", "V2", "V3", "V4",
  "B1", "B2", "B3",
  "T1", "T2", "T3",
  "Zi1", "Zi2",
  "H13_bottom", "H24_bottom", "H34_bottom",
  "H13_mid", "H24_mid", "H34_mid",
  "H13_top", "H24_top", "T4", "T5",
  "VD_zone-3",
].forEach((id) => assert(boardIds.has(id), `expected board id ${id}`));

for (const board of boards) {
  const widthX = Number(board.x1) - Number(board.x0);
  const depthY = Number(board.y1) - Number(board.y0);
  const heightZ = Number(board.z1) - Number(board.z0);
  assert(Number.isFinite(widthX) && widthX > 0, `board ${board.id} width must be > 0`);
  assert(Number.isFinite(depthY) && depthY > 0, `board ${board.id} depth must be > 0`);
  assert(Number.isFinite(heightZ) && heightZ > 0, `board ${board.id} height must be > 0`);
}

const sidePanelResult = runBridge({
  ...baseParams,
  leftSidePanelThickness: 16,
  rightSidePanelThickness: 16,
  avoidance: { enabled: true, depth: 200, height: 400 },
});
const sidePanelBoards = sidePanelResult.boards || [];
const sidePanelIds = new Set(sidePanelBoards.map((board) => board.id));
assert(sidePanelIds.has("SidePanel_L"), "SidePanel_L should be generated when enabled");
assert(sidePanelIds.has("SidePanel_R"), "SidePanel_R should be generated when enabled");
assert.strictEqual(sidePanelBoards.length, boards.length + 4, "side panels and avoidance supports should add four boards");

const sidePanelL = sidePanelBoards.find((board) => board.id === "SidePanel_L");
const sidePanelR = sidePanelBoards.find((board) => board.id === "SidePanel_R");
assert.deepStrictEqual(
  {
    x0: sidePanelL.x0,
    x1: sidePanelL.x1,
    y0: sidePanelL.y0,
    y1: sidePanelL.y1,
    z0: sidePanelL.z0,
    z1: sidePanelL.z1,
    profilePlane: sidePanelL.profilePlane,
    thicknessAxis: sidePanelL.thicknessAxis,
    vectorSource: Array.isArray(sidePanelL.profileVector) ? "profileVector" : "bboxFallback",
  },
  {
    x0: 0,
    x1: 16,
    y0: -16,
    y1: 568,
    z0: 0,
    z1: 2000,
    profilePlane: "YZ",
    thicknessAxis: "X",
    vectorSource: "profileVector",
  },
);
assert.deepStrictEqual(
  {
    x0: sidePanelR.x0,
    x1: sidePanelR.x1,
    y0: sidePanelR.y0,
    y1: sidePanelR.y1,
    z0: sidePanelR.z0,
    z1: sidePanelR.z1,
    profilePlane: sidePanelR.profilePlane,
    thicknessAxis: sidePanelR.thicknessAxis,
    vectorSource: Array.isArray(sidePanelR.profileVector) ? "profileVector" : "bboxFallback",
  },
  {
    x0: 584,
    x1: 600,
    y0: -16,
    y1: 568,
    z0: 0,
    z1: 2000,
    profilePlane: "YZ",
    thicknessAxis: "X",
    vectorSource: "profileVector",
  },
);
assert(sidePanelResult.debug?.sidePanelOverlapAudit, "side panel overlap audit should be present");
assert(sidePanelResult.debug?.assemblyOverlapAudit, "assembly overlap audit should be present");
assert.strictEqual(
  sidePanelResult.debug.assemblyOverlapAudit.unexpectedOverlapCount,
  0,
  `unexpected parallel overlaps: ${JSON.stringify(sidePanelResult.debug.assemblyOverlapAudit.unexpectedOverlaps)}`,
);
assert(sidePanelIds.has("avoidance_horizontal"), "avoidance_horizontal should be generated when avoidance enabled");
assert(sidePanelIds.has("Avoidance_Vertical"), "Avoidance_Vertical should be generated when avoidance enabled");

const frontPanels = result.frontPanels || [];
assert(Array.isArray(frontPanels), "frontPanels should be an array");
// side_door + drawer + double_door (2 leaves) = 4 front panels
assert.strictEqual(frontPanels.length, 4, `expected 4 front panels, got ${frontPanels.length}`);
const fpIds = new Set(frontPanels.map((panel) => panel.id));
["FP_zone-1", "FP_zone-2", "FP_zone-3_L", "FP_zone-3_R"].forEach((id) => assert(fpIds.has(id), `expected front panel ${id}`));
for (const panel of frontPanels) {
  assert(panel.width > 0, `front panel ${panel.id} width must be > 0`);
  assert(panel.height > 0, `front panel ${panel.id} height must be > 0`);
  assert.strictEqual(panel.y1, 0, `front panel ${panel.id} y1 should be 0`);
  assert.strictEqual(panel.y0, -16, `front panel ${panel.id} y0 should be -16`);
}
const doorPanel = frontPanels.find((panel) => panel.id === "FP_zone-1");
assert(doorPanel.hingeHoles && doorPanel.hingeHoles.length >= 2, "side door should have hinge cups");
assert(doorPanel.lockCutout, "side door should have a lock cutout");
const doubleLeft = frontPanels.find((panel) => panel.id === "FP_zone-3_L");
assert.strictEqual(doubleLeft.lockCutout?.orientation, "vertical", "double door leaf with divider should default to side lock");

// --- Horizontal door shelf (opt-in, kitchen-style) ---
const shelfResult = runBridge({
  ...baseParams,
  zones: [
    { id: "zone-1", type: "side_door", height: 550, shelfEnabled: true, shelfHeight: 300 },
    { id: "zone-2", type: "drawer", height: 300 },
    { id: "zone-3", type: "double_door", height: 995, verticalDivider: true, shelfEnabled: true },
  ],
});
assert.strictEqual((shelfResult.validation?.errors || []).length, 0, "shelf case should have no validation errors");
const shelfBoards = shelfResult.boards || [];
const shelfIds = new Set(shelfBoards.map((board) => board.id));
["DS_zone-1", "DS_zone-3_L", "DS_zone-3_R"].forEach((id) => assert(shelfIds.has(id), `expected shelf board ${id}`));
assert.strictEqual(shelfBoards.length, boards.length + 3, "shelf case should add exactly three boards");

const zoneItems = (shelfResult.stacking?.items || []).filter((item) => item.type === "functional_zone");
const zone1Item = zoneItems.find((item) => item.zoneId === "zone-1");
const shelf1 = shelfBoards.find((board) => board.id === "DS_zone-1");
assert.strictEqual(shelf1.z1 - shelf1.z0, 16, "shelf thickness should equal panelThickness");
assert.strictEqual(shelf1.z1 - zone1Item.z0, 300, "shelf top should sit shelfHeight above the zone bottom");
assert.strictEqual(shelf1.x0, 0, "single shelf should start at x0=0");
assert.strictEqual(shelf1.x1, 600, "single shelf should span the mid width");
assert.strictEqual(shelf1.y1, 568, "shelf depth should equal midDepth");

const shelf3L = shelfBoards.find((board) => board.id === "DS_zone-3_L");
const shelf3R = shelfBoards.find((board) => board.id === "DS_zone-3_R");
assert.strictEqual(shelf3L.x0, 0, "left shelf segment starts at 0");
assert.strictEqual(shelf3L.x1, 292.5, "left shelf segment ends at divider x0");
assert.strictEqual(shelf3R.x0, 307.5, "right shelf segment starts at divider x1");
assert.strictEqual(shelf3R.x1, 600, "right shelf segment ends at mid width");
const zone3Item = zoneItems.find((item) => item.zoneId === "zone-3");
const zone3Height = zone3Item.z1 - zone3Item.z0;
assert.strictEqual(shelf3L.z1 - zone3Item.z0, Math.round(zone3Height / 2), "default shelf top is half the zone height");

// Shelf boards carry the full-Zi joinery profile (side tongues).
// Side notch width follows CPT (panelThickness = 16 in baseParams).
assert(Array.isArray(shelf1.profileVector), "full-width shelf should have a profile vector");
assert.strictEqual(shelf1.profileVector.length, 13, "full-width rear-connected shelf profile should match full_zi (13 points)");
assert.deepStrictEqual(shelf1.profileVector[0], { x: 16, y: 0 }, "shelf profile side notch should equal CPT");
assert(
  shelf1.profileVector.some((point) => point.x === 0 && point.y === 105),
  "shelf profile should contain the front notch corner",
);
assert(
  shelf1.profileVector.some((point) => point.x === 0 && point.y === 568 - 105),
  "shelf profile should contain the rear notch corner",
);
assert(Array.isArray(shelf3L.profileVector), "split shelf segments should have profile vectors");
assert(
  !shelf3L.profileVector.some((point) => point.x === shelf3L.x1 - shelf3L.x0 - 16),
  "left segment must not have a tongue on the divider-side edge",
);

// V1-V4 must receive zi_slot features for every shelf tongue.
const shelfSlots = (shelfResult.features || []).filter(
  (feature) => feature.type === "zi_slot" && String(feature.source || "").startsWith("DS_"),
);
assert.strictEqual(shelfSlots.length, 8, "expected 8 shelf zi slots (4 full-width + 2 left + 2 right)");
const slotTargets = (sourceId) => shelfSlots.filter((f) => f.source === sourceId).map((f) => f.targetBoardId).sort();
assert.deepStrictEqual(slotTargets("DS_zone-1"), ["V1", "V2", "V3", "V4"], "full-width shelf engages all four V boards");
assert.deepStrictEqual(slotTargets("DS_zone-3_L"), ["V1", "V3"], "left segment engages left stiles only");
assert.deepStrictEqual(slotTargets("DS_zone-3_R"), ["V2", "V4"], "right segment engages right stiles only");
const v1ShelfSlot = shelfSlots.find((f) => f.source === "DS_zone-1" && f.targetBoardId === "V1");
assert.strictEqual(v1ShelfSlot.y0, 100, "V1/V2 shelf slot uses the front-stile Zi slot y range");
assert.strictEqual(v1ShelfSlot.y1, 150, "V1/V2 shelf slot uses the front-stile Zi slot y range");
assert.strictEqual(v1ShelfSlot.z1 - v1ShelfSlot.z0, 17, "shelf slot height = shelf thickness (CPT 16) + 1mm clearance");
assert.strictEqual(v1ShelfSlot.z1 - zone1Item.z0, 300.5, "shelf slot is centred on the shelf board (+0.5 clearance above)");

// Boundary Zi boards also follow CPT for the side notch width.
const ziBoard = shelfBoards.find((board) => board.boardType === "full_zi");
assert(ziBoard, "expected a full_zi boundary board");
assert.deepStrictEqual(ziBoard.profileVector[0], { x: 16, y: 0 }, "full_zi side notch should equal CPT");
const ziGrooves = (shelfResult.features || []).filter((feature) => feature.type === "zi_groove");
assert(ziGrooves.length > 0, "double_door divider should produce zi grooves");
assert(ziGrooves.every((feature) => feature.depth === 8), "zi groove depth should be CPT/2 (16/2)");
assert(ziGrooves.every((feature) => feature.x1 - feature.x0 === 16), "zi groove width = divider thickness 15 + 1mm clearance");
const dividerTongues = (shelfResult.features || []).filter((feature) => feature.type === "divider_tongue");
assert(dividerTongues.length > 0, "double_door divider should produce tongues");
assert(dividerTongues.every((feature) => feature.insertionDepth === 7.5), "tongue insertion should be CPT/2 - 0.5");

// Slots must reach the V boards' side profiles (cut features on V1-V4).
const shelfV1 = shelfBoards.find((board) => board.id === "V1");
assert(
  (shelfV1.profileFeatures || []).some((feature) => feature.type === "zi_slot" && feature.source === "DS_zone-1"),
  "V1 side profile should include the shelf zi slot",
);

// Shelf must be skipped (warning, no error) when the zone is too short.
const shortShelfResult = runBridge({
  ...baseParams,
  zones: [
    { id: "zone-1", type: "side_door", height: 300, shelfEnabled: true },
    { id: "zone-2", type: "drawer", height: 550 },
    { id: "zone-3", type: "double_door", height: 995 },
  ],
});
assert.strictEqual((shortShelfResult.validation?.errors || []).length, 0, "short-zone shelf case should have no errors");
assert(
  (shortShelfResult.validation?.warnings || []).some((msg) => String(msg).includes("Door shelf skipped")),
  "short zone should produce a door-shelf-skipped warning",
);
assert(!(shortShelfResult.boards || []).some((board) => board.id.startsWith("DS_")), "short zone should not generate shelf boards");

console.log(`OK general tall bridge: ${boards.length} boards, ${sidePanelBoards.length} with side panels/avoidance supports, ${frontPanels.length} front panels, ${shelfBoards.length - boards.length} shelf boards`);
