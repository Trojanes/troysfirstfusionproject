"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");

const { rotatePolygon, translatePolygon, normalizePolygonToOrigin } = require("../geometry/polygon_transform.js");
const { boundsOverlap, pointInPolygon, polygonsIntersect, isPolygonInsideRect } = require("../geometry/intersections.js");
const { polygonBounds } = require("../geometry/polygon_basic.js");
const { solveSimpleBottomLeft, solveNestingJob } = require("../solver/simple_bottom_left.js");

function rect(w, h) {
  return [
    { x: 0, y: 0 },
    { x: w, y: 0 },
    { x: w, y: h },
    { x: 0, y: h },
  ];
}

function makePart(id, w, h, rotations) {
  return {
    panelId: id,
    outlineLocal: rect(w, h),
    allowedRotations: rotations || [0, 90, 180, 270],
  };
}

// ---------------------------------------------------------------------------
// Geometry
// ---------------------------------------------------------------------------

test("rotatePolygon 90 swaps extents exactly", () => {
  const rotated = normalizePolygonToOrigin(rotatePolygon(rect(100, 50), 90));
  const bounds = polygonBounds(rotated);
  assert.equal(bounds.width, 50);
  assert.equal(bounds.height, 100);
});

test("translate and normalize round-trip", () => {
  const moved = translatePolygon(rect(10, 10), 55, -20);
  const normalized = normalizePolygonToOrigin(moved);
  const bounds = polygonBounds(normalized);
  assert.deepEqual([bounds.minX, bounds.minY], [0, 0]);
});

test("boundsOverlap honours clearance gap", () => {
  const a = polygonBounds(rect(100, 100));
  const b = polygonBounds(translatePolygon(rect(100, 100), 104, 0));
  assert.equal(boundsOverlap(a, b, 0), false);
  assert.equal(boundsOverlap(a, b, 5), true);
});

test("pointInPolygon and polygonsIntersect basics", () => {
  const square = rect(100, 100);
  assert.equal(pointInPolygon({ x: 50, y: 50 }, square), true);
  assert.equal(pointInPolygon({ x: 150, y: 50 }, square), false);
  const overlapping = translatePolygon(rect(100, 100), 50, 50);
  const separate = translatePolygon(rect(100, 100), 200, 0);
  assert.equal(polygonsIntersect(square, overlapping), true);
  assert.equal(polygonsIntersect(square, separate), false);
  const contained = translatePolygon(rect(10, 10), 40, 40);
  assert.equal(polygonsIntersect(square, contained), true);
});

test("isPolygonInsideRect respects margin", () => {
  const part = translatePolygon(rect(100, 100), 10, 10);
  assert.equal(isPolygonInsideRect(part, 200, 200, 10), true);
  assert.equal(isPolygonInsideRect(part, 200, 200, 20), false);
  assert.equal(isPolygonInsideRect(part, 105, 200, 10), false);
});

// ---------------------------------------------------------------------------
// Solver
// ---------------------------------------------------------------------------

const SHEET = { sheetTypeId: "S1", widthMm: 2400, heightMm: 1200, marginMm: 10 };

test("two parts nest on one sheet without overlap", () => {
  const result = solveSimpleBottomLeft(
    [makePart("A", 1000, 500), makePart("B", 800, 400)],
    SHEET,
    { clearanceMm: 5 }
  );
  assert.equal(result.stats.sheetCount, 1);
  assert.equal(result.unplaced.length, 0);
  const [p1, p2] = result.sheets[0].placements;
  assert.equal(boundsOverlap(p1.bounds, p2.bounds, 0), false);
});

test("oversize part overflows to a second sheet", () => {
  const result = solveSimpleBottomLeft(
    [makePart("A", 2300, 1100), makePart("B", 2300, 1100)],
    SHEET,
    { clearanceMm: 5 }
  );
  assert.equal(result.stats.sheetCount, 2);
  assert.equal(result.unplaced.length, 0);
});

test("part that only fits rotated is rotated", () => {
  const sheet = { widthMm: 600, heightMm: 1100, marginMm: 10 };
  const result = solveSimpleBottomLeft([makePart("A", 1000, 500)], sheet, { clearanceMm: 5 });
  assert.equal(result.unplaced.length, 0);
  assert.equal(result.sheets[0].placements[0].rotation % 180, 90);
});

test("rotation restriction can make a part unplaceable", () => {
  const sheet = { widthMm: 600, heightMm: 1100, marginMm: 10 };
  const result = solveSimpleBottomLeft([makePart("A", 1000, 500, [0, 180])], sheet, {});
  assert.equal(result.unplaced.length, 1);
  assert.equal(result.stats.sheetCount, 0);
});

test("clearance is respected between placements", () => {
  const clearance = 20;
  const result = solveSimpleBottomLeft(
    [makePart("A", 500, 500, [0]), makePart("B", 500, 500, [0])],
    SHEET,
    { clearanceMm: clearance }
  );
  const [p1, p2] = result.sheets[0].placements;
  const gapX = Math.max(p2.bounds.minX - p1.bounds.maxX, p1.bounds.minX - p2.bounds.maxX);
  const gapY = Math.max(p2.bounds.minY - p1.bounds.maxY, p1.bounds.minY - p2.bounds.maxY);
  assert.ok(gapX >= clearance - 1e-9 || gapY >= clearance - 1e-9);
});

test("solver is deterministic", () => {
  const parts = [makePart("A", 900, 600), makePart("B", 700, 300), makePart("C", 400, 400)];
  const a = solveSimpleBottomLeft(parts, SHEET, { clearanceMm: 5 });
  const b = solveSimpleBottomLeft(parts, SHEET, { clearanceMm: 5 });
  assert.deepEqual(
    a.sheets[0].placements.map((p) => [p.panelId, p.x, p.y, p.rotation]),
    b.sheets[0].placements.map((p) => [p.panelId, p.x, p.y, p.rotation])
  );
});

test("solveNestingJob aggregates group stats", () => {
  const job = {
    groups: [
      { groupKey: "g1", parts: [makePart("A", 1000, 500)] },
      { groupKey: "g2", parts: [makePart("B", 800, 400)] },
    ],
  };
  const result = solveNestingJob(job, SHEET, { clearanceMm: 5 });
  assert.equal(result.groups.length, 2);
  assert.equal(result.stats.sheetCount, 2);
  assert.equal(result.stats.unplacedCount, 0);
  assert.ok(result.stats.utilization > 0);
});
