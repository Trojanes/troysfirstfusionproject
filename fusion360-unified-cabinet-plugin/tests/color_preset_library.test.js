"use strict";

const { test } = require("node:test");
const assert = require("node:assert/strict");
const presets = require("../panel_attributes/color_preset_library.js");


function memoryStorage() {
  const values = new Map();
  return {
    getItem(key) {
      return values.has(key) ? values.get(key) : null;
    },
    setItem(key, value) {
      values.set(key, String(value));
    },
  };
}


test("color slug is stable and bounded", () => {
  assert.equal(presets.slug("  Alpine White!! "), "alpine_white");
  assert.equal(presets.slug(""), "");
  assert.equal(presets.slug("x".repeat(80)).length, 32);
});


test("upsert deduplicates by color tag and updates display name", () => {
  const first = presets.upsert([], "Alpine White", "2026-01-01T00:00:00Z");
  const second = presets.upsert(first, "Alpine   White", "2026-01-02T00:00:00Z");
  assert.equal(second.length, 1);
  assert.equal(second[0].colorTag, "alpine_white");
  assert.equal(second[0].name, "Alpine   White");
  assert.equal(second[0].createdAt, "2026-01-01T00:00:00Z");
  assert.equal(second[0].updatedAt, "2026-01-02T00:00:00Z");
});


test("saved presets survive a fresh load", () => {
  const storage = memoryStorage();
  const items = presets.upsert([], "Smoked Oak", "2026-01-01T00:00:00Z");
  presets.save(storage, items);
  const loaded = presets.load(storage);
  assert.equal(loaded.length, 1);
  assert.equal(loaded[0].name, "Smoked Oak");
  assert.equal(loaded[0].colorTag, "smoked_oak");
});


test("remove only deletes the selected preset", () => {
  let items = presets.upsert([], "Alpine White", "2026-01-01T00:00:00Z");
  items = presets.upsert(items, "Smoked Oak", "2026-01-01T00:00:00Z");
  const result = presets.remove(items, "Alpine White");
  assert.equal(result.removed, true);
  assert.deepEqual(result.items.map((item) => item.colorTag), ["smoked_oak"]);
  assert.equal(presets.remove(result.items, "Missing").removed, false);
});
