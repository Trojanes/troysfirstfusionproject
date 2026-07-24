# Batch Hardware Cut (3c) Checklist

**Feature:** 对所有已可切关系，按当前 Connect 五金类型批量创建  
**Status:** offline ready 2026-07-12

---

## Product rules

- [x] Only `is_cut_allowed` + contact hardware pairs
  (`edge_to_surface`/`structural_butt_joint` or `surface_to_surface`/`face_contact`)
- [x] Uses current UI hardware type + params
- [x] Failure → skip + remind (does not abort batch)
- [x] Default `maxPairs = 50`
- [x] Does not relax bbox cut gate
- [x] Hydrates persisted `face_verified` before filtering

---

## Delivered

| Layer | Item |
|-------|------|
| Pure | `batch_hardware_from_relationships.py` |
| Fusion | `hardware.createHardwareForCutSafeRelationships` → `hardwareBatchCutResult` |
| UI | Connect「批量创建五金」 |
| Offline | `tests/run_batch_hardware_cut_offline.py` |

## Typical flow

```text
扫描 / 验证全部候选（落盘）
  → 选五金类型与参数
  → 批量创建五金
  → 看通过/跳过提醒
```
