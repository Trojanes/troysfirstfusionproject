# Post-M9 — Connect UI hardware-type selector

**Status:** offline sealed (2026-07-09). No Fusion smoke required (palette wiring + route dispatch).

## Scope

| Item | Detail |
|------|--------|
| Milestone | post-M9 |
| Modifies generators | **No** |
| Deliverable | Connect palette dropdown + generic preview/cut routes |

## UI

Connect → 操作:

- `<select id="connectHardwareType">` — screw / tongue / hinge / lock / runner
- Status: 可切削 vs 仅预览
- Preview / Cut buttons label follow selected type
- Preview-only types keep Cut disabled even after confirm

## Routes

| Action | Behavior |
|--------|----------|
| `hardware.listHardwareTypes` | Registry rows for selector labels / cutReady |
| `hardware.previewHardwareFromRelationship` | Dispatch by `rule.type` |
| `hardware.createHardwareFromRelationship` | Dispatch by `rule.type`; preview-only blocked |

Legacy per-type routes remain for smokes.

## Offline

```powershell
cd fusion360-unified-cabinet-plugin
python tests/run_connect_hardware_type_ui_offline.py
python tests/run_plugin_offline_regression.py
```

## Acceptance

- [x] Selector in palette.html
- [x] Generic preview/create routes registered
- [x] Preview works for all 5 types (dispatch)
- [x] Cut ready for screw / tongue / hinge; blocked for lock / runner
- [x] Wired into offline regression
- [ ] Manual: stop/start CabinetNC add-in, open Connect, switch types
