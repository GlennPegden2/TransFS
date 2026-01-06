import os
import time
import pickle
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

# getattr cache: {path: (dir_mtime, stat_dict)}
_getattr_cache = {}
_getattr_cache_loaded = False
_getattr_cache_dirty = False
_last_getattr_save = time.time()
GETATTR_SAVE_INTERVAL = 5.0  # Save every 5 seconds if dirty

def _load_cache():
    """Load cache from disk."""
    global _dir_cache, _cache_loaded
    if not _cache_loaded:
        try:
            if os.path.exists(CACHE_FILE):
                with open(CACHE_FILE, 'rb') as f:
                    _dir_cache = pickle.load(f)
                logger.info(f"Loaded cache with {len(_dir_cache)} entries from disk")
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")
            _dir_cache = {}
        _cache_loaded = True

def _save_cache():
    """Save cache to disk."""
    try:
        with open(CACHE_FILE, 'wb') as f:
            pickle.dump(_dir_cache, f)
    except Exception as e:
        logger.warning(f"Failed to save cache: {e}")

def _load_getattr_cache():
    """Load getattr cache from disk."""
    global _getattr_cache, _getattr_cache_loaded
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
    try:
        with open(GETATTR_CACHE_FILE, 'wb') as f:
            pickle.dump(_getattr_cache, f)
    except Exception as e:
        logger.warning(f"Failed to save getattr cache: {e}")

def cache_getattr(path: str, parent_dir: str, stat_dict: dict):
    """Cache getattr result for a file. Saves periodically to avoid excessive disk I/O."""
    global _getattr_cache_dirty, _last_getattr_save
    try:
        _load_getattr_cache()
        
        # Get parent directory mtime from directory cache to avoid filesystem access
        _load_cache()
        parent_mtime = 0
        if parent_dir in _dir_cache:
            parent_mtime, _ = _dir_cache[parent_dir]
        else:
            # Fallback to filesystem check (may trigger FUSE recursion)
            try:
                parent_mtime = os.path.getmtime(parent_dir) if os.path.isdir(parent_dir) else 0
            except Exception:
                parent_mtime = 0
        
        _getattr_cache[path] = (parent_mtime, stat_dict)
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
        _save_getattr_cache()
        _getattr_cache_dirty = False

def get_cached_getattr(path: str, parent_dir: str):
    """Get cached getattr result if valid. Uses dir cache mtime to avoid recursion."""
    try:
        _load_getattr_cache()
        if path in _getattr_cache:
            cached_parent_mtime, stat_dict = _getattr_cache[path]
            
            # Get parent directory mtime from the directory cache to avoid filesystem access
            _load_cache()
            if parent_dir in _dir_cache:
                current_parent_mtime, _ = _dir_cache[parent_dir]
                if cached_parent_mtime == current_parent_mtime:
                    return stat_dict
            else:
                # Parent not in directory cache - check filesystem
                # But this might trigger FUSE recursion!
                try:
                    current_parent_mtime = os.path.getmtime(parent_dir) if os.path.isdir(parent_dir) else 0
                    if cached_parent_mtime == current_parent_mtime:
                        return stat_dict
                except Exception:
                    pass
    except Exception:
        pass
    return None
    return None

def get_cache_status(path: str) -> dict:
    """Get cache status for a given path."""
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
    # Some clients (like Mame) don't have a systems key
    if 'systems' not in client:
        return []
    return [system['name'] for system in client['systems']]

def list_maps(config, path: Path, root_parts: tuple) -> list:
    """List all maps and dynamic SoftwareArchives for a system."""
    client_name = path.parts[len(root_parts)]
    client = next((c for c in config['clients'] if c['name'] == client_name), None)
    if not client:
        return []
    if 'systems' not in client:
        return []
    system_name = path.parts[len(root_parts) + 1]
    system = next((s for s in client['systems'] if s['name'] == system_name), None)
    if not system:
        return []
    maps = []
    mapped_names = set()
    # Track top-level virtual directories (e.g., "MMBs" from "MMBs/beeb1_mmb.VHD")
    virtual_dirs = set()
    # Track source directories used by ...SoftwareArchives... to exclude them from listing
    excluded_dirs = set()
    
    # Find SoftwareArchives source_dir
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
    # Add any real files/dirs in the real directory that aren't mapped
    real_dir = os.path.join(
        config.get("filestore", "/mnt/filestorefs"),
        "Native",
        system['local_base_path']
    )
    if os.path.isdir(real_dir):
        for entry in os.listdir(real_dir):
            if entry not in mapped_names and entry not in excluded_dirs and not entry.startswith('.'):
                maps.append(entry)
    return maps

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
    if 'systems' not in client:
        return []
    system_name = path.parts[len(root_parts) + 1]
    system = next((s for s in client['systems'] if s['name'] == system_name), None)
    if not system:
        return []
    map_name = path.parts[len(root_parts) + 2]
    
    # Check if this is a virtual directory containing nested maps
    nested = list_nested_map_entries(config, path, root_parts, system, map_name)
    if nested:
        return nested
    
    sa_entry = find_software_archive_entry(system)
    if sa_entry and is_dynamic_map(config,map_name, sa_entry):
        return list_dynamic_map(config, path, root_parts, system, sa_entry, map_name)
    return list_regular_map(config,path, root_parts, system, map_name)

def is_dynamic_map(config, map_name: str, sa_entry: dict) -> bool:
    """Check if the map is a dynamic ...SoftwareArchives... map."""
    filetypes = sa_entry["...SoftwareArchives..."].get("filetypes", [])
    for filetype in filetypes:
        if map_name in filetype:
            return True
    return False

def list_dynamic_map(
    config, path: Path, root_parts: tuple, system: dict, sa_entry: dict, map_name: str
) -> list[str]:
    """
    List files and directories for a dynamic ...SoftwareArchives... map,
    handling extension mapping and zip handling modes (hierarchical, flatten, file).
    
    zip_mode options:
      - hierarchical (default): ZIPs appear as navigable directories
      - flatten: ZIPs are transparent, contents merged into parent listing (legacy)
      - file: ZIPs appear as opaque files, not navigable
      
    Caching: Results are cached based on source directory mtime for performance.
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
    # Parts after /<mount>/<client>/<system>/<map_name>/
    subpath = path.parts[len(root_parts) + 3:]
    
    # Cache key: full path string
    cache_key = str(path)
    
    # Check cache validity by comparing directory mtime
    # For FILE mode at root level, check the actual source directory
    if not subpath and zip_mode == "file" and real_exts:
        check_dir = os.path.join(source_dir, real_exts[0])
    else:
        check_dir = source_dir
    
    try:
        current_mtime = os.path.getmtime(check_dir) if os.path.isdir(check_dir) else 0
        
        _load_cache()
        if cache_key in _dir_cache:
            cached_mtime, cached_entries = _dir_cache[cache_key]
            if cached_mtime == current_mtime:
                _cache_hits += 1
                logger.info(f"CACHE HIT: {cache_key} (hits={_cache_hits}, misses={_cache_misses})")
                return cached_entries
    except (OSError, PermissionError):
        current_mtime = 0
    
    _cache_misses += 1
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

    for real_ext in real_exts:
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
                    candidate1 = os.path.join(source_dir, real_ext, *cumulative)
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
            path_components = subpath[:-1] if subpath else []
            dir_path = os.path.join(source_dir, real_ext, *path_components)
            actual_folder = real_ext
            
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
            if zip_path.startswith(os.path.join(source_dir, real_ext)):
                actual_folder = real_ext
            else:
                actual_folder = map_name
            dir_path = os.path.dirname(zip_path)

        # ========== HIERARCHICAL MODE (default) ==========
        if zip_mode == "hierarchical":
            # Root level: subpath empty → list only immediate dirs and zip containers
            if not subpath:
                t_start = time.time()
                listdir_path = dir_path  # Use the resolved dir_path (may be fallback folder)
                dir_entries = [e for e in os.listdir(listdir_path) if not e.startswith('.')]
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
                elif entry_name.lower().endswith(".zip") and supports_zip:
                    entries.add(entry_name)
                elif entry_name.lower().endswith(".zip") and not supports_zip:
                    # Treat as regular file
                    name, ext = os.path.splitext(entry_name)
                    if ext[1:].upper() == real_ext.upper():
                        virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                        entries.add(f"{name}.{virt_ext.lower()}")
                else:
                    name, ext = os.path.splitext(entry_name)
                    if ext[1:].upper() == real_ext.upper():
                        virt_ext = reverse_map.get(real_ext.upper(), real_ext.upper())
                        entries.add(f"{name}.{virt_ext.lower()}")
            t_process_elapsed = time.time() - t_process
            if t_process_elapsed > 0.5:
                logger.warning(f"SLOW entry processing took {t_process_elapsed:.2f}s for {len(dir_entries)} entries")

        # ========== FILE MODE ==========
        elif zip_mode == "file":
            # ZIPs are opaque files, never navigable
            if not subpath:
                # Use os.scandir for efficiency (avoids 3500+ stat calls)
                scan_path = os.path.join(source_dir, real_ext)
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
                dir_entries = [e for e in os.listdir(os.path.join(source_dir, real_ext)) if not e.startswith('.')]
                for entry in dir_entries:
                    entry_path = os.path.join(source_dir, real_ext, entry)
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
    
    # Cache the result with current mtime
    try:
        _load_cache()
        _dir_cache[cache_key] = (current_mtime, entries_list)
        _save_cache()
        logger.info(f"CACHED: {cache_key} with mtime={current_mtime}")
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
