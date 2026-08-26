import type {
  LoungeBounds2D,
  LoungeGeometryResult,
  LoungeLid,
  LoungeOpening,
  LoungePanel,
  LoungeSettings,
} from "./types.ts";
import { relationshipDeclarationsForPanels } from "./relationshipDeclarations.ts";

const DEFAULT_HEIGHT = 420;
const DEFAULT_PPT = 18;
const OPENING_RADIUS = 50;
const LID_CLEARANCE_EACH_SIDE = 1.5;
const FINGER_HOLE_DIAMETER = 40;

function withRelationshipDeclarations(result: LoungeGeometryResult): LoungeGeometryResult {
  return {
    ...result,
    relationshipDeclarations: relationshipDeclarationsForPanels(result.panels),
  };
}

function num(value: unknown, fallback: number): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function normalizeCarcassColor(input: Partial<LoungeSettings>): { carcassColor: string; carcassColorName: string } {
  const raw = String(input.carcassColor || input.carcassColorName || "white_stipple").trim();
  const tag = raw.toLowerCase().replace(/\s+/g, "_").replace(/[^a-z0-9_]+/g, "_").replace(/_+/g, "_").replace(/^_|_$/g, "") || "white_stipple";
  const name = String(input.carcassColorName || (tag === "white_stipple" ? "White Stipple" : raw)).trim() || "White Stipple";
  return { carcassColor: tag, carcassColorName: name };
}

function normalizeSettings(input: Partial<LoungeSettings>): LoungeSettings {
  return {
    style: input.style || "L_SHAPE",
    height: num(input.height, DEFAULT_HEIGHT),
    partitionPanelThickness: num(input.partitionPanelThickness, DEFAULT_PPT),
    ...normalizeCarcassColor(input),
    wheelAvoidanceEnabled: input.wheelAvoidanceEnabled === true,
    mainWidth: num(input.mainWidth, 2000),
    mainDepth: num(input.mainDepth, 600),
    lWidth: num(input.lWidth, 1600),
    lDepth: num(input.lDepth, 800),
    lPosition: input.lPosition || "RIGHT",
    topLidEnabled: input.topLidEnabled !== false,
    lFrontAccess: input.lFrontAccess || "NONE",
    totalWidth: num(input.totalWidth, 4000),
    singleLoungeWidth: num(input.singleLoungeWidth, 1500),
    depth: num(input.depth, 800),
    avoidanceDepth: num(input.avoidanceDepth, 300),
    avoidanceHeight: num(input.avoidanceHeight, 250),
    hasMiddleCabinet: input.hasMiddleCabinet === true,
    middleCabinet: {
      width: num(input.middleCabinet?.width, 600),
      depth: num(input.middleCabinet?.depth, 350),
      height: num(input.middleCabinet?.height, 500),
      startHeight: num(input.middleCabinet?.startHeight, 300),
      doorPanelThickness: num(input.middleCabinet?.doorPanelThickness, 16),
      doorClearance: num(input.middleCabinet?.doorClearance, 2),
      doorLockStyle: input.middleCabinet?.doorLockStyle === "NONE" ? "NONE" : "RAZOR_ROUNDED",
      lockSideDistance: num(input.middleCabinet?.lockSideDistance, 30),
      hingeSideDistance: num(input.middleCabinet?.hingeSideDistance, 80),
      hingeCupCenterFromEdge: num(input.middleCabinet?.hingeCupCenterFromEdge, 22.5),
      hingeCupDiameter: num(input.middleCabinet?.hingeCupDiameter, 35),
      hingeCupDepth: num(input.middleCabinet?.hingeCupDepth, 12.5),
    },
  };
}

export function loungeLBounds(state: LoungeSettings): LoungeBounds2D {
  // L box sits on the front of one main end so the two I-boxes meet at 90°.
  if (state.lPosition === "LEFT") {
    return { x0: 0, x1: state.lWidth, y0: state.mainDepth, y1: state.mainDepth + state.lDepth };
  }
  return {
    x0: state.mainWidth - state.lWidth,
    x1: state.mainWidth,
    y0: state.mainDepth,
    y1: state.mainDepth + state.lDepth,
  };
}

export function loungeMainVisibleBounds(state: LoungeSettings): LoungeBounds2D {
  if (state.lPosition === "LEFT") {
    return { x0: state.lWidth, x1: state.mainWidth, y0: 0, y1: state.mainDepth };
  }
  return { x0: 0, x1: state.mainWidth - state.lWidth, y0: 0, y1: state.mainDepth };
}

function openingForPanel(panelId: string, width: number, depth: number, ppt: number): LoungeOpening {
  return {
    id: `${panelId}_opening`,
    panelId,
    x0: width / 4,
    x1: width * 3 / 4,
    y0: depth / 4,
    y1: depth * 3 / 4,
    width: width / 2,
    depth: depth / 2,
    radius: OPENING_RADIUS,
    stepWidth: ppt / 2,
    stepHeight: ppt / 2,
  };
}

function lidForOpening(panelName: string, opening: LoungeOpening, ppt: number, sourceBounds: LoungeBounds2D, loungeHeight: number): LoungeLid {
  const width = Math.max(0, opening.width - LID_CLEARANCE_EACH_SIDE * 2);
  const depth = Math.max(0, opening.depth - LID_CLEARANCE_EACH_SIDE * 2);
  const x0 = sourceBounds.x0 + opening.x0 + LID_CLEARANCE_EACH_SIDE;
  const y0 = sourceBounds.y0 + opening.y0 + LID_CLEARANCE_EACH_SIDE;
  return {
    id: `${opening.panelId}_lid`,
    name: `${panelName} Lid`,
    kind: "lid",
    profilePlane: "XY",
    width,
    depth,
    thickness: ppt,
    radius: OPENING_RADIUS - LID_CLEARANCE_EACH_SIDE,
    stepWidth: ppt / 2,
    stepHeight: ppt / 2,
    fingerHoleDiameter: FINGER_HOLE_DIAMETER,
    fingerHole: {
      diameter: FINGER_HOLE_DIAMETER,
      centerX: width / 2,
      centerY: depth / 2,
      through: true,
    },
    placement: {
      x0,
      x1: x0 + width,
      y0,
      y1: y0 + depth,
      z0: loungeHeight - ppt,
      z1: loungeHeight,
    },
    outer: [[0, 0], [width, 0], [width, depth], [0, depth], [0, 0]],
  };
}

function addTopPanel(
  panels: LoungePanel[],
  openings: LoungeOpening[],
  lids: LoungeLid[],
  id: string,
  name: string,
  width: number,
  depth: number,
  ppt: number,
  sourceBounds: LoungeBounds2D,
  loungeHeight: number,
  topLidEnabled: boolean,
): void {
  const panel: LoungePanel = {
    id,
    name,
    kind: "top_panel",
    profilePlane: "XY",
    width,
    depth,
    height: ppt,
    thickness: ppt,
    outer: [[0, 0], [width, 0], [width, depth], [0, depth], [0, 0]],
    sourceBounds,
    placement: {
      x0: sourceBounds.x0,
      x1: sourceBounds.x1,
      y0: sourceBounds.y0,
      y1: sourceBounds.y1,
      z0: loungeHeight - ppt,
      z1: loungeHeight,
    },
  };
  if (topLidEnabled) {
    const opening = openingForPanel(id, width, depth, ppt);
    panel.opening = opening;
    openings.push(opening);
    lids.push(lidForOpening(name, opening, ppt, sourceBounds, loungeHeight));
  }
  panels.push(panel);
}

function loungeWarnings(state: LoungeSettings): string[] {
  const warnings: string[] = [];
  const ppt = Math.max(1, state.partitionPanelThickness);
  if (!(state.lWidth < state.mainWidth)) warnings.push("L Width should be less than Main Width for a valid L footprint.");
  if (state.style !== "L_SHAPE") warnings.push("Only L-Shaped Lounge is implemented in this phase.");
  if (state.lFrontAccess !== "NONE") warnings.push("Drawer/Flap access is a UI placeholder and does not affect geometry yet.");
  if (state.wheelAvoidanceEnabled) {
    if (!(state.avoidanceDepth < Math.min(state.mainDepth, state.lDepth))) {
      warnings.push("Avoidance Depth must be less than both Main Depth and L Depth.");
    }
    if (!(state.avoidanceHeight < state.height - ppt)) {
      warnings.push("Avoidance Height must be less than Height - PPT.");
    }
  }
  return warnings;
}

function sidePanelOuter(
  sideDepth: number,
  panelHeight: number,
  cutout: "none" | "rear" | "front",
  AD: number,
  AH: number,
): number[][] {
  if (cutout === "rear" && AD > 0 && AH > 0 && AD < sideDepth && AH < panelHeight) {
    return [[AD, 0], [sideDepth, 0], [sideDepth, panelHeight], [0, panelHeight], [0, AH], [AD, AH], [AD, 0]];
  }
  if (cutout === "front" && AD > 0 && AH > 0 && AD < sideDepth && AH < panelHeight) {
    return [
      [0, 0], [sideDepth - AD, 0], [sideDepth - AD, AH], [sideDepth, AH],
      [sideDepth, panelHeight], [0, panelHeight], [0, 0],
    ];
  }
  return [[0, 0], [sideDepth, 0], [sideDepth, panelHeight], [0, panelHeight], [0, 0]];
}

function addAxisAlignedIBox(
  panels: LoungePanel[],
  openings: LoungeOpening[],
  lids: LoungeLid[],
  state: LoungeSettings,
  ppt: number,
  panelHeight: number,
  prefix: "main" | "l",
  label: "Main" | "L",
  bounds: LoungeBounds2D,
  innerSide: "left" | "right",
  cutoutEnd: "none" | "rear" | "front",
): void {
  const W = Math.max(0, bounds.x1 - bounds.x0);
  const D = Math.max(0, bounds.y1 - bounds.y0);
  const AD = Math.max(0, state.avoidanceDepth);
  const AH = Math.max(0, state.avoidanceHeight);
  const sideDepth = Math.max(0, D - ppt);
  const hasCutout = cutoutEnd !== "none"
    && AD > 0 && AD < D && AH > 0 && AH < panelHeight;
  const end = hasCutout ? cutoutEnd : "none";
  const leftCut = innerSide === "left" ? end : "none";
  const rightCut = innerSide === "right" ? end : "none";
  const note = hasCutout ? "Inner-corner wheel avoidance cutout applied." : undefined;

  panels.push({
    id: `${prefix}_front`,
    name: `${label} Front`,
    kind: "front_panel",
    profilePlane: "XZ",
    width: W,
    height: panelHeight,
    depth: ppt,
    thickness: ppt,
    placement: {
      x0: bounds.x0,
      x1: bounds.x1,
      y0: Math.max(bounds.y0, bounds.y1 - ppt),
      y1: bounds.y1,
      z0: 0,
      z1: panelHeight,
    },
    outer: [[0, 0], [W, 0], [W, panelHeight], [0, panelHeight], [0, 0]],
  });

  const leftId = prefix === "l"
    ? (innerSide === "left" ? "l_inner_side" : "l_side")
    : "main_left_side";
  const rightId = prefix === "l"
    ? (innerSide === "right" ? "l_inner_side" : "l_side")
    : "main_right_side";
  const leftName = prefix === "l"
    ? (innerSide === "left" ? "L Inner Side" : "L Side")
    : "Main Left Side";
  const rightName = prefix === "l"
    ? (innerSide === "right" ? "L Inner Side" : "L Side")
    : "Main Right Side";

  panels.push({
    id: leftId,
    name: leftName,
    kind: "side_panel",
    profilePlane: "YZ",
    width: sideDepth,
    height: panelHeight,
    depth: ppt,
    thickness: ppt,
    note: leftCut !== "none" ? note : undefined,
    placement: {
      x0: bounds.x0,
      x1: bounds.x0 + ppt,
      y0: bounds.y0,
      y1: bounds.y0 + sideDepth,
      z0: 0,
      z1: panelHeight,
    },
    outer: sidePanelOuter(sideDepth, panelHeight, leftCut, AD, AH),
  });
  panels.push({
    id: rightId,
    name: rightName,
    kind: "side_panel",
    profilePlane: "YZ",
    width: sideDepth,
    height: panelHeight,
    depth: ppt,
    thickness: ppt,
    note: rightCut !== "none" ? note : undefined,
    placement: {
      x0: bounds.x1 - ppt,
      x1: bounds.x1,
      y0: bounds.y0,
      y1: bounds.y0 + sideDepth,
      z0: 0,
      z1: panelHeight,
    },
    outer: sidePanelOuter(sideDepth, panelHeight, rightCut, AD, AH),
  });

  addTopPanel(panels, openings, lids, `${prefix}_top`, `${label} Top`, W, D, ppt, bounds, state.height, state.topLidEnabled);

  if (!hasCutout || !(AH > ppt)) return;
  const coverW = Math.min(AD, W);
  if (end === "front") {
    const x0 = innerSide === "right" ? bounds.x1 - coverW : bounds.x0;
    const x1 = innerSide === "right" ? bounds.x1 : bounds.x0 + coverW;
    panels.push({
      id: `${prefix === "main" ? "M" : "L"}_AT`,
      name: `${label} Avoidance Top`,
      kind: "avoidance_top",
      profilePlane: "XY",
      width: coverW,
      depth: AD,
      thickness: ppt,
      placement: { x0, x1, y0: bounds.y1 - AD, y1: bounds.y1, z0: AH - ppt, z1: AH },
      outer: [[0, 0], [coverW, 0], [coverW, AD], [0, AD], [0, 0]],
    });
    panels.push({
      id: `${prefix === "main" ? "M" : "L"}_AF`,
      name: `${label} Avoidance Front`,
      kind: "avoidance_front",
      profilePlane: "XZ",
      width: coverW,
      height: AH - ppt,
      thickness: ppt,
      placement: { x0, x1, y0: bounds.y1 - AD, y1: bounds.y1 - AD + ppt, z0: 0, z1: AH - ppt },
      outer: [[0, 0], [coverW, 0], [coverW, AH - ppt], [0, AH - ppt], [0, 0]],
    });
    return;
  }
  const x0 = innerSide === "left" ? bounds.x0 : bounds.x1 - coverW;
  const x1 = innerSide === "left" ? bounds.x0 + coverW : bounds.x1;
  panels.push({
    id: `${prefix === "main" ? "M" : "L"}_AT`,
    name: `${label} Avoidance Top`,
    kind: "avoidance_top",
    profilePlane: "XY",
    width: coverW,
    depth: AD,
    thickness: ppt,
    placement: { x0, x1, y0: bounds.y0, y1: bounds.y0 + AD, z0: AH - ppt, z1: AH },
    outer: [[0, 0], [coverW, 0], [coverW, AD], [0, AD], [0, 0]],
  });
  panels.push({
    id: `${prefix === "main" ? "M" : "L"}_AF`,
    name: `${label} Avoidance Front`,
    kind: "avoidance_front",
    profilePlane: "XZ",
    width: coverW,
    height: AH - ppt,
    thickness: ppt,
    placement: { x0, x1, y0: bounds.y0 + AD - ppt, y1: bounds.y0 + AD, z0: 0, z1: AH - ppt },
    outer: [[0, 0], [coverW, 0], [coverW, AH - ppt], [0, AH - ppt], [0, 0]],
  });
}

function parallelWarnings(state: LoungeSettings): string[] {
  const warnings: string[] = [];
  const gap = state.totalWidth - state.singleLoungeWidth * 2;
  if (gap < 0) warnings.push("Left and Right sections overlap: Total Width must be at least 2 x Single Lounge Width.");
  if (state.wheelAvoidanceEnabled) {
    if (!(state.avoidanceDepth < state.depth)) warnings.push("Avoidance Depth must be less than Depth.");
    if (!(state.avoidanceHeight < state.height - state.partitionPanelThickness)) warnings.push("Avoidance Height must be less than Height - PPT.");
  }
  if (state.hasMiddleCabinet) {
    const mc = state.middleCabinet;
    if (state.wheelAvoidanceEnabled && !(mc.startHeight > state.avoidanceHeight)) {
      warnings.push("Middle cabinet start height must be greater than avoidance height.");
    }
    if (mc.width > Math.max(0, gap)) warnings.push("Middle cabinet width exceeds the middle gap.");
    if (mc.depth > state.depth) warnings.push("Middle cabinet depth exceeds lounge depth.");
    if (!(mc.width > 3 * mc.doorClearance)) warnings.push("Middle cabinet width must exceed 3 x door clearance.");
    if (!(mc.height > 2 * mc.doorClearance)) warnings.push("Middle cabinet height must exceed 2 x door clearance.");
    const doorHeight = mc.height - 2 * mc.doorClearance;
    if (!(mc.hingeSideDistance * 2 < doorHeight)) warnings.push("Hinge side distance is too large for the door height.");
  }
  return warnings;
}

function addParallelSection(
  panels: LoungePanel[],
  openings: LoungeOpening[],
  lids: LoungeLid[],
  state: LoungeSettings,
  ppt: number,
  panelHeight: number,
  prefix: "left" | "right",
  label: "Left" | "Right",
): void {
  const D = state.depth;
  const SW = state.singleLoungeWidth;
  const isLeft = prefix === "left";
  const xStart = isLeft ? 0 : state.totalWidth - SW;
  const xEnd = isLeft ? SW : state.totalWidth;
  // Side panel faces the middle gap; support strip sits on the outer end wall.
  const sideX0 = isLeft ? xEnd - ppt : xStart;
  const sideX1 = isLeft ? xEnd : xStart + ppt;
  const frontX0 = isLeft ? xStart : xStart + ppt;
  const frontX1 = isLeft ? xEnd - ppt : xEnd;
  const stripX0 = isLeft ? xStart : xEnd - ppt;
  const stripX1 = isLeft ? xStart + ppt : xEnd;
  const avoidance = state.wheelAvoidanceEnabled === true;
  const AD = Math.max(0, state.avoidanceDepth);
  const AH = Math.max(0, state.avoidanceHeight);

  panels.push({
    id: `${prefix}_front`,
    name: `${label} Front`,
    kind: "front_panel",
    profilePlane: "XZ",
    width: Math.max(0, SW - ppt),
    height: panelHeight,
    depth: ppt,
    thickness: ppt,
    placement: { x0: frontX0, x1: frontX1, y0: 0, y1: ppt, z0: 0, z1: panelHeight },
    outer: [[0, 0], [Math.max(0, SW - ppt), 0], [Math.max(0, SW - ppt), panelHeight], [0, panelHeight], [0, 0]],
  });

  const hasCutout = avoidance && AD > 0 && AD < D && AH > 0 && AH < panelHeight;
  panels.push({
    id: `${prefix}_side`,
    name: `${label} Side`,
    kind: "side_panel",
    profilePlane: "YZ",
    width: D,
    height: panelHeight,
    depth: ppt,
    thickness: ppt,
    placement: { x0: sideX0, x1: sideX1, y0: 0, y1: D, z0: 0, z1: panelHeight },
    outer: hasCutout
      ? [[0, 0], [D - AD, 0], [D - AD, AH], [D, AH], [D, panelHeight], [0, panelHeight], [0, 0]]
      : [[0, 0], [D, 0], [D, panelHeight], [0, panelHeight], [0, 0]],
  });

  addTopPanel(panels, openings, lids, `${prefix}_top`, `${label} Top`, SW, D, ppt, { x0: xStart, x1: xEnd, y0: 0, y1: D }, state.height, state.topLidEnabled);

  panels.push({
    id: `${prefix}_SS`,
    name: `${label} Support Strip`,
    kind: "support_strip",
    profilePlane: "YZ",
    length: Math.max(0, D - ppt),
    height: 100,
    thickness: ppt,
    placement: { x0: stripX0, x1: stripX1, y0: ppt, y1: D, z0: Math.max(0, panelHeight - 100), z1: panelHeight },
    outer: [[0, 0], [Math.max(0, D - ppt), 0], [Math.max(0, D - ppt), 100], [0, 100], [0, 0]],
  });

}

function addParallelAvoidanceCovers(panels: LoungePanel[], state: LoungeSettings, ppt: number): void {
  if (state.wheelAvoidanceEnabled !== true) return;
  const TW = state.totalWidth;
  const D = state.depth;
  const AD = Math.max(0, state.avoidanceDepth);
  const AH = Math.max(0, state.avoidanceHeight);
  if (!(AD > 0 && AH > ppt)) return;
  panels.push({
    id: "PA_TOP",
    name: "Parallel Avoidance Top",
    kind: "avoidance_top",
    profilePlane: "XY",
    width: TW,
    depth: AD,
    thickness: ppt,
    placement: { x0: 0, x1: TW, y0: D - AD, y1: D, z0: AH - ppt, z1: AH },
    outer: [[0, 0], [TW, 0], [TW, AD], [0, AD], [0, 0]],
  });
  panels.push({
    id: "PA_FRONT",
    name: "Parallel Avoidance Front",
    kind: "avoidance_front",
    profilePlane: "XZ",
    width: TW,
    height: AH - ppt,
    thickness: ppt,
    placement: { x0: 0, x1: TW, y0: D - AD, y1: D - AD + ppt, z0: 0, z1: AH - ppt },
    outer: [[0, 0], [TW, 0], [TW, AH - ppt], [0, AH - ppt], [0, 0]],
  });
}

function addMiddleCabinet(panels: LoungePanel[], state: LoungeSettings): void {
  const mc = state.middleCabinet;
  const dpt = Math.max(1, mc.doorPanelThickness);
  const dc = Math.max(0, mc.doorClearance);
  const CW = mc.width;
  const CD = mc.depth;
  const CH = mc.height;
  const CSH = mc.startHeight;
  const x0 = (state.totalWidth - CW) / 2;
  const y0 = state.depth - CD;
  const dividerDepth = Math.max(0, CD - dpt);
  const tongueWidth = dividerDepth / 2;
  const tongueDepth = dpt / 2 - 0.5;
  const dividerBodyWidth = Math.max(0, CW - 2 * dpt);
  // Door slot from the clearance layout | DC | door | DC | door | DC |, then the panels
  // inset one DPT on top/bottom and on the hinge-side outer edge (left edge of the left
  // door, right edge of the right door) so they clear the carcass panels.
  const doorSlotWidth = Math.max(0, (CW - 3 * dc) / 2);
  const doorWidth = Math.max(0, doorSlotWidth - dpt);
  const doorHeight = Math.max(0, CH - 2 * dc - 2 * dpt);

  panels.push({
    id: "MC_BOT",
    name: "Middle Cabinet Bottom",
    kind: "cabinet_bottom",
    profilePlane: "XY",
    width: CW,
    depth: CD,
    thickness: dpt,
    placement: { x0, x1: x0 + CW, y0, y1: state.depth, z0: CSH, z1: CSH + dpt },
    outer: [[0, 0], [CW, 0], [CW, CD], [0, CD], [0, 0]],
  });
  panels.push({
    id: "MC_TOP",
    name: "Middle Cabinet Top",
    kind: "cabinet_top",
    profilePlane: "XY",
    width: CW,
    depth: CD,
    thickness: dpt,
    note: "Cabinet top only. Razor lock bases mount on the mid-shelf underside.",
    placement: { x0, x1: x0 + CW, y0, y1: state.depth, z0: CSH + CH - dpt, z1: CSH + CH },
    outer: [[0, 0], [CW, 0], [CW, CD], [0, CD], [0, 0]],
  });
  const sideHeight = Math.max(0, CH - 2 * dpt);
  // Groove for the mid divider tongue: 0.5mm deeper, 1mm taller, 5mm longer toward -Y than the tongue.
  const grooveX0 = Math.max(0, CD - tongueWidth - 5);
  const grooveY0 = (CH - dpt) / 2 - dpt - 0.5;
  const grooveRect = { x0: grooveX0, y0: grooveY0, x1: CD, y1: grooveY0 + dpt + 1, depth: dpt / 2 };
  panels.push({
    id: "MC_L",
    name: "Middle Cabinet Left",
    kind: "cabinet_side",
    profilePlane: "YZ",
    width: CD,
    height: sideHeight,
    thickness: dpt,
    placement: { x0, x1: x0 + dpt, y0, y1: state.depth, z0: CSH + dpt, z1: CSH + dpt + sideHeight },
    outer: [[0, 0], [CD, 0], [CD, sideHeight], [0, sideHeight], [0, 0]],
    // Inner face of the left side is world X+, which is the local flat top face.
    grooves: [{ id: "MC_L_GR", ...grooveRect, face: "top" }],
  });
  panels.push({
    id: "MC_R",
    name: "Middle Cabinet Right",
    kind: "cabinet_side",
    profilePlane: "YZ",
    width: CD,
    height: sideHeight,
    thickness: dpt,
    placement: { x0: x0 + CW - dpt, x1: x0 + CW, y0, y1: state.depth, z0: CSH + dpt, z1: CSH + dpt + sideHeight },
    outer: [[0, 0], [CD, 0], [CD, sideHeight], [0, sideHeight], [0, 0]],
    // Inner face of the right side is world X-, which is the local flat bottom face.
    grooves: [{ id: "MC_R_GR", ...grooveRect, face: "bottom" }],
  });
  const dividerZ0 = CSH + (CH - dpt) / 2;
  panels.push({
    id: "MC_MID",
    name: "Middle Cabinet Mid Horizontal Divider",
    kind: "cabinet_divider",
    profilePlane: "XY",
    width: dividerBodyWidth,
    depth: dividerDepth,
    thickness: dpt,
    note: "Tongues on both sides, rear half of the divider depth. Razor lock bases mount on this underside.",
    placement: { x0: x0 + dpt, x1: x0 + CW - dpt, y0: y0 + dpt, y1: state.depth, z0: dividerZ0, z1: dividerZ0 + dpt },
    outer: [
      [0, 0],
      [dividerBodyWidth, 0],
      [dividerBodyWidth, dividerDepth - tongueWidth],
      [dividerBodyWidth + tongueDepth, dividerDepth - tongueWidth],
      [dividerBodyWidth + tongueDepth, dividerDepth],
      [-tongueDepth, dividerDepth],
      [-tongueDepth, dividerDepth - tongueWidth],
      [0, dividerDepth - tongueWidth],
      [0, 0],
    ],
  });
  const LOCK_WIDTH = 55;
  const LOCK_HEIGHT = 15.5;
  // lockSideDistance is from the meeting edge; +35mm toward each door's outer side.
  const lockSideDistance = Math.max(0, mc.lockSideDistance) + 35;
  // Kitchen Razor rule: lock center is 30.5mm below the host panel underside.
  // Mid-cab host is the mid shelf (MC_MID) bottom face, not the cabinet top.
  // Door z0 = CSH + dc + dpt; mid-shelf z0 = CSH + (CH - dpt) / 2.
  const lockCenterY = (CH - dpt) / 2 - dc - dpt - 30.5;
  const hingeSide = Math.max(0, mc.hingeSideDistance);
  const hingeEdge = Math.max(0, mc.hingeCupCenterFromEdge);
  const cupDiameter = Math.max(1, mc.hingeCupDiameter);
  const cupDepth = Math.min(Math.max(0.5, mc.hingeCupDepth), dpt);
  const doorCuts = (doorId: string, isLeftDoor: boolean) => {
    // Hinges on the outer vertical edge (side panels), interior door face (local top = y1).
    const hingeCenterX = isLeftDoor ? hingeEdge : doorWidth - hingeEdge;
    const hingeHoles = [
      { id: `${doorId}_hinge_bottom`, centerX: hingeCenterX, centerY: hingeSide, diameter: cupDiameter, depth: cupDepth, face: "top" as const },
      { id: `${doorId}_hinge_top`, centerX: hingeCenterX, centerY: doorHeight - hingeSide, diameter: cupDiameter, depth: cupDepth, face: "top" as const },
    ];
    if (mc.doorLockStyle === "NONE") return { hingeHoles, lockCutouts: [] };
    const lockCenterX = isLeftDoor ? doorWidth - lockSideDistance : lockSideDistance;
    return {
      hingeHoles,
      lockCutouts: [{
        id: `${doorId}_lock`,
        presetId: "razor_long_rounded_1",
        shape: "rounded_slot" as const,
        centerX: lockCenterX,
        centerY: lockCenterY,
        width: LOCK_WIDTH,
        height: LOCK_HEIGHT,
        radius: LOCK_HEIGHT / 2,
        through: true as const,
      }],
    };
  };
  const leftDoorCuts = doorCuts("MC_L_DR", true);
  panels.push({
    id: "MC_L_DR",
    name: "Middle Cabinet Left Door",
    kind: "cabinet_door",
    profilePlane: "XZ",
    width: doorWidth,
    height: doorHeight,
    thickness: dpt,
    placement: { x0: x0 + dc + dpt, x1: x0 + dc + doorSlotWidth, y0, y1: y0 + dpt, z0: CSH + dc + dpt, z1: CSH + dc + dpt + doorHeight },
    outer: [[0, 0], [doorWidth, 0], [doorWidth, doorHeight], [0, doorHeight], [0, 0]],
    hingeHoles: leftDoorCuts.hingeHoles,
    lockCutouts: leftDoorCuts.lockCutouts,
  });
  const rightDoorCuts = doorCuts("MC_R_DR", false);
  panels.push({
    id: "MC_R_DR",
    name: "Middle Cabinet Right Door",
    kind: "cabinet_door",
    profilePlane: "XZ",
    width: doorWidth,
    height: doorHeight,
    thickness: dpt,
    placement: { x0: x0 + dc + doorSlotWidth + dc, x1: x0 + dc + doorSlotWidth + dc + doorWidth, y0, y1: y0 + dpt, z0: CSH + dc + dpt, z1: CSH + dc + dpt + doorHeight },
    outer: [[0, 0], [doorWidth, 0], [doorWidth, doorHeight], [0, doorHeight], [0, 0]],
    hingeHoles: rightDoorCuts.hingeHoles,
    lockCutouts: rightDoorCuts.lockCutouts,
  });
}

function iShapeWarnings(state: LoungeSettings): string[] {
  const warnings: string[] = [];
  const ppt = Math.max(1, state.partitionPanelThickness);
  if (!(state.mainWidth > 2 * ppt)) warnings.push("Width must exceed 2 x PPT for the side panels.");
  if (!(state.mainDepth > 2 * ppt)) warnings.push("Depth must exceed 2 x PPT for the front panel.");
  if (!(state.height > ppt)) warnings.push("Height must exceed PPT.");
  if (state.wheelAvoidanceEnabled) {
    if (!(state.avoidanceDepth < state.mainDepth)) warnings.push("Avoidance Depth must be less than Depth.");
    if (!(state.avoidanceHeight < state.height - ppt)) warnings.push("Avoidance Height must be less than Height - PPT.");
  }
  return warnings;
}

function generateIShapeGeometry(state: LoungeSettings): LoungeGeometryResult {
  const ppt = Math.max(1, state.partitionPanelThickness);
  const panelHeight = Math.max(0, state.height - ppt);
  const W = state.mainWidth;
  const D = state.mainDepth;
  const bounds: LoungeBounds2D = { x0: 0, x1: W, y0: 0, y1: D };
  const panels: LoungePanel[] = [];
  const openings: LoungeOpening[] = [];
  const lids: LoungeLid[] = [];
  const avoidance = state.wheelAvoidanceEnabled === true;
  const AD = Math.max(0, state.avoidanceDepth);
  const AH = Math.max(0, state.avoidanceHeight);
  const hasCutout = avoidance && AD > 0 && AD < D && AH > 0 && AH < panelHeight;

  // Front covers the full width; side panels tuck behind it (y from ppt), matching the L-shape main conventions.
  panels.push({
    id: "i_front",
    name: "I Front",
    kind: "front_panel",
    profilePlane: "XZ",
    width: W,
    height: panelHeight,
    depth: ppt,
    thickness: ppt,
    placement: { x0: 0, x1: W, y0: Math.max(0, D - ppt), y1: D, z0: 0, z1: panelHeight },
    outer: [[0, 0], [W, 0], [W, panelHeight], [0, panelHeight], [0, 0]],
  });

  // Side panels: full YZ rectangles, depth reduced by the front panel.
  // Rear-lower wheel avoidance cutout sits at the wall side (local y = 0).
  const sideDepth = Math.max(0, D - ppt);
  const sideOuter = hasCutout
    ? [[AD, 0], [sideDepth, 0], [sideDepth, panelHeight], [0, panelHeight], [0, AH], [AD, AH], [AD, 0]]
    : [[0, 0], [sideDepth, 0], [sideDepth, panelHeight], [0, panelHeight], [0, 0]];
  const sideNote = hasCutout ? "Rear-lower wheel avoidance cutout applied." : undefined;
  panels.push({
    id: "i_left_side",
    name: "I Left Side",
    kind: "side_panel",
    profilePlane: "YZ",
    width: sideDepth,
    height: panelHeight,
    depth: ppt,
    thickness: ppt,
    note: sideNote,
    placement: { x0: 0, x1: ppt, y0: 0, y1: sideDepth, z0: 0, z1: panelHeight },
    outer: sideOuter.map((point) => [...point]),
  });
  panels.push({
    id: "i_right_side",
    name: "I Right Side",
    kind: "side_panel",
    profilePlane: "YZ",
    width: sideDepth,
    height: panelHeight,
    depth: ppt,
    thickness: ppt,
    note: sideNote,
    placement: { x0: W - ppt, x1: W, y0: 0, y1: sideDepth, z0: 0, z1: panelHeight },
    outer: sideOuter.map((point) => [...point]),
  });

  addTopPanel(panels, openings, lids, "i_top", "I Top", W, D, ppt, bounds, state.height, state.topLidEnabled);

  if (hasCutout && AH > ppt) {
    panels.push({
      id: "I_AT",
      name: "I Avoidance Top",
      kind: "avoidance_top",
      profilePlane: "XY",
      width: W,
      depth: AD,
      thickness: ppt,
      placement: { x0: 0, x1: W, y0: 0, y1: AD, z0: AH - ppt, z1: AH },
      outer: [[0, 0], [W, 0], [W, AD], [0, AD], [0, 0]],
    });
    panels.push({
      id: "I_AF",
      name: "I Avoidance Front",
      kind: "avoidance_front",
      profilePlane: "XZ",
      width: W,
      height: AH - ppt,
      thickness: ppt,
      placement: { x0: 0, x1: W, y0: AD - ppt, y1: AD, z0: 0, z1: AH - ppt },
      outer: [[0, 0], [W, 0], [W, AH - ppt], [0, AH - ppt], [0, 0]],
    });
  }

  return withRelationshipDeclarations({
    meta: { module: "lounge", style: "I_SHAPE", phase: "i_shape_geometry_v1" },
    state,
    footprint: { i: bounds },
    panels,
    openings,
    lids,
    validation: { warnings: iShapeWarnings(state), errors: [] },
  });
}

function generateParallelLoungeGeometry(state: LoungeSettings): LoungeGeometryResult {
  const ppt = Math.max(1, state.partitionPanelThickness);
  const panelHeight = Math.max(0, state.height - ppt);
  const gap = state.totalWidth - state.singleLoungeWidth * 2;
  const panels: LoungePanel[] = [];
  const openings: LoungeOpening[] = [];
  const lids: LoungeLid[] = [];

  addParallelSection(panels, openings, lids, state, ppt, panelHeight, "left", "Left");
  addParallelSection(panels, openings, lids, state, ppt, panelHeight, "right", "Right");
  addParallelAvoidanceCovers(panels, state, ppt);
  if (state.hasMiddleCabinet) addMiddleCabinet(panels, state);

  return withRelationshipDeclarations({
    meta: { module: "lounge", style: "PARALLEL", phase: "parallel_geometry_v1" },
    state,
    footprint: {
      left: { x0: 0, x1: state.singleLoungeWidth, y0: 0, y1: state.depth },
      right: { x0: state.totalWidth - state.singleLoungeWidth, x1: state.totalWidth, y0: 0, y1: state.depth },
      middleGap: gap,
    },
    panels,
    openings,
    lids,
    validation: { warnings: parallelWarnings(state), errors: [] },
  });
}

export function generateLoungeGeometry(input: Partial<LoungeSettings>): LoungeGeometryResult {
  const state = normalizeSettings(input);
  if (state.style === "PARALLEL") return generateParallelLoungeGeometry(state);
  if (state.style === "I_SHAPE") return generateIShapeGeometry(state);
  const ppt = Math.max(1, state.partitionPanelThickness);
  const panelHeight = Math.max(0, state.height - ppt);
  const mainBounds = { x0: 0, x1: state.mainWidth, y0: 0, y1: state.mainDepth };
  const mainVisibleBounds = loungeMainVisibleBounds(state);
  const lBounds = loungeLBounds(state);
  const panels: LoungePanel[] = [];
  const openings: LoungeOpening[] = [];
  const lids: LoungeLid[] = [];
  const AD = Math.max(0, state.avoidanceDepth);
  const AH = Math.max(0, state.avoidanceHeight);
  const hasCutout = state.wheelAvoidanceEnabled === true
    && AD > 0 && AD < Math.min(state.mainDepth, state.lDepth)
    && AH > 0 && AH < panelHeight;
  const mainInner = state.lPosition === "LEFT" ? "left" : "right";
  const lInner = state.lPosition === "LEFT" ? "right" : "left";

  addAxisAlignedIBox(
    panels, openings, lids, state, ppt, panelHeight,
    "main", "Main", mainVisibleBounds, mainInner, hasCutout ? "front" : "none",
  );
  addAxisAlignedIBox(
    panels, openings, lids, state, ppt, panelHeight,
    "l", "L", lBounds, lInner, hasCutout ? "rear" : "none",
  );

  return withRelationshipDeclarations({
    meta: { module: "lounge", style: state.style, phase: "l_shape_two_box_v1" },
    state,
    footprint: {
      main: mainBounds,
      l: lBounds,
      lPosition: state.lPosition,
    },
    panels,
    openings,
    lids,
    validation: { warnings: loungeWarnings(state), errors: [] },
  });
}
