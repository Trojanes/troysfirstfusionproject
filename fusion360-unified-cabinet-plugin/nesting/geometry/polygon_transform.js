"use strict";

/**
 * Rigid 2D transforms for nesting polygons. Points are {x, y} mm.
 * Rotations are restricted to 0/90/180/270 and computed exactly (no trig
 * rounding error).
 */

function rotatePoint(point, rotationDeg) {
  switch (((rotationDeg % 360) + 360) % 360) {
    case 90:
      return { x: -point.y, y: point.x };
    case 180:
      return { x: -point.x, y: -point.y };
    case 270:
      return { x: point.y, y: -point.x };
    default:
      return { x: point.x, y: point.y };
  }
}

function rotatePolygon(polygon, rotationDeg) {
  return (polygon || []).map((p) => rotatePoint(p, rotationDeg));
}

function translatePolygon(polygon, dx, dy) {
  return (polygon || []).map((p) => ({ x: p.x + dx, y: p.y + dy }));
}

/** Translate so the polygon's bounding-box min corner sits at (0, 0). */
function normalizePolygonToOrigin(polygon) {
  if (!Array.isArray(polygon) || polygon.length === 0) return [];
  let minX = Infinity;
  let minY = Infinity;
  for (const p of polygon) {
    if (p.x < minX) minX = p.x;
    if (p.y < minY) minY = p.y;
  }
  return translatePolygon(polygon, -minX, -minY);
}

const api = { rotatePoint, rotatePolygon, translatePolygon, normalizePolygonToOrigin };

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== "undefined") {
  globalThis.CabinetNesting = Object.assign(globalThis.CabinetNesting || {}, {
    polygonTransform: api,
  });
}
