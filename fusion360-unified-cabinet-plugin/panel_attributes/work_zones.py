"""Work zones: generation / assembly / nesting areas on the XY plane.

Dual-track instance identification:

* PRIMARY - explicit attributes stamped at creation time
  (``UnifiedCabinet/instanceRole`` = generated | nested). Attribute checks are
  deterministic and survive any move.
* SECONDARY - positional zones (this module). The assembly zone sits at the
  origin; the generation zone sits at +X and the nesting zone at +Y, each
  separated by a fixed gap. Zones are used for scan filtering, placement
  targets and cross-check warnings.

Layout rules (agreed):
- Assembly zone centred at the origin, size set by the user.
- Generation zone: +X of the assembly zone, 1 m gap, same size.
- Nesting zone: +Y of the assembly zone, 1 m gap; its size may grow with
  nesting output (extend in X+/- and Y+ only) and must never overlap the
  other zones.
"""

import json

ZONE_ASSEMBLY = "assembly"
ZONE_GENERATION = "generation"
ZONE_NESTING = "nesting"
ZONE_NONE = "unzoned"

ZONE_GAP_MM = 1000.0

ZONE_LAYOUT_ATTR_GROUP = "UnifiedCabinet"
ZONE_LAYOUT_ATTR_NAME = "workZoneLayout"

INSTANCE_ROLE_ATTR_GROUP = "UnifiedCabinet"
INSTANCE_ROLE_ATTR_NAME = "instanceRole"
INSTANCE_ROLE_GENERATED = "generated"
INSTANCE_ROLE_NESTED = "nested"
SYSTEM_ROLE_NESTING_WORKPIECE = "nestingWorkpiece"

WORK_ZONE_MARKER_GROUP = "UnifiedCabinet"
WORK_ZONE_MARKER_NAME = "systemRole"
WORK_ZONE_MARKER_VALUE = "workZone"


# ---------------------------------------------------------------------------
# Pure layout math (unit tested)
# ---------------------------------------------------------------------------

def compute_zone_layout(assembly_width_mm, assembly_depth_mm,
                        nesting_width_mm=None, nesting_depth_mm=None,
                        gap_mm=ZONE_GAP_MM,
                        generation_width_mm=None, generation_depth_mm=None):
    """Compute the three zone rectangles from the zone size specs.

    Returns {zoneId: {"x0","x1","y0","y1"}} in mm, world XY. The generation
    zone sits at +X (own size, defaults to the assembly size, vertically
    centred on y=0); the nesting zone sits at +Y (own size, defaults to the
    assembly size) and its growth only extends X+/- and Y+ so it can never
    reach the other zones.
    """
    aw = max(float(assembly_width_mm or 0.0), 1.0)
    ad = max(float(assembly_depth_mm or 0.0), 1.0)
    gw = max(float(generation_width_mm or aw), 1.0)
    gd = max(float(generation_depth_mm or ad), 1.0)
    nw = max(float(nesting_width_mm or aw), 1.0)
    nd = max(float(nesting_depth_mm or ad), 1.0)
    gap = max(float(gap_mm or 0.0), 0.0)

    assembly = {"x0": -aw / 2.0, "x1": aw / 2.0, "y0": -ad / 2.0, "y1": ad / 2.0}
    # Generation zone: left edge anchored 1 gap right of the assembly zone
    # (width grows +X only); TOP edge anchored to the assembly top so depth
    # grows -Y only. This keeps generation.y1 <= assembly.y1, so resizing the
    # generation zone can never push the nesting zone around.
    generation = {
        "x0": assembly["x1"] + gap,
        "x1": assembly["x1"] + gap + gw,
        "y0": assembly["y1"] - gd,
        "y1": assembly["y1"],
    }
    # Nesting zone: anchored 1 gap above the TALLEST of the two lower zones so
    # X+/- growth can never overlap the generation zone. With the top-aligned
    # generation rule this base depends on the assembly zone only.
    base_y = max(assembly["y1"], generation["y1"]) + gap
    nesting = {
        "x0": -nw / 2.0,
        "x1": nw / 2.0,
        "y0": base_y,
        "y1": base_y + nd,
    }
    return {
        ZONE_ASSEMBLY: assembly,
        ZONE_GENERATION: generation,
        ZONE_NESTING: nesting,
        "gapMm": gap,
    }


def zones_overlap(layout):
    """True when any two zone rectangles overlap (should never happen)."""
    rects = [layout.get(zone) for zone in (ZONE_ASSEMBLY, ZONE_GENERATION, ZONE_NESTING)]
    rects = [r for r in rects if isinstance(r, dict)]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            if a["x0"] < b["x1"] and b["x0"] < a["x1"] and a["y0"] < b["y1"] and b["y0"] < a["y1"]:
                return True
    return False


def zone_of_point(layout, x_mm, y_mm):
    """Classify a world XY point into a zone id (or ZONE_NONE)."""
    if not isinstance(layout, dict):
        return ZONE_NONE
    for zone_id in (ZONE_ASSEMBLY, ZONE_GENERATION, ZONE_NESTING):
        rect = layout.get(zone_id)
        if not isinstance(rect, dict):
            continue
        if rect["x0"] <= x_mm <= rect["x1"] and rect["y0"] <= y_mm <= rect["y1"]:
            return zone_id
    return ZONE_NONE


def rect_size(rect):
    if not isinstance(rect, dict):
        return (None, None)
    width = rect.get("x1", 0.0) - rect.get("x0", 0.0)
    depth = rect.get("y1", 0.0) - rect.get("y0", 0.0)
    return (width or None, depth or None)


def grow_nesting_zone(layout, required_width_mm, required_depth_mm):
    """Return a new layout whose nesting zone covers the required area.

    Growth only extends X+/- (symmetric) and Y+ per the agreed rule; the other
    zones keep their sizes.
    """
    current_w, current_d = rect_size(layout.get(ZONE_NESTING))
    new_w = max(current_w or 0.0, float(required_width_mm or 0.0))
    new_d = max(current_d or 0.0, float(required_depth_mm or 0.0))
    aw, ad = rect_size(layout.get(ZONE_ASSEMBLY))
    gw, gd = rect_size(layout.get(ZONE_GENERATION))
    return compute_zone_layout(
        aw, ad, new_w, new_d, layout.get("gapMm", ZONE_GAP_MM), gw, gd
    )


# ---------------------------------------------------------------------------
# Fusion persistence + body classification (defensive)
# ---------------------------------------------------------------------------

def save_zone_layout(root_component, layout):
    try:
        payload = json.dumps(layout, separators=(",", ":"))
        attrs = root_component.attributes
        existing = attrs.itemByName(ZONE_LAYOUT_ATTR_GROUP, ZONE_LAYOUT_ATTR_NAME)
        if existing is not None:
            existing.value = payload
        else:
            attrs.add(ZONE_LAYOUT_ATTR_GROUP, ZONE_LAYOUT_ATTR_NAME, payload)
        return True
    except Exception:
        return False


def load_zone_layout(root_component):
    try:
        attr = root_component.attributes.itemByName(ZONE_LAYOUT_ATTR_GROUP, ZONE_LAYOUT_ATTR_NAME)
        if attr is None or not attr.value:
            return None
        layout = json.loads(attr.value)
        return layout if isinstance(layout, dict) else None
    except Exception:
        return None


def _body_world_center_mm(body):
    """Best-effort world-space bounding-box centre in mm."""
    try:
        bbox = body.boundingBox
        cx = (bbox.minPoint.x + bbox.maxPoint.x) / 2.0
        cy = (bbox.minPoint.y + bbox.maxPoint.y) / 2.0
        cz = (bbox.minPoint.z + bbox.maxPoint.z) / 2.0
    except Exception:
        return None
    # Proxy bodies (createForAssemblyContext) already expose world-space
    # geometry. Applying assemblyContext.transform again would double-shift.
    is_proxy = False
    try:
        is_proxy = bool(getattr(body, "isProxy", False))
    except Exception:
        is_proxy = False
    if not is_proxy:
        try:
            assembly_context = getattr(body, "assemblyContext", None)
            transform = assembly_context.transform if assembly_context else None
            if transform is not None:
                import adsk.core  # noqa: PLC0415

                point = adsk.core.Point3D.create(cx, cy, cz)
                point.transformBy(transform)
                cx, cy = point.x, point.y
        except Exception:
            pass
    return (cx * 10.0, cy * 10.0)


def generation_zone_center_mm(root_component):
    """World XY centre of the generation zone from the saved layout (or None)."""
    layout = load_zone_layout(root_component)
    if not isinstance(layout, dict):
        return None
    rect = layout.get(ZONE_GENERATION)
    if not isinstance(rect, dict):
        return None
    try:
        return (
            (float(rect["x0"]) + float(rect["x1"])) / 2.0,
            (float(rect["y0"]) + float(rect["y1"])) / 2.0,
        )
    except Exception:
        return None


def generation_zone_origin_mm(root_component):
    """World XY min corner (x0, y0) of the generation zone from the saved layout."""
    layout = load_zone_layout(root_component)
    if not isinstance(layout, dict):
        return None
    rect = layout.get(ZONE_GENERATION)
    if not isinstance(rect, dict):
        return None
    try:
        return (float(rect["x0"]), float(rect["y0"]))
    except Exception:
        return None


def resolve_origin_from_payload(payload, root_component):
    """Origin for generator output: explicit payload values win; otherwise the
    generation-zone centre (when work zones exist); otherwise (0, 0)."""
    data = payload if isinstance(payload, dict) else {}
    has_explicit = data.get("originXMm") is not None or data.get("originYMm") is not None
    if not has_explicit:
        center = generation_zone_center_mm(root_component) if root_component is not None else None
        if center:
            return center
        return (0.0, 0.0)

    def _num(key):
        try:
            return float(data.get(key) or 0.0)
        except Exception:
            return 0.0

    return (_num("originXMm"), _num("originYMm"))


def zone_of_body(body, layout):
    if not isinstance(layout, dict):
        return ZONE_NONE
    center = _body_world_center_mm(body)
    if center is None:
        return ZONE_NONE
    return zone_of_point(layout, center[0], center[1])


def instance_role_of_body(body):
    try:
        attr = body.attributes.itemByName(INSTANCE_ROLE_ATTR_GROUP, INSTANCE_ROLE_ATTR_NAME)
        return str(attr.value) if attr and attr.value else ""
    except Exception:
        return ""


def is_nested_instance(body):
    if instance_role_of_body(body) == INSTANCE_ROLE_NESTED:
        return True
    try:
        attr = body.attributes.itemByName(
            WORK_ZONE_MARKER_GROUP, WORK_ZONE_MARKER_NAME
        )
        return bool(
            attr
            and str(attr.value or "") == SYSTEM_ROLE_NESTING_WORKPIECE
        )
    except Exception:
        return False


def mark_instance_role(body, role):
    try:
        attrs = body.attributes
        existing = attrs.itemByName(INSTANCE_ROLE_ATTR_GROUP, INSTANCE_ROLE_ATTR_NAME)
        if existing is not None:
            existing.value = str(role)
        else:
            attrs.add(INSTANCE_ROLE_ATTR_GROUP, INSTANCE_ROLE_ATTR_NAME, str(role))
        return True
    except Exception:
        return False
