"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const preflight = require("../nesting/preflight.js");


function panel(overrides) {
  const base = {
    entityKind: "body",
    panelId: "panel-1",
    bodyName: "Panel 1",
    requiredFaceUp: "MILLING",
    derivedTags: { boardTypeTag: "carcass", colorTag: "white" },
    metadata: {
      defaultAttributes: { materialClass: "carcass_board" },
      classification: {
        boardType: { value: "carcass" },
        color: { value: "white" },
        cuttingFace: { value: "MILLING" },
      },
    },
  };
  return Object.assign(base, overrides || {});
}


test("panel is ready when board type color and cutting face are known", () => {
  const result = preflight.evaluatePanel(panel());
  assert.equal(result.ready, true);
  assert.deepEqual(result.missing, []);
});


test("EITHER is an accepted cutting-face constraint", () => {
  const result = preflight.evaluatePanel(panel({
    requiredFaceUp: "EITHER",
    metadata: {
      defaultAttributes: { materialClass: "carcass_board" },
      classification: {
        boardType: { value: "carcass" },
        color: { value: "white" },
        cuttingFace: { value: "EITHER" },
      },
    },
  }));
  assert.equal(result.ready, true);
  assert.equal(result.cuttingFace, "EITHER");
});


test("missing fields are listed independently", () => {
  const record = panel({
    requiredFaceUp: "UNASSIGNED",
    derivedTags: { boardTypeTag: "", colorTag: "" },
    metadata: {
      classification: {
        boardType: { value: "" },
        color: { value: "" },
      },
    },
  });
  const result = preflight.evaluatePanel(record);
  assert.equal(result.ready, false);
  assert.deepEqual(result.missing, ["Board Type", "Color", "Cutting Face"]);
});


test("canonical color is used ahead of compatibility tags", () => {
  const record = panel({
    derivedTags: { colorTag: "" },
    metadata: {
      defaultAttributes: { materialClass: "door_board" },
      classification: {
        boardType: { value: "door" },
        color: { value: "oak" },
        cuttingFace: { value: "MILLING" },
      },
    },
  });
  const result = preflight.evaluatePanel(record);
  assert.equal(result.ready, true);
  assert.equal(result.colorTag, "oak");
});


test("evaluateRecords ignores non-body scan records", () => {
  const result = preflight.evaluateRecords([
    panel(),
    panel({
      panelId: "bad",
      requiredFaceUp: "UNASSIGNED",
      metadata: {
        defaultAttributes: { materialClass: "carcass_board" },
        classification: {
          boardType: { value: "carcass" },
          color: { value: "white" },
          cuttingFace: { value: "" },
        },
      },
    }),
    { entityKind: "component", panelId: "component" },
  ]);
  assert.equal(result.total, 2);
  assert.equal(result.ready.length, 1);
  assert.equal(result.notReady.length, 1);
});
