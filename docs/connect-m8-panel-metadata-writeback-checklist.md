# M8 Panel Metadata Writeback Checklist

**Milestone:** M8 — Panel Metadata Writeback Integration  
**Status:** ✅ **SEALED** (2026-07-05)

---

## Scope (v1)

- After successful screw-hole cut, append hardware feature to host body `metadata.features[]`
- Dedupe by `featureId` / `sourceRelationshipId + operationType`
- Cut feature metadata unchanged (M3); body writeback is additive
- Metadata scan can find written hardware features

---

## Runners

> **Note (2026-07-05):** One-click smoke scripts removed.

| Script / surface | Environment |
|------------------|-------------|
| `tests/test_panel_metadata_writeback.py` | Terminal — M8 unit tests |
| `tests/run_plugin_offline_regression.py` | Terminal — full offline regression |
| **CabinetNC palette → Connect cut flow** | Fusion — verify `metadataWritten` + body `features[]` after cut |

---

## Completed

- [x] `panel_metadata_writeback.py` — read/append/write body metadata
- [x] `build_panel_feature_record` — screw-hole → nesting-compatible feature row
- [x] `writeback_screw_hole_feature` wired in `HardwareController.create_screw_holes_from_relationship`
- [x] Duplicate write protection (unless `allow_duplicate=True`)

---

## After M8

See [`CabinetNC_Connect_Relationship_Hardware_Roadmap.md`](../CabinetNC_Connect_Relationship_Hardware_Roadmap.md) — M9 Expand Hardware Types.
