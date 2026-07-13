# One-Click Connect Pipeline Checklist

**Feature:** Connect one-click verify-all (3a) → batch hardware cut (3c)  
**Status:** offline ready 2026-07-13

---

## Product rules

- [x] One action runs face-verify batch then cut-safe batch create
- [x] Reuses existing 3a / 3c gates (no bbox cut)
- [x] Passes through `gapJoints` + `autoHardware` + UI `rule`
- [x] Cut stage consumes `verifiedRelationships` from verify (no rescan race)
- [x] Default UI type still applies when auto-select is off

---

## Delivered

| Layer | Item |
|-------|------|
| Pure | `modules/hardware/connect_pipeline.py` |
| Controller | `HardwareController.run_connect_pipeline` |
| Route | `hardware.runConnectPipeline` → `hardwarePipelineResult` |
| UI | 「一键验证并创建五金」 |
| Offline | `tests/run_connect_pipeline_offline.py` |

---

## Fusion smoke (manual)

1. Scan / open Connect with panels present
2. Optionally enable gap joints / auto-select
3. Click **一键验证并创建五金**
4. Expect summary: verify counts + create counts; cut features on hosts
