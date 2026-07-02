"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");

const { outlineRecordsToPolygon } = require("../input/outline_records_to_polygon.js");
const { panelToNestPart, resolveRequiredFaceUp } = require("../input/panel_to_nest_part.js");
const { deriveAllowedRotations } = require("../input/derive_allowed_rotations.js");
const {
  makeNestingGroupKey,
  makeConservativeNestingGroupKey,
  groupNestParts,
} = require("../input/group_nest_parts.js");
const { buildNestingInputJob } = require("../input/build_nesting_input_job.js");
const { polygonArea } = require("../geometry/polygon_basic.js");

function makeScanRecord(overrides) {
  const record = {
    entityKind: "body",
    panelId: "ohc.run1.BP",
    bodyName: "OH_BP",
    entityToken: "tok-body",
    derivedTags: { colorTag: "carcass_colour", boardTypeTag: "carcass" },
    metadata: {
      schemaVersion: 1,
      identity: {
        panelId: "ohc.run1.BP",
        generator: "overhead",
        module: "overhead",
        sourceBoardId: "BP",
        sourceBoardType: "bottom",
        boardType: "carcass_bottom",
        runId: "run1",
      },
      defaultAttributes: {
        role: "carcass",
        category: "carcass",
        materialClass: "carcass_board",
        tags: [],
      },
      dimensions: { lengthMm: 2000, widthMm: 400, thicknessMm: 15 },
      millingSurfaceSvg: {
        widthMm: 2000,
        heightMm: 400,
        millingFaceToken: "tok-mill",
        outline: [
          // points2d carries deliberately bogus display values; geometry must
          // come from pointsLocal only.
          { segIndex: 0, edgeToken: "e1", pointsLocal: [[0, 0], [2000, 0]], points2d: [[9999, 9999]] },
          { segIndex: 1, edgeToken: "e2", pointsLocal: [[2000, 0], [2000, 400]], points2d: [[9999, 9999]] },
          { segIndex: 2, edgeToken: "e3", pointsLocal: [[2000, 400], [0, 400]], points2d: [[9999, 9999]] },
          // Adjacent duplicate + explicit closing point exercise cleanup.
          { segIndex: 3, edgeToken: "e4", pointsLocal: [[0, 400], [0, 0], [0, 0]], points2d: [[9999, 9999]] },
        ],
      },
      features: [
        {
          featureId: "FEAT-01",
          cutType: "HALF",
          kind: "groove",
          depthMm: 7.5,
          isCircle: false,
          radiusMm: null,
          center2d: null,
          pointsLocal: [[100, 50], [150, 50], [150, 350], [100, 350]],
          openSurfaceToken: "tok-surf",
        },
        {
          featureId: "FEAT-02",
          cutType: "FULL",
          kind: "hole",
          depthMm: 15,
          isCircle: true,
          radiusMm: 2.5,
          center2d: [500, 200],
          pointsLocal: [],
          openSurfaceToken: "tok-surf",
        },
      ],
      faceRegistry: {
        surfaceMode: "DOUBLE_SIDED",
        faces: [
          { faceId: "F1", faceRole: "carcass_bottom_outer", faceClass: "SURFACE", millingSurface: "MILLING", entityToken: "t1" },
          { faceId: "F2", faceRole: "carcass_bottom_inner", faceClass: "SURFACE", millingSurface: "NON_MILLING", entityToken: "t2" },
        ],
        edges: [],
        edgeGroups: [
          {
            edgeGroupId: "EG-01",
            side: "+X",
            directionHint: "+X",
            bandable: true,
            bandingRequired: false,
            bandingColor: "raw-core",
            edgeIds: ["EDGE-01"],
            faceIds: ["F3"],
            entityTokens: ["t3"],
            memberCount: 1,
            areaMm2: 6000,
          },
        ],
      },
    },
  };
  return Object.assign(record, overrides || {});
}

// ---------------------------------------------------------------------------
// Outline conversion
// ---------------------------------------------------------------------------

test("outline uses pointsLocal only and ignores points2d", () => {
  const record = makeScanRecord();
  const { polygon, issues } = outlineRecordsToPolygon(record.metadata.millingSurfaceSvg.outline);
  assert.equal(issues.length, 0);
  for (const p of polygon) {
    assert.notEqual(p.x, 9999);
  }
  assert.equal(polygonArea(polygon), 2000 * 400);
});

test("adjacent duplicates and closing point are removed", () => {
  const record = makeScanRecord();
  const { polygon } = outlineRecordsToPolygon(record.metadata.millingSurfaceSvg.outline);
  assert.equal(polygon.length, 4);
  assert.deepEqual(polygon[0], { x: 0, y: 0 });
  assert.deepEqual(polygon[3], { x: 0, y: 400 });
});

test("missing pointsLocal fails validation", () => {
  const { polygon, issues } = outlineRecordsToPolygon([
    { segIndex: 0, points2d: [[1, 1], [2, 2]] },
  ]);
  assert.equal(polygon.length, 0);
  assert.match(issues[0], /missing_pointsLocal/);
});

test("too few unique points fails validation", () => {
  const { issues } = outlineRecordsToPolygon([
    { segIndex: 0, pointsLocal: [[0, 0], [100, 0]] },
  ]);
  assert.deepEqual(issues, ["outline_too_few_unique_points"]);
});

// ---------------------------------------------------------------------------
// panelToNestPart
// ---------------------------------------------------------------------------

test("happy path produces a valid part with only grain warning", () => {
  const { part, issues } = panelToNestPart(makeScanRecord());
  assert.ok(part);
  const errors = issues.filter((i) => i.severity === "error");
  assert.equal(errors.length, 0);
  assert.ok(issues.some((i) => i.code === "missing_grainDirection"));
  assert.equal(part.panelId, "ohc.run1.BP");
  assert.equal(part.materialClass, "carcass_board");
  assert.equal(part.thicknessMm, 15);
  assert.equal(part.widthMm, 2000);
  assert.equal(part.heightMm, 400);
  assert.equal(part.outlineLocal.length, 4);
});

test("feature pointsLocal and center2d are preserved in canonical frame", () => {
  const { part } = panelToNestPart(makeScanRecord());
  const groove = part.features[0];
  assert.deepEqual(groove.pointsLocal, [
    { x: 100, y: 50 },
    { x: 150, y: 50 },
    { x: 150, y: 350 },
    { x: 100, y: 350 },
  ]);
  const hole = part.features[1];
  assert.deepEqual(hole.centerLocal, { x: 500, y: 200 });
  assert.equal(hole.radiusMm, 2.5);
});

test("colorTag containing unknown is fatal", () => {
  const record = makeScanRecord({
    derivedTags: { colorTag: "door_colour_1_unknown_surface_mode", boardTypeTag: "door" },
  });
  const { part, issues } = panelToNestPart(record);
  assert.equal(part, null);
  assert.ok(issues.some((i) => i.code === "invalid_colorTag" && i.severity === "error"));
});

test("missing boardTypeTag is fatal", () => {
  const record = makeScanRecord({ derivedTags: { colorTag: "carcass_colour" } });
  const { part, issues } = panelToNestPart(record);
  assert.equal(part, null);
  assert.ok(issues.some((i) => i.code === "invalid_boardTypeTag"));
});

test("HALF feature without openSurfaceToken warns but stays valid", () => {
  const record = makeScanRecord();
  record.metadata.features[0].openSurfaceToken = null;
  const { part, issues } = panelToNestPart(record);
  assert.ok(part);
  assert.ok(issues.some((i) => i.code === "half_feature_missing_openSurfaceToken" && i.severity === "warning"));
});

test("entity tokens are copied into metadataRefs", () => {
  const { part } = panelToNestPart(makeScanRecord());
  assert.equal(part.metadataRefs.bodyToken, "tok-body");
  assert.equal(part.metadataRefs.millingFaceToken, "tok-mill");
});

test("requiredFaceUp resolves MILLING when a surface is marked MILLING", () => {
  const { part } = panelToNestPart(makeScanRecord());
  assert.equal(part.requiredFaceUp, "MILLING");
});

test("requiredFaceUp resolves EITHER when both surfaces are EITHER", () => {
  const record = makeScanRecord();
  for (const face of record.metadata.faceRegistry.faces) {
    face.millingSurface = "EITHER";
  }
  assert.equal(resolveRequiredFaceUp(record.metadata), "EITHER");
});

// ---------------------------------------------------------------------------
// Rotations
// ---------------------------------------------------------------------------

test("rotation policy follows grain direction", () => {
  assert.deepEqual(deriveAllowedRotations({ grainDirection: "LENGTH" }), [0, 180]);
  assert.deepEqual(deriveAllowedRotations({ grainDirection: "NONE" }), [0, 90, 180, 270]);
  assert.deepEqual(deriveAllowedRotations({ grainDirection: "UNKNOWN" }), [0, 90, 180, 270]);
  assert.deepEqual(
    deriveAllowedRotations({ grainDirection: "UNKNOWN" }, { conservativeUnknownGrain: true }),
    [0, 180]
  );
});

// ---------------------------------------------------------------------------
// Grouping
// ---------------------------------------------------------------------------

test("grouping by materialClass/colorTag/thickness", () => {
  const a = { materialClass: "carcass_board", colorTag: "carcass_colour", thicknessMm: 15, requiredFaceUp: "MILLING" };
  const b = { materialClass: "carcass_board", colorTag: "carcass_colour", thicknessMm: 15, requiredFaceUp: "EITHER" };
  const c = { materialClass: "door_board", colorTag: "door_colour_1", thicknessMm: 15, requiredFaceUp: "MILLING" };

  assert.equal(makeNestingGroupKey(a), makeNestingGroupKey(b));
  assert.notEqual(makeNestingGroupKey(a), makeNestingGroupKey(c));
  assert.notEqual(makeConservativeNestingGroupKey(a), makeConservativeNestingGroupKey(b));

  const groups = groupNestParts([a, b, c]);
  assert.equal(groups.length, 2);
  const conservative = groupNestParts([a, b, c], { conservative: true });
  assert.equal(conservative.length, 3);
});

// ---------------------------------------------------------------------------
// Job orchestration
// ---------------------------------------------------------------------------

test("buildNestingInputJob filters non-bodies and reports invalid panels", () => {
  const good = makeScanRecord();
  const bad = makeScanRecord({
    derivedTags: { colorTag: "", boardTypeTag: "carcass" },
  });
  bad.metadata = JSON.parse(JSON.stringify(bad.metadata));
  const component = { entityKind: "component", componentName: "OHC" };

  const job = buildNestingInputJob([good, bad, component]);
  assert.equal(job.summary.totalScanned, 2);
  assert.equal(job.summary.validParts, 1);
  assert.equal(job.summary.invalidParts, 1);
  assert.equal(job.groups.length, 1);
  assert.equal(job.groups[0].parts.length, 1);
  assert.ok(job.summary.errors >= 1);
  assert.ok(job.invalidPanels[0].issues.some((i) => i.code === "invalid_colorTag"));
  assert.equal(job.source, "UnifiedCabinet.Attributes");
});
