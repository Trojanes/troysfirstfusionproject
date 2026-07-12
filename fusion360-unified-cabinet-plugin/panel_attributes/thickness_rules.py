"""Thickness → board-type rules for panel attribute classification.

Users configure nominal thicknesses for board families (defaults: carcass /
partition / door; custom types can be added). At scan time each body's
measured thickness (min bbox edge, mm) is matched to the nearest rule within
tolerance and used to fill boardTypeTag / materialClass when those are still
unknown.
"""

import re
import attribute_state_service

DEFAULT_TOLERANCE_MM = 0.6

DEFAULT_RULES = [
    {"boardTypeTag": "carcass", "materialClass": "carcass_board", "thicknessMm": 15.0, "label": "Carcass"},
    {"boardTypeTag": "partition", "materialClass": "partition_board", "thicknessMm": 18.0, "label": "Partition"},
    {"boardTypeTag": "door", "materialClass": "door_board", "thicknessMm": 16.0, "label": "Door"},
]

KNOWN_BOARD_TYPE_TAGS = ("carcass", "partition", "door")

MATERIAL_FOR_TAG = {
    "carcass": "carcass_board",
    "partition": "partition_board",
    "door": "door_board",
}

ROLE_FOR_TAG = {
    "carcass": "carcass",
    "partition": "partition",
    "door": "door",
}

_TAG_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

RULES_ATTR_GROUP = "UnifiedCabinet"
RULES_ATTR_NAME = "thicknessBoardRules"
USER_DEFAULTS_FILENAME = "thickness_board_rules_default.json"


def user_defaults_path():
    """Cross-design defaults file (Windows APPDATA / ~/.config)."""
    try:
        from pathlib import Path
        import os

        if os.name == "nt":
            base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        else:
            base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
        folder = base / "UnifiedCabinet"
        folder.mkdir(parents=True, exist_ok=True)
        return folder / USER_DEFAULTS_FILENAME
    except Exception:
        return None


def load_user_defaults():
    """Load user-wide default rules, or None if unset/invalid."""
    path = user_defaults_path()
    if path is None:
        return None
    try:
        import json

        if not path.is_file():
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return normalize_rules(data.get("rules"), data.get("toleranceMm"))
        if isinstance(data, list):
            return normalize_rules(data)
    except Exception:
        return None
    return None


def save_user_defaults(rules_payload):
    """Persist rules as the user-wide default for new / unset designs."""
    payload = normalize_rules(
        (rules_payload or {}).get("rules") if isinstance(rules_payload, dict) else rules_payload,
        (rules_payload or {}).get("toleranceMm") if isinstance(rules_payload, dict) else None,
    )
    path = user_defaults_path()
    if path is None:
        return False, payload
    try:
        import json

        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return True, payload
    except Exception:
        return False, payload


def builtin_defaults():
    return normalize_rules(DEFAULT_RULES)


def material_class_for_tag(tag):
    text = str(tag or "").strip().lower()
    if text in MATERIAL_FOR_TAG:
        return MATERIAL_FOR_TAG[text]
    if text:
        return "{}_board".format(text)
    return ""


def role_for_tag(tag):
    text = str(tag or "").strip().lower()
    return ROLE_FOR_TAG.get(text, text)


def is_valid_board_type_tag(tag):
    text = str(tag or "").strip().lower()
    return bool(_TAG_RE.match(text))


def normalize_rules(rules, tolerance_mm=None):
    """Return a clean rules payload suitable for UI + scan.

    Accepts built-in tags and custom tags matching ``^[a-z][a-z0-9_]{0,31}$``.
    """
    cleaned = []
    seen = set()
    for item in rules or []:
        if not isinstance(item, dict):
            continue
        tag = str(item.get("boardTypeTag") or item.get("tag") or "").strip().lower()
        if not is_valid_board_type_tag(tag) or tag in seen:
            continue
        try:
            thickness = float(
                item.get("thicknessMm") if item.get("thicknessMm") is not None else item.get("thickness")
            )
        except Exception:
            continue
        if thickness <= 0:
            continue
        seen.add(tag)
        label = str(item.get("label") or "").strip() or tag.replace("_", " ").title()
        material = str(item.get("materialClass") or "").strip() or material_class_for_tag(tag)
        cleaned.append(
            {
                "boardTypeTag": tag,
                "materialClass": material,
                "thicknessMm": round(thickness, 3),
                "label": label,
            }
        )
    if not cleaned:
        cleaned = [dict(rule) for rule in DEFAULT_RULES]
    try:
        tol = float(tolerance_mm if tolerance_mm is not None else DEFAULT_TOLERANCE_MM)
    except Exception:
        tol = DEFAULT_TOLERANCE_MM
    if tol <= 0:
        tol = DEFAULT_TOLERANCE_MM
    return {"rules": cleaned, "toleranceMm": round(tol, 3)}


def measure_body_thickness_mm(body, metadata=None, rules_payload=None):
    """Best-effort panel thickness in mm.

    For rule matching, prefer physical bbox / face dimensions over generator
    ``materialThickness`` so real stock (e.g. 24 mm bunk) is not forced to CPT.
    Face under-reads (~14.5 for CPT 15) still recover via +0.5 when needed.
    """
    report = measure_body_thickness_report(body, metadata, rules_payload=rules_payload)
    return report.get("thicknessMm")


def measure_body_thickness_report(body, metadata=None, rules_payload=None):
    """Return thickness plus source diagnostics for UI / skip reasons.

    When classifying by thickness rules, prefer the **physical** body measure
    (world bbox / face dimensions) over generator ``materialThickness``.
    Otherwise a bunk board that is really 24 mm but still carries CPT=15 in
    designGeometry would always match carcass and never bunk_bed.
    """
    declared = _declared_thickness_mm(metadata)
    design_span = _design_geometry_thickness_mm(metadata)
    bbox_thickness = _bbox_shortest_edge_mm(body)
    dims_thickness = _dimensions_thickness_mm(metadata)

    # Physical first when matching rules; declared/span are design intent only.
    physical = []
    declared_like = []
    if bbox_thickness is not None:
        physical.append((bbox_thickness, "bbox"))
    if dims_thickness is not None:
        physical.append((dims_thickness, "dimensions"))
    if declared is not None:
        declared_like.append((declared, "designGeometry.materialThickness"))
    if design_span is not None:
        declared_like.append((design_span, "designGeometry.span"))

    chosen = None
    source = None

    def _first_matching(candidates):
        for value, label in candidates:
            if match_thickness_rule(value, rules_payload) is not None:
                return value, label + "+rule"
        return None, None

    if rules_payload is not None:
        chosen, source = _first_matching(physical)
        if chosen is None:
            chosen, source = _first_matching(declared_like)

    if chosen is None:
        # No rule match (or no rules): prefer physical bbox, then declared.
        if bbox_thickness is not None:
            if dims_thickness is not None and abs(dims_thickness - bbox_thickness) <= 0.15:
                chosen, source = dims_thickness, "dimensions≈bbox"
            elif (
                dims_thickness is not None
                and bbox_thickness - dims_thickness >= 0.35
                and bbox_thickness - dims_thickness <= 0.6
            ):
                # Classic CPT-0.5 under-read on face dims — keep bbox.
                chosen, source = bbox_thickness, "bbox>dimensions(0.5)"
            else:
                chosen, source = bbox_thickness, "bbox"
        elif dims_thickness is not None:
            chosen, source = dims_thickness, "dimensions"
        elif declared is not None:
            chosen, source = declared, "designGeometry.materialThickness"
        elif design_span is not None:
            chosen, source = design_span, "designGeometry.span"

    # Recovery for known CPT-0.5 under-reads when the raw measure misses rules
    # but +0.5 would hit (e.g. 14.5 → 15 carcass). Only when no better match.
    if chosen is not None and rules_payload is not None:
        if match_thickness_rule(chosen, rules_payload) is None:
            recovered = round(chosen + 0.5, 3)
            if match_thickness_rule(recovered, rules_payload) is not None:
                chosen, source = recovered, (source or "measure") + "+0.5recover"

    return {
        "thicknessMm": chosen,
        "source": source,
        "declaredMm": declared,
        "designSpanMm": design_span,
        "bboxMm": bbox_thickness,
        "dimensionsMm": dims_thickness,
    }


def _as_positive_mm(value):
    try:
        number = float(value)
    except Exception:
        return None
    if number > 0:
        return round(number, 3)
    return None


def _declared_thickness_mm(metadata):
    if not isinstance(metadata, dict):
        return None
    design = metadata.get("designGeometry") if isinstance(metadata.get("designGeometry"), dict) else {}
    for key in ("materialThickness", "thicknessMm", "thickness"):
        number = _as_positive_mm(design.get(key))
        if number is not None:
            return number
    defaults = metadata.get("defaultAttributes") if isinstance(metadata.get("defaultAttributes"), dict) else {}
    for key in ("materialThickness", "thicknessMm", "thickness"):
        number = _as_positive_mm(defaults.get(key))
        if number is not None:
            return number
    identity = metadata.get("identity") if isinstance(metadata.get("identity"), dict) else {}
    for key in ("materialThickness", "thicknessMm", "thickness"):
        number = _as_positive_mm(identity.get(key))
        if number is not None:
            return number
    return None


def _design_geometry_thickness_mm(metadata):
    """Thickness from designGeometry bbox span along thicknessAxis (or min edge)."""
    if not isinstance(metadata, dict):
        return None
    design = metadata.get("designGeometry")
    if not isinstance(design, dict):
        return None
    # Prefer explicit materialThickness already handled elsewhere; here use spans.
    axis = str(design.get("thicknessAxis") or "").strip().upper()
    try:
        x0, x1 = float(design.get("x0")), float(design.get("x1"))
        y0, y1 = float(design.get("y0")), float(design.get("y1"))
        z0, z1 = float(design.get("z0")), float(design.get("z1"))
    except Exception:
        return None
    spans = {
        "X": abs(x1 - x0),
        "Y": abs(y1 - y0),
        "Z": abs(z1 - z0),
    }
    if axis in spans and spans[axis] > 1e-6:
        return round(spans[axis], 3)
    edges = [v for v in spans.values() if v > 1e-6]
    if not edges:
        return None
    return round(min(edges), 3)


def _dimensions_thickness_mm(metadata):
    if not isinstance(metadata, dict):
        return None
    dims = metadata.get("dimensions")
    if not isinstance(dims, dict):
        return None
    for key in ("thicknessMm", "thickness", "t"):
        number = _as_positive_mm(dims.get(key))
        if number is not None:
            return number
    return None


def _bbox_shortest_edge_mm(body):
    if not body:
        return None
    try:
        bbox = body.boundingBox
        if not bbox:
            return None
        dx = abs(bbox.maxPoint.x - bbox.minPoint.x) * 10.0
        dy = abs(bbox.maxPoint.y - bbox.minPoint.y) * 10.0
        dz = abs(bbox.maxPoint.z - bbox.minPoint.z) * 10.0
        edges = [v for v in (dx, dy, dz) if v > 1e-6]
        if not edges:
            return None
        return round(min(edges), 3)
    except Exception:
        return None


def match_thickness_rule(thickness_mm, rules_payload):
    """Return the closest rule within tolerance, or None.

    When multiple board types share the same nominal thickness (e.g. carcass
    and partition both 16 mm), the first configured rule wins. Prefer unique
    thicknesses per type when possible.
    """
    try:
        thickness = float(thickness_mm)
    except Exception:
        return None
    payload = normalize_rules(
        (rules_payload or {}).get("rules") if isinstance(rules_payload, dict) else rules_payload,
        (rules_payload or {}).get("toleranceMm") if isinstance(rules_payload, dict) else None,
    )
    tolerance = float(payload.get("toleranceMm") or DEFAULT_TOLERANCE_MM)
    best = None
    best_delta = None
    for rule in payload.get("rules") or []:
        try:
            nominal = float(rule.get("thicknessMm"))
        except Exception:
            continue
        delta = abs(nominal - thickness)
        if delta > tolerance:
            continue
        if best is None or delta < best_delta:
            best = dict(rule)
            best_delta = delta
    if best is None:
        return None
    best["measuredThicknessMm"] = round(thickness, 3)
    best["deltaMm"] = round(best_delta, 3)
    return best


def _empty_tag(value):
    text = str(value or "").strip().lower()
    return (not text) or ("unknown" in text) or text in ("undefined", "unassigned", "none", "n/a")


def current_board_type_tag(metadata):
    """Best-effort current board-type tag from metadata / derived fields."""
    if not isinstance(metadata, dict):
        return ""
    classification = metadata.get("classification") if isinstance(metadata.get("classification"), dict) else {}
    board_state = classification.get("boardType") if isinstance(classification.get("boardType"), dict) else {}
    canonical = str(board_state.get("value") or "").strip().lower()
    if not _empty_tag(canonical):
        return canonical
    derived = metadata.get("derivedTags") if isinstance(metadata.get("derivedTags"), dict) else {}
    typed = metadata.get("typedTags") if isinstance(metadata.get("typedTags"), dict) else {}
    defaults = metadata.get("defaultAttributes") if isinstance(metadata.get("defaultAttributes"), dict) else {}
    tag = (
        derived.get("boardTypeTag")
        or typed.get("boardTypeTag")
        or ""
    )
    tag = str(tag or "").strip().lower()
    if not _empty_tag(tag):
        return tag
    material = str(defaults.get("materialClass") or "").strip()
    for known_tag, material_class in MATERIAL_FOR_TAG.items():
        if material == material_class:
            return known_tag
    if material.endswith("_board") and len(material) > 6:
        return material[:-6]
    return tag


def has_known_board_type(metadata):
    """True when a real board-type tag is set (built-in or custom). unknown/empty ≠ existing."""
    tag = current_board_type_tag(metadata)
    return not _empty_tag(tag)


def apply_rule_to_metadata(metadata, rule, overwrite=False):
    """Fill board-type fields from a matched thickness rule.

    unknown / empty / undefined do NOT count as an existing board type, so they
    are always filled even when overwrite=False. Overwrite only replaces an
    already-known board type (built-in or custom).
    """
    if not isinstance(rule, dict):
        return metadata, False
    working = dict(metadata) if isinstance(metadata, dict) else {
        "schemaVersion": 1,
        "identity": {},
        "defaultAttributes": {},
        "lifecycle": {"state": "thickness_classified", "reviewRequired": True},
    }
    tag = str(rule.get("boardTypeTag") or "").strip().lower()
    working, result = attribute_state_service.apply_board_type(
        working,
        tag,
        source="thickness",
        lock=False,
        force=bool(overwrite),
    )
    changed = bool(result.get("changed"))
    if result.get("reason") in ("manual_locked", "lower_priority"):
        return metadata, False

    measured = rule.get("measuredThicknessMm")
    if measured is not None:
        dimensions = dict(working.get("dimensions") or {})
        if overwrite or dimensions.get("thicknessMm") in (None, "", 0):
            if dimensions.get("thicknessMm") != float(measured):
                dimensions["thicknessMm"] = float(measured)
                working["dimensions"] = dimensions
                changed = True
            else:
                working["dimensions"] = dimensions

    working["_thicknessRule"] = {
        "boardTypeTag": tag,
        "thicknessMm": rule.get("thicknessMm"),
        "measuredThicknessMm": rule.get("measuredThicknessMm"),
        "deltaMm": rule.get("deltaMm"),
    }
    return working, changed


def load_rules(root_component):
    """Load design rules, else user defaults, else built-in defaults.

    Returns payload with optional ``source``: design | userDefault | builtin.
    """
    if root_component:
        try:
            attr = root_component.attributes.itemByName(RULES_ATTR_GROUP, RULES_ATTR_NAME)
            if attr is not None and attr.value:
                import json

                data = json.loads(attr.value)
                if isinstance(data, dict):
                    payload = normalize_rules(data.get("rules"), data.get("toleranceMm"))
                elif isinstance(data, list):
                    payload = normalize_rules(data)
                else:
                    payload = None
                if payload:
                    payload["source"] = "design"
                    return payload
        except Exception:
            pass

    user = load_user_defaults()
    if user:
        user["source"] = "userDefault"
        return user

    payload = builtin_defaults()
    payload["source"] = "builtin"
    return payload


def save_rules(root_component, rules_payload):
    payload = normalize_rules(
        (rules_payload or {}).get("rules") if isinstance(rules_payload, dict) else rules_payload,
        (rules_payload or {}).get("toleranceMm") if isinstance(rules_payload, dict) else None,
    )
    if not root_component:
        return False, payload
    try:
        import json

        raw = json.dumps(payload, separators=(",", ":"))
        attrs = root_component.attributes
        existing = attrs.itemByName(RULES_ATTR_GROUP, RULES_ATTR_NAME)
        if existing is not None:
            existing.value = raw
        else:
            attrs.add(RULES_ATTR_GROUP, RULES_ATTR_NAME, raw)
        payload["source"] = "design"
        return True, payload
    except Exception:
        return False, payload
