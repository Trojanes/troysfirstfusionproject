# Reusable Generator Loop

**Project rule:** after any generator / adapter / assembly change, run the module autoloop before calling the work done (see `.cursor/rules/generator-loop-selfcheck.mdc`).

The loop has three layers:

1. `generator_loop_framework.js`
   - runs a parameter matrix
   - isolates exceptions per case
   - aggregates findings with stable error codes
2. `assembly_loop_core.js`
   - audits final board-face contacts and forbidden overlaps
   - fingerprints parameter cases
   - certifies current-build Fusion evidence
3. `<module>_autoloop.js`
   - supplies the generator, final Adapter simulator, cases and module invariants

## Minimum module contract

```js
const matrix = runGeneratorCaseMatrix({
  moduleId: "my_module",
  cases: [{ id: "default", params: {} }],
  generate: generateMyModule,
  evaluateCase: ({ caseId, inputParams, result }) => ({
    params: result.params,
    findings: [],
  }),
});
```

An assembly module should additionally provide:

- a simulator of the **final Adapter pipeline**, including placement offsets,
  rotations, cuts and postprocess moves;
- declarative face-contact contracts passed to `auditBoardContacts`;
- forbidden solid-overlap pairs passed to `auditForbiddenOverlaps`;
- Fusion logs containing `adapterBuild`, `caseFingerprint`, final board AABBs
  and semantic audit results.

## Certification rules

- `offline_preflight`: generator/simulator only; never a Fusion pass.
- `stale_fusion`: build, source time or case identity is stale.
- `fusion_failed`: current matching Fusion evidence contains failures.
- `fusion_verified`: current matching Fusion evidence passes.

Do not use generator `worldBoards` as final expected geometry when the Adapter
moves bodies. Expected AABBs must replay the complete Adapter pipeline.
