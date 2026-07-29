import assert from "node:assert/strict";
import {
  auditBoardContacts,
  auditForbiddenOverlaps,
  certifyFusionEvidence,
  fingerprintParams,
} from "./assembly_loop_core.js";
import {
  runGeneratorCaseMatrix,
  summarizeGeneratorLoop,
} from "./generator_loop_framework.js";

const box = (id, x0, x1, y0, y1, z0 = 0, z1 = 40) => ({
  id,
  bboxMm: { x0, x1, y0, y1, z0, z1 },
  sizeMm: { x: x1 - x0, y: y1 - y0, z: z1 - z0 },
});
const contract = [{
  id: "a_to_b",
  a: "A",
  b: "B",
  aFace: "y0",
  bFace: "y1",
  overlapAxes: ["x", "z"],
  toleranceMm: 0.1,
}];

const touching = [
  box("A", 0, 16, 40, 100),
  box("B", 0, 100, 20, 40),
];
assert.equal(auditBoardContacts(touching, contract).ok, true);

const gap = [
  box("A", 0, 16, 79, 100),
  box("B", 0, 100, 20, 40),
];
const gapAudit = auditBoardContacts(gap, contract);
assert.equal(gapAudit.ok, false);
assert.equal(gapAudit.findings[0].code, "contact_gap");
assert.equal(gapAudit.contacts[0].deltaMm, 39);

const overlap = [
  box("A", 0, 20, 0, 20, 0, 20),
  box("B", 10, 30, 10, 30, 10, 30),
];
assert.equal(
  auditForbiddenOverlaps(overlap, [{ id: "no_overlap", a: "A", b: "B" }]).findings[0].code,
  "forbidden_overlap",
);

const fusion = {
  ok: true,
  adapterBuild: "build-2",
  cases: [{ ok: true, boards: [box("A", 0, 10, 0, 10, 0, 10)] }],
};
const fp = fingerprintParams({ width: 100 }, ["width"]);
assert.equal(certifyFusionEvidence({
  fusion,
  requiredBuild: "build-2",
  adapterMtimeMs: 100,
  fusionLogMtimeMs: 101,
  expectedCaseFingerprints: [fp],
  measuredCaseFingerprints: [fp],
}).level, "fusion_verified");
assert.equal(certifyFusionEvidence({
  fusion,
  requiredBuild: "build-3",
  adapterMtimeMs: 100,
  fusionLogMtimeMs: 101,
}).level, "stale_fusion");
assert.equal(certifyFusionEvidence({
  fusion,
  requiredBuild: "build-2",
  adapterMtimeMs: 200,
  fusionLogMtimeMs: 101,
}).level, "stale_fusion");
assert.equal(certifyFusionEvidence({
  fusion: null,
  requiredBuild: "build-2",
  adapterMtimeMs: 200,
  fusionLogMtimeMs: 0,
}).level, "offline_preflight");
assert.equal(certifyFusionEvidence({
  fusion,
  requiredBuild: "build-2",
  adapterMtimeMs: 100,
  fusionLogMtimeMs: 101,
  expectedCaseFingerprints: [fp],
  measuredCaseFingerprints: [fingerprintParams({ width: 101 }, ["width"])],
}).level, "mismatched_fusion_case");
assert.equal(certifyFusionEvidence({
  fusion,
  requiredBuild: "build-2",
  adapterMtimeMs: 100,
  fusionLogMtimeMs: 101,
  requiredCaseAudits: ["ledGrooveAudit"],
}).level, "invalid_fusion");
assert.equal(certifyFusionEvidence({
  fusion: { ...fusion, cases: [{ ...fusion.cases[0], ledGrooveAudit: { ok: false } }] },
  requiredBuild: "build-2",
  adapterMtimeMs: 100,
  fusionLogMtimeMs: 101,
  requiredCaseAudits: ["ledGrooveAudit"],
}).level, "fusion_failed");
assert.equal(certifyFusionEvidence({
  fusion: { ...fusion, cases: [{ ...fusion.cases[0], ledGrooveAudit: { ok: true } }] },
  requiredBuild: "build-2",
  adapterMtimeMs: 100,
  fusionLogMtimeMs: 101,
  requiredCaseAudits: ["ledGrooveAudit"],
}).level, "fusion_verified");

const matrix = runGeneratorCaseMatrix({
  moduleId: "fake_generator",
  cases: [
    { id: "good", params: { width: 100 } },
    { id: "bad", params: { width: -1 } },
  ],
  generate: (params) => ({ params, boards: [] }),
  evaluateCase: ({ caseId, result }) => ({
    params: result.params,
    findings: result.params.width > 0
      ? []
      : [{ code: "invalid_width", detail: `${caseId}: width must be positive` }],
  }),
});
assert.equal(matrix.cases.length, 2);
assert.equal(matrix.cases[0].ok, true);
assert.equal(matrix.cases[1].ok, false);
assert.equal(summarizeGeneratorLoop(matrix).countsByCode.invalid_width, 1);

console.log("OK reusable assembly loop core");
