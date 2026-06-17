from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


SOURCE_ROOTS = {"roms", "saves", "savestates", "bios", "wallpapers"}


@dataclass(frozen=True)
class CanonicalSystem:
    id: str
    src: str
    pretty_name: str
    local_base_path: str
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProjectionTopLevel:
    name: str
    source_root: str
    per_system: bool = True


@dataclass(frozen=True)
class ProjectionMapping:
    client: str
    system_id: str
    client_name: str


@dataclass(frozen=True)
class ProjectionOverride:
    client: str
    top_level: str
    client_name: str
    src: str


@dataclass(frozen=True)
class ClientProjection:
    client: str
    transport: str
    top_levels: tuple[ProjectionTopLevel, ...]
    mappings: tuple[ProjectionMapping, ...] = field(default_factory=tuple)
    overrides: tuple[ProjectionOverride, ...] = field(default_factory=tuple)
    enabled: bool = True
    auto_map_system_name: bool = True
    canonical_roots: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProjectionEntry:
    top_level: str
    client_name: str
    source_base: str


_NOT_RETRONAS_SUPPORT = object()


def _norm_rel(value: str) -> str:
    normalized = str(value or "").replace("\\", "/").strip("/")
    return "/".join(part for part in normalized.split("/") if part)


def _norm_key(value: str) -> str:
    return _norm_rel(value).lower()


def _extract_canonical_system(system: dict[str, Any]) -> Optional[CanonicalSystem]:
    manufacturer = str(system.get("manufacturer") or "").strip()
    mapping_name = str(system.get("system_mapping_name") or system.get("cananonical_system_name") or "").strip()
    if not manufacturer or not mapping_name:
        return None

    src = _norm_rel(system.get("canonical_src") or f"{manufacturer}/{mapping_name}")
    if not src:
        return None

    aliases = system.get("retronas_aliases") or system.get("projection_aliases") or system.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]

    return CanonicalSystem(
        id=src,
        src=src,
        pretty_name=str(system.get("display_name") or system.get("name") or mapping_name),
        local_base_path=_norm_rel(system.get("local_base_path") or ""),
        aliases=tuple(_norm_rel(alias) for alias in aliases if _norm_rel(alias)),
    )


def _load_projection(client: dict[str, Any]) -> Optional[ClientProjection]:
    cfg = client.get("retronas_support") or client.get("projection") or {}
    if not isinstance(cfg, dict):
        return None
    if not cfg.get("enabled", False):
        return None

    top_levels_cfg = cfg.get("top_levels") or []
    top_levels: list[ProjectionTopLevel] = []
    for item in top_levels_cfg:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        source_root = str(item.get("source_root") or "").strip().lower()
        if not name or not source_root or source_root not in SOURCE_ROOTS:
            continue
        top_levels.append(
            ProjectionTopLevel(
                name=name,
                source_root=source_root,
                per_system=bool(item.get("per_system", True)),
            )
        )

    if not top_levels:
        return None

    mappings_cfg = cfg.get("mappings") or []
    mappings: list[ProjectionMapping] = []
    for item in mappings_cfg:
        if not isinstance(item, dict):
            continue
        system_id = _norm_rel(item.get("system_id") or item.get("src") or "")
        client_name = str(item.get("client_name") or "").strip()
        if not system_id or not client_name:
            continue
        mappings.append(
            ProjectionMapping(
                client=str(client.get("name") or ""),
                system_id=system_id,
                client_name=client_name,
            )
        )

    overrides_cfg = cfg.get("overrides") or []
    overrides: list[ProjectionOverride] = []
    for item in overrides_cfg:
        if not isinstance(item, dict):
            continue
        top_level = str(item.get("top_level") or "").strip()
        client_name = str(item.get("client_name") or "").strip()
        src = _norm_rel(item.get("src") or "")
        if not top_level or not client_name or not src:
            continue
        overrides.append(
            ProjectionOverride(
                client=str(client.get("name") or ""),
                top_level=top_level,
                client_name=client_name,
                src=src,
            )
        )

    canonical_roots = cfg.get("canonical_roots") or {}
    if not isinstance(canonical_roots, dict):
        canonical_roots = {}

    return ClientProjection(
        client=str(client.get("name") or ""),
        transport=str(cfg.get("transport") or "smb").strip().lower() or "smb",
        top_levels=tuple(top_levels),
        mappings=tuple(mappings),
        overrides=tuple(overrides),
        enabled=True,
        auto_map_system_name=bool(cfg.get("auto_map_system_name", True)),
        canonical_roots={str(k).strip().lower(): str(v) for k, v in canonical_roots.items()},
    )


def _build_canonical_index(client: dict[str, Any]) -> dict[str, CanonicalSystem]:
    index: dict[str, CanonicalSystem] = {}
    for system in client.get("systems") or []:
        if not isinstance(system, dict):
            continue
        canonical = _extract_canonical_system(system)
        if canonical is None:
            continue
        index[_norm_key(canonical.id)] = canonical
    return index


def _resolve_source_base(
    filestore: str,
    projection: ClientProjection,
    top_level: ProjectionTopLevel,
    canonical: CanonicalSystem,
) -> str:
    template = projection.canonical_roots.get(top_level.source_root)
    if template:
        rel = template.format(
            src=canonical.src,
            source_root=top_level.source_root,
            system_id=canonical.id,
            local_base_path=canonical.local_base_path,
            filestore=filestore,
        )
        # If the template rendered to an absolute path (i.e. {filestore} was
        # expanded), return it directly — it already includes the Native/ segment.
        if os.path.isabs(rel):
            return rel
        rel = _norm_rel(rel)
    else:
        # Default: RetroNAS-inside-Native convention — Native/{category}/{src}
        rel = _norm_rel(os.path.join(top_level.source_root, canonical.src))

    return os.path.join(filestore, "Native", rel)


def _build_entries(client: dict[str, Any], filestore: str) -> tuple[Optional[ClientProjection], dict[str, dict[str, ProjectionEntry]]]:
    projection = _load_projection(client)
    if projection is None:
        return None, {}

    canonical_index = _build_canonical_index(client)

    names_by_system: dict[str, list[str]] = {key: [] for key in canonical_index.keys()}

    explicit_map: dict[str, str] = {}
    for mapping in projection.mappings:
        explicit_map[_norm_key(mapping.system_id)] = mapping.client_name

    for system in client.get("systems") or []:
        if not isinstance(system, dict):
            continue
        canonical = _extract_canonical_system(system)
        if canonical is None:
            continue
        key = _norm_key(canonical.id)
        if key in explicit_map:
            names_by_system[key].append(explicit_map[key])
        elif projection.auto_map_system_name:
            default_name = str(system.get("retronas_name") or system.get("projection_name") or system.get("name") or "").strip()
            if default_name:
                names_by_system[key].append(default_name)

        for alias in canonical.aliases:
            if alias:
                names_by_system[key].append(alias)

    entries_by_top: dict[str, dict[str, ProjectionEntry]] = {top.name: {} for top in projection.top_levels}

    for top in projection.top_levels:
        if not top.per_system:
            continue
        for key, canonical in canonical_index.items():
            names = names_by_system.get(key, [])
            for name in names:
                if not name:
                    continue
                source_base = _resolve_source_base(filestore, projection, top, canonical)
                entries_by_top[top.name].setdefault(
                    name.lower(),
                    ProjectionEntry(top_level=top.name, client_name=name, source_base=source_base),
                )

    for override in projection.overrides:
        top = next((item for item in projection.top_levels if item.name == override.top_level), None)
        if top is None:
            continue
        canonical = CanonicalSystem(
            id=override.src,
            src=override.src,
            pretty_name=override.client_name,
            local_base_path="",
            aliases=(),
        )
        source_base = _resolve_source_base(filestore, projection, top, canonical)
        entries_by_top[top.name][override.client_name.lower()] = ProjectionEntry(
            top_level=top.name,
            client_name=override.client_name,
            source_base=source_base,
        )

    return projection, entries_by_top


def list_retronas_support_directory(config: dict[str, Any], root: str, full_path: str, show_hidden: bool = True) -> Optional[list[str]]:
    path = Path(full_path)
    root_parts = Path(root).parts
    rel_parts = path.parts[len(root_parts):]
    if not rel_parts:
        return None

    client_name = rel_parts[0]
    client = next((c for c in config.get("clients", []) if c.get("name") == client_name), None)
    if client is None:
        return None

    filestore = config.get("filestore", "/mnt/filestorefs")
    projection, entries_by_top = _build_entries(client, filestore)
    if projection is None:
        return None

    if len(rel_parts) == 1:
        return [top.name for top in projection.top_levels]

    top_name = rel_parts[1]
    top = next((item for item in projection.top_levels if item.name.lower() == top_name.lower()), None)
    if top is None:
        return None

    top_entries = entries_by_top.get(top.name, {})
    if len(rel_parts) == 2:
        return sorted(entry.client_name for entry in top_entries.values())

    client_entry = top_entries.get(rel_parts[2].lower())
    if client_entry is None:
        return []

    source_path = client_entry.source_base
    if len(rel_parts) > 3:
        source_path = os.path.join(source_path, *rel_parts[3:])

    if not os.path.isdir(source_path):
        return []

    entries: list[str] = []
    for name in os.listdir(source_path):
        if not show_hidden and name.startswith("."):
            continue
        entries.append(name)
    return sorted(entries)


def resolve_retronas_support_source_path(
    config: dict[str, Any],
    root: str,
    translated_path: str,
    *,
    for_write: bool = False,
) -> Any:
    path = Path(translated_path)
    root_parts = Path(root).parts
    rel_parts = path.parts[len(root_parts):]
    if len(rel_parts) < 3:
        return _NOT_RETRONAS_SUPPORT

    client = next((c for c in config.get("clients", []) if c.get("name") == rel_parts[0]), None)
    if client is None:
        return _NOT_RETRONAS_SUPPORT

    filestore = config.get("filestore", "/mnt/filestorefs")
    projection, entries_by_top = _build_entries(client, filestore)
    if projection is None:
        return _NOT_RETRONAS_SUPPORT

    top_name = rel_parts[1]
    top = next((item for item in projection.top_levels if item.name.lower() == top_name.lower()), None)
    if top is None:
        return _NOT_RETRONAS_SUPPORT

    entry = entries_by_top.get(top.name, {}).get(rel_parts[2].lower())
    if entry is None:
        return None

    source_path = entry.source_base
    if len(rel_parts) > 3:
        source_path = os.path.join(source_path, *rel_parts[3:])

    if for_write:
        return source_path

    if os.path.exists(source_path):
        return source_path

    return None


def retronas_support_not_applicable(value: Any) -> bool:
    return value is _NOT_RETRONAS_SUPPORT


def get_primary_smb_retronas_root(config: dict[str, Any]) -> Optional[str]:
    for client in config.get("clients", []):
        projection = _load_projection(client)
        if projection is None:
            continue
        if projection.enabled and projection.transport == "smb":
            return str(client.get("name") or "").strip() or None
    return None


# Backward-compatible aliases for in-flight branch references.
list_projection_directory = list_retronas_support_directory
resolve_projection_source_path = resolve_retronas_support_source_path
projection_not_applicable = retronas_support_not_applicable
get_primary_smb_projection_root = get_primary_smb_retronas_root
