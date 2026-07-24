import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pluginDir = path.resolve(__dirname, "..");
const script = path.join(pluginDir, "scripts", "overhead_from_params.js");

function runBridge(params) {
  const proc = spawnSync(process.execPath, [script], {
    cwd: pluginDir,
    input: JSON.stringify({ params }),
    encoding: "utf8",
  });
  assert.equal(proc.status, 0, proc.stderr || proc.stdout);
  const payload = JSON.parse(proc.stdout);
  assert.equal(payload.ok, true);
  return payload.result;
}

const edgeOnly = runBridge({
  cabinetWidth: 900,
  cabinetDepth: 350,
  cabinetHeight: 720,
});
assert.equal(edgeOnly.debug.phase, "geometry_v1");
assert.equal(edgeOnly.boards.length, 8);
assert.deepEqual(edgeOnly.debug.dividerCenterlines, [7.5, 892.5]);

const v7Case = runBridge({
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
});
assert.equal(v7Case.features.length, 12);
const t3Led = v7Case.features.find((feature) => feature && feature.type === "t3_groove" && feature.targetBoardId === "T3");
assert.ok(t3Led, "expected T3 LED groove");
assert.equal(t3Led.face, "top");
assert.equal(t3Led.branches.length, 2);

const ledOff = runBridge({
  style: "style_1",
  cabinetWidth: 2000,
  cabinetDepth: 400,
  cabinetHeight: 400,
  topClearanceHeight: 40,
  featureWidth: 15,
  frontPanelThickness: 16,
  clearance: 2.5,
  routerDiameter: 10,
  ledGroove: false,
  zones: [
    { id: "zone-1", type: "up_flap", width: 650 },
    { id: "zone-2", type: "fixed_panel", width: 750 },
    { id: "zone-3", type: "up_flap", width: 600 },
  ],
});
assert.equal(
  ledOff.features.filter((feature) => feature && (feature.type === "t3_groove" || feature.type === "b3_groove")).length,
  0,
);
assert.deepEqual(
  v7Case.debug.dividerCenterlines,
  [7.5, 650, 1400, 1992.5],
);
const legacyGeometry = v7Case.debug.legacyGeometry;
assert.ok(legacyGeometry);
assert.equal(legacyGeometry.manufacturing.FeatureSlotWidth, 16);
assert.equal(legacyGeometry.manufacturing.Dntg_h, 7);
assert.deepEqual(legacyGeometry.divider_features[1].bp_groove.x, [642, 658]);
assert.deepEqual(legacyGeometry.divider_features[1].bp_groove.z, [0, -7.5]);
assert.deepEqual(legacyGeometry.front_panels[0].x, [2.5, 648.75]);
assert.deepEqual(legacyGeometry.front_panels[0].z, [-30, 359]);
assert.deepEqual(legacyGeometry.hinge_holes[0].center, [100, 366.5]);
assert.equal(legacyGeometry.hinge_holes.length, 4);

const explicit = runBridge({
  cabinetWidth: 500,
  cabinetDepth: 300,
  cabinetHeight: 400,
  internalDividerCenterlines: [125, 250, 375],
  bottomThickness: 15,
  dividerTongueHeight: 7.5,
  routerDiameter: 10,
  featureWidth: 15,
});
const explicitGeometry = explicit.debug.legacyGeometry;
assert.ok(explicitGeometry);
assert.deepEqual(explicitGeometry.trimmed_vectors.T4.slice(0, 4), [
  [0, 50],
  [500, 50],
  [500, 20],
  [484.5, 20],
]);

console.log("OK overhead bridge: geometry_v1 with v7 golden checks");
