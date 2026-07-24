import assert from "node:assert/strict";
import { resolveBoundary, resolveZoneBoundaries, type FunctionalZone } from "./boundaryResolver.ts";

function zone(id: string, type: FunctionalZone["type"], extra: Partial<FunctionalZone> = {}): FunctionalZone {
  return {
    id,
    type,
    height: 300,
    ...extra,
  };
}

function boundaryType(above: FunctionalZone["type"], below: FunctionalZone["type"]) {
  return resolveBoundary(zone("above", above), zone("below", below)).boundaryType;
}

function firstBoundary(zones: FunctionalZone[]) {
  const result = resolveZoneBoundaries(zones);
  assert.deepEqual(result.errors, []);
  assert.equal(result.boundaries.length, 1);
  return result.boundaries[0];
}

function debugBoundary(zones: FunctionalZone[], id: "top_system" | "bottom_system") {
  const result = resolveZoneBoundaries(zones);
  assert.deepEqual(result.errors, []);
  const found = result.debugBoundaries.find((item) =>
    id === "top_system" ? item.aboveZoneId === id : item.belowZoneId === id,
  );
  assert(found, `missing ${id} debug boundary`);
  return found;
}

function testBlankPanelRules() {
  assert.equal(boundaryType("blank_panel", "side_door"), "none");
  assert.equal(boundaryType("blank_panel", "drawer"), "none");
  assert.equal(boundaryType("side_door", "blank_panel"), "full_zi");
  assert.equal(boundaryType("drawer", "blank_panel"), "full_zi");
  assert.equal(boundaryType("blank_panel", "blank_panel"), "none");
}

function testDrawerRules() {
  assert.equal(boundaryType("drawer", "drawer"), "half_zi");
  assert.equal(boundaryType("drawer", "side_door"), "full_zi");
  assert.equal(boundaryType("drawer", "open_space"), "full_zi");
      assert.equal(boundaryType("drawer", "open_appliance"), "full_zi");
      assert.equal(boundaryType("fridge", "drawer"), "full_zi");
      assert.equal(boundaryType("drawer", "fridge"), "full_zi");
}

function testDoorOpenApplianceRules() {
  assert.equal(boundaryType("side_door", "side_door"), "full_zi");
  assert.equal(boundaryType("side_door", "open_space"), "full_zi");
  assert.equal(boundaryType("open_space", "open_appliance"), "full_zi");
  assert.equal(boundaryType("open_appliance", "drawer"), "full_zi");
  assert.equal(boundaryType("open_space", "fridge"), "full_zi");
  assert.equal(boundaryType("fridge", "open_appliance"), "full_zi");
}

function testFlapRules() {
  const topDebug = debugBoundary([zone("top-flap", "top_flap")], "top_system");
  assert.equal(topDebug.boundaryType, "none");

  const topFlapToDrawer = firstBoundary([zone("drawer", "drawer"), zone("top-flap", "top_flap")]);
  assert.equal(topFlapToDrawer.boundaryType, "full_zi");

  const bottomDebug = debugBoundary([zone("bottom-flap", "bottom_flap")], "bottom_system");
  assert.equal(bottomDebug.boundaryType, "none");

  const invalid = resolveZoneBoundaries([zone("blank", "blank_panel"), zone("bottom-flap", "bottom_flap")]);
  assert.deepEqual(invalid.errors, []);
  assert(invalid.warnings.some((warning) => warning.includes("Bottom flap is not the lowest functional zone")));
}

function testDoubleDoorDividerMiddle() {
  const result = resolveZoneBoundaries([
    zone("side", "side_door"),
    zone("double", "double_door", { verticalDivider: true }),
    zone("drawer", "drawer"),
  ]);

  assert.deepEqual(result.errors, []);
  assert.equal(result.boundaries[0].boundaryType, "full_zi");
  assert.equal(result.boundaries[1].boundaryType, "full_zi");
}

function testDoubleDoorDividerAtTopSystem() {
  const result = resolveZoneBoundaries([
    zone("double", "double_door", { verticalDivider: true }),
    zone("drawer", "drawer"),
  ]);

  assert.deepEqual(result.errors, []);
  assert.equal(result.debugBoundaries.find((item) => item.aboveZoneId === "top_system")?.boundaryType, "none");
  assert.equal(result.boundaries[0].boundaryType, "full_zi");
}

function testDoubleDoorDividerAtBottomSystem() {
  const result = resolveZoneBoundaries([
    zone("drawer", "drawer"),
    zone("double", "double_door", { verticalDivider: true }),
  ]);

  assert.deepEqual(result.errors, []);
  assert.equal(result.boundaries[0].boundaryType, "full_zi");
  assert.equal(result.debugBoundaries.find((item) => item.belowZoneId === "bottom_system")?.boundaryType, "none");
}

function testDividerUpgradeFromNoneAndHalfZi() {
  const noneUpgrade = firstBoundary([
    zone("blank", "blank_panel"),
    zone("double", "double_door", { verticalDivider: true }),
  ]);
  assert.equal(noneUpgrade.boundaryType, "full_zi");
  assert.equal(noneUpgrade.upgradedByDoubleDoorDivider, true);

  const halfUpgrade = firstBoundary([
    zone("drawer-a", "drawer"),
    zone("drawer-b", "drawer"),
  ]);
  assert.equal(halfUpgrade.boundaryType, "half_zi");

  const result = resolveZoneBoundaries([
    zone("drawer", "drawer"),
    zone("double", "double_door", { verticalDivider: true }),
  ]);
  assert.equal(result.boundaries[0].boundaryType, "full_zi");
}

function testValidation() {
  const topFlapInvalid = resolveZoneBoundaries([zone("door", "side_door"), zone("flap", "top_flap"), zone("drawer", "drawer")]);
  assert(topFlapInvalid.warnings.some((warning) => warning.includes("Top flap is not the highest functional zone")));

  const heightInvalid = resolveZoneBoundaries([zone("bad", "drawer", { height: 0 })]);
  assert(heightInvalid.errors.includes("Zone bad height must be > 0."));

  const middleBottomFlap = resolveZoneBoundaries([
    zone("door", "right_side_door"),
    zone("flap", "bottom_flap"),
    zone("top", "double_door"),
  ]);
  assert.deepEqual(middleBottomFlap.errors, []);
  assert(middleBottomFlap.warnings.some((warning) => warning.includes("Bottom flap is not the lowest functional zone")));
}

function testNoShortenedZiOutput() {
  const result = resolveZoneBoundaries([
    zone("door", "side_door"),
    zone("drawer", "drawer"),
    zone("blank", "blank_panel"),
  ]);

  for (const boundary of [...result.boundaries, ...result.debugBoundaries]) {
    assert.notEqual(boundary.boundaryType, "shortened_zi");
  }
}

const tests = [
  testBlankPanelRules,
  testDrawerRules,
  testDoorOpenApplianceRules,
  testFlapRules,
  testDoubleDoorDividerMiddle,
  testDoubleDoorDividerAtTopSystem,
  testDoubleDoorDividerAtBottomSystem,
  testDividerUpgradeFromNoneAndHalfZi,
  testValidation,
  testNoShortenedZiOutput,
];

for (const test of tests) {
  test();
  console.log(`TEST ${test.name}: PASS`);
}
