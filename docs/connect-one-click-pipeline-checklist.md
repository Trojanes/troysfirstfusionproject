# One-Click Connect Pipeline Checklist

**Feature:** Connect one-click declare → verify-all (3a) → batch hardware cut (3c)  
**Status:** offline ready 2026-07-13 (declaration-first)

---

## Product rules

- [x] One action: reconcile generator declarations → face-verify remaining → batch create
- [x] Same panel-pair prefers `generator_declared` over `face_verified`
- [x] Declarations alone can cut if face-verify fails (verify errors → warnings)
- [x] Reuses existing 3a / 3c gates (no bbox cut)
- [x] Passes through `gapJoints` + `autoHardware` + UI `rule`
- [x] Default UI type still applies when auto-select is off

---

## Delivered

| Layer | Item |
|-------|------|
| Pure | `modules/hardware/connect_pipeline.py` (`merge_pipeline_cut_candidates`) |
| Controller | `HardwareController.run_connect_pipeline` |
| Route | `hardware.runConnectPipeline` → `hardwarePipelineResult` |
| UI | 「一键验证并创建五金」 |
| Offline | `tests/run_connect_pipeline_offline.py` |

---

## Fusion smoke (manual)

1. Generate Overhead / GT / Kitchen with declarations
2. Optionally enable gap joints / auto-select
3. Click **一键验证并创建五金**
4. Expect summary: 声明可切 + 验证通过 + 创建 counts; hosts get cut features
