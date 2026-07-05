# M4 Real Cabinet Smoke Test Checklist

**Milestone:** M4 — Real Cabinet Smoke Test  
**Status:** ✅ **SEALED** (2026-07-03, Fusion 2703.1.20, Overhead, overall PASS)

---

## Prerequisites

- [x] M3 sealed ✅
- [x] Offline M4 passes (2026-07-03 — Overhead, rel.BP.D0, holeCount=2)
- [x] Fusion M4 passes (2026-07-03)

### Automated runners

> **Note (2026-07-05):** One-click Fusion smoke scripts removed. M4 was sealed with historical `m4_fusion_smoke` / `connect_pipeline_smoke` runs; re-verify via offline regression + manual Fusion flow.

- Full offline regression: `tests/run_plugin_offline_regression.py`
- Connect demo pack: `tests/run_connect_demo_pack_offline.py`
- Fusion: **CabinetNC palette** — generate Overhead → scan → preview → confirm → cut (manual)

---

## Results log

```text
Date: 2026-07-03
Tester: User + run_m4_fusion_smoke_in_fusion.py
Fusion version: 2703.1.20
Generator: overhead

Step 1 generate: PASS — 8 bodies (BP,T1,T2,T3,T4,D0,D1,FP0)
Step 2 scan: PASS — 17 relationships; selected rel.ohc.m4_smoke.BP.ohc.m4_smoke.FP0
Step 3 preview: PASS — holeCount=3, host=ohc.m4_smoke.BP, target=ohc.m4_smoke.FP0
Step 4 confirm: PASS — manual_confirmed
Step 5 negative gate: PASS
Step 6 create cut: PASS — HW_REL_SCREW_HOLE_1783072406, metadataWritten=true, targetBodyModified=false
Step 7 visual: PASS — cutFeatureInTimeline=true

Overall M4: PASS ✅
```

**Observation:** Fusion panelIds include run prefix `ohc.m4_smoke.*` (not bare `BP`/`D0`). Script fell back to BP↔FP0 after preferred pairs; still valid `edge_to_surface` / `structural_butt_joint`.

Offline JSON: `fusion360-unified-cabinet-plugin/tests/output/m4_smoke_offline_results.json`  
Fusion JSON: `fusion360-unified-cabinet-plugin/tests/output/m4_fusion_smoke_results.json`

```json
// cut audit (Fusion 2026-07-03)
{
  "ok": true,
  "relationshipId": "rel.ohc.m4_smoke.BP.ohc.m4_smoke.FP0",
  "hostBodyName": "OH_BP",
  "targetBodyName": "OH_FP0",
  "holeCount": 3,
  "cutFeatureName": "HW_REL_SCREW_HOLE_1783072406",
  "metadataWritten": true,
  "targetBodyModified": false
}
```

---

## After M4 passes

✅ Done. Next milestones: **M4.5A Demo Pack** → **M4.6A Visual Overlay** → **M5 Face Verification** (see roadmap).

- M4.5A: [connect-m4.5a-demo-pack-checklist.md](connect-m4.5a-demo-pack-checklist.md)
- M4.6A: [connect-m4.6a-overlay-checklist.md](connect-m4.6a-overlay-checklist.md)
- M5: [connect-m5-face-verification-checklist.md](connect-m5-face-verification-checklist.md)
