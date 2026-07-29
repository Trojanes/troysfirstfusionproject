import assert from "node:assert";
import { generateUShapeOverheadCabinet } from "./generator.ts";

function board(result: ReturnType<typeof generateUShapeOverheadCabinet>, runId: string, id: string) {
  return result.runs.find((run) => run.id === runId)?.result.boards.find((entry) => entry.id === id);
}

function feature(result: ReturnType<typeof generateUShapeOverheadCabinet>, runId: string, type: string) {
  return result.runs.find((run) => run.id === runId)?.result.features.find(
    (entry) => (entry as Record<string, unknown>).type === type,
  ) as Record<string, unknown> | undefined;
}

function standardResult() {
  return generateUShapeOverheadCabinet({
    totalWidth: 2400,
    leftArmLength: 1500,
    rightArmLength: 1300,
    cabinetDepth: 450,
    cabinetHeight: 400,
    sideClearance: 50,
    frontPanelThickness: 16,
    featureWidth: 15,
    zones: {
      LEFT: [{ id: "left-main", type: "up_flap", width: 1000 }],
      BACK: [{ id: "back-main", type: "up_flap", width: 1368 }],
      RIGHT: [{ id: "right-main", type: "fixed_panel", width: 800 }],
    },
  });
}

function testStandardGeometry(): void {
  const result = standardResult();
  assert.deepEqual(result.validation.errors, []);
  assert.equal(result.params.backCabinetWidth, 2400);
  assert.equal(result.params.backFunctionalSpan, 1500);
  assert.equal(result.params.backClearanceWidth, 66);
  assert.equal(result.runs.find((run) => run.id === "LEFT")?.usableZoneWidth, 984);
  assert.equal(result.runs.find((run) => run.id === "BACK")?.usableZoneWidth, 1368);
  assert.equal(result.runs.find((run) => run.id === "RIGHT")?.usableZoneWidth, 784);
  assert.equal(new Set(result.worldBoards.map((entry) => entry.id)).size, result.worldBoards.length);
  assert(result.audit.every((entry) => entry.ok), JSON.stringify(result.audit));

  for (const run of result.runs) {
    const dividers = run.result.boards.filter((entry) => /^D\d+$/.test(entry.id));
    assert.equal(dividers.length, 2, `${run.id} clearance fronts must not add dividers`);
    assert(!run.result.features.some((entry) => String((entry as Record<string, unknown>).type || "").includes("rangehood")));
    assert(run.result.features.some((entry) => (entry as Record<string, unknown>).type === "t3_groove"));
  }
  assert(!board(result, "BACK", "D_CORNER_LEFT"));
  assert(!board(result, "BACK", "D_CORNER_RIGHT"));
}

function testClearanceFrontsAndTopJoin(): void {
  const result = standardResult();
  assert.equal((board(result, "BACK", "FP_CLEARANCE_LEFT")?.x1 ?? 0) - (board(result, "BACK", "FP_CLEARANCE_LEFT")?.x0 ?? 0), 66);
  assert.equal((board(result, "BACK", "FP_CLEARANCE_RIGHT")?.x1 ?? 0) - (board(result, "BACK", "FP_CLEARANCE_RIGHT")?.x0 ?? 0), 66);
  assert.equal((board(result, "LEFT", "FP_CLEARANCE_SIDE")?.x1 ?? 0) - (board(result, "LEFT", "FP_CLEARANCE_SIDE")?.x0 ?? 0), 50);
  assert.equal((board(result, "RIGHT", "FP_CLEARANCE_SIDE")?.x1 ?? 0) - (board(result, "RIGHT", "FP_CLEARANCE_SIDE")?.x0 ?? 0), 50);
  const leftFixed = result.worldBoards.find((entry) => entry.id === "LEFT.FP_CLEARANCE_SIDE")!;
  const rightFixed = result.worldBoards.find((entry) => entry.id === "RIGHT.FP_CLEARANCE_SIDE")!;
  assert.deepEqual(
    { x0: leftFixed.x0, x1: leftFixed.x1, y0: leftFixed.y0, y1: leftFixed.y1 },
    { x0: 450, x1: 466, y0: 466, y1: 516 },
  );
  assert.deepEqual(
    { x0: rightFixed.x0, x1: rightFixed.x1, y0: rightFixed.y0, y1: rightFixed.y1 },
    { x0: 1934, x1: 1950, y0: 466, y1: 516 },
  );

  // BACK owns both corners; Style-1 TCH-1 seats BACK T1/T2 into divider notches.
  // Side rails extend into the corner by TCH-1 so final faces meet BACK.T2.
  const rearNotch = 40 - 1;
  const fpt = 16;
  assert.equal(board(result, "LEFT", "T1")?.x0, -(fpt + rearNotch));
  assert.equal(board(result, "LEFT", "T1")?.x1, 1050);
  assert.equal(board(result, "RIGHT", "T1")?.x0, 0);
  assert.equal(board(result, "RIGHT", "T1")?.x1, 850 + fpt + rearNotch);
  assert.equal(board(result, "LEFT", "T2")?.x0, -(fpt + rearNotch));
  assert.equal(board(result, "RIGHT", "T2")?.x1, 850 + fpt + rearNotch);
  assert.equal(board(result, "BACK", "T1")?.x0, 450 - rearNotch);
  assert.equal(board(result, "BACK", "T1")?.x1, 2400 - 450 + rearNotch);
  assert.equal(board(result, "BACK", "T1")?.y0, 0);
  assert.equal(board(result, "BACK", "T2")?.y0, fpt);
  assert.equal(board(result, "BACK", "T2")?.x0, 0);
  assert.equal(board(result, "BACK", "T2")?.x1, 2400);
  assert.equal(board(result, "BACK", "T3")?.x0, 0);
  assert.equal(board(result, "BACK", "T3")?.x1, 2400);
  const backT3 = board(result, "BACK", "T3")!;
  const backT4 = board(result, "BACK", "T4")!;
  const t3Xs = new Set((backT3.profileVector as Array<{ x: number }>).map((point) => point.x));
  assert((backT4.profileVector as Array<{ x?: number; y?: number; z?: number }>).every(
    (point) => Number.isFinite(point.x) && Number.isFinite(point.y) && point.z == null,
  ), "BACK.T4 XY profile must not be rewritten as XZ");
  for (const x of [0, 15.5, 2384.5, 2400]) assert(t3Xs.has(x), `missing BACK.T3 notch X=${x}`);
  for (const [runId, boardId] of [["LEFT", "T1"], ["RIGHT", "T1"], ["BACK", "T1"], ["BACK", "T2"]]) {
    const topBoard = board(result, runId, boardId)!;
    const profileXs = (topBoard.profileVector || []).map((point) => Number((point as { x?: number }).x)).filter(Number.isFinite);
    if (profileXs.length) {
      assert.equal(Math.max(...profileXs) - Math.min(...profileXs), topBoard.x1 - topBoard.x0, `${runId}.${boardId} profile width`);
    }
  }
}

function testConnectorTonguesAndGrooves(): void {
  const result = standardResult();
  const connector = board(result, "BACK", "U_CONNECTOR_LEFT");
  assert(connector);
  assert.equal(connector.materialThickness, 15);
  assert.equal(connector.x1 - connector.x0, 435);
  assert.equal(connector.y0, 0);
  assert.equal(connector.y1, 15);
  assert.equal(connector.z0, 23);
  assert.equal(connector.z1, 374);

  const bpGroove = feature(result, "BACK", "u_connector_bp_groove");
  const t3Groove = feature(result, "BACK", "u_connector_t3_through_groove");
  assert(bpGroove && t3Groove);
  const bpX = bpGroove.x as number[];
  const bpY = bpGroove.y as number[];
  assert.equal(bpX[1]! - bpX[0]!, 145);
  assert.equal(bpY[1]! - bpY[0]!, 16);
  assert.equal(bpGroove.depth, 7.5);
  assert.equal(t3Groove.depth, 15);
  assert.equal(t3Groove.through, true);

  const profile = connector.profileVector as Array<{ x: number; z: number }>;
  const top = Math.max(...profile.map((point) => point.z));
  const bottom = Math.min(...profile.map((point) => point.z));
  assert.equal(top - bottom, 351);
  const tongueLength = 435 / 3 - 10;
  const tongueXs = [...new Set(profile.filter((point) => point.z === 0).map((point) => point.x))];
  assert.equal(Math.max(...tongueXs) - Math.min(...tongueXs), tongueLength);
}

function testWorldContacts(): void {
  const result = standardResult();
  const leftConnector = result.worldBoards.find((entry) => entry.id === "BACK.U_CONNECTOR_LEFT")!;
  const leftSideDivider = result.worldBoards
    .filter((entry) => entry.runId === "LEFT" && /^D\d+$/.test(entry.localBoardId))
    .sort((a, b) => a.y0 - b.y0)[0]!;
  const rightConnector = result.worldBoards.find((entry) => entry.id === "BACK.U_CONNECTOR_RIGHT")!;
  const rightSideDivider = result.worldBoards
    .filter((entry) => entry.runId === "RIGHT" && /^D\d+$/.test(entry.localBoardId))
    .sort((a, b) => a.y0 - b.y0)[0]!;
  assert.equal(leftConnector.y1, leftSideDivider.y0);
  assert.equal(rightConnector.y1, rightSideDivider.y0);
}

function testValidationAndNormalization(): void {
  const normalized = generateUShapeOverheadCabinet({
    totalWidth: 2400,
    leftArmLength: 1500,
    rightArmLength: 1300,
    cabinetDepth: 450,
    cabinetHeight: 400,
    zones: { BACK: [{ type: "up_flap", width: 100 }] },
  });
  assert(normalized.validation.warnings.some((warning) => warning.includes("BACK zone widths were normalized")));
  assert.equal(normalized.runs.find((run) => run.id === "BACK")?.usableZoneWidth, 1368);

  const invalid = generateUShapeOverheadCabinet({
    totalWidth: 800,
    leftArmLength: 450,
    rightArmLength: 450,
    cabinetDepth: 450,
    cabinetHeight: 100,
  });
  assert(invalid.validation.errors.length >= 3);
  assert.equal(invalid.runs.length, 0);
}

function testDefaultDimensions(): void {
  const result = generateUShapeOverheadCabinet({} as never);
  assert.equal(result.params.totalWidth, 2275);
  assert.equal(result.params.cabinetDepth, 400);
  assert.equal(result.params.cabinetHeight, 400);
  assert.deepEqual(result.validation.errors, []);
  assert(result.audit.every((row) => row.ok));
}

function testSideLedTrim(): void {
  const result = generateUShapeOverheadCabinet({
    totalWidth: 2275,
    leftArmLength: 1500,
    rightArmLength: 1500,
    cabinetDepth: 400,
    cabinetHeight: 400,
  });
  const leftLed = feature(result, "LEFT", "t3_groove")!;
  const rightLed = feature(result, "RIGHT", "t3_groove")!;
  const backLed = feature(result, "BACK", "t3_groove")!;
  // Side grooves span each shortened side T3 seam-to-tip.
  assert.equal((leftLed.main as { x0: number; x1: number }).x0, 0);
  assert.equal((leftLed.main as { x0: number; x1: number }).x1, 1100);
  assert.equal((rightLed.main as { x0: number; x1: number }).x0, 0);
  assert.equal((rightLed.main as { x0: number; x1: number }).x1, 1100);
  assert.equal(leftLed.frontEndThrough, true);
  assert.equal(rightLed.frontEndThrough, true);
  assert.equal(leftLed.adapterMirrorX, true);
  assert.equal(rightLed.adapterMirrorX, true);
  // BACK stays through-running for end wire exits.
  assert.equal((backLed.main as { x0: number; x1: number }).x0, 320);
  assert.equal((backLed.main as { x0: number; x1: number }).x1, 1955);
  assert.deepEqual(
    (backLed.branches as Array<{ x0: number; x1: number }>).map((branch) => (branch.x0 + branch.x1) / 2),
    [400, 1875],
  );
  assert(!result.runs.find((run) => run.id === "BACK")?.result.features.some(
    (row) => (row as Record<string, unknown>).role === "u_corner_continuation",
  ));
  assert(result.audit.some((row) => row.id === "left_side_led_trim" && row.ok));
  assert(result.audit.some((row) => row.id === "right_side_led_trim" && row.ok));
}

function testIndependentBackLedSwitch(): void {
  const result = generateUShapeOverheadCabinet({
    totalWidth: 2275,
    leftArmLength: 1500,
    rightArmLength: 1500,
    cabinetDepth: 400,
    cabinetHeight: 400,
    runLedGroove: { LEFT: true, BACK: false, RIGHT: false },
  });
  const backFeatures = result.runs.find((run) => run.id === "BACK")!.result.features as Array<Record<string, unknown>>;
  assert(!backFeatures.some((row) => row.type === "t3_groove" && row.role !== "u_corner_continuation"));
  assert(!backFeatures.some((row) => row.type === "t3_groove"));
}

testStandardGeometry();
testClearanceFrontsAndTopJoin();
testConnectorTonguesAndGrooves();
testWorldContacts();
testValidationAndNormalization();
testDefaultDimensions();
testSideLedTrim();
testIndependentBackLedSwitch();
console.log("OK U Shape OHC generator tests");
