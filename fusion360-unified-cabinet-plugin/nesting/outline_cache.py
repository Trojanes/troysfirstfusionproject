"""Persistent nesting flat-outline cache on panel body metadata.

Build Nesting Outlines writes ``nestingFlatOutline`` after a true flatten+extract.
Create Layout reuses it only when the geometry signature and options still match.
"""

from __future__ import annotations

import hashlib
import time

CACHE_KEY = "nestingFlatOutline"
CACHE_SCHEMA = 2


def _num(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return float(default)


def native_brep_entity(entity):
    """Prefer native BRep for attributes/signatures.

    Occurrence proxies use world-space bounds and sometimes hide body
    attributes written on the native entity (and vice versa). Signature and
    metadata freshness must stay on the native object.
    """
    if entity is None:
        return None
    try:
        native = getattr(entity, "nativeObject", None)
        if native is not None:
            return native
    except Exception:
        pass
    return entity


def attribute_entities(entity):
    """Yield proxy then native so attribute reads/writes can try both."""
    seen = set()
    for candidate in (entity, native_brep_entity(entity)):
        if candidate is None:
            continue
        key = id(candidate)
        if key in seen:
            continue
        seen.add(key)
        yield candidate


def body_geometry_signature(body, detail=False):
    """Geometry change detector.

    ``detail=True`` adds sorted per-face area/bounds descriptors. Lay Flat
    manufacturing analysis uses this because volume/topology/bbox alone cannot
    detect a same-size hole moving inside an otherwise unchanged panel.
    """
    body = native_brep_entity(body)
    volume = 0.0
    face_count = 0
    edge_count = 0
    box = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    try:
        volume = float(body.volume)
    except Exception:
        pass
    try:
        face_count = int(body.faces.count)
    except Exception:
        pass
    try:
        edge_count = int(body.edges.count)
    except Exception:
        pass
    try:
        bounds = body.boundingBox
        box = (
            float(bounds.minPoint.x),
            float(bounds.minPoint.y),
            float(bounds.minPoint.z),
            float(bounds.maxPoint.x),
            float(bounds.maxPoint.y),
            float(bounds.maxPoint.z),
        )
    except Exception:
        pass
    base = "v{:.6f}|f{}|e{}|b{:.4f},{:.4f},{:.4f},{:.4f},{:.4f},{:.4f}".format(
        volume,
        face_count,
        edge_count,
        box[0],
        box[1],
        box[2],
        box[3],
        box[4],
        box[5],
    )
    if not detail:
        return base

    faces = []
    try:
        count = int(body.faces.count or 0)
    except Exception:
        count = 0
    for index in range(count):
        try:
            face = body.faces.item(index)
            area = float(getattr(face, "area", 0.0) or 0.0)
            bounds = face.boundingBox
            geometry = getattr(face, "geometry", None)
            object_type = str(getattr(geometry, "objectType", "") or "")
            edges = int(getattr(getattr(face, "edges", None), "count", 0) or 0)
            descriptor = (
                object_type,
                round(area, 7),
                edges,
                round(float(bounds.minPoint.x), 5),
                round(float(bounds.minPoint.y), 5),
                round(float(bounds.minPoint.z), 5),
                round(float(bounds.maxPoint.x), 5),
                round(float(bounds.maxPoint.y), 5),
                round(float(bounds.maxPoint.z), 5),
            )
            faces.append(repr(descriptor))
        except Exception:
            continue
    faces.sort()
    digest = hashlib.sha256("|".join(faces).encode("utf-8")).hexdigest()[:24]
    return "{}|fh{}".format(base, digest)


def get_cached_outline(metadata):
    meta = metadata if isinstance(metadata, dict) else {}
    cached = meta.get(CACHE_KEY)
    return cached if isinstance(cached, dict) else None


def build_cache_record(
    outline,
    dimensions,
    geometry_signature,
    cutting_face,
    allow_parts_in_part=False,
    reflected_source=False,
):
    dims = dimensions if isinstance(dimensions, dict) else {}
    reflected = bool(reflected_source)
    if isinstance(outline, dict) and "reflectedSource" in outline:
        reflected = bool(outline.get("reflectedSource"))
    payload = {
        "schemaVersion": CACHE_SCHEMA,
        "geometrySignature": str(geometry_signature or ""),
        "cuttingFace": str(cutting_face or "").strip().upper(),
        "allowPartsInPart": bool(allow_parts_in_part),
        "reflectedSource": reflected,
        "widthMm": round(_num(dims.get("widthMm")), 3),
        "depthMm": round(_num(dims.get("depthMm")), 3),
        "builtAtMs": int(time.time() * 1000),
        "outline": outline if isinstance(outline, dict) else None,
    }
    if isinstance(outline, dict):
        payload["source"] = str(outline.get("source") or "")
        payload["pointCount"] = int(outline.get("pointCount") or 0)
        payload["holeCount"] = int(outline.get("holeCount") or 0)
    return payload


def outline_cache_status(
    metadata,
    geometry_signature,
    cutting_face,
    allow_parts_in_part=False,
    reflected_source=None,
):
    """Return ``fresh``, ``stale``, ``missing``, or ``invalid``."""
    cached = get_cached_outline(metadata)
    if not cached:
        return "missing"
    outline = cached.get("outline")
    if not isinstance(outline, dict) or not outline.get("points"):
        return "invalid"
    if int(cached.get("schemaVersion") or 0) != CACHE_SCHEMA:
        return "stale"
    if str(cached.get("geometrySignature") or "") != str(geometry_signature or ""):
        return "stale"
    if str(cached.get("cuttingFace") or "").strip().upper() != str(
        cutting_face or ""
    ).strip().upper():
        return "stale"
    if bool(cached.get("allowPartsInPart")) != bool(allow_parts_in_part):
        return "stale"
    if reflected_source is not None:
        cached_reflected = bool(cached.get("reflectedSource"))
        if "reflectedSource" in (outline or {}):
            cached_reflected = bool(outline.get("reflectedSource"))
        if cached_reflected != bool(reflected_source):
            return "stale"
    width = _num(cached.get("widthMm"))
    depth = _num(cached.get("depthMm"))
    if width <= 0.0 or depth <= 0.0:
        return "invalid"
    return "fresh"


def cached_outline_for_prepare(
    metadata,
    geometry_signature,
    cutting_face,
    allow_parts_in_part=False,
    reflected_source=None,
):
    """Return (outline, dimensions) when cache is fresh, else (None, None)."""
    if (
        outline_cache_status(
            metadata,
            geometry_signature,
            cutting_face,
            allow_parts_in_part,
            reflected_source=reflected_source,
        )
        != "fresh"
    ):
        return None, None
    cached = get_cached_outline(metadata)
    outline = dict(cached.get("outline") or {})
    outline["reflectedSource"] = bool(
        cached.get("reflectedSource")
        if "reflectedSource" in cached
        else outline.get("reflectedSource")
    )
    dimensions = {
        "widthMm": _num(cached.get("widthMm")),
        "depthMm": _num(cached.get("depthMm")),
    }
    return outline, dimensions
