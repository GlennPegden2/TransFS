"""Metadata provider subsystem for folder scans and metadata enrichment."""
from __future__ import annotations

import binascii
import hashlib
import os
import time
from dataclasses import dataclass
from typing import Any, Optional

import yaml

from config import read_app_config
from db.connection import get_cursor
from metadata.catalog_utils import build_catalog_entries, build_index_from_entries, normalize_name
from metadata.dat_importer import DatImportService
from metadata.parser import parse_filename
from metadata.rulesets import RulesetRegistry


def _chunked_sha1_crc(path: str, chunk_size: int = 1024 * 1024) -> tuple[str, str]:
    sha1 = hashlib.sha1()
    crc = 0
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk_size)
            if not block:
                break
            sha1.update(block)
            crc = binascii.crc32(block, crc)
    return sha1.hexdigest().lower(), f"{crc & 0xFFFFFFFF:08x}"


def _ensure_lookup(table: str, name: Optional[str]) -> Optional[int]:
    if not name:
        return None
    with get_cursor(commit=True) as cursor:
        cursor.execute(
            f"INSERT INTO {table} (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id",
            (name,)
        )
        result = cursor.fetchone()
        if result:
            return result["id"] if isinstance(result, dict) else result[0]
        cursor.execute(f"SELECT id FROM {table} WHERE name = %s", (name,))
        row = cursor.fetchone()
        return row["id"] if isinstance(row, dict) else row[0] if row else None


def _ensure_file_metadata_provenance_columns() -> None:
    with get_cursor(commit=True) as cursor:
        cursor.execute("ALTER TABLE file_metadata ADD COLUMN IF NOT EXISTS metadata_provider TEXT")
        cursor.execute("ALTER TABLE file_metadata ADD COLUMN IF NOT EXISTS metadata_source TEXT")
        cursor.execute("ALTER TABLE file_metadata ADD COLUMN IF NOT EXISTS metadata_applied_at BIGINT")


def _config_set_path(config_dir: str, category: str, filename: str) -> str:
    app_cfg = read_app_config(config_dir)
    source_set = app_cfg.get("config_sets", {}).get("active_source_config", "default")
    source_specific = os.path.join(config_dir, "metadata", category, f"{source_set}.yaml")
    if os.path.exists(source_specific):
        return source_specific
    return os.path.join(config_dir, "metadata", category, filename)


@dataclass
class MetadataProvider:
    id: str
    name: str
    kind: str
    config: dict[str, Any]


@dataclass
class ScanMatch:
    file_path: str
    filename: str
    matched: bool
    metadata: dict[str, Any]
    match_method: Optional[str] = None
    provider_source: Optional[str] = None


class MetadataProviderRegistry:
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self._ruleset_registry = RulesetRegistry(config_dir=config_dir)

    def _providers_path(self) -> str:
        return _config_set_path(self.config_dir, "providers", "default.yaml")

    def list_providers(self) -> list[MetadataProvider]:
        providers: list[MetadataProvider] = []
        rulesets = self._ruleset_registry.load_all()
        for ruleset_name, ruleset in sorted(rulesets.items()):
            providers.append(
                MetadataProvider(
                    id=f"filename:{ruleset_name.lower()}",
                    name=f"Filename Ruleset: {ruleset.name}",
                    kind="filename_ruleset",
                    config={"ruleset": ruleset_name, "version": ruleset.version},
                )
            )

        providers_file = self._providers_path()
        if os.path.exists(providers_file):
            with open(providers_file, "r", encoding="utf-8") as handle:
                data = yaml.safe_load(handle) or {}
            for entry in data.get("providers", []):
                provider_id = entry.get("id")
                kind = entry.get("kind")
                if not provider_id or not kind:
                    continue
                providers.append(
                    MetadataProvider(
                        id=provider_id,
                        name=entry.get("name", provider_id),
                        kind=kind,
                        config=entry,
                    )
                )

        try:
            importer = DatImportService(config_dir=self.config_dir)
            for entry in importer.imported_providers():
                providers.append(
                    MetadataProvider(
                        id=entry["id"],
                        name=entry["name"],
                        kind=entry["kind"],
                        config=entry.get("config") or {},
                    )
                )
        except Exception:
            pass
        return providers

    def get_provider(self, provider_id: str) -> Optional[MetadataProvider]:
        for provider in self.list_providers():
            if provider.id == provider_id:
                return provider
        return None


class MetadataScanService:
    def __init__(self, config_dir: str = "config"):
        self.config_dir = config_dir
        self.registry = MetadataProviderRegistry(config_dir=config_dir)
        self._importer = DatImportService(config_dir=config_dir)
        self._resolved_dat_xml_paths: dict[str, Optional[str]] = {}

    def _xml_formats_path(self) -> str:
        return _config_set_path(self.config_dir, "xml_formats", "default.yaml")

    def _load_xml_format(self, format_name: str) -> Optional[dict[str, Any]]:
        formats_path = self._xml_formats_path()
        if not os.path.exists(formats_path):
            return None
        with open(formats_path, "r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle) or {}
        formats = data.get("formats") or {}
        format_def = formats.get(format_name)
        return format_def if isinstance(format_def, dict) else None

    def scan_folder(self, folder: str, provider_id: str, recursive: bool = True, limit: int = 200) -> dict[str, Any]:
        provider = self.registry.get_provider(provider_id)
        if not provider:
            raise ValueError(f"Unknown metadata provider: {provider_id}")
        if not os.path.isdir(folder):
            raise ValueError(f"Folder does not exist: {folder}")

        files = self._enumerate_files(folder, recursive=recursive)
        matches: list[ScanMatch] = []
        matched_count = 0
        scanned_count = 0
        result_limit = max(limit, 1)
        for file_path in files:
            scanned_count += 1
            outcome = self._match_file(provider, file_path)
            if not outcome or not outcome.matched:
                continue
            matched_count += 1
            if len(matches) < result_limit:
                matches.append(outcome)
            if len(matches) >= result_limit:
                break

        return {
            "provider": {
                "id": provider.id,
                "name": provider.name,
                "kind": provider.kind,
            },
            "folder": folder,
            "recursive": recursive,
            "files_scanned": scanned_count,
            "matches_found": matched_count,
            "results": [
                {
                    "file_path": m.file_path,
                    "filename": m.filename,
                    "matched": m.matched,
                    "metadata": m.metadata,
                    "match_method": m.match_method,
                    "provider_source": m.provider_source,
                }
                for m in matches
            ],
        }

    def _resolve_dat_xml_path(self, configured_path: Optional[str]) -> Optional[str]:
        if not configured_path:
            return None

        cached = self._resolved_dat_xml_paths.get(configured_path)
        if cached is not None:
            return cached

        if os.path.exists(configured_path):
            self._resolved_dat_xml_paths[configured_path] = configured_path
            return configured_path

        xml_basename = os.path.basename(configured_path)
        if not xml_basename:
            self._resolved_dat_xml_paths[configured_path] = ""
            return None

        try:
            from config import read_app_config
            _app_cfg = read_app_config()
            _filestore = _app_cfg.get("filestore", "/data/retronas")
        except Exception:  # pylint: disable=broad-except
            _filestore = "/data/retronas"
        _native = _filestore + "/Native"

        candidate_paths = [
            os.path.join(_native, "Clients/Mame/mame_cache", xml_basename),
            os.path.join(_native, "Clients/MAME/mame_cache", xml_basename),
            os.path.join(_native, "Clients/RetroBat/bios/mame/hash", xml_basename),
        ]
        for candidate in candidate_paths:
            if os.path.exists(candidate):
                self._resolved_dat_xml_paths[configured_path] = candidate
                return candidate

        native_root = _native
        if os.path.isdir(native_root):
            for root, _, filenames in os.walk(native_root):
                if xml_basename in filenames and "/mame/hash" in root.replace("\\", "/").lower():
                    resolved = os.path.join(root, xml_basename)
                    self._resolved_dat_xml_paths[configured_path] = resolved
                    return resolved

        self._resolved_dat_xml_paths[configured_path] = ""
        return None

    def apply_scan_results(self, folder: str, provider_id: str, recursive: bool = True, limit: int = 2000) -> dict[str, Any]:
        _ensure_file_metadata_provenance_columns()
        preview = self.scan_folder(folder, provider_id=provider_id, recursive=recursive, limit=limit)
        applied = 0
        skipped = 0
        errors: list[str] = []

        for result in preview["results"]:
            if not result.get("matched"):
                skipped += 1
                continue
            try:
                updated = self._apply_to_database(
                    file_path=result["file_path"],
                    metadata=result.get("metadata") or {},
                    provider_id=provider_id,
                    provider_source=result.get("provider_source"),
                )
                if updated:
                    applied += 1
                else:
                    skipped += 1
            except Exception as exc:  # pylint: disable=broad-except
                errors.append(f"{result['file_path']}: {exc}")

        return {
            "provider_id": provider_id,
            "folder": folder,
            "files_scanned": preview.get("files_scanned", 0),
            "matches_found": preview.get("matches_found", 0),
            "applied": applied,
            "skipped": skipped,
            "errors": errors,
        }

    def _enumerate_files(self, folder: str, recursive: bool) -> list[str]:
        collected: list[str] = []
        if recursive:
            for root, _, filenames in os.walk(folder):
                for filename in filenames:
                    collected.append(os.path.join(root, filename))
        else:
            for name in os.listdir(folder):
                candidate = os.path.join(folder, name)
                if os.path.isfile(candidate):
                    collected.append(candidate)
        return collected

    def _match_file(self, provider: MetadataProvider, file_path: str) -> Optional[ScanMatch]:
        if provider.kind == "filename_ruleset":
            return self._match_filename_ruleset(provider, file_path)
        if provider.kind == "dat_xml_lookup":
            return self._match_dat_xml(provider, file_path)
        if provider.kind == "imported_dat_lookup":
            return self._match_imported_dat(provider, file_path)
        return None

    def _match_filename_ruleset(self, provider: MetadataProvider, file_path: str) -> ScanMatch:
        filename = os.path.basename(file_path)
        parsed = parse_filename(filename)
        metadata = {
            "title": parsed.title,
            "release_year": parsed.year,
            "publisher": parsed.publisher,
            "region": parsed.region,
            "language": parsed.language,
            "tags": parsed.tags,
            "is_prototype": parsed.is_prototype,
            "is_homebrew": parsed.is_homebrew,
        }
        matched = bool(parsed.title or parsed.publisher or parsed.year or parsed.tags)
        return ScanMatch(
            file_path=file_path,
            filename=filename,
            matched=matched,
            metadata={k: v for k, v in metadata.items() if v not in (None, "", [])},
            match_method="filename",
            provider_source=provider.config.get("ruleset"),
        )

    def _match_dat_xml(self, provider: MetadataProvider, file_path: str) -> Optional[ScanMatch]:
        configured_xml_path = provider.config.get("xml_path") or provider.config.get("dat_path")
        xml_path = self._resolve_dat_xml_path(configured_xml_path)
        xml_format = (provider.config.get("format") or "mame_softwarelist").lower()
        checksum_fallback = bool(provider.config.get("checksum_fallback", False))
        if not xml_path:
            return ScanMatch(
                file_path=file_path,
                filename=os.path.basename(file_path),
                matched=False,
                metadata={},
                match_method="missing_dat_xml",
                provider_source=configured_xml_path,
            )

        format_def = self._load_xml_format(xml_format)
        if not format_def:
            return ScanMatch(
                file_path=file_path,
                filename=os.path.basename(file_path),
                matched=False,
                metadata={},
                match_method="unsupported_format",
                provider_source=xml_format,
            )

        index = _build_xml_index(xml_path, format_def)
        filename = os.path.basename(file_path)
        normalized = normalize_name(filename)
        by_name = index["by_name"].get(normalized)
        if by_name:
            return ScanMatch(
                file_path=file_path,
                filename=filename,
                matched=True,
                metadata=by_name["metadata"],
                match_method="filename",
                provider_source=xml_path,
            )

        if checksum_fallback:
            sha1, crc = _chunked_sha1_crc(file_path)
            by_checksum = index["by_sha1"].get(sha1) or index["by_crc"].get(crc)
            if by_checksum:
                return ScanMatch(
                    file_path=file_path,
                    filename=filename,
                    matched=True,
                    metadata=by_checksum["metadata"],
                    match_method="checksum",
                    provider_source=xml_path,
                )

        return ScanMatch(
            file_path=file_path,
            filename=filename,
            matched=False,
            metadata={},
            match_method="no_match",
            provider_source=xml_path,
        )

    def _match_imported_dat(self, provider: MetadataProvider, file_path: str) -> ScanMatch:
        import_id = provider.config.get("dat_import_id") or provider.config.get("config", {}).get("dat_import_id") or provider.config.get("dat_import_id")
        checksum_fallback = bool(provider.config.get("checksum_fallback", False))
        if not import_id:
            return ScanMatch(
                file_path=file_path,
                filename=os.path.basename(file_path),
                matched=False,
                metadata={},
                match_method="missing_import_id",
                provider_source=None,
            )

        index = self._importer.imported_index(int(import_id))
        filename = os.path.basename(file_path)
        normalized = normalize_name(filename)
        by_name = index["by_name"].get(normalized)
        if by_name:
            return ScanMatch(
                file_path=file_path,
                filename=filename,
                matched=True,
                metadata=by_name["metadata"],
                match_method="filename",
                provider_source=provider.config.get("source_path"),
            )

        if checksum_fallback:
            sha1, crc = _chunked_sha1_crc(file_path)
            by_checksum = index["by_sha1"].get(sha1) or index["by_crc"].get(crc)
            if by_checksum:
                return ScanMatch(
                    file_path=file_path,
                    filename=filename,
                    matched=True,
                    metadata=by_checksum["metadata"],
                    match_method="checksum",
                    provider_source=provider.config.get("source_path"),
                )

        return ScanMatch(
            file_path=file_path,
            filename=filename,
            matched=False,
            metadata={},
            match_method="no_match",
            provider_source=provider.config.get("source_path"),
        )

    def _apply_to_database(self, file_path: str, metadata: dict[str, Any], provider_id: str, provider_source: Optional[str]) -> bool:
        now = int(time.time())
        with get_cursor(commit=True) as cursor:
            cursor.execute(
                """
                SELECT f.file_id
                FROM files f
                LEFT JOIN virtual_mappings vm ON vm.file_id = f.file_id
                WHERE f.source_path = %s OR vm.virtual_path = %s
                LIMIT 1
                """,
                (file_path, file_path),
            )
            file_row = cursor.fetchone()
            if not file_row:
                return False

            file_id = file_row["file_id"] if isinstance(file_row, dict) else file_row[0]
            region_id = _ensure_lookup("regions", metadata.get("region"))
            language_id = _ensure_lookup("languages", metadata.get("language"))
            publisher_id = _ensure_lookup("publishers", metadata.get("publisher"))

            cursor.execute(
                """
                INSERT INTO file_metadata (
                    file_id,
                    transfs_path,
                    title,
                    release_year,
                    region_id,
                    language_id,
                    publisher_id,
                    is_prototype,
                    is_homebrew,
                    metadata_provider,
                    metadata_source,
                    metadata_applied_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT(file_id) DO UPDATE SET
                    title = COALESCE(excluded.title, file_metadata.title),
                    release_year = COALESCE(excluded.release_year, file_metadata.release_year),
                    region_id = COALESCE(excluded.region_id, file_metadata.region_id),
                    language_id = COALESCE(excluded.language_id, file_metadata.language_id),
                    publisher_id = COALESCE(excluded.publisher_id, file_metadata.publisher_id),
                    is_prototype = COALESCE(excluded.is_prototype, file_metadata.is_prototype),
                    is_homebrew = COALESCE(excluded.is_homebrew, file_metadata.is_homebrew),
                    metadata_provider = excluded.metadata_provider,
                    metadata_source = excluded.metadata_source,
                    metadata_applied_at = excluded.metadata_applied_at
                """,
                (
                    file_id,
                    file_path if file_path.startswith("/mnt/transfs") else None,
                    metadata.get("title"),
                    metadata.get("release_year"),
                    region_id,
                    language_id,
                    publisher_id,
                    metadata.get("is_prototype"),
                    metadata.get("is_homebrew"),
                    provider_id,
                    provider_source,
                    now,
                ),
            )

            tags = metadata.get("tags") or []
            for tag in tags:
                cursor.execute(
                    "INSERT INTO file_tags (file_id, tag_type, tag_value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (file_id, "metadata_tag", str(tag)),
                )
            cursor.execute(
                "INSERT INTO file_tags (file_id, tag_type, tag_value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                (file_id, "metadata_provider", provider_id),
            )
        return True
def _build_xml_index(xml_path: str, format_def: dict[str, Any]) -> dict[str, dict[str, dict[str, Any]]]:
    return build_index_from_entries(build_catalog_entries(xml_path, format_def))
