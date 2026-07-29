/**
 * Generator-agnostic loop orchestration.
 *
 * A module supplies:
 * - cases: parameter matrix
 * - generate(params): pure generator
 * - evaluateCase({ caseId, inputParams, result }): module-specific invariants
 *
 * The framework owns case isolation, exception handling, finding aggregation,
 * and stable result shape. Assembly semantics remain declarative through
 * assembly_loop_core.js.
 */

function normalizeFinding(finding, caseId) {
  if (typeof finding === "string") {
    return { severity: "error", code: "audit", detail: finding, caseId };
  }
  return {
    severity: finding?.severity || "error",
    code: finding?.code || "audit",
    detail: finding?.detail || "Audit failed",
    ...finding,
    caseId: finding?.caseId || caseId,
  };
}

export function runGeneratorCaseMatrix({
  moduleId,
  cases,
  generate,
  evaluateCase,
}) {
  if (typeof generate !== "function") throw new TypeError("generate must be a function");
  if (typeof evaluateCase !== "function") throw new TypeError("evaluateCase must be a function");
  const rows = [];
  const findings = [];
  const seenIds = new Set();

  for (const entry of cases || []) {
    const caseId = String(entry?.id || `case-${rows.length + 1}`);
    if (seenIds.has(caseId)) {
      findings.push({
        severity: "error",
        code: "duplicate_case_id",
        detail: `Duplicate case id ${caseId}`,
        caseId,
      });
      continue;
    }
    seenIds.add(caseId);
    const inputParams = entry?.params || {};
    try {
      const result = generate(inputParams);
      const evaluated = evaluateCase({ caseId, inputParams, result }) || {};
      const rowFindings = (evaluated.findings || []).map((finding) => normalizeFinding(finding, caseId));
      const row = {
        caseId,
        moduleId,
        ok: evaluated.ok !== false && rowFindings.every((finding) => finding.severity !== "error"),
        ...evaluated,
        findings: rowFindings,
      };
      rows.push(row);
      findings.push(...rowFindings);
    } catch (error) {
      const finding = {
        severity: "error",
        code: "case_exception",
        detail: `${error?.name || "Error"}: ${error?.message || String(error)}`,
        caseId,
      };
      rows.push({
        caseId,
        moduleId,
        ok: false,
        params: inputParams,
        findings: [finding],
      });
      findings.push(finding);
    }
  }

  return {
    moduleId,
    ok: findings.every((finding) => finding.severity !== "error")
      && rows.every((row) => row.ok !== false),
    cases: rows,
    findings,
  };
}

export function summarizeGeneratorLoop(report) {
  const cases = report?.cases || [];
  const findings = report?.findings || [];
  const countsByCode = {};
  for (const finding of findings) {
    const code = String(finding.code || "audit");
    countsByCode[code] = (countsByCode[code] || 0) + 1;
  }
  return {
    moduleId: report?.moduleId,
    caseCount: cases.length,
    casePass: cases.filter((row) => row.ok).length,
    findingCount: findings.length,
    countsByCode,
    ok: report?.ok === true,
    certification: report?.certification || null,
  };
}
