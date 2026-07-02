"use strict";

/**
 * 2D overlap tests for nesting. Points are {x, y} mm.
 * Pure functions, no state.
 */

let polygonBasic;
if (typeof require === "function") {
  polygonBasic = require("./polygon_basic.js");
} else {
  polygonBasic = (globalThis.CabinetNesting || {}).polygonBasic;
}
const { polygonBounds } = polygonBasic;

function boundsOverlap(a, b, gap) {
  const spacing = gap || 0;
  return !(
    a.maxX + spacing <= b.minX ||
    b.maxX + spacing <= a.minX ||
    a.maxY + spacing <= b.minY ||
    b.maxY + spacing <= a.minY
  );
}

/** Ray-cast point-in-polygon (boundary counts as inside). */
function pointInPolygon(point, polygon) {
  if (!Array.isArray(polygon) || polygon.length < 3) return false;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i, i += 1) {
    const a = polygon[i];
    const b = polygon[j];
    const onEdge =
      Math.min(a.x, b.x) - 1e-9 <= point.x && point.x <= Math.max(a.x, b.x) + 1e-9 &&
      Math.min(a.y, b.y) - 1e-9 <= point.y && point.y <= Math.max(a.y, b.y) + 1e-9 &&
      Math.abs((b.x - a.x) * (point.y - a.y) - (b.y - a.y) * (point.x - a.x)) <= 1e-6;
    if (onEdge) return true;
    if ((a.y > point.y) !== (b.y > point.y)) {
      const xCross = ((b.x - a.x) * (point.y - a.y)) / (b.y - a.y) + a.x;
      if (point.x < xCross) inside = !inside;
    }
  }
  return inside;
}

function orientation(a, b, c) {
  const value = (b.y - a.y) * (c.x - b.x) - (b.x - a.x) * (c.y - b.y);
  if (Math.abs(value) < 1e-9) return 0;
  return value > 0 ? 1 : 2;
}

function onSegment(a, b, c) {
  return (
    Math.min(a.x, c.x) - 1e-9 <= b.x && b.x <= Math.max(a.x, c.x) + 1e-9 &&
    Math.min(a.y, c.y) - 1e-9 <= b.y && b.y <= Math.max(a.y, c.y) + 1e-9
  );
}

function segmentsIntersect(p1, p2, q1, q2) {
  const o1 = orientation(p1, p2, q1);
  const o2 = orientation(p1, p2, q2);
  const o3 = orientation(q1, q2, p1);
  const o4 = orientation(q1, q2, p2);
  if (o1 !== o2 && o3 !== o4) return true;
  if (o1 === 0 && onSegment(p1, q1, p2)) return true;
  if (o2 === 0 && onSegment(p1, q2, p2)) return true;
  if (o3 === 0 && onSegment(q1, p1, q2)) return true;
  if (o4 === 0 && onSegment(q1, p2, q2)) return true;
  return false;
}

/** True when polygon interiors/edges touch (edge crossing or containment). */
function polygonsIntersect(a, b) {
  if (!Array.isArray(a) || a.length < 3 || !Array.isArray(b) || b.length < 3) {
    return false;
  }
  if (!boundsOverlap(polygonBounds(a), polygonBounds(b))) return false;
  for (let i = 0; i < a.length; i += 1) {
    const a1 = a[i];
    const a2 = a[(i + 1) % a.length];
    for (let j = 0; j < b.length; j += 1) {
      if (segmentsIntersect(a1, a2, b[j], b[(j + 1) % b.length])) return true;
    }
  }
  if (pointInPolygon(a[0], b)) return true;
  if (pointInPolygon(b[0], a)) return true;
  return false;
}

function isPolygonInsideRect(polygon, width, height, margin) {
  const inset = margin || 0;
  for (const p of polygon || []) {
    if (p.x < inset - 1e-9 || p.y < inset - 1e-9) return false;
    if (p.x > width - inset + 1e-9 || p.y > height - inset + 1e-9) return false;
  }
  return Array.isArray(polygon) && polygon.length >= 3;
}

const api = {
  boundsOverlap,
  pointInPolygon,
  segmentsIntersect,
  polygonsIntersect,
  isPolygonInsideRect,
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== "undefined") {
  globalThis.CabinetNesting = Object.assign(globalThis.CabinetNesting || {}, {
    intersections: api,
  });
}
