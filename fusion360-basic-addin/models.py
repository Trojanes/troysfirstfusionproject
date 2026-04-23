from dataclasses import dataclass
from typing import Dict, List, Tuple


Vec3 = Tuple[float, float, float]


@dataclass
class Part:
    id: str
    name: str
    component_id: str
    body_id: str
    thickness: float
    bbox_min: Vec3
    bbox_max: Vec3
    dimensions: Vec3


@dataclass
class Connection:
    id: str
    part_a: str
    part_b: str
    contact_type: str
    contact_length: float
    status: str
    axis: int
    gap: float


@dataclass
class ScrewRule:
    connection_id: str
    diameter: float
    depth: float
    spacing: float
    margin: float
    through: bool = False


def project_config() -> Dict[str, float]:
    from config import (
        CONFIRM_TOLERANCE,
        CONTACT_TOLERANCE,
        DEFAULT_SCREW_DEPTH,
        DEFAULT_SCREW_DIAMETER,
        DEFAULT_SCREW_MARGIN,
        DEFAULT_SCREW_SPACING,
    )

    return {
        "contact_tolerance": CONTACT_TOLERANCE,
        "confirm_tolerance": CONFIRM_TOLERANCE,
        "default_screw_diameter": DEFAULT_SCREW_DIAMETER,
        "default_screw_depth": DEFAULT_SCREW_DEPTH,
        "default_screw_spacing": DEFAULT_SCREW_SPACING,
        "default_screw_margin": DEFAULT_SCREW_MARGIN,
    }


def group_thickness(parts: List[Part]) -> Dict[float, List[Part]]:
    groups: Dict[float, List[Part]] = {}
    for part in parts:
        bucket = round(part.thickness)
        groups.setdefault(bucket, []).append(part)
    return groups
