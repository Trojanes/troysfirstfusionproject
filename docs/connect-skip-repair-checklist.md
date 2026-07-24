# Connect Skip → Manual Repair Checklist

**Feature:** Click batch/pipeline skip row to load pair for manual fix  
**Status:** offline ready 2026-07-13

---

## Product rules

- [x] Human still drives Connect (no auto cut-all)
- [x] Skip list rows are clickable「手修」
- [x] Click → `relationships.inspectPair` for that panel pair
- [x] Hint by skip reason (declare / face-verify / create)
- [x] Scope: OH/GT/Kitchen declared path + existing face-verify repair

---

## Delivered

| Layer | Item |
|-------|------|
| Pure | `repair_hint_for_skip_reason` in `batch_hardware_from_relationships.py` |
| UI | `connectUiRepairFromSkip` + clickable skip list |
| Offline | `run_batch_hardware_cut_offline.py` + UI tokens |

---

## Fusion smoke (manual)

1. Run 一键流水线 or 批量创建 with at least one skip
2. Open skip list → click「手修」
3. Expect inspect of that pair + next-step message
4. Sync declare or face-verify → preview → create
