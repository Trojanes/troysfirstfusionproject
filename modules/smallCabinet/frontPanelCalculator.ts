/**
 * Small Cabinet front-panel clearance calculator.
 *
 * Aligns with General Tall / Kitchen neighbor rules:
 * - Side gaps: full frontClearance from cabinet outer edges.
 * - Against top/bottom carcass face: full frontClearance.
 * - Between two front zones sharing a middle board: half clearance from the
 *   middle centerline (doors meet with total FC across the seam).
 */

import type { ResolvedZone, SmallCabinetZoneType } from "./types.ts";

export interface FrontPanelClearanceInput {
  cabinetWidth: number;
  cabinetHeight: number;
  panelThickness: number;
  frontClearance: number;
  zone: ResolvedZone;
  zoneIndex: number;
  zones: ResolvedZone[];
}

export interface FrontPanelBounds {
  x0: number;
  x1: number;
  z0: number;
  z1: number;
  /** How each edge was resolved (debug / tests). */
  sources: {
    x: string;
    z0: string;
    z1: string;
  };
}

function round1(value: number): number {
  return Math.round(value * 10) / 10;
}

function zoneHasFront(type: SmallCabinetZoneType): boolean {
  return type === "left_door" || type === "right_door" || type === "drawer";
}

/**
 * Compute front-panel XZ bounds for one zone (door / drawer face).
 * Y placement (-FPT..0) stays in the generator.
 */
export function computeFrontPanelBounds(input: FrontPanelClearanceInput): FrontPanelBounds {
  const W = input.cabinetWidth;
  const H = input.cabinetHeight;
  const CPT = input.panelThickness;
  const FC = input.frontClearance;
  const { zone, zoneIndex, zones } = input;

  const x0 = round1(FC);
  const x1 = round1(W - FC);

  const above = zoneIndex > 0 ? zones[zoneIndex - 1] : null;
  const below = zoneIndex < zones.length - 1 ? zones[zoneIndex + 1] : null;

  let z0: number;
  let z0Source: string;
  if (below && zoneHasFront(below.type)) {
    // Shared middle centered on this zone's zBottom.
    z0 = round1(zone.zBottom + FC / 2);
    z0Source = "mid_center_plus_half_fc";
  } else {
    // Sit above bottom board top face (or mid top when neighbor has no front).
    z0 = round1(zone.clearZ0 + FC);
    z0Source = below ? "clear_plus_fc_open_neighbor" : "bottom_face_plus_fc";
  }

  let z1: number;
  let z1Source: string;
  if (above && zoneHasFront(above.type)) {
    z1 = round1(zone.zTop - FC / 2);
    z1Source = "mid_center_minus_half_fc";
  } else {
    z1 = round1(zone.clearZ1 - FC);
    z1Source = above ? "clear_minus_fc_open_neighbor" : "top_face_minus_fc";
  }

  // Doors intentionally overlap middle-board thickness when neighbors are fronts
  // (half-FC from mid centerline), matching GT/Kitchen. Do not clamp to clearZ.

  return {
    x0,
    x1,
    z0,
    z1,
    sources: { x: "outer_fc", z0: z0Source, z1: z1Source },
  };
}

export function frontPanelIsValid(bounds: FrontPanelBounds, eps = 1e-6): boolean {
  return bounds.x1 - bounds.x0 > eps && bounds.z1 - bounds.z0 > eps;
}
