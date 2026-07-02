"use strict";

/**
 * Deterministic first solver: bottom-left style candidate placement.
 *
 * Geometry only — no manufacturing rules in here (face-up / flip / banding are
 * resolved by a later manufacturing-correction stage). Clearance between parts
 * is enforced at bounding-box level, which is exact for rectangular panels and
 * conservative for notched outlines. Proper polygon offsetting (kerf) arrives
 * with the NFP solver.
 */

let polygonBasic;
let polygonTransform;
let intersections;
if (typeof require === "function") {
  polygonBasic = require("../geometry/polygon_basic.js");
  polygonTransform = require("../geometry/polygon_transform.js");
  intersections = require("../geometry/intersections.js");
} else {
  const ns = globalThis.CabinetNesting || {};
  polygonBasic = ns.polygonBasic;
  polygonTransform = ns.polygonTransform;
  intersections = ns.intersections;
}

const { polygonArea, polygonBounds } = polygonBasic;
const { rotatePolygon, translatePolygon, normalizePolygonToOrigin } = polygonTransform;
const { boundsOverlap, polygonsIntersect, isPolygonInsideRect } = intersections;

const DEFAULT_MAX_SHEETS = 100;

function orientationsForPart(part) {
  const rotations = Array.isArray(part.allowedRotations) && part.allowedRotations.length
    ? part.allowedRotations
    : [0];
  return rotations.map((rotation) => {
    const polygon = normalizePolygonToOrigin(rotatePolygon(part.outlineLocal, rotation));
    return { rotation, polygon, bounds: polygonBounds(polygon) };
  });
}

function candidatePoints(placements, marginMm, clearanceMm) {
  const candidates = [{ x: marginMm, y: marginMm }];
  for (const placed of placements) {
    const b = placed.bounds;
    candidates.push({ x: b.maxX + clearanceMm, y: b.minY });
    candidates.push({ x: b.minX, y: b.maxY + clearanceMm });
    candidates.push({ x: b.maxX + clearanceMm, y: marginMm });
    candidates.push({ x: marginMm, y: b.maxY + clearanceMm });
  }
  return candidates;
}

function conflicts(candidatePolygon, candidateBounds, placements, clearanceMm) {
  for (const placed of placements) {
    if (!boundsOverlap(candidateBounds, placed.bounds, clearanceMm)) continue;
    // Bounds already violate clearance; for rectangles this is exact. Run the
    // polygon test only to allow genuinely non-overlapping concave cases at
    // zero clearance.
    if (clearanceMm > 0) return true;
    if (polygonsIntersect(candidatePolygon, placed.transformedOutline)) return true;
  }
  return false;
}

function placementScore(candidateBounds, placements, marginMm) {
  let usedX = candidateBounds.maxX;
  let usedY = candidateBounds.maxY;
  for (const placed of placements) {
    if (placed.bounds.maxX > usedX) usedX = placed.bounds.maxX;
    if (placed.bounds.maxY > usedY) usedY = placed.bounds.maxY;
  }
  return (usedX - marginMm) * 2 + (usedY - marginMm);
}

function tryPlaceOnSheet(part, orientations, sheetState, sheetSpec, clearanceMm) {
  const marginMm = sheetSpec.marginMm || 0;
  const candidates = candidatePoints(sheetState.placements, marginMm, clearanceMm);
  let best = null;

  for (const orientation of orientations) {
    for (const candidate of candidates) {
      const polygon = translatePolygon(orientation.polygon, candidate.x, candidate.y);
      const bounds = polygonBounds(polygon);
      if (!isPolygonInsideRect(polygon, sheetSpec.widthMm, sheetSpec.heightMm, marginMm)) {
        continue;
      }
      if (conflicts(polygon, bounds, sheetState.placements, clearanceMm)) continue;

      const score = placementScore(bounds, sheetState.placements, marginMm);
      if (
        best === null ||
        score < best.score - 1e-9 ||
        (Math.abs(score - best.score) <= 1e-9 &&
          (candidate.y < best.y - 1e-9 ||
            (Math.abs(candidate.y - best.y) <= 1e-9 && candidate.x < best.x - 1e-9)))
      ) {
        best = {
          score,
          x: candidate.x,
          y: candidate.y,
          rotation: orientation.rotation,
          polygon,
          bounds,
        };
      }
    }
  }

  if (!best) return null;
  const placement = {
    panelId: part.panelId,
    sheetId: sheetState.sheetId,
    x: best.x,
    y: best.y,
    rotation: best.rotation,
    flipped: false,
    transformedOutline: best.polygon,
    bounds: best.bounds,
    solver: "simpleBottomLeft",
  };
  sheetState.placements.push(placement);
  return placement;
}

/**
 * Nest one group of parts onto copies of a single sheet spec.
 *
 * @param {Array} parts NestPart[]
 * @param {Object} sheetSpec { sheetTypeId?, widthMm, heightMm, marginMm }
 * @param {Object} [options] { clearanceMm?: number, maxSheets?: number }
 * @returns {{sheets: Array, unplaced: Array, stats: Object}}
 */
function solveSimpleBottomLeft(parts, sheetSpec, options) {
  const opts = options || {};
  const clearanceMm = Number.isFinite(opts.clearanceMm) ? opts.clearanceMm : 5;
  const maxSheets = opts.maxSheets || DEFAULT_MAX_SHEETS;

  const sorted = [...(parts || [])].sort(
    (a, b) => polygonArea(b.outlineLocal) - polygonArea(a.outlineLocal)
  );

  const sheets = [];
  const unplaced = [];
  let totalPartArea = 0;

  for (const part of sorted) {
    if (!Array.isArray(part.outlineLocal) || part.outlineLocal.length < 3) {
      unplaced.push(part);
      continue;
    }
    const orientations = orientationsForPart(part);
    let placed = null;

    for (const sheetState of sheets) {
      placed = tryPlaceOnSheet(part, orientations, sheetState, sheetSpec, clearanceMm);
      if (placed) break;
    }
    if (!placed && sheets.length < maxSheets) {
      const sheetState = {
        sheetId: "SHEET-{0}".replace("{0}", String(sheets.length + 1).padStart(2, "0")),
        sheet: { ...sheetSpec },
        placements: [],
      };
      placed = tryPlaceOnSheet(part, orientations, sheetState, sheetSpec, clearanceMm);
      if (placed) {
        sheets.push(sheetState);
      }
    }
    if (placed) {
      totalPartArea += polygonArea(part.outlineLocal);
    } else {
      unplaced.push(part);
    }
  }

  const sheetArea = sheetSpec.widthMm * sheetSpec.heightMm;
  const totalSheetArea = sheetArea * sheets.length;
  return {
    sheets,
    unplaced,
    stats: {
      sheetCount: sheets.length,
      totalPartAreaMm2: Math.round(totalPartArea),
      totalSheetAreaMm2: Math.round(totalSheetArea),
      utilization: totalSheetArea > 0 ? totalPartArea / totalSheetArea : 0,
    },
  };
}

/**
 * Run the solver for every group of a NestingInputJob.
 */
function solveNestingJob(job, sheetSpec, options) {
  const groups = [];
  let sheetCount = 0;
  let partArea = 0;
  let sheetArea = 0;
  let unplacedCount = 0;

  for (const group of (job && job.groups) || []) {
    const result = solveSimpleBottomLeft(group.parts, sheetSpec, options);
    groups.push({ groupKey: group.groupKey, ...result });
    sheetCount += result.stats.sheetCount;
    partArea += result.stats.totalPartAreaMm2;
    sheetArea += result.stats.totalSheetAreaMm2;
    unplacedCount += result.unplaced.length;
  }

  return {
    solver: "simpleBottomLeft",
    groups,
    stats: {
      sheetCount,
      totalPartAreaMm2: partArea,
      totalSheetAreaMm2: sheetArea,
      utilization: sheetArea > 0 ? partArea / sheetArea : 0,
      unplacedCount,
    },
  };
}

const api = { solveSimpleBottomLeft, solveNestingJob };

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== "undefined") {
  globalThis.CabinetNesting = Object.assign(globalThis.CabinetNesting || {}, {
    simpleBottomLeft: api,
  });
}
