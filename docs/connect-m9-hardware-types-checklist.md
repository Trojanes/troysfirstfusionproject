# M9 Expand Hardware Types Checklist

**Milestone:** M9 — Expand Hardware Types  
**Status:** ✅ **SEALED** (v1 scaffold — 2026-07-05)

---

## Scope (v1)

- Central registry + dispatch: `hardware_rule_engine.py`
- **Implemented:** `screw_hole` (existing relationship pipeline)
- **Scaffold (preview-only):** `tongue_groove`, `hinge_hole`, `lock_cutout`, `drawer_runner_hole`
- All types follow VerifiedRelationship → RuleEngine → Preview → Cut → Metadata shape
- Non-screw types block cut with explicit `previewOnly` errors (no ad-hoc Fusion scripts)

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

- Implement preview/plan/cut for tongue/groove, hinge, lock, runner using same pipeline
- Connect UI hardware-type selector (when more than screw_hole is cut-ready)

See [`CabinetNC_Connect_Relationship_Hardware_Roadmap.md`](../CabinetNC_Connect_Relationship_Hardware_Roadmap.md).
