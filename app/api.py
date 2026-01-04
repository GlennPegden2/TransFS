""" API Wrapper 

SECURITY NOTE: This API is designed for local development use within Docker.
- Path Traversal: Paths are from trusted transfs.yaml configuration
- SSRF: URLs are from trusted archive_sources configuration  
- SSL Verification: May be disabled for legacy/local sources
DO NOT expose this API to untrusted networks or public internet.
"""
import asyncio
import math
import os
import re
import tempfile
import zipfile
from urllib.parse import unquote, urlparse

import internetarchive
import libtorrent as lt  # pylint: disable=import-error
import py7zr
import rarfile  # pylint: disable=import-error
import requests
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
)
from post_process import PostProcessor
app = FastAPI()


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


@app.get("/logs", response_class=PlainTextResponse)
def get_logs():
    try:
        with open("/tmp/transfs.log", "r", encoding="utf-8") as f:
            return f.read()[-10000:]  # Return last 10k chars (or whatever you want)
    except Exception as e:  # pylint: disable=broad-except
        return f"Could not read log: {e}"

@app.get("/browse")
def api_browse_directory(path: str):
    """Browse a directory and return its contents."""
    # Validate path is within allowed directories
    allowed_prefixes = ["/mnt/filestorefs/Native", "/mnt/transfs"]
    if not any(path.startswith(prefix) for prefix in allowed_prefixes):
        return {"error": "Access denied - path must be within allowed directories"}
    
    # Normalize path to prevent directory traversal
    path = os.path.normpath(path)
    
    if not os.path.exists(path):
        return {"error": "Path does not exist"}
    
    if not os.path.isdir(path):
        return {"error": "Path is not a directory"}
    
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
                        "size": item["size"] if not item["is_dir"] else None
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
                    "size": None  # Skip size for performance
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
                        "size": size
                    })
                except (PermissionError, OSError):
                    # Skip entries we can't access
                    continue
        
        return {"path": path, "entries": entries}
    except PermissionError:
        return {"error": "Permission denied"}
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}

@app.get("/cache/status")
def cache_status(path: str):
    """Get cache status for a given path."""
    try:
        from dirlisting import get_cache_status
        # Translate /mnt/transfs to /mnt/filestorefs for cache lookup
        cache_path = path.replace('/mnt/transfs', '/mnt/filestorefs')
        return get_cache_status(cache_path)
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}

@app.post("/cache/clear")
def cache_clear(path: str = None):
    """Clear cache for a specific path or all caches."""
    try:
        from dirlisting import clear_cache
        # Translate /mnt/transfs to /mnt/filestorefs for cache lookup
        cache_path = path.replace('/mnt/transfs', '/mnt/filestorefs') if path else None
        return clear_cache(cache_path)
    except Exception as e:  # pylint: disable=broad-except
        return {"error": str(e)}

@app.get("/clients")
def api_get_clients():
    """Return a list of all configured clients."""
    return get_clients()


@app.get("/clients/{client_name}/systems")
def api_get_systems(client_name: str):
    """Return a list of systems for a given client."""
    return get_systems_for_client(client_name)


@app.get("/systems/meta")
def api_get_manufacturers_and_canonical_names():
    """Return manufacturers and canonical system names metadata."""
    return get_manufacturers_and_canonical_names()


@app.get("/clients/{client_name}/systems/{system_name}/packs")
def api_get_packs(client_name: str, system_name: str):
    """Return available packs for a specific system."""
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
                "info_links": pack.info_links or []
            }
            for pack in system_config.packs
        ]
    }


@app.post("/clients/{client_name}/systems/{system_name}/install-packs")
async def api_install_packs(client_name: str, system_name: str, req: PackInstallRequest):
    """
    Install selected packs for a system by:
    1. Downloading sources referenced by each pack
    2. Running build scripts to process the downloaded content
    Streams output as downloads and builds execute.
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
                                                    yield f"      {percent}% "
                                
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
                                        yield f"      {percent}% ({s.download_rate/1000:.1f} kB/s) "
                                        last_percent = percent
                                    await asyncio.sleep(2)
                                
                                yield "\n      ✓ Torrent download complete\n"
                                
                            except Exception as e:  # pylint: disable=broad-except
                                yield f"      ✗ Torrent download failed: {str(e)}\n"
                                continue
                        
                        # Handle organize_by_extension at source level (after all URLs downloaded/extracted)
                        organize_ext = source.get("organize_by_extension")
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
    
    return StreamingResponse(run_and_stream(), media_type="text/plain")


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

        # --- Find filetypes for this client/system ---
        filetypes = None
        # Find the client config
        for client in clients:
            for system in client.get("systems", []):
                if (
                    system.get("manufacturer") == req.manufacturer
                    and system.get("cananonical_system_name") == req.system
                ):
                    # Look for ...SoftwareArchives... map
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
            source_type = entry.get("type")
            
            # Normalize URLs for all source types that use direct downloads
            if source_type in ["ddl", "mega"]:
                url_entries = normalize_source_urls(entry)
                if not url_entries:
                    yield "Source has no URL(s) configured\n"
                    continue
                
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
                folder = entry.get("folder", "")
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
                folder = entry.get("folder", "")
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
