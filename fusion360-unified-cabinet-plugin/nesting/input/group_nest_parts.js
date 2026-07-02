"use strict";

/**
 * Group NestParts into nesting jobs. One group = one sheet-stock pool.
 */

function makeNestingGroupKey(part) {
  return [part.materialClass, part.colorTag, String(part.thicknessMm)].join("|");
}

/**
 * Conservative variant: also separates by requiredFaceUp so milling-up and
 * milling-down boards are not mixed until face correction is stable.
 */
function makeConservativeNestingGroupKey(part) {
  return [
    part.materialClass,
    part.colorTag,
    String(part.thicknessMm),
    part.requiredFaceUp,
  ].join("|");
}

/**
 * @param {Array} parts NestPart[]
 * @param {Object} [options] { conservative?: boolean }
 * @returns {Array} NestingGroup[]
 */
function groupNestParts(parts, options) {
  const opts = options || {};
  const keyFn = opts.conservative ? makeConservativeNestingGroupKey : makeNestingGroupKey;
  const byKey = new Map();

  for (const part of parts || []) {
    const key = keyFn(part);
    if (!byKey.has(key)) {
      byKey.set(key, {
        groupKey: key,
        materialClass: part.materialClass,
        colorTag: part.colorTag,
        thicknessMm: part.thicknessMm,
        parts: [],
        issues: [],
      });
    }
    byKey.get(key).parts.push(part);
  }
  return [...byKey.values()];
}

const api = { makeNestingGroupKey, makeConservativeNestingGroupKey, groupNestParts };

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== "undefined") {
  globalThis.CabinetNesting = Object.assign(globalThis.CabinetNesting || {}, {
    groupNestParts: api,
  });
}
