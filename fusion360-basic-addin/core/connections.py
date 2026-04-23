from typing import Dict, List

from config import CONFIRM_TOLERANCE, CONTACT_TOLERANCE
from core.geometry import bbox_gap, is_near_perpendicular, overlap_length_2d
from models import Connection, Part


def detect_connections(parts: List[Part]) -> List[Connection]:
    connections: List[Connection] = []
    seen = set()

    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            a = parts[i]
            b = parts[j]
            key = tuple(sorted((a.id, b.id)))
            if key in seen:
                continue

            gap, axis = bbox_gap(a, b)
            if gap > CONFIRM_TOLERANCE:
                continue
            if not is_near_perpendicular(a, b):
                continue

            contact_length = overlap_length_2d(a, b, axis)
            if contact_length <= 1.0:
                continue

            if gap <= CONTACT_TOLERANCE:
                status = "confirmed"
            else:
                status = "review"

            connections.append(
                Connection(
                    id=f"{a.id}:{b.id}",
                    part_a=a.id,
                    part_b=b.id,
                    contact_type="edge_contact",
                    contact_length=contact_length,
                    status=status,
                    axis=axis,
                    gap=gap,
                )
            )
            seen.add(key)

    return connections


def index_connections(connections: List[Connection]) -> Dict[str, Connection]:
    return {c.id: c for c in connections}
