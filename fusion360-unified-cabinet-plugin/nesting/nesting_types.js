"use strict";

/**
 * CabinetNC nesting — shared constants and JSDoc typedefs.
 *
 * All geometry consumed by this module is in the CANONICAL face-local
 * millimetre frame (body-attached frame, thickness axis dropped). See
 * ATTRIBUTES_HANDOVER_FOR_NESTING.md §2.6. Never use `points2d` / the rendered
 * SVG string for geometry work — those are display-space only.
 */

const SEVERITY = {
  ERROR: "error",
  WARNING: "warning",
  INFO: "info",
};

const REQUIRED_FACE_UP = {
  MILLING: "MILLING",
  EITHER: "EITHER",
  UP: "UP",
  DOWN: "DOWN",
  UNASSIGNED: "UNASSIGNED",
};

const GRAIN_DIRECTION = {
  NONE: "NONE",
  LENGTH: "LENGTH",
  WIDTH: "WIDTH",
  UNKNOWN: "UNKNOWN",
};

const CUT_TYPE = {
  HALF: "HALF",
  FULL: "FULL",
};

const ALL_ROTATIONS = [0, 90, 180, 270];

/**
 * @typedef {{x: number, y: number}} PointXY
 *
 * @typedef {Object} NestFeature
 * @property {string} featureId
 * @property {"HALF"|"FULL"} cutType
 * @property {string} kind            groove | hole | pocket | ...
 * @property {number} depthMm
 * @property {boolean} [isCircle]
 * @property {number} [radiusMm]
 * @property {PointXY} [centerLocal]  canonical face-local mm
 * @property {PointXY[]} [pointsLocal] canonical face-local mm polygon
 * @property {string} [openSurfaceToken] non-authoritative across sessions
 *
 * @typedef {Object} NestEdgeGroup
 * @property {string} edgeGroupId
 * @property {string} side            "+X" | "-X" | "+Y" | "-Y" | ...
 * @property {string} directionHint
 * @property {boolean} bandable
 * @property {boolean} bandingRequired
 * @property {string} bandingColor    one colour per logical edge (hard rule)
 * @property {string} [bandingFinishName]
 * @property {string[]} [edgeIds]
 * @property {string[]} [faceIds]
 * @property {string[]} [entityTokens]
 *
 * @typedef {Object} NestPart
 * @property {string} panelId
 * @property {string} sourceBoardId
 * @property {string} [sourceBoardType]
 * @property {string} boardType
 * @property {string} generator
 * @property {string} module
 * @property {string} [runId]
 * @property {string} [role]
 * @property {string} [category]
 * @property {string} materialClass
 * @property {string} colorTag
 * @property {string} boardTypeTag
 * @property {number} thicknessMm
 * @property {number} widthMm         X extent of the milling-face projection
 * @property {number} heightMm        Y extent of the milling-face projection
 * @property {number} [lengthMm]      sorted long dimension (informational)
 * @property {PointXY[]} outlineLocal true nesting contour (canonical frame)
 * @property {NestFeature[]} features
 * @property {NestEdgeGroup[]} edgeGroups
 * @property {string} requiredFaceUp  REQUIRED_FACE_UP value
 * @property {string} grainDirection  GRAIN_DIRECTION value
 * @property {Array<0|90|180|270>} allowedRotations
 * @property {Object} metadataRefs    tokens are non-authoritative cross-session
 *
 * @typedef {Object} NestingInputIssue
 * @property {"error"|"warning"|"info"} severity
 * @property {string} code
 * @property {string} [panelId]
 * @property {string} [sourceBoardId]
 * @property {string} message
 */

const api = {
  SEVERITY,
  REQUIRED_FACE_UP,
  GRAIN_DIRECTION,
  CUT_TYPE,
  ALL_ROTATIONS,
};

if (typeof module !== "undefined" && module.exports) {
  module.exports = api;
}
if (typeof globalThis !== "undefined") {
  globalThis.CabinetNesting = Object.assign(globalThis.CabinetNesting || {}, {
    types: api,
  });
}
