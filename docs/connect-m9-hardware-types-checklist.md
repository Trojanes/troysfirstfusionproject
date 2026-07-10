# M9 Expand Hardware Types Checklist

**Milestone:** M9 — Expand Hardware Types  
**Status:** ✅ **SEALED** (v1 scaffold — 2026-07-05)

---

## Scope (v1)

- Central registry + dispatch: `hardware_rule_engine.py`
- **Implemented:** `screw_hole` (existing relationship pipeline)
- **Implemented:** `tongue_groove` — host groove + target tongue shoulders
- **Implemented:** `hinge_hole`, `drawer_runner_hole`, `lock_cutout` (host-only cuts; post-M9)
- All types follow VerifiedRelationship → RuleEngine → Preview → Cut → Metadata shape

---

## Runners

> **Note (2026-07-05):** One-click smoke scripts removed.

| Script / surface | Environment |
|------------------|-------------|
| `tests/test_panel_metadata_writeback.py` | Terminal — includes `HardwareRuleEngineTests` |
| `tests/run_plugin_offline_regression.py` | Terminal — full offline regression |
| **CabinetNC palette → Connect** | Fusion — screw_hole cut; scaffold types preview-only |

---

## Completed (v1)

- [x] `list_hardware_types()` registry with UI metadata
- [x] `evaluate_hardware_rule()` / `dispatch_hardware_preview()` / `dispatch_hardware_cut_plan()`
- [x] Screw hole delegates to `connect_formal_ui` gates + `screw_hole_from_relationship`
- [x] Scaffold types registered; cut blocked until future implementation

---

## Future (post-M9)

- [x] Tongue/groove **preview** intent (`tongue_groove_from_relationship.py`)
- [x] Tongue/groove **host groove** Fusion cut + metadata writeback
- [x] Tongue CAD cut on target panel (shoulder cuts)
- [x] Hinge / lock / runner **preview** intents (`scaffold_hardware_from_relationship.py`)
- [x] Hinge Fusion cut (host cups) — SEALED 2026-07-09
- [x] Runner Fusion cut (host mount holes) — SEALED 2026-07-10
- [x] Lock Fusion cut (host pocket) — SEALED 2026-07-10
- [x] Connect UI hardware-type selector

See [`connect-post-m9-tongue-groove-checklist.md`](./connect-post-m9-tongue-groove-checklist.md)  
and [`connect-post-m9-scaffold-hardware-checklist.md`](./connect-post-m9-scaffold-hardware-checklist.md)  
and [`connect-post-m9-hardware-type-ui-checklist.md`](./connect-post-m9-hardware-type-ui-checklist.md).
