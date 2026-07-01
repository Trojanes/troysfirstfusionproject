from face_geometry_signature import build_geometry_signature, signature_match_score, signatures_match


RESOLVE_FOUND = "FOUND"
RESOLVE_NOT_FOUND = "NOT_FOUND"
RESOLVE_AMBIGUOUS = "AMBIGUOUS"


def _entity_token(face):
    try:
        token = getattr(face, "entityToken", None)
        return str(token) if token else ""
    except Exception:
        return ""


def _iter_body_faces(body):
    if body is None:
        return []
    faces = []
    try:
        for index in range(body.faces.count):
            faces.append(body.faces.item(index))
    except Exception:
        pass
    return faces


def resolve_face_by_token(faces, token):
    if not token:
        return RESOLVE_NOT_FOUND, None
    matches = []
    for face in faces or []:
        if _entity_token(face) == str(token):
            matches.append(face)
    if not matches:
        return RESOLVE_NOT_FOUND, None
    if len(matches) > 1:
        return RESOLVE_AMBIGUOUS, None
    return RESOLVE_FOUND, matches[0]


def resolve_face_by_signature(faces, stored_metadata, panel_context=None):
    stored_signature = (stored_metadata or {}).get("geometrySignature")
    if not stored_signature:
        return RESOLVE_NOT_FOUND, None, ["Missing geometry signature"]

    scored = []
    diagnostics = []
    for face in faces or []:
        candidate_signature = build_geometry_signature(face, panel_context)
        score = signature_match_score(stored_signature, candidate_signature)
        if signatures_match(stored_signature, candidate_signature):
            scored.append((score, face))

    if not scored:
        diagnostics.append("No face matched stored geometry signature")
        return RESOLVE_NOT_FOUND, None, diagnostics

    scored.sort(key=lambda item: item[0], reverse=True)
    best_score = scored[0][0]
    best_faces = [face for score, face in scored if abs(score - best_score) < 1e-6]
    if len(best_faces) > 1:
        diagnostics.append("Multiple faces matched geometry signature")
        return RESOLVE_AMBIGUOUS, None, diagnostics
    return RESOLVE_FOUND, best_faces[0], diagnostics


def resolve_face(panel_context, face_id, face_records):
    records = [record for record in (face_records or []) if str(record.get("faceId")) == str(face_id)]
    if not records:
        return RESOLVE_NOT_FOUND, None, ["Unknown faceId"]
    if len(records) > 1:
        return RESOLVE_AMBIGUOUS, None, ["Duplicate faceId in registry"]

    stored_metadata = records[0].get("metadata") or records[0]
    body = (panel_context or {}).get("body")
    faces = _iter_body_faces(body)

    token = stored_metadata.get("entityToken") or records[0].get("entityToken")
    status, face = resolve_face_by_token(faces, token)
    if status == RESOLVE_FOUND:
        return status, face, []
    if status == RESOLVE_AMBIGUOUS:
        return status, None, ["Multiple faces share the same entity token"]

    return resolve_face_by_signature(faces, stored_metadata, panel_context)
