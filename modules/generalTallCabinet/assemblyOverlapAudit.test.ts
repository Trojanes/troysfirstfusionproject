import assert from "node:assert/strict";
import { test } from "node:test";
import {
  boardsOverlap3d,
  overlapBbox,
  overlapVolumeMm3,
  runAssemblyOverlapAudit,
} from "./assemblyOverlapAudit.ts";
import { generateGeneralTallCabinet } from "./generator.ts";
import type { Board } from "./types.ts";

function board(overrides: Partial<Board> & Pick<Board, "id">): Board {
  return {
    name: overrides.id,
    boardType: overrides.boardType ?? overrides.id,
    category: overrides.category ?? "test",
    materialThickness: overrides.materialThickness ?? 16,
    profilePlane: overrides.profilePlane ?? "YZ",
    thicknessAxis: overrides.thicknessAxis ?? "X",
    x0: overrides.x0 ?? 0,
    x1: overrides.x1 ?? 16,
    y0: overrides.y0 ?? 0,
    y1: overrides.y1 ?? 100,
    z0: overrides.z0 ?? 0,
    z1: overrides.z1 ?? 1000,
    source: "test",
    ...overrides,
  };
}

test("boardsOverlap3d detects volumetric intersection", () => {
  const a = { x0: 0, x1: 16, y0: 0, y1: 100, z0: 0, z1: 1000 };
  const b = { x0: 8, x1: 24, y0: 50, y1: 150, z0: 10, z1: 20 };
  assert.equal(boardsOverlap3d(a, b), true);
  const region = overlapBbox(a, b);
  assert(region);
  assert.equal(overlapVolumeMm3(region), 8 * 50 * 10);
});

test("boardsOverlap3d ignores face contact", () => {
  const a = { x0: 0, x1: 16, y0: 0, y1: 100, z0: 0, z1: 1000 };
  const b = { x0: 16, x1: 32, y0: 0, y1: 100, z0: 0, z1: 1000 };
  assert.equal(boardsOverlap3d(a, b), false);
});

test("runAssemblyOverlapAudit allows split V stiles but flags side-panel/V coplanar volume", () => {
  const colocated = runAssemblyOverlapAudit([
    board({ id: "SidePanel_L", category: "side_panel", x0: 0, x1: 16, y0: -16, y1: 624, z0: 0, z1: 2000 }),
    board({ id: "V1", category: "vertical_structure", x0: 0, x1: 16, y0: 0, y1: 624, z0: 0, z1: 2000 }),
    board({ id: "V3", category: "vertical_structure", x0: 0, x1: 16, y0: 474, y1: 624, z0: 0, z1: 2000 }),
  ]);
  assert.equal(colocated.unexpectedOverlapCount, 2);
  assert(
    colocated.unexpectedOverlaps.every((pair) =>
      [pair.boardAId, pair.boardBId].includes("SidePanel_L"),
    ),
  );

  const outerSkin = runAssemblyOverlapAudit([
    board({ id: "SidePanel_L", category: "side_panel", x0: 0, x1: 16, y0: -16, y1: 624, z0: 0, z1: 2000 }),
    board({ id: "V1", category: "vertical_structure", x0: 16, x1: 32, y0: 0, y1: 624, z0: 0, z1: 2000 }),
    board({ id: "V3", category: "vertical_structure", x0: 16, x1: 32, y0: 474, y1: 624, z0: 0, z1: 2000 }),
  ]);
  assert.equal(outerSkin.unexpectedOverlapCount, 0);
  assert.equal(outerSkin.parallelOverlapCount, 1);
});

test("runAssemblyOverlapAudit flags parallel slabs that should not share volume", () => {
  const audit = runAssemblyOverlapAudit([
    board({ id: "V1", category: "vertical_structure", x0: 0, x1: 16, y0: 0, y1: 624, z0: 0, z1: 2000 }),
    board({ id: "VD_zone-1", category: "vertical_divider", x0: 0, x1: 16, y0: 0, y1: 568, z0: 100, z1: 900 }),
  ]);
  assert.equal(audit.unexpectedOverlapCount, 1);
  assert.equal(audit.unexpectedOverlaps[0].boardAId, "V1");
  assert.equal(audit.unexpectedOverlaps[0].boardBId, "VD_zone-1");
});

test("runAssemblyOverlapAudit ignores perpendicular corner intersections", () => {
  const audit = runAssemblyOverlapAudit([
    board({ id: "V1", category: "vertical_structure", profilePlane: "YZ", thicknessAxis: "X", x0: 0, x1: 16, y0: 0, y1: 624, z0: 0, z1: 2000 }),
    board({ id: "T1", category: "top_rail", profilePlane: "XY", thicknessAxis: "Z", x0: 0, x1: 584, y0: 0, y1: 16, z0: 1960, z1: 2000 }),
  ]);
  assert.equal(audit.unexpectedOverlapCount, 0);
  assert(audit.perpendicularOverlapCount > 0);
});

test("generateGeneralTallCabinet emits zero unexpected parallel overlaps for side-panel default", () => {
  const result = generateGeneralTallCabinet({
    cabinetHeight: 2000,
    cabinetWidth: 600,
    cabinetDepth: 640,
    panelThickness: 16,
    frontPanelThickness: 16,
    sideClearance: 3,
    ziThickness: 15,
    hThickness: 15,
    leftSidePanelThickness: 16,
    rightSidePanelThickness: 16,
    topSystem: { style: "style_1", frontRailHeight: 40 },
    bottomSystem: { style: "style_2", height: 100 },
    avoidance: { enabled: false, depth: 200, height: 400 },
    zones: [
      { id: "zone-1", type: "left_side_door", height: 920 },
      { id: "zone-2", type: "double_door", height: 932, verticalDivider: true },
    ],
  });
  const audit = result.debug.assemblyOverlapAudit;
  assert(audit);
  assert.equal(audit.unexpectedOverlapCount, 0, audit.unexpectedOverlaps.map((pair) => pair.boardAId + "+" + pair.boardBId).join(", "));
  assert.equal(
    (result.validation.warnings || []).some((warning) => warning.startsWith("Assembly overlap:")),
    false,
  );
});
