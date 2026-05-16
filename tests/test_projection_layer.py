import logging
import os
import sys


sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

from dirlisting import parse_trans_path
from retronas_support import get_primary_smb_retronas_root
from sourcepath import get_source_path, get_source_path_for_write


def _build_projection_config(filestore: str) -> dict:
    return {
        "filestore": filestore,
        "clients": [
            {
                "name": "MiSTer",
                "default_target_path": "{name}/{system_name}/{maps}",
                "retronas_support": {
                    "enabled": True,
                    "transport": "smb",
                    "auto_map_system_name": False,
                    "canonical_roots": {
                        "roms": "Canonical/roms/{src}",
                        "saves": "Canonical/saves/{src}",
                        "savestates": "Canonical/savestates/{src}",
                        "bios": "Canonical/bios/{src}",
                    },
                    "top_levels": [
                        {"name": "games", "source_root": "roms", "per_system": True},
                        {"name": "saves", "source_root": "saves", "per_system": True},
                        {"name": "savestates", "source_root": "savestates", "per_system": True},
                        {"name": "BIOS", "source_root": "bios", "per_system": True},
                    ],
                    "mappings": [
                        {"system_id": "sony/playstation1", "client_name": "PSX"},
                    ],
                    "overrides": [
                        {"top_level": "games", "client_name": "PlayStation", "src": "sony/playstation1"},
                    ],
                },
                "systems": [
                    {
                        "name": "SonyPS1",
                        "manufacturer": "Sony",
                        "system_mapping_name": "PlayStation1",
                        "canonical_src": "sony/playstation1",
                        "local_base_path": "Systems/Sony/PlayStation1",
                        "retronas_aliases": ["PS1"],
                    },
                    {
                        "name": "NeoGeoUnmapped",
                        "manufacturer": "SNK",
                        "system_mapping_name": "NeoGeo",
                        "canonical_src": "snk/neogeo",
                        "local_base_path": "Systems/SNK/NeoGeo",
                    },
                ],
            }
        ],
    }


def _seed_projection_content(filestore: str) -> None:
    entries = [
        "Native/Canonical/roms/sony/playstation1/Final Fantasy VII.cue",
        "Native/Canonical/saves/sony/playstation1/memory.card",
        "Native/Canonical/savestates/sony/playstation1/state1.sav",
        "Native/Canonical/bios/sony/playstation1/scph1001.bin",
        "Native/Canonical/roms/snk/neogeo/metal_slug.zip",
    ]
    for rel in entries:
        full = os.path.join(filestore, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "wb") as handle:
            handle.write(b"x")


def test_projection_generates_mister_top_levels(tmp_path):
    filestore = str(tmp_path)
    _seed_projection_content(filestore)
    config = _build_projection_config(filestore)

    root_entries = parse_trans_path(config, "/mnt/transfs", "/mnt/transfs/MiSTer")

    assert set(root_entries) == {"games", "saves", "savestates", "BIOS"}


def test_projection_omits_systems_without_mapping(tmp_path):
    filestore = str(tmp_path)
    _seed_projection_content(filestore)
    config = _build_projection_config(filestore)

    games_entries = parse_trans_path(config, "/mnt/transfs", "/mnt/transfs/MiSTer/games")

    assert "PSX" in games_entries
    assert "NeoGeoUnmapped" not in games_entries


def test_projection_required_psx_paths_exist(tmp_path):
    filestore = str(tmp_path)
    _seed_projection_content(filestore)
    config = _build_projection_config(filestore)

    assert "PSX" in parse_trans_path(config, "/mnt/transfs", "/mnt/transfs/MiSTer/games")
    assert "PSX" in parse_trans_path(config, "/mnt/transfs", "/mnt/transfs/MiSTer/saves")
    assert "PSX" in parse_trans_path(config, "/mnt/transfs", "/mnt/transfs/MiSTer/savestates")
    assert "PSX" in parse_trans_path(config, "/mnt/transfs", "/mnt/transfs/MiSTer/BIOS")


def test_projection_path_resolution_to_canonical(tmp_path):
    filestore = str(tmp_path)
    _seed_projection_content(filestore)
    config = _build_projection_config(filestore)
    logger = logging.getLogger("test")

    resolved = get_source_path(
        logger,
        config,
        "/mnt/transfs",
        "/mnt/transfs/MiSTer/games/PSX/Final Fantasy VII.cue",
    )

    expected = os.path.join(filestore, "Native", "Canonical", "roms", "sony", "playstation1", "Final Fantasy VII.cue")
    assert os.path.normpath(str(resolved)) == os.path.normpath(expected)


def test_projection_alias_override_entries(tmp_path):
    filestore = str(tmp_path)
    _seed_projection_content(filestore)
    config = _build_projection_config(filestore)

    games_entries = parse_trans_path(config, "/mnt/transfs", "/mnt/transfs/MiSTer/games")

    assert "PlayStation" in games_entries
    assert "PS1" in games_entries


def test_projection_write_resolution(tmp_path):
    filestore = str(tmp_path)
    _seed_projection_content(filestore)
    config = _build_projection_config(filestore)
    logger = logging.getLogger("test")

    target = get_source_path_for_write(
        logger,
        config,
        "/mnt/transfs",
        "/mnt/transfs/MiSTer/savestates/PSX/new_state.sav",
    )

    expected = os.path.join(filestore, "Native", "Canonical", "savestates", "sony", "playstation1", "new_state.sav")
    assert os.path.normpath(str(target)) == os.path.normpath(expected)


def test_primary_smb_projection_root_detected(tmp_path):
    config = _build_projection_config(str(tmp_path))

    root = get_primary_smb_retronas_root(config)

    assert root == "MiSTer"
