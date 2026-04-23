from typing import List, Tuple

from models import Part


def bbox_gap(a: Part, b: Part) -> Tuple[float, int]:
    max_gap = float("inf")
    gap_axis = 0
    for axis in range(3):
        a_min = a.bbox_min[axis]
        a_max = a.bbox_max[axis]
        b_min = b.bbox_min[axis]
        b_max = b.bbox_max[axis]
        if a_max < b_min:
            gap = b_min - a_max
        elif b_max < a_min:
            gap = a_min - b_max
        else:
            gap = 0.0
        if gap < max_gap:
            max_gap = gap
            gap_axis = axis
    return max_gap, gap_axis


def overlap_length_2d(a: Part, b: Part, normal_axis: int) -> float:
    axes = [i for i in (0, 1, 2) if i != normal_axis]
    overlaps: List[float] = []
    for axis in axes:
        start = max(a.bbox_min[axis], b.bbox_min[axis])
        end = min(a.bbox_max[axis], b.bbox_max[axis])
        overlaps.append(max(0.0, end - start))
    return min(overlaps) if overlaps else 0.0


def is_near_perpendicular(a: Part, b: Part) -> bool:
    # Heuristic for V1: boards with similar thickness are usually candidates.
    return abs(a.thickness - b.thickness) <= 3.0
