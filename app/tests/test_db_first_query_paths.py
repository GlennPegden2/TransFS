"""Unit tests for DB-first query-map path helpers."""

from vfs.dirlisting import _extract_relative_path
from vfs.pathutils import derive_query_map_relative_dir


def test_extract_relative_path_with_source_dir_anchor():
    source_path = "/mnt/filestorefs/Native/Acorn/Atom/Software/Sources/hoglet67/AA/GALAXIAN.ATM"
    relative = _extract_relative_path(
        source_path=source_path,
        source_dir="Software",
        local_base_path="Acorn/Atom",
    )
    assert relative == "Sources/hoglet67/AA"


def test_extract_relative_path_without_source_dir_uses_local_base_anchor():
    source_path = "/mnt/filestorefs/Native/Collections/NES/Community/SetA/game.nes"
    relative = _extract_relative_path(
        source_path=source_path,
        source_dir=None,
        local_base_path="Collections/NES",
    )
    assert relative == "Community/SetA"


def test_extract_relative_path_returns_empty_when_no_anchor_found():
    source_path = "/mnt/other/location/file.bin"
    relative = _extract_relative_path(
        source_path=source_path,
        source_dir=None,
        local_base_path="Collections/NES",
    )
    assert relative == ""


def test_extract_relative_path_without_source_dir_handles_zip_marker_source():
    source_path = "/mnt/filestorefs/Native/Collections/NES/Community/SetA/game.7z#ZIP#disk1/game.nes"
    relative = _extract_relative_path(
        source_path=source_path,
        source_dir=None,
        local_base_path="Collections/NES",
    )
    # _extract_relative_path treats source_path as a plain path string; callers
    # that pass #ZIP# source paths should strip archive markers first.
    assert relative == "Community/SetA/game.7z#ZIP#disk1"


def test_derive_query_map_relative_dir_with_source_dir_anchor():
    relative_dir = derive_query_map_relative_dir(
        relative_path="Software/Sources/hoglet67/AA/GALAXIAN.ATM",
        map_source_dir="Software",
    )
    assert relative_dir == "Sources/hoglet67/AA"


def test_derive_query_map_relative_dir_without_source_dir_anchor():
    relative_dir = derive_query_map_relative_dir(
        relative_path="Community/SetA/game.nes",
        map_source_dir=None,
    )
    assert relative_dir == "Community/SetA"


def test_derive_query_map_relative_dir_returns_empty_when_anchor_mismatch():
    relative_dir = derive_query_map_relative_dir(
        relative_path="OtherRoot/SetA/game.nes",
        map_source_dir="Software",
    )
    assert relative_dir == ""
