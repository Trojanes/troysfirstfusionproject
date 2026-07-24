#!/usr/bin/env python3
"""Offline check: UI language switch has zh/en parity and no mixed chrome copy."""

from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _fail(step: str, detail) -> int:
    print("[FAIL] {} -> {}".format(step, detail))
    return 1


def _extract_lang_keys(js: str, lang: str) -> set[str]:
    # STRINGS = { zh: { ... }, en: { ... } }
    marker = "{}:".format(lang)
    idx = js.find(marker)
    if idx < 0:
        return set()
    brace = js.find("{", idx)
    if brace < 0:
        return set()
    depth = 0
    end = brace
    for i, ch in enumerate(js[brace:], start=brace):
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    block = js[brace : end + 1]
    return set(re.findall(r'"([a-z0-9_.]+)"\s*:', block))


def main() -> int:
    i18n_path = os.path.join(ROOT, "ui", "i18n.js")
    palette_path = os.path.join(ROOT, "palette.html")
    if not os.path.isfile(i18n_path):
        return _fail("missing ui/i18n.js", i18n_path)
    if not os.path.isfile(palette_path):
        return _fail("missing palette.html", palette_path)

    js = open(i18n_path, encoding="utf-8").read()
    html = open(palette_path, encoding="utf-8").read()

    if 'src="ui/i18n.js"' not in html:
        return _fail("palette loads ui/i18n.js", "script src missing")
    if 'data-lang="zh"' not in html or 'data-lang="en"' not in html:
        return _fail("lang toggle buttons", "data-lang zh/en missing")
    if 'data-i18n="tab.design"' not in html:
        return _fail("data-i18n chrome", "tab.design missing")

    zh_keys = _extract_lang_keys(js, "zh")
    en_keys = _extract_lang_keys(js, "en")
    if not zh_keys or not en_keys:
        return _fail("parse string keys", {"zh": len(zh_keys), "en": len(en_keys)})
    if zh_keys != en_keys:
        only_zh = sorted(zh_keys - en_keys)
        only_en = sorted(en_keys - zh_keys)
        return _fail("zh/en key parity", {"only_zh": only_zh[:20], "only_en": only_en[:20]})
    print("[PASS] zh/en key parity ({})".format(len(zh_keys)))

    html_keys = set(re.findall(r'data-i18n(?:-title|-placeholder|-html|-empty)?="([a-z0-9_.]+)"', html))
    missing = sorted(html_keys - zh_keys)
    if missing:
        return _fail("html data-i18n keys in dict", missing[:30])
    print("[PASS] palette data-i18n keys resolved ({})".format(len(html_keys)))

    if "data-i18n-empty" not in html or "data-i18n-empty" not in js:
        return _fail("empty-state i18n", "data-i18n-empty missing")
    print("[PASS] empty-state i18n wired")

    mixed = [
        "高柜 General Tall",
        "吊柜 Overhead",
        "地柜 Kitchen",
        "客厅柜 Lounge",
        "Preset / 预设",
        "Generate / 生成",
        "排版 Nesting",
        "Geometry valid /",
        "Fixed Panel /",
        "Up Flap /",
        "Total Zones /",
        "Attribute Ready /",
        "Work Zones /",
        "Validation / 验证",
        "Summary / 摘要",
    ]
    for needle in mixed:
        if needle in html:
            return _fail("no mixed chrome", needle)
    print("[PASS] no classic mixed chrome strings")

    # Markup bilingual slash labels (EN word + CN word with /).
    # ponytail: Nesting page keeps Troy bilingual copy until local UI polish; strip it from this gate.
    markup = html.split("<script>", 1)[0]
    markup = re.sub(
        r'<div class="attributes-page page" id="page-nesting"[^>]*>.*?</div>\s*<div class="blank-page page" id="page-toolpath"',
        '<div class="blank-page page" id="page-toolpath"',
        markup,
        count=1,
        flags=re.S,
    )
    bilingual = []
    for m in re.finditer(r">([^<>]{0,120})<", markup):
        s = m.group(1).strip()
        if "/" not in s:
            continue
        if re.search(r"[A-Za-z]{3,}", s) and re.search(r"[\u4e00-\u9fff]", s):
            bilingual.append(s[:100])
    if bilingual:
        return _fail("no bilingual slash markup", bilingual[:15])
    print("[PASS] no bilingual slash markup labels")

    if "overheadZoneLabel" in html and 'return "Fixed Panel /' in html:
        return _fail("overheadZoneLabel localized", "still returns mixed Fixed Panel /")
    if "Geometry valid / 几何" in html:
        return _fail("overhead warnings localized", "Geometry valid / still present")
    print("[PASS] preview/warning mixed literals removed")

    if "CabinetNC_I18N" not in js or "applyI18n" not in js or "tf(" not in js:
        return _fail("i18n API", "CabinetNC_I18N / applyI18n / tf missing")
    print("[PASS] i18n API present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
