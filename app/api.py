""" API Wrapper 

SECURITY NOTE: This API is designed for local development use within Docker.
- Path Traversal: Paths are from trusted transfs.yaml configuration
- SSRF: URLs are from trusted archive_sources configuration  
- SSL Verification: May be disabled for legacy/local sources
DO NOT expose this API to untrusted networks or public internet.
"""
import asyncio
import base64
import fnmatch
import io
import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

import internetarchive
import libtorrent as lt  # pylint: disable=import-error
import py7zr
import rarfile  # pylint: disable=import-error
import requests
import yaml
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import PlainTextResponse, StreamingResponse
from mega import Mega
from pydantic import BaseModel
from config import (
    get_clients,
    get_systems_for_client,
    get_manufacturers_and_canonical_names,
    get_system_config,
    read_config,
    read_app_config,
    read_clients_config,
)
from lint_config import lint_all as lint_all_configs, lint_file as lint_single_config
from native_mounts import (
    build_unc_path,
    get_mount_status,
    mount_entry,
    probe_entry,
    reconcile_mounts,
    unmount_entry,
    write_credentials_file,
    normalize_target_subpath,
)
from post_process import PostProcessor
from sync_database import DatabaseSync

app = FastAPI(
    title="TransFS API",
    description="""
TransFS (Transforming File System) API provides endpoints for:
* **Download Management**: Install software packs for retro computing systems
* **File Browsing**: Browse native and virtual file systems
* **Database Sync**: Synchronize file metadata with PostgreSQL
* **Cache Management**: Control directory and attribute caching
* **System Configuration**: Manage clients, systems, and packs

Downloads are shared across all clients - the same source files work for MiSTer, RetroBat, MAME, and other platforms.
    """,
    version="1.0.0",
    contact={
        "name": "TransFS Project",
        "url": "https://github.com/GlennPegden2/TransFS",
    },
    license_info={
        "name": "MIT",
    },
    root_path="/api",
    openapi_url="/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
)

_dat_import_jobs: dict[str, dict] = {}
_dat_import_jobs_lock = threading.Lock()


# ============================================================================
# SECURITY VALIDATION FUNCTIONS
# ============================================================================

def _safe_join(base: str, *parts: str) -> str:
    """Join path parts and ensure the result stays within base."""
    base_abs = os.path.abspath(base)
    candidate = os.path.abspath(os.path.join(base_abs, *parts))
    if os.path.commonpath([base_abs, candidate]) != base_abs:
        raise ValueError(f"Path traversal detected: {candidate}")
    return candidate


def _ensure_safe_relpath(rel: str) -> str:
    """Ensure a user/config-supplied relative path cannot escape its base."""
    if rel is None:
        return ""
    rel = rel.strip()
    if rel in {"", "."}:
        return ""
    candidate = Path(rel)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError(f"Unsafe relative path: {rel}")
    # Normalize separators to avoid platform surprises
    return str(candidate.as_posix())


def _safe_filename(name: str) -> str:
    """Return a basename-only filename and reject unsafe values."""
    candidate = os.path.basename(name or "").strip()
    if candidate in {"", ".", ".."}:
        raise ValueError(f"Unsafe filename: {name}")
    if ".." in Path(candidate).parts:
        raise ValueError(f"Unsafe filename: {name}")
    return candidate


def _normalize_mount_id(mount_id: str | None) -> str:
    candidate = (mount_id or "").strip()
    if not candidate:
        candidate = f"mount-{uuid.uuid4().hex[:8]}"
    candidate = re.sub(r"[^a-zA-Z0-9_-]", "-", candidate)
    return candidate[:64]


def _read_app_yaml() -> dict:
    app_config_path = "config/app.yaml"
    with open(app_config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _write_app_yaml(app_config: dict) -> None:
    app_config_path = "config/app.yaml"
    with open(app_config_path, "w", encoding="utf-8") as f:
        yaml.dump(app_config, f, default_flow_style=False, sort_keys=False)


def _native_mount_entries_from_app_config(app_config: dict) -> list[dict]:
    entries = app_config.get("native_external_mounts", [])
    if not isinstance(entries, list):
        return []
    out = []
    for entry in entries:
        if isinstance(entry, dict):
            out.append(dict(entry))
    return out


def _public_native_mount_entry(config: dict, entry: dict) -> dict:
    status = get_mount_status(config, entry)
    status["id"] = entry.get("id")
    status["display_name"] = entry.get("display_name") or entry.get("id")
    status["extra_options"] = entry.get("extra_options") or []
    status["unc_path"] = build_unc_path(entry)
    return status


def _prepare_native_mount_entry(
    config: dict,
    payload: dict,
    existing_entry: dict | None = None,
) -> dict:
    existing_entry = existing_entry or {}

    mount_id = _normalize_mount_id(payload.get("id") or existing_entry.get("id"))
    enabled = bool(payload.get("enabled", existing_entry.get("enabled", True)))
    guest = bool(payload.get("guest", existing_entry.get("guest", False)))
    read_only = bool(payload.get("read_only", existing_entry.get("read_only", False)))
    auto_reconnect = bool(payload.get("auto_reconnect", existing_entry.get("auto_reconnect", True)))
    target_subpath = normalize_target_subpath(
        payload.get("target_subpath", existing_entry.get("target_subpath", ""))
    )
    smb_host = (payload.get("smb_host", existing_entry.get("smb_host", "")) or "").strip()
    smb_share = (payload.get("smb_share", existing_entry.get("smb_share", "")) or "").strip().strip("/")
    smb_subpath = _ensure_safe_relpath(
        payload.get("smb_subpath", existing_entry.get("smb_subpath", "")) or ""
    )
    vers = str(payload.get("vers", existing_entry.get("vers", "3.0")) or "3.0").strip()
    display_name = (payload.get("display_name", existing_entry.get("display_name", "")) or "").strip()
    username = (payload.get("username", existing_entry.get("username", "")) or "").strip()

    smb_port = payload.get("smb_port", existing_entry.get("smb_port"))
    if smb_port in (None, ""):
        smb_port = None
    else:
        smb_port = int(smb_port)
        if smb_port < 1 or smb_port > 65535:
            raise ValueError("smb_port must be between 1 and 65535")

    extra_options = payload.get("extra_options", existing_entry.get("extra_options", [])) or []
    if not isinstance(extra_options, list):
        raise ValueError("extra_options must be a list")
    extra_options = [str(opt).strip() for opt in extra_options if str(opt).strip()]

    if not smb_host:
        raise ValueError("smb_host is required")
    if not smb_share:
        raise ValueError("smb_share is required")

    entry = {
        "id": mount_id,
        "display_name": display_name or mount_id,
        "enabled": enabled,
        "target_subpath": target_subpath,
        "smb_host": smb_host,
        "smb_share": smb_share,
        "smb_subpath": smb_subpath,
        "smb_port": smb_port,
        "guest": guest,
        "read_only": read_only,
        "vers": vers,
        "auto_reconnect": auto_reconnect,
        "extra_options": extra_options,
        "username": username,
        "last_error": existing_entry.get("last_error", ""),
        "last_ok": existing_entry.get("last_ok", 0),
        "last_checked": existing_entry.get("last_checked", 0),
    }

    password = payload.get("password")
    if guest:
        entry["credentials_file"] = existing_entry.get("credentials_file", "")
    else:
        if not username:
            raise ValueError("username is required when guest is false")
        if password is not None:
            filestore = config.get("filestore", "/mnt/filestorefs")
            entry["credentials_file"] = write_credentials_file(filestore, mount_id, username, str(password))
        else:
            entry["credentials_file"] = existing_entry.get("credentials_file", "")
            if not entry["credentials_file"]:
                raise ValueError("password is required for new non-guest mounts")

    return entry


def _native_mount_runtime_fields(entry: dict | None) -> dict:
    entry = entry or {}
    return {
        "enabled": bool(entry.get("enabled", True)),
        "target_subpath": entry.get("target_subpath", ""),
        "smb_host": entry.get("smb_host", ""),
        "smb_share": entry.get("smb_share", ""),
        "smb_subpath": entry.get("smb_subpath", ""),
        "smb_port": entry.get("smb_port"),
        "guest": bool(entry.get("guest", False)),
        "read_only": bool(entry.get("read_only", False)),
        "vers": entry.get("vers", "3.0"),
        "extra_options": list(entry.get("extra_options") or []),
        "credentials_file": entry.get("credentials_file", ""),
        "username": entry.get("username", ""),
    }


def _safe_member_name(name: str) -> bool:
    """Reject absolute paths and any component containing '..'."""
    p = Path(name)
    return (not p.is_absolute()) and (".." not in p.parts)


def _safe_zip_members(zf: zipfile.ZipFile, pattern: str | bool | None = None):
    """Filter ZIP members for safety, optionally matching a pattern."""
    members = zf.infolist()
    filtered = []
    for info in members:
        name = info.filename
        if not _safe_member_name(name):
            continue
        if pattern is True:
            filtered.append(info)
        elif isinstance(pattern, str):
            if fnmatch.fnmatch(name, pattern):
                filtered.append(info)
        elif pattern is None:
            filtered.append(info)
    return filtered


def _safe_tar_members(tf: tarfile.TarFile, pattern: str | bool | None = None):
    """Filter TAR members for safety, optionally matching a pattern."""
    members = []
    for member in tf.getmembers():
        name = member.name
        if member.issym() or member.islnk():
            continue
        if not _safe_member_name(name):
            continue
        if pattern is True:
            members.append(member)
        elif isinstance(pattern, str):
            if fnmatch.fnmatch(name, pattern):
                members.append(member)
        elif pattern is None:
            members.append(member)
    return members


def _safe_write_file(src, dest_path: str):
    """Safely write a file to destination with directory creation."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    with open(dest_path, "wb") as dst:
        shutil.copyfileobj(src, dst)


def _safe_extract_zip_members(zf: zipfile.ZipFile, members, dest_dir: str):
    """Safely extract ZIP members to destination directory with path traversal checks."""
    for member in members:
        info = zf.getinfo(member) if isinstance(member, str) else member
        name = info.filename
        if not _safe_member_name(name):
            continue
        target_path = _safe_join(dest_dir, name)
        if info.is_dir():
            os.makedirs(target_path, exist_ok=True)
            continue
        with zf.open(info) as src:
            _safe_write_file(src, target_path)


def _safe_extract_tar_members(tf: tarfile.TarFile, members, dest_dir: str):
    """Safely extract TAR members to destination directory with path traversal checks."""
    for member in members:
        if member.issym() or member.islnk():
            continue
        name = member.name
        if not _safe_member_name(name):
            continue
        target_path = _safe_join(dest_dir, name)
        if member.isdir():
            os.makedirs(target_path, exist_ok=True)
            continue
        extracted = tf.extractfile(member)
        if extracted:
            _safe_write_file(extracted, target_path)


def _safe_extract_rar_members(rf: rarfile.RarFile, members, dest_dir: str):
    """Safely extract RAR members to destination directory with path traversal checks."""
    for name in members:
        if not _safe_member_name(name):
            continue
        if name.endswith("/"):
            os.makedirs(_safe_join(dest_dir, name), exist_ok=True)
            continue
        with rf.open(name) as src:
            _safe_write_file(src, _safe_join(dest_dir, name))


def _validate_outbound_url(url: str, allowed_hosts: set[str]):
    """Validate outbound URLs against an allowlist of hosts."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL must include a hostname")
    host = parsed.hostname.lower()
    if allowed_hosts and host not in allowed_hosts:
        raise ValueError(f"Host '{host}' not in allowlist")


def _is_transfs_cmd(cmd: str) -> bool:
    """Detect TransFS FUSE process command line."""
    if "python3 -m transfs" in cmd or "python -m transfs" in cmd:
        return True
    if "transfs.py" in cmd and "debugpy" in cmd:
        return True
    return False


def _find_transfs_pids() -> tuple[list[int], str | None]:
    """Return PIDs of TransFS FUSE process(es)."""
    try:
        output = subprocess.check_output(["ps", "-eo", "pid,args"], text=True)
    except Exception as exc:  # pylint: disable=broad-except
        return [], str(exc)

    pids: list[int] = []
    for line in output.splitlines()[1:]:
        parts = line.strip().split(None, 1)
        if len(parts) != 2:
            continue
        pid_str, cmd = parts
        if _is_transfs_cmd(cmd):
            try:
                pids.append(int(pid_str))
            except ValueError:
                continue
    return pids, None


def _unmount_fuse(mountpoint: str) -> dict:
    """Best-effort unmount of FUSE mountpoint."""
    for cmd in ("fusermount3", "fusermount"):
        if shutil.which(cmd):
            result = subprocess.run([cmd, "-u", mountpoint], capture_output=True, text=True, check=False)
            return {"command": cmd, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    if shutil.which("umount"):
        result = subprocess.run(["umount", mountpoint], capture_output=True, text=True, check=False)
        return {"command": "umount", "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}
    return {"command": None, "returncode": -1, "stdout": "", "stderr": "No unmount command available"}


# ============================================================================
# END SECURITY VALIDATION FUNCTIONS
# ============================================================================


def normalize_source_urls(source: dict, default_folder: str = "") -> list[dict]:
    """
    Normalize source URL configuration to a list of URL objects.
    
    Supports:
    1. Legacy single url: {"url": "...", "folder": "...", "extract_from_archive": [...]}
    2. Simple urls list: {"urls": ["url1", "url2"], "folder": "..."}
    3. Rich urls list: {"urls": [{"url": "...", "folder": "...", "extract_from_archive": [...]}, ...]}
    4. Auto-extract: {"url": "...", "folder": "...", "extract": true} or {"extract": "*.hdf"}
    
    Returns list of dicts with: url, folder, extract_from_archive, extract
    """
    default_extract = source.get("extract_from_archive")
    default_extract_auto = source.get("extract")  # true, "*.pattern", or None
    source_folder = source.get("folder", default_folder)
    
    # Handle legacy single URL
    if "url" in source:
        return [{
            "url": source["url"],
            "folder": source_folder,
            "extract_from_archive": default_extract,
            "extract": default_extract_auto
        }]
    
    # Handle new urls list
    urls_list = source.get("urls", [])
    if not urls_list:
        return []
    
    normalized = []
    for url_entry in urls_list:
        # Simple string URL
        if isinstance(url_entry, str):
            normalized.append({
                "url": url_entry,
                "folder": source_folder,
                "extract_from_archive": default_extract,
                "extract": default_extract_auto
            })
        # Rich URL object
        elif isinstance(url_entry, dict):
            normalized.append({
                "url": url_entry.get("url"),
                "folder": url_entry.get("folder", source_folder),
                "extract_from_archive": url_entry.get("extract_from_archive", default_extract),
                "extract": url_entry.get("extract", default_extract_auto)
            })
    
    return normalized


def _sanitize_source_folder_name(source_name: str) -> str:
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", (source_name or "").strip())
    return sanitized or "source"


def _is_bios_folder(folder: str) -> bool:
    if not folder:
        return False
    normalized = folder.replace("\\", "/").lower().strip("/")
    if normalized == "bios" or normalized.startswith("bios/"):
        return True
    return "/bios/" in f"/{normalized}/"


def _resolve_source_folder(
    source_name: str,
    folder: str,
    download_layout: str,
    base_path_rel: str | None = None,
) -> str:
    folder = folder or ""
    if download_layout != "legacy_source_based":
        return folder
    if _is_bios_folder(folder):
        return folder

    normalized = folder.replace("\\", "/").lower()
    if "sources/" in normalized:
        return folder

    safe_name = _sanitize_source_folder_name(source_name)
    if base_path_rel:
        base_norm = base_path_rel.replace("\\", "/").lower().rstrip("/")
        if base_norm.endswith("software"):
            return os.path.join("Sources", safe_name)

    return os.path.join("Software", "Sources", safe_name)


def _get_download_layout_for_system(clients: list, manufacturer: str, canonical_name: str) -> str:
    for client in clients:
        client_layout = client.get("download_layout")
        for system in client.get("systems", []):
            system_canonical = system.get("system_mapping_name") or system.get("cananonical_system_name")
            if system.get("manufacturer") == manufacturer and system_canonical == canonical_name:
                return system.get("download_layout", client_layout or "folder_based")
    return "folder_based"


class DownloadRequest(BaseModel):
    """Request model for download endpoints."""
    manufacturer: str
    system: str


class BuildRequest(BaseModel):
    """Request model for build endpoints."""
    builds: list  # List of dicts: {"manufacturer": ..., "system": ...}
    clients: list  # List of client names


class PackInstallRequest(BaseModel):
    """Request model for pack installation."""
    client: str
    system: str
    pack_ids: list[str]  # List of pack IDs to install
    skip_existing: bool = True  # Deduplicate - skip files that already exist
    update_db: bool = True  # Run database sync after install


class PackInstallRequestNoClient(BaseModel):
    """Request model for client-agnostic pack installation."""
    pack_ids: list[str]  # List of pack IDs to install
    skip_existing: bool = True  # Deduplicate - skip files that already exist
    update_db: bool = True  # Run database sync after install


class MetadataScanRequest(BaseModel):
    """Request model for metadata scan preview and apply."""
    folder: str
    provider_id: str
    recursive: bool = True
    limit: int = 200


class DatImportStartRequest(BaseModel):
    """Request model for starting a tracked DAT/XML import."""
    dat_path: str
    xml_format: str


class DatGenerateClientConfigRequest(BaseModel):
    """Request model for generating a client config from an imported DAT catalog."""
    dat_import_id: int
    config_set_name: str
    system_name: str
    client_name: str = "MiSTer"
    manufacturer: str = "Imported"
    system_mapping_name: Optional[str] = None
    local_base_path: Optional[str] = None
    output_filename: Optional[str] = None


class MetadataEntryUpdateRequest(BaseModel):
    """Request model for updating a metadata entry."""
    file_id: int
    source_path: Optional[str] = None
    virtual_path: Optional[str] = None
    file_extension: Optional[str] = None
    system: Optional[str] = None
    client: Optional[str] = None
    map_name: Optional[str] = None
    content_type: Optional[str] = None
    is_archive: Optional[bool] = None
    archive_format: Optional[str] = None
    transfs_path: Optional[str] = None
    metadata_extension: Optional[str] = None
    title: Optional[str] = None
    media_type: Optional[str] = None
    release_year: Optional[int] = None
    release_date: Optional[str] = None
    release_precision: Optional[str] = None
    rom_size: Optional[int] = None
    genre: Optional[str] = None
    app_type: Optional[str] = None
    is_revision: Optional[bool] = None
    publisher: Optional[str] = None
    region: Optional[str] = None
    language: Optional[str] = None
    is_prototype: Optional[bool] = None
    is_homebrew: Optional[bool] = None
    metadata_provider: Optional[str] = None
    metadata_source: Optional[str] = None
    metadata_tags: Optional[list[str]] = None
    pack_names: Optional[list[str]] = None


class MetadataEntryDeleteRequest(BaseModel):
    """Request model for deleting metadata for a single file."""
    file_id: int


class MetadataClearAllRequest(BaseModel):
    """Request model for deleting all metadata records."""
    confirm_text: str


class SnapshotCaptureRequest(BaseModel):
    """Request model for capturing a locked snapshot baseline."""
    snapshot_name: str
    transfs_path: str
    max_depth: int = 3


class SnapshotCompareRequest(BaseModel):
    """Request model for comparing current state to a locked baseline."""
    snapshot_name: str
    transfs_path: Optional[str] = None
    max_depth: Optional[int] = None


class LintConfigRequest(BaseModel):
    scope: str = "all"  # all | app | clients | sources | file
    file_path: Optional[str] = None


def _ensure_db_for_metadata() -> None:
    """Best-effort DB pool initialization for metadata endpoints."""
    try:
        from db.connection import init_database  # pylint: disable=import-outside-toplevel
        init_database(pool_size=30, max_overflow=40)
    except Exception:
        # Pool is likely already initialized.
        pass


def _ensure_metadata_schema_compat() -> None:
    """Ensure metadata columns needed by browser/editor exist on older DBs."""
    from db.connection import get_cursor  # pylint: disable=import-outside-toplevel

    with get_cursor() as cursor:
        cursor.execute("ALTER TABLE file_metadata ADD COLUMN IF NOT EXISTS metadata_provider TEXT")
        cursor.execute("ALTER TABLE file_metadata ADD COLUMN IF NOT EXISTS metadata_source TEXT")
        cursor.execute("ALTER TABLE file_metadata ADD COLUMN IF NOT EXISTS metadata_applied_at BIGINT")


def _append_dat_import_log(job_id: str, message: str) -> None:
    with _dat_import_jobs_lock:
        job = _dat_import_jobs.get(job_id)
        if not job:
            return
        logs = job.setdefault("logs", [])
        logs.append(message)
        if len(logs) > 1000:
            del logs[:-1000]
        job["updated_at"] = int(time.time())


def _update_dat_import_job(job_id: str, **fields) -> None:
    with _dat_import_jobs_lock:
        job = _dat_import_jobs.get(job_id)
        if not job:
            return
        job.update(fields)
        job["updated_at"] = int(time.time())


@app.get("/logs", response_class=PlainTextResponse, tags=["System"])
def get_logs():
    try:
        with open("/tmp/transfs.log", "r", encoding="utf-8") as f:
            return f.read()[-10000:]  # Return last 10k chars (or whatever you want)
    except Exception as e:  # pylint: disable=broad-except
        return f"Could not read log: {e}"

@app.get("/source-paths", tags=["File Browsing"])
def api_source_paths(path: str):
    """Get the real filestore path(s) that back a virtual path.
    
    For tooltips and debugging, returns the actual filestore location(s)
    that a virtual path maps to via clients.yaml configuration.
    """
    try:
        import logging
        from pathlib import Path as PathLib
        from sourcepath import get_source_path, get_transform_pipeline_for_file
        from pathutils import get_client, get_system_info
        
        logger = logging.getLogger("api")
        config = read_clients_config()
        if not isinstance(config, dict) or 'clients' not in config:
            config = read_config()
        
        # Only allow virtual paths
        if not path.startswith("/mnt/transfs"):
            return {"error": "Only virtual paths (/mnt/transfs/...) are supported"}
        
        # Get the source path using the same resolution logic as the filesystem
        source_path = get_source_path(logger, config, "/mnt/transfs", path)
        
        if source_path is None:
            # Path doesn't exist yet or can't be resolved
            # Return best guess based on standard mapping
            return {"source_paths": [], "error": "Path could not be resolved"}
        
        # Handle different return types from get_source_path
        source_paths = []
        transform_info = {"is_transformed": False}
        if isinstance(source_path, str):
            # Simple string path
            source_paths = [source_path]
            # Attempt to detect transforms based on real file extension
            try:
                if os.path.isfile(source_path):
                    path_parts = PathLib(path).parts
                    root_parts = PathLib("/mnt/transfs").parts
                    rel_parts = path_parts[len(root_parts):]
                    if len(rel_parts) >= 3:
                        client = get_client(config, rel_parts)
                        if client:
                            path_template_parts = PathLib(client['default_target_path']).parts
                            system_info = get_system_info(client, list(rel_parts), path_template_parts)
                            if system_info:
                                virtual_folder = rel_parts[2]
                                real_filename = os.path.basename(source_path)
                                cache_config = config.get("cache", {}) if isinstance(config, dict) else {}
                                pipeline = get_transform_pipeline_for_file(
                                    logger,
                                    system_info,
                                    real_filename,
                                    virtual_folder,
                                    cache_config,
                                )
                                if pipeline:
                                    transform_info = {
                                        "is_transformed": True,
                                        "output_extension": pipeline.output_extension,
                                    }
            except Exception:  # pylint: disable=broad-except
                pass
        elif isinstance(source_path, tuple):
            # ZIP tuple (zip_path, internal_path)
            zip_path, internal_path = source_path
            source_paths = [f"{zip_path}/{internal_path}"]
        elif isinstance(source_path, dict) and 'path' in source_path:
            # Transform pipeline dict
            source_paths = [source_path['path']]
            pipeline = source_path.get('transform_pipeline')
            if pipeline:
                transform_info = {
                    "is_transformed": True,
                    "output_extension": pipeline.output_extension,
                }
        
        return {"source_paths": source_paths, "path": path, "transform": transform_info}
    except Exception as e:  # pylint: disable=broad-except
        import logging
        logger = logging.getLogger("api")
        logger.error(f"Error resolving source paths for {path}: {e}", exc_info=True)
        return {"error": str(e), "source_paths": []}

@app.get("/browse", tags=["File Browsing"])
def api_browse_directory(path: str):
    """Browse a directory and return its contents with metadata and cache status.
    
    Supports both regular directories and archive exploration:
    - Regular: /path/to/dir
    - Archive: /path/to/file.7z#inner/path (after # is the path inside the archive)
    """
    import time
    start_time = time.time()
    
    # Validate path is within allowed directories
    allowed_prefixes = ["/mnt/filestorefs", "/mnt/transfs"]
    if not any(path.startswith(prefix) for prefix in allowed_prefixes):
        return {"error": "Access denied - path must be within allowed directories"}
    
    # Normalize path to prevent directory traversal
    path = os.path.normpath(path)
    print(f"[BROWSE] validation done, elapsed={time.time()-start_time:.4f}s", flush=True)
    
    # Check if this is an archive browse path (format: /path/to/file.7z#inner/path)
    archive_inner_path = None
    if "#" in path:
        real_path, archive_inner_path = path.split("#", 1)
        path = real_path
    
    # For virtual paths, determine supports_zaparoo flag from system config
    supports_zaparoo = None
    if path.startswith("/mnt/transfs"):
        from pathutils import get_client, get_system_info, find_software_archive_entry, find_map_entry, get_map_config
        from pathlib import Path as PathLib
        
        config = read_config()
        print(f"[BROWSE] config read done, elapsed={time.time()-start_time:.4f}s", flush=True)
        parts = PathLib(path).parts
        root_parts = PathLib("/mnt/transfs").parts
        rel_parts = parts[len(root_parts):]
        
        # Need at least client/system to determine zaparoo support
        if len(rel_parts) >= 2:
            client = get_client(config, rel_parts)
            print(f"[BROWSE] get_client done, elapsed={time.time()-start_time:.4f}s", flush=True)
            if client:
                system = next((s for s in client.get('systems', []) if s['name'] == rel_parts[1]), None)
                print(f"[BROWSE] system lookup done, elapsed={time.time()-start_time:.4f}s", flush=True)
                if system:
                    if len(rel_parts) >= 3:
                        map_name = rel_parts[2]
                        map_entry = find_map_entry(system, map_name)
                        print(f"[BROWSE] find_map_entry done, elapsed={time.time()-start_time:.4f}s", flush=True)
                        map_config = get_map_config(map_entry)
                        print(f"[BROWSE] get_map_config done, elapsed={time.time()-start_time:.4f}s", flush=True)
                        if map_config and isinstance(map_config, dict):
                            query_cfg = map_config.get("query", {})
                            supports_zaparoo = query_cfg.get("supports_zaparoo")
                    if supports_zaparoo is None:
                        sa_entry = find_software_archive_entry(system)
                        print(f"[BROWSE] find_software_archive_entry done, elapsed={time.time()-start_time:.4f}s", flush=True)
                        if sa_entry:
                            supports_zaparoo = sa_entry.get("...SoftwareArchives...", {}).get("supports_zaparoo", True)
        
        print(f"[BROWSE] zaparoo config done, elapsed={time.time()-start_time:.4f}s", flush=True)
    
    # If browsing inside an archive, list archive contents instead of filesystem
    if archive_inner_path is not None:
        print(f"[BROWSE] browsing archive contents: {path}#{archive_inner_path}", flush=True)
        if not os.path.isfile(path):
            return {"error": "Archive file does not exist"}
        
        try:
            from zippath import listdir_with_info
            items = listdir_with_info(f"{path}#{archive_inner_path}")
            entries = []
            for item in items:
                entry_type = "directory" if item["is_dir"] else "file"
                entries.append({
                    "name": item["name"],
                    "type": entry_type,
                    "size": item.get("size"),
                    "supports_zaparoo": False
                })
            return {"path": path + "#" + archive_inner_path, "entries": entries}
        except Exception as e:  # pylint: disable=broad-except
            print(f"[BROWSE] error listing archive: {e}", flush=True)
            return {"error": f"Failed to list archive contents: {str(e)}"}
    
    if not os.path.exists(path):
        return {"error": "Path does not exist"}
    print(f"[BROWSE] exists check done, elapsed={time.time()-start_time:.4f}s", flush=True)
    
    if not os.path.isdir(path):
        return {"error": "Path is not a directory"}
    print(f"[BROWSE] isdir check done, elapsed={time.time()-start_time:.4f}s", flush=True)
    
    # NOTE: For virtual paths under /mnt/transfs, we rely on reading from the FUSE mount point
    # directly. This ensures consistency with preserve_structure and other FUSE-level features.
    # The FUSE filesystem handles all directory composition and file listing logic.
    
    try:
        # Standard method for all paths (including /mnt/transfs) to accurately
        # reflect the live FUSE layer.
        entries = []
        entry_count = 0
        entry_list = list(os.scandir(path))
        total_entries = len(entry_list)
        
        # For very large directories (>1000 files), use fast path - skip all stat calls
        if total_entries > 1000:
            for entry in entry_list:
                # Simple heuristic: files typically have extensions, directories don't
                # This avoids 3500+ FUSE getattr() calls for is_dir() checks
                name = entry.name
                is_probably_dir = '.' not in name
                entries.append({
                    "name": name,
                    "type": "directory" if is_probably_dir else "file",
                    "size": None,  # Skip size for performance
                    "supports_zaparoo": supports_zaparoo
                })
        else:
            # Normal path for smaller directories - full stat information
            for entry in entry_list:
                try:
                    # Use DirEntry methods which may use cached data from readdir
                    is_dir = entry.is_dir(follow_symlinks=False)
                    
                    # Check if this is a 7z/zip archive file
                    is_archive = False
                    if not is_dir:
                        from zippath import is_supported_archive_name
                        is_archive = is_supported_archive_name(entry.name)
                    
                    size = None
                    if not is_dir:
                        try:
                            size = entry.stat(follow_symlinks=False).st_size
                        except (PermissionError, OSError):
                            pass
                    
                    entry_type = "archive" if is_archive else ("directory" if is_dir else "file")
                    entries.append({
                        "name": entry.name,
                        "type": entry_type,
                        "size": size,
                        "supports_zaparoo": supports_zaparoo
                    })
                except (PermissionError, OSError):
                    # Skip entries we can't access
                    continue
        
        return {"path": path, "entries": entries}
    except PermissionError:
        return {"error": "Permission denied"}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/metadata/providers", tags=["Metadata"])
def metadata_providers():
    """List available metadata providers for the active source config set."""
    try:
        from metadata.providers import MetadataProviderRegistry

        registry = MetadataProviderRegistry(config_dir="config")
        providers = registry.list_providers()
        return {
            "providers": [
                {
                    "id": provider.id,
                    "name": provider.name,
                    "kind": provider.kind,
                    "config": provider.config,
                }
                for provider in providers
            ]
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/metadata/xml-formats", tags=["Metadata"])
def metadata_xml_formats():
    """List configured XML/DAT parser formats available for manual import."""
    try:
        from metadata.dat_importer import DatImportService

        service = DatImportService(config_dir="config")
        return {
            "default_dat_folder": service.default_dat_folder(),
            "formats": [
                {"id": name, "definition": definition}
                for name, definition in sorted(service.xml_formats().items())
            ],
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/metadata/dat-files", tags=["Metadata"])
def metadata_dat_files(folder: str = ""):
    """List candidate DAT/XML files and highlight which are new or changed since import."""
    try:
        _ensure_db_for_metadata()
        from metadata.dat_importer import DatImportService

        service = DatImportService(config_dir="config")
        return service.list_dat_files(folder=folder or None)
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/metadata/configured-client-names", tags=["Metadata"])
def metadata_configured_client_names():
    """List configured client names across config/clients/* sets for combobox suggestions."""
    try:
        config_dir = "config"
        app_cfg = read_app_config(config_dir) or {}
        active_client_config = app_cfg.get("config_sets", {}).get("active_client_config", "default")

        client_sets_dir = os.path.join(config_dir, "clients")
        config_sets: list[str] = []
        if os.path.isdir(client_sets_dir):
            for entry in sorted(os.listdir(client_sets_dir)):
                candidate = os.path.join(client_sets_dir, entry)
                if os.path.isdir(candidate):
                    config_sets.append(entry)

        if not config_sets:
            config_sets = [active_client_config]

        by_config_set: dict[str, list[str]] = {}
        all_names: set[str] = set()
        for config_set in config_sets:
            loaded = read_clients_config(config_dir, config_set=config_set) or {"clients": []}
            names = sorted({
                client.get("name", "").strip()
                for client in loaded.get("clients", [])
                if isinstance(client, dict) and client.get("name")
            })
            by_config_set[config_set] = names
            all_names.update(names)

        return {
            "active_client_config": active_client_config,
            "client_names": sorted(all_names),
            "by_config_set": by_config_set,
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/metadata/dat-upload", tags=["Metadata"])
async def metadata_dat_upload(
    folder: str = Form(""),
    file: UploadFile = File(...),
):
    """Upload a DAT/XML file from browser and store it in the selected DAT folder."""
    try:
        from metadata.dat_importer import DatImportService

        service = DatImportService(config_dir="config")
        target_folder = os.path.normpath((folder or "").strip() or service.default_dat_folder())
        if not target_folder.startswith("/mnt/filestorefs"):
            return {"error": "Folder must be inside /mnt/filestorefs"}

        os.makedirs(target_folder, exist_ok=True)
        filename = _safe_filename(file.filename or "")
        if not filename.lower().endswith((".dat", ".xml")):
            return {"error": "Only .dat or .xml files are supported"}

        destination_path = _safe_join(target_folder, filename)
        total_bytes = 0
        with open(destination_path, "wb") as output:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                total_bytes += len(chunk)

        return {
            "folder": target_folder,
            "filename": filename,
            "path": destination_path,
            "size": total_bytes,
            "mtime": int(os.path.getmtime(destination_path)),
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}
    finally:
        try:
            await file.close()
        except Exception:  # pylint: disable=broad-except
            pass


@app.get("/metadata/dat-imports", tags=["Metadata"])
def metadata_dat_imports():
    """List imported DAT/XML catalogs tracked in the database."""
    try:
        _ensure_db_for_metadata()
        from metadata.dat_importer import DatImportService

        service = DatImportService(config_dir="config")
        return {"imports": service.list_imports()}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/metadata/dat-import/start", tags=["Metadata"])
def metadata_dat_import_start(req: DatImportStartRequest):
    """Start a tracked DAT/XML import job and stream progress via polling."""
    try:
        _ensure_db_for_metadata()
        job_id = str(uuid.uuid4())
        with _dat_import_jobs_lock:
            _dat_import_jobs[job_id] = {
                "job_id": job_id,
                "status": "running",
                "dat_path": os.path.normpath(req.dat_path),
                "xml_format": (req.xml_format or "").lower().strip(),
                "logs": [],
                "started_at": int(time.time()),
                "updated_at": int(time.time()),
                "result": None,
                "error": None,
            }

        def run_job() -> None:
            from metadata.dat_importer import DatImportService

            service = DatImportService(config_dir="config")
            try:
                result = service.import_dat(
                    dat_path=req.dat_path,
                    xml_format=req.xml_format,
                    log_callback=lambda message: _append_dat_import_log(job_id, message),
                )
                _update_dat_import_job(job_id, status="completed", result=result)
            except Exception as exc:  # pylint: disable=broad-except
                service.mark_import_failed(req.dat_path, req.xml_format, str(exc))
                _append_dat_import_log(job_id, f"Import failed: {exc}")
                _update_dat_import_job(job_id, status="failed", error=str(exc))

        threading.Thread(target=run_job, daemon=True).start()
        return {"job_id": job_id, "status": "running"}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/metadata/dat-import/jobs/{job_id}", tags=["Metadata"])
def metadata_dat_import_job(job_id: str):
    """Poll a DAT/XML import job for live logs and completion state."""
    with _dat_import_jobs_lock:
        job = _dat_import_jobs.get(job_id)
        if not job:
            return {"error": f"Unknown job_id: {job_id}"}
        return {
            "job_id": job["job_id"],
            "status": job["status"],
            "dat_path": job.get("dat_path"),
            "xml_format": job.get("xml_format"),
            "started_at": job.get("started_at"),
            "updated_at": job.get("updated_at"),
            "logs": list(job.get("logs") or []),
            "result": job.get("result"),
            "error": job.get("error"),
        }


@app.post("/metadata/dat-imports/generate-client-config", tags=["Metadata"])
def metadata_generate_client_config(req: DatGenerateClientConfigRequest):
    """Generate or update a client config set from imported DAT path structure."""
    try:
        from metadata.dat_importer import DatImportService

        service = DatImportService(config_dir="config")
        return service.generate_client_config(
            dat_import_id=req.dat_import_id,
            config_set_name=req.config_set_name,
            system_name=req.system_name,
            client_name=req.client_name,
            manufacturer=req.manufacturer,
            system_mapping_name=req.system_mapping_name,
            local_base_path=req.local_base_path,
            output_filename=req.output_filename,
        )
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/metadata/scan-preview", tags=["Metadata"])
def metadata_scan_preview(req: MetadataScanRequest):
    """Scan a folder and preview metadata matches from a selected provider."""
    try:
        folder = os.path.normpath(req.folder)
        if not folder.startswith("/mnt/filestorefs"):
            return {"error": "Folder must be inside /mnt/filestorefs"}
        if not os.path.isdir(folder):
            return {"error": f"Folder does not exist: {folder}"}

        from metadata.providers import MetadataScanService

        service = MetadataScanService(config_dir="config")
        return service.scan_folder(
            folder=folder,
            provider_id=req.provider_id,
            recursive=req.recursive,
            limit=req.limit,
        )
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/metadata/apply", tags=["Metadata"])
def metadata_apply(req: MetadataScanRequest):
    """Apply metadata matches from a selected provider to database metadata tables."""
    try:
        folder = os.path.normpath(req.folder)
        if not folder.startswith("/mnt/filestorefs"):
            return {"error": "Folder must be inside /mnt/filestorefs"}
        if not os.path.isdir(folder):
            return {"error": f"Folder does not exist: {folder}"}

        from metadata.providers import MetadataScanService

        service = MetadataScanService(config_dir="config")
        return service.apply_scan_results(
            folder=folder,
            provider_id=req.provider_id,
            recursive=req.recursive,
            limit=max(req.limit, 2000),
        )
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/metadata/stats", tags=["Metadata"])
def metadata_stats():
    """Get summary statistics about metadata coverage in the database."""
    try:
        _ensure_db_for_metadata()
        _ensure_metadata_schema_compat()
        from db.connection import get_cursor  # pylint: disable=import-outside-toplevel

        with get_cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) as total_files FROM files WHERE is_directory = false"
            )
            row = cursor.fetchone()
            total_files = row["total_files"] if isinstance(row, dict) else row[0]

            cursor.execute(
                "SELECT COUNT(*) as total FROM files f JOIN file_metadata fm ON f.file_id = fm.file_id"
            )
            row = cursor.fetchone()
            total_with_metadata = row["total"] if isinstance(row, dict) else row[0]

            cursor.execute(
                """
                SELECT fm.metadata_provider, COUNT(*) as cnt
                FROM file_metadata fm
                GROUP BY fm.metadata_provider
                ORDER BY cnt DESC
                """
            )
            provider_rows = cursor.fetchall()
            by_provider = {}
            for r in provider_rows:
                key = (r["metadata_provider"] if isinstance(r, dict) else r[0]) or "unknown"
                val = r["cnt"] if isinstance(r, dict) else r[1]
                by_provider[key] = val

        return {
            "total_files": total_files,
            "total_with_metadata": total_with_metadata,
            "coverage_pct": round(total_with_metadata / total_files * 100, 1) if total_files else 0.0,
            "by_provider": by_provider,
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/metadata/entries", tags=["Metadata"])
def metadata_entries(
    search: str = "",
    publisher: str = "",
    year: int = None,
    tag: str = "",
    provider: str = "",
    page: int = 1,
    limit: int = 50,
):
    """List files that have metadata in the database, with optional filtering."""
    try:
        _ensure_db_for_metadata()
        _ensure_metadata_schema_compat()
        from db.connection import get_cursor  # pylint: disable=import-outside-toplevel

        offset = (max(page, 1) - 1) * limit
        conditions = []
        params: list = []

        if search:
            conditions.append("(f.filename ILIKE %s OR fm.title ILIKE %s)")
            params.extend([f"%{search}%", f"%{search}%"])
        if publisher:
            conditions.append("pub.name ILIKE %s")
            params.append(f"%{publisher}%")
        if year:
            conditions.append("fm.release_year = %s")
            params.append(year)
        if tag:
            conditions.append(
                "EXISTS (SELECT 1 FROM file_tags ft WHERE ft.file_id = f.file_id AND ft.tag_value = %s)"
            )
            params.append(tag)
        if provider:
            conditions.append("fm.metadata_provider = %s")
            params.append(provider)

        where = ("WHERE " + " AND ".join(conditions)) if conditions else ""

        base_from = (
            "FROM files f "
            "JOIN file_metadata fm ON f.file_id = fm.file_id "
            "LEFT JOIN publishers pub ON fm.publisher_id = pub.id "
            "LEFT JOIN regions reg ON fm.region_id = reg.id "
            "LEFT JOIN languages lang ON fm.language_id = lang.id "
            "LEFT JOIN media_types mt ON fm.media_type_id = mt.id "
            "LEFT JOIN genres gen ON fm.genre_id = gen.id "
            "LEFT JOIN app_types appt ON fm.app_type_id = appt.id"
        )

        with get_cursor() as cursor:
            cursor.execute(f"SELECT COUNT(*) as total {base_from} {where}", params)
            row = cursor.fetchone()
            total = row["total"] if isinstance(row, dict) else row[0]

            cursor.execute(
                f"""
                                SELECT f.file_id, f.filename, f.source_path, f.virtual_path,
                                             f.extension AS file_extension,
                                             f.system, f.client, f.map_name, f.content_type,
                                             f.is_archive, f.archive_format,
                                             fm.transfs_path, fm.extension AS metadata_extension,
                                             fm.title, fm.release_year, fm.release_date, fm.release_precision,
                                             fm.rom_size, fm.is_revision,
                                             mt.name AS media_type,
                                             gen.name AS genre,
                                             appt.name AS app_type,
                       pub.name AS publisher,
                       reg.name AS region,
                       lang.name AS language,
                       fm.is_prototype, fm.is_homebrew,
                                             fm.metadata_provider, fm.metadata_source, fm.metadata_applied_at,
                                             (
                                                 SELECT array_agg(ft.tag_value ORDER BY ft.tag_value)
                                                 FROM file_tags ft
                                                 WHERE ft.file_id = f.file_id AND ft.tag_type = 'metadata_tag'
                                             ) AS metadata_tags,
                                             (
                                                 SELECT array_agg(p.name ORDER BY p.name)
                                                 FROM file_packs fp
                                                 JOIN packs p ON p.pack_id = fp.pack_id
                                                 WHERE fp.file_id = f.file_id
                                             ) AS pack_names,
                                             (
                                                 SELECT array_agg(p.source ORDER BY p.name)
                                                 FROM file_packs fp
                                                 JOIN packs p ON p.pack_id = fp.pack_id
                                                 WHERE fp.file_id = f.file_id
                                             ) AS pack_sources
                {base_from}
                {where}
                ORDER BY fm.title NULLS LAST, f.filename
                LIMIT %s OFFSET %s
                """,
                params + [limit, offset],
            )
            rows = cursor.fetchall()

        def _row_to_dict(r):
            def _to_list(value):
                if value is None:
                    return []
                if isinstance(value, list):
                    return value
                if isinstance(value, tuple):
                    return list(value)
                return [value]

            if isinstance(r, dict):
                return {
                    "file_id": r["file_id"],
                    "filename": r["filename"],
                    "source_path": r["source_path"],
                    "virtual_path": r["virtual_path"],
                    "file_extension": r["file_extension"],
                    "system": r["system"],
                    "client": r["client"],
                    "map_name": r["map_name"],
                    "content_type": r["content_type"],
                    "is_archive": bool(r["is_archive"]),
                    "archive_format": r["archive_format"],
                    "transfs_path": r["transfs_path"],
                    "metadata_extension": r["metadata_extension"],
                    "title": r["title"],
                    "release_year": r["release_year"],
                    "release_date": r["release_date"],
                    "release_precision": r["release_precision"],
                    "rom_size": r["rom_size"],
                    "is_revision": bool(r["is_revision"]),
                    "media_type": r["media_type"],
                    "genre": r["genre"],
                    "app_type": r["app_type"],
                    "publisher": r["publisher"],
                    "region": r["region"],
                    "language": r["language"],
                    "is_prototype": bool(r["is_prototype"]),
                    "is_homebrew": bool(r["is_homebrew"]),
                    "metadata_provider": r["metadata_provider"],
                    "metadata_source": r["metadata_source"],
                    "metadata_applied_at": r["metadata_applied_at"],
                    "metadata_tags": _to_list(r["metadata_tags"]),
                    "pack_names": _to_list(r["pack_names"]),
                    "pack_sources": [p for p in _to_list(r["pack_sources"]) if p],
                }
            return {
                "file_id": r[0], "filename": r[1], "source_path": r[2],
                "virtual_path": r[3], "file_extension": r[4],
                "system": r[5], "client": r[6], "map_name": r[7], "content_type": r[8],
                "is_archive": bool(r[9]), "archive_format": r[10],
                "transfs_path": r[11], "metadata_extension": r[12],
                "title": r[13], "release_year": r[14], "release_date": r[15],
                "release_precision": r[16], "rom_size": r[17], "is_revision": bool(r[18]),
                "media_type": r[19], "genre": r[20], "app_type": r[21],
                "publisher": r[22], "region": r[23], "language": r[24],
                "is_prototype": bool(r[25]), "is_homebrew": bool(r[26]),
                "metadata_provider": r[27], "metadata_source": r[28], "metadata_applied_at": r[29],
                "metadata_tags": _to_list(r[30]), "pack_names": _to_list(r[31]),
                "pack_sources": [p for p in _to_list(r[32]) if p],
            }

        return {
            "total": total,
            "page": page,
            "limit": limit,
            "pages": math.ceil(total / limit) if total else 0,
            "entries": [_row_to_dict(r) for r in rows],
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/metadata/entry/update", tags=["Metadata"])
def metadata_entry_update(req: MetadataEntryUpdateRequest):
    """Update editable metadata fields for a single file_metadata record."""
    try:
        _ensure_db_for_metadata()
        _ensure_metadata_schema_compat()
        from db.connection import get_cursor  # pylint: disable=import-outside-toplevel

        def _lookup_id(cursor, table: str, name: Optional[str]) -> Optional[int]:
            if name is None:
                return None
            normalized = name.strip()
            if not normalized:
                return None
            cursor.execute(
                f"INSERT INTO {table} (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id",
                (normalized,),
            )
            row = cursor.fetchone()
            if row:
                return row["id"] if isinstance(row, dict) else row[0]
            cursor.execute(f"SELECT id FROM {table} WHERE name = %s", (normalized,))
            row = cursor.fetchone()
            if not row:
                return None
            return row["id"] if isinstance(row, dict) else row[0]

        def _normalize_optional_text(value: Optional[str]) -> Optional[str]:
            if value is None:
                return None
            normalized = value.strip()
            return normalized or None

        def _replace_metadata_tags(cursor, file_id: int, tags: list[str]) -> None:
            cursor.execute(
                "DELETE FROM file_tags WHERE file_id = %s AND tag_type = 'metadata_tag'",
                (file_id,),
            )
            for tag in sorted({t.strip() for t in tags if t and t.strip()}):
                cursor.execute(
                    "INSERT INTO file_tags (file_id, tag_type, tag_value) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (file_id, "metadata_tag", tag),
                )

        def _replace_pack_membership(cursor, file_id: int, pack_names: list[str]) -> None:
            normalized = sorted({p.strip() for p in pack_names if p and p.strip()})
            pack_ids: list[int] = []
            for pack_name in normalized:
                cursor.execute(
                    "INSERT INTO packs (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING pack_id",
                    (pack_name,),
                )
                row = cursor.fetchone()
                if row:
                    pack_ids.append(row["pack_id"] if isinstance(row, dict) else row[0])
                    continue
                cursor.execute("SELECT pack_id FROM packs WHERE name = %s", (pack_name,))
                row = cursor.fetchone()
                if row:
                    pack_ids.append(row["pack_id"] if isinstance(row, dict) else row[0])

            cursor.execute("DELETE FROM file_packs WHERE file_id = %s", (file_id,))
            for pack_id in pack_ids:
                cursor.execute(
                    "INSERT INTO file_packs (file_id, pack_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (file_id, pack_id),
                )

        with get_cursor() as cursor:
            cursor.execute("SELECT file_id FROM files WHERE file_id = %s", (req.file_id,))
            if not cursor.fetchone():
                return {"error": f"File not found for file_id={req.file_id}"}

            cursor.execute(
                "INSERT INTO file_metadata (file_id) VALUES (%s) ON CONFLICT(file_id) DO NOTHING",
                (req.file_id,),
            )

            updates = []
            params = []

            file_updates = []
            file_params = []

            if req.source_path is not None:
                file_updates.append("source_path = %s")
                file_params.append(_normalize_optional_text(req.source_path))
            if req.virtual_path is not None:
                file_updates.append("virtual_path = %s")
                file_params.append(_normalize_optional_text(req.virtual_path))
            if req.file_extension is not None:
                file_updates.append("extension = %s")
                file_params.append(_normalize_optional_text(req.file_extension))
            if req.system is not None:
                file_updates.append("system = %s")
                file_params.append(_normalize_optional_text(req.system))
            if req.client is not None:
                file_updates.append("client = %s")
                file_params.append(_normalize_optional_text(req.client))
            if req.map_name is not None:
                file_updates.append("map_name = %s")
                file_params.append(_normalize_optional_text(req.map_name))
            if req.content_type is not None:
                file_updates.append("content_type = %s")
                file_params.append(_normalize_optional_text(req.content_type))
            if req.is_archive is not None:
                file_updates.append("is_archive = %s")
                file_params.append(req.is_archive)
            if req.archive_format is not None:
                file_updates.append("archive_format = %s")
                file_params.append(_normalize_optional_text(req.archive_format))

            if req.title is not None:
                updates.append("title = %s")
                params.append(_normalize_optional_text(req.title))
            if req.transfs_path is not None:
                updates.append("transfs_path = %s")
                params.append(_normalize_optional_text(req.transfs_path))
            if req.metadata_extension is not None:
                updates.append("extension = %s")
                params.append(_normalize_optional_text(req.metadata_extension))
            if req.media_type is not None:
                updates.append("media_type_id = %s")
                params.append(_lookup_id(cursor, "media_types", req.media_type))
            if req.release_year is not None:
                updates.append("release_year = %s")
                params.append(req.release_year)
            if req.release_date is not None:
                updates.append("release_date = %s")
                params.append(_normalize_optional_text(req.release_date))
            if req.release_precision is not None:
                updates.append("release_precision = %s")
                params.append(_normalize_optional_text(req.release_precision))
            if req.rom_size is not None:
                updates.append("rom_size = %s")
                params.append(req.rom_size)
            if req.genre is not None:
                updates.append("genre_id = %s")
                params.append(_lookup_id(cursor, "genres", req.genre))
            if req.app_type is not None:
                updates.append("app_type_id = %s")
                params.append(_lookup_id(cursor, "app_types", req.app_type))
            if req.is_revision is not None:
                updates.append("is_revision = %s")
                params.append(req.is_revision)
            if req.publisher is not None:
                updates.append("publisher_id = %s")
                params.append(_lookup_id(cursor, "publishers", req.publisher))
            if req.region is not None:
                updates.append("region_id = %s")
                params.append(_lookup_id(cursor, "regions", req.region))
            if req.language is not None:
                updates.append("language_id = %s")
                params.append(_lookup_id(cursor, "languages", req.language))
            if req.is_prototype is not None:
                updates.append("is_prototype = %s")
                params.append(req.is_prototype)
            if req.is_homebrew is not None:
                updates.append("is_homebrew = %s")
                params.append(req.is_homebrew)
            if req.metadata_provider is not None:
                updates.append("metadata_provider = %s")
                params.append(_normalize_optional_text(req.metadata_provider))
            if req.metadata_source is not None:
                updates.append("metadata_source = %s")
                params.append(_normalize_optional_text(req.metadata_source))

            if file_updates:
                file_params.append(req.file_id)
                cursor.execute(
                    f"UPDATE files SET {', '.join(file_updates)} WHERE file_id = %s",
                    file_params,
                )

            if updates:
                params.append(req.file_id)
                cursor.execute(
                    f"UPDATE file_metadata SET {', '.join(updates)} WHERE file_id = %s",
                    params,
                )

            if req.metadata_tags is not None:
                _replace_metadata_tags(cursor, req.file_id, req.metadata_tags)

            if req.pack_names is not None:
                _replace_pack_membership(cursor, req.file_id, req.pack_names)

            if not updates and not file_updates and req.metadata_tags is None and req.pack_names is None:
                return {"success": True, "message": "No fields to update"}

        return {"success": True, "file_id": req.file_id}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/metadata/entry/delete", tags=["Metadata"])
def metadata_entry_delete(req: MetadataEntryDeleteRequest):
    """Delete metadata-only records for a single file_id (keeps the file record)."""
    try:
        _ensure_db_for_metadata()
        _ensure_metadata_schema_compat()
        from db.connection import get_cursor  # pylint: disable=import-outside-toplevel

        with get_cursor() as cursor:
            cursor.execute("SELECT file_id FROM files WHERE file_id = %s", (req.file_id,))
            if not cursor.fetchone():
                return {"error": f"File not found for file_id={req.file_id}"}

            cursor.execute("DELETE FROM file_tags WHERE file_id = %s AND tag_type = 'metadata_tag'", (req.file_id,))
            tags_deleted = cursor.rowcount or 0

            cursor.execute("DELETE FROM file_packs WHERE file_id = %s", (req.file_id,))
            packs_deleted = cursor.rowcount or 0

            cursor.execute("DELETE FROM file_metadata WHERE file_id = %s", (req.file_id,))
            metadata_deleted = cursor.rowcount or 0

        if metadata_deleted == 0 and tags_deleted == 0 and packs_deleted == 0:
            return {
                "success": True,
                "file_id": req.file_id,
                "message": "No metadata existed for this file",
                "metadata_deleted": metadata_deleted,
                "tags_deleted": tags_deleted,
                "pack_links_deleted": packs_deleted,
            }

        return {
            "success": True,
            "file_id": req.file_id,
            "metadata_deleted": metadata_deleted,
            "tags_deleted": tags_deleted,
            "pack_links_deleted": packs_deleted,
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/metadata/clear-all", tags=["Metadata"])
def metadata_clear_all(req: MetadataClearAllRequest):
    """Delete all metadata records, metadata tags, and file-pack metadata links."""
    try:
        if (req.confirm_text or "").strip() != "DELETE ALL METADATA":
            return {"error": "Confirmation text mismatch. Type 'DELETE ALL METADATA' to proceed."}

        _ensure_db_for_metadata()
        _ensure_metadata_schema_compat()
        from db.connection import get_cursor  # pylint: disable=import-outside-toplevel

        with get_cursor() as cursor:
            cursor.execute("SELECT COUNT(*) AS total FROM file_metadata")
            row = cursor.fetchone()
            metadata_before = row["total"] if isinstance(row, dict) else row[0]

            cursor.execute("SELECT COUNT(*) AS total FROM file_tags WHERE tag_type = 'metadata_tag'")
            row = cursor.fetchone()
            tags_before = row["total"] if isinstance(row, dict) else row[0]

            cursor.execute("SELECT COUNT(*) AS total FROM file_packs")
            row = cursor.fetchone()
            pack_links_before = row["total"] if isinstance(row, dict) else row[0]

            cursor.execute("DELETE FROM file_tags WHERE tag_type = 'metadata_tag'")
            tags_deleted = cursor.rowcount or 0

            cursor.execute("DELETE FROM file_packs")
            pack_links_deleted = cursor.rowcount or 0

            cursor.execute("DELETE FROM file_metadata")
            metadata_deleted = cursor.rowcount or 0

        return {
            "success": True,
            "metadata_deleted": metadata_deleted,
            "tags_deleted": tags_deleted,
            "pack_links_deleted": pack_links_deleted,
            "metadata_before": metadata_before,
            "tags_before": tags_before,
            "pack_links_before": pack_links_before,
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/cache/status", tags=["Cache"])
def cache_status(path: str):
    """Get cache status for a given path."""
    try:
        from dirlisting import get_cache_status
        # Translate /mnt/transfs to /mnt/filestorefs for cache lookup
        cache_path = path.replace('/mnt/transfs', '/mnt/filestorefs')
        return get_cache_status(cache_path)
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}

@app.post("/cache/clear", tags=["Cache"])
def cache_clear(path: str = None):
    """Clear stat cache for a specific path or all stat cache entries."""
    try:
        from dirlisting import clear_stat_cache_path
        # Translate /mnt/transfs to /mnt/filestorefs for cache lookup
        cache_path = path.replace('/mnt/transfs', '/mnt/filestorefs') if path else None
        return clear_stat_cache_path(cache_path)
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/cache/status-all", tags=["Cache"])
def cache_status_all(path: str | None = None):
    """Get comprehensive status for the stat cache."""
    try:
        from dirlisting import get_all_cache_status
        cache_path = path.replace('/mnt/transfs', '/mnt/filestorefs') if path else None
        return get_all_cache_status(cache_path)
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/cache/clear-getattr", tags=["Cache"])
def cache_clear_getattr():
    """Clear the stat cache (legacy getattr endpoint)."""
    try:
        from dirlisting import clear_stat_cache
        return clear_stat_cache()
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/cache/clear-all", tags=["Cache"])
def cache_clear_all():
    """Clear all caches (stat cache only)."""
    try:
        from dirlisting import clear_all_caches
        return clear_all_caches()
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/db/sync", tags=["Database"])
@app.get("/db/sync", tags=["Database"])
async def db_sync(path: str | None = None, stream: bool = False, client: str | None = None, system: str | None = None):
    """
    Synchronize database with filesystem.
    
    Args:
        path: Optional path to sync (currently ignored, syncs full filestore)
        stream: If True, returns Server-Sent Events with progress updates
        client: Optional client name to sync only that client
        system: Optional system name to sync only that system
    
    Supports filtered syncing by client and/or system for faster targeted updates.
    
    Requires database mode to be enabled.
    """
    logger = logging.getLogger("api")
    
    try:
        from config import read_config, reload_config
        from feature_flags import FeatureFlagManager
        
        reload_config()  # Always re-read YAML from disk before syncing
        config = read_config()
        flags = FeatureFlagManager(config)
        
        if not flags.is_database_mode():
            return {
                "success": False,
                "message": "Database mode is not enabled"
            }
        
        # If streaming requested, use SSE
        if stream:
            from fastapi.responses import StreamingResponse
            import json
            import asyncio
            from queue import Queue
            from threading import Thread
            
            async def generate_progress():
                from sync_database import DatabaseSync
                from db.connection import init_database
                
                # Create a queue for progress updates
                progress_queue = Queue()
                
                # Initialize database with larger pool for concurrent operations
                init_database(pool_size=100, max_overflow=100)
                
                # Send initial message
                yield f"data: {json.dumps({'status': 'starting', 'message': 'Initializing sync...'})}\n\n"
                await asyncio.sleep(0)  # Allow event loop to process
                
                # Create sync instance with progress callback
                db_sync_inst = DatabaseSync(config, progress_callback=lambda msg: progress_queue.put(msg))
                
                # Run sync in background thread
                sync_complete = False
                sync_error = None
                
                def run_sync():
                    nonlocal sync_complete, sync_error
                    try:
                        db_sync_inst.full_sync(client_filter=client, system_filter=system)
                        progress_queue.put({'status': 'done', 'stats': db_sync_inst.stats})
                    except Exception as e:
                        sync_error = str(e)
                        progress_queue.put({'status': 'error', 'message': str(e)})
                    finally:
                        sync_complete = True
                
                sync_thread = Thread(target=run_sync, daemon=True)
                sync_thread.start()
                
                # Stream progress updates
                while not sync_complete or not progress_queue.empty():
                    try:
                        # Non-blocking check for messages
                        if not progress_queue.empty():
                            msg = progress_queue.get_nowait()
                            yield f"data: {json.dumps(msg)}\n\n"
                        else:
                            # Send heartbeat to keep connection alive
                            yield ": heartbeat\n\n"
                            await asyncio.sleep(0.5)
                    except Exception as e:
                        logger.error(f"Stream error: {e}")
                        yield f"data: {json.dumps({'status': 'error', 'message': str(e)})}\n\n"
                        break
                
                # Final message
                if sync_error:
                    yield f"data: {json.dumps({'status': 'error', 'message': sync_error})}\n\n"
                else:
                    yield f"data: {json.dumps({'status': 'complete'})}\n\n"
                
            return StreamingResponse(generate_progress(), media_type="text/event-stream")
        
        # Non-streaming mode (original behavior)
        from sync_database import DatabaseSync
        from db.connection import init_database
        
        filestore_path = config.get("filestore", "/mnt/filestorefs")
        
        if client and system:
            logger.info(f"Starting database sync for client '{client}', system '{system}'")
        elif client:
            logger.info(f"Starting database sync for client '{client}'")
        elif system:
            logger.info(f"Starting database sync for system '{system}'")
        else:
            logger.info(f"Starting database sync for filestore: {filestore_path}")
        
        # Initialize database connection if needed (uses environment variables)
        # Use larger pool for concurrent operations
        init_database(pool_size=30, max_overflow=40)
        
        # Create DatabaseSync instance and run full sync with filters
        db_sync = DatabaseSync(config)
        db_sync.full_sync(client_filter=client, system_filter=system)
        
        stats = db_sync.stats
        
        return {
            "success": True,
            "message": "Database synced successfully",
            "stats": stats
        }
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Database sync failed: {e}", exc_info=True)
        return {
            "success": False,
            "message": str(e)
        }


@app.get("/fuse/status")
def fuse_status():
    """Get TransFS FUSE process status."""
    pids, err = _find_transfs_pids()
    if err:
        return {"status": "error", "detail": err}
    return {"status": "running" if pids else "stopped", "pids": pids}


@app.post("/fuse/stop")
def fuse_stop():
    """Stop the TransFS FUSE process and unmount the filesystem."""
    config = read_config()
    mountpoint = config.get("mountpoint", "/mnt/transfs") if isinstance(config, dict) else "/mnt/transfs"

    pids, err = _find_transfs_pids()
    if err:
        return {"status": "error", "detail": err}
    if not pids:
        return {"status": "stopped", "pids": []}

    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            continue

    deadline = time.time() + 5
    while time.time() < deadline:
        remaining, _ = _find_transfs_pids()
        if not remaining:
            break
        time.sleep(0.2)

    remaining, _ = _find_transfs_pids()
    if remaining:
        for pid in remaining:
            try:
                os.kill(pid, signal.SIGKILL)
            except Exception:
                continue

    unmount_result = _unmount_fuse(mountpoint)
    final_pids, _ = _find_transfs_pids()
    return {
        "status": "stopped" if not final_pids else "error",
        "pids": final_pids,
        "unmount": unmount_result,
    }


@app.post("/fuse/start")
def fuse_start():
    """Start the TransFS FUSE process if not already running."""
    config = read_config()
    mountpoint = config.get("mountpoint", "/mnt/transfs") if isinstance(config, dict) else "/mnt/transfs"

    pids, err = _find_transfs_pids()
    if err:
        return {"status": "error", "detail": err}
    if pids:
        return {"status": "running", "pids": pids}

    log_path = "/tmp/transfs.log"
    try:
        log_file = open(log_path, "ab")
    except Exception:
        log_file = subprocess.DEVNULL

    try:
        subprocess.Popen(
            ["python3", "-m", "transfs"],
            stdout=log_file,
            stderr=log_file,
            start_new_session=True,
        )
    except Exception as e:  # pylint: disable=broad-except
        return {"status": "error", "detail": str(e)}

    return {"status": "starting", "mountpoint": mountpoint, "log": log_path}


@app.get("/cache/config")
def cache_config_get():
    """Get current cache configuration."""
    try:
        from dirlisting import get_cache_config
        return {"cache": get_cache_config()}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/cache/config")
def cache_config_set(
    stat_cache_enabled: bool | None = None,
    stat_cache_save_interval: float | None = None,
    transform_pipeline_cache_enabled: bool | None = None,
    transform_output_size_cache_enabled: bool | None = None,
    readdir_direntry_cache_enabled: bool | None = None,
    readdir_skip_cache_lookup_with_direntry: bool | None = None,
):
    """Update cache configuration at runtime."""
    try:
        from dirlisting import set_cache_config, get_cache_config
        current = get_cache_config()
        if stat_cache_enabled is not None:
            current['stat_cache_enabled'] = stat_cache_enabled
        if stat_cache_save_interval is not None:
            current['stat_cache_save_interval'] = stat_cache_save_interval
        if transform_pipeline_cache_enabled is not None:
            current['transform_pipeline_cache_enabled'] = transform_pipeline_cache_enabled
        if transform_output_size_cache_enabled is not None:
            current['transform_output_size_cache_enabled'] = transform_output_size_cache_enabled
        if readdir_direntry_cache_enabled is not None:
            current['readdir_direntry_cache_enabled'] = readdir_direntry_cache_enabled
        if readdir_skip_cache_lookup_with_direntry is not None:
            current['readdir_skip_cache_lookup_with_direntry'] = readdir_skip_cache_lookup_with_direntry
        set_cache_config(current)
        return {"updated": True, "cache": current}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/cache/info")
def cache_info():
    """Get detailed cache information for the dashboard."""
    try:
        from dirlisting import get_cache_info
        return get_cache_info()
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/config")
def config_get(fields: str = None):
    """Get current application configuration.
    
    Args:
        fields: Comma-separated list of fields to return (e.g., 'ui,web_api').
                If not specified, returns all fields.
    """
    try:
        # If fields specified, only load what's needed
        if fields:
            field_list = [f.strip() for f in fields.split(',')]
            from config import read_app_config
            
            # For ui and web_api, we only need app.yaml
            if all(f in ['ui', 'web_api', 'mountpoint', 'filestore', 'database', 'native_external_mounts'] for f in field_list):
                app_config = read_app_config()
                result = {}
                for field in field_list:
                    if field == 'ui':
                        result['ui'] = app_config.get('ui', {'advanced_options': False, 'show_real_path_tooltips': True})
                    elif field == 'web_api':
                        result['web_api'] = app_config.get('web_api', {'host': '0.0.0.0', 'port': 8000})
                    elif field == 'mountpoint':
                        result['mountpoint'] = app_config.get('mountpoint', '/mnt/transfs')
                    elif field == 'filestore':
                        result['filestore'] = app_config.get('filestore', '/mnt/filestorefs')
                    elif field == 'database':
                        result['database'] = app_config.get('database', {
                            'enabled': True,
                            'mode': 'hybrid',
                            'path': '/mnt/filestorefs/.transfs_metadata.db',
                            'auto_sync': False,
                            'sync_on_startup': False
                        })
                    elif field == 'native_external_mounts':
                        result['native_external_mounts'] = app_config.get('native_external_mounts', [])
                return result
        
        # Otherwise, load full config (expensive)
        config = read_config()
        return {
            "mountpoint": config.get("mountpoint", "/mnt/transfs"),
            "filestore": config.get("filestore", "/mnt/filestorefs"),
            "web_api": config.get("web_api", {"host": "0.0.0.0", "port": 8000}),
            "ui": config.get("ui", {"advanced_options": False, "show_real_path_tooltips": True}),
            "database": config.get("database", {
                "enabled": True,
                "mode": "hybrid",
                "path": "/mnt/filestorefs/.transfs_metadata.db",
                "auto_sync": False,
                "sync_on_startup": False
            }),
            "native_external_mounts": config.get("native_external_mounts", []),
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


class ConfigUpdate(BaseModel):
    """Request body for config updates."""
    mountpoint: str | None = None
    filestore: str | None = None
    web_api: dict | None = None
    ui: dict | None = None
    database: dict | None = None
    native_external_mounts: list[dict] | None = None


class NativeMountRequest(BaseModel):
    id: str | None = None
    display_name: str | None = None
    enabled: bool = True
    target_subpath: str
    smb_host: str
    smb_share: str
    smb_subpath: str | None = None
    smb_port: int | None = None
    guest: bool = False
    username: str | None = None
    password: str | None = None
    read_only: bool = False
    vers: str = "3.0"
    auto_reconnect: bool = True
    extra_options: list[str] | None = None


class NativeMountUpdateRequest(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None
    target_subpath: str | None = None
    smb_host: str | None = None
    smb_share: str | None = None
    smb_subpath: str | None = None
    smb_port: int | None = None
    guest: bool | None = None
    username: str | None = None
    password: str | None = None
    read_only: bool | None = None
    vers: str | None = None
    auto_reconnect: bool | None = None
    extra_options: list[str] | None = None


class QueryMappingRequest(BaseModel):
    """Request body for database query mapping."""
    extensions: list[str]  # Required: list of file extensions
    limit: int = 100  # Optional: max results


@app.post("/config")
def config_set(config_update: ConfigUpdate):
    """Update application configuration."""
    try:
        # Read current config
        config = read_config()
        
        # Update fields if provided
        if config_update.mountpoint is not None:
            config["mountpoint"] = config_update.mountpoint
        if config_update.filestore is not None:
            config["filestore"] = config_update.filestore
        if config_update.web_api is not None:
            config.setdefault("web_api", {}).update(config_update.web_api)
        if config_update.ui is not None:
            config.setdefault("ui", {}).update(config_update.ui)
        if config_update.database is not None:
            config.setdefault("database", {}).update(config_update.database)
        if config_update.native_external_mounts is not None:
            config["native_external_mounts"] = config_update.native_external_mounts
        
        # Write updated app.yaml (only the top-level config keys that belong there)
        app_config_path = "config/app.yaml"
        with open(app_config_path, "r", encoding="utf-8") as f:
            app_config = yaml.safe_load(f) or {}
        
        # Update only the keys that should be in app.yaml
        if config_update.mountpoint is not None:
            app_config["mountpoint"] = config_update.mountpoint
        if config_update.filestore is not None:
            app_config["filestore"] = config_update.filestore
        if config_update.web_api is not None:
            app_config.setdefault("web_api", {}).update(config_update.web_api)
        if config_update.ui is not None:
            app_config.setdefault("ui", {}).update(config_update.ui)
        if config_update.database is not None:
            app_config.setdefault("database", {}).update(config_update.database)
        if config_update.native_external_mounts is not None:
            app_config["native_external_mounts"] = config_update.native_external_mounts
        
        with open(app_config_path, "w", encoding="utf-8") as f:
            yaml.dump(app_config, f, default_flow_style=False)

        read_config.cache_clear()
        
        return {
            "updated": True,
            "config": {
                "mountpoint": app_config.get("mountpoint", "/mnt/transfs"),
                "filestore": app_config.get("filestore", "/mnt/filestorefs"),
                "web_api": app_config.get("web_api", {"host": "0.0.0.0", "port": 8000}),
                "ui": app_config.get("ui", {"advanced_options": False}),
                "database": app_config.get("database", {
                    "enabled": True,
                    "mode": "hybrid",
                    "path": "/mnt/filestorefs/.transfs_metadata.db",
                    "auto_sync": False,
                    "sync_on_startup": False
                }),
                "native_external_mounts": app_config.get("native_external_mounts", []),
            }
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/native-mounts", tags=["Config"])
def get_native_mounts():
    """List managed Native external SMB mounts with runtime status."""
    try:
        config = read_config()
        app_config = _read_app_yaml()
        entries = _native_mount_entries_from_app_config(app_config)
        mounts = [_public_native_mount_entry(config, entry) for entry in entries]
        mounts.sort(key=lambda item: item.get("id", ""))
        return {"mounts": mounts}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/native-mounts", tags=["Config"])
def create_native_mount(request: NativeMountRequest):
    """Create a managed Native external SMB mount entry and persist it."""
    try:
        config = read_config()
        app_config = _read_app_yaml()
        entries = _native_mount_entries_from_app_config(app_config)

        payload = request.dict()
        new_entry = _prepare_native_mount_entry(config, payload)
        if any((entry.get("id") == new_entry.get("id")) for entry in entries):
            raise ValueError(f"native mount id already exists: {new_entry['id']}")

        entries.append(new_entry)
        app_config["native_external_mounts"] = entries
        _write_app_yaml(app_config)

        if bool(new_entry.get("enabled", True)):
            mount_result = mount_entry(config, new_entry)
            new_entry["last_checked"] = int(time.time())
            if mount_result.get("success"):
                new_entry["last_ok"] = int(time.time())
                new_entry["last_error"] = ""
            else:
                new_entry["last_error"] = mount_result.get("error", "mount failed")
            app_config["native_external_mounts"] = entries
            _write_app_yaml(app_config)

        read_config.cache_clear()
        return {"created": True, "mount": _public_native_mount_entry(read_config(), new_entry)}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.patch("/native-mounts/{mount_id}", tags=["Config"])
def update_native_mount(mount_id: str, request: NativeMountUpdateRequest):
    """Update a managed Native external SMB mount entry and persist it."""
    try:
        config = read_config()
        app_config = _read_app_yaml()
        entries = _native_mount_entries_from_app_config(app_config)

        idx = next((i for i, entry in enumerate(entries) if entry.get("id") == mount_id), None)
        if idx is None:
            return {"error": f"mount not found: {mount_id}"}

        existing = entries[idx]
        payload = request.dict(exclude_unset=True)
        payload["id"] = mount_id
        updated = _prepare_native_mount_entry(config, payload, existing)

        runtime_changed = _native_mount_runtime_fields(existing) != _native_mount_runtime_fields(updated)
        if runtime_changed:
            unmount_result = unmount_entry(config, existing)
            if not unmount_result.get("success"):
                return {
                    "error": unmount_result.get("error", "failed to unmount existing mount before update"),
                    "unmount": unmount_result,
                }

        entries[idx] = updated
        now = int(time.time())

        if runtime_changed and bool(updated.get("enabled", True)):
            mount_result = mount_entry(config, updated)
            updated["last_checked"] = now
            if mount_result.get("success"):
                updated["last_ok"] = now
                updated["last_error"] = ""
            else:
                updated["last_error"] = mount_result.get("error", "mount failed")
        elif runtime_changed:
            updated["last_checked"] = now
            updated["last_error"] = ""

        app_config["native_external_mounts"] = entries
        _write_app_yaml(app_config)

        read_config.cache_clear()
        return {"updated": True, "mount": _public_native_mount_entry(read_config(), updated)}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.delete("/native-mounts/{mount_id}", tags=["Config"])
def delete_native_mount(mount_id: str):
    """Delete a managed Native external SMB mount entry (best-effort unmount first)."""
    try:
        config = read_config()
        app_config = _read_app_yaml()
        entries = _native_mount_entries_from_app_config(app_config)

        idx = next((i for i, entry in enumerate(entries) if entry.get("id") == mount_id), None)
        if idx is None:
            return {"error": f"mount not found: {mount_id}"}

        entry = entries[idx]
        unmount_result = unmount_entry(config, entry)

        credentials_file = (entry.get("credentials_file") or "").strip()
        if credentials_file and os.path.exists(credentials_file):
            try:
                os.remove(credentials_file)
            except OSError:
                pass

        del entries[idx]
        app_config["native_external_mounts"] = entries
        _write_app_yaml(app_config)

        read_config.cache_clear()
        return {"deleted": True, "unmount": unmount_result}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/native-mounts/{mount_id}/mount", tags=["Config"])
def mount_native_mount(mount_id: str):
    """Manually mount a managed Native external SMB mount."""
    try:
        config = read_config()
        app_config = _read_app_yaml()
        entries = _native_mount_entries_from_app_config(app_config)
        entry = next((item for item in entries if item.get("id") == mount_id), None)
        if not entry:
            return {"error": f"mount not found: {mount_id}"}

        result = mount_entry(config, entry)
        entry["last_checked"] = int(time.time())
        if result.get("success"):
            entry["last_ok"] = int(time.time())
            entry["last_error"] = ""
        else:
            entry["last_error"] = result.get("error", "mount failed")
        app_config["native_external_mounts"] = entries
        _write_app_yaml(app_config)

        return {
            "result": result,
            "mount": _public_native_mount_entry(config, entry),
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/native-mounts/{mount_id}/unmount", tags=["Config"])
def unmount_native_mount(mount_id: str):
    """Manually unmount a managed Native external SMB mount."""
    try:
        config = read_config()
        app_config = _read_app_yaml()
        entries = _native_mount_entries_from_app_config(app_config)
        entry = next((item for item in entries if item.get("id") == mount_id), None)
        if not entry:
            return {"error": f"mount not found: {mount_id}"}

        result = unmount_entry(config, entry)
        entry["last_checked"] = int(time.time())
        if not result.get("success"):
            entry["last_error"] = result.get("error", "unmount failed")
        app_config["native_external_mounts"] = entries
        _write_app_yaml(app_config)

        return {
            "result": result,
            "mount": _public_native_mount_entry(config, entry),
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/native-mounts/reconcile", tags=["Config"])
def reconcile_native_mounts():
    """Attempt to mount all enabled auto-reconnect managed Native external mounts."""
    try:
        config = read_config()
        app_config = _read_app_yaml()
        entries = _native_mount_entries_from_app_config(app_config)
        result = reconcile_mounts(config, entries)

        now = int(time.time())
        detail_by_id = {item.get("id"): item for item in result.get("details", [])}
        for entry in entries:
            entry["last_checked"] = now
            detail = detail_by_id.get(entry.get("id"), {})
            if detail.get("success"):
                if detail.get("changed"):
                    entry["last_ok"] = now
                entry["last_error"] = ""
            elif detail:
                entry["last_error"] = detail.get("error", "mount failed")

        app_config["native_external_mounts"] = entries
        _write_app_yaml(app_config)
        result["mounts"] = [_public_native_mount_entry(config, entry) for entry in entries]
        return result
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/native-mounts/validate", tags=["Config"])
def validate_native_mount(request: NativeMountRequest):
    """Validate Native mount configuration without persisting or mounting."""
    try:
        config = read_config()
        payload = request.dict()
        entry = _prepare_native_mount_entry(config, payload)
        target = normalize_target_subpath(entry.get("target_subpath", ""))
        target_path = os.path.join(config.get("filestore", "/mnt/filestorefs"), "Native", target)
        unc_path = build_unc_path(entry)
        probe = probe_entry(config, entry)
        return {
            "valid": True,
            "target_subpath": target,
            "target_path": target_path,
            "unc_path": unc_path,
            "guest": bool(entry.get("guest", False)),
            "probe": probe,
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"valid": False, "error": str(e)}


@app.post("/native-mounts/{mount_id}/probe", tags=["Config"])
def probe_native_mount(mount_id: str):
    """Probe a saved Native external SMB mount without attempting a kernel mount."""
    try:
        config = read_config()
        app_config = _read_app_yaml()
        entries = _native_mount_entries_from_app_config(app_config)
        entry = next((item for item in entries if item.get("id") == mount_id), None)
        if not entry:
            return {"error": f"mount not found: {mount_id}"}

        result = probe_entry(config, entry)
        return {
            "probe": result,
            "mount": _public_native_mount_entry(config, entry),
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


# ============================================================================
# CONFIG SET MANAGEMENT ENDPOINTS
# ============================================================================

@app.get("/config/sets", tags=["System"])
def get_config_sets():
    """Get list of available client and source config sets."""
    try:
        from config import get_available_config_sets
        return get_available_config_sets()
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/config/sets/active", tags=["System"])
def get_active_config_sets_endpoint():
    """Get the currently active client and source config sets."""
    try:
        from config import get_active_config_sets
        return get_active_config_sets()
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


class ConfigSetSwitchRequest(BaseModel):
    """Request model for switching config sets."""
    config_type: str  # 'client' or 'source'
    config_set: str   # Name of the config set to activate


@app.post("/config/sets/switch", tags=["System"])
def switch_config_set(request: ConfigSetSwitchRequest):
    """Switch the active config set for clients or sources.
    
    This will update app.yaml and clear the config cache to force reload.
    """
    try:
        from config import set_active_config_set
        result = set_active_config_set(request.config_type, request.config_set)
        return result
    except ValueError as e:
        return {"success": False, "error": str(e)}
    except Exception as e:  # pylint: disable=broad-except
        return {"success": False, "error": str(e)}


@app.post("/config/sets/import", tags=["System"])
async def import_config_set(file: bytes, config_type: str, config_set_name: str):
    """Import a config set from a ZIP file.
    
    Args:
        file: ZIP file bytes
        config_type: 'client' or 'source'
        config_set_name: Name for the new config set (will be the folder name)
    
    The ZIP should contain:
    - For clients: *.yaml files at the root
    - For sources: manufacturer folders containing *.yaml files
    
    Returns success status and prompts to activate if successful.
    """
    try:
        import zipfile
        from io import BytesIO
        
        if not file or not config_type or not config_set_name:
            return {"success": False, "error": "Missing required parameters: file, config_type, config_set_name"}
        
        if config_type not in ['client', 'source']:
            return {"success": False, "error": "config_type must be 'client' or 'source'"}
        
        # Sanitize config set name
        config_set_name = re.sub(r'[^a-zA-Z0-9_-]', '_', config_set_name)
        
        # Determine target directory
        if config_type == 'client':
            target_dir = os.path.join("config", "clients", config_set_name)
        else:
            target_dir = os.path.join("config", "sources", config_set_name)
        
        # Check if directory exists
        directory_exists = os.path.exists(target_dir)
        
        # Extract ZIP
        zip_file = BytesIO(file)
        with zipfile.ZipFile(zip_file, 'r') as zf:
            # Validate ZIP structure
            file_list = zf.namelist()
            if config_type == 'client':
                # Expect *.yaml files at root
                yaml_files = [f for f in file_list if f.endswith('.yaml') and '/' not in f]
                if not yaml_files:
                    return {"success": False, "error": "ZIP must contain .yaml files at the root for client configs"}
            else:
                # Expect manufacturer/system.yaml structure
                yaml_files = [f for f in file_list if f.endswith('.yaml') and f.count('/') >= 1]
                if not yaml_files:
                    return {"success": False, "error": "ZIP must contain manufacturer/*.yaml structure for source configs"}
            
            # Extract files
            os.makedirs(target_dir, exist_ok=True)
            zf.extractall(target_dir)
        
        return {
            "success": True,
            "config_type": config_type,
            "config_set_name": config_set_name,
            "directory_existed": directory_exists,
            "files_imported": len(file_list),
            "prompt_activation": True
        }
        
    except zipfile.BadZipFile:
        return {"success": False, "error": "Invalid ZIP file"}
    except Exception as e:  # pylint: disable=broad-except
        return {"success": False, "error": str(e)}


@app.post("/config/reload", tags=["System"])
def reload_client_mappings():
    """Reload client and source configuration mappings from disk.
    
    This clears the config cache and forces re-reading of client/source YAML files
    on the next access. This is useful when you've modified config files (which are
    bind-mounted in Docker) without restarting the container.
    
    Returns:
        - success: True if cache was cleared
        - timestamp: Time when reload was triggered
        - message: Human-readable status message
    
    Note: The FUSE process maintains its own copy of the config in memory. For FUSE
    to pick up changes, you will need to restart the TransFS container (docker compose restart transfs).
    The web service (this API) will immediately use the reloaded config on next request.
    """
    try:
        from config import reload_config
        reload_config()
        return {
            "success": True,
            "timestamp": time.time(),
            "message": "Config cache cleared. Web service will reload mappings on next request. FUSE requires container restart.",
            "scope": "web_service_only"
        }
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Failed to reload config: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": time.time()
        }


# ============================================================================
# TEST ENDPOINTS
# ============================================================================

@app.get("/test-suites")
def get_test_suites():
    """Get available test suites."""
    return {
        "suites": [
            {
                "id": "foundation",
                "label": "Foundation Tests",
                "description": "Core application level tests"
            },
            {
                "id": "systems",
                "label": "Systems Tests",
                "description": "System-specific configuration tests"
            },
            {
                "id": "performance",
                "label": "Performance Tests",
                "description": "Performance thresholds and timing validation"
            },
            {
                "id": "snapshots",
                "label": "Snapshot Tests",
                "description": "Filesystem snapshot validation tests"
            }
        ]
    }


@app.post("/fuse/reload-config", tags=["System"])
def reload_fuse_config_endpoint():
    """Reload configuration in the FUSE process without restarting.
    
    This triggers a reload of client and source configuration mappings directly
    in the FUSE process, allowing changes to take effect immediately without
    requiring a container restart.
    
    Returns:
        - success: True if reload was successful
        - timestamp: Time when reload was triggered
        - message: Human-readable status message
        - scope: Indicates this reloads the FUSE process config
    """
    try:
        from transfs import reload_fuse_config
        result = reload_fuse_config()
        
        if result.get('success'):
            result['timestamp'] = time.time()
            result['scope'] = 'fuse_process'
            return result
        else:
            result['timestamp'] = time.time()
            return result
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Failed to trigger FUSE config reload: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "timestamp": time.time()
        }


# Global storage for test runs (in production, use a database)
_test_runs = {}
_snapshot_baseline_dir = Path("/tests/snapshots/locked")


def _safe_snapshot_name(name: str) -> str:
    """Normalize and validate snapshot name for filesystem-safe storage."""
    normalized = re.sub(r"[^a-zA-Z0-9_.-]+", "_", (name or "").strip()).strip("._-")
    if not normalized:
        raise ValueError("snapshot_name must contain at least one alphanumeric character")
    if len(normalized) > 128:
        raise ValueError("snapshot_name is too long (max 128 chars)")
    return normalized


def _ensure_valid_transfs_path(path_value: str) -> Path:
    """Ensure capture/compare paths stay under /mnt/transfs."""
    if not path_value:
        raise ValueError("transfs_path is required")

    candidate = Path(path_value)
    if not candidate.is_absolute():
        raise ValueError("transfs_path must be absolute (e.g., /mnt/transfs/RetroBat/ROMS/3DO)")

    resolved = candidate.resolve()
    transfs_root = Path("/mnt/transfs").resolve()
    if transfs_root not in resolved.parents and resolved != transfs_root:
        raise ValueError(f"transfs_path must be under {transfs_root}")

    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"transfs_path does not exist or is not a directory: {resolved}")

    return resolved


def _capture_directory_tree(path: Path, max_depth: int = 3, current_depth: int = 0) -> Dict[str, Any]:
    """Recursively capture a deterministic directory tree for baseline comparison."""
    if current_depth >= max_depth:
        return {"_type": "truncated"}

    tree: Dict[str, Any] = {"_type": "directory", "_items": {}}
    try:
        items = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower(), p.name))
        for item in items:
            if item.name.startswith("."):
                continue
            try:
                if item.is_dir():
                    tree["_items"][item.name] = _capture_directory_tree(
                        item,
                        max_depth=max_depth,
                        current_depth=current_depth + 1,
                    )
                else:
                    file_info: Dict[str, Any] = {
                        "_type": "file",
                        "size": item.stat().st_size,
                    }
                    if item.is_symlink():
                        file_info["target"] = os.path.realpath(item)
                    tree["_items"][item.name] = file_info
            except (OSError, PermissionError) as exc:
                tree["_items"][item.name] = {"_type": "error", "reason": str(exc)}
    except (OSError, PermissionError) as exc:
        return {"_type": "error", "reason": str(exc)}

    return tree


def _flatten_tree(tree: Dict[str, Any], prefix: str = "") -> Dict[str, Dict[str, Any]]:
    """Flatten tree into path->node map for readable diffs."""
    result: Dict[str, Dict[str, Any]] = {}
    node_type = tree.get("_type")
    if node_type != "directory":
        result[prefix or "/"] = tree
        return result

    for name, node in tree.get("_items", {}).items():
        node_path = f"{prefix}/{name}" if prefix else name
        result[node_path] = node
        if isinstance(node, dict) and node.get("_type") == "directory":
            result.update(_flatten_tree(node, node_path))
    return result


@app.get("/snapshots")
def list_locked_snapshots():
    """List available locked snapshot baselines."""
    _snapshot_baseline_dir.mkdir(parents=True, exist_ok=True)
    baselines = []
    for baseline_file in sorted(_snapshot_baseline_dir.glob("*.json")):
        try:
            with baseline_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
            baselines.append(
                {
                    "snapshot_name": baseline_file.stem,
                    "transfs_path": data.get("transfs_path", ""),
                    "max_depth": data.get("max_depth", 0),
                    "captured_at": data.get("captured_at", 0),
                }
            )
        except Exception as exc:  # pylint: disable=broad-except
            baselines.append({"snapshot_name": baseline_file.stem, "error": str(exc)})

    return {"success": True, "baselines": baselines}


@app.get("/snapshots/options")
def snapshot_capture_options():
    """Return configured clients/systems with per-category paths so UI can build snapshot dropdowns."""
    try:
        clients_cfg = read_clients_config()
        mount_root = "/mnt/transfs"

        # Pretty labels for well-known category keys
        _CATEGORY_LABELS = {
            "roms": "ROMs",
            "bios": "BIOS",
            "shared_bios": "Shared BIOS",
            "mame_roms": "MAME ROMs",
            "mame_bios": "MAME BIOS",
            "retroarch": "RetroArch",
        }
        # When a system has maps in multiple categories pick the most "content-rich" one as default
        _CATEGORY_PRIORITY = ["roms", "mame_roms", "bios", "mame_bios", "shared_bios", "retroarch"]

        def _render_template(template: str, client_name: str, system_name: str) -> str:
            return (
                template
                .replace("{name}", client_name)
                .replace("{system_name}", system_name)
            )

        def _get_system_paths(client_cfg: dict, system_cfg: dict) -> list:
            """Return all unique virtual paths this system is reachable under, with labels."""
            client_name = client_cfg.get("name", "")
            system_name = system_cfg.get("name", "")
            category_paths: dict = client_cfg.get("category_paths") or {}

            if not category_paths:
                # No category routing — system lives directly under client
                return [
                    {
                        "category": None,
                        "label": "System",
                        "path": f"{mount_root}/{client_name}/{system_name}",
                    }
                ]

            # Collect every category referenced by this system's maps
            categories_used: set = set()
            for map_entry in (system_cfg.get("maps") or []):
                if not isinstance(map_entry, dict):
                    continue
                for _, map_cfg in map_entry.items():
                    if isinstance(map_cfg, dict):
                        cat = map_cfg.get("category")
                        if cat and cat in category_paths:
                            categories_used.add(cat)

            if not categories_used:
                # System has no categorised maps; fall back to direct path
                return [
                    {
                        "category": None,
                        "label": "System",
                        "path": f"{mount_root}/{client_name}/{system_name}",
                    }
                ]

            # Sort categories by priority then alpha for stable ordering
            def _sort_key(cat: str) -> tuple:
                try:
                    return (0, _CATEGORY_PRIORITY.index(cat))
                except ValueError:
                    return (1, cat)

            result = []
            seen_paths: set = set()
            for cat in sorted(categories_used, key=_sort_key):
                template = category_paths[cat]
                rendered = _render_template(template, client_name, system_name)
                full_path = f"{mount_root}/{rendered}"
                if full_path in seen_paths:
                    continue
                seen_paths.add(full_path)
                result.append(
                    {
                        "category": cat,
                        "label": _CATEGORY_LABELS.get(cat, cat),
                        "path": full_path,
                    }
                )
            return result

        clients = []
        for client in clients_cfg.get("clients", []):
            client_name = client.get("name")
            if not client_name:
                continue

            systems = []
            for system in client.get("systems", []):
                system_name = system.get("name")
                if not system_name:
                    continue
                paths = _get_system_paths(client, system)
                systems.append(
                    {
                        "name": system_name,
                        "display_name": system.get("display_name", system_name),
                        # paths[0] is the default (highest priority category)
                        "paths": paths,
                    }
                )

            clients.append(
                {
                    "name": client_name,
                    "systems": sorted(
                        systems,
                        key=lambda s: (s.get("display_name", "").lower(), s.get("name", "").lower()),
                    ),
                }
            )

        clients = sorted(clients, key=lambda c: c.get("name", "").lower())
        return {
            "success": True,
            "mount_root": mount_root,
            "clients": clients,
        }
    except Exception as exc:  # pylint: disable=broad-except
        logging.getLogger("api").error("Failed to build snapshot capture options", exc_info=True)
        return {"success": False, "error": str(exc)}


@app.post("/snapshots/capture")
def capture_locked_snapshot(req: SnapshotCaptureRequest):
    """Capture a locked snapshot baseline for a verified TransFS directory."""
    try:
        snapshot_name = _safe_snapshot_name(req.snapshot_name)
        max_depth = max(1, min(int(req.max_depth), 10))
        transfs_path = _ensure_valid_transfs_path(req.transfs_path)

        tree = _capture_directory_tree(transfs_path, max_depth=max_depth)
        baseline = {
            "snapshot_name": snapshot_name,
            "transfs_path": str(transfs_path),
            "max_depth": max_depth,
            "captured_at": time.time(),
            "tree": tree,
        }

        _snapshot_baseline_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = _snapshot_baseline_dir / f"{snapshot_name}.json"
        with baseline_path.open("w", encoding="utf-8") as f:
            json.dump(baseline, f, indent=2, sort_keys=True)

        return {
            "success": True,
            "snapshot_name": snapshot_name,
            "baseline_path": str(baseline_path),
            "transfs_path": str(transfs_path),
            "max_depth": max_depth,
            "message": "Locked snapshot captured successfully",
        }
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(f"Failed to capture locked snapshot: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}


@app.post("/snapshots/compare")
def compare_locked_snapshot(req: SnapshotCompareRequest):
    """Compare current directory structure with a previously captured locked baseline."""
    try:
        snapshot_name = _safe_snapshot_name(req.snapshot_name)
        baseline_path = _snapshot_baseline_dir / f"{snapshot_name}.json"
        if not baseline_path.exists():
            return {"success": False, "error": f"Baseline not found: {snapshot_name}"}

        with baseline_path.open("r", encoding="utf-8") as f:
            baseline = json.load(f)

        baseline_path_value = baseline.get("transfs_path", "")
        transfs_path = _ensure_valid_transfs_path(req.transfs_path or baseline_path_value)
        max_depth = req.max_depth if req.max_depth is not None else baseline.get("max_depth", 3)
        max_depth = max(1, min(int(max_depth), 10))

        current_tree = _capture_directory_tree(transfs_path, max_depth=max_depth)
        expected_tree = baseline.get("tree", {})
        is_match = current_tree == expected_tree

        expected_flat = _flatten_tree(expected_tree)
        current_flat = _flatten_tree(current_tree)
        expected_paths = set(expected_flat.keys())
        current_paths = set(current_flat.keys())

        added = sorted(current_paths - expected_paths)
        removed = sorted(expected_paths - current_paths)
        changed = sorted(
            path for path in (expected_paths & current_paths)
            if expected_flat[path] != current_flat[path]
        )

        return {
            "success": True,
            "snapshot_name": snapshot_name,
            "transfs_path": str(transfs_path),
            "max_depth": max_depth,
            "match": is_match,
            "diff": {
                "added": added[:200],
                "removed": removed[:200],
                "changed": changed[:200],
                "added_count": len(added),
                "removed_count": len(removed),
                "changed_count": len(changed),
            },
        }
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    except Exception as exc:  # pylint: disable=broad-except
        logger.error(f"Failed to compare locked snapshot: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}


@app.post("/run-tests")
def run_tests(test_type: str = "snapshot"):
    """Start a test run asynchronously.
    
    Args:
        test_type: 'snapshot', 'systems', or 'foundation' (default: 'snapshot')
    """
    try:
        task_id = str(uuid.uuid4())
        
        # Map test types to their files
        test_files = {
            "snapshot": "/tests/test_filesystem_snapshots.py",
            "snapshots": "/tests/test_snapshots.py",
            "systems": "/tests/test_systems.py",
            "performance": "/tests/test_systems.py::TestSystemPerformance",
            "foundation": "/tests/test_foundation.py",
            "all": "/tests/test_*.py"
        }
        
        test_file = test_files.get(test_type, test_files["snapshot"])
        
        # Start pytest in a background subprocess
        pytest_args = ["python", "-m", "pytest", test_file, "-vv", "--tb=short", "-rs"]
        if test_type == "performance":
            # Allow PERF lines to appear in stdout for UI parsing
            pytest_args.append("-s")

        test_process = subprocess.Popen(
              pytest_args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd="/app"
        )
        
        _test_runs[task_id] = {
            "status": "running",
            "process": test_process,
            "output": "",
            "summary": {"total": 0, "passed": 0, "failed": 0},
            "progress": 0,
            "test_type": test_type
        }
        
        return {"task_id": task_id, "status": "running"}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.post("/lint-config")
def lint_config(request: LintConfigRequest):
    """Run configuration linting and return summary + per-file issues."""
    try:
        config_root = Path("/app/config").resolve()
        scope = (request.scope or "all").strip().lower()
        valid_scopes = {"all", "app", "clients", "sources", "file"}
        if scope not in valid_scopes:
            return {
                "success": False,
                "error": f"Invalid scope '{scope}'. Valid scopes: {', '.join(sorted(valid_scopes))}"
            }

        if scope == "file":
            if not request.file_path:
                return {"success": False, "error": "file_path is required when scope='file'"}

            requested = Path(request.file_path)
            resolved = requested.resolve() if requested.is_absolute() else (config_root / requested).resolve()

            # Keep linting constrained to config files
            try:
                resolved.relative_to(config_root)
            except ValueError:
                return {
                    "success": False,
                    "error": f"file_path must be within {config_root}"
                }

            if not resolved.exists() or not resolved.is_file():
                return {"success": False, "error": f"Config file not found: {resolved}"}

            result = lint_single_config(str(resolved)).to_dict()
            files = [result]
        else:
            summary = lint_all_configs(str(config_root)).to_dict()
            files = summary.get("files", [])

            if scope == "app":
                files = [f for f in files if f.get("config_type") == "app"]
            elif scope == "clients":
                files = [f for f in files if f.get("config_type") == "client"]
            elif scope == "sources":
                files = [f for f in files if f.get("config_type") == "source"]

        total_errors = sum(int(f.get("errors", 0)) for f in files)
        total_warnings = sum(int(f.get("warnings", 0)) for f in files)
        clean_files = sum(1 for f in files if f.get("status") == "ok")

        return {
            "success": True,
            "scope": scope,
            "summary": {
                "total_files": len(files),
                "total_errors": total_errors,
                "total_warnings": total_warnings,
                "clean_files": clean_files,
            },
            "files": files,
        }
    except Exception as exc:  # pylint: disable=broad-except
        logging.getLogger("api").error(f"Error running config lint: {exc}", exc_info=True)
        return {"success": False, "error": str(exc)}


@app.get("/test-results/{task_id}")
def get_test_results(task_id: str):
    """Get the status and results of a test run."""
    try:
        if task_id not in _test_runs:
            return {"status": "not_found", "error": f"Task {task_id} not found"}
        
        run = _test_runs[task_id]
        
        # Check if process is still running
        if run["process"].poll() is None:
            # Process still running, read any available output
            try:
                line = run["process"].stdout.readline()
                if line:
                    run["output"] += line
            except:
                pass
            
            return {
                "status": "running",
                "progress": 50,  # Placeholder progress
                "summary": run["summary"],
                "results": {"stdout": run["output"]},
                "task_id": task_id
            }
        else:
            # Process completed, read remaining output
            remaining = run["process"].stdout.read()
            run["output"] += remaining
            
            # Parse individual tests from output
            import re
            tests_list = []
            
            # Pattern for test start line (may have PERF lines after on same line)
            # Supports tests paths emitted as tests/..., ../tests/..., app/tests/..., ../app/tests/...
            # Match: path/to/test_file.py::ClassName::test_name[param] PERF|...
            # Stop at PERF or status keywords
            test_start_pattern = r'^((?:(?:\.\./)?(?:app/)?tests|/(?:app/)?tests)/[^\s:]+\.py)::(.+?)(?:\s+(?:PERF|PASSED|FAILED|SKIPPED|XPASS|XFAIL))'
            status_pattern = r'^\s*(PASSED|FAILED|SKIPPED|XPASS|XFAIL)(?:\s+(.*))?$'
            perf_pattern = r'PERF\|test=(.+?)\|op=(.+?)\|path=(.+?)\|actual=([\d.]+)\|target=([\d.]+)'
            ansi_escape_pattern = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

            def _normalize_test_file_path(path_value: str) -> str:
                """Normalize pytest-emitted file paths so we can map summary lines reliably."""
                if not path_value:
                    return ""

                normalized = path_value.replace('\\\\', '/').strip()
                normalized = normalized.lstrip('./')
                if normalized.startswith('/app/'):
                    normalized = normalized[len('/app/'):]
                if normalized.startswith('app/'):
                    normalized = normalized[len('app/'):]

                tests_idx = normalized.find('tests/')
                if tests_idx >= 0:
                    normalized = normalized[tests_idx:]

                return normalized

            def _strip_ansi(line_value: str) -> str:
                return ansi_escape_pattern.sub('', line_value or '')
            
            # Parse test output line by line
            test_results = {}
            current_test = None
            current_perf_data = []
            
            lines = run["output"].split('\n')
            i = 0
            while i < len(lines):
                line = _strip_ansi(lines[i])
                
                # Check for test start
                test_match = re.search(test_start_pattern, line)
                if test_match:
                    test_file = test_match.group(1).strip()
                    test_name = test_match.group(2).strip()
                    
                    test_key = f"{test_file}::{test_name}"
                    current_test = test_key
                    current_perf_data = []
                    
                    # Check if status is on same line, with optional inline reason
                    inline_status_match = re.search(
                        r'\s(PASSED|FAILED|SKIPPED|XPASS|XFAIL)(?:\s+\((.*?)\))?(?:\s+\[\s*\d+%\])?\s*$',
                        line
                    )
                    if inline_status_match:
                        status = inline_status_match.group(1)
                        inline_reason = (inline_status_match.group(2) or "").strip()
                    else:
                        # Look ahead for status on next lines
                        status = None
                        inline_reason = ""
                        j = i + 1
                        while j < len(lines) and j < i + 10:  # Look ahead max 10 lines
                            next_line = _strip_ansi(lines[j])
                            status_match = re.match(status_pattern, next_line)
                            if status_match:
                                status = status_match.group(1)
                                inline_reason = (status_match.group(2) or "").strip()
                                break
                            # Check if we hit another test (stop looking)
                            if re.search(test_start_pattern, next_line):
                                break
                            j += 1
                        
                        if not status:
                            status = "UNKNOWN"
                    
                    # Set default output based on status
                    if status == "SKIPPED":
                        default_output = "(Skipped test)"
                        reason = inline_reason if inline_reason else "Skipped (fixture or condition not met)"
                    elif status == "PASSED":
                        default_output = "(Test passed - no output captured)"
                        reason = ""
                    elif status == "FAILED":
                        default_output = "(Test failed - details below)"
                        reason = ""
                    else:
                        default_output = "(No output captured)"
                        reason = ""
                    
                    test_results[test_key] = {
                        "id": len(test_results),
                        "name": test_key,
                        "status": status,
                        "reason": reason,
                        "output": default_output,
                        "perfDetails": []
                    }
                
                # Check for PERF line anywhere in the line
                for perf_match in re.finditer(perf_pattern, line):
                    perf_test = perf_match.group(1).strip()
                    operation = perf_match.group(2).strip()
                    path = perf_match.group(3).strip()
                    actual = float(perf_match.group(4))
                    target = float(perf_match.group(5))
                    
                    # Match PERF line to current test
                    # The PERF test= value might not have the path prefix
                    if current_test:
                        # Check if PERF test matches current test (with or without path)
                        perf_test_normalized = perf_test.replace('test_systems.py::', '../tests/test_systems.py::')
                        if perf_test in current_test or current_test.endswith(perf_test) or current_test == perf_test_normalized:
                            test_results[current_test]["perfDetails"].append({
                                "operation": operation,
                                "path": path,
                                "actual": actual,
                                "target": target
                            })
                
                i += 1
            
            # Second pass: extract failure details from FAILURES section
            failures_section = False
            lines = run["output"].split('\n')
            i = 0
            while i < len(lines):
                line = lines[i]
                
                # Detect FAILURES section start
                if '=== FAILURES ===' in line or line.startswith('=== FAILURES '):
                    failures_section = True
                    i += 1
                    continue
                
                # Stop at end of failures section
                if failures_section and (line.startswith('=== warnings') or line.startswith('=== short test')):
                    failures_section = False
                
                if failures_section:
                    # Look for test failure headers: "_____ ClassName.test_method _____"
                    if line.startswith('_') and '.' in line:
                        # Extract test name from underscore-padded line
                        test_name_section = line.strip('_').strip()
                        # test_name_section is like "TestVolumeMounts.test_transfs_volume_mounted"
                        # We need to match it against keys like "../tests/test_foundation.py::TestVolumeMounts::test_transfs_volume_mounted"
                        
                        matching_test = None
                        # Convert the failure section format to match our test key format
                        # Replace first dot with :: to match ClassName::method format
                        test_key_pattern = test_name_section.replace('.', '::', 1)  # Only first dot
                        
                        for test_key in test_results.keys():
                            # Check if test key ends with the pattern
                            if test_key.endswith(test_key_pattern) or test_key_pattern in test_key:
                                matching_test = test_key
                                break
                        
                        if matching_test:
                            # Collect error lines until next test section or blank lines
                            output_lines = []
                            i += 1
                            while i < len(lines):
                                next_line = lines[i]
                                if next_line.startswith('_'):  # Next test failure
                                    i -= 1
                                    break
                                if next_line.startswith('='):  # End of failures section
                                    i -= 1
                                    break
                                output_lines.append(next_line)
                                i += 1
                            
                            # Store output (first 30 lines)
                            test_results[matching_test]["output"] = '\n'.join(output_lines[:30]).strip()
                
                i += 1
            
            # Third pass: extract skip reasons from custom test output
            # Supports:
            #   [SKIP_REASON] tests/test_file.py::Class::test_name - reason
            #   [SKIP_REASON] Human-readable reason text
            skip_reason_pattern = r'^\[SKIP_REASON\]\s+(.+)$'
            for raw_line in run["output"].split('\n'):
                line = _strip_ansi(raw_line)
                match = re.match(skip_reason_pattern, line)
                if match:
                    payload = match.group(1).strip()

                    nodeid_match = re.match(r'^([^\s]+::[^\s]+)\s+-\s+(.+)$', payload)
                    if nodeid_match:
                        test_nodeid = nodeid_match.group(1).strip()
                        skip_reason = nodeid_match.group(2).strip()

                        for result_key in test_results.keys():
                            if test_nodeid in result_key or result_key.endswith(test_nodeid):
                                test_results[result_key]["reason"] = skip_reason
                                break
                        continue

                    # If only free text is provided, try to map by [SystemName] token,
                    # otherwise apply to first skipped test still using the placeholder reason.
                    skip_reason = payload
                    system_name_match = re.match(r'^([^:]+):\s+(.+)$', skip_reason)
                    if system_name_match:
                        system_name = system_name_match.group(1).strip()
                        for result_key in test_results.keys():
                            if f"[{system_name}]" in result_key and test_results[result_key]["status"] == "SKIPPED":
                                test_results[result_key]["reason"] = skip_reason
                        continue

                    for result_key in test_results.keys():
                        if (
                            test_results[result_key]["status"] == "SKIPPED"
                            and test_results[result_key]["reason"] == "Skipped (fixture or condition not met)"
                        ):
                            test_results[result_key]["reason"] = skip_reason
                            break
            
            # Fourth pass: extract skip reasons from short summary output (pytest -rs)
            # Lines look like: "SKIPPED [1] ../tests/test_systems.py:221: Amstrad CPC: TransFS path not found at /mnt/transfs/..."
            in_skipped_section = False
            skip_line_pattern = r'^SKIPPED\s+\[(\d+)\]\s+(.+?):\s+(.+)$'

            # Build per-file ordered buckets of skipped tests still using placeholder reason.
            skipped_by_file = {}
            for result_key, result in test_results.items():
                if result.get("status") != "SKIPPED":
                    continue
                if result.get("reason") and result.get("reason") != "Skipped (fixture or condition not met)":
                    continue

                file_part = result_key.split('::', 1)[0]
                normalized_file = _normalize_test_file_path(file_part)
                if normalized_file:
                    skipped_by_file.setdefault(normalized_file, []).append(result_key)
            
            lines = run["output"].split('\n')
            for i, line in enumerate(lines):
                line = _strip_ansi(line)
                # Detect "short test summary info" section start (from -rs flag)
                if 'short test summary info' in line.lower() or 'short test summary' in line.lower():
                    in_skipped_section = True
                    continue
                
                # Stop at end of SKIPPED section
                if in_skipped_section and line.strip().startswith('==='):
                    break
                
                if in_skipped_section:
                    match = re.match(skip_line_pattern, line.strip())
                    if match:
                        skip_count = int(match.group(1)) if match.group(1) else 1
                        file_with_line = match.group(2).strip()
                        reason = match.group(3).strip()

                        file_part = file_with_line.rsplit(':', 1)[0]
                        normalized_file = _normalize_test_file_path(file_part)

                        # Try to map by system name inside the reason
                        system_name_match = re.match(r'^([^:]+):\s+(.+)$', reason)
                        if system_name_match:
                            system_name = system_name_match.group(1).strip()
                            for result_key in test_results.keys():
                                if f"[{system_name}]" in result_key and test_results[result_key]["status"] == "SKIPPED":
                                    test_results[result_key]["reason"] = reason
                            continue

                        # Otherwise, map by file order among unresolved skipped tests.
                        if normalized_file and normalized_file in skipped_by_file and skipped_by_file[normalized_file]:
                            assigned = 0
                            while assigned < skip_count and skipped_by_file[normalized_file]:
                                target_key = skipped_by_file[normalized_file].pop(0)
                                test_results[target_key]["reason"] = reason
                                assigned += 1
                            continue

                        # Last-resort fallback: assign by overall unresolved skipped order.
                        unresolved = [
                            key for key, result in test_results.items()
                            if result.get("status") == "SKIPPED"
                            and result.get("reason") == "Skipped (fixture or condition not met)"
                        ]
                        if unresolved:
                            for target_key in unresolved[:max(skip_count, 1)]:
                                test_results[target_key]["reason"] = reason
                            continue

                        # Fallback: map specific known skip reason to its test
                        if "TransFS ROM not found" in reason:
                            for result_key in test_results.keys():
                                if "test_archimedes_riscos_byte_by_byte" in result_key:
                                    test_results[result_key]["reason"] = reason
                            continue
            
            tests_list = list(test_results.values())
            # Re-index the IDs
            for idx, test in enumerate(tests_list):
                test["id"] = idx
            
            # Parse test results summary from pytest output - handle pytest summary line
            passed = run["output"].count(" PASSED")
            failed = run["output"].count(" FAILED")
            skipped = run["output"].count(" SKIPPED")
            
            # Also try to parse the pytest summary line (e.g., "17 skipped, 1 warning in 0.26s")
            summary_match = re.search(r'=+\s*([\w\d\s,]+)\s*=+', run["output"][-200:])
            if summary_match:
                summary_text = summary_match.group(1)
                # Extract numbers from summary
                passed_match = re.search(r'(\d+)\s+passed', summary_text)
                failed_match = re.search(r'(\d+)\s+failed', summary_text)
                skipped_match = re.search(r'(\d+)\s+skipped', summary_text)
                
                if passed_match or failed_match or skipped_match:
                    passed = int(passed_match.group(1)) if passed_match else passed
                    failed = int(failed_match.group(1)) if failed_match else failed
                    skipped = int(skipped_match.group(1)) if skipped_match else skipped
            
            run["summary"] = {
                "total": passed + failed + skipped,
                "passed": passed,
                "failed": failed,
                "skipped": skipped
            }
            
            return_code = run["process"].returncode
            status = "completed" if return_code == 0 else "failed"
            
            return {
                "status": status,
                "progress": 100,
                "summary": run["summary"],
                "results": {
                    "stdout": run["output"],
                    "return_code": return_code,
                    "tests": tests_list,
                    "task_id": task_id
                },
                "task_id": task_id
            }
    except Exception as e:  # pylint: disable=broad-except
        return {"status": "error", "error": str(e)}


@app.get("/test-results/last")
def get_last_test_results():
    """Get the last completed test results."""
    try:
        # Find the most recently completed test run
        last_run = None
        last_time = 0
        
        for task_id, run in _test_runs.items():
            if run["process"].poll() is not None:  # Completed
                # Use task_id creation order as proxy for time
                if not last_run:
                    last_run = (task_id, run)
        
        if not last_run:
            return {"results": None, "error": "No completed test runs found"}
        
        task_id, run = last_run
        passed = run["output"].count(" PASSED")
        failed = run["output"].count(" FAILED")
        
        return {
            "results": {
                "task_id": task_id,
                "status": "completed" if run["process"].returncode == 0 else "failed",
                "summary": {
                    "total": passed + failed,
                    "passed": passed,
                    "failed": failed
                },
                "stdout": run["output"],
                "return_code": run["process"].returncode
            }
        }
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}


@app.get("/zaparoo/status")
def zaparoo_status():
    """Check Zaparoo configuration and connectivity status for all clients."""
    try:
        config = read_config()
        zaparoo_config = config.get("zaparoo", {})
        clients = zaparoo_config.get("clients", [])

        if not clients:
            return {
                "clients": [],
                "has_enabled": False,
                "message": "No Zaparoo clients configured"
            }

        client_statuses = []
        has_enabled = False

        for client in clients:
            name = client.get("name", "unknown")
            enabled = client.get("enabled", False)
            host = client.get("host")
            port = client.get("port", 7497)
            mount_path = client.get("mount_path", "/")

            status = {
                "name": name,
                "enabled": enabled,
                "configured": bool(host),
                "host": host,
                "port": port,
                "mount_path": mount_path,
                "reachable": False,
                "message": ""
            }

            if enabled:
                has_enabled = True

            if not enabled:
                status["message"] = f"{name}: Disabled in configuration"
            elif not host:
                status["message"] = f"{name}: Host not configured"
            else:
                try:
                    zaparoo_url = f"http://{host}:{port}/"
                    response = requests.get(zaparoo_url, timeout=2)
                    status["reachable"] = response.status_code < 500
                    if status["reachable"]:
                        status["message"] = f"{name}: Reachable"
                    else:
                        status["message"] = f"{name}: Returned status {response.status_code}"
                except requests.exceptions.Timeout:
                    status["message"] = f"{name}: Connection timed out"
                except requests.exceptions.ConnectionError:
                    status["message"] = f"{name}: Cannot reach at {host}:{port}"
                except requests.exceptions.RequestException as e:
                    status["message"] = f"{name}: Connection error - {str(e)}"

            client_statuses.append(status)

        return {
            "clients": client_statuses,
            "has_enabled": has_enabled,
            "message": f"Found {len(client_statuses)} Zaparoo client(s)"
        }
    except Exception as e:  # pylint: disable=broad-except
        return {
            "clients": [],
            "has_enabled": False,
            "message": f"Error checking Zaparoo status: {str(e)}"
        }


class ZaparooLaunchRequest(BaseModel):
    """Request model for Zaparoo launch endpoint"""
    file_path: str
    client_name: str = "MiSTer"


@app.post("/zaparoo/launch")
def zaparoo_launch(request: ZaparooLaunchRequest):
    """Launch a file/game using Zaparoo remote launching."""
    logger = logging.getLogger("api")
    try:
        file_path = request.file_path
        client_name = request.client_name
        
        logger.info(f"Zaparoo launch request: file_path={file_path}, client_name={client_name}")

        config = read_config()
        zaparoo_config = config.get("zaparoo", {})
        clients = zaparoo_config.get("clients", [])

        if not clients:
            return {"error": "No Zaparoo clients configured in app.yaml"}

        client = next((c for c in clients if c.get("name") == client_name), None)
        if not client:
            available = ", ".join([c.get("name", "unknown") for c in clients])
            return {"error": f"Zaparoo client '{client_name}' not found. Available: {available}"}

        if not client.get("enabled", False):
            return {"error": f"Zaparoo client '{client_name}' is disabled in configuration"}

        host = client.get("host")
        port = client.get("port", 7497)
        mount_path = client.get("mount_path", "/")

        if not host:
            return {"error": f"Zaparoo client '{client_name}' has no host configured"}

        if not file_path.startswith("/mnt/transfs"):
            return {"error": "Invalid file path"}

        # Remove /mnt/transfs prefix and clean up any double slashes
        relative_path = file_path.replace("/mnt/transfs/", "", 1).replace("/mnt/transfs", "", 1)
        relative_path = relative_path.lstrip("/")  # Remove any leading slashes
        logger.info(f"Zaparoo relative_path after replace: {relative_path}")
        
        client_prefix = f"{client_name}/"
        if relative_path.startswith(client_prefix):
            relative_path = relative_path[len(client_prefix):]
            logger.info(f"Zaparoo relative_path after removing client prefix: {relative_path}")
        else:
            logger.error(f"Zaparoo path validation failed: relative_path='{relative_path}' does not start with client_prefix='{client_prefix}'")
            return {"error": f"Path does not belong to client '{client_name}'"}

        relative_path = relative_path.replace("\\", "/")
        mount_path = mount_path.rstrip("/")
        if mount_path == "":
            client_path = f"/{relative_path}"
        else:
            client_path = f"{mount_path}/{relative_path}"
        
        logger.info(f"Zaparoo final client_path: {client_path}")

        zaparoo_url = f"http://{host}:{port}/api/v0.1"
        # Quote the path to handle special characters (commas, question marks, etc.)
        # ZapScript requires quoting for arguments containing ',' or '?'
        zapscript = f'**launch.path:"{client_path}"'
        logger.info(f"Zaparoo zapscript: {zapscript}")

        import uuid

        def zaparoo_rpc(method: str, params: dict | None = None):
            payload = {
                "jsonrpc": "2.0",
                "id": str(uuid.uuid4()),
                "method": method,
                "params": params or {},
            }
            return requests.post(
                zaparoo_url,
                json=payload,
                timeout=2,
                headers={"Content-Type": "application/json"},
            )

        try:
            settings_resp = zaparoo_rpc("settings")
            settings_json = settings_resp.json()
            current_run_zapscript = settings_json.get("result", {}).get("runZapScript")

            if current_run_zapscript is None:
                current_run_zapscript = False

            toggled_run_zapscript = False
            if current_run_zapscript is False:
                try:
                    enable_resp = zaparoo_rpc("settings.update", {"runZapScript": True})
                    enable_json = enable_resp.json()
                    if "error" in enable_json:
                        msg = enable_json.get("error", {}).get("message", "Unknown error enabling runZapScript")
                        return {"error": f"Zaparoo error enabling ZapScript: {msg}"}
                    toggled_run_zapscript = True
                except requests.exceptions.RequestException as e:
                    return {"error": f"Failed to enable ZapScript: {str(e)}"}

            def try_run(script_text: str):
                resp = zaparoo_rpc("run", {"text": script_text})
                return script_text, resp, resp.json()

            # Quote the path to handle special characters in filenames (commas, question marks, etc.)
            # ZapScript requires quoting for arguments containing ',' or '?'
            quoted_path = f'"{client_path}"'
            attempts = [
                f"**launch:{quoted_path}",
                f"**launch {quoted_path}",
                zapscript,
                f"**launch.path {quoted_path}",
            ]

            errors = []
            for script_variant in attempts:
                logger.info(f"Zaparoo attempting script: {script_variant}")
                script_used, run_resp, run_json = try_run(script_variant)
                logger.info(f"Zaparoo response: status={run_resp.status_code}, json={run_json}")

                if "result" in run_json:
                    # Give zaparoo time to start processing the command before we restore the setting
                    # Without this delay, the restore happens before zaparoo's queue processes the token
                    # causing "ignoring ZapScript, run ZapScript is disabled" errors
                    if toggled_run_zapscript:
                        import time
                        time.sleep(0.5)  # 500ms delay
                        try:
                            zaparoo_rpc("settings.update", {"runZapScript": False})
                        except requests.exceptions.RequestException:
                            pass

                    return {
                        "success": True,
                        "message": f"Launched on {client_name}: {relative_path}",
                        "client": client_name,
                        "status_code": run_resp.status_code,
                        "zapscript": script_used,
                        "runZapScriptEnabled": True,
                        "runZapScriptToggled": toggled_run_zapscript,
                    }

                msg = run_json.get("error", {}).get("message", "Unknown error")
                errors.append({
                    "zapscript": script_variant,
                    "status_code": run_resp.status_code,
                    "message": msg,
                })

                if "unknown command" not in msg.lower():
                    break

            return {
                "error": "Zaparoo run failed",
                "client": client_name,
                "attempts": errors,
            }

        except requests.exceptions.Timeout:
            return {"error": f"Zaparoo connection to {client_name} timed out. Is it running?"}
        except requests.exceptions.ConnectionError as e:
            return {"error": f"Could not reach Zaparoo {client_name} at {host}:{port}. {str(e)}"}
        except requests.exceptions.RequestException as e:
            return {"error": f"Request to {client_name} failed: {str(e)}"}

    except Exception as e:  # pylint: disable=broad-except
        return {"error": f"Unexpected error: {str(e)}"}


@app.get("/file-metadata")
def file_metadata(path: str):
    """Get metadata for a file from the database.
    
    Args:
        path: Virtual filesystem path (e.g., /mnt/transfs/...)
    
    Returns:
        JSON with file metadata including genre, language, region, year, etc.
    """
    try:
        from db.connection import get_connection, init_database, get_cursor
        
        config = read_config()
        
        # Normalize path
        if not path.startswith("/mnt/transfs") and not path.startswith("/mnt/filestorefs"):
            return {"error": "Invalid path"}
        
        # Convert /mnt/transfs paths to /mnt/filestorefs for database lookup
        db_path_lookup = path.replace("/mnt/transfs", "/mnt/filestorefs")
        
        try:
            # Initialize database connection pool if needed (uses environment variables)
            # Use larger pool for concurrent FUSE operations
            try:
                init_database(pool_size=100, max_overflow=100)
            except Exception:
                # If init fails, continue - connection pool might already be initialized
                pass
            
            # Use context manager to ensure connection is properly returned
            with get_cursor(commit=False) as cursor:
                # Get file info via virtual_mappings table (one-to-many mapping)
                cursor.execute("""
                    SELECT f.file_id, f.filename, f.extension, f.size, f.mtime, f.is_archive, f.content_type, vm.display_name, f.source_path, f.created_at, f.updated_at
                    FROM files f
                    JOIN virtual_mappings vm ON f.file_id = vm.file_id
                    WHERE vm.virtual_path = %s
                    LIMIT 1
                """, (path,))
                
                file_row = cursor.fetchone()
                if not file_row:
                    # Case-insensitive fallback for clients/category casing differences
                    # (e.g., MAME vs Mame, ROMS vs ROMs)
                    cursor.execute("""
                        SELECT f.file_id, f.filename, f.extension, f.size, f.mtime, f.is_archive, f.content_type, vm.display_name, f.source_path, f.created_at, f.updated_at
                        FROM files f
                        JOIN virtual_mappings vm ON f.file_id = vm.file_id
                        WHERE lower(vm.virtual_path) = lower(%s)
                        LIMIT 1
                    """, (path,))
                    file_row = cursor.fetchone()

                if not file_row:
                    # Fallback: try direct source_path or legacy virtual_path lookup
                    cursor.execute("""
                        SELECT file_id, filename, extension, size, mtime, is_archive, content_type, filename as display_name, source_path, created_at, updated_at
                        FROM files
                        WHERE source_path = %s OR virtual_path = %s
                           OR lower(source_path) = lower(%s) OR lower(virtual_path) = lower(%s)
                        LIMIT 1
                    """, (db_path_lookup, path, db_path_lookup, path))
                    file_row = cursor.fetchone()

                if not file_row:
                    # Final fallback: resolve virtual path to real source path(s) and try again
                    try:
                        import logging
                        from sourcepath import get_source_path

                        logger = logging.getLogger("api")
                        source_path = get_source_path(logger, config, "/mnt/transfs", path)
                        resolved_paths = []

                        if isinstance(source_path, str):
                            resolved_paths = [source_path]
                        elif isinstance(source_path, tuple):
                            zip_path, internal_path = source_path
                            resolved_paths = [f"{zip_path}/{internal_path}"]
                        elif isinstance(source_path, dict) and "path" in source_path:
                            resolved_paths = [source_path["path"]]

                        if resolved_paths:
                            cursor.execute("""
                                SELECT file_id, filename, extension, size, mtime, is_archive, content_type, filename as display_name, source_path, created_at, updated_at
                                FROM files
                                WHERE source_path = ANY(%s)
                                LIMIT 1
                            """, (resolved_paths,))
                            file_row = cursor.fetchone()
                    except Exception:  # pylint: disable=broad-except
                        file_row = None

                if not file_row:
                    # Graceful fallback: provide basic metadata from filename/path so
                    # virtual browser info panel remains usable even before DB sync.
                    try:
                        from metadata.parser import parse_filename

                        filename = Path(path).name
                        parsed = parse_filename(filename)

                        fallback_metadata = {
                            "title": parsed.title,
                            "region": parsed.region,
                            "language": parsed.language,
                            "version": parsed.version,
                            "year": parsed.year,
                            "publisher": parsed.publisher,
                            "is_prototype": parsed.is_prototype,
                            "is_homebrew": parsed.is_homebrew,
                            "is_translation": parsed.is_translation,
                            "is_hack": parsed.is_hack,
                            "is_demo": parsed.is_demo,
                            "is_beta": parsed.is_beta,
                            "is_sample": parsed.is_sample,
                            "tags": parsed.tags,
                        }

                        # Try to resolve actual source path for size/mtime when possible
                        resolved_source_path = None
                        resolved_size = None
                        resolved_mtime = None
                        try:
                            from sourcepath import get_source_path

                            logger = logging.getLogger("api")
                            source_path = get_source_path(logger, config, "/mnt/transfs", path)
                            if isinstance(source_path, str):
                                resolved_source_path = source_path
                            elif isinstance(source_path, tuple):
                                zip_path, internal_path = source_path
                                resolved_source_path = f"{zip_path}/{internal_path}"
                            elif isinstance(source_path, dict) and "path" in source_path:
                                resolved_source_path = source_path["path"]

                            if isinstance(source_path, str) and os.path.exists(source_path):
                                stat_result = os.stat(source_path)
                                resolved_size = stat_result.st_size
                                resolved_mtime = int(stat_result.st_mtime)
                        except Exception:
                            pass

                        return {
                            "file_id": None,
                            "filename": filename,
                            "display_name": filename,
                            "extension": Path(filename).suffix.lstrip('.'),
                            "size": resolved_size,
                            "mtime": resolved_mtime,
                            "created_at": None,
                            "updated_at": None,
                            "is_archive": False,
                            "content_type": None,
                            "source_path": resolved_source_path,
                            "metadata": {k: v for k, v in fallback_metadata.items() if v is not None},
                            "metadata_source": "filename_fallback",
                            "warning": "Metadata not found in database; showing filename-derived metadata",
                            "hint": "Run Update DB to sync full metadata for this file",
                        }
                    except Exception:
                        return {
                            "error": "File not found in metadata database",
                            "hint": "Run Update DB to sync metadata for this file",
                            "path": path,
                        }
                
                if isinstance(file_row, dict):
                    file_id = file_row.get("file_id")
                    filename = file_row.get("filename")
                    extension = file_row.get("extension")
                    size = file_row.get("size")
                    mtime = file_row.get("mtime")
                    is_archive = file_row.get("is_archive")
                    content_type = file_row.get("content_type")
                    display_name = file_row.get("display_name")
                    source_path = file_row.get("source_path")
                    created_at = file_row.get("created_at")
                    updated_at = file_row.get("updated_at")
                else:
                    file_id, filename, extension, size, mtime, is_archive, content_type, display_name, source_path, created_at, updated_at = file_row
                
                # Get normalized metadata with joins to get actual lookup table values
                cursor.execute("""
                    SELECT 
                        mt.name as media_type,
                        r.name as region,
                        l.name as language,
                        p.name as publisher,
                        fm.release_year,
                        fm.release_date,
                        fm.release_precision,
                        fm.rom_size,
                        fm.is_revision,
                        fm.is_prototype,
                        fm.is_homebrew
                    FROM file_metadata fm
                    LEFT JOIN media_types mt ON fm.media_type_id = mt.id
                    LEFT JOIN regions r ON fm.region_id = r.id
                    LEFT JOIN languages l ON fm.language_id = l.id
                    LEFT JOIN publishers p ON fm.publisher_id = p.id
                    WHERE fm.file_id = %s
                """, (file_id,))
                
                normalized_row = cursor.fetchone()
                
                # Also check extended metadata table for any data
                cursor.execute("""
                    SELECT genre, subgenre, language, region, year, publisher, developer,
                           rating, play_count, last_played, is_prototype, is_homebrew,
                           is_translation, is_hack, tags, raw_metadata
                    FROM metadata
                    WHERE file_id = %s
                """, (file_id,))
                
                meta_row = cursor.fetchone()
                
                # Build response
                response = {
                    "file_id": file_id,
                    "filename": filename,
                    "display_name": display_name,
                    "extension": extension,
                    "size": size,
                    "mtime": mtime,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "is_archive": is_archive,
                    "content_type": content_type,
                    "source_path": source_path,
                    "metadata": {}
                }
                
                # Prefer normalized metadata (with joins) as primary source
                if normalized_row:
                    if isinstance(normalized_row, dict):
                        media_type = normalized_row.get("media_type")
                        region = normalized_row.get("region")
                        language = normalized_row.get("language")
                        publisher = normalized_row.get("publisher")
                        release_year = normalized_row.get("release_year")
                        release_date = normalized_row.get("release_date")
                        release_precision = normalized_row.get("release_precision")
                        rom_size = normalized_row.get("rom_size")
                        is_revision = normalized_row.get("is_revision")
                        is_prototype = normalized_row.get("is_prototype")
                        is_homebrew = normalized_row.get("is_homebrew")
                    else:
                        (media_type, region, language, publisher, release_year, release_date,
                         release_precision, rom_size, is_revision, is_prototype, is_homebrew) = normalized_row
                    
                    response["metadata"] = {
                        "media_type": media_type,
                        "region": region,
                        "language": language,
                        "publisher": publisher,
                        "release_year": release_year,
                        "release_date": release_date,
                        "release_precision": release_precision,
                        "rom_size": rom_size,
                        "is_revision": is_revision,
                        "is_prototype": is_prototype,
                        "is_homebrew": is_homebrew
                    }
                
                # Add extended metadata if available (will overwrite normalized if both exist)
                if meta_row:
                    if isinstance(meta_row, dict):
                        genre = meta_row.get("genre")
                        subgenre = meta_row.get("subgenre")
                        language = meta_row.get("language")
                        region = meta_row.get("region")
                        year = meta_row.get("year")
                        publisher = meta_row.get("publisher")
                        developer = meta_row.get("developer")
                        rating = meta_row.get("rating")
                        play_count = meta_row.get("play_count")
                        last_played = meta_row.get("last_played")
                        is_prototype = meta_row.get("is_prototype")
                        is_homebrew = meta_row.get("is_homebrew")
                        is_translation = meta_row.get("is_translation")
                        is_hack = meta_row.get("is_hack")
                        tags = meta_row.get("tags")
                        raw_metadata = meta_row.get("raw_metadata")
                    else:
                        (genre, subgenre, language, region, year, publisher, developer,
                         rating, play_count, last_played, is_prototype, is_homebrew,
                         is_translation, is_hack, tags, raw_metadata) = meta_row
                    
                    extended = {
                        "genre": genre,
                        "subgenre": subgenre,
                        "language": language,
                        "region": region,
                        "year": year,
                        "publisher": publisher,
                        "developer": developer,
                        "rating": rating,
                        "play_count": play_count,
                        "last_played": last_played,
                        "is_prototype": is_prototype,
                        "is_homebrew": is_homebrew,
                        "is_translation": is_translation,
                        "is_hack": is_hack,
                        "tags": tags,
                        "raw_metadata": raw_metadata
                    }
                    # Merge, with extended metadata taking precedence for overlapping fields
                    response["metadata"].update({k: v for k, v in extended.items() if v is not None})
                
                # Filter out None values for cleaner output
                response["metadata"] = {k: v for k, v in response["metadata"].items() if v is not None}
                
                return response
            
        except Exception as e:  # pylint: disable=broad-except
            return {"error": f"Database query failed: {str(e)}"}
            
    except Exception as e:  # pylint: disable=broad-except
        return {"error": f"Failed to retrieve file metadata: {str(e)}"}


@app.get("/clients", tags=["Clients & Systems"])
def api_get_clients():
    """Get list of all available clients (MiSTer, RetroBat, MAME, etc.)."""
    return get_clients()


@app.get("/clients/{client_name}/systems", tags=["Clients & Systems"])
def api_get_systems(client_name: str):
    """Get list of systems supported by a specific client."""
    return get_systems_for_client(client_name)


@app.get("/systems/meta", tags=["Clients & Systems"])
def api_get_manufacturers_and_canonical_names():
    """
    Get all systems organized by manufacturer with multi-client support information.
    
    Returns a dict mapping manufacturer names to lists of systems, where each system includes:
    - mapping_name: Canonical system identifier
    - display_name: Human-readable name
    - name: Filesystem name
    - supported_by: List of client names that support this system
    """
    return get_manufacturers_and_canonical_names()


@app.post("/sync/client/{client_name}/system/{system_name}")
def sync_system_cache(client_name: str, system_name: str):
    """
    Manually trigger cache population for a specific system.
    This walks the virtual filesystem and pre-populates getattr cache,
    which is especially useful for systems with transforms.
    """
    import os
    import time
    mount_path = "/mnt/transfs"
    system_path = os.path.join(mount_path, client_name, system_name)
    
    if not os.path.exists(system_path):
        return {"error": f"System path not found: {system_path}", "success": False}
    
    # Walk the system directory and stat all files
    file_count = 0
    dir_count = 0
    error_count = 0
    start_time = time.time()
    
    try:
        for root, dirs, files in os.walk(system_path):
            dir_count += len(dirs)
            for filename in files:
                try:
                    file_path = os.path.join(root, filename)
                    os.stat(file_path)  # Triggers getattr, populates cache
                    file_count += 1
                    
                    # Progress logging every 100 files
                    if file_count % 100 == 0:
                        elapsed = time.time() - start_time
                        logger.info(f"Sync progress: {file_count} files cached in {elapsed:.1f}s")
                except Exception as e:
                    error_count += 1
                    logger.debug(f"Sync error on {filename}: {e}")
        
        elapsed = time.time() - start_time
        return {
            "success": True,
            "client": client_name,
            "system": system_name,
            "files_cached": file_count,
            "directories": dir_count,
            "errors": error_count,
            "elapsed_seconds": round(elapsed, 2)
        }
    except Exception as e:
        return {
            "error": str(e),
            "success": False,
            "files_cached": file_count
        }


@app.get("/clients/{client_name}/systems/{system_name}/packs", tags=["Downloads"])
def api_get_packs(client_name: str, system_name: str):
    """Get available software packs for a specific system (client-specific endpoint)."""
    system_config = get_system_config(client_name, system_name)
    if not system_config:
        return {"error": "System not found"}
    
    return {
        "system": system_config.name,
        "manufacturer": system_config.manufacturer,
        "canonical_name": system_config.canonical_name,
        "packs": [
            {
                "id": pack.id,
                "name": pack.name,
                "description": pack.description,
                "estimated_size": pack.estimated_size,
                "has_build_script": pack.build_script is not None,
                "info_links": pack.info_links or [],
                "supported_by": pack.supported_by or []
            }
            for pack in system_config.packs
        ]
    }


@app.get("/systems/{manufacturer}/{system_name}/packs", tags=["Downloads"])
def api_get_packs_no_client(manufacturer: str, system_name: str):
    """
    Get available software packs for a system (client-agnostic).
    
    Downloads are shared across all clients - use this endpoint to get packs
    without selecting a specific client. The supported_by field indicates
    which clients can use each pack.
    """
    # Use any client that supports this system to get the pack info
    # Since packs are client-agnostic (downloads go to same location), 
    # we just need to find any client that defines this system
    clients_config = read_clients_config()
    
    for client in clients_config.get("clients", []):
        for system in client.get("systems", []):
            system_mapping_name = system.get("system_mapping_name") or system.get("cananonical_system_name")
            if (system.get("manufacturer") == manufacturer and 
                system_mapping_name == system_name):
                # Found a client with this system, use it to get packs
                system_config = get_system_config(client["name"], system.get("name"))
                if system_config:
                    return {
                        "system": system_config.name,
                        "manufacturer": system_config.manufacturer,
                        "canonical_name": system_config.canonical_name,
                        "packs": [
                            {
                                "id": pack.id,
                                "name": pack.name,
                                "description": pack.description,
                                "estimated_size": pack.estimated_size,
                                "has_build_script": pack.build_script is not None,
                                "info_links": pack.info_links or [],
                                "supported_by": pack.supported_by or []
                            }
                            for pack in system_config.packs
                        ]
                    }
    
    return {"error": "System not found"}


@app.post("/clients/{client_name}/systems/{system_name}/install-packs", tags=["Downloads"])
async def api_install_packs(client_name: str, system_name: str, req: PackInstallRequest):
    """
    Install selected software packs for a system.
    
    Downloads sources referenced by each pack and runs build scripts.
    Returns a streaming response with real-time progress updates.
    
    Downloads are shared across all clients - files go to the same location
    regardless of which client context is used.
    """
    system_config = get_system_config(client_name, system_name)
    if not system_config:
        return {"error": "System not found"}
    
    config = read_config()
    filestore = config.get("filestore", "filestore")
    archive_sources = config.get("archive_sources", {})
    ssl_ignore_hosts = config.get("ssl_ignore_hosts", [])
    
    # Get sources from both archive_sources (old) and source YAML (new)
    manufacturer_sources = archive_sources.get(system_config.manufacturer, {})
    system_sources = manufacturer_sources.get(system_config.canonical_name, {})
    available_sources = {s["name"]: s for s in system_sources.get("sources", [])}
    
    # Also load from source YAML (new config structure)
    from config import read_source_config
    source_config = read_source_config(system_config.manufacturer, system_config.canonical_name)
    if source_config:
        for source in source_config.get("sources", []):
            available_sources[source["name"]] = source
    
    base_path = os.path.join(filestore, "Native", system_config.local_base_path)
    
    async def run_and_stream():
        """Execute downloads and build scripts for selected packs."""
        for pack_id in req.pack_ids:
            # Find the pack
            pack = next((p for p in system_config.packs if p.id == pack_id), None)
            if not pack:
                yield f"Pack '{pack_id}' not found, skipping...\n"
                continue
            
            yield f"\n{'='*60}\n"
            yield f"Installing pack: {pack.name}\n"
            yield f"Description: {pack.description}\n"
            yield f"Estimated size: {pack.estimated_size}\n"
            yield f"Native mount base path: {base_path}\n"
            yield f"{'='*60}\n\n"
            
            # Download sources referenced by this pack
            if pack.sources:
                yield f"Downloading {len(pack.sources)} source(s): {', '.join(pack.sources)}\n\n"
                
                for source_name in pack.sources:
                    source = available_sources.get(source_name)
                    if not source:
                        yield f"⚠ Warning: Source '{source_name}' not found in archive_sources\n"
                        continue
                    
                    source_type = source.get("type")
                    
                    # MAME sources don't have URLs - handle them first
                    if source_type == "mame":
                        # MAME Software List downloader
                        from mame.manager import MAMEDownloadManager
                        
                        mame_config = config.get('mame', {})
                        manager = MAMEDownloadManager(config)
                        
                        system = source.get("system")
                        media_types = source.get("media_types", [])
                        filters = source.get("filters")
                        
                        if not system:
                            yield "⚠ MAME source missing 'system' field\n"
                            continue
                        
                        if not media_types:
                            yield "⚠ MAME source missing 'media_types' field\n"
                            continue
                        
                        yield f"📥 Downloading '{source_name}' (MAME) - {len(media_types)} media type(s)...\n"
                        
                        for media_config in media_types:
                            media_type = media_config.get("type")
                            target_folder = media_config.get("target_folder") or media_config.get("folder")
                            
                            if not media_type or not target_folder:
                                yield f"      ⚠ Skipping invalid media_type config: {media_config}\n"
                                continue
                            
                            mame_dest_dir = os.path.join(mame_base_path, target_folder)
                            yield f"   🔍 Downloading MAME {system}_{media_type}...\n"
                            yield f"      📂 Destination: {mame_dest_dir}\n"
                            
                            try:
                                # Download with progress callback
                                def progress_callback(filename, file_num, total_files, bytes_dl, total_bytes):
                                    percent = int(bytes_dl * 100 / total_bytes) if total_bytes > 0 else 0
                                    # Only yield on completion
                                    if bytes_dl >= total_bytes:
                                        pass  # Don't yield intermediate progress to avoid flooding
                                
                                # Calculate the correct base path (same as for DDL sources)
                                mame_base_path = os.path.join(filestore, "Native", system_config.local_base_path)
                                
                                stats = manager.download_for_system(
                                    system,
                                    media_type,
                                    target_folder,
                                    filters,
                                    progress_callback=progress_callback,
                                    base_path_override=mame_base_path
                                )
                                
                                # Check if download actually retrieved anything
                                if stats['downloaded'] == 0 and stats['failed'] == 0 and stats['total_entries'] == 0:
                                    yield f"      ⚠ No software entries found for {system}_{media_type}\n"
                                    yield "         (This may indicate a network issue fetching the MAME hash file)\n"
                                else:
                                    yield f"      ✓ Downloaded {stats['downloaded']} file(s)\n"
                                    yield f"      ⏭ Skipped {stats['already_existed']} existing file(s)\n"
                                    if stats['failed'] > 0:
                                        yield f"      ✗ Failed {stats['failed']} file(s)\n"
                                    yield f"      📊 Processed {stats['filtered_entries']} software entries\n"
                                
                            except Exception as e:  # pylint: disable=broad-except
                                yield f"      ✗ MAME download failed: {str(e)}\n"
                                logger.error(f"MAME download error for {system}_{media_type}: {e}", exc_info=True)
                        
                        yield "\n"
                        continue
                    
                    # For other source types, normalize URLs (supports single url or multiple urls)
                    url_entries = normalize_source_urls(source)
                    if not url_entries:
                        yield f"⚠ Warning: Source '{source_name}' has no URL(s) configured\n"
                        continue

                    for url_entry in url_entries:
                        url_entry["folder"] = _resolve_source_folder(
                            source_name=source_name,
                            folder=url_entry.get("folder", ""),
                            download_layout=system_config.download_layout,
                            base_path_rel=system_config.local_base_path,
                        )

                    destination_dirs = sorted({os.path.join(base_path, entry["folder"]) for entry in url_entries})
                    if destination_dirs:
                        yield "   📂 Destination path(s):\n"
                        for destination_dir in destination_dirs:
                            yield f"      - {destination_dir}\n"
                    
                    # Handle rename at source level (applied after all URLs downloaded)
                    source_rename_pairs = source.get("rename")
                    
                    yield f"📥 Downloading '{source_name}' ({source_type}) - {len(url_entries)} file(s)...\n"
                    
                    if source_type == "ddl":
                        for idx, url_entry in enumerate(url_entries, 1):
                            url = url_entry["url"]
                            folder = url_entry["folder"]
                            extract_files = url_entry["extract_from_archive"]
                            
                            dest_dir = os.path.join(base_path, folder)
                            os.makedirs(dest_dir, exist_ok=True)
                            
                            if len(url_entries) > 1:
                                yield f"   📄 File {idx}/{len(url_entries)}: {url}\n"
                            
                            try:
                                # Disable SSL verification for configured legacy sites with certificate issues
                                verify_ssl = not any(host in url.lower() for host in ssl_ignore_hosts)
                                resp = requests.get(url, stream=True, timeout=30, verify=verify_ssl)
                                resp.raise_for_status()
                                filename = get_filename_from_response(resp, url)
                                dest_path = os.path.join(dest_dir, filename)
                                
                                # Check if file exists and skip if requested
                                if req.skip_existing and os.path.exists(dest_path):
                                    yield f"      ⏭ Skipping '{filename}' (already exists)\n"
                                    continue
                                
                                total = int(resp.headers.get("Content-Length", 0))
                                downloaded_bytes = 0
                                chunk_size = 8192
                                
                                with open(dest_path, "wb") as f:
                                    for chunk in resp.iter_content(chunk_size=chunk_size):
                                        if chunk:
                                            f.write(chunk)
                                            downloaded_bytes += len(chunk)
                                            if total:
                                                percent = int(downloaded_bytes * 100 / total)
                                                if percent % 10 == 0:  # Report every 10%
                                                    yield f"\r      {percent:3d}%   "
                                
                                yield f"\n      ✓ Downloaded '{filename}' ({downloaded_bytes} bytes)\n"
                                
                                # Handle extract_from_archive if specified for this URL
                                if extract_files and (filename.lower().endswith('.zip') or filename.lower().endswith('.7z') or filename.lower().endswith('.rar')):
                                    yield f"      📦 Extracting specific files from '{filename}'...\n"
                                    try:
                                        if filename.lower().endswith('.zip'):
                                            with zipfile.ZipFile(dest_path, 'r') as zf:
                                                all_files = zf.namelist()
                                                yield f"         Archive contains {len(all_files)} file(s): {', '.join(all_files[:10])}\n"
                                                for file_to_extract in extract_files:
                                                    if file_to_extract in all_files:
                                                        zf.extract(file_to_extract, dest_dir)
                                                        yield f"         ✓ Extracted: {file_to_extract}\n"
                                                    else:
                                                        yield f"         ⚠ File not found in archive: {file_to_extract}\n"
                                        elif filename.lower().endswith('.7z'):
                                            with py7zr.SevenZipFile(dest_path, mode='r') as zf:
                                                all_names = zf.getnames()
                                                for file_to_extract in extract_files:
                                                    if file_to_extract in all_names:
                                                        zf.extract(targets=[file_to_extract], path=dest_dir)
                                                        yield f"         ✓ Extracted: {file_to_extract}\n"
                                                    else:
                                                        yield f"         ⚠ File not found in archive: {file_to_extract}\n"
                                        elif filename.lower().endswith('.rar'):
                                            with rarfile.RarFile(dest_path, 'r') as rf:
                                                all_files = rf.namelist()
                                                yield f"         Archive contains {len(all_files)} file(s): {', '.join(all_files[:10])}\n"
                                                for file_to_extract in extract_files:
                                                    if file_to_extract in all_files:
                                                        rf.extract(file_to_extract, dest_dir)
                                                        yield f"         ✓ Extracted: {file_to_extract}\n"
                                                    else:
                                                        yield f"         ⚠ File not found in archive: {file_to_extract}\n"
                                    except Exception as e:  # pylint: disable=broad-except
                                        yield f"         ✗ Extraction failed: {str(e)}\n"
                                
                                # Handle auto-extract if specified
                                extract_mode = url_entry.get("extract")
                                if extract_mode and (filename.lower().endswith(('.zip', '.7z', '.rar'))):
                                    try:
                                        import fnmatch
                                        import shutil
                                        yield f"      📦 Auto-extracting '{filename}'...\n"
                                        
                                        if filename.lower().endswith('.zip'):
                                            with zipfile.ZipFile(dest_path, 'r') as zf:
                                                all_files = zf.namelist()
                                                if extract_mode is True:
                                                    # Extract all
                                                    zf.extractall(dest_dir)
                                                    yield f"         ✓ Extracted all {len(all_files)} file(s)\n"
                                                elif isinstance(extract_mode, str):
                                                    # Extract matching pattern
                                                    matched = [f for f in all_files if fnmatch.fnmatch(f, extract_mode)]
                                                    for match in matched:
                                                        zf.extract(match, dest_dir)
                                                    yield f"         ✓ Extracted {len(matched)} file(s) matching '{extract_mode}'\n"
                                        elif filename.lower().endswith('.7z'):
                                            with py7zr.SevenZipFile(dest_path, mode='r') as zf:
                                                all_names = zf.getnames()
                                                if extract_mode is True:
                                                    # Extract all
                                                    zf.extractall(path=dest_dir)
                                                    yield f"         ✓ Extracted all {len(all_names)} file(s)\n"
                                                elif isinstance(extract_mode, str):
                                                    # Extract matching pattern - extract all then remove unwanted
                                                    matched = [f for f in all_names if fnmatch.fnmatch(f, extract_mode)]
                                                    if matched:
                                                        with tempfile.TemporaryDirectory() as tmpdir:
                                                            zf.extractall(path=tmpdir)
                                                            for fname in matched:
                                                                src = os.path.join(tmpdir, fname)
                                                                if os.path.exists(src):
                                                                    dst = os.path.join(dest_dir, os.path.basename(fname))
                                                                    shutil.copy2(src, dst)
                                                    yield f"         ✓ Extracted {len(matched)} file(s) matching '{extract_mode}'\n"
                                        elif filename.lower().endswith('.rar'):
                                            with rarfile.RarFile(dest_path, 'r') as rf:
                                                all_files = rf.namelist()
                                                if extract_mode is True:
                                                    # Extract all
                                                    rf.extractall(dest_dir)
                                                    yield f"         ✓ Extracted all {len(all_files)} file(s)\n"
                                                elif isinstance(extract_mode, str):
                                                    # Extract matching pattern
                                                    matched = [f for f in all_files if fnmatch.fnmatch(f, extract_mode)]
                                                    for match in matched:
                                                        rf.extract(match, dest_dir)
                                                    yield f"         ✓ Extracted {len(matched)} file(s) matching '{extract_mode}'\n"
                                        
                                        # Remove original archive after successful extraction
                                        os.remove(dest_path)
                                        yield f"         🗑 Removed archive '{filename}'\n"
                                    except Exception as e:  # pylint: disable=broad-except
                                        yield f"         ✗ Auto-extraction failed: {str(e)}\n"
                                
                            except Exception as e:  # pylint: disable=broad-except
                                yield f"      ✗ Download failed: {str(e)}\n"
                                continue
                        
                        # Handle organize_by_extension at source level (after all URLs downloaded/extracted)
                        organize_ext = source.get("organize_by_extension")
                        if system_config.download_layout == "legacy_source_based" and organize_ext:
                            yield "   ⚠ Skipping organize_by_extension for legacy_source_based layout\n"
                            organize_ext = None
                        if organize_ext:
                            dest_dir = os.path.join(base_path, url_entries[-1]["folder"])
                            conflict_strategy = source.get("organize_on_conflict", "increment")
                            yield "   📂 Organizing files by extension...\n"
                            
                            # Collect all files recursively
                            files_by_ext = {}
                            for root, _, files in os.walk(dest_dir):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    _, ext = os.path.splitext(file)
                                    ext = ext.lower().lstrip('.')
                                    
                                    # Check if we should process this extension
                                    if organize_ext is True or (isinstance(organize_ext, list) and ext in [e.lower() for e in organize_ext]):
                                        if ext not in files_by_ext:
                                            files_by_ext[ext] = []
                                        files_by_ext[ext].append((file_path, file))
                            
                            # Move files to extension subdirectories
                            moved_count = 0
                            for ext, file_list in files_by_ext.items():
                                ext_dir = os.path.join(dest_dir, ext.upper())
                                os.makedirs(ext_dir, exist_ok=True)
                                
                                for src_path, filename in file_list:
                                    dest_path = os.path.join(ext_dir, filename)
                                    
                                    # Handle duplicates
                                    if os.path.exists(dest_path):
                                        if conflict_strategy == "skip":
                                            yield f"      ⏭ Skipping duplicate: {filename}\n"
                                            continue
                                        elif conflict_strategy == "overwrite":
                                            pass  # Will overwrite below
                                        else:  # increment
                                            base_name, ext_part = os.path.splitext(filename)
                                            counter = 1
                                            while os.path.exists(dest_path):
                                                new_filename = f"{base_name}_{counter}{ext_part}"
                                                dest_path = os.path.join(ext_dir, new_filename)
                                                counter += 1
                                            filename = os.path.basename(dest_path)
                                    
                                    try:
                                        import shutil
                                        shutil.move(src_path, dest_path)
                                        moved_count += 1
                                    except Exception as e:  # pylint: disable=broad-except
                                        yield f"      ✗ Failed to move {filename}: {str(e)}\n"
                            
                            # Clean up empty directories
                            for root, dirs, files in os.walk(dest_dir, topdown=False):
                                for dir_name in dirs:
                                    dir_path = os.path.join(root, dir_name)
                                    if dir_path != dest_dir and not os.listdir(dir_path):
                                        try:
                                            os.rmdir(dir_path)
                                        except:  # pylint: disable=bare-except
                                            pass
                            
                            yield f"      ✓ Organized {moved_count} file(s) into {len(files_by_ext)} extension folder(s)\n"
                        
                        # Handle rename/move at source level (after all URLs downloaded)
                        # Uses the folder from the last URL entry as base
                        if source_rename_pairs:
                            dest_dir = os.path.join(base_path, url_entries[-1]["folder"])
                            yield "   📝 Renaming/moving files...\n"
                            for rename_pair in source_rename_pairs:
                                if isinstance(rename_pair, dict):
                                    from_name = rename_pair.get("from")
                                    to_name = rename_pair.get("to")
                                elif isinstance(rename_pair, list) and len(rename_pair) == 2:
                                    from_name, to_name = rename_pair
                                else:
                                    yield f"      ⚠ Invalid rename format: {rename_pair}\n"
                                    continue
                                
                                if not from_name or not to_name:
                                    yield "      ⚠ Invalid rename: missing 'from' or 'to' field\n"
                                    continue
                                
                                from_path = os.path.join(dest_dir, from_name)
                                # to_name can be a simple filename or a path (e.g., "../../BIOS/file.rom")
                                to_path = os.path.join(dest_dir, to_name)
                                
                                if os.path.exists(from_path):
                                    try:
                                        # Create parent directories if needed
                                        os.makedirs(os.path.dirname(to_path), exist_ok=True)
                                        os.rename(from_path, to_path)
                                        yield f"      ✓ Moved: {from_name} → {to_name}\n"
                                    except Exception as e:  # pylint: disable=broad-except
                                        yield f"      ✗ Move failed: {str(e)}\n"
                                else:
                                    yield f"      ⚠ Source file not found: {from_name}\n"
                    
                    elif source_type == "mega":
                        for idx, url_entry in enumerate(url_entries, 1):
                            url = url_entry["url"]
                            folder = url_entry["folder"]
                            
                            dest_dir = os.path.join(base_path, folder)
                            os.makedirs(dest_dir, exist_ok=True)
                            
                            if len(url_entries) > 1:
                                yield f"   📄 File {idx}/{len(url_entries)}: {url}\n"
                            
                            try:
                                yield "      🌐 Starting MEGA download...\n"
                                mega_client = Mega()
                                m = mega_client.login()
                                downloaded_file = m.download_url(url, dest_dir)
                                
                                # Get the actual filename
                                if isinstance(downloaded_file, str):
                                    filename = os.path.basename(downloaded_file)
                                else:
                                    filename = "unknown"
                                
                                yield f"      ✓ Downloaded MEGA file: {filename}\n"
                                
                                # Handle auto-extract if specified
                                extract_mode = url_entry.get("extract")
                                if extract_mode and downloaded_file and os.path.exists(downloaded_file):
                                    filename_lower = str(downloaded_file).lower()
                                    if filename_lower.endswith(('.zip', '.7z', '.rar')):
                                        try:
                                            import fnmatch
                                            import shutil
                                            yield f"      📦 Auto-extracting '{filename}'...\n"
                                            
                                            if filename_lower.endswith('.zip'):
                                                with zipfile.ZipFile(downloaded_file, 'r') as zf:
                                                    all_files = zf.namelist()
                                                    if extract_mode is True:
                                                        zf.extractall(dest_dir)
                                                        yield f"         ✓ Extracted all {len(all_files)} file(s)\n"
                                                    elif isinstance(extract_mode, str):
                                                        matched = [f for f in all_files if fnmatch.fnmatch(f, extract_mode)]
                                                        for match in matched:
                                                            zf.extract(match, dest_dir)
                                                        yield f"         ✓ Extracted {len(matched)} file(s) matching '{extract_mode}'\n"
                                            elif filename_lower.endswith('.7z'):
                                                with py7zr.SevenZipFile(downloaded_file, mode='r') as zf:
                                                    all_names = zf.getnames()
                                                    if extract_mode is True:
                                                        zf.extractall(path=dest_dir)
                                                        yield f"         ✓ Extracted all {len(all_names)} file(s)\n"
                                                    elif isinstance(extract_mode, str):
                                                        matched = [f for f in all_names if fnmatch.fnmatch(f, extract_mode)]
                                                        if matched:
                                                            with tempfile.TemporaryDirectory() as tmpdir:
                                                                zf.extractall(path=tmpdir)
                                                                for fname in matched:
                                                                    src = os.path.join(tmpdir, fname)
                                                                    if os.path.exists(src):
                                                                        dst = os.path.join(dest_dir, os.path.basename(fname))
                                                                        shutil.copy2(src, dst)
                                                        yield f"         ✓ Extracted {len(matched)} file(s) matching '{extract_mode}'\n"
                                            elif filename_lower.endswith('.rar'):
                                                with rarfile.RarFile(downloaded_file, 'r') as rf:
                                                    all_files = rf.namelist()
                                                    if extract_mode is True:
                                                        rf.extractall(dest_dir)
                                                        yield f"         ✓ Extracted all {len(all_files)} file(s)\n"
                                                    elif isinstance(extract_mode, str):
                                                        matched = [f for f in all_files if fnmatch.fnmatch(f, extract_mode)]
                                                        for match in matched:
                                                            rf.extract(match, dest_dir)
                                                        yield f"         ✓ Extracted {len(matched)} file(s) matching '{extract_mode}'\n"
                                            
                                            # Remove original archive after successful extraction
                                            os.remove(downloaded_file)
                                            yield f"         🗑 Removed archive '{filename}'\n"
                                        except Exception as e:  # pylint: disable=broad-except
                                            yield f"         ✗ Auto-extraction failed: {str(e)}\n"
                                
                            except Exception as e:  # pylint: disable=broad-except
                                yield f"      ✗ MEGA download failed: {str(e)}\n"
                                continue
                        
                        # Handle organize_by_extension at source level (after all URLs downloaded/extracted)
                        organize_ext = source.get("organize_by_extension")
                        if system_config.download_layout == "legacy_source_based" and organize_ext:
                            yield "   ⚠ Skipping organize_by_extension for legacy_source_based layout\n"
                            organize_ext = None
                        if organize_ext:
                            dest_dir = os.path.join(base_path, url_entries[-1]["folder"])
                            conflict_strategy = source.get("organize_on_conflict", "increment")
                            yield "   📂 Organizing files by extension...\n"
                            
                            # Collect all files recursively
                            files_by_ext = {}
                            for root, _, files in os.walk(dest_dir):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    _, ext = os.path.splitext(file)
                                    ext = ext.lower().lstrip('.')
                                    
                                    # Check if we should process this extension
                                    if organize_ext is True or (isinstance(organize_ext, list) and ext in [e.lower() for e in organize_ext]):
                                        if ext not in files_by_ext:
                                            files_by_ext[ext] = []
                                        files_by_ext[ext].append((file_path, file))
                            
                            # Move files to extension subdirectories
                            moved_count = 0
                            for ext, file_list in files_by_ext.items():
                                ext_dir = os.path.join(dest_dir, ext.upper())
                                os.makedirs(ext_dir, exist_ok=True)
                                
                                for src_path, filename in file_list:
                                    dest_path = os.path.join(ext_dir, filename)
                                    
                                    # Handle duplicates
                                    if os.path.exists(dest_path):
                                        if conflict_strategy == "skip":
                                            yield f"      ⏭ Skipping duplicate: {filename}\n"
                                            continue
                                        elif conflict_strategy == "overwrite":
                                            pass  # Will overwrite below
                                        else:  # increment
                                            base_name, ext_part = os.path.splitext(filename)
                                            counter = 1
                                            while os.path.exists(dest_path):
                                                new_filename = f"{base_name}_{counter}{ext_part}"
                                                dest_path = os.path.join(ext_dir, new_filename)
                                                counter += 1
                                            filename = os.path.basename(dest_path)
                                    
                                    try:
                                        import shutil
                                        shutil.move(src_path, dest_path)
                                        moved_count += 1
                                    except Exception as e:  # pylint: disable=broad-except
                                        yield f"      ✗ Failed to move {filename}: {str(e)}\n"
                            
                            # Clean up empty directories
                            for root, dirs, files in os.walk(dest_dir, topdown=False):
                                for dir_name in dirs:
                                    dir_path = os.path.join(root, dir_name)
                                    if dir_path != dest_dir and not os.listdir(dir_path):
                                        try:
                                            os.rmdir(dir_path)
                                        except:  # pylint: disable=bare-except
                                            pass
                            
                            yield f"      ✓ Organized {moved_count} file(s) into {len(files_by_ext)} extension folder(s)\n"
                        
                        # Handle rename/move at source level (after all URLs downloaded)
                        if source_rename_pairs:
                            dest_dir = os.path.join(base_path, url_entries[-1]["folder"])
                            yield "   📝 Renaming/moving files...\n"
                            for rename_pair in source_rename_pairs:
                                if isinstance(rename_pair, dict):
                                    from_name = rename_pair.get("from")
                                    to_name = rename_pair.get("to")
                                elif isinstance(rename_pair, list) and len(rename_pair) == 2:
                                    from_name, to_name = rename_pair
                                else:
                                    yield f"      ⚠ Invalid rename format: {rename_pair}\n"
                                    continue
                                
                                if not from_name or not to_name:
                                    yield "      ⚠ Invalid rename: missing 'from' or 'to' field\n"
                                    continue
                                
                                from_path = os.path.join(dest_dir, from_name)
                                to_path = os.path.join(dest_dir, to_name)
                                
                                if os.path.exists(from_path):
                                    try:
                                        os.makedirs(os.path.dirname(to_path), exist_ok=True)
                                        os.rename(from_path, to_path)
                                        yield f"      ✓ Moved: {from_name} → {to_name}\n"
                                    except Exception as e:  # pylint: disable=broad-except
                                        yield f"      ✗ Move failed: {str(e)}\n"
                                else:
                                    yield f"      ⚠ Source file not found: {from_name}\n"
                    
                    elif source_type == "tor":
                        for idx, url_entry in enumerate(url_entries, 1):
                            url = url_entry["url"]
                            folder = url_entry["folder"]
                            
                            dest_dir = os.path.join(base_path, folder)
                            os.makedirs(dest_dir, exist_ok=True)
                            
                            if len(url_entries) > 1:
                                yield f"   📄 File {idx}/{len(url_entries)}: {url}\n"
                            
                            try:
                                yield "      🌱 Starting torrent download...\n"
                                ses = lt.session()  # type: ignore
                                ses.listen_on(6881, 6891)
                                params = {
                                    'save_path': dest_dir,
                                    'storage_mode': lt.storage_mode_t(2),  # type: ignore
                                }
                                
                                if url.endswith('.torrent'):
                                    # Download the torrent file
                                    verify_ssl = not any(host in url.lower() for host in ssl_ignore_hosts)
                                    resp = requests.get(url, verify=verify_ssl, timeout=30)
                                    resp.raise_for_status()
                                    with tempfile.NamedTemporaryFile(delete=False, suffix=".torrent") as tf:
                                        tf.write(resp.content)
                                        torrent_path = tf.name
                                    info = lt.torrent_info(torrent_path)  # type: ignore
                                    h = ses.add_torrent({'ti': info, 'save_path': dest_dir})
                                else:
                                    # Assume magnet link
                                    h = lt.add_magnet_uri(ses, url, params)  # type: ignore
                                
                                yield "      📡 Fetching metadata...\n"
                                while not h.has_metadata():
                                    await asyncio.sleep(1)
                                
                                yield "      📥 Downloading torrent...\n"
                                last_percent = -1
                                while not h.is_seed():
                                    s = h.status()
                                    percent = int(s.progress * 100)
                                    if percent != last_percent and percent % 10 == 0:
                                        yield f"\r      {percent:3d}% ({s.download_rate/1000:.1f} kB/s)   "
                                        last_percent = percent
                                    await asyncio.sleep(2)
                                
                                yield "\n      ✓ Torrent download complete\n"
                                
                            except Exception as e:  # pylint: disable=broad-except
                                yield f"      ✗ Torrent download failed: {str(e)}\n"
                                continue
                        
                        # Handle organize_by_extension at source level (after all URLs downloaded/extracted)
                        organize_ext = source.get("organize_by_extension")
                        if system_config.download_layout == "legacy_source_based" and organize_ext:
                            yield "   ⚠ Skipping organize_by_extension for legacy_source_based layout\n"
                            organize_ext = None
                        if organize_ext:
                            dest_dir = os.path.join(base_path, url_entries[-1]["folder"])
                            conflict_strategy = source.get("organize_on_conflict", "increment")
                            yield "   📂 Organizing files by extension...\n"
                            
                            # Collect all files recursively
                            files_by_ext = {}
                            for root, _, files in os.walk(dest_dir):
                                for file in files:
                                    file_path = os.path.join(root, file)
                                    _, ext = os.path.splitext(file)
                                    ext = ext.lower().lstrip('.')
                                    
                                    # Check if we should process this extension
                                    if organize_ext is True or (isinstance(organize_ext, list) and ext in [e.lower() for e in organize_ext]):
                                        if ext not in files_by_ext:
                                            files_by_ext[ext] = []
                                        files_by_ext[ext].append((file_path, file))
                            
                            # Move files to extension subdirectories
                            moved_count = 0
                            for ext, file_list in files_by_ext.items():
                                ext_dir = os.path.join(dest_dir, ext.upper())
                                os.makedirs(ext_dir, exist_ok=True)
                                
                                for src_path, filename in file_list:
                                    dest_path = os.path.join(ext_dir, filename)
                                    
                                    # Handle duplicates
                                    if os.path.exists(dest_path):
                                        if conflict_strategy == "skip":
                                            yield f"      ⏭ Skipping duplicate: {filename}\n"
                                            continue
                                        elif conflict_strategy == "overwrite":
                                            pass  # Will overwrite below
                                        else:  # increment
                                            base_name, ext_part = os.path.splitext(filename)
                                            counter = 1
                                            while os.path.exists(dest_path):
                                                new_filename = f"{base_name}_{counter}{ext_part}"
                                                dest_path = os.path.join(ext_dir, new_filename)
                                                counter += 1
                                            filename = os.path.basename(dest_path)
                                    
                                    try:
                                        import shutil
                                        shutil.move(src_path, dest_path)
                                        moved_count += 1
                                    except Exception as e:  # pylint: disable=broad-except
                                        yield f"      ✗ Failed to move {filename}: {str(e)}\n"
                            
                            # Clean up empty directories
                            for root, dirs, files in os.walk(dest_dir, topdown=False):
                                for dir_name in dirs:
                                    dir_path = os.path.join(root, dir_name)
                                    if dir_path != dest_dir and not os.listdir(dir_path):
                                        try:
                                            os.rmdir(dir_path)
                                        except:  # pylint: disable=bare-except
                                            pass
                            
                            yield f"      ✓ Organized {moved_count} file(s) into {len(files_by_ext)} extension folder(s)\n"
                        
                        # Handle rename/move at source level (after all URLs downloaded)
                        if source_rename_pairs:
                            dest_dir = os.path.join(base_path, url_entries[-1]["folder"])
                            yield "   📝 Renaming/moving files...\n"
                            for rename_pair in source_rename_pairs:
                                if isinstance(rename_pair, dict):
                                    from_name = rename_pair.get("from")
                                    to_name = rename_pair.get("to")
                                elif isinstance(rename_pair, list) and len(rename_pair) == 2:
                                    from_name, to_name = rename_pair
                                else:
                                    yield f"      ⚠ Invalid rename format: {rename_pair}\n"
                                    continue
                                
                                if not from_name or not to_name:
                                    yield "      ⚠ Invalid rename: missing 'from' or 'to' field\n"
                                    continue
                                
                                from_path = os.path.join(dest_dir, from_name)
                                to_path = os.path.join(dest_dir, to_name)
                                
                                if os.path.exists(from_path):
                                    try:
                                        os.makedirs(os.path.dirname(to_path), exist_ok=True)
                                        os.rename(from_path, to_path)
                                        yield f"      ✓ Moved: {from_name} → {to_name}\n"
                                    except Exception as e:  # pylint: disable=broad-except
                                        yield f"      ✗ Move failed: {str(e)}\n"
                                else:
                                    yield f"      ⚠ Source file not found: {from_name}\n"
                    
                    elif source_type == "IA-COL":
                        # Internet Archive collection download
                        url = url_entries[0]["url"] if url_entries else None
                        folder = url_entries[0]["folder"] if url_entries else ""
                        filetypes = source.get("filetypes")
                        
                        if not url:
                            yield f"   ⚠ Source '{source_name}' has no URL configured\n"
                        else:
                            try:
                                for msg in download_ia_collection(url, base_path, folder, filetypes=filetypes):
                                    yield msg
                                yield f"   ✓ IA-COL download complete: {os.path.join(base_path, folder)}\n"
                            except Exception as exc:  # pylint: disable=broad-except
                                yield f"   ✗ Failed to download IA-COL '{source_name}': {exc}\n"

                    else:
                        yield f"   ⚠ Source type '{source_type}' not yet supported for pack installation\n"
                
                yield "\n"
            else:
                yield "No sources to download for this pack\n\n"
            
            # Post-process downloaded files (declarative operations)
            if pack.post_process:
                yield "🔧 Running post-processing operations...\n"
                yield "=" * 60 + "\n"
                
                processor = PostProcessor(base_path, skip_existing=req.skip_existing)
                
                # Set up logging callback to yield messages
                # Using class to avoid cell variable linting warning
                class MessageCollector:
                    def __init__(self):
                        self.queue = []
                    
                    def log(self, msg: str) -> None:
                        self.queue.append(msg + "\n")
                
                collector = MessageCollector()
                processor.set_log_callback(collector.log)
                
                try:
                    success = processor.process(pack.post_process)
                    
                    # Yield all logged messages
                    for msg in collector.queue:
                        yield msg
                    
                    if success:
                        yield "=" * 60 + "\n"
                        yield "✓ Post-processing completed successfully\n"
                    else:
                        yield "=" * 60 + "\n"
                        yield "✗ Post-processing failed\n"
                except Exception as e:  # pylint: disable=broad-except
                    yield f"✗ Post-processing error: {str(e)}\n"
            
            # Run legacy build script if provided (for complex edge cases)
            if pack.build_script:
                script_path = os.path.join("build_scripts", pack.build_script)
                if not os.path.isfile(script_path):
                    yield f"✗ Build script not found: {script_path}\n"
                    continue
                
                # Prepare environment variables
                env = {
                    **os.environ,
                    "BASE_PATH": base_path,
                    "PACK_ID": pack.id,
                    "PACK_NAME": pack.name,
                    "SKIP_EXISTING": "1" if req.skip_existing else "0"
                }
                
                yield f"🔨 Running build script: {script_path}\n"
                yield f"{'='*60}\n"
                
                process = await asyncio.create_subprocess_exec(
                    "bash",
                    script_path,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                
                if process.stdout is not None:
                    while True:
                        line = await process.stdout.readline()
                        if not line:
                            break
                        yield line.decode(errors="replace")
                
                await process.wait()
                
                yield "=" * 60 + "\n"
                if process.returncode == 0:
                    yield "✓ Build script completed successfully\n"
                else:
                    yield f"✗ Build script failed (exit code {process.returncode})\n"
            
            # Final status if no post-processing or build script
            if not pack.post_process and not pack.build_script:
                yield f"✓ Pack '{pack.name}' downloaded (no post-processing needed)\n"
        
        yield "\n" + "=" * 60 + "\n"
        yield "All selected packs processed\n"
        
        if req.update_db:
            # Run database sync at the end of pack installation
            try:
                yield "\n" + "=" * 60 + "\n"
                yield "🔄 Starting database synchronization...\n"
                yield "=" * 60 + "\n\n"
                
                # Yield control to the event loop so the above messages are flushed
                # to the browser before the blocking sync operation begins
                await asyncio.sleep(0)
                
                # Flush to ensure header is sent immediately
                sys.stdout.flush()
                sys.stderr.flush()
                
                # Set up logging to capture sync output
                log_capture = io.StringIO()
                log_handler = logging.StreamHandler(log_capture)
                log_handler.setLevel(logging.INFO)
                formatter = logging.Formatter('%(message)s')
                log_handler.setFormatter(formatter)
                
                # Add handler to sync_database logger
                sync_logger = logging.getLogger('sync_database')
                sync_logger.addHandler(log_handler)
                sync_logger.setLevel(logging.INFO)
                
                # Create DatabaseSync instance and run full sync in a thread to avoid
                # blocking the async event loop (which would prevent other requests from
                # being served while the sync processes potentially hundreds of files)
                sync_config = read_config()
                db_sync = DatabaseSync(sync_config)
                await asyncio.get_running_loop().run_in_executor(
                    None,
                    lambda: db_sync.full_sync(client_filter=client_name, system_filter=system_name)
                )
                
                # Stream captured log output
                sync_output = log_capture.getvalue()
                if sync_output:
                    for line in sync_output.split('\n'):
                        if line.strip():
                            yield f"  {line}\n"
                else:
                    yield "  (sync completed with no log output)\n"
                
                # Remove handler
                sync_logger.removeHandler(log_handler)
                log_handler.close()
                
                yield "\n" + "=" * 60 + "\n"
                yield "✓ Database synchronization completed\n"
                yield "=" * 60 + "\n"
            except Exception as e:  # pylint: disable=broad-except
                yield f"\n✗ Database synchronization failed: {str(e)}\n"
        else:
            yield "\nDB synchronization skipped (Install/Download Only selected)\n"
    
    return StreamingResponse(run_and_stream(), media_type="text/plain")


@app.post("/systems/{manufacturer}/{system_name}/install-packs", tags=["Downloads"])
async def api_install_packs_no_client(manufacturer: str, system_name: str, req: PackInstallRequestNoClient):
    """
    Install selected software packs for a system (client-agnostic).
    
    Downloads sources referenced by each pack and runs build scripts.
    Returns a streaming response with real-time progress updates.
    
    Downloads are shared across all clients - files go to the same location
    regardless of which client context is used. This endpoint doesn't require
    a client selection; it uses any client that supports this system.
    """
    # Use any client that supports this system and delegate to full install logic
    clients_config = read_clients_config()
    client_name = None
    system_actual_name = None

    for client in clients_config.get("clients", []):
        for system in client.get("systems", []):
            system_actual = system.get("name")
            system_mapping_name = system.get("system_mapping_name") or system.get("cananonical_system_name")
            # Check both actual system name and mapping name
            if (system.get("manufacturer") == manufacturer and 
                (system_actual == system_name or system_mapping_name == system_name)):
                client_name = client.get("name")
                system_actual_name = system_actual
                break
        if client_name:
            break

    if not client_name or not system_actual_name:
        return {"error": "System not found"}

    full_request = PackInstallRequest(
        client=client_name,
        system=system_actual_name,
        pack_ids=req.pack_ids,
        skip_existing=req.skip_existing,
        update_db=req.update_db,
    )

    return await api_install_packs(client_name, system_actual_name, full_request)


def estimate_download_time(url, speed_mbps=10):
    """
    Estimate download time in seconds for a given URL and speed in Mbps.

    Args:
        url (str): The URL of the file to estimate.
        speed_mbps (int): Download speed in megabits per second.

    Returns:
        int or None: Estimated download time in seconds, or None if unknown.
    """
    try:
        head = requests.head(url, allow_redirects=True, timeout=10)
        size = int(head.headers.get("Content-Length", 0))
        if size == 0:
            return None
        speed_bps = speed_mbps * 1024 * 1024 / 8  # Convert Mbps to bytes/sec
        seconds = math.ceil(size / speed_bps)
        return seconds
    except Exception:  # pylint: disable=broad-except
        return None


@app.post("/build")
async def api_build_stream(req: BuildRequest):
    """
    Stream output from running build scripts for the specified builds and clients.

    Args:
        req (BuildRequest): The build request.

    Returns:
        StreamingResponse: Streaming output of build script execution.
    """
    config = read_config()
    filestore = config.get("filestore", "filestore")
    archive_sources = config.get("archive_sources", {})

    async def run_and_stream():
        """Async generator to run build scripts and yield output lines."""
        for build in req.builds:
            manufacturer = build.get("manufacturer")
            system = build.get("system")
            manufacturer_sources = archive_sources.get(manufacturer, {})
            system_entry = manufacturer_sources.get(system, {})
            base_path_rel = system_entry.get("base_path", "")
            base_path = os.path.join(filestore, "Native" , base_path_rel)
            for client in req.clients:
                script_path = os.path.join(
                    "build_scripts", client, manufacturer, system, "build.sh"
                )
                if os.path.isfile(script_path):
                    yield f"Running {script_path} with BASE_PATH={base_path}...\n"
                    process = await asyncio.create_subprocess_exec(
                        "bash",
                        script_path,
                        env={**os.environ, "BASE_PATH": base_path},
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                    )
                    if process.stdout is not None:
                        while True:
                            line = await process.stdout.readline()
                            if not line:
                                break
                            yield line.decode(errors="replace")
                    await process.wait()
                    yield (
                        f"Completed {script_path} (exit code {process.returncode})\n"
                    )
                else:
                    yield f"Script not found: {script_path}\n"

    return StreamingResponse(run_and_stream(), media_type="text/plain")


@app.post("/download")
async def api_download_stream(req: DownloadRequest):
    """
    Stream download progress for DDL and IA-COL sources for a given manufacturer/system.
    Only downloads filetypes specified in the maps for the selected client/system.
    """
    config = read_config()

    archive_sources = config.get("archive_sources", {})
    filestore = config.get("filestore", "filestore")
    clients = config.get("clients", [])

    async def run_and_stream():
        manufacturer_sources = archive_sources.get(req.manufacturer)
        if not manufacturer_sources:
            yield "Manufacturer not found\n"
            return
        system_entry = manufacturer_sources.get(req.system)
        if not system_entry:
            yield "System not found\n"
            return

        base_path_rel = system_entry.get("base_path", "")
        base_path = os.path.join(filestore, "Native" , base_path_rel)
        sources = system_entry.get("sources", [])
        download_layout = _get_download_layout_for_system(clients, req.manufacturer, req.system)

        # --- Find filetypes for this client/system ---
        filetypes = None
        # Find the client config
        for client in clients:
            for system in client.get("systems", []):
                if (
                    system.get("manufacturer") == req.manufacturer
                    and (system.get("system_mapping_name") or system.get("cananonical_system_name")) == req.system
                ):
                    # Look for query maps (new schema)
                    for map_entry in system.get("maps", []):
                        map_name = list(map_entry.keys())[0]
                        map_config = map_entry.get(map_name, {})
                        query_cfg = map_config.get("query") if isinstance(map_config, dict) else None
                        if not isinstance(query_cfg, dict):
                            continue
                        ft = []
                        for ext in query_cfg.get("extensions", []) or []:
                            ext_str = str(ext).strip()
                            if ext_str and ext_str != "*":
                                ft.append(ext_str)
                        if ft:
                            filetypes = list(set((filetypes or []) + ft))

                    # Backward compatibility: ...SoftwareArchives... filetypes
                    if not filetypes:
                        for map_entry in system.get("maps", []):
                            if "...SoftwareArchives..." in map_entry:
                                ft = []
                                for ft_entry in map_entry["...SoftwareArchives..."].get("filetypes", []):
                                    # filetypes can be dicts like {'Tape': 'UEF'} or {'HD': 'MMB,VHD'}
                                    if isinstance(ft_entry, dict):
                                        for v in ft_entry.values():
                                            ft.extend([x.strip() for x in v.split(",")])
                                    elif isinstance(ft_entry, str):
                                        ft.extend([x.strip() for x in ft_entry.split(",")])
                                filetypes = list(set(ft))
        # --- End filetype extraction ---

        found = False
        for entry in sources:
            source_name = entry.get("name", "source")
            source_type = entry.get("type")
            
            # Normalize URLs for all source types that use direct downloads
            if source_type in ["ddl", "mega"]:
                url_entries = normalize_source_urls(entry)
                if not url_entries:
                    yield "Source has no URL(s) configured\n"
                    continue

                for url_entry in url_entries:
                    url_entry["folder"] = _resolve_source_folder(
                        source_name=source_name,
                        folder=url_entry.get("folder", ""),
                        download_layout=download_layout,
                        base_path_rel=base_path_rel,
                    )
                
                found = True
                for idx, url_entry in enumerate(url_entries, 1):
                    url = url_entry["url"]
                    folder = url_entry["folder"]
                    dest_dir = os.path.join(base_path, folder)
                    os.makedirs(dest_dir, exist_ok=True)
                    
                    if len(url_entries) > 1:
                        yield f"Downloading file {idx}/{len(url_entries)}...\n"
                    
                    if source_type == "ddl":
                        # Estimate download time
                        est_sec = estimate_download_time(url)
                        try:
                            resp = requests.get(url, stream=True, timeout=30)
                            resp.raise_for_status()
                            filename = get_filename_from_response(resp, url)
                            dest_path = os.path.join(dest_dir, filename)
                            total = int(resp.headers.get("Content-Length", 0))
                            downloaded_bytes = 0
                            chunk_size = 8192
                            if est_sec is not None:
                                est_msg = f"Estimated download time for {filename}: ~{est_sec//60}m {est_sec%60}s at 10Mbps\n"
                            else:
                                est_msg = f"Could not estimate download time for {filename}\n"
                            yield est_msg
                            with open(dest_path, "wb") as f:
                                for chunk in resp.iter_content(chunk_size=chunk_size):
                                    if chunk:
                                        f.write(chunk)
                                        downloaded_bytes += len(chunk)
                                        if total:
                                            percent = int(downloaded_bytes * 100 / total)
                                            yield f"Downloading {filename}: {percent}%\n"
                            yield f"Downloaded for {req.manufacturer} / {req.system}: {dest_path}\n"
                        except Exception as e:  # pylint: disable=broad-except
                            yield f"Failed to download {url}: {e}\n"
                    
                    elif source_type == "mega":
                        try:
                            yield f"Starting MEGA download: {url}\n"
                            mega_client = Mega()
                            m = mega_client.login()
                            m.download_url(url, dest_dir)
                            yield f"Downloaded MEGA file for {req.manufacturer} / {req.system} to {dest_dir}\n"
                        except Exception as e:  # pylint: disable=broad-except
                            yield f"Failed to download MEGA {url}: {e}\n"
            
            elif source_type == "IA-COL":
                found = True
                url = entry.get("url")
                folder = _resolve_source_folder(
                    source_name=source_name,
                    folder=entry.get("folder", ""),
                    download_layout=download_layout,
                    base_path_rel=base_path_rel,
                )
                print(f"Downloading IA-COL {url} to {base_path} for {req.manufacturer} / {req.system}")
                try:
                    for msg in download_ia_collection(url, base_path, folder, filetypes=filetypes):
                        yield msg
                    yield (
                        f"Downloaded IA-COL for {req.manufacturer} / "
                        f"{req.system}: {os.path.join(base_path, folder)}\n"
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    yield f"Failed to download IA-COL {url}: {exc}\n"
            elif entry.get("type") == "tor":
                found = True
                url = entry.get("url")
                folder = _resolve_source_folder(
                    source_name=source_name,
                    folder=entry.get("folder", ""),
                    download_layout=download_layout,
                    base_path_rel=base_path_rel,
                )
                dest_dir = os.path.join(base_path, folder)
                os.makedirs(dest_dir, exist_ok=True)
                yield f"Starting torrent download: {url}\n"
                try:
                    ses = lt.session() # type: ignore
                    ses.listen_on(6881, 6891)
                    params = {
                        'save_path': dest_dir,
                        'storage_mode': lt.storage_mode_t(2), # type: ignore
                    }
                    if url.endswith('.torrent'):
                        yield f"Not a magnet - {url}\n"
                        # Download the torrent file to a temp location
                        resp = requests.get(url, verify=False, timeout=30)
                        resp.raise_for_status()
                        filename = get_filename_from_response(resp, url)
                        with tempfile.NamedTemporaryFile(delete=False, suffix=".torrent") as tf:
                            tf.write(resp.content)
                            torrent_path = tf.name
                        info = lt.torrent_info(torrent_path) # type: ignore
                        h = ses.add_torrent({'ti': info, 'save_path': dest_dir})
                    else:
                        # Assume magnet link
                        yield f"Is a magnet - {url}\n"
                        h = lt.add_magnet_uri(ses, url, params) # type: ignore
                    yield "Fetching metadata...\n"
                    while not h.has_metadata():
                        await asyncio.sleep(1)
                    yield "Metadata received. Downloading...\n"
                    while not h.is_seed():
                        s = h.status()
                        percent = int(s.progress * 100)
                        yield f"Torrent progress: {percent}% ({s.download_rate/1000:.1f} kB/s)\n"
                        await asyncio.sleep(2)
                    yield f"Torrent download complete for {req.manufacturer} / {req.system}: {dest_dir}\n"
                except Exception as e:  # pylint: disable=broad-except
                    yield f"Failed to download torrent {url}: {e}\n"
        
        if not found:
            yield "No sources found for this system\n"
        else:
            yield f"Done downloading for {req.manufacturer} / {req.system}.\n"

    return StreamingResponse(run_and_stream(), media_type="text/plain")


def download_ia_collection(url, base_path, folder, filetypes=None):
    """
    Download all files from an Internet Archive collection to the correct folder directory.
    Optionally filter by file extension.

    Args:
        url (str): The Internet Archive collection URL.
        base_path (str): The base directory (from YAML).
        folder (str): The folder subdirectory (from YAML).
        filetypes (str or list, optional): Comma-separated string or list of file extensions.

    Yields:
        str: Progress messages for each item downloaded.
    """
    dest_dir = os.path.join(base_path, folder)
    os.makedirs(dest_dir, exist_ok=True)

    match = re.search(r'/details/([^/?#]+)', url)
    if not match:
        yield f"Could not extract collection name from URL: {url}\n"
        return

    if filetypes:
        if isinstance(filetypes, str):
            filetypes_set = set(ft.strip().lower() for ft in filetypes.split(","))
        else:
            filetypes_set = set(ft.strip().lower() for ft in filetypes)
    else:
        filetypes_set = None

    collection_name = match.group(1)
    yield f"Fetching Internet Archive collection: {collection_name}\n"

    # Extensions used by IA for thumbnails and metadata - skip unless an explicit filetype filter is set
    IA_METADATA_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'xml', 'sqlite', 'torrent', 'md5', 'sha1'}

    def _download_ia_item(ia_item, item_id):
        """Download matching files from a single IA item. Yields progress strings."""
        files_to_download = []
        for f in ia_item.files:
            name = f['name']
            ext = name.split('.')[-1].lower() if '.' in name else ''
            # Skip IA-generated metadata/derivative files unless caller requested them explicitly
            if not filetypes_set:
                if f.get('source') == 'metadata' or name.startswith('_'):
                    continue
                if ext in IA_METADATA_EXTENSIONS:
                    continue
            if not filetypes_set or ext in filetypes_set:
                files_to_download.append(name)
        if not files_to_download:
            yield f"No matching files in item: {item_id}\n"
            return
        yield f"Downloading {len(files_to_download)} content file(s) from item: {item_id}\n"
        # Download one file at a time: gives per-file progress, isolates errors,
        # and avoids a single timeout killing the entire batch.
        for fname in files_to_download:
            try:
                ia_item.download(
                    destdir=dest_dir,
                    files=[fname],
                    verbose=False,
                    checksum=True,
                    no_directory=True,
                    timeout=300,
                )
                yield f"   ✓ {fname}\n"
            except Exception as exc:  # pylint: disable=broad-except
                yield f"   ✗ Failed '{fname}': {exc}\n"

    # First try treating the identifier as a collection (search for member items).
    # If the search returns nothing the identifier is likely a single item itself
    # (e.g. https://archive.org/details/rr-3do is one item, not a collection of items).
    search_results = list(internetarchive.search_items(f'collection:{collection_name}'))
    if search_results:
        yield f"Found {len(search_results)} item(s) in collection '{collection_name}'\n"
        for result in search_results:
            item_id = result['identifier']
            ia_item = internetarchive.get_item(item_id)
            yield from _download_ia_item(ia_item, item_id)
    else:
        # Fall back: treat the identifier as a direct single-item download
        yield f"No collection found for '{collection_name}', trying as a direct item...\n"
        ia_item = internetarchive.get_item(collection_name)
        if not ia_item.metadata:
            yield f"Item '{collection_name}' not found on Internet Archive\n"
            return
        yield f"Found item: {ia_item.metadata.get('title', collection_name)}\n"
        yield from _download_ia_item(ia_item, collection_name)


def get_filename_from_response(resp, url):
    # Try Content-Disposition header
    cd = resp.headers.get('Content-Disposition')
    if cd:
        fname_match = re.findall('filename="?([^"]+)"?', cd)
        if fname_match:
            return fname_match[0]
    # Fallback: sanitize URL
    parsed = urlparse(url)
    filename = os.path.basename(parsed.path)
    return unquote(filename)


# ============================================================================
# DATABASE-DRIVEN VIRTUAL MAPPINGS ENDPOINTS
# ============================================================================

@app.get("/systems")
def list_all_systems():
    """
    List all systems available in database.
    
    Returns: {
        "systems": ["Apple/AppleII", "Nintendo/NES", ...],
        "count": N
    }
    """
    try:
        from db.queries import query_all_systems
        systems = query_all_systems()
        return {
            'systems': systems,
            'count': len(systems)
        }
    except Exception as e:
        logger.error(f"Error listing systems: {e}", exc_info=True)
        return {'error': str(e), 'systems': []}, 500


@app.post("/systems/{system}/query-mapping")
def query_custom_mapping(system: str, request: QueryMappingRequest):
    """
    Query files for custom mapping creation.
    
    POST body: {
        "extensions": ["nib", "bxy", "dsk"],
        "limit": 100
    }
    
    Returns: {
        "files": [
            {"file_id": 1, "filename": "game.nib", "path": "...", "extension": "nib"},
            ...
        ],
        "count": N,
        "system": "Apple/AppleII",
        "extensions": ["nib", "bxy", "dsk"]
    }
    """
    try:
        from db.queries import query_files_by_system_and_extensions
        
        system = unquote(system)  # Handle URL-encoded system names
        
        # Validate input
        if not request.extensions:
            return {'error': 'extensions parameter required (array of file extensions)'}, 400
        
        if not system:
            return {'error': 'system parameter required (from URL path)'}, 400
        
        # Query database
        files = query_files_by_system_and_extensions(system, request.extensions, request.limit)
        
        return {
            'files': files,
            'count': len(files),
            'system': system,
            'extensions': request.extensions,
            'query_mode': 'database'
        }
    
    except Exception as e:
        logger.error(f"Error querying mapping: {e}", exc_info=True)
        return {'error': str(e)}, 500


@app.get("/systems/{system}/extensions")
def get_system_extensions(system: str):
    """
    Get all available file extensions for a system.
    
    Returns: {
        "system": "Apple/AppleII",
        "extensions": ["dsk", "do", "po", "2mg", "nib", "bxy"],
        "counts": {"dsk": 47, "do": 12, ...}
    }
    """
    try:
        from db.queries import query_extensions_by_system, query_file_count_by_system_and_extension
        
        system = unquote(system)
        extensions = query_extensions_by_system(system)
        
        # Get count for each extension
        counts = {}
        for ext in extensions:
            counts[ext] = query_file_count_by_system_and_extension(system, ext)
        
        return {
            'system': system,
            'extensions': extensions,
            'counts': counts
        }
    
    except Exception as e:
        logger.error(f"Error getting system extensions: {e}", exc_info=True)
        return {'error': str(e)}, 500


@app.get("/systems/{system}/stats")
def get_system_statistics(system: str):
    """
    Get statistics about a system (file counts, sizes, extensions).
    
    Returns: {
        "system": "Apple/AppleII",
        "total_files": 200,
        "total_size": 1048576,
        "extension_counts": {"dsk": 47, "do": 12, ...},
        "extensions": ["dsk", "do", "po", ...]
    }
    """
    try:
        from db.queries import query_system_statistics
        
        system = unquote(system)
        stats = query_system_statistics(system)
        stats['system'] = system
        
        return stats
    
    except Exception as e:
        logger.error(f"Error getting system statistics: {e}", exc_info=True)
        return {'error': str(e)}, 500


# ==================== MAME Software Downloads ====================

@app.get("/mame/systems", tags=["MAME Downloads"])
def get_mame_configured_systems():
    """Get all systems with MAME sources configured."""
    try:
        from mame.manager import MAMEDownloadManager
        
        config = read_config()
        manager = MAMEDownloadManager(config)
        systems = manager.discover_systems_with_mame_sources()
        
        return {
            'systems': systems,
            'total': len(systems)
        }
    except Exception as e:
        logger.error(f"Error getting MAME systems: {e}", exc_info=True)
        return {'error': str(e)}, 500


@app.get("/mame/status", tags=["MAME Downloads"])
def get_mame_download_status():
    """Get MAME download directory status and statistics."""
    try:
        from mame.manager import MAMEDownloadManager
        
        config = read_config()
        manager = MAMEDownloadManager(config)
        status = manager.get_download_status()
        
        return status
    except Exception as e:
        logger.error(f"Error getting MAME download status: {e}", exc_info=True)
        return {'error': str(e)}, 500


class MAMEDownloadRequest(BaseModel):
    """Request body for MAME downloads."""
    system: str
    media_type: str
    target_folder: str
    filters: dict = None


@app.post("/mame/download", tags=["MAME Downloads"])
def download_mame_software(request: MAMEDownloadRequest):
    """
    Download MAME software for a specific system and media type.
    
    Request body:
    {
        "system": "atom",
        "media_type": "cass",
        "target_folder": "Software/MAME/Cassettes",
        "filters": {
            "publishers": ["Acornsoft"],
            "exclude_unsupported": true,
            "year_range": [1980, 1990]
        }
    }
    """
    try:
        from mame.manager import MAMEDownloadManager
        
        config = read_config()
        manager = MAMEDownloadManager(config)
        
        stats = manager.download_for_system(
            request.system,
            request.media_type,
            request.target_folder,
            request.filters
        )
        
        return {
            'status': 'completed',
            'stats': stats
        }
    except Exception as e:
        logger.error(f"Error downloading MAME software: {e}", exc_info=True)
        return {'error': str(e)}, 500


@app.post("/mame/download-all", tags=["MAME Downloads"])
def download_all_mame_software():
    """Download all configured MAME software across all systems."""
    try:
        from mame.manager import MAMEDownloadManager
        
        config = read_config()
        manager = MAMEDownloadManager(config)
        
        all_stats = manager.download_all_configured()
        
        return {
            'status': 'completed',
            'stats': all_stats,
            'total_systems': len(all_stats)
        }
    except Exception as e:
        logger.error(f"Error downloading all MAME software: {e}", exc_info=True)
        return {'error': str(e)}, 500


@app.get("/mame/hash/{system}/{media_type}", tags=["MAME Downloads"])
def get_mame_hash_entries(system: str, media_type: str):
    """
    Get software entries from a MAME hash file without downloading.

    Useful for previewing what would be downloaded.
    """
    try:
        from mame.manager import MAMEDownloadManager
        from mame.hash_parser import MAMEHashParser

        config = read_config()
        manager = MAMEDownloadManager(config)

        # Fetch hash file
        hash_content = manager._get_hash_file(system, media_type)
        if not hash_content:
            return {'error': f'Hash file not found for {system}_{media_type}'}, 404

        # Parse entries
        parser = MAMEHashParser()
        entries = parser.parse_hash_file(hash_content)

        # Convert to serializable format
        entries_data = []
        for entry in entries:
            entries_data.append({
                'software_name': entry.software_name,
                'description': entry.description,
                'year': entry.year,
                'publisher': entry.publisher,
                'supported': entry.supported,
                'interface': entry.interface,
                'usage_info': entry.usage_info,
                'rom_files': [
                    {
                        'name': rom.name,
                        'size': rom.size,
                        'crc': rom.crc,
                        'sha1': rom.sha1
                    }
                    for rom in entry.rom_files
                ]
            })

        return {
            'system': system,
            'media_type': media_type,
            'total_entries': len(entries),
            'entries': entries_data
        }
    except Exception as e:
        logger.error(f"Error getting MAME hash entries: {e}", exc_info=True)
        return {'error': str(e)}, 500


def _get_connection_profile(request: Request | None = None):
    """Resolve externally reachable SMB endpoint for setup guidance and script generation."""
    config = read_config()
    smb_config = config.get('smb', {})

    def _strip_port(hostname: str) -> str:
        value = (hostname or '').strip()
        if value and ':' in value and not value.startswith('['):
            value = value.split(':', 1)[0]
        return value

    def _is_loopback(hostname: str) -> bool:
        normalized = (hostname or '').strip().lower()
        return normalized in {'localhost', '127.0.0.1', '::1'}

    advertised_host = (os.getenv('SMB_ADVERTISE_HOST') or '').strip()
    advertised_port = (os.getenv('SMB_ADVERTISE_PORT') or '').strip()
    advertised_share = (os.getenv('SMB_ADVERTISE_SHARE') or '').strip()
    advertised_native_share = (os.getenv('SMB_ADVERTISE_NATIVE_SHARE') or '').strip()
    avahi_hostname = (os.getenv('AVAHI_HOSTNAME') or '').strip()

    host = _strip_port(advertised_host)
    if not host and request is not None:
        forwarded_host = (request.headers.get('x-forwarded-host') or '').split(',')[0].strip()
        host = _strip_port(forwarded_host or (request.url.hostname or ''))

    if _is_loopback(host):
        fallback_host = _strip_port(avahi_hostname)
        if fallback_host and not _is_loopback(fallback_host):
            host = fallback_host

    if not host:
        host = _strip_port(avahi_hostname) or 'transfs.local'

    port = advertised_port or '3445'
    try:
        port_num = int(str(port))
        if port_num < 1 or port_num > 65535:
            raise ValueError('invalid port range')
        port = str(port_num)
    except Exception:
        port = '3445'

    share_name = advertised_share or 'TransFS'
    native_share_name = advertised_native_share or 'TransFSNative'
    smb_username = smb_config.get('username', 'root')
    allow_guest = bool(smb_config.get('allow_guest', False))

    unc_path = f"\\\\{host}\\{share_name}"
    if share_name.lower().endswith('\\retrobat'):
        virtual_unc_path = unc_path
    else:
        virtual_unc_path = f"{unc_path}\\RetroBat"
    requires_custom_port = port != '445'

    return {
        'host': host,
        'port': port,
        'share_name': share_name,
        'native_share_name': native_share_name,
        'unc_path': unc_path,
        'virtual_unc_path': virtual_unc_path,
        'requires_custom_port': requires_custom_port,
        'smb_username': smb_username,
        'allow_guest': allow_guest,
        'source': 'env' if (advertised_host or advertised_port or advertised_share or advertised_native_share) else 'derived'
    }


@app.get("/setup/connection-profile", tags=["Setup"])
def get_setup_connection_profile(request: Request):
    """Return client setup connection details for Windows/Linux/MiSTer guidance."""
    try:
        profile = _get_connection_profile(request)

        profile['windows_mapping_command'] = (
            f"New-SmbMapping -LocalPath U: -RemotePath {profile['virtual_unc_path']} "
            f"-TcpPort {profile['port']} -UserName {profile['smb_username']} -Persistent $true"
        )
        profile['windows_native_mapping_command'] = (
            f"New-SmbMapping -LocalPath V: -RemotePath \\\\{profile['host']}\\{profile['native_share_name']} "
            f"-TcpPort {profile['port']} -UserName {profile['smb_username']} -Persistent $true"
        )

        mister_opts = [
            'rw',
            'relatime',
            'vers=3.1.1',
            f"username={profile['smb_username']}",
            'uid=0',
            'gid=0'
        ]
        if profile['requires_custom_port']:
            mister_opts.append(f"port={profile['port']}")

        profile['mister_mount_example'] = (
            f"//{profile['host']}/{profile['share_name']}/MiSTer on /media/fat/cifs "
            f"type cifs ({','.join(mister_opts)})"
        )
        profile['download_script_url'] = '/api/download/setup-windows'

        return profile
    except Exception as e:
        logger.error(f"Error building setup connection profile: {e}", exc_info=True)
        return {'error': str(e)}, 500


@app.get("/download/setup-windows", tags=["Setup"])
def download_setup_windows_script(request: Request):
    """Download setup_windows.ps1 with values injected from the resolved connection profile."""
    try:
        profile = _get_connection_profile(request)

        candidate_paths = [
            Path('/app/setup_windows.ps1.template'),
            Path(__file__).resolve().with_name('setup_windows.ps1.template'),
            Path(__file__).resolve().parent.parent / 'setup_windows.ps1.template',
        ]
        template_path = next((path for path in candidate_paths if path.exists()), None)
        if template_path is None:
            return {'error': 'Setup script template not found'}, 404

        template_content = template_path.read_text(encoding='utf-8')
        script_content = template_content
        script_content = script_content.replace('{{TRANSFS_SMB_USERNAME}}', profile['smb_username'])
        script_content = script_content.replace('{{TRANSFS_SMB_HOST}}', profile['host'])
        script_content = script_content.replace('{{TRANSFS_SMB_PORT}}', profile['port'])
        script_content = script_content.replace('{{TRANSFS_SHARE_NAME}}', profile['share_name'])
        script_content = script_content.replace('{{TRANSFS_NATIVE_SHARE_NAME}}', profile['native_share_name'])

        return StreamingResponse(
            iter([script_content]),
            media_type="application/x-powershell",
            headers={"Content-Disposition": "attachment; filename=setup_windows.ps1"}
        )
    except Exception as e:
        logger.error(f"Error generating setup script: {e}", exc_info=True)
        return {'error': str(e)}, 500

