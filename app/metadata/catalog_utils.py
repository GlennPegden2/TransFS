from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any


@dataclass
class CatalogEntry:
    source_name: str
    normalized_name: str
    metadata: dict[str, Any]
    sha1: str | None = None
    crc: str | None = None
    top_level_dir: str | None = None
    relative_dir: str | None = None
    extension: str | None = None


def normalize_name(value: str) -> str:
    stem = PurePosixPath((value or "").replace("\\", "/")).stem
    return "".join(ch.lower() for ch in stem if ch.isalnum())


def extract_spec_value(element: ET.Element, spec: Any) -> Any:
    if isinstance(spec, str):
        if spec.startswith("@"):
            return (element.get(spec[1:]) or "").strip() or None
        return (element.findtext(spec) or "").strip() or None

    if not isinstance(spec, dict):
        return spec

    value: Any = None
    fallback = spec.get("fallback")
    if isinstance(fallback, list):
        for candidate in fallback:
            candidate_value = extract_spec_value(element, candidate)
            if candidate_value not in (None, ""):
                value = candidate_value
                break
    elif "attr" in spec:
        value = (element.get(str(spec.get("attr"))) or "").strip() or None
    elif "path" in spec:
        value = (element.findtext(str(spec.get("path"))) or "").strip() or None
    elif "value" in spec:
        value = spec.get("value")

    if value in (None, "") and "default" in spec:
        value = spec.get("default")

    if value in (None, ""):
        return None

    cast = (spec.get("cast") or "").lower()
    if cast == "int":
        text_value = str(value).strip()
        return int(text_value) if text_value.isdigit() else None
    if cast == "bool":
        text_value = str(value).strip().lower()
        return text_value in {"1", "true", "yes", "y", "on"}

    value_map = spec.get("map") or {}
    if isinstance(value_map, dict):
        text_value = str(value).strip()
        if text_value in value_map:
            return value_map[text_value]
        if "*" in value_map:
            return value_map["*"]

    return value


def clean_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if value not in (None, "", [])}


def _path_details(source_name: str) -> tuple[str | None, str | None, str | None]:
    normalized_path = (source_name or "").replace("\\", "/").strip("/")
    if not normalized_path:
        return None, None, None

    path = PurePosixPath(normalized_path)
    parts = list(path.parts)
    top_level = parts[0] if len(parts) > 1 else None
    relative_dir = "/".join(parts[1:-1]) if len(parts) > 2 else None
    extension = path.suffix[1:].upper() if path.suffix else None
    return top_level, relative_dir, extension


def build_catalog_entries(xml_path: str, format_def: dict[str, Any]) -> list[CatalogEntry]:
    root = ET.parse(xml_path).getroot()
    item_path = format_def.get("item_path") or ".//software"
    match_def = format_def.get("match") or {}
    filename_match = match_def.get("filename") or {}
    checksum_defs = match_def.get("checksums") or []
    if isinstance(checksum_defs, dict):
        checksum_defs = [checksum_defs]

    metadata_def = format_def.get("metadata") or {}
    static_tags = (format_def.get("tags") or {}).get("static") or []

    entries: list[CatalogEntry] = []
    seen: set[tuple[str, str | None, str | None]] = set()

    for item in root.findall(item_path):
        metadata: dict[str, Any] = {}
        for key, spec in metadata_def.items():
            metadata[key] = extract_spec_value(item, spec)
        if static_tags:
            existing = metadata.get("tags") or []
            if isinstance(existing, str):
                existing = [existing]
            metadata["tags"] = [*existing, *static_tags]
        metadata = clean_metadata(metadata)

        name_spec = filename_match.get("source") or "@name"
        default_source_name = str(extract_spec_value(item, name_spec) or "").strip()

        item_entries: list[CatalogEntry] = []
        if checksum_defs:
            for checksum_def in checksum_defs:
                node_path = checksum_def.get("item_path") or "."
                name_attr = checksum_def.get("name_attr") or "name"
                sha1_attr = checksum_def.get("sha1_attr") or "sha1"
                crc_attr = checksum_def.get("crc_attr") or "crc"
                for checksum_node in item.findall(node_path):
                    source_name = (checksum_node.get(name_attr) or default_source_name or "").strip()
                    if not source_name:
                        continue
                    top_level, relative_dir, extension = _path_details(source_name)
                    item_entries.append(
                        CatalogEntry(
                            source_name=source_name,
                            normalized_name=normalize_name(source_name),
                            metadata=dict(metadata),
                            sha1=(checksum_node.get(sha1_attr) or "").strip().lower() or None,
                            crc=(checksum_node.get(crc_attr) or "").strip().lower() or None,
                            top_level_dir=top_level,
                            relative_dir=relative_dir,
                            extension=extension,
                        )
                    )

        if not item_entries and default_source_name:
            top_level, relative_dir, extension = _path_details(default_source_name)
            item_entries.append(
                CatalogEntry(
                    source_name=default_source_name,
                    normalized_name=normalize_name(default_source_name),
                    metadata=dict(metadata),
                    top_level_dir=top_level,
                    relative_dir=relative_dir,
                    extension=extension,
                )
            )

        for entry in item_entries:
            dedupe_key = (entry.source_name, entry.sha1, entry.crc)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            entries.append(entry)

    return entries


def build_index_from_entries(entries: list[CatalogEntry]) -> dict[str, dict[str, dict[str, Any]]]:
    by_name: dict[str, dict[str, Any]] = {}
    by_sha1: dict[str, dict[str, Any]] = {}
    by_crc: dict[str, dict[str, Any]] = {}

    for entry in entries:
        payload = {
            "metadata": entry.metadata,
            "source_name": entry.source_name,
        }
        if entry.normalized_name and entry.normalized_name not in by_name:
            by_name[entry.normalized_name] = payload
        if entry.sha1 and entry.sha1 not in by_sha1:
            by_sha1[entry.sha1] = payload
        if entry.crc and entry.crc not in by_crc:
            by_crc[entry.crc] = payload

    return {
        "by_name": by_name,
        "by_sha1": by_sha1,
        "by_crc": by_crc,
    }
