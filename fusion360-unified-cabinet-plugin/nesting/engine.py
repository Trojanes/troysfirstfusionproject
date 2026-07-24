"""Stable CabinetNC nesting API with replaceable engine adapters."""

from __future__ import annotations

import importlib
import os

from nesting import sheet_pack
from nesting.engines import deepnest
from nesting.engines import sparrow


deepnest = importlib.reload(deepnest)
sparrow = importlib.reload(sparrow)

# Default to improved sheet_pack (fast + stable). Deepnest only for small jobs
# when explicitly requested — large true-shape Deepnest runs often time out.
DEFAULT_ENGINE = "sheet_pack"
DEEPNEST_SMALL_JOB_LIMIT = 60


def create_layout(
    items,
    sheet_params,
    origin_x_mm,
    origin_y_mm,
    engine_name=None,
    wait_callback=None,
):
    """Create a layout without exposing an engine's internal data structures.

    Default engine is sheet_pack_hybrid_v3. Deepnest is optional for small jobs
    (``DEEPNEST_SMALL_JOB_LIMIT``); larger Deepnest requests use sheet_pack.
    """
    selected = str(
        engine_name
        or os.environ.get("CABINETNC_NEST_ENGINE")
        or DEFAULT_ENGINE
    ).strip().lower()
    part_count = len(items or [])

    if selected in (
        "sheet_pack",
        "legacy",
        "sheet_pack_poly_v1",
        "sheet_pack_poly_v2",
        "sheet_pack_hybrid_v3",
    ):
        return sheet_pack.sheet_pack_layout(
            items, sheet_params, origin_x_mm, origin_y_mm
        )

    wants_deepnest = selected in (
        "deepnest",
        "deepnest_next",
        deepnest.ENGINE_NAME.lower(),
    )
    if wants_deepnest and part_count > DEEPNEST_SMALL_JOB_LIMIT:
        layout = sheet_pack.sheet_pack_layout(
            items, sheet_params, origin_x_mm, origin_y_mm
        )
        layout["requestedEngine"] = deepnest.ENGINE_NAME
        layout["engineFallback"] = True
        layout["engineFallbackReason"] = (
            "Deepnest skipped for {} parts (limit {}); using {}."
        ).format(part_count, DEEPNEST_SMALL_JOB_LIMIT, sheet_pack.ENGINE_NAME)
        return layout

    if wants_deepnest:
        try:
            return deepnest.layout(
                items,
                sheet_params,
                origin_x_mm,
                origin_y_mm,
                wait_callback=wait_callback,
            )
        except Exception as ex:
            fallback = sheet_pack.sheet_pack_layout(
                items, sheet_params, origin_x_mm, origin_y_mm
            )
            fallback["requestedEngine"] = deepnest.ENGINE_NAME
            fallback["engineFallback"] = True
            fallback["engineFallbackReason"] = str(ex)
            return fallback

    wants_sparrow = selected in (
        "quality",
        "sparrow",
        "sparrow_native",
        sparrow.ENGINE_NAME.lower(),
    )
    if wants_sparrow:
        try:
            return sparrow.layout(
                items,
                sheet_params,
                origin_x_mm,
                origin_y_mm,
                wait_callback=wait_callback,
            )
        except Exception as ex:
            fallback = sheet_pack.sheet_pack_layout(
                items, sheet_params, origin_x_mm, origin_y_mm
            )
            fallback["requestedEngine"] = sparrow.ENGINE_NAME
            fallback["engineFallback"] = True
            fallback["engineFallbackReason"] = str(ex)
            return fallback

    # Unknown engine name → safe default.
    return sheet_pack.sheet_pack_layout(
        items, sheet_params, origin_x_mm, origin_y_mm
    )
