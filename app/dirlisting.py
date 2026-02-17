import os
import time
import pickle
import threading
from pathlib import Path
from filetypes import get_filetype_maps
from pathutils import find_software_archive_entry
from zippath import listdir as zippath_listdir, exists as zippath_exists, isfile as zippath_isfile
import logging

logger = logging.getLogger("transfs")

# Shared cache file between processes (persistent across container restarts)
CACHE_FILE = "/mnt/filestorefs/.transfs_cache.pkl"
GETATTR_CACHE_FILE = "/mnt/filestorefs/.transfs_getattr_cache.pkl"

# In-memory cache: {path: (mtime, entries_list)}
_dir_cache = {}
_cache_hits = 0
_cache_misses = 0
_cache_loaded = False

# Thread-safe lock for getattr cache (used by FUSE main loop + cache warmer thread)
_getattr_cache_lock = threading.Lock()

# Cache configuration (set via app.yaml and /cache/config endpoint)
_cache_config = {
    "dir_cache_enabled": True,
    "dir_listing_cache_enabled": True,
    "getattr_cache_enabled": True,
    "getattr_cache_save_interval": 5.0,
    "transform_pipeline_cache_enabled": True,
    "transform_output_size_cache_enabled": True,
    "readdir_direntry_cache_enabled": True,
    "readdir_skip_cache_lookup_with_direntry": True,
}

# getattr cache: {path: (dir_mtime, stat_dict)}
_getattr_cache = {}
_getattr_cache_loaded = False
_getattr_cache_dirty = False
_last_getattr_save = time.time()
GETATTR_SAVE_INTERVAL = 5.0  # Save every 5 seconds if dirty

def _load_cache():
    """Load cache from disk.
    
    DISABLED: PKL cache causes staleness issues when configuration changes.
    Only in-memory session cache is used now. Persistent metadata comes from database.
    """
    global _dir_cache, _cache_loaded
    # PKL cache is disabled - always use empty in-memory cache per session
    _dir_cache = {}
    _cache_loaded = True

def _save_cache():
    """Save cache to disk.
    
    DISABLED: PKL cache causes staleness issues when configuration changes.
    Only in-memory session cache is used now. Persistent metadata comes from database.
    """
    # PKL cache is disabled - nothing to save
    pass

def _load_getattr_cache():
    """Load getattr cache from disk."""
    global _getattr_cache, _getattr_cache_loaded
    if not _cache_config.get("getattr_cache_enabled", True):
        _getattr_cache = {}
        _getattr_cache_loaded = True
        return
    if not _getattr_cache_loaded:
        try:
            if os.path.exists(GETATTR_CACHE_FILE):
                with open(GETATTR_CACHE_FILE, 'rb') as f:
                    _getattr_cache = pickle.load(f)
                logger.info(f"Loaded getattr cache with {len(_getattr_cache)} entries from disk")
        except Exception as e:
            logger.warning(f"Failed to load getattr cache: {e}")
            _getattr_cache = {}
        _getattr_cache_loaded = True

def _save_getattr_cache():
    """Save getattr cache to disk."""
    if not _cache_config.get("getattr_cache_enabled", True):
        return
    try:
        with open(GETATTR_CACHE_FILE, 'wb') as f:
            pickle.dump(_getattr_cache, f)
    except Exception as e:
        logger.warning(f"Failed to save getattr cache: {e}")

def cache_getattr(path: str, parent_dir: str, stat_dict: dict):
    """Cache getattr result for a file. Saves periodically to avoid excessive disk I/O."""
    global _getattr_cache_dirty, _last_getattr_save
    if not _cache_config.get("getattr_cache_enabled", True):
        return
    try:
        _load_getattr_cache()
        
        # Use file's own mtime for validation instead of parent dir mtime
        # This prevents cache invalidation when directory is accessed/modified
        # For transforms, this is more stable and only invalidates when source changes
        file_mtime = stat_dict.get('st_mtime', 0)
        
        with _getattr_cache_lock:
            _getattr_cache[path] = (file_mtime, stat_dict)
            _getattr_cache_dirty = True
        
        # Save periodically (every N seconds) instead of after every call
        now = time.time()
        if now - _last_getattr_save >= GETATTR_SAVE_INTERVAL:
            _save_getattr_cache()
            _getattr_cache_dirty = False
            _last_getattr_save = now
    except Exception as e:
        logger.warning(f"Failed to cache getattr: {e}")

def flush_getattr_cache():
    """Flush getattr cache to disk. Call this periodically or after bulk operations."""
    global _getattr_cache_dirty
    if _getattr_cache_dirty:
        with _getattr_cache_lock:
            _save_getattr_cache()
            _getattr_cache_dirty = False

def get_cached_getattr(path: str, parent_dir: str):
    """Get cached getattr result if valid. Validates using file's own mtime."""
    if not _cache_config.get("getattr_cache_enabled", True):
        return None
    try:
        _load_getattr_cache()
        with _getattr_cache_lock:
            result = path in _getattr_cache
            
            if result:
                cached_file_mtime, stat_dict = _getattr_cache[path]
                return stat_dict
    except Exception as e:
        logger.warning(f"GETATTR CACHE ERROR: {path}: {e}")
    return None

def get_cache_status(path: str) -> dict:
    """Get cache status for a given path."""
    if not _cache_config.get("dir_cache_enabled", True):
        return {"cached": False, "disabled": True, "hits": _cache_hits, "misses": _cache_misses}
    _load_cache()
    cache_key = str(path)
    print(f"DEBUG get_cache_status: cache_key='{cache_key}', cache keys={list(_dir_cache.keys())}", flush=True)
    logger.info(f"get_cache_status: checking cache_key='{cache_key}', cache has {len(_dir_cache)} entries: {list(_dir_cache.keys())}")
    if cache_key in _dir_cache:
        cached_mtime, entries = _dir_cache[cache_key]
        return {
            "cached": True,
            "entry_count": len(entries),
            "mtime": cached_mtime,
            "hits": _cache_hits,
            "misses": _cache_misses
        }
    return {"cached": False, "hits": _cache_hits, "misses": _cache_misses}

def clear_cache(path: str = None) -> dict:
    """Clear cache for a specific path or all caches."""
    global _dir_cache
    if not _cache_config.get("dir_cache_enabled", True):
        _dir_cache = {}
        return {"cleared": True, "disabled": True}
    _load_cache()
    if path:
        cache_key = str(path)
        if cache_key in _dir_cache:
            del _dir_cache[cache_key]
            _save_cache()
            return {"cleared": True, "path": path}
        return {"cleared": False, "message": "Path not in cache"}
    else:
        count = len(_dir_cache)
        _dir_cache = {}
        _save_cache()
        return {"cleared": True, "count": count}


def clear_getattr_cache() -> dict:
    """Clear the getattr cache and remove persisted cache file."""
    global _getattr_cache, _getattr_cache_loaded, _getattr_cache_dirty
    _getattr_cache = {}
    _getattr_cache_loaded = True
    _getattr_cache_dirty = False
    try:
        if os.path.exists(GETATTR_CACHE_FILE):
            os.remove(GETATTR_CACHE_FILE)
        return {"cleared": True}
    except Exception as e:
        return {"cleared": False, "error": str(e)}


def clear_all_caches() -> dict:
    """Clear both directory and getattr caches."""
    dir_result = clear_cache(None)
    getattr_result = clear_getattr_cache()
    return {
        "dir_cache": dir_result,
        "getattr_cache": getattr_result,
    }


def get_cache_config() -> dict:
    """Get current cache configuration."""
    return dict(_cache_config)


def set_cache_config(config: dict):
    """Set cache configuration. Used by transfs.py to configure caching behavior."""
    global _cache_config, GETATTR_SAVE_INTERVAL
    _cache_config = dict(_cache_config, **config)
    GETATTR_SAVE_INTERVAL = float(_cache_config.get("getattr_cache_save_interval", GETATTR_SAVE_INTERVAL))
    logger.info(f"Cache configuration set: {_cache_config}")


def get_all_cache_status(path: str | None = None) -> dict:
    """Get comprehensive status for both directory and getattr caches."""
    dir_status = get_cache_status(path) if path else {
        "cached": False,
        "disabled": not _cache_config.get("dir_cache_enabled", True),
        "hits": _cache_hits,
        "misses": _cache_misses,
        "entry_count": len(_dir_cache),
    }
    getattr_status = {
        "enabled": _cache_config.get("getattr_cache_enabled", True),
        "entry_count": len(_getattr_cache),
        "save_interval": GETATTR_SAVE_INTERVAL,
    }
    return {
        "dir_cache": dir_status,
        "getattr_cache": getattr_status,
        "config": get_cache_config(),
    }


def get_cache_info() -> dict:
    """Get detailed cache information for the dashboard."""
    return {
        "dir_cache_entries": len(_dir_cache),
        "getattr_cache_entries": len(_getattr_cache),
        "dir_cache_hits": _cache_hits,
        "dir_cache_misses": _cache_misses,
        "config": get_cache_config(),
    }


def record_fuse_getattr_cache(enabled: bool):
    """Stub function for recording getattr cache operations. Used by transfs.py."""
    pass


def record_fuse_readdir_cache(enabled: bool):
    """Stub function for recording readdir cache operations. Used by transfs.py."""
    pass


def parse_trans_path(config,root,full_path: str) -> list:
    """
    Return directory entries for the given virtual path, using get_source_path for translation.
    Supports dynamic expansion of ...SoftwareArchives... maps, including subfolders and zip logic.
    """
    path = Path(full_path)
    root_parts = Path(root).parts
    lev = len(path.parts) - len(root_parts)

    if lev == 0:
        return list_clients(config)
    if lev == 1:
        return list_systems(config, path, root_parts)
    if lev == 2:
        return list_maps(config, path, root_parts)
    return list_dynamic_or_regular(config, path, root_parts)

def list_clients(config) -> list:
    """List all clients."""
    return [client['name'] for client in config['clients']]

def list_systems(config, path: Path, root_parts: tuple) -> list:
    """List all systems for a client."""
    client_name = path.parts[len(root_parts)]
    client = next((c for c in config['clients'] if c['name'] == client_name), None)
    if not client:
        return []
    # Handle clients that don't have systems defined yet
    if 'systems' not in client:
        return []
    # Return name for filesystem paths (display_name is only for UI)
    return [system['name'] for system in client['systems']]

def list_maps(config, path: Path, root_parts: tuple) -> list:
    """List all maps and dynamic SoftwareArchives for a system."""
    client_name = path.parts[len(root_parts)]
    client = next((c for c in config['clients'] if c['name'] == client_name), None)
    if not client:
        return []
    display_or_actual_name = path.parts[len(root_parts) + 1]
    # Resolve display name to actual system name
    from pathutils import resolve_system_name
    system_name = resolve_system_name(client, display_or_actual_name)
    if not system_name:
        return []
    system = next((s for s in client['systems'] if s['name'] == system_name), None)
    if not system:
        return []
    maps = []
    mapped_names = set()
    # Track top-level virtual directories (e.g., "MMBs" from "MMBs/beeb1_mmb.VHD")
    virtual_dirs = set()
    # Track source directories used by ...SoftwareArchives... (legacy)
    excluded_dirs = set()
    sa_entry = find_software_archive_entry(system)
    if sa_entry:
        source_dir = sa_entry["...SoftwareArchives..."].get("source_dir")
        if source_dir:
            excluded_dirs.add(source_dir)

    for map_entry in system['maps']:
        map_name = list(map_entry.keys())[0]
        # If map_name contains '/', extract the top-level directory
        if '/' in map_name:
            top_dir = map_name.split('/')[0]
            virtual_dirs.add(top_dir)
            mapped_names.add(top_dir)
        else:
            mapped_names.add(map_name)
        if map_name == "...SoftwareArchives...":
            filetypes = map_entry[map_name].get("filetypes", [])
            for filetype in filetypes:
                for ft_name in filetype.keys():
                    maps.append(ft_name)
                    mapped_names.add(ft_name)
        else:
            # Only add top-level entries (not nested paths)
            if '/' not in map_name:
                maps.append(map_name)
    # Add virtual directories
    maps.extend(virtual_dirs)
    # Don't add implicit real files/dirs - only show explicitly mapped items
    # Deduplicate while preserving order
    deduped = []
    seen = set()
    for entry in maps:
        if entry in seen:
            continue
        seen.add(entry)
        deduped.append(entry)
    return deduped

def list_nested_map_entries(config, path: Path, root_parts: tuple, system: dict, parent_path: str) -> list:
    """
    List entries within a virtual directory that contains nested maps.
    E.g., for /MiSTer/BBCMicro/MMBs, list beeb1_mmb.VHD, beeb2_mmb.VHD
    """
    entries = []
    prefix = parent_path + '/'
    for map_entry in system['maps']:
        map_name = list(map_entry.keys())[0]
        if map_name.startswith(prefix):
            # Extract the immediate child name
            remainder = map_name[len(prefix):]
            if '/' in remainder:
                # It's a nested path; add the directory component
                entries.append(remainder.split('/')[0])
            else:
                # It's a direct child file
                entries.append(remainder)
    return sorted(set(entries))

def list_dynamic_or_regular(config, path: Path, root_parts: tuple) -> list:
    """List dynamic SoftwareArchives subfolders and their contents, or regular map subfolders."""
    client_name = path.parts[len(root_parts)]
    client = next((c for c in config['clients'] if c['name'] == client_name), None)
    if not client:
        return []
    display_or_actual_name = path.parts[len(root_parts) + 1]
    # Resolve display name to actual system name
    from pathutils import resolve_system_name
    system_name = resolve_system_name(client, display_or_actual_name)
    if not system_name:
        return []
    system = next((s for s in client['systems'] if s['name'] == system_name), None)
    if not system:
        return []
    map_name = path.parts[len(root_parts) + 2]
    
    # Check if this is a virtual directory containing nested maps
    nested = list_nested_map_entries(config, path, root_parts, system, map_name)
    if nested:
        return nested
    
    from pathutils import find_map_entry, get_map_config, is_query_map
    map_entry = find_map_entry(system, map_name)
    map_config = get_map_config(map_entry)
    if map_config and is_query_map(map_config):
        return list_query_map(config, path, root_parts, system, map_name, map_config)
    sa_entry = find_software_archive_entry(system)
    if sa_entry and is_dynamic_map(config, map_name, sa_entry):
        sa_config = sa_entry.get("...SoftwareArchives...", {})
        db_mode = sa_config.get("db_mode", False)
        extensions = sa_config.get("extensions")
        return list_dynamic_map(
            config, path, root_parts, system, sa_entry, map_name,
            db_mode=db_mode, extensions=extensions
        )
    return list_regular_map(config,path, root_parts, system, map_name)

def list_query_map(config, path: Path, root_parts: tuple, system: dict, map_name: str, map_config: dict) -> list[str]:
    """List files for a query-based map."""
    global _cache_hits, _cache_misses
    t_func_start = time.time()

    query_cfg = map_config.get("query", {})
    extensions = query_cfg.get("extensions", [])
    extension_map = query_cfg.get("extension_map", {}) or {}
    extension_map = {str(k).upper(): str(v).upper() for k, v in extension_map.items()}
    source_dir = query_cfg.get("source_dir", "Software")
    supports_zip = query_cfg.get("supports_zip", True)
    zip_mode = query_cfg.get("zip_mode", "hierarchical")

    cache_key = str(path)
    cache_enabled = _cache_config.get("dir_cache_enabled", True) and _cache_config.get("dir_listing_cache_enabled", True)

    # For cache key mtime, use source directory if it exists
    check_dir = os.path.join(
        config.get("filestore", "/mnt/filestorefs"),
        "Native",
        system["local_base_path"],
        source_dir,
    )

    try:
        current_mtime = os.path.getmtime(check_dir) if os.path.isdir(check_dir) else 0
        if cache_enabled and cache_key in _dir_cache:
            cached_mtime, cached_entries = _dir_cache[cache_key]
            if cached_mtime == current_mtime:
                _cache_hits += 1
                logger.info(f"IN-MEMORY CACHE HIT: {cache_key} (hits={_cache_hits}, misses={_cache_misses})")
                return cached_entries
    except (OSError, PermissionError):
        current_mtime = 0

    if cache_enabled:
        _cache_misses += 1

    # Parts after /<mount>/<client>/<system>/<map_name>/
    subpath = path.parts[len(root_parts) + 3:]

    try:
        from db.queries import query_files_by_system_and_query
        from pathutils import get_system_identifier

        system_id = get_system_identifier(system)
        if not system_id:
            logger.warning(f"Query map requested but system identifier not found for {system.get('name')}")
            return []

        # If navigating within a subpath, fall back to filesystem/zip handling
        if subpath:
            base_dir = os.path.join(
                config.get("filestore", "/mnt/filestorefs"),
                "Native",
                system["local_base_path"],
                source_dir,
            )
            # Check for zip navigation
            zip_idx = next((i for i, part in enumerate(subpath) if part.lower().endswith('.zip')), None)
            if zip_idx is not None and supports_zip and zip_mode != "file":
                zip_name = subpath[zip_idx]
                inner_parts = subpath[zip_idx + 1:]
                zip_path = os.path.join(base_dir, zip_name)
                if not os.path.isfile(zip_path):
                    zip_path = os.path.join(base_dir, "ZIP", zip_name)
                if os.path.isfile(zip_path):
                    target = zip_path if not inner_parts else f"{zip_path}/" + "/".join(inner_parts)
                    try:
                        internal = zippath_listdir(target)
                        return sorted(set(internal))
                    except Exception:
                        return []
            # Regular directory listing
            dir_path = os.path.join(base_dir, *subpath)
            if not os.path.isdir(dir_path):
                return []
            entries = set()
            for entry in os.listdir(dir_path):
                if entry.startswith('.'):
                    continue
                name, ext = os.path.splitext(entry)
                ext = ext[1:].upper() if ext else ""
                if ext and ext in extension_map:
                    virt_ext = extension_map[ext]
                    entries.add(f"{name}.{virt_ext.lower()}")
                else:
                    entries.add(entry)
            return sorted(entries)

        logger.info(f"QUERY MAP: system={system_id}, map={map_name}, extensions={extensions}")
        db_entries = query_files_by_system_and_query(
            system=system_id,
            query=query_cfg,
            system_config=system,
            limit=10000
        )

        if not db_entries:
            t_func_elapsed = time.time() - t_func_start
            logger.info(f"list_query_map END: 0 entries in {t_func_elapsed:.2f}s")
            return []

        entries: set[str] = set()
        zip_entries: list[str] = []
        for entry in db_entries:
            filename = entry.get("filename") if isinstance(entry, dict) else None
            if not filename:
                filename = entry[0] if isinstance(entry, (tuple, list)) else str(entry)
            if filename.lower().endswith('.zip'):
                zip_entries.append(filename)
                if zip_mode == "file" or not supports_zip:
                    entries.add(filename)
                elif zip_mode == "hierarchical":
                    entries.add(filename)
                continue
            name, ext = os.path.splitext(filename)
            ext = ext[1:].upper() if ext else ""
            if ext and ext in extension_map:
                virt_ext = extension_map[ext]
                entries.add(f"{name}.{virt_ext.lower()}")
            else:
                entries.add(filename)

        if zip_mode == "flatten" and supports_zip and zip_entries:
            base_dir = os.path.join(
                config.get("filestore", "/mnt/filestorefs"),
                "Native",
                system["local_base_path"],
                source_dir,
            )
            for zip_name in zip_entries:
                zip_path = os.path.join(base_dir, zip_name)
                if not os.path.isfile(zip_path):
                    zip_path = os.path.join(base_dir, "ZIP", zip_name)
                if os.path.isfile(zip_path):
                    try:
                        internal = zippath_listdir(zip_path)
                        for child in internal:
                            entries.add(child)
                    except Exception:
                        continue

        entries_list = sorted(entries)

        if cache_enabled:
            try:
                _dir_cache[cache_key] = (current_mtime, entries_list)
            except Exception:
                pass

        t_func_elapsed = time.time() - t_func_start
        logger.info(f"list_query_map END: returned {len(entries_list)} entries in {t_func_elapsed:.2f}s")
        return entries_list
    except Exception as e:
        logger.error(f"Query map failed: {e}", exc_info=True)
        return []

def is_dynamic_map(config, map_name: str, sa_entry: dict) -> bool:
    """Check if the map is a dynamic ...SoftwareArchives... map."""
    filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
    for filetype in filetypes:
        if map_name in filetype:
            return True
    return False

def list_dynamic_map(
    config, path: Path, root_parts: tuple, system: dict, sa_entry: dict, map_name: str,
    db_mode: bool = False, extensions: list = None
) -> list[str]:
    """
    List files and directories for a dynamic ...SoftwareArchives... map.
    
    Supports two modes:
    
    1. YAML-driven (db_mode=False, default):
       - Uses filetypes from clients.yaml configuration
       - Scans extension folders on disk
       - Handles zip_mode (hierarchical, flatten, file)
       - Backward compatible with existing behavior
       
    2. Database-driven (db_mode=True):
       - Uses database queries for file discovery
       - Requires pre-computed extensions list or system field in database
       - Optimal for flat layout systems
       - Avoids expensive folder scans
    
    Args:
        config: Configuration object with filestore path
        path: Virtual path being listed
        root_parts: Tuple of path parts up to mount point
        system: System configuration dict
        sa_entry: Software archives entry from config
        map_name: Name of the map (e.g., "ROMs", "FDs")
        db_mode: If True, use database queries; if False, use folder scanning (default)
        extensions: Pre-computed extensions list for db_mode (e.g., ["ROM", "BIN"])
    
    Returns:
        List of entries (filenames and directories) at the given virtual path
    
    zip_mode options (folder-based only):
      - hierarchical (default): ZIPs appear as navigable directories
      - flatten: ZIPs are transparent, contents merged into parent listing
      - file: ZIPs appear as opaque files, not navigable
      
    Caching: Results cached in-memory based on source directory mtime.
    """
    global _cache_hits, _cache_misses
    t_func_start = time.time()
    
    filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
    supports_zip = sa_entry["...SoftwareArchives..."].get("supports_zip", True)
    zip_mode = sa_entry["...SoftwareArchives..."].get("zip_mode", "hierarchical")
    source_dir = os.path.join(
        config["filestore"],
        "Native",
        system["local_base_path"],
        sa_entry["...SoftwareArchives..."]["source_dir"]
    )
    filetype_map, reverse_map = get_filetype_maps(sa_entry)
    real_exts = filetype_map.get(map_name.upper(), [])
    logger.info(f"DEBUG filetype_map for {map_name}: filetype_map={filetype_map}, real_exts={real_exts}")
    # Parts after /<mount>/<client>/<system>/<map_name>/
    subpath = path.parts[len(root_parts) + 3:]
    
    # Cache key: full path string (persistent cache disabled, in-memory only)
    cache_key = str(path)
    
    # In-memory session cache only (no persistent PKL cache)
    cache_enabled = _cache_config.get("dir_cache_enabled", True) and _cache_config.get("dir_listing_cache_enabled", True)

    # Get directory mtime for in-memory cache validity check
    check_dir = source_dir
    
    try:
        current_mtime = os.path.getmtime(check_dir) if os.path.isdir(check_dir) else 0
        
        # Check in-memory cache (session-scoped, cleared on restart)
        if cache_enabled and cache_key in _dir_cache:
            cached_mtime, cached_entries = _dir_cache[cache_key]
            if cached_mtime == current_mtime:
                _cache_hits += 1
                logger.info(f"IN-MEMORY CACHE HIT: {cache_key} (hits={_cache_hits}, misses={_cache_misses})")
                return cached_entries
    except (OSError, PermissionError):
        current_mtime = 0
    
    if cache_enabled:
        _cache_misses += 1
    
    # ========== DATABASE-DRIVEN MODE (Phase 2) ==========
    if db_mode:
        """Query database for files instead of scanning folders."""
        try:
            from db.queries import query_files_by_system_and_extensions
            from pathutils import get_system_identifier
            
            # Get system identifier for database lookup
            system_info = get_system_identifier(system)
            if not system_info:
                logger.warning(f"Database mode requested but system identifier not found for {system.get('name')}")
                # Fall back to folder-based mode
                db_mode = False
            else:
                # Determine extensions to query
                if extensions is None:
                    # Use filetypes from config as fallback
                    filetype_map, reverse_map = get_filetype_maps(sa_entry)
                    extensions = filetype_map.get(map_name.upper(), [])
                
                if not extensions:
                    logger.info(f"No extensions configured for {map_name}, returning empty listing")
                    t_func_elapsed = time.time() - t_func_start
                    logger.info(f"list_dynamic_map END: database mode, 0 entries in {t_func_elapsed:.2f}s")
                    return []
                
                # Query database for files
                logger.info(f"DATABASE MODE: querying {system_info} for extensions {extensions}")
                db_entries = query_files_by_system_and_extensions(
                    system=system_info,
                    extensions=extensions,
                    limit=10000  # Reasonable limit for listings
                )
                
                if not db_entries:
                    logger.info(f"Database query returned no results for {system_info} with {extensions}")
                    t_func_elapsed = time.time() - t_func_start
                    logger.info(f"list_dynamic_map END: database mode, 0 entries in {t_func_elapsed:.2f}s")
                    return []
                
                # Extract unique filenames from database results
                entries: set[str] = set()
                for entry in db_entries:
                    # Entry is a dict with 'filename' key
                    if isinstance(entry, dict) and 'filename' in entry:
                        entries.add(entry['filename'])
                    else:
                        # Handle tuples or direct filenames
                        filename = entry[0] if isinstance(entry, (tuple, list)) else str(entry)
                        entries.add(filename)
                
                entries_list = sorted(entries)
                
                # Log result
                t_func_elapsed = time.time() - t_func_start
                logger.info(f"list_dynamic_map END: database mode, returned {len(entries)} entries in {t_func_elapsed:.2f}s")
                
                # Cache result
                if cache_enabled:
                    try:
                        # For database mode, use current time as mtime (stable, database-backed)
                        db_mtime = int(time.time())
                        _dir_cache[cache_key] = (db_mtime, entries_list)
                    except Exception:
                        pass
                
                return entries_list
        
        except ImportError as e:
            logger.warning(f"Database mode requested but db.queries module not available: {e}. Falling back to folder-based.")
            db_mode = False
        except Exception as e:
            logger.error(f"Database mode failed: {e}. Falling back to folder-based.", exc_info=True)
            db_mode = False
    
    # ========== YAML-DRIVEN MODE (Default) ==========
    logger.info(f"list_dynamic_map START: path={path}, subpath={subpath}, source_dir={source_dir}, zip_mode={zip_mode}, real_exts={real_exts} (cache miss)")
    
    entries: set[str] = set()

    # Explicit YAML 'files' entries
    for file_spec in sa_entry["...SoftwareArchives..."].get("files", []):
        items = []
        if isinstance(file_spec, dict):
            for k, v in file_spec.items():
                if k == map_name:
                    items.extend(v if isinstance(v, list) else [v])
                else:
                    items.extend(v if isinstance(v, list) else [v])
        elif isinstance(file_spec, str):
            items.append(file_spec)
        for item in items:
            try:
                base = os.path.basename(item)
                name, ext = os.path.splitext(base)
                if ext:
                    ext_no = ext[1:]
                    matched = False
                    for real_ext in real_exts:
                        if ext_no.upper() == real_ext.upper():
                            virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                            entries.add(f"{name}.{virt_ext.lower()}")
                            matched = True
                            break
                    if not matched:
                        entries.add(base)
                else:
                    entries.add(base)
            except Exception:
                continue

    # Flattening control (legacy behavior, deprecated in favor of zip_mode)
    flatten_enabled = os.getenv("TRANSFS_FLATTEN_ZIPS", "1") != "0"
    try:
        auto_limit = int(os.getenv("TRANSFS_FLATTEN_ZIPS_AUTO_LIMIT", "0"))
    except ValueError:
        auto_limit = 0

    logger.info(f"LOOP START: real_exts={real_exts}, len={len(real_exts)}")
    for real_ext in real_exts:
        logger.info(f"LOOP ITERATION: real_ext={real_ext}")
        # Resolve extension directory case-insensitively (e.g., 2mg vs 2MG)
        ext_dir_name = real_ext
        for candidate in (real_ext, real_ext.lower(), real_ext.upper()):
            if os.path.isdir(os.path.join(source_dir, candidate)):
                ext_dir_name = candidate
                break
        # Detect zip context first to know where to stop building dir_path
        in_zip = False
        zip_path = ""
        zip_inner = ""
        zip_index = -1  # index in subpath where the .zip file is
        
        if subpath:
            cumulative = []
            for i, part in enumerate(subpath):
                cumulative.append(part)
                if part.lower().endswith(".zip"):
                    # Check both real_ext and map_name folders
                    candidate1 = os.path.join(source_dir, ext_dir_name, *cumulative)
                    candidate2 = os.path.join(source_dir, map_name, *cumulative)
                    
                    if os.path.isfile(candidate1):
                        in_zip = True
                        zip_path = candidate1
                        zip_index = i
                        inner_parts = subpath[i + 1:]
                        if inner_parts:
                            zip_inner = "/".join(inner_parts).strip("/")
                        break
                    elif os.path.isfile(candidate2):
                        in_zip = True
                        zip_path = candidate2
                        zip_index = i
                        inner_parts = subpath[i + 1:]
                        if inner_parts:
                            zip_inner = "/".join(inner_parts).strip("/")
                        break
        
        # If we're inside a ZIP, we don't need to check dir_path existence
        # Otherwise, build dir_path and apply fallback logic
        if not in_zip:
            # Use all of subpath to build the directory path we're listing
            path_components = subpath if subpath else []
            dir_path = os.path.join(source_dir, ext_dir_name, *path_components)
            actual_folder = ext_dir_name
            
            logger.info(f"DEBUG list_dynamic_map: subpath={subpath}, path_components={path_components}, dir_path={dir_path}")
            
            # If extension folder doesn't exist, try map_name as folder
            if not os.path.isdir(dir_path):
                alt_dir_path = os.path.join(source_dir, map_name, *path_components)
                if os.path.isdir(alt_dir_path):
                    dir_path = alt_dir_path
                    actual_folder = map_name
            
            if not os.path.isdir(dir_path):
                continue
        else:
            # For ZIP-internal paths, set actual_folder based on which candidate matched
            if zip_path.startswith(os.path.join(source_dir, ext_dir_name)):
                actual_folder = ext_dir_name
            else:
                actual_folder = map_name
            dir_path = os.path.dirname(zip_path)

        # ========== HIERARCHICAL MODE (default) ==========
        if zip_mode == "hierarchical":
            # Root level: subpath empty → list only immediate dirs and zip containers
            if not subpath:
                logger.info(f"HIER ROOT: real_ext={real_ext}, dir_path={dir_path}, listdir_path will be={dir_path}")
                t_start = time.time()
                listdir_path = dir_path  # Use the resolved dir_path (may be fallback folder)
                dir_entries = [e for e in os.listdir(listdir_path) if not e.startswith('.')]
                logger.info(f"HIER ROOT: listdir returned {len(dir_entries)} entries from {listdir_path}")
                t_listdir = time.time() - t_start
                if t_listdir > 0.5:
                    logger.warning(f"SLOW os.listdir({listdir_path}) took {t_listdir:.2f}s for {len(dir_entries)} entries")
                
                for entry in dir_entries:
                    entry_path = os.path.join(listdir_path, entry)
                    if os.path.isdir(entry_path):
                        entries.add(entry)
                    elif entry.lower().endswith(".zip") and supports_zip:
                        entries.add(entry)
                    elif entry.lower().endswith(".zip") and not supports_zip:
                        # Treat as regular file with extension mapping
                        name, ext = os.path.splitext(entry)
                        if ext[1:].upper() == real_ext.upper():
                            virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                            entries.add(f"{name}.{virt_ext.lower()}")
                    else:
                        name, ext = os.path.splitext(entry)
                        if ext[1:].upper() == real_ext.upper():
                            virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                            entries.add(f"{name}.{virt_ext.lower()}")
                continue

            # Inside a zip (possibly with inner path)
            if in_zip and supports_zip:
                try:
                    target = zip_path if not zip_inner else f"{zip_path}/{zip_inner}"
                    logger.debug(f"ZIPPATH_LISTDIR: target={target}, zip_path={zip_path}, zip_inner={zip_inner}")
                    internal = zippath_listdir(target)
                    logger.debug(f"ZIPPATH_LISTDIR result: {internal[:10] if len(internal) > 10 else internal}")
                except Exception as e:
                    logger.error(f"ZIPPATH_LISTDIR failed: {e}", exc_info=True)
                    internal = []
                for child in internal:
                    # Inside a ZIP, show all contents regardless of extension filtering
                    # Extension filtering only applies at the root to determine which ZIPs to show
                    entries.add(child)
                continue

            # Deeper real filesystem path but not inside a zip: list dirs, zip containers, mapped files
            t_start = time.time()
            try:
                full_dir_path = dir_path
                # Use os.scandir() instead of os.listdir() for better performance
                # scandir returns DirEntry objects that cache stat results
                with os.scandir(full_dir_path) as entries_iter:
                    dir_entries = [(e.name, e.is_dir()) for e in entries_iter if not e.name.startswith('.')]
                t_listdir = time.time() - t_start
                if t_listdir > 0.5:
                    logger.warning(f"SLOW os.scandir({full_dir_path}) took {t_listdir:.2f}s for {len(dir_entries)} entries")
            except Exception:
                continue
            
            t_process = time.time()
            for entry_name, is_directory in dir_entries:
                if is_directory:
                    entries.add(entry_name)
                    logger.debug(f"Added DIR: {entry_name}")
                elif entry_name.lower().endswith(".zip") and supports_zip:
                    entries.add(entry_name)
                    logger.debug(f"Added ZIP: {entry_name}")
                elif entry_name.lower().endswith(".zip") and not supports_zip:
                    # Treat as regular file
                    name, ext = os.path.splitext(entry_name)
                    if ext[1:].upper() == real_ext.upper():
                        virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                        entries.add(f"{name}.{virt_ext.lower()}")
                        logger.debug(f"Added ZIP-treated-as-file: {name}.{virt_ext.lower()}")
                else:
                    name, ext = os.path.splitext(entry_name)
                    if ext[1:].upper() == real_ext.upper():
                        virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                        entries.add(f"{name}.{virt_ext.lower()}")
                        logger.debug(f"Added FILE {real_ext}: {name}.{virt_ext.lower()}")
            t_process_elapsed = time.time() - t_process
            if t_process_elapsed > 0.5:
                logger.warning(f"SLOW entry processing took {t_process_elapsed:.2f}s for {len(dir_entries)} entries")

        # ========== FILE MODE ==========
        elif zip_mode == "file":
            # ZIPs are opaque files, never navigable
            if not subpath:
                # Use os.scandir for efficiency (avoids 3500+ stat calls)
                scan_path = os.path.join(source_dir, ext_dir_name)
                t_scan_start = time.time()
                logger.info(f"FILE MODE scanning: {scan_path}")
                try:
                    with os.scandir(scan_path) as it:
                        for entry in it:
                            if entry.name.startswith('.'):
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                entries.add(entry.name)
                            else:
                                # All files treated as files (including .zip)
                                name, ext = os.path.splitext(entry.name)
                                if ext and ext[1:].upper() == real_ext.upper():
                                    virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                                    entries.add(f"{name}.{virt_ext.lower()}")
                                elif entry.name.lower().endswith(".zip"):
                                    # Map .zip extension too
                                    entries.add(entry.name)
                    t_scan_elapsed = time.time() - t_scan_start
                    logger.info(f"FILE MODE scan completed: {scan_path} took {t_scan_elapsed:.2f}s, found {len(entries)} entries")
                except Exception as e:
                    logger.error(f"FILE MODE scan failed: {scan_path}, error: {e}")
                    pass
                continue

            # Deeper paths: never enter ZIPs, only list real filesystem
            try:
                dir_entries = [e for e in os.listdir(dir_path) if not e.startswith('.')]
            except Exception:
                continue
            for entry in dir_entries:
                entry_path = os.path.join(dir_path, entry)
                if os.path.isdir(entry_path):
                    entries.add(entry)
                else:
                    name, ext = os.path.splitext(entry)
                    if ext[1:].upper() == real_ext.upper():
                        virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                        entries.add(f"{name}.{virt_ext.lower()}")
                    elif entry.lower().endswith(".zip"):
                        entries.add(entry)

        # ========== FLATTEN MODE (legacy, expensive) ==========
        elif zip_mode == "flatten":
            # Merge ZIP contents into parent directory listing (performance warning)
            if not subpath:
                dir_entries = [e for e in os.listdir(os.path.join(source_dir, ext_dir_name)) if not e.startswith('.')]
                for entry in dir_entries:
                    entry_path = os.path.join(source_dir, ext_dir_name, entry)
                    if os.path.isdir(entry_path):
                        entries.add(entry)
                    elif entry.lower().endswith(".zip") and supports_zip and flatten_enabled:
                        # Flatten: enumerate ZIP contents at this level
                        try:
                            internal = zippath_listdir(entry_path)
                            for child in internal:
                                if child.upper().endswith(f".{real_ext.upper()}"):
                                    name, ext = os.path.splitext(child)
                                    virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                                    entries.add(f"{name}.{virt_ext.lower()}")
                        except Exception:
                            pass  # Skip problematic ZIPs
                    else:
                        name, ext = os.path.splitext(entry)
                        if ext[1:].upper() == real_ext.upper():
                            virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                            entries.add(f"{name}.{virt_ext.lower()}")
                continue

            # Deeper paths in flatten mode: treat as hierarchical (no change)
            if in_zip and supports_zip:
                try:
                    target = zip_path if not zip_inner else f"{zip_path}/{zip_inner}"
                    internal = zippath_listdir(target)
                except Exception:
                    internal = []
                for child in internal:
                    if child.upper().endswith(f".{real_ext.upper()}"):
                        name, ext = os.path.splitext(child)
                        virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                        entries.add(f"{name}.{virt_ext.lower()}")
                    else:
                        if '.' not in child:
                            entries.add(child)
                continue

            try:
                dir_entries = [e for e in os.listdir(dir_path) if not e.startswith('.')]
            except Exception:
                continue
            for entry in dir_entries:
                entry_path = os.path.join(dir_path, entry)
                if os.path.isdir(entry_path):
                    entries.add(entry)
                elif entry.lower().endswith(".zip") and supports_zip:
                    entries.add(entry)
                else:
                    name, ext = os.path.splitext(entry)
                    if ext[1:].upper() == real_ext.upper():
                        virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                        entries.add(f"{name}.{virt_ext.lower()}")

    t_func_elapsed = time.time() - t_func_start
    entries_list = sorted(entries)
    
    # Cache result in memory for this session (no persistent PKL cache)
    if cache_enabled:
        try:
            _dir_cache[cache_key] = (current_mtime, entries_list)
            logger.info(f"IN-MEMORY CACHED: {cache_key} with mtime={current_mtime}")
        except Exception:  # pylint: disable=broad-except
            pass
    
    logger.info(f"list_dynamic_map END: returned {len(entries)} entries in {t_func_elapsed:.2f}s for path={path}")
    if t_func_elapsed > 1.0:
        logger.warning(f"SLOW list_dynamic_map() took {t_func_elapsed:.2f}s, returned {len(entries)} entries at path={path}")
    return entries_list

def list_regular_map(config, path: Path, root_parts: tuple, system: dict, map_name: str) -> list:
    """List contents of a regular map subfolder."""
    map_entry = next((m for m in system['maps'] if list(m.keys())[0] == map_name), None)
    if not map_entry:
        return []
    mapdict = map_entry[map_name]
    if "source_dir" in mapdict:
        base = os.path.join(
            config.get("filestore", "/mnt/filestorefs"),
            "Native",
            system['local_base_path'],
            mapdict["source_dir"]
        )
        subpath = path.parts[len(root_parts) + 3:]
        dir_path = os.path.join(base, *subpath)
        if os.path.isdir(dir_path):
            return sorted(os.listdir(dir_path))
    return []

def is_virtual_directory(config, full_path: str, mountpoint: str) -> bool:
    """
    Return True if 'full_path' should be treated as a synthetic directory in the virtual FS.
    Uses existing parse_trans_path to decide: if listing it yields entries, it is a dir.
    """
    try:
        entries = parse_trans_path(config, mountpoint, full_path)
        return isinstance(entries, list)
    except Exception:
        return False
