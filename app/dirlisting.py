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


def _get_subdirectories_from_db(mount_path: str, virtual_prefix: str) -> list:
    """
    Query database to discover subdirectories under a given virtual path prefix.
    
    Args:
        mount_path: Mount point path (e.g., "/mnt/transfs")
        virtual_prefix: Virtual path prefix to search under (e.g., "RetroBat/ROMS/AcornAtom")
    
    Returns:
        List of unique subdirectory names at the next level
    """
    try:
        from db.connection import get_cursor, init_database
        from db import get_connection
        
        # Initialize database connection if needed
        try:
            conn = get_connection()
            if conn is None:
                init_database()
        except:
            init_database()
        
        # Build the full path prefix, ensuring it ends with /
        if virtual_prefix.startswith('/'):
            full_prefix = virtual_prefix
        else:
            full_prefix = os.path.join(mount_path, virtual_prefix)
        
        if not full_prefix.endswith('/'):
            full_prefix += '/'
        
        # Calculate the position to extract from (after the prefix)
        extract_from_pos = len(full_prefix) + 1  # +1 for 1-based PostgreSQL indexing
        
        # Query for unique next-level components
        # For paths like /mnt/transfs/RetroBat/ROMS/AcornAtom/FDs/file.dsk
        # When querying /mnt/transfs/RetroBat/ROMS/AcornAtom/, extract "FDs"
        sql = """
            SELECT DISTINCT 
                SPLIT_PART(
                    SUBSTRING(virtual_path FROM %s),
                    '/',
                    1
                ) AS subdir
            FROM files
            WHERE virtual_path LIKE %s
                AND LENGTH(SUBSTRING(virtual_path FROM %s)) > 0
                AND virtual_path <> %s
        """
        
        params = [
            extract_from_pos,       # Extract substring starting after prefix
            full_prefix + '%',      # Match paths under prefix
            extract_from_pos,       # Same as first param
            full_prefix.rstrip('/') # Exclude the directory itself
        ]
        
        with get_cursor(commit=False) as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()
        
        subdirs = [row['subdir'] for row in rows if row['subdir'] and row['subdir'].strip()]
        logger.debug(f"Found {len(subdirs)} subdirectories under {full_prefix}: {subdirs}")
        return subdirs
    
    except Exception as e:
        logger.error(f"Error querying subdirectories from database for {virtual_prefix}: {e}")
        return []


def _adjust_source_dir_for_layout(source_dir: str, system_info: dict) -> str:
    layout = system_info.get("download_layout") if system_info else None
    if layout != "source_based":
        return source_dir
    normalized = (source_dir or "").replace("\\", "/").strip("/").lower()
    if "sources" in normalized:
        return source_dir
    if "bios" in normalized.split("/"):
        return source_dir
    return os.path.join(source_dir, "Sources")


def _find_file_recursive(base_dir: str, filename: str) -> str | None:
    if not os.path.isdir(base_dir):
        return None
    for root, _, files in os.walk(base_dir):
        if filename in files:
            return os.path.join(root, filename)
    return None

# Stat cache file (persistent across container restarts)
STAT_CACHE_FILE = "/mnt/filestorefs/.transfs_stat_cache.pkl"

# In-memory cache: {path: (mtime, entries_list)}
_dir_cache = {}
_cache_hits = 0
_cache_misses = 0
_cache_loaded = False

# Thread-safe lock for stat cache (used by FUSE main loop + cache warmer thread)
_stat_cache_lock = threading.Lock()

# Cache configuration (set via app.yaml and /cache/config endpoint)
_cache_config = {
    "stat_cache_enabled": True,
    "stat_cache_save_interval": 5.0,
    "transform_pipeline_cache_enabled": True,
    "transform_output_size_cache_enabled": True,
    "readdir_direntry_cache_enabled": True,
    "readdir_skip_cache_lookup_with_direntry": True,
}

# Stat cache: {path: (dir_mtime, stat_dict)}
_stat_cache = {}
_stat_cache_loaded = False
_stat_cache_dirty = False
_last_stat_save = time.time()
STAT_SAVE_INTERVAL = 5.0  # Save every 5 seconds if dirty

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

def _load_stat_cache():
    """Load stat cache from disk."""
    global _stat_cache, _stat_cache_loaded
    if not _cache_config.get("stat_cache_enabled", True):
        _stat_cache = {}
        _stat_cache_loaded = True
        return
    if not _stat_cache_loaded:
        try:
            if os.path.exists(STAT_CACHE_FILE):
                with open(STAT_CACHE_FILE, 'rb') as f:
                    _stat_cache = pickle.load(f)
                logger.info(f"Loaded stat cache with {len(_stat_cache)} entries from disk")
        except Exception as e:
            logger.warning(f"Failed to load stat cache: {e}")
            _stat_cache = {}
        _stat_cache_loaded = True

def _save_stat_cache():
    """Save stat cache to disk."""
    if not _cache_config.get("stat_cache_enabled", True):
        return
    try:
        with open(STAT_CACHE_FILE, 'wb') as f:
            pickle.dump(_stat_cache, f)
    except Exception as e:
        logger.warning(f"Failed to save stat cache: {e}")

def cache_stat(path: str, parent_dir: str, stat_dict: dict):
    """Cache stat result for a file. Saves periodically to avoid excessive disk I/O."""
    global _stat_cache_dirty, _last_stat_save
    if not _cache_config.get("stat_cache_enabled", True):
        return
    try:
        _load_stat_cache()
        
        # Use file's own mtime for validation instead of parent dir mtime
        # This prevents cache invalidation when directory is accessed/modified
        # For transforms, this is more stable and only invalidates when source changes
        file_mtime = stat_dict.get('st_mtime', 0)
        
        with _stat_cache_lock:
            _stat_cache[path] = (file_mtime, stat_dict)
            _stat_cache_dirty = True
        
        # Save periodically (every N seconds) instead of after every call
        now = time.time()
        if now - _last_stat_save >= STAT_SAVE_INTERVAL:
            _save_stat_cache()
            _stat_cache_dirty = False
            _last_stat_save = now
    except Exception as e:
        logger.warning(f"Failed to cache stat: {e}")

def flush_stat_cache():
    """Flush stat cache to disk. Call this periodically or after bulk operations."""
    global _stat_cache_dirty
    if _stat_cache_dirty:
        with _stat_cache_lock:
            _save_stat_cache()
            _stat_cache_dirty = False

def get_cached_stat(path: str, parent_dir: str):
    """Get cached stat result if valid. Validates using file's own mtime."""
    if not _cache_config.get("stat_cache_enabled", True):
        return None
    try:
        _load_stat_cache()
        with _stat_cache_lock:
            result = path in _stat_cache
            
            if result:
                cached_file_mtime, stat_dict = _stat_cache[path]
                return stat_dict
    except Exception as e:
        logger.warning(f"STAT CACHE ERROR: {path}: {e}")
    return None

def clear_stat_cache() -> dict:
    """Clear the stat cache and remove persisted cache file."""
    global _stat_cache, _stat_cache_loaded, _stat_cache_dirty
    _stat_cache = {}
    _stat_cache_loaded = True
    _stat_cache_dirty = False
    try:
        if os.path.exists(STAT_CACHE_FILE):
            os.remove(STAT_CACHE_FILE)
        return {"cleared": True}
    except Exception as e:
        return {"cleared": False, "error": str(e)}


def clear_stat_cache_path(path: str) -> dict:
    """Clear stat cache entries under a specific path."""
    if not path:
        return clear_stat_cache()
    _load_stat_cache()
    removed = 0
    with _stat_cache_lock:
        for key in list(_stat_cache.keys()):
            if key.startswith(path):
                del _stat_cache[key]
                removed += 1
        if removed:
            _save_stat_cache()
    return {"cleared": True, "path": path, "removed": removed}


def clear_all_caches() -> dict:
    """Clear all caches (stat cache only - dir caches are disabled)."""
    stat_result = clear_stat_cache()
    return {
        "stat_cache": stat_result,
    }


def get_cache_config() -> dict:
    """Get current cache configuration."""
    return dict(_cache_config)


def set_cache_config(config: dict):
    """Set cache configuration. Used by transfs.py to configure caching behavior."""
    global _cache_config, STAT_SAVE_INTERVAL
    # Backward compatibility: map legacy getattr cache keys to stat cache keys
    legacy_map = {
        "getattr_cache_enabled": "stat_cache_enabled",
        "getattr_cache_save_interval": "stat_cache_save_interval",
    }
    for legacy_key, new_key in legacy_map.items():
        if legacy_key in config and new_key not in config:
            config[new_key] = config[legacy_key]

    _cache_config = dict(_cache_config, **config)
    STAT_SAVE_INTERVAL = float(_cache_config.get("stat_cache_save_interval", STAT_SAVE_INTERVAL))
    logger.info(f"Cache configuration set: {_cache_config}")


def get_all_cache_status(path: str | None = None) -> dict:
    """Get comprehensive status for stat cache."""
    _load_stat_cache()
    path_count = 0
    if path:
        path_count = sum(1 for key in _stat_cache.keys() if key.startswith(path))
    stat_status = {
        "enabled": _cache_config.get("stat_cache_enabled", True),
        "entry_count": len(_stat_cache),
        "save_interval": _cache_config.get("stat_cache_save_interval", STAT_SAVE_INTERVAL),
        "dirty": _stat_cache_dirty,
        "path_cached": path_count > 0,
        "path_entry_count": path_count,
    }

    return {
        "stat_cache": stat_status,
        "cache_config": _cache_config,
    }


def get_cache_info() -> dict:
    """Get detailed cache information for the dashboard."""
    _load_stat_cache()

    # Get ZIP index cache stats from zippath module
    try:
        from zippath import get_zip_cache_stats
        zip_stats = get_zip_cache_stats()
    except Exception:
        zip_stats = {"entries": 0, "error": "Failed to load ZIP cache stats"}

    return {
        "stat_cache": {
            "enabled": _cache_config.get("stat_cache_enabled", True),
            "entries": len(_stat_cache),
            "save_interval": _cache_config.get("stat_cache_save_interval", STAT_SAVE_INTERVAL),
            "dirty": _stat_cache_dirty,
            "file": STAT_CACHE_FILE,
        },
        "zip_index_cache": zip_stats,
        "transform_caches": {
            "pipeline_enabled": _cache_config.get("transform_pipeline_cache_enabled", True),
            "output_size_enabled": _cache_config.get("transform_output_size_cache_enabled", True),
        },
        "readdir_optimizations": {
            "direntry_cache_enabled": _cache_config.get("readdir_direntry_cache_enabled", True),
            "skip_lookup_with_direntry": _cache_config.get("readdir_skip_cache_lookup_with_direntry", True),
        },
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
    Handles variable-depth hierarchies with category paths.
    """
    from pathutils import get_system_info
    
    path = Path(full_path)
    root_parts = Path(root).parts
    lev = len(path.parts) - len(root_parts)

    # Level 0: List clients
    if lev == 0:
        return list_clients(config)
    
    # Level 1+: Could be systems, categories, or maps depending on configuration
    client_name = path.parts[len(root_parts)]
    client = next((c for c in config.get('clients', []) if c['name'] == client_name), None)
    if not client:
        return []
    
    # Level 1: List systems/categories under client
    if lev == 1:
        return list_systems(config, path, root_parts)
    
    # Level 2+: Could be system, category+system, or maps
    # Try to find system at any position in the path
    rel_path_parts = path.parts[len(root_parts):]
    system_info = get_system_info(client, rel_path_parts)
    
    if system_info:
        # Found a system - determine if we're AT the system level or deeper
        system_name = system_info['name']
        # Find where the system name appears in the path
        try:
            system_idx = rel_path_parts.index(system_name)
            # If we're exactly at the system level, list maps
            if len(rel_path_parts) == system_idx + 1:
                return list_maps(config, path, root_parts)
            # If we're deeper, use the dynamic listing
            else:
                return list_dynamic_or_regular(config, path, root_parts)
        except ValueError:
            pass
    
    # Not at system level - might be at category level
    # Check if this is a client-level nested map directory
    potential_map_name = path.parts[len(root_parts) + 1] if lev >= 2 else None
    if potential_map_name:
        client_maps = client.get('maps', [])
        is_client_nested_map = any(
            list(m.keys())[0].startswith(potential_map_name + '/')
            for m in client_maps
        )
        if is_client_nested_map:
            return list_client_nested_map_entries(config, client, potential_map_name)
    
    # At category level (e.g., /RetroBat/ROMS/) - list systems with those categories
    # Query database to find subdirectories
    mount_path = config.get('mount_path', '/mnt/transfs')
    rel_path = '/'.join(rel_path_parts)
    db_subdirs = _get_subdirectories_from_db(mount_path, rel_path)
    if db_subdirs:
        return db_subdirs
    
    # Fallback to dynamic listing
    return list_dynamic_or_regular(config, path, root_parts)

def list_clients(config) -> list:
    """List all clients."""
    return [client['name'] for client in config['clients']]

def list_systems(config, path: Path, root_parts: tuple) -> list:
    """List all systems for a client, plus any client-level maps and category directories."""
    client_name = path.parts[len(root_parts)]
    client = next((c for c in config['clients'] if c['name'] == client_name), None)
    if not client:
        return []
    
    result = []
    seen = set()
    
    # Add client-level maps (e.g., bios/atom.zip)
    # For nested maps, only show the top-level directory (e.g., 'bios' from 'bios/atom.zip')
    client_maps = client.get('maps', [])
    for map_entry in client_maps:
        map_name = list(map_entry.keys())[0]
        # Extract the first component (e.g., 'bios' from 'bios/atom.zip')
        top_level = map_name.split('/')[0]
        if top_level not in seen:
            result.append(top_level)
            seen.add(top_level)
    
    # Query database to discover actual directory structure (handles category paths)
    mount_path = config.get('mount_path', '/mnt/transfs')
    db_subdirs = _get_subdirectories_from_db(mount_path, client_name)
    
    # Add database-discovered directories (categories like ROMS, BIOS, or systems)
    for subdir in db_subdirs:
        if subdir not in seen:
            result.append(subdir)
            seen.add(subdir)
    
    # Also add configured systems (in case database is empty or incomplete)
    if 'systems' in client:
        for system in client['systems']:
            system_name = system['name']
            if system_name not in seen:
                result.append(system_name)
                seen.add(system_name)
    
    return result

def list_maps(config, path: Path, root_parts: tuple) -> list:
    """List all maps and dynamic SoftwareArchives for a system."""
    from pathutils import resolve_system_name, is_flatten_map, is_parent_level_map, normalize_map_name, get_system_info
    
    client_name = path.parts[len(root_parts)]
    client = next((c for c in config['clients'] if c['name'] == client_name), None)
    if not client:
        return []
    
    # First try database-driven discovery (works with category paths)
    mount_path = config.get('mount_path', '/mnt/transfs')
    rel_path_parts = path.parts[len(root_parts):]
    rel_path = '/'.join(rel_path_parts)
    db_maps = _get_subdirectories_from_db(mount_path, rel_path)
    
    # If database returns results, use them
    if db_maps:
        logger.debug(f"list_maps: Using database-discovered maps for {rel_path}: {db_maps}")
        return db_maps
    
    # Fallback: Try to find system using flexible search
    system_info = get_system_info(client, rel_path_parts)
    if not system_info:
        # Not found - might be at a different level, return empty
        logger.debug(f"list_maps: No system found for {rel_path}")
        return []
    
    system = system_info
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
        
        # Skip flattened maps (.) - their contents appear directly in this directory
        if is_flatten_map(map_name):
            continue
        
        # Skip parent-level maps (../) - they appear at parent directory level
        if is_parent_level_map(map_name):
            continue
        
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
    
    # Handle flattened maps (.) - merge their contents directly into this listing
    flatten_map_entry = next((m for m in system['maps'] if list(m.keys())[0] == '.'), None)
    if flatten_map_entry:
        flatten_config = flatten_map_entry['.']
        if 'query' in flatten_config:
            # For flattened query maps, list the files from the source_dir
            query_cfg = flatten_config['query']
            source_dir = query_cfg.get('source_dir', 'Software')
            local_base = system.get('local_base_path', '')
            filestore = config.get('filestore', '/mnt/filestorefs')
            
            flat_source_path = os.path.join(filestore, 'Native', local_base, source_dir)
            if os.path.isdir(flat_source_path):
                try:
                    files_in_source = os.listdir(flat_source_path)
                    for fname in files_in_source:
                        if not fname.startswith('.'):
                            maps.append(fname)
                            mapped_names.add(fname)
                except OSError:
                    pass
    
    # Deduplicate while preserving order
    deduped = []
    seen = set()
    for entry in maps:
        if entry in seen:
            continue
        seen.add(entry)
        deduped.append(entry)
    
    logger.debug(f"list_maps: Config-based maps for {rel_path}: {deduped}")
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

def list_client_nested_map_entries(config, client: dict, parent_path: str) -> list:
    """
    List entries within a client-level virtual directory that contains nested maps.
    E.g., for /RetroBat/bios, list atom.zip from 'bios/atom.zip'
    """
    entries = []
    prefix = parent_path + '/'
    for map_entry in client.get('maps', []):
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
    """List dynamic Software Archives subfolders and their contents, or regular map subfolders."""
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
    
    # For nested paths (e.g., /RetroBat/AcornAtom/FDs/bios), construct the full map path
    rel_parts = path.parts[len(root_parts):]
    map_parts = rel_parts[2:]  # Everything after client and system
    map_path = '/'.join(map_parts)  # e.g., "FDs/bios"
    map_name = map_parts[0] if map_parts else ""  # e.g., "FDs"
    
    # Check if this is a virtual directory containing nested maps
    # Pass the full map_path for deeper nesting
    nested = list_nested_map_entries(config, path, root_parts, system, map_path)
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
    source_dir = _adjust_source_dir_for_layout(
        query_cfg.get("source_dir", "Software"),
        system,
    )
    supports_zip = query_cfg.get("supports_zip", True)
    zip_mode = query_cfg.get("zip_mode", "hierarchical")
    preserve_structure = query_cfg.get("preserve_structure", False)  # New: preserve source directory structure
    
    # CRITICAL DEBUG: Log config loading
    logger.warning(f"[CRITICAL] list_query_map called for {map_name}. map_config keys: {list(map_config.keys())}")
    logger.warning(f"[CRITICAL] query_cfg keys: {list(query_cfg.keys())}")
    logger.warning(f"[CRITICAL] preserve_structure value: {preserve_structure} (type: {type(preserve_structure).__name__})")

    cache_key = str(path)
    cache_enabled = False  # Directory listing cache is disabled

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
        system_name = system.get("name") if isinstance(system, dict) else None
        system_candidates = []
        if system_id:
            system_candidates.append(system_id)
        if system_name and system_name not in system_candidates:
            system_candidates.append(system_name)
        if not system_candidates:
            logger.warning(f"Query map requested but no system identifier found for {system.get('name')}")
            return []

        # If navigating within a subpath, fall back to filesystem/zip handling
        if subpath:
            # If preserve_structure is enabled, filter database results instead of filesystem
            if preserve_structure:
                subpath_prefix = '/'.join(subpath)
                logger.info(f"Preserve_structure subpath navigation: {subpath_prefix}")
                
                filtered_entries: set[str] = set()
                for entry in entries:
                    # Check if this entry is under the requested subpath
                    if entry.startswith(subpath_prefix + '/'):
                        # Extract the relative path after the subpath
                        remainder = entry[len(subpath_prefix) + 1:]
                        filtered_entries.add(remainder)
                    elif entry.startswith(subpath_prefix) and '/' in entry[len(subpath_prefix):]:
                        # Handle partial matches (e.g., subpath_prefix is part of a deeper path)
                        remainder = entry[len(subpath_prefix):].lstrip('/')
                        filtered_entries.add(remainder)
                
                if not filtered_entries:
                    return []
                
                # Rebuild virtual tree for this subpath
                virtual_tree: set[str] = set()
                for entry in filtered_entries:
                    parts = entry.split('/')
                    if len(parts) > 1:
                        for i in range(len(parts)):
                            virtual_tree.add('/'.join(parts[:i+1]))
                    else:
                        virtual_tree.add(entry)
                
                return sorted(virtual_tree)
            
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
                if not os.path.isfile(zip_path):
                    zip_path = _find_file_recursive(base_dir, zip_name)
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

        query_db = dict(query_cfg)
        query_db["source_dir"] = source_dir

        db_entries = []
        for system_key in system_candidates:
            logger.info(f"QUERY MAP: system={system_key}, map={map_name}, extensions={extensions}")
            db_entries = query_files_by_system_and_query(
                system=system_key,
                query=query_db,
                system_config=system,
                limit=10000
            )
            if db_entries:
                break

        if not db_entries:
            t_func_elapsed = time.time() - t_func_start
            logger.info(f"list_query_map END: 0 entries in {t_func_elapsed:.2f}s")
            return []

        entries: set[str] = set()
        zip_entries: list[str] = []
        logger.debug(f"Processing {len(db_entries)} database entries with preserve_structure={preserve_structure}")
        for entry in db_entries:
            filename = entry.get("filename") if isinstance(entry, dict) else None
            db_ext = entry.get("extension") if isinstance(entry, dict) else None
            source_path = entry.get("source_path") if isinstance(entry, dict) else None
            if not filename:
                filename = entry[0] if isinstance(entry, (tuple, list)) else str(entry)
            
            # Debug: Log first entry to understand database structure
            if entry == db_entries[0]:
                logger.info(f"DB entry structure: filename={filename}, extension={db_ext}, source_path={source_path}, full_entry={entry}")
            
            if filename.lower().endswith('.zip'):
                zip_entries.append(filename)
                if zip_mode == "file" or not supports_zip:
                    entries.add(filename)
                elif zip_mode == "hierarchical":
                    entries.add(filename)
                continue
            
            # Use extension from database if available, otherwise extract from filename
            if db_ext:
                ext = db_ext.upper() if db_ext else ""
                # Build filename with extension if not already included
                if not filename.lower().endswith(f".{db_ext.lower()}"):
                    full_filename = f"{filename}.{db_ext.lower()}"
                else:
                    full_filename = filename
            else:
                name, ext = os.path.splitext(filename)
                ext = ext[1:].upper() if ext else ""
                full_filename = filename
            
            if ext and ext in extension_map:
                virt_ext = extension_map[ext]
                name = filename.rsplit('.', 1)[0] if '.' in filename else filename
                final_entry = f"{name}.{virt_ext.lower()}"
            else:
                final_entry = full_filename if db_ext else filename
            
            # If preserve_structure is enabled, include relative directory path
            if preserve_structure and source_path:
                relative_path = _extract_relative_path(source_path, source_dir, system.get("local_base_path"))
                if relative_path:
                    full_entry = f"{relative_path}/{final_entry}"
                    logger.debug(f"Adding with structure: {full_entry} (from {final_entry})")
                    entries.add(full_entry)
                else:
                    logger.debug(f"No relative path found for {final_entry}, adding as root")
                    entries.add(final_entry)
            else:
                entries.add(final_entry)

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
                if not os.path.isfile(zip_path):
                    zip_path = _find_file_recursive(base_dir, zip_name)
                if os.path.isfile(zip_path):
                    try:
                        internal = zippath_listdir(zip_path)
                        for child in internal:
                            entries.add(child)
                    except Exception:
                        continue

        # When preserve_structure is enabled, build virtual directory tree from relative paths
        if preserve_structure and entries:
            logger.warning(f"[CRITICAL] About to build virtual tree. preserve_structure={preserve_structure}, entries count={len(entries)}")
            virtual_tree: set[str] = set()
            for entry in entries:
                # Split paths and extract components for virtual directory structure
                parts = entry.split('/')
                if len(parts) > 1:
                    # Add each directory level
                    for i in range(len(parts)):
                        virtual_tree.add('/'.join(parts[:i+1]))
                else:
                    # Top-level files/entries without subdirectories
                    virtual_tree.add(entry)
            entries = virtual_tree
            logger.info(f"Preserve_structure enabled: built virtual tree with {len(entries)} total entries (dirs + files)")
            sample_entries = sorted(list(entries))[:10]
            logger.debug(f"Sample entries from virtual tree: {sample_entries}")

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

def _extract_relative_path(source_path: str, source_dir: str, local_base_path: str) -> str:
    """
    Extract the relative directory path from a full source path.
    
    For example:
      source_path: "/mnt/filestorefs/Native/Acorn/Atom/Software/Sources/hoglet67/AA/GALAXIAN"
      source_dir: "Software"
      local_base_path: "Acorn/Atom"
    Returns: "Sources/hoglet67/AA"
    """
    if not source_path:
        return ""
    
    try:
        # Normalize paths
        source_path = source_path.replace("\\", "/")
        source_dir = source_dir.strip("/").lower()
        local_base_path = (local_base_path or "").strip("/").lower()
        
        # Find the source_dir in the path
        source_dir_idx = source_path.lower().find(f"/{source_dir}/")
        if source_dir_idx == -1:
            source_dir_idx = source_path.lower().find(f"/{source_dir.lower()}/")
        
        if source_dir_idx == -1:
            logger.debug(f"Source dir '{source_dir}' not found in path '{source_path}'")
            return ""
        
        # Extract everything after source_dir/
        start_idx = source_dir_idx + len(source_dir) + 2  # +2 for the slashes
        remainder = source_path[start_idx:]
        
        # Get the directory part (everything except the filename)
        dir_part = remainder.rsplit("/", 1)[0] if "/" in remainder else ""
        
        logger.debug(f"_extract_relative_path: source_path={source_path}, source_dir={source_dir}, result={dir_part}")
        return dir_part
    except Exception as e:
        logger.warning(f"Error extracting relative path from {source_path}: {e}")
        return ""


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
    cache_enabled = False  # Directory listing cache is disabled

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
