"use strict";

/**
 * Rotation policy. grainDirection is not written by the Attributes system yet
 * (deferred metadata field) — callers receive a warning elsewhere and this
 * function applies a configurable default policy for UNKNOWN grain.
 */

function deriveAllowedRotations(part, options) {
  const opts = options || {};
  const grain = (part && part.grainDirection) || "UNKNOWN";

  if (grain === "LENGTH" || grain === "WIDTH") {
    return [0, 180];
  }
  if (grain === "NONE") {
    return [0, 90, 180, 270];
  }
  // UNKNOWN grain: conservative mode prevents accidental grain violations.
  if (opts.conservativeUnknownGrain) {
    return [0, 180];
  }
  return [0, 90, 180, 270];
}

const api = { deriveAllowedRotations };

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== "undefined") {
  globalThis.CabinetNesting = Object.assign(globalThis.CabinetNesting || {}, {
    deriveAllowedRotations: api,
  });
}
