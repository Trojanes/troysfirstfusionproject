# M4.5A Connect Demo Pack Checklist

**Milestone:** M4.5A — Demo / Golden Case Pack  
**Status:** ✅ **SEALED** (offline 2026-07-03)

---

## Scope

Three offline demos exercising the Connect pipeline:

| Demo | Purpose |
|------|---------|
| `synthetic_fixture_baseline` | Fixture scan → preview → confirm → cut |
| `simple_overhead_structural_joint` | Overhead snapshots, screw-eligible joint |
| `negative_non_screw_filtering` | Non-screw relationships must not cut |

---

## Runners

| Script | Environment |
|--------|-------------|
| `tests/run_connect_demo_pack_offline.py` | Terminal |
| Debug UI: **Run Demo Pack Offline** | Fusion palette |

---

## Results

```text
milestone: M4.5A
summaries: 3/3 PASS
  synthetic_fixture_baseline — cutOk=true
  simple_overhead_structural_joint — cutOk=true
  negative_non_screw_filtering — cutOk=false (expected)
```

Output: `tests/output/connect_demo_pack_summaries.json`

---

## After M4.5A

Next: **M4.6A Relationship Visual Overlay**
