from __future__ import annotations

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from metadata.catalog_utils import build_catalog_entries, build_index_from_entries


def test_build_catalog_entries_uses_rom_paths_and_game_metadata(tmp_path: Path):
    xml_path = tmp_path / "organizer.xml"
    xml_path.write_text(
        """
        <datafile>
          <game name="Acorn Atom">
            <description>Acorn Atom Collection</description>
            <manufacturer>Example Publisher</manufacturer>
            <year>1983</year>
            <rom name="Games/Action/Alien8.zip" sha1="abc123" crc="1a2b3c4d" />
            <rom name="Utilities/Toolkit/toolkit.rom" sha1="def456" crc="5e6f7788" />
          </game>
        </datafile>
        """.strip(),
        encoding="utf-8",
    )

    format_def = {
        "item_path": ".//game",
        "metadata": {
            "title": {"path": "description"},
            "publisher": {"path": "manufacturer"},
            "release_year": {"path": "year", "cast": "int"},
        },
        "match": {
            "filename": {"source": "@name", "normalize": "alnum_stem"},
            "checksums": [
                {"item_path": ".//rom", "name_attr": "name", "sha1_attr": "sha1", "crc_attr": "crc"}
            ],
        },
    }

    entries = build_catalog_entries(str(xml_path), format_def)

    assert len(entries) == 2
    assert entries[0].source_name == "Games/Action/Alien8.zip"
    assert entries[0].top_level_dir == "Games"
    assert entries[0].relative_dir == "Action"
    assert entries[0].extension == "ZIP"
    assert entries[0].metadata["title"] == "Acorn Atom Collection"
    assert entries[0].metadata["publisher"] == "Example Publisher"
    assert entries[0].metadata["release_year"] == 1983

    assert entries[1].source_name == "Utilities/Toolkit/toolkit.rom"
    assert entries[1].top_level_dir == "Utilities"
    assert entries[1].relative_dir == "Toolkit"
    assert entries[1].extension == "ROM"


def test_build_index_from_entries_indexes_name_and_checksums(tmp_path: Path):
    xml_path = tmp_path / "catalog.xml"
    xml_path.write_text(
        """
        <datafile>
          <game name="System">
            <description>Catalog</description>
            <rom name="Games/Foo Bar.zip" sha1="0011" crc="aa22" />
          </game>
        </datafile>
        """.strip(),
        encoding="utf-8",
    )

    format_def = {
        "item_path": ".//game",
        "metadata": {"title": {"path": "description"}},
        "match": {
            "filename": {"source": "@name", "normalize": "alnum_stem"},
            "checksums": [
                {"item_path": ".//rom", "name_attr": "name", "sha1_attr": "sha1", "crc_attr": "crc"}
            ],
        },
    }

    entries = build_catalog_entries(str(xml_path), format_def)
    index = build_index_from_entries(entries)

    assert index["by_name"]["foobar"]["metadata"]["title"] == "Catalog"
    assert index["by_sha1"]["0011"]["source_name"] == "Games/Foo Bar.zip"
    assert index["by_crc"]["aa22"]["source_name"] == "Games/Foo Bar.zip"
