# Attributes Section — Handover Document (for Nesting Feature Design)

> Purpose of this document: a complete, accurate snapshot of the **Attributes** functionality inside the Fusion 360 **Unified Cabinet Plugin**, written as input for designing the next feature: **nesting** (arranging panels on sheet stock for cutting).
> Everything described here is implemented and working unless explicitly marked *deferred*.

---

## 1. Context

The plugin generates cabinet furniture (overhead cabinets, kitchen, lounge, general tall) as Fusion 360 solid bodies. The **Attributes** section is the bridge between generated geometry and **manufacturing metadata**: every panel body carries structured metadata describing what it is, its faces/edges, machining features, dimensions, and a 2D SVG of its milling surface.

Current test vehicle: the **Overhead Cabinet (OHC) Test Bench**, which generates boards `BP` (bottom), `T1–T4` (top/rails), `D*` (dividers), `FP*` (front/door panels). Face-level metadata initialization currently runs for these OHC skeleton boards only, and runs **after** post-processing cuts (grooves, hinge holes) so classification sees final machined geometry.

Units: all metadata dimensions are **millimetres** (Fusion internal API is cm; conversion handled internally).

---

## 2. Data Model (the core of this handover)

### 2.1 Body-level metadata

Stored as Fusion attributes on each `BRepBody`:

| Attribute group | Name | Content |
|---|---|---|
| `UnifiedCabinet.Panel` | `panelId` | e.g. `ohc.<runLabel>.<boardId>` |
| `UnifiedCabinet.Panel` | `metadata` | JSON payload (below) |

```jsonc
{
  "schemaVersion": 1,
  "identity": {
    "panelId": "ohc.run1.FP2",
    "generator": "overhead", "module": "overhead", "cabinetType": "overhead",
    "sourceBoardId": "FP2", "sourceBoardType": "up_flap",
    "boardType": "up_flap_door_panel",   // semantic board type
    "runId": "run1"
  },
  "defaultAttributes": {
    "role": "door",                       // door / carcass / front_visible / divider ...
    "category": "front",
    "materialClass": "door_board",        // door_board / carcass_board / ...
    "doorColorSlot": 1,                   // optional, for door boards
    "tags": ["overhead", "front", "door", "up-flap"]
  },
  "designGeometry": { "x0": ..., "x1": ..., "y0": ..., "y1": ..., "z0": ..., "z1": ...,
                      "profilePlane": "...", "thicknessAxis": "...", "materialThickness": 15 },
  "lifecycle": { "state": "generated", "reviewRequired": false },

  // ---- added by the face/geometry framework ----
  "faceRegistry":      { ... },   // see 2.3
  "dimensions":        { "lengthMm": 2000, "widthMm": 400, "thicknessMm": 15 },
  "millingSurfaceSvg": { ... },   // see 2.5
  "features":          [ ... ],   // see 2.4 — HALF/FULL machining features
  "featureSummary":    { "total": 4, "half": 4, "full": 0, "byKind": { "groove": 4 } }
}
```

Derived tags (computed at scan time, not stored): `colorTag` (e.g. `carcass_colour`, `door_colour_1_single_sided`, `door_colour_1_unknown_surface_mode`) and `boardTypeTag` (`carcass` / `partition` / `door`). A tag containing `unknown` is treated as **undefined** by the UI.

### 2.2 Face-level metadata

Stored per `BRepFace` under attribute group `UC_FACE_METADATA`, name `payload` (JSON):

```jsonc
{
  "schemaVersion": 1,
  "panelId": "ohc.run1.FP2",
  "faceId": "FACE-1A2B3C4D",          // stable id, generated
  "faceClass": "SURFACE" | "EDGE",
  "faceRole": "door_outer" | "carcass_bottom_inner" | "edge_bandable" | "edge_non_bandable" | ...,
  "millingSurface": "MILLING" | "NON_MILLING" | "EITHER",   // SURFACE faces only
  "edgeId": "EDGE-01",                 // EDGE faces only
  "edgeGroupId": "EG-01",              // EDGE faces on a bandable side
  "classificationStatus": "classified" | "unclassified",
  "finish": { "finishId": "raw-core", "finishName": "Raw Core" },
  "nestingOrientation": "UP" | "DOWN" | "EITHER" | "NOT_APPLICABLE" | "UNASSIGNED",
  "machiningPermission": "PRIMARY" | "SECONDARY" | "ALLOWED" | "NOT_ALLOWED",
  "edgeBanding": { "required": false, "bandingCode": 0, "finishId": "raw-core", "finishName": "Raw Core" },  // EDGE only
  "geometrySignature": {               // rigid-move invariant, see 3.5
    "surfaceType": "PLANE", "area": 800000.0, "perimeter": 4800.0,
    "centroidLocal": [x, y, z], "normalLocal": [x, y, z], "edgeCount": 4
  }
}
```

### 2.3 `faceRegistry` (on the body)

```jsonc
{
  "surfaceMode": "SINGLE_SIDED" | "DOUBLE_SIDED" | "UNASSIGNED",  // doors single-sided, carcass double
  "faceMetadataVersion": 1,
  "referenceFrontFaceId": "FACE-....",
  "faces":   [ { "faceId", "faceRole", "faceClass", "millingSurface"?, "entityToken", "edgeId"?, "edgeGroupId"? } ],
  "faceIds": [ ... ],
  "edges":   [ {           // TRUE perimeter edges only (span full thickness)
      "edgeId": "EDGE-01", "edgeRole": "edge_01",
      "faceRole": "edge_bandable" | "edge_non_bandable",
      "bandable": true | false,
      "edgeGroupId": "EG-01" | null,        // null for non-bandable
      "classificationStatus": "classified",
      "faceId", "entityToken",
      "areaMm2", "directionHint": "+X" | "-Y" | ...,   // outward normal bucket, body-local
      "planeOffsetMm", "normalLocal", "centroidLocal"
  } ],
  "edgeGroups": [ {         // one logical board edge = one banding pass = ONE colour
      "edgeGroupId": "EG-01", "side": "+X", "directionHint": "+X",
      "bandable": true,
      "bandingRequired": false,
      "bandingColor": "raw-core", "bandingFinishName": "Raw Core",
      "edgeIds": ["EDGE-01","EDGE-03"], "faceIds": [...], "entityTokens": [...],
      "memberCount": 2, "areaMm2": 12345.0
  } ],
  "featureFaces": [ {       // internal feature faces, kept separate for future use
      "featureFaceId": "FF-01", "faceRole": "feature_unclassified",
      "classificationStatus": "unclassified",
      "entityToken", "areaMm2", "directionHint", "planeOffsetMm", "normalLocal", "centroidLocal"
  } ]
}
```

### 2.4 `features[]` — machining features (for nesting/CNC)

Detected from final machined geometry, classified **HALF (blind)** vs **FULL (through)**:

```jsonc
{
  "featureId": "FEAT-01",
  "cutType": "HALF" | "FULL",
  "kind": "groove" | "hole" | "pocket",
  "depthMm": 7.5,                  // HALF: blind depth; FULL: board thickness
  "isCircle": true|false, "radiusMm": 17.5,   // hinge cups / drill holes
  "center2d": [x, y],              // face-local 2D mm (circles)
  "pointsLocal": [[x, y], ...],    // face-local 2D mm polygon of the feature opening
                                   // (grooves/pockets; same frame as outline pointsLocal)
  "openSurfaceToken": "..."        // which broad face the cut opens onto
}
```

Detection rules:
- **HALF**: found via *floor faces* — planar faces parallel to the broad faces whose offset lies strictly **between** the two surfaces. This also catches grooves that open to a panel edge (they never form an inner loop).
- **FULL**: inner loops on a broad face whose walls reach the opposite broad face.
- Through features appearing on both faces are deduplicated by 2D centroid (2 mm tolerance).

### 2.5 `millingSurfaceSvg` — 2D projection of the milling surface

```jsonc
{
  "svg": "<svg ...>",              // self-contained; width/height=100%, unitless viewBox, non-scaling strokes
  "viewBox": "0 0 2000 400",
  "widthMm": 2000, "heightMm": 400,
  "millingFaceToken": "...",
  "outline": [ {                   // one record per outer-loop BRep edge (maps SVG segment -> EDGE face)
      "segIndex": 0, "edgeToken": "...",
      "signature": { "start": [x,y], "end": [x,y], "mid": [x,y], "lengthMm": 812.5, "isCircle": false },
      "pointsLocal": [[x, y], ...],  // CANONICAL face-local mm (pre-flip) — use for nesting geometry
      "points2d": [...]              // display-space only (shifted to origin, Y flipped for SVG); do NOT use
  } ],
  "features": [ { "featureId", "cutType", "kind", "depthMm", "isCircle", "radiusMm" } ]
}
```

- The **outline** uses the broad face with the larger outer-loop area (the face NOT notched by edge-open grooves), so the silhouette is the true panel footprint — exactly what nesting needs.
- Each outer edge is its own `<path>` with `data-edge-token`, so SVG segments can be bound back to EDGE faces later.
- Features drawn inside: HALF = blue dashed, FULL = red solid; circles as `<circle>` with true radius.
- Y axis is flipped for display (SVG Y-down).

### 2.6 Canonical coordinate frame (important for nesting)

All geometry written to panel metadata shares **one** 2D coordinate frame: the
**body-attached frame** (see 3.6) projected onto the board plane (thickness axis
dropped). Concretely, these are all in the same face-local mm space:

- `millingSurfaceSvg.outline[].pointsLocal`  (part contour)
- `features[].pointsLocal` and `features[].center2d`  (machining features)
- `faceRegistry.edges[].directionHint / normalLocal / centroidLocal`  (edge sides, e.g. `+X`)

Because the frame is derived from the body's own geometry, all of it is
**rigid-move invariant** (panels can be moved/rotated in Fusion without changing
these coordinates). The only display-space data is `outline[].points2d` and the
rendered `svg` string (shifted to origin + Y-flipped) — never use those for
geometry work.

---

## 3. Classification Algorithms (rules of record)

### 3.1 SURFACE selection — always exactly 2
1. Largest-area face is surface A (always a broad face).
2. Surface B = largest face whose normal opposes A (dot ≤ −0.7).
3. Fallback: two largest by area (guarantees exactly 2 SURFACEs even if normals unavailable).
4. Everything else initially goes to the "non-surface" pool.

### 3.2 Milling surface (`millingSurface` attribute)
Manufacturing rule: of a body's two broad faces, the side a **half-slot / blind feature opens onto** is the machined face.
- Wall faces perpendicular to the board plane that are adjacent (share a BRep edge) to **only one** broad face mark that side as `MILLING`; the other side becomes `NON_MILLING`.
- Faces adjacent to **both** broad faces span full thickness → genuine perimeter edges, ignored for this test.
- No half-slot on either side → both `EITHER`. Both sides cut → both `MILLING`.

### 3.3 True edges vs feature faces
A **true perimeter edge** spans the full panel thickness → it shares boundary edges with the **outer loop of BOTH broad surfaces**. Everything else (groove walls/floors, hole walls, chamfers, blind pocket walls) goes to `featureFaces[]` (kept but unclassified, reserved for future use). Fallback: if loop data is unavailable, all faces stay as edges.

### 3.4 Bandable vs non-bandable edges (`faceRole`)
Manufacturing rule: the edge bander can only run edges on the panel's **overall bounding rectangle**.
- The 2D frame extremes are recovered from edge centroids (min/max per in-plane axis).
- An edge whose dominant-normal-axis coordinate sits at the frame extreme (±1 mm) → `edge_bandable`; set back (notch/cut-out interior) → `edge_non_bandable`.
- A frame edge split into several faces by a notch keeps all its pieces bandable.
- Caveat: assumes rectangular panels (axis-aligned frame in body space). Sloped-edge panels would need a convex-hull variant (not implemented).

### 3.5 Edge groups — one board edge = one banding colour
Manufacturing rule (confirmed with user): a straight board edge is banded in a **single continuous pass**, so every coplanar/collinear face on that side shares **one strip = one colour**. Physically impossible to band segments of the same edge in different colours.
- Bandable edges are grouped by `directionHint` (frame side) into `edgeGroups[]`, each with a single `bandingColor` (default `raw-core`).
- `validate_edge_group_banding(groups, faceId→colour)` returns violations if any group carries mixed colours.
- Non-bandable edges are excluded from groups.

### 3.6 Geometry signatures — rigid-move invariant (re-binding after manual moves)
`centroidLocal` / `normalLocal` are expressed in a **body-attached frame** derived from the geometry itself:
- Origin = area-weighted centroid of all faces; Z = dominant face-normal cluster (thickness axis); X = next non-parallel cluster; axis signs fixed by area-weighted third moment (equivariant under rigid motion; symmetric boards keep the cluster-representative direction).
- Consequence: signatures survive **any** rigid move — occurrence move, in-component translation, rotation. Face resolution order: `entityToken` first, geometry signature fallback (`resolve_face`). Symmetric boards may bind to the geometrically equivalent twin face (inherent, acceptable).
- Matching threshold: score ≥ 9 of 12 (surfaceType 2 + area 2 + perimeter 1 + centroid 3 + normal 3 + edgeCount 1).

### 3.7 Fusion API pitfalls solved (do not regress)
- `SurfaceEvaluator.getArea()` returns `(bool, area)` — a generic "first numeric" extractor handles all shapes.
- `getNormalAtParameter(0.5, 0.5)` is WRONG (takes a `Point2D` in the *parametric range*, not normalized 0–1). Use `face.pointOnFace` + `evaluator.getNormalAtPoint(point)`.
- Module reloads: `fusion_adapter` reloads the whole metadata dependency chain in dependency order (`face_models` → … → `panel_geometry` → `panel_face_initializer`) to avoid stale-module ImportErrors inside Fusion.

---

## 4. UI Features (palette.html — Attributes tabs)

### Overview tab
- **Scan All Metadata / Scan Selected Bodies/Faces** — walks the design, returns records with derived tags, counts (Valid/Warning/Invalid/Missing).
- **Select Panels With Chosen Tag** — Color × BoardType listboxes (AND), selects matching bodies in the viewport.
- **Assembly Zone / 装配区** — creates a **zero-thickness surface patch** on XY at z=0 (default 10 m × 10 m, adjustable), deep-blue semi-transparent (opacity 0.5), labelled "Assembly Zone" as sketch text on both opposite edges. Marked `UnifiedCabinet/systemRole=assemblyZone` and **excluded from every scan** (also naturally excluded because scans only walk `isSolid` bodies). Idempotent: re-setting deletes and recreates.

### Panel Manager tab
- Vehicle door colour slots, metadata scan table, typed-tag filters, search, per-record select, JSON inspector.

### Tag Edit tab (main working area)
- **Tag Scan Selected**: scan selected bodies/faces/edges → per-body card showing:
  - body metadata (editable rows: Board Type, Color, Material Class, Role, Lifecycle…),
  - selection detail for faces (Face Class, Face Role, **Milling Surface**, Face Color, Edge Banding…),
  - **Bandable Edges** (logical edge groups, open by default), **All Edges** (collapsed), **Feature Faces** (collapsed), **Face Registry** (collapsed),
  - **Dimensions**, **Internal Features** (half/full counts + per-feature detail, collapsed), **Milling Surface SVG** (square, aspect-correct preview).
- **Pending Changes**: edits are stored as local drafts → **Apply Pending to Fusion** writes body metadata (and face metadata when a face was scanned). Robust body re-resolution: entityToken → design-tree search → panelId+bodyName → selection fallback.
- **Select By Missing Attribute**: one-click select all bodies with undefined Color (optionally filtered by Board Type) or undefined Board Type (optionally filtered by Color). Options come from the full metadata scan; "undefined" = empty **or containing `unknown`**.
- **Global Edit**: apply one attribute value (Board Type / Color) to every scanned body as pending drafts.

### Overhead Test Bench tab
- Generate → Create Fusion Bodies → per-board **Face Metadata** summary (surface/edge/feature counts) from `faceInitSummary`.

---

## 5. Backend Routes (palette → Python)

| Route | Function |
|---|---|
| `panelAttributes.scanMetadata` | full-design scan |
| `panelAttributes.scanSelectedMetadata` | scan selection |
| `panelAttributes.tagScanSelected` | Tag Edit scan |
| `panelAttributes.applyTagScanDrafts` | write pending drafts to Fusion |
| `panelAttributes.searchPanels` / `selectByTag` / `selectPanel` | search & select |
| `panelAttributes.selectMetadataRecord(s)` | select bodies from scan records |
| `panelAttributes.setAssemblyZone` | create/update assembly zone plane |
| `overhead.*` | OHC test bench generate / create bodies |

Key modules:

| Path | Responsibility |
|---|---|
| `metadata/panel_face_initializer.py` | surface/edge classification, milling roles, edge split & bandability, edge groups, face init orchestration |
| `metadata/panel_geometry.py` | dimensions, milling-surface SVG, HALF/FULL feature extraction |
| `metadata/face_geometry_signature.py` | body-frame signatures, matching |
| `metadata/face_models.py` | schemas, constants, registry builder |
| `metadata/face_metadata_service.py` | face metadata read/write/validate service |
| `panel_attributes/controller.py` | all routes, assembly zone |
| `panel_attributes/metadata_inspector.py` | scans, faceSummary, tag scan |
| `panel_attributes/tag_metadata_editor.py` | draft application/write-back |
| `panel_attributes/panel_body_resolver.py` | body lookup (token/name/panelId) |
| `modules/general_tall/fusion_adapter.py` | OHC body creation, post-process cuts, face-init hook (runs AFTER cuts) |
| `tests/` | 32+ unit tests, all passing (pure logic paths; Fusion API mocked) |

---

## 6. What Nesting Can Rely On (design inputs)

Per panel body, nesting has:
1. **`dimensions`** — true L × W × T from body-local geometry (rotation-proof).
2. **`millingSurfaceSvg.outline[].pointsLocal`** — exact 2D footprint polygon (canonical face-local mm), per-edge segments with entity tokens; use as the nesting part contour. (`points2d` is display-only.)
3. **`features[]`** — machining features with HALF/FULL classification:
   - FULL cuts matter for part outline/holes on any machine pass;
   - HALF cuts constrain **which face must be up** on the CNC (see next).
4. **`millingSurface`** per SURFACE — `MILLING` side must face the tool; `EITHER` boards are free to flip (nesting freedom); doors are SINGLE_SIDED with `nestingOrientation` UP/DOWN semantics already present in face metadata.
5. **`edgeGroups[]`** — banding demand per logical edge (one colour per edge); can drive edge-banding routing and cost.
6. **`defaultAttributes.materialClass` + `colorTag`** — sheet/material pooling key for grouping parts onto the same stock (e.g. all `door_board` in `door_colour_1` on one sheet type).
7. **Selection tooling** — bodies with missing colour/board type can be found and fixed before nesting (Select By Missing Attribute).

### Suggested nesting grouping key
`(materialClass, colorTag, thicknessMm)` → one nesting job per key; part orientation constrained by `millingSurface`/`nestingOrientation`; part contour from `millingSurfaceSvg` outline; hole/groove data from `features[]`.

### Runtime decision (agreed)
The nesting engine (geometry, NFP, GA) should run **palette-side (JS in the Fusion
palette webview, optionally in a Web Worker)** — same runtime class as SVGnest.
The plugin's Python side only collects/serves metadata (routes) and applies
results back to Fusion. The plugin currently has **no TS build step**
(`palette.html` is a single self-contained file); introducing TypeScript requires
adding a bundler first, otherwise implement as plain JS modules.

---

## 7. Known Limitations / Deferred Items

1. **Scope**: face/geometry init runs only for OHC skeleton boards (BP, T1–T4, D*, FP*); other generators (kitchen, lounge…) write body metadata but no faceRegistry yet.
2. **Edge semantic roles** (`edge_top/left/right/...`): helper functions exist (`edge_role_from_geometry`) but are not applied; edges carry `edge_bandable`/`edge_non_bandable` only.
3. **Feature faces** are enumerated but unclassified (`feature_unclassified`); linking `featureFaces[]` ↔ `features[]` (which walls belong to which groove) is not done.
4. **Banding colour editing UI** (per edge group) not built; data model + validation ready.
5. **Bandability** assumes rectangular outlines; sloped edges need a convex-hull rule.
6. **Kind detection** for features is coarse (arc → hole, 4 edges → groove, else pocket).
7. Existing bodies keep old metadata until regenerated — always **re-create Fusion bodies** after algorithm changes.
8. Three legacy test failures in `test_face_metadata_framework.py` predate this work (validation defaults + a resolver test with fake signatures); unrelated to current logic.
9. **`grainDirection` is not in the metadata yet.** Boards with wood grain / brushed texture must restrict allowed rotations to 0/180 during nesting; add a `grainDirection` field (e.g. `NONE | LENGTH | WIDTH`) to `defaultAttributes` and derive `allowedRotations` from it before the GA solver lands.
10. **Polygon offsetting (kerf/clearance)** is not provided by the Attributes layer; the nesting engine must offset part contours by tool diameter + clearance itself (SVGnest uses ClipperLib for this).
11. Entity tokens (`openSurfaceToken`, `millingFaceToken`, outline `edgeToken`) become stale after bodies are regenerated; cross-session re-binding must go through `panelId` + geometry signatures.

---

## 8. Manufacturing Rules Captured (confirmed with the owner)

1. A panel has **exactly 2 SURFACE faces** (broad faces).
2. The face a half-slot opens onto = **MILLING** surface; opposite = NON_MILLING; none cut = EITHER.
3. Edge bander can only band edges on the **overall bounding rectangle frame**; interior notch edges cannot be banded.
4. **One straight board edge = one continuous banding pass = exactly one banding colour**, regardless of how many BRep faces the edge is split into.
5. Internal features split into **HALF (blind)** vs **FULL (through)** — the distinction nesting/CNC needs.
6. Groove/hole faces are **not edges**; they are machining features and are stored separately.
