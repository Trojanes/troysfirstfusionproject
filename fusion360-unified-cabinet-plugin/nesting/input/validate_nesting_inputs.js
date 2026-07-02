"use strict";

/**
 * Issue constructors and tag validity helpers shared by the input layer.
 */

function makeIssue(severity, code, message, ids) {
  const issue = {
    severity,
    code,
    message: message || code,
  };
  if (ids && ids.panelId) issue.panelId = ids.panelId;
  if (ids && ids.sourceBoardId) issue.sourceBoardId = ids.sourceBoardId;
  return issue;
}

function err(code, ids, message) {
  return makeIssue("error", code, message, ids);
}

function warn(code, ids, message) {
  return makeIssue("warning", code, message, ids);
}

function info(code, ids, message) {
  return makeIssue("info", code, message, ids);
}

/**
 * Matches the Attributes UI convention: a tag is undefined when it is empty
 * or still carries an unresolved "unknown" marker
 * (e.g. door_colour_1_unknown_surface_mode).
 */
function isUndefinedTag(value) {
  const text = String(value == null ? "" : value).trim().toLowerCase();
  return !text || text.includes("unknown");
}

function hasErrors(issues) {
  return (issues || []).some((issue) => issue.severity === "error");
}

function countBySeverity(issues) {
  const counts = { error: 0, warning: 0, info: 0 };
  for (const issue of issues || []) {
    if (counts[issue.severity] != null) counts[issue.severity] += 1;
  }
  return counts;
}

const api = { makeIssue, err, warn, info, isUndefinedTag, hasErrors, countBySeverity };

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== "undefined") {
  globalThis.CabinetNesting = Object.assign(globalThis.CabinetNesting || {}, {
    validateNestingInputs: api,
  });
}
