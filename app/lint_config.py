"""
TransFS YAML Configuration Linter — Library Module
====================================================
Importable core used by both the CLI (tools/lint_config.py) and the web API.

Public API
----------
lint_file(filepath)          -> LintResult
lint_all(config_dir)         -> LintSummary
lint_all_to_json(config_dir) -> dict   (API-friendly)
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml


# ─────────────────────────────────────────────────────────────
# Duplicate-key-detecting YAML loader
# ─────────────────────────────────────────────────────────────
class _DupKeyLoader(yaml.SafeLoader):
    pass


def _construct_mapping_with_dup_check(loader, node):
    keys_seen = {}
    duplicates = []
    for key_node, _ in node.value:
        key = loader.construct_object(key_node, deep=False)
        line = key_node.start_mark.line + 1
        if key in keys_seen:
            duplicates.append((key, keys_seen[key], line))
        else:
            keys_seen[key] = line
    loader._duplicates = getattr(loader, "_duplicates", [])
    loader._duplicates.extend(duplicates)
    return loader.construct_mapping(node, deep=True)


_DupKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_mapping_with_dup_check,
)


def _load_yaml_with_dup_check(text: str):
    """Return (data, duplicates_list, error_str)."""
    loader = _DupKeyLoader(text)
    try:
        data = loader.get_single_data()
        duplicates = getattr(loader, "_duplicates", [])
        return data, duplicates, None
    except yaml.YAMLError as exc:
        return None, [], str(exc)
    finally:
        loader.dispose()


# ─────────────────────────────────────────────────────────────
# Issue & Result containers
# ─────────────────────────────────────────────────────────────
@dataclass
class Issue:
    ERROR   = "ERROR"
    WARNING = "WARNING"
    INFO    = "INFO"

    severity:   str
    path:       str
    message:    str
    suggestion: str = ""

    def to_dict(self) -> dict:
        d = {"severity": self.severity, "path": self.path, "message": self.message}
        if self.suggestion:
            d["suggestion"] = self.suggestion
        return d


class LintResult:
    def __init__(self, filepath: str, config_type: str):
        self.filepath    = filepath
        self.config_type = config_type          # "app" | "client" | "source"
        self.filename    = os.path.basename(filepath)
        self.issues: list[Issue] = []

    def _add(self, severity, path, message, suggestion=""):
        self.issues.append(Issue(severity=severity, path=path,
                                 message=message, suggestion=suggestion))

    def error(self, path, message, suggestion=""):
        self._add(Issue.ERROR, path, message, suggestion)

    def warn(self, path, message, suggestion=""):
        self._add(Issue.WARNING, path, message, suggestion)

    def info(self, path, message, suggestion=""):
        self._add(Issue.INFO, path, message, suggestion)

    @property
    def has_errors(self):
        return any(i.severity == Issue.ERROR for i in self.issues)

    @property
    def has_warnings(self):
        return any(i.severity == Issue.WARNING for i in self.issues)

    @property
    def status(self) -> str:
        if self.has_errors:
            return "fail"
        if self.has_warnings:
            return "warn"
        return "ok"

    @property
    def error_count(self):
        return sum(1 for i in self.issues if i.severity == Issue.ERROR)

    @property
    def warning_count(self):
        return sum(1 for i in self.issues if i.severity == Issue.WARNING)

    def to_dict(self) -> dict:
        return {
            "filepath":    self.filepath,
            "filename":    self.filename,
            "config_type": self.config_type,
            "status":      self.status,
            "errors":      self.error_count,
            "warnings":    self.warning_count,
            "issues":      [i.to_dict() for i in self.issues],
        }


@dataclass
class LintSummary:
    results: list[LintResult] = field(default_factory=list)

    @property
    def total_files(self):
        return len(self.results)

    @property
    def total_errors(self):
        return sum(r.error_count for r in self.results)

    @property
    def total_warnings(self):
        return sum(r.warning_count for r in self.results)

    @property
    def clean_files(self):
        return sum(1 for r in self.results if r.status == "ok")

    @property
    def has_errors(self):
        return self.total_errors > 0

    def to_dict(self) -> dict:
        return {
            "total_files":    self.total_files,
            "total_errors":   self.total_errors,
            "total_warnings": self.total_warnings,
            "clean_files":    self.clean_files,
            "files":          [r.to_dict() for r in self.results],
        }


# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def _require(result: LintResult, data: dict, field_name: str, ctx: str, suggestion: str = ""):
    if field_name not in data or data[field_name] is None or data[field_name] == "":
        result.error(f"{ctx}.{field_name}",
                     f"Mandatory field '{field_name}' is missing or empty.", suggestion)
        return False
    return True


def _recommend(result: LintResult, data: dict, field_name: str, ctx: str, suggestion: str = ""):
    if field_name not in data or data[field_name] is None:
        result.warn(f"{ctx}.{field_name}",
                    f"Recommended field '{field_name}' is missing.", suggestion)


URL_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


def _is_valid_url(url) -> bool:
    return isinstance(url, str) and bool(URL_RE.match(url.strip()))


# ─────────────────────────────────────────────────────────────
# app.yaml linter
# ─────────────────────────────────────────────────────────────
def lint_app_yaml(filepath: str) -> LintResult:
    result = LintResult(filepath, "app")

    with open(filepath, "r", encoding="utf-8") as fh:
        raw = fh.read()

    data, duplicates, err = _load_yaml_with_dup_check(raw)

    if err:
        result.error("app.yaml", f"YAML syntax error: {err}",
                     "Check indentation, special characters, and quote usage.")
        return result

    if not isinstance(data, dict):
        result.error("app.yaml", "Top-level structure must be a YAML mapping (key: value pairs).")
        return result

    for key, first_line, dup_line in duplicates:
        result.error(f"app.yaml[line {dup_line}]",
                     f"Duplicate key '{key}' (first seen at line {first_line}).",
                     "Remove or rename the duplicate key.")

    _require(result, data, "filestore", "app.yaml",
             "Add: filestore: /data/retronas")

    cs = data.get("config_sets", {}) or {}
    if not isinstance(cs, dict) or not cs.get("active_client_config"):
        result.error("app.yaml.config_sets.active_client_config",
                     "Mandatory field 'config_sets.active_client_config' is missing.",
                     "Add: config_sets:\n  active_client_config: default")
    if not isinstance(cs, dict) or not cs.get("active_source_config"):
        result.error("app.yaml.config_sets.active_source_config",
                     "Mandatory field 'config_sets.active_source_config' is missing.",
                     "Add: config_sets:\n  active_source_config: default")

    db = data.get("database", {}) or {}
    if not isinstance(db, dict) or not db:
        result.error("app.yaml.database",
                     "Mandatory 'database' block is missing.",
                     "Add a database: block with host, port, name, user, password.")
    else:
        for f in ("host", "port", "name", "user", "password"):
            if not db.get(f):
                result.error(f"app.yaml.database.{f}",
                             f"Mandatory database field '{f}' is missing or empty.")
        mode = db.get("mode", "")
        valid_modes = ("enabled", "disabled", "read_only")
        if mode and mode not in valid_modes:
            result.error("app.yaml.database.mode",
                         f"Invalid database mode '{mode}'.",
                         f"Valid values: {', '.join(valid_modes)}")

    smb = data.get("smb", {}) or {}
    if not isinstance(smb, dict) or not smb:
        result.warn("app.yaml.smb",
                    "Recommended 'smb' block is missing.",
                    "Add: smb:\n  username: root\n  password: '1'\n  allow_guest: false")
    else:
        for f in ("username", "password"):
            if smb.get(f) is None:
                result.warn(f"app.yaml.smb.{f}",
                            f"Recommended smb field '{f}' is missing.")

    _recommend(result, data, "cache", "app.yaml",
               "Add a cache: block to tune caching behaviour.")
    _recommend(result, data, "startup_prewarm", "app.yaml",
               "Add startup_prewarm: block to speed up initial directory listings.")
    _recommend(result, data, "mame", "app.yaml",
               "Add mame: block if you intend to use MAME software lists.")

    mounts = data.get("native_external_mounts", []) or []
    for i, mount in enumerate(mounts):
        ctx = f"app.yaml.native_external_mounts[{i}]"
        if not isinstance(mount, dict):
            result.error(ctx, "Mount entry must be a mapping.")
            continue
        for f in ("id", "target_subpath"):
            if not mount.get(f):
                result.error(f"{ctx}.{f}", f"Mandatory mount field '{f}' is missing.")
        mount_type = str(mount.get("mount_type", "cifs") or "cifs").strip().lower()
        if mount_type in {"smb", "cifs"}:
            if not mount.get("smb_host"):
                result.error(f"{ctx}.smb_host", "Mandatory cifs mount field 'smb_host' is missing.")
            if not mount.get("smb_share"):
                result.error(f"{ctx}.smb_share", "Mandatory cifs mount field 'smb_share' is missing.")
            if mount.get("smb_host") and not mount.get("credentials_file") and not mount.get("guest"):
                result.warn(f"{ctx}.credentials_file",
                            "SMB mount has no credentials_file and guest is not true.",
                            "Add: credentials_file: /path/to/.cred  or set  guest: true")
        elif mount_type == "nfs":
            if not mount.get("nfs_server"):
                result.error(f"{ctx}.nfs_server", "Mandatory nfs mount field 'nfs_server' is missing.")
            if not mount.get("nfs_export"):
                result.error(f"{ctx}.nfs_export", "Mandatory nfs mount field 'nfs_export' is missing.")
        elif mount_type == "bind":
            if not mount.get("bind_source"):
                result.error(f"{ctx}.bind_source", "Mandatory bind mount field 'bind_source' is missing.")
        else:
            result.error(f"{ctx}.mount_type",
                         f"Unsupported mount_type '{mount_type}'.",
                         "Valid values: cifs, nfs, bind")

    return result


# ─────────────────────────────────────────────────────────────
# Client config linter
# ─────────────────────────────────────────────────────────────
def _lint_map_entry(result: LintResult, map_dict: dict, ctx: str):
    if not isinstance(map_dict, dict):
        result.error(ctx, "Map entry must be a mapping.")
        return

    has_file  = "file"  in map_dict
    has_query = "query" in map_dict

    if not has_file and not has_query:
        result.error(ctx, "Map entry must contain either 'file' or 'query'.",
                     "Example:\n  CDs:\n    query:\n      source_dir: Software\n      extensions: [CUE, ISO]")
        return

    if has_file:
        f = map_dict["file"] or {}
        if not isinstance(f, dict) or not f.get("path"):
            result.error(f"{ctx}.file.path", "file entry must have a non-empty 'path'.")

    if has_query:
        q = map_dict["query"] or {}
        if not isinstance(q, dict):
            result.error(f"{ctx}.query", "query value must be a mapping.")
            return
        if not q.get("source_dir"):
            result.error(f"{ctx}.query.source_dir", "Mandatory query field 'source_dir' is missing.")
        exts = q.get("extensions")
        if exts is None:
            result.warn(f"{ctx}.query.extensions",
                        "Recommended query field 'extensions' is missing.",
                        "Add: extensions: [CUE, ISO, CHD]  (or ['*'] for all)")
        elif not isinstance(exts, list) or len(exts) == 0:
            result.warn(f"{ctx}.query.extensions", "extensions should be a non-empty list.")


def lint_client_yaml(filepath: str) -> LintResult:
    result = LintResult(filepath, "client")

    with open(filepath, "r", encoding="utf-8") as fh:
        raw = fh.read()

    data, duplicates, err = _load_yaml_with_dup_check(raw)

    if err:
        result.error(result.filename,
                     f"YAML syntax error: {err}",
                     "Check indentation, special characters, and quote usage.")
        return result

    if not isinstance(data, dict):
        result.error(result.filename, "Top-level structure must be a YAML mapping.")
        return result

    for key, first_line, dup_line in duplicates:
        result.error(f"line {dup_line}",
                     f"Duplicate key '{key}' (first seen at line {first_line}).",
                     "Remove or rename the duplicate key.")

    name = result.filename
    _require(result, data, "name", name, "Add: name: MyClientName")
    _recommend(result, data, "download_layout", name,
               "Add: download_layout: folder_based  (or flat / legacy_source_based)")
    _recommend(result, data, "category_paths", name,
               "Add a category_paths: block to define roms/bios path templates.")

    systems = data.get("systems", []) or []
    if not isinstance(systems, list) or len(systems) == 0:
        result.warn(f"{name}.systems", "No systems defined in this client config.")
        return result

    system_names_seen = set()
    for i, system in enumerate(systems):
        ctx = f"{name}.systems[{i}]"
        if not isinstance(system, dict):
            result.error(ctx, "System entry must be a mapping.")
            continue

        sys_name = system.get("name", f"<unnamed #{i}>")
        ctx = f"{name}.systems[{sys_name}]"

        if sys_name in system_names_seen:
            result.warn(ctx, f"Duplicate system name '{sys_name}'.")
        system_names_seen.add(sys_name)

        _require(result, system, "name",            ctx)
        _require(result, system, "manufacturer",    ctx, "Add: manufacturer: SomeManufacturer")
        _require(result, system, "local_base_path", ctx, "Add: local_base_path: Systems/Manufacturer/System")
        _recommend(result, system, "system_mapping_name", ctx,
                   "Add system_mapping_name to match the source config canonical name.")

        maps = system.get("maps", []) or []
        if not isinstance(maps, list) or len(maps) == 0:
            result.warn(f"{ctx}.maps",
                        "System has no maps defined — it won't appear in the virtual filesystem.")
        else:
            for j, map_entry in enumerate(maps):
                if not isinstance(map_entry, dict):
                    result.error(f"{ctx}.maps[{j}]", "Map entry must be a mapping.")
                    continue
                for map_key, map_val in map_entry.items():
                    _lint_map_entry(result, map_val or {}, f"{ctx}.maps[{map_key}]")

    return result


# ─────────────────────────────────────────────────────────────
# Source config linter
# ─────────────────────────────────────────────────────────────
def lint_source_yaml(filepath: str) -> LintResult:
    result = LintResult(filepath, "source")

    with open(filepath, "r", encoding="utf-8") as fh:
        raw = fh.read()

    data, duplicates, err = _load_yaml_with_dup_check(raw)

    if err:
        result.error(result.filename,
                     f"YAML syntax error: {err}",
                     "Check indentation, special characters, and quote usage.")
        return result

    if data is None:
        result.warn(result.filename, "File is empty.")
        return result

    if not isinstance(data, dict):
        result.error(result.filename, "Top-level structure must be a YAML mapping.")
        return result

    name = result.filename

    for key, first_line, dup_line in duplicates:
        result.error(f"{name} line {dup_line}",
                     f"Duplicate key '{key}' (first seen at line {first_line}).",
                     "YAML allows duplicate keys but only the last value is visible to Python. "
                     "Rename or merge the duplicates.")

    _require(result, data, "base_path", name,
             "Add: base_path: Manufacturer/SystemName/")

    sources = data.get("sources", []) or []
    if not isinstance(sources, list):
        result.error(f"{name}.sources", "sources must be a YAML list.")
        sources = []

    source_names: set[str] = set()

    for i, src in enumerate(sources):
        ctx = f"{name}.sources[{i}]"
        if not isinstance(src, dict):
            result.error(ctx, "Source entry must be a mapping.")
            continue

        src_name = src.get("name", f"<unnamed #{i}>")
        ctx = f"{name}.sources[{src_name}]"

        if src_name in source_names:
            result.warn(ctx, f"Duplicate source name '{src_name}'.",
                        "Each source name must be unique within a file.")
        source_names.add(src_name)

        _require(result, src, "name", ctx)
        _require(result, src, "type", ctx, "Add: type: ddl")

        src_type = src.get("type", "")
        valid_types = ("ddl", "torrent", "tor", "base64", "git", "IA-COL", "mega", "mame")
        if src_type and src_type not in valid_types:
            result.warn(f"{ctx}.type",
                        f"Unrecognised source type '{src_type}'.",
                        f"Known types: {', '.join(valid_types)}")

        if src_type != "mame":
            _require(result, src, "folder", ctx, "Add: folder: Software/roms")

        url_optional_types = ("base64", "git", "mame", "IA-COL")
        has_url  = "url"  in src
        has_urls = "urls" in src

        if not has_url and not has_urls and src_type not in url_optional_types:
            result.error(f"{ctx}.url",
                         "Source must have 'url' or 'urls' field.",
                         "Add: url: https://example.com/file.zip")

        if has_url:
            url = src.get("url")
            if not _is_valid_url(url):
                result.error(f"{ctx}.url",
                             f"'url' value does not look like a valid HTTP(S) URL: {url!r}")

        if has_urls:
            urls = src.get("urls") or []
            if not isinstance(urls, list):
                result.error(f"{ctx}.urls", "urls must be a list.")
            else:
                for j, u in enumerate(urls):
                    if u is None or u == "":
                        result.warn(f"{ctx}.urls[{j}]",
                                    "Empty/null URL in urls list — will be ignored.",
                                    "Remove the blank line or add the missing URL.")
                    elif not _is_valid_url(u):
                        result.error(f"{ctx}.urls[{j}]", f"Invalid URL: {u!r}")

        if src_type == "ddl" and not src.get("extract") and not src.get("extract_from_archive"):
            url_val  = src.get("url") or ""
            urls_val = src.get("urls") or []
            archive_exts = (".zip", ".7z", ".tar.gz", ".tgz", ".rar")
            all_urls = ([url_val] if url_val else []) + (urls_val if isinstance(urls_val, list) else [])
            if any(str(u).lower().endswith(archive_exts) for u in all_urls if u):
                result.info(f"{ctx}.extract",
                            "Source downloads archives but 'extract' is not set.",
                            "Consider: extract: true  (or extract: '*.rom')")

    packs = data.get("packs", []) or []
    if not isinstance(packs, list):
        result.error(f"{name}.packs", "packs must be a YAML list.")
        packs = []

    if len(sources) > 0 and len(packs) == 0:
        result.info(f"{name}.packs",
                    "No packs defined — users won't be able to download content via the UI.",
                    "Add a packs: section grouping sources into downloadable bundles.")

    pack_ids_seen: set[str] = set()
    for i, pack in enumerate(packs):
        ctx = f"{name}.packs[{i}]"
        if not isinstance(pack, dict):
            result.error(ctx, "Pack entry must be a mapping.")
            continue

        pack_id = pack.get("id", f"<unnamed #{i}>")
        ctx = f"{name}.packs[{pack_id}]"

        if pack_id in pack_ids_seen:
            result.error(ctx, f"Duplicate pack id '{pack_id}'.",
                         "Each pack id must be unique within a file.")
        pack_ids_seen.add(pack_id)

        _require(result, pack, "id",          ctx, "Add: id: my-unique-pack-id")
        _require(result, pack, "name",        ctx, "Add: name: My Pack Display Name")
        _require(result, pack, "description", ctx, "Add: description: Short description.")
        _require(result, pack, "sources",     ctx, "Add: sources: [source-name-1]")

        _recommend(result, pack, "estimated_size", ctx,
                   "Add: estimated_size: 50MB")
        _recommend(result, pack, "info_links", ctx,
                   "Add info_links: with links to documentation or the source project.")
        _recommend(result, pack, "supported_by", ctx,
                   "Add: supported_by: [MiSTer, RetroBat]")

        pack_sources = pack.get("sources") or []
        if isinstance(pack_sources, list):
            for ref in pack_sources:
                if ref not in source_names:
                    result.error(f"{ctx}.sources",
                                 f"Pack references source '{ref}' which is not defined in this file.",
                                 f"Available sources: {', '.join(sorted(source_names)) or '<none>'}")

    return result


# ─────────────────────────────────────────────────────────────
# Public: lint a single file (type auto-detected from path)
# ─────────────────────────────────────────────────────────────
def lint_file(filepath: str) -> LintResult:
    """Lint a single YAML file; config type inferred from path."""
    filepath = os.path.abspath(filepath)
    fname  = os.path.basename(filepath)
    parts  = Path(filepath).parts

    if fname == "app.yaml":
        return lint_app_yaml(filepath)
    if "clients" in parts:
        return lint_client_yaml(filepath)
    if "sources" in parts:
        return lint_source_yaml(filepath)
    # Fallback: try as source config
    return lint_source_yaml(filepath)


# ─────────────────────────────────────────────────────────────
# Public: lint entire config tree
# ─────────────────────────────────────────────────────────────
def lint_all(config_dir: str) -> LintSummary:
    """Lint all YAML config files under config_dir. Returns a LintSummary."""
    config_dir = os.path.abspath(config_dir)
    summary = LintSummary()

    app_yaml = os.path.join(config_dir, "app.yaml")
    if os.path.exists(app_yaml):
        summary.results.append(lint_app_yaml(app_yaml))

    clients_root = os.path.join(config_dir, "clients")
    if os.path.isdir(clients_root):
        for config_set in sorted(os.listdir(clients_root)):
            set_dir = os.path.join(clients_root, config_set)
            if not os.path.isdir(set_dir):
                continue
            for fname in sorted(os.listdir(set_dir)):
                if fname.endswith(".yaml"):
                    summary.results.append(lint_client_yaml(os.path.join(set_dir, fname)))

    sources_root = os.path.join(config_dir, "sources")
    if os.path.isdir(sources_root):
        for config_set in sorted(os.listdir(sources_root)):
            set_dir = os.path.join(sources_root, config_set)
            if not os.path.isdir(set_dir):
                continue
            for manufacturer in sorted(os.listdir(set_dir)):
                mfr_dir = os.path.join(set_dir, manufacturer)
                if not os.path.isdir(mfr_dir):
                    continue
                for fname in sorted(os.listdir(mfr_dir)):
                    if fname.endswith(".yaml"):
                        summary.results.append(lint_source_yaml(os.path.join(mfr_dir, fname)))

    return summary
