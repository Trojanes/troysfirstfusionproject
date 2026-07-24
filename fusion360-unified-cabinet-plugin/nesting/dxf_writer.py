"""Minimal ASCII DXF writer tuned for ArtCAM import.

Single layer, millimetre units, closed polylines only. No third-party deps.
"""

from __future__ import annotations


DEFAULT_LAYER = "0"


def _fmt(value):
    return "{:.6f}".format(float(value))


def _close_ring(points):
    ring = [[float(p[0]), float(p[1])] for p in (points or []) if len(p) >= 2]
    if len(ring) < 3:
        return []
    if (
        abs(ring[0][0] - ring[-1][0]) > 1e-9
        or abs(ring[0][1] - ring[-1][1]) > 1e-9
    ):
        ring.append([ring[0][0], ring[0][1]])
    if len(ring) < 4:
        return []
    return ring


def build_dxf_ascii(polylines, layer=DEFAULT_LAYER):
    """Return DXF R12-compatible ASCII text for closed 2D polylines (mm)."""
    lines = [
        "0",
        "SECTION",
        "2",
        "HEADER",
        "9",
        "$INSUNITS",
        "70",
        "4",  # millimetres
        "9",
        "$MEASUREMENT",
        "70",
        "1",  # metric
        "0",
        "ENDSEC",
        "0",
        "SECTION",
        "2",
        "TABLES",
        "0",
        "TABLE",
        "2",
        "LAYER",
        "70",
        "1",
        "0",
        "LAYER",
        "2",
        str(layer or DEFAULT_LAYER),
        "70",
        "0",
        "62",
        "7",
        "6",
        "CONTINUOUS",
        "0",
        "ENDTAB",
        "0",
        "ENDSEC",
        "0",
        "SECTION",
        "2",
        "ENTITIES",
    ]
    for points in polylines or []:
        ring = _close_ring(points)
        if not ring:
            continue
        # Classic POLYLINE is the most reliable ArtCAM import path.
        lines.extend(
            [
                "0",
                "POLYLINE",
                "8",
                str(layer or DEFAULT_LAYER),
                "66",
                "1",
                "70",
                "1",  # closed
                "10",
                "0.0",
                "20",
                "0.0",
                "30",
                "0.0",
            ]
        )
        for x, y in ring[:-1]:
            lines.extend(
                [
                    "0",
                    "VERTEX",
                    "8",
                    str(layer or DEFAULT_LAYER),
                    "10",
                    _fmt(x),
                    "20",
                    _fmt(y),
                    "30",
                    "0.0",
                ]
            )
        lines.extend(["0", "SEQEND"])
    lines.extend(["0", "ENDSEC", "0", "EOF", ""])
    return "\n".join(lines)


def write_dxf_file(path, polylines, layer=DEFAULT_LAYER):
    text = build_dxf_ascii(polylines, layer=layer)
    with open(path, "w", encoding="ascii", newline="\n") as handle:
        handle.write(text)
    return path
