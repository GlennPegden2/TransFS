#!/usr/bin/env python3
"""
import_mister_cifs.py — Generate a TransFS mister.yaml from RetroNAS mister_cifs data.

Reads the RetroNAS systems map and mister_cifs playbook variables to generate a
mister.yaml client config that reflects the MiSTer CIFS directory structure.

The generated config is written to a new 'retronas' config set so it does not
overwrite the default MiSTer config.

Usage (inside container, or with --retronas-root pointing to a copy):
    python3 tools/import_mister_cifs.py
    python3 tools/import_mister_cifs.py --retronas-root /opt/retronas --output /app/config/clients/retronas/mister.yaml
    python3 tools/import_mister_cifs.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML not available. Install with: pip install pyyaml", file=sys.stderr)
    sys.exit(1)

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_RETRONAS_ROOT = "/opt/retronas"
DEFAULT_SYSTEMS_FILE = "ansible/retronas_systems.yml"
DEFAULT_CIFS_PLAYBOOK = "ansible/install_mister_cifs.yml"
DEFAULT_VARS_FILE = "ansible/retronas_vars.yml"
DEFAULT_OUTPUT = "/app/config/clients/retronas/mister.yaml"

# top_level_paths defined in install_mister_cifs.yml (fallback if not parseable)
FALLBACK_TOP_LEVEL_PATHS = [
    {"name": "games",      "enabled": True,  "generic": "roms",        "systems": True},
    {"name": "saves",      "enabled": True,  "generic": "saves",       "systems": True},
    {"name": "savestates", "enabled": True,  "generic": "savestates",  "systems": True},
    {"name": "BIOS",       "enabled": True,  "generic": "bios",        "systems": True},
    {"name": "wallpapers", "enabled": True,  "generic": "wallpapers",  "systems": False},
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_yaml(path: str) -> dict[str, Any]:
    """Load a YAML file, returning an empty dict on failure."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if not isinstance(data, dict):
            return {}
        return data
    except FileNotFoundError:
        return {}
    except yaml.YAMLError as exc:
        print(f"WARNING: YAML parse error in {path}: {exc}", file=sys.stderr)
        return {}


def _extract_vars_from_playbook(playbook_path: str) -> dict[str, Any]:
    """
    Extract the vars block from the first play in an Ansible playbook YAML file.
    Returns an empty dict if the file can't be parsed or has no vars.
    """
    try:
        with open(playbook_path, "r", encoding="utf-8") as fh:
            plays = yaml.safe_load(fh) or []
        if not isinstance(plays, list) or not plays:
            return {}
        first_play = plays[0]
        if not isinstance(first_play, dict):
            return {}
        return first_play.get("vars") or {}
    except (FileNotFoundError, yaml.YAMLError):
        return {}


def _manufacturer_from_src(src: str) -> str:
    """Derive a human-readable manufacturer name from the src path component."""
    manufacturer_map = {
        "3do": "3DO",
        "acorn": "Acorn",
        "amstrad": "Amstrad",
        "apple": "Apple",
        "atari": "Atari",
        "bandai": "Bandai",
        "commodore": "Commodore",
        "coleco": "ColecoVision",
        "fujitsu": "Fujitsu",
        "gce": "GCE",
        "mattel": "Mattel",
        "microsoft": "Microsoft",
        "nec": "NEC",
        "nintendo": "Nintendo",
        "philips": "Philips",
        "sega": "Sega",
        "snk": "SNK",
        "sony": "Sony",
        "sinclair": "Sinclair",
        "tiger": "Tiger",
        "tomy": "Tomy",
        "mame": "MAME",
        "arcade": "Arcade",
        "misc": "Miscellaneous",
        "computer": "Computer",
        "other": "Other",
    }
    if not src:
        return "Unknown"
    parts = src.replace("\\", "/").split("/")
    key = parts[0].lower()
    return manufacturer_map.get(key, parts[0].title())


# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------

def generate_mister_yaml(
    systems_file: str,
    cifs_playbook: str,
    retronas_path: str = "/data/retronas",
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Parse RetroNAS files and generate the TransFS mister.yaml content.

    Returns a dict ready for yaml.dump().
    """

    # --- Load systems map ---------------------------------------------------
    systems_data = _load_yaml(systems_file)
    system_map: list[dict[str, Any]] = systems_data.get("system_map") or []
    save_links: list[dict[str, Any]] = systems_data.get("system_links") or []

    if not system_map:
        print(f"WARNING: No system_map found in {systems_file}", file=sys.stderr)

    # --- Load mister_cifs playbook vars -------------------------------------
    playbook_vars = _extract_vars_from_playbook(cifs_playbook)
    top_level_paths: list[dict[str, Any]] = playbook_vars.get("top_level_paths") or FALLBACK_TOP_LEVEL_PATHS
    save_overrides: list[dict[str, Any]] = playbook_vars.get("save_overrides") or []
    system_key: str = str(playbook_vars.get("system_key") or "mister")

    if verbose:
        print(f"system_key: {system_key}")
        print(f"top_level_paths: {[t.get('name') for t in top_level_paths]}")
        print(f"save_overrides count: {len(save_overrides)}")

    # --- Build retronas_support section ------------------------------------
    top_levels_cfg = []
    canon_roots_cfg: dict[str, str] = {}
    for tl in top_level_paths:
        if not tl.get("enabled", True):
            continue
        name = str(tl.get("name") or "")
        generic = str(tl.get("generic") or name).lower()
        per_system = bool(tl.get("systems", True))
        if not name:
            continue
        top_levels_cfg.append({
            "name": name,
            "source_root": generic,
            "per_system": per_system,
        })
        canon_roots_cfg[generic] = f"{{{generic}_src}}"  # placeholder — override below

    # canonical_roots: map each generic root to its canonical path template
    # Under MiSTer CIFS the filestore layout is:
    #   <retronas_path>/<generic>/<src>   e.g. /data/retronas/roms/nintendo/gameboy
    # TransFS uses {src} as the system canonical src.
    canon_roots_final: dict[str, str] = {}
    for tl in top_level_paths:
        if not tl.get("enabled", True):
            continue
        generic = str(tl.get("generic") or tl.get("name") or "").lower()
        if generic:
            canon_roots_final[generic] = f"{retronas_path}/{generic}/{{src}}"

    # --- Build overrides from save_overrides --------------------------------
    overrides_cfg = []
    save_dir_names = [
        tl["name"]
        for tl in top_level_paths
        if tl.get("enabled", True) and tl.get("generic", "") in ("saves", "savestates")
    ]
    for override in save_overrides:
        client_name = str(override.get("name") or "")
        src = str(override.get("src") or "")
        if not client_name or not src:
            continue
        for tl_name in save_dir_names:
            overrides_cfg.append({
                "top_level": tl_name,
                "client_name": client_name,
                "src": src,
            })

    # --- Build systems list -------------------------------------------------
    systems_cfg = []
    seen_mister_names: set[str] = set()

    for entry in system_map:
        if not isinstance(entry, dict):
            continue
        mister_name = str(entry.get("mister") or "").strip()
        if not mister_name:
            continue
        if mister_name in seen_mister_names:
            continue
        seen_mister_names.add(mister_name)

        src = str(entry.get("src") or "").strip()
        pretty_name = str(entry.get("pretty_name") or mister_name).strip()
        manufacturer = _manufacturer_from_src(src)

        # Derive a reasonable local_base_path from the MiSTer structure
        # MiSTer organises per system in e.g. games/SNES, BIOS/SNES etc.
        # local_base_path in TransFS is a sub-path hint for download layout.
        # Use manufacturer + pretty_name as a default, or just the mister name.
        if src:
            parts = src.replace("\\", "/").split("/")
            if len(parts) >= 2:
                local_base_path = "/".join(p.title() for p in parts)
            else:
                local_base_path = mister_name
        else:
            local_base_path = mister_name

        system_entry: dict[str, Any] = {
            "name": mister_name,
            "manufacturer": manufacturer,
            "system_mapping_name": pretty_name,
            "canonical_src": src,
            "local_base_path": local_base_path,
            "maps": [],  # no detailed maps — this is a structural import
        }
        systems_cfg.append(system_entry)

    if verbose:
        print(f"Generated {len(systems_cfg)} system entries")

    # --- Assemble full config -----------------------------------------------
    config: dict[str, Any] = {
        "name": "MiSTer",
        "download_layout": "folder_based",
        "default_target_path": "{name}/{system_name}/{maps}",
        "retronas_support": {
            "enabled": True,
            "transport": "smb",
            "auto_map_system_name": False,
            "canonical_roots": canon_roots_final,
            "top_levels": top_levels_cfg,
            **({"overrides": overrides_cfg} if overrides_cfg else {}),
        },
        "systems": systems_cfg,
    }

    return config


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a TransFS mister.yaml from RetroNAS mister_cifs configuration."
    )
    parser.add_argument(
        "--retronas-root",
        default=DEFAULT_RETRONAS_ROOT,
        help=f"Path to RetroNAS installation root (default: {DEFAULT_RETRONAS_ROOT})",
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=f"Destination for the generated mister.yaml (default: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the generated YAML to stdout without writing any files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress information",
    )
    args = parser.parse_args()

    retronas_root = args.retronas_root.rstrip("/")
    systems_file = os.path.join(retronas_root, DEFAULT_SYSTEMS_FILE)
    cifs_playbook = os.path.join(retronas_root, DEFAULT_CIFS_PLAYBOOK)
    vars_file = os.path.join(retronas_root, DEFAULT_VARS_FILE)

    # Validate inputs
    for label, path in [
        ("Systems file", systems_file),
        ("MiSTer CIFS playbook", cifs_playbook),
    ]:
        if not os.path.exists(path):
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            sys.exit(1)

    # Read retronas_path from vars file
    retronas_path = "/data/retronas"
    if os.path.exists(vars_file):
        rn_vars = _load_yaml(vars_file)
        retronas_path = str(rn_vars.get("retronas_path") or retronas_path)
    else:
        print(f"WARNING: RetroNAS vars file not found at {vars_file}; using default path {retronas_path}", file=sys.stderr)

    if args.verbose:
        print(f"RetroNAS root : {retronas_root}")
        print(f"Systems file  : {systems_file}")
        print(f"CIFS playbook : {cifs_playbook}")
        print(f"retronas_path : {retronas_path}")
        print(f"Output file   : {args.output}")

    config = generate_mister_yaml(
        systems_file=systems_file,
        cifs_playbook=cifs_playbook,
        retronas_path=retronas_path,
        verbose=args.verbose,
    )

    output_yaml = yaml.dump(
        config,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        indent=2,
        width=120,
    )

    header = (
        "# MiSTer FPGA Client Configuration — generated from RetroNAS mister_cifs\n"
        "# Generated by tools/import_mister_cifs.py\n"
        "# This config is part of the 'retronas' config set and reflects the\n"
        "# directory structure created by the RetroNAS MiSTer_CIFS Ansible playbook.\n"
        "#\n"
        "# Do not hand-edit — re-run the importer to refresh after RetroNAS changes.\n\n"
    )

    if args.dry_run:
        print(header, end="")
        print(output_yaml)
        return

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(header)
        fh.write(output_yaml)

    print(f"Generated {len(config.get('systems', []))} system entries.")
    print(f"Written to: {output_path}")


if __name__ == "__main__":
    main()
