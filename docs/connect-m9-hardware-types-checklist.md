# M9 Expand Hardware Types Checklist

**Milestone:** M9 — Expand Hardware Types  
**Status:** ✅ **SEALED** (v1 + post-M9 cuts — 2026-07-10; writeback/UI polish 2026-07-11)

---

## Scope (v1)

- Central registry + dispatch: `hardware_rule_engine.py`
- **Implemented (cut-ready):** `screw_hole`, `tongue_groove` (host+target), `hinge_hole`, `drawer_runner_hole`, `lock_cutout` (host-only)
- All types follow VerifiedRelationship → RuleEngine → Preview → Cut → Metadata

---

## Runners

| Script / surface | Environment |
|------------------|-------------|
| `tests/test_panel_metadata_writeback.py` | Terminal — includes `HardwareRuleEngineTests` |
| `tests/run_plugin_offline_regression.py` | Terminal — full offline regression |
| `tests/run_generic_hardware_route_offline.py` | Generic Connect routes + lock pocket record |
| **CabinetNC palette → Connect** | Fusion — all 5 types via selector |

Fusion smokes: `--batch tg|hinge|runner|lock|generic|realhw` via `scripts/manage_fusion_smokes.py`

---

## Completed

- [x] `list_hardware_types()` registry with UI metadata
- [x] `evaluate_hardware_rule()` / `dispatch_hardware_preview()` / `dispatch_hardware_cut_plan()`
- [x] Screw / tongue / hinge / lock / runner Fusion cuts
- [x] Connect UI hardware-type selector + editable params
- [x] Lock pocket writeback uses `kind=pocket` (not circular hole) — 2026-07-11
- [x] Connect cut/preview result panel type-aware — 2026-07-11

See [`connect-post-m9-tongue-groove-checklist.md`](./connect-post-m9-tongue-groove-checklist.md)  
See [`connect-post-m9-scaffold-hardware-checklist.md`](./connect-post-m9-scaffold-hardware-checklist.md)  
See [`connect-post-m9-hardware-type-ui-checklist.md`](./connect-post-m9-hardware-type-ui-checklist.md)  
See [`connect-real-cabinet-hardware-checklist.md`](./connect-real-cabinet-hardware-checklist.md)
