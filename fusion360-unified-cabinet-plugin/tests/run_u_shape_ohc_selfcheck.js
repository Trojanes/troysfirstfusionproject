import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import { generateUShapeOverheadCabinet } from "../../modules/uShapeOverheadCabinet/generator.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.resolve(here, "..");
const repoRoot = path.resolve(pluginRoot, "..");

function countDividers(run) {
  return run.result.boards.filter((board) => board.id.startsWith("D")).length;
}

function assertValid(result, label) {
  assert.deepEqual(result.validation.errors, [], `${label}: ${result.validation.errors.join("; ")}`);
  assert.equal(result.runs.length, 3, `${label}: run count`);
  assert(result.audit.every((row) => row.ok), `${label}: ${JSON.stringify(result.audit)}`);
  assert.equal(new Set(result.worldBoards.map((board) => board.id)).size, result.worldBoards.length, `${label}: duplicate world IDs`);
}

const cases = [
  {
    label: "default-2275x400x400",
    params: { totalWidth: 2275, leftArmLength: 1500, rightArmLength: 1500, cabinetDepth: 400, cabinetHeight: 400 },
  },
  {
    label: "compact-symmetric",
    params: { totalWidth: 1700, leftArmLength: 850, rightArmLength: 850, cabinetDepth: 350, cabinetHeight: 360, sideClearance: 40 },
  },
  {
    label: "asymmetric",
    params: { totalWidth: 2600, leftArmLength: 1750, rightArmLength: 1200, cabinetDepth: 420, cabinetHeight: 460 },
  },
  {
    label: "non-default thickness",
    params: {
      totalWidth: 2500, leftArmLength: 1450, rightArmLength: 1350, cabinetDepth: 430, cabinetHeight: 430,
      featureWidth: 18, frontPanelThickness: 19, sideClearance: 60,
    },
  },
  {
    label: "small-clearance",
    params: { totalWidth: 2275, leftArmLength: 1450, rightArmLength: 1250, cabinetDepth: 400, cabinetHeight: 400, sideClearance: 30 },
  },
  {
    label: "large-clearance",
    params: { totalWidth: 2500, leftArmLength: 1600, rightArmLength: 1400, cabinetDepth: 450, cabinetHeight: 440, sideClearance: 80 },
  },
  {
    label: "multi-zone",
    params: {
      totalWidth: 2700, leftArmLength: 1700, rightArmLength: 1600, cabinetDepth: 450, cabinetHeight: 420,
      zones: {
        LEFT: [{ type: "up_flap", width: 500 }, { type: "fixed_panel", width: 700 }],
        BACK: [{ type: "up_flap", width: 600 }, { type: "open", width: 500 }, { type: "up_flap", width: 600 }],
        RIGHT: [{ type: "fixed_panel", width: 500 }, { type: "up_flap", width: 600 }],
      },
    },
  },
  {
    label: "independent LED",
    params: {
      totalWidth: 2400, leftArmLength: 1400, rightArmLength: 1300, cabinetDepth: 450, cabinetHeight: 400,
      runLedGroove: { LEFT: false, BACK: true, RIGHT: false },
    },
  },
  {
    label: "wide-deep",
    params: { totalWidth: 3600, leftArmLength: 2300, rightArmLength: 2100, cabinetDepth: 600, cabinetHeight: 500, sideClearance: 70 },
  },
  {
    label: "shallow",
    params: { totalWidth: 1900, leftArmLength: 1050, rightArmLength: 950, cabinetDepth: 300, cabinetHeight: 350, sideClearance: 40 },
  },
  {
    label: "tall",
    params: { totalWidth: 2275, leftArmLength: 1650, rightArmLength: 1200, cabinetDepth: 400, cabinetHeight: 700 },
  },
  {
    label: "decimal-thickness",
    params: {
      totalWidth: 2325, leftArmLength: 1510, rightArmLength: 1385, cabinetDepth: 410, cabinetHeight: 425,
      featureWidth: 16.5, frontPanelThickness: 18.5, sideClearance: 52.5, clearance: 2.8,
    },
  },
];

let stressIndex = 0;
for (const depth of [320, 400, 520]) {
  for (const featureWidth of [15, 18]) {
    for (const sideClearance of [35, 65]) {
      for (const asymmetric of [false, true]) {
        stressIndex += 1;
        const frontPanelThickness = featureWidth === 15 ? 16 : 20;
        cases.push({
          label: `stress-${stressIndex}`,
          params: {
            totalWidth: 2 * depth + 2 * (sideClearance + frontPanelThickness) + 950 + stressIndex * 3,
            leftArmLength: depth + sideClearance + 620 + (asymmetric ? 170 : 0),
            rightArmLength: depth + sideClearance + 620 + (asymmetric ? 0 : 90),
            cabinetDepth: depth,
            cabinetHeight: 420 + (stressIndex % 3) * 40,
            featureWidth,
            frontPanelThickness,
            sideClearance,
            runLedGroove: { LEFT: stressIndex % 2 === 0, BACK: true, RIGHT: stressIndex % 3 === 0 },
            zones: {
              LEFT: [{ type: "up_flap", width: 300 }, { type: "fixed_panel", width: 300 }],
              BACK: [{ type: "up_flap", width: 300 }, { type: "open", width: 300 }, { type: "up_flap", width: 300 }],
              RIGHT: [{ type: "fixed_panel", width: 300 }, { type: "up_flap", width: 300 }],
            },
          },
        });
      }
    }
  }
}

for (const testCase of cases) {
  const result = generateUShapeOverheadCabinet(testCase.params);
  assertValid(result, testCase.label);
  for (const run of result.runs) {
    const expectedZones = testCase.params.zones?.[run.id]?.length || 1;
    const expectedDividers = expectedZones + 1;
    assert.equal(countDividers(run), expectedDividers, `${testCase.label}/${run.id}: corner divider count`);
  }
  const connectors = result.worldBoards.filter((board) => board.localBoardId.startsWith("U_CONNECTOR"));
  assert.equal(connectors.length, 2, `${testCase.label}: connector count`);
  const clearanceFronts = result.worldBoards.filter((board) => board.boardType === "u_clearance_fixed_panel");
  assert.equal(clearanceFronts.length, 4, `${testCase.label}: clearance front count`);
  for (const run of result.runs) {
    const boardIds = new Set(run.result.boards.map((board) => board.id));
    assert.equal(boardIds.size, run.result.boards.length, `${testCase.label}/${run.id}: duplicate local board IDs`);
    for (const relation of run.result.relationshipDeclarations) {
      assert(boardIds.has(relation.panelAId), `${testCase.label}/${run.id}: relationship panelA escaped run`);
      assert(boardIds.has(relation.panelBId), `${testCase.label}/${run.id}: relationship panelB escaped run`);
      assert(!relation.panelAId.startsWith("U_CONNECTOR"), `${testCase.label}/${run.id}: connector hardware relationship forbidden`);
      assert(!relation.panelBId.startsWith("U_CONNECTOR"), `${testCase.label}/${run.id}: connector hardware relationship forbidden`);
    }
    const connectorCuts = run.result.features.filter((feature) =>
      feature.type === "u_connector_bp_groove" || feature.type === "u_connector_t3_through_groove"
    );
    assert.equal(connectorCuts.length, run.id === "BACK" ? 4 : 0, `${testCase.label}/${run.id}: connector cut count`);
    for (const cut of connectorCuts) {
      const target = run.result.boards.find((board) => board.id === cut.targetBoardId);
      assert(target, `${testCase.label}/${run.id}: cut target missing`);
      assert(["BP", "T3"].includes(target.id), `${testCase.label}/${run.id}: connector cut targeted ${target.id}`);
      assert(cut.x[0] >= target.x0 - 0.001 && cut.x[1] <= target.x1 + 0.001, `${testCase.label}/${run.id}: cut X outside target`);
      assert(cut.y[0] >= target.y0 - 0.001 && cut.y[1] <= target.y1 + 0.001, `${testCase.label}/${run.id}: cut Y outside target`);
    }
  }
}

const runtimeDefaults = generateUShapeOverheadCabinet({});
assert.equal(runtimeDefaults.params.totalWidth, 2275);
assert.equal(runtimeDefaults.params.cabinetDepth, 400);
assert.equal(runtimeDefaults.params.cabinetHeight, 400);
assertValid(runtimeDefaults, "runtime defaults");

const ledResult = generateUShapeOverheadCabinet(cases.find((entry) => entry.label === "independent LED").params);
for (const run of ledResult.runs) {
  const hasLed = run.result.features.some((feature) => feature.type === "t3_groove");
  assert.equal(hasLed, run.id === "BACK", `${run.id}: independent LED switch`);
}

const bridge = spawnSync(
  process.execPath,
  [path.join(pluginRoot, "scripts", "u_shape_overhead_from_params.js")],
  {
    cwd: repoRoot,
    input: JSON.stringify({ params: cases[0].params }),
    encoding: "utf8",
    timeout: 30000,
  },
);
assert.equal(bridge.status, 0, bridge.stderr);
const bridgePayload = JSON.parse(bridge.stdout);
assert.equal(bridgePayload.ok, true);
assert.equal(bridgePayload.result.runs.length, 3);

const fusionSource = fs.readFileSync(path.join(pluginRoot, "modules", "general_tall", "fusion_adapter.py"), "utf8");
assert(fusionSource.includes("def create_u_shape_overhead_assembly("));
assert(fusionSource.includes("avoid_existing_origin=False"));
assert(fusionSource.includes("def _compose_occurrence_matrix("));
assert(fusionSource.includes("_set_single_body_participants(ext_input, body)"));
assert(fusionSource.includes("\"uConnectorBpGrooves\""));
assert(fusionSource.includes("\"uConnectorT3Grooves\""));
assert(fusionSource.includes("_update_run_body_metadata_to_world"));
assert(fusionSource.includes("if create_container_component and container is not root_comp:"));
assert(fusionSource.includes("Final pass: verify every run received a body-move pose"));
assert(fusionSource.includes("Build each run in LOCAL identity first"));
assert(fusionSource.includes("def _pose_run_via_body_moves("));
assert(fusionSource.includes("def audit_u_shape_footprint("));
assert(fusionSource.includes("NOT_U_FOOTPRINT"));
assert(fusionSource.includes("def audit_board_contact_contracts("));
assert(fusionSource.includes("def audit_u_shape_top_contacts("));
assert(fusionSource.includes("\"caseFingerprint\""));
assert(fusionSource.includes("\"contactFailed\""));
assert(
  /origin_rotation_deg=0\.0[\s\S]*_pose_run_via_body_moves\(/.test(fusionSource),
  "T4/local postprocess must finish before body-move U pose is applied",
);

const pluginSource = fs.readFileSync(path.join(pluginRoot, "UnifiedCabinetPlugin.py"), "utf8");
assert(pluginSource.includes("\"uShapeOverhead.generate\""));
assert(pluginSource.includes("\"uShapeOverhead.createFusionBodies\""));
const paletteSource = fs.readFileSync(path.join(pluginRoot, "palette.html"), "utf8");
assert(paletteSource.includes("转角接触异常"));
for (const id of ["uohParamsPanel", "uohWorkspacePanel", "uohValidationPanel", "uohPlanView"]) {
  assert(paletteSource.includes(`id="${id}"`), `palette missing ${id}`);
}
for (const match of paletteSource.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)) {
  if (match[1].trim()) new vm.Script(match[1], { filename: "palette-inline.js" });
}
const uohIds = [...paletteSource.matchAll(/id="(uoh[^"]+)"/g)].map((match) => match[1]);
assert.equal(new Set(uohIds).size, uohIds.length, "duplicate UOH palette IDs");

const invalid = generateUShapeOverheadCabinet({
  totalWidth: 900,
  leftArmLength: 500,
  rightArmLength: 500,
  cabinetDepth: 450,
  cabinetHeight: 100,
});
assert(invalid.validation.errors.length > 0);
assert.equal(invalid.runs.length, 0);

console.log(`OK U Shape OHC self-check (${cases.length} dimensional cases + defaults/assembly/cut-isolation audits)`);
