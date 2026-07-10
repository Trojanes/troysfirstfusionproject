# Connect Batch C checklist — real cabinet pairs + dual-path verification

**Status:** SEALED (2026-07-09) — offline + Fusion `connect_batch_c_smoke` 8/8 PASS.

## Scope

| Item | Detail |
|------|--------|
| Real cabinet | Overhead `overhead_edge_only` → assembly `OHC_BATCH_C` |
| Pairs | BP↔D0, BP↔FP0 (`edge_to_surface` / `generator_declared`) |
| Dual-path A | `connectExecute confirm` on BP–D0 → preview holes |
| Dual-path B | Select BP–FP0 bodies → `verifySelectedPairFaces` → `face_verified` → preview holes |

## Offline

```powershell
cd fusion360-unified-cabinet-plugin
python tests/run_connect_batch_c_offline.py
# or full suite
python tests/run_plugin_offline_regression.py
```

## Fusion (one touchpoint)

```powershell
# Close Fusion first
python scripts/manage_fusion_smokes.py install --batch c
# Restart Fusion → Shift+S → 脚本 + 由我创建 → Play ▶ connect_batch_c_smoke
# After PASS:
python scripts/manage_fusion_smokes.py remove --batch c
```

## Acceptance

- [x] Offline Batch C ALL PASS (incl. overhead BP↔FP0 offline face_verified)
- [x] Fusion smoke 8/8 PASS (create → reconcile → 2 pairs → confirm path → face-verify path)
- [x] Temporary Scripts entry removed after PASS
- [x] Roadmap Batch C marked SEALED
- [x] Offline overhead golden face verify wired (CI closes Fusion-only gap)

## Notes

- Confirm path may keep `generator_declared` when the relationship is already cut-safe; session confirm still must succeed.
- Face-verify path uses Fusion selection + axis-aligned face matcher (same as main Connect 面验证).
