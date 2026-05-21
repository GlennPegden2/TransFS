#!/usr/bin/env python3
"""GP + RetroNAS → mister.yaml stub generator

Generates stub entries for the default/mister.yaml client config from
Game Populator and RetroNAS system databases, for systems not yet covered.

Non-destructive: existing systems in mister.yaml are never modified.

Usage:
  python tools/generate_mister_stubs.py            # dry-run, print new stubs
  python tools/generate_mister_stubs.py --write    # append stubs to mister.yaml
  python tools/generate_mister_stubs.py --sources  # also write stub source yamls
"""

import argparse
import json
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

# ---------------------------------------------------------------------------
# URLs / paths
# ---------------------------------------------------------------------------

GP_URL = (
    "https://raw.githubusercontent.com/cosmickatamari/game-populator"
    "/main/libraries/console-names.template.json"
)
RETRONAS_URL = (
    "https://raw.githubusercontent.com/retronas/retronas"
    "/main/ansible/retronas_systems.yml"
)

WORKSPACE_ROOT = Path(__file__).parent.parent
MISTER_YAML_PATH = WORKSPACE_ROOT / "app/config/clients/default/mister.yaml"
SOURCES_DEFAULT_PATH = WORKSPACE_ROOT / "app/config/sources/default"

# ---------------------------------------------------------------------------
# GP ShortNames already covered in mister.yaml under a different name
# (anything not here is caught automatically by case-insensitive name matching)
# ---------------------------------------------------------------------------

GP_COVERED_ALIASES: dict[str, str] = {
    "Coleco": "ColecoVision",
    "GBA": "GameBoyAdvance",         # GP ShortName differs from mister.yaml name
    "GBC": "GameBoyColor",
    "Gameboy": "GameBoy",           # case only
    "GameGear": "SegaGameGear",
    "MegaDrive": "SegaGenesis",
    "SMS": "SegaMasterSystem",
    "TGFX16": "TurboGrafx16",       # we cover as PC-Engine + TurboGrafx16
}

# Extensions that unambiguously signal an optical-media system
# (BIN is excluded - it's also a cartridge ROM format for many systems)
OPTICAL_EXTS: frozenset[str] = frozenset({"CUE", "CHD", "ISO", "MDS", "CSO", "NRG"})

# Non-disc-image extensions to strip from optical system maps (save files etc.)
OPTICAL_EXCLUDE: frozenset[str] = frozenset({"SAV", "SRM", "MC", "MCR", "EXE", "PSV", "FCS", "FSV"})

# Preferred display order for optical extensions (CHD first — smaller files)
OPTICAL_ORDER = ["CHD", "CUE", "BIN", "ISO", "MDS"]

# Manufacturer normalisations from RetroNAS src first-component
MANUFACTURER_NORMALISE: dict[str, str] = {
    "benesse": "Benesse",
    "bitcorporation": "Bit Corporation",
    "bit_corp": "Bit Corporation",
    "casio": "Casio",
    "entex": "Entex",
    "epoch": "Epoch",
    "epoch_co": "Epoch",
    "fairchild": "Fairchild",
    "interton": "Interton",
    "nec": "NEC",
    "nichibutsu": "Nichibutsu",
    "panasonic": "Panasonic",
    "philips": "Philips",
    "snk": "SNK",
    "videotechnology": "VTech",
    "watara": "Watara",
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def fetch_url(url: str) -> str:
    with urllib.request.urlopen(url, timeout=15) as resp:  # noqa: S310 (known safe URLs)
        return resp.read().decode("utf-8")


def load_gp_data() -> dict[str, list]:
    """Return GP console entries grouped by ShortName."""
    raw: list = json.loads(fetch_url(GP_URL))
    grouped: dict[str, list] = defaultdict(list)
    for entry in raw:
        grouped[entry["ShortName"]].append(entry)
    return dict(grouped)


def load_retronas_data() -> dict[str, dict]:
    """Return RetroNAS systems indexed by `mister` field (lower-case key)."""
    raw = yaml.safe_load(fetch_url(RETRONAS_URL))
    index: dict[str, dict] = {}
    for system in raw.get("retronas_systems", []):
        mister = (system.get("mister") or "").strip()
        if mister:
            index[mister.lower()] = system
    return index


def load_mister_yaml() -> dict:
    with open(MISTER_YAML_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


# ---------------------------------------------------------------------------
# Gap analysis
# ---------------------------------------------------------------------------

def covered_shortnames(mister_data: dict, gp_grouped: dict) -> set[str]:
    """Return the set of GP ShortNames already handled in mister.yaml."""
    existing_lower = {s["name"].lower() for s in mister_data.get("systems", [])}
    covered = set(GP_COVERED_ALIASES.keys())
    for shortname in gp_grouped:
        if shortname.lower() in existing_lower:
            covered.add(shortname)
    return covered


# ---------------------------------------------------------------------------
# Stub construction
# ---------------------------------------------------------------------------

def clean_extensions(raw: list[str]) -> list[str]:
    """Return unique uppercase extensions without leading dot, stable order."""
    seen: set[str] = set()
    result: list[str] = []
    for ext in raw:
        upper = ext.lstrip(".").upper()
        if upper not in seen:
            seen.add(upper)
            result.append(upper)
    return result


def is_optical(gp_entries: list) -> bool:
    if any(e.get("Optical") == "yes" for e in gp_entries):
        return True
    all_exts: set[str] = set()
    for e in gp_entries:
        all_exts.update(clean_extensions(e.get("Extensions", [])))
    return bool(all_exts & OPTICAL_EXTS)


def derive_manufacturer(shortname: str, gp_entries: list, retronas_entry: dict | None) -> str:
    if retronas_entry:
        src_parts = (retronas_entry.get("src") or "").split("/")
        raw = src_parts[0] if src_parts else ""
        if raw in MANUFACTURER_NORMALISE:
            return MANUFACTURER_NORMALISE[raw]
        if raw:
            return raw.replace("_", " ").title()
    # Fall back to first word of the GP system name
    return gp_entries[0].get("Name", shortname).split()[0]


def build_stub(shortname: str, gp_entries: list, retronas_entry: dict | None) -> dict:
    """Build a mister.yaml system stub as a plain dict."""
    # Combine extensions from all SubDir variants
    seen_exts: set[str] = set()
    all_exts: list[str] = []
    for entry in gp_entries:
        for ext in clean_extensions(entry.get("Extensions", [])):
            if ext not in seen_exts:
                seen_exts.add(ext)
                all_exts.append(ext)

    optical = is_optical(gp_entries)
    manufacturer = derive_manufacturer(shortname, gp_entries, retronas_entry)

    # system_mapping_name: use RetroNAS mister field if available
    sys_map_name = (retronas_entry or {}).get("mister") or shortname

    # display_name: prefer RetroNAS pretty_name, else GP Name
    gp_full_name = gp_entries[0].get("Name", shortname)
    display_name = (retronas_entry or {}).get("pretty_name") or gp_full_name

    local_base_path = f"{manufacturer}/{shortname}"

    if optical:
        # Canonical optical extension set, ordered CHD-first; strip save/runtime files
        filtered_exts = {e for e in seen_exts if e not in OPTICAL_EXCLUDE}
        ext_list = [e for e in OPTICAL_ORDER if e in filtered_exts]
        for e in all_exts:
            if e not in ext_list and e not in OPTICAL_EXCLUDE:
                ext_list.append(e)
        # Ensure at minimum CHD/CUE/BIN are present for optical systems
        for base_ext in ["CHD", "CUE", "BIN"]:
            if base_ext not in ext_list:
                ext_list.insert(["CHD", "CUE", "BIN"].index(base_ext), base_ext)
        map_name = "CDs"
    else:
        ext_list = all_exts
        map_name = "ROMs"

    return {
        "name": shortname,
        "display_name": display_name if display_name != shortname else None,
        "manufacturer": manufacturer,
        "system_mapping_name": sys_map_name,
        "local_base_path": local_base_path,
        "maps": [
            {
                map_name: {
                    "query": {
                        "source_dir": "Software",
                        "extensions": ext_list,
                        "transform_zip": False,
                        "supports_zaparoo": True,
                    }
                }
            }
        ],
    }


# ---------------------------------------------------------------------------
# YAML text rendering  (matches existing mister.yaml indent style)
# ---------------------------------------------------------------------------

def render_stub(stub: dict) -> str:
    lines: list[str] = []
    lines.append(f"  - name: {stub['name']}")
    if stub.get("display_name"):
        lines.append(f'    display_name: "{stub["display_name"]}"')
    lines.append(f"    manufacturer: {stub['manufacturer']}")
    lines.append(f"    system_mapping_name: {stub['system_mapping_name']}")
    lines.append(f"    local_base_path: {stub['local_base_path']}")
    lines.append("    maps:")
    for map_entry in stub["maps"]:
        for map_name, map_content in map_entry.items():
            lines.append(f"      - {map_name}:")
            q = map_content["query"]
            lines.append("          query:")
            lines.append(f"            source_dir: {q['source_dir']}")
            lines.append("            extensions:")
            for ext in q["extensions"]:
                lines.append(f"              - {ext}")
            tf = "true" if q.get("transform_zip") else "false"
            sz = "true" if q.get("supports_zaparoo", True) else "false"
            lines.append(f"            transform_zip: {tf}")
            lines.append(f"            supports_zaparoo: {sz}")
    return "\n".join(lines)


def render_manufacturer_section(manufacturer: str, stubs: list[dict]) -> str:
    parts = [f"  # --- {manufacturer} ---"]
    parts.extend(render_stub(s) for s in stubs)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Source yaml stub generation
# ---------------------------------------------------------------------------

SOURCE_STUB_TEMPLATE = """\
# {display_name} Software Sources
# AUTO-GENERATED STUB - replace placeholder URL with actual download source

base_path: {local_base_path}/

sources:
  - name: placeholder
    type: ddl
    url: https://example.com/placeholder.zip  # TODO: replace with real URL
    folder: Software
    extract: true

packs:
  - id: {pack_id}
    name: {display_name}
    description: {display_name} software
    estimated_size: unknown
    sources: [placeholder]
"""


def write_source_stub(stub: dict) -> tuple[Path, bool]:
    """Write a source yaml stub. Returns (path, was_created)."""
    manufacturer = stub["manufacturer"]
    shortname = stub["name"]
    display_name = stub.get("display_name") or shortname
    local_base_path = stub["local_base_path"]
    pack_id = shortname.lower().replace(" ", "_").replace("-", "_")

    dest_dir = SOURCES_DEFAULT_PATH / manufacturer
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_file = dest_dir / f"{shortname}.yaml"

    if dest_file.exists():
        return dest_file, False

    content = SOURCE_STUB_TEMPLATE.format(
        display_name=display_name,
        local_base_path=local_base_path,
        pack_id=pack_id,
    )
    dest_file.write_text(content, encoding="utf-8")
    return dest_file, True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate mister.yaml stubs from Game Populator + RetroNAS data"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Append new stubs to mister.yaml (default: dry-run, print only)",
    )
    parser.add_argument(
        "--sources",
        action="store_true",
        help="Also write stub source yamls for new systems",
    )
    args = parser.parse_args()

    print("Fetching Game Populator data...", file=sys.stderr)
    gp_grouped = load_gp_data()

    print("Fetching RetroNAS data...", file=sys.stderr)
    retronas_index = load_retronas_data()

    print("Loading mister.yaml...", file=sys.stderr)
    mister_data = load_mister_yaml()

    # ---- Gap analysis ----
    covered = covered_shortnames(mister_data, gp_grouped)
    new_shortnames = sorted(sn for sn in gp_grouped if sn not in covered)

    print(f"\n{len(new_shortnames)} new systems not yet in mister.yaml:", file=sys.stderr)
    for sn in new_shortnames:
        print(f"  {sn}", file=sys.stderr)
    print(file=sys.stderr)

    if not new_shortnames:
        print("Nothing to add.", file=sys.stderr)
        return 0

    # ---- Build stubs grouped by manufacturer ----
    stubs_by_mfr: dict[str, list] = defaultdict(list)
    for shortname in new_shortnames:
        gp_entries = gp_grouped[shortname]
        retronas_entry = retronas_index.get(shortname.lower())
        stub = build_stub(shortname, gp_entries, retronas_entry)
        stubs_by_mfr[stub["manufacturer"]].append(stub)

    # ---- Render YAML ----
    sections = [
        render_manufacturer_section(mfr, stubs)
        for mfr, stubs in sorted(stubs_by_mfr.items())
    ]
    output_yaml = "\n".join(sections) + "\n"

    if not args.write:
        print(output_yaml)
        print(
            f"Dry-run: {len(new_shortnames)} stubs generated. Use --write to append to mister.yaml.",
            file=sys.stderr,
        )
    else:
        with open(MISTER_YAML_PATH, "a", encoding="utf-8") as fh:
            fh.write("\n" + output_yaml)
        print(
            f"Appended {len(new_shortnames)} stubs to {MISTER_YAML_PATH}",
            file=sys.stderr,
        )

    # ---- Optionally write source stubs ----
    if args.sources:
        created: list[Path] = []
        skipped: list[str] = []
        for stubs in stubs_by_mfr.values():
            for stub in stubs:
                path, was_new = write_source_stub(stub)
                if was_new:
                    created.append(path)
                else:
                    skipped.append(stub["name"])
        print(f"\nSource stubs created: {len(created)}", file=sys.stderr)
        for p in created:
            print(f"  {p}", file=sys.stderr)
        if skipped:
            print(f"Source stubs skipped (already exist): {', '.join(skipped)}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    sys.exit(main())
