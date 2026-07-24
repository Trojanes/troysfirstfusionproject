"""Stable JSON schemas for panel snapshots and board relationships."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

GEOMETRY_TYPES = (
    "edge_to_surface",
    "surface_to_surface",
    "gap_parallel",
    "intersection",
    "none",
)

RELATIONSHIP_TYPES = (
    "structural_butt_joint",
    "face_contact",
    "door_to_carcass_candidate",
    "collision",
    "unknown",
)

CONTACT_AXES = ("X", "Y", "Z", "NONE")

SOURCE_METHODS = (
    "geometry_detected",
    "semantic_inferred",
    "manual",
    "generator_declared",
)

VERIFICATION_LEVELS = (
    "bbox_candidate",
    "manual_confirmed",
    "face_verified",
    "generator_declared",
    "cut_approved",
)

DETECTION_METHOD_BBOX_AABB = "bbox_aabb"


@dataclass
class BBoxMm:
    x0: float
    x1: float
    y0: float
    y1: float
    z0: float
    z1: float

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)

    @property
    def size_x(self) -> float:
        return self.x1 - self.x0

    @property
    def size_y(self) -> float:
        return self.y1 - self.y0

    @property
    def size_z(self) -> float:
        return self.z1 - self.z0


@dataclass
class PanelRef:
    panelId: str
    bodyName: str
    boardType: Optional[str] = None
    role: Optional[str] = None
    sourceBoardId: Optional[str] = None
    materialClass: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "panelId": self.panelId,
            "bodyName": self.bodyName,
        }
        if self.boardType:
            out["boardType"] = self.boardType
        if self.role:
            out["role"] = self.role
        if self.sourceBoardId:
            out["sourceBoardId"] = self.sourceBoardId
        if self.materialClass:
            out["materialClass"] = self.materialClass
        return out


@dataclass
class PanelSnapshot:
    panelId: str
    bodyName: str
    bbox: BBoxMm
    boardType: Optional[str] = None
    role: Optional[str] = None
    sourceBoardId: Optional[str] = None
    materialClass: Optional[str] = None
    thicknessAxis: str = "UNKNOWN"
    sizeX: float = 0.0
    sizeY: float = 0.0
    sizeZ: float = 0.0
    thicknessMm: Optional[float] = None
    metadataWarnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "panelId": self.panelId,
            "bodyName": self.bodyName,
            "boardType": self.boardType,
            "role": self.role,
            "sourceBoardId": self.sourceBoardId,
            "materialClass": self.materialClass,
            "bbox": self.bbox.to_dict(),
            "dimensions": {
                "sizeX": self.sizeX,
                "sizeY": self.sizeY,
                "sizeZ": self.sizeZ,
                "thicknessMm": self.thicknessMm,
            },
            "inferred": {
                "thicknessAxis": self.thicknessAxis,
            },
            "metadataWarnings": list(self.metadataWarnings),
        }


@dataclass
class ContactMetrics:
    axis: str = "NONE"
    distanceMm: float = 0.0
    overlapX: float = 0.0
    overlapY: float = 0.0
    overlapZ: float = 0.0
    contactLengthMm: float = 0.0
    contactAreaMm2: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class RelationshipRoles:
    hostPanelId: Optional[str] = None
    targetPanelId: Optional[str] = None

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "hostPanelId": self.hostPanelId,
            "targetPanelId": self.targetPanelId,
        }


@dataclass
class RelationshipSource:
    method: str = "geometry_detected"
    confidence: float = 0.0
    ruleId: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        out = {
            "method": self.method,
            "confidence": round(float(self.confidence), 4),
        }
        if self.ruleId:
            out["ruleId"] = self.ruleId
        return out


@dataclass
class RelationshipValidation:
    ok: bool = True
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ok": self.ok,
            "warnings": list(self.warnings),
            "errors": list(self.errors),
        }


@dataclass
class RelationshipVerification:
    level: str = "bbox_candidate"
    safeForPreview: bool = True
    safeForCut: bool = False
    requiresManualConfirmation: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "safeForPreview": bool(self.safeForPreview),
            "safeForCut": bool(self.safeForCut),
            "requiresManualConfirmation": bool(self.requiresManualConfirmation),
        }


def bbox_candidate_verification() -> RelationshipVerification:
    return RelationshipVerification(
        level="bbox_candidate",
        safeForPreview=True,
        safeForCut=False,
        requiresManualConfirmation=True,
    )


def manual_confirmed_verification() -> RelationshipVerification:
    return RelationshipVerification(
        level="manual_confirmed",
        safeForPreview=True,
        safeForCut=True,
        requiresManualConfirmation=False,
    )


def face_verified_verification() -> RelationshipVerification:
    return RelationshipVerification(
        level="face_verified",
        safeForPreview=True,
        safeForCut=True,
        requiresManualConfirmation=False,
    )


def generator_declared_verification(*, geometry_ok: bool = False) -> RelationshipVerification:
    return RelationshipVerification(
        level="generator_declared",
        safeForPreview=True,
        safeForCut=bool(geometry_ok),
        requiresManualConfirmation=not bool(geometry_ok),
    )


def verification_from_dict(data: Optional[Dict[str, Any]]) -> RelationshipVerification:
    if not isinstance(data, dict):
        return bbox_candidate_verification()
    level = str(data.get("level") or "bbox_candidate")
    if level in ("manual_confirmed", "face_verified", "generator_declared"):
        return RelationshipVerification(
            level=level,
            safeForPreview=bool(data.get("safeForPreview", True)),
            safeForCut=bool(data.get("safeForCut", level != "generator_declared")),
            requiresManualConfirmation=bool(data.get("requiresManualConfirmation", level == "generator_declared")),
        )
    return RelationshipVerification(
        level=level,
        safeForPreview=bool(data.get("safeForPreview", level == "bbox_candidate")),
        safeForCut=bool(data.get("safeForCut", False)),
        requiresManualConfirmation=bool(
            data.get("requiresManualConfirmation", level == "bbox_candidate")
        ),
    )


def confirm_relationship_for_cut(relationship: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy of a relationship dict approved for debug-session cut testing."""
    if not isinstance(relationship, dict):
        raise TypeError("relationship must be a dict")
    confirmed = dict(relationship)
    confirmed["verification"] = manual_confirmed_verification().to_dict()
    notes = list(confirmed.get("auditNotes") or [])
    notes.append("Manual cut confirmation applied (debug session only).")
    confirmed["auditNotes"] = notes
    return confirmed


def upgrade_relationship_with_face_verification(
    relationship: Dict[str, Any],
    face_match: Dict[str, Any],
) -> Dict[str, Any]:
    if not isinstance(relationship, dict):
        raise TypeError("relationship must be a dict")
    upgraded = dict(relationship)
    upgraded["verification"] = face_verified_verification().to_dict()
    upgraded["faceMatch"] = dict(face_match or {})
    upgraded["detectionMethod"] = str(relationship.get("detectionMethod") or DETECTION_METHOD_BBOX_AABB)
    notes = list(upgraded.get("auditNotes") or [])
    notes.append("Face-level verification applied (M5 axis-aligned v1).")
    upgraded["auditNotes"] = notes
    return upgraded


@dataclass
class BoardRelationship:
    schemaVersion: int
    relationshipId: str
    panelA: PanelRef
    panelB: PanelRef
    geometryType: str
    relationshipType: str
    contact: ContactMetrics
    roles: RelationshipRoles
    source: RelationshipSource
    validation: RelationshipValidation
    verification: RelationshipVerification = field(default_factory=bbox_candidate_verification)
    detectionMethod: str = DETECTION_METHOD_BBOX_AABB
    auditNotes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "relationshipId": self.relationshipId,
            "panelA": self.panelA.to_dict(),
            "panelB": self.panelB.to_dict(),
            "geometryType": self.geometryType,
            "relationshipType": self.relationshipType,
            "contact": self.contact.to_dict(),
            "roles": self.roles.to_dict(),
            "source": self.source.to_dict(),
            "validation": self.validation.to_dict(),
            "verification": self.verification.to_dict(),
            "detectionMethod": self.detectionMethod,
            "auditNotes": list(self.auditNotes),
        }


def make_relationship_id(panel_a_id: str, panel_b_id: str) -> str:
    left, right = sorted([panel_a_id, panel_b_id])
    return "rel.{}.{}".format(left, right)


def stable_json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
