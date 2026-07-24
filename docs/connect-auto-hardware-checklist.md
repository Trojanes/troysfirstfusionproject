# Auto Hardware Type Selection Checklist

**Feature:** Connect optional auto hardware type from relationship  
**Status:** offline ready 2026-07-13

---

## Product rules

- [x] Default **off** (UI type applies to single + batch)
- [x] When on: per-relationship type
  1. `allowedHardware` first implemented type
  2. `gap_parallel` → `hinge_hole`
  3. contact (`edge_to_surface` / `surface_to_surface`) → `screw_hole`
  4. else → `screw_hole`
- [x] Auto switch drops UI numeric params (planners use type defaults)
- [x] Batch reports `hardwareTypeCounts`

---

## Delivered

| Layer | Item |
|-------|------|
| Pure | `suggest_hardware_from_relationship.py` |
| Batch/single | resolve before create/preview |
| UI | 「自动选型」+ hint |
| Offline | `tests/test_suggest_hardware.py` |
