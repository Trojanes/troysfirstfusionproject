import json

from face_models import FACE_ATTRIBUTE_GROUP, FACE_PAYLOAD_ATTR


def has_face_metadata(face):
    if not face:
        return False
    try:
        attrs = face.attributes
        attr = attrs.itemByName(FACE_ATTRIBUTE_GROUP, FACE_PAYLOAD_ATTR) if attrs else None
        # A deleted attribute can linger as an object with an empty value;
        # only a non-empty payload counts as metadata.
        return bool(attr and str(getattr(attr, "value", "") or "").strip())
    except Exception:
        return False


def read_face_metadata(face):
    if not face:
        return None, "Missing face"
    try:
        attrs = face.attributes
        attr = attrs.itemByName(FACE_ATTRIBUTE_GROUP, FACE_PAYLOAD_ATTR) if attrs else None
        if not attr:
            return None, None
        raw = str(attr.value or "").strip()
        if not raw:
            return None, "Empty face metadata attribute"
        return json.loads(raw), None
    except json.JSONDecodeError as ex:
        return None, "Invalid face metadata JSON: {}".format(ex)
    except Exception as ex:
        return None, str(ex)


def write_face_metadata(face, metadata):
    if not face:
        raise ValueError("Missing face")
    payload = json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))
    attrs = face.attributes
    existing = attrs.itemByName(FACE_ATTRIBUTE_GROUP, FACE_PAYLOAD_ATTR) if attrs else None
    if existing:
        existing.value = payload
    else:
        attrs.add(FACE_ATTRIBUTE_GROUP, FACE_PAYLOAD_ATTR, payload)
    return metadata


def update_face_metadata(face, patch):
    current, error = read_face_metadata(face)
    if error:
        raise ValueError(error)
    if current is None:
        raise ValueError("Face metadata does not exist")
    merged = dict(current)
    for key, value in (patch or {}).items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            nested = dict(merged[key])
            nested.update(value)
            merged[key] = nested
        else:
            merged[key] = value
    return write_face_metadata(face, merged)


def remove_face_metadata(face):
    if not face:
        return False
    try:
        attrs = face.attributes
        attr = attrs.itemByName(FACE_ATTRIBUTE_GROUP, FACE_PAYLOAD_ATTR) if attrs else None
        if not attr:
            return False
        attr.deleteMe()
        return True
    except Exception:
        return False
