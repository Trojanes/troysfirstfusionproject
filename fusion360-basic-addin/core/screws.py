from typing import List

from models import Connection


def compute_screw_count(contact_length: float, spacing: float, margin: float) -> int:
    usable = max(0.0, contact_length - (2.0 * margin))
    if usable <= 0:
        return 1
    return max(2, int(usable // spacing) + 1)


def compute_positions_1d(contact_length: float, spacing: float, margin: float) -> List[float]:
    count = compute_screw_count(contact_length, spacing, margin)
    if count <= 1:
        return [contact_length / 2.0]
    start = margin
    end = max(margin, contact_length - margin)
    if end == start:
        return [contact_length / 2.0]
    step = (end - start) / (count - 1)
    return [start + (i * step) for i in range(count)]


def estimate_total_holes(connections: List[Connection], spacing: float, margin: float) -> int:
    total = 0
    for c in connections:
        total += compute_screw_count(c.contact_length, spacing, margin)
    return total
