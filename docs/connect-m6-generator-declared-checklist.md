# M6 Generator-Declared Relationships Checklist

**Milestone:** M6 — Generator-Declared Relationships  
**Status:** ✅ **SEALED** (Overhead v1 — 2026-07-05; GT + Kitchen offline — 2026-07-11; Lounge + Fusion Kitchen/GT/Lounge declared smoke — 2026-07-13)

---

## Scope (v1)

- Overhead skeleton declares structural joints (BP↔D0, BP↔FP0, D0↔FP0, T1↔T2)
- Declarations emitted in Overhead generator JSON (`relationshipDeclarations`)
- Assembly component stores declarations attribute for reconcile
- Reconcile declarations against design-intent bbox geometry (`bboxSource: design_preferred`)
- `generator_declared` verification when geometry matches
- Preview + cut plan accept declared + geometry-validated relationships

---

## Extension: General Tall (2026-07-11)

Offline-ready (same pattern as Overhead):

- GT skeleton declares 4 rail→deck joints: B1↔B3, T1↔T3, B2↔B3, T2↔T3
- Emit: `modules/generalTallCabinet/relationshipDeclarations.ts`
- Catalog: `modules/relationships/general_tall_declared_relationships.py`
- Service dispatch: `generator_declared_service.py` (`ohc.` / `gtc.` scope)
- Offline: `tests/test_generator_declared_relationships.py` (4 GT tests)

Not declared (by design): V1↔B1/T1 intersection; B1↔B2 / T1↔T2 surface stacks.

---

## Extension: Kitchen (2026-07-11)

Offline-ready (same pattern as Overhead / General Tall):

- Kitchen skeleton declares 2 bottom rail→deck joints: B1↔B3, B2↔B3
- Emit: `modules/kitchenCabinet/relationshipDeclarations.ts`
- Catalog: `modules/relationships/kitchen_declared_relationships.py`
- Service dispatch: `generator_declared_service.py` (`kc.` scope)
- Fusion: kitchen assembly writes `relationshipDeclarations` attribute
- Offline: `tests/test_generator_declared_relationships.py` (4 Kitchen tests)

Not declared (by design): top strip-to-deck (intersection on kitchen_base); B1↔B2 surface stack; strip joints.

---

## Extension: Lounge (2026-07-13)

Offline + Fusion declared smoke sealed:

- L_SHAPE declares 3 joints: main_front→main_top, l_front→l_side, l_front→l_top
- Emit: `modules/loungeGenerator/relationshipDeclarations.ts`
- Catalog: `modules/relationships/lounge_declared_relationships.py`
- Service dispatch: `generator_declared_service.py`
- Fusion: lounge assembly writes `relationshipDeclarations`; smoke `--batch declared`
- Offline: `tests/run_declared_generators_offline.py` + lounge unit tests

---

## Runners

> **Note (2026-07-05):** One-click smoke scripts (`connect_pipeline_smoke`, `contact_patch_smoke`) removed. M6 seal used historical Fusion smoke JSON; ongoing verification uses offline regression + manual Fusion reconcile flow.

| Script / surface | Environment |
|------------------|-------------|
| `tests/run_plugin_offline_regression.py` | Terminal — full offline regression |
| `tests/run_declared_generators_offline.py` | Kitchen / GT / Lounge emit→reconcile→preview |
| `tests/run_generator_relationship_regression.py` | Generator declared-relationship matrix |
| `tests/run_connect_demo_pack_offline.py` | Connect demo pack (includes Overhead structural joint) |
| `python scripts/manage_fusion_smokes.py install --batch declared` | Fusion — temporary Play smoke (remove after PASS) |
| **CabinetNC palette → Debug** | Fusion — generate → Reconcile Declarations → cut |

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
- [x] General Tall emit + Python catalog + reconcile offline (2026-07-11)
- [x] Kitchen emit + Python catalog + reconcile offline (2026-07-11)

---

## After M6 (next milestones)

1. ~~**General Tall** — same declaration + reconcile pattern~~ ✅ offline 2026-07-11
2. ~~**Kitchen** — same declaration + reconcile pattern~~ ✅ offline 2026-07-11
3. **Lounge / Fridge** — later generator declaration extensions
4. **M7 Formal Connect UI** — product-facing relationship/hardware UI (sealed)
5. **M8 Panel Metadata Writeback** — body-level `features[]` sync after cut (sealed)
6. **M9 Expand Hardware Types** — tongue/groove, hinge, lock, runner (sealed)

See [`CabinetNC_Connect_Relationship_Hardware_Roadmap.md`](../CabinetNC_Connect_Relationship_Hardware_Roadmap.md).
