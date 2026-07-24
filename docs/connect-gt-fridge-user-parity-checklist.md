# GT replaces Fridge — user-effect parity

**Goal:** Fridge cabinets are built only via General Tall. Standalone Fridge module is **deleted**.

**Bar:** Same *user-visible* outcome, not Fridge board-ID / `flat_xy` / PureParams clone.

## Acceptance (must)

- [x] Zone `fridge` + appliance W/D/H; cavity has no front panel
- [x] `exteriorSide` → SidePanel + CW = W+45/61
- [x] V5 opposite exterior
- [x] Avoidance gap &lt; 105 → raised + `H*_fridge`; else normal
- [x] Drawer / flap fronts + hinge/lock via GT front hardware
- [x] Connect decls: SidePanel↔V, V5 mate
- [x] Offline user-effect smoke: `tests/run_gt_fridge_user_parity_offline.py`
- [x] Palette: Fridge module removed; GT “Load fridge layout” one-shot
- [x] Fusion hand-check: load fridge layout → Generate → Create rough bodies
- [x] Standalone Fridge code deleted (recover via git)

## Explicit YAGNI (do not port)

- Fridge `flat_xy` / `outerVector` / `HSet_P*` naming
- Fridge-only PureParams boardPlan JSON shape
- Cabinet-level duplicate `fridgeWidth` fields
- Standalone Fridge `generator_declared`
- Multi-fridge multi-V5

## Recovery (standalone Fridge code)

Last commit that still contained the standalone Fridge tree:

```text
4bfe809  Hide Fridge UI and route fridge cabinets through General Tall.
```

Restore the deleted tree (without switching branch):

```powershell
cd d:\project\troysfirstfusionproject-main
git checkout 4bfe809 -- "Fridge Cabinet Generator" `
  fusion360-unified-cabinet-plugin/modules/fridge `
  fusion360-unified-cabinet-plugin/core/fridge_logic.js `
  fusion360-unified-cabinet-plugin/scripts/boardplan_from_pureparams.js `
  fusion360-unified-cabinet-plugin/tests/run_fridge_bridge_tests.js `
  fusion360-unified-cabinet-plugin/tests/fixtures/generator_params/fridge_base.json `
  docs/fridge-cabinet-ui-rules-current.md `
  docs/fridge-cabinet-current-module-handoff.md
```

Or browse history: `git log -- "Fridge Cabinet Generator"` / `git show 4bfe809:Fridge Cabinet Generator/fridge_logic.js`
