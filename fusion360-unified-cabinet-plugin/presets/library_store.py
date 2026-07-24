"""Persistent preset libraries for the Fusion palette.

Fusion palette ``localStorage`` is unreliable across Fusion restarts (file://
webview / palette deleteMe). Store libraries under APPDATA so Save New / Update
survive closing Fusion.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

_MODULE_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]{0,63}$")


def presets_dir():
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


def _safe_module_key(module_key):
    key = str(module_key or "").strip()
    if not _MODULE_RE.match(key):
        return None
    return key


def library_path(module_key):
    folder = presets_dir()
    key = _safe_module_key(module_key)
    if folder is None or key is None:
        return None
    return folder / "{}.json".format(key)


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


def load_library(module_key):
    path = library_path(module_key)
    if path is None:
        return {
            "ok": False,
            "moduleKey": module_key,
            "library": empty_library(module_key),
            "errors": ["Invalid module key or presets folder unavailable."],
        }
    if not path.is_file():
        return {
            "ok": True,
            "moduleKey": module_key,
            "library": empty_library(module_key),
            "path": str(path),
            "exists": False,
        }
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        library = normalize_library(raw, module_key)
        return {
            "ok": True,
            "moduleKey": module_key,
            "library": library,
            "path": str(path),
            "exists": True,
        }
    except Exception as ex:
        return {
            "ok": False,
            "moduleKey": module_key,
            "library": empty_library(module_key),
            "path": str(path),
            "errors": ["Failed to read preset library: {}".format(ex)],
        }


def save_library(module_key, library_payload):
    path = library_path(module_key)
    if path is None:
        return {
            "ok": False,
            "moduleKey": module_key,
            "errors": ["Invalid module key or presets folder unavailable."],
        }
    library = normalize_library(library_payload, module_key)
    try:
        path.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")
        return {
            "ok": True,
            "moduleKey": module_key,
            "library": library,
            "path": str(path),
            "itemCount": len(library.get("items") or []),
        }
    except Exception as ex:
        return {
            "ok": False,
            "moduleKey": module_key,
            "errors": ["Failed to write preset library: {}".format(ex)],
        }
