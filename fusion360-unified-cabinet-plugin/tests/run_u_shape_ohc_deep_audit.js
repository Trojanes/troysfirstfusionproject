/**
 * Deep UOHC assembly audit — footprint, connectors, simulated T4, cuts, adapter.
 * Exit 0 only when every check passes.
 */
import assert from "node:assert";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { generateUShapeOverheadCabinet } from "../../modules/uShapeOverheadCabinet/generator.ts";

const here = path.dirname(fileURLToPath(import.meta.url));
const pluginRoot = path.resolve(here, "..");
const logDir = path.join(pluginRoot, "logs");
const outPath = path.join(logDir, "u_shape_ohc_deep_audit.json");

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

function corners(board) {
  const out = [];
  for (const x of [board.x0, board.x1]) {
    for (const y of [board.y0, board.y1]) {
      for (const z of [board.z0, board.z1]) out.push([x, y, z]);
    }
  }
  return out;
}

function profileCorners(board) {
  if (board.profilePlane !== "XY" || !Array.isArray(board.profileVector) || !board.profileVector.length) {
    return corners(board);
  }
  return board.profileVector.flatMap((point) => (
    [board.z0, board.z1].map((z) => [board.x0 + Number(point.x || 0), board.y0 + Number(point.y || 0), z])
  ));
}

function bbox(points) {
  return {
    x0: Math.min(...points.map((p) => p[0])),
    x1: Math.max(...points.map((p) => p[0])),
    y0: Math.min(...points.map((p) => p[1])),
    y1: Math.max(...points.map((p) => p[1])),
    z0: Math.min(...points.map((p) => p[2])),
    z1: Math.max(...points.map((p) => p[2])),
  };
}

function overlapArea(a, b) {
  const dx = Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0));
  const dy = Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
  return dx * dy;
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

/**
 * Match Fusion `_oh_postprocess_bodies` order:
 *   1) rotate T4 90° about world X through body center
 *   2) then apply Style-1 dy/dz translation
 *   3) then apply U run Z pose
 */
function simulateT4World(run, t4, params) {
  const D = params.cabinetDepth;
  const fg = params.featureWidth;
  const cl = params.clearance ?? 2.5;
  const dy = D - (2 * fg + cl);
  const dz = -cl;
  let pts = profileCorners(t4);
  const pivot = centerOf(pts);
  pts = pts.map((p) => rotateXAbout(p, pivot, 90));
  pts = pts.map(([x, y, z]) => [x, y + dy, z + dz]);
  const world = pts.map((p) => {
    const [x, y, z] = rotateZ(p, run.transform.rotationDeg);
    return [x + run.transform.translateX, y + run.transform.translateY, z];
  });
  return bbox(world);
}

const cases = [
  {
    id: "default",
    params: {
      totalWidth: 2275,
      leftArmLength: 1500,
      rightArmLength: 1500,
      cabinetDepth: 400,
      cabinetHeight: 400,
      featureWidth: 15,
      frontPanelThickness: 18,
      sideClearance: 50,
    },
  },
  {
    id: "asymmetric",
    params: {
      totalWidth: 2400,
      leftArmLength: 1700,
      rightArmLength: 1200,
      cabinetDepth: 400,
      cabinetHeight: 400,
    },
  },
  {
    id: "tall",
    params: {
      totalWidth: 2275,
      leftArmLength: 1500,
      rightArmLength: 1500,
      cabinetDepth: 400,
      cabinetHeight: 700,
    },
  },
  {
    id: "shallow",
    params: {
      totalWidth: 1900,
      leftArmLength: 1200,
      rightArmLength: 1100,
      cabinetDepth: 320,
      cabinetHeight: 400,
    },
  },
  {
    id: "multi-zone",
    params: {
      totalWidth: 2275,
      leftArmLength: 1500,
      rightArmLength: 1500,
      cabinetDepth: 400,
      cabinetHeight: 400,
      zones: {
        LEFT: [{ type: "up_flap", width: 500 }, { type: "fixed_panel", width: 550 }],
        BACK: [{ type: "up_flap", width: 450 }, { type: "open", width: 443 }, { type: "up_flap", width: 450 }],
        RIGHT: [{ type: "fixed_panel", width: 500 }, { type: "up_flap", width: 550 }],
      },
    },
  },
];

const findings = [];
const caseReports = [];

for (const tc of cases) {
  const result = generateUShapeOverheadCabinet(tc.params);
  const P = result.params;
  const H = P.cabinetHeight;
  const D = P.cabinetDepth;
  const W = P.totalWidth;
  const localFindings = [];

  if (result.validation.errors.length) {
    localFindings.push({ code: "validation", detail: result.validation.errors.join("; ") });
  }
  for (const row of result.audit) {
    if (!row.ok) localFindings.push({ code: "audit", detail: `${row.id}: ${row.detail}` });
  }

  const leftBp = result.worldBoards.find((b) => b.id === "LEFT.BP");
  const backBp = result.worldBoards.find((b) => b.id === "BACK.BP");
  const rightBp = result.worldBoards.find((b) => b.id === "RIGHT.BP");
  if (!leftBp || !backBp || !rightBp) {
    localFindings.push({ code: "missing_bp", detail: "LEFT/BACK/RIGHT BP missing" });
  } else {
    if (!(close(leftBp.x0, 0) && close(leftBp.x1, D) && close(leftBp.y0, D) && close(leftBp.y1, P.leftArmLength))) {
      localFindings.push({ code: "left_bp_footprint", detail: JSON.stringify(leftBp) });
    }
    if (!(close(backBp.x0, 0) && close(backBp.x1, W) && close(backBp.y0, 0) && close(backBp.y1, D))) {
      localFindings.push({ code: "back_bp_footprint", detail: JSON.stringify(backBp) });
    }
    if (!(close(rightBp.x0, W - D) && close(rightBp.x1, W) && close(rightBp.y0, D) && close(rightBp.y1, P.rightArmLength))) {
      localFindings.push({ code: "right_bp_footprint", detail: JSON.stringify(rightBp) });
    }
    if (backBp.x1 - backBp.x0 < 50) {
      localFindings.push({ code: "back_too_narrow", detail: String(backBp.x1 - backBp.x0) });
    }
  }

  const fpt = P.frontPanelThickness;
  const sideClearance = P.sideClearance;
  const sideY0 = D + fpt;
  const sideY1 = sideY0 + sideClearance;
  const leftFixed = result.worldBoards.find((b) => b.id === "LEFT.FP_CLEARANCE_SIDE");
  const rightFixed = result.worldBoards.find((b) => b.id === "RIGHT.FP_CLEARANCE_SIDE");
  const backAtLeft = result.worldBoards.find((b) => b.id === "BACK.FP_CLEARANCE_RIGHT");
  const backAtRight = result.worldBoards.find((b) => b.id === "BACK.FP_CLEARANCE_LEFT");
  const clearancePoseOk = leftFixed && rightFixed && backAtLeft && backAtRight
    && close(leftFixed.x0, D) && close(leftFixed.x1, D + fpt)
    && close(rightFixed.x0, W - D - fpt) && close(rightFixed.x1, W - D)
    && close(leftFixed.y0, sideY0) && close(leftFixed.y1, sideY1)
    && close(rightFixed.y0, sideY0) && close(rightFixed.y1, sideY1)
    && close(backAtLeft.y1, leftFixed.y0) && close(backAtRight.y1, rightFixed.y0)
    && overlapArea(leftFixed, backAtLeft) < 0.01
    && overlapArea(rightFixed, backAtRight) < 0.01;
  if (!clearancePoseOk) {
    localFindings.push({
      code: "side_clearance_front_pose",
      detail: `expected side fixed fronts ${sideClearance}×${fpt} at Y=${sideY0}..${sideY1}`,
    });
  }
  for (const runId of ["LEFT", "RIGHT"]) {
    const fixed = runId === "LEFT" ? leftFixed : rightFixed;
    const functionalFronts = result.worldBoards.filter((b) => (
      b.runId === runId && /^FP\d+$/.test(b.localBoardId)
    ));
    if (fixed && functionalFronts.some((front) => (
      overlapArea(fixed, front) > 0.01 || front.y0 < sideY1 + P.clearance - 0.05
    ))) {
      localFindings.push({
        code: "side_clearance_function_overlap",
        detail: `${runId} clearance front overlaps or crowds its adjacent function zone`,
      });
    }
  }

  // Style-1 dividers are intentionally z0=2*FGw .. z1=H+FGw.
  const zCeil = H + P.featureWidth + 0.5;
  for (const board of result.worldBoards) {
    if (/^T[1-4]$/.test(board.localBoardId) || board.localBoardId.startsWith("FP")) continue;
    if (board.z0 < -0.5 || board.z1 > zCeil) {
      localFindings.push({
        code: "structural_z_oob",
        detail: `${board.id} z=[${board.z0},${board.z1}] ceil=${zCeil}`,
      });
    }
  }

  const leftC = result.worldBoards.find((b) => b.id === "BACK.U_CONNECTOR_LEFT");
  const rightC = result.worldBoards.find((b) => b.id === "BACK.U_CONNECTOR_RIGHT");
  const leftRearD = result.worldBoards
    .filter((b) => b.runId === "LEFT" && /^D\d+$/.test(b.localBoardId))
    .sort((a, b) => a.y0 - b.y0)[0];
  const rightRearD = result.worldBoards
    .filter((b) => b.runId === "RIGHT" && /^D\d+$/.test(b.localBoardId))
    .sort((a, b) => a.y0 - b.y0)[0];
  if (!leftC || !rightC || !leftRearD || !rightRearD) {
    localFindings.push({ code: "connector_set", detail: "connector/divider set incomplete" });
  } else {
    if (!close(leftC.y1, leftRearD.y0)) {
      localFindings.push({ code: "left_gap", detail: `${leftC.y1} vs ${leftRearD.y0}` });
    }
    if (!close(rightC.y1, rightRearD.y0)) {
      localFindings.push({ code: "right_gap", detail: `${rightC.y1} vs ${rightRearD.y0}` });
    }
    // Connectors must sit in the BACK depth band (world Y).
    if (!close(leftC.y1, D) || leftC.y0 < D - P.featureWidth - 1) {
      localFindings.push({ code: "left_conn_band", detail: `${leftC.y0}..${leftC.y1}` });
    }
    if (!close(rightC.y1, D) || rightC.y0 < D - P.featureWidth - 1) {
      localFindings.push({ code: "right_conn_band", detail: `${rightC.y0}..${rightC.y1}` });
    }
  }

  const t4Rows = [];
  for (const run of result.runs) {
    const t4 = run.result.boards.find((b) => b.id === "T4");
    if (!t4) {
      localFindings.push({ code: "no_t4", detail: run.id });
      continue;
    }
    const bb = simulateT4World(run, t4, P);
    const height = bb.z1 - bb.z0;
    t4Rows.push({ runId: run.id, bboxMm: bb, heightMm: height });
    if (height > H + 120) {
      localFindings.push({ code: "t4_spike", detail: `${run.id} height=${height}` });
    }
    // T4 profile is a 50 mm strip; after X fold its final vertical height is 50.
    if (height < 49 || height > 51) {
      localFindings.push({
        code: "t4_height_band",
        detail: `${run.id} height=${height.toFixed(1)} expected 50 mm`,
      });
    }
    // Plan check: T4 must stay within a generous envelope of the run BP
    // (Style-1 rear offset can sit slightly outside the BP rectangle).
    const bp = result.worldBoards.find((b) => b.id === `${run.id}.BP`);
    if (bp) {
      const pad = D; // allow rear fascia outside BP by up to one depth
      const envelope = {
        x0: bp.x0 - pad,
        x1: bp.x1 + pad,
        y0: bp.y0 - pad,
        y1: bp.y1 + pad,
      };
      if (overlapArea(bb, envelope) < 1) {
        localFindings.push({
          code: "t4_far_from_run",
          detail: `${run.id} T4 plan far from BP envelope`,
        });
      }
    }
    // Wrong order must still spike for ±90 runs (oracle).
    if (Math.abs(run.transform.rotationDeg) === 90) {
      const wrong = bbox(
        profileCorners(t4)
          .map((p) => rotateZ(p, run.transform.rotationDeg))
          .map((p) => rotateX(p, 90)),
      );
      if (wrong.z1 - wrong.z0 < H + 200) {
        localFindings.push({
          code: "spike_oracle_weak",
          detail: `${run.id} wrong-order height ${wrong.z1 - wrong.z0}`,
        });
      }
    }
  }

  for (const run of result.runs) {
    const ids = new Set(run.result.boards.map((b) => b.id));
    for (const feature of run.result.features) {
      const target = feature.targetBoardId || feature.boardId;
      if (!target) continue;
      if (!ids.has(target)) {
        localFindings.push({
          code: "cut_escape",
          detail: `${run.id}/${feature.id || feature.type} → ${target}`,
        });
      }
    }
  }

  // BACK owns corners; side BPs begin at its front seam y=D.
  if (leftBp && backBp && !close(leftBp.y0, backBp.y1)) {
    localFindings.push({ code: "left_arm_back_seam", detail: `${leftBp.y0} vs ${backBp.y1}` });
  }
  if (rightBp && backBp && !close(rightBp.y0, backBp.y1)) {
    localFindings.push({ code: "right_arm_back_seam", detail: `${rightBp.y0} vs ${backBp.y1}` });
  }

  // BACK owns full-width T2; side rails extend into corner by TCH-1 for Style-1 seating.
  const rearNotch = (P.topClearanceHeight ?? 40) - 1;
  const leftT1 = result.worldBoards.find((b) => b.id === "LEFT.T1");
  const leftT2 = result.worldBoards.find((b) => b.id === "LEFT.T2");
  const rightT1 = result.worldBoards.find((b) => b.id === "RIGHT.T1");
  const rightT2 = result.worldBoards.find((b) => b.id === "RIGHT.T2");
  const backT1 = result.worldBoards.find((b) => b.id === "BACK.T1");
  const backT2 = result.worldBoards.find((b) => b.id === "BACK.T2");
  const checks = [
    ["LEFT.T1.len", leftT1 ? leftT1.y1 - leftT1.y0 : NaN, P.leftArmLength - D + fpt + rearNotch],
    ["RIGHT.T1.len", rightT1 ? rightT1.y1 - rightT1.y0 : NaN, P.rightArmLength - D + fpt + rearNotch],
    ["LEFT.T2.len", leftT2 ? leftT2.y1 - leftT2.y0 : NaN, P.leftArmLength - D + fpt + rearNotch],
    ["RIGHT.T2.len", rightT2 ? rightT2.y1 - rightT2.y0 : NaN, P.rightArmLength - D + fpt + rearNotch],
    ["BACK.T1.len", backT1 ? backT1.x1 - backT1.x0 : NaN, W - 2 * D + 2 * rearNotch],
    ["BACK.T2.len", backT2 ? backT2.x1 - backT2.x0 : NaN, W],
    ["LEFT.T1.thick", leftT1 ? leftT1.x1 - leftT1.x0 : NaN, fpt],
    ["RIGHT.T1.thick", rightT1 ? rightT1.x1 - rightT1.x0 : NaN, fpt],
    ["BACK.T1.thick", backT1 ? backT1.y1 - backT1.y0 : NaN, fpt],
  ];
  for (const [label, got, expect] of checks) {
    if (!close(got, expect, 0.05)) {
      localFindings.push({ code: "t1t2_dim", detail: `${label} got ${got} expect ${expect}` });
    }
  }
  const backRun = result.runs.find((run) => run.id === "BACK");
  const backT3 = backRun?.result.boards.find((b) => b.id === "T3");
  const profileXs = new Set((backT3?.profileVector || []).map((point) => Number(point.x)));
  const notchRanges = (backRun?.result.features || [])
    .map((feature) => feature.t3_notch?.x)
    .filter((range) => Array.isArray(range) && range.length === 2);
  if (!notchRanges.length || notchRanges.some((range) => !profileXs.has(Number(range[0])) || !profileXs.has(Number(range[1])))) {
    localFindings.push({ code: "back_t3_notch_profile", detail: "BACK.T3 profile is missing divider notch boundaries" });
  }

  caseReports.push({
    caseId: tc.id,
    ok: localFindings.length === 0,
    boardCount: result.worldBoards.length,
    transforms: result.runs.map((run) => ({ id: run.id, ...run.transform })),
    t4: t4Rows,
    findings: localFindings,
  });
  for (const finding of localFindings) {
    findings.push({ caseId: tc.id, ...finding });
  }
}

const adapterSource = fs.readFileSync(
  path.join(pluginRoot, "modules", "general_tall", "fusion_adapter.py"),
  "utf8",
);
const createSlice = adapterSource.slice(
  adapterSource.indexOf("run_summary = create_rough_bodies_from_board_result("),
  adapterSource.indexOf("run_component = run_summary.get(\"_containerComponent\")"),
);
const adapterChecks = [
  ["local_identity", adapterSource.includes("Build each run in LOCAL identity first")],
  ["final_repose", adapterSource.includes("Final pass: verify every run received a body-move pose")],
  ["body_move_pose", adapterSource.includes("def _pose_run_via_body_moves(")],
  ["u_footprint_audit", adapterSource.includes("def audit_u_shape_footprint(") && adapterSource.includes("NOT_U_FOOTPRINT")],
  ["generic_contact_audit", adapterSource.includes("def audit_board_contact_contracts(")],
  ["u_top_contact_audit", adapterSource.includes("def audit_u_shape_top_contacts(")],
  ["case_fingerprint", adapterSource.includes("\"caseFingerprint\"")],
  ["measure", adapterSource.includes("def measure_u_shape_assembly(")],
  ["compare", adapterSource.includes("def compare_u_shape_board_poses(")],
  ["no_create_posed_comment", !adapterSource.includes("Create each run already posed")],
  ["create_rot0", createSlice.includes("origin_rotation_deg=0.0")],
  ["create_local_xy", createSlice.includes("origin_x_mm=0.0") && createSlice.includes("origin_y_mm=0.0")],
];
for (const [code, ok] of adapterChecks) {
  if (!ok) findings.push({ caseId: "adapter", code, detail: "contract failed" });
}

const report = {
  ok: findings.length === 0,
  generatedAt: new Date().toISOString(),
  findingCount: findings.length,
  findings,
  cases: caseReports,
  adapterChecks: Object.fromEntries(adapterChecks),
};
fs.mkdirSync(logDir, { recursive: true });
fs.writeFileSync(outPath, JSON.stringify(report, null, 2));
console.log(JSON.stringify({ ok: report.ok, findingCount: report.findingCount, outPath }, null, 2));
if (!report.ok) {
  console.error(JSON.stringify(findings.slice(0, 30), null, 2));
  process.exit(1);
}
console.log("OK U Shape OHC deep assembly audit");
