# Post-M9 — Tongue / Groove host groove + target tongue

**Status:** SEALED 2026-07-09 (offline + Fusion smoke PASS 7/7, then remove `--batch tg`).

## Scope

| Item | Detail |
|------|--------|
| Milestone | post-M9 |
| Modifies generators | **No** |
| Host cut | **Yes** — groove pocket on host (surface) panel |
| Target cut | **Yes** — shoulder cuts leaving tongue strip on edge panel |
| Side-contact hardware | **No** |

## Pipeline

```text
VerifiedRelationship (edge_to_surface + structural_butt_joint)
  → HardwareRuleEngine (type=tongue_groove)
  → preview_tongue_groove_from_relationship
  → plan_tongue_groove_cut_from_relationship (needs safeForCut)
  → create_host_groove_cut + create_target_tongue_cut (Fusion)
  → writeback_tongue_groove_feature (host groove + target tongue)
```

## Defaults

- grooveDepthMm: 8
- grooveWidthMm: 4
- tongueProtrusionMm: 7

## Offline

```powershell
cd fusion360-unified-cabinet-plugin
python tests/run_tongue_groove_offline.py
python -m unittest tests.test_panel_metadata_writeback.HardwareRuleEngineTests -v
python tests/run_plugin_offline_regression.py
```

## Fusion smoke

```powershell
# Fusion closed
python scripts/manage_fusion_smokes.py install --batch tg
# Restart Fusion → Scripts → tongue_groove_connect_smoke → Run
# After PASS:
python scripts/manage_fusion_smokes.py remove --batch tg
```

## Acceptance

- [x] Preview includes groove.sketch + tongue.sketch.shoulders
- [x] Cut blocked without verification; cut plan ok after confirm
- [x] Host groove + target tongue Fusion executors + dual writeback
- [x] Wired into `run_plugin_offline_regression.py`
- [x] Fusion smoke PASS (`tongue_groove_connect_smoke` 7/7), then remove `--batch tg`
