import {
  DIVIDER_THICKNESS_MM,
  DEFAULT_ROUTER_DIAMETER_MM,
  boardXRange,
  calculateOverheadGeometry,
  clampRange,
  dividerSideTrimmedOutlinePoints,
  type OverheadCabinetInputs,
  type OverheadLegacyGeometry,
  type OutlinePoint,
} from "./geometry.ts";
import { generateOHCSvgPreview } from "./svgPreview.ts";
import type { Board, OverheadCabinetParams, OverheadCabinetResult } from "./types.ts";
import { relationshipDeclarationsForBoards } from "./relationshipDeclarations.ts";

export * from "./geometry.ts";
export * from "./svgPreview.ts";

/** Match General Tall / Kitchen / Fridge LED insert groove (mm). */
const LED_GROOVE_WIDTH = 14.5;
const LED_GROOVE_DEPTH = 6.5;
/**
 * Clear strip from T3 front edge to the near wall of the main channel.
 * Shared with GT / Kitchen / Fridge: 18 mm land → centerline 25.25.
 */
const LED_GROOVE_FRONT_LAND_MM = 18;
const LED_GROOVE_FRONT_OFFSET = LED_GROOVE_FRONT_LAND_MM + LED_GROOVE_WIDTH / 2;
const LED_GROOVE_BRANCH_END_INSET = 80;
const T3_LED_BOARD_DEPTH_FALLBACK = 90;

const RANGEHOOD_PRESET_NCE = "NCE";
const RANGEHOOD_CUTOUT_WIDTH_MM = 555;
const RANGEHOOD_CUTOUT_DEPTH_MM = 285;
const RANGEHOOD_MIN_EDGE_MM = 40;
const RANGEHOOD_DEFAULT_CLEAR_HEIGHT_MM = 75;

interface ResolvedZone {
  id: string;
  type: string;
  width: number;
  x0: number;
  x1: number;
}

interface RangehoodGroup {
  firstZoneIndex: number;
  lastZoneIndex: number;
  leftDividerIndex: number;
  rightDividerIndex: number;
  internalDividerIndices: number[];
  x0: number;
  x1: number;
  clearWidth: number;
  clearHeight: number;
  alignment: "left" | "right";
  edgeOffsetX: number;
}

function toInputs(params: OverheadCabinetParams): OverheadCabinetInputs {
  return {
    cabinetWidth: Number(params.cabinetWidth),
    cabinetDepth: Number(params.cabinetDepth),
    cabinetHeight: params.cabinetHeight,
    style: params.style,
    topClearanceHeight: params.topClearanceHeight ?? 40,
    frontPanelThickness: params.frontPanelThickness ?? 16,
    clearance: params.clearance ?? 2.5,
    hingeHoleDiameter: params.hingeHoleDiameter ?? 35,
    hingeHoleDepth: params.hingeHoleDepth ?? 12,
    hingeHoleFromTop: params.hingeHoleFromTop ?? 22.5,
    hingeHoleFromSide: params.hingeHoleFromSide ?? 100,
    bottomThickness: params.featureWidth ?? params.bottomThickness ?? DIVIDER_THICKNESS_MM,
    dividerTongueHeight: params.dividerTongueHeight ?? (params.featureWidth ?? DIVIDER_THICKNESS_MM) / 2 - 0.5,
    routerDiameter: params.routerDiameter ?? DEFAULT_ROUTER_DIAMETER_MM,
    featureWidth: params.featureWidth ?? DIVIDER_THICKNESS_MM,
    internalDividerCenterlines: Array.isArray(params.internalDividerCenterlines)
      ? params.internalDividerCenterlines.map(Number)
      : [],
    zones: params.zones,
  };
}

function resolvedZones(params: OverheadCabinetParams): ResolvedZone[] {
  const zones = Array.isArray(params.zones) ? params.zones : [];
  let x = 0;
  return zones.map((zone, index) => {
    const width = Number(zone.width) || 0;
    const resolved = {
      id: String(zone.id || `zone-${index + 1}`),
      type: String(zone.type || "up_flap"),
      width,
      x0: x,
      x1: x + width,
    };
    x += width;
    return resolved;
  });
}

function resolveRangehoodGroup(
  params: OverheadCabinetParams,
  geometry: OverheadLegacyGeometry,
  validation: { errors: string[]; warnings: string[] },
): RangehoodGroup | null {
  const zones = resolvedZones(params);
  const indices = zones
    .map((zone, index) => zone.type === "rangehood_flap" ? index : -1)
    .filter((index) => index >= 0);
  if (indices.length === 0) return null;

  const firstZoneIndex = indices[0]!;
  const lastZoneIndex = indices[indices.length - 1]!;
  if (indices.some((index, offset) => index !== firstZoneIndex + offset)) {
    validation.errors.push("Only one contiguous rangehood group is allowed per overhead cabinet.");
    return null;
  }

  const preset = String(params.rangehoodPreset || RANGEHOOD_PRESET_NCE).toUpperCase();
  if (preset !== RANGEHOOD_PRESET_NCE) {
    validation.errors.push(`Unsupported rangehood preset: ${preset}.`);
  }
  const alignmentRaw = String(params.rangehoodAlignment || "left").toLowerCase();
  if (alignmentRaw !== "left" && alignmentRaw !== "right") {
    validation.errors.push("rangehoodAlignment must be left or right.");
  }
  const alignment: "left" | "right" = alignmentRaw === "right" ? "right" : "left";
  const edgeOffsetX = Number(params.rangehoodEdgeOffsetX ?? RANGEHOOD_MIN_EDGE_MM);
  const clearHeight = Number(params.rangehoodClearHeight ?? RANGEHOOD_DEFAULT_CLEAR_HEIGHT_MM);
  const cpt = geometry.manufacturing.FGw;
  const leftDivider = geometry.divider_features[firstZoneIndex];
  const rightDivider = geometry.divider_features[lastZoneIndex + 1];
  if (!leftDivider || !rightDivider) {
    validation.errors.push("Rangehood group boundary dividers could not be resolved.");
    return null;
  }
  const x0 = leftDivider.XDi + cpt / 2;
  const x1 = rightDivider.XDi - cpt / 2;
  const clearWidth = x1 - x0;

  if (!Number.isFinite(clearHeight) || clearHeight <= 0) {
    validation.errors.push("rangehoodClearHeight must be a positive number.");
  }
  if (!Number.isFinite(edgeOffsetX) || edgeOffsetX < RANGEHOOD_MIN_EDGE_MM) {
    validation.errors.push(`NCE rangehood edge offset must be at least ${RANGEHOOD_MIN_EDGE_MM} mm.`);
  }
  if (geometry.cabinet.Cd < RANGEHOOD_CUTOUT_DEPTH_MM + RANGEHOOD_MIN_EDGE_MM * 2) {
    validation.errors.push(
      `NCE rangehood requires BP depth >= ${RANGEHOOD_CUTOUT_DEPTH_MM + RANGEHOOD_MIN_EDGE_MM * 2} mm.`,
    );
  }
  if (clearWidth < RANGEHOOD_CUTOUT_WIDTH_MM + RANGEHOOD_MIN_EDGE_MM * 2) {
    validation.errors.push(
      `NCE rangehood requires clear width between outer D inner faces >= ${RANGEHOOD_CUTOUT_WIDTH_MM + RANGEHOOD_MIN_EDGE_MM * 2} mm.`,
    );
  }
  if (
    Number.isFinite(edgeOffsetX) &&
    clearWidth - RANGEHOOD_CUTOUT_WIDTH_MM - edgeOffsetX < RANGEHOOD_MIN_EDGE_MM
  ) {
    validation.errors.push("NCE rangehood cutout must leave at least 40 mm on the opposite X side.");
  }
  const cabinetHeight = Number(geometry.cabinet.Ch ?? 0);
  const functionalTop = cabinetHeight - geometry.manufacturing.TCH;
  if (3 * cpt + clearHeight > functionalTop) {
    validation.errors.push("Rangehood insert collides with the overhead top-clearance structure.");
  }

  return {
    firstZoneIndex,
    lastZoneIndex,
    leftDividerIndex: firstZoneIndex,
    rightDividerIndex: lastZoneIndex + 1,
    internalDividerIndices: Array.from(
      { length: Math.max(0, lastZoneIndex - firstZoneIndex) },
      (_, offset) => firstZoneIndex + offset + 1,
    ),
    x0,
    x1,
    clearWidth,
    clearHeight,
    alignment,
    edgeOffsetX,
  };
}

function rangehoodTopProfile(clearWidth: number, cabinetDepth: number, tongueProjection: number): Array<{ x: number; y: number }> {
  const y0 = cabinetDepth / 3 + 5;
  const y1 = cabinetDepth * 2 / 3 - 5;
  const rightMain = tongueProjection + clearWidth;
  const total = rightMain + tongueProjection;
  return [
    { x: tongueProjection, y: 0 },
    { x: rightMain, y: 0 },
    { x: rightMain, y: y0 },
    { x: total, y: y0 },
    { x: total, y: y1 },
    { x: rightMain, y: y1 },
    { x: rightMain, y: cabinetDepth },
    { x: tongueProjection, y: cabinetDepth },
    { x: tongueProjection, y: y1 },
    { x: 0, y: y1 },
    { x: 0, y: y0 },
    { x: tongueProjection, y: y0 },
    { x: tongueProjection, y: 0 },
  ];
}

function internalRangehoodDividerProfile(
  inputs: OverheadCabinetInputs,
  clearHeight: number,
): OutlinePoint[] {
  const cpt = inputs.featureWidth ?? DIVIDER_THICKNESS_MM;
  const effectiveCabinetHeight = (inputs.cabinetHeight ?? 0) - cpt - clearHeight;
  return dividerSideTrimmedOutlinePoints(
    inputs.cabinetDepth,
    effectiveCabinetHeight,
    cpt,
    inputs.dividerTongueHeight,
    inputs.routerDiameter,
    cpt + 1,
    inputs.topClearanceHeight,
    inputs.style === "style_2" ? "style_2" : "style_1",
    inputs.frontPanelThickness,
  );
}

function legacyToBoards(
  geometry: OverheadLegacyGeometry,
  inputs: OverheadCabinetInputs,
  rangehood: RangehoodGroup | null = null,
): Board[] {
  const { cabinetWidth, cabinetDepth, cabinetHeight, bottomThickness, featureWidth, topClearanceHeight, frontPanelThickness } = {
    cabinetWidth: inputs.cabinetWidth,
    cabinetDepth: inputs.cabinetDepth,
    cabinetHeight: inputs.cabinetHeight,
    bottomThickness: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
    featureWidth: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
    topClearanceHeight: inputs.topClearanceHeight ?? 40,
    frontPanelThickness: inputs.frontPanelThickness ?? 16,
  };

  const boards: Board[] = [
    {
      id: "BP",
      name: "Bottom Panel",
      category: "panel",
      boardType: "BP",
      materialThickness: bottomThickness,
      profilePlane: "XY",
      thicknessAxis: "Z",
      x0: 0,
      x1: cabinetWidth,
      y0: 0,
      y1: cabinetDepth,
      z0: 0,
      z1: bottomThickness,
      source: "overhead_geometry",
    },
  ];

  boards.push({
    id: "T1",
    name: "Top Front Rail T1",
    category: "rail",
    boardType: "T1",
    materialThickness: frontPanelThickness,
    profilePlane: "XZ",
    thicknessAxis: "Y",
    x0: 0,
    x1: cabinetWidth,
    y0: 0,
    y1: frontPanelThickness,
    z0: (cabinetHeight ?? topClearanceHeight) - topClearanceHeight,
    z1: cabinetHeight ?? topClearanceHeight,
    source: "overhead_geometry_v7",
  });

  boards.push({
    id: "T2",
    name: "Top Front Rail T2",
    category: "rail",
    boardType: "T2",
    materialThickness: featureWidth,
    profilePlane: "XZ",
    thicknessAxis: "Y",
    x0: 0,
    x1: cabinetWidth,
    y0: frontPanelThickness,
    y1: frontPanelThickness + featureWidth,
    z0: (cabinetHeight ?? topClearanceHeight) - topClearanceHeight,
    z1: cabinetHeight ?? topClearanceHeight,
    source: "overhead_geometry_v7",
  });

  if (geometry.trimmed_vectors.T3.length > 0) {
    boards.push({
      id: "T3",
      name: "Top Rear Panel",
      category: "panel",
      boardType: "T3",
      materialThickness: featureWidth,
      profilePlane: "XY",
      thicknessAxis: "Z",
      x0: 0,
      x1: cabinetWidth,
      y0: 0,
      y1: cabinetDepth,
      z0: cabinetHeight != null ? cabinetHeight - featureWidth : 0,
      z1: cabinetHeight ?? bottomThickness,
      source: "overhead_geometry",
      profileVector: geometry.trimmed_vectors.T3.map(([x, y]) => ({ x, y })),
    });
  }

  if (geometry.trimmed_vectors.T4.length > 0) {
    boards.push({
      id: "T4",
      name: "Top Front Panel",
      category: "panel",
      boardType: "T4",
      materialThickness: featureWidth,
      profilePlane: "XY",
      thicknessAxis: "Z",
      x0: 0,
      x1: cabinetWidth,
      y0: 0,
      y1: cabinetDepth,
      z0: cabinetHeight != null ? cabinetHeight - featureWidth : 0,
      z1: cabinetHeight ?? bottomThickness,
      source: "overhead_geometry",
      profileVector: geometry.trimmed_vectors.T4.map(([x, y]) => ({ x, y })),
    });
  }

  for (let dividerIndex = 0; dividerIndex < geometry.divider_features.length; dividerIndex += 1) {
    const feature = geometry.divider_features[dividerIndex]!;
    // Board solid thickness must be featureWidth (CPT), not the BP groove
    // slot width (CPT + clearance). Groove/notch features keep the wider
    // slot range; only the divider body uses boardXRange.
    const [x0, x1] = clampRange(boardXRange(feature.XDi, featureWidth), 0, cabinetWidth);
    // Dividers sit on the shifted bottom panel top at z = 2 * FGw. Fusion
    // postprocess used to apply this as a +2*FGw move; bake it into board Z.
    const isInternalRangehoodDivider = Boolean(rangehood?.internalDividerIndices.includes(dividerIndex));
    const dividerZ0 = isInternalRangehoodDivider
      ? featureWidth * 3 + (rangehood?.clearHeight ?? 0)
      : featureWidth * 2;
    const dividerTopZ = (cabinetHeight ?? bottomThickness + 1) + featureWidth;
    const dividerProfile = isInternalRangehoodDivider
      ? internalRangehoodDividerProfile(inputs, rangehood?.clearHeight ?? 0)
      : geometry.trimmed_vectors.DividerSide;
    boards.push({
      id: feature.id,
      name: `Divider ${feature.id}`,
      category: "divider",
      boardType: "divider",
      materialThickness: featureWidth,
      profilePlane: "YZ",
      thicknessAxis: "X",
      x0,
      x1,
      y0: 0,
      y1: cabinetDepth,
      z0: dividerZ0,
      z1: dividerTopZ,
      source: "overhead_geometry",
      cutProfileVector:
        dividerProfile.length > 0
          ? dividerProfile.map(([y, z]) => ({ y, z }))
          : undefined,
      profileFeatures: [
        ...(isInternalRangehoodDivider ? [] : [feature.bp_groove]),
        feature.divider_tongue,
        feature.t3_notch,
        feature.t4_notch,
      ],
      notes: isInternalRangehoodDivider
        ? ["Rangehood internal divider starts on RGHD_TOP; BP groove suppressed."]
        : undefined,
    });
  }

  if (rangehood) {
    const tongueProjection = featureWidth / 2 - 0.5;
    const bpTopZ = featureWidth * 2;
    const topBottomZ = bpTopZ + rangehood.clearHeight;
    const topX0 = rangehood.x0 - tongueProjection;
    const topX1 = rangehood.x1 + tongueProjection;
    boards.push({
      id: "RGHD_TOP",
      name: "Rangehood Top",
      category: "rangehood",
      boardType: "RGHD_TOP",
      materialThickness: featureWidth,
      profilePlane: "XY",
      thicknessAxis: "Z",
      x0: topX0,
      x1: topX1,
      y0: 0,
      y1: cabinetDepth,
      z0: topBottomZ,
      z1: topBottomZ + featureWidth,
      source: "overhead_rangehood",
      profileVector: rangehoodTopProfile(rangehood.clearWidth, cabinetDepth, tongueProjection),
      notes: ["NCE rangehood top with side tongues."],
    });
    boards.push({
      id: "RGHD_FRONT",
      name: "Rangehood Front",
      category: "rangehood",
      boardType: "RGHD_FRONT",
      materialThickness: featureWidth,
      profilePlane: "XZ",
      thicknessAxis: "Y",
      x0: rangehood.x0,
      x1: rangehood.x1,
      y0: 0,
      y1: featureWidth,
      z0: bpTopZ,
      z1: topBottomZ,
      source: "overhead_rangehood",
    });
    boards.push({
      id: "RGHD_BACK",
      name: "Rangehood Back",
      category: "rangehood",
      boardType: "RGHD_BACK",
      materialThickness: featureWidth,
      profilePlane: "XZ",
      thicknessAxis: "Y",
      x0: rangehood.x0,
      x1: rangehood.x1,
      y0: cabinetDepth - featureWidth,
      y1: cabinetDepth,
      z0: bpTopZ,
      z1: topBottomZ,
      source: "overhead_rangehood",
    });
  }

  for (const panel of geometry.front_panels) {
    boards.push({
      id: panel.id,
      name: `Front Panel ${panel.zoneIndex + 1}`,
      category: "front_panel",
      boardType: panel.type,
      materialThickness: panel.thickness,
      profilePlane: "XZ",
      thicknessAxis: "Y",
      x0: panel.x[0],
      x1: panel.x[1],
      y0: panel.y[0],
      y1: panel.y[1],
      z0: panel.z[0],
      z1: panel.z[1],
      source: "overhead_geometry_v7",
      profileVector: [
        { x: 0, z: 0 },
        { x: panel.width, z: 0 },
        { x: panel.width, z: panel.height },
        { x: 0, z: panel.height },
        { x: 0, z: 0 },
      ],
    });
  }

  return boards;
}

function generateRangehoodFeatures(
  geometry: OverheadLegacyGeometry,
  rangehood: RangehoodGroup | null,
): Array<Record<string, unknown>> {
  if (!rangehood) return [];
  const cpt = geometry.manufacturing.FGw;
  const depth = geometry.cabinet.Cd;
  const bpTopZ = cpt * 2;
  const grooveZ0 = bpTopZ + rangehood.clearHeight;
  const grooveY: [number, number] = [depth / 3, depth * 2 / 3];
  const cutoutY0 = (depth - RANGEHOOD_CUTOUT_DEPTH_MM) / 2;
  const cutoutX0 = rangehood.alignment === "left"
    ? rangehood.x0 + rangehood.edgeOffsetX
    : rangehood.x1 - rangehood.edgeOffsetX - RANGEHOOD_CUTOUT_WIDTH_MM;
  const cutoutX1 = cutoutX0 + RANGEHOOD_CUTOUT_WIDTH_MM;

  const features: Array<Record<string, unknown>> = [
    {
      id: "RGHD_GROUP",
      type: "rangehood_group",
      preset: RANGEHOOD_PRESET_NCE,
      firstZoneIndex: rangehood.firstZoneIndex,
      lastZoneIndex: rangehood.lastZoneIndex,
      clearWidth: rangehood.clearWidth,
      clearHeight: rangehood.clearHeight,
      alignment: rangehood.alignment,
      edgeOffsetX: rangehood.edgeOffsetX,
      boundaryDividerIds: [
        `D${rangehood.leftDividerIndex}`,
        `D${rangehood.rightDividerIndex}`,
      ],
      internalDividerIds: rangehood.internalDividerIndices.map((index) => `D${index}`),
    },
    {
      id: "BP_NCE_RANGEHOOD_CUTOUT",
      type: "rangehood_bp_cutout",
      targetBoardId: "BP",
      preset: RANGEHOOD_PRESET_NCE,
      through: true,
      shape: "rectangle",
      x: [cutoutX0, cutoutX1],
      y: [cutoutY0, cutoutY0 + RANGEHOOD_CUTOUT_DEPTH_MM],
      width: RANGEHOOD_CUTOUT_WIDTH_MM,
      depth: RANGEHOOD_CUTOUT_DEPTH_MM,
      alignment: rangehood.alignment,
      edgeOffsetX: rangehood.edgeOffsetX,
    },
    {
      id: `RGHD_D${rangehood.leftDividerIndex}_SIDE_GROOVE`,
      type: "rangehood_divider_side_groove",
      targetBoardId: `D${rangehood.leftDividerIndex}`,
      face: "+X",
      y: grooveY,
      z: [grooveZ0, grooveZ0 + cpt + 1],
      depth: cpt / 2,
      widthY: depth / 3,
    },
    {
      id: `RGHD_D${rangehood.rightDividerIndex}_SIDE_GROOVE`,
      type: "rangehood_divider_side_groove",
      targetBoardId: `D${rangehood.rightDividerIndex}`,
      face: "-X",
      y: grooveY,
      z: [grooveZ0, grooveZ0 + cpt + 1],
      depth: cpt / 2,
      widthY: depth / 3,
    },
  ];

  for (const dividerIndex of rangehood.internalDividerIndices) {
    const divider = geometry.divider_features[dividerIndex];
    if (!divider) continue;
    features.push({
      id: `RGHD_TOP_D${dividerIndex}_GROOVE`,
      type: "rangehood_top_divider_groove",
      targetBoardId: "RGHD_TOP",
      dividerBoardId: `D${dividerIndex}`,
      face: "top",
      x: [divider.XDi - (cpt + 1) / 2, divider.XDi + (cpt + 1) / 2],
      y: grooveY,
      depth: cpt / 2,
    });
  }
  return features;
}

function buildInsertBoardLedGroovePath(
  boardWidth: number,
  boardDepth: number,
  boardId: string,
  warnings: string[],
  frontOffset = LED_GROOVE_FRONT_OFFSET,
): {
  main: { x0: number; x1: number; y0: number; y1: number };
  branches: Array<{ x0: number; x1: number; y0: number; y1: number }>;
  branchLength: number;
} | null {
  const halfWidth = LED_GROOVE_WIDTH / 2;
  if (boardWidth <= LED_GROOVE_BRANCH_END_INSET * 2 + LED_GROOVE_WIDTH) {
    warnings.push(
      `${boardId} LED groove skipped: board width ${boardWidth.toFixed(1)} too narrow for 80 mm end insets.`,
    );
    return null;
  }
  const mainYCenter = frontOffset;
  const main = {
    x0: 0,
    x1: boardWidth,
    y0: mainYCenter - halfWidth,
    y1: mainYCenter + halfWidth,
  };
  if (main.y0 < -1e-6 || main.y1 > boardDepth + 1e-6) {
    warnings.push(
      `${boardId} LED groove skipped: main channel y=${main.y0.toFixed(2)}..${main.y1.toFixed(2)} leaves board depth ${boardDepth.toFixed(1)} (frontOffset=${frontOffset}).`,
    );
    return null;
  }
  const branchY0 = main.y1;
  const branchY1 = boardDepth;
  const branchLength = branchY1 - branchY0;
  if (branchLength <= 1e-6) {
    warnings.push(
      `${boardId} LED groove T-branches skipped: no remaining depth behind main channel (y=${branchY0.toFixed(2)}).`,
    );
    return null;
  }
  const branchCenters = [
    LED_GROOVE_BRANCH_END_INSET,
    boardWidth - LED_GROOVE_BRANCH_END_INSET,
  ];
  const branches = branchCenters.map((centerX) => ({
    x0: centerX - halfWidth,
    x1: centerX + halfWidth,
    y0: branchY0,
    y1: branchY1,
  }));
  return { main, branches, branchLength };
}

function t3LedBoardExtents(board: Board): { width: number; depth: number } {
  const width = board.x1 - board.x0;
  const profileYs = (board.profileVector || [])
    .map((point) => Number((point as { y?: number }).y))
    .filter((value) => Number.isFinite(value));
  if (profileYs.length >= 2) {
    return { width, depth: Math.max(...profileYs) - Math.min(...profileYs) };
  }
  // T3 board bbox is padded to cabinet depth; solid outline is ~90 mm.
  return {
    width,
    depth: Math.min(T3_LED_BOARD_DEPTH_FALLBACK, Math.max(0, board.y1 - board.y0)),
  };
}

function generateT3LedGrooveFeatures(
  boards: Board[],
  warnings: string[],
  params: OverheadCabinetParams,
): Array<Record<string, unknown>> {
  // Overhead Style 1/2 only changes divider front notches; gate on checkbox.
  if (params.ledGroove === false) return [];

  const t3 = boards.find((board) => board.id === "T3" && board.boardType === "T3");
  if (!t3) {
    warnings.push("T3 LED groove skipped: T3 board missing.");
    return [];
  }

  // Front land (edge → groove) = 18 mm → centerline = 18 + 14.5/2 = 25.25.
  const frontOffset = LED_GROOVE_FRONT_OFFSET;
  const { width, depth } = t3LedBoardExtents(t3);
  const path = buildInsertBoardLedGroovePath(width, depth, "T3", warnings);
  if (!path) return [];

  t3.notes = [
    ...(t3.notes ?? []).filter((note) => !note.toLowerCase().includes("led groove")),
    `T3 LED groove path on top face (${LED_GROOVE_FRONT_LAND_MM} mm front land)`,
  ];

  return [
    {
      id: "T3_led_groove",
      type: "t3_groove",
      targetBoardId: "T3",
      face: "top",
      width: LED_GROOVE_WIDTH,
      depth: LED_GROOVE_DEPTH,
      frontOffset,
      frontLand: LED_GROOVE_FRONT_LAND_MM,
      branchCount: path.branches.length,
      branchLength: path.branchLength,
      branchWidth: LED_GROOVE_WIDTH,
      branchEndInset: LED_GROOVE_BRANCH_END_INSET,
      main: path.main,
      branches: path.branches,
      source: "T3",
      notes: [
        "T3 LED groove on top face (opens upward)",
        `Main channel along X, ${LED_GROOVE_FRONT_LAND_MM} mm land from T3 front then ${LED_GROOVE_WIDTH} mm groove (centerline ${frontOffset} mm)`,
        "Two rear T-branches parallel to Y, extend to T3 back edge, centers inset 80 mm from each X end",
      ],
    },
  ];
}

function resolveCarcassColor(params: OverheadCabinetParams): { carcassColor: string; carcassColorName: string } {
  const raw = String(params.carcassColor || params.carcassColorName || "white_stipple").trim();
  const tag = raw.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]+/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "") || "white_stipple";
  const name = String(params.carcassColorName || (tag === "white_stipple" ? "White Stipple" : raw)).trim() || "White Stipple";
  return { carcassColor: tag, carcassColorName: name };
}

export function generateOverheadCabinet(rawParams: OverheadCabinetParams): OverheadCabinetResult {
  const inputs = toInputs(rawParams);
  const carcassColor = resolveCarcassColor(rawParams);
  const validation = { errors: [] as string[], warnings: [] as string[] };

  if (!Number.isFinite(inputs.cabinetWidth) || inputs.cabinetWidth <= 0) {
    validation.errors.push("cabinetWidth must be a positive number.");
  }
  if (!Number.isFinite(inputs.cabinetDepth) || inputs.cabinetDepth <= 0) {
    validation.errors.push("cabinetDepth must be a positive number.");
  }
  if (
    inputs.cabinetHeight != null &&
    (!Number.isFinite(inputs.cabinetHeight) || inputs.cabinetHeight <= 0)
  ) {
    validation.errors.push("cabinetHeight must be a positive number when provided.");
  }

  const geometry = validation.errors.length === 0 ? calculateOverheadGeometry(inputs) : null;
  const rangehood = geometry ? resolveRangehoodGroup(rawParams, geometry, validation) : null;
  const centerlines = geometry ? geometry.divider_features.map((f) => f.XDi) : [];

  if (validation.errors.length > 0) {
    return {
      params: {
        cabinetWidth: inputs.cabinetWidth,
        cabinetDepth: inputs.cabinetDepth,
        cabinetHeight: inputs.cabinetHeight ?? 0,
        style: inputs.style ?? "style_1",
        topClearanceHeight: inputs.topClearanceHeight ?? 40,
        frontPanelThickness: inputs.frontPanelThickness ?? 16,
        clearance: inputs.clearance ?? 2.5,
        hingeHoleDiameter: inputs.hingeHoleDiameter ?? 35,
        hingeHoleDepth: inputs.hingeHoleDepth ?? 12,
        hingeHoleFromTop: inputs.hingeHoleFromTop ?? 22.5,
        hingeHoleFromSide: inputs.hingeHoleFromSide ?? 100,
        bottomThickness: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
        dividerTongueHeight: inputs.dividerTongueHeight ?? (inputs.featureWidth ?? DIVIDER_THICKNESS_MM) / 2 - 0.5,
        routerDiameter: inputs.routerDiameter ?? DEFAULT_ROUTER_DIAMETER_MM,
        featureWidth: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
        internalDividerCenterlines: inputs.internalDividerCenterlines ?? [],
        rangehoodPreset: String(rawParams.rangehoodPreset || RANGEHOOD_PRESET_NCE),
        rangehoodClearHeight: Number(rawParams.rangehoodClearHeight ?? RANGEHOOD_DEFAULT_CLEAR_HEIGHT_MM),
        rangehoodAlignment: String(rawParams.rangehoodAlignment || "left"),
        rangehoodEdgeOffsetX: Number(rawParams.rangehoodEdgeOffsetX ?? RANGEHOOD_MIN_EDGE_MM),
        ...carcassColor,
      },
      boards: [],
      features: [],
      relationshipDeclarations: [],
      validation,
      debug: {
        phase: "geometry_v1",
        legacyReference: "fusion360-cabinet-generator/core/overhead_geometry.py",
        dividerCenterlines: centerlines,
      },
    };
  }

  if (!geometry) {
    throw new Error("Overhead geometry was not resolved after validation.");
  }
  const boards = legacyToBoards(geometry, inputs, rangehood);
  const relationshipDeclarations = relationshipDeclarationsForBoards(boards);
  const ledFeatures = generateT3LedGrooveFeatures(boards, validation.warnings, rawParams);
  const rangehoodFeatures = generateRangehoodFeatures(geometry, rangehood);
  const dividerFeatures = geometry.divider_features.map((feature, index) => {
    if (!rangehood?.internalDividerIndices.includes(index)) return feature;
    return { ...feature, bp_groove: undefined };
  });

  return {
    params: {
      cabinetWidth: inputs.cabinetWidth,
      cabinetDepth: inputs.cabinetDepth,
      cabinetHeight: inputs.cabinetHeight ?? 0,
      style: inputs.style ?? "style_1",
      topClearanceHeight: inputs.topClearanceHeight ?? 40,
      frontPanelThickness: inputs.frontPanelThickness ?? 16,
      clearance: inputs.clearance ?? 2.5,
      hingeHoleDiameter: inputs.hingeHoleDiameter ?? 35,
      hingeHoleDepth: inputs.hingeHoleDepth ?? 12,
      hingeHoleFromTop: inputs.hingeHoleFromTop ?? 22.5,
      hingeHoleFromSide: inputs.hingeHoleFromSide ?? 100,
      bottomThickness: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
      dividerTongueHeight: inputs.dividerTongueHeight ?? (inputs.featureWidth ?? DIVIDER_THICKNESS_MM) / 2 - 0.5,
      routerDiameter: inputs.routerDiameter ?? DEFAULT_ROUTER_DIAMETER_MM,
      featureWidth: inputs.featureWidth ?? DIVIDER_THICKNESS_MM,
      internalDividerCenterlines: inputs.internalDividerCenterlines ?? [],
      rangehoodPreset: String(rawParams.rangehoodPreset || RANGEHOOD_PRESET_NCE),
      rangehoodClearHeight: Number(rawParams.rangehoodClearHeight ?? RANGEHOOD_DEFAULT_CLEAR_HEIGHT_MM),
      rangehoodAlignment: String(rawParams.rangehoodAlignment || "left"),
      rangehoodEdgeOffsetX: Number(rawParams.rangehoodEdgeOffsetX ?? RANGEHOOD_MIN_EDGE_MM),
      ...carcassColor,
    },
    boards,
    features: [
      ...dividerFeatures,
      ...geometry.front_panels,
      ...geometry.hinge_holes,
      ...rangehoodFeatures,
      ...ledFeatures,
    ],
    relationshipDeclarations,
    validation,
    debug: {
      phase: "geometry_v1",
      legacyReference: "fusion360-cabinet-generator/core/overhead_geometry.py",
      dividerCenterlines: centerlines,
      legacyGeometry: geometry,
      svgPreview: generateOHCSvgPreview(geometry, {
        selectedZoneIndex: Number((rawParams as { selectedZoneIndex?: number }).selectedZoneIndex ?? -1),
      }),
    },
  };
}
