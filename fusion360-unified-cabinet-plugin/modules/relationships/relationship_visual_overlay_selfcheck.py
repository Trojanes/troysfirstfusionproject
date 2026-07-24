"""Preflight checks for M4.6A relationship visual overlay (offline + Fusion)."""

from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

REL_DIR = Path(__file__).resolve().parent

OVERLAY_IMPL_VERSION = "2026-07-03-custom-graphics-v3"
EXPECTED_OVERLAY_FUSION_BUILD = OVERLAY_IMPL_VERSION

PURE_MODULE = "relationship_visual_overlay"
FUSION_MODULE = "relationship_visual_overlay_fusion"

FORBIDDEN_FUSION_MARKERS = (
    "_create_plane_for_segment",
    "setByThreePoints",
    "setByNormalAndPoint",
    "constructionPlanes.createInput",
    "constructionPlanes.add(",
    "CustomGraphicsLines.create",
    "CustomGraphicsMeshColorEffect",
)

REQUIRED_FUSION_MARKERS = (
    "OVERLAY_FUSION_BUILD",
    "CustomGraphicsCoordinates.create",
    "addLines(coords",
    "root.xYConstructionPlane",
    "_create_custom_graphics_line",
    "ensure_distinct_overlay_endpoints_mm",
)


def _check(name: str, passed: bool, detail: str = "") -> Dict[str, Any]:
    return {"name": name, "ok": bool(passed), "detail": detail}


def _read_source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_overlay_source_files() -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    checks: List[Dict[str, Any]] = []
    errors: List[str] = []

    fusion_path = REL_DIR / "{}.py".format(FUSION_MODULE)
    pure_path = REL_DIR / "{}.py".format(PURE_MODULE)

    for path in (fusion_path, pure_path):
        if not path.is_file():
            errors.append("Missing overlay source file: {}".format(path))
            checks.append(_check("source_exists:{}".format(path.name), False, "file not found"))
            continue
        checks.append(_check("source_exists:{}".format(path.name), True, str(path)))

    if errors:
        return False, checks, errors

    fusion_source = _read_source(fusion_path)
    pure_source = _read_source(pure_path)

    for marker in FORBIDDEN_FUSION_MARKERS:
        found = marker in fusion_source
        checks.append(_check("forbidden:{}".format(marker), not found, "found" if found else "absent"))
        if found:
            errors.append("Forbidden stale overlay marker in {}: {}".format(fusion_path.name, marker))

    for marker in REQUIRED_FUSION_MARKERS:
        found = marker in fusion_source
        checks.append(_check("required:{}".format(marker), found, "present" if found else "missing"))
        if not found:
            errors.append("Required overlay marker missing in {}: {}".format(fusion_path.name, marker))

    build_match = re.search(r'OVERLAY_FUSION_BUILD\s*=\s*"([^"]+)"', fusion_source)
    build_value = build_match.group(1) if build_match else None
    build_ok = build_value == EXPECTED_OVERLAY_FUSION_BUILD
    checks.append(
        _check(
            "fusion_build_constant",
            build_ok,
            "expected={} actual={}".format(EXPECTED_OVERLAY_FUSION_BUILD, build_value),
        )
    )
    if not build_ok:
        errors.append(
            "Overlay fusion build mismatch: expected {}, found {}".format(
                EXPECTED_OVERLAY_FUSION_BUILD,
                build_value,
            )
        )

    if "OVERLAY_CUSTOM_GRAPHICS_PREFIX" not in pure_source:
        errors.append("Pure overlay module missing OVERLAY_CUSTOM_GRAPHICS_PREFIX.")
        checks.append(_check("pure_custom_graphics_prefix", False, "missing"))
    else:
        checks.append(_check("pure_custom_graphics_prefix", True, "present"))

    return not errors, checks, errors


def _ensure_rel_dir_on_path() -> None:
    rel_dir = str(REL_DIR)
    if rel_dir not in sys.path:
        sys.path.insert(0, rel_dir)


def check_loaded_overlay_modules(force_reload: bool = True) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    checks: List[Dict[str, Any]] = []
    errors: List[str] = []
    _ensure_rel_dir_on_path()

    for name in list(sys.modules.keys()):
        if "relationship_visual_overlay" in name:
            del sys.modules[name]

    pure = importlib.import_module(PURE_MODULE)
    fusion = importlib.import_module(FUSION_MODULE)
    if force_reload:
        pure = importlib.reload(pure)
        fusion = importlib.reload(fusion)

    build = getattr(fusion, "OVERLAY_FUSION_BUILD", None)
    build_ok = build == EXPECTED_OVERLAY_FUSION_BUILD
    checks.append(
        _check(
            "loaded_fusion_build",
            build_ok,
            "module={} build={}".format(getattr(fusion, "__file__", FUSION_MODULE), build),
        )
    )
    if not build_ok:
        errors.append("Loaded fusion overlay module build is stale: {}".format(build))

    has_forbidden = hasattr(fusion, "_create_plane_for_segment")
    checks.append(_check("loaded_no_create_plane_helper", not has_forbidden, "has helper={}".format(has_forbidden)))
    if has_forbidden:
        errors.append("Loaded fusion overlay module still exposes _create_plane_for_segment (stale cache).")

    has_cg = hasattr(fusion, "_create_custom_graphics_line")
    checks.append(_check("loaded_custom_graphics_helper", has_cg, "present={}".format(has_cg)))
    if not has_cg:
        errors.append("Loaded fusion overlay module missing _create_custom_graphics_line.")

    label = pure.build_overlay_label_text(
        {
            "relationshipType": "structural_butt_joint",
            "geometryType": "edge_to_surface",
            "verification": {"level": "bbox_candidate", "safeForCut": False},
        }
    )
    label_ok = all(token in label for token in ("structural_butt_joint", "edge_to_surface", "bbox_candidate", "safeForCut=false"))
    checks.append(_check("pure_label_text", label_ok, label.replace("\n", " | ")))
    if not label_ok:
        errors.append("Overlay label text preflight failed.")

    return not errors, checks, errors


def run_overlay_selfcheck(force_reload: bool = True) -> Dict[str, Any]:
    source_ok, source_checks, source_errors = check_overlay_source_files()
    module_ok, module_checks, module_errors = check_loaded_overlay_modules(force_reload=force_reload)
    checks = source_checks + module_checks
    errors = source_errors + module_errors
    return {
        "ok": source_ok and module_ok,
        "implVersion": OVERLAY_IMPL_VERSION,
        "expectedFusionBuild": EXPECTED_OVERLAY_FUSION_BUILD,
        "checks": checks,
        "errors": errors,
        "hint": (
            "If Fusion still reports _create_plane_for_segment, restart Fusion or stop/start CabinetNC "
            "to clear stale Python modules before testing Show Relationship Overlay."
        ),
    }


def load_overlay_fusion_module(force_reload: bool = True):
    """Reload overlay modules and fail fast if preflight does not pass."""
    preflight = run_overlay_selfcheck(force_reload=force_reload)
    if not preflight.get("ok"):
        return None, preflight
    _ensure_rel_dir_on_path()
    fusion = importlib.import_module(FUSION_MODULE)
    if force_reload:
        fusion = importlib.reload(fusion)
    return fusion, preflight
