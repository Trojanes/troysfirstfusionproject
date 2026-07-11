# Post-M9 — Hardware writeback + generic route polish

**Status:** offline sealed 2026-07-11. Fusion smokes ready (`--batch generic`, `--batch realhw`).

## Delivered

| Item | Detail |
|------|--------|
| Lock writeback | `build_lock_cutout_panel_feature_record` → `kind=pocket`, W×H×D, sketch |
| Hinge/runner writeback | circular hole + `hostRole` / `hardwareType` tags |
| Generic route offline | `tests/run_generic_hardware_route_offline.py` |
| Generic Fusion smoke | fixture → confirm → preview×5 → `createHardwareFromRelationship` lock cut |
| Real-cabinet Fusion smoke | Overhead BP↔D0 screw + BP↔FP0 tongue via generic routes |
| Connect UI results | type-aware summary (口袋尺寸、榫双边写回等) |
| Gate copy | "hardware preview" (not M7 screw-only) |

## Offline

```powershell
cd fusion360-unified-cabinet-plugin
python tests/run_generic_hardware_route_offline.py
python -m unittest tests.test_panel_metadata_writeback -v
python tests/run_plugin_offline_regression.py
```

## Fusion

```powershell
python scripts/manage_fusion_smokes.py install --batch generic
python scripts/manage_fusion_smokes.py install --batch realhw
```

Play each smoke once, then `remove --batch generic` / `remove --batch realhw`.
