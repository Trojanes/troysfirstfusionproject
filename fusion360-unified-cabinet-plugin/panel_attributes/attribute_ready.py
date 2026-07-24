"""Pure Attribute Ready evaluation for panel metadata.

A panel is Attribute Ready when classification.boardType and
classification.cuttingFace are both known. Ready reads only the canonical
classification fields (after migrate); derivedTags are not authoritative.
"""

try:
    import attribute_state_service
except Exception:
    try:
        from panel_attributes import attribute_state_service
    except Exception:
        attribute_state_service = None


ATTRIBUTE_READY_STATE = "attribute_ready"
NOT_ATTRIBUTE_READY_STATE = "not_attribute_ready"

KNOWN_BOARD_TYPE_TAGS = frozenset({"carcass", "partition", "door"})
KNOWN_FACE_UP = frozenset({"MILLING", "EITHER"})


def _is_undefined_tag(value):
    text = str(value or "").strip().lower()
    if not text:
        return True
    return "unknown" in text or text in (
        "undefined",
        "unassigned",
        "none",
        "n/a",
    )


def _classification_value(metadata, field):
    classification = (
        metadata.get("classification") if isinstance(metadata, dict) else {}
    )
    state = classification.get(field) if isinstance(classification, dict) else {}
    return str((state or {}).get("value") or "").strip()


def resolve_board_type_known(metadata, derived_tags=None):
    """Return (known, boardTypeTag, missing_reason). Canonical classification only."""
    del derived_tags  # unused; kept for call-site compatibility
    canonical = _classification_value(metadata, "boardType")
    if canonical and not _is_undefined_tag(canonical):
        return True, canonical, None
    return False, canonical, "board_type_unknown"


def resolve_required_face_up(metadata):
    """Return MILLING / EITHER / UNASSIGNED from classification.cuttingFace."""
    raw = _classification_value(metadata, "cuttingFace").upper()
    if raw in KNOWN_FACE_UP:
        return raw
    # One-release fallback while older bodies only have registry roles.
    if callable(
        getattr(attribute_state_service, "derive_cutting_face_from_registry", None)
    ):
        derived = attribute_state_service.derive_cutting_face_from_registry(metadata)
        if derived in KNOWN_FACE_UP:
            return derived
    return "UNASSIGNED"


def resolve_face_up_known(metadata):
    face_up = resolve_required_face_up(metadata)
    if face_up in KNOWN_FACE_UP:
        return True, face_up, None
    cutting = (
        (metadata.get("classification") or {}).get("cuttingFace")
        if isinstance(metadata, dict)
        else None
    )
    if not isinstance(cutting, dict) or not str(cutting.get("value") or "").strip():
        registry = (
            (metadata or {}).get("faceRegistry")
            if isinstance(metadata, dict)
            else None
        )
        if not isinstance(registry, dict) or not registry.get("faces"):
            return False, face_up, "face_registry_missing"
    return False, face_up, "face_up_unassigned"


def resolve_color_known(metadata, derived_tags=None):
    """Return (known, colorTag, missing_reason). Canonical classification only."""
    del derived_tags
    canonical = _classification_value(metadata, "color").lower()
    if canonical and not _is_undefined_tag(canonical):
        return True, canonical, None
    return False, canonical, "color_unknown"


def evaluate_attribute_ready(metadata, derived_tags=None):
    normalized = metadata
    if callable(
        getattr(attribute_state_service, "migrate_metadata", None)
    ):
        normalized = attribute_state_service.migrate_metadata(metadata)
    board_ok, board_tag, board_missing = resolve_board_type_known(
        normalized, derived_tags
    )
    face_ok, face_up, face_missing = resolve_face_up_known(normalized)
    missing = [
        reason for reason in (board_missing, face_missing) if reason
    ]
    ready = bool(board_ok and face_ok)
    return {
        "ready": ready,
        "state": (
            ATTRIBUTE_READY_STATE
            if ready
            else NOT_ATTRIBUTE_READY_STATE
        ),
        "boardTypeKnown": board_ok,
        "faceUpKnown": face_ok,
        "boardTypeTag": board_tag,
        "requiredFaceUp": face_up,
        "cuttingFace": face_up,
        "missing": missing,
    }
