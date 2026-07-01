import importlib.util
import os

import adsk.core
import adsk.fusion

from geometry_ops import MODEL_Z_OFFSET_MM, offset_matching_bodies_z_mm


_SOURCE_PATH = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "..",
        "Fridge Cabinet Generator",
        "fridge_flat_board_geometry.py",
    )
)

_spec = importlib.util.spec_from_file_location("_ucp_source_fridge_flat_board_geometry", _SOURCE_PATH)
_source = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_source)
_source.ATTRIBUTE_GROUP = "UnifiedCabinetPlugin"
_source.FEATURE_PREFIX = "FRIDGE_"

GEOMETRY_BUILD = "unified-wrapper-" + getattr(_source, "GEOMETRY_BUILD", "unknown")


def generate_flat_board_bodies(board_plan, spacing_mm=100.0, preview_mode=None):
    result = _source.generate_flat_board_bodies(board_plan, spacing_mm=spacing_mm, preview_mode=preview_mode)
    if isinstance(result, dict):
        result["geometryBuild"] = GEOMETRY_BUILD
        result.setdefault("warnings", []).append("Generated via Unified Cabinet Plugin fridge wrapper.")
        try:
            existing_offset = result.get("modelZOffset") if isinstance(result.get("modelZOffset"), dict) else {}
            if existing_offset.get("mode") == "componentAtModelZ":
                result["modelZOffset"] = existing_offset
            else:
                app = adsk.core.Application.get()
                design = adsk.fusion.Design.cast(app.activeProduct) if app and app.activeProduct else None
                root = design.rootComponent if design else None
                if root:
                    result["modelZOffset"] = offset_matching_bodies_z_mm(
                        root,
                        name_prefixes=["FRIDGE_"],
                        module="fridge",
                        dz_mm=MODEL_Z_OFFSET_MM,
                        feature_prefix="FRIDGE_MODEL_Z_OFFSET_",
                    )
        except Exception as ex:
            result.setdefault("warnings", []).append("Fridge model Z offset failed: {}".format(ex))
    return result
