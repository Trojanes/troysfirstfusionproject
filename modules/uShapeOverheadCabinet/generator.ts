import { generateOverheadCabinet } from "../overheadCabinet/generator.ts";
import { t3TrimmedOutlinePoints, t4TrimmedOutlinePoints } from "../overheadCabinet/geometry.ts";
import { relationshipDeclarationsForBoards } from "../overheadCabinet/relationshipDeclarations.ts";
import type { Board, OverheadCabinetParams, OverheadCabinetResult } from "../overheadCabinet/types.ts";
import type {
  UShapeContactAudit,
  UShapeOverheadParams,
  UShapeOverheadResult,
  UShapeRunBuildOptions,
  UShapeRunId,
  UShapeRunResult,
  UShapeRunTransform,
  UShapeWorldBoard,
  UShapeZone,
} from "./types.ts";

const DEFAULT_HEIGHT = 400;
const DEFAULT_DEPTH = 400;
const DEFAULT_CPT = 15;
const DEFAULT_FPT = 16;
const DEFAULT_CLEARANCE = 2.5;
const DEFAULT_SIDE_CLEARANCE = 50;

function finite(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function color(input: UShapeOverheadParams): { carcassColor: string; carcassColorName: string } {
  const raw = String(input.carcassColor || input.carcassColorName || "white_stipple").trim();
  const carcassColor = raw.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]+/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "") || "white_stipple";
  return {
    carcassColor,
    carcassColorName: String(input.carcassColorName || (carcassColor === "white_stipple" ? "White Stipple" : raw)).trim() || "White Stipple",
  };
}

function normalizeZones(
  input: UShapeZone[] | undefined,
  usableWidth: number,
  runId: UShapeRunId,
  warnings: string[],
): UShapeZone[] {
  const source = Array.isArray(input) && input.length > 0
    ? input.map((zone, index) => ({
      id: String(zone.id || `${runId.toLowerCase()}-zone-${index + 1}`),
      type: String(zone.type || "up_flap"),
      width: Math.max(0, finite(zone.width, 0)),
    }))
    : [{ id: `${runId.toLowerCase()}-zone-1`, type: "up_flap", width: Math.max(0, usableWidth) }];
  const total = source.reduce((sum, zone) => sum + zone.width, 0);
  if (usableWidth <= 0) return source.map((zone) => ({ ...zone, width: 0 }));
  if (total <= 0) {
    warnings.push(`${runId} zones had no positive width; one default zone was substituted.`);
    return [{ id: `${runId.toLowerCase()}-zone-1`, type: "up_flap", width: usableWidth }];
  }
  if (Math.abs(total - usableWidth) > 0.01) {
    warnings.push(`${runId} zone widths were normalized from ${total.toFixed(2)} mm to ${usableWidth.toFixed(2)} mm.`);
  }
  const scale = usableWidth / total;
  let consumed = 0;
  return source.map((zone, index) => {
    const width = index === source.length - 1
      ? Math.max(0, usableWidth - consumed)
      : zone.width * scale;
    consumed += width;
    return { ...zone, width };
  });
}

function structuralZones(zones: UShapeZone[], reservedStart: number, reservedEnd: number): UShapeZone[] {
  return zones.map((zone, index) => ({
    ...zone,
    width: zone.width
      + (index === 0 ? reservedStart : 0)
      + (index === zones.length - 1 ? reservedEnd : 0),
  }));
}

/**
 * When a run hosts rangehood_flap, never inflate reserved width into that zone —
 * OHC resolveRangehoodGroup would otherwise pull the hood into the corner/reserved
 * band. Emit reserved as synthetic open pads instead so dividers stay correct.
 */
function structuralZonesForOhc(
  zones: UShapeZone[],
  reservedStart: number,
  reservedEnd: number,
): UShapeZone[] {
  const hasRangehood = zones.some((zone) => zone.type === "rangehood_flap");
  if (!hasRangehood) return structuralZones(zones, reservedStart, reservedEnd);
  const padded: UShapeZone[] = [];
  if (reservedStart > 0) {
    padded.push({ id: "structural-reserved-start", type: "open", width: reservedStart });
  }
  padded.push(...zones.map((zone) => ({ ...zone })));
  if (reservedEnd > 0) {
    padded.push({ id: "structural-reserved-end", type: "open", width: reservedEnd });
  }
  return padded;
}

function zoneHasRangehood(zones: UShapeZone[]): boolean {
  return zones.some((zone) => zone.type === "rangehood_flap");
}

function isGeneratedFrontFeature(feature: unknown): boolean {
  if (!feature || typeof feature !== "object") return false;
  const row = feature as Record<string, unknown>;
  const id = String(row.id || "");
  const boardId = String(row.boardId || "");
  return /^FP\d+(?:_|$)/.test(id) || /^FP\d+$/.test(boardId) || row.purpose === "hinge";
}

function frontBoard(
  id: string,
  name: string,
  boardType: string,
  x0: number,
  x1: number,
  params: OverheadCabinetResult["params"],
  source: string,
): Board {
  const width = Math.max(0, x1 - x0);
  const z0 = -30;
  const z1 = params.cabinetHeight - params.topClearanceHeight - 1;
  return {
    id,
    name,
    category: "front_panel",
    boardType,
    materialThickness: params.frontPanelThickness,
    profilePlane: "XZ",
    thicknessAxis: "Y",
    x0,
    x1,
    y0: -params.frontPanelThickness,
    y1: 0,
    z0,
    z1,
    source,
    profileVector: [
      { x: 0, z: 0 },
      { x: width, z: 0 },
      { x: width, z: z1 - z0 },
      { x: 0, z: z1 - z0 },
      { x: 0, z: 0 },
    ],
  };
}

function frontFeature(board: Board, zone: UShapeZone, zoneIndex: number): Record<string, unknown> {
  return {
    id: board.id,
    zoneId: zone.id,
    zoneIndex,
    type: zone.type,
    x: [board.x0, board.x1],
    y: [board.y0, board.y1],
    z: [board.z0, board.z1],
    width: board.x1 - board.x0,
    height: board.z1 - board.z0,
    thickness: board.materialThickness,
  };
}

function hingeFeatures(
  board: Board,
  params: OverheadCabinetResult["params"],
): Array<Record<string, unknown>> {
  if (board.boardType !== "up_flap" && board.boardType !== "rangehood_flap") return [];
  const width = board.x1 - board.x0;
  const height = board.z1 - board.z0;
  return [params.hingeHoleFromSide, width - params.hingeHoleFromSide].map((centerX, index) => ({
    id: `${board.id}_HINGE_${index + 1}`,
    boardId: board.id,
    center: [centerX, height - params.hingeHoleFromTop],
    diameter: params.hingeHoleDiameter,
    depth: params.hingeHoleDepth,
    axis: "Y",
    purpose: "hinge",
    face: "back",
  }));
}

function connectorBoardAt(
  id: "U_CONNECTOR_LEFT" | "U_CONNECTOR_RIGHT",
  bodyX0: number,
  depth: number,
  params: OverheadCabinetResult["params"],
): { board: Board; features: Array<Record<string, unknown>> } {
  const cpt = params.featureWidth;
  const bodyWidth = depth - cpt;
  const bodyX1 = bodyX0 + bodyWidth;
  const tongueX0 = bodyX0 + bodyWidth / 3 + 5;
  const tongueX1 = bodyX0 + bodyWidth * 2 / 3 - 5;
  const grooveX0 = bodyX0 + bodyWidth / 3;
  const grooveX1 = bodyX0 + bodyWidth * 2 / 3;
  const bpTop = cpt * 2;
  const t3Bottom = params.cabinetHeight - cpt - params.topClearanceHeight + 14;
  const halfTongue = Math.max(0, cpt / 2 - 0.5);
  const fullTongue = cpt;
  const localTongueX0 = tongueX0 - bodyX0;
  const localTongueX1 = tongueX1 - bodyX0;
  const bodyHeight = Math.max(0, t3Bottom - bpTop);
  const board: Board = {
    id,
    name: `${id === "U_CONNECTOR_LEFT" ? "Left" : "Right"} BACK Corner Connector Panel`,
    category: "connector_panel",
    boardType: "u_back_connector_panel",
    materialThickness: cpt,
    profilePlane: "XZ",
    thicknessAxis: "Y",
    x0: bodyX0,
    x1: bodyX1,
    y0: 0,
    y1: cpt,
    z0: bpTop - halfTongue,
    z1: t3Bottom + fullTongue,
    source: "u_shape_overhead_geometry",
    notes: [
      "Carcass connector for face-to-face field screw connection to BACK boundary divider.",
      "Top full tongue; bottom half tongue.",
    ],
    profileVector: [
      { x: 0, z: halfTongue },
      { x: localTongueX0, z: halfTongue },
      { x: localTongueX0, z: 0 },
      { x: localTongueX1, z: 0 },
      { x: localTongueX1, z: halfTongue },
      { x: bodyWidth, z: halfTongue },
      { x: bodyWidth, z: halfTongue + bodyHeight },
      { x: localTongueX1, z: halfTongue + bodyHeight },
      { x: localTongueX1, z: halfTongue + bodyHeight + fullTongue },
      { x: localTongueX0, z: halfTongue + bodyHeight + fullTongue },
      { x: localTongueX0, z: halfTongue + bodyHeight },
      { x: 0, z: halfTongue + bodyHeight },
      { x: 0, z: halfTongue },
    ],
  };
  // Connector sits on the front edge (Y=0), so the 1 mm groove allowance
  // must extend into the board rather than being clipped outside its bbox.
  const slotY0 = 0;
  const slotY1 = cpt + 1;
  return {
    board,
    features: [
      {
        id: `${id}_BP_GROOVE`,
        type: "u_connector_bp_groove",
        targetBoardId: "BP",
        connectorBoardId: board.id,
        face: "top",
        x: [grooveX0, grooveX1],
        y: [slotY0, slotY1],
        depth: cpt / 2,
        tongueInsertion: halfTongue,
      },
      {
        id: `${id}_T3_GROOVE`,
        type: "u_connector_t3_through_groove",
        targetBoardId: "T3",
        connectorBoardId: board.id,
        face: "top",
        x: [grooveX0, grooveX1],
        y: [slotY0, slotY1],
        through: true,
        depth: cpt,
        tongueInsertion: fullTongue,
      },
    ],
  };
}

function rebuildBackTopNotchProfiles(result: OverheadCabinetResult): void {
  const notchRanges = (result.features as Array<Record<string, unknown>>)
    .map((feature) => feature.t3_notch as { x?: number[] } | undefined)
    .filter((notch): notch is { x: number[] } => (
      Array.isArray(notch?.x) && notch.x.length === 2
    ))
    .map((notch) => [Number(notch.x[0]), Number(notch.x[1])] as [number, number]);
  const t3 = result.boards.find((board) => board.id === "T3");
  const t4 = result.boards.find((board) => board.id === "T4");
  if (t3) {
    t3.profileVector = t3TrimmedOutlinePoints(result.params.cabinetWidth, notchRanges)
      .map(([x, y]) => ({ x, y }));
  }
  if (t4) {
    t4.profileVector = t4TrimmedOutlinePoints(result.params.cabinetWidth, notchRanges)
      .map(([x, y]) => ({ x, y }));
  }
}

function replaceFacade(
  base: OverheadCabinetResult,
  options: UShapeRunBuildOptions,
  zones: UShapeZone[],
  sideClearance: number,
  backClearance: number,
): OverheadCabinetResult {
  const boards = base.boards.filter((board) => !/^FP\d+$/.test(board.id));
  const features = base.features.filter((feature) => !isGeneratedFrontFeature(feature));
  const p = base.params;
  const clearance = p.clearance;
  let cursor = options.reservedStart;
  const facadeBoards: Board[] = [];
  const facadeFeatures: Array<Record<string, unknown>> = [];

  for (let index = 0; index < zones.length; index += 1) {
    const zone = zones[index]!;
    const segmentX0 = cursor;
    const segmentX1 = cursor + zone.width;
    cursor = segmentX1;
    if (zone.type === "open") continue;
    const leftGap = index === 0 ? clearance : clearance / 2;
    const rightGap = index === zones.length - 1 ? clearance : clearance / 2;
    const board = frontBoard(
      `FP${index}`,
      `${options.id} Front Panel ${index + 1}`,
      zone.type,
      segmentX0 + leftGap,
      segmentX1 - rightGap,
      p,
      "u_shape_overhead_facade",
    );
    facadeBoards.push(board);
    facadeFeatures.push(frontFeature(board, zone, index), ...hingeFeatures(board, p));
  }

  if (options.id === "BACK") {
    facadeBoards.push(
      frontBoard("FP_CLEARANCE_LEFT", "Back Left Clearance Fixed Front", "u_clearance_fixed_panel", p.cabinetDepth, p.cabinetDepth + backClearance, p, "u_shape_overhead_facade"),
      frontBoard("FP_CLEARANCE_RIGHT", "Back Right Clearance Fixed Front", "u_clearance_fixed_panel", options.width - p.cabinetDepth - backClearance, options.width - p.cabinetDepth, p, "u_shape_overhead_facade"),
    );
    const leftConnector = connectorBoardAt(
      "U_CONNECTOR_LEFT",
      options.width - p.cabinetDepth,
      p.cabinetDepth,
      p,
    );
    const rightConnector = connectorBoardAt(
      "U_CONNECTOR_RIGHT",
      p.featureWidth,
      p.cabinetDepth,
      p,
    );
    boards.push(leftConnector.board, rightConnector.board);
    features.push(...leftConnector.features, ...rightConnector.features);
    rebuildBackTopNotchProfiles({ ...base, boards, features });
  } else {
    const isLeft = options.id === "LEFT";
    const x0 = isLeft
      ? options.reservedStart - sideClearance
      : options.width - options.endClearance;
    const x1 = x0 + sideClearance;
    facadeBoards.push(
      frontBoard("FP_CLEARANCE_SIDE", `${options.id} Side Clearance Fixed Front`, "u_clearance_fixed_panel", x0, x1, p, "u_shape_overhead_facade"),
    );
  }

  boards.push(...facadeBoards);
  features.push(...facadeFeatures);
  return {
    ...base,
    boards,
    features,
    relationshipDeclarations: relationshipDeclarationsForBoards(boards),
  };
}

/** Fusion `_placement_offset_mm` for overhead T1/T2: local +Y by TCH-1. */
function style1RearNotchShiftMm(params: { topClearanceHeight?: number }): number {
  return Math.max(0, Number(params.topClearanceHeight ?? 40) - 1);
}

/**
 * Style 1 U top join (final-Adapter face targets, not design-space only):
 * - BACK owns both corners; BACK.T2 is full total width; BACK.T1 spans between
 *   the final side-T1 faces after TCH-1.
 * - Do NOT pre-cancel Fusion's TCH-1 on BACK Y: that shift seats T1/T2 into the
 *   divider front-top notch (step at y=FRONT_TOP_NOTCH≈FPT+CPT+TCH-1). Cancelling
 *   it leaves a gap between T1/T2 and the divider upper step.
 * - SIDE T1/T2 extend toward BACK by TCH-1 so their seam face meets final BACK.T2.
 */
function adjustStyle1Top(result: OverheadCabinetResult, runId: UShapeRunId): void {
  const runWidth = result.params.cabinetWidth;
  const depth = result.params.cabinetDepth;
  const fpt = result.params.frontPanelThickness;
  const rearNotch = style1RearNotchShiftMm(result.params);
  const t1 = result.boards.find((board) => board.id === "T1");
  const t2 = result.boards.find((board) => board.id === "T2");
  if (runId === "BACK") {
    if (t1) {
      t1.x0 = depth - rearNotch;
      t1.x1 = runWidth - depth + rearNotch;
      resizeBoardProfileX(t1);
    }
    if (t2) {
      t2.x0 = 0;
      t2.x1 = runWidth;
      resizeBoardProfileX(t2);
    }
    return;
  }
  for (const board of [t1, t2]) {
    if (!board) continue;
    if (runId === "LEFT") {
      // Extend into the corner by TCH-1 so final y0 meets BACK.T2 after Adapter.
      board.x0 = -(fpt + rearNotch);
      board.x1 = runWidth;
    } else {
      board.x0 = 0;
      board.x1 = runWidth + fpt + rearNotch;
    }
    resizeBoardProfileX(board);
  }
}

/** Apply Fusion T1/T2 TCH-1 shift in world XY for a posed run board. */
function finalTopWorldBBox(
  board: UShapeWorldBoard,
  rotationDeg: number,
  rearNotch: number,
): Pick<UShapeWorldBoard, "x0" | "x1" | "y0" | "y1"> {
  if (rearNotch <= 0 || (board.localBoardId !== "T1" && board.localBoardId !== "T2")) {
    return { x0: board.x0, x1: board.x1, y0: board.y0, y1: board.y1 };
  }
  if (rotationDeg === 90) {
    return { x0: board.x0 - rearNotch, x1: board.x1 - rearNotch, y0: board.y0, y1: board.y1 };
  }
  if (rotationDeg === -90) {
    return { x0: board.x0 + rearNotch, x1: board.x1 + rearNotch, y0: board.y0, y1: board.y1 };
  }
  if (rotationDeg === 180) {
    return { x0: board.x0, x1: board.x1, y0: board.y0 - rearNotch, y1: board.y1 - rearNotch };
  }
  return { x0: board.x0, x1: board.x1, y0: board.y0 + rearNotch, y1: board.y1 + rearNotch };
}

function resizeBoardProfileX(board: Board): void {
  if (!Array.isArray(board.profileVector)) return;
  const points = board.profileVector as Array<Record<string, number>>;
  const xValues = points.map((point) => Number(point.x)).filter(Number.isFinite);
  if (xValues.length < 2) return;
  const oldMin = Math.min(...xValues);
  const oldMax = Math.max(...xValues);
  const oldWidth = oldMax - oldMin;
  const newWidth = board.x1 - board.x0;
  if (!(oldWidth > 0) || !(newWidth > 0)) return;
  board.profileVector = points.map((point) => (
    Number.isFinite(Number(point.x))
      ? { ...point, x: (Number(point.x) - oldMin) / oldWidth * newWidth }
      : { ...point }
  )) as Board["profileVector"];
}

function buildRun(
  options: UShapeRunBuildOptions,
  zones: UShapeZone[],
  sideClearance: number,
  backClearance: number,
): UShapeRunResult {
  const reservedEnd = options.endClearance;
  const allowRangehood = options.id === "LEFT" || options.id === "RIGHT";
  const wantsRangehood = allowRangehood && zoneHasRangehood(zones);
  const base = generateOverheadCabinet({
    ...options.overheadParams,
    cabinetWidth: options.width,
    zones: structuralZonesForOhc(zones, options.reservedStart, reservedEnd),
    // BACK never hosts rangehood; side arms only, and never into corners.
    rangehoodPreset: wantsRangehood ? (options.overheadParams.rangehoodPreset || "NCE") : undefined,
    ledGroove: options.overheadParams.ledGroove,
  });
  const result = replaceFacade(base, options, zones, sideClearance, backClearance);
  adjustStyle1Top(result, options.id);
  adjustSideLedGroove(result, options.id);
  if (options.id === "BACK") adjustBackLedForConnectorClearance(result);
  else adjustLedBranchesForNotchClearance(result);
  return {
    id: options.id,
    cabinetWidth: options.width,
    reservedStart: options.reservedStart,
    usableZoneWidth: zones.reduce((sum, zone) => sum + zone.width, 0),
    transform: options.transform,
    result,
  };
}

/** BACK-owned corners split each side LED at the y=D assembly seam. */
const SIDE_LED_BRANCH_INSET_MM = 80;
const SIDE_LED_PAST_BACK_T2_MM = 10;

function adjustSideLedGroove(result: OverheadCabinetResult, runId: UShapeRunId): void {
  if (runId === "BACK") return;
  const led = result.features.find((feature) => (
    feature
    && typeof feature === "object"
    && (feature as Record<string, unknown>).type === "t3_groove"
    && (feature as Record<string, unknown>).targetBoardId === "T3"
  )) as Record<string, unknown> | undefined;
  if (!led) return;
  const main = led.main as { x0?: number; x1?: number; y0?: number; y1?: number } | undefined;
  if (!main) return;
  const width = result.params.cabinetWidth;
  if (width <= SIDE_LED_BRANCH_INSET_MM * 2 + 1) return;
  main.x0 = 0;
  main.x1 = width;

  // Reflection does not change the sorted 80 mm endpoint insets.
  const halfW = (Number(main.y1) - Number(main.y0)) / 2;
  const branchY0 = Number(main.y1);
  const branchY1 = Array.isArray(led.branches) && led.branches[0]
    ? Number((led.branches[0] as { y1?: number }).y1)
    : branchY0;
  const centers = [SIDE_LED_BRANCH_INSET_MM, width - SIDE_LED_BRANCH_INSET_MM];
  if (centers[1]! - centers[0]! > halfW * 2) {
    led.branches = centers.map((centerX) => ({
      x0: centerX - halfW,
      x1: centerX + halfW,
      y0: branchY0,
      y1: branchY1,
    }));
    led.branchCount = 2;
  }
  led.frontEndThrough = true;
  led.openEndInset = 0;
  led.rearAtBackSeam = true;
  led.sideArmTrimmed = true;
  // Fusion creates the Style-1 T3 outline with a 180° XY profile correction.
  // Keep generator coordinates semantic, and tell the Adapter to mirror the
  // pocket X ranges so the final posed body—not the raw sketch—has apex flush.
  led.adapterMirrorX = true;
  const notes = Array.isArray(led.notes) ? led.notes.map(String) : [];
  led.notes = [
    ...notes.filter((note) => !/side-arm|open-end|BACK\.T2|apex|通到顶/i.test(note)),
    "Side-arm LED: rear ends at BACK seam; front runs through the open U tip",
  ];
}

function adjustBackLedForConnectorClearance(result: OverheadCabinetResult): void {
  const led = result.features.find((feature) => (
    feature && typeof feature === "object"
    && (feature as Record<string, unknown>).type === "t3_groove"
    && !(feature as Record<string, unknown>).role
  )) as Record<string, unknown> | undefined;
  const main = led?.main as { y0?: number; y1?: number } | undefined;
  if (!led || !main) return;
  const oldY1 = Number(main.y1);
  const minLand = result.params.featureWidth + 1;
  if (Number(main.y0) >= minLand) return;
  const grooveWidth = oldY1 - Number(main.y0);
  main.y0 = minLand;
  main.y1 = minLand + grooveWidth;
  led.frontLand = minLand;
  led.frontOffset = minLand + grooveWidth / 2;
  led.branches = ((led.branches as Array<Record<string, unknown>>) || []).map((branch) => ({
    ...branch,
    y0: Math.abs(Number(branch.y0) - oldY1) <= 0.05 ? Number(main.y1) : branch.y0,
  }));
}

const LED_BRANCH_NOTCH_CLEARANCE_MM = 20;

function adjustLedBranchesForNotchClearance(
  result: OverheadCabinetResult,
  clearance = LED_BRANCH_NOTCH_CLEARANCE_MM,
): void {
  const led = result.features.find((feature) => (
    feature && typeof feature === "object"
    && (feature as Record<string, unknown>).type === "t3_groove"
  )) as Record<string, unknown> | undefined;
  const main = led?.main as { x0?: number; x1?: number } | undefined;
  const branches = (led?.branches as Array<Record<string, unknown>>) || [];
  if (!led || !main || !branches.length) return;
  const notchRanges = (result.features as Array<Record<string, unknown>>)
    .map((feature) => (feature.t3_notch as { x?: number[] } | undefined)?.x)
    .filter((range): range is number[] => Array.isArray(range) && range.length === 2)
    .map((range) => [Number(range[0]), Number(range[1])] as [number, number])
    .sort((a, b) => a[0] - b[0]);
  const midpoint = (Number(main.x0) + Number(main.x1)) / 2;
  led.branches = branches.map((branch) => {
    const halfWidth = (Number(branch.x1) - Number(branch.x0)) / 2;
    let center = (Number(branch.x0) + Number(branch.x1)) / 2;
    if (center <= midpoint) {
      for (const [notchX0, notchX1] of notchRanges) {
        if (center + halfWidth + clearance > notchX0 && center - halfWidth - clearance < notchX1) {
          center = notchX1 + clearance + halfWidth;
        }
      }
    } else {
      for (const [notchX0, notchX1] of [...notchRanges].reverse()) {
        if (center + halfWidth + clearance > notchX0 && center - halfWidth - clearance < notchX1) {
          center = notchX0 - clearance - halfWidth;
        }
      }
    }
    const minCenter = Number(main.x0) + halfWidth;
    const maxCenter = Number(main.x1) - halfWidth;
    center = Math.min(Math.max(center, minCenter), maxCenter);
    return { ...branch, x0: center - halfWidth, x1: center + halfWidth };
  });
  led.branchNotchClearance = clearance;
}

function adjustBackLedExtent(runs: UShapeRunResult[]): void {
  const back = runs.find((run) => run.id === "BACK");
  if (!back) return;
  const led = back.result.features.find((feature) => (
    feature && typeof feature === "object"
    && (feature as Record<string, unknown>).type === "t3_groove"
  )) as Record<string, unknown> | undefined;
  const main = led?.main as { x0?: number; x1?: number; y1?: number } | undefined;
  if (!led || !main) return;
  const width = back.cabinetWidth;
  const rearNotch = style1RearNotchShiftMm(back.result.params);
  const cornerInset = back.result.params.cabinetDepth
    - back.result.params.frontPanelThickness
    - back.result.params.featureWidth
    - rearNotch
    - SIDE_LED_PAST_BACK_T2_MM;
  if (!(cornerInset >= 0 && width > cornerInset * 2 + SIDE_LED_BRANCH_INSET_MM * 2)) return;
  main.x0 = cornerInset;
  main.x1 = width - cornerInset;
  const halfW = Number(led.width || 14.5) / 2;
  const branchY0 = Number(main.y1);
  const oldBranches = (led.branches as Array<Record<string, unknown>>) || [];
  const branchY1 = oldBranches[0] ? Number(oldBranches[0].y1) : branchY0;
  const centers = [cornerInset + SIDE_LED_BRANCH_INSET_MM, width - cornerInset - SIDE_LED_BRANCH_INSET_MM];
  led.branches = centers.map((centerX) => ({
    x0: centerX - halfW,
    x1: centerX + halfW,
    y0: branchY0,
    y1: branchY1,
  }));
  led.branchCount = 2;
  led.sideT2PastMm = SIDE_LED_PAST_BACK_T2_MM;
  led.cornerInset = cornerInset;
  const notes = Array.isArray(led.notes) ? led.notes.map(String) : [];
  led.notes = [
    ...notes.filter((note) => !/corner|side T2/i.test(note)),
    `BACK LED stops ${SIDE_LED_PAST_BACK_T2_MM} mm past each side T2 and does not enter the outer corners.`,
  ];
  adjustLedBranchesForNotchClearance(back.result);
}

function transformXY(x: number, y: number, transform: UShapeRunTransform): [number, number] {
  const radians = transform.rotationDeg * Math.PI / 180;
  const cos = Math.round(Math.cos(radians));
  const sin = Math.round(Math.sin(radians));
  return [
    transform.translateX + x * cos - y * sin,
    transform.translateY + x * sin + y * cos,
  ];
}

function transformedPlane(plane: Board["profilePlane"], rotationDeg: number): Board["profilePlane"] {
  if (rotationDeg === 0 || rotationDeg === 180 || plane === "XY") return plane;
  if (plane === "XZ") return "YZ";
  if (plane === "YZ") return "XZ";
  return plane;
}

function transformedAxis(axis: Board["thicknessAxis"], rotationDeg: number): Board["thicknessAxis"] {
  if (rotationDeg === 0 || rotationDeg === 180 || axis === "Z") return axis;
  return axis === "X" ? "Y" : "X";
}

function worldBoard(run: UShapeRunResult, board: Board): UShapeWorldBoard {
  const corners = [
    transformXY(board.x0, board.y0, run.transform),
    transformXY(board.x0, board.y1, run.transform),
    transformXY(board.x1, board.y0, run.transform),
    transformXY(board.x1, board.y1, run.transform),
  ];
  const xs = corners.map(([x]) => x);
  const ys = corners.map(([, y]) => y);
  return {
    ...board,
    id: `${run.id}.${board.id}`,
    localBoardId: board.id,
    runId: run.id,
    name: `${run.id} ${board.name}`,
    profilePlane: transformedPlane(board.profilePlane, run.transform.rotationDeg),
    thicknessAxis: transformedAxis(board.thicknessAxis, run.transform.rotationDeg),
    x0: Math.min(...xs),
    x1: Math.max(...xs),
    y0: Math.min(...ys),
    y1: Math.max(...ys),
    notes: [...(board.notes || []), `Run transform ${run.transform.rotationDeg}deg @ (${run.transform.translateX}, ${run.transform.translateY})`],
  };
}

function positiveOverlap(a: Board, b: Board): number {
  const dx = Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0));
  const dy = Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
  const dz = Math.max(0, Math.min(a.z1, b.z1) - Math.max(a.z0, b.z0));
  return dx * dy * dz;
}

function featureRectOverlapArea(
  a: { x0: number; x1: number; y0: number; y1: number },
  b: { x0: number; x1: number; y0: number; y1: number },
): number {
  return Math.max(0, Math.min(a.x1, b.x1) - Math.max(a.x0, b.x0))
    * Math.max(0, Math.min(a.y1, b.y1) - Math.max(a.y0, b.y0));
}

function auditGeometry(
  runs: UShapeRunResult[],
  boards: UShapeWorldBoard[],
  sideClearance: number,
): UShapeContactAudit[] {
  const audit: UShapeContactAudit[] = [];
  const close = (a: number, b: number) => Math.abs(a - b) <= 0.01;
  // T3/T4 are intentionally emitted in their pre-postprocess design pose and
  // T4 is rotated later in Fusion. Their raw AABBs are not physical assembly
  // boxes, so only audit the already-physical lower carcass here.
  const structural = boards.filter((board) =>
    !board.id.includes(".FP")
    && !board.localBoardId.startsWith("U_CONNECTOR")
    && !/^T[1-4]$/.test(board.localBoardId)
  );
  let overlaps = 0;
  for (let i = 0; i < structural.length; i += 1) {
    for (let j = i + 1; j < structural.length; j += 1) {
      if (structural[i]!.runId === structural[j]!.runId) continue;
      if (positiveOverlap(structural[i]!, structural[j]!) > 0.01) overlaps += 1;
    }
  }
  audit.push({
    id: "cross_run_positive_overlap",
    kind: "no_overlap",
    ok: overlaps === 0,
    detail: overlaps === 0 ? "No cross-run structural AABB overlap." : `${overlaps} cross-run structural overlaps detected.`,
  });
  const baseParams = runs[0]?.result.params;
  const depth = baseParams?.cabinetDepth ?? 0;
  const fpt = baseParams?.frontPanelThickness ?? 0;
  const leftBp = boards.find((board) => board.id === "LEFT.BP");
  const backBp = boards.find((board) => board.id === "BACK.BP");
  const rightBpBoard = boards.find((board) => board.id === "RIGHT.BP");
  const totalOuterWidth = backBp ? backBp.x1 - backBp.x0 : 0;
  const backOwnsCorners = Boolean(
    leftBp && backBp && rightBpBoard
    && close(backBp.x0, 0) && close(backBp.x1, totalOuterWidth)
    && close(backBp.y0, 0) && close(backBp.y1, depth)
    && close(leftBp.y0, depth) && close(rightBpBoard.y0, depth)
    && close(leftBp.x0, 0) && close(leftBp.x1, depth)
    && close(rightBpBoard.x0, totalOuterWidth - depth) && close(rightBpBoard.x1, totalOuterWidth)
    && positiveOverlap(leftBp, backBp) <= 0.01
    && positiveOverlap(rightBpBoard, backBp) <= 0.01
  );
  audit.push({
    id: "back_owns_corner_cells",
    kind: "no_overlap",
    ok: backOwnsCorners,
    detail: backOwnsCorners
      ? "BACK owns both depth×depth corners; side BP boards begin at y=depth."
      : "BACK must cover both corner cells while LEFT/RIGHT BP begin at y=depth with no positive overlap.",
  });
  const rightBp = boards.find((board) => board.id === "RIGHT.BP");
  const totalWidth = rightBp?.x1 ?? 0;
  const sideY0 = depth + fpt;
  const sideY1 = sideY0 + sideClearance;
  const leftFixed = boards.find((board) => board.id === "LEFT.FP_CLEARANCE_SIDE");
  const rightFixed = boards.find((board) => board.id === "RIGHT.FP_CLEARANCE_SIDE");
  const backAtLeft = boards.find((board) => board.id === "BACK.FP_CLEARANCE_RIGHT");
  const backAtRight = boards.find((board) => board.id === "BACK.FP_CLEARANCE_LEFT");
  const fixedPlacementOk = Boolean(
    leftFixed && rightFixed && backAtLeft && backAtRight
    && close(leftFixed.x0, depth) && close(leftFixed.x1, depth + fpt)
    && close(rightFixed.x0, totalWidth - depth - fpt) && close(rightFixed.x1, totalWidth - depth)
    && close(leftFixed.y0, sideY0) && close(leftFixed.y1, sideY1)
    && close(rightFixed.y0, sideY0) && close(rightFixed.y1, sideY1)
    && close(backAtLeft.y1, leftFixed.y0)
    && close(backAtRight.y1, rightFixed.y0)
    && positiveOverlap(leftFixed, backAtLeft) <= 0.01
    && positiveOverlap(rightFixed, backAtRight) <= 0.01
  );
  const otherFronts = boards.filter((board) => (
    board.localBoardId.startsWith("FP")
    && board.localBoardId !== "FP_CLEARANCE_SIDE"
    && board.localBoardId !== "FP_CLEARANCE_LEFT"
    && board.localBoardId !== "FP_CLEARANCE_RIGHT"
  ));
  const sideFrontOverlap = [leftFixed, rightFixed].some((fixed) => (
    fixed && otherFronts.some((front) => positiveOverlap(fixed, front) > 0.01)
  ));
  audit.push({
    id: "side_clearance_front_contract",
    kind: "touch",
    ok: fixedPlacementOk && !sideFrontOverlap,
    detail: fixedPlacementOk && !sideFrontOverlap
      ? `Side clearance fronts are ${sideClearance}×${fpt} mm at Y=${sideY0}..${sideY1}, face-touching BACK fronts without overlap.`
      : `Side clearance fronts must be ${sideClearance}×${fpt} mm at Y=${sideY0}..${sideY1}, touch BACK front outer faces, and not overlap functional fronts.`,
  });
  for (const runId of ["LEFT", "RIGHT"] as const) {
    const run = runs.find((entry) => entry.id === runId);
    if (!run) continue;
    const led = run.result.features.find((feature) => (
      (feature as Record<string, unknown>).type === "t3_groove"
      && (feature as Record<string, unknown>).targetBoardId === "T3"
    )) as Record<string, unknown> | undefined;
    if (led) {
      const main = led.main as { x0?: number; x1?: number } | undefined;
      const width = run.cabinetWidth;
      const rangeOk = close(Number(main?.x0), 0) && close(Number(main?.x1), width);
      audit.push({
        id: `${runId.toLowerCase()}_side_led_trim`,
        kind: "dimension",
        ok: Boolean(main && rangeOk && led.adapterMirrorX === true),
        detail: main && rangeOk && led.adapterMirrorX === true
          ? `${runId} LED spans the complete side T3 from BACK seam to open tip.`
          : `${runId} LED raw [${main?.x0},${main?.x1}] expected [0,${width}] with Adapter mirroring.`,
      });
    }
  }
  if (runs.length === 3) {
    const leftConnector = boards.find((board) => board.id === "BACK.U_CONNECTOR_LEFT");
    const rightConnector = boards.find((board) => board.id === "BACK.U_CONNECTOR_RIGHT");
    const leftSideDivider = boards
      .filter((board) => board.runId === "LEFT" && board.localBoardId.startsWith("D"))
      .sort((a, b) => a.y0 - b.y0)[0];
    const rightSideDivider = boards
      .filter((board) => board.runId === "RIGHT" && board.localBoardId.startsWith("D"))
      .sort((a, b) => a.y0 - b.y0)[0];
    const backRunResult = runs.find((run) => run.id === "BACK")?.result;
    const bpGrooves = (backRunResult?.features || []).filter((feature) => (
      (feature as Record<string, unknown>).type === "u_connector_bp_groove"
    ));
    const t3Grooves = (backRunResult?.features || []).filter((feature) => (
      (feature as Record<string, unknown>).type === "u_connector_t3_through_groove"
    ));
    const connectorContactOk = Boolean(
      leftConnector
      && rightConnector
      && leftSideDivider
      && rightSideDivider
      && close(leftConnector.y1, leftSideDivider.y0)
      && close(rightConnector.y1, rightSideDivider.y0)
      && bpGrooves.length === 2
      && t3Grooves.length === 2
    );
    audit.push({
      id: "connector_back_divider_contacts",
      kind: "touch",
      ok: connectorContactOk,
      detail: connectorContactOk
        ? "Both BACK-owned connectors face-touch the side rear dividers and own their BP/T3 grooves."
        : "BACK connectors must face-touch both side rear dividers with two isolated BP and T3 grooves.",
    });

    // Corner closure without extra D_CORNER boards: outer edge dividers + BACK
    // connectors in the D×D cells + full-width BP/T3 + side rear dividers at y=D.
    const cpt = baseParams?.featureWidth ?? 0;
    const totalW = backBp ? backBp.x1 - backBp.x0 : 0;
    const backDividers = boards
      .filter((board) => board.runId === "BACK" && /^D\d+$/.test(board.localBoardId))
      .sort((a, b) => a.x0 - b.x0);
    const outerLeftD = backDividers[0];
    const outerRightD = backDividers[backDividers.length - 1];
    const backT3World = boards.find((board) => board.id === "BACK.T3");
    const cornerFronts = boards.filter((board) => (
      board.runId === "BACK"
      && board.localBoardId.startsWith("FP")
      && !board.localBoardId.startsWith("FP_CLEARANCE")
      && (
        (board.x1 <= depth + 0.01)
        || (board.x0 >= totalW - depth - 0.01)
      )
    ));
    // Connectors are local y=0..CPT on BACK; after 180° pose they sit at world y=D-CPT..D.
    // U_CONNECTOR_LEFT local [W-D,W-CPT] → world [CPT,D]; RIGHT local [CPT,D] → world [W-D,W-CPT].
    const leftConnectorPoseOk = Boolean(
      leftConnector
      && leftConnector.x0 >= cpt - 0.01
      && leftConnector.x1 <= depth + 0.01
      && Math.abs(leftConnector.y1 - depth) <= 0.01
      && Math.abs(leftConnector.y0 - (depth - cpt)) <= 0.01
    );
    const rightConnectorPoseOk = Boolean(
      rightConnector
      && rightConnector.x0 >= totalW - depth - 0.01
      && rightConnector.x1 <= totalW - cpt + 0.01
      && Math.abs(rightConnector.y1 - depth) <= 0.01
      && Math.abs(rightConnector.y0 - (depth - cpt)) <= 0.01
    );
    const cornerClosureOk = Boolean(
      backOwnsCorners
      && outerLeftD && outerRightD
      && close(outerLeftD.x0, 0) && close(outerLeftD.x1, cpt)
      && close(outerRightD.x0, totalW - cpt) && close(outerRightD.x1, totalW)
      && leftConnectorPoseOk
      && rightConnectorPoseOk
      && leftSideDivider && rightSideDivider
      && close(leftSideDivider.y0, depth)
      && close(rightSideDivider.y0, depth)
      && backT3World
      && close(backT3World.x0, 0) && close(backT3World.x1, totalW)
      && cornerFronts.length === 0
      && connectorContactOk
    );
    audit.push({
      id: "back_corner_closure",
      kind: "touch",
      ok: cornerClosureOk,
      detail: cornerClosureOk
        ? "Each BACK corner is closed by outer edge divider, connector, full-width BP/T3, and the side rear divider at y=D."
        : "BACK corner closure failed: need outer edge dividers, connectors in both D×D cells, full-width BP/T3, side rear dividers at y=D, and no function fronts in corners.",
    });
    const connectorRects = t3Grooves.map((feature) => {
      const row = feature as Record<string, unknown>;
      const x = row.x as number[];
      const y = row.y as number[];
      return { x0: x[0]!, x1: x[1]!, y0: y[0]!, y1: y[1]! };
    });
    const ledRects = (backRunResult?.features || [])
      .filter((feature) => (feature as Record<string, unknown>).type === "t3_groove")
      .flatMap((feature) => {
        const row = feature as Record<string, unknown>;
        return [row.main, ...((row.branches as unknown[]) || [])]
          .filter((segment): segment is { x0: number; x1: number; y0: number; y1: number } => (
            Boolean(segment) && typeof segment === "object"
          ));
      });
    const connectorLedOverlap = connectorRects.some((connector) => (
      ledRects.some((led) => featureRectOverlapArea(connector, led) > 0.01)
    ));
    audit.push({
      id: "back_t3_feature_clearance",
      kind: "no_overlap",
      ok: !connectorLedOverlap,
      detail: connectorLedOverlap
        ? "A BACK connector through-groove overlaps an LED groove on T3."
        : "BACK connector through-grooves preserve material around all LED segments.",
    });
    const backLed = (backRunResult?.features || []).find((feature) => (
      (feature as Record<string, unknown>).type === "t3_groove"
    )) as Record<string, unknown> | undefined;
    const backLedMain = backLed?.main as { x0?: number; x1?: number } | undefined;
    const backRearNotch = style1RearNotchShiftMm(baseParams ?? {});
    const backRunEntry = runs.find((entry) => entry.id === "BACK");
    const expectedBackLedInset = depth - fpt - (baseParams?.featureWidth ?? 15) - backRearNotch - SIDE_LED_PAST_BACK_T2_MM;
    const backLedExtentOk = !backLedMain || (
      close(Number(backLedMain.x0), expectedBackLedInset)
      && close(Number(backLedMain.x1), (backRunEntry?.cabinetWidth ?? 0) - expectedBackLedInset)
      && !(backRunResult?.features || []).some((feature) => (
        (feature as Record<string, unknown>).role === "u_corner_continuation"
      ))
    );
    audit.push({
      id: "back_led_middle_extent",
      kind: "dimension",
      ok: backLedExtentOk,
      detail: backLedExtentOk
        ? "BACK LED is limited to the middle span, 10 mm past each side T2."
        : "BACK LED must stop 10 mm past each side T2 and have no corner continuation.",
    });
    const backT3 = backRunResult?.boards.find((board) => board.id === "T3");
    const profileXs = new Set(
      ((backT3?.profileVector || []) as Array<{ x?: number }>).map((point) => Number(point.x)),
    );
    const notchRanges = (backRunResult?.features || [])
      .map((feature) => (feature as Record<string, unknown>).t3_notch as { x?: number[] } | undefined)
      .filter((notch): notch is { x: number[] } => Array.isArray(notch?.x) && notch.x.length === 2);
    const notchProfileOk = notchRanges.length > 0 && notchRanges.every((notch) => (
      profileXs.has(Number(notch.x[0])) && profileXs.has(Number(notch.x[1]))
    ));
    audit.push({
      id: "back_t3_notch_profile",
      kind: "dimension",
      ok: notchProfileOk,
      detail: notchProfileOk
        ? `BACK.T3 profile contains all ${notchRanges.length} divider notch ranges.`
        : "BACK.T3 profile is missing one or more divider notch ranges.",
    });

    const world = (id: string) => boards.find((board) => board.id === id);
    const leftT1 = world("LEFT.T1");
    const leftT2 = world("LEFT.T2");
    const backT1 = world("BACK.T1");
    const backT2 = world("BACK.T2");
    const rightT1 = world("RIGHT.T1");
    const rightT2 = world("RIGHT.T2");
    const rearNotch = style1RearNotchShiftMm(runs[0]?.result.params ?? {});
    const leftRun = runs.find((entry) => entry.id === "LEFT");
    const rightRun = runs.find((entry) => entry.id === "RIGHT");
    const backRun = runs.find((entry) => entry.id === "BACK");
    // Contact contracts must use final Adapter XY (after TCH-1), not raw generator world.
    const final = (board: UShapeWorldBoard | undefined, runId: UShapeRunId) => {
      if (!board) return null;
      const rot = runs.find((entry) => entry.id === runId)?.transform.rotationDeg ?? 0;
      return finalTopWorldBBox(board, rot, rearNotch);
    };
    const fLeftT1 = final(leftT1, "LEFT");
    const fLeftT2 = final(leftT2, "LEFT");
    const fBackT1 = final(backT1, "BACK");
    const fBackT2 = final(backT2, "BACK");
    const fRightT1 = final(rightT1, "RIGHT");
    const fRightT2 = final(rightT2, "RIGHT");
    const topContactsOk = Boolean(
      fLeftT1 && fLeftT2 && fBackT1 && fBackT2 && fRightT1 && fRightT2
      && close(fLeftT1.y0, fBackT2.y1)
      && close(fRightT1.y0, fBackT2.y1)
      && close(fLeftT2.y0, fBackT2.y1)
      && close(fRightT2.y0, fBackT2.y1)
      && close(fLeftT1.x1, fBackT1.x0)
      && close(fRightT1.x0, fBackT1.x1)
    );
    audit.push({
      id: "style1_top_contacts",
      kind: "touch",
      ok: topContactsOk,
      detail: topContactsOk
        ? `SIDE T1/T2 butt final BACK.T2; BACK T1/T2 keep Style-1 TCH-1 notch seating; shortened BACK.T1 fits between SIDE T1 faces (${rearNotch} mm).`
        : "Style 1 T1/T2 corner contact contract is not satisfied after final Adapter pose.",
    });

    const leftT1Len = leftT1 ? leftT1.y1 - leftT1.y0 : 0;
    const rightT1Len = rightT1 ? rightT1.y1 - rightT1.y0 : 0;
    const leftT2Len = leftT2 ? leftT2.y1 - leftT2.y0 : 0;
    const rightT2Len = rightT2 ? rightT2.y1 - rightT2.y0 : 0;
    const backT1Len = backT1 ? backT1.x1 - backT1.x0 : 0;
    const backT2Len = backT2 ? backT2.x1 - backT2.x0 : 0;
    const expectLeftT1 = (leftRun?.cabinetWidth ?? 0) + fpt + rearNotch;
    const expectRightT1 = (rightRun?.cabinetWidth ?? 0) + fpt + rearNotch;
    const expectSideT2Left = (leftRun?.cabinetWidth ?? 0) + fpt + rearNotch;
    const expectSideT2Right = (rightRun?.cabinetWidth ?? 0) + fpt + rearNotch;
    const expectBackT1 = (backRun?.cabinetWidth ?? 0) - 2 * depth + 2 * rearNotch;
    const expectBackT2 = backRun?.cabinetWidth ?? 0;
    const dimOk = Boolean(
      close(leftT1Len, expectLeftT1)
      && close(rightT1Len, expectRightT1)
      && close(leftT2Len, expectSideT2Left)
      && close(rightT2Len, expectSideT2Right)
      && close(backT1Len, expectBackT1)
      && close(backT2Len, expectBackT2)
      && leftT1 && rightT1 && backT1 && backT2
      && close(leftT1.x1 - leftT1.x0, fpt)
      && close(rightT1.x1 - rightT1.x0, fpt)
      && close(backT1.y1 - backT1.y0, fpt)
    );
    audit.push({
      id: "style1_top_dimensions",
      kind: "dimension",
      ok: dimOk,
      detail: dimOk
        ? `Top lengths OK (side=${expectLeftT1}/${expectRightT1}, BACK.T1=${expectBackT1}, BACK.T2=${expectBackT2}).`
        : `T1/T2 length mismatch: L.T1=${leftT1Len}/${expectLeftT1}, R.T1=${rightT1Len}/${expectRightT1}, L.T2=${leftT2Len}/${expectSideT2Left}, R.T2=${rightT2Len}/${expectSideT2Right}, B.T1=${backT1Len}/${expectBackT1}, B.T2=${backT2Len}/${expectBackT2}.`,
    });
  }

  for (const run of runs) {
    const boardIds = new Set(run.result.boards.map((board) => board.id));
    const failures: string[] = [];
    for (const rawFeature of run.result.features) {
      if (!rawFeature || typeof rawFeature !== "object") continue;
      const feature = rawFeature as Record<string, unknown>;
      const type = String(feature.type || "");
      if ((type === "rangehood_group" || type.startsWith("rangehood_")) && run.id === "BACK") {
        failures.push(`${String(feature.id || type)}: rangehood is forbidden on BACK (corners)`);
      }
      if ((type === "rangehood_group" || type.startsWith("rangehood_")) && feature.role === "u_corner_continuation") {
        failures.push(`${String(feature.id || type)}: rangehood must not use corner continuation`);
      }
      const explicitTarget = String(feature.targetBoardId || "");
      if (explicitTarget && !boardIds.has(explicitTarget)) {
        failures.push(`${String(feature.id || type)}: missing target ${explicitTarget}`);
      }
      if (type === "u_connector_bp_groove" && explicitTarget !== "BP") {
        failures.push(`${String(feature.id || type)}: BP groove targets ${explicitTarget || "nothing"}`);
      }
      if (type === "u_connector_t3_through_groove" && explicitTarget !== "T3") {
        failures.push(`${String(feature.id || type)}: T3 groove targets ${explicitTarget || "nothing"}`);
      }
      if (type === "t3_groove" && explicitTarget !== "T3") {
        failures.push(`${String(feature.id || type)}: LED groove targets ${explicitTarget || "nothing"}`);
      }
      if (feature.purpose === "hinge" && !boardIds.has(String(feature.boardId || ""))) {
        failures.push(`${String(feature.id || "hinge")}: hinge target is outside this run`);
      }
    }
    const notchRanges = (run.result.features as Array<Record<string, unknown>>)
      .map((feature) => (feature.t3_notch as { x?: number[]; y?: number[] } | undefined))
      .filter((notch): notch is { x: number[]; y: number[] } => (
        Array.isArray(notch?.x) && Array.isArray(notch?.y)
      ));
    const ledBranches = (run.result.features as Array<Record<string, unknown>>)
      .filter((feature) => feature.type === "t3_groove")
      .flatMap((feature) => (feature.branches as Array<{ x0: number; x1: number; y0: number; y1: number }>) || []);
    const branchNotchFailures = ledBranches.flatMap((branch, branchIndex) => (
      notchRanges.flatMap((notch) => {
        const yOverlap = Math.max(0, Math.min(branch.y1, notch.y[1]!) - Math.max(branch.y0, notch.y[0]!));
        const xGap = Math.max(0, Math.max(notch.x[0]! - branch.x1, branch.x0 - notch.x[1]!));
        return yOverlap > 0 && xGap < LED_BRANCH_NOTCH_CLEARANCE_MM - 0.01
          ? [`branch${branchIndex + 1} gap ${xGap.toFixed(2)} mm to ${String((notch as Record<string, unknown>).id || "divider notch")}`]
          : [];
      })
    ));
    audit.push({
      id: `${run.id.toLowerCase()}_led_branch_notch_clearance`,
      kind: "no_overlap",
      ok: branchNotchFailures.length === 0,
      detail: branchNotchFailures.length === 0
        ? `All T3 LED branches clear divider notches by ${LED_BRANCH_NOTCH_CLEARANCE_MM} mm.`
        : branchNotchFailures.join("; "),
    });
    audit.push({
      id: `${run.id.toLowerCase()}_cut_target_isolation`,
      kind: "no_overlap",
      ok: failures.length === 0,
      detail: failures.length === 0
        ? `All ${run.id} cuts resolve only to boards inside the ${run.id} run component.`
        : failures.join("; "),
    });

    const rangehoodFeatures = (run.result.features as Array<Record<string, unknown>>)
      .filter((feature) => {
        const type = String(feature.type || "");
        return type === "rangehood_group" || type.startsWith("rangehood_");
      });
    const rghdBoards = run.result.boards.filter((board) => String(board.id || "").startsWith("RGHD_"));
    if (run.id === "BACK") {
      audit.push({
        id: "back_rangehood_forbidden",
        kind: "no_overlap",
        ok: rangehoodFeatures.length === 0 && rghdBoards.length === 0,
        detail: rangehoodFeatures.length === 0 && rghdBoards.length === 0
          ? "BACK has no rangehood (corners stay clear)."
          : "BACK must not host rangehood boards or features.",
      });
    } else if (rangehoodFeatures.length > 0 || rghdBoards.length > 0) {
      // Side-arm hood must stay outside reserved/corner band (RGHD_TOP local X).
      const top = rghdBoards.find((board) => board.id === "RGHD_TOP");
      const reservedStart = run.reservedStart;
      const reservedEnd = run.id === "LEFT" ? 0 : sideClearance + fpt;
      const runWidth = run.cabinetWidth;
      const clearOfCorner = Boolean(
        top
        && top.x0 >= reservedStart - 0.5
        && top.x1 <= runWidth - reservedEnd + 0.5
        && rangehoodFeatures.some((feature) => feature.type === "rangehood_group")
      );
      audit.push({
        id: `${run.id.toLowerCase()}_side_rangehood_outside_corner`,
        kind: "dimension",
        ok: clearOfCorner,
        detail: clearOfCorner
          ? `${run.id} NCE rangehood stays in the usable span outside the BACK corner reserved band.`
          : `${run.id} rangehood must stay outside reserved/corner (x>=${reservedStart}, x<=${runWidth - reservedEnd}).`,
      });
    }
  }
  return audit;
}

function escapeXml(value: string): string {
  return value.replace(/[<>&"']/g, (char) => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;", "\"": "&quot;", "'": "&apos;" }[char]!));
}

function planSvg(totalWidth: number, leftLength: number, rightLength: number, depth: number, runs: UShapeRunResult[]): string {
  const maxY = Math.max(leftLength, rightLength);
  const pad = 35;
  const viewW = totalWidth + pad * 2;
  const viewH = maxY + pad * 2;
  const rects = [
    { id: "LEFT", x: 0, y: depth, w: depth, h: Math.max(0, leftLength - depth) },
    { id: "BACK", x: 0, y: 0, w: totalWidth, h: depth },
    { id: "RIGHT", x: totalWidth - depth, y: depth, w: depth, h: Math.max(0, rightLength - depth) },
  ];
  return [
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${-pad} ${-pad} ${viewW} ${viewH}" role="img" aria-label="U Shape OHC plan">`,
    `<g fill="none" stroke="currentColor" stroke-width="3">`,
    ...rects.map((rect) => `<rect data-run-id="${rect.id}" x="${rect.x}" y="${rect.y}" width="${rect.w}" height="${rect.h}"/>`),
    `</g>`,
    ...rects.map((rect) => `<text x="${rect.x + rect.w / 2}" y="${rect.y + Math.min(rect.h / 2, 30)}" text-anchor="middle" font-size="24">${escapeXml(rect.id)}</text>`),
    ...runs.flatMap((run) => run.result.debug.dividerCenterlines.map((x) => {
      const [x0, y0] = transformXY(x, 0, run.transform);
      const [x1, y1] = transformXY(x, depth, run.transform);
      return `<line x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}" stroke="currentColor" stroke-width="1"/>`;
    })),
    `</svg>`,
  ].join("");
}

export function generateUShapeOverheadCabinet(raw: UShapeOverheadParams): UShapeOverheadResult {
  const errors: string[] = [];
  const warnings: string[] = [];
  const totalWidth = finite(raw.totalWidth, 2275);
  const leftArmLength = finite(raw.leftArmLength, 1500);
  const rightArmLength = finite(raw.rightArmLength, 1500);
  const cabinetDepth = finite(raw.cabinetDepth, DEFAULT_DEPTH);
  const cabinetHeight = finite(raw.cabinetHeight, DEFAULT_HEIGHT);
  const sideClearance = finite(raw.sideClearance, DEFAULT_SIDE_CLEARANCE);
  const featureWidth = finite(raw.featureWidth, DEFAULT_CPT);
  const frontPanelThickness = finite(raw.frontPanelThickness, DEFAULT_FPT);
  const topClearanceHeight = finite(raw.topClearanceHeight, 40);
  const clearance = finite(raw.clearance, DEFAULT_CLEARANCE);
  const backCabinetWidth = totalWidth;
  const backFunctionalSpan = totalWidth - 2 * cabinetDepth;
  const backClearanceWidth = sideClearance + frontPanelThickness;
  const backUsable = backFunctionalSpan - 2 * backClearanceWidth;
  const sideReservedWidth = frontPanelThickness + sideClearance;
  const leftRunWidth = leftArmLength - cabinetDepth;
  const rightRunWidth = rightArmLength - cabinetDepth;
  const leftUsable = leftRunWidth - sideReservedWidth;
  const rightUsable = rightRunWidth - sideReservedWidth;
  const resolvedColor = color(raw);

  if (raw.style && raw.style !== "style_1") errors.push("U Shape OHC v1 supports style_1 only.");
  if (!(totalWidth > 2 * cabinetDepth)) errors.push("totalWidth must exceed 2 x cabinetDepth.");
  if (!(backUsable >= 120)) errors.push("BACK must retain at least 120 mm usable width between its locked corner/clearance regions.");
  if (!(leftUsable >= 120)) errors.push("LEFT must retain at least 120 mm usable width after the BACK corner, front thickness and clearance.");
  if (!(rightUsable >= 120)) errors.push("RIGHT must retain at least 120 mm usable width after the BACK corner, front thickness and clearance.");
  if (!(cabinetHeight > topClearanceHeight + 3 * featureWidth)) errors.push("cabinetHeight is too small for BP, connector and Style 1 top structure.");
  if (!(cabinetDepth > featureWidth + 30)) errors.push("cabinetDepth is too small for the connector tongue.");
  const leftLedEnabled = raw.runLedGroove?.LEFT ?? raw.ledGroove !== false;
  const rightLedEnabled = raw.runLedGroove?.RIGHT ?? raw.ledGroove !== false;
  if (leftLedEnabled && leftRunWidth <= SIDE_LED_BRANCH_INSET_MM * 2 + 1) {
    errors.push("LEFT side run is too short for two 80 mm LED branch insets.");
  }
  if (rightLedEnabled && rightRunWidth <= SIDE_LED_BRANCH_INSET_MM * 2 + 1) {
    errors.push("RIGHT side run is too short for two 80 mm LED branch insets.");
  }

  const rangehoodPreset = String(raw.rangehoodPreset || "NCE");
  const rangehoodClearHeight = Math.max(1, finite(raw.rangehoodClearHeight, 75));
  const rangehoodAlignment = raw.rangehoodAlignment === "right" ? "right" as const : "left" as const;
  const rangehoodEdgeOffsetX = Math.max(40, finite(raw.rangehoodEdgeOffsetX, 40));

  const common: Omit<OverheadCabinetParams, "cabinetWidth" | "zones"> = {
    style: "style_1",
    cabinetDepth,
    cabinetHeight,
    topClearanceHeight,
    frontPanelThickness,
    clearance,
    featureWidth,
    bottomThickness: finite(raw.bottomThickness, featureWidth),
    dividerTongueHeight: finite(raw.dividerTongueHeight, featureWidth / 2 - 0.5),
    routerDiameter: finite(raw.routerDiameter, 6),
    hingeHoleDiameter: finite(raw.hingeHoleDiameter, 35),
    hingeHoleDepth: finite(raw.hingeHoleDepth, 12),
    hingeHoleFromTop: finite(raw.hingeHoleFromTop, 22.5),
    hingeHoleFromSide: finite(raw.hingeHoleFromSide, 100),
    carcassColor: resolvedColor.carcassColor,
    carcassColorName: resolvedColor.carcassColorName,
    ledGroove: raw.ledGroove !== false,
    rangehoodPreset,
    rangehoodClearHeight,
    rangehoodAlignment,
    rangehoodEdgeOffsetX,
  };

  const normalizedByRun = {
    LEFT: normalizeZones(raw.zones?.LEFT, Math.max(0, leftUsable), "LEFT", warnings),
    BACK: normalizeZones(raw.zones?.BACK, Math.max(0, backUsable), "BACK", warnings),
    RIGHT: normalizeZones(raw.zones?.RIGHT, Math.max(0, rightUsable), "RIGHT", warnings),
  };
  if (zoneHasRangehood(normalizedByRun.BACK)) {
    warnings.push("Rangehood on BACK was converted to up_flap — hoods are LEFT/RIGHT only and never enter corners.");
    normalizedByRun.BACK = normalizedByRun.BACK.map((zone) => (
      zone.type === "rangehood_flap" ? { ...zone, type: "up_flap" } : zone
    ));
  }
  const runLed = (id: UShapeRunId) => raw.runLedGroove?.[id] ?? common.ledGroove;

  const runOptions: UShapeRunBuildOptions[] = [
    {
      id: "LEFT",
      width: leftRunWidth,
      reservedStart: sideReservedWidth,
      endClearance: 0,
      zones: normalizedByRun.LEFT,
      transform: { rotationDeg: 90, translateX: cabinetDepth, translateY: cabinetDepth },
      overheadParams: { ...common, ledGroove: runLed("LEFT") },
    },
    {
      id: "BACK",
      width: backCabinetWidth,
      reservedStart: cabinetDepth + backClearanceWidth,
      endClearance: cabinetDepth + backClearanceWidth,
      zones: normalizedByRun.BACK,
      transform: { rotationDeg: 180, translateX: totalWidth, translateY: cabinetDepth },
      overheadParams: { ...common, ledGroove: runLed("BACK") },
    },
    {
      id: "RIGHT",
      width: rightRunWidth,
      reservedStart: 0,
      endClearance: sideReservedWidth,
      zones: normalizedByRun.RIGHT,
      transform: { rotationDeg: -90, translateX: totalWidth - cabinetDepth, translateY: rightArmLength },
      overheadParams: { ...common, ledGroove: runLed("RIGHT") },
    },
  ];

  const runs = errors.length === 0
    ? runOptions.map((options) => buildRun(options, options.zones, sideClearance, backClearanceWidth))
    : [];
  if (runs.length === 3) {
    adjustBackLedExtent(runs);
  }
  for (const run of runs) {
    errors.push(...run.result.validation.errors.map((error) => `${run.id}: ${error}`));
    warnings.push(...run.result.validation.warnings.map((warning) => `${run.id}: ${warning}`));
  }
  const worldBoards = runs.flatMap((run) => run.result.boards.map((board) => worldBoard(run, board)));
  const audit = auditGeometry(runs, worldBoards, sideClearance);
  for (const row of audit) {
    if (!row.ok) errors.push(`${row.id}: ${row.detail}`);
  }

  return {
    meta: {
      module: "u_shape_overhead",
      style: "style_1",
      phase: "u_shape_geometry_v2",
      geometryRevision: "back_owns_corners_v5",
      cornerOwnership: "BACK",
    },
    params: {
      totalWidth,
      leftArmLength,
      rightArmLength,
      cabinetDepth,
      cabinetHeight,
      sideClearance,
      style: "style_1",
      topClearanceHeight,
      frontPanelThickness,
      clearance,
      featureWidth,
      carcassColor: resolvedColor.carcassColor,
      carcassColorName: resolvedColor.carcassColorName,
      ledGroove: common.ledGroove !== false,
      rangehoodPreset,
      rangehoodClearHeight,
      rangehoodAlignment,
      rangehoodEdgeOffsetX,
      geometryRevision: "back_owns_corners_v5",
      backCabinetWidth,
      backFunctionalSpan,
      backClearanceWidth,
    },
    runs,
    worldBoards,
    validation: { errors, warnings },
    audit,
    debug: {
      planBounds: { x0: 0, x1: totalWidth, y0: 0, y1: Math.max(leftArmLength, rightArmLength) },
      planSvg: planSvg(totalWidth, leftArmLength, rightArmLength, cabinetDepth, runs),
    },
  };
}

export * from "./types.ts";
