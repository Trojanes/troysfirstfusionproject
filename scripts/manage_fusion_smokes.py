#!/usr/bin/env python3
"""Install or remove temporary Connect smoke scripts in Fusion Scripts and Add-ins.

Fusion must be closed before install/remove, then restarted so the combined
Scripts and Add-ins dialog (Shift+S) shows only the active smoke entry.

Usage:
  python scripts/manage_fusion_smokes.py install --day 2
  python scripts/manage_fusion_smokes.py remove --passed day1
  python scripts/manage_fusion_smokes.py remove --names day2_connect_smoke
  python scripts/manage_fusion_smokes.py cleanup-legacy
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable, List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
PLUGIN_DIR = REPO_ROOT / "fusion360-unified-cabinet-plugin"
FUSION_ROAMING = Path(os.environ.get("APPDATA", "")) / "Autodesk" / "Autodesk Fusion 360"
SCRIPTS_DIR = FUSION_ROAMING / "API" / "Scripts"
INFO_DIR = FUSION_ROAMING / "WH9C79ZD58AKJL7X"
INFO_PATH = INFO_DIR / "JSLoadedScriptsinfo"

# Historical one-off smokes — always safe to purge from Fusion deployment.
LEGACY_SMOKE_NAMES = (
    "connect_pipeline_smoke",
    "smoke_connect_helpers",
    "contact_patch_smoke",
    "m4_fusion_smoke",
    "m5_connect_smoke",
    "m6_connect_smoke",
    "m7_connect_smoke",
)

DAY_SMOKE = {
    1: "day1_connect_smoke",
    2: "day2_connect_smoke",
}

BATCH_SMOKE = {
    "main": "connect_main_flow_smoke",
    "c": "connect_batch_c_smoke",
    "tg": "tongue_groove_connect_smoke",
    "hinge": "hinge_hole_connect_smoke",
    "runner": "drawer_runner_hole_connect_smoke",
    "lock": "lock_cutout_connect_smoke",
    "generic": "generic_hardware_connect_smoke",
    "realhw": "real_cabinet_hardware_connect_smoke",
    "verifyall": "verify_all_connect_smoke",
    "declared": "declared_generators_connect_smoke",
}

ALL_TEMPORARY_SMOKES = list(DAY_SMOKE.values()) + list(BATCH_SMOKE.values())


def _info_path() -> Path:
    if INFO_PATH.is_file():
        return INFO_PATH
    matches = sorted(FUSION_ROAMING.glob("*/JSLoadedScriptsinfo"))
    if len(matches) == 1:
        return matches[0]
    if matches:
        return matches[0]
    raise FileNotFoundError("JSLoadedScriptsinfo not found under {}".format(FUSION_ROAMING))


def _load_info(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as handle:
        return json.load(handle)


def _save_info(path: Path, payload: dict) -> None:
    text = json.dumps(payload, indent="\t", ensure_ascii=False)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def _script_path(name: str) -> Path:
    return SCRIPTS_DIR / "{}.py".format(name)


def _forward_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def remove_smokes(names: Sequence[str], *, dry_run: bool = False) -> List[str]:
    removed: List[str] = []
    info_path = _info_path()
    payload = _load_info(info_path)
    entries = payload.get("loadedScripts") or []
    name_set = set(names)

    for name in names:
        target = _script_path(name)
        if target.is_file():
            if dry_run:
                print("[dry-run] delete file {}".format(target))
            else:
                target.unlink()
            removed.append(name)
            print("Removed file: {}".format(target))
        elif name in name_set:
            print("File already absent: {}".format(target))

    kept = []
    for entry in entries:
        if entry.get("name") in name_set:
            removed.append(str(entry.get("name")))
            print("Unregistered: {}".format(entry.get("name")))
            continue
        kept.append(entry)

    if not dry_run and len(kept) != len(entries):
        payload["loadedScripts"] = kept
        _save_info(info_path, payload)
        print("Updated {}".format(info_path))

    return sorted(set(removed))


def install_smoke_by_name(name: str, *, dry_run: bool = False) -> str:
    source = PLUGIN_DIR / "{}.py".format(name)
    if not source.is_file():
        raise SystemExit("Missing repo script: {}".format(source))

    if dry_run:
        print("[dry-run] would install {}".format(name))
        return name

    SCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    target = _script_path(name)
    shutil.copy2(source, target)
    print("Copied: {}".format(target))

    info_path = _info_path()
    payload = _load_info(info_path)
    entries = payload.get("loadedScripts") or []
    registered_path = _forward_path(target)

    for entry in entries:
        if entry.get("name") == name:
            entry["path"] = registered_path
            entry["location"] = 3
            entry["isRemoved"] = False
            _save_info(info_path, payload)
            print("Refreshed registration for {} in {}".format(name, info_path))
            return name

    insert_index = len(entries)
    for index, entry in enumerate(entries):
        if entry.get("name") == "UnifiedCabinetPlugin":
            insert_index = index
            break

    entries.insert(
        insert_index,
        {
            "name": name,
            "path": registered_path,
            "location": 3,
            "isRemoved": False,
            "isFavorite": False,
            "runOnStartup": False,
        },
    )
    payload["loadedScripts"] = entries
    _save_info(info_path, payload)
    print("Registered {} in {}".format(name, info_path))
    return name


def install_smoke(day: int, *, dry_run: bool = False) -> str:
    name = DAY_SMOKE.get(day)
    if not name:
        raise SystemExit("Unsupported day {}. Known: {}".format(day, sorted(DAY_SMOKE)))
    return install_smoke_by_name(name, dry_run=dry_run)


def cleanup_legacy(*, dry_run: bool = False) -> None:
    remove_smokes(LEGACY_SMOKE_NAMES, dry_run=dry_run)


def install_batch(batch: str, *, dry_run: bool = False) -> None:
    active = BATCH_SMOKE.get(batch)
    if not active:
        raise SystemExit("Unsupported batch {}. Known: {}".format(batch, sorted(BATCH_SMOKE)))
    cleanup_legacy(dry_run=dry_run)
    remove_smokes(ALL_TEMPORARY_SMOKES, dry_run=dry_run)
    install_smoke_by_name(active, dry_run=dry_run)
    print()
    print("Active Fusion smoke: {}".format(active))
    print("Restart Fusion, open Shift+S -> enable Script + Created-by-me filters -> Play on {}.".format(active))


def install_day(day: int, *, dry_run: bool = False) -> None:
    """Install only the active day's smoke; remove other day smokes and legacy entries."""
    active = DAY_SMOKE[day]
    other_days = [DAY_SMOKE[d] for d in DAY_SMOKE if d != day]
    cleanup_legacy(dry_run=dry_run)
    remove_smokes(other_days, dry_run=dry_run)
    install_smoke(day, dry_run=dry_run)
    print()
    print("Active Fusion smoke: {}".format(active))
    print("Restart Fusion, open Shift+S -> enable Script + Created-by-me filters -> Play on {}.".format(active))


def remove_batch(batch: str, *, dry_run: bool = False) -> None:
    name = BATCH_SMOKE.get(batch)
    if not name:
        raise SystemExit("Unsupported batch {}".format(batch))
    remove_smokes([name] + list(LEGACY_SMOKE_NAMES), dry_run=dry_run)
    print()
    print("Removed temporary Fusion deployment for {} (repo copy kept).".format(name))


def remove_passed(day: int, *, dry_run: bool = False) -> None:
    name = DAY_SMOKE.get(day)
    if not name:
        raise SystemExit("Unsupported day {}".format(day))
    remove_smokes([name] + list(LEGACY_SMOKE_NAMES), dry_run=dry_run)
    print()
    print("Removed temporary Fusion deployment for {} (repo copy kept).".format(name))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage temporary Fusion Connect smoke scripts.")
    sub = parser.add_subparsers(dest="command", required=True)

    install = sub.add_parser("install", help="Install active smoke into Fusion Scripts list")
    install.add_argument("--day", type=int)
    install.add_argument("--batch", choices=sorted(BATCH_SMOKE))
    install.add_argument("--dry-run", action="store_true")

    remove = sub.add_parser("remove", help="Remove temporary smokes from Fusion deployment")
    remove.add_argument("--names", nargs="*", default=[])
    remove.add_argument("--passed", type=int, help="Remove a completed day smoke (e.g. --passed 1)")
    remove.add_argument("--batch", choices=sorted(BATCH_SMOKE))
    remove.add_argument("--dry-run", action="store_true")

    sub.add_parser("cleanup-legacy", help="Remove historical smoke registrations/files")
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    dry_run = bool(getattr(args, "dry_run", False))

    if args.command == "install":
        if args.batch:
            install_batch(args.batch, dry_run=dry_run)
        elif args.day is not None:
            install_day(args.day, dry_run=dry_run)
        else:
            parser.error("install requires --day or --batch")
        return 0

    if args.command == "remove":
        names = list(args.names or [])
        if args.batch:
            remove_batch(args.batch, dry_run=dry_run)
            return 0
        if args.passed is not None:
            remove_passed(args.passed, dry_run=dry_run)
            return 0
        if not names:
            parser.error("provide --names or --passed")
        remove_smokes(names, dry_run=dry_run)
        return 0

    if args.command == "cleanup-legacy":
        cleanup_legacy(dry_run=dry_run)
        return 0

    parser.error("unknown command")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
