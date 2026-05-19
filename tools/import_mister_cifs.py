#!/usr/bin/env python3
"""
import_mister_cifs.py — Generate TransFS client configs from RetroNAS *_cifs playbooks.

Reads the RetroNAS systems map and one or more install_*_cifs.yml playbook files to
generate TransFS client YAML configs that reflect each platform's CIFS directory
structure.  Configs are written to the 'retronas' client config set.

Supports all RetroNAS CIFS playbooks that follow the standard format:
  install_mister_cifs.yml, install_batocera_cifs.yml, install_retrodeck_cifs.yml, etc.

Usage (inside container, or with --retronas-root pointing to a copy):

  # Generate/refresh just the MiSTer config (default, backward-compatible):
  python3 tools/import_mister_cifs.py

  # Generate from a specific playbook:
  python3 tools/import_mister_cifs.py --playbook /opt/retronas/ansible/install_batocera_cifs.yml

  # Generate all configs from every *_cifs.yml found in retronas/ansible/:
  python3 tools/import_mister_cifs.py --all

  # Dry-run (print YAML, write nothing):
  python3 tools/import_mister_cifs.py --all --dry-run
"""
from __future__ import annotations

import argparse
import glob
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

# Derive output paths relative to this script's location so they work regardless
# of whether TransFS is installed at /app (main container) or /opt/transfs (testbed).
# tools/import_mister_cifs.py → project root is one level up → app/config/clients/retronas
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = str(_PROJECT_ROOT / "app" / "config" / "clients" / "retronas")
DEFAULT_OUTPUT = str(_PROJECT_ROOT / "app" / "config" / "clients" / "retronas" / "mister.yaml")

# top_level_paths used when a playbook defines none (MiSTer-style layout).
FALLBACK_TOP_LEVEL_PATHS = [
    {"name": "games",      "enabled": True,  "generic": "roms",        "systems": True},
    {"name": "saves",      "enabled": True,  "generic": "saves",       "systems": True},
    {"name": "savestates", "enabled": True,  "generic": "savestates",  "systems": True},
    {"name": "BIOS",       "enabled": True,  "generic": "bios",        "systems": True},
    {"name": "wallpapers", "enabled": True,  "generic": "wallpapers",  "systems": False},
]

# Per-platform fallback top_level_paths for platforms that don't define them in their
# playbook vars (e.g. emuelec, retroarch).  Keyed by system_key.
PLATFORM_FALLBACK_TOP_LEVELS: dict[str, list[dict[str, Any]]] = {
    "emuelec": [
        {"name": "roms",   "enabled": True, "generic": "roms",        "systems": True},
        {"name": "saves",  "enabled": True, "generic": "saves",       "systems": True},
        {"name": "states", "enabled": True, "generic": "savestates",  "systems": True},
        {"name": "bios",   "enabled": True, "generic": "bios",        "systems": True},
    ],
    "retroarch": [
        {"name": "roms",   "enabled": True, "generic": "roms",        "systems": True},
        {"name": "saves",  "enabled": True, "generic": "saves",       "systems": True},
        {"name": "states", "enabled": True, "generic": "savestates",  "systems": True},
        {"name": "system", "enabled": True, "generic": "bios",        "systems": True},
    ],
}

# Human-readable display name for each known system_key.
CLIENT_DISPLAY_NAMES: dict[str, str] = {
    "analoguepocket": "Analogue Pocket",
    "batocera":       "Batocera",
    "emudeck":        "EmuDeck",
    "emuelec":        "EmuELEC",
    "mister":         "MiSTer",
    "recalbox":       "Recalbox",
    "retroarch":      "RetroArch",
    "retrodeck":      "RetroDeck",
    "retropie":       "RetroPie",
    "romm":           "RomM",
}

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


def _client_name_from_key(system_key: str) -> str:
    """Return the human-readable client display name for a system_key."""
    return CLIENT_DISPLAY_NAMES.get(system_key.lower(), system_key.title())


def _output_filename_from_key(system_key: str) -> str:
    """Derive the YAML output filename from a system_key (e.g. 'batocera' → 'batocera.yaml')."""
    return f"{system_key.lower()}.yaml"


def discover_cifs_playbooks(ansible_dir: str) -> list[str]:
    """
    Return paths to all install_*_cifs.yml playbooks found in ansible_dir,
    sorted alphabetically.
    """
    pattern = os.path.join(ansible_dir, "install_*_cifs.yml")
    return sorted(glob.glob(pattern))


# ---------------------------------------------------------------------------
# Core generation logic
# ---------------------------------------------------------------------------

def generate_client_config(
    systems_file: str,
    cifs_playbook: str,
    retronas_path: str = "/data/retronas",
    verbose: bool = False,
) -> dict[str, Any]:
    """
    Parse RetroNAS files and generate a TransFS client YAML config for the
    platform identified by the system_key declared in the playbook vars.

    Returns a dict ready for yaml.dump().
    """

    # --- Load systems map ---------------------------------------------------
    systems_data = _load_yaml(systems_file)
    system_map: list[dict[str, Any]] = systems_data.get("system_map") or []

    if not system_map:
        print(f"WARNING: No system_map found in {systems_file}", file=sys.stderr)

    # --- Load playbook vars -------------------------------------------------
    playbook_vars = _extract_vars_from_playbook(cifs_playbook)
    system_key: str = str(playbook_vars.get("system_key") or "mister").lower()

    # Resolve top_level_paths: playbook → platform fallback → global fallback
    top_level_paths: list[dict[str, Any]] = (
        playbook_vars.get("top_level_paths")
        or PLATFORM_FALLBACK_TOP_LEVELS.get(system_key)
        or FALLBACK_TOP_LEVEL_PATHS
    )
    save_overrides: list[dict[str, Any]] = playbook_vars.get("save_overrides") or []

    client_name = _client_name_from_key(system_key)

    if verbose:
        print(f"system_key:         {system_key}")
        print(f"client_name:        {client_name}")
        print(f"top_level_paths:    {[t.get('name') for t in top_level_paths]}")
        print(f"save_overrides:     {len(save_overrides)}")

    # --- Build retronas_support section ------------------------------------
    top_levels_cfg = []
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

    # canonical_roots: RetroNAS-inside-Native convention.
    # All categories live under {filestore}/Native/{category}/{src}.
    # - {filestore} is resolved at runtime from the TransFS app config.
    # - {src}       is the lower-case manufacturer/system path from RetroNAS
    #               (e.g. "acorn/bbcmicro").
    # ROMs/games downloaded by TransFS go to Native/roms/{src}/.
    # Saves written by the emulator go to Native/saves/{src}/ etc.
    canon_roots_final: dict[str, str] = {}
    for tl in top_level_paths:
        if not tl.get("enabled", True):
            continue
        generic = str(tl.get("generic") or tl.get("name") or "").lower()
        if not generic:
            continue
        canon_roots_final[generic] = "{filestore}/Native/" + generic + "/{src}"

    # --- Build save overrides -----------------------------------------------
    overrides_cfg = []
    save_dir_names = [
        tl["name"]
        for tl in top_level_paths
        if tl.get("enabled", True) and tl.get("generic", "") in ("saves", "savestates")
    ]
    for override in save_overrides:
        client_entry_name = str(override.get("name") or "")
        src = str(override.get("src") or "")
        if not client_entry_name or not src:
            continue
        for tl_name in save_dir_names:
            overrides_cfg.append({
                "top_level": tl_name,
                "client_name": client_entry_name,
                "src": src,
            })

    # --- Build systems list -------------------------------------------------
    systems_cfg = []
    seen_platform_names: set[str] = set()

    for entry in system_map:
        if not isinstance(entry, dict):
            continue

        # Use the platform-specific name field (e.g. 'batocera', 'mister').
        # Skip systems where this platform has no entry.
        platform_name = str(entry.get(system_key) or "").strip()
        if not platform_name:
            continue
        if platform_name in seen_platform_names:
            continue
        seen_platform_names.add(platform_name)

        src = str(entry.get("src") or "").strip()
        pretty_name = str(entry.get("pretty_name") or platform_name).strip()
        manufacturer = _manufacturer_from_src(src)

        # Derive canonical_system_name for TransFS source file lookup.
        # RetroNAS pretty_names often include a manufacturer prefix
        # (e.g. "Acorn BBC Micro"), but TransFS source files are named
        # without it (e.g. "BBC Micro.yaml").  Strip the prefix so that
        # get_system_config can resolve the correct source config file.
        canonical_system_name = pretty_name
        prefix = manufacturer + " "
        if canonical_system_name.startswith(prefix):
            canonical_system_name = canonical_system_name[len(prefix):]

        # local_base_path: two-level path derived from the src field.
        if src:
            parts = src.replace("\\", "/").split("/")
            local_base_path = "/".join(p.title() for p in parts) if len(parts) >= 2 else platform_name
        else:
            local_base_path = platform_name

        system_entry: dict[str, Any] = {
            "name": platform_name,
            "manufacturer": manufacturer,
            "system_mapping_name": pretty_name,
            "canonical_system_name": canonical_system_name,
            "canonical_src": src,
            "local_base_path": local_base_path,
            "maps": [],
        }
        systems_cfg.append(system_entry)

    if verbose:
        print(f"Generated {len(systems_cfg)} system entries")

    # --- Assemble full config -----------------------------------------------
    config: dict[str, Any] = {
        "name": client_name,
        "download_layout": "folder_based",
        "default_target_path": "{name}/{system_name}/{maps}",
        "retronas_support": {
            "enabled": True,
            "transport": "smb",
            "auto_map_system_name": True,
            "canonical_roots": canon_roots_final,
            "top_levels": top_levels_cfg,
            **({"overrides": overrides_cfg} if overrides_cfg else {}),
        },
        "systems": systems_cfg,
    }

    return config


# ---------------------------------------------------------------------------
# Backward-compatible alias
# ---------------------------------------------------------------------------

def generate_mister_yaml(
    systems_file: str,
    cifs_playbook: str,
    retronas_path: str = "/data/retronas",
    verbose: bool = False,
) -> dict[str, Any]:
    """Alias for generate_client_config (kept for backward compatibility)."""
    return generate_client_config(
        systems_file=systems_file,
        cifs_playbook=cifs_playbook,
        retronas_path=retronas_path,
        verbose=verbose,
    )


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate TransFS client configs from RetroNAS install_*_cifs.yml playbooks.\n"
            "By default generates only mister.yaml (backward-compatible).\n"
            "Use --all to generate configs for every *_cifs playbook found."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--retronas-root",
        default=DEFAULT_RETRONAS_ROOT,
        help=f"Path to RetroNAS installation root (default: {DEFAULT_RETRONAS_ROOT})",
    )
    parser.add_argument(
        "--playbook",
        metavar="PATH",
        help=(
            "Path to a specific install_*_cifs.yml playbook to generate a config for. "
            "Overrides the default MiSTer playbook. Mutually exclusive with --all."
        ),
    )
    parser.add_argument(
        "--all",
        action="store_true",
        dest="all_playbooks",
        help=(
            "Auto-discover and generate configs for all install_*_cifs.yml playbooks "
            "found in <retronas-root>/ansible/. Mutually exclusive with --playbook."
        ),
    )
    parser.add_argument(
        "--output",
        default=DEFAULT_OUTPUT,
        help=(
            f"Output path for single-playbook mode (default: {DEFAULT_OUTPUT}). "
            "Ignored when --all is used."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=(
            f"Output directory used by --all mode (default: {DEFAULT_OUTPUT_DIR}). "
            "Each client gets a <system_key>.yaml file inside this directory."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print generated YAML to stdout without writing any files",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print progress information",
    )
    args = parser.parse_args()

    if args.playbook and args.all_playbooks:
        parser.error("--playbook and --all are mutually exclusive")

    retronas_root = args.retronas_root.rstrip("/")
    systems_file = os.path.join(retronas_root, DEFAULT_SYSTEMS_FILE)
    vars_file = os.path.join(retronas_root, DEFAULT_VARS_FILE)
    ansible_dir = os.path.join(retronas_root, "ansible")

    # Validate the systems map exists (needed for all modes)
    if not os.path.exists(systems_file):
        print(f"ERROR: Systems file not found: {systems_file}", file=sys.stderr)
        sys.exit(1)

    # Read retronas_path from vars file
    retronas_path = "/data/retronas"
    if os.path.exists(vars_file):
        rn_vars = _load_yaml(vars_file)
        retronas_path = str(rn_vars.get("retronas_path") or retronas_path)
    else:
        print(
            f"WARNING: RetroNAS vars file not found at {vars_file}; "
            f"using default retronas_path={retronas_path}",
            file=sys.stderr,
        )

    if args.verbose:
        print(f"RetroNAS root : {retronas_root}")
        print(f"Systems file  : {systems_file}")
        print(f"retronas_path : {retronas_path}")

    # ------------------------------------------------------------------
    # Determine which playbooks to process
    # ------------------------------------------------------------------
    if args.all_playbooks:
        playbooks = discover_cifs_playbooks(ansible_dir)
        if not playbooks:
            print(f"ERROR: No install_*_cifs.yml files found in {ansible_dir}", file=sys.stderr)
            sys.exit(1)
        if args.verbose:
            print(f"Found {len(playbooks)} CIFS playbooks: {[os.path.basename(p) for p in playbooks]}")
    elif args.playbook:
        if not os.path.exists(args.playbook):
            print(f"ERROR: Playbook not found: {args.playbook}", file=sys.stderr)
            sys.exit(1)
        playbooks = [args.playbook]
    else:
        # Default: MiSTer only (backward-compatible behaviour)
        default_playbook = os.path.join(retronas_root, DEFAULT_CIFS_PLAYBOOK)
        if not os.path.exists(default_playbook):
            print(f"ERROR: MiSTer CIFS playbook not found: {default_playbook}", file=sys.stderr)
            sys.exit(1)
        playbooks = [default_playbook]

    # ------------------------------------------------------------------
    # Process each playbook
    # ------------------------------------------------------------------
    for playbook_path in playbooks:
        playbook_name = os.path.basename(playbook_path)

        # Peek at the system_key before full generation (for output path)
        peek_vars = _extract_vars_from_playbook(playbook_path)
        system_key = str(peek_vars.get("system_key") or "mister").lower()

        # Determine output path
        if args.all_playbooks:
            output_path = os.path.join(args.output_dir, _output_filename_from_key(system_key))
        elif args.playbook:
            # Single custom playbook: derive output from --output-dir unless --output given
            if args.output != DEFAULT_OUTPUT:
                output_path = args.output
            else:
                output_path = os.path.join(args.output_dir, _output_filename_from_key(system_key))
        else:
            # Default MiSTer mode: honour --output exactly
            output_path = args.output

        if args.verbose:
            print(f"\n--- Processing {playbook_name} (system_key={system_key}) ---")
            print(f"    Output: {output_path}")

        config = generate_client_config(
            systems_file=systems_file,
            cifs_playbook=playbook_path,
            retronas_path=retronas_path,
            verbose=args.verbose,
        )

        client_display = config.get("name", system_key)
        n_systems = len(config.get("systems", []))

        output_yaml = yaml.dump(
            config,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
            indent=2,
            width=120,
        )

        header = (
            f"# {client_display} Client Configuration — generated from RetroNAS {playbook_name}\n"
            "# Generated by tools/import_mister_cifs.py\n"
            "# This config is part of the 'retronas' config set and reflects the\n"
            f"# directory structure created by the RetroNAS {playbook_name} Ansible playbook.\n"
            "#\n"
            "# Do not hand-edit — re-run the importer to refresh after RetroNAS changes.\n\n"
        )

        if args.dry_run:
            print(f"# ===== {output_path} =====")
            print(header, end="")
            print(output_yaml)
            continue

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(header)
            fh.write(output_yaml)

        print(f"[{client_display}] {n_systems} systems → {out}")

    if not args.dry_run:
        print("Done.")


if __name__ == "__main__":
    main()
