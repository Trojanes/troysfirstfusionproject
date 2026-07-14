# Nesting engine boundary

CabinetNC calls `nesting.engine.create_layout()` and consumes one stable layout
shape. Fusion-specific code must not import Deepnest classes or data structures.

Current adapters:

- `deepnest.py`: JSON job/result adapter around embedded Deepnest-next v1.5.6.
- `sheet_pack.py`: built-in polygon Bottom-Left fallback.

The Deepnest adapter sends normalized polygon JSON over one-request localhost
TCP connections to a process-local pool of two persistent, pinned Electron
workers. Electron publishes its ephemeral `127.0.0.1` port through a private
per-worker readiness file. Each worker handles one job at a time, preserves
Deepnest's geometry cache for matching geometry signatures, and is terminated,
restarted, and retried once after a bridge failure. The pool allows material
jobs to run concurrently without paying Electron startup cost for every
material. To replace Deepnest later, add an adapter that returns the same keys
(`placements`, `groups`, `sheets`, `unplaced`, dimensions, and engine metadata),
then change the selection in `nesting/engine.py`.

When `allowPartsInPart` is enabled, the adapter sends validated outline holes as
Deepnest polygon-tree children. Results report `holeOutlineCount`,
`partsInPartApplied`, and (when Deepnest exposes placement `inHole` flags)
`nestedInHoleCount`; packed placements retain transformed `packedHoles`.

Deepnest failure is non-destructive: the facade records the failure and uses
`sheet_pack_poly_v1`. The result exposes `engineFallback` and
`engineFallbackReason` so the UI and diagnostics do not silently claim that
Deepnest ran.
