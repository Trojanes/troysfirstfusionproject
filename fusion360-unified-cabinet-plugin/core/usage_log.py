"""Append-only plugin usage log for offline debugging.

Writes:
  fusion360-unified-cabinet-plugin/logs/plugin_usage.jsonl   (history)
  fusion360-unified-cabinet-plugin/logs/plugin_usage_latest.json (last event)

Agents should read ``plugin_usage_latest.json`` first, then the jsonl tail.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone

_LOG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "logs"))
_JSONL_PATH = os.path.join(_LOG_DIR, "plugin_usage.jsonl")
_LATEST_PATH = os.path.join(_LOG_DIR, "plugin_usage_latest.json")
_MAX_JSONL_BYTES = 4 * 1024 * 1024
_MAX_LIST_ITEMS = 40
_MAX_STRING = 500


def log_paths():
    return {
        "dir": _LOG_DIR,
        "jsonl": _JSONL_PATH,
        "latest": _LATEST_PATH,
    }


def _json_safe(value, depth=0):
    if depth > 8:
        return "<max-depth>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > _MAX_STRING:
            return value[:_MAX_STRING] + "…"
        return value
    if isinstance(value, (list, tuple)):
        items = [_json_safe(item, depth + 1) for item in list(value)[:_MAX_LIST_ITEMS]]
        if len(value) > _MAX_LIST_ITEMS:
            items.append({"_truncated": len(value) - _MAX_LIST_ITEMS})
        return items
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in (
                "tempBody",
                "body",
                "occurrence",
                "component",
                "entity",
                "metadata",
                "nestingFlatOutline",
                "faceRegistry",
            ):
                continue
            out[key_text] = _json_safe(item, depth + 1)
        return out
    # Fusion API objects and other non-JSON types
    try:
        name = getattr(value, "name", None)
        if name not in (None, ""):
            return {"_type": type(value).__name__, "name": str(name)}
    except Exception:
        pass
    return {"_type": type(value).__name__}


def _ensure_dir():
    try:
        os.makedirs(_LOG_DIR, exist_ok=True)
    except Exception:
        pass


def _trim_jsonl_if_huge():
    try:
        if not os.path.isfile(_JSONL_PATH):
            return
        if os.path.getsize(_JSONL_PATH) <= _MAX_JSONL_BYTES:
            return
        with open(_JSONL_PATH, "r", encoding="utf-8") as handle:
            lines = handle.readlines()
        keep = lines[-800:] if len(lines) > 800 else lines
        with open(_JSONL_PATH, "w", encoding="utf-8") as handle:
            handle.writelines(keep)
    except Exception:
        pass


def log_event(kind, action="", payload=None, error=None, **extra):
    """Append one usage event. Never raises into Fusion UI."""
    event = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "tLocal": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "kind": str(kind or "event"),
        "action": str(action or ""),
        "payload": _json_safe(payload),
        "error": str(error) if error else None,
        "paths": log_paths(),
    }
    for key, value in extra.items():
        if key in event:
            continue
        event[key] = _json_safe(value)
    try:
        _ensure_dir()
        line = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
        with open(_JSONL_PATH, "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        with open(_LATEST_PATH, "w", encoding="utf-8") as handle:
            json.dump(event, handle, indent=2, ensure_ascii=False)
        _trim_jsonl_if_huge()
    except Exception:
        pass
    return event


def summarize_nesting_result(data):
    """Compact nesting fields agents care about (unplaced names/sizes)."""
    if not isinstance(data, dict):
        return {}
    unplaced = []
    for item in list(data.get("unplaced") or [])[:20]:
        if not isinstance(item, dict):
            continue
        dims = item.get("dimensions") if isinstance(item.get("dimensions"), dict) else {}
        unplaced.append({
            "bodyName": item.get("bodyName") or "",
            "panelId": item.get("panelId") or "",
            "reason": item.get("reason") or "",
            "widthMm": dims.get("widthMm"),
            "depthMm": dims.get("depthMm"),
            "heightMm": dims.get("heightMm") or dims.get("thicknessMm"),
        })
    return {
        "ok": data.get("ok"),
        "action": data.get("action"),
        "createdCount": data.get("createdCount"),
        "readyCount": data.get("readyCount"),
        "sheetCount": data.get("sheetCount"),
        "unplacedCount": data.get("unplacedCount"),
        "unplaced": unplaced,
        "trueShapeCount": data.get("trueShapeCount"),
        "rectangleFallbackCount": data.get("rectangleFallbackCount"),
        "engine": data.get("engine"),
        "message": data.get("message"),
        "errors": list(data.get("errors") or [])[:10],
        "warnings": list(data.get("warnings") or [])[:10],
    }
