import assert from "node:assert/strict";
import { resolveBoundary, resolveZoneBoundaries } from "./boundaryResolver.ts";
import { generateGeneralTallCabinet } from "./generator.ts";
import type { FunctionalZone, GeneralTallCabinetParams } from "./types.ts";

function zone(id: string, type: FunctionalZone["type"], height: number, extra: Partial<FunctionalZone> = {}): FunctionalZone {
  return { id, type, height, ...extra };
}

function boundaryType(above: FunctionalZone["type"], below: FunctionalZone["type"]) {
  return resolveBoundary(zone("above", above, 300), zone("below", below, 300)).boundaryType;
}

function fridgeParams(zones: FunctionalZone[]): GeneralTallCabinetParams {
  return {
    cabinetHeight: 2100,
    cabinetWidth: 611,
    cabinetDepth: 616,
    panelThickness: 15,
    frontFaceAllowance: 16,
    ziThickness: 15,
    hThickness: 15,
    sideClearance: 3,
    topSystem: { style: "style_1", frontRailHeight: 40, insertSlotThickness: 16 },
    bottomSystem: { style: "style_1", frontRailHeight: 53, insertSlotThickness: 16 },
    avoidance: { enabled: false, depth: 300, height: 200 },
    zones,
  };
}

function testFridgeBoundaryRules() {
  assert.equal(boundaryType("fridge", "drawer"), "full_zi");
  assert.equal(boundaryType("drawer", "fridge"), "full_zi");
  assert.equal(boundaryType("fridge", "open_space"), "full_zi");
  assert.equal(boundaryType("side_door", "fridge"), "full_zi");
  assert.equal(boundaryType("blank_panel", "fridge"), "none");

  const resolved = resolveZoneBoundaries([
    zone("drawer", "drawer", 250),
    zone("fridge", "fridge", 1470, {
      applianceWidthMm: 550,
      applianceDepthMm: 580,
      applianceHeightMm: 1470,
    }),
  ]);
  assert.deepEqual(resolved.errors, []);
  assert.equal(resolved.boundaries[0].boundaryType, "full_zi");
}

function testFridgeZoneUsesApplianceHeightAndStaysOpen() {
  const result = generateGeneralTallCabinet(
    fridgeParams([
      zone("bottom-drawer", "drawer", 200),
      zone("fridge-cavity", "fridge", 999, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1470,
      }),
      zone("top-flap", "top_flap", 180),
    ]),
  );

  const fridgeItem = result.stacking.items.find(
    (item) => item.type === "functional_zone" && item.zoneId === "fridge-cavity",
  );
  assert(fridgeItem, "fridge stacking item missing");
  assert.equal(fridgeItem.height, 1470);
  assert.ok(Math.abs(fridgeItem.z1 - fridgeItem.z0 - 1470) < 0.01);

  assert.equal(
    result.frontPanels.filter((panel) => panel.zoneId === "fridge-cavity").length,
    0,
    "fridge cavity must not generate a front panel",
  );

  const boardIds = new Set(result.boards.map((board) => board.id));
  for (const id of ["T1", "T2", "T3", "B1", "B2", "B3", "V1", "V2"]) {
    assert(boardIds.has(id), `expected carcass board ${id}`);
  }

  assert(
    result.warnings.some((w) => w.includes("fridge-cavity") && w.includes("1470")),
    "expected fridge height sync note in warnings",
  );
}

function testFridgeFitsInteriorWarning() {
  const result = generateGeneralTallCabinet(
    fridgeParams([
      zone("fridge-cavity", "fridge", 1470, {
        applianceWidthMm: 900,
        applianceDepthMm: 800,
        applianceHeightMm: 1470,
      }),
    ]),
  );
  assert(
    result.warnings.some((w) => w.includes("applianceWidthMm") || w.includes("applianceDepthMm") || w.includes("exceeds")),
    "oversized appliance should warn",
  );
}

function testFridgeExteriorSideLeftAddsSidePanelAndSyncsWidth() {
  const result = generateGeneralTallCabinet({
    ...fridgeParams([
      zone("fridge-cavity", "fridge", 1470, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1470,
      }),
    ]),
    cabinetWidth: 500,
    leftSidePanelThickness: 0,
    rightSidePanelThickness: 0,
    exteriorSide: "left",
  });

  assert.equal(result.debug.leftSidePanelThickness, 16);
  assert(result.boards.find((b) => b.id === "SidePanel_L"), "SidePanel_L missing");
  assert.equal(result.boards.find((b) => b.id === "SidePanel_R"), undefined);
  assert.equal(result.debug.midWidth + result.debug.leftSidePanelThickness + result.debug.rightSidePanelThickness, 611);
  assert(
    result.warnings.some((w) => w.includes("Cabinet width synced") && w.includes("611")),
    "expected cabinet width sync warning",
  );
}

function testFridgeExteriorSideNoneSyncsWidthWithoutForcedSidePanel() {
  const result = generateGeneralTallCabinet({
    ...fridgeParams([
      zone("fridge-cavity", "fridge", 1470, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1470,
      }),
    ]),
    cabinetWidth: 500,
    leftSidePanelThickness: 0,
    rightSidePanelThickness: 0,
    exteriorSide: "none",
  });

  assert.equal(result.boards.find((b) => b.id === "SidePanel_L"), undefined);
  assert.equal(result.boards.find((b) => b.id === "SidePanel_R"), undefined);
  assert.equal(Number(result.debug.midWidth), 595);
  assert(
    result.warnings.some((w) => w.includes("595") || w.includes("45")),
    "expected none-side width sync 550+45=595",
  );
}

function testFridgeExteriorSideRight() {
  const result = generateGeneralTallCabinet({
    ...fridgeParams([
      zone("fridge-cavity", "fridge", 1470, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1470,
      }),
    ]),
    exteriorSide: "right",
    leftSidePanelThickness: 0,
    rightSidePanelThickness: 0,
  });
  assert(result.boards.find((b) => b.id === "SidePanel_R"));
  assert.equal(result.boards.find((b) => b.id === "SidePanel_L"), undefined);
  assert.equal(result.debug.rightSidePanelThickness, 16);
}

function testFridgeEmitsV5OppositeExteriorSide() {
  const withLeftExterior = generateGeneralTallCabinet({
    ...fridgeParams([
      zone("drawer", "drawer", 200),
      zone("fridge-cavity", "fridge", 1470, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1470,
      }),
    ]),
    exteriorSide: "left",
  });
  const v5Right = withLeftExterior.boards.find((b) => b.id === "V5");
  assert(v5Right, "V5 missing for fridge stack");
  assert.equal(v5Right.boardType, "V5");
  // Opposite exterior left → V5 on right half of cabinet.
  assert.ok(v5Right.x0 > 611 / 2);

  const fridgeItem = withLeftExterior.stacking.items.find(
    (item) => item.type === "functional_zone" && item.zoneId === "fridge-cavity",
  );
  assert(fridgeItem);
  assert.ok(Math.abs(v5Right.z0 - fridgeItem.z0) < 0.5, "V5 bottom should meet fridge cavity floor");
  assert.ok(Math.abs(v5Right.z1 - fridgeItem.z1) < 0.5, "V5 top should meet fridge cavity ceiling");

  const withNone = generateGeneralTallCabinet({
    ...fridgeParams([
      zone("fridge-cavity", "fridge", 1470, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1470,
      }),
    ]),
    exteriorSide: "none",
  });
  const v5Left = withNone.boards.find((b) => b.id === "V5");
  assert(v5Left);
  assert.ok(v5Left.x1 < Number(withNone.debug.midWidth) / 2, "exterior none → V5 defaults to left");
}

function testFridgeRaisedAvoidanceWhenGapBelow105() {
  // bottom system ~69 + drawer 200 + zi 15 ≈ fridge base z0 ~284; avoidH 200 → gap ~84 < 105
  const result = generateGeneralTallCabinet({
    ...fridgeParams([
      zone("drawer", "drawer", 200),
      zone("fridge-cavity", "fridge", 1470, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1470,
      }),
    ]),
    avoidance: { enabled: true, depth: 300, height: 200 },
    exteriorSide: "none",
  });

  assert.equal(result.debug.fridgeAvoidance?.finalMode, "raised");
  assert.ok((result.debug.fridgeAvoidance?.fridgeGap ?? 999) < 105);
  assert(
    result.warnings.some((w) => w.includes("raised") && w.includes("105")),
    "expected raised-mode warning",
  );

  const avoidH = result.boards.find((b) => b.id === "avoidance_horizontal");
  assert(avoidH, "avoidance_horizontal missing");
  const fridgeBaseZ = result.debug.fridgeAvoidance?.fridgeBaseBottomZ;
  assert(fridgeBaseZ != null);
  assert.ok(Math.abs(avoidH.z1 - fridgeBaseZ) < 0.5, "raised avoidance top should meet fridge base");

  const hFridge = result.boards.filter((b) => b.id.startsWith("H13_fridge") || b.id.startsWith("H24_fridge") || b.id.startsWith("H34_fridge"));
  assert.equal(hFridge.length, 3, "raised mode should emit fridge H13/H24/H34 above base");
  assert.ok(hFridge.every((b) => b.z0 >= fridgeBaseZ - 0.01));
  // Fridge parity: H_bot omitted in raised mode (would overlap above-fridge HSet band).
  assert.equal(
    result.boards.filter((b) => ["H13_bottom", "H24_bottom", "H34_bottom"].includes(b.id)).length,
    0,
    "raised mode should omit H*_bottom",
  );
}

function testFridgeNormalAvoidanceWhenGapAtLeast105() {
  // drawer 400 → fridge base higher → gap >= 105
  const result = generateGeneralTallCabinet({
    ...fridgeParams([
      zone("drawer", "drawer", 400),
      zone("fridge-cavity", "fridge", 1200, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1200,
      }),
    ]),
    avoidance: { enabled: true, depth: 300, height: 200 },
    exteriorSide: "none",
  });
  assert.equal(result.debug.fridgeAvoidance?.finalMode, "normal");
  assert.ok((result.debug.fridgeAvoidance?.fridgeGap ?? 0) >= 105);
  assert.equal(result.boards.filter((b) => String(b.id).includes("_fridge")).length, 0);
  const avoidH = result.boards.find((b) => b.id === "avoidance_horizontal");
  assert(avoidH);
  assert.ok(Math.abs(avoidH.z1 - 200) < 0.5, "normal mode keeps input avoidance height");
  assert(result.boards.some((b) => b.id === "H13_bottom"), "normal mode still emits H*_bottom");
}

function testFridgeStackEmitsConnectDeclarations() {
  const left = generateGeneralTallCabinet({
    ...fridgeParams([
      zone("fridge-cavity", "fridge", 1470, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1470,
      }),
    ]),
    exteriorSide: "left",
  });
  const ids = new Set(left.relationshipDeclarations.map((d) => d.declarationId));
  assert(ids.has("gt_b1_b3_bottom_rail_to_deck"), "skeleton declarations still present");
  assert(ids.has("gt_sidepanel_l_v1"), "SidePanel_L↔V1 declaration missing");
  assert(!ids.has("gt_sidepanel_r_v2"), "right sidepanel declaration should be absent");
  assert(ids.has("gt_v5_v2"), "V5 opposite left exterior should declare against V2");
  assert(!ids.has("gt_v5_v1"), "V5 should not also declare against V1");

  const none = generateGeneralTallCabinet({
    ...fridgeParams([
      zone("fridge-cavity", "fridge", 1470, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1470,
      }),
    ]),
    exteriorSide: "none",
  });
  const noneIds = new Set(none.relationshipDeclarations.map((d) => d.declarationId));
  assert(noneIds.has("gt_v5_v1"), "exterior none → V5 declares against V1");
  assert(!noneIds.has("gt_sidepanel_l_v1"));
  assert(!noneIds.has("gt_sidepanel_r_v2"));
}

function profileClosed(points: { y?: number; z?: number }[] | undefined): boolean {
  if (!points || points.length < 4) return false;
  const a = points[0];
  const b = points[points.length - 1];
  return Math.abs(Number(a.y) - Number(b.y)) < 1e-6 && Math.abs(Number(a.z) - Number(b.z)) < 1e-6;
}

function hasYzPoint(
  points: { y?: number; z?: number }[] | undefined,
  y: number,
  z: number,
  tol = 0.6,
): boolean {
  return Boolean(
    points?.some(
      (p) => Math.abs(Number(p.y) - y) <= tol && Math.abs(Number(p.z) - z) <= tol,
    ),
  );
}

/** vVerify-lite: fridge stack keeps V1/V2 cut-ready + V5 closed profile (GT uses profileVector, not Fridge flat_xy). */
function testFridgeStackVProfilesCutReady() {
  const result = generateGeneralTallCabinet({
    ...fridgeParams([
      zone("drawer", "drawer", 200),
      zone("fridge-cavity", "fridge", 1470, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1470,
      }),
    ]),
    avoidance: { enabled: true, depth: 300, height: 200 },
    exteriorSide: "left",
  });
  assert.equal(result.debug.fridgeAvoidance?.finalMode, "raised");

  const ch = 2100;
  for (const id of ["V1", "V2"] as const) {
    const v = result.boards.find((b) => b.id === id);
    assert(v, `${id} missing`);
    assert.equal(v.profilePlane, "YZ");
    assert(v.cutProfileVector, `${id} cutProfileVector missing`);
    assert(profileClosed(v.cutProfileVector), `${id} cutProfileVector not closed`);
    const ys = v.cutProfileVector!.map((p) => Number(p.y));
    const zs = v.cutProfileVector!.map((p) => Number(p.z));
    assert.equal(Math.max(...ys), 150, `${id} stile depth`);
    assert.equal(Math.min(...zs), 0);
    assert.equal(Math.max(...zs), ch);

    const fridgeSlot = v.profileFeatures?.find(
      (f) => f.type === "zi_slot" && String(f.source || "").includes("fridge"),
    );
    assert(fridgeSlot, `${id} missing fridge-base Zi slot feature`);
    assert(
      hasYzPoint(v.cutProfileVector, 100, Number(fridgeSlot.z0)) &&
        hasYzPoint(v.cutProfileVector, 100, Number(fridgeSlot.z1)),
      `${id} cut profile missing fridge Zi slot corners`,
    );
  }

  const v5 = result.boards.find((b) => b.id === "V5");
  assert(v5, "V5 missing");
  assert.equal(v5.profilePlane, "YZ");
  const v5Profile = v5.cutProfileVector || v5.profileVector;
  assert(v5Profile, "V5 should emit a closed YZ profile (not bbox-only)");
  assert(profileClosed(v5Profile), "V5 profile not closed");
  const depth = Number(v5.y1) - Number(v5.y0);
  const height = Number(v5.z1) - Number(v5.z0);
  const ys = v5Profile!.map((p) => Number(p.y));
  const zs = v5Profile!.map((p) => Number(p.z));
  assert.ok(Math.abs(Math.max(...ys) - depth) < 0.5, "V5 profile depth");
  assert.ok(Math.abs(Math.max(...zs) - height) < 0.5, "V5 profile height");
}

function testClassicFridgeStackUserEffects() {
  // User-facing classic: drawer under fridge, flap above, exterior right, avoidance on.
  const result = generateGeneralTallCabinet({
    ...fridgeParams([
      zone("drawer", "drawer", 250),
      zone("fridge", "fridge", 1500, {
        applianceWidthMm: 550,
        applianceDepthMm: 580,
        applianceHeightMm: 1500,
      }),
      zone("flap", "top_flap", 195),
    ]),
    exteriorSide: "right",
    syncCabinetWidthFromFridge: true,
    avoidance: { enabled: true, depth: 300, height: 200 },
    frontHardware: {
      frontPanelsEnabled: true,
      frontClearance: 2.5,
      locksEnabled: true,
      lockPresetId: "razor_long_rounded_1",
    },
  });

  assert.deepEqual(result.validation.errors, []);
  const ids = new Set(result.boards.map((b) => b.id));
  assert(ids.has("V5"), "V5 required for fridge cavity");
  assert(ids.has("SidePanel_R"), "exterior right → SidePanel_R");
  assert(!ids.has("SidePanel_L"), "should not force left side panel");

  assert.equal(
    result.frontPanels.filter((p) => p.zoneId === "fridge").length,
    0,
    "fridge cavity stays open",
  );
  assert.ok(
    result.frontPanels.some((p) => p.zoneId === "drawer"),
    "drawer gets a front panel",
  );
  assert.ok(
    result.frontPanels.some((p) => p.zoneId === "flap"),
    "flap gets a front panel",
  );

  const mode = result.debug.fridgeAvoidance?.finalMode;
  assert.ok(mode === "normal" || mode === "raised", `expected fridge avoidance mode, got ${mode}`);

  const decls = new Set((result.relationshipDeclarations || []).map((d) => d.declarationId));
  assert(decls.has("gt_v5_v1"), "V5 opposite right exterior mates V1");
  assert(decls.has("gt_sidepanel_r_v2"), "SidePanel_R Connect decl");
}

const tests = [
  testFridgeBoundaryRules,
  testFridgeZoneUsesApplianceHeightAndStaysOpen,
  testFridgeFitsInteriorWarning,
  testFridgeExteriorSideLeftAddsSidePanelAndSyncsWidth,
  testFridgeExteriorSideNoneSyncsWidthWithoutForcedSidePanel,
  testFridgeExteriorSideRight,
  testFridgeEmitsV5OppositeExteriorSide,
  testFridgeRaisedAvoidanceWhenGapBelow105,
  testFridgeNormalAvoidanceWhenGapAtLeast105,
  testFridgeStackEmitsConnectDeclarations,
  testFridgeStackVProfilesCutReady,
  testClassicFridgeStackUserEffects,
];

for (const test of tests) {
  test();
  console.log(`TEST ${test.name}: PASS`);
}
