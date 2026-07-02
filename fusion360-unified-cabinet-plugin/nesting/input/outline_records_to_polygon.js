"use strict";

/**
 * Convert millingSurfaceSvg.outline[] records into one clean nesting polygon.
 *
 * Uses record.pointsLocal ONLY (canonical face-local mm). record.points2d is
 * display-space (origin-shifted + Y-flipped) and must never be used here.
 */

const polygonBasic = (typeof require === "function")
  ? require("../geometry/polygon_basic.js")
  : (globalThis.CabinetNesting || {}).polygonBasic;

const POINT_EPS_MM = 1e-3;
const MIN_AREA_MM2 = 1.0;

function samePoint(a, b, eps) {
  const tol = eps == null ? POINT_EPS_MM : eps;
  return Math.abs(a.x - b.x) <= tol && Math.abs(a.y - b.y) <= tol;
}

function toPointXY(raw) {
  if (Array.isArray(raw)) {
    return { x: Number(raw[0]), y: Number(raw[1]) };
  }
  if (raw && typeof raw === "object") {
    return { x: Number(raw.x), y: Number(raw.y) };
  }
  return { x: NaN, y: NaN };
}

/**
 * @param {Array} outlineRecords metadata.millingSurfaceSvg.outline
 * @returns {{polygon: Array<{x:number,y:number}>, issues: string[]}}
 */
function outlineRecordsToPolygon(outlineRecords) {
  if (!Array.isArray(outlineRecords) || outlineRecords.length === 0) {
    return { polygon: [], issues: ["missing_outline_records"] };
  }

  const sorted = [...outlineRecords].sort(
    (a, b) => (a.segIndex ?? 0) - (b.segIndex ?? 0)
  );
  const points = [];

  for (const record of sorted) {
    const pts = record.pointsLocal;
    if (!Array.isArray(pts) || pts.length === 0) {
      return {
        polygon: [],
        issues: [`outline_segment_${record.segIndex ?? "?"}_missing_pointsLocal`],
      };
    }
    for (const raw of pts) {
      const next = toPointXY(raw);
      if (!Number.isFinite(next.x) || !Number.isFinite(next.y)) {
        return {
          polygon: [],
          issues: [`outline_segment_${record.segIndex ?? "?"}_invalid_point`],
        };
      }
      if (points.length === 0 || !samePoint(points[points.length - 1], next)) {
        points.push(next);
      }
    }
  }

  // Drop an explicit closing duplicate (polygon is implicitly closed).
  if (points.length > 1 && samePoint(points[0], points[points.length - 1])) {
    points.pop();
  }

  if (points.length < 3) {
    return { polygon: points, issues: ["outline_too_few_unique_points"] };
  }

  const area = polygonBasic ? polygonBasic.polygonArea(points) : NaN;
  if (Number.isFinite(area) && area < MIN_AREA_MM2) {
    return { polygon: points, issues: ["outline_area_near_zero"] };
  }

  return { polygon: points, issues: [] };
}

const api = { outlineRecordsToPolygon, samePoint, POINT_EPS_MM, MIN_AREA_MM2 };

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== "undefined") {
  globalThis.CabinetNesting = Object.assign(globalThis.CabinetNesting || {}, {
    outlineRecordsToPolygon: api,
  });
}
