/** Overhead Cabinet geometry v7. */

export const DEFAULT_ROUTER_DIAMETER_MM = 10;
export const DIVIDER_THICKNESS_MM = 15;
export const FEATURE_CLEARANCE_MM = 1;
export const FEATURE_GROOVE_WIDTH_MM = DIVIDER_THICKNESS_MM + FEATURE_CLEARANCE_MM;
export const SCREW_HOLE_DIAMETER_MM = 3;
export const SCREW_HOLE_DEPTH_MM = 15;
export const BOTTOM_THICKNESS_MM = 15;
export const DIVIDER_TONGUE_HEIGHT_MM = DIVIDER_THICKNESS_MM / 2 - 0.5;
export const T1_HEIGHT_MM = 40;
export const T3_DEPTH_MM = 90;
export const T3_THICKNESS_MM = 15;
export const T3_NOTCH_DEPTH_MM = 20;
export const T4_THICKNESS_MM = 15;
export const T4_HEIGHT_MM = 50;
export const T4_NOTCH_HEIGHT_MM = 20;
export const T4_SCREW_HOLE_NOTCH_CLEARANCE_MM = 8;
export const T4_SCREW_HOLE_UP_SHIFT_MM = 10;
export const FRONT_TOP_NOTCH_Y_OFFSET_MM = 70;
export const FRONT_TOP_STEP_Y_MM = 10;
export const FRONT_TOP_STEP_DROP_MM = FEATURE_GROOVE_WIDTH_MM;
export const REAR_TOP_NOTCH_HEIGHT_MM = T4_HEIGHT_MM - 15;

export type OverheadStyle = "style_1" | "style_2";

export interface FunctionZoneInput {
  id?: string;
  type: string;
  width: number;
}

export interface OverheadCabinetInputs {
  style?: string;
  cabinetWidth: number;
  cabinetDepth: number;
  cabinetHeight?: number | null;
  topClearanceHeight?: number;
  frontPanelThickness?: number;
  clearance?: number;
  hingeHoleDiameter?: number;
  hingeHoleDepth?: number;
  hingeHoleFromTop?: number;
  hingeHoleFromSide?: number;
  bottomThickness?: number;
  dividerTongueHeight?: number;
  routerDiameter?: number;
  featureWidth?: number;
  internalDividerCenterlines?: number[];
  zones?: FunctionZoneInput[];
}

export interface ScrewHolePosition {
  x: number;
  y: number;
  diameter: number;
}

export interface PanelScrewHole {
  id: string;
  part: string;
  for_divider: string;
  center: [number, number];
  diameter: number;
  depth: number;
  axis: "thickness";
}

export interface BpGroove {
  id: string;
  part: "BP";
  for_divider: string;
  x: [number, number];
  y: [number, number];
  z: [number, number];
  width_x: number;
  length_y: number;
  depth_z: number;
}

export interface DividerNotch {
  id: string;
  part: string;
  for_divider: string;
  x: [number, number];
  y: number[] | [number, number];
  z: number[] | [number, number];
  width_x: number;
  depth_y?: number;
  height_z?: number;
}

export interface DividerTongue {
  length_y: number;
  y: [number, number];
  z: [number, number];
}

export interface DividerFeature {
  id: string;
  XDi: number;
  bp_groove: BpGroove;
  screw_holes: ScrewHolePosition[];
  divider_tongue: DividerTongue;
  t3_notch: DividerNotch;
  t4_notch: DividerNotch;
}

export interface BottomPanel {
  origin: "left-top-front";
  global_origin: [number, number, number];
  size: [number, number, number];
  local_bounds: {
    x: [number, number];
    y: [number, number];
    z: [number, number];
  };
}

export type OutlinePoint = [number, number];

export interface OverheadLegacyGeometry {
  cabinet: { Cw: number; Cd: number; Ch: number | null | undefined };
  manufacturing: {
    Crd: number;
    Crr: number;
    FGw: number;
    FGh: number;
    FPt: number;
    TCH: number;
    FZH: number;
    FitClearance: number;
    FeatureSlotWidth: number;
    Dntg_h: number;
    style: OverheadStyle;
  };
  bottom_panel: BottomPanel;
  divider_features: DividerFeature[];
  front_panels: FrontPanelFeature[];
  hinge_holes: HingeHoleFeature[];
  panel_screw_holes: {
    T2: PanelScrewHole[];
    T3: PanelScrewHole[];
    T4: PanelScrewHole[];
  };
  trimmed_vectors: {
    T3: OutlinePoint[];
    T4: OutlinePoint[];
    DividerSide: OutlinePoint[];
  };
}

export interface FunctionZone {
  id: string;
  type: string;
  width: number;
  x0: number;
  x1: number;
}

export interface FrontPanelFeature {
  id: string;
  zoneId: string;
  zoneIndex: number;
  type: string;
  x: [number, number];
  y: [number, number];
  z: [number, number];
  width: number;
  height: number;
  thickness: number;
  clearance: number;
  opening: {
    x: [number, number];
    width: number;
  };
}

export interface HingeHoleFeature {
  id: string;
  boardId: string;
  center: [number, number];
  diameter: number;
  depth: number;
  axis: "Y";
  purpose: "hinge";
  face: "back";
}

function dedupePoints(points: OutlinePoint[]): OutlinePoint[] {
  const out: OutlinePoint[] = [];
  for (const point of points) {
    if (out.length > 0 && out[out.length - 1]![0] === point[0] && out[out.length - 1]![1] === point[1]) {
      continue;
    }
    out.push(point);
  }
  return out;
}

export function edgeDividerCenterlines(
  cabinetWidth: number,
  featureWidth = DIVIDER_THICKNESS_MM,
): [number, number] {
  const halfWidth = featureWidth / 2;
  return [halfWidth, cabinetWidth - halfWidth];
}

export function dividerCenterlines(
  cabinetWidth: number,
  internalCenterlines: number[],
  featureWidth = DIVIDER_THICKNESS_MM,
): number[] {
  const [left, right] = edgeDividerCenterlines(cabinetWidth, featureWidth);
  return [left, ...internalCenterlines, right];
}

export function clampRange(range: [number, number], min: number, max: number): [number, number] {
  return [Math.max(min, range[0]), Math.min(max, range[1])];
}

export function featureXRange(centerlineX: number, featureSlotWidth = FEATURE_GROOVE_WIDTH_MM): [number, number] {
  const halfWidth = featureSlotWidth / 2;
  return [centerlineX - halfWidth, centerlineX + halfWidth];
}

export function boardXRange(centerlineX: number, boardThickness = DIVIDER_THICKNESS_MM): [number, number] {
  const halfWidth = boardThickness / 2;
  return [centerlineX - halfWidth, centerlineX + halfWidth];
}

export function bpGrooveYRange(cabinetDepth: number): [number, number] {
  return [cabinetDepth / 3, (2 * cabinetDepth) / 3];
}

export function bpGrooveLength(cabinetDepth: number): number {
  return cabinetDepth / 3;
}

export function screwHolePositions(
  centerlineX: number,
  cabinetDepth: number,
  diameter = SCREW_HOLE_DIAMETER_MM,
): ScrewHolePosition[] {
  return [
    { x: centerlineX, y: cabinetDepth / 6, diameter },
    { x: centerlineX, y: (5 * cabinetDepth) / 6, diameter },
  ];
}

export function panelScrewHoles(
  part: string,
  centers: number[],
  localMidline: number,
  diameter = SCREW_HOLE_DIAMETER_MM,
  depth = SCREW_HOLE_DEPTH_MM,
): PanelScrewHole[] {
  return centers.map((centerlineX, index) => ({
    id: `${part}SH_D${index}`,
    part,
    for_divider: `D${index}`,
    center: [centerlineX, localMidline],
    diameter,
    depth,
    axis: "thickness" as const,
  }));
}

export function dividerTongueYRange(
  cabinetDepth: number,
  _routerDiameter = DEFAULT_ROUTER_DIAMETER_MM,
): [number, number] {
  const sideInset = 5;
  return [
    cabinetDepth / 3 + sideInset,
    (2 * cabinetDepth) / 3 - sideInset,
  ];
}

export function dividerTongueLength(
  cabinetDepth: number,
  _routerDiameter = DEFAULT_ROUTER_DIAMETER_MM,
): number {
  return cabinetDepth / 3 - 10;
}

export function t3NotchYRange(
  t3Depth = T3_DEPTH_MM,
  notchDepth = T3_NOTCH_DEPTH_MM,
): [number, number] {
  return [t3Depth - notchDepth, t3Depth];
}

export function t4NotchZRange(notchHeight = T4_NOTCH_HEIGHT_MM): [number, number] {
  return [0, notchHeight];
}

export function bpGroove(
  dividerId: string,
  centerlineX: number,
  cabinetDepth: number,
  featureSlotWidth = FEATURE_GROOVE_WIDTH_MM,
  tongueHeight?: number,
  cabinetWidth?: number,
): BpGroove {
  const z1 = tongueHeight !== undefined ? -tongueHeight : 0;
  const [rawX0, rawX1] = featureXRange(centerlineX, featureSlotWidth);
  const [x0, x1] = cabinetWidth === undefined ? [rawX0, rawX1] : clampRange([rawX0, rawX1], 0, cabinetWidth);
  const [y0, y1] = bpGrooveYRange(cabinetDepth);
  const depthZ = tongueHeight ?? 0;
  return {
    id: `BG_${dividerId}`,
    part: "BP",
    for_divider: dividerId,
    x: [x0, x1],
    y: [y0, y1],
    z: [0, z1],
    width_x: x1 - x0,
    length_y: bpGrooveLength(cabinetDepth),
    depth_z: depthZ,
  };
}

export function t3Notch(
  dividerId: string,
  centerlineX: number,
  featureSlotWidth = FEATURE_GROOVE_WIDTH_MM,
  cabinetWidth?: number,
): DividerNotch {
  const [rawX0, rawX1] = featureXRange(centerlineX, featureSlotWidth);
  const x = cabinetWidth === undefined ? [rawX0, rawX1] as [number, number] : clampRange([rawX0, rawX1], 0, cabinetWidth);
  return {
    id: `T3N_${dividerId}`,
    part: "T3",
    for_divider: dividerId,
    x,
    y: t3NotchYRange(),
    z: [0, -DIVIDER_THICKNESS_MM],
    width_x: x[1] - x[0],
    depth_y: T3_NOTCH_DEPTH_MM,
  };
}

export function t4Notch(
  dividerId: string,
  centerlineX: number,
  featureSlotWidth = FEATURE_GROOVE_WIDTH_MM,
  cabinetWidth?: number,
): DividerNotch {
  const [rawX0, rawX1] = featureXRange(centerlineX, featureSlotWidth);
  const x = cabinetWidth === undefined ? [rawX0, rawX1] as [number, number] : clampRange([rawX0, rawX1], 0, cabinetWidth);
  return {
    id: `T4N_${dividerId}`,
    part: "T4",
    for_divider: dividerId,
    x,
    y: [0, DIVIDER_THICKNESS_MM],
    z: t4NotchZRange(),
    width_x: x[1] - x[0],
    height_z: T4_NOTCH_HEIGHT_MM,
  };
}

export function t3TrimmedOutlinePoints(
  cabinetWidth: number,
  notchXRanges: [number, number][],
  t3Depth = T3_DEPTH_MM,
  notchDepth = T3_NOTCH_DEPTH_MM,
): OutlinePoint[] {
  const rearY = t3Depth;
  const notchY = t3Depth - notchDepth;
  const ranges = [...notchXRanges].sort((a, b) => b[0] - a[0]);
  const points: OutlinePoint[] = [
    [0, 0],
    [cabinetWidth, 0],
  ];

  let currentX = cabinetWidth;

  if (ranges.length > 0 && ranges[0]![1] >= cabinetWidth) {
    const [x0] = ranges.shift()!;
    points.push([cabinetWidth, notchY], [x0, notchY], [x0, rearY]);
    currentX = x0;
  } else {
    points.push([cabinetWidth, rearY]);
    currentX = cabinetWidth;
  }

  while (ranges.length > 0) {
    const [x0, x1] = ranges.shift()!;
    if (x0 <= 0) {
      points.push([x1, rearY], [x1, notchY], [0, notchY], [0, 0]);
      return dedupePoints(points);
    }
    points.push([x1, rearY], [x1, notchY], [x0, notchY], [x0, rearY]);
    currentX = x0;
  }

  if (currentX > 0) {
    points.push([0, rearY], [0, 0]);
  }
  return dedupePoints(points);
}

export function t4TrimmedOutlinePoints(
  cabinetWidth: number,
  notchXRanges: [number, number][],
  t4Height = T4_HEIGHT_MM,
  notchHeight = T4_NOTCH_HEIGHT_MM,
): OutlinePoint[] {
  const ranges = [...notchXRanges].sort((a, b) => b[0] - a[0]);
  const points: OutlinePoint[] = [
    [0, t4Height],
    [cabinetWidth, t4Height],
  ];

  let currentX = cabinetWidth;

  if (ranges.length > 0 && ranges[0]![1] >= cabinetWidth) {
    const [x0] = ranges.shift()!;
    points.push([cabinetWidth, notchHeight], [x0, notchHeight], [x0, 0]);
    currentX = x0;
  } else {
    points.push([cabinetWidth, 0]);
    currentX = cabinetWidth;
  }

  while (ranges.length > 0) {
    const [x0, x1] = ranges.shift()!;
    if (x0 <= 0) {
      points.push([x1, 0], [x1, notchHeight], [0, notchHeight], [0, t4Height]);
      return dedupePoints(points);
    }
    points.push([x1, 0], [x1, notchHeight], [x0, notchHeight], [x0, 0]);
    currentX = x0;
  }

  if (currentX > 0) {
    points.push([0, 0], [0, t4Height]);
  }
  return dedupePoints(points);
}

export function dividerSideTrimmedOutlinePoints(
  cabinetDepth: number,
  cabinetHeight: number | null | undefined,
  fgWidth = DIVIDER_THICKNESS_MM,
  tongueHeight?: number,
  routerDiameter = DEFAULT_ROUTER_DIAMETER_MM,
  featureSlotWidth = FEATURE_GROOVE_WIDTH_MM,
  topClearanceHeight = T1_HEIGHT_MM,
  style: OverheadStyle = "style_1",
  frontPanelThickness = 16,
): OutlinePoint[] {
  if (cabinetHeight == null) {
    return [];
  }

  const resolvedTongueHeight = tongueHeight ?? fgWidth / 2 - 0.5;
  const dividerHeight = cabinetHeight - fgWidth;
  const [tongueY0, tongueY1] = dividerTongueYRange(cabinetDepth, routerDiameter);
  const tongueZ0 = -resolvedTongueHeight;

  const frontY0 = style === "style_2" ? frontPanelThickness + fgWidth : FRONT_TOP_NOTCH_Y_OFFSET_MM;
  const frontZ0 = dividerHeight - topClearanceHeight;

  const rearY0 = cabinetDepth - featureSlotWidth;
  const rearZ0 = dividerHeight - (T4_HEIGHT_MM - fgWidth);
  const frontStepY1 = FRONT_TOP_NOTCH_Y_OFFSET_MM + FRONT_TOP_STEP_Y_MM;
  const frontStepZ1 = frontZ0 - featureSlotWidth;

  return dedupePoints([
    [0, 0],
    [tongueY0, 0],
    [tongueY0, tongueZ0],
    [tongueY1, tongueZ0],
    [tongueY1, 0],
    [cabinetDepth, 0],
    [cabinetDepth, rearZ0],
    [rearY0, rearZ0],
    [rearY0, dividerHeight],
    [frontY0, dividerHeight],
    [frontY0, frontZ0],
    [frontStepY1, frontZ0],
    [frontStepY1, frontStepZ1],
    [frontStepY1 - (T3_DEPTH_MM - 10), frontStepZ1],
    [0, 0],
  ]);
}

function bottomPanel(inputs: OverheadCabinetInputs): BottomPanel {
  const bottomThickness = inputs.featureWidth ?? DIVIDER_THICKNESS_MM;
  return {
    origin: "left-top-front",
    global_origin: [0, 0, bottomThickness],
    size: [inputs.cabinetWidth, inputs.cabinetDepth, bottomThickness],
    local_bounds: {
      x: [0, inputs.cabinetWidth],
      y: [0, inputs.cabinetDepth],
      z: [-bottomThickness, 0],
    },
  };
}

function dividerFeature(dividerId: string, centerlineX: number, inputs: OverheadCabinetInputs): DividerFeature {
  const fgWidth = inputs.featureWidth ?? DIVIDER_THICKNESS_MM;
  const featureSlotWidth = fgWidth + FEATURE_CLEARANCE_MM;
  const dividerTongueHeight = inputs.dividerTongueHeight ?? fgWidth / 2 - 0.5;
  const bpGrooveDepth = fgWidth / 2;
  const routerDiameter = inputs.routerDiameter ?? DEFAULT_ROUTER_DIAMETER_MM;

  return {
    id: dividerId,
    XDi: centerlineX,
    bp_groove: bpGroove(
      dividerId,
      centerlineX,
      inputs.cabinetDepth,
      featureSlotWidth,
      bpGrooveDepth,
      inputs.cabinetWidth,
    ),
    screw_holes: screwHolePositions(centerlineX, inputs.cabinetDepth),
    divider_tongue: {
      length_y: dividerTongueLength(inputs.cabinetDepth, routerDiameter),
      y: dividerTongueYRange(inputs.cabinetDepth, routerDiameter),
      z: [-dividerTongueHeight, 0],
    },
    t3_notch: t3Notch(dividerId, centerlineX, featureSlotWidth, inputs.cabinetWidth),
    t4_notch: t4Notch(dividerId, centerlineX, featureSlotWidth, inputs.cabinetWidth),
  };
}

function normalizeStyle(style?: string): OverheadStyle {
  return style === "style_2" ? "style_2" : "style_1";
}

function resolveZones(inputs: OverheadCabinetInputs): FunctionZone[] {
  if (Array.isArray(inputs.zones) && inputs.zones.length > 0) {
    let x = 0;
    return inputs.zones.map((zone, index) => {
      const width = Number(zone.width) || 0;
      const out = {
        id: zone.id || `zone-${index + 1}`,
        type: zone.type || "up_flap",
        width,
        x0: x,
        x1: x + width,
      };
      x += width;
      return out;
    });
  }
  const centers = inputs.internalDividerCenterlines ?? [];
  const boundaries = [0, ...centers, inputs.cabinetWidth];
  return boundaries.slice(0, -1).map((x0, index) => ({
    id: `zone-${index + 1}`,
    type: index % 2 === 0 ? "up_flap" : "fixed_panel",
    width: boundaries[index + 1]! - x0,
    x0,
    x1: boundaries[index + 1]!,
  }));
}

function frontPanels(inputs: OverheadCabinetInputs, zones: FunctionZone[], centers: number[]): FrontPanelFeature[] {
  const fgWidth = inputs.featureWidth ?? DIVIDER_THICKNESS_MM;
  const clearance = inputs.clearance ?? 2.5;
  const fpThickness = inputs.frontPanelThickness ?? 16;
  const topClearanceHeight = inputs.topClearanceHeight ?? T1_HEIGHT_MM;
  const functionZoneHeight = (inputs.cabinetHeight ?? topClearanceHeight) - topClearanceHeight;
  const halfClearance = clearance / 2;
  return zones
    .map((zone, index) => {
      if (zone.type === "open") return null;
      const openingX0 = centers[index]! + fgWidth / 2;
      const openingX1 = centers[index + 1]! - fgWidth / 2;
      const leftClearance = zone.x0 <= 0 ? clearance : halfClearance;
      const rightClearance = zone.x1 >= inputs.cabinetWidth ? clearance : halfClearance;
      const x0 = zone.x0 + leftClearance;
      const x1 = zone.x1 - rightClearance;
      const z0 = -30;
      const z1 = functionZoneHeight - 1;
      return {
        id: `FP${index}`,
        zoneId: zone.id,
        zoneIndex: index,
        type: zone.type,
        x: [x0, x1],
        y: [-fpThickness, 0],
        z: [z0, z1],
        width: x1 - x0,
        height: z1 - z0,
        thickness: fpThickness,
        clearance,
        opening: {
          x: [openingX0, openingX1],
          width: openingX1 - openingX0,
        },
      } as FrontPanelFeature;
    })
    .filter((panel): panel is FrontPanelFeature => panel !== null);
}

function hingeHoles(panels: FrontPanelFeature[], inputs: OverheadCabinetInputs): HingeHoleFeature[] {
  const holeDiameter = inputs.hingeHoleDiameter ?? 35;
  const holeDepth = inputs.hingeHoleDepth ?? 12;
  const holeFromTop = inputs.hingeHoleFromTop ?? 22.5;
  const holeFromSide = inputs.hingeHoleFromSide ?? 100;
  return panels
    .filter((panel) => panel.type === "up_flap" || panel.type === "rangehood_flap")
    .flatMap((panel) => {
      const z = panel.height - holeFromTop;
      return [holeFromSide, panel.width - holeFromSide].map((x, index) => ({
        id: `${panel.id}_HINGE_${index + 1}`,
        boardId: panel.id,
        center: [x, z] as [number, number],
        diameter: holeDiameter,
        depth: holeDepth,
        axis: "Y" as const,
        purpose: "hinge" as const,
        face: "back" as const,
      }));
    });
}

function buildLegacyGeometry(inputs: OverheadCabinetInputs, centers: number[]): OverheadLegacyGeometry {
  const fgWidth = inputs.featureWidth ?? DIVIDER_THICKNESS_MM;
  const featureSlotWidth = fgWidth + FEATURE_CLEARANCE_MM;
  const routerDiameter = inputs.routerDiameter ?? DEFAULT_ROUTER_DIAMETER_MM;
  const style = normalizeStyle(inputs.style);
  const topClearanceHeight = inputs.topClearanceHeight ?? T1_HEIGHT_MM;
  const frontPanelThickness = inputs.frontPanelThickness ?? 16;
  const dntgH = inputs.dividerTongueHeight ?? fgWidth / 2 - 0.5;
  const zones = resolveZones(inputs);
  const panels = frontPanels(inputs, zones, centers);
  const dividerIds = centers.map((_, index) => `D${index}`);

  return {
    cabinet: {
      Cw: inputs.cabinetWidth,
      Cd: inputs.cabinetDepth,
      Ch: inputs.cabinetHeight ?? null,
    },
    manufacturing: {
      Crd: routerDiameter,
      Crr: routerDiameter / 2,
      FGw: fgWidth,
      FGh: fgWidth / 2,
      FPt: frontPanelThickness,
      TCH: topClearanceHeight,
      FZH: (inputs.cabinetHeight ?? topClearanceHeight) - topClearanceHeight,
      FitClearance: FEATURE_CLEARANCE_MM,
      FeatureSlotWidth: featureSlotWidth,
      Dntg_h: dntgH,
      style,
    },
    bottom_panel: bottomPanel(inputs),
    divider_features: dividerIds.map((dividerId, index) =>
      dividerFeature(dividerId, centers[index]!, inputs),
    ),
    front_panels: panels,
    hinge_holes: hingeHoles(panels, inputs),
    panel_screw_holes: {
      T2: panelScrewHoles("T2", centers, topClearanceHeight / 2),
      T3: panelScrewHoles("T3", centers, T3_DEPTH_MM / 2),
      T4: panelScrewHoles(
        "T4",
        centers,
        T4_NOTCH_HEIGHT_MM + T4_SCREW_HOLE_NOTCH_CLEARANCE_MM + T4_SCREW_HOLE_UP_SHIFT_MM,
      ),
    },
    trimmed_vectors: {
      T3: t3TrimmedOutlinePoints(
        inputs.cabinetWidth,
        centers.map((centerlineX) => clampRange(featureXRange(centerlineX, featureSlotWidth), 0, inputs.cabinetWidth)),
      ),
      T4: t4TrimmedOutlinePoints(
        inputs.cabinetWidth,
        centers.map((centerlineX) => clampRange(featureXRange(centerlineX, featureSlotWidth), 0, inputs.cabinetWidth)),
      ),
      DividerSide: dividerSideTrimmedOutlinePoints(
        inputs.cabinetDepth,
        inputs.cabinetHeight,
        fgWidth,
        dntgH,
        routerDiameter,
        featureSlotWidth,
        topClearanceHeight,
        style,
        frontPanelThickness,
      ),
    },
  };
}

export function calculateOverheadGeometry(inputs: OverheadCabinetInputs): OverheadLegacyGeometry {
  const fgWidth = inputs.featureWidth ?? DIVIDER_THICKNESS_MM;
  const zones = resolveZones(inputs);
  const internalCenters = Array.isArray(inputs.zones) && inputs.zones.length > 0
    ? zones.slice(0, -1).map((zone) => zone.x1)
    : inputs.internalDividerCenterlines ?? [];
  const centers = dividerCenterlines(inputs.cabinetWidth, internalCenters, fgWidth);
  return buildLegacyGeometry(inputs, centers);
}

export function calculateOverheadGeometryFromXds(
  cabinetWidth: number,
  cabinetDepth: number,
  cabinetHeight: number | null | undefined,
  xds: number[],
  bottomThickness = BOTTOM_THICKNESS_MM,
  dividerTongueHeight = DIVIDER_TONGUE_HEIGHT_MM,
  routerDiameter = DEFAULT_ROUTER_DIAMETER_MM,
  featureWidth = DIVIDER_THICKNESS_MM,
): OverheadLegacyGeometry {
  const inputs: OverheadCabinetInputs = {
    cabinetWidth,
    cabinetDepth,
    cabinetHeight,
    bottomThickness,
    dividerTongueHeight,
    routerDiameter,
    featureWidth,
    internalDividerCenterlines: xds.slice(1, -1),
  };
  return buildLegacyGeometry(inputs, xds);
}

export function calculateOverheadGeometryFromInternalXds(
  cabinetWidth: number,
  cabinetDepth: number,
  cabinetHeight: number | null | undefined,
  internalXds: number[],
  bottomThickness = BOTTOM_THICKNESS_MM,
  dividerTongueHeight?: number,
  routerDiameter = DEFAULT_ROUTER_DIAMETER_MM,
  featureWidth = DIVIDER_THICKNESS_MM,
): OverheadLegacyGeometry {
  const resolvedTongueHeight = dividerTongueHeight ?? featureWidth / 2 - 0.5;
  const [leftXd, rightXd] = edgeDividerCenterlines(cabinetWidth, featureWidth);
  return calculateOverheadGeometryFromXds(
    cabinetWidth,
    cabinetDepth,
    cabinetHeight,
    [leftXd, ...internalXds, rightXd],
    bottomThickness,
    resolvedTongueHeight,
    routerDiameter,
    featureWidth,
  );
}

export function testCase001Geometry(): OverheadLegacyGeometry {
  return calculateOverheadGeometryFromInternalXds(
    500,
    300,
    null,
    [125, 250, 375],
    BOTTOM_THICKNESS_MM,
    undefined,
    10,
    16,
  );
}
