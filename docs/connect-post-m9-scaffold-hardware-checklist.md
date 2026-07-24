# Post-M9 — Hinge / Runner / Lock host cuts

**Status:** hinge + runner + lock SEALED (Fusion 7/7, 2026-07-10).

## Scope

| Item | Detail |
|------|--------|
| Milestone | post-M9 |
| Modifies generators | **No** |
| Allows bbox cut | **No** |
| Deliverable | `hinge_hole` + `drawer_runner_hole` + `lock_cutout` host cuts |

## Defaults

| Type | Key defaults | Cut |
|------|--------------|-----|
| hinge_hole | Ø35 × 13 deep, 2 cups | host-only SEALED |
| drawer_runner_hole | Ø5 × 12 deep, 3 holes | host-only SEALED |
| lock_cutout | 22 × 40 × 12 pocket | host-only SEALED |

## Offline

```powershell
cd fusion360-unified-cabinet-plugin
python tests/run_scaffold_hardware_offline.py
python -m unittest tests.test_panel_metadata_writeback.HardwareRuleEngineTests -v
```

## Fusion smoke (lock) — done

```powershell
# Fusion closed
python scripts/manage_fusion_smokes.py install --batch lock
# Restart Fusion → Scripts → lock_cutout_connect_smoke → Play
# After PASS:
python scripts/manage_fusion_smokes.py remove --names lock_cutout_connect_smoke
```

## Acceptance

- [x] Registry: hinge + runner + lock implemented
- [x] Lock preview + cut plan after confirm
- [x] Wired into offline regression
- [x] Fusion smoke PASS for lock (7/7, then remove --batch lock)
