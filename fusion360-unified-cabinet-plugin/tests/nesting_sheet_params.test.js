"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const palette = fs.readFileSync(path.join(__dirname, "..", "palette.html"), "utf8");

test("nesting UI exposes fast and Sparrow quality engines", () => {
  assert.match(palette, /id="nestingEngineMode"/);
  assert.match(palette, /value="sheet_pack"/);
  assert.match(palette, /value="sparrow"/);
  assert.match(palette, /id="nestingQualityTimeLimitSec"/);
});

test("sheet params persist engine and quality timeout", () => {
  assert.match(palette, /qualityTimeLimitSec/);
  assert.match(palette, /saved\?\.engine/);
  assert.match(palette, /saved\?\.qualityTimeLimitSec/);
  assert.match(palette, /nestingEngine:\s*sheetParams\.engine/);
});

test("rotation off sends no rotation increment", () => {
  assert.match(
    palette,
    /rotationIncrementDeg:\s*allowRotation\s*\?\s*rotationIncrementDeg\s*:\s*null/,
  );
});
