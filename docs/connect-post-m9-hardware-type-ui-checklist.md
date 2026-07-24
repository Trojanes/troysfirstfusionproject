# Post-M9 — Connect UI hardware-type selector

**Status:** offline sealed (2026-07-10). Params editable in Connect UI.

## Scope

| Item | Detail |
|------|--------|
| Milestone | post-M9 |
| Modifies generators | **No** |
| Deliverable | Connect palette dropdown + editable rule params + generic preview/cut routes |

## UI

Connect → 操作:

- `<select id="connectHardwareType">` — screw / tongue / hinge / lock / runner
- `#connectHardwareParams` — per-type numeric fields (diameter / depth / offsets / counts / pocket size)
- Status: 可切削 vs 仅预览
- Preview / Cut buttons label follow selected type
- Verify hint: generator_declared → face_verified → (debug) manual confirm
- Near-contact (≤1mm) shown on inspect distance row; cut-safe after verify
- Inspect auto-reconciles declarations; main actions: 同步声明 / 面验证; 手动确认 in 开发工具 only

## Product decisions (2026-07-10)

1. **Near-contact ≤1mm is cut-eligible** once verification is cut-safe (same as flush contact).
2. **Default verify path:** prefer `generator_declared` when present; else `face_verified`; keep `manual_confirm` as debug fallback only.
3. **Hardware params are UI-editable** (defaults remain in `CONNECT_HW_RULES`).
4. **Downstream NC consumers of writeback:** not yet — defer metadata polish.

## Default verify path (productized 2026-07-11)

| Step | Behavior |
|------|----------|
| Inspect | If already cut-safe → ready; else auto `reconcileGeneratorDeclarations` |
| Match | Selected pair upgraded when a cut-safe `generator_declared` match exists |
| Else | Guide to 面验证; 手动确认 stays under 开发工具 |
| Helpers | `preferred_verify_step` + `match_declared_relationship_for_pair` in `connect_formal_ui.py` |

## Routes

| Action | Behavior |
|--------|----------|
| `hardware.listHardwareTypes` | Registry rows for selector labels / cutReady |
| `hardware.previewHardwareFromRelationship` | Dispatch by `rule.type` + form params |
| `hardware.createHardwareFromRelationship` | Dispatch by `rule.type` + form params |

Legacy per-type routes remain for smokes.

## Offline

```powershell
cd fusion360-unified-cabinet-plugin
python tests/run_connect_hardware_type_ui_offline.py
python tests/run_plugin_offline_regression.py
```

## Acceptance

- [x] Selector wired for all 5 types
- [x] Per-type params rendered and sent in preview/cut payload
- [x] Offline type-UI smoke PASS
- [x] Verify-path hint + near-contact distance label in Connect UI
- [x] Default path productized: auto-reconcile after inspect; confirm moved to debug
