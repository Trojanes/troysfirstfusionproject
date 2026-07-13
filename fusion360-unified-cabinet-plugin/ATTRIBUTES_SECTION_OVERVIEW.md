# Attributes Section Overview

This document records the current state of the `Attributes` section in the Unified Cabinet Fusion 360 plugin.

The current goal of this section is to become the bridge between generated cabinet geometry and manufacturing metadata. It lets us inspect, search, select, and eventually edit panel metadata attached to Fusion components and bodies.

## Canonical Nesting Attributes (authoritative storage)

Board Type, Color, and Cutting Face share one body-level schema under
`UnifiedCabinet.Panel` metadata:

```json
"classification": {
  "boardType": { "value": "door", "source": "manual", "locked": true },
  "color": { "value": "supermatt_white", "source": "manual", "locked": true },
  "cuttingFace": { "value": "MILLING", "source": "geometry", "locked": false }
}
```

| Field | Meaning | Writers |
|-------|---------|---------|
| `classification.boardType` | Nesting family (`carcass` / `partition` / `door` / custom) | Tag Edit, thickness rules |
| `classification.color` | Colour pool slug | Color Override / Tag Edit |
| `classification.cuttingFace` | Nesting face-up constraint (`MILLING` / `EITHER`) | Milling Analyze / Orient / Propagate / Revert |

Rules:

- Attribute Ready and Nesting Ready read **only** these `classification.*` values (after `migrate_metadata`).
- `derivedTags` / `typedTags` are **deprecated mirrors** kept for older UI; do not treat them as authoritative.
- Face-level `millingSurface` on Fusion faces (and `faceRegistry.faces[]`) remains geometry detail for which physical face is MILLING vs NON_MILLING. Writing those roles also syncs `classification.cuttingFace`.
- `faceRegistry.faceUpState` is a compatibility mirror of cuttingFace `source` / `locked`.
- Generator `identity.boardType` (e.g. `B3`, `front_panel`) is never overwritten by the high-level board family.

## High Level Purpose

The Attributes section is being developed for four related workflows:

1. Manage panel-level manufacturing metadata.
2. Inspect metadata already written into Fusion bodies/components.
3. Test generator output through the isolated Overhead Test Bench.
4. Prepare for later secondary scan / reconciliation after manual Fusion edits.

The current implementation is still a prototype. Some UI controls are preview-only, while metadata scan and selection routes are connected to Fusion.

## UI Structure

The `Attributes` page currently has four sub-tabs:

- `Overview`
- `Panel Manager`
- `Tag Edit`
- `Overhead Test Bench`

The sub-tab switching is handled in `palette.html` with `.attr-page-tab` buttons and the views:

- `#attr-view-overview`
- `#attr-view-panel-manager`
- `#attr-view-tag-edit`
- `#attr-view-overhead-test`

## Overview

The Overview tab is the scan-first starting point for the Attributes workflow.

It contains:

- `Scan All Metadata`
- `Scan Selected Bodies/Faces`
- Two vertical listboxes:
  - Color
  - BoardTypes
- `Select Panels With Chosen Tag`
- Shortcut to `Panel Manager`
- Shortcut to `Overhead Test Bench`
- Current metadata status summary
- Current typed tag summary
- A short OHC metadata testing checklist

The Overview listboxes are populated from the latest metadata scan. Each listbox includes `All`; `Undefined` appears when the scan contains records without that typed tag. Selecting one Color row and one BoardTypes row uses AND logic. The button selects matching Fusion bodies.

## Tag Edit

The Tag Edit tab currently provides a read-only `Tag Scan Selected` tool.

Current status:

- Select a body, face, or edge in Fusion.
- Click `Tag Scan Selected`.
- The UI displays the panel/body metadata and selection-level scan result.
- No metadata write-back.

Current behavior:

- Body selections show panel metadata, color tag, BoardType tag, source board id, material class, and lifecycle data.
- Face selections resolve to the owner body and show owner panel metadata plus face metadata if present.
- Edge selections resolve to the owner body and show owner panel metadata plus unresolved edge semantics.

Current limitation:

- Face front/back/edge semantic classification is only reliable when face metadata exists.
- Edge banding judgement is still unresolved unless future face/edge metadata provides it.

## Panel Manager

### Vehicle Door Colors

The top card defines two vehicle-level door colour slots:

- `Colour 1`
- `Colour 2`

The intended rule is:

- One RV / motorhome shares the same door colour palette across all cabinets.
- Individual panels should reference a door colour slot rather than storing a standalone colour.

Current status:

- UI is present.
- Values are stored in frontend preview state.
- Persistent Fusion/project-level storage is not implemented yet.

### Current Selection

The current selection card shows:

- Component
- Body
- Metadata status
- Thickness
- Panel ID

Current status:

- It can display search/selection results.
- Some selection fields still use preview state unless data comes back from Fusion routes.

### Panel Definition

The panel definition card contains:

- Panel Type:
  - `CARCASS`
  - `DOOR`
  - `PARTITION`
- Door colour slot selector
- Reference front face placeholder
- Cutting side:
  - `FRONT`
  - `BACK`

Current status:

- UI and preview state exist.
- Real write-back/edit of selected Fusion metadata is not implemented yet.
- Reference front face picking is still UI placeholder logic.

### Edge Banding

Edge banding UI currently supports four edge directions:

- Top
- Right
- Bottom
- Left

Each edge can use:

- `0`: None
- `1`: Carcass colour
- `2`: Door colour 1
- `3`: Door colour 2

Current status:

- UI is present.
- The edge diagram updates in frontend state.
- The values are not yet written to body metadata as production edge metadata.

### Tags

The tags UI allows adding/removing simple tag strings.

Current status:

- Preview state works.
- Search by tag can use Fusion data returned by backend routes.
- Editing/saving tags back to Fusion metadata is not implemented yet.

### Search By Tag

The right-side search panel contains:

- Search input
- `Select by Tag`
- `Search Only`
- `Clear`
- Color Tag dropdown
- BoardType Tag dropdown
- `Find Panels With Selected Tags`
- Quick tag buttons
- Search result list

Backend routes:

- `panelAttributes.searchPanels`
- `panelAttributes.selectByTag`
- `panelAttributes.selectPanel`

Important current limitation:

- The existing search service mostly reads component-level `UnifiedCabinet.Panel / metadata`.
- Body-level OHC metadata written during Overhead body creation is primarily visible through Metadata Inspector scan, not necessarily through the older panel search path yet.

### Typed Tag Filters

Typed tag filters are derived from the latest metadata scan.

Current filter columns:

- `Color Tag`
- `BoardType Tag`

Each column has an `All` option.

Default selection:

```text
Color Tag = All
BoardType Tag = All
```

Filtering rule:

- AND logic is always used across columns.
- If a column is `All`, that column does not restrict results.

Examples:

```text
Color Tag = door_colour_1_single_sided
BoardType Tag = All
=> all scanned records with color tag door_colour_1_single_sided
```

```text
Color Tag = All
BoardType Tag = door
=> all scanned door records
```

```text
Color Tag = carcass_colour
BoardType Tag = carcass
=> only carcass records with carcass_colour
```

The button `Find Panels With Selected Tags` filters `panelAttrMock.metadataScanRecords` and displays matching records in the existing search result list. Matching scan records can still be clicked to select the related Fusion body through `panelAttributes.selectMetadataRecord`.

Derived scan fields:

```json
{
  "derivedTags": {
    "colorTag": "carcass_colour",
    "boardTypeTag": "carcass"
  },
  "typedTags": {
    "colorTag": "carcass_colour",
    "boardTypeTag": "carcass"
  }
}
```

Supported initial color tags:

- `carcass_colour`
- `door_colour_1_single_sided`
- `door_colour_1_double_sided`
- `door_colour_2_single_sided`
- `door_colour_2_double_sided`
- `white_stipple`
- custom slugs from Tag Edit door color define (e.g. `alpine_white`)

Empty / missing color is **Undefined**. Legacy `door_colour_*_unknown_surface_mode` values are collapsed to Undefined in the UI.

Color tag derivation:

- Explicit non-unknown `typedTags`/`derivedTags` `colorTag` (including custom slugs) is kept on rescan
- Else `defaultAttributes.doorColorName` → slug (e.g. `Alpine White` → `alpine_white`); **surfaceMode does not change the tag**
- `materialClass == carcass_board` => `carcass_colour` (when no custom tag/name)
- Legacy: `materialClass == door_board` + `doorColorSlot` 1/2 + surface mode => `door_colour_{n}_single_sided` / `_double_sided`
- Missing legacy surface mode with no name/tag => empty (**Undefined**)
- Explicit `white_stipple` metadata derives `white_stipple`

Tag Edit → **Define Door Color on Selection** expands the current Fusion selection (assembly / components / bodies), filters to door panels only, and writes `doorColorName` + `surfaceMode` + stable `colorTag`.

Tag Edit → **Propagate Back Face from Hinge Cups** detects blind circular hinge cups geometrically, treats the open broad face as back (`MILLING`), and propagates that back to coplanar same-orientation panels in the selection.

BoardType tag derivation:

BoardType tag is a high-level panel class, not a detailed generator board kind.

Supported values:

- `carcass`
- `partition`
- `door`

Detailed OHC board kinds such as `bottom_panel`, `top_front_door_fascia`, `internal_vertical_divider`, and `up_flap_door_panel` remain in `metadata.identity.boardType`, but they are not used as BoardType filter rows.

Current derivation:

- `materialClass == door_board` or `role in (door, front_visible)` => `door`
- explicit `role == partition`, `category == partition`, or `panelType == partition` => `partition`
- `materialClass == carcass_board` or `role in (carcass, carcass_rail)` => `carcass`

OHC divider boards (`D*`) are structural carcass boards, not `partition`, unless explicitly marked otherwise.

## Metadata Inspector

The Metadata Inspector card is the main tool for checking what metadata currently exists in Fusion.

It has two buttons:

- `Scan Metadata`
- `Scan Selected Bodies`

### Scan Metadata

`Scan Metadata` scans the whole active Fusion design for existing panel metadata.

It reads:

- Component attributes
- Body attributes

Attribute group/name:

```text
UnifiedCabinet.Panel / metadata
UnifiedCabinet.Panel / panelId
```

Backend route:

```text
panelAttributes.scanMetadata
```

Backend implementation:

```text
panel_attributes/metadata_inspector.py
PanelAttributesController.scan_metadata()
```

Result table columns:

- Entity
- Component / Body
- panelId
- boardType
- role
- material
- Status

Clicking a row shows the full JSON record in the JSON preview panel.

### Scan Selected Bodies

`Scan Selected Bodies` scans only the current Fusion selection.

Supported selections:

- One or more `BRepBody` objects.
- One or more `BRepFace` objects.

If faces are selected, the scanner resolves each face to its owning body and scans that body. Multiple faces from the same body are deduplicated.

Backend route:

```text
panelAttributes.scanSelectedMetadata
```

Backend behavior:

- Reads current Fusion selection.
- Resolves selected faces to bodies.
- Deduplicates bodies.
- Reads `UnifiedCabinet.Panel / metadata` and `panelId`.
- Includes selected bodies even when metadata is missing.

This is useful for manual checking:

1. Select one or more generated OHC bodies or faces in Fusion.
2. Click `Scan Selected Bodies`.
3. Confirm which body has which `panelId`, `boardType`, role, and material class.

### Metadata Validation Status

The inspector classifies each record as:

- `Valid`
- `Warning`
- `Invalid`
- `Missing`

Current validation rules check for:

- `schemaVersion`
- `panelId`
- `boardType` or `panelType`
- `role`
- `materialClass`
- `designGeometry`
- invalid JSON
- duplicate `panelId`

`Missing` is used when a selected body has no panel metadata.

## Overhead Test Bench

The Overhead Test Bench is an isolated copy of the main Overhead generator UI inside the Attributes section.

Purpose:

- Generate OHC boards while testing metadata workflows.
- Avoid interfering with the main Overhead module state.
- Provide a controlled test fixture for body metadata, scan, and later secondary scan.

### Bench Isolation

The main Overhead module and Attributes Overhead Test Bench share logic but use separate bench state.

Main Overhead:

```text
benchId: main
prefix: oh
state: overheadState
presetKey: overhead
controlsRootId: overheadWorkspacePanel
```

Attributes Overhead Test Bench:

```text
benchId: attr
prefix: aoh
state: attrOverheadState
presetKey: attrOverhead
controlsRootId: attrOverheadTestPanel
```

Shared helper functions:

- `ohBench()`
- `ohId()`
- `ohEl()`
- `ohNum()`
- `ohState()`
- `runOverheadBench()`
- `overheadBenchFromClientId()`
- `setOverheadStatusText()`

The backend request includes:

```json
{
  "clientBenchId": "attr"
}
```

This allows `overheadResult` and `overheadFusionResult` to route back to the correct UI copy.

### OHC Test Bench UI

The Attributes copy includes:

- Global OHC settings
- Function zones
- Front elevation preview
- Zone properties
- Validation
- Summary
- Resolved geometry preview
- Per-board SVG preview
- Generated boards table
- Divider features table
- Debug result JSON

Button IDs use the `aoh` prefix:

- `aohGenerateBtn`
- `aohCreateFusionBodiesBtn`
- `aohSavePresetBtn`
- `aohLoadPresetBtn`
- `aohAddZoneBtn`
- `aohDeleteZoneBtn`

### OHC Generated Board Data

The generated board table currently displays raw generator board fields:

- `id`
- `boardType`
- `category`
- `materialThickness`
- `profilePlane`
- `thicknessAxis`
- `x0`, `x1`
- `y0`, `y1`
- `z0`, `z1`

Examples of generated OHC board IDs:

- `BP`
- `T1`
- `T2`
- `T3`
- `T4`
- `D0...Dn`
- `FP0...FPn`

## OHC Body Metadata Written During Fusion Body Creation

OHC now writes default body-level panel metadata when Fusion bodies are created.

This happens during:

```text
overhead.createFusionRoughBodies
```

The Overhead controller calls the shared rough body adapter:

```text
modules/general_tall/fusion_adapter.py
create_rough_bodies_from_board_result(...)
```

The metadata write is limited to:

```python
module_name == "overhead"
```

So the current OHC metadata write should not affect General Tall / Kitchen / Lounge generation.

### Attribute Location

Each generated OHC body receives:

```text
UnifiedCabinet.Panel / panelId
UnifiedCabinet.Panel / metadata
```

### Metadata Shape

Current OHC body metadata shape:

```json
{
  "schemaVersion": 1,
  "identity": {
    "panelId": "ohc.<runLabel>.<boardId>",
    "generator": "overhead",
    "module": "overhead",
    "cabinetType": "overhead",
    "sourceBoardId": "T1",
    "sourceBoardType": "T1",
    "boardType": "top_front_door_fascia",
    "runId": "<runLabel>"
  },
  "defaultAttributes": {
    "role": "front_visible",
    "category": "front",
    "materialClass": "door_board",
    "doorColorSlot": 1,
    "tags": ["overhead", "front", "door-color", "top-fascia"]
  },
  "designGeometry": {
    "x0": 0,
    "x1": 2000,
    "y0": 0,
    "y1": 16,
    "z0": 360,
    "z1": 400,
    "profilePlane": "XZ",
    "thicknessAxis": "Y",
    "materialThickness": 16
  },
  "lifecycle": {
    "state": "generated",
    "reviewRequired": false
  }
}
```

### OHC BoardType Mapping

Current canonical board type mapping:

| Source board | Canonical boardType | Role | Material |
|---|---|---|---|
| `BP` | `bottom_panel` | `carcass` | `carcass_board` |
| `T1` | `top_front_door_fascia` | `front_visible` | `door_board` |
| `T2` | `top_front_inner_rail` | `carcass_rail` | `carcass_board` |
| `T3` | `top_rear_panel` | `carcass` | `carcass_board` |
| `T4` | `top_front_panel` | `carcass` | `carcass_board` |
| First `D*` | `left_side_panel` | `side_panel` | `carcass_board` |
| Middle `D*` | `internal_vertical_divider` | `divider` | `carcass_board` |
| Last `D*` | `right_side_panel` | `side_panel` | `carcass_board` |
| `FP*` with `up_flap` | `up_flap_door_panel` | `door` | `door_board` |
| `FP*` with `fixed_panel` | `fixed_front_panel` | `front_visible` | `door_board` |
| Other `FP*` | `front_panel` | `front_visible` | `door_board` |

Important design decision:

- `T1` is treated as a front visible door-colour fascia, not as a normal carcass rail.
- `T2` is the inner structural rail behind T1.

## Backend Files

### Routes

Routes are registered in:

```text
UnifiedCabinetPlugin.py
```

Current panel attribute routes:

```text
panelAttributes.searchPanels
panelAttributes.selectByTag
panelAttributes.selectPanel
panelAttributes.selectMetadataRecord
panelAttributes.scanMetadata
panelAttributes.scanSelectedMetadata
```

### Controller

```text
panel_attributes/controller.py
```

Responsibilities:

- Search panels.
- Select panels by tag.
- Select a single panel/body.
- Scan all metadata.
- Scan selected bodies/faces.

The controller explicitly reloads `metadata_inspector` to avoid Fusion Python module-cache issues during plugin reload.

### Metadata Inspector

```text
panel_attributes/metadata_inspector.py
```

Responsibilities:

- Read `UnifiedCabinet.Panel / metadata`.
- Parse JSON metadata.
- Extract summary fields.
- Validate required fields.
- Scan all components/bodies.
- Scan selected bodies/faces.
- Deduplicate selected bodies.
- Detect duplicate `panelId`.

### Search Service

```text
panel_attributes/panel_search_service.py
```

Responsibilities:

- Collect defined panel components.
- Search by text/tag.
- Resolve panel records back to Fusion bodies.

Current limitation:

- It primarily uses component-level metadata records.
- Body-level OHC metadata is currently better inspected through the Metadata Inspector.

### Metadata Constants

```text
panel_attributes/panel_metadata_types.py
```

Constants:

```python
PANEL_ATTRIBUTE_GROUP = "UnifiedCabinet.Panel"
PANEL_METADATA_ATTR = "metadata"
PANEL_ID_ATTR = "panelId"
```

## Frontend State

The Attributes UI uses frontend state under `panelAttrMock`.

Important fields:

- `vehicleColors`
- `tags`
- `edgeBanding`
- `panels`
- `fusionPanels`
- `availableTags`
- `metadataScanRecords`
- `useFusionData`

Mock data is used when Fusion is not available.

When Fusion is available, UI actions call `fusionSend(...)`.

## Current User Workflow For Testing OHC Metadata

Recommended test flow:

1. Reload the plugin in Fusion.
2. Open `Attributes`.
3. Switch to `Overhead Test Bench`.
4. Click `Generate`.
5. Click `Create Fusion Bodies`.
6. Select one or more generated OHC bodies or faces in Fusion.
7. Return to `Panel Manager`.
8. Click `Scan Selected Bodies`.
9. Inspect the table and JSON preview.

For all generated OHC metadata:

1. Generate OHC bodies.
2. Open `Panel Manager`.
3. Click `Scan Metadata`.
4. Review Valid / Warning / Invalid / Missing counts.

## Known Limitations

The following are not fully implemented yet:

- Real edit/write-back from Panel Manager form into selected Fusion metadata.
- Persistent vehicle-level door colour storage.
- Real reference front face picker.
- Edge banding write-back into body metadata.
- Secondary scan / reconciliation after manual body edits.
- Split-body parent-child tracking.
- Current geometry comparison against design geometry.
- Face/edge metadata binding from this UI.
- Full integration between body-level OHC metadata and the older search-by-tag component scanner.

## Planned Next Steps

Near-term:

1. Make Search by Tag aware of body-level metadata, not only component-level metadata.
2. Add an OHC metadata preview table before writing bodies.
3. Add write/edit operations for selected body metadata.
4. Add a first Secondary Scan:
   - unchanged
   - moved
   - resized
   - missing/deleted
   - new untracked body

Later:

1. Add split-body reconciliation.
2. Add face/edge metadata inheritance and review.
3. Add metadata version migration tools.

