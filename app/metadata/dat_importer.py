from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Optional

import yaml

from config import read_app_config, reload_config
from db.connection import get_cursor
from metadata.catalog_utils import CatalogEntry, build_catalog_entries, build_index_from_entries

DEFAULT_DAT_FOLDER = "/mnt/filestorefs/Native/DATs"


@dataclass
class DatImportRecord:
    dat_import_id: int
    source_path: str
    source_name: str
    xml_format: str
    file_size: int | None
    file_mtime: int | None
    file_sha1: str | None
    item_count: int
    imported_at: int
    status: str
    last_error: str | None = None


@dataclass
class GeneratedMap:
    name: str
    source_dir: str
    extensions: list[str]
    preserve_structure: bool = True
    supports_zip: bool = True


def _config_set_path(config_dir: str, category: str, filename: str) -> str:
    app_cfg = read_app_config(config_dir)
    source_set = app_cfg.get("config_sets", {}).get("active_source_config", "default")
    source_specific = os.path.join(config_dir, "metadata", category, f"{source_set}.yaml")
    if os.path.exists(source_specific):
        return source_specific
    return os.path.join(config_dir, "metadata", category, filename)


def _safe_slug(value: str, default: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", (value or "").strip())
    return slug.strip("._") or default


def _chunked_sha1(path: str, chunk_size: int = 1024 * 1024) -> str:
    sha1 = hashlib.sha1()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            sha1.update(block)
    return sha1.hexdigest().lower()


def _row_to_record(row: Any) -> DatImportRecord:
    if isinstance(row, dict):
        return DatImportRecord(**row)
    return DatImportRecord(
        dat_import_id=row[0],
        source_path=row[1],
        source_name=row[2],
        xml_format=row[3],
        file_size=row[4],
        file_mtime=row[5],
        file_sha1=row[6],
        item_count=row[7],
        imported_at=row[8],
        status=row[9],
        last_error=row[10] if len(row) > 10 else None,
    )


class DatImportService:
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self._import_index_cache: dict[int, dict[str, dict[str, dict[str, Any]]]] = {}

    def default_dat_folder(self) -> str:
        app_cfg = read_app_config(self.config_dir) or {}
        filestore = (app_cfg.get("filestore") or "/mnt/filestorefs").rstrip("/")
        return os.path.normpath(f"{filestore}/Native/DATs")

    def xml_formats(self) -> dict[str, dict[str, Any]]:
        formats_path = _config_set_path(self.config_dir, "xml_formats", "default.yaml")
        if not os.path.exists(formats_path):
            return {}
        with open(formats_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        return data.get("formats") or {}

    def get_xml_format(self, format_name: str) -> dict[str, Any]:
        formats = self.xml_formats()
        format_def = formats.get((format_name or "").lower())
        if not isinstance(format_def, dict):
            raise ValueError(f"Unknown xml_format: {format_name}")
        return format_def

    def ensure_schema(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS dat_imports (
                dat_import_id SERIAL PRIMARY KEY,
                source_path TEXT NOT NULL,
                source_name TEXT NOT NULL,
                xml_format TEXT NOT NULL,
                file_size BIGINT,
                file_mtime BIGINT,
                file_sha1 TEXT,
                item_count INTEGER NOT NULL DEFAULT 0,
                imported_at BIGINT NOT NULL,
                status TEXT NOT NULL DEFAULT 'completed',
                last_error TEXT,
                UNIQUE(source_path, xml_format)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS dat_import_entries (
                dat_import_entry_id SERIAL PRIMARY KEY,
                dat_import_id INTEGER NOT NULL REFERENCES dat_imports(dat_import_id) ON DELETE CASCADE,
                source_name TEXT NOT NULL,
                normalized_name TEXT NOT NULL,
                entry_path TEXT,
                top_level_dir TEXT,
                relative_dir TEXT,
                extension TEXT,
                sha1 TEXT,
                crc TEXT,
                title TEXT,
                publisher TEXT,
                release_year INTEGER,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_dat_import_entries_import_id ON dat_import_entries(dat_import_id)",
            "CREATE INDEX IF NOT EXISTS idx_dat_import_entries_name ON dat_import_entries(normalized_name)",
            "CREATE INDEX IF NOT EXISTS idx_dat_import_entries_sha1 ON dat_import_entries(sha1)",
            "CREATE INDEX IF NOT EXISTS idx_dat_import_entries_crc ON dat_import_entries(crc)",
        ]
        with get_cursor(commit=True) as cursor:
            for statement in statements:
                cursor.execute(statement)

    def list_dat_files(self, folder: Optional[str] = None) -> dict[str, Any]:
        self.ensure_schema()
        folder = os.path.normpath(folder or self.default_dat_folder())
        if not os.path.isdir(folder):
            return {"folder": folder, "files": [], "error": f"Folder does not exist: {folder}"}

        imports_by_path: dict[tuple[str, str], DatImportRecord] = {}
        with get_cursor() as cursor:
            cursor.execute(
                """
                SELECT dat_import_id, source_path, source_name, xml_format, file_size, file_mtime,
                       file_sha1, item_count, imported_at, status, last_error
                FROM dat_imports
                ORDER BY imported_at DESC
                """
            )
            for row in cursor.fetchall():
                record = _row_to_record(row)
                imports_by_path.setdefault((record.source_path, record.xml_format), record)

        files: list[dict[str, Any]] = []
        for root, _, filenames in os.walk(folder):
            for filename in filenames:
                if not filename.lower().endswith((".dat", ".xml")):
                    continue
                full_path = os.path.join(root, filename)
                stat_info = os.stat(full_path)
                matching_records = [
                    record for (path, _), record in imports_by_path.items()
                    if path == full_path
                ]
                if not matching_records:
                    status = "new"
                    imported = None
                else:
                    imported = matching_records[0]
                    status = (
                        "imported"
                        if imported.file_size == stat_info.st_size and imported.file_mtime == int(stat_info.st_mtime)
                        else "changed"
                    )
                files.append(
                    {
                        "path": full_path,
                        "filename": filename,
                        "size": stat_info.st_size,
                        "mtime": int(stat_info.st_mtime),
                        "status": status,
                        "suggested": status in {"new", "changed"},
                        "imports": [asdict(record) for record in matching_records],
                    }
                )

        files.sort(key=lambda item: (0 if item["suggested"] else 1, item["filename"].lower()))
        return {
            "folder": folder,
            "default_folder": self.default_dat_folder(),
            "files": files,
        }

    def list_imports(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with get_cursor() as cursor:
            cursor.execute(
                """
                SELECT dat_import_id, source_path, source_name, xml_format, file_size, file_mtime,
                       file_sha1, item_count, imported_at, status, last_error
                FROM dat_imports
                ORDER BY imported_at DESC, source_name ASC
                """
            )
            return [asdict(_row_to_record(row)) for row in cursor.fetchall()]

    def import_dat(
        self,
        dat_path: str,
        xml_format: str,
        log_callback: Optional[Callable[[str], None]] = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        dat_path = os.path.normpath(dat_path)
        if not os.path.isfile(dat_path):
            raise ValueError(f"DAT/XML file does not exist: {dat_path}")

        format_name = (xml_format or "").lower().strip()
        format_def = self.get_xml_format(format_name)
        stat_info = os.stat(dat_path)
        file_sha1 = _chunked_sha1(dat_path)
        now = int(time.time())

        def emit(message: str) -> None:
            if log_callback:
                log_callback(message)

        emit(f"Opening DAT/XML file: {dat_path}")
        emit(f"Using xml_format: {format_name}")
        emit(f"File size: {stat_info.st_size} bytes; modified: {int(stat_info.st_mtime)}")
        emit("Parsing catalog entries…")

        entries = build_catalog_entries(dat_path, format_def)
        emit(f"Discovered {len(entries)} catalog entries")

        with get_cursor(commit=True) as cursor:
            cursor.execute(
                """
                INSERT INTO dat_imports (
                    source_path, source_name, xml_format, file_size, file_mtime,
                    file_sha1, item_count, imported_at, status, last_error
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'running', NULL)
                ON CONFLICT (source_path, xml_format) DO UPDATE SET
                    source_name = EXCLUDED.source_name,
                    file_size = EXCLUDED.file_size,
                    file_mtime = EXCLUDED.file_mtime,
                    file_sha1 = EXCLUDED.file_sha1,
                    item_count = EXCLUDED.item_count,
                    imported_at = EXCLUDED.imported_at,
                    status = 'running',
                    last_error = NULL
                RETURNING dat_import_id
                """,
                (
                    dat_path,
                    os.path.basename(dat_path),
                    format_name,
                    stat_info.st_size,
                    int(stat_info.st_mtime),
                    file_sha1,
                    len(entries),
                    now,
                ),
            )
            row = cursor.fetchone()
            dat_import_id = row["dat_import_id"] if isinstance(row, dict) else row[0]
            cursor.execute("DELETE FROM dat_import_entries WHERE dat_import_id = %s", (dat_import_id,))

            for index, entry in enumerate(entries, start=1):
                cursor.execute(
                    """
                    INSERT INTO dat_import_entries (
                        dat_import_id, source_name, normalized_name, entry_path, top_level_dir,
                        relative_dir, extension, sha1, crc, title, publisher, release_year, metadata_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        dat_import_id,
                        entry.source_name,
                        entry.normalized_name,
                        entry.source_name,
                        entry.top_level_dir,
                        entry.relative_dir,
                        entry.extension,
                        entry.sha1,
                        entry.crc,
                        entry.metadata.get("title"),
                        entry.metadata.get("publisher"),
                        entry.metadata.get("release_year"),
                        json.dumps(entry.metadata, sort_keys=True),
                    ),
                )
                if index <= 50:
                    emit(
                        f"[{index}/{len(entries)}] Imported {entry.source_name}"
                        f" -> {entry.metadata.get('title') or entry.source_name}"
                    )
                elif index % 250 == 0:
                    emit(f"Progress: imported {index} / {len(entries)} entries")

            cursor.execute(
                "UPDATE dat_imports SET status = 'completed', last_error = NULL WHERE dat_import_id = %s",
                (dat_import_id,),
            )

        self._import_index_cache.pop(dat_import_id, None)
        emit(f"DAT import complete. Wrote {len(entries)} entries to the database.")
        return {
            "dat_import_id": dat_import_id,
            "source_path": dat_path,
            "xml_format": format_name,
            "item_count": len(entries),
            "file_sha1": file_sha1,
            "imported_at": now,
        }

    def mark_import_failed(self, dat_path: str, xml_format: str, error_message: str) -> None:
        self.ensure_schema()
        with get_cursor(commit=True) as cursor:
            cursor.execute(
                """
                UPDATE dat_imports
                SET status = 'failed', last_error = %s, imported_at = %s
                WHERE source_path = %s AND xml_format = %s
                """,
                (error_message[:4000], int(time.time()), os.path.normpath(dat_path), (xml_format or "").lower().strip()),
            )

    def imported_providers(self) -> list[dict[str, Any]]:
        providers: list[dict[str, Any]] = []
        for record in self.list_imports():
            if record.get("status") != "completed":
                continue
            providers.append(
                {
                    "id": f"imported_dat:{record['dat_import_id']}",
                    "name": f"Imported DAT: {record['source_name']} ({record['xml_format']})",
                    "kind": "imported_dat_lookup",
                    "config": record,
                }
            )
        return providers

    def imported_index(self, dat_import_id: int) -> dict[str, dict[str, dict[str, Any]]]:
        if dat_import_id in self._import_index_cache:
            return self._import_index_cache[dat_import_id]

        self.ensure_schema()
        entries: list[CatalogEntry] = []
        with get_cursor() as cursor:
            cursor.execute(
                """
                SELECT source_name, normalized_name, sha1, crc, metadata_json,
                       top_level_dir, relative_dir, extension
                FROM dat_import_entries
                WHERE dat_import_id = %s
                ORDER BY dat_import_entry_id ASC
                """,
                (dat_import_id,),
            )
            for row in cursor.fetchall():
                if isinstance(row, dict):
                    source_name = row["source_name"]
                    normalized_name = row["normalized_name"]
                    sha1 = row["sha1"]
                    crc = row["crc"]
                    metadata_json = row["metadata_json"]
                    top_level_dir = row["top_level_dir"]
                    relative_dir = row["relative_dir"]
                    extension = row["extension"]
                else:
                    source_name, normalized_name, sha1, crc, metadata_json, top_level_dir, relative_dir, extension = row
                entries.append(
                    CatalogEntry(
                        source_name=source_name,
                        normalized_name=normalized_name,
                        metadata=json.loads(metadata_json or "{}"),
                        sha1=sha1,
                        crc=crc,
                        top_level_dir=top_level_dir,
                        relative_dir=relative_dir,
                        extension=extension,
                    )
                )

        index = build_index_from_entries(entries)
        self._import_index_cache[dat_import_id] = index
        return index

    def generate_client_config(
        self,
        dat_import_id: int,
        config_set_name: str,
        system_name: str,
        client_name: str = "MiSTer",
        manufacturer: str = "Imported",
        system_mapping_name: Optional[str] = None,
        local_base_path: Optional[str] = None,
        output_filename: Optional[str] = None,
    ) -> dict[str, Any]:
        self.ensure_schema()
        config_set = _safe_slug(config_set_name, "imported")
        client_basename = _safe_slug(output_filename or f"{client_name.lower()}.yaml", "client.yaml")
        if not client_basename.lower().endswith(".yaml"):
            client_basename = f"{client_basename}.yaml"

        system_mapping_name = (system_mapping_name or system_name).strip()
        manufacturer = (manufacturer or "Imported").strip() or "Imported"
        local_base_path = (local_base_path or f"{manufacturer}/{system_mapping_name}").replace("\\", "/").strip("/")

        groups: dict[str, set[str]] = {}
        root_extensions: set[str] = set()
        with get_cursor() as cursor:
            cursor.execute(
                """
            SELECT source_name, top_level_dir, relative_dir, extension
                FROM dat_import_entries
                WHERE dat_import_id = %s
                ORDER BY source_name ASC
                """,
                (dat_import_id,),
            )
            rows = cursor.fetchall()

        if not rows:
            raise ValueError(f"No imported DAT entries found for import_id={dat_import_id}")

        for row in rows:
            if isinstance(row, dict):
                top_level = row["top_level_dir"]
                relative_dir = row.get("relative_dir")
                extension = (row["extension"] or "ZIP").upper()
            else:
                _, top_level, relative_dir, extension = row
                extension = (extension or "ZIP").upper()
            if top_level:
                map_name = top_level
                if relative_dir:
                    map_name = f"{top_level}/{str(relative_dir).strip('/')}"
                groups.setdefault(map_name, set()).add(extension)
            else:
                root_extensions.add(extension)

        generated_maps: list[GeneratedMap] = []
        for map_path, extensions in sorted(groups.items(), key=lambda item: item[0].lower()):
            generated_maps.append(
                GeneratedMap(
                    name=map_path,
                    source_dir=f"Software/Sources/{map_path}",
                    extensions=sorted(extensions),
                )
            )
        if root_extensions:
            generated_maps.append(
                GeneratedMap(
                    name="Root",
                    source_dir="Software/Sources",
                    extensions=sorted(root_extensions),
                )
            )

        config_rel_dir = os.path.join(self.config_dir, "clients", config_set)
        os.makedirs(config_rel_dir, exist_ok=True)
        output_path = os.path.join(config_rel_dir, client_basename)

        if os.path.exists(output_path):
            with open(output_path, "r", encoding="utf-8") as handle:
                client_config = yaml.safe_load(handle) or {}
        else:
            client_config = {}

        if not isinstance(client_config, dict):
            client_config = {}
        client_config.setdefault("name", client_name)
        client_config.setdefault("download_layout", "source_based")
        client_config.setdefault("default_target_path", "{name}/{system_name}/{maps}")
        systems = client_config.get("systems") or []
        systems = [system for system in systems if system.get("name") != system_name]
        systems.append(
            {
                "name": system_name,
                "manufacturer": manufacturer,
                "system_mapping_name": system_mapping_name,
                "local_base_path": local_base_path,
                "maps": [
                    {
                        generated_map.name: {
                            "query": {
                                "source_dir": generated_map.source_dir,
                                "extensions": generated_map.extensions,
                                "preserve_structure": generated_map.preserve_structure,
                                "supports_zip": generated_map.supports_zip,
                            }
                        }
                    }
                    for generated_map in generated_maps
                ],
            }
        )
        client_config["systems"] = sorted(systems, key=lambda system: system.get("name", "").lower())

        with open(output_path, "w", encoding="utf-8") as handle:
            yaml.dump(client_config, handle, sort_keys=False, default_flow_style=False)

        reload_config()
        return {
            "config_set_name": config_set,
            "client_name": client_name,
            "system_name": system_name,
            "output_path": output_path,
            "maps_generated": [asdict(item) for item in generated_maps],
            "config_preview": yaml.dump(client_config, sort_keys=False, default_flow_style=False),
        }
