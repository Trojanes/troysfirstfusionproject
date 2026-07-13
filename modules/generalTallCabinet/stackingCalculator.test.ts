import assert from "node:assert/strict";
import { calculateZStacking } from "./stackingCalculator.ts";
import type { FunctionalZone, StackingCalculatorInput } from "./types.ts";

function zone(id: string, type: FunctionalZone["type"], height: number, extra: Partial<FunctionalZone> = {}): FunctionalZone {
  return {
    id,
    type,
    height,
    ...extra,
  };
}

function style1Case(openSpaceHeight: number): StackingCalculatorInput {
  return {
    cabinetHeight: 2100,
    topSystem: { style: "style_1", frontRailHeight: 40, insertSlotThickness: 16 },
    bottomSystem: { style: "style_1", frontRailHeight: 53, insertSlotThickness: 16 },
    ziThickness: 15,
    zones: [
      zone("side-door", "side_door", 600),
      zone("drawer-a", "drawer", 300),
      zone("drawer-b", "drawer", 300),
      zone("blank", "blank_panel", 400),
      zone("open", "open_space", openSpaceHeight),
    ],
  };
}

function testStyle1DefaultMismatch() {
  const result = calculateZStacking(style1Case(300));

  assert.equal(result.topSystemHeight, 56);
  assert.equal(result.bottomSystemHeight, 69);
  assert.equal(result.boundaryPanelTotal, 45);
  assert.equal(result.functionalZoneTotal, 1900);
  assert.equal(result.calculatedHeight, 2070);
  assert.equal(result.difference, -30);
  assert(result.validation.warnings.some((warning) => warning.includes("Height mismatch")));

  assert.deepEqual(
    result.boundaryResolution.boundaries.map((boundary) => boundary.boundaryType),
    ["full_zi", "half_zi", "full_zi", "none"],
  );

  assert.deepEqual(
    result.items.map((item) => [item.id, item.type, item.z0, item.z1, item.height]),
    [
      ["bottom-system", "bottom_system", 0, 69, 69],
      ["zone-side-door", "functional_zone", 69, 669, 600],
      ["boundary-side-door-drawer-a", "boundary_panel", 669, 684, 15],
      ["zone-drawer-a", "functional_zone", 684, 984, 300],
      ["boundary-drawer-a-drawer-b", "boundary_panel", 984, 999, 15],
      ["zone-drawer-b", "functional_zone", 999, 1299, 300],
      ["boundary-drawer-b-blank", "boundary_panel", 1299, 1314, 15],
      ["zone-blank", "functional_zone", 1314, 1714, 400],
      ["zone-open", "functional_zone", 1714, 2014, 300],
      ["top-system", "top_system", 2014, 2070, 56],
    ],
  );

  const firstBoundary = result.items.find((item) => item.id === "boundary-side-door-drawer-a");
  assert.equal(firstBoundary?.centerZ, 676.5);
}

function testStyle1ExactFit() {
  const result = calculateZStacking(style1Case(330));

  assert.equal(result.topSystemHeight, 56);
  assert.equal(result.bottomSystemHeight, 69);
  assert.equal(result.boundaryPanelTotal, 45);
  assert.equal(result.functionalZoneTotal, 1930);
  assert.equal(result.calculatedHeight, 2100);
  assert.equal(result.difference, 0);
  assert(!result.validation.warnings.some((warning) => warning.includes("Height mismatch")));
  assert.equal(result.items.at(-1)?.z1, 2100);
}

function testStyle2Mismatch() {
  const result = calculateZStacking({
    cabinetHeight: 2100,
    topSystem: { style: "style_2", height: 80 },
    bottomSystem: { style: "style_2", height: 100 },
    ziThickness: 15,
    zones: [
      zone("side-door", "side_door", 800),
      zone("blank", "blank_panel", 400),
      zone("drawer", "drawer", 690),
    ],
  });

  assert.equal(result.topSystemHeight, 80);
  assert.equal(result.bottomSystemHeight, 100);
  assert.equal(result.boundaryPanelTotal, 15);
  assert.equal(result.functionalZoneTotal, 1890);
  assert.equal(result.calculatedHeight, 2085);
  assert.equal(result.difference, -15);
  assert(result.validation.warnings.some((warning) => warning.includes("Height mismatch")));
  assert.deepEqual(
    result.boundaryResolution.boundaries.map((boundary) => boundary.boundaryType),
    ["full_zi", "none"],
  );
}

function testFlapValidationFromBoundaryResolver() {
  const topValid = calculateZStacking({
    cabinetHeight: 500,
    topSystem: { style: "style_1", frontRailHeight: 40, insertSlotThickness: 16 },
    bottomSystem: { style: "style_1", frontRailHeight: 53, insertSlotThickness: 16 },
    zones: [zone("door", "side_door", 200), zone("top-flap", "top_flap", 100)],
  });
  assert(!topValid.validation.errors.some((error) => error.includes("Top flap must")));

  const topInvalid = calculateZStacking({
    cabinetHeight: 500,
    topSystem: { style: "style_1", frontRailHeight: 40, insertSlotThickness: 16 },
    bottomSystem: { style: "style_1", frontRailHeight: 53, insertSlotThickness: 16 },
    zones: [zone("door", "side_door", 100), zone("top-flap", "top_flap", 100), zone("drawer", "drawer", 100)],
  });
  assert(topInvalid.validation.warnings.some((warning) => warning.includes("Top flap is not the highest functional zone")));

  const bottomValid = calculateZStacking({
    cabinetHeight: 500,
    topSystem: { style: "style_1", frontRailHeight: 40, insertSlotThickness: 16 },
    bottomSystem: { style: "style_1", frontRailHeight: 53, insertSlotThickness: 16 },
    zones: [zone("bottom-flap", "bottom_flap", 100), zone("blank", "blank_panel", 100)],
  });
  assert(!bottomValid.validation.errors.some((error) => error.includes("Bottom flap must")));

  const bottomInvalid = calculateZStacking({
    cabinetHeight: 500,
    topSystem: { style: "style_1", frontRailHeight: 40, insertSlotThickness: 16 },
    bottomSystem: { style: "style_1", frontRailHeight: 53, insertSlotThickness: 16 },
    zones: [zone("blank", "blank_panel", 100), zone("bottom-flap", "bottom_flap", 100)],
  });
  assert(
    bottomInvalid.validation.warnings.includes(
      "Bottom flap is not the lowest functional zone; hinge semantics still apply but verify the layout is intentional.",
    ),
  );
}

function testStyle2MinimumValidation() {
  const result = calculateZStacking({
    cabinetHeight: 200,
    topSystem: { style: "style_2", height: 59 },
    bottomSystem: { style: "style_2", height: 60 },
    zones: [zone("open", "open_space", 50)],
  });

  assert(result.validation.errors.includes("top Style 2 height must be >= 60 mm."));
}

const tests = [
  testStyle1DefaultMismatch,
  testStyle1ExactFit,
  testStyle2Mismatch,
  testFlapValidationFromBoundaryResolver,
  testStyle2MinimumValidation,
];

for (const test of tests) {
  test();
  console.log(`TEST ${test.name}: PASS`);
}
