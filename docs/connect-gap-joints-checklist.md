# Configurable Gap Joints Checklist

**Feature:** Connect optional gap joints (`gap_parallel`) — default **off**  
**Status:** offline ready 2026-07-13

---

## Product rules

- [x] Not door-specialized — any `gap_parallel` with host/target
- [x] Default `enabled: false` (scan may list gaps; not in 3a/3c / hardware gates)
- [x] User settings: enabled, minGapMm, maxGapMm, includeInBatch
- [x] Session persist: `cabinetnc.connect.gapJoints.v1`
- [x] When enabled: same verify → cut-safe → batch/single path as contact pairs
- [x] Face verify uses distance band `[minGapMm, maxGapMm]` (contact path unchanged)
- [x] Does not relax bbox cut gate

---

## Delivered

| Layer | Item |
|-------|------|
| Pure | `normalize_gap_joints_settings` / `is_hardware_eligible` |
| Scan | gap host/target via face-thickness rule |
| Verify | `gap_parallel` in face verify when enabled |
| 3a/3c | filters accept gap when enabled + includeInBatch |
| UI | Connect「启用缝隙接头」+ min/max |
| Offline | `tests/test_gap_joints.py` |

## Typical flow

```text
（默认）扫描可见 gap，但不进验证全部 / 批量五金
  → 勾选「启用缝隙接头」，设 min/max
  → 验证全部 / 预览 / 批量创建五金
```
