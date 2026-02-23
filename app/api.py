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
import time
import uuid
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import internetarchive
import libtorrent as lt  # pylint: disable=import-error
import py7zr
import rarfile  # pylint: disable=import-error
import requests
import yaml
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse, StreamingResponse
from mega import Mega
from pydantic import BaseModel
from config import (
    get_clients,
    get_systems_for_client,
    get_manufacturers_and_canonical_names,
    get_system_config,
    read_config,
    read_clients_config,
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
    if download_layout != "source_based":
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


class PackInstallRequestNoClient(BaseModel):
    """Request model for client-agnostic pack installation."""
    pack_ids: list[str]  # List of pack IDs to install
    skip_existing: bool = True  # Deduplicate - skip files that already exist


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
    """Browse a directory and return its contents with metadata and cache status."""
    import time
    start_time = time.time()
    
    # Validate path is within allowed directories
    allowed_prefixes = ["/mnt/filestorefs/Native", "/mnt/transfs"]
    if not any(path.startswith(prefix) for prefix in allowed_prefixes):
        return {"error": "Access denied - path must be within allowed directories"}
    
    # Normalize path to prevent directory traversal
    path = os.path.normpath(path)
    print(f"[BROWSE] validation done, elapsed={time.time()-start_time:.4f}s", flush=True)
    
    if not os.path.exists(path):
        return {"error": "Path does not exist"}
    print(f"[BROWSE] exists check done, elapsed={time.time()-start_time:.4f}s", flush=True)
    
    if not os.path.isdir(path):
        return {"error": "Path is not a directory"}
    print(f"[BROWSE] isdir check done, elapsed={time.time()-start_time:.4f}s", flush=True)
    
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
    
    # OPTIMIZATION: For query map directories, use database instead of FUSE
    # This is MUCH faster for large directories (4000+ files)
    if path.startswith("/mnt/transfs"):
        from pathlib import Path as PathLib
        parts = PathLib(path).parts
        root_parts = PathLib("/mnt/transfs").parts
        rel_parts = parts[len(root_parts):]
        
        # Check if this is a query map directory (client/system/map)
        if len(rel_parts) == 3:
            print(f"[BROWSE] ENTERED query map handler - rel_parts={rel_parts}", flush=True)
            client_name, system_name, map_name = rel_parts
            try:
                from db.queries import query_files_by_client_system_and_map
                from pathutils import get_client, get_system_info, get_map_config
                print(f"[BROWSE] Attempting database query for {client_name}/{system_name}/{map_name}", flush=True)
                
                db_files = query_files_by_client_system_and_map(
                    client=client_name,
                    system=system_name,
                    map_name=map_name
                )
                
                if db_files:
                    print(f"[BROWSE] Database returned {len(db_files)} files, elapsed={time.time()-start_time:.4f}s", flush=True)
                    
                    # Check for preserve_structure setting
                    config = read_config()
                    client = get_client(config, rel_parts)
                    system = next((s for s in client.get('systems', []) if s['name'] == system_name), None) if client else None
                    map_entry = None
                    preserve_structure = False
                    
                    if system:
                        map_entry = next((m for m in system.get('maps', []) if m and isinstance(m, dict) and map_name in m), None)
                        if map_entry and map_name in map_entry:
                            map_config = get_map_config(map_entry)
                            if map_config and isinstance(map_config, dict):
                                query_cfg = map_config.get("query", {})
                                preserve_structure = query_cfg.get("preserve_structure", False)
                    
                    logger = logging.getLogger("api")
                    logger.warning(f"[CRITICAL-API] Processing {map_name}. preserve_structure={preserve_structure}")
                    
                    if preserve_structure:
                        # Build virtual directory tree from relative paths
                        entries_set = set()
                        source_dir = "Software"  # Default, would come from query_cfg in real scenario
                        
                        logger.warning(f"[CRITICAL-API] Building virtual tree for {len(db_files)} files")
                        
                        for f in db_files:
                            source_path = f.get("source_path", "")
                            filename = f.get("filename", "")
                            
                            if source_path and source_dir in source_path:
                                # Extract relative path from source_path
                                parts = source_path.split('/')
                                try:
                                    idx = parts.index(source_dir)
                                    relative_parts = parts[idx+1:]
                                    if relative_parts:
                                        # Join all but the last part (which is filename) to get directory
                                        relative_dir = '/'.join(relative_parts[:-1])
                                        if relative_dir:
                                            entry = relative_dir + '/' + filename
                                        else:
                                            entry = filename
                                        entries_set.add(entry)
                                    else:
                                        entries_set.add(filename)
                                except ValueError:
                                    entries_set.add(filename)
                            else:
                                entries_set.add(filename)
                        
                        # Build virtual tree with directory entries
                        virtual_tree = set()
                        for entry in entries_set:
                            parts = entry.split('/')
                            if len(parts) > 1:
                                for i in range(len(parts)):
                                    virtual_tree.add('/'.join(parts[:i+1]))
                            else:
                                virtual_tree.add(entry)
                        
                        logger.warning(f"[CRITICAL-API] Built virtual tree with {len(virtual_tree)} entries from {len(entries_set)}")
                        
                        # Convert to API response format
                        entries = []
                        for entry in sorted(virtual_tree):
                            if '/' in entry:
                                dir_parts = entry.split('/')
                                name = dir_parts[-1]
                                entries.append({
                                    "name": name,
                                    "type": "dir",
                                    "size": None,
                                    "supports_zaparoo": False
                                })
                            else:
                                entries.append({
                                    "name": entry,
                                    "type": "file",
                                    "size": next((f["size"] for f in db_files if f["filename"] == entry), None),
                                    "supports_zaparoo": supports_zaparoo
                                })
                    else:
                        # Plain file listing (original behavior)
                        entries = [
                            {
                                "name": f["filename"],
                                "type": "file",
                                "size": f["size"],
                                "supports_zaparoo": supports_zaparoo
                            }
                            for f in db_files
                        ]
                    
                    return {"path": path, "entries": entries}
                else:
                    print(f"[BROWSE] Database returned no files, falling back to FUSE", flush=True)
            except Exception as e:
                import logging
                logger = logging.getLogger("api")
                logger.warning(f"Database query failed for {path}, falling back to FUSE: {e}")
                print(f"[BROWSE] Database query failed, falling back to FUSE: {e}", flush=True)
    
    try:
        # Optimization: for ZIP-internal paths under /mnt/transfs, translate to real path first
        # This bypasses FUSE and uses zippath's cached index directly
        real_path = path
        if path.startswith("/mnt/transfs") and (".zip/" in path or ".zip\\" in path):
            # Import here to access TransFS internals
            from sourcepath import get_source_path
            import logging
            
            logger = logging.getLogger("api")
            config = read_config()
            root = "/mnt/filestorefs"
            
            # Get the real source path (bypasses FUSE)
            source_path = get_source_path(logger, config, root, path)
            if isinstance(source_path, tuple):
                # It's a ZIP tuple (zip_path, internal_path)
                zip_real_path, internal = source_path
                real_path = os.path.join(zip_real_path, internal)
            elif source_path:
                real_path = source_path
        
        # Now use zippath.listdir_with_info on the real path
        if ".zip/" in real_path or ".zip\\" in real_path:
            from zippath import listdir_with_info
            try:
                items = listdir_with_info(real_path)
                entries = [
                    {
                        "name": item["name"],
                        "type": "directory" if item["is_dir"] else "file",
                        "size": item["size"] if not item["is_dir"] else None,
                        "supports_zaparoo": supports_zaparoo
                    }
                    for item in items
                ]
                return {"path": path, "entries": entries}
            except Exception as e:  # pylint: disable=broad-except
                # Fall back to standard method if zippath fails
                import logging
                logger = logging.getLogger("api")
                logger.error("zippath.listdir_with_info failed: %s", e, exc_info=True)
        
        # Standard method for non-ZIP paths
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
                    
                    size = None
                    if not is_dir:
                        try:
                            size = entry.stat(follow_symlinks=False).st_size
                        except (PermissionError, OSError):
                            pass
                    
                    entries.append({
                        "name": entry.name,
                        "type": "directory" if is_dir else "file",
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
        from config import read_config
        from feature_flags import FeatureFlagManager
        
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
                
                # Initialize database
                init_database()
                
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
        init_database()
        
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
            if all(f in ['ui', 'web_api', 'mountpoint', 'filestore', 'database'] for f in field_list):
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
            })
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
        
        with open(app_config_path, "w", encoding="utf-8") as f:
            yaml.dump(app_config, f, default_flow_style=False)
        
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
                })
            }
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

# Global storage for test runs (in production, use a database)
_test_runs = {}


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
            # Match: ../tests/file.py::ClassName::test_name[param] PERF|...
            # Stop at PERF or status keywords
            test_start_pattern = r'^(\.\./tests/[^\s]+)::(.+?)(?:\s+(?:PERF|PASSED|FAILED|SKIPPED|XPASS|XFAIL))'
            status_pattern = r'^\s*(PASSED|FAILED|SKIPPED|XPASS|XFAIL)(?:\s+(.*))?$'
            perf_pattern = r'PERF\|test=(.+?)\|op=(.+?)\|path=(.+?)\|actual=([\d.]+)\|target=([\d.]+)'
            
            # Parse test output line by line
            test_results = {}
            current_test = None
            current_perf_data = []
            
            lines = run["output"].split('\n')
            i = 0
            while i < len(lines):
                line = lines[i]
                
                # Check for test start
                test_match = re.search(test_start_pattern, line)
                if test_match:
                    test_file = test_match.group(1).strip()
                    test_name = test_match.group(2).strip()
                    
                    test_key = f"{test_file}::{test_name}"
                    current_test = test_key
                    current_perf_data = []
                    
                    # Check if status is on same line
                    inline_status_match = re.search(r'\s(PASSED|FAILED|SKIPPED|XPASS|XFAIL)', line)
                    if inline_status_match:
                        status = inline_status_match.group(1)
                    else:
                        # Look ahead for status on next lines
                        status = None
                        j = i + 1
                        while j < len(lines) and j < i + 10:  # Look ahead max 10 lines
                            next_line = lines[j]
                            status_match = re.match(status_pattern, next_line)
                            if status_match:
                                status = status_match.group(1)
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
                        reason = "Skipped (fixture or condition not met)"
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
            
            # Third pass: extract skip reasons from our custom pytest hook output
            # We added a pytest hook that prints "[SKIP_REASON] test_nodeid - reason" 
            skip_reason_pattern = r'\[SKIP_REASON\]\s+([^\s]+)\s+-\s+(.+)$'
            for line in run["output"].split('\n'):
                match = re.match(skip_reason_pattern, line)
                if match:
                    test_nodeid = match.group(1).strip()
                    skip_reason = match.group(2).strip()
                    
                    # Try to find a matching test in test_results
                    for result_key in test_results.keys():
                        # The nodeid format is path::Class::method[param], we need to convert our keys
                        if test_nodeid in result_key or result_key.endswith(test_nodeid):
                            test_results[result_key]["reason"] = skip_reason
                            break
            
            # Fourth pass: extract skip reasons from short summary output (pytest -rs)
            # Lines look like: "SKIPPED [1] ../tests/test_systems.py:221: Amstrad CPC: TransFS path not found at /mnt/transfs/..."
            in_skipped_section = False
            skip_line_pattern = r'^SKIPPED\s+\[\d+\]\s+(.+?):\s+(.+)$'
            
            lines = run["output"].split('\n')
            for i, line in enumerate(lines):
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
                        reason = match.group(2).strip()

                        # Try to map by system name inside the reason
                        system_name_match = re.match(r'^([^:]+):\s+(.+)$', reason)
                        if system_name_match:
                            system_name = system_name_match.group(1).strip()
                            for result_key in test_results.keys():
                                if f"[{system_name}]" in result_key and test_results[result_key]["status"] == "SKIPPED":
                                    test_results[result_key]["reason"] = reason
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
        from db.connection import get_connection, init_database
        
        config = read_config()
        
        # Normalize path
        if not path.startswith("/mnt/transfs") and not path.startswith("/mnt/filestorefs"):
            return {"error": "Invalid path"}
        
        # Convert /mnt/transfs paths to /mnt/filestorefs for database lookup
        db_path_lookup = path.replace("/mnt/transfs", "/mnt/filestorefs")
        
        try:
            # Initialize database connection pool if needed (uses environment variables)
            try:
                init_database()
            except Exception:
                # If init fails, continue - connection pool might already be initialized
                pass
            
            conn = get_connection()
            cursor = conn.cursor()
            
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
                # Fallback: try direct source_path or legacy virtual_path lookup
                cursor.execute("""
                    SELECT file_id, filename, extension, size, mtime, is_archive, content_type, filename as display_name, source_path, created_at, updated_at
                    FROM files
                    WHERE source_path = %s OR virtual_path = %s
                    LIMIT 1
                """, (db_path_lookup, path))
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
                return {
                    "error": "File not found in metadata database",
                    "hint": "Run Update DB to sync metadata for this file",
                    "path": path,
                }
            
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
    
    # Get the system's sources from archive_sources
    manufacturer_sources = archive_sources.get(system_config.manufacturer, {})
    system_sources = manufacturer_sources.get(system_config.canonical_name, {})
    available_sources = {s["name"]: s for s in system_sources.get("sources", [])}
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
                    
                    # Normalize URLs (supports single url or multiple urls)
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
                        if system_config.download_layout == "source_based" and organize_ext:
                            yield "   ⚠ Skipping organize_by_extension for source_based layout\n"
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
                        if system_config.download_layout == "source_based" and organize_ext:
                            yield "   ⚠ Skipping organize_by_extension for source_based layout\n"
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
                        if system_config.download_layout == "source_based" and organize_ext:
                            yield "   ⚠ Skipping organize_by_extension for source_based layout\n"
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
        
        # Run database sync at the end of pack installation
        try:
            yield "\n" + "=" * 60 + "\n"
            yield "🔄 Starting database synchronization...\n"
            yield "=" * 60 + "\n\n"
            
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
            
            # Create DatabaseSync instance and run full sync
            config = read_config()
            db_sync = DatabaseSync(config)
            db_sync.full_sync(client_filter=client_name, system_filter=system_name)
            
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
            system_mapping_name = system.get("system_mapping_name") or system.get("cananonical_system_name")
            if (system.get("manufacturer") == manufacturer and 
                system_mapping_name == system_name):
                client_name = client.get("name")
                system_actual_name = system.get("name") or system_name
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

    for item in internetarchive.search_items(f'collection:{collection_name}'):
        item_id = item['identifier']
#        yield f"Processing item: {item_id}\n"
        ia_item = internetarchive.get_item(item_id)
        ia_files = ia_item.files
        files_to_download = []
        for f in ia_files:
            ext = f['name'].split('.')[-1].lower() if '.' in f['name'] else ''
            if not filetypes_set or ext in filetypes_set:
                files_to_download.append(f['name'])
        if files_to_download:
            yield f"Downloading {len(files_to_download)} file(s) from item: {item_id}\n"
            ia_item.download(
                destdir=dest_dir,
                files=files_to_download,
                verbose=False,
                checksum=True,
                no_directory=True
            )
 #           yield f"Downloaded item: {item_id}\n"
        else:
            yield f"No matching files in item: {item_id}\n"


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
