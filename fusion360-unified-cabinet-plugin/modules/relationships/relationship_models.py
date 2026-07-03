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
            "auditNotes": list(self.auditNotes),
        }


def make_relationship_id(panel_a_id: str, panel_b_id: str) -> str:
    left, right = sorted([panel_a_id, panel_b_id])
    return "rel.{}.{}".format(left, right)


def stable_json_dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
