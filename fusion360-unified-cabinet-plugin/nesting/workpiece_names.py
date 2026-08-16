"""Canonical shop-facing workpiece naming (Fusion-independent).

Identity and display names are deliberately separate:

* ``runLabel`` / ``caseName`` identifies one generator run.
* ``panelId`` identifies a manufacturing record (descriptive, not always unique).
* ``assemblyName`` and ``componentName`` form the shop label
  ``assembly-component``.

Fusion generators, Lay Flat/Nesting and manufacturing export all use this module
so their browser and package names cannot drift independently.
"""

from __future__ import annotations

import re


_ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}T", re.IGNORECASE)
_MILLIS_RE = re.compile(r"^\d{10,}$")
_SHORT_CODE_RE = re.compile(r"^[A-Za-z]{1,8}\d+[A-Za-z0-9_-]*$")


def sanitize_name_part(value, fallback=""):
    """Return a Fusion-safe name without changing valid punctuation/case."""
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


def is_layout_container_label(value):
    """True for work-zone containers, never for a source assembly."""
    text = str(value or "").strip()
    if not text:
        return False
    upper = text.upper()
    return (
        upper == "LAY_FLAT"
        or upper.startswith("LAY_FLAT:")
        or upper.startswith("LAY_FLAT (")
        or upper.startswith("LAY_FLAT -")
        or (
            "LAY_FLAT" in upper
            and upper.replace(" ", "").startswith("LAY_FLAT:")
        )
    )


def is_generic_body_name(value):
    """True for Fusion's default ``Body`` / ``Body1`` labels."""
    text = str(value or "").strip()
    if not text:
        return True
    upper = text.upper()
    return upper == "BODY" or (
        upper.startswith("BODY") and upper[4:].isdigit()
    )


def is_blob_label(value):
    """True when a run/timestamp label was incorrectly used as a shop name."""
    text = str(value or "").strip()
    if not text:
        return True
    upper = text.upper()
    return (
        "FLAT_ASSEMBLY" in upper
        or bool(_ISO_DATE_RE.search(text))
        or "KITCHEN_KITCHEN" in upper
        or bool(_MILLIS_RE.fullmatch(text))
        or (
            upper.startswith("KITCHEN_")
            and bool(re.search(r"_\d{10,}$", upper))
        )
    )


def strip_instance_suffix(value):
    """Remove a Lay Flat/export uniquifier after the first ``@`` for display."""
    text = str(value or "").strip()
    at = text.find("@")
    return text if at < 0 else text[:at]


def short_part_from_body(body_name):
    """Derive a readable board code from a module body name.

    ``KITCHEN_vPanel_V2`` → ``V2``
    ``KITCHEN_frontPanel_k-zone-left-door`` → ``k-zone-left-door``
    """
    text = sanitize_name_part(body_name)
    if not text:
        return ""
    upper = text.upper()
    if upper.startswith("KITCHEN_"):
        rest = text[8:]
        index = rest.find("_")
        if index > 0:
            panel_id = rest[index + 1 :].strip(" ._")
            return (panel_id or rest[:index])[:48]
        return rest[:48]
    if _SHORT_CODE_RE.match(text) and len(text) <= 48:
        return text
    return text[:48]


def short_group_label(assembly_name, body_name="", default_group="Assembly"):
    """Resolve a stable short group for legacy polluted assemblies."""
    assembly = sanitize_name_part(assembly_name)
    body = str(body_name or "")
    if is_blob_label(assembly) or not assembly:
        if body.upper().startswith("KITCHEN") or (
            assembly and assembly.upper().startswith("KITCHEN")
        ):
            return "Kitchen"
        return sanitize_name_part(default_group, fallback="Assembly")
    if assembly.upper() == "KITCHEN":
        return "Kitchen"
    return assembly


def resolve_assembly_name(
    explicit_name,
    run_label="",
    default_name="Assembly",
    include_human_run_label=False,
):
    """Resolve a generator container name without leaking run timestamps.

    Explicit user names always win. A non-blob run label is appended only for
    generators that historically used a meaningful case label.
    """
    explicit = sanitize_name_part(explicit_name)
    if explicit and not is_blob_label(explicit):
        return explicit
    default = sanitize_name_part(default_name, fallback="Assembly")
    run = sanitize_name_part(run_label)
    if (
        include_human_run_label
        and run
        and not is_blob_label(run)
        and run.lower() != default.lower()
    ):
        return "{}_{}".format(default, run)[:76].rstrip(" ._")
    return default


def join_group_part(group, part):
    """Join valid source names using the canonical hyphen separator."""
    left = sanitize_name_part(group)
    right = sanitize_name_part(part)
    if (
        not left
        or not right
        or is_layout_container_label(left)
        or is_layout_container_label(right)
        or is_blob_label(left)
        or is_blob_label(right)
    ):
        return ""
    return "{}-{}".format(left, right)


def resolve_shop_label(
    assembly_name="",
    component_name="",
    body_name="",
    panel_id="",
    default_group="Assembly",
):
    """Resolve one deterministic shop label from canonical naming fields."""
    assembly = sanitize_name_part(assembly_name)
    component = sanitize_name_part(component_name)
    body = sanitize_name_part(body_name)
    panel = strip_instance_suffix(panel_id)

    assembly_invalid = (
        not assembly
        or is_blob_label(assembly)
        or is_layout_container_label(assembly)
    )
    component_invalid = (
        not component
        or is_blob_label(component)
        or is_layout_container_label(component)
    )
    same_container = bool(
        assembly
        and component
        and assembly.lower() == component.lower()
    )

    if not assembly_invalid and not component_invalid and not same_container:
        joined = join_group_part(assembly, component)
        if joined:
            return joined[:120].rstrip(" ._")

    # Legacy Kitchen often put the same timestamp blob in both fields.
    if (assembly_invalid or same_container) and body.upper().startswith("KITCHEN"):
        group = short_group_label(assembly, body, default_group="Kitchen")
        part = short_part_from_body(body) or "panel"
        return "{}-{}".format(group, part)[:120].rstrip(" ._")

    # A renamed LAY_FLAT body already holds the canonical browser label.
    if body and not is_generic_body_name(body) and not is_layout_container_label(body):
        return body[:120].rstrip(" ._")

    if not component_invalid:
        if not assembly_invalid and not same_container:
            return join_group_part(assembly, component)[:120].rstrip(" ._")
        return component[:120].rstrip(" ._")

    if not assembly_invalid and body:
        part = short_part_from_body(body)
        joined = join_group_part(assembly, part)
        if joined:
            return joined[:120].rstrip(" ._")

    return panel or short_part_from_body(body) or "panel"


def _source_identity(record):
    metadata = (
        (record or {}).get("metadata")
        if isinstance((record or {}).get("metadata"), dict)
        else {}
    )
    identity = (
        metadata.get("identity")
        if isinstance(metadata.get("identity"), dict)
        else {}
    )
    source_ref = (
        identity.get("sourceRef")
        if isinstance(identity.get("sourceRef"), dict)
        else {}
    )
    if not source_ref and isinstance((record or {}).get("sourceRef"), dict):
        source_ref = record.get("sourceRef") or {}
    return identity, source_ref


def display_workpiece_name(record, panel_id=""):
    """Resolve `.cnjob name` with the same rules used by Lay Flat bodies."""
    record = record or {}
    identity, source_ref = _source_identity(record)
    body = str(record.get("bodyName") or "").strip()
    record_assembly = str(record.get("assemblyName") or "").strip()
    record_component = str(record.get("componentName") or "").strip()

    # A LAY_FLAT scan sees only its container; preserve its already-renamed body.
    if (
        (
            is_layout_container_label(record_assembly)
            or is_layout_container_label(record_component)
        )
        and body
        and not is_generic_body_name(body)
        and not is_layout_container_label(body)
    ):
        return resolve_shop_label(body_name=body, panel_id=panel_id)

    source_assembly = str(
        identity.get("sourceAssemblyName")
        or source_ref.get("assemblyName")
        or record.get("sourceAssemblyName")
        or ""
    ).strip()
    source_component = str(
        identity.get("sourceComponentName")
        or source_ref.get("componentName")
        or record.get("sourceComponentName")
        or ""
    ).strip()
    source_body = str(
        identity.get("sourceBodyName")
        or source_ref.get("bodyName")
        or record.get("sourceBodyName")
        or ""
    ).strip()
    source_panel = str(
        identity.get("sourcePanelId")
        or source_ref.get("panelId")
        or record.get("sourcePanelId")
        or panel_id
        or ""
    ).strip()

    if source_assembly or source_component or source_body:
        source_name = resolve_shop_label(
            assembly_name=source_assembly,
            component_name=source_component,
            body_name=source_body,
            panel_id=source_panel,
        )
        if source_name and source_name != strip_instance_suffix(source_panel):
            return source_name

    return resolve_shop_label(
        assembly_name=record_assembly,
        component_name=record_component,
        body_name=body,
        panel_id=panel_id,
    )


def nesting_workpiece_name(placement, used_names=None):
    """Build a canonical unique browser label for Lay Flat/Nesting copies."""
    placement = placement or {}
    base = resolve_shop_label(
        assembly_name=placement.get("assemblyName"),
        component_name=placement.get("componentName"),
        body_name=placement.get("bodyName"),
        panel_id=placement.get("panelId"),
    )
    used = used_names if isinstance(used_names, set) else None
    if used is None:
        return base
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = "{}__{}".format(base[:110], suffix)
        suffix += 1
    used.add(candidate)
    return candidate
