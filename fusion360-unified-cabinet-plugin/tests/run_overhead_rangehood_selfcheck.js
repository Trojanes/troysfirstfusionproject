import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const pluginDir = path.resolve(__dirname, "..");
const rootDir = path.resolve(pluginDir, "..");
const bridgeScript = path.join(pluginDir, "scripts", "overhead_from_params.js");

function runBridge(params) {
  const proc = spawnSync(process.execPath, [bridgeScript], {
    cwd: pluginDir,
    input: JSON.stringify({ params }),
    encoding: "utf8",
  });
  assert.equal(proc.status, 0, proc.stderr || proc.stdout);
  const payload = JSON.parse(proc.stdout);
  assert.equal(payload.ok, true, JSON.stringify(payload.errors || []));
  return payload.result;
}

function near(actual, expected, label, tolerance = 1e-6) {
  assert.ok(
    Math.abs(Number(actual) - Number(expected)) <= tolerance,
    `${label}: expected ${expected}, got ${actual}`,
  );
}

function polygonArea(points, a, b) {
  let area = 0;
  for (let index = 0; index < points.length - 1; index += 1) {
    area += Number(points[index][a]) * Number(points[index + 1][b])
      - Number(points[index + 1][a]) * Number(points[index][b]);
  }
  return Math.abs(area) / 2;
}

function validateEveryBoard(result, caseName) {
  const ids = new Set();
  for (const board of result.boards) {
    assert.ok(board.id && !ids.has(board.id), `${caseName}: duplicate/missing board id ${board.id}`);
    ids.add(board.id);
    for (const axis of ["x", "y", "z"]) {
      const low = Number(board[`${axis}0`]);
      const high = Number(board[`${axis}1`]);
      assert.ok(Number.isFinite(low) && Number.isFinite(high), `${caseName}/${board.id}: invalid ${axis} bbox`);
      assert.ok(high > low, `${caseName}/${board.id}: non-positive ${axis} extent`);
    }
    assert.ok(Number(board.materialThickness) > 0, `${caseName}/${board.id}: invalid material thickness`);
    const thicknessAxis = String(board.thicknessAxis || "").toLowerCase();
    near(
      Number(board[`${thicknessAxis}1`]) - Number(board[`${thicknessAxis}0`]),
      Number(board.materialThickness),
      `${caseName}/${board.id}: thickness-axis extent`,
    );

    const profile = board.cutProfileVector || board.profileVector;
    if (!profile) continue;
    assert.ok(profile.length >= 4, `${caseName}/${board.id}: profile has too few points`);
    const plane = board.profilePlane;
    const [a, b] = plane === "XY" ? ["x", "y"] : plane === "XZ" ? ["x", "z"] : ["y", "z"];
    for (const point of profile) {
      assert.ok(Number.isFinite(Number(point[a])) && Number.isFinite(Number(point[b])), `${caseName}/${board.id}: invalid profile point`);
    }
    near(profile[0][a], profile.at(-1)[a], `${caseName}/${board.id}: profile closure ${a}`);
    near(profile[0][b], profile.at(-1)[b], `${caseName}/${board.id}: profile closure ${b}`);
    assert.ok(polygonArea(profile, a, b) > 0.01, `${caseName}/${board.id}: zero-area profile`);
  }

  for (const feature of result.features) {
    if (!feature?.targetBoardId) continue;
    assert.ok(ids.has(feature.targetBoardId), `${caseName}: feature ${feature.id} targets missing ${feature.targetBoardId}`);
  }
}

function assemblyBBox(board, result) {
  const bbox = {
    x0: Number(board.x0), x1: Number(board.x1),
    y0: Number(board.y0), y1: Number(board.y1),
    z0: Number(board.z0), z1: Number(board.z1),
  };
  const cpt = Number(result.params.featureWidth);
  const id = String(board.id);
  if (["BP", "T1", "T2"].includes(id) || board.category === "front_panel") {
    bbox.z0 += cpt;
    bbox.z1 += cpt;
  }
  if (id === "T1" || id === "T2") {
    const dy = Number(result.params.topClearanceHeight) - 1;
    bbox.y0 += dy;
    bbox.y1 += dy;
  }
  if (id === "T3") {
    const dz = -Number(result.params.topClearanceHeight) + 14;
    bbox.z0 += dz;
    bbox.z1 += dz;
  }
  // T4 rotates at the top of the cabinet. Its pre-rotation Z interval is
  // already entirely above the validated rangehood insert, so retaining that
  // conservative interval is sufficient for the collision gate below.
  return bbox;
}

function positiveAabbIntersection(a, b, tolerance = 1e-6) {
  return (
    Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0) > tolerance
    && Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0) > tolerance
    && Math.min(a.z1, b.z1) - Math.max(a.z0, b.z0) > tolerance
  );
}

function validateNoUnintendedRangehoodCollisions(result, caseName) {
  const group = result.features.find((feature) => feature?.type === "rangehood_group");
  const boundaryIds = new Set(group.boundaryDividerIds);
  const rangehoodIds = new Set(["RGHD_TOP", "RGHD_FRONT", "RGHD_BACK"]);
  const byId = new Map(result.boards.map((board) => [board.id, board]));
  for (const rangehoodId of rangehoodIds) {
    const rangehoodBoard = byId.get(rangehoodId);
    const rangehoodBox = assemblyBBox(rangehoodBoard, result);
    for (const other of result.boards) {
      if (rangehoodIds.has(other.id)) continue;
      if (!positiveAabbIntersection(rangehoodBox, assemblyBBox(other, result))) continue;
      const intentionalTopTongueInBoundaryD = rangehoodId === "RGHD_TOP" && boundaryIds.has(other.id);
      assert.ok(
        intentionalTopTongueInBoundaryD,
        `${caseName}: unintended positive-volume assembly collision ${rangehoodId} / ${other.id}`,
      );
    }
  }
}

function validateRangehoodAssembly(result, expected) {
  const byId = new Map(result.boards.map((board) => [board.id, board]));
  const cpt = Number(result.params.featureWidth);
  const depth = Number(result.params.cabinetDepth);
  const height = Number(result.params.cabinetHeight);
  const topClearance = Number(result.params.topClearanceHeight);
  const bp = byId.get("BP");
  const top = byId.get("RGHD_TOP");
  const front = byId.get("RGHD_FRONT");
  const back = byId.get("RGHD_BACK");
  assert.ok(bp && top && front && back, `${expected.name}: missing rangehood boards`);

  // Fusion moves BP +CPT after all BP cuts. Every rangehood support starts at
  // that final top face; no positive-volume overlap is permitted.
  const finalBpTop = Number(bp.z1) + cpt;
  near(front.z0, finalBpTop, `${expected.name}: FRONT on BP top`);
  near(back.z0, finalBpTop, `${expected.name}: BACK on BP top`);
  near(front.z1, top.z0, `${expected.name}: FRONT supports TOP`);
  near(back.z1, top.z0, `${expected.name}: BACK supports TOP`);
  near(top.z1 - top.z0, cpt, `${expected.name}: TOP thickness`);
  near(front.z1 - front.z0, expected.clearHeight, `${expected.name}: clear height`);
  near(front.x0, back.x0, `${expected.name}: FRONT/BACK x0`);
  near(front.x1, back.x1, `${expected.name}: FRONT/BACK x1`);
  near(front.y0, 0, `${expected.name}: FRONT at BP front`);
  near(front.y1, cpt, `${expected.name}: FRONT thickness position`);
  near(back.y0, depth - cpt, `${expected.name}: BACK position`);
  near(back.y1, depth, `${expected.name}: BACK at BP back`);
  assert.ok(front.y1 < back.y0, `${expected.name}: FRONT/BACK overlap`);
  assert.ok(top.z1 <= height - topClearance, `${expected.name}: TOP intrudes into top-clearance structure`);

  const tongueProjection = cpt / 2 - 0.5;
  near(top.x0 + tongueProjection, front.x0, `${expected.name}: left TOP tongue`);
  near(top.x1 - tongueProjection, front.x1, `${expected.name}: right TOP tongue`);
  const topXs = top.profileVector.map((point) => Number(point.x));
  near(Math.min(...topXs), 0, `${expected.name}: TOP profile left tongue`);
  near(Math.max(...topXs), top.x1 - top.x0, `${expected.name}: TOP profile right tongue`);

  const group = result.features.find((feature) => feature?.type === "rangehood_group");
  const cutout = result.features.find((feature) => feature?.type === "rangehood_bp_cutout");
  assert.ok(group && cutout, `${expected.name}: missing group/cutout feature`);
  assert.equal(group.preset, "NCE");
  assert.equal(group.alignment, expected.alignment);
  near(group.clearHeight, expected.clearHeight, `${expected.name}: group clear height`);
  near(cutout.x[1] - cutout.x[0], 555, `${expected.name}: NCE cutout width`);
  near(cutout.y[1] - cutout.y[0], 285, `${expected.name}: NCE cutout depth`);
  near((cutout.y[0] + cutout.y[1]) / 2, depth / 2, `${expected.name}: cutout Y centered`);
  assert.ok(cutout.x[0] >= front.x0 + 40 - 1e-6, `${expected.name}: cutout left margin < 40`);
  assert.ok(cutout.x[1] <= front.x1 - 40 + 1e-6, `${expected.name}: cutout right margin < 40`);
  assert.ok(cutout.y[0] >= 40 - 1e-6 && depth - cutout.y[1] >= 40 - 1e-6, `${expected.name}: cutout Y margin < 40`);
  if (expected.alignment === "left") {
    near(cutout.x[0] - front.x0, expected.edgeOffsetX, `${expected.name}: left offset`);
  } else {
    near(front.x1 - cutout.x[1], expected.edgeOffsetX, `${expected.name}: right offset`);
  }

  const sideGrooves = result.features.filter((feature) => feature?.type === "rangehood_divider_side_groove");
  assert.equal(sideGrooves.length, 2, `${expected.name}: outer D side groove count`);
  for (const groove of sideGrooves) {
    const target = byId.get(groove.targetBoardId);
    assert.ok(target, `${expected.name}: missing side-groove target`);
    near(groove.y[0], depth / 3, `${expected.name}/${groove.id}: groove y0`);
    near(groove.y[1], depth * 2 / 3, `${expected.name}/${groove.id}: groove y1`);
    near(groove.z[0], top.z0, `${expected.name}/${groove.id}: groove lower edge`);
    near(groove.z[1], top.z1 + 1, `${expected.name}/${groove.id}: groove top clearance`);
    near(groove.depth, cpt / 2, `${expected.name}/${groove.id}: side groove depth`);
    if (groove.face === "+X") near(target.x1, front.x0, `${expected.name}: left D inner face`);
    if (groove.face === "-X") near(target.x0, front.x1, `${expected.name}: right D inner face`);
  }

  const internalIds = group.internalDividerIds || [];
  const topGrooves = result.features.filter((feature) => feature?.type === "rangehood_top_divider_groove");
  assert.equal(internalIds.length, expected.internalDividerCount, `${expected.name}: internal D count`);
  assert.equal(topGrooves.length, internalIds.length, `${expected.name}: RGHD_TOP groove count`);
  for (const dividerId of internalIds) {
    const divider = byId.get(dividerId);
    assert.ok(divider, `${expected.name}: missing ${dividerId}`);
    near(divider.z0, top.z1, `${expected.name}/${dividerId}: sits on TOP`);
    const profileMinZ = Math.min(...divider.cutProfileVector.map((point) => Number(point.z)));
    near(profileMinZ, -(cpt / 2 - 0.5), `${expected.name}/${dividerId}: lower tongue projection`);
    const emittedDividerFeature = result.features.find((feature) => feature?.id === dividerId);
    assert.equal(emittedDividerFeature?.bp_groove, undefined, `${expected.name}/${dividerId}: BP groove not suppressed`);
    const topGroove = topGrooves.find((feature) => feature.dividerBoardId === dividerId);
    assert.ok(topGroove, `${expected.name}/${dividerId}: missing TOP groove`);
    near(topGroove.depth, cpt / 2, `${expected.name}/${dividerId}: TOP groove depth`);
    const centerX = (divider.x0 + divider.x1) / 2;
    near((topGroove.x[0] + topGroove.x[1]) / 2, centerX, `${expected.name}/${dividerId}: TOP groove centered`);
    near(topGroove.x[1] - topGroove.x[0], cpt + 1, `${expected.name}/${dividerId}: TOP groove clearance`);
  }

  const rangehoodPanels = result.boards.filter((board) => board.boardType === "rangehood_flap");
  assert.equal(rangehoodPanels.length, expected.rangehoodZoneCount, `${expected.name}: flap count`);
  const rangehoodPanelIds = new Set(rangehoodPanels.map((panel) => panel.id));
  const hingeFeatures = result.features.filter(
    (feature) => feature?.purpose === "hinge" && rangehoodPanelIds.has(feature.boardId),
  );
  assert.equal(hingeFeatures.length, expected.rangehoodZoneCount * 2, `${expected.name}: hinge count`);
  for (const panel of rangehoodPanels) {
    assert.ok(panel.y1 <= front.y0, `${expected.name}/${panel.id}: flap overlaps carcass in Y`);
  }
}

const cases = [
  {
    name: "minimum-left",
    params: {
      cabinetWidth: 665,
      cabinetDepth: 365,
      cabinetHeight: 400,
      featureWidth: 15,
      topClearanceHeight: 40,
      rangehoodAlignment: "left",
      rangehoodEdgeOffsetX: 40,
      zones: [{ id: "rh", type: "rangehood_flap", width: 665 }],
    },
    expected: { clearHeight: 75, alignment: "left", edgeOffsetX: 40, internalDividerCount: 0, rangehoodZoneCount: 1 },
  },
  {
    name: "roomy-single-right",
    params: {
      cabinetWidth: 1000,
      cabinetDepth: 400,
      cabinetHeight: 500,
      featureWidth: 15,
      topClearanceHeight: 40,
      rangehoodAlignment: "right",
      rangehoodEdgeOffsetX: 60,
      rangehoodClearHeight: 90,
      zones: [{ id: "rh", type: "rangehood_flap", width: 1000 }],
    },
    expected: { clearHeight: 90, alignment: "right", edgeOffsetX: 60, internalDividerCount: 0, rangehoodZoneCount: 1 },
  },
  {
    name: "middle-two-adjacent",
    params: {
      cabinetWidth: 2200,
      cabinetDepth: 400,
      cabinetHeight: 500,
      featureWidth: 15,
      topClearanceHeight: 40,
      rangehoodAlignment: "right",
      rangehoodEdgeOffsetX: 50,
      zones: [
        { id: "left", type: "up_flap", width: 500 },
        { id: "rh-1", type: "rangehood_flap", width: 400 },
        { id: "rh-2", type: "rangehood_flap", width: 400 },
        { id: "right", type: "fixed_panel", width: 900 },
      ],
    },
    expected: { clearHeight: 75, alignment: "right", edgeOffsetX: 50, internalDividerCount: 1, rangehoodZoneCount: 2 },
  },
  {
    name: "three-adjacent",
    params: {
      cabinetWidth: 2400,
      cabinetDepth: 450,
      cabinetHeight: 600,
      featureWidth: 15,
      topClearanceHeight: 40,
      rangehoodAlignment: "left",
      rangehoodEdgeOffsetX: 80,
      zones: [
        { id: "rh-1", type: "rangehood_flap", width: 600 },
        { id: "rh-2", type: "rangehood_flap", width: 600 },
        { id: "rh-3", type: "rangehood_flap", width: 600 },
        { id: "normal", type: "up_flap", width: 600 },
      ],
    },
    expected: { clearHeight: 75, alignment: "left", edgeOffsetX: 80, internalDividerCount: 2, rangehoodZoneCount: 3 },
  },
];

for (const item of cases) {
  const result = runBridge(item.params);
  assert.deepEqual(result.validation.errors, [], `${item.name}: ${JSON.stringify(result.validation.errors)}`);
  validateEveryBoard(result, item.name);
  validateRangehoodAssembly(result, { name: item.name, ...item.expected });
  validateNoUnintendedRangehoodCollisions(result, item.name);
  console.log(`SELF-CHECK ${item.name}: ${result.boards.length} boards PASS`);
}

const tooTall = runBridge({
  cabinetWidth: 1000,
  cabinetDepth: 400,
  cabinetHeight: 400,
  featureWidth: 15,
  topClearanceHeight: 40,
  rangehoodClearHeight: 316, // 3*CPT + 316 = 361 > functionalTop 360.
  zones: [{ type: "rangehood_flap", width: 1000 }],
});
assert.ok(tooTall.validation.errors.some((error) => error.includes("top-clearance")));

const adapterSource = fs.readFileSync(
  path.join(pluginDir, "modules", "general_tall", "fusion_adapter.py"),
  "utf8",
);
const controllerSource = fs.readFileSync(
  path.join(pluginDir, "modules", "overhead", "controller.py"),
  "utf8",
);
for (const functionName of ["_oh_cut_xy_rect_features", "_oh_cut_divider_side_grooves"]) {
  const start = adapterSource.indexOf(`def ${functionName}`);
  const end = adapterSource.indexOf("\ndef ", start + 5);
  const body = adapterSource.slice(start, end);
  assert.ok(body.includes("_set_single_body_participants(ext_input, body)"), `${functionName}: compatible participant isolation missing`);
  assert.ok(body.includes('raise RuntimeError("participantBodies isolation failed'), `${functionName}: isolation must fail closed`);
  assert.ok(body.indexOf("_set_single_body_participants") < body.indexOf("extrudes.add(ext_input)"), `${functionName}: cut created before isolation`);
}
const participantHelperStart = adapterSource.indexOf("def _set_single_body_participants");
const participantHelperEnd = adapterSource.indexOf("\ndef ", participantHelperStart + 5);
const participantHelper = adapterSource.slice(participantHelperStart, participantHelperEnd);
assert.ok(participantHelper.includes("ext_input.participantBodies = [body]"), "Fusion SWIG list participant path missing");
assert.ok(controllerSource.includes("create_container_component=True"), "Overhead must create one child component per board");
assert.ok(adapterSource.includes('components_by_id.get("RGHD_TOP") or component'), "RGHD_TOP cut must use its own component");
assert.ok(adapterSource.includes("components_by_id.get(board_id) or component"), "D side groove must use target board component");
console.log("SELF-CHECK extrusion isolation: PASS (per-board component + fail-closed participantBodies)");
console.log(`SELF-CHECK COMPLETE: ${cases.length} valid standards + 1 invalid boundary case`);
