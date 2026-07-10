# CabinetNC Connect / Relationship / Hardware Pipeline Roadmap

## Purpose

This document is the master development framework for the CabinetNC **Connect / Relationship / Hardware** module.

Cursor should use this document as the governing roadmap and complete the milestones one by one.

The goal is to build a safe production pipeline:

```text
Panel Metadata
  ↓
Relationship Detection
  ↓
Relationship Verification
  ↓
Hardware Feature Intent
  ↓
Fusion Execution
  ↓
Operation / Panel Metadata Writeback
```

Do not skip layers.

---

## Current Project State

Current completed or partially completed work:

```text
M1 Candidate Layer:
  ✅ bbox/AABB relationship detection
  ✅ relationships.* routes
  ✅ fixture regression
  ✅ offline regression
  ✅ Developer Debug UI
  ✅ hardware preview from relationship

M2 Verification Gate:
  ✅ manual_confirmed verification level
  ✅ confirm helper
  ✅ Developer UI confirmation button
  ✅ cut gate blocks bbox_candidate
  ✅ preview still accepts bbox_candidate

M3 Cut Execution:
  ✅ hardware.createScrewHolesFromRelationship route (host-only cut + metadata audit)
  ✅ Developer Debug UI: Create Screw Holes From Confirmed Relationship
  ✅ validate_manual_confirmed_relationship_for_cut helper
  ✅ offline cut gate tests (69 tests, regression ALL PASS)
  ✅ Fusion smoke test PASS (Fusion 2703.1.20, 2026-07-03)

M4 Real Cabinet Smoke:
  ✅ Overhead generator Fusion smoke PASS (2026-07-03, Fusion 2703.1.20)
  ✅ offline + Fusion runners; BP↔FP0 edge_to_surface cut on real bodies

M4.5A Demo / Golden Case Pack:
  ✅ connect_demo_pack.py (3 demos, eligibility, summaries)
  ✅ offline runner ALL PASS (fixture + Overhead + negative filtering)

M4.6A Relationship Visual Overlay:
  ✅ overlay line + labels (CustomGraphics v3)
  ✅ selected-pair overlay route (Show Overlay For Selected Pair)
  ✅ offline self-check + regression PASS
  ✅ Fusion validated by user

M5 Face Verification:
  ✅ SEALED (2026-07-05) — face_verified + verifySelectedPairFaces
  (M5 one-click smoke scripts removed; use regression + Debug UI)

M6 Generator Declared Relationships:
  ✅ SEALED (2026-07-05) — Overhead v1 offline + Fusion smoke PASS
  ✅ relationshipDeclarations in Overhead generator JSON + assembly attribute
  ✅ reconcile + generator_declared cut gate + design_preferred bbox validation

M7 Formal Connect UI:
  ✅ SEALED (2026-07-05) — Formal Connect card + offline/Fusion smoke
  ✅ connect_list / connect_execute + action gates (preview/confirm/cut)
  ✅ palette Connect M7 UI (filters, table, detail, operation results)

M8 Panel Metadata Writeback:
  ✅ SEALED (2026-07-05) — body features[] writeback after screw-hole cut
  ✅ panel_metadata_writeback + dedupe + metadata scan compatibility

M9 Expand Hardware Types:
  ✅ SEALED (v1 scaffold — 2026-07-05) — hardware_rule_engine registry
  ✅ screw_hole implemented; tongue/groove/hinge/lock/runner scaffold (cut blocked)

Batch B (Main Connect polish — SEALED 2026-07-09):
  ✅ ContactPatch-centric Connect card (probe selection, contact overlay, preview/confirm/cut)
  ✅ Main UI 面验证 button wired to relationships.verifySelectedPairFaces
  ✅ Offline: day1/day2/connect_main_flow (+ face_verified cut gate) in run_plugin_offline_regression
  ✅ Fusion: connect_main_flow_smoke PASS (13/13), then remove --batch main

Batch C (Real cabinet pairs + dual-path — SEALED 2026-07-09):
  ✅ Offline dual-path: confirm vs face_verified cut gates + preview
  ✅ Offline overhead pairs BP–D0 + BP–FP0 preview
  ✅ Fusion: connect_batch_c_smoke PASS (8/8), then remove --batch c
  📄 docs/connect-batch-c-checklist.md

Post-M9 Tongue/Groove full pair (SEALED 2026-07-09):
  ✅ tongue_groove preview (host=groove, target=tongue) + groove.sketch + tongue shoulders
  ✅ cut plan after confirm/face_verified; bbox still blocked
  ✅ Fusion host-groove + target-tongue executors + dual writeback
  ✅ offline: run_tongue_groove_offline.py + HardwareRuleEngineTests
  ✅ Fusion: tongue_groove_connect_smoke PASS (7/7), then remove --batch tg
  ✅ Fixture cleanup before create (avoids stale REL_* body cuts)
  📄 docs/connect-post-m9-tongue-groove-checklist.md

Post-M9 Hinge/Runner/Lock cut (SEALED 2026-07-10):
  ✅ hinge_hole SEALED (Fusion 7/7)
  ✅ drawer_runner_hole SEALED (Fusion 7/7; reuses screw-hole CAD)
  ✅ lock_cutout SEALED (Fusion 7/7; reuses tongue/groove rect CAD)
  ✅ offline: run_scaffold_hardware_offline.py + HardwareRuleEngineTests
  ✅ Fusion: lock_cutout_connect_smoke PASS (7/7), then remove --batch lock
  📄 docs/connect-post-m9-scaffold-hardware-checklist.md

Post-M9 Connect UI hardware-type selector (offline sealed 2026-07-09):
  ✅ palette dropdown + cutReady status
  ✅ hardware.listHardwareTypes / previewHardwareFromRelationship / createHardwareFromRelationship
  ✅ offline: run_connect_hardware_type_ui_offline.py
  📄 docs/connect-post-m9-hardware-type-ui-checklist.md
```

Current relationship layer is **not production-truth**. It is currently:

```text
bbox/AABB spatial candidate detection
  +
rule-based semantic inference
```

It must not be treated as true BRep face-to-face physical connection.

---

## Global Architecture Rules

### Rule 1: Relationship is always pairwise

All relationships are between exactly two panels.

```text
Panel A ↔ Panel B
```

Do not create multi-panel relationship structures at this stage.

Complex assemblies can later be expressed as multiple pairwise relationships.

---

### Rule 2: bbox_candidate is preview-only

All bbox/AABB-detected relationships must be treated as candidates:

```json
{
  "detectionMethod": "bbox_aabb",
  "verification": {
    "level": "bbox_candidate",
    "safeForPreview": true,
    "safeForCut": false,
    "requiresManualConfirmation": true
  }
}
```

Do not allow automatic Fusion cut from `bbox_candidate`.

---

### Rule 3: cut requires verification

Fusion cut is only allowed when:

```text
relationship.verification.safeForCut === true
```

Allowed cut-safe levels:

```text
manual_confirmed
face_verified
generator_declared
cut_approved
```

Blocked levels:

```text
bbox_candidate
unknown
collision
none
gap_parallel
```

---

### Rule 4: Hardware must consume BoardRelationship

Hardware modules must not rediscover board contact independently.

Correct structure:

```text
RelationshipService
  ↓
BoardRelationship
  ↓
HardwareRuleEngine
  ↓
HardwareFeatureIntent
  ↓
FusionExecutor
```

Do not put relationship detection logic inside hardware controllers.

---

### Rule 5: UI is currently Developer Debug UI

Current UI should only support debugging, smoke testing, JSON audit, and manual confirmation.

Do not build customer-facing production UI until backend cut and metadata flow is stable.

---

### Rule 6: Do not modify generators unless a milestone explicitly requires it

For M1–M5, do not modify existing generator behavior.

Generator-declared relationships are M6.

---

## Core Data Concepts

### BoardRelationship

Expected core fields:

```ts
BoardRelationship {
  schemaVersion: 1
  relationshipId: string

  panelA: {
    panelId: string
    bodyName: string
    boardType?: string
    role?: string
    sourceBoardId?: string
    materialClass?: string
  }

  panelB: {
    panelId: string
    bodyName: string
    boardType?: string
    role?: string
    sourceBoardId?: string
    materialClass?: string
  }

  geometryType:
    | "edge_to_surface"
    | "surface_to_surface"
    | "gap_parallel"
    | "intersection"
    | "none"

  relationshipType:
    | "structural_butt_joint"
    | "face_contact"
    | "door_to_carcass_candidate"
    | "collision"
    | "unknown"

  contact: {
    axis: "X" | "Y" | "Z" | "NONE"
    distanceMm: number
    overlapX: number
    overlapY: number
    overlapZ: number
    contactLengthMm: number
    contactAreaMm2: number
  }

  roles: {
    hostPanelId?: string
    targetPanelId?: string
  }

  source: {
    method:
      | "geometry_detected"
      | "semantic_inferred"
      | "manual"
      | "generator_declared"
    confidence: number
    ruleId?: string
  }

  verification: {
    level:
      | "bbox_candidate"
      | "manual_confirmed"
      | "face_verified"
      | "generator_declared"
      | "cut_approved"
    safeForPreview: boolean
    safeForCut: boolean
    requiresManualConfirmation: boolean
  }

  validation: {
    ok: boolean
    warnings: string[]
    errors: string[]
  }
}
```

---

### HardwareFeatureIntent

Expected core structure:

```ts
HardwareFeatureIntent {
  schemaVersion: 1
  featureId: string
  type:
    | "screw_hole"
    | "hinge_hole"
    | "lock_cutout"
    | "runner_hole"
    | "tongue"
    | "groove"

  sourceRelationshipId: string

  hostPanelId: string
  targetPanelId?: string

  geometry: object

  source: {
    method: "relationship_based_rule"
    ruleId: string
  }

  validation: {
    ok: boolean
    warnings: string[]
    errors: string[]
  }
}
```

Current supported hardware feature:

```text
screw_hole_from_edge_to_surface_v1
```

Do not implement hinge, lock, runner, tongue/groove until screw-hole connect pipeline is stable.

---

# Milestone 1 — Candidate Relationship Layer

## Status

```text
✅ Completed / mostly completed
```

## Goal

Detect pairwise board relationship candidates using bbox/AABB.

## Required Capabilities

```text
- collect panel bodies
- build PanelSnapshot[]
- classify bbox/AABB relationships
- output BoardRelationship[]
- support routes:
  - relationships.scan
  - relationships.scanSelected
  - relationships.inspectPair
  - relationships.createTestFixture
- support test fixture
- support offline regression
- support Developer Debug UI smoke flow
```

## Classification Types

```text
edge_to_surface
surface_to_surface
gap_parallel
intersection
none
```

## Acceptance Criteria

```text
- bbox/AABB detection works
- JSON audit is readable
- fixture can be created
- scan can detect fixture relationships
- offline regression passes
- all bbox relationships are verification.level = bbox_candidate
- bbox_candidate safeForPreview = true
- bbox_candidate safeForCut = false
```

## Do Not Do

```text
- do not create Fusion cuts
- do not mark bbox_candidate as cut-safe
- do not implement face-level detection
- do not modify generators
```

---

# Milestone 2 — Verification Gate

## Status

```text
✅ Completed / should be sealed if tests pass
```

## Goal

Add a manual confirmation gate so bbox candidates can be explicitly approved for controlled cut testing.

## Required Behavior

Add verification level:

```text
manual_confirmed
```

Manual confirmed state:

```json
{
  "level": "manual_confirmed",
  "safeForPreview": true,
  "safeForCut": true,
  "requiresManualConfirmation": false
}
```

## Required Capabilities

```text
- helper to confirm relationship for cut
- require geometryType = edge_to_surface
- require relationshipType = structural_butt_joint
- require roles.hostPanelId
- require roles.targetPanelId
- Developer UI confirm button
- preview still accepts bbox_candidate
- cut validation rejects bbox_candidate
- cut validation accepts manual_confirmed
```

## Tests

Cover:

```text
- bbox_candidate is not safe for cut
- bbox_candidate is safe for preview
- valid bbox_candidate can become manual_confirmed
- manual_confirmed is safe for cut
- unsupported geometryType cannot be manually confirmed
- missing hostPanelId cannot be manually confirmed
- missing targetPanelId cannot be manually confirmed
- hardware preview still accepts bbox_candidate
- cut validation rejects bbox_candidate
- cut validation accepts manual_confirmed
```

## Acceptance Criteria

```text
- offline regression passes
- relationship tests pass
- hardware preview tests pass
- manual confirmation tests pass
- Developer UI can scan, preview, confirm, and show updated JSON
- bbox_candidate remains safeForCut=false
- manual_confirmed becomes safeForCut=true
- no Fusion cut is required in this milestone
```

## Do Not Do

```text
- do not implement Fusion cut in M2
- do not persist manual confirmations into production metadata
- do not implement face-level detection
- do not modify generators
```

---

# Milestone 3 — Relationship-Based Screw-Hole Fusion Cut

## Status

```text
✅ SEALED — offline + Fusion smoke complete (2026-07-03)

Completed:
  ✅ hardware.createScrewHolesFromRelationship
  ✅ cut gate: bbox_candidate blocked, manual_confirmed accepted
  ✅ Developer Debug UI full flow (scan → preview → confirm → create cut)
  ✅ validate_manual_confirmed_relationship_for_cut()
  ✅ offline regression ALL PASS
  ✅ Fusion smoke ALL PASS (7/7 steps, Fusion 2703.1.20)
  ✅ Results: fusion360-unified-cabinet-plugin/tests/output/m3_fusion_smoke_results.json
```

## Goal

Create actual screw-hole Fusion cuts from a manually confirmed relationship.

Target flow:

```text
Scan Relationships
  ↓
Preview Screw Holes
  ↓
Confirm Relationship For Cut
  ↓
Create Screw Holes From Confirmed Relationship
  ↓
Write cut feature metadata
  ↓
Return JSON audit
```

## Required Route

```text
hardware.createScrewHolesFromRelationship
```

## Required Developer UI Button

```text
Create Screw Holes From Confirmed Relationship
```

## Input Rule

The cut route must require:

```text
relationship.verification.safeForCut === true
```

For current milestone, accepted relationship level:

```text
manual_confirmed
```

Rejected:

```text
bbox_candidate
safeForCut=false
unsupported geometryType
missing hostPanelId
missing targetPanelId
```

## Supported Relationship

Only support:

```text
geometryType = edge_to_surface
relationshipType = structural_butt_joint
```

## Fusion Execution Requirements

```text
- resolve host body by hostPanelId
- resolve target body by targetPanelId for audit only
- create screw-hole cuts only on host body
- target body must not be cut
- use participantBodies or project-safe equivalent
- write operation metadata on created cut feature
- return stable JSON audit
```

## Suggested Cut Feature Metadata

```json
{
  "operationType": "SCREW_HOLE_FROM_RELATIONSHIP",
  "sourceRelationshipId": "...",
  "hostPanelId": "...",
  "targetPanelId": "...",
  "ruleId": "screw_hole_from_edge_to_surface_v1",
  "holeCount": 2,
  "diameterMm": 4,
  "depthMm": 15
}
```

## Suggested JSON Audit

```json
{
  "ok": true,
  "operationType": "SCREW_HOLE_FROM_RELATIONSHIP",
  "relationshipId": "...",
  "hostPanelId": "...",
  "targetPanelId": "...",
  "holeCount": 2,
  "cutFeatureName": "...",
  "metadataWritten": true,
  "warnings": [],
  "errors": []
}
```

## Required Tests

Offline tests should cover non-Fusion logic:

```text
- cut route rejects bbox_candidate
- cut route accepts manual_confirmed
- cut route rejects safeForCut=false
- cut route rejects unsupported geometryType
- cut route rejects missing hostPanelId
- cut route rejects missing targetPanelId
- metadata payload is stable
- preview route remains unchanged
```

## Fusion Smoke Test

**Detailed checklist:** [`docs/connect-m3-fusion-smoke-checklist.md`](docs/connect-m3-fusion-smoke-checklist.md)

Summary flow:

```text
1. Create Relationship Fixture
2. Scan Relationships
3. Preview Screw Holes From First Valid Relationship
4. Confirm First Valid Relationship For Cut
5. (Negative) Attempt cut without confirm — must fail
6. Create Screw Holes From Confirmed Relationship
7. Visual verify host cut, target unchanged, timeline metadata
```

Verify:

```text
- JSON ok=true
- hostPanelId / targetPanelId correct
- holeCount matches preview
- host body is cut; target body is not cut
- cut feature metadata exists (metadataWritten: true)
- bbox_candidate cannot bypass gate
```

Record results in the checklist **Results log** section before marking M3 sealed.

## Acceptance Criteria

```text
Offline (complete):
  ✅ offline regression passes
  ✅ relationship + hardware preview tests pass
  ✅ M2 manual confirmation tests pass
  ✅ Developer UI confirmed cut button wired
  ✅ button refuses without manual_confirmed
  ✅ bbox_candidate cannot be cut

Fusion smoke (complete — 2026-07-03):
  ✅ actual Fusion cut modifies host body only
  ✅ target body remains unmodified (targetBodyModified: false)
  ✅ cut feature metadata written (metadataWritten: true)
  ✅ JSON audit matches expected fields
  ✅ cut feature in timeline (HW_REL_SCREW_HOLE_*)
  ✅ generator behavior unchanged
  ✅ hardware side-contact cut behavior unchanged
```

## Do Not Do

```text
- do not implement hinge / lock / runner
- do not implement tongue / groove
- do not implement face-level verification
- do not modify generators
- do not build formal product UI
```

---

# Milestone 4 — Real Cabinet Smoke Test

## Status

```text
✅ SEALED — offline + Fusion smoke complete (2026-07-03)

Generator: Overhead (8 bodies, 17 relationships)
Selected pair: BP ↔ FP0 (ohc.m4_smoke.BP / ohc.m4_smoke.FP0)
Cut: 3 holes on host OH_BP, target OH_FP0 unchanged
Results: fusion360-unified-cabinet-plugin/tests/output/m4_fusion_smoke_results.json

Note: Fusion panelIds use run prefix (ohc.m4_smoke.*); golden BP↔D0 ids differ from offline snapshots.
```

## Goal

Validate the debug connect pipeline on a real generated cabinet, not only synthetic fixtures.

## Recommended First Generator

Use one of:

```text
Overhead
General Tall
Kitchen
```

Prefer the generator with the most stable panel metadata.

## Smoke Flow

Inside Fusion:

```text
1. Generate a simple real cabinet
2. Run panel metadata scan if required
3. Scan Relationships
4. Inspect relationship JSON
5. Identify one reasonable edge_to_surface structural_butt_joint
6. Preview screw holes
7. Manually confirm relationship
8. Create screw holes from confirmed relationship
9. Verify host body cut
10. Verify target body not cut
11. Verify cut feature metadata
```

## Data to Record

Record JSON audit for:

```text
- relationship scan
- selected / first valid relationship
- screw-hole preview
- manual confirmation
- cut result
```

## Expected Findings

Real generated cabinets may reveal:

```text
- missing panelId
- inconsistent boardType / role
- wrong host / target inference
- too many intersections
- false edge_to_surface candidates
- doors/front panels being incorrectly included
- same module/runId filtering needs
```

## Follow-up Filters If Needed

Add filters only after observing real cabinet output:

```text
- same runId filter
- same module filter
- exclude door/front_panel for screw structural joints
- exclude gap_parallel for screw cut
- suppress obvious intersection false positives
- require material/thickness compatibility
```

## Acceptance Criteria

```text
✅ at least one real cabinet can be generated (Overhead, 8 bodies)
✅ relationships.scan detects panel candidates (17 relationships)
✅ valid edge_to_surface candidate previewed (BP↔FP0, 3 holes)
✅ relationship manually confirmed (manual_confirmed)
✅ screw holes cut on host only (OH_BP)
✅ target body unmodified (targetBodyModified: false)
✅ JSON reports captured (m4_fusion_smoke_results.json)
✅ no generator behavior changes required
```

## Do Not Do

```text
- do not attempt one-click connect for all relationships
- do not cut all detected candidates
- do not claim production readiness
- do not implement formal UI
```

---

# Milestone 5 — Face-Level Relationship Verification

## Status

```text
✅ SEALED — offline + Fusion fixture smoke complete (2026-07-05)

Completed:
  ✅ face_verified verification level
  ✅ face_verification.py + face_verification_fusion.py (BRep faces)
  ✅ relationships.verifySelectedPairFaces + Debug UI
  ✅ cut gate accepts face_verified
  ✅ offline tests + run_m5_smoke_offline.py ALL PASS
  ✅ Fusion m5_connect_smoke.py ALL PASS (8/8 steps, Fusion 2703.1.20)
  ✅ Results: tests/output/m5_fusion_smoke_results.json

Optional follow-up (not blocking M6):
  ❌ real Overhead pair face verify in Fusion
  ❌ BRep face bounds refinement beyond axis-aligned v1
```

## Goal

Upgrade selected pair verification from bbox/AABB candidate to true or near-true face-level verification.

This is not required before M3/M4, but is required before production automation.

## New Verification Level

```text
face_verified
```

Face verified state:

```json
{
  "level": "face_verified",
  "safeForPreview": true,
  "safeForCut": true,
  "requiresManualConfirmation": false
}
```

## Required Capabilities

First version should support selected pair only:

```text
relationships.verifySelectedPairFaces
```

or:

```text
relationships.verifyPairFaces
```

## Inputs

```text
- two selected panel bodies
- existing BoardRelationship candidate, if available
- faceRegistry, if available
- Fusion BRep face data
```

## Verification Logic

Check:

```text
- faceClass: SURFACE / EDGE
- face normals are parallel or opposite as expected
- face plane distance <= tolerance
- projected overlap region is valid
- matched face ids can be reported
- matched contact area is above threshold
```

## Output

Return relationship upgraded to:

```text
verification.level = face_verified
safeForCut = true
```

Only if all required checks pass.

## First Supported Cases

Only support:

```text
- axis-aligned rectangular panels
- edge_to_surface
- surface_to_surface
```

Do not support:

```text
- rotated arbitrary panels
- curved panels
- miter joints
- sloped caravan panels
- holes/grooves as contact faces
```

## Acceptance Criteria

```text
- bbox_candidate can be face-verified for a simple fixture
- selected real cabinet panel pair can be face-verified
- false bbox candidates can be rejected
- matchedFaceAId / matchedFaceBId are reported
- cut route can accept face_verified
- offline tests cover face verification helper logic where possible
```

## Do Not Do

```text
- do not replace all bbox detection
- do not attempt full geometric robustness in v1
- do not handle irregular DXF panels in v1
```

---

# Milestone 6 — Generator-Declared Relationships

## Status

```text
✅ SEALED — Overhead v1 (2026-07-05)

Completed:
  ✅ generator_declared verification level
  ✅ overhead_declared_relationships.py + modules/overheadCabinet/relationshipDeclarations.ts
  ✅ generator_declared_relationships.py + generator_declared_service.py
  ✅ relationships.reconcileGeneratorDeclarations + Debug UI button
  ✅ cut gate accepts generator_declared when geometryValidation.ok
  ✅ offline regression + historical Fusion smoke (M6–M9 sealed 2026-07-05)
  ✅ relationshipDeclarations embedded in Overhead generator JSON output
  ✅ assembly component attribute + reconcile loads embedded declarations

Next extension (not blocking M7):
  ❌ General Tall / Kitchen / Lounge / Fridge generators
```

## Goal

Make generators declare intended joints during generation so relationship semantics come from design intent, not only geometry inference.

## New Verification Level

```text
generator_declared
```

Generator-declared relationship should still be geometry-validated before production cut.

## Generator Declaration Example

```json
{
  "relationshipId": "rel.ohc.run1.side_left.bottom",
  "type": "structural_butt_joint",
  "hostPanelId": "ohc.run1.side_left",
  "targetPanelId": "ohc.run1.bottom",
  "allowedHardware": ["screw_hole", "tongue_groove"],
  "source": {
    "method": "generator_declared",
    "generator": "overhead",
    "ruleId": "side_bottom_joint_v1"
  }
}
```

## Required Capabilities

```text
- generator can emit intended relationships
- RelationshipService can load declared relationships
- declared relationship can be compared against bbox/face geometry
- warnings emitted if declared relationship geometry does not match actual body positions
```

## Priority Generators

Implement in this order:

```text
1. Overhead
2. General Tall
3. Kitchen
4. Lounge
5. Fridge
```

Only move to next generator after the previous one passes smoke tests.

## Acceptance Criteria

```text
- one generator emits declared relationships
- RelationshipService reports them
- declared relationship can be validated against geometry
- hardware preview can consume declared relationship
- cut can consume declared + geometry-validated relationship
```

## Do Not Do

```text
- do not modify all generators at once
- do not use declarations without geometry validation
- do not replace manual_confirmed or face_verified
```

---

# Milestone 7 — Formal Connect UI

## Status

```text
✅ SEALED (2026-07-05)
```

Checklist: docs/connect-m7-formal-ui-checklist.md

## Goal

Create a product-facing Connect UI after backend relationship, verification, cut, and metadata flow are stable.

## Required UI Features

```text
- list relationships
- filter by type
- show verification level
- show safeForPreview / safeForCut
- show confidence
- inspect selected relationship
- preview hardware
- confirm relationship
- create cut
- show operation metadata
- show warnings/errors
```

## UI Must Clearly Distinguish

```text
bbox_candidate:
  candidate only, preview allowed, cut blocked

manual_confirmed:
  user-approved for cut testing

face_verified:
  geometry verified

generator_declared:
  design-intent relationship

cut_approved:
  final machining-approved relationship
```

## Acceptance Criteria

```text
- user can inspect relationships without reading raw JSON
- user can preview hardware for safe candidates
- user can confirm a relationship
- user can create cut only when safeForCut=true
- UI prevents bbox_candidate direct cut
- UI displays operation result and metadata status
```

## Do Not Do

```text
- do not hide verification state
- do not make one-click cut-all default
- do not make bbox_candidate look production-safe
```

---

# Milestone 8 — Panel Metadata Writeback Integration

## Status

```text
✅ SEALED (2026-07-05)
```

Checklist: docs/connect-m8-panel-metadata-writeback-checklist.md

## Goal

## Current M3 Writeback

M3 writes metadata to cut feature only.

## Future Writeback Target

Update body-level `metadata.features[]` with screw-hole feature records.

Potential feature record:

```json
{
  "featureId": "...",
  "kind": "hole",
  "source": "hardware_relationship",
  "operationType": "SCREW_HOLE_FROM_RELATIONSHIP",
  "sourceRelationshipId": "...",
  "hostPanelId": "...",
  "targetPanelId": "...",
  "diameterMm": 4,
  "depthMm": 15,
  "cutType": "FULL",
  "positionsLocal": []
}
```

## Required Capabilities

```text
- safe helper for reading body-level panel metadata
- safe helper for appending hardware feature
- no duplicate feature writes
- feature can be found by metadata scan
- feature can later be exported to nesting/CAM intent
```

## Acceptance Criteria

```text
- cut feature metadata exists
- body-level features[] receives corresponding hardware feature
- metadata scan reports the feature
- duplicate route calls do not create duplicate records unless explicitly allowed
```

## Do Not Do

```text
- do not write inconsistent features[]
- do not break existing faceRegistry / millingSurfaceSvg
- do not update panel metadata before cut execution succeeds
```

---

# Milestone 9 — Expand Hardware Types

## Status

```text
✅ SEALED (v1 scaffold — 2026-07-05)
```

Checklist: docs/connect-m9-hardware-types-checklist.md

## Goal

After screw-hole connect pipeline is stable, expand to other hardware and connection types.

## Suggested Order

```text
1. screw_hole improvements
2. tongue / groove
3. hinge hole
4. lock cutout
5. drawer runner hole
```

## Rule

Each new hardware type must follow the same pipeline:

```text
VerifiedRelationship
  ↓
HardwareRuleEngine
  ↓
HardwareFeatureIntent
  ↓
Preview
  ↓
Cut
  ↓
Metadata
```

Do not implement any hardware type as an ad-hoc Fusion cut script.

---

# Cursor Execution Protocol

For every new task, Cursor must state:

```text
1. Which milestone this task belongs to.
2. Whether it modifies generators.
3. Whether it allows bbox_candidate to cut.
4. Whether it modifies existing hardware side-contact behavior.
5. Which tests will be added or updated.
6. What the acceptance criteria are.
```

If any answer violates the global rules, stop and ask for clarification.

---

# Immediate Next Task

**Batch A/B/C**, **tongue/groove**, **hinge_hole**, **drawer_runner_hole**, **lock_cutout**, **Connect UI selector** sealed.

All five Connect hardware types are cut-ready (host-only where applicable).
Post-M9 scaffold hardware lane is complete.

Checklist: `docs/connect-post-m9-scaffold-hardware-checklist.md`

M7 reference (sealed):
- Checklist: docs/connect-m7-formal-ui-checklist.md

M8 reference (sealed):
- Checklist: docs/connect-m8-panel-metadata-writeback-checklist.md

M9 reference (sealed):
- Checklist: docs/connect-m9-hardware-types-checklist.md

M6 reference (sealed):
- Checklist: docs/connect-m6-generator-declared-checklist.md

M4 reference (sealed):
- Checklist: docs/connect-m4-real-cabinet-smoke-checklist.md

M4.5A reference (sealed):
- Runner: tests/run_connect_demo_pack_offline.py
- Output: tests/output/connect_demo_pack_summaries.json

M4.6A reference (sealed):
- Runner: tests/run_relationship_overlay_selfcheck.py
- Route: relationships.showRelationshipOverlayForSelected

M5 scope (active):
- Upgrade selected pair verification from bbox/AABB to face-level contact
- New verification level: `face_verified`
- Runners: `tests/run_plugin_offline_regression.py` (offline); Fusion via Connect palette + Debug UI
- See Milestone 5 section below
