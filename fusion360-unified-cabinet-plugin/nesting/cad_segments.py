"""Re-export CAD segment helpers for nesting modules."""

from __future__ import annotations

import sys
from pathlib import Path

_METADATA = Path(__file__).resolve().parent.parent / "metadata"
if str(_METADATA) not in sys.path:
    sys.path.insert(0, str(_METADATA))

from cad_segments import (  # noqa: E402
    arc_segment,
    circle_segment,
    cw_from_samples,
    line_segment,
    lines_from_samples,
    normalize_segment,
    normalize_segments,
    reverse_segments,
    rotate_segments,
    segments_are_complete,
    translate_segment,
    translate_segments,
)

__all__ = [
    "arc_segment",
    "circle_segment",
    "cw_from_samples",
    "line_segment",
    "lines_from_samples",
    "normalize_segment",
    "normalize_segments",
    "reverse_segments",
    "rotate_segments",
    "segments_are_complete",
    "translate_segment",
    "translate_segments",
]
