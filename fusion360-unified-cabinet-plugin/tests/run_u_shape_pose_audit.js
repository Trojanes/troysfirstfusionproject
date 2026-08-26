/**
 * Offline U-Shape OHC pose / assembly audit.
 * Cannot drive Fusion's viewport, but verifies:
 *  1) generator world poses form a real U (not three parallel runs)
 *  2) Fusion adapter finishes local postprocess before baking the U pose
 *  3) final-pose math matches the generator transform contract
 *  4) cut targets stay inside their own run boards
 */
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { generateUShapeOverheadCabinet } from "../../modules/uShapeOverheadCabinet/generator.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.resolve(here, "..");
const adapterSource = fs.readFileSync(
  path.join(pluginRoot, "modules", "general_tall", "fusion_adapter.py"),
  "utf8",
);
const adapterBuild = adapterSource.match(/ADAPTER_BUILD = "([^"]+)"/)?.[1] || "missing";

function close(a, b, tol = 0.05) {
  return Math.abs(a - b) <= tol;
}

/** Match fusion_adapter._compose_occurrence_matrix (mm space, Z rotation). */
function composeOccurrence(tx, ty, rotationDeg) {
  const rad = rotationDeg * Math.PI / 180;
  const cos = Math.round(Math.cos(rad));
  const sin = Math.round(Math.sin(rad));
  return (x, y) => [tx + x * cos - y * sin, ty + x * sin + y * cos];
}

function board(result, runId, localId) {
  return result.worldBoards.find((entry) => entry.id === `${runId}.${localId}`);
}

function localBoard(result, runId, localId) {
  return result.runs.find((run) => run.id === runId)?.result.boards.find((entry) => entry.id === localId);
}

function assertUFootprint(result, label) {
  const params = result.params;
  const depth = params.cabinetDepth;
  const total = params.totalWidth;
  const leftLen = params.leftArmLength;
  const rightLen = params.rightArmLength;

  const leftBp = board(result, "LEFT", "BP");
  const backBp = board(result, "BACK", "BP");
  const rightBp = board(result, "RIGHT", "BP");
  assert(leftBp && backBp && rightBp, `${label}: missing BP boards`);

  // LEFT arm: thin in X (~depth), long in Y.
  assert(close(leftBp.x1 - leftBp.x0, depth), `${label}: LEFT BP should span depth in X`);
  assert(close(leftBp.y1 - leftBp.y0, leftLen - depth), `${label}: LEFT BP should exclude BACK corner`);
  assert(close(leftBp.x0, 0), `${label}: LEFT BP at x=0`);
  assert(close(leftBp.y0, depth), `${label}: LEFT BP starts at BACK seam`);

  // BACK: long in X, thin in Y (~depth), at the rear of the U.
  assert(close(backBp.x1 - backBp.x0, total), `${label}: BACK BP full width`);
  assert(close(backBp.y1 - backBp.y0, depth), `${label}: BACK BP should span depth in Y`);
  assert(close(backBp.x0, 0), `${label}: BACK BP owns left corner`);
  assert(close(backBp.y0, 0), `${label}: BACK BP at y=0`);

  // RIGHT arm: thin in X (~depth), long in Y, on the far side.
  assert(close(rightBp.x1 - rightBp.x0, depth), `${label}: RIGHT BP should span depth in X`);
  assert(close(rightBp.y1 - rightBp.y0, rightLen - depth), `${label}: RIGHT BP should exclude BACK corner`);
  assert(close(rightBp.x0, total - depth), `${label}: RIGHT BP at far X`);
  assert(close(rightBp.y0, depth), `${label}: RIGHT BP starts at BACK seam`);

  // Broken/regressed pose (no rotation) would make side runs long in X.
  for (const run of result.runs) {
    if (run.id === "BACK") continue;
    const map = composeOccurrence(run.transform.translateX, run.transform.translateY, 0);
    const local = localBoard(result, run.id, "BP");
    const [wx0] = map(local.x0, local.y0);
    const [wx1] = map(local.x1, local.y0);
    const unrotatedWidth = Math.abs(wx1 - wx0);
    assert(
      Math.abs(unrotatedWidth - run.cabinetWidth) < 1,
      `${label}: sanity — unrotated ${run.id} would be long in X`,
    );
    assert(
      Math.abs((board(result, run.id, "BP").x1 - board(result, run.id, "BP").x0) - depth) < 1,
      `${label}: rotated ${run.id} must NOT stay as a long parallel run`,
    );
  }
}

function assertOccurrenceMathMatchesGenerator(result, label) {
  for (const run of result.runs) {
    const map = composeOccurrence(
      run.transform.translateX,
      run.transform.translateY,
      run.transform.rotationDeg,
    );
    for (const local of run.result.boards) {
      if (!["BP", "T3"].includes(local.id) && !local.id.startsWith("U_CONNECTOR") && !local.id.startsWith("D")) continue;
      const corners = [
        map(local.x0, local.y0),
        map(local.x0, local.y1),
        map(local.x1, local.y0),
        map(local.x1, local.y1),
      ];
      const xs = corners.map(([x]) => x);
      const ys = corners.map(([, y]) => y);
      const world = board(result, run.id, local.id);
      assert(world, `${label}: missing world ${run.id}.${local.id}`);
      assert(close(world.x0, Math.min(...xs)), `${label}: ${run.id}.${local.id} x0 mismatch`);
      assert(close(world.x1, Math.max(...xs)), `${label}: ${run.id}.${local.id} x1 mismatch`);
      assert(close(world.y0, Math.min(...ys)), `${label}: ${run.id}.${local.id} y0 mismatch`);
      assert(close(world.y1, Math.max(...ys)), `${label}: ${run.id}.${local.id} y1 mismatch`);
    }
  }
}

function finalTopBBox(boardRow, rotationDeg, rearNotch) {
  if (!boardRow || rearNotch <= 0) return boardRow;
  if (rotationDeg === 90) {
    return { ...boardRow, x0: boardRow.x0 - rearNotch, x1: boardRow.x1 - rearNotch };
  }
  if (rotationDeg === -90) {
    return { ...boardRow, x0: boardRow.x0 + rearNotch, x1: boardRow.x1 + rearNotch };
  }
  if (rotationDeg === 180) {
    return { ...boardRow, y0: boardRow.y0 - rearNotch, y1: boardRow.y1 - rearNotch };
  }
  return { ...boardRow, y0: boardRow.y0 + rearNotch, y1: boardRow.y1 + rearNotch };
}

function assertAssemblyContacts(result, label) {
  const leftConnector = board(result, "BACK", "U_CONNECTOR_LEFT");
  const rightConnector = board(result, "BACK", "U_CONNECTOR_RIGHT");
  const leftRearDivider = result.worldBoards
    .filter((entry) => entry.runId === "LEFT" && /^D\d+$/.test(entry.localBoardId))
    .sort((a, b) => a.y0 - b.y0)[0];
  const rightRearDivider = result.worldBoards
    .filter((entry) => entry.runId === "RIGHT" && /^D\d+$/.test(entry.localBoardId))
    .sort((a, b) => a.y0 - b.y0)[0];
  assert(close(leftConnector.y1, leftRearDivider.y0), `${label}: LEFT connector/side rear divider contact`);
  assert(close(rightConnector.y1, rightRearDivider.y0), `${label}: RIGHT connector/side rear divider contact`);

  // T1/T2 contacts are evaluated after Fusion's TCH-1 rear-notch placement.
  const rearNotch = (result.params.topClearanceHeight ?? 40) - 1;
  const leftT1 = finalTopBBox(board(result, "LEFT", "T1"), 90, rearNotch);
  const backT1 = finalTopBBox(board(result, "BACK", "T1"), 180, rearNotch);
  const rightT1 = finalTopBBox(board(result, "RIGHT", "T1"), -90, rearNotch);
  const leftT2 = finalTopBBox(board(result, "LEFT", "T2"), 90, rearNotch);
  const rightT2 = finalTopBBox(board(result, "RIGHT", "T2"), -90, rearNotch);
  const backT2 = finalTopBBox(board(result, "BACK", "T2"), 180, rearNotch);
  assert(close(leftT1.y0, backT2.y1), `${label}: LEFT.T1 meets BACK.T2`);
  assert(close(rightT1.y0, backT2.y1), `${label}: RIGHT.T1 meets BACK.T2`);
  assert(close(leftT2.y0, backT2.y1), `${label}: LEFT.T2 meets BACK.T2`);
  assert(close(rightT2.y0, backT2.y1), `${label}: RIGHT.T2 meets BACK.T2`);
  assert(close(backT1.x0, leftT1.x1), `${label}: BACK.T1 meets LEFT.T1 side face`);
  assert(close(backT1.x1, rightT1.x0), `${label}: BACK.T1 meets RIGHT.T1 side face`);
}

function assertCutIsolation(result, label) {
  for (const run of result.runs) {
    const ids = new Set(run.result.boards.map((entry) => entry.id));
    for (const feature of run.result.features) {
      const target = feature.targetBoardId || feature.boardId;
      if (!target) continue;
      if (feature.type === "rangehood_group" || String(feature.type || "").startsWith("rangehood_")) {
        if (run.id === "BACK") {
          throw new Error(`${label}/${run.id}: rangehood is forbidden on BACK/corners`);
        }
        // LEFT/RIGHT NCE rangehood is allowed; cuts must still stay inside the run.
      }
      assert(ids.has(target), `${label}/${run.id}: cut ${feature.id || feature.type} targets foreign board ${target}`);
      if (feature.type === "u_connector_bp_groove") assert.equal(target, "BP");
      if (feature.type === "u_connector_t3_through_groove") assert.equal(target, "T3");
      if (feature.type === "t3_groove") assert.equal(target, "T3");
    }
  }
}

function assertFusionAdapterPoseContract() {
  const source = fs.readFileSync(
    path.join(pluginRoot, "modules", "general_tall", "fusion_adapter.py"),
    "utf8",
  );
  assert(/ADAPTER_BUILD = \"20\d{2}-\d{2}-\d{2}-u-shape-ohc-\d+\"/.test(source));
  assert(source.includes("def measure_u_shape_assembly("));
  assert(source.includes("def _compose_occurrence_matrix("));
  assert(source.includes("Build each run in LOCAL identity first"));
  assert(source.includes("def _pose_run_via_body_moves("));
  assert(source.includes("Final pass: verify every run received a body-move pose"));
  const createCall = source.slice(
    source.indexOf("run_summary = create_rough_bodies_from_board_result("),
    source.indexOf("run_component = run_summary.get(\"_containerComponent\")"),
  );
  assert(createCall.includes("origin_rotation_deg=0.0"), "create call must stay local/identity");
  assert(createCall.includes("origin_x_mm=0.0"), "create call must stay at local origin X");
  assert(createCall.includes("origin_y_mm=0.0"), "create call must stay at local origin Y");
  const uCreate = source.slice(source.indexOf("def create_u_shape_overhead_assembly("));
  assert(
    uCreate.indexOf("enable_overhead_postprocess=True")
      < uCreate.indexOf("_pose_run_via_body_moves("),
    "local T4 postprocess must precede body-move U pose",
  );
}

const cases = [
  {
    label: "default-2275",
    params: {
      totalWidth: 2275,
      leftArmLength: 1500,
      rightArmLength: 1500,
      cabinetDepth: 400,
      cabinetHeight: 400,
      featureWidth: 15,
      frontPanelThickness: 18,
    },
  },
  {
    label: "asymmetric",
    params: {
      totalWidth: 2400,
      leftArmLength: 1700,
      rightArmLength: 1200,
      cabinetDepth: 400,
      cabinetHeight: 400,
    },
  },
  {
    label: "screenshot-match",
    params: {
      totalWidth: 2275,
      leftArmLength: 1500,
      rightArmLength: 1500,
      cabinetDepth: 400,
      cabinetHeight: 400,
      featureWidth: 15,
      frontPanelThickness: 18,
      topClearanceHeight: 40,
      sideClearance: 50,
      clearance: 2.5,
      runLedGroove: { LEFT: true, BACK: true, RIGHT: true },
    },
  },
];

const reports = [];
for (const testCase of cases) {
  const result = generateUShapeOverheadCabinet(testCase.params);
  assert.deepEqual(result.validation.errors, [], `${testCase.label}: ${result.validation.errors.join("; ")}`);
  assert(result.audit.every((row) => row.ok), `${testCase.label}: ${JSON.stringify(result.audit)}`);
  assertUFootprint(result, testCase.label);
  assertOccurrenceMathMatchesGenerator(result, testCase.label);
  assertAssemblyContacts(result, testCase.label);
  assertCutIsolation(result, testCase.label);
  reports.push({
    label: testCase.label,
    transforms: result.runs.map((run) => ({ id: run.id, ...run.transform })),
    worldBp: ["LEFT", "BACK", "RIGHT"].map((id) => {
      const bp = board(result, id, "BP");
      return { id, x0: bp.x0, x1: bp.x1, y0: bp.y0, y1: bp.y1 };
    }),
  });
}

assertFusionAdapterPoseContract();

// Reproduce the spike failure mode offline: Z-pose before T4's local X fold
// turns the ~1500 mm run length into world-Z height.
function rotateX([x, y, z], deg) {
  const rad = deg * Math.PI / 180;
  const c = Math.round(Math.cos(rad));
  const s = Math.round(Math.sin(rad));
  return [x, y * c - z * s, y * s + z * c];
}
function rotateZ([x, y, z], deg) {
  const rad = deg * Math.PI / 180;
  const c = Math.round(Math.cos(rad));
  const s = Math.round(Math.sin(rad));
  return [x * c - y * s, x * s + y * c, z];
}
const t4Corners = [
  [0, 0, 385], [1500, 0, 385], [0, 400, 385], [1500, 400, 400],
  [0, 0, 400], [1500, 0, 400], [0, 400, 400], [1500, 400, 385],
];
function centerOf(points) {
  return [
    points.reduce((s, p) => s + p[0], 0) / points.length,
    points.reduce((s, p) => s + p[1], 0) / points.length,
    points.reduce((s, p) => s + p[2], 0) / points.length,
  ];
}
function rotateXAbout(point, center, deg) {
  const [dx, dy, dz] = [point[0] - center[0], point[1] - center[1], point[2] - center[2]];
  const [rx, ry, rz] = rotateX([dx, dy, dz], deg);
  return [rx + center[0], ry + center[1], rz + center[2]];
}
// Wrong order: Z-pose then X-fold about origin (old spike).
const wrongOrder = t4Corners.map((p) => rotateX(rotateZ(p, 90), 90));
// Right order: X-fold about body center, then Z-pose (matches Fusion).
const folded = (() => {
  const pivot = centerOf(t4Corners);
  return t4Corners.map((p) => rotateXAbout(p, pivot, 90));
})();
const rightOrder = folded.map((p) => rotateZ(p, 90));
const wrongHeight = Math.max(...wrongOrder.map((p) => p[2])) - Math.min(...wrongOrder.map((p) => p[2]));
const rightHeight = Math.max(...rightOrder.map((p) => p[2])) - Math.min(...rightOrder.map((p) => p[2]));
assert(wrongHeight > 1000, `expected spike failure mode, got height ${wrongHeight}`);
assert(rightHeight < 500, `expected local-then-pose T4 height < 500, got ${rightHeight}`);

console.log("OK U Shape pose audit");
console.log(JSON.stringify({
  note: "Offline math pose audit. Fusion XYZ compare lives in logs/u_shape_ohc_fusion_measure.json after create/self-check.",
  adapterBuildRequired: adapterBuild,
  cases: reports,
}, null, 2));
