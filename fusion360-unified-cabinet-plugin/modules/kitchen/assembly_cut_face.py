"""Pure helpers for kitchen assembly-path groove cut faces.

YZ V panels are built in pose; half grooves must open onto the mating board
face:
  side=left  → open on -X (bbox.x0), cut toward +X
  side=right → open on +X (bbox.x1), cut toward -X

Through cuts keep the legacy +max-face sketch and cut inward.
"""


def normalize_slot_side(value):
    text = str(value or "").strip().lower()
    if text in ("left", "right"):
        return text
    return None


def assembly_cut_face(plane, bbox, cutout):
    """Resolve sketch-face coordinate and extrude sign for an assembly cutout.

    Returns:
        {
          "side": "left"|"right"|None,
          "axis": "x"|"y"|"z",
          "originMm": float,
          "extrudeSign": +1|-1,  # world-axis direction of the cut into the panel
          "isHalf": bool,
        }
    """
    plane = str(plane or "").upper()
    bbox = bbox if isinstance(bbox, dict) else {}
    cutout = cutout if isinstance(cutout, dict) else {}
    is_half = (
        str(cutout.get("kind") or "") == "slot"
        and str(cutout.get("slotType") or "").lower() == "half"
    )
    side = normalize_slot_side(cutout.get("side")) if is_half else None

    if plane == "YZ":
        axis = "x"
        low = float(bbox.get("x0") or 0.0)
        high = float(bbox.get("x1") or 0.0)
    elif plane == "XY":
        axis = "z"
        low = float(bbox.get("z0") or 0.0)
        high = float(bbox.get("z1") or 0.0)
    elif plane == "XZ":
        axis = "y"
        low = float(bbox.get("y0") or 0.0)
        high = float(bbox.get("y1") or 0.0)
    else:
        return {
            "side": side,
            "axis": None,
            "originMm": None,
            "extrudeSign": -1,
            "isHalf": is_half,
        }

    if is_half and side == "left":
        return {
            "side": "left",
            "axis": axis,
            "originMm": low,
            "extrudeSign": 1,
            "isHalf": True,
        }
    # half/right, through, notches: legacy +max face, cut toward -axis
    return {
        "side": side or ("right" if is_half else None),
        "axis": axis,
        "originMm": high,
        "extrudeSign": -1,
        "isHalf": is_half,
    }
