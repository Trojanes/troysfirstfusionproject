"""Persist / hydrate face_verified relationship upgrades on panel metadata.

ponytail: session-only face verify was fine for 3a smokes; production reloads need
a durable mark on the panels so scan can restore safeForCut without re-picking faces.
Does not relax bbox cut gate — only restores face_verified records already earned.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, List, Optional, Tuple

RELATIONSHIP_VERIFICATIONS_KEY = "relationshipVerifications"
PERSISTED_METHOD = "face_verified_persisted_v1"

# Do not overwrite these with a restored face_verified mark.
_PROTECTED_LEVELS = frozenset(
    {"generator_declared", "manual_confirmed", "cut_approved", "face_verified"}
)


def _panel_ids(relationship: Dict[str, Any]) -> Tuple[str, str]:
    panel_a = relationship.get("panelA") or {}
    panel_b = relationship.get("panelB") or {}
    return (
        str(panel_a.get("panelId") or "").strip(),
        str(panel_b.get("panelId") or "").strip(),
    )


def build_persisted_verification_record(
    relationship: Dict[str, Any],
    *,
    face_match: Optional[Dict[str, Any]] = None,
    for_panel_id: str = "",
) -> Dict[str, Any]:
    panel_a_id, panel_b_id = _panel_ids(relationship)
    partner = panel_b_id if for_panel_id == panel_a_id else panel_a_id
    if for_panel_id and for_panel_id not in (panel_a_id, panel_b_id):
        partner = panel_b_id or panel_a_id
    match = face_match if isinstance(face_match, dict) else (relationship.get("faceMatch") or {})
    return {
        "level": "face_verified",
        "safeForPreview": True,
        "safeForCut": True,
        "requiresManualConfirmation": False,
        "partnerPanelId": partner,
        "faceMatch": dict(match),
        "method": PERSISTED_METHOD,
    }


def upsert_relationship_verification(
    panel_metadata: Dict[str, Any],
    relationship_id: str,
    record: Dict[str, Any],
) -> Dict[str, Any]:
    metadata = copy.deepcopy(panel_metadata or {})
    if "schemaVersion" not in metadata:
        metadata["schemaVersion"] = 1
    store = metadata.get(RELATIONSHIP_VERIFICATIONS_KEY)
    if not isinstance(store, dict):
        store = {}
    store = dict(store)
    rid = str(relationship_id or "").strip()
    if rid:
        store[rid] = dict(record or {})
    metadata[RELATIONSHIP_VERIFICATIONS_KEY] = store
    return metadata


def read_persisted_verification(
    panel_metadata: Optional[Dict[str, Any]],
    relationship_id: str,
) -> Optional[Dict[str, Any]]:
    if not isinstance(panel_metadata, dict):
        return None
    store = panel_metadata.get(RELATIONSHIP_VERIFICATIONS_KEY)
    if not isinstance(store, dict):
        return None
    record = store.get(str(relationship_id or "").strip())
    return dict(record) if isinstance(record, dict) else None


def apply_persisted_verification_to_relationship(
    relationship: Dict[str, Any],
    record: Dict[str, Any],
) -> Dict[str, Any]:
    """Upgrade bbox_candidate (only) to face_verified from a persisted record."""
    if not isinstance(relationship, dict) or not isinstance(record, dict):
        return relationship
    if str(record.get("level") or "") != "face_verified":
        return relationship
    verification = relationship.get("verification") or {}
    level = str(verification.get("level") or "bbox_candidate")
    if level in _PROTECTED_LEVELS:
        return relationship
    upgraded = copy.deepcopy(relationship)
    upgraded["verification"] = {
        "level": "face_verified",
        "safeForPreview": True,
        "safeForCut": True,
        "requiresManualConfirmation": False,
    }
    face_match = record.get("faceMatch")
    if isinstance(face_match, dict) and face_match:
        upgraded["faceMatch"] = dict(face_match)
    notes = list(upgraded.get("auditNotes") or [])
    notes.append("Restored face_verified from panel metadata ({}).".format(PERSISTED_METHOD))
    upgraded["auditNotes"] = notes
    return upgraded


def hydrate_relationships_from_panel_metadata(
    relationships: List[Dict[str, Any]],
    metadata_by_panel_id: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Restore face_verified when either panel carries a matching verification record."""
    out: List[Dict[str, Any]] = []
    meta_map = metadata_by_panel_id if isinstance(metadata_by_panel_id, dict) else {}
    for rel in relationships or []:
        if not isinstance(rel, dict):
            continue
        rid = str(rel.get("relationshipId") or "").strip()
        panel_a_id, panel_b_id = _panel_ids(rel)
        record = read_persisted_verification(meta_map.get(panel_a_id), rid)
        if record is None:
            record = read_persisted_verification(meta_map.get(panel_b_id), rid)
        if record is None:
            out.append(rel)
            continue
        out.append(apply_persisted_verification_to_relationship(rel, record))
    return out


def persist_face_verification_to_body_metadata(
    body,
    relationship: Dict[str, Any],
    *,
    face_match: Optional[Dict[str, Any]] = None,
    panel_id: str = "",
) -> Dict[str, Any]:
    """Write verification mark onto one panel body. Uses hardware writeback I/O helpers."""
    from panel_metadata_writeback import read_panel_metadata_from_body, write_panel_metadata_to_body

    rid = str((relationship or {}).get("relationshipId") or "").strip()
    if not body or not rid:
        return {"ok": False, "persisted": False, "errors": ["Missing body or relationshipId."]}

    existing, read_error = read_panel_metadata_from_body(body)
    if read_error and existing is None and read_error not in (None, "Empty metadata attribute"):
        return {"ok": False, "persisted": False, "errors": [read_error]}

    base = existing if isinstance(existing, dict) else {"schemaVersion": 1, "features": []}
    pid = str(panel_id or "").strip()
    if not pid:
        pid = str((base.get("panelId") or "")).strip()
    record = build_persisted_verification_record(
        relationship,
        face_match=face_match,
        for_panel_id=pid,
    )
    updated = upsert_relationship_verification(base, rid, record)
    written = write_panel_metadata_to_body(body, updated)
    return {
        "ok": written,
        "persisted": written,
        "relationshipId": rid,
        "panelId": pid,
        "errors": [] if written else ["Failed to write relationship verification to body."],
    }


def persist_face_verification_to_pair_bodies(
    body_a,
    body_b,
    relationship: Dict[str, Any],
    *,
    face_match: Optional[Dict[str, Any]] = None,
    panel_a_id: str = "",
    panel_b_id: str = "",
) -> Dict[str, Any]:
    reports = []
    if body_a is not None:
        reports.append(
            persist_face_verification_to_body_metadata(
                body_a,
                relationship,
                face_match=face_match,
                panel_id=panel_a_id,
            )
        )
    if body_b is not None:
        reports.append(
            persist_face_verification_to_body_metadata(
                body_b,
                relationship,
                face_match=face_match,
                panel_id=panel_b_id,
            )
        )
    ok = all(item.get("ok") for item in reports) if reports else False
    return {
        "ok": ok,
        "persistedCount": sum(1 for item in reports if item.get("persisted")),
        "panels": reports,
        "errors": [err for item in reports for err in (item.get("errors") or [])],
    }
