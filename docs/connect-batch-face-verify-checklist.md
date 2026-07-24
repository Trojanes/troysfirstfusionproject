# Batch Face Verify (3a) Checklist

**Feature:** 批量自动面验证 bbox 候选 → `face_verified`  
**Status:** ✅ **SEALED** (2026-07-11) — offline + Fusion `verify_all_connect_smoke` PASS

---

## Product rules (locked)

- [x] Candidate filter: `bbox_candidate` + contact hardware pairs
  (`edge_to_surface`/`structural_butt_joint` or `surface_to_surface`/`face_contact`)
- [x] Default `maxPairs = 200`; overflow → skip `cap_reached` + remind
- [x] Failure → **skip** that pair + user reminders (do not abort batch)
- [x] Never allow `bbox_candidate` to cut (gate unchanged)
- [x] Verification upgrades are **session-only** (no attribute persistence in v1)

## Follow-up (2026-07-11+)

- [x] Persist `face_verified` into panel metadata `relationshipVerifications`
- [x] Hydrate on `relationships.scan` / `scanSelected` / batch verify
- [x] Single-pair face verify also persists to both bodies
- [x] Does not overwrite `generator_declared` / `manual_confirmed`

---

## Delivered

| Layer | Item |
|-------|------|
| Pure | `filter_face_verifiable_candidates` / `verify_all_bbox_candidates` in `face_verification.py` |
| Fusion | `relationships.verifyAllBboxCandidates` → `relationshipFaceVerifyBatchResult` |
| UI | Connect「验证全部候选」+ skip list + reminders |
| Offline | `tests/test_face_verification_batch.py`, `tests/run_verify_all_offline.py` |
| Fusion smoke | `verify_all_connect_smoke` (`--batch verifyall`) — PASS then removed |

---

## Also in this seal (hardware)

- [x] Cut/preview re-plan from **physical** body bboxes (`HardwareController._resolve_cut_panel_snapshots`)
- [x] Fixes silent zero-volume cuts after Overhead `OH_SUPPORT_Z` / divider Z moves
- [x] Real-cabinet hardware Fusion smoke previously PASS (screw BP–D0 + tongue BP–FP0)

---

## How to re-run

```text
# Offline
python tests/run_verify_all_offline.py
python -m unittest tests.test_face_verification_batch -v

# Fusion (temporary)
python scripts/manage_fusion_smokes.py install --batch verifyall
# Play verify_all_connect_smoke → then:
python scripts/manage_fusion_smokes.py remove --batch verifyall
```

Connect UI: 板件连接 → **验证全部候选** → read 通过/跳过 reminders → preview/cut.
