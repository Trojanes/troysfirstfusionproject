# M5 Face Verification Checklist

**Milestone:** M5 — Face-Level Relationship Verification  
**Status:** ✅ **SEALED** (2026-07-05, Fusion 2703.1.20, fixture smoke PASS)

---

## Prerequisites

- [x] M4.6A sealed
- [x] Offline face verification tests PASS
- [x] Fusion smoke on fixture pair (`m5_connect_smoke.py`)
- [x] Fusion smoke on real Overhead pair (Batch C `connect_batch_c_smoke`, BP↔FP0)

---

## Offline runners

| Script | Environment |
|--------|-------------|
| `python -m unittest tests.test_face_verification` | Terminal |
| `python -m unittest tests.test_face_verification_batch` | Terminal |
| `tests/run_verify_all_offline.py` | Terminal (batch 3a) |
| `tests/run_relationship_regression.py` | Terminal (includes face + declared tests) |

M5 one-click smoke scripts (`m5_connect_smoke.py`, `run_m5_smoke_offline.py`, later `connect_pipeline_smoke` / `contact_patch_smoke`) were removed after seal. Use offline regression + Debug UI workflow below.

## Fusion workflow (Debug UI)

```text
1. Create Relationship Fixture
2. Select REL_EDGE_A + REL_SURFACE_B (or any 2 panel bodies)
3. Verify Face Contact For Selected Pair
4. Preview Screw Holes (optional)
5. Create Screw Holes — face_verified skips manual confirm
```

Route: `relationships.verifySelectedPairFaces`

---

## Acceptance (v1)

```text
- edge_to_surface fixture pair → face_verified, matchedFaceAId/BId reported
- surface_to_surface fixture pair → face_verified
- gap_parallel / intersection → rejected
- cut gate accepts face_verified
- bbox_candidate still blocked without verify/confirm
```

---

## Results log

```text
Date: 2026-07-05
Fusion version: 2703.1.20
Script: m5_connect_smoke.py
Pair: REL_EDGE_A ↔ REL_SURFACE_B (edge_to_surface)
face_verified: PASS (level=face_verified, safeForCut=true)
matchedFaceAId / matchedFaceBId: REL_EDGE_A::BREP_2 / REL_SURFACE_B::BREP_0
planeDistanceMm: 0.0, overlapArea: 4800 mm², contactAxis: Y
cut without manual confirm: PASS — HW_REL_SCREW_HOLE_1783233622, holeCount=2, metadataWritten=true, targetBodyModified=false
timeline: PASS
Overall M5 Fusion: PASS ✅
```

JSON: `fusion360-unified-cabinet-plugin/tests/output/m5_fusion_smoke_results.json`

---

## After M5 passes

Next: **M6 Generator-Declared Relationships** (sealed).  
Overhead real-pair face verify: see [`connect-batch-c-checklist.md`](./connect-batch-c-checklist.md).

### Face bounds refinement (2026-07-11 / v1.2 2026-07-14)

- Fusion `extract_brep_faces_from_body` builds per-face AABB clamped to panel bbox.
- **v1.2:** prefer **outer-loop edge vertices** (`boundsSource: outer_loop_vertices`); fall back to edge-parameter samples when verts &lt; 3.
- Axis-aligned normals only (`|n| max ≥ 0.99`); non-aligned faces skipped.
- Offline helpers: `bounds_mm_from_points`, `clamp_bounds_to_panel`, `select_face_bound_points`.
- Matching method remains `axis_aligned_planar_faces_v1`.
