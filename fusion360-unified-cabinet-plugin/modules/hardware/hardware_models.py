"""Hardware feature intent schemas."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

HARDWARE_SCHEMA_VERSION = 1


@dataclass
class HardwareFeatureGeometry:
    diameterMm: float
    depthMm: float
    axis: str
    positions: List[Dict[str, float]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "diameterMm": round(float(self.diameterMm), 4),
            "depthMm": round(float(self.depthMm), 4),
            "axis": self.axis,
            "positions": [
                {
                    "x": round(float(pos["x"]), 4),
                    "y": round(float(pos["y"]), 4),
                    "z": round(float(pos["z"]), 4),
                }
                for pos in self.positions
            ],
        }


@dataclass
class HardwareFeatureSource:
    method: str = "relationship_based_rule"
    ruleId: str = "screw_hole_from_edge_to_surface_v1"

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


@dataclass
class HardwareFeatureValidation:
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
class HardwareFeatureIntent:
    schemaVersion: int
    featureId: str
    type: str
    sourceRelationshipId: str
    hostPanelId: str
    targetPanelId: str
    geometry: HardwareFeatureGeometry
    source: HardwareFeatureSource
    validation: HardwareFeatureValidation

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": self.schemaVersion,
            "featureId": self.featureId,
            "type": self.type,
            "sourceRelationshipId": self.sourceRelationshipId,
            "hostPanelId": self.hostPanelId,
            "targetPanelId": self.targetPanelId,
            "geometry": self.geometry.to_dict(),
            "source": self.source.to_dict(),
            "validation": self.validation.to_dict(),
        }
