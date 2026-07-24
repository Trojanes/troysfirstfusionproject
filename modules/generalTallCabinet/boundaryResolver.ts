import type {
  BoundaryResult,
  BoundaryType,
  FunctionalZone,
  ZoneBoundaryResolution,
  ZoneLike,
} from "./types.ts";

const TOP_SYSTEM: ZoneLike = { id: "top_system", type: "top_system" };
const BOTTOM_SYSTEM: ZoneLike = { id: "bottom_system", type: "bottom_system" };

function isFunctionalZone(zone: ZoneLike): zone is FunctionalZone {
  return zone.type !== "top_system" && zone.type !== "bottom_system";
}

function zoneId(zone: ZoneLike): string {
  return "id" in zone && zone.id ? String(zone.id) : String(zone.type);
}

function fullZi(reason: string): Omit<BoundaryResult, "index" | "aboveZoneId" | "belowZoneId"> {
  return { boundaryType: "full_zi", reason };
}

function none(reason: string): Omit<BoundaryResult, "index" | "aboveZoneId" | "belowZoneId"> {
  return { boundaryType: "none", reason };
}

function halfZi(reason: string): Omit<BoundaryResult, "index" | "aboveZoneId" | "belowZoneId"> {
  return { boundaryType: "half_zi", reason };
}

export function resolveBoundary(
  aboveZone: ZoneLike,
  belowZone: ZoneLike,
): Omit<BoundaryResult, "index" | "aboveZoneId" | "belowZoneId"> {
  if (!aboveZone || !belowZone) {
    throw new Error("resolveBoundary requires aboveZone and belowZone.");
  }

  if (aboveZone.type === "top_system") {
    return none("Top System already provides the upper structural interface.");
  }

  if (belowZone.type === "bottom_system") {
    return none("Bottom System already provides the lower structural interface.");
  }

  if (aboveZone.type === "blank_panel") {
    return none("Blank Panel above does not force a lower top boundary.");
  }

  if (aboveZone.type === "drawer" && belowZone.type === "drawer") {
    return halfZi("Drawer to drawer uses half Zi support.");
  }

  if (aboveZone.type === "top_flap") {
    return fullZi("Top flap bottom requires full Zi.");
  }

  if (
    aboveZone.type === "side_door" ||
    aboveZone.type === "double_door" ||
    aboveZone.type === "drawer" ||
    aboveZone.type === "open_space" ||
    aboveZone.type === "open_appliance" ||
    aboveZone.type === "fridge" ||
    aboveZone.type === "bottom_flap"
  ) {
    return fullZi(`${aboveZone.type} bottom rule requires full Zi.`);
  }

  return none("No boundary panel required by resolver rules.");
}

function makeBoundary(index: number, aboveZone: ZoneLike, belowZone: ZoneLike): BoundaryResult {
  const base = resolveBoundary(aboveZone, belowZone);
  return {
    index,
    aboveZoneId: zoneId(aboveZone),
    belowZoneId: zoneId(belowZone),
    ...base,
  };
}

function forceFullZiForDivider(boundary: BoundaryResult, doubleDoorId: string): BoundaryResult {
  if (boundary.boundaryType === "full_zi") {
    return {
      ...boundary,
      reason: `${boundary.reason} Double-door vertical divider support requires full Zi.`,
    };
  }

  return {
    ...boundary,
    boundaryType: "full_zi",
    reason: `Double-door vertical divider in ${doubleDoorId} requires full-depth structural support.`,
    upgradedByDoubleDoorDivider: true,
  };
}

function applyDoubleDoorDividerUpgrade(
  boundary: BoundaryResult,
  aboveZone: ZoneLike,
  belowZone: ZoneLike,
): BoundaryResult {
  if (isFunctionalZone(belowZone) && belowZone.type === "double_door" && belowZone.verticalDivider) {
    if (aboveZone.type !== "top_system") {
      return forceFullZiForDivider(boundary, belowZone.id);
    }
  }

  if (isFunctionalZone(aboveZone) && aboveZone.type === "double_door" && aboveZone.verticalDivider) {
    if (belowZone.type !== "bottom_system") {
      return forceFullZiForDivider(boundary, aboveZone.id);
    }
  }

  return boundary;
}

function validateZones(zones: FunctionalZone[]): { errors: string[]; warnings: string[] } {
  const errors: string[] = [];
  const warnings: string[] = [];

  if (!Array.isArray(zones)) {
    throw new Error("resolveZoneBoundaries requires an array of functional zones.");
  }

  zones.forEach((zone, index) => {
    if (!zone || typeof zone !== "object") {
      errors.push(`Zone at index ${index} is missing or invalid.`);
      return;
    }

    if (!(Number(zone.height) > 0)) {
      errors.push(`Zone ${zone.id || index} height must be > 0.`);
    }

    if (zone.type === "top_flap" && index !== zones.length - 1) {
      warnings.push(
        "Top flap is not the highest functional zone; hinge semantics still apply but verify the layout is intentional.",
      );
    }

    if (zone.type === "bottom_flap" && index !== 0) {
      warnings.push(
        "Bottom flap is not the lowest functional zone; hinge semantics still apply but verify the layout is intentional.",
      );
    }
  });

  return { errors, warnings };
}

export function resolveZoneBoundaries(zones: FunctionalZone[]): ZoneBoundaryResolution {
  const validation = validateZones(zones);
  const boundaries: BoundaryResult[] = [];
  const debugBoundaries: BoundaryResult[] = [];

  if (zones.length > 0) {
    const topDebug = makeBoundary(-1, TOP_SYSTEM, zones[0]);
    debugBoundaries.push(applyDoubleDoorDividerUpgrade(topDebug, TOP_SYSTEM, zones[0]));
  }

  for (let index = 0; index < zones.length - 1; index += 1) {
    const aboveZone = zones[index];
    const belowZone = zones[index + 1];
    const boundary = makeBoundary(index, aboveZone, belowZone);
    boundaries.push(applyDoubleDoorDividerUpgrade(boundary, aboveZone, belowZone));
  }

  if (zones.length > 0) {
    const lastIndex = zones.length - 1;
    const bottomDebug = makeBoundary(lastIndex, zones[lastIndex], BOTTOM_SYSTEM);
    debugBoundaries.push(applyDoubleDoorDividerUpgrade(bottomDebug, zones[lastIndex], BOTTOM_SYSTEM));
  }

  return {
    boundaries,
    debugBoundaries,
    errors: validation.errors,
    warnings: validation.warnings,
  };
}

export type { BoundaryResult, BoundaryType, FunctionalZone, ZoneBoundaryResolution, ZoneLike };
