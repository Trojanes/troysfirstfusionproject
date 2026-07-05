# M6 Generator-Declared Relationships Checklist

**Milestone:** M6 — Generator-Declared Relationships  
**Status:** ✅ **SEALED** (Overhead v1 — 2026-07-05)

---

## Scope (v1)

- Overhead skeleton declares structural joints (BP↔D0, BP↔FP0, D0↔FP0, T1↔T2)
- Declarations emitted in Overhead generator JSON (`relationshipDeclarations`)
- Assembly component stores declarations attribute for reconcile
- Reconcile declarations against design-intent bbox geometry (`bboxSource: design_preferred`)
- `generator_declared` verification when geometry matches
- Preview + cut plan accept declared + geometry-validated relationships

---

## Runners

> **Note (2026-07-05):** One-click smoke scripts (`connect_pipeline_smoke`, `contact_patch_smoke`) removed. M6 seal used historical Fusion smoke JSON; ongoing verification uses offline regression + manual Fusion reconcile flow.

| Script / surface | Environment |
|------------------|-------------|
| `tests/run_plugin_offline_regression.py` | Terminal — full offline regression |
| `tests/run_generator_relationship_regression.py` | Generator declared-relationship matrix |
| `tests/run_connect_demo_pack_offline.py` | Connect demo pack (includes Overhead structural joint) |
| **CabinetNC palette → Debug** | Fusion — generate Overhead → Reconcile Declarations → cut |

```powershell
cd fusion360-unified-cabinet-plugin
python tests/run_plugin_offline_regression.py
```

Fusion: load **UnifiedCabinetPlugin** add-in, then follow Debug UI — no Scripts-folder smoke runner.

---

## Results (2026-07-05, historical)

**Offline (sealed via connect pipeline smoke — script since removed):**

```text
M6 offline: PASS
declarations=4 geometryOk=4
BP↔D0: generator_declared + geometryValidation.ok + cut plan OK
```

Historical JSON (no longer generated): `tests/output/connect_pipeline_smoke_offline_results.json`

**Fusion (historical):**

```text
M6 Connect smoke: PASS
Declarations: 4 / 4 geometry OK
Fusion 2703.1.20
```

JSON: `tests/output/m6_fusion_smoke_results.json`

---

## Completed for M6 seal

- [x] Fusion smoke: generate Overhead → reconcile → cut on declared BP↔D0
- [x] Emit declarations from Overhead generation JSON (`modules/overheadCabinet/relationshipDeclarations.ts`)
- [x] Write declarations to assembly component attribute on Fusion body create
- [x] Reconcile loads embedded declarations from assembly (fallback: Python catalog)

---

## After M6 (next milestones)

1. **General Tall** — same declaration + reconcile pattern (M6 extension, not blocking M7)
2. **M7 Formal Connect UI** — product-facing relationship/hardware UI
3. **M8 Panel Metadata Writeback** — body-level `features[]` sync after cut
4. **M9 Expand Hardware Types** — tongue/groove, hinge, lock, runner

See [`CabinetNC_Connect_Relationship_Hardware_Roadmap.md`](../CabinetNC_Connect_Relationship_Hardware_Roadmap.md).
