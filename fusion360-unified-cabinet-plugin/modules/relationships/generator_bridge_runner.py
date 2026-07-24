"""Spawn generator bridge scripts and return parsed JSON results."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional


PLUGIN_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = PLUGIN_ROOT.parent
FIXTURE_DIR = PLUGIN_ROOT / "tests" / "fixtures" / "generator_params"


def load_params_fixture(name: str) -> Dict[str, Any]:
    path = FIXTURE_DIR / name
    if not path.exists():
        raise FileNotFoundError("Missing generator params fixture: {}".format(path))
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _run_node(script: Path, payload: Dict[str, Any], cwd: Path) -> Dict[str, Any]:
    proc = subprocess.run(
        ["node", str(script)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=str(cwd),
    )
    if proc.returncode:
        raise RuntimeError((proc.stderr or proc.stdout or "node bridge failed").strip())
    data = json.loads(proc.stdout or "{}")
    if isinstance(data, dict) and data.get("ok") is False:
        errors = data.get("errors") or ["Generator bridge returned ok=false."]
        raise RuntimeError("; ".join(str(item) for item in errors))
    return data if isinstance(data, dict) else {}


def run_general_tall(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = params if params is not None else load_params_fixture("general_tall_base.json")
    data = _run_node(
        PLUGIN_ROOT / "scripts" / "general_tall_from_params.js",
        {"params": payload},
        PLUGIN_ROOT,
    )
    return data.get("result") or {}


def run_overhead(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = params if params is not None else load_params_fixture("overhead_edge_only.json")
    data = _run_node(
        PLUGIN_ROOT / "scripts" / "overhead_from_params.js",
        {"params": payload},
        PLUGIN_ROOT,
    )
    return data.get("result") or {}


def run_kitchen(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = params if params is not None else load_params_fixture("kitchen_base.json")
    data = _run_node(
        PLUGIN_ROOT / "scripts" / "kitchen_from_params.js",
        {"params": payload},
        PLUGIN_ROOT,
    )
    return data.get("result") or {}


def run_lounge(params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    payload = params if params is not None else load_params_fixture("lounge_l_shape.json")
    data = _run_node(
        PLUGIN_ROOT / "scripts" / "lounge_from_params.js",
        {"params": payload},
        PLUGIN_ROOT,
    )
    return data.get("result") or {}


GENERATOR_RUNNERS = {
    "general_tall": run_general_tall,
    "overhead": run_overhead,
    "kitchen": run_kitchen,
    "lounge": run_lounge,
}
