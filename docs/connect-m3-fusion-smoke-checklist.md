# M3 Fusion Smoke Test Checklist

**Milestone:** M3 — Relationship-Based Screw-Hole Fusion Cut  
**Status:** ✅ **SEALED** (2026-07-03, Fusion 2703.1.20, overall PASS)

---

## Prerequisites

- [x] Offline regression passes locally (automated):
  ```bash
  python fusion360-unified-cabinet-plugin/tests/run_plugin_offline_regression.py
  ```
- [ ] Fusion 360 with CabinetNC add-in loaded from this repo (`fusion360-unified-cabinet-plugin/`)
- [ ] Active **Design** document (Part or Assembly — fixture supports both)
- [x] Latest plugin code includes M3 UI button **Create Screw Holes From Confirmed Relationship**

### Automated runners

> **Note (2026-07-05):** One-click Fusion smoke scripts (`connect_pipeline_smoke`, `contact_patch_smoke`, per-milestone `m*_connect_smoke.py`) were removed after seal. Use offline regression + this manual Fusion checklist.

- Full offline regression: `tests/run_plugin_offline_regression.py`
- Connect demo pack: `tests/run_connect_demo_pack_offline.py`
- Fusion: **CabinetNC palette → Relationship / Hardware Debug** (steps below)

Smoke JSON is written to `tests/output/` (gitignored; regenerated on each run).

---

## UI location

**CabinetNC palette → Hardware / Installation → Relationship / Hardware Debug**

---

## Smoke flow (execute in order)

### Step 1 — Create Relationship Fixture

- [ ] Click **Create Relationship Fixture**
- [ ] JSON shows `ok: true`
- [ ] `createdBodies` > 0
- [ ] Scan section in response shows relationships including at least one `edge_to_surface`

**Record:** `relationshipCount` = _______

---

### Step 2 — Scan Relationships (optional if fixture scan embedded)

- [ ] Click **Scan Relationships** (or rely on fixture scan result)
- [ ] At least one relationship has:
  - `geometryType`: `edge_to_surface`
  - `relationshipType`: `structural_butt_joint`
  - `roles.hostPanelId` and `roles.targetPanelId` set
- [ ] Every relationship shows:
  - `verification.level`: `bbox_candidate`
  - `safeForPreview`: `true`
  - `safeForCut`: `false`

**Record:** first valid `relationshipId` = _______

---

### Step 3 — Preview Screw Holes

- [ ] Click **Preview Screw Holes From First Valid Relationship**
- [ ] JSON shows `ok: true`
- [ ] `holeCount` >= 1
- [ ] `audit.verificationLevel` = `bbox_candidate`
- [ ] `audit.safeForPreview` = `true`
- [ ] `audit.safeForCut` = `false`

**Record:** `holeCount` = _______, `hostPanelId` = _______, `targetPanelId` = _______

---

### Step 4 — Confirm For Cut

- [ ] Click **Confirm First Valid Relationship For Cut** (or **Confirm Selected…** after Inspect Selected Pair)
- [ ] JSON shows `action`: `manualConfirmForCut`, `ok: true`
- [ ] `verification.level`: `manual_confirmed`
- [ ] `verification.safeForCut`: `true`
- [ ] `persisted`: `false` (session only)

**Record:** confirmed `relationshipId` = _______

---

### Step 5 — Negative gate (bbox cannot cut)

- [ ] Clear confirmed state OR attempt cut **before** Step 4
- [ ] Click **Create Screw Holes From Confirmed Relationship** without confirming
- [ ] Error message contains:
  > No manual_confirmed relationship available. Scan, preview, and confirm a relationship before creating cut.
- [ ] JSON `ok`: `false`

- [ ] (Optional) Re-confirm, then manually edit session — if you skip confirm and send raw bbox relationship via debug console, cut plan should fail with cut-safe error.

---

### Step 6 — Create Screw Holes From Confirmed Relationship

- [ ] Complete Step 4 first
- [ ] Click **Create Screw Holes From Confirmed Relationship**
- [ ] JSON audit shows `ok: true`
- [ ] Verify audit fields:

| Field | Expected |
|-------|----------|
| `operationType` | `SCREW_HOLE_FROM_RELATIONSHIP` |
| `relationshipId` | matches confirmed relationship |
| `hostPanelId` | e.g. fixture host panel id |
| `targetPanelId` | e.g. fixture target panel id |
| `holeCount` | >= 1, matches preview |
| `cutFeatureName` | non-empty |
| `metadataWritten` | `true` |
| `targetBodyModified` | `false` |
| `errors` | `[]` |

**Record:** `cutFeatureName` = _______, `metadataWritten` = _______

---

### Step 7 — Fusion model verification (visual)

- [ ] Identify **host** body by `hostPanelId` in Fusion browser
- [ ] Identify **target** body by `targetPanelId`
- [ ] Host body shows new hole cut feature(s) in timeline
- [ ] Target body has **no** new cut features from this operation
- [ ] Cut feature attributes contain operation metadata (inspect in Fusion if available)

---

## Expected fixture reference (edge_to_surface case)

From `relationship_fixtures.py` golden case `edge_to_surface_001`:

- Host (surface): `REL_SURFACE_B`
- Target (edge): `REL_EDGE_A`
- Geometry: `edge_to_surface` / `structural_butt_joint`

If your first valid relationship differs, record actual ids above.

---

## Failure triage

| Symptom | Likely cause |
|---------|----------------|
| Host body not found | `panelId` attribute missing on fixture bodies |
| Cut ok but `targetBodyModified: true` | bbox overlap; host-only cut safety check failed |
| `metadataWritten: false` | Fusion attribute write issue on cut feature |
| No valid relationship for preview | Fixture scan failed or roles not inferred |
| Cut blocked after confirm | Session state cleared; re-run confirm before cut |

---

## Results log (fill in after test)

```text
Date: 2026-07-03
Tester: User + run_m3_fusion_smoke_in_fusion.py
Fusion version: 2703.1.20
Plugin: d:\project\troysfirstfusionproject-main\fusion360-unified-cabinet-plugin

Step 1 fixture: PASS — createdBodies=10, relationshipCount=45
Step 2 scan: PASS — rel.REL_EDGE_A.REL_SURFACE_B, bbox_candidate, safeForCut=false
Step 3 preview: PASS — holeCount=2, host=REL_SURFACE_B, target=REL_EDGE_A
Step 4 confirm: PASS — manual_confirmed, safeForCut=true
Step 5 negative gate: PASS — bbox blocked
Step 6 create cut: PASS — HW_REL_SCREW_HOLE_1783071531, metadataWritten=true, targetBodyModified=false
Step 7 visual: PASS — cutFeatureInTimeline=true

Overall M3 Fusion smoke: PASS ✅
```

Offline JSON: `fusion360-unified-cabinet-plugin/tests/output/m3_smoke_offline_results.json`

Fusion JSON (after in-Fusion run): `fusion360-unified-cabinet-plugin/tests/output/m3_fusion_smoke_results.json`

Paste representative JSON snippets (preview audit + cut audit) below when complete:

```json
// preview audit (offline 2026-07-03)
{
  "verificationLevel": "bbox_candidate",
  "safeForPreview": true,
  "safeForCut": false,
  "holeCount": 2,
  "hostPanelId": "REL_SURFACE_B",
  "targetPanelId": "REL_EDGE_A"
}
```

```json
// cut audit (Fusion 2026-07-03)
{
  "ok": true,
  "operationType": "SCREW_HOLE_FROM_RELATIONSHIP",
  "relationshipId": "rel.REL_EDGE_A.REL_SURFACE_B",
  "holeCount": 2,
  "cutFeatureName": "HW_REL_SCREW_HOLE_1783071531",
  "metadataWritten": true,
  "targetBodyModified": false
}
```

---

## After M3 passes

✅ Done. Next: **M4 — Real Cabinet Smoke Test** (see roadmap; prefer Overhead or General Tall).
