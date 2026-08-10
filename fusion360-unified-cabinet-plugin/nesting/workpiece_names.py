"""Nesting workpiece body naming (Fusion-independent)."""

from __future__ import annotations


def sanitize_name_part(value, fallback=""):
    text = str(value or "").strip()
    if not text:
        return str(fallback or "")
    cleaned = []
    for ch in text:
        code = ord(ch)
        if ch in '\\/:*?"<>|\n\r\t':
            cleaned.append("_")
        elif code < 32:
            continue
        else:
            cleaned.append(ch)
    text = "".join(cleaned).strip(" ._")
    return text or str(fallback or "")


def nesting_workpiece_name(placement, used_names=None):
    """Build ``assemblyName-componentName`` (unique within the layout)."""
    assembly = sanitize_name_part((placement or {}).get("assemblyName") or "")
    component = sanitize_name_part((placement or {}).get("componentName") or "")
    body = sanitize_name_part((placement or {}).get("bodyName") or "")
    if assembly and component:
        base = "{}-{}".format(assembly, component)
    elif component:
        base = component
    elif assembly and body:
        base = "{}-{}".format(assembly, body)
    else:
        base = body or "panel"
    if len(base) > 120:
        base = base[:120].rstrip(" ._")
    used = used_names if isinstance(used_names, set) else None
    if used is None:
        return base
    candidate = base
    suffix = 2
    while candidate in used:
        tail = body if body and body not in candidate else str(suffix)
        candidate = "{}__{}".format(base[:100], tail)
        if candidate in used:
            candidate = "{}__{}".format(base[:100], suffix)
        suffix += 1
    used.add(candidate)
    return candidate
