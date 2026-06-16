# Cabinet Generator — Current Handover (2026-06-16)

This document is the handover snapshot for moving the project to another machine or account. It summarizes what works today, how to install it, and where the important code lives.

## Repository

- **GitHub:** https://github.com/Trojanes/troysfirstfusionproject.git
- **Branch:** `b3` (local `main` tracks `origin/b3`)
- **Latest commit at handover:** includes Kitchen side panel options, V-panel conflict resolution, strip/shelf joinery, and global Z-offset

```bash
git clone https://github.com/Trojanes/troysfirstfusionproject.git
cd troysfirstfusionproject
git checkout b3
```

## What To Install On The New Computer

### Required

1. **Autodesk Fusion 360** with Scripts and Add-Ins enabled.
2. **Node.js** (v20+ recommended; v24 tested). Kitchen, General Tall, Overhead, and Lounge geometry run through Node bridge scripts that import TypeScript directly.
   - If Fusion cannot find Node, set environment variable `NODE_EXE` to the full path of `node.exe`.
3. **Git** (to clone/pull the repo).

### Fusion Add-In Setup

1. Clone or copy the repo to a stable folder, e.g. `C:\CabinetGenerator\troysfirstfusionproject`.
2. In Fusion 360: **Utilities → Scripts and Add-Ins → Add-Ins → green +**.
3. Browse to and select:

   `fusion360-unified-cabinet-plugin`

4. Enable the add-in **CabinetNC** (`UnifiedCabinetPlugin.manifest`).
5. Run **CabinetNC** from the toolbar to open the palette UI.

> The unified plugin is the primary entry point. Older standalone folders (`Fridge Cabinet Generator`, `fusion360-cabinet-generator`, `fusion360-basic-addin`) remain in the repo for reference but are not the main workflow.

## Architecture Overview

```text
palette.html (UI + state)
  -> Python controller (Fusion add-in)
  -> Node bridge script (scripts/*_from_params.js)
  -> TypeScript generator (modules/*/)
  -> Python fusion_adapter.py (Fusion 360 bodies)
```

| Layer | Role |
|-------|------|
| `fusion360-unified-cabinet-plugin/palette.html` | All module UIs, SVG previews, state serialization |
| `fusion360-unified-cabinet-plugin/modules/*/controller.py` | Routes palette actions, runs Node bridges |
| `fusion360-unified-cabinet-plugin/scripts/*.js` | stdin/stdout JSON bridge to TypeScript |
| `modules/*/` | Geometry engines (TypeScript) |
| `fusion360-unified-cabinet-plugin/modules/*/fusion_adapter.py` | Creates/cuts/moves Fusion bodies |
| `fusion360-unified-cabinet-plugin/fusion/geometry_ops.py` | Shared helpers (Z-offset, body naming) |

## Module Status

| Module | UI | Geometry (TS) | Fusion Bodies | Notes |
|--------|----|---------------|---------------|-------|
| **Fridge** | Yes | JS (`fridge_logic.js`) | Yes (flat + assembly) | Mature; uses `PureParams` → `BoardPlan` |
| **General Tall** | Yes | Yes | Yes | V-board YZ profiles, front panel hinge/lock |
| **Overhead** | Yes | Yes (skeleton) | Partial | Bridge wired; see `docs/overhead-cabinet-*` |
| **Kitchen** | Yes | Yes | Yes (flat + assembly) | Most recent work; see section below |
| **Lounge** | Yes | Yes | Yes (flat + assembly) | L-shape sofa + Parallel Lounge UI started |

## Global Z-Offset (+10 m)

All generated models are offset **+10000 mm on Z** so they do not collide with existing workspace geometry.

- Constant: `MODEL_Z_OFFSET_MM = 10000.0` in `fusion/geometry_ops.py`
- Applied per module in each `fusion_adapter.py` (Kitchen, Lounge, General Tall, Fridge wrapper)
- Kitchen applies offset to bodies created in the current run via `_offset_created_kitchen_bodies`

## Kitchen Module — Current Capabilities

### Geometry engine

- `modules/kitchenCabinet/types.ts` — layout state, side panel options, slot types
- `modules/kitchenCabinet/generator.ts` — boards, V-panels, slots, assembly metadata

### UI workflow

1. Configure columns/zones in the Kitchen sidebar.
2. Click **Update Preview** → runs `kitchen.generateGeometry` → SVG panel previews.
3. Resolve any V-panel machining conflicts via dropdown in the warnings panel.
4. **Generate Flat Bodies** or **Assemble Bodies** → Fusion 360 bodies (auto-regenerates geometry if parameters changed since last preview).

### Important parameters

- **Total Depth (Y)** = structural depth + front panel thickness (FPT), same convention as Fridge.
- **Side Panel Options** (outer left/right only, tied to column function zone):
  - Panel type: CPT (carcass) or FPT (door thickness)
  - Front visible: extends side to `Y = -FPT`, removes T1 notch
  - BCH notch: can fill front-bottom cutout when front visible
  - Groove visibility: outer slots → inner half grooves
  - T2/T3/B4 extend to outer face
  - Strengthening strip: optional strip in door zones with shelf joinery
- **Shelf Enabled** per door zone (disables shelf geometry and related slot conflicts when off)
- Column-level side panel options sync across all zones in the same column

### V-panel slot conflict resolution (four modes)

When both left and right half-slots exist on the same V-panel:

| Mode | Left side | Right side |
|------|-----------|------------|
| `left_half_right_none` | half | none |
| `right_half_left_none` | none | half |
| `right_half_left_through` | through | half |
| `left_half_right_through` | half | through |

### Side strengthening strip + shelf joinery

When strip and shelf intersect:

- **Shelf** (`door_shelf`): 85 mm deep notch, `(CPT+1)` mm wide on inner edge
- **Strip** (`side_strengthening_strip`): slot on YZ face, Y=80..100 from rear, `(CPT+1)` × 20 mm, ±0.5 mm on Z

### Fusion adapter

- `modules/kitchen/fusion_adapter.py`
- Revision tag: `frontPanelHingeCupInside_notchVectors_v23`
- Batched slot/notch cuts, flat-then-transform assembly, recursive cleanup of old `KITCHEN_` artifacts

## Lounge Module — Current Capabilities

- `modules/loungeGenerator/generator.ts` — L-shape sofa geometry, Parallel Lounge middle cabinet
- Flat bodies first (dispersed staging layout), then assembly transforms
- L-strip profile uses user-defined L points; lid step cut via outer-ring offset
- UI mirrors L-position for display vs geometry (X flip in top view only)
- Parallel Lounge: middle cabinet doors, hinge cups, lock cutouts, side grooves (UI + geometry started)
- Adapter revision: `loungeCabinetHingeLockGroove_v14`

## Fridge / General Tall / Overhead

See existing handoff docs:

- `docs/fridge-cabinet-current-module-handoff.md`
- `docs/general-tall-cabinet-v1-implementation-checkpoint.md`
- `docs/overhead-cabinet-new-chat-handoff.md`
- `docs/kitchen-cabinet-generator-v0-ui-state-handoff.md` (older UI spec; geometry has since advanced)

## Smoke Tests (without Fusion)

From repo root, with Node installed:

```bash
node fusion360-unified-cabinet-plugin/tests/run_fridge_bridge_tests.js
node fusion360-unified-cabinet-plugin/tests/run_general_tall_bridge_tests.js
node fusion360-unified-cabinet-plugin/tests/run_overhead_bridge_tests.js
```

Kitchen/Lounge: pipe JSON params into bridge scripts:

```bash
node fusion360-unified-cabinet-plugin/scripts/kitchen_from_params.js < test-payload.json
node fusion360-unified-cabinet-plugin/scripts/lounge_from_params.js < test-payload.json
```

## Fusion Validation Checklist

1. Open CabinetNC palette; switch between modules without errors.
2. Kitchen: Update Preview → check SVG panels and warnings panel.
3. Kitchen: Generate Flat Bodies → bodies appear at Z ≈ 10000 mm, prefixed `KITCHEN_`.
4. Kitchen: change a parameter without Update Preview → Generate Flat Bodies should auto-refresh.
5. Lounge: Create Flat Bodies → check L-strip shape and lid step; then Create Assembly Bodies.
6. Fridge / General Tall: generate bodies and confirm Z-offset and cleanup on re-run.

## Known Issues / Follow-Ups

- **Overhead module** geometry port is incomplete relative to General Tall.
- **Lounge placement metadata**: explicit placement boxes in generator + adapter placement-by-id (not fully migrated from id guesses).
- **Python module caching**: controllers use `importlib.reload` on adapters; if Fusion still shows old behavior, restart Fusion or toggle the add-in off/on.
- **README** in unified plugin is outdated (does not list Kitchen/Lounge); this handover doc supersedes it for current scope.

## Key File Index

```
fusion360-unified-cabinet-plugin/
  UnifiedCabinetPlugin.py          # Add-in entry, route table
  palette.html                     # All module UIs
  fusion/geometry_ops.py           # MODEL_Z_OFFSET_MM, shared body ops
  modules/kitchen/
    controller.py                  # Node bridge + Fusion actions
    fusion_adapter.py              # Kitchen body creation
  modules/lounge/
    controller.py
    fusion_adapter.py
  modules/fridge/
    controller.py
    flat_board_geometry.py
  modules/general_tall/
    controller.py
    fusion_adapter.py
  scripts/
    kitchen_from_params.js
    lounge_from_params.js
    general_tall_from_params.js
    boardplan_from_pureparams.js

modules/
  kitchenCabinet/generator.ts      # Kitchen geometry (main)
  kitchenCabinet/types.ts
  loungeGenerator/generator.ts
  generalTallCabinet/generator.ts
  overheadCabinet/generator.ts
```

## Account / Access Notes

- Repo is under GitHub user **Trojanes**.
- For a new account: clone from the URL above, or transfer/fork the repo and update `git remote origin` on the new machine.
- No npm install step — TypeScript is run directly by Node (no `package.json` in repo).

---

*Generated for handover on 2026-06-16. Push target branch: `b3`.*
