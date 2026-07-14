# Generator / Connect UI tiers

**Scope:** Design generators + Connect hardware only (Nesting/NC out of scope for this lane).

## Language (zh / en)

- Toggle: top-right **中文 | EN** (`ui/i18n.js`, persisted in `localStorage`)
- Markup: `data-i18n` / `data-i18n-title` / `data-i18n-placeholder` — **no mixed Chinese+English chrome**
- JS UI: use `t()` / `tf()` for preview labels, warnings, status summaries; re-render on `cabinetnc:langchange`
- Brand/product tokens (CabinetNC, Fusion, mm, JSON, SVG, schema field ids) may stay as-is
- Offline check: `tests/run_ui_i18n_offline.py` (includes bilingual-slash markup ban)
- Residual: some Attributes/Nesting long help notes and Python generator validation strings are still English-only until mapped into the dict; they must not be bilingual slash copy

## Industrial IA (product UX)

Each top tab and module must answer in one glance: **what is this page for?**

| Surface | One job |
|---------|---------|
| 柜体设计 | Pick cabinet type → params/zones → generate → Fusion bodies |
| 五金连接 | Inspect board relations → cut hardware (pair / cabinet / ops) |
| 板件属性 | Scan metadata → filter → edit tags |
| 排版 Nesting | Ready check → nesting layout |
| 加工输出 | Placeholder (not productized) |

**Rules**

- Page purpose banner (`.page-purpose`) at the top of each major page / module workspace
- Numbered sections (`.ui-section`) for primary workflow; detail tables/SVG under a later step
- Module nav shows short purpose line (`.module-sub`)
- Unwired commandbar stubs stay **visible but disabled** (`title="未实现"`)
- Orange「测试」stays for debug; do not hide until Test panel exists

GT workspace order (canonical): **1 生成与建体 → 2 分区编辑 → 3 检查结果 → 4 板件预览**

## Module shell contract (柜体设计)

All four formal generators share one product shell:

| Column | Role |
|--------|------|
| Left `.params` | Slow-changing overall settings (`params-head` + cards) |
| Center `.workspace` | Numbered `.ui-section` ①–④ |
| Right `.validation` | `validation-head` → selection props → warnings → (test) JSON |

**Step semantics (do not reorder):**

| Step | Meaning | Tall / Overhead CTA | Kitchen / Living-room CTA |
|------|---------|---------------------|---------------------------|
| ① | Primary action + preset / assembly bar | 生成数据 → Fusion 实体 | 更新预览 → 平面体 / 装配体 |
| ② | Spatial layout editor | Vertical / horizontal zones | Columns+elevation / top view |
| ③ | Checks / summary | Stacking / OH summary | Wheel avoidance / footprint summary |
| ④ | Board preview | SVG / tables | Debug SVG / panel SVG |

**Rules**

- Left rail is always visible (do not hide `.params` for OH/Kitchen).
- Editors that need width stay in step ②; globals stay on the left.
- Preview-maturity modules use a **Preview** pill (`pill.preview`) — not the orange Test badge.
- Commandbar primary button follows the active module (`cmd.generate` vs `cmd.updatePreview`).
- Shared chrome labels use `common.*` / `common.ws.sN.*` where possible.

## Tiers

| Tier | `data-ui-tier` | Meaning |
|------|----------------|---------|
| **Formal** | `formal` | Product path users use every day |
| **Test** | `test` | Debug / duplicate benches / raw JSON — later move to a dedicated Test panel |

Visual markers in `palette.html`: `.pill-test`, `.ui-test-zone` (dashed border).

**Policy:** Do **not** hide or default-collapse test controls — easy to forget. Keep them visible in place with a clear **测试** badge until they move to a dedicated Test panel.

## Formal (stay in main UI)

- Design modules: General Tall, Overhead, Kitchen, Lounge
- Generate / Create bodies / presets / params / zone editors
- Connect pair / cabinet / ops (scan, verify, cut, pipeline)
- Attributes Overview / Panel Manager / Tag Edit (production metadata)
- Nesting tab (product page; not this lane’s focus)
- Board SVG / profile inspectors (power-user product)
- `gtPresetJson` import/export textarea (product aid)

## Test (marked now → move later)

- Raw JSON result boxes (`gtResultBox`, `ohResultBox`, `kitchenResultBox`, `loungeResultBox`, `gtDebugBox`)
- Kitchen Geometry Debug card
- Connect contact-patch overlay buttons (same row, tagged 测试)
- Attributes **Overhead Test Bench** (`aoh*`) + Open OHC Test Bench
- Attributes Last Command debug card
- `#bridgeState` bridge telemetry

## Ambiguous (defaults)

| Item | Recommendation |
|------|----------------|
| Commandbar New/Save/CSV stubs | Keep visible but **disabled** + title「未实现」— do not hide |
| Toolpath tab | Keep placeholder visible |
| Kitchen immaturity | Badge **Preview**, not 测试 |

## Next slice

1. Add top-level **Test** page tab
2. Move `data-ui-tier="test"` blocks there (keep element ids) so formal Design/Connect stays clean without losing test surfaces
3. ~~Apply numbered `ui-section` to OH / Kitchen / Lounge~~ **done** (shell contract above)
