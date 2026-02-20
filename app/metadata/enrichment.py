"""
Metadata enrichment for files.

Builds normalized metadata records from filename parsing, map context, and
optional pack/ruleset overrides.
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from typing import Optional, Dict, Any, Iterable

from .parser import parse_filename


@dataclass
class PackContext:
    """Optional pack-level metadata context."""
    pack_name: Optional[str] = None
    ruleset: Optional[str] = None
    ruleset_overrides: Optional[dict] = None
    defaults: Optional[dict] = None
    tags: Optional[list[str]] = None


MEDIA_TYPE_MAP = {
    "FDS": "Floppy",
    "HDS": "HardDisk",
    "ROMS": "ROM",
    "TAPES": "Tape",
}


def _normalize_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _ensure_lookup(conn: sqlite3.Connection, table: str, name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    cursor = conn.cursor()
    cursor.execute(f"SELECT id FROM {table} WHERE name = ?", (name,))
    row = cursor.fetchone()
    if row:
        return row[0]
    cursor.execute(f"INSERT INTO {table} (name) VALUES (?)", (name,))
    return cursor.lastrowid


def _extract_release_date(filename: str) -> tuple[Optional[str], Optional[int], Optional[str]]:
    """
    Extract release date from filename when possible.

    Supports:
    - YYYY
    - YYYY-MM
    - YYYY-MM-DD
    - YYYY.MM.DD
    """
    match = re.search(r"\b(19\d{2}|20\d{2})([-.](0[1-9]|1[0-2]))?([-.](0[1-9]|[12]\d|3[01]))?\b", filename)
    if not match:
        return None, None, None

    year = int(match.group(1))
    month = match.group(2)
    day = match.group(4)

    if month and day:
        normalized = f"{match.group(1)}-{match.group(3)}-{match.group(5)}"
        return normalized, year, "day"
    if month:
        normalized = f"{match.group(1)}-{match.group(3)}"
        return normalized, year, "month"
    return None, year, "year"


def _collect_languages(parsed_language: Optional[str]) -> list[str]:
    if not parsed_language:
        return []
    return [lang.strip() for lang in parsed_language.split(",") if lang.strip()]


def _upsert_file_tags(
    conn: sqlite3.Connection,
    file_id: int,
    tags: Iterable[tuple[str, str]],
) -> None:
    cursor = conn.cursor()
    for tag_type, tag_value in tags:
        cursor.execute(
            "INSERT OR IGNORE INTO file_tags (file_id, tag_type, tag_value) VALUES (?, ?, ?)",
            (file_id, tag_type, tag_value),
        )


def enrich_file_metadata(
    conn: sqlite3.Connection,
    file_info: Dict[str, Any],
    pack_context: Optional[PackContext] = None,
) -> None:
    """
    Upsert normalized metadata for a file.

    Args:
        conn: Active SQLite connection
        file_info: Dict with file fields (file_id, filename, extension, map_name, virtual_path, size)
        pack_context: Optional pack-level defaults and ruleset info
    """
    file_id = file_info["file_id"]
    filename = file_info.get("filename") or ""
    map_name = (file_info.get("map_name") or "").upper()
    virtual_path = file_info.get("virtual_path")
    extension = file_info.get("extension")
    size = file_info.get("size")

    parsed = parse_filename(filename)
    title = parsed.title

    media_type = MEDIA_TYPE_MAP.get(map_name)
    region = _normalize_value(parsed.region)
    languages = _collect_languages(parsed.language)
    language = languages[0] if languages else None

    if pack_context and pack_context.defaults:
        defaults = pack_context.defaults
        media_type = _normalize_value(defaults.get("media_type")) or media_type
        region = _normalize_value(defaults.get("region")) or region
        default_language = _normalize_value(defaults.get("language"))
        if default_language and not language:
            language = default_language
        default_genre = _normalize_value(defaults.get("genre"))
        default_app_type = _normalize_value(defaults.get("app_type"))
        default_publisher = _normalize_value(defaults.get("publisher"))
    else:
        default_genre = None
        default_app_type = None
        default_publisher = None

    release_date, release_year, release_precision = _extract_release_date(filename)
    if not release_year and parsed.year:
        release_year = parsed.year
        release_precision = "year"

    publisher = _normalize_value(parsed.publisher) or default_publisher

    media_type_id = _ensure_lookup(conn, "media_types", media_type)
    region_id = _ensure_lookup(conn, "regions", region)
    language_id = _ensure_lookup(conn, "languages", language)
    genre_id = _ensure_lookup(conn, "genres", default_genre)
    app_type_id = _ensure_lookup(conn, "app_types", default_app_type)
    publisher_id = _ensure_lookup(conn, "publishers", publisher)

    is_revision = bool(parsed.version)

    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT INTO file_metadata (
            file_id, transfs_path, extension, title, media_type_id, region_id, language_id,
            genre_id, app_type_id, publisher_id, release_date, release_year,
            release_precision, rom_size, is_revision, is_prototype, is_homebrew
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(file_id) DO UPDATE SET
            transfs_path = excluded.transfs_path,
            extension = excluded.extension,
            title = excluded.title,
            media_type_id = excluded.media_type_id,
            region_id = excluded.region_id,
            language_id = excluded.language_id,
            genre_id = excluded.genre_id,
            app_type_id = excluded.app_type_id,
            publisher_id = excluded.publisher_id,
            release_date = excluded.release_date,
            release_year = excluded.release_year,
            release_precision = excluded.release_precision,
            rom_size = excluded.rom_size,
            is_revision = excluded.is_revision,
            is_prototype = excluded.is_prototype,
            is_homebrew = excluded.is_homebrew
        """,
        (
            file_id,
            virtual_path,
            extension,
            title,
            media_type_id,
            region_id,
            language_id,
            genre_id,
            app_type_id,
            publisher_id,
            release_date,
            release_year,
            release_precision,
            size,
            1 if is_revision else 0,
            1 if parsed.is_prototype else 0,
            1 if parsed.is_homebrew else 0,
        ),
    )

    tag_entries = []
    for tag in parsed.tags:
        tag_entries.append(("filename_tag", tag))
    for extra_lang in languages[1:]:
        tag_entries.append(("language_alt", extra_lang))

    if pack_context and pack_context.tags:
        for tag in pack_context.tags:
            tag_entries.append(("pack_tag", tag))

    if tag_entries:
        _upsert_file_tags(conn, file_id, tag_entries)

    if pack_context and pack_context.pack_name:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT OR IGNORE INTO packs (name, ruleset, ruleset_overrides) VALUES (?, ?, ?)",
            (
                pack_context.pack_name,
                pack_context.ruleset,
                str(pack_context.ruleset_overrides) if pack_context.ruleset_overrides else None,
            ),
        )
        cursor.execute("SELECT pack_id FROM packs WHERE name = ?", (pack_context.pack_name,))
        pack_row = cursor.fetchone()
        if pack_row:
            cursor.execute(
                "INSERT OR IGNORE INTO file_packs (file_id, pack_id) VALUES (?, ?)",
                (file_id, pack_row[0]),
            )
