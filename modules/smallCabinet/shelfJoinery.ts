/**
 * Small Cabinet shelf / back ↔ side joinery (层板 + 后板锁定).
 *
 * Horizontal boards (TOP / MID / BOTTOM):
 *   - Tongue along depth Y = span/3, centered; insertion through side (CPT).
 *   - Side groove: Y ±5, Z ±0.5.
 *
 * Back board:
 *   - Tongue along height Z = span/3, centered; insertion through side (CPT).
 *   - Side groove: Z ±5, Y ±0.5 (same rule: length axis ±5, thickness axis ±0.5).
 */

import type { Board, ProfilePoint, SmallCabinetFeature } from "./types.ts";

export const SHELF_TONGUE_DEPTH_FRACTION = 1 / 3;
export const GROOVE_LENGTH_OVERSIZE = 5;
export const GROOVE_THICKNESS_OVERSIZE = 0.5;
/** @deprecated alias — horizontal groove Y oversize */
export const GROOVE_Y_OVERSIZE = GROOVE_LENGTH_OVERSIZE;
/** @deprecated alias — horizontal groove Z oversize */
export const GROOVE_Z_OVERSIZE = GROOVE_THICKNESS_OVERSIZE;

export interface ShelfTongueSpec {
  shelfId: string;
  bodyX0: number;
  bodyX1: number;
  y0: number;
  y1: number;
  tongueY0: number;
  tongueY1: number;
  tongueLength: number;
  z0: number;
  z1: number;
}

export interface BackTongueSpec {
  backId: string;
  bodyX0: number;
  bodyX1: number;
  y0: number;
  y1: number;
  z0: number;
  z1: number;
  tongueZ0: number;
  tongueZ1: number;
  tongueLength: number;
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

export function centeredThirdRange(spanStart: number, spanEnd: number): { a0: number; a1: number } {
  const span = spanEnd - spanStart;
  const length = span * SHELF_TONGUE_DEPTH_FRACTION;
  const a0 = round1(spanStart + (span - length) / 2);
  const a1 = round1(a0 + length);
  return { a0, a1 };
}

export function shelfTongueYRange(shelfY0: number, shelfY1: number): { tongueY0: number; tongueY1: number } {
  const { a0, a1 } = centeredThirdRange(shelfY0, shelfY1);
  return { tongueY0: a0, tongueY1: a1 };
}

/** XY outer profile with left/right tongues (world X/Y). */
export function shelfProfileWithTongues(
  bodyX0: number,
  bodyX1: number,
  y0: number,
  y1: number,
  tongueLength: number,
  tongueY0: number,
  tongueY1: number,
): ProfilePoint[] {
  const left = Math.max(0, tongueLength);
  const right = Math.max(0, tongueLength);
  return [
    { x: bodyX0, y: y0 },
    { x: bodyX1, y: y0 },
    { x: bodyX1, y: tongueY0 },
    { x: bodyX1 + right, y: tongueY0 },
    { x: bodyX1 + right, y: tongueY1 },
    { x: bodyX1, y: tongueY1 },
    { x: bodyX1, y: y1 },
    { x: bodyX0, y: y1 },
    { x: bodyX0, y: tongueY1 },
    { x: bodyX0 - left, y: tongueY1 },
    { x: bodyX0 - left, y: tongueY0 },
    { x: bodyX0, y: tongueY0 },
    { x: bodyX0, y: y0 },
  ];
}

/** XZ outer profile with left/right tongues (world X/Z) for back panel. */
export function backProfileWithTongues(
  bodyX0: number,
  bodyX1: number,
  z0: number,
  z1: number,
  tongueLength: number,
  tongueZ0: number,
  tongueZ1: number,
): ProfilePoint[] {
  const left = Math.max(0, tongueLength);
  const right = Math.max(0, tongueLength);
  return [
    { x: bodyX0, z: z0 },
    { x: bodyX1, z: z0 },
    { x: bodyX1, z: tongueZ0 },
    { x: bodyX1 + right, z: tongueZ0 },
    { x: bodyX1 + right, z: tongueZ1 },
    { x: bodyX1, z: tongueZ1 },
    { x: bodyX1, z: z1 },
    { x: bodyX0, z: z1 },
    { x: bodyX0, z: tongueZ1 },
    { x: bodyX0 - left, z: tongueZ1 },
    { x: bodyX0 - left, z: tongueZ0 },
    { x: bodyX0, z: tongueZ0 },
    { x: bodyX0, z: z0 },
  ];
}

export function buildShelfTongueSpec(shelf: Board, panelThickness: number): ShelfTongueSpec {
  const bodyX0 = shelf.x0;
  const bodyX1 = shelf.x1;
  const { tongueY0, tongueY1 } = shelfTongueYRange(shelf.y0, shelf.y1);
  return {
    shelfId: shelf.id,
    bodyX0,
    bodyX1,
    y0: shelf.y0,
    y1: shelf.y1,
    tongueY0,
    tongueY1,
    // Through tongue so side groove reads on the outer face (matches Fusion visual).
    tongueLength: round1(panelThickness),
    z0: shelf.z0,
    z1: shelf.z1,
  };
}

export function buildBackTongueSpec(back: Board, panelThickness: number): BackTongueSpec {
  const { a0: tongueZ0, a1: tongueZ1 } = centeredThirdRange(back.z0, back.z1);
  return {
    backId: back.id,
    bodyX0: back.x0,
    bodyX1: back.x1,
    y0: back.y0,
    y1: back.y1,
    z0: back.z0,
    z1: back.z1,
    tongueZ0,
    tongueZ1,
    tongueLength: round1(panelThickness),
  };
}

export function applyShelfTongues(shelf: Board, spec: ShelfTongueSpec): void {
  shelf.x0 = round1(spec.bodyX0 - spec.tongueLength);
  shelf.x1 = round1(spec.bodyX1 + spec.tongueLength);
  shelf.profileVector = shelfProfileWithTongues(
    spec.bodyX0,
    spec.bodyX1,
    spec.y0,
    spec.y1,
    spec.tongueLength,
    spec.tongueY0,
    spec.tongueY1,
  );
  shelf.notes = [
    ...(shelf.notes || []),
    `Tongues length=${spec.tongueLength} Y=${spec.tongueY0}..${spec.tongueY1} (depth/3, through)`,
  ];
}

export function applyBackTongues(back: Board, spec: BackTongueSpec): void {
  back.x0 = round1(spec.bodyX0 - spec.tongueLength);
  back.x1 = round1(spec.bodyX1 + spec.tongueLength);
  back.profileVector = backProfileWithTongues(
    spec.bodyX0,
    spec.bodyX1,
    spec.z0,
    spec.z1,
    spec.tongueLength,
    spec.tongueZ0,
    spec.tongueZ1,
  );
  back.notes = [
    ...(back.notes || []),
    `Tongues length=${spec.tongueLength} Z=${spec.tongueZ0}..${spec.tongueZ1} (height/3, through)`,
  ];
}

export function buildShelfJoineryFeatures(spec: ShelfTongueSpec): SmallCabinetFeature[] {
  const grooveY0 = round1(spec.tongueY0 - GROOVE_LENGTH_OVERSIZE);
  const grooveY1 = round1(spec.tongueY1 + GROOVE_LENGTH_OVERSIZE);
  const grooveZ0 = round1(spec.z0 - GROOVE_THICKNESS_OVERSIZE);
  const grooveZ1 = round1(spec.z1 + GROOVE_THICKNESS_OVERSIZE);
  const depth = spec.tongueLength;

  return [
    {
      id: `${spec.shelfId}_tongue_L`,
      type: "shelf_tongue",
      targetBoardId: spec.shelfId,
      relatedBoardId: "SIDE_L",
      side: "left",
      y0: spec.tongueY0,
      y1: spec.tongueY1,
      z0: spec.z0,
      z1: spec.z1,
      insertionDepth: depth,
      source: "shelf_joinery",
    },
    {
      id: `${spec.shelfId}_tongue_R`,
      type: "shelf_tongue",
      targetBoardId: spec.shelfId,
      relatedBoardId: "SIDE_R",
      side: "right",
      y0: spec.tongueY0,
      y1: spec.tongueY1,
      z0: spec.z0,
      z1: spec.z1,
      insertionDepth: depth,
      source: "shelf_joinery",
    },
    {
      id: `SIDE_L_${spec.shelfId}_groove`,
      type: "side_groove",
      targetBoardId: "SIDE_L",
      relatedBoardId: spec.shelfId,
      side: "left",
      y0: grooveY0,
      y1: grooveY1,
      z0: grooveZ0,
      z1: grooveZ1,
      depth,
      source: "shelf_joinery",
    },
    {
      id: `SIDE_R_${spec.shelfId}_groove`,
      type: "side_groove",
      targetBoardId: "SIDE_R",
      relatedBoardId: spec.shelfId,
      side: "right",
      y0: grooveY0,
      y1: grooveY1,
      z0: grooveZ0,
      z1: grooveZ1,
      depth,
      source: "shelf_joinery",
    },
  ];
}

export function buildBackJoineryFeatures(spec: BackTongueSpec): SmallCabinetFeature[] {
  const grooveZ0 = round1(spec.tongueZ0 - GROOVE_LENGTH_OVERSIZE);
  const grooveZ1 = round1(spec.tongueZ1 + GROOVE_LENGTH_OVERSIZE);
  const grooveY0 = round1(spec.y0 - GROOVE_THICKNESS_OVERSIZE);
  const grooveY1 = round1(spec.y1 + GROOVE_THICKNESS_OVERSIZE);
  const depth = spec.tongueLength;

  return [
    {
      id: `${spec.backId}_tongue_L`,
      type: "back_tongue",
      targetBoardId: spec.backId,
      relatedBoardId: "SIDE_L",
      side: "left",
      y0: spec.y0,
      y1: spec.y1,
      z0: spec.tongueZ0,
      z1: spec.tongueZ1,
      insertionDepth: depth,
      source: "back_joinery",
    },
    {
      id: `${spec.backId}_tongue_R`,
      type: "back_tongue",
      targetBoardId: spec.backId,
      relatedBoardId: "SIDE_R",
      side: "right",
      y0: spec.y0,
      y1: spec.y1,
      z0: spec.tongueZ0,
      z1: spec.tongueZ1,
      insertionDepth: depth,
      source: "back_joinery",
    },
    {
      id: `SIDE_L_${spec.backId}_groove`,
      type: "side_groove",
      targetBoardId: "SIDE_L",
      relatedBoardId: spec.backId,
      side: "left",
      y0: grooveY0,
      y1: grooveY1,
      z0: grooveZ0,
      z1: grooveZ1,
      depth,
      source: "back_joinery",
    },
    {
      id: `SIDE_R_${spec.backId}_groove`,
      type: "side_groove",
      targetBoardId: "SIDE_R",
      relatedBoardId: spec.backId,
      side: "right",
      y0: grooveY0,
      y1: grooveY1,
      z0: grooveZ0,
      z1: grooveZ1,
      depth,
      source: "back_joinery",
    },
  ];
}

export function attachSideGrooveProfileFeatures(side: Board, features: SmallCabinetFeature[]): void {
  const grooves = features.filter(
    (feature) => feature.type === "side_groove" && feature.targetBoardId === side.id,
  );
  if (!grooves.length) return;
  side.profileFeatures = [
    ...(side.profileFeatures || []),
    ...grooves.map((groove) => ({
      id: groove.id,
      type: "side_groove",
      y0: groove.y0,
      y1: groove.y1,
      z0: groove.z0,
      z1: groove.z1,
      depth: groove.depth,
      relatedBoardId: groove.relatedBoardId,
      source: groove.source,
    })),
  ];
}

/** Apply horizontal tongue/groove joinery and return features. */
export function applyHorizontalJoinery(board: Board, panelThickness: number): SmallCabinetFeature[] {
  const spec = buildShelfTongueSpec(board, panelThickness);
  applyShelfTongues(board, spec);
  return buildShelfJoineryFeatures(spec);
}

/** Apply back tongue/groove joinery and return features. */
export function applyBackJoinery(board: Board, panelThickness: number): SmallCabinetFeature[] {
  const spec = buildBackTongueSpec(board, panelThickness);
  applyBackTongues(board, spec);
  return buildBackJoineryFeatures(spec);
}
