/**
 * Reusable assembly-loop primitives.
 *
 * Module-specific loops provide final measured/simulated board AABBs and
 * declarative contact contracts. This file owns generic contact and Fusion
 * evidence checks so a generator cannot certify itself with matching mistakes.
 */

export function bboxSize(bbox = {}) {
  return {
    x: Math.abs(Number(bbox.x1 || 0) - Number(bbox.x0 || 0)),
    y: Math.abs(Number(bbox.y1 || 0) - Number(bbox.y0 || 0)),
    z: Math.abs(Number(bbox.z1 || 0) - Number(bbox.z0 || 0)),
  };
}

export function fingerprintParams(params = {}, keys = Object.keys(params).sort()) {
  return JSON.stringify(keys.map((key) => [key, params[key] ?? null]));
}

export function positiveOverlap1d(a0, a1, b0, b1) {
  return Math.max(0, Math.min(Number(a1), Number(b1)) - Math.max(Number(a0), Number(b0)));
}

export function positiveOverlapVolume(a = {}, b = {}) {
  return positiveOverlap1d(a.x0, a.x1, b.x0, b.x1)
    * positiveOverlap1d(a.y0, a.y1, b.y0, b.y1)
    * positiveOverlap1d(a.z0, a.z1, b.z0, b.z1);
}

/**
 * Contract shape:
 * { id, a, b, aFace, bFace, overlapAxes?: ["x", "z"], toleranceMm?: 2.5 }
 */
export function auditBoardContacts(boards, contracts, defaultToleranceMm = 2.5) {
  const byId = new Map((boards || []).map((row) => [String(row.id || ""), row]));
  const findings = [];
  const contacts = [];
  for (const contract of contracts || []) {
    const a = byId.get(contract.a);
    const b = byId.get(contract.b);
    const tol = Number(contract.toleranceMm ?? defaultToleranceMm);
    if (!a || !b) {
      findings.push({
        severity: "error",
        code: "contact_missing_board",
        contractId: contract.id,
        detail: `${contract.id}: missing ${!a ? contract.a : contract.b}`,
      });
      continue;
    }
    const abb = a.bboxMm || a;
    const bbb = b.bboxMm || b;
    const av = Number(abb[contract.aFace]);
    const bv = Number(bbb[contract.bFace]);
    const delta = av - bv;
    const overlapAxes = contract.overlapAxes || [];
    const overlaps = Object.fromEntries(overlapAxes.map((axis) => [
      axis,
      positiveOverlap1d(abb[`${axis}0`], abb[`${axis}1`], bbb[`${axis}0`], bbb[`${axis}1`]),
    ]));
    const faceOk = Number.isFinite(delta) && Math.abs(delta) <= tol;
    const overlapOk = overlapAxes.every((axis) => overlaps[axis] > tol);
    const row = {
      id: contract.id,
      a: contract.a,
      b: contract.b,
      aFace: contract.aFace,
      bFace: contract.bFace,
      deltaMm: delta,
      overlapMm: overlaps,
      toleranceMm: tol,
      ok: faceOk && overlapOk,
    };
    contacts.push(row);
    if (!faceOk) {
      findings.push({
        severity: "error",
        code: "contact_gap",
        contractId: contract.id,
        detail: `${contract.id}: ${contract.a}.${contract.aFace}=${av.toFixed(2)} vs `
          + `${contract.b}.${contract.bFace}=${bv.toFixed(2)} (delta=${delta.toFixed(2)} mm)`,
      });
    } else if (!overlapOk) {
      findings.push({
        severity: "error",
        code: "contact_no_face_overlap",
        contractId: contract.id,
        detail: `${contract.id}: faces align but overlap is insufficient ${JSON.stringify(overlaps)}`,
      });
    }
  }
  return {
    ok: findings.length === 0,
    contacts,
    findings,
  };
}

export function auditForbiddenOverlaps(boards, pairs, toleranceVolumeMm3 = 1) {
  const byId = new Map((boards || []).map((row) => [String(row.id || ""), row]));
  const findings = [];
  for (const pair of pairs || []) {
    const a = byId.get(pair.a);
    const b = byId.get(pair.b);
    if (!a || !b) continue;
    const volume = positiveOverlapVolume(a.bboxMm || a, b.bboxMm || b);
    if (volume > Number(pair.toleranceVolumeMm3 ?? toleranceVolumeMm3)) {
      findings.push({
        severity: "error",
        code: "forbidden_overlap",
        contractId: pair.id,
        detail: `${pair.id}: ${pair.a}/${pair.b} overlap=${volume.toFixed(2)} mm³`,
      });
    }
  }
  return { ok: findings.length === 0, findings };
}

export function certifyFusionEvidence({
  fusion,
  requiredBuild,
  adapterMtimeMs,
  fusionLogMtimeMs,
  expectedCaseFingerprints = [],
  measuredCaseFingerprints = [],
  requiredCaseAudits = [],
}) {
  if (!fusion) {
    return {
      level: "offline_preflight",
      certified: false,
      valid: false,
      reason: "No Fusion evidence. Offline checks are preflight only.",
    };
  }
  if (String(fusion.adapterBuild || "") !== String(requiredBuild || "")) {
    return {
      level: "stale_fusion",
      certified: false,
      valid: false,
      reason: `Fusion build ${fusion.adapterBuild || "missing"} != required ${requiredBuild}`,
    };
  }
  if (Number(fusionLogMtimeMs || 0) + 1 < Number(adapterMtimeMs || 0)) {
    return {
      level: "stale_fusion",
      certified: false,
      valid: false,
      reason: "Fusion log predates the current adapter source.",
    };
  }
  if (!Array.isArray(fusion.cases) || fusion.cases.length === 0) {
    return {
      level: "invalid_fusion",
      certified: false,
      valid: false,
      reason: "Fusion log has no measured cases.",
    };
  }
  const expectedSet = new Set(expectedCaseFingerprints.filter(Boolean));
  const measuredSet = new Set(measuredCaseFingerprints.filter(Boolean));
  const matchedFingerprints = [...measuredSet].filter((value) => expectedSet.has(value));
  if (expectedSet.size && matchedFingerprints.length === 0) {
    return {
      level: "mismatched_fusion_case",
      certified: false,
      valid: false,
      reason: "Fusion measurements do not match any current loop parameter case.",
      coverage: { matched: 0, expected: expectedSet.size, measured: measuredSet.size },
    };
  }
  const boards = fusion.cases.flatMap((row) => row.boards || []);
  if (!boards.length || boards.every((board) => {
    const size = board.sizeMm || bboxSize(board.bboxMm);
    return Number(size.x || 0) <= 0.5
      && Number(size.y || 0) <= 0.5
      && Number(size.z || 0) <= 0.5;
  })) {
    return {
      level: "invalid_fusion",
      certified: false,
      valid: false,
      reason: "Fusion evidence has no positive-volume board measurements.",
    };
  }
  for (const auditName of requiredCaseAudits || []) {
    const missing = fusion.cases.filter((row) => !row?.[auditName] || typeof row[auditName].ok !== "boolean");
    if (missing.length) {
      return {
        level: "invalid_fusion",
        certified: false,
        valid: false,
        reason: `Fusion evidence is missing required ${auditName} geometry audit.`,
      };
    }
    if (fusion.cases.some((row) => row[auditName].ok === false)) {
      return {
        level: "fusion_failed",
        certified: false,
        valid: true,
        reason: `Fusion ${auditName} geometry audit failed.`,
      };
    }
  }
  const passed = fusion.ok === true && fusion.cases.every((row) => row.ok !== false);
  return {
    level: passed ? "fusion_verified" : "fusion_failed",
    certified: passed,
    valid: true,
    reason: passed ? "Current-build Fusion measurements passed." : "Current-build Fusion measurements failed.",
    coverage: {
      matched: matchedFingerprints.length,
      expected: expectedSet.size,
      measured: measuredSet.size,
    },
  };
}
