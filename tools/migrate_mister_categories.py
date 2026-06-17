"""
One-shot migration script: replaces retronas_support block in mister.yaml
with category_paths, and injects category: tags into every map entry.

Rules:
  - Query maps named "BIOS" (case-insensitive)          -> category: bios
  - File  maps whose key ends in .rom / .bin, or is KICK.ROM -> category: bios
  - All other query maps                                -> category: roms
  - File  maps whose key ends in .vhd                  -> no category (boot disks)
  - All other file  maps                               -> no category (download-only)

The retronas_support: block is replaced with:
  category_paths:
    roms: "MiSTer/games/{system_name}"
    bios: "MiSTer/BIOS/{system_name}"
"""

import re
import sys
from pathlib import Path

YAML_PATH = Path(__file__).parent.parent / "app" / "config" / "clients" / "default" / "mister.yaml"

RETRONAS_BLOCK_PATTERN = re.compile(r"^retronas_support:\s*\n(?:[ \t]+.*\n|\n)*", re.MULTILINE)

CATEGORY_PATHS_BLOCK = (
    "category_paths:\n"
    '  roms: "MiSTer/games/{system_name}"\n'
    '  bios: "MiSTer/BIOS/{system_name}"\n'
)

# Match the map key line: "      - some_name:"  (6-space indent with dash)
MAP_KEY_RE = re.compile(r"^( {6}- )(\S+):\s*$")

# Match "          query:" or "          file:" at 10-space indent
QUERY_LINE_RE  = re.compile(r"^( {10})(query:)\s*$")
FILE_LINE_RE   = re.compile(r"^( {10})(file:)\s*$")

# BIOS file map name rules
BIOS_FILE_SUFFIXES = (".rom", ".bin")
BIOS_FILE_EXACT    = {"kick.rom"}   # lower-case comparison


def is_bios_file_map(key: str) -> bool:
    k = key.lower()
    return k in BIOS_FILE_EXACT or any(k.endswith(s) for s in BIOS_FILE_SUFFIXES)


def is_boot_disk_map(key: str) -> bool:
    return key.lower().endswith(".vhd")


def migrate(text: str) -> str:
    # ------------------------------------------------------------------ #
    # Step 1: Replace retronas_support block                              #
    # ------------------------------------------------------------------ #
    # Find the block manually (the regex above can be greedy across the
    # whole overrides list which contains many lines).
    lines = text.splitlines(keepends=True)
    start_idx = None
    end_idx   = None
    for i, line in enumerate(lines):
        if line.strip() == "retronas_support:":
            start_idx = i
        if start_idx is not None and i > start_idx:
            # The block ends at the first line that starts at col 0
            # (next top-level key) or is blank then followed by top-level key
            if line and not line[0].isspace() and line.strip() != "":
                end_idx = i
                break
    if start_idx is None:
        print("WARNING: retronas_support block not found – skipping step 1", file=sys.stderr)
        new_lines = lines
    else:
        print(f"Replacing retronas_support block (lines {start_idx+1}–{end_idx})")
        replacement_lines = CATEGORY_PATHS_BLOCK.splitlines(keepends=True)
        new_lines = lines[:start_idx] + replacement_lines + ["\n"] + lines[end_idx:]

    # ------------------------------------------------------------------ #
    # Step 2: Inject category: tags                                       #
    # ------------------------------------------------------------------ #
    current_map_key: str | None = None
    result: list[str] = []

    for line in new_lines:
        map_key_match = MAP_KEY_RE.match(line)
        if map_key_match:
            current_map_key = map_key_match.group(2)
            result.append(line)
            continue

        query_match = QUERY_LINE_RE.match(line)
        if query_match:
            indent = query_match.group(1)
            key = current_map_key or ""
            if key.lower() == "bios":
                cat = "bios"
            else:
                cat = "roms"
            result.append(f"{indent}category: {cat}\n")
            result.append(line)
            continue

        file_match = FILE_LINE_RE.match(line)
        if file_match:
            indent = file_match.group(1)
            key = current_map_key or ""
            if is_bios_file_map(key):
                result.append(f"{indent}category: bios\n")
            # boot disks and other file maps: no category injected
            result.append(line)
            continue

        result.append(line)

    return "".join(result)


def main():
    original = YAML_PATH.read_text(encoding="utf-8")
    migrated = migrate(original)
    YAML_PATH.write_text(migrated, encoding="utf-8")
    print(f"Written: {YAML_PATH}")

    # Quick sanity check — count injected categories
    roms_count = migrated.count("category: roms")
    bios_count = migrated.count("category: bios")
    print(f"Injected  category: roms  x{roms_count}")
    print(f"Injected  category: bios  x{bios_count}")
    print("Done.")


if __name__ == "__main__":
    main()
