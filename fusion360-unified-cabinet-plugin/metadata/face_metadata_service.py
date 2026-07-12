from face_attribute_store import (
    has_face_metadata,
    read_face_metadata,
    remove_face_metadata,
    update_face_metadata,
    write_face_metadata,
)
from face_entity_resolver import RESOLVE_AMBIGUOUS, RESOLVE_FOUND, RESOLVE_NOT_FOUND, resolve_face
from face_geometry_signature import build_geometry_signature
from face_models import (
    FACE_CLASS_EDGE,
    FACE_CLASS_SURFACE,
    SURFACE_MODE_DOUBLE_SIDED,
    SURFACE_MODE_SINGLE_SIDED,
    create_edge_metadata,
    default_carcass_surface,
    default_double_sided_door_surface,
    default_single_sided_door_door_colour_surface,
    default_single_sided_door_white_stipple_surface,
    generate_face_id,
    merge_panel_face_registry,
    panel_face_registry_fields,
)
from face_validation import validate_face_metadata, validate_unique_face_ids


class FaceMetadataService:
    """Single entry point for face metadata read/write and resolution."""

    def get_face_metadata(self, face, panel_context=None):
        metadata, error = read_face_metadata(face)
        if error:
            return None, error
        if metadata is None:
            return None, None
        validation = validate_face_metadata(metadata, panel_context)
        if validation.get("warnings"):
            metadata = dict(metadata)
            metadata["_diagnostics"] = {"warnings": validation["warnings"]}
        return metadata, None

    def initialize_face_metadata(self, face, panel_id, values, panel_context=None):
        if face is None:
            raise ValueError("Missing face")
        if has_face_metadata(face):
            raise ValueError("Face metadata already exists")

        values = dict(values or {})
        face_id = str(values.get("faceId") or generate_face_id())
        face_class = values.get("faceClass")
        if face_class not in {FACE_CLASS_SURFACE, FACE_CLASS_EDGE}:
            raise ValueError("faceClass must be SURFACE or EDGE")

        geometry_signature = values.get("geometrySignature")
        if geometry_signature is None:
            geometry_signature = build_geometry_signature(face, panel_context)

        metadata = self._build_metadata_from_values(panel_id, face_id, face_class, values, geometry_signature)
        validation = validate_face_metadata(metadata, {"panelId": panel_id, **(panel_context or {})})
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))

        return write_face_metadata(face, metadata)

    def update_face_metadata(self, face, patch, panel_context=None):
        current, error = read_face_metadata(face)
        if error:
            raise ValueError(error)
        if current is None:
            raise ValueError("Face metadata does not exist")

        merged = update_face_metadata(face, patch)
        validation = validate_face_metadata(merged, panel_context)
        if not validation["valid"]:
            raise ValueError("; ".join(validation["errors"]))
        return merged

    def remove_face_metadata(self, face):
        return remove_face_metadata(face)

    def build_geometry_signature(self, face, panel_context=None):
        return build_geometry_signature(face, panel_context)

    def resolve_face(self, panel_context, face_id, face_records):
        return resolve_face(panel_context, face_id, face_records)

    def validate_face_metadata(self, metadata, panel_context=None):
        return validate_face_metadata(metadata, panel_context)

    def validate_face_id_uniqueness(self, face_metadatas):
        return validate_unique_face_ids(face_metadatas)

    def build_panel_face_registry(self, surface_mode, face_ids):
        return panel_face_registry_fields(surface_mode=surface_mode, face_ids=face_ids)

    def merge_panel_face_registry(self, panel_metadata, surface_mode=None, face_ids=None):
        return merge_panel_face_registry(panel_metadata, surface_mode=surface_mode, face_ids=face_ids)

    def initialize_single_sided_door_surfaces(
        self,
        door_colour_face,
        white_stipple_face,
        panel_id,
        door_finish,
        panel_context=None,
        door_face_id=None,
        white_face_id=None,
    ):
        door_signature = build_geometry_signature(door_colour_face, panel_context)
        white_signature = build_geometry_signature(white_stipple_face, panel_context)
        door_metadata = default_single_sided_door_door_colour_surface(
            panel_id,
            door_face_id or generate_face_id(),
            door_finish,
            geometry_signature=door_signature,
        )
        white_metadata = default_single_sided_door_white_stipple_surface(
            panel_id,
            white_face_id or generate_face_id(),
            geometry_signature=white_signature,
        )
        self.initialize_face_metadata(
            door_colour_face,
            panel_id,
            door_metadata,
            panel_context=panel_context,
        )
        self.initialize_face_metadata(
            white_stipple_face,
            panel_id,
            white_metadata,
            panel_context=panel_context,
        )
        registry = self.build_panel_face_registry(
            SURFACE_MODE_SINGLE_SIDED,
            [door_metadata["faceId"], white_metadata["faceId"]],
        )
        return {
            "doorFace": door_metadata,
            "whiteStippleFace": white_metadata,
            "panelRegistry": registry,
        }

    def initialize_double_sided_door_surfaces(
        self,
        surface_faces,
        panel_id,
        door_finish,
        panel_context=None,
        face_ids=None,
    ):
        if not surface_faces or len(surface_faces) < 2:
            raise ValueError("DOUBLE_SIDED door requires two SURFACE faces")

        face_ids = list(face_ids or [])
        created = []
        for index, face in enumerate(surface_faces[:2]):
            face_id = face_ids[index] if index < len(face_ids) else generate_face_id()
            metadata = default_double_sided_door_surface(
                panel_id,
                face_id,
                door_finish,
                geometry_signature=build_geometry_signature(face, panel_context),
            )
            self.initialize_face_metadata(face, panel_id, metadata, panel_context=panel_context)
            created.append(metadata)

        registry = self.build_panel_face_registry(
            SURFACE_MODE_DOUBLE_SIDED,
            [item["faceId"] for item in created],
        )
        return {"surfaceFaces": created, "panelRegistry": registry}

    def initialize_carcass_surfaces(self, surface_faces, panel_id, panel_context=None, finish=None, face_ids=None):
        face_ids = list(face_ids or [])
        created = []
        for index, face in enumerate(surface_faces or []):
            face_id = face_ids[index] if index < len(face_ids) else generate_face_id()
            metadata = default_carcass_surface(
                panel_id,
                face_id,
                finish=finish,
                geometry_signature=build_geometry_signature(face, panel_context),
            )
            self.initialize_face_metadata(face, panel_id, metadata, panel_context=panel_context)
            created.append(metadata)

        registry = self.build_panel_face_registry(
            SURFACE_MODE_DOUBLE_SIDED,
            [item["faceId"] for item in created],
        )
        return {"surfaceFaces": created, "panelRegistry": registry}

    def initialize_edge_face(self, face, panel_id, edge_banding, panel_context=None, face_id=None, finish=None):
        metadata = create_edge_metadata(
            panel_id,
            face_id or generate_face_id(),
            edge_banding,
            geometry_signature=build_geometry_signature(face, panel_context),
            finish=finish,
        )
        return self.initialize_face_metadata(face, panel_id, metadata, panel_context=panel_context)

    def _build_metadata_from_values(self, panel_id, face_id, face_class, values, geometry_signature):
        metadata = {
            "schemaVersion": values.get("schemaVersion", 1),
            "panelId": str(panel_id),
            "faceId": str(face_id),
            "faceClass": face_class,
            "faceRole": str(values.get("faceRole") or "unknown"),
            "millingSurface": values.get("millingSurface"),
            "edgeId": str(values.get("edgeId") or "") or None,
            "edgeGroupId": str(values.get("edgeGroupId") or "") or None,
            "classificationStatus": str(values.get("classificationStatus") or "") or None,
            "logicalEdgeMemberIndex": values.get("logicalEdgeMemberIndex"),
            "finish": dict(values.get("finish") or {}),
            "machiningPermission": values.get("machiningPermission"),
            "edgeBanding": values.get("edgeBanding"),
            "geometrySignature": dict(geometry_signature or {}),
        }
        if face_class == FACE_CLASS_SURFACE:
            metadata["edgeBanding"] = None
        if face_class == FACE_CLASS_EDGE and metadata.get("edgeBanding") is None:
            metadata["edgeBanding"] = create_edge_metadata(panel_id, face_id, None)["edgeBanding"]
        return metadata


__all__ = [
    "FaceMetadataService",
    "RESOLVE_AMBIGUOUS",
    "RESOLVE_FOUND",
    "RESOLVE_NOT_FOUND",
]
