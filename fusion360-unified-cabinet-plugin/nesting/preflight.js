(function (root, factory) {
  "use strict";
  const api = factory();
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  root.CabinetNestingPreflight = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
  "use strict";

  function isUndefined(value) {
    const text = String(value || "").trim().toLowerCase();
    return !text
      || text.includes("unknown")
      || ["undefined", "unassigned", "none", "n/a"].includes(text);
  }

  function canonical(metadata, field) {
    const classification = metadata && metadata.classification || {};
    const state = classification[field] || {};
    return String(state.value || "").trim();
  }

  function boardTypeTagOf(record) {
    return canonical(record && record.metadata || {}, "boardType");
  }

  function colorTagOf(record) {
    return canonical(record && record.metadata || {}, "color");
  }

  function cuttingFaceOf(record) {
    let cuttingFace = canonical(record && record.metadata || {}, "cuttingFace")
      .toUpperCase();
    if (["MILLING", "EITHER"].includes(cuttingFace)) return cuttingFace;
    cuttingFace = String(
      record && (record.requiredFaceUp || record.cuttingFace) || "UNASSIGNED",
    ).trim().toUpperCase();
    if (["MILLING", "EITHER"].includes(cuttingFace)) return cuttingFace;
    const faces = record
      && record.metadata
      && record.metadata.faceRegistry
      && Array.isArray(record.metadata.faceRegistry.faces)
      ? record.metadata.faceRegistry.faces
      : [];
    const surfaces = faces.filter((face) => (
      face
      && (
        face.faceClass === "SURFACE"
        || ["MILLING", "NON_MILLING", "EITHER"].includes(
          String(face.millingSurface || "").toUpperCase(),
        )
      )
    ));
    if (surfaces.some((face) => String(face.millingSurface || "").toUpperCase() === "MILLING")) {
      return "MILLING";
    }
    const eitherCount = surfaces.filter(
      (face) => String(face.millingSurface || "").toUpperCase() === "EITHER",
    ).length;
    if (eitherCount >= 2) return "EITHER";
    return "UNASSIGNED";
  }

  function evaluatePanel(record) {
    const boardTypeTag = boardTypeTagOf(record);
    const colorTag = colorTagOf(record);
    const cuttingFace = cuttingFaceOf(record);
    const missing = [];
    if (isUndefined(boardTypeTag)) missing.push("Board Type");
    if (isUndefined(colorTag)) missing.push("Color");
    if (!["MILLING", "EITHER"].includes(cuttingFace)) {
      missing.push("Cutting Face");
    }
    return {
      ready: missing.length === 0,
      missing,
      boardTypeTag,
      colorTag,
      cuttingFace,
    };
  }

  function evaluateRecords(records) {
    const bodies = (Array.isArray(records) ? records : []).filter((record) => (
      String(record && record.entityKind || "").toLowerCase().includes("body")
    ));
    const evaluated = bodies.map((record) => ({
      record,
      check: evaluatePanel(record),
    }));
    return {
      total: bodies.length,
      ready: evaluated.filter((item) => item.check.ready),
      notReady: evaluated.filter((item) => !item.check.ready),
    };
  }

  return {
    isUndefined,
    colorTagOf,
    boardTypeTagOf,
    cuttingFaceOf,
    evaluatePanel,
    evaluateRecords,
  };
});
