/**
 * U Shape OHC autonomous offline loop (no Fusion required).
 *
 * Agent workflow:
 *   1. node .../run_u_shape_ohc_autoloop.js
 *   2. Read logs/u_shape_ohc_loop_report.json (+ simulated measure)
 *   3. If failed → fix code → re-run
 *
 * Fusion CAD cannot be launched from Cursor. Assembly poses are simulated
 * mathematically (Style-1 T4 fold then run Z pose) so the agent can loop
 * without opening Fusion. Optional real Fusion AABB log is merged if present.
 */
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { generateUShapeOverheadCabinet } from "../../modules/uShapeOverheadCabinet/generator.ts";
import {
  auditBoardContacts,
  auditForbiddenOverlaps,
  certifyFusionEvidence,
  fingerprintParams,
} from "./assembly_loop_core.js";
import {
  runGeneratorCaseMatrix,
  summarizeGeneratorLoop,
} from "./generator_loop_framework.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.resolve(here, "..");
const logDir = path.join(pluginRoot, "logs");
const reportPath = path.join(logDir, "u_shape_ohc_loop_report.json");
const fusionLogPath = path.join(logDir, "u_shape_ohc_fusion_measure.json");
const simulatedLogPath = path.join(logDir, "u_shape_ohc_simulated_measure.json");
const adapterPath = path.join(pluginRoot, "modules", "general_tall", "fusion_adapter.py");
const palettePath = path.join(pluginRoot, "palette.html");
const adapterSource = fs.readFileSync(adapterPath, "utf8");
const paletteSource = fs.readFileSync(palettePath, "utf8");
const adapterBuildMatch = adapterSource.match(/ADAPTER_BUILD = "([^"]+)"/);
const requiredAdapterBuild = adapterBuildMatch?.[1] || "missing";
const CASE_FINGERPRINT_KEYS = [
  "totalWidth",
  "leftArmLength",
  "rightArmLength",
  "cabinetDepth",
  "cabinetHeight",
  "topClearanceHeight",
  "frontPanelThickness",
  "featureWidth",
  "clearance",
  "sideClearance",
  "geometryRevision",
];
const REQUIRED_CASE_AUDITS = [
  "ledGrooveAudit",
  "clearanceFrontAudit",
  "cornerOwnershipAudit",
  "backCornerClosureAudit",
  "postprocessAudit",
  "backT3NotchAudit",
  "t4GeometryAudit",
];

function loopCaseFingerprints(report) {
  return (report.cases || []).map((row) => fingerprintParams(row.params || {}, CASE_FINGERPRINT_KEYS));
}

function fusionCaseFingerprints(fusion) {
  return (fusion?.cases || []).map((row) => (
    row.caseFingerprint
    || fingerprintParams(row.params || {}, CASE_FINGERPRINT_KEYS)
  ));
}

const STYLE1_CONTACT_CONTRACTS = [
  { id: "left_t1_to_back_t2", a: "LEFT.T1", b: "BACK.T2", aFace: "y0", bFace: "y1", overlapAxes: ["x", "z"] },
  { id: "right_t1_to_back_t2", a: "RIGHT.T1", b: "BACK.T2", aFace: "y0", bFace: "y1", overlapAxes: ["x", "z"] },
  { id: "left_t2_to_back_t2", a: "LEFT.T2", b: "BACK.T2", aFace: "y0", bFace: "y1", overlapAxes: ["x", "z"] },
  { id: "right_t2_to_back_t2", a: "RIGHT.T2", b: "BACK.T2", aFace: "y0", bFace: "y1", overlapAxes: ["x", "z"] },
  { id: "back_t1_to_left_t1", a: "BACK.T1", b: "LEFT.T1", aFace: "x0", bFace: "x1", overlapAxes: ["y", "z"] },
  { id: "back_t1_to_right_t1", a: "BACK.T1", b: "RIGHT.T1", aFace: "x1", bFace: "x0", overlapAxes: ["y", "z"] },
];

const STYLE1_FORBIDDEN_OVERLAPS = [
  { id: "left_t1_back_t2_overlap", a: "LEFT.T1", b: "BACK.T2" },
  { id: "right_t1_back_t2_overlap", a: "RIGHT.T1", b: "BACK.T2" },
  { id: "left_t2_back_t2_overlap", a: "LEFT.T2", b: "BACK.T2" },
  { id: "right_t2_back_t2_overlap", a: "RIGHT.T2", b: "BACK.T2" },
];

function close(a, b, tol = 0.05) {
  return Math.abs(Number(a) - Number(b)) <= tol;
}

function rotateX([x, y, z], deg) {
  const rad = (deg * Math.PI) / 180;
  const c = Math.round(Math.cos(rad));
  const s = Math.round(Math.sin(rad));
  return [x, y * c - z * s, y * s + z * c];
}

function rotateZ([x, y, z], deg) {
  const rad = (deg * Math.PI) / 180;
  const c = Math.round(Math.cos(rad));
  const s = Math.round(Math.sin(rad));
  return [x * c - y * s, x * s + y * c, z];
}

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

function bboxFromPoints(points) {
  const xs = points.map((p) => p[0]);
  const ys = points.map((p) => p[1]);
  const zs = points.map((p) => p[2]);
  return {
    x0: Math.min(...xs),
    x1: Math.max(...xs),
    y0: Math.min(...ys),
    y1: Math.max(...ys),
    z0: Math.min(...zs),
    z1: Math.max(...zs),
  };
}

function boardCorners(board) {
  const corners = [];
  for (const x of [board.x0, board.x1]) {
    for (const y of [board.y0, board.y1]) {
      for (const z of [board.z0, board.z1]) corners.push([x, y, z]);
    }
  }
  return corners;
}

function boardProfileCorners(board) {
  if (board.profilePlane !== "XY" || !Array.isArray(board.profileVector) || !board.profileVector.length) {
    return boardCorners(board);
  }
  return board.profileVector.flatMap((point) => (
    [board.z0, board.z1].map((z) => [
      Number(board.x0 || 0) + Number(point.x || 0),
      Number(board.y0 || 0) + Number(point.y || 0),
      z,
    ])
  ));
}

/** Simulate Fusion Style-1 postprocess + U run pose without opening Fusion. */
function simulateFusionAssembledBoards(result) {
  const params = result.params;
  const cd = params.cabinetDepth;
  const fg = params.featureWidth;
  const clearance = params.clearance ?? 2.5;
  const height = params.cabinetHeight;
  const boards = [];
  const findings = [];
  let spikeDetected = false;

  for (const run of result.runs) {
    const rotZ = run.transform.rotationDeg;
    const tx = run.transform.translateX;
    const ty = run.transform.translateY;
    for (const local of run.result.boards) {
      let corners = local.id === "T4" ? boardProfileCorners(local) : boardCorners(local);
      // Match `_placement_offset_mm` before overhead postprocess. This stage
      // was previously absent, allowing generator and simulator to agree while
      // real Fusion moved T1/T2 another TCH-1 (39 mm).
      if (local.id === "T1" || local.id === "T2") {
        const rearNotchShift = (params.topClearanceHeight ?? 40) - 1;
        corners = corners.map(([x, y, z]) => [x, y + rearNotchShift, z]);
      }
      // Match Fusion `_oh_postprocess_bodies`: rotate T4 about center, then translate.
      if (local.id === "T4") {
        const dy = cd - (2 * fg + clearance);
        const dz = -clearance;
        const pivot = centerOf(corners);
        corners = corners.map((p) => rotateXAbout(p, pivot, 90));
        corners = corners.map(([x, y, z]) => [x, y + dy, z + dz]);
      } else if (local.id === "BP" || local.id === "T1" || local.id === "T2") {
        corners = corners.map(([x, y, z]) => [x, y, z + fg]);
      } else if (local.id === "T3") {
        const tch = params.topClearanceHeight ?? 40;
        const dz = -(tch + fg - 14) + fg;
        corners = corners.map(([x, y, z]) => [x, y, z + dz]);
      }
      const world = corners.map((p) => {
        const [x, y, z] = rotateZ(p, rotZ);
        return [x + tx, y + ty, z];
      });
      const bbox = bboxFromPoints(world);
      const sizeZ = bbox.z1 - bbox.z0;
      const row = {
        id: `${run.id}.${local.id}`,
        runId: run.id,
        localBoardId: local.id,
        bboxMm: bbox,
        centerMm: {
          x: (bbox.x0 + bbox.x1) / 2,
          y: (bbox.y0 + bbox.y1) / 2,
          z: (bbox.z0 + bbox.z1) / 2,
        },
        sizeMm: { x: bbox.x1 - bbox.x0, y: bbox.y1 - bbox.y0, z: sizeZ },
        heightMm: sizeZ,
        spikeDetected: sizeZ > height + 120,
        simulated: true,
      };
      boards.push(row);
      if (row.spikeDetected) {
        spikeDetected = true;
        findings.push({
          severity: "error",
          code: "sim_t4_spike",
          detail: `${row.id} simulated Z span ${sizeZ.toFixed(1)} > cabinetHeight+120`,
        });
      }
    }
  }

  // Wrong-order regression: Z-pose before T4 fold must still fail hard.
  for (const run of result.runs) {
    const t4 = run.result.boards.find((entry) => entry.id === "T4");
    if (!t4) continue;
    const wrong = boardProfileCorners(t4)
      .map((p) => rotateZ(p, run.transform.rotationDeg))
      .map((p) => rotateX(p, 90));
    const wrongBb = bboxFromPoints(wrong);
    const wrongH = wrongBb.z1 - wrongBb.z0;
    if (Math.abs(run.transform.rotationDeg) === 90 && wrongH < height + 200) {
      findings.push({
        severity: "error",
        code: "sim_spike_oracle_weak",
        detail: `${run.id}: wrong-order height ${wrongH} should still spike`,
      });
    }
  }

  // Spike = single-board Z extent, not the union of absolute Z (Style-1 rotate
  // about origin can float T4 in Z while its thickness/height stays ~Cd).
  const contacts = auditBoardContacts(boards, STYLE1_CONTACT_CONTRACTS);
  findings.push(...contacts.findings);
  const overlaps = auditForbiddenOverlaps(boards, STYLE1_FORBIDDEN_OVERLAPS);
  findings.push(...overlaps.findings);
  const maxBoardHeight = boards.length ? Math.max(...boards.map((b) => b.heightMm)) : 0;
  return {
    ok: findings.length === 0 && !spikeDetected,
    source: "offline_fusion_simulator",
    spikeDetected,
    boards,
    findings,
    contacts,
    forbiddenOverlaps: overlaps,
    maxBoardHeightMm: maxBoardHeight,
    assemblyHeightMm: maxBoardHeight,
  };
}

function board(result, runId, localId) {
  return result.worldBoards.find((entry) => entry.id === `${runId}.${localId}`);
}

function buildCases() {
  const base = {
    totalWidth: 2275,
    leftArmLength: 1500,
    rightArmLength: 1500,
    cabinetDepth: 400,
    cabinetHeight: 400,
    featureWidth: 15,
    frontPanelThickness: 18,
    sideClearance: 50,
  };
  return [
    { id: "default", params: { ...base } },
    { id: "asymmetric", params: { ...base, leftArmLength: 1700, rightArmLength: 1200, totalWidth: 2400 } },
    { id: "thick", params: { ...base, featureWidth: 18, frontPanelThickness: 19, sideClearance: 60 } },
    { id: "shallow", params: { ...base, cabinetDepth: 320, leftArmLength: 1200, rightArmLength: 1100, totalWidth: 1900 } },
    { id: "tall", params: { ...base, cabinetHeight: 700 } },
    {
      id: "multi-zone",
      params: {
        ...base,
        zones: {
          LEFT: [{ type: "up_flap", width: 500 }, { type: "fixed_panel", width: 550 }],
          BACK: [{ type: "up_flap", width: 450 }, { type: "open", width: 443 }, { type: "up_flap", width: 450 }],
          RIGHT: [{ type: "fixed_panel", width: 500 }, { type: "up_flap", width: 550 }],
        },
      },
    },
    {
      id: "led-mix",
      params: { ...base, runLedGroove: { LEFT: false, BACK: true, RIGHT: false } },
    },
  ];
}

function auditCase({ caseId, inputParams: params, result }) {
  const findings = [];
  if (result.validation.errors.length) {
    findings.push({ severity: "error", code: "validation", detail: result.validation.errors.join("; ") });
    return { caseId, ok: false, findings, params: result.params };
  }
  for (const row of result.audit) {
    if (!row.ok) findings.push({ severity: "error", code: row.id, detail: row.detail });
  }

  const depth = result.params.cabinetDepth;
  const height = result.params.cabinetHeight;
  for (const runId of ["LEFT", "BACK", "RIGHT"]) {
    const bp = board(result, runId, "BP");
    if (!bp) {
      findings.push({ severity: "error", code: "missing_bp", detail: `${runId}.BP missing` });
      continue;
    }
    if (runId === "BACK") {
      if (!close(bp.y1 - bp.y0, depth)) {
        findings.push({ severity: "error", code: "back_not_rotated", detail: `BACK BP depth-in-Y=${bp.y1 - bp.y0}` });
      }
    } else if (!close(bp.x1 - bp.x0, depth)) {
      findings.push({
        severity: "error",
        code: "side_not_rotated",
        detail: `${runId} BP still long in X (${bp.x1 - bp.x0}); looks like parallel straight run`,
      });
    }
  }
  const leftBp = board(result, "LEFT", "BP");
  const backBp = board(result, "BACK", "BP");
  const rightBp = board(result, "RIGHT", "BP");
  const cornerOwnershipOk = leftBp && backBp && rightBp
    && close(backBp.x0, 0) && close(backBp.x1, result.params.totalWidth)
    && close(backBp.y0, 0) && close(backBp.y1, depth)
    && close(leftBp.y0, depth) && close(leftBp.y1, result.params.leftArmLength)
    && close(rightBp.y0, depth) && close(rightBp.y1, result.params.rightArmLength);
  if (!cornerOwnershipOk) {
    findings.push({
      severity: "error",
      code: "back_corner_ownership",
      detail: "BACK must own both corner cells and side BP boards must begin at y=depth",
    });
  }

  const simulated = simulateFusionAssembledBoards(result);
  for (const finding of simulated.findings) findings.push(finding);
  if (simulated.maxBoardHeightMm != null && simulated.maxBoardHeightMm > height + 120) {
    findings.push({
      severity: "error",
      code: "sim_board_spike",
      detail: `max simulated board height ${simulated.maxBoardHeightMm.toFixed(1)} > cabinetHeight+120`,
    });
  }

  const SIDE_LED_BRANCH_INSET = 80;
  for (const run of result.runs) {
    const ids = new Set(run.result.boards.map((entry) => entry.id));
    for (const feature of run.result.features) {
      const target = feature.targetBoardId || feature.boardId;
      if (!target) continue;
      if (!ids.has(target)) {
        findings.push({
          severity: "error",
          code: "cut_escape",
          detail: `${run.id}/${feature.id || feature.type} → ${target}`,
        });
      }
    }
    if (run.id === "BACK") continue;
    const led = run.result.features.find((feature) => (
      feature?.type === "t3_groove" && feature?.targetBoardId === "T3"
    ));
    if (!led?.main) continue;
    const width = run.cabinetWidth;
    const { x0, x1 } = led.main;
    const expectedRearY = result.params.cabinetDepth;
    const expectedOpenY = run.id === "LEFT" ? result.params.leftArmLength : result.params.rightArmLength;
    const finalY0 = run.id === "LEFT"
      ? run.transform.translateY + width - x1
      : run.transform.translateY - width + x0;
    const finalY1 = run.id === "LEFT"
      ? run.transform.translateY + width - x0
      : run.transform.translateY - width + x1;
    if (!close(finalY0, expectedRearY, 0.05) || !close(finalY1, expectedOpenY, 0.05)) {
      findings.push({
        severity: "error",
        code: "side_led_extent",
        detail: `${run.id} final LED worldY [${finalY0},${finalY1}] expected BACK seam=${expectedRearY} through front tip=${expectedOpenY}`,
      });
    }
    const adapterX0 = width - x1;
    const adapterX1 = width - x0;
    const adapterPoseOk = led.adapterMirrorX === true
      && close(finalY0, expectedRearY, 0.05)
      && close(finalY1, expectedOpenY, 0.05);
    if (!adapterPoseOk) {
      findings.push({
        severity: "error",
        code: "side_led_adapter_pose",
        detail: `${run.id} Adapter mirrored range [${adapterX0},${adapterX1}] does not compensate final T3 profile pose`,
      });
    }
    const branches = Array.isArray(led.branches) ? led.branches : [];
    const finalBranchCenters = branches.map((branch) => {
      const rawCenter = (Number(branch.x0) + Number(branch.x1)) / 2;
      return run.id === "LEFT"
        ? run.transform.translateY + width - rawCenter
        : run.transform.translateY - width + rawCenter;
    }).sort((a, b) => a - b);
    const expectedBranchCenters = [expectedRearY + SIDE_LED_BRANCH_INSET, expectedOpenY - SIDE_LED_BRANCH_INSET];
    if (finalBranchCenters.length !== 2 || finalBranchCenters.some(
      (center, index) => !close(center, expectedBranchCenters[index], 1.0),
    )) {
      findings.push({
        severity: "error",
        code: "side_led_branch_inset",
        detail: `${run.id} final branch centers [${finalBranchCenters}] expected [${expectedBranchCenters}]`,
      });
    }
  }
  const backRun = result.runs.find((run) => run.id === "BACK");
  const backLed = backRun?.result.features.find((feature) => (
    feature?.type === "t3_groove"
  ));
  if (backLed?.main) {
    const rearNotch = result.params.topClearanceHeight - 1;
    const expectedInset = depth
      - result.params.frontPanelThickness
      - result.params.featureWidth
      - rearNotch
      - 10;
    if (!close(backLed.main.x0, expectedInset) || !close(backLed.main.x1, result.params.totalWidth - expectedInset)) {
      findings.push({
        severity: "error",
        code: "back_led_middle_extent",
        detail: `BACK LED [${backLed.main.x0},${backLed.main.x1}] expected [${expectedInset},${result.params.totalWidth - expectedInset}]`,
      });
    }
  }
  if (backRun?.result.features.some((feature) => feature?.role === "u_corner_continuation")) {
    findings.push({ severity: "error", code: "back_led_corner_continuation", detail: "BACK corner continuation is forbidden" });
  }

  const leftC = board(result, "BACK", "U_CONNECTOR_LEFT");
  const rightC = board(result, "BACK", "U_CONNECTOR_RIGHT");
  const fpt = result.params.frontPanelThickness;
  const sideClearance = result.params.sideClearance;
  const sideY0 = depth + fpt;
  const sideY1 = sideY0 + sideClearance;
  const leftFixed = board(result, "LEFT", "FP_CLEARANCE_SIDE");
  const rightFixed = board(result, "RIGHT", "FP_CLEARANCE_SIDE");
  const backAtLeft = board(result, "BACK", "FP_CLEARANCE_RIGHT");
  const backAtRight = board(result, "BACK", "FP_CLEARANCE_LEFT");
  const clearancePoseOk = leftFixed && rightFixed && backAtLeft && backAtRight
    && close(leftFixed.x0, depth) && close(leftFixed.x1, depth + fpt)
    && close(rightFixed.x0, result.params.totalWidth - depth - fpt)
    && close(rightFixed.x1, result.params.totalWidth - depth)
    && close(leftFixed.y0, sideY0) && close(leftFixed.y1, sideY1)
    && close(rightFixed.y0, sideY0) && close(rightFixed.y1, sideY1)
    && close(backAtLeft.y1, leftFixed.y0) && close(backAtRight.y1, rightFixed.y0);
  if (!clearancePoseOk) {
    findings.push({
      severity: "error",
      code: "side_clearance_front_pose",
      detail: `side fixed fronts must be ${sideClearance}×${fpt} at Y=${sideY0}..${sideY1}`,
    });
  }
  for (const runId of ["LEFT", "RIGHT"]) {
    const functionalFronts = result.worldBoards.filter((entry) => (
      entry.runId === runId && /^FP\d+$/.test(entry.localBoardId)
    ));
    if (functionalFronts.some((front) => front.y0 < sideY1 + result.params.clearance - 0.05)) {
      findings.push({
        severity: "error",
        code: "side_clearance_function_overlap",
        detail: `${runId} function front starts before clearance-front boundary + gap`,
      });
    }
  }
  const leftRearDivider = result.worldBoards
    .filter((entry) => entry.runId === "LEFT" && /^D\d+$/.test(entry.localBoardId))
    .sort((a, b) => a.y0 - b.y0)[0];
  const rightRearDivider = result.worldBoards
    .filter((entry) => entry.runId === "RIGHT" && /^D\d+$/.test(entry.localBoardId))
    .sort((a, b) => a.y0 - b.y0)[0];
  if (!leftC || !rightC || !leftRearDivider || !rightRearDivider) {
    findings.push({ severity: "error", code: "connector_missing", detail: "connector/divider contact boards missing" });
  } else {
    if (!close(leftC.y1, leftRearDivider.y0)) {
      findings.push({ severity: "error", code: "left_connector_gap", detail: `${leftC.y1} vs ${leftRearDivider.y0}` });
    }
    if (!close(rightC.y1, rightRearDivider.y0)) {
      findings.push({ severity: "error", code: "right_connector_gap", detail: `${rightC.y1} vs ${rightRearDivider.y0}` });
    }
  }

  // Expected poses must represent the final Adapter pipeline, not raw generator
  // worldBoards. This prevents matching omissions on both sides of the loop.
  const poses = simulated.boards.map((entry) => ({
    ...entry,
    compareMode: entry.id.endsWith(".FP_CLEARANCE_SIDE")
      ? "xy_aabb"
      : /(?:^|\.)(T[34]|FP)/.test(entry.id) ? "height_band" : "aabb",
  }));

  return {
    caseId,
    ok: findings.length === 0,
    findings,
    params: result.params,
    transforms: result.runs.map((run) => ({ id: run.id, ...run.transform })),
    boardCount: result.worldBoards.length,
    poses,
    simulated,
  };
}

function assertAdapterContract() {
  const source = adapterSource;
  const findings = [];
  if (!source.includes("Build each run in LOCAL identity first")) {
    findings.push({ severity: "error", code: "adapter_order", detail: "local-identity-before-pose contract missing" });
  }
  if (!/ADAPTER_BUILD = \"2026-07-3\d-u-shape-ohc-\d+\"/.test(source)) {
    findings.push({ severity: "warn", code: "adapter_build", detail: "unexpected adapter build tag" });
  }
  if (!source.includes("def measure_u_shape_assembly(") || !source.includes("def write_u_shape_fusion_measure_log(")) {
    findings.push({ severity: "error", code: "adapter_measure", detail: "Fusion measure/log helpers missing" });
  }
  if (!source.includes("def compare_u_shape_board_poses(")) {
    findings.push({ severity: "error", code: "adapter_pose_compare", detail: "XYZ pose compare helper missing" });
  }
  if (!source.includes("def audit_u_shape_footprint(") || !source.includes("NOT_U_FOOTPRINT")) {
    findings.push({ severity: "error", code: "adapter_u_footprint", detail: "non-U footprint hard-fail audit missing" });
  }
  if (!source.includes("def audit_board_contact_contracts(") || !source.includes("def audit_u_shape_top_contacts(")) {
    findings.push({ severity: "error", code: "adapter_contact_audit", detail: "final-board contact contract audit missing" });
  }
  if (!source.includes("def audit_u_shape_clearance_fronts(") || !source.includes('"clearanceFrontAudit"')) {
    findings.push({ severity: "error", code: "adapter_clearance_front_audit", detail: "side clearance-front BRep audit missing" });
  }
  if (!source.includes("def audit_u_shape_corner_ownership(") || !source.includes('"cornerOwnershipAudit"')) {
    findings.push({ severity: "error", code: "adapter_corner_audit", detail: "BACK corner-ownership BRep audit missing" });
  }
  if (!source.includes("def audit_u_shape_back_corner_closure(") || !source.includes('"backCornerClosureAudit"')) {
    findings.push({ severity: "error", code: "adapter_corner_closure_audit", detail: "BACK corner-closure BRep audit missing" });
  }
  if (!source.includes("def audit_u_shape_postprocess(") || !source.includes('"postprocessAudit"')) {
    findings.push({ severity: "error", code: "adapter_postprocess_audit", detail: "UOHC postprocess audit missing" });
  }
  if (!source.includes("def audit_u_shape_back_t3_profile(") || !source.includes('"backT3NotchAudit"')) {
    findings.push({ severity: "error", code: "adapter_back_t3_notch_audit", detail: "BACK.T3/T4 notch profile audit missing" });
  }
  if (!source.includes("def audit_u_shape_t4_geometry(") || !source.includes('"t4GeometryAudit"')) {
    findings.push({ severity: "error", code: "adapter_t4_geometry_audit", detail: "final T4 BRep geometry audit missing" });
  }
  if (!source.includes('"uShapeGeometryRevision"') || !adapterSource.includes('"geometryRevision"')) {
    findings.push({ severity: "error", code: "geometry_revision", detail: "geometry revision is not persisted into Fusion evidence" });
  }
  if (!source.includes('"caseFingerprint"') || !source.includes("contactFailed")) {
    findings.push({ severity: "error", code: "adapter_evidence_identity", detail: "Fusion evidence identity/contact status missing" });
  }
  if (!source.includes("def _pose_run_via_body_moves(") || !source.includes('"mode": "bodyMove"')) {
    findings.push({ severity: "error", code: "adapter_body_move_pose", detail: "body-move U pose helper missing" });
  }
  if (!source.includes("_pose_run_via_body_moves(") || !source.includes("Build each run in LOCAL identity first")) {
    findings.push({ severity: "error", code: "adapter_pose_order", detail: "local build then body-move pose contract missing" });
  }
  if (source.includes("origin_rotation_deg=rotation_deg") && source.includes("Create each run already posed")) {
    findings.push({ severity: "error", code: "adapter_regression", detail: "create-already-posed strategy returned (causes T4 spikes)" });
  }
  const uiSideMappingOk = paletteSource.includes('data-uoh-run="LEFT" data-i18n="uoh.run.left"')
    && paletteSource.includes('data-uoh-run="RIGHT" data-i18n="uoh.run.right"')
    && paletteSource.includes('id="uohRightLength" type="number"')
    && paletteSource.includes('id="uohLeftLength" type="number"')
    && paletteSource.includes("function uohParamsForModel(uiParams)")
    && paletteSource.includes("leftArmLength: uiParams.rightArmLength")
    // Model RIGHT local +X is tip→corner, so UI LEFT zones (corner→tip) must reverse.
    && paletteSource.includes("RIGHT: uiLeftZones.reverse()")
    && paletteSource.includes("LEFT: uiRightZones");
  if (!uiSideMappingOk) {
    findings.push({
      severity: "error",
      code: "ui_side_mapping",
      detail: "UOHC UI must swap LEFT/RIGHT at the model interface and reverse UI LEFT zones onto model RIGHT",
    });
  }
  return findings;
}

/** Offline mirror of Python audit_u_shape_footprint — catches stacked straight runs. */
function auditMeasuredFootprint(boards, params = {}) {
  const depth = Number(params.cabinetDepth || 400);
  const byId = Object.fromEntries((boards || []).map((row) => [row.id, row]));
  const left = byId["LEFT.BP"];
  const back = byId["BACK.BP"];
  const right = byId["RIGHT.BP"];
  if (!left || !back || !right) {
    return { ok: false, isUShape: false, errors: ["missing BP measures"] };
  }
  const size = (row) => {
    const s = row.sizeMm || {};
    if (s.x != null) return [Number(s.x), Number(s.y)];
    const b = row.bboxMm || {};
    return [Math.abs(b.x1 - b.x0), Math.abs(b.y1 - b.y0)];
  };
  const [lx, ly] = size(left);
  const [rx, ry] = size(right);
  const leftStraight = lx > ly && lx > depth + 80;
  const rightStraight = rx > ry && rx > depth + 80;
  if (leftStraight || rightStraight) {
    return {
      ok: false,
      isUShape: false,
      errors: [`NOT_U_FOOTPRINT: LEFT ${lx}x${ly}, RIGHT ${rx}x${ry}`],
    };
  }
  return { ok: true, isUShape: true, errors: [] };
}

function mergeFusionLog(report) {
  if (!fs.existsSync(fusionLogPath)) {
    report.certification = certifyFusionEvidence({
      fusion: null,
      requiredBuild: requiredAdapterBuild,
      adapterMtimeMs: fs.statSync(adapterPath).mtimeMs,
      fusionLogMtimeMs: 0,
      expectedCaseFingerprints: loopCaseFingerprints(report),
      requiredCaseAudits: REQUIRED_CASE_AUDITS,
    });
    report.fusion = {
      present: false,
      ok: null,
      note: report.certification.reason,
    };
    return report;
  }
  const fusion = JSON.parse(fs.readFileSync(fusionLogPath, "utf8"));
  report.certification = certifyFusionEvidence({
    fusion,
    requiredBuild: requiredAdapterBuild,
    adapterMtimeMs: fs.statSync(adapterPath).mtimeMs,
    fusionLogMtimeMs: fs.statSync(fusionLogPath).mtimeMs,
    expectedCaseFingerprints: loopCaseFingerprints(report),
    measuredCaseFingerprints: fusionCaseFingerprints(fusion),
    requiredCaseAudits: REQUIRED_CASE_AUDITS,
  });
  if (!report.certification.valid) {
    report.fusion = {
      present: true,
      valid: false,
      adapterBuild: fusion.adapterBuild,
      note: report.certification.reason,
    };
    return report;
  }
  const cases = Array.isArray(fusion.cases) ? fusion.cases : [];
  const boards = cases.flatMap((row) => row.boards || []);
  const positive = boards.filter((board) => {
    const size = board.sizeMm || {};
    return (size.x || 0) > 0.5 || (size.y || 0) > 0.5 || (size.z || 0) > 0.5;
  });
  // Stale/broken measure (all zero-volume) must not fail the offline loop.
  if (boards.length > 0 && positive.length === 0) {
    report.fusion = {
      present: true,
      valid: false,
      adapterBuild: fusion.adapterBuild,
      note: `Fusion measure log is invalid (all board sizes 0). Reload plugin ${requiredAdapterBuild}, recreate bodies, re-run 自检.`,
    };
    report.certification = {
      level: "invalid_fusion",
      certified: false,
      valid: false,
      reason: report.fusion.note,
    };
    return report;
  }
  report.fusion = { present: true, valid: true, certification: report.certification, ...fusion };
  if (fusion.ok === false) {
    report.ok = false;
    report.findings.push({
      severity: "error",
      code: "fusion_measure_failed",
      detail: (fusion.errors || fusion.findings || ["Fusion self-check failed"]).toString(),
    });
  }
  for (const row of cases) {
    const contacts = auditBoardContacts(row.boards || [], STYLE1_CONTACT_CONTRACTS);
    row.contactAudit = contacts;
    if (!contacts.ok) {
      report.ok = false;
      for (const finding of contacts.findings) {
        report.findings.push({
          ...finding,
          code: `fusion_${finding.code}`,
          detail: `${row.caseId || row.id}: ${finding.detail}`,
        });
      }
    }
    const overlaps = auditForbiddenOverlaps(row.boards || [], STYLE1_FORBIDDEN_OVERLAPS);
    row.overlapAudit = overlaps;
    if (!overlaps.ok) {
      report.ok = false;
      report.findings.push(...overlaps.findings.map((finding) => ({
        ...finding,
        code: `fusion_${finding.code}`,
        detail: `${row.caseId || row.id}: ${finding.detail}`,
      })));
    }
    const footprint = row.footprint || auditMeasuredFootprint(row.boards || [], row.params || report.cases?.[0]?.params || {});
    if (footprint.isUShape === false || /NOT_U_FOOTPRINT/i.test(String((footprint.errors || []).join(" ")))) {
      report.ok = false;
      report.findings.push({
        severity: "error",
        code: "fusion_not_u_footprint",
        detail: `${row.caseId || row.id}: ${(footprint.errors || ["measured footprint is not U-shaped"]).join("; ")}`,
      });
    }
    if (row.spikeDetected) {
      report.ok = false;
      report.findings.push({
        severity: "error",
        code: "fusion_t4_spike",
        detail: `${row.caseId || row.id}: measuredHeight=${row.assemblyHeightMm}`,
      });
    }
    const pose = row.poseCompare;
    if (pose && pose.ok === false) {
      report.ok = false;
      for (const finding of pose.findings || []) {
        report.findings.push({
          severity: finding.severity || "error",
          code: `fusion_${finding.code || "pose"}`,
          detail: `${row.caseId || row.id}: ${finding.detail}`,
        });
      }
    }
    const ledAudit = row.ledGrooveAudit;
    if (ledAudit && ledAudit.ok === false) {
      report.ok = false;
      for (const finding of ledAudit.findings || []) {
        report.findings.push({
          severity: finding.severity || "error",
          code: `fusion_${finding.code || "led_groove"}`,
          detail: `${row.caseId || row.id}: ${finding.detail}`,
        });
      }
    }
    const clearanceAudit = row.clearanceFrontAudit;
    if (clearanceAudit && clearanceAudit.ok === false) {
      report.ok = false;
      for (const finding of clearanceAudit.findings || []) {
        report.findings.push({
          severity: finding.severity || "error",
          code: `fusion_${finding.code || "clearance_front"}`,
          detail: `${row.caseId || row.id}: ${finding.detail}`,
        });
      }
    }
    const cornerAudit = row.cornerOwnershipAudit;
    if (cornerAudit && cornerAudit.ok === false) {
      report.ok = false;
      for (const finding of cornerAudit.findings || []) {
        report.findings.push({
          severity: finding.severity || "error",
          code: `fusion_${finding.code || "corner_ownership"}`,
          detail: `${row.caseId || row.id}: ${finding.detail}`,
        });
      }
    }
    const notchAudit = row.backT3NotchAudit;
    if (notchAudit && notchAudit.ok === false) {
      report.ok = false;
      for (const finding of notchAudit.findings || []) {
        report.findings.push({
          severity: finding.severity || "error",
          code: `fusion_${finding.code || "back_t3_notch"}`,
          detail: `${row.caseId || row.id}: ${finding.detail}`,
        });
      }
    }
    const t4Audit = row.t4GeometryAudit;
    if (t4Audit && t4Audit.ok === false) {
      report.ok = false;
      for (const finding of t4Audit.findings || []) {
        report.findings.push({
          severity: finding.severity || "error",
          code: `fusion_${finding.code || "t4_geometry"}`,
          detail: `${row.caseId || row.id}: ${finding.detail}`,
        });
      }
    }
    if (Array.isArray(row.boards) && row.boards.length === 0) {
      report.ok = false;
      report.findings.push({
        severity: "error",
        code: "fusion_no_board_xyz",
        detail: `${row.caseId || row.id}: measure log has no per-board XYZ records`,
      });
    }
  }
  return report;
}

function writeReport(report) {
  fs.mkdirSync(logDir, { recursive: true });
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  // Compact expected XYZ dump the agent can diff without reading the full report.
  const posesPath = path.join(logDir, "u_shape_ohc_expected_poses.json");
  fs.writeFileSync(
    posesPath,
    JSON.stringify(
      {
        generatedAt: report.generatedAt,
        cases: (report.cases || []).map((row) => ({
          caseId: row.caseId,
          transforms: row.transforms,
          poses: row.poses,
        })),
      },
      null,
      2,
    ),
  );
  report.expectedPosesPath = posesPath;

  const simulatedPayload = {
    ok: (report.cases || []).every((row) => row.simulated?.ok !== false),
    generatedAt: report.generatedAt,
    source: "offline_fusion_simulator",
    note: "Math stand-in for Fusion AABB. No Fusion process required.",
    cases: (report.cases || []).map((row) => ({
      caseId: row.caseId,
      ...(row.simulated || {}),
    })),
  };
  fs.writeFileSync(simulatedLogPath, JSON.stringify(simulatedPayload, null, 2));
  report.simulatedLogPath = simulatedLogPath;
  if (!simulatedPayload.ok) report.ok = false;
}

function runStaticSuites(report) {
  const suites = [
    ["assembly_loop_core", path.join(here, "test_assembly_loop_core.js")],
    ["generator.test.ts", path.join(pluginRoot, "..", "modules", "uShapeOverheadCabinet", "generator.test.ts")],
    ["pose_audit", path.join(here, "run_u_shape_pose_audit.js")],
    ["selfcheck", path.join(here, "run_u_shape_ohc_selfcheck.js")],
    ["deep_audit", path.join(here, "run_u_shape_ohc_deep_audit.js")],
  ];
  report.suites = [];
  for (const [name, script] of suites) {
    const proc = spawnSync(process.execPath, [script], { encoding: "utf8", cwd: path.join(pluginRoot, ".."), timeout: 60000 });
    const ok = proc.status === 0;
    report.suites.push({
      name,
      ok,
      status: proc.status,
      stdout: (proc.stdout || "").trim().split(/\r?\n/).slice(-3),
      stderr: (proc.stderr || "").trim().slice(0, 500),
    });
    if (!ok) {
      report.ok = false;
      report.findings.push({ severity: "error", code: `suite_${name}`, detail: `exit ${proc.status}` });
    }
  }
}

const args = new Set(process.argv.slice(2));
const report = {
  ok: true,
  generatedAt: new Date().toISOString(),
  adapterBuildRequired: requiredAdapterBuild,
  reportPath,
  fusionLogPath,
  findings: [],
  cases: [],
};

for (const finding of assertAdapterContract()) {
  report.findings.push(finding);
  if (finding.severity === "error") report.ok = false;
}

const matrix = runGeneratorCaseMatrix({
  moduleId: "u_shape_overhead",
  cases: buildCases(),
  generate: generateUShapeOverheadCabinet,
  evaluateCase: auditCase,
});
report.moduleId = matrix.moduleId;
report.cases.push(...matrix.cases);
report.findings.push(...matrix.findings);
if (!matrix.ok) report.ok = false;

if (!args.has("--skip-suites")) runStaticSuites(report);
if (args.has("--fusion-log") || args.has("--include-fusion") || fs.existsSync(fusionLogPath)) {
  mergeFusionLog(report);
} else {
  report.certification = certifyFusionEvidence({
    fusion: null,
    requiredBuild: requiredAdapterBuild,
    adapterMtimeMs: fs.statSync(adapterPath).mtimeMs,
    fusionLogMtimeMs: 0,
    expectedCaseFingerprints: loopCaseFingerprints(report),
    requiredCaseAudits: REQUIRED_CASE_AUDITS,
  });
}

report.summary = {
  ...summarizeGeneratorLoop(report),
  next:
    report.ok && report.certification?.certified
      ? "Fusion-certified green."
      : report.ok
        ? `Offline preflight only: ${report.certification?.reason || "run Fusion self-check"}`
      : report.findings.some((row) => row.code === "fusion_not_u_footprint")
        ? `Fusion log shows NOT U (straight runs). Reload plugin ${requiredAdapterBuild}, delete old assembly, recreate, 自检.`
        : report.findings.some((row) => /contact_gap/.test(row.code))
          ? "Final-pose contact gap detected. Fix geometry from measured face deltas, then recreate and re-run."
          : "Offline/fusion failed. Read findings, fix generator/adapter, re-run.",
};

writeReport(report);
console.log(JSON.stringify(report.summary, null, 2));
console.log(`report: ${reportPath}`);
if (!report.ok) process.exit(1);
