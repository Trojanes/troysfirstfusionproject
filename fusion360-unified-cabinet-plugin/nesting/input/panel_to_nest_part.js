"use strict";

/**
 * Convert one Attributes scan record (from panelAttributes.scanMetadata) into a
 * validated NestPart.
 *
 * Input shape: a scan record whose `metadata` field is the full
 * UnifiedCabinet.Panel metadata JSON, and whose derived tags live in
 * `record.derivedTags.colorTag` / `record.derivedTags.boardTypeTag`
 * (typedTags as fallback) — the tags are derived at scan time and are NOT
 * stored inside the metadata JSON itself.
 */

let outlineModule;
let rotationsModule;
let validate;
if (typeof require === "function") {
  outlineModule = require("./outline_records_to_polygon.js");
  rotationsModule = require("./derive_allowed_rotations.js");
  validate = require("./validate_nesting_inputs.js");
} else {
  const ns = globalThis.CabinetNesting || {};
  outlineModule = ns.outlineRecordsToPolygon;
  rotationsModule = ns.deriveAllowedRotations;
  validate = ns.validateNestingInputs;
}

const { outlineRecordsToPolygon } = outlineModule;
const { deriveAllowedRotations } = rotationsModule;
const { err, warn, isUndefinedTag, hasErrors } = validate;

function toPointXY(raw) {
  if (Array.isArray(raw)) return { x: Number(raw[0]), y: Number(raw[1]) };
  if (raw && typeof raw === "object") return { x: Number(raw.x), y: Number(raw.y) };
  return null;
}

function convertFeature(feature, ids, issues) {
  const out = {
    featureId: String(feature.featureId || ""),
    cutType: feature.cutType,
    kind: feature.kind,
    depthMm: Number(feature.depthMm),
    isCircle: Boolean(feature.isCircle),
    radiusMm: feature.radiusMm != null ? Number(feature.radiusMm) : undefined,
    centerLocal: Array.isArray(feature.center2d) ? toPointXY(feature.center2d) : undefined,
    pointsLocal: Array.isArray(feature.pointsLocal)
      ? feature.pointsLocal.map(toPointXY).filter(Boolean)
      : undefined,
    // Useful in-session, but stale after body regeneration; never a stable id.
    openSurfaceToken: feature.openSurfaceToken || undefined,
  };

  if (!Number.isFinite(out.depthMm) || out.depthMm < 0) {
    issues.push(err("feature_invalid_depth", ids, `Feature ${out.featureId} has invalid depthMm.`));
  }
  if (out.cutType === "HALF" && !out.openSurfaceToken) {
    issues.push(warn("half_feature_missing_openSurfaceToken", ids,
      `HALF feature ${out.featureId} has no openSurfaceToken.`));
  }
  if (out.isCircle && (!out.centerLocal || !Number.isFinite(out.radiusMm))) {
    issues.push(warn("circle_feature_missing_center_or_radius", ids,
      `Circle feature ${out.featureId} is missing centerLocal/radiusMm.`));
  }
  if (!out.isCircle && (!out.pointsLocal || out.pointsLocal.length < 3)) {
    issues.push(warn("feature_missing_pointsLocal", ids,
      `Feature ${out.featureId} (${out.kind}) has no usable pointsLocal polygon.`));
  }
  return out;
}

function convertEdgeGroup(group) {
  return {
    edgeGroupId: String(group.edgeGroupId || ""),
    side: group.side || group.directionHint || "unknown",
    directionHint: group.directionHint || group.side || "unknown",
    bandable: Boolean(group.bandable),
    bandingRequired: Boolean(group.bandingRequired),
    bandingColor: group.bandingColor || "raw-core",
    bandingFinishName: group.bandingFinishName || undefined,
    edgeIds: Array.isArray(group.edgeIds) ? [...group.edgeIds] : [],
    faceIds: Array.isArray(group.faceIds) ? [...group.faceIds] : [],
    entityTokens: Array.isArray(group.entityTokens) ? [...group.entityTokens] : [],
  };
}

/**
 * Conservative face-up constraint from faceRegistry surfaces.
 * Rule of record: the face a half-slot opens onto is the MILLING surface; a
 * board with no half-slot has both surfaces EITHER (free to flip).
 * Note: registry face entries do not currently carry nestingOrientation (it
 * lives in per-face metadata); the UP/DOWN branch is future-proofing for when
 * door defaults are wired into the registry.
 */
function resolveRequiredFaceUp(metadata) {
  const faces = (metadata.faceRegistry && metadata.faceRegistry.faces) || [];
  const surfaces = faces.filter((f) => f.faceClass === "SURFACE");

  if (surfaces.some((f) => f.millingSurface === "MILLING")) return "MILLING";
  if (surfaces.filter((f) => f.millingSurface === "EITHER").length >= 2) return "EITHER";

  const up = surfaces.find((f) => f.nestingOrientation === "UP");
  if (up) return "UP";
  const down = surfaces.find((f) => f.nestingOrientation === "DOWN");
  if (down) return "DOWN";

  return "UNASSIGNED";
}

/**
 * @param {Object} scanRecord one record from panelAttributes.scanMetadata
 * @param {Object} [options]  { conservativeUnknownGrain?: boolean }
 * @returns {{part: Object|null, issues: Array}}
 */
function panelToNestPart(scanRecord, options) {
  const issues = [];
  const record = scanRecord || {};

  const metadata = record.metadata || record.panelMetadata;
  if (!metadata || typeof metadata !== "object") {
    return {
      part: null,
      issues: [err("missing_panel_metadata", {
        panelId: record.panelId,
        sourceBoardId: record.sourceBoardId,
      })],
    };
  }

  const identity = metadata.identity || {};
  const defaults = metadata.defaultAttributes || {};
  const dimensions = metadata.dimensions || {};
  const millingSvg = metadata.millingSurfaceSvg || {};

  const panelId = identity.panelId || record.panelId;
  const ids = { panelId, sourceBoardId: identity.sourceBoardId };
  if (!panelId) issues.push(err("missing_panelId", ids));

  const materialClass = defaults.materialClass || record.materialClass;
  if (!materialClass) issues.push(err("missing_materialClass", ids));

  // Derived tags live on the scan record (derivedTags/typedTags), NOT in the
  // metadata JSON.
  const derivedTags = record.derivedTags || {};
  const typedTags = record.typedTags || {};
  const colorTag = derivedTags.colorTag || typedTags.colorTag || "";
  const boardTypeTag = derivedTags.boardTypeTag || typedTags.boardTypeTag || "";
  if (isUndefinedTag(colorTag)) {
    issues.push(err("invalid_colorTag", ids, `colorTag "${colorTag}" is missing or unresolved.`));
  }
  if (isUndefinedTag(boardTypeTag)) {
    issues.push(err("invalid_boardTypeTag", ids, `boardTypeTag "${boardTypeTag}" is missing or unresolved.`));
  }

  const thicknessMm = Number(dimensions.thicknessMm);
  if (!Number.isFinite(thicknessMm) || thicknessMm <= 0) {
    issues.push(err("invalid_thickness", ids));
  }

  if (!metadata.millingSurfaceSvg) {
    issues.push(err("missing_millingSurfaceSvg", ids));
  }
  const outlineResult = outlineRecordsToPolygon(millingSvg.outline);
  for (const code of outlineResult.issues) {
    issues.push(err(code, ids));
  }

  const features = Array.isArray(metadata.features)
    ? metadata.features.map((feature) => convertFeature(feature, ids, issues))
    : [];

  const rawEdgeGroups = (metadata.faceRegistry && metadata.faceRegistry.edgeGroups) || [];
  if (!Array.isArray(rawEdgeGroups) || rawEdgeGroups.length === 0) {
    issues.push(warn("missing_edgeGroups", ids));
  }
  const edgeGroups = (rawEdgeGroups || []).map(convertEdgeGroup);

  const requiredFaceUp = resolveRequiredFaceUp(metadata);
  if (requiredFaceUp === "UNASSIGNED") {
    issues.push(warn("requiredFaceUp_unassigned", ids));
  }

  let grainDirection = defaults.grainDirection || "UNKNOWN";
  if (grainDirection === "UNKNOWN") {
    issues.push(warn("missing_grainDirection", ids,
      "grainDirection missing; using default rotation policy."));
  }

  // SVG width/height are axis-specific extents of the milling-face projection;
  // dimensions.length/width are SORTED long/short — only use them as fallback.
  const widthMm = Number(millingSvg.widthMm != null ? millingSvg.widthMm : dimensions.widthMm);
  const heightMm = Number(millingSvg.heightMm != null ? millingSvg.heightMm : dimensions.widthMm);

  const part = {
    panelId,
    sourceBoardId: identity.sourceBoardId || "",
    sourceBoardType: identity.sourceBoardType || undefined,
    boardType: identity.boardType || "",
    generator: identity.generator || "",
    module: identity.module || "",
    runId: identity.runId || undefined,

    role: defaults.role || undefined,
    category: defaults.category || undefined,
    materialClass: materialClass || "",
    colorTag,
    boardTypeTag,

    thicknessMm,
    widthMm,
    heightMm,
    lengthMm: dimensions.lengthMm != null ? Number(dimensions.lengthMm) : undefined,

    outlineLocal: outlineResult.polygon,
    features,
    edgeGroups,

    requiredFaceUp,
    grainDirection,
    allowedRotations: [],

    metadataRefs: {
      bodyName: record.bodyName || undefined,
      bodyToken: record.entityToken || undefined,
      millingFaceToken: millingSvg.millingFaceToken || undefined,
      panelMetadataRaw: metadata,
    },
  };
  part.allowedRotations = deriveAllowedRotations(part, options);

  return {
    part: hasErrors(issues) ? null : part,
    issues,
  };
}

const api = { panelToNestPart, convertFeature, convertEdgeGroup, resolveRequiredFaceUp };

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== "undefined") {
  globalThis.CabinetNesting = Object.assign(globalThis.CabinetNesting || {}, {
    panelToNestPart: api,
  });
}
