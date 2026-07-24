"""Python counterpart of nesting/preflight.js.

Nesting Ready reads only canonical classification fields after migrate:
Board Type, Color, Cutting Face.
"""

from __future__ import annotations


def _undefined(value):
    text = str(value or "").strip().lower()
    return (
        not text
        or "unknown" in text
        or text in ("undefined", "unassigned", "none", "n/a")
    )


def _canonical(metadata, field):
    classification = (
        metadata.get("classification") if isinstance(metadata, dict) else {}
    )
    state = classification.get(field) if isinstance(classification, dict) else {}
    return str((state or {}).get("value") or "").strip()


def evaluate_record(record):
    metadata = record.get("metadata") if isinstance(record, dict) else {}
    try:
        import attribute_state_service
    except Exception:
        try:
            from panel_attributes import attribute_state_service
        except Exception:
            attribute_state_service = None
    if callable(getattr(attribute_state_service, "migrate_metadata", None)):
        metadata = attribute_state_service.migrate_metadata(metadata)

    board_type = _canonical(metadata or {}, "boardType")
    color = _canonical(metadata or {}, "color")
    cutting_face = _canonical(metadata or {}, "cuttingFace").upper()
    if cutting_face not in ("MILLING", "EITHER"):
        # Prefer scan-computed requiredFaceUp when migrate could not fill value.
        cutting_face = str(
            (record or {}).get("requiredFaceUp")
            or (record or {}).get("cuttingFace")
            or "UNASSIGNED"
        ).strip().upper()
    if cutting_face not in ("MILLING", "EITHER"):
        try:
            from attribute_ready import resolve_required_face_up
        except Exception:
            try:
                from panel_attributes.attribute_ready import resolve_required_face_up
            except Exception:
                resolve_required_face_up = None
        if callable(resolve_required_face_up):
            cutting_face = str(
                resolve_required_face_up(metadata) or "UNASSIGNED"
            ).strip().upper()

    missing = []
    if _undefined(board_type):
        missing.append("Board Type")
    if _undefined(color):
        missing.append("Color")
    if cutting_face not in ("MILLING", "EITHER"):
        missing.append("Cutting Face")
    return {
        "ready": not missing,
        "missing": missing,
        "boardTypeTag": board_type,
        "colorTag": color,
        "cuttingFace": cutting_face if cutting_face in ("MILLING", "EITHER") else "UNASSIGNED",
    }
