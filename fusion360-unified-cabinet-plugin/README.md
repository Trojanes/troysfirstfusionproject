# CabinetNC Unified Fusion Plugin

MVP unified Fusion 360 add-in for cabinet generators.

## MVP Scope

- Working module: General Tall Cabinet (`modules/generalTallCabinet/`), including fridge cavity zone.
- Working module: Overhead Cabinet.
- Working module: Kitchen Cabinet.
- Working module: Lounge Generator.
- Reserved module: Automation Tools.
- UI: Figma-inspired top action bar, module sidebar, parameter panel, central workspace, validation panel, and status footer.

Standalone **Fridge Cabinet** was removed; fridge cabinets use General Tall zone type `fridge` (see `docs/connect-gt-fridge-user-parity-checklist.md`).

## Fusion Entry

- Manifest: `UnifiedCabinetPlugin.manifest`
- Main file: `UnifiedCabinetPlugin.py`
- Fusion palette: `palette.html`

Install or link this folder as a Fusion 360 add-in folder, then run `CabinetNC` from the Scripts and Add-ins dialog.

## Fridge cabinets (via General Tall)

```text
palette.html → Load fridge layout / zone type fridge
  -> modules/generalTallCabinet/generator.ts
  -> generalTall.generate
  -> generalTall.createFusionRoughBodies
```

## Manual Fusion Validation

1. Load the `CabinetNC` add-in.
2. Confirm the palette opens on General Tall (no Fridge tab).
3. Click **Load fridge layout**, then Generate / Create Fusion Rough Bodies.
4. Confirm validation/status panels update.
