"""Persistent preset libraries for the Fusion palette.

Fusion palette ``localStorage`` is wiped when Fusion closes or the palette is
recreated. Libraries are written to two local folders:

1. Plugin ``presets/user/<module>.json`` — visible file next to the add-in
2. ``%APPDATA%/UnifiedCabinet/presets/<module>.json`` — roaming backup

Opening the plugin reads and merges both so Save New / Update survive restart.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_MODULE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")

KNOWN_MODULE_KEYS = (
    "generalTall",
    "overhead",
    "attrOverhead",
    "uShapeOverhead",
    "kitchen",
    "lounge",
)


def plugin_user_presets_dir():
    try:
        folder = Path(__file__).resolve().parent / "user"
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    except Exception:
        return None


def roaming_presets_dir():
    try:
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        folder = base / "UnifiedCabinet" / "presets"
        folder.mkdir(parents=True, exist_ok=True)
        return folder
    except Exception:
        return None


def presets_dir():
    """Primary visible store (plugin folder), falling back to AppData."""
    return plugin_user_presets_dir() or roaming_presets_dir()


# Tests may replace this list so they never touch the real plugin/AppData folders.
STORE_DIRS = [plugin_user_presets_dir, roaming_presets_dir]


def _safe_module_key(module_key):
    key = str(module_key or "").strip()
    if not _MODULE_RE.match(key):
        return None
    return key


def library_paths(module_key):
    key = _safe_module_key(module_key)
    if key is None:
        return []
    paths = []
    for folder_fn in STORE_DIRS:
        try:
            folder = folder_fn()
        except Exception:
            folder = None
        if folder is None:
            continue
        path = Path(folder) / "{}.json".format(key)
        if path not in paths:
            paths.append(path)
    return paths


def library_path(module_key):
    paths = library_paths(module_key)
    return paths[0] if paths else None


def empty_library(module_key):
    return {"version": 2, "module": str(module_key or ""), "activeId": "", "items": []}


def normalize_library(payload, module_key):
    if not isinstance(payload, dict):
        return empty_library(module_key)
    items = payload.get("items")
    if not isinstance(items, list):
        items = []
    clean_items = []
    for item in items:
        if not isinstance(item, dict):
            continue
        item_id = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not item_id or not name:
            continue
        clean_items.append(
            {
                "id": item_id,
                "name": name,
                "savedAt": str(item.get("savedAt") or ""),
                "data": item.get("data") if isinstance(item.get("data"), dict) else {},
            }
        )
    active_id = str(payload.get("activeId") or "")
    if active_id and not any(item["id"] == active_id for item in clean_items):
        active_id = clean_items[0]["id"] if clean_items else ""
    return {
        "version": 2,
        "module": str(payload.get("module") or module_key or ""),
        "activeId": active_id,
        "items": clean_items,
    }


def merge_libraries(libraries, module_key):
    by_id = {}
    active_id = ""
    module_name = str(module_key or "")
    for payload in libraries or []:
        library = normalize_library(payload, module_key)
        if library.get("module"):
            module_name = library["module"]
        if library.get("activeId"):
            active_id = library["activeId"]
        for item in library.get("items") or []:
            prev = by_id.get(item["id"])
            if prev is None or str(item.get("savedAt") or "") >= str(prev.get("savedAt") or ""):
                by_id[item["id"]] = item
    items = list(by_id.values())
    if active_id and not any(item["id"] == active_id for item in items):
        active_id = items[0]["id"] if items else ""
    return {
        "version": 2,
        "module": module_name,
        "activeId": active_id,
        "items": items,
    }


def _read_library_file(path):
    if path is None or not path.is_file():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, dict) else None


def load_library(module_key):
    paths = library_paths(module_key)
    if not paths:
        return {
            "ok": False,
            "moduleKey": module_key,
            "library": empty_library(module_key),
            "errors": ["Invalid module key or presets folder unavailable."],
        }
    loaded = []
    errors = []
    existing_paths = []
    for path in paths:
        try:
            raw = _read_library_file(path)
        except Exception as ex:
            errors.append("Failed to read {}: {}".format(path, ex))
            continue
        if raw is None:
            continue
        loaded.append(normalize_library(raw, module_key))
        existing_paths.append(str(path))
    library = merge_libraries(loaded, module_key) if loaded else empty_library(module_key)
    result = {
        "ok": not errors,
        "moduleKey": module_key,
        "library": library,
        "path": existing_paths[0] if existing_paths else str(paths[0]),
        "paths": [str(path) for path in paths],
        "exists": bool(existing_paths),
    }
    if errors:
        result["errors"] = errors
        if loaded:
            result["ok"] = True
    return result


def save_library(module_key, library_payload):
    paths = library_paths(module_key)
    if not paths:
        return {
            "ok": False,
            "moduleKey": module_key,
            "errors": ["Invalid module key or presets folder unavailable."],
        }
    library = normalize_library(library_payload, module_key)
    written = []
    errors = []
    text = json.dumps(library, ensure_ascii=False, indent=2)
    for path in paths:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
            written.append(str(path))
        except Exception as ex:
            errors.append("Failed to write {}: {}".format(path, ex))
    if not written:
        return {
            "ok": False,
            "moduleKey": module_key,
            "errors": errors or ["Failed to write preset library."],
        }
    result = {
        "ok": True,
        "moduleKey": module_key,
        "library": library,
        "path": written[0],
        "paths": written,
        "itemCount": len(library.get("items") or []),
    }
    if errors:
        result["errors"] = errors
    return result


def load_all_libraries(module_keys=None):
    keys = []
    raw_keys = module_keys if isinstance(module_keys, (list, tuple)) else KNOWN_MODULE_KEYS
    for key in raw_keys:
        safe = _safe_module_key(key)
        if safe and safe not in keys:
            keys.append(safe)
    libraries = [load_library(key) for key in keys]
    paths = []
    for entry in libraries:
        for path in entry.get("paths") or []:
            if path not in paths:
                paths.append(path)
    item_count = sum(len((entry.get("library") or {}).get("items") or []) for entry in libraries)
    return {
        "ok": True,
        "libraries": libraries,
        "paths": paths,
        "itemCount": item_count,
    }
