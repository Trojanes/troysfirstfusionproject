"use strict";

/**
 * Milestone 1 orchestrator:
 *   scan records (panelAttributes.scanMetadata)
 *   → NestPart[] (validated)
 *   → NestingGroup[]
 *   → NestingInputJob { groups, invalidPanels, summary }
 */

let panelModule;
let groupModule;
let validate;
if (typeof require === "function") {
  panelModule = require("./panel_to_nest_part.js");
  groupModule = require("./group_nest_parts.js");
  validate = require("./validate_nesting_inputs.js");
} else {
  const ns = globalThis.CabinetNesting || {};
  panelModule = ns.panelToNestPart;
  groupModule = ns.groupNestParts;
  validate = ns.validateNestingInputs;
}

const { panelToNestPart } = panelModule;
const { groupNestParts } = groupModule;
const { countBySeverity } = validate;

const BODY_ENTITY_KINDS = new Set(["body", "selected_body"]);

/**
 * @param {Array} scanRecords records from panelAttributes.scanMetadata
 * @param {Object} [options] { conservative?: boolean, conservativeUnknownGrain?: boolean }
 * @returns {Object} NestingInputJob
 */
function buildNestingInputJob(scanRecords, options) {
  const opts = options || {};
  const bodyRecords = (scanRecords || []).filter((record) =>
    BODY_ENTITY_KINDS.has(String(record && record.entityKind))
  );

  const parts = [];
  const invalidPanels = [];
  const allIssues = [];

  for (const record of bodyRecords) {
    const { part, issues } = panelToNestPart(record, opts);
    allIssues.push(...issues);
    if (part) {
      parts.push(part);
    } else {
      invalidPanels.push({
        panelId: record.panelId || (record.metadata && record.metadata.identity
          ? record.metadata.identity.panelId
          : undefined),
        sourceBoardId: record.sourceBoardId
          || (record.metadata && record.metadata.identity
            ? record.metadata.identity.sourceBoardId
            : undefined),
        issues,
      });
    }
  }

  const groups = groupNestParts(parts, opts);
  const severity = countBySeverity(allIssues);

  return {
    schemaVersion: 1,
    createdAt: new Date().toISOString(),
    source: "UnifiedCabinet.Attributes",
    groups,
    invalidPanels,
    summary: {
      totalScanned: bodyRecords.length,
      validParts: parts.length,
      invalidParts: invalidPanels.length,
      groupCount: groups.length,
      warnings: severity.warning,
      errors: severity.error,
    },
  };
}

const api = { buildNestingInputJob };

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== "undefined") {
  globalThis.CabinetNesting = Object.assign(globalThis.CabinetNesting || {}, {
    buildNestingInputJob: api,
  });
}
