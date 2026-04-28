#!/usr/bin/env python3
"""
Async TransFS filesystem using pyfuse3.

This is the pyfuse3 version of TransFS with async operations and inode-based interface.
"""

import errno
import logging
import mmap
import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Optional
import trio

import pyfuse3
from pyfuse3 import FUSEError, InodeT, FileHandleT

from passthroughfs import Passthrough
from dirlisting import parse_trans_path, get_cached_stat, cache_stat

# Backwards-compatible aliases for older getattr naming in this module
get_cached_getattr = get_cached_stat
cache_getattr = cache_stat
from pathutils import full_path, is_virtual_path, map_virtual_to_real
from sourcepath import get_source_path, get_source_path_for_write
from zippath import is_supported_archive_name, open_file as zippath_open_file, listdir as zippath_listdir
from logging_setup import setup_logging
from data_provider_init import initialize_data_provider, get_data_provider_manager
from fuse_adapter import FUSEOperationAdapter

setup_logging(logging.INFO)
logger = logging.getLogger("transfs")
logger.info("TransFS logging initialized (pyfuse3 version)")

# Global reference to the FUSE instance for API access and signal handling
_fuse_instance: Optional['TransFS'] = None


def _adjust_source_dir_for_layout(source_dir: str, system_info: dict) -> str:
    layout = system_info.get("download_layout") if system_info else None
    if layout != "legacy_source_based":
        return source_dir
    normalized = (source_dir or "").replace("\\", "/").strip("/").lower()
    if "sources" in normalized:
        return source_dir
    if "bios" in normalized.split("/"):
        return source_dir
    return os.path.join(source_dir, "Sources")


def _find_sample_file_recursive(source_dir: str, ext: str, extension_filters: dict) -> Optional[str]:
    if not source_dir or not os.path.isdir(source_dir):
        return None
    ext_upper = ext.upper()
    filters = extension_filters.get(ext_upper)
    min_size = filters.get('min_size') if filters else None
    max_size = filters.get('max_size') if filters else None
    for root, _, files in os.walk(source_dir):
        for filename in files:
            if not filename.upper().endswith(f'.{ext_upper}'):
                continue
            candidate = os.path.join(root, filename)
            if min_size is None and max_size is None:
                return candidate
            try:
                size = os.path.getsize(candidate)
            except OSError:
                continue
            if (min_size is None or size >= min_size) and (max_size is None or size <= max_size):
                return candidate
    return None


class TransFS(Passthrough):
    """
    FUSE filesystem for translating virtual paths to real files with zip support.
    Async version using pyfuse3.
    """

    # Disable kernel writeback caching to reduce write-related hangs with SMB clients
    enable_writeback_cache = False
    
    # Profiling stats (class variables for global tracking)
    _getattr_count = 0
    _getattr_total_time = 0.0
    _getattr_cache_hits = 0
    _getattr_cache_misses = 0
    _last_stats_print = time.time()

    def __init__(self, root_path: str, mount_path: str = None):
        super().__init__(root_path)
        logger.debug("Starting TransFS (pyfuse3)")
        self.root = root_path
        self.mount_path = mount_path or root_path  # Store mount point for path mapping
        self._source_path_cache = {}  # Cache virtual_path -> source_path to avoid re-computation
        self._pending_utime = {}  # inode -> (atime_ns, mtime_ns) deferred for open fh
        self._fd_open_meta = {}  # fd -> lifecycle metadata (opened_at, path, flags, source_kind)
        self._fd_path_map = {}  # fd -> real path for read diagnostics
        self._fd_read_stats = {}  # fd -> {'total': int, 'max_end': int}
        self._fd_mmap = {}  # fd -> mmap object for memory-mapped file I/O
        self._fd_file_size = {}  # fd -> file size for mmap boundary checking
        self._db_readdir_cache = {}  # path -> (timestamp, db_files)
        self._db_readdir_cache_ttl = 120.0  # seconds
        # Disc cache: (client_name, system_name) -> {'zip_path': str, 'files': {inner_file: temp_path}}
        # Mimics a single "disc in the drive" per (client, system) pair.  A different
        # game evicts (and unlinks) the previous cached files before caching the new ones.
        self._disc_cache: dict = {}
        self._config_readdir_cache = {}  # path -> (timestamp, config_entries)
        self._config_readdir_cache_ttl = 15.0  # seconds
        self._lookup_parent_entries_cache = {}  # parent_path -> (timestamp, set(entries))
        self._lookup_parent_entries_ttl = 0.5  # seconds
        from config import read_config
        self.config = read_config()
        
        # Initialize database connection for queries
        try:
            from db.connection import init_database as db_init_database
            # Increase pool size for concurrent FUSE operations (especially recursive directory listing)
            # Default was 5+10=15, now 30+40=70 to balance concurrency with PostgreSQL limits (300 max)
            db_init_database(pool_size=100, max_overflow=100)
            logger.info("Database connection initialized with pool_size=100, max_overflow=100")
        except Exception as e:  # pylint: disable=broad-except
            logger.warning(f"Failed to initialize database connection: {e}")
        
        try:
            from dirlisting import set_cache_config
            cache_config = self.config.get("cache", {})
            if cache_config:
                set_cache_config(cache_config)
        except Exception as e:  # pylint: disable=broad-except
            logger.warning(f"Failed to apply cache config: {e}")
        
        # Initialize DataProvider if database is enabled
        self.data_adapter = None
        try:
            if self.config.get('database', {}).get('enabled', False):
                logger.info("Database mode enabled - initializing DataProvider")
                manager = initialize_data_provider(self.config)
                self.data_adapter = FUSEOperationAdapter(manager.get_provider())
                logger.info(f"DataProvider initialized: mode={self.data_adapter.get_provider_mode()}")
            else:
                logger.info("Database mode disabled - using cache-only mode")
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Failed to initialize DataProvider: {e}", exc_info=True)
            logger.warning("Falling back to cache-only mode")
            self.data_adapter = None

    def reload_config_from_disk(self) -> dict:
        """Reload config from disk and update in-memory state.
        
        Returns:
            dict with status and details about the reload operation
        """
        try:
            from config import read_config, reload_config
            
            logger.info("SIGHUP: Reloading config from disk...")
            
            # Clear config cache in the config module
            reload_config()
            
            # Re-read config
            new_config = read_config()
            self.config = new_config
            
            # Clear cache entries that may be stale with new config
            self._config_readdir_cache.clear()
            self._source_path_cache.clear()
            self._db_readdir_cache.clear()
            self._disc_cache.clear()
            
            # Reinitialize data adapter if database settings changed
            try:
                if new_config.get('database', {}).get('enabled', False):
                    if self.data_adapter is None:
                        logger.info("Database mode now enabled - reinitializing DataProvider")
                        manager = initialize_data_provider(new_config)
                        self.data_adapter = FUSEOperationAdapter(manager.get_provider())
                    # If already initialized, leave it alone (connection pool remains valid)
                else:
                    if self.data_adapter is not None:
                        logger.info("Database mode now disabled - clearing DataProvider")
                        self.data_adapter = None
            except Exception as e:  # pylint: disable=broad-except
                logger.warning(f"Failed to reinitialize DataProvider after config reload: {e}")
            
            logger.info("Config reload complete - client/source mappings refreshed")
            return {
                "success": True,
                "message": "Config reloaded and applied to FUSE process",
                "timestamp": time.time()
            }
        except Exception as e:  # pylint: disable=broad-except
            logger.error(f"Failed to reload config: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "timestamp": time.time()
            }

    def _filestore_to_mount_path(self, filestore_path: str) -> str:
        """Convert a filestore path to a mount-relative path for get_source_path()."""
        try:
            rel_path = os.path.relpath(filestore_path, self.root)
            mount_path = os.path.join(self.mount_path, rel_path)
            return mount_path
        except ValueError:
            # If relpath fails, return as-is
            return filestore_path
    
    def _maybe_print_stats(self):
        """Print profiling stats every 10 seconds."""
        now = time.time()
        if now - TransFS._last_stats_print >= 10.0:
            if TransFS._getattr_count > 0:
                avg_time = TransFS._getattr_total_time / TransFS._getattr_count
                hit_rate = 100.0 * TransFS._getattr_cache_hits / TransFS._getattr_count
                logger.info(
                    "GETATTR STATS: count=%d hits=%d misses=%d hit_rate=%.1f%% avg_time=%.4fs total_time=%.2fs",
                    TransFS._getattr_count,
                    TransFS._getattr_cache_hits,
                    TransFS._getattr_cache_misses,
                    hit_rate,
                    avg_time,
                    TransFS._getattr_total_time
                )
            TransFS._last_stats_print = now

    def _log_fh_state(self, fh: int, context: str) -> None:
        """Log current file-handle state for debugging SMB/FUSE deadlocks."""
        try:
            inode = self._fd_inode_map.get(fh)
            count = self._fd_open_count.get(fh)
            meta = self._fd_open_meta.get(fh, {})
            opened_at = meta.get("opened_at")
            age = None
            if opened_at is not None:
                age = max(0.0, time.time() - opened_at)
            logger.info(
                "FH_STATE: %s fh=%s inode=%s open_count=%s source_kind=%s age=%.3fs path=%s",
                context,
                fh,
                inode,
                count,
                meta.get("source_kind"),
                age if age is not None else -1.0,
                meta.get("path")
            )
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning("FH_STATE: failed to log state for fh=%s (%s)", fh, exc)

    def _register_open_handle(self, fh: int, inode: InodeT, path: str, flags: int, source_kind: str) -> None:
        """Register all internal state for a newly opened file handle."""
        self._fd_inode_map[fh] = inode
        self._inode_fd_map[inode] = fh
        self._fd_open_count[fh] = 1
        self._fd_path_map[fh] = path
        self._fd_open_meta[fh] = {
            "opened_at": time.time(),
            "path": path,
            "flags": flags,
            "source_kind": source_kind,
        }
        self._fd_read_stats[fh] = {
            "total": 0,
            "max_end": 0,
            "reads": 0,
            "errors": 0,
            "last_off": -1,
            "last_size": 0,
            "last_elapsed_ms": 0.0,
        }
        self._log_fh_state(fh, "open-registered")
    
    def _setup_mmap_if_applicable(self, fh: int, path: str) -> None:
        """Setup memory-mapped I/O for large files if enabled."""
        if not getattr(self, '_use_mmap', False):
            return
        
        try:
            # Get file size
            stat_result = os.fstat(fh)
            file_size = stat_result.st_size
            
            # Check if file meets threshold
            threshold = getattr(self, '_mmap_threshold', 10485760)  # Default 10MB
            if file_size < threshold:
                logger.debug("MMAP: skipping fh=%s size=%d (below threshold %d)", fh, file_size, threshold)
                return
            
            # Create read-only memory map
            mmap_obj = mmap.mmap(fh, 0, access=mmap.ACCESS_READ)
            self._fd_mmap[fh] = mmap_obj
            self._fd_file_size[fh] = file_size
            logger.info("MMAP: enabled for fh=%s size=%.2fMB path=%s", 
                       fh, file_size / 1048576, path)
        except Exception as e:
            # Non-fatal - file can still be read via os.read()
            logger.warning("MMAP: failed to create mmap for fh=%s: %s (falling back to os.read)", fh, e)
    
    def _is_database_mode_enabled(self) -> bool:
        """Check if database mode is enabled and adapter is available."""
        return self.data_adapter is not None and self.data_adapter.is_database_mode()
    
    def _can_use_database(self, path: str) -> bool:
        """Check if database can be used for this path (database mode + path is suitable)."""
        if not self.data_adapter:
            return False
        # Only use database for deep paths (level 3+)
        # Level 0 (/mnt/transfs): Show clients from config
        # Level 1 (/mnt/transfs/MiSTer): Show systems from config
        # Level 2 (/mnt/transfs/MiSTer/Amstrad): Show maps from config
        # Level 3+ (/mnt/transfs/MiSTer/Amstrad/Tapes): Can use database with config filtering
        root_parts = Path(self.root).parts
        path_parts = Path(path).parts
        hierarchy_level = len(path_parts) - len(root_parts)
        
        if hierarchy_level < 3:
            return False
        
        # Exclude known physical filesystem paths from database mode
        # BIOS folders contain physical files, not database-indexed ROM files
        # Using database mode for these paths is wasteful (tries DB, gets 0, falls back to filesystem)
        path_lower = path.lower()
        if '/bios/' in path_lower or path_lower.endswith('/bios'):
            return False
        
        # Use database for all deep paths (Native and client paths)
        # Database results are filtered through parse_trans_path for config compliance
        return True

    def _get_parent_entries_for_lookup(self, parent_path: str):
        """Get parent entries for LOOKUP with a short-lived cache."""
        now = time.time()
        cached = self._lookup_parent_entries_cache.get(parent_path)
        if cached:
            cached_at, entries = cached
            if now - cached_at < self._lookup_parent_entries_ttl:
                return entries

        entries = set(parse_trans_path(self.config, self.mount_path, parent_path))
        self._lookup_parent_entries_cache[parent_path] = (now, entries)
        return entries

    def _get_zip_mode_for_path(self, xfull_path: str) -> str:
        """
        Extract zip_mode configuration for the given path.
        Returns 'hierarchical' (default), 'flatten', or 'file'.
        """
        from pathutils import (
            get_client,
            get_system_info,
            find_software_archive_entry,
            find_map_entry,
            get_map_config,
            resolve_virtual_base_path,
            format_virtual_base_path,
        )
        
        path = Path(xfull_path)
        root_parts = Path(self.root).parts
        rel_parts = path.parts[len(root_parts):]
        
        if len(rel_parts) < 2:
            return "hierarchical"
        
        client = get_client(self.config, rel_parts)
        if not client:
            return "hierarchical"
        
        # Check for client-level file maps first (e.g., /RetroBat/bios/atom.zip)
        if len(rel_parts) >= 2:
            potential_client_map_path = '/'.join(rel_parts[1:])
            client_maps = client.get('maps') or []
            client_map_entry = find_map_entry({'maps': client_maps}, potential_client_map_path)
            if client_map_entry:
                map_config = get_map_config(client_map_entry)
                if map_config and isinstance(map_config, dict):
                    file_spec = map_config.get('file', {})
                    if isinstance(file_spec, dict) and 'zip_mode' in file_spec:
                        return file_spec.get('zip_mode', 'hierarchical')
        
        # Check system-level maps (including nested maps like FDs/bios/atom.zip)
        if len(rel_parts) < 3:
            return "hierarchical"

        # Category-level fallback (e.g., /RetroBat/bios/atom.zip where system name is omitted)
        # Needed for shared category paths that map files from systems without exposing system segment.
        # In this shape, rel_parts = [client, category, filename]
        if len(rel_parts) == 3:
            virtual_rel = '/'.join(rel_parts)
            for candidate_system in client.get('systems', []):
                for map_entry in (candidate_system.get('maps') or []):
                    map_name = list(map_entry.keys())[0]
                    map_config = map_entry.get(map_name, {})
                    if not isinstance(map_config, dict):
                        continue

                    file_spec = map_config.get('file', {})
                    if not file_spec:
                        # Also check '.' query maps that serve files directly at a category path
                        # e.g., a '.' map with query: {zip_mode: file} at shared_bios
                        if map_name == '.':
                            query_cfg = map_config.get('query', {})
                            if isinstance(query_cfg, dict) and 'zip_mode' in query_cfg:
                                try:
                                    base_path_template = resolve_virtual_base_path(client, candidate_system, map_config)
                                    virtual_base = format_virtual_base_path(
                                        base_path_template,
                                        client.get('name', ''),
                                        candidate_system.get('name', ''),
                                    )
                                except Exception:
                                    continue
                                candidate_virtual_path = f"{virtual_base}/{rel_parts[-1]}".replace('\\', '/').rstrip('/')
                                if candidate_virtual_path == virtual_rel:
                                    return query_cfg.get('zip_mode', 'hierarchical')
                        continue

                    try:
                        base_path_template = resolve_virtual_base_path(client, candidate_system, map_config)
                        virtual_base = format_virtual_base_path(
                            base_path_template,
                            client.get('name', ''),
                            candidate_system.get('name', ''),
                        )
                    except Exception:
                        continue

                    candidate_virtual_path = f"{virtual_base}/{map_name}".replace('\\', '/').rstrip('/')
                    if candidate_virtual_path != virtual_rel:
                        continue

                    if isinstance(file_spec, dict) and 'zip_mode' in file_spec:
                        return file_spec.get('zip_mode', 'hierarchical')
                    if 'zip_mode' in map_config:
                        return map_config.get('zip_mode', 'hierarchical')
        
        path_template_parts = Path(client['default_target_path']).parts
        system_info = get_system_info(client, list(rel_parts), path_template_parts)
        if not system_info:
            return "hierarchical"
        
        # First check for nested file maps (e.g., FDs/bios/atom.zip)
        if len(rel_parts) >= 4:
            map_path = '/'.join(rel_parts[2:])  # e.g., 'FDs/bios/atom.zip'
            nested_map_entry = find_map_entry(system_info, map_path)
            if nested_map_entry:
                nested_map_config = get_map_config(nested_map_entry)
                if nested_map_config and isinstance(nested_map_config, dict):
                    file_spec = nested_map_config.get('file', {})
                    if isinstance(file_spec, dict) and 'zip_mode' in file_spec:
                        return file_spec.get('zip_mode', 'hierarchical')
        
        # Then check top-level map
        map_name = rel_parts[2]
        map_entry = find_map_entry(system_info, map_name)
        map_config = get_map_config(map_entry)
        if map_config and isinstance(map_config, dict):
            query_cfg = map_config.get("query", {})
            if isinstance(query_cfg, dict) and "zip_mode" in query_cfg:
                return query_cfg.get("zip_mode", "hierarchical")

        sa_entry = find_software_archive_entry(system_info)
        if not sa_entry:
            return "hierarchical"
        
        return sa_entry["...SoftwareArchives..."].get("zip_mode", "hierarchical")

    def _get_transform_output_size(self, pipeline, source_size: int, source_path: Optional[str] = None) -> int:
        """Get transform output size with optional caching.
        
        If source_path is provided and the last transform stage supports
        get_output_size_for_path(), that is called first (e.g. ChdTransform
        can check the on-disk CHD cache without building it).
        """
        # Path-aware size lookup (e.g. ChdTransform checking its disk cache)
        if source_path and pipeline.stages:
            last_stage = pipeline.stages[-1]
            if hasattr(last_stage, 'get_output_size_for_path'):
                size = last_stage.get_output_size_for_path(source_path)
                if size >= 0:
                    return size

        cache_config = self.config.get("cache", {})
        if cache_config.get("transform_output_size_cache_enabled", True):
            cache = getattr(pipeline, "_output_size_cache", None)
            if cache is None:
                try:
                    cache = {}
                    setattr(pipeline, "_output_size_cache", cache)
                except Exception:
                    cache = None
            if cache is not None:
                cached_size = cache.get(source_size)
                if cached_size is not None:
                    return cached_size
                computed_size = pipeline.get_output_size(source_size)
                cache[source_size] = computed_size
                return computed_size
        return pipeline.get_output_size(source_size)

    def _build_system_transform_map(self, xfull_path: str) -> dict[str, Optional[Any]]:
        """Build a map of file extensions to transform pipelines for this system directory.
        
        This is an optimization that builds the transform pipeline once per extension
        at the system level, rather than calling get_source_path() for every file.
        
        Returns a dict like {"DSK": pipeline, "2MG": pipeline} or empty dict if not applicable.
        """
        from pathutils import get_client, get_system_info, find_map_entry, get_map_config, get_map_transforms
        from filetypes import get_filetype_transforms
        from sourcepath import find_software_archive_entry, get_transform_pipeline_for_file
        from pathlib import Path
        
        try:
            # Parse path using same logic as get_source_path
            path = Path(xfull_path)
            root_parts = Path(self.mount_path).parts
            rel_parts = path.parts[len(root_parts):]
            
            if not rel_parts or rel_parts[0] == "Native":
                return {}
            
            client = get_client(self.config, rel_parts)
            if not client or len(rel_parts) < 3:
                return {}
            
            path_template_parts = Path(client['default_target_path']).parts
            system_info = get_system_info(client, list(rel_parts), path_template_parts)
            if not system_info:
                return {}
            
            # Get the virtual folder (e.g., "Disks", "ROMs") - this is rel_parts[2]
            virtual_folder = rel_parts[2]
            
            # Prefer transforms from query map (new schema)
            map_entry = find_map_entry(system_info, virtual_folder)
            map_config = get_map_config(map_entry)
            transform_map = get_map_transforms(map_config)
            if not transform_map:
                # Fallback to legacy SoftwareArchives transforms
                sa_entry = find_software_archive_entry(system_info)
                if not sa_entry:
                    return {}
                transform_map = get_filetype_transforms(sa_entry)
            if not transform_map:
                return {}
            
            # Build transform pipeline for each extension that has transforms
            pipeline_map = {}
            cache_config = self.config.get("cache", {})
            
            # Get the actual source directory to find real files for detection
            source_dir = None
            if map_config and isinstance(map_config, dict):
                query_cfg = map_config.get("query", {})
                source_subdir = query_cfg.get("source_dir") if isinstance(query_cfg, dict) else None
                if source_subdir:
                    source_subdir = _adjust_source_dir_for_layout(source_subdir, system_info)
                    source_dir = os.path.join(
                        self.config.get("filestore", "/mnt/filestorefs"),
                        "Native",
                        system_info['local_base_path'],
                        source_subdir
                    )
            if not source_dir:
                sa_entry = find_software_archive_entry(system_info)
                if sa_entry:
                    if 'source_paths' in sa_entry and sa_entry['source_paths']:
                        source_dir = sa_entry['source_paths'][0]  # Use first source path
            
            for ext in transform_map.keys():
                # Try to find a real file with this extension for accurate detection
                sample_file = None
                
                # Get extension filters from query config to help select appropriate sample file
                extension_filters = {}
                if map_config and isinstance(map_config, dict):
                    query_cfg = map_config.get("query", {})
                    if isinstance(query_cfg, dict):
                        extension_filters = query_cfg.get("extension_filters", {})
                
                if source_dir and os.path.isdir(source_dir):
                    # Check for extension-specific subdirectory first
                    ext_subdir = os.path.join(source_dir, ext.upper())
                    if os.path.isdir(ext_subdir):
                        try:
                            candidates = []
                            for entry in os.scandir(ext_subdir):
                                if entry.is_file() and entry.name.upper().endswith(f'.{ext.upper()}'):
                                    candidates.append(entry.path)
                            
                            # If extension has size filters, find a file matching this map's filter
                            if candidates and ext.upper() in extension_filters:
                                filters = extension_filters[ext.upper()]
                                min_size = filters.get('min_size')
                                max_size = filters.get('max_size')
                                
                                # Find first file matching size constraint
                                for candidate in candidates:
                                    try:
                                        size = os.path.getsize(candidate)
                                        if (min_size is None or size >= min_size) and (max_size is None or size <= max_size):
                                            sample_file = candidate
                                            break
                                    except OSError:
                                        pass
                            else:
                                # No size filter, just use first file
                                sample_file = candidates[0] if candidates else None
                        except OSError:
                            pass
                    
                    # If not found in subdir, check main directory
                    if not sample_file:
                        try:
                            candidates = []
                            for entry in os.scandir(source_dir):
                                if entry.is_file() and entry.name.upper().endswith(f'.{ext.upper()}'):
                                    candidates.append(entry.path)
                            
                            # If extension has size filters, find a file matching this map's filter
                            if candidates and ext.upper() in extension_filters:
                                filters = extension_filters[ext.upper()]
                                min_size = filters.get('min_size')
                                max_size = filters.get('max_size')
                                
                                # Find first file matching size constraint
                                for candidate in candidates:
                                    try:
                                        size = os.path.getsize(candidate)
                                        if (min_size is None or size >= min_size) and (max_size is None or size <= max_size):
                                            sample_file = candidate
                                            break
                                    except OSError:
                                        pass
                            else:
                                # No size filter, just use first file
                                sample_file = candidates[0] if candidates else None
                        except OSError:
                            pass

                    if not sample_file:
                        sample_file = _find_sample_file_recursive(source_dir, ext, extension_filters)
                
                # Use sample file if found, otherwise fallback to dummy
                filename_for_detection = sample_file if sample_file else f"test.{ext.lower()}"
                
                pipeline = get_transform_pipeline_for_file(
                    logger, 
                    system_info, 
                    filename_for_detection, 
                    virtual_folder,
                    cache_config,
                    full_path=sample_file  # Pass actual file path for format detection
                )
                if pipeline:
                    pipeline_map[ext.upper()] = pipeline
                    if sample_file:
                        logger.info(f"TRANSFORM MAP: Built pipeline for {ext} using sample file: {os.path.basename(sample_file)}")
            
            logger.info(f"TRANSFORM MAP for {virtual_folder}: {len(pipeline_map)} extensions")
            return pipeline_map
            
        except Exception as e:
            # Log but don't fail - just return empty map and fall back to normal path
            logger.warning(f"Failed to build system transform map for {xfull_path}: {e}")
            return {}

    def _dict_to_entry_attributes(self, stat_dict: dict, inode: InodeT, cache_timeout: float = 60.0) -> pyfuse3.EntryAttributes:
        """Convert fusepy-style stat dict to pyfuse3 EntryAttributes."""
        entry = pyfuse3.EntryAttributes()
        entry.st_ino = inode
        entry.st_mode = stat_dict['st_mode']
        entry.st_nlink = stat_dict.get('st_nlink', 1)
        entry.st_uid = stat_dict.get('st_uid', 0)
        entry.st_gid = stat_dict.get('st_gid', 0)
        entry.st_size = stat_dict.get('st_size', 0)
        entry.st_atime_ns = int(stat_dict['st_atime'] * 1e9)
        entry.st_mtime_ns = int(stat_dict['st_mtime'] * 1e9)
        entry.st_ctime_ns = int(stat_dict['st_ctime'] * 1e9)
        entry.st_rdev = 0
        entry.generation = 0
        entry.entry_timeout = cache_timeout  # Cache entry - use 0 for placeholder attrs
        entry.attr_timeout = cache_timeout   # Cache attributes
        entry.st_blksize = 512
        entry.st_blocks = (stat_dict.get('st_size', 0) + 511) // 512
        return entry

    def _make_synthetic_inode(self, path: str) -> int:
        """Generate a stable synthetic inode from a path.
        
        Uses SHA-256 so the same path always produces the same inode number
        across process restarts. This is required for Samba durable handles:
        if the inode changed after a FUSE restart Samba can't reclaim its
        stored handles and logs "Could not close dir! fd=-1, err=ENOENT".
        """
        import hashlib
        digest = hashlib.sha256(path.encode('utf-8')).digest()
        synthetic_inode = int.from_bytes(digest[:4], 'little') & 0x7FFFFFFF
        if synthetic_inode == 0:
            synthetic_inode = 1
        if synthetic_inode == pyfuse3.ROOT_INODE:
            synthetic_inode += 1
        return synthetic_inode

    def _increment_lookup_count(self, inode: InodeT) -> None:
        """Increment the lookup reference count for an inode."""
        self._lookup_cnt[inode] += 1
        logger.info(f"INC_LOOKUP_CNT: inode={inode} count={self._lookup_cnt[inode]}")

    def _get_hidden_root_alias_names(self) -> set[str]:
        """Return lower-cased names that some clients may probe under the share root."""
        alias_names: set[str] = set()
        normalized_mount = os.path.normpath(self.mount_path or "")
        mount_name = os.path.basename(normalized_mount.rstrip(os.sep))
        if mount_name:
            alias_names.add(mount_name.lower())

        advertised_share = (os.getenv("SMB_ADVERTISE_SHARE") or "").strip().strip("/\\")
        if advertised_share:
            alias_names.add(advertised_share.lower())

        return alias_names

    def _is_hidden_root_alias_lookup(self, parent_inode: InodeT, parent_path: str, name: str) -> bool:
        """Return True when a client probes the share name as a hidden child of root.

        Some SMB/FUSE clients issue lookups like /mnt/transfs/transfs even though the
        share root is already /mnt/transfs. Treat that hidden alias as the real root
        instead of returning ENOENT.
        """
        if parent_inode != pyfuse3.ROOT_INODE:
            return False

        normalized_parent = os.path.normpath(parent_path or "")
        normalized_mount = os.path.normpath(self.mount_path or "")
        if normalized_parent != normalized_mount:
            return False

        return (name or "").strip().strip("/\\").lower() in self._get_hidden_root_alias_names()

    def _collapse_hidden_root_alias_path(self, path: str) -> str:
        """Collapse /mount/<share-name>/... compatibility paths back to /mount/..."""
        normalized_path = os.path.normpath(path or "")
        normalized_mount = os.path.normpath(self.mount_path or "")
        if not normalized_mount or normalized_path == normalized_mount:
            return normalized_mount or normalized_path
        if not normalized_path.startswith(normalized_mount):
            return path

        rel_path = os.path.relpath(normalized_path, normalized_mount)
        if rel_path in (".", ""):
            return normalized_mount

        rel_parts = [part for part in rel_path.split(os.sep) if part and part != "."]
        if rel_parts and rel_parts[0].lower() in self._get_hidden_root_alias_names():
            rel_parts = rel_parts[1:]
            collapsed = os.path.join(normalized_mount, *rel_parts) if rel_parts else normalized_mount
            logger.info("PATH NORMALIZE: collapsed hidden root alias %s -> %s", normalized_path, collapsed)
            return collapsed

        return path

    def _normalize_to_virtual_path(self, path: str) -> str:
        """Convert real filesystem path to virtual mount path for consistency."""
        # If it's already a virtual path, keep it (after collapsing any hidden root alias)
        if path.startswith(self.mount_path):
            return self._collapse_hidden_root_alias_path(path)
        # If it's a real path, convert it back to virtual
        if path.startswith("/mnt/filestorefs"):
            rel_path = os.path.relpath(path, "/mnt/filestorefs")
            if rel_path == '.':
                # If it's the root directory, return mount_path without the '.'
                return self.mount_path
            return self._collapse_hidden_root_alias_path(os.path.join(self.mount_path, rel_path))
        return self._collapse_hidden_root_alias_path(path)

    def _normalize_cue_reference_name(self, name: str) -> str:
        """Normalize cue target names for loose matching against sibling disc files."""
        import re

        base = os.path.basename(name or "")
        stem, _ = os.path.splitext(base)
        stem = re.sub(r"\[[^\]]*\]", "", stem)
        return re.sub(r"[^a-z0-9]+", "", stem.lower())

    def _rewrite_cue_content(self, cue_bytes: bytes, sibling_names: list[str], context: str) -> bytes:
        """Rewrite broken FILE references in cue sheets to match available sibling files."""
        if not cue_bytes or not sibling_names:
            return cue_bytes

        import re

        sibling_set = {os.path.basename(name) for name in sibling_names}
        encodings = ("utf-8", "cp1252", "latin-1")
        text = None
        encoding_used = "utf-8"
        for encoding in encodings:
            try:
                text = cue_bytes.decode(encoding)
                encoding_used = encoding
                break
            except UnicodeDecodeError:
                continue
        if text is None:
            return cue_bytes

        def pick_candidate(reference_name: str) -> Optional[str]:
            ref_base = os.path.basename(reference_name)
            if ref_base in sibling_set:
                return ref_base

            _, ref_ext = os.path.splitext(ref_base)
            same_ext = [name for name in sibling_set if os.path.splitext(name)[1].lower() == ref_ext.lower()]
            if not same_ext:
                return None
            if len(same_ext) == 1:
                return same_ext[0]

            normalized_ref = self._normalize_cue_reference_name(ref_base)
            for candidate in same_ext:
                normalized_candidate = self._normalize_cue_reference_name(candidate)
                if normalized_candidate == normalized_ref:
                    return candidate
                if normalized_ref and (normalized_ref in normalized_candidate or normalized_candidate in normalized_ref):
                    return candidate
            return None

        changed = False
        pattern = re.compile(r'(?im)^(FILE\s+")([^"]+)(".*)$')

        def replace_match(match: re.Match) -> str:
            nonlocal changed
            original_name = match.group(2)
            replacement = pick_candidate(original_name)
            if replacement and replacement != original_name:
                changed = True
                logger.info("CUE_REWRITE: %s -> %s for %s", original_name, replacement, context)
                return f'{match.group(1)}{replacement}{match.group(3)}'
            return match.group(0)

        rewritten_text = pattern.sub(replace_match, text)
        if not changed:
            return cue_bytes
        return rewritten_text.encode(encoding_used, errors='replace')

    def _extract_map_info(self, path: str) -> Optional[tuple]:
        """
        Extract client, system, and map_name from a virtual path.
        Returns tuple (client_name, system_name, map_name) or None.
        
        Example: /mnt/transfs/MiSTer/Apple-II/FDs -> ('MiSTer', 'Apple-II', 'FDs')
        Also supports category paths like /mnt/transfs/RetroBat/ROMS/3DO/CDs.
        """
        try:
            rel_parts = Path(path).parts[len(Path(self.mount_path).parts):]
            if len(rel_parts) < 3:
                return None
            
            client_name = rel_parts[0]
            
            # Verify this is a valid client/system/map
            client_config = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
            if not client_config:
                logger.debug(f"_extract_map_info: client {client_name} not found")
                return None

            # Resolve system segment for both non-category and category paths.
            # Non-category: /<client>/<system>/<map>
            # Category: /<client>/<category>/<system>/<map>
            from pathutils import resolve_system_name
            system_idx = None
            system_name = None
            for idx, part in enumerate(rel_parts[1:], start=1):
                resolved = resolve_system_name(client_config, part)
                if resolved:
                    system_idx = idx
                    system_name = resolved
                    break

            if system_idx is None or system_name is None:
                logger.debug(f"_extract_map_info: system not found in path {rel_parts}")
                return None

            map_idx = system_idx + 1
            if len(rel_parts) <= map_idx:
                return None

            map_name = rel_parts[map_idx]
            
            system_info = next((s for s in client_config.get('systems', []) if s['name'] == system_name), None)
            if not system_info:
                logger.debug(f"_extract_map_info: system {system_name} not found")
                return None
            
            # Check if map exists
            map_entry = next((m for m in (system_info.get('maps') or []) if list(m.keys())[0] == map_name), None)
            if not map_entry:
                logger.debug(f"_extract_map_info: map {map_name} not found in {system_name}")
                return None
            
            # Check if it's a query map
            map_config = map_entry.get(map_name)
            if not map_config:
                logger.debug(f"_extract_map_info: no config for map {map_name}")
                return None
            
            # Accept both query maps and unzipped file maps
            is_query_map = 'query' in map_config
            is_unzipped_file_map = False
            if 'file' in map_config:
                file_spec = map_config.get('file')
                if isinstance(file_spec, dict):
                    is_unzipped_file_map = file_spec.get('unzip', False)
                elif isinstance(map_config.get('unzip'), bool):
                    is_unzipped_file_map = map_config.get('unzip', False)
            
            if not is_query_map and not is_unzipped_file_map:
                logger.debug(f"_extract_map_info: {map_name} is not a query map or unzipped file map")
                return None
            
            if is_query_map:
                logger.debug(f"_extract_map_info: found query map {client_name}/{system_name}/{map_name}")
            else:
                logger.debug(f"_extract_map_info: found unzipped file map {client_name}/{system_name}/{map_name}")
            return (client_name, system_name, map_name)
        except Exception as e:
            logger.debug(f"_extract_map_info error for {path}: {e}")
            return None

    async def _readdir_database_only(self, path: str, start_id: int, token, map_info: tuple):
        """
        Read directory entries using ONLY database queries (no filesystem fallback).
        
        This is the primary mode for query map directories.
        Returns False if completed successfully, True if should fall back to filesystem.
        """
        client_name, system_name, map_name = map_info
        logger.info(f"READDIR_DB_ONLY: {path} client={client_name} system={system_name} map={map_name}")
        
        try:
            # Get map configuration to find allowed extensions
            from pathutils import find_map_entry, get_map_config
            client_config = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
            if not client_config:
                logger.warning(f"READDIR_DB_ONLY: client {client_name} not found")
                return True  # Fall back to filesystem
            
            system_info = next((s for s in client_config.get('systems', []) if s['name'] == system_name), None)
            if not system_info:
                logger.warning(f"READDIR_DB_ONLY: system {system_name} not found")
                return True
            
            map_entry = find_map_entry(system_info, map_name)
            if not map_entry:
                logger.warning(f"READDIR_DB_ONLY: map {map_name} not found")
                return True
            
            map_config = get_map_config(map_entry)
            if not map_config:
                logger.warning(f"READDIR_DB_ONLY: no config for map {map_name}")
                return True
            
            # Extract allowed extensions from map config (inside query key)
            from pathutils import get_query_config
            query_config = get_query_config(map_config)
            allowed_extensions = [str(ext).upper() for ext in query_config.get('extensions', []) if ext]
            if query_config.get('transform_zip', False):
                for archive_ext in ('ZIP', '7Z'):
                    if archive_ext not in allowed_extensions:
                        allowed_extensions.append(archive_ext)
            logger.info(f"READDIR_DB_ONLY: allowed_extensions for {map_name}: {allowed_extensions}")
            if not allowed_extensions:
                logger.info(f"READDIR_DB_ONLY: no extensions configured for {map_name}")
                return True
            
            # Extract size filters from query config if present
            extension_filters = {}
            preserve_structure = False
            if query_config:
                # Parse preserve_structure option
                preserve_structure = query_config.get('preserve_structure', False)
                logger.info(f"READDIR_DB_ONLY: preserve_structure={preserve_structure}")
                
                # Build size filter dict from extension-specific configs
                ext_config = query_config.get('extension_filters', {})
                if ext_config:
                    for ext, filters in ext_config.items():
                        extension_filters[ext] = filters
                        logger.info(f"READDIR_DB_ONLY: size filter for {ext}: {filters}")
                if not extension_filters:
                    logger.debug(f"READDIR_DB_ONLY: no extension_filters in query config")
            
            # Query database for files in this map (with cache)
            cache_entry = self._db_readdir_cache.get(path)
            if cache_entry:
                cached_at, cached_files = cache_entry
                if (time.time() - cached_at) <= self._db_readdir_cache_ttl:
                    db_files = cached_files
                else:
                    self._db_readdir_cache.pop(path, None)
                    db_files = None
            else:
                db_files = None

            if db_files is None:
                from db.queries import query_files_by_client_system_and_map
                db_files = query_files_by_client_system_and_map(
                    client_name, system_name, map_name, allowed_extensions, extension_filters
                )
                self._db_readdir_cache[path] = (time.time(), db_files)
            
            logger.info(f"READDIR_DB_ONLY: found {len(db_files)} files in map-index database")

            # QUERY FALLBACK: Older or partial sync runs may miss file_client_maps rows for query maps.
            # Fall back to system/query resolution (same semantics as dirlisting) when map-index lookup is empty.
            if not db_files and query_config:
                try:
                    from db.queries import query_files_by_system_and_query
                    from pathutils import get_system_identifier

                    query_db = dict(query_config)
                    query_db["source_dir"] = _adjust_source_dir_for_layout(
                        query_config.get("source_dir", "Software"),
                        system_info,
                    )

                    system_candidates = []

                    def _add_system_candidate(value):
                        candidate = str(value or "").strip()
                        if candidate and candidate not in system_candidates:
                            system_candidates.append(candidate)

                    _add_system_candidate(get_system_identifier(system_info))
                    _add_system_candidate(system_info.get("name"))
                    _add_system_candidate(system_info.get("system_mapping_name"))
                    _add_system_candidate(system_info.get("cananonical_system_name"))
                    _add_system_candidate(str(system_info.get("name") or "").lower())
                    _add_system_candidate(str(system_info.get("system_mapping_name") or "").lower())
                    _add_system_candidate(str(system_info.get("cananonical_system_name") or "").lower())

                    query_entries_by_filename = {}
                    for system_key in system_candidates:
                        candidate_entries = query_files_by_system_and_query(
                            system=system_key,
                            query=query_db,
                            system_config=system_info,
                            limit=10000,
                        )
                        for entry in candidate_entries:
                            fname = entry.get('filename', '') if isinstance(entry, dict) else str(entry)
                            if fname and fname not in query_entries_by_filename:
                                query_entries_by_filename[fname] = entry

                    if query_entries_by_filename:
                        db_files = list(query_entries_by_filename.values())
                        logger.info(
                            "READDIR_DB_ONLY: query fallback recovered %d files for %s/%s/%s",
                            len(db_files),
                            client_name,
                            system_name,
                            map_name,
                        )
                except Exception as fallback_error:  # pylint: disable=broad-except
                    logger.warning("READDIR_DB_ONLY: query fallback failed: %s", fallback_error)
            
            # FILESYSTEM MERGE/FALLBACK: include files that exist on disk but are not in the
            # map index yet (for example newly mounted NAS content) so they appear immediately
            # without requiring a DB sync.
            if query_config:
                source_dir = query_config.get('source_dir', '')
                if source_dir:
                    filestore = self.config.get('filestore', '/mnt/filestorefs')
                    local_base = system_info.get('local_base_path', '')
                    full_source_dir = os.path.join(filestore, 'Native', local_base, source_dir)
                    
                    # Determine current subpath for preserve_structure mode
                    rel_parts = Path(path).parts[len(Path(self.mount_path).parts):]
                    try:
                        map_idx = rel_parts.index(map_name)
                        subpath_parts = rel_parts[map_idx + 1:] if len(rel_parts) > map_idx + 1 else []
                    except ValueError:
                        subpath_parts = rel_parts[3:] if len(rel_parts) > 3 else []
                    current_subpath = '/'.join(subpath_parts)
                    
                    # Build full directory path to scan
                    scan_dir = os.path.join(full_source_dir, current_subpath) if current_subpath else full_source_dir
                    
                    if os.path.exists(scan_dir) and os.path.isdir(scan_dir):
                        # Get existing database filenames for comparison
                        db_filenames = {f.get('filename', '') for f in db_files}
                        show_hidden = self.config.get('show_hidden_files', True)
                        allowed_exts = {str(ext).upper() for ext in (allowed_extensions or []) if ext and str(ext) != '*'}
                        
                        # Scan filesystem for files not in database
                        fs_only_files = []
                        try:
                            for entry in os.scandir(scan_dir):
                                if not show_hidden and entry.name.startswith('.'):
                                    continue
                                
                                if entry.is_file():
                                    if entry.name not in db_filenames:
                                        # File exists on disk but not in database
                                        try:
                                            stat_info = entry.stat()
                                            _, ext = os.path.splitext(entry.name)
                                            ext_upper = ext[1:].upper() if ext else ''
                                            if allowed_exts and ext_upper not in allowed_exts:
                                                continue
                                            
                                            # Create a minimal file record for this filesystem file
                                            fs_file_record = {
                                                'filename': entry.name,
                                                'source_path': entry.path,
                                                'extension': ext_upper,
                                                'size': stat_info.st_size,
                                                'mtime': stat_info.st_mtime,
                                            }
                                            fs_only_files.append(fs_file_record)
                                            logger.debug(f"READDIR_DB_ONLY: filesystem fallback found {entry.name} (not in database)")
                                        except:
                                            pass
                        except Exception as e:
                            logger.warning(f"READDIR_DB_ONLY: filesystem fallback error: {e}")

                        # If no direct files found, recursively scan nested source folders.
                        if not fs_only_files:
                            try:
                                for root_dir, _, filenames in os.walk(scan_dir):
                                    for filename in filenames:
                                        if not show_hidden and filename.startswith('.'):
                                            continue
                                        if filename in db_filenames:
                                            continue

                                        _, ext = os.path.splitext(filename)
                                        ext_upper = ext[1:].upper() if ext else ''
                                        if allowed_exts and ext_upper not in allowed_exts:
                                            continue

                                        file_path = os.path.join(root_dir, filename)
                                        try:
                                            stat_info = os.stat(file_path)
                                            fs_only_files.append({
                                                'filename': filename,
                                                'source_path': file_path,
                                                'extension': ext_upper,
                                                'size': stat_info.st_size,
                                                'mtime': stat_info.st_mtime,
                                            })
                                        except Exception:
                                            continue
                            except Exception as nested_error:
                                logger.warning(f"READDIR_DB_ONLY: nested filesystem fallback error: {nested_error}")
                        
                        if fs_only_files:
                            logger.info(f"READDIR_DB_ONLY: filesystem fallback added {len(fs_only_files)} files not in database")
                            db_files = list(db_files) + fs_only_files

            # Refresh cache with the final recovered result set so subsequent paged readdir
            # calls do not repeat expensive query/fallback scans.
            self._db_readdir_cache[path] = (time.time(), db_files)

            if not db_files:
                # Empty directory
                logger.info(f"READDIR_DB_ONLY: no files found, returning empty directory")
                return False
            
            # If preserve_structure is enabled, build a virtual directory tree
            entries_to_send = []
            if preserve_structure:
                logger.info("READDIR_DB_ONLY: building virtual directory tree for preserve_structure")
                source_dir = query_config.get('source_dir', 'Software')

                # Determine which subpath inside the map we're listing
                rel_parts = Path(path).parts[len(Path(self.mount_path).parts):]
                try:
                    map_idx = rel_parts.index(map_name)
                    subpath_parts = rel_parts[map_idx + 1:] if len(rel_parts) > map_idx + 1 else []
                except ValueError:
                    subpath_parts = rel_parts[3:] if len(rel_parts) > 3 else []
                subpath = '/'.join(subpath_parts)

                entries_map = {}  # name -> ('dir'|'file', file_record)

                for file_record in db_files:
                    filename = file_record.get('filename', '')
                    source_path = file_record.get('source_path', '')

                    # Extract relative directory from source_path after source_dir.
                    # source_dir can contain '/' (e.g., Software/BIOS/retrobat-bios-main),
                    # so split/index by path segments is unreliable.
                    rel_dir = ''
                    if source_path:
                        normalized_source = source_path.replace('\\', '/')
                        normalized_source_dir = (source_dir or '').replace('\\', '/').strip('/')
                        marker = f"/{normalized_source_dir}/"
                        if marker in normalized_source:
                            relative_after_source_dir = normalized_source.split(marker, 1)[1]
                            rel_dir = os.path.dirname(relative_after_source_dir).replace('\\', '/').strip('/')

                    # Filter to the current subpath
                    if subpath:
                        if not rel_dir.startswith(subpath):
                            continue
                        remainder = rel_dir[len(subpath):].lstrip('/')
                    else:
                        remainder = rel_dir

                    if remainder:
                        # Show the next directory segment under this subpath
                        next_dir = remainder.split('/', 1)[0]
                        if next_dir not in entries_map:
                            entries_map[next_dir] = ('dir', None)
                    else:
                        # File is directly under this subpath
                        if filename and filename not in entries_map:
                            entries_map[filename] = ('file', file_record)

                entries_to_send = [
                    (entry_type, entry_name, file_record)
                    for entry_name, (entry_type, file_record) in sorted(entries_map.items())
                ]

                logger.info(
                    "READDIR_DB_ONLY: preserve_structure created %d entries from %d files for subpath='%s'",
                    len(entries_to_send),
                    len(db_files),
                    subpath,
                )
            else:
                # Normal mode: flat list of files
                for file_record in db_files:
                    filename = file_record.get('filename', '')
                    entries_to_send.append(('file', filename, file_record))
            
            # Check for nested file map virtual directories (e.g., "bios" from "FDs/bios/atom.zip")
            # These should appear as directories in the query map directory
            nested_map_dirs = set()
            for map_entry in (system_info.get('maps') or []):
                map_key = list(map_entry.keys())[0]
                # Check if this map is nested under the current map (e.g., "FDs/bios/atom.zip")
                if map_key.startswith(map_name + '/'):
                    # Extract the immediate subdirectory (e.g., "bios" from "FDs/bios/atom.zip")
                    remainder = map_key[len(map_name) + 1:]
                    subdir = remainder.split('/')[0]
                    nested_map_dirs.add(subdir)
            
            # Add nested map directories as virtual directories
            if nested_map_dirs:
                logger.info(f"READDIR_DB_ONLY: adding {len(nested_map_dirs)} nested map directories: {nested_map_dirs}")
                for dir_name in sorted(nested_map_dirs):
                    # Insert at beginning so directories appear first
                    entries_to_send.insert(0, ('dir', dir_name, None))
            
            # Build system transform map for extension-based renaming
            system_transform_map = self._build_system_transform_map(path)
            
            # Send entries to client
            sent_count = 0
            for entry_id, (entry_type, display_name, file_record) in enumerate(entries_to_send, start=1):
                if entry_id <= start_id:
                    continue
                
                # Determine stat mode based on entry type
                if entry_type == 'dir':
                    # Directory entry
                    st_mode = 0o040555  # Directory, read-execute for all
                    size = 4096
                    stat_dict = {
                        'st_atime': int(time.time()),
                        'st_ctime': int(time.time()),
                        'st_mtime': int(time.time()),
                        'st_gid': 0,
                        'st_uid': 0,
                        'st_mode': st_mode,
                        'st_nlink': 2,  # Directories have at least 2 links (. and ..)
                        'st_size': size,
                    }
                else:
                    # File entry
                    source_path = file_record.get('source_path', '')
                    extension = file_record.get('extension', '').upper()
                    size = file_record.get('size', 0)
                    mtime = file_record.get('mtime', int(time.time()))
                    
                    # Create stat dict for file
                    now = int(time.time())
                    st_mtime = int(mtime) if mtime else now
                    stat_dict = {
                        'st_atime': st_mtime,
                        'st_ctime': st_mtime,
                        'st_mtime': st_mtime,
                        'st_gid': 0,
                        'st_uid': 0,
                        'st_mode': 0o100444,
                        'st_nlink': 1,
                        'st_size': size,
                    }
                    
                    # Apply transform renaming for files
                    if system_transform_map and file_record:
                        _, ext = os.path.splitext(file_record.get('filename', ''))
                        ext = ext[1:].upper() if ext else ""
                        # Try both uppercase and lowercase for case-insensitive lookup
                        pipeline = system_transform_map.get(ext) or system_transform_map.get(ext.lower())
                        if pipeline:
                            effective_ext = pipeline.get_effective_output_extension()
                            if effective_ext:
                                base_name, _ = os.path.splitext(display_name)
                                display_name = f"{base_name}.{effective_ext}"
                                logger.debug(f"READDIR_DB_ONLY: {file_record.get('filename', '')} -> {display_name}")
                
                entry_path = os.path.join(path, display_name)
                entry_inode = self._make_synthetic_inode(entry_path)
                self._add_path(entry_inode, entry_path)
                entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
                
                if not pyfuse3.readdir_reply(token, display_name.encode('utf-8'), entry, entry_id):
                    logger.info(f"READDIR_DB_ONLY: client buffer full after {sent_count} entries")
                    break
                sent_count += 1
            
            logger.info(f"READDIR_DB_ONLY: complete, sent {sent_count}/{len(entries_to_send)} entries")
            return False  # Successfully completed database-only readdir
            
        except Exception as e:
            logger.error(f"READDIR_DB_ONLY: error: {e}", exc_info=True)
            return True  # Fall back to filesystem

    async def _getattr_database_only(self, path: str, map_info: tuple):
        """
        Get file attributes using ONLY database queries (no filesystem lookup).
        
        This is used for files within query map directories.
        Returns stat_dict if found in database, None if should fall back.
        """
        client_name, system_name, map_name = map_info
        filename = os.path.basename(path)
        
        logger.info(f"GETATTR_DB_ONLY: {path} client={client_name} system={system_name} map={map_name} file={filename}")
        
        # If the basename IS the map name, we're at the map directory root itself — return
        # a virtual directory stat immediately rather than querying for a file named after the map.
        if filename == map_name:
            now = int(time.time())
            logger.info(f"GETATTR_DB_ONLY: {path} is the map directory root, returning virtual dir stat")
            return {
                'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                'st_gid': 0, 'st_uid': 0,
                'st_mode': 0o040555,
                'st_nlink': 2,
                'st_size': 4096,
            }
        
        try:
            # Handle virtual directories for preserve_structure query maps
            from pathutils import find_map_entry, get_map_config, get_query_config
            client_config = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
            if client_config:
                system_info = next((s for s in client_config.get('systems', []) if s['name'] == system_name), None)
                if system_info:
                    map_entry = find_map_entry(system_info, map_name)
                    if map_entry:
                        map_config = get_map_config(map_entry)
                        query_config = get_query_config(map_config)
                        if query_config and query_config.get('preserve_structure', False):
                            source_dir = query_config.get('source_dir', 'Software')
                            rel_parts = Path(path).parts[len(Path(self.mount_path).parts):]
                            try:
                                map_idx = rel_parts.index(map_name)
                                subpath_parts = rel_parts[map_idx + 1:] if len(rel_parts) > map_idx + 1 else []
                            except ValueError:
                                subpath_parts = rel_parts[3:] if len(rel_parts) > 3 else []
                            subpath = '/'.join(subpath_parts)

                            def build_dir_stat() -> dict:
                                now = int(time.time())
                                return {
                                    'st_atime': now,
                                    'st_ctime': now,
                                    'st_mtime': now,
                                    'st_gid': 0,
                                    'st_uid': 0,
                                    'st_mode': 0o040555,
                                    'st_nlink': 2,
                                    'st_size': 4096,
                                }

                            if not subpath:
                                return build_dir_stat()

                            try:
                                map_idx = rel_parts.index(map_name)
                                map_root_path = os.path.join(self.mount_path, *rel_parts[:map_idx + 1])
                            except ValueError:
                                map_root_path = os.path.join(self.mount_path, *rel_parts[:3])
                            cache_entry = self._db_readdir_cache.get(map_root_path)
                            if cache_entry:
                                cached_at, cached_files = cache_entry
                                if (time.time() - cached_at) <= self._db_readdir_cache_ttl:
                                    db_files = cached_files
                                else:
                                    self._db_readdir_cache.pop(map_root_path, None)
                                    db_files = None
                            else:
                                db_files = None

                            if db_files is None:
                                from db.queries import query_files_by_client_system_and_map
                                allowed_extensions = [str(ext).upper() for ext in query_config.get('extensions', []) if ext]
                                if query_config.get('transform_zip', False):
                                    for archive_ext in ('ZIP', '7Z'):
                                        if archive_ext not in allowed_extensions:
                                            allowed_extensions.append(archive_ext)
                                extension_filters = query_config.get('extension_filters', {}) or {}
                                db_files = query_files_by_client_system_and_map(
                                    client_name, system_name, map_name, allowed_extensions, extension_filters
                                )
                                self._db_readdir_cache[map_root_path] = (time.time(), db_files)

                            for file_record in db_files or []:
                                source_path = file_record.get('source_path', '')
                                rel_dir = ''
                                if source_path:
                                    normalized_source = source_path.replace('\\', '/')
                                    normalized_source_dir = (source_dir or '').replace('\\', '/').strip('/')
                                    marker = f"/{normalized_source_dir}/"
                                    if marker in normalized_source:
                                        relative_after_source_dir = normalized_source.split(marker, 1)[1]
                                        rel_dir = os.path.dirname(relative_after_source_dir).replace('\\', '/').strip('/')

                                if rel_dir == subpath or rel_dir.startswith(subpath + '/'):
                                    return build_dir_stat()

            # Query database for this specific file
            # First try exact virtual_path (supports preserve_structure subpaths),
            # then fall back to legacy client/system/map/filename lookup.
            from db.queries import query_file_by_client_system_map_and_name, query_file_by_virtual_path
            file_record = query_file_by_virtual_path(path)
            if not file_record:
                file_record = query_file_by_client_system_map_and_name(client_name, system_name, map_name, filename)
            
            if not file_record:
                logger.debug(f"GETATTR_DB_ONLY: file {filename} not found in database")
                return None  # Fall back to filesystem
            
            # Build stat structure from database record
            size = file_record.get('size', 0)
            mtime = file_record.get('mtime', int(time.time()))
            source_path = file_record.get('source_path', '')
            
            # For transformed files, check if we need to adjust size
            transformed_size = size
            # For zip-internal paths, resolve to the zip file for existence check
            _stat_check_path = source_path.split('#ZIP#', 1)[0] if source_path and '#ZIP#' in source_path else source_path
            if _stat_check_path and os.path.exists(_stat_check_path):
                try:
                    # Get transform pipeline for this file
                    from pathutils import find_map_entry, get_map_config
                    client_config = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
                    if client_config:
                        system_info = next((s for s in client_config.get('systems', []) if s['name'] == system_name), None)
                        if system_info:
                            map_entry = find_map_entry(system_info, map_name)
                            if map_entry:
                                map_config = get_map_config(map_entry)
                                if map_config:
                                    # Build transform map to get output size
                                    system_transform_map = self._build_system_transform_map(path)
                                    if system_transform_map:
                                        ext = file_record.get('extension', '').upper()
                                        pipeline = system_transform_map.get(ext) or system_transform_map.get(ext.lower())
                                        if pipeline:
                                            source_stat = os.lstat(source_path)
                                            transformed_size = self._get_transform_output_size(pipeline, source_stat.st_size)
                                            if transformed_size < 0:
                                                transformed_size = size
                                            logger.debug(f"GETATTR_DB_ONLY: applied transform for {filename}: {size} -> {transformed_size}")
                except Exception as e:
                    logger.debug(f"GETATTR_DB_ONLY: error applying transform: {e}")
            
            # Create stat structure
            stat_dict = {
                'st_atime': int(mtime) if mtime else int(time.time()),
                'st_ctime': int(mtime) if mtime else int(time.time()),
                'st_mtime': int(mtime) if mtime else int(time.time()),
                'st_gid': 0,
                'st_uid': 0,
                'st_mode': 0o100444,  # Regular file, read-only
                'st_nlink': 1,
                'st_size': transformed_size,
            }
            
            logger.info(f"GETATTR_DB_ONLY: returning stat for {filename} (size={transformed_size})")
            return stat_dict
            
        except Exception as e:
            logger.error(f"GETATTR_DB_ONLY: error: {e}", exc_info=True)
            return None  # Fall back to filesystem

    async def _open_database_only(self, path: str, map_info: tuple):
        """
        Resolve source path for opening using ONLY database queries.
        
        Returns either:
        - A string path to the source file (possibly with transforms)
        - A tuple (zip_path, internal_file) for zip archive files
        - None to fall back to filesystem resolution
        """
        client_name, system_name, map_name = map_info
        filename = os.path.basename(path)
        
        logger.info(f"OPEN_DB_ONLY: {path} client={client_name} system={system_name} map={map_name} file={filename}")
        
        try:
            # Query database for this specific file
            # First try exact virtual_path (supports preserve_structure subpaths),
            # then fall back to legacy client/system/map/filename lookup.
            from db.queries import query_file_by_client_system_map_and_name, query_file_by_virtual_path
            file_record = query_file_by_virtual_path(path)
            if not file_record:
                file_record = query_file_by_client_system_map_and_name(client_name, system_name, map_name, filename)
            
            if not file_record:
                logger.debug(f"OPEN_DB_ONLY: file {filename} not found in database")
                return None
            
            source_path = file_record.get('source_path')
            if not source_path:
                logger.warning(f"OPEN_DB_ONLY: no source_path in database for {filename}")
                return None
            
            # Handle zip-internal paths (stored as "/path/to/file.zip#ZIP#inner.bin")
            if '#ZIP#' in source_path:
                zip_path, inner_file = source_path.split('#ZIP#', 1)
                if not os.path.exists(zip_path):
                    logger.warning(f"OPEN_DB_ONLY: source zip does not exist: {zip_path}")
                    return None
                logger.info(f"OPEN_DB_ONLY: returning zip tuple ({zip_path}, {inner_file})")
                return (zip_path, inner_file)
            
            if not os.path.exists(source_path):
                logger.warning(f"OPEN_DB_ONLY: source file does not exist: {source_path}")
                return None
            
            # Check if this file needs transformation
            try:
                from sourcepath import get_transform_pipeline_for_file
                client_config = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
                if client_config:
                    system_info = next((s for s in client_config.get('systems', []) if s['name'] == system_name), None)
                    if system_info:
                        cache_config = self.config.get("cache", {})
                        pipeline = get_transform_pipeline_for_file(
                            logger,
                            system_info,
                            filename,
                            map_name,
                            cache_config,
                            full_path=source_path,
                        )
                        if pipeline:
                            logger.info(f"OPEN_DB_ONLY: {filename} needs transform pipeline")
                            return {'path': source_path, 'transform_pipeline': pipeline}
            except Exception as e:
                logger.debug(f"OPEN_DB_ONLY: error checking transform: {e}")
            
            logger.info(f"OPEN_DB_ONLY: returning source path {source_path}")
            return source_path
            
        except Exception as e:
            logger.error(f"OPEN_DB_ONLY: error: {e}", exc_info=True)
            return None

    async def readdir(self, fh: FileHandleT, start_id: int, token):
        """
        Read directory entries with FULL attributes (readdirplus support).
        Optimized to batch-resolve virtual paths and use cache efficiently.
        Database-only mode for query map directories.
        """
        t_start = time.time()
        path = self._inode_to_path(fh)
        # Normalize to virtual path for consistency
        path = self._normalize_to_virtual_path(path)
        logger.info("READDIR START: path=%s start_id=%d", path, start_id)
        
        # Try database-only mode for query map directories first
        map_info = self._extract_map_info(path)
        if map_info:
            logger.info(f"READDIR: detected query map directory, using database-only mode")
            should_fallback = await self._readdir_database_only(path, start_id, token, map_info)
            if not should_fallback:
                return  # Successfully completed database-only readdir
            logger.info(f"READDIR: database-only mode failed, falling back to filesystem")
        
        # Try database mode first if enabled and path is suitable
        if self._can_use_database(path):
            try:
                logger.info(f"READDIR: using database mode for {path}")
                
                # Get allowed entries from config using parse_trans_path
                t_config_start = time.time()
                config_cache_entry = self._config_readdir_cache.get(path)
                if config_cache_entry:
                    config_cached_at, config_cached_entries = config_cache_entry
                    if (time.time() - config_cached_at) <= self._config_readdir_cache_ttl:
                        config_entries = config_cached_entries
                    else:
                        self._config_readdir_cache.pop(path, None)
                        config_entries = None
                else:
                    config_entries = None

                if config_entries is None:
                    config_entries = list(parse_trans_path(self.config, self.root, path))
                    self._config_readdir_cache[path] = (time.time(), config_entries)
                t_config = time.time() - t_config_start
                logger.info(f"READDIR DATABASE: config allows {len(config_entries)} entries (parsed in {t_config:.4f}s)")
                
                # Build system transform map for efficient extension-based renaming
                system_transform_map = self._build_system_transform_map(path)
                
                # Get entries from database
                cache_entry = self._db_readdir_cache.get(path)
                if cache_entry:
                    cached_at, cached_db_entries = cache_entry
                    if (time.time() - cached_at) <= self._db_readdir_cache_ttl:
                        db_entries = cached_db_entries
                    else:
                        self._db_readdir_cache.pop(path, None)
                        db_entries = None
                else:
                    db_entries = None

                if db_entries is None:
                    db_entries = self.data_adapter.readdir_entries(path)
                    self._db_readdir_cache[path] = (time.time(), db_entries)
                logger.info(f"READDIR DATABASE: got {len(db_entries) if db_entries else 0} entries from adapter")
                
                # NOTE: We don't filter stale entries here to avoid connection pool exhaustion
                # Stale entries will be caught in GETATTR when individual files are accessed
                
                # If we have config_entries but no db_entries, or if config_entries don't look like files,
                # create synthetic directory entries for them (handles category paths and map directories)
                entries_to_send = []
                if config_entries:
                    # Classify config entries using per-entry shape instead of extension variety.
                    # A map containing a single file type (e.g., only .cue) must still be treated as files.
                    config_entries_set = set(config_entries)
                    file_like_count = sum(1 for e in config_entries if os.path.splitext(e)[1])
                    dir_like_count = len(config_entries) - file_like_count
                    looks_like_files = file_like_count > 0 and dir_like_count == 0
                    looks_like_dirs = dir_like_count > 0 and file_like_count == 0
                    
                    logger.info(f"READDIR DATABASE: config_entries look_like_files={looks_like_files}, look_like_dirs={looks_like_dirs}")
                    
                    if dir_like_count > 0:
                        # Handle configs with dir-like entries (pure-dir or mixed dir+file).
                        # Dir-like entries become synthetic directories; file-like entries are
                        # looked up by name in db_entries (they may be absent at this path level).
                        db_entries_by_name = {ename: estat for ename, estat in db_entries} if db_entries else {}
                        sent_count = 0
                        logger.info(f"READDIR DATABASE: creating entries for {len(config_entries)} config entries (dir={dir_like_count}, file={file_like_count})")
                        for entry_id, entry_name in enumerate(config_entries, start=1):
                            if entry_id <= start_id:
                                continue
                            
                            entry_path = os.path.join(path, entry_name)
                            is_dir_entry = not os.path.splitext(entry_name)[1]
                            
                            if is_dir_entry:
                                # Synthetic directory stat
                                now = int(time.time())
                                stat_dict = {
                                    'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                                    'st_gid': 0, 'st_uid': 0,
                                    'st_mode': 0o040555,  # Directory, read-only
                                    'st_nlink': 2,
                                    'st_size': 0,
                                }
                            else:
                                # File entry — look up by name in DB entries at this path level
                                stat_dict = db_entries_by_name.get(entry_name)
                                if stat_dict is None:
                                    # DB can legitimately miss explicit file maps under shared
                                    # category paths (e.g., /RetroBat/bios/panafz1.bin). Resolve
                                    # from source mapping and synthesize file attrs.
                                    resolved = get_source_path(logger, self.config, self.mount_path, entry_path)
                                    if isinstance(resolved, dict):
                                        resolved = resolved.get('path')
                                    if isinstance(resolved, str) and os.path.isfile(resolved):
                                        st = os.lstat(resolved)
                                        stat_dict = {
                                            'st_atime': int(st.st_atime),
                                            'st_ctime': int(st.st_ctime),
                                            'st_mtime': int(st.st_mtime),
                                            'st_gid': st.st_gid,
                                            'st_uid': st.st_uid,
                                            'st_mode': st.st_mode,
                                            'st_nlink': 1,
                                            'st_size': st.st_size,
                                        }
                                    else:
                                        continue  # Not present at this level, skip
                            
                            entry_inode = self._make_synthetic_inode(entry_path)
                            self._add_path(entry_inode, entry_path)
                            entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
                            
                            if not pyfuse3.readdir_reply(token, entry_name.encode('utf-8'), entry, entry_id):
                                break
                            sent_count += 1
                        
                        logger.info(f"READDIR DATABASE: sent {sent_count} entries")
                        return
                
                # Otherwise, filter database entries against config (if config specifies entries)
                # If config_entries is empty, send all database entries (query map mode)
                if db_entries:
                    should_filter = len(config_entries) > 0
                    config_entries_set = set(config_entries) if should_filter else set()
                    sent_count = 0
                    filtered_count = 0
                    for entry_id, (entry_name, stat_dict) in enumerate(db_entries, start=1):
                        if entry_id <= start_id:
                            continue
                        
                        # Filter: only send entries that are allowed by config (if filtering is enabled)
                        if should_filter and entry_name not in config_entries_set:
                            filtered_count += 1
                            continue
                            
                        entry_path = os.path.join(path, entry_name)
                        # Fix misclassified directory entries for file-like names
                        if (
                            "." in entry_name
                            and stat_dict.get('st_nlink') == 2
                            and stat_dict.get('st_mode', 0) & 0o040000
                        ):
                            resolved = get_source_path(logger, self.config, self.mount_path, entry_path)
                            if isinstance(resolved, dict):
                                resolved = resolved.get('path')
                            if isinstance(resolved, tuple):
                                zip_path, internal_file = resolved
                                import zippath
                                full_internal = os.path.join(zip_path, internal_file)
                                info = zippath.getinfo(full_internal)
                                if info and not info.get('is_dir', False):
                                    now = int(os.path.getmtime(zip_path))
                                    stat_dict = {
                                        'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                                        'st_gid': 0, 'st_uid': 0,
                                        'st_mode': 0o100444,
                                        'st_nlink': 1,
                                        'st_size': info.get('size', 0),
                                    }
                            elif isinstance(resolved, str) and os.path.exists(resolved) and not os.path.isdir(resolved):
                                st = os.lstat(resolved)
                                stat_dict = {
                                    'st_atime': int(st.st_atime), 'st_ctime': int(st.st_ctime),
                                    'st_mtime': int(st.st_mtime), 'st_gid': st.st_gid,
                                    'st_uid': st.st_uid, 'st_mode': st.st_mode,
                                    'st_nlink': 1, 'st_size': st.st_size,
                                }
                        entry_inode = self._make_synthetic_inode(entry_path)
                        self._add_path(entry_inode, entry_path)
                        entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
                        
                        # Apply transform renaming using system transform map
                        display_name = entry_name
                        if system_transform_map:
                            _, ext = os.path.splitext(entry_name)
                            ext = ext[1:].upper() if ext else ""
                            pipeline = system_transform_map.get(ext) or system_transform_map.get(ext.lower())
                            logger.info(f"READDIR database: entry={entry_name}, ext={ext}, pipeline={pipeline is not None}")
                            if pipeline:
                                effective_ext = pipeline.get_effective_output_extension()
                                logger.info(f"READDIR database: effective_ext={effective_ext}")
                                if effective_ext:
                                    base_name, _ = os.path.splitext(entry_name)
                                    display_name = f"{base_name}.{effective_ext}"
                                    logger.info(f"READDIR database: Renamed {entry_name} -> {display_name}")
                        
                        if not pyfuse3.readdir_reply(token, display_name.encode('utf-8'), entry, entry_id):
                            break
                        sent_count += 1
                    t_total = time.time() - t_start
                    logger.info(f"READDIR DATABASE: sent {sent_count} entries, filtered {filtered_count}, total time {t_total:.4f}s")
                    return
            except Exception as e:
                logger.error(f"READDIR DATABASE mode error for {path}: {e}", exc_info=True)

        xfull_path = path
        # Get the real source path for this directory (handles virtual mappings)
        t_source_path_start = time.time()
        parent_source = get_source_path(logger, self.config, self.mount_path, xfull_path)
        t_source_path = time.time() - t_source_path_start
        if t_source_path > 0.1:
            logger.warning(f"READDIR SLOW: get_source_path took {t_source_path:.3f}s for {xfull_path}")

        if isinstance(parent_source, dict) and 'path' in parent_source:
            parent_dir = parent_source['path']
        elif isinstance(parent_source, str):
            parent_dir = parent_source
        else:
            parent_dir = xfull_path.replace("/mnt/transfs", "/mnt/filestorefs")

        logger.info(f"READDIR: xfull_path={xfull_path}, parent_dir={parent_dir}")

        # Parse virtual entries
        t_parse_start = time.time()
        virtual_entries = list(parse_trans_path(self.config, self.root, xfull_path))
        t_parse = time.time() - t_parse_start
        logger.info(f"READDIR: parse_trans_path returned {len(virtual_entries)} entries: {virtual_entries}")

        # Detect if this is a query map directory (e.g., /MiSTer/Apple-II/FDs)
        # or a nested file map virtual directory (e.g., /MiSTer/BBCMicro/bios from bios/atom.zip)
        is_query_map_dir = False
        is_nested_file_map_dir = False
        is_unzipped_file_map_dir = False
        try:
            from pathutils import get_client, get_system_info, find_map_entry, get_map_config, is_query_map
            rel_parts = Path(xfull_path).parts[len(Path(self.root).parts):]
            if len(rel_parts) >= 3:
                client = get_client(self.config, rel_parts)
                if client:
                    path_template_parts = Path(client['default_target_path']).parts
                    system_info = get_system_info(client, list(rel_parts), path_template_parts)
                    if system_info:
                        map_name = rel_parts[2]
                        map_entry = find_map_entry(system_info, map_name)
                        map_config = get_map_config(map_entry)
                        is_query_map_dir = bool(map_config and is_query_map(map_config))
                        
                        # Check if this is a file-based unzipped map
                        # e.g., map_config has 'file' with 'unzip: true'
                        is_unzipped_file_map_dir = False
                        if not is_query_map_dir and map_config:
                            file_spec = map_config.get('file')
                            if isinstance(file_spec, dict):
                                is_unzipped_file_map_dir = file_spec.get('unzip', False)
                            elif file_spec and isinstance(map_config.get('unzip'), bool):
                                is_unzipped_file_map_dir = map_config.get('unzip', False)
                            if is_unzipped_file_map_dir:
                                logger.info(f"READDIR: detected unzipped file map directory: {map_name}")
                        
                        # Check if this is a nested file map virtual directory
                        # e.g., map_name="bios" and we have a map "bios/atom.zip"
                        if not is_query_map_dir and not is_unzipped_file_map_dir:
                            is_nested_file_map_dir = any(
                                list(m.keys())[0].startswith(map_name + '/')
                                for m in (system_info.get('maps') or [])
                            )
                            if is_nested_file_map_dir:
                                logger.info(f"READDIR: detected nested file map virtual directory: {map_name}")
        except Exception:
            pass

        # Fast-path for query map directories, unzipped file maps, and nested file map virtual directories
        # This avoids per-entry resolution and stat, keeping listings responsive.
        if (is_query_map_dir or is_nested_file_map_dir or is_unzipped_file_map_dir) and virtual_entries:
            # Build system transform map once for efficient extension-based renaming
            system_transform_map = self._build_system_transform_map(xfull_path)
            logger.info(f"READDIR fast-path: built transform map with {len(system_transform_map)} extensions")
            
            sent_count = 0
            for entry_id, entry_name in enumerate(virtual_entries, start=1):
                if entry_id <= start_id:
                    continue
                entry_path = os.path.join(xfull_path, entry_name)
                entry_inode = self._make_synthetic_inode(entry_path)
                now = int(time.time())
                stat_dict = {
                    'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                    'st_gid': 0, 'st_uid': 0,
                    'st_mode': 0o100444, 'st_nlink': 1, 'st_size': 0,
                }
                entry = self._dict_to_entry_attributes(stat_dict, entry_inode, cache_timeout=1.0)
                
                # Apply transform renaming using system transform map
                display_name = entry_name
                if system_transform_map:
                    _, ext = os.path.splitext(entry_name)
                    ext = ext[1:].upper() if ext else ""
                    pipeline = system_transform_map.get(ext) or system_transform_map.get(ext.lower())
                    if pipeline:
                        effective_ext = pipeline.get_effective_output_extension()
                        if effective_ext:
                            base_name, _ = os.path.splitext(entry_name)
                            display_name = f"{base_name}.{effective_ext}"
                            logger.debug(f"READDIR fast-path: Renamed {entry_name} -> {display_name}")
                
                if not pyfuse3.readdir_reply(token, display_name.encode('utf-8'), entry, entry_id):
                    logger.info(f"READDIR: client buffer full after {sent_count} entries (fast query map)")
                    break
                sent_count += 1
            
            t_total = time.time() - t_start
            logger.info(
                f"READDIR COMPLETE: {path} entries={len(virtual_entries)} sent={sent_count} "
                f"cache_hits=0 hit_rate=0.0% parse={t_parse:.4f}s batch=0.0000s total={t_total:.4f}s"
            )
            return

        # Determine hierarchy level to decide if implicit mappings are allowed
        # Level 0 (root): /mnt/transfs - only show clients from config
        # Level 1: /mnt/transfs/MiSTer - only show systems from config
        # Level 2: /mnt/transfs/MiSTer/Amstrad - only show maps from config
        # Level 3+: Allow implicit real files/dirs to appear
        root_parts = Path(self.root).parts
        path_parts = Path(xfull_path).parts
        hierarchy_level = len(path_parts) - len(root_parts)
        allow_implicit_entries = hierarchy_level >= 3

        cache_config = self.config.get("cache", {})
        direntry_cache_enabled = cache_config.get("readdir_direntry_cache_enabled", True)
        skip_cache_lookup_enabled = cache_config.get("readdir_skip_cache_lookup_with_direntry", True)
        max_readdir_getattr_cache = cache_config.get("readdir_getattr_cache_max_entries", 300)
        fast_listing_threshold = cache_config.get("readdir_fast_listing_threshold", 500)
        virtual_fast_listing_threshold = cache_config.get(
            "readdir_fast_listing_threshold_virtual",
            fast_listing_threshold,
        )

        # Add real directory entries using scandir for better performance
        # scandir() returns DirEntry objects with cached stat info, avoiding extra stat() calls
        dir_entry_cache = {}
        parent_dir_mtime = None

        # Determine if we need to scan multiple extension subdirectories
        # This happens when filetypes like "A52,BIN,ROM" map to subdirs A52/, BIN/, ROM/
        # CRITICAL: Only process KNOWN extension subdirectories to avoid scanning non-extension dirs
        extension_subdirs = []
        known_extension_subdirs = {'A52', 'BIN', 'ROM', 'TMP', 'CDT', 'CRT', 'CAS', 'TAP'}
        if allow_implicit_entries and os.path.isdir(parent_dir):
            parent_parent = os.path.dirname(parent_dir)
            current_subdir_name = os.path.basename(parent_dir)
            
            # Only process if current dir is in the whitelist of known extension subdirectories
            is_known_extension_subdir = current_subdir_name in known_extension_subdirs
            parent_is_known_extension_subdir = False
            relative_subpath = ""
            
            if not is_known_extension_subdir:
                # Check if parent directory is a known extension subdir (for nested cases like A52/Prototype Games/)
                parent_of_parent = os.path.basename(parent_parent)
                if parent_of_parent in known_extension_subdirs:
                    parent_is_known_extension_subdir = True
                    relative_subpath = current_subdir_name
                    parent_parent = os.path.dirname(parent_parent)
                    current_subdir_name = parent_of_parent
            
            if is_known_extension_subdir or parent_is_known_extension_subdir:
                try:
                    # Use scandir for efficiency - it returns DirEntry with cached is_dir info
                    with os.scandir(parent_parent) as entries:
                        siblings = []
                        for entry in entries:
                            if (entry.name != current_subdir_name and 
                                entry.name in known_extension_subdirs and
                                entry.is_dir()):
                                siblings.append(entry.name)
                        
                        if siblings:
                            if relative_subpath:
                                # We're in a nested directory, so scan sibling extension dirs + relative path
                                extension_subdirs = [os.path.join(parent_parent, s, relative_subpath) 
                                                    for s in siblings
                                                    if os.path.isdir(os.path.join(parent_parent, s, relative_subpath))]
                            else:
                                # We're at the top level of extension dirs
                                extension_subdirs = [os.path.join(parent_parent, s) for s in siblings]
                            logger.debug(f"READDIR: found extension subdirs to merge: {siblings} (relative_subpath={relative_subpath})")
                except OSError as e:
                    logger.debug(f"READDIR: failed to list extension subdirs: {e}")
        
        if allow_implicit_entries and os.path.isdir(parent_dir):  # Scan the SOURCE directory, not virtual path
            existing = set(virtual_entries)
            
            # Scan the main directory
            try:
                # Get parent directory mtime once for cache validation
                parent_dir_mtime = os.path.getmtime(parent_dir)
                
                # Check if hidden files should be shown
                show_hidden = self.config.get('show_hidden_files', True)
                
                with os.scandir(parent_dir) as entries:
                    for entry in entries:
                        # Skip hidden files (starting with .) if show_hidden_files is False
                        # Skip subdirectories that are extension folders (they'll be merged)
                        if not show_hidden and entry.name.startswith('.'):
                            continue
                        if entry.is_dir() and entry.name.isupper() and 2 <= len(entry.name) <= 4:
                            continue  # Skip extension subdirs like BIN/, ROM/, A52/
                        if direntry_cache_enabled:
                            dir_entry_cache[entry.name] = entry
                        if entry.name not in existing:
                            virtual_entries.append(entry.name)
                            logger.debug(f"READDIR: added filesystem entry: {entry.name}")
                            # Cache the DirEntry object for later stat access
                            if not direntry_cache_enabled:
                                dir_entry_cache[entry.name] = entry
            except OSError as e:
                logger.warning(f"READDIR: scandir failed for {parent_dir}: {e}")
            
            # Also scan extension subdirectories if found
            for ext_subdir in extension_subdirs:
                try:
                    with os.scandir(ext_subdir) as entries:
                        for entry in entries:
                            if not show_hidden and entry.name.startswith('.'):
                                continue
                            if entry.name not in existing:
                                logger.debug(f"READDIR: adding {entry.name} from extension subdir")
                                virtual_entries.append(entry.name)
                                existing.add(entry.name)
                                # Important: cache DirEntry for files from extension subdirs
                                # BUT we need to adjust the path resolution later
                                if direntry_cache_enabled or entry.name not in dir_entry_cache:
                                    # Store with a marker that this came from an extension subdir
                                    dir_entry_cache[entry.name] = entry
                except OSError as e:
                    logger.debug(f"READDIR: scandir failed for extension subdir: {e}")
        
        # Deduplicate entries while preserving order
        if virtual_entries:
            deduped_entries = []
            seen_entries = set()
            for entry_name in virtual_entries:
                if entry_name in seen_entries:
                    continue
                seen_entries.add(entry_name)
                deduped_entries.append(entry_name)
            virtual_entries = deduped_entries

        # BIOS directories are physical-file backed; drop stale DB-only ghost entries.
        # This prevents long delete stalls on files that no longer exist on disk.
        if '/bios/' in xfull_path.lower() and dir_entry_cache:
            original_count = len(virtual_entries)
            virtual_entries = [entry_name for entry_name in virtual_entries if entry_name in dir_entry_cache]
            removed_count = original_count - len(virtual_entries)
            if removed_count > 0:
                logger.info(
                    "READDIR: pruned %d stale BIOS virtual entries (kept %d physical)",
                    removed_count,
                    len(virtual_entries)
                )
        
        # Optimize for Native paths - skip expensive get_source_path() call
        is_native_path = parent_dir.startswith("/mnt/filestorefs/Native/")
        
        # Build system-level transform map for this directory (MAJOR OPTIMIZATION)
        # Instead of calling get_source_path() 400+ times, build the map once
        t_transform_map_start = time.time()
        system_transform_map = self._build_system_transform_map(xfull_path)
        t_transform_map = time.time() - t_transform_map_start
        
        if system_transform_map:
            logger.info(f"READDIR: Built system_transform_map with {len(system_transform_map)} extensions: {list(system_transform_map.keys())}")
        
        logger.debug(f"READDIR: {len(virtual_entries)} entries parsed from {parent_dir}")
        
        # Batch get source paths for ALL entries (much faster than one-by-one)
        t_batch_start = time.time()
        source_paths = {}
        t_cache_check = 0
        t_path_resolve = 0
        t_get_source_path = 0
        get_source_path_calls = 0
        cache_checked = 0
        cache_hits = 0  # Track cache hits in batch phase
        
        # Skip expensive cache lookups if we have DirEntry cache for all entries
        skip_cache_lookup = False
        if skip_cache_lookup_enabled and dir_entry_cache:
            missing_entries = [name for name in virtual_entries if name not in dir_entry_cache]
            if not missing_entries:
                skip_cache_lookup = True
            else:
                logger.info(f"READDIR: skip_cache_lookup=False, missing {len(missing_entries)} entries from DirEntry cache (total virtual_entries={len(virtual_entries)}, dir_entry_cache={len(dir_entry_cache)})")
                skip_cache_lookup = all(
                    is_virtual_path(self.config, self.mount_path, os.path.join(xfull_path, entry_name))
                    for name in missing_entries
                )
                if skip_cache_lookup:
                    logger.info(f"READDIR: skip_cache_lookup=True via virtual path check")
        else:
            if not skip_cache_lookup_enabled:
                logger.info(f"READDIR: skip_cache_lookup disabled in config")
            elif not dir_entry_cache:
                logger.info(f"READDIR: no DirEntry cache available")
        
        logger.info(f"READDIR: skip_cache_lookup={skip_cache_lookup}, dir_entry_cache_size={len(dir_entry_cache)}, virtual_entries_size={len(virtual_entries)}")
        
        is_virtual_browse = (
            path.startswith(self.mount_path)
            and not path.startswith(os.path.join(self.mount_path, "Native"))
        )
        threshold = virtual_fast_listing_threshold if is_virtual_browse else fast_listing_threshold
        fast_listing = len(virtual_entries) > threshold
        # Skip getattr cache for very large directories to reduce cache churn
        skip_getattr_cache = len(virtual_entries) > max_readdir_getattr_cache

        # OPTIMIZATION: Only batch-process entries for this pagination batch, not the entire directory
        # This avoids processing 759 entries when we'll only send 24, improving perf by ~30x for large dirs
        batch_size = 24  # Standard FUSE readdir batch size
        batch_start_idx = max(0, start_id)  # Convert start_id to array index
        batch_end_idx = min(len(virtual_entries), batch_start_idx + batch_size)
        batch_entries = virtual_entries[batch_start_idx:batch_end_idx]
        
        # Note: We still need to track total entries for send phase, but only process this batch
        logger.debug(f"READDIR: batch pagination start_id={start_id} batch_entries={len(batch_entries)}/{len(virtual_entries)}")

        for entry_name in batch_entries:
            entry_path = os.path.join(xfull_path, entry_name)
            
            # PRIORITY 1: Always check getattr cache FIRST, before any other resolution
            # This is critical for files with transforms which would otherwise be expensive
            cached = get_cached_getattr(entry_path, parent_dir)
            if cached:
                source_paths[entry_name] = ('cached', cached)
                # Don't increment cache_hits here - it will be counted in send phase
                continue
            
            # Fast path: Pre-stat using DirEntry cache to avoid send-phase filesystem calls
            # This is a HUGE optimization for all large directories (100+ files)
            # IMPORTANT: Check this for EVERY entry, not just when skip_cache_lookup is True
            # This allows optimization for physical files even when virtual entries exist
            if skip_cache_lookup_enabled and entry_name in dir_entry_cache:
                # Pre-stat using DirEntry.is_dir() (fast), cache the result for send phase
                de = dir_entry_cache[entry_name]
                try:
                    st = de.stat(follow_symlinks=False)
                    is_dir = de.is_dir(follow_symlinks=False)
                    stat_dict = {
                        'st_atime': int(st.st_atime), 'st_ctime': int(st.st_ctime), 'st_mtime': int(st.st_mtime),
                        'st_gid': int(st.st_gid), 'st_uid': int(st.st_uid),
                        'st_mode': 0o040755 if is_dir else 0o100444,
                        'st_nlink': 2 if is_dir else 1,
                        'st_size': int(st.st_size) if not is_dir else 4096,
                    }
                    source_paths[entry_name] = ('cached', stat_dict)
                    cache_hits += 1  # Count pre-caching as cache hit
                    continue
                except OSError:
                    pass  # Fall through to normal path
            
            # For directories with system transform map, try direct transform application
            if skip_cache_lookup and system_transform_map:
                _, ext = os.path.splitext(entry_name)
                ext = ext[1:].upper() if ext else ""
                if ext in system_transform_map:
                    # Direct transform application without get_source_path!
                    # Build proper source path - different extensions may be in different subdirectories
                    # e.g., DSK files in Software/DSK/, 2MG files in Software/2MG/
                    # Or BIN files in Software/BIN/, ROM files in Software/ROM/ (Atari 5200)
                    
                    # Check if there's a subdirectory matching the extension
                    ext_subdir = os.path.join(parent_dir, ext)
                    if os.path.isdir(ext_subdir):
                        fspath = os.path.join(ext_subdir, entry_name)
                    elif parent_dir.endswith(f'/{ext}'):
                        # Already in the extension-specific directory, use as-is
                        fspath = os.path.join(parent_dir, entry_name)
                    elif parent_dir.endswith('/DSK') and ext == '2MG':
                        # .2mg file is actually in the 2MG sibling directory
                        source_dir = parent_dir[:-3] + '2MG'
                        fspath = os.path.join(source_dir, entry_name)
                    elif parent_dir.endswith('/2MG') and ext == 'DSK':
                        # .dsk file is actually in the DSK sibling directory  
                        source_dir = parent_dir[:-3] + 'DSK'
                        fspath = os.path.join(source_dir, entry_name)
                    else:
                        # Fallback: file in parent directory directly
                        fspath = os.path.join(parent_dir, entry_name)
                    
                    pipeline = system_transform_map[ext]
                    source_paths[entry_name] = ('uncached', {'path': fspath, 'transform_pipeline': pipeline})
                    continue
            
            # Fallback: resolve source path normally
            if is_native_path:
                fspath = os.path.join(parent_dir, entry_name)
            else:
                t_gsp = time.time()
                fspath = get_source_path(logger, self.config, self.mount_path, entry_path)
                t_get_source_path += time.time() - t_gsp
                get_source_path_calls += 1
                # Cache the source path for getattr to reuse (major optimization for large dirs)
                self._source_path_cache[entry_path] = fspath
            source_paths[entry_name] = ('uncached', fspath)
        
        t_batch = time.time() - t_batch_start
        logger.info(f"READDIR BATCH: {len(batch_entries)}/{len(virtual_entries)} entries, transform_map={len(system_transform_map)} exts, get_source_path={get_source_path_calls} calls, time={t_batch:.4f}s skip_cache={skip_cache_lookup}")
        
        # Send entries with full attributes
        # Note: cache_hits was already accumulated in batch phase, don't reset it
        sent_count = 0
        t_send_start = time.time()
        t_attr_creation = 0.0
        t_readdir_reply = 0.0
        
        for entry_id, entry_name in enumerate(batch_entries, start=batch_start_idx + 1):
            entry_path = os.path.join(xfull_path, entry_name)
            
            # Determine inode: use actual inode for real files, synthetic for virtual
            entry_inode = self._make_synthetic_inode(entry_path)
            
            # Check if this is a real file/directory and use its actual inode for consistency
            source_type, source_data = source_paths[entry_name]
            fspath = source_data
            if isinstance(fspath, dict):
                fspath = fspath.get('path')
            
            filestore_root = self.config.get("filestore", "/mnt/filestorefs") if isinstance(self.config, dict) else "/mnt/filestorefs"
            use_actual_inode = (
                isinstance(fspath, str)
                and os.path.exists(fspath)
                and os.path.normpath(fspath) != os.path.normpath(filestore_root)
            )

            if use_actual_inode:
                try:
                    stat = os.lstat(fspath)
                    entry_inode = stat.st_ino
                except (OSError, FileNotFoundError):
                    pass  # Fall back to synthetic inode if stat fails
            
            self._add_path(entry_inode, entry_path)
            
            # Get attributes from cache or source path
            source_type, source_data = source_paths[entry_name]
            
            if source_type == 'cached':
                # Use cached attributes
                entry = self._dict_to_entry_attributes(source_data, entry_inode)
                cache_hits += 1
            else:
                # Build attributes from source path
                fspath = source_data
                pipeline = None
                
                # Check if this is a dict with transform pipeline
                if isinstance(fspath, dict):
                    pipeline = fspath.get('transform_pipeline')
                    fspath = fspath.get('path')
                
                zip_mode = self._get_zip_mode_for_path(entry_path)
                
                try:
                    # Handle different path types
                    if isinstance(fspath, tuple):
                        # Zip internal file
                        zip_path, internal_file = fspath
                        import zippath
                        full_internal = os.path.join(zip_path, internal_file)
                        info = zippath.getinfo(full_internal)
                        if info:
                            now = int(os.path.getmtime(zip_path))
                            stat_dict = {
                                'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                                'st_gid': 0, 'st_uid': 0,
                                'st_mode': 0o040555 if info['is_dir'] else 0o100444,
                                'st_nlink': 2 if info['is_dir'] else 1,
                                'st_size': 0 if info['is_dir'] else info['size'],
                            }
                            if not skip_getattr_cache:
                                cache_getattr(entry_path, parent_dir, stat_dict)
                            entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
                        else:
                            continue
                    elif isinstance(fspath, str) and is_supported_archive_name(fspath):
                        # Archive file itself
                        st = os.lstat(fspath)
                        is_dir = zip_mode == "hierarchical"
                        stat_dict = {
                            'st_atime': int(st.st_atime), 'st_ctime': int(st.st_ctime),
                            'st_mtime': int(st.st_mtime), 'st_gid': st.st_gid,
                            'st_uid': st.st_uid,
                            'st_mode': 0o040755 if is_dir else 0o100444,
                            'st_nlink': 2 if is_dir else 1,
                            'st_size': 4096 if is_dir else st.st_size,
                        }
                        if not skip_getattr_cache:
                            cache_getattr(entry_path, parent_dir, stat_dict)
                        entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
                    elif isinstance(fspath, str):
                        # PRIORITY 1: Check getattr cache first (even for transforms!)
                        cached_stat = get_cached_getattr(entry_path, parent_dir)
                        if cached_stat:
                            # Note: This shouldn't normally happen since cached files are handled in batch phase
                            # but keep this check as fallback for edge cases
                            logger.debug(f"READDIR: unexpected cache hit in send phase for {entry_name}")
                            entry = self._dict_to_entry_attributes(cached_stat, entry_inode)
                        # PRIORITY 2: Use cached DirEntry stat if available (avoids extra stat!)
                        # BUT: If there's a pipeline, we can't trust DirEntry cache (file may be from different source dir)
                        elif not pipeline and entry_name in dir_entry_cache:
                            # Fast path: use cached DirEntry info; skip stat in large directories
                            de = dir_entry_cache[entry_name]
                            logger.debug(f"READDIR: using DirEntry cache for {entry_name}")
                            try:
                                if fast_listing:
                                    is_dir = de.is_dir(follow_symlinks=False)
                                    now = int(time.time())
                                    stat_dict = {
                                        'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                                        'st_gid': 0, 'st_uid': 0,
                                        'st_mode': 0o040755 if is_dir else 0o100444,
                                        'st_nlink': 2 if is_dir else 1,
                                        'st_size': 4096 if is_dir else 0,
                                    }
                                else:
                                    st = de.stat(follow_symlinks=False)
                                    stat_dict = {
                                        'st_atime': int(st.st_atime), 'st_ctime': int(st.st_ctime),
                                        'st_mtime': int(st.st_mtime), 'st_gid': st.st_gid,
                                        'st_uid': st.st_uid, 'st_mode': st.st_mode,
                                        'st_nlink': 1, 'st_size': st.st_size,
                                    }
                                cache_getattr(entry_path, parent_dir, stat_dict)
                                entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
                            except OSError as e:
                                logger.warning(f"READDIR: DirEntry.stat() failed for {entry_name}: {e}")
                                continue
                        elif os.path.exists(fspath):
                            logger.debug(f"READDIR: statting {entry_name} at {fspath}")
                            # Stat the actual source file
                            st = os.lstat(fspath)
                            
                            # If there's a transform pipeline, override mode and size
                            if pipeline:
                                st_mode = 0o100444  # Regular file, read-only
                                st_size = self._get_transform_output_size(pipeline, st.st_size, fspath)
                            else:
                                st_mode = st.st_mode
                                st_size = st.st_size
                            
                            stat_dict = {
                                'st_atime': int(st.st_atime), 'st_ctime': int(st.st_ctime),
                                'st_mtime': int(st.st_mtime), 'st_gid': st.st_gid,
                                'st_uid': st.st_uid, 'st_mode': st_mode,
                                'st_nlink': 1, 'st_size': st_size,
                            }
                            cache_getattr(entry_path, parent_dir, stat_dict)
                            entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
                        else:
                            logger.debug(f"READDIR FALLBACK: {entry_name} - fspath does not exist")
                            # File doesn't exist at expected path - might be in extension subdir
                            # Try checking extension-based subdirectory
                            _, ext = os.path.splitext(entry_name)
                            if ext:
                                ext_upper = ext[1:].upper()  # Remove dot and uppercase
                                parent_parent = os.path.dirname(parent_dir)
                                current_subdir = os.path.basename(parent_dir)
                                
                                # Check if we're in a nested directory within an extension subdir
                                # Pattern 1: /Software/A52/ -> check /Software/BIN/
                                # Pattern 2: /Software/A52/Prototype Games/ -> check /Software/BIN/Prototype Games/
                                relative_subpath = ""
                                if not (current_subdir.isupper() and 2 <= len(current_subdir) <= 4):
                                    # We might be in a subdirectory of an extension dir
                                    grandparent = os.path.dirname(parent_parent)
                                    parent_of_parent = os.path.basename(parent_parent)
                                    if parent_of_parent.isupper() and 2 <= len(parent_of_parent) <= 4:
                                        # We're nested, adjust paths
                                        relative_subpath = current_subdir
                                        parent_parent = grandparent
                                
                                if relative_subpath:
                                    ext_subdir_path = os.path.join(parent_parent, ext_upper, relative_subpath, entry_name)
                                else:
                                    ext_subdir_path = os.path.join(parent_parent, ext_upper, entry_name)
                                    
                                if os.path.exists(ext_subdir_path):
                                    logger.debug(f"READDIR: FOUND {entry_name} in extension subdir")
                                    st = os.lstat(ext_subdir_path)
                                    if pipeline:
                                        st_mode = 0o100444
                                        st_size = self._get_transform_output_size(pipeline, st.st_size)
                                    else:
                                        st_mode = st.st_mode
                                        st_size = st.st_size
                                    stat_dict = {
                                        'st_atime': int(st.st_atime), 'st_ctime': int(st.st_ctime),
                                        'st_mtime': int(st.st_mtime), 'st_gid': st.st_gid,
                                        'st_uid': st.st_uid, 'st_mode': st_mode,
                                        'st_nlink': 1, 'st_size': st_size,
                                    }
                                    cache_getattr(entry_path, parent_dir, stat_dict)
                                    entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
                                    # Don't continue - fall through to send entry
                                else:
                                    # Extension subdir doesn't have the file either
                                    # Create placeholder if virtual path
                                    if is_virtual_path(self.config, self.mount_path, entry_path):
                                        now = int(time.time())
                                        stat_dict = {
                                            'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                                            'st_gid': 0, 'st_uid': 0, 'st_mode': 0o040755,
                                            'st_nlink': 2, 'st_size': 4096,
                                        }
                                        entry = self._dict_to_entry_attributes(stat_dict, entry_inode, cache_timeout=1.0)
                                    else:
                                        continue
                            else:
                                # No extension, file doesn't exist
                                if is_virtual_path(self.config, self.mount_path, entry_path):
                                    now = int(time.time())
                                    stat_dict = {
                                        'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                                        'st_gid': 0, 'st_uid': 0, 'st_mode': 0o040755,
                                        'st_nlink': 2, 'st_size': 4096,
                                    }
                                    entry = self._dict_to_entry_attributes(stat_dict, entry_inode, cache_timeout=1.0)
                                else:
                                    continue
                    elif entry_name.startswith('...') and entry_name.endswith('...'):
                        # Virtual directory
                        now = int(time.time())
                        stat_dict = {
                            'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                            'st_gid': 0, 'st_uid': 0, 'st_mode': 0o040755,
                            'st_nlink': 2, 'st_size': 4096,
                        }
                        cache_getattr(entry_path, parent_dir, stat_dict)
                        entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
                    else:
                        # Fallback: minimal attributes
                        entry = pyfuse3.EntryAttributes()
                        entry.st_ino = entry_inode
                        entry.st_mode = 0o040755
                        entry.st_nlink = 2
                        entry.st_uid = 0
                        entry.st_gid = 0
                        entry.st_size = 4096
                        now = int(time.time() * 1e9)
                        entry.st_atime_ns = entry.st_mtime_ns = entry.st_ctime_ns = now
                        entry.st_rdev = 0
                        entry.generation = 0
                        entry.entry_timeout = 60.0  # Cache for 60 seconds - reduces SMB client re-stats
                        entry.attr_timeout = 60.0
                        entry.st_blksize = 512
                        entry.st_blocks = 8
                except Exception as e:
                    logger.warning(f"READDIR: failed to stat {entry_name}: {e}")
                    continue

            # Final safety: fix misclassified file-like entries (e.g., boot.rom) showing as directories
            try:
                if "." in entry_name and (entry.st_mode & 0o040000):
                    resolved = get_source_path(logger, self.config, self.mount_path, entry_path)
                    if isinstance(resolved, dict):
                        resolved = resolved.get('path')
                    if isinstance(resolved, tuple):
                        zip_path, internal_file = resolved
                        import zippath
                        full_internal = os.path.join(zip_path, internal_file)
                        info = zippath.getinfo(full_internal)
                        if info and not info.get('is_dir', False):
                            now = int(os.path.getmtime(zip_path))
                            stat_dict = {
                                'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                                'st_gid': 0, 'st_uid': 0,
                                'st_mode': 0o100444,
                                'st_nlink': 1,
                                'st_size': info.get('size', 0),
                            }
                            cache_getattr(entry_path, parent_dir, stat_dict)
                            entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
                    elif isinstance(resolved, str) and os.path.exists(resolved) and not os.path.isdir(resolved):
                        st = os.lstat(resolved)
                        stat_dict = {
                            'st_atime': int(st.st_atime), 'st_ctime': int(st.st_ctime),
                            'st_mtime': int(st.st_mtime), 'st_gid': st.st_gid,
                            'st_uid': st.st_uid, 'st_mode': st.st_mode,
                            'st_nlink': 1, 'st_size': st.st_size,
                        }
                        cache_getattr(entry_path, parent_dir, stat_dict)
                        entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
            except Exception as e:
                logger.debug(f"READDIR: correction failed for {entry_name}: {e}")
            
            # Apply output_extension renaming if transform pipeline has one
            display_name = entry_name
            source_type, source_data = source_paths.get(entry_name, ('', None))
            pipeline = None
            
            # Use cached pipeline from source_paths (avoid expensive get_source_path call per entry)
            if isinstance(source_data, dict) and 'transform_pipeline' in source_data:
                pipeline = source_data.get('transform_pipeline')
            elif system_transform_map:
                # Fall back to system transform map
                _, ext = os.path.splitext(entry_name)
                ext = ext[1:].upper() if ext else ""
                pipeline = system_transform_map.get(ext) or system_transform_map.get(ext.lower())
            
            if pipeline:
                effective_ext = pipeline.get_effective_output_extension()
                if effective_ext:
                    # Rename the file with the output extension
                    base_name, _ = os.path.splitext(entry_name)
                    display_name = f"{base_name}.{effective_ext}"
                    logger.info(f"READDIR: Renamed {entry_name} -> {display_name} (output_extension={effective_ext})")
                else:
                    logger.debug(f"READDIR: Pipeline found for {entry_name} but no output_extension")
            
            # Send entry to client
            t_reply_start = time.time()
            if not pyfuse3.readdir_reply(token, display_name.encode('utf-8'), entry, entry_id):
                t_readdir_reply += time.time() - t_reply_start
                logger.info(f"READDIR: client buffer full after {sent_count} entries")
                break
            t_readdir_reply += time.time() - t_reply_start
            
            sent_count += 1
        
        # Fallback: if query map entries resolved but none were sent, emit minimal entries
        if is_query_map_dir and virtual_entries and sent_count == 0:
            logger.info(f"READDIR: fallback minimal listing for query map {xfull_path}")
            for entry_id, entry_name in enumerate(virtual_entries, start=1):
                if entry_id <= start_id:
                    continue
                entry_path = os.path.join(xfull_path, entry_name)
                entry_inode = self._make_synthetic_inode(entry_path)
                now = int(time.time())
                stat_dict = {
                    'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                    'st_gid': 0, 'st_uid': 0,
                    'st_mode': 0o100444, 'st_nlink': 1, 'st_size': 0,
                }
                entry = self._dict_to_entry_attributes(stat_dict, entry_inode, cache_timeout=1.0)
                if not pyfuse3.readdir_reply(token, entry_name.encode('utf-8'), entry, entry_id):
                    logger.info(f"READDIR: client buffer full after {sent_count} entries (fallback)")
                    break
                sent_count += 1

        t_total = time.time() - t_start
        t_send = time.time() - t_send_start
        hit_rate = (cache_hits / len(virtual_entries) * 100) if virtual_entries else 0
        logger.info(f"READDIR COMPLETE: {path} entries={len(virtual_entries)} sent={sent_count} "
                   f"cache_hits={cache_hits} hit_rate={hit_rate:.1f}% "
                   f"parse={t_parse:.4f}s batch={t_batch:.4f}s send={t_send:.4f}s reply={t_readdir_reply:.4f}s total={t_total:.4f}s")


    async def getattr(self, inode: InodeT, ctx=None):
        """
        Get file attributes by inode (pyfuse3 async version).
        This converts the path-based fusepy version to inode-based.
        """
        t_start = time.time()
        logger.info(f"GETATTR START: inode={inode}")
        try:
            path = self._inode_to_path(inode)
        except Exception as e:
            logger.info(f"GETATTR FAILED AT inode_to_path: inode={inode} error={e}")
            raise
        
        path = self._normalize_to_virtual_path(path)
        logger.info(f"GETATTR: inode={inode} path={path}")
        logger.debug("DEBUG: getattr(inode=%s) path=%s", inode, path)
        
        xfull_path = path  # Already full path from inode map
        
        # PRIORITY 0.5: Try database-only mode for query map directories first
        map_info = self._extract_map_info(xfull_path)
        if map_info:
            # This is a file within a query map directory, try database-only mode
            logger.info(f"GETATTR: detected query map file, trying database-only mode")
            stat_dict = await self._getattr_database_only(xfull_path, map_info)
            if stat_dict:
                logger.info(f"GETATTR: database-only mode successful for {xfull_path}")
                return self._dict_to_entry_attributes(stat_dict, inode)
            logger.info(f"GETATTR: database-only mode failed, falling back to cache/filesystem")
        
        # PRIORITY 1: Check getattr cache first (fastest, includes transform sizes)
        t_cache_start = time.time()
        parent_path = str(Path(xfull_path).parent)
        parent_dir_virtual = parent_path
        parent_source = get_source_path(logger, self.config, self.mount_path, parent_dir_virtual)
        if isinstance(parent_source, dict):
            parent_dir = parent_source.get("path")
        elif isinstance(parent_source, tuple):
            parent_dir = parent_source[0]
        elif isinstance(parent_source, str):
            parent_dir = parent_source
        else:
            parent_dir = parent_dir_virtual.replace("/mnt/transfs", "/mnt/filestorefs")
        
        cached_stat = get_cached_getattr(xfull_path, parent_dir)
        t_cache_elapsed = time.time() - t_cache_start
        
        if cached_stat is not None:
            # Check if this is a placeholder directory entry (from readdir for virtual paths)
            # These have mode=0o040755 and size=4096 - skip cache and resolve properly
            is_placeholder = (cached_stat.get('st_mode') == 0o040755 and 
                            cached_stat.get('st_size') == 4096 and
                            cached_stat.get('st_nlink') == 2)
            
            if not is_placeholder:
                # Refresh cache for transformed files to ensure size is accurate
                try:
                    if xfull_path.startswith(self.mount_path):
                        fspath = get_source_path(logger, self.config, self.mount_path, xfull_path)
                        if isinstance(fspath, dict) and 'transform_pipeline' in fspath:
                            source_path = fspath['path']
                            if os.path.exists(source_path):
                                st = os.lstat(source_path)
                                source_size = st.st_size
                                pipeline = fspath['transform_pipeline']
                                transformed_size = self._get_transform_output_size(pipeline, source_size, source_path)
                                if transformed_size >= 0 and cached_stat.get('st_size') != transformed_size:
                                    cached_stat = {
                                        'st_atime': int(st.st_atime),
                                        'st_ctime': int(st.st_ctime),
                                        'st_mtime': int(st.st_mtime),
                                        'st_gid': st.st_gid,
                                        'st_uid': st.st_uid,
                                        'st_mode': 0o100444,
                                        'st_nlink': 1,
                                        'st_size': transformed_size,
                                    }
                                    cache_getattr(xfull_path, parent_dir, cached_stat)
                except Exception:
                    pass
                t_total = time.time() - t_start
                TransFS._getattr_cache_hits += 1
                TransFS._getattr_count += 1
                TransFS._getattr_total_time += t_total
                logger.info(f"GETATTR CACHE HIT: inode={inode} path={xfull_path} (cache_lookup={t_cache_elapsed:.4f}s, total={t_total:.4f}s)")
                self._maybe_print_stats()
                return self._dict_to_entry_attributes(cached_stat, inode)
            else:
                logger.debug("GETATTR: skipping placeholder cache entry for %s", xfull_path)
        
        TransFS._getattr_cache_misses += 1
        logger.info(f"GETATTR CACHE MISS: inode={inode} path={xfull_path} (cache_lookup={t_cache_elapsed:.4f}s)")
        
        # PRIORITY 2: Try database mode if enabled and path is suitable
        if self._can_use_database(path):
            try:
                logger.info(f"GETATTR: trying database mode for {path}")
                stat_dict = self.data_adapter.getattr_stat(path)
                if stat_dict:
                    # Guard against incorrect DB directory entries for file-like paths
                    name = os.path.basename(path)
                    is_dir = stat_dict.get('st_nlink') == 2 and stat_dict.get('st_mode', 0) & 0o040000
                    if is_dir and "." in name:
                        logger.info(f"GETATTR DATABASE: possible misclassified dir for {path}, verifying source")
                        resolved = get_source_path(logger, self.config, self.mount_path, path)
                        if isinstance(resolved, tuple):
                            logger.info(f"GETATTR DATABASE: override to zip file for {path}")
                            stat_dict = None
                        elif isinstance(resolved, str) and os.path.exists(resolved) and not os.path.isdir(resolved):
                            logger.info(f"GETATTR DATABASE: override to file for {path}")
                            stat_dict = None
                    if stat_dict:
                        t_total = time.time() - t_start
                        TransFS._getattr_count += 1
                        TransFS._getattr_total_time += t_total
                        logger.info(f"GETATTR DATABASE: found entry in {t_total:.4f}s")
                        
                        # Verify backend file still exists (prevent stale cache issues)
                        t_verify_start = time.time()
                        backend_path = get_source_path(logger, self.config, self.mount_path, path)
                        t_verify = time.time() - t_verify_start
                        logger.info(f"GETATTR DATABASE: get_source_path returned in {t_verify:.4f}s: {backend_path}")
                        
                        if isinstance(backend_path, str):
                            t_exists_start = time.time()
                            exists = os.path.exists(backend_path)
                            t_exists = time.time() - t_exists_start
                            logger.info(f"GETATTR DATABASE: os.path.exists checked in {t_exists:.4f}s: {exists}")
                            
                            if not exists:
                                logger.info(f"GETATTR DATABASE: entry found but backend file missing at {backend_path}, treating as ENOENT")
                                stat_dict = None  # Fall through to full resolution which will return ENOENT
                            else:
                                logger.info(f"GETATTR DATABASE: verification complete, returning attributes")
                                return self._dict_to_entry_attributes(stat_dict, inode)
                        elif isinstance(backend_path, tuple):
                            # Virtual zip directory or similar - trust database
                            return self._dict_to_entry_attributes(stat_dict, inode)
                        else:
                            logger.warning(f"GETATTR DATABASE: could not resolve backend path for {path}")
                            stat_dict = None  # Fall through
                else:
                    logger.info(f"GETATTR DATABASE: no entry found for {path}")
            except Exception as e:
                logger.warning(f"GETATTR: database mode failed, falling back to full resolution: {e}")
        
        # PRIORITY 3: Full resolution (slowest, computes transforms)
        logger.info(f"GETATTR: full resolution for {xfull_path}")
        
        # Check for nested file map virtual directories BEFORE calling get_source_path
        # This handles both system-level (e.g., /RetroBat/AcornAtom/bios) and client-level (e.g., /RetroBat/bios)
        from pathutils import find_map_entry, is_query_map, get_map_config
        path_parts = Path(xfull_path).parts
        mount_parts = Path(self.mount_path).parts
        rel_parts = path_parts[len(mount_parts):]
        
        # IMPORTANT: Check if this path is actually a FILE MAP entry before treating it as a virtual directory
        # E.g., /RetroBat/bios/atom.zip where atom.zip is a system map with category=shared_bios and file: key
        if len(rel_parts) == 3:  # /<client>/<category>/<filename>
            client_name = rel_parts[0]
            category_name = rel_parts[1]
            file_name = rel_parts[2]
            client = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
            if client:
                # Check ALL systems for a file map with this name and category
                for system in client.get('systems', []):
                    for map_entry in (system.get('maps') or []):
                        map_name = list(map_entry.keys())[0]
                        map_config = list(map_entry.values())[0]
                        if (isinstance(map_config, dict) and
                            map_name == file_name and
                            map_config.get('category') == category_name and
                            'file' in map_config):
                            # This is a file map entry, NOT a virtual directory
                            # Let it fall through to get_source_path resolution
                            logger.info(f"GETATTR: detected file map {file_name}, skipping virtual directory check")
                            break
                    else:
                        continue
                    break  # Found the file map, exit both loops
        
        # Check for client-level nested map directories (e.g., /RetroBat/bios where "bios/atom.zip" is a client-level map)
        if len(rel_parts) == 2:  # /<client>/<map-or-system>
            client_name = rel_parts[0]
            potential_map = rel_parts[1]
            client = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
            if client:
                # Check if this is a virtual directory for nested client-level maps
                client_maps = client.get('maps') or []
                is_virtual_dir = any(
                    list(m.keys())[0].startswith(potential_map + '/')
                    for m in client_maps
                )
                if is_virtual_dir:
                    now = int(time.time())
                    result = {
                        'st_atime': now,
                        'st_ctime': now,
                        'st_mtime': now,
                        'st_gid': 0,
                        'st_uid': 0,
                        'st_mode': 0o040755,
                        'st_nlink': 2,
                        'st_size': 4096,
                    }
                    logger.info(f"GETATTR: returning virtual directory for client-level nested map parent {potential_map}")
                    return self._dict_to_entry_attributes(result, inode)
        
        # Check for system-level nested file map directories
        if len(rel_parts) >= 3:  # /<client>/<system>/<map> or deeper like /<client>/<system>/<map>/<subdir>
            client_name = rel_parts[0]
            system_name = rel_parts[1]
            map_parts = rel_parts[2:]  # Everything after system (e.g., ['FDs', 'bios'])
            map_path = '/'.join(map_parts)  # e.g., 'FDs/bios'
            map_name = map_parts[0] if map_parts else ""  # e.g., 'FDs'
            
            client = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
            if client:
                system_info = next((s for s in client.get('systems', []) if s['name'] == system_name), None)
                if system_info:
                    # Check if this is a virtual directory for nested file maps
                    # e.g., "bios" from "bios/atom.zip" OR "FDs/bios" from "FDs/bios/atom.zip"
                    is_virtual_dir = any(
                        list(m.keys())[0].startswith(map_path + '/')
                        for m in (system_info.get('maps') or [])
                    )
                    if is_virtual_dir:
                        now = int(time.time())
                        result = {
                            'st_atime': now,
                            'st_ctime': now,
                            'st_mtime': now,
                            'st_gid': 0,
                            'st_uid': 0,
                            'st_mode': 0o040755,
                            'st_nlink': 2,
                            'st_size': 4096,
                        }
                        logger.info(f"GETATTR: returning virtual directory for nested map parent {map_path}")
                        return self._dict_to_entry_attributes(result, inode)
                    
                    # Also check if it's a query map directory (only for top-level map, not nested)
                    if len(map_parts) == 1:
                        map_entry = find_map_entry(system_info, map_name)
                        map_config = get_map_config(map_entry)
                        if is_query_map(map_config):
                            now = int(time.time())
                            result = {
                                'st_atime': now,
                                'st_ctime': now,
                                'st_mtime': now,
                                'st_gid': 0,
                                'st_uid': 0,
                                'st_mode': 0o040755,
                                'st_nlink': 2,
                                'st_size': 4096,
                            }
                            logger.info(f"GETATTR: returning virtual directory for query map {map_name}")
                            return self._dict_to_entry_attributes(result, inode)
        
        # Check if source path was cached by readdir (major optimization - avoid re-computation)
        if xfull_path in self._source_path_cache:
            logger.info(f"GETATTR: source path CACHE HIT for {xfull_path}")
            fspath = self._source_path_cache[xfull_path]
        else:
            logger.info(f"GETATTR: calling get_source_path for {xfull_path}")
            t_source_start = time.time()
            # Convert filestore path to mount path for get_source_path() only if needed
            filestore_root = self.config.get("filestore", "/mnt/filestorefs")
            if xfull_path.startswith(filestore_root):
                virtual_path = self._filestore_to_mount_path(xfull_path)
            else:
                virtual_path = xfull_path
            virtual_path = os.path.normpath(virtual_path)
            logger.info(f"GETATTR: virtual_path={virtual_path}")
            fspath = get_source_path(logger, self.config, self.mount_path, virtual_path)
            t_source_elapsed = time.time() - t_source_start
            logger.info(f"GETATTR: get_source_path returned fspath={fspath}")
            logger.debug("GETATTR get_source_path took %.4fs for inode=%s", t_source_elapsed, inode)
        logger.debug("DEBUG: getattr full_path=%s, fspath=%s", xfull_path, fspath)

        # Determine zip_mode
        zip_mode = self._get_zip_mode_for_path(xfull_path)
        logger.debug("DEBUG: getattr zip_mode=%s for path=%s", zip_mode, path)

        # Handle files with transformation pipelines
        if isinstance(fspath, dict) and 'transform_pipeline' in fspath:
            logger.info(f"GETATTR: handling transform pipeline")
            source_path = fspath['path']
            pipeline = fspath['transform_pipeline']
            
            if not os.path.exists(source_path):
                logger.info(f"GETATTR: source_path does not exist: {source_path}")
                raise FUSEError(errno.ENOENT)
            
            # Get source file stats and adjust size for transformation
            st = os.lstat(source_path)
            source_size = st.st_size
            transformed_size = self._get_transform_output_size(pipeline, source_size, source_path)
            
            result = {
                'st_atime': int(st.st_atime),
                'st_ctime': int(st.st_ctime),
                'st_mtime': int(st.st_mtime),
                'st_gid': st.st_gid,
                'st_uid': st.st_uid,
                'st_mode': 0o100444,
                'st_nlink': 1,
                'st_size': transformed_size if transformed_size >= 0 else source_size,
            }
            logger.debug("DEBUG: getattr with transform: source_size=%d, transformed_size=%d", 
                        source_size, result['st_size'])
            cache_getattr(xfull_path, parent_dir, result)
            logger.info(f"GETATTR: returning transform result for {inode}")
            return self._dict_to_entry_attributes(result, inode)

        # Handle file inside a zip
        if isinstance(fspath, tuple):
            logger.info(f"GETATTR: handling zip file")
            logger.debug("DEBUG: Inside isinstance(fspath, tuple) branch: %s", fspath)
            zip_path, internal_file = fspath
            import zippath
            
            full_internal_path = os.path.join(zip_path, internal_file)
            now = int(os.path.getmtime(zip_path))
            
            info = zippath.getinfo(full_internal_path)
            if info is None:
                raise FUSEError(errno.ENOENT)
            
            if info['is_dir']:
                result = {
                    'st_atime': now,
                    'st_ctime': now,
                    'st_mtime': now,
                    'st_gid': 0,
                    'st_uid': 0,
                    'st_mode': 0o040555,
                    'st_nlink': 2,
                    'st_size': 0,
                }
            else:
                result = {
                    'st_atime': now,
                    'st_ctime': now,
                    'st_mtime': now,
                    'st_gid': 0,
                    'st_uid': 0,
                    'st_mode': 0o100444,
                    'st_nlink': 1,
                    'st_size': info['size'],
                }
            
            logger.info(f"GETATTR: returning zip result for {inode}")
            cache_getattr(xfull_path, parent_dir, result)
            return self._dict_to_entry_attributes(result, inode)

        # Handle virtual directories
        if fspath is None:
            parent_path = str(Path(xfull_path).parent)
            entries = set(parse_trans_path(self.config, self.mount_path, parent_path))
            name = os.path.basename(xfull_path)
            logger.debug("DEBUG getattr fallback: parent_path=%s, entries=%s, name=%s", parent_path, entries, name)

            if name in entries:
                # Check if this is a category directory (level 2: /<client>/<category>)
                path_parts = Path(xfull_path).parts
                mount_parts = Path(self.mount_path).parts
                rel_parts = path_parts[len(mount_parts):]
                
                if len(rel_parts) == 2:  # /<client>/<potential_category>
                    client_name = rel_parts[0]
                    category_name = rel_parts[1]
                    client = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
                    if client and 'category_paths' in client:
                        # Check if this is a valid category directory
                        category_paths = client.get('category_paths', {})
                        # Check if the directory name appears in any category path template
                        is_category = any(
                            category_name in template
                            for template in category_paths.values()
                        )
                        if is_category:
                            now = int(time.time())
                            result = {
                                'st_atime': now,
                                'st_ctime': now,
                                'st_mtime': now,
                                'st_gid': 0,
                                'st_uid': 0,
                                'st_mode': 0o040755,
                                'st_nlink': 2,
                                'st_size': 4096,
                            }
                            cache_getattr(xfull_path, parent_dir, result)
                            logger.info(f"GETATTR: returning virtual directory for category {category_name}")
                            return self._dict_to_entry_attributes(result, inode)
                
                # Check if it's a virtual directory (legacy ...Name... style or query map)
                if name.startswith('...') and name.endswith('...'):
                    now = int(time.time())
                    result = {
                        'st_atime': now,
                        'st_ctime': now,
                        'st_mtime': now,
                        'st_gid': 0,
                        'st_uid': 0,
                        'st_mode': 0o040755,
                        'st_nlink': 2,
                        'st_size': 4096,
                    }
                    cache_getattr(xfull_path, parent_dir, result)
                    return self._dict_to_entry_attributes(result, inode)
                
                # Check if it's a query map directory or virtual directory for nested maps
                from pathutils import find_map_entry, is_query_map, get_map_config
                path_parts = Path(xfull_path).parts
                mount_parts = Path(self.mount_path).parts
                rel_parts = path_parts[len(mount_parts):]
                if len(rel_parts) == 3:  # /<client>/<system>/<map>
                    client_name = rel_parts[0]
                    system_name = rel_parts[1]
                    map_name = rel_parts[2]
                    client = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
                    if client:
                        system_info = next((s for s in client.get('systems', []) if s['name'] == system_name), None)
                        if system_info:
                            # Check if this is a virtual directory for nested file maps (e.g., "bios" from "bios/atom.zip")
                            is_virtual_dir = any(
                                list(m.keys())[0].startswith(map_name + '/')
                                for m in (system_info.get('maps') or [])
                            )
                            if is_virtual_dir:
                                now = int(time.time())
                                result = {
                                    'st_atime': now,
                                    'st_ctime': now,
                                    'st_mtime': now,
                                    'st_gid': 0,
                                    'st_uid': 0,
                                    'st_mode': 0o040755,
                                    'st_nlink': 2,
                                    'st_size': 4096,
                                }
                                cache_getattr(xfull_path, parent_dir, result)
                                logger.info(f"GETATTR: returning virtual directory for nested map parent {map_name}")
                                return self._dict_to_entry_attributes(result, inode)
                            
                            map_entry = find_map_entry(system_info, map_name)
                            map_config = get_map_config(map_entry)
                            if is_query_map(map_config):
                                now = int(time.time())
                                result = {
                                    'st_atime': now,
                                    'st_ctime': now,
                                    'st_mtime': now,
                                    'st_gid': 0,
                                    'st_uid': 0,
                                    'st_mode': 0o040755,
                                    'st_nlink': 2,
                                    'st_size': 4096,
                                }
                                cache_getattr(xfull_path, parent_dir, result)
                                logger.info(f"GETATTR: returning virtual directory for query map {map_name}")
                                return self._dict_to_entry_attributes(result, inode)
                
                # Retry get_source_path
                retry_virtual_path = self._filestore_to_mount_path(xfull_path)
                retry_fspath = get_source_path(logger, self.config, self.mount_path, retry_virtual_path)
                logger.debug("DEBUG getattr retry_fspath: %s", retry_fspath)
                
                if retry_fspath and isinstance(retry_fspath, str) and os.path.exists(retry_fspath):
                    st = os.lstat(retry_fspath)
                    result = {
                        'st_atime': int(st.st_atime),
                        'st_ctime': int(st.st_ctime),
                        'st_mtime': int(st.st_mtime),
                        'st_gid': st.st_gid,
                        'st_uid': st.st_uid,
                        'st_mode': 0o100444,
                        'st_nlink': 1,
                        'st_size': st.st_size,
                    }
                    cache_getattr(xfull_path, parent_dir, result)
                    return self._dict_to_entry_attributes(result, inode)

                # Final fallback: name is listed by the parent directory but no physical path
                # was found. This covers system directories under category paths
                # (e.g. /RetroBat/ROMS/3DO where ROMS is a category and 3DO is a system),
                # plus any other virtual entry that isn't explicitly matched above.
                now = int(time.time())
                result = {
                    'st_atime': now, 'st_ctime': now, 'st_mtime': now,
                    'st_gid': 0, 'st_uid': 0,
                    'st_mode': 0o040755,
                    'st_nlink': 2,
                    'st_size': 4096,
                }
                cache_getattr(xfull_path, parent_dir, result)
                logger.info(f"GETATTR: returning virtual directory (listed-in-parent fallback) for {xfull_path}")
                return self._dict_to_entry_attributes(result, inode)

            raise FUSEError(errno.ENOENT)

        # Handle archive files based on zip_mode
        if isinstance(fspath, str) and is_supported_archive_name(fspath):
            st = os.lstat(fspath)
            if zip_mode == "hierarchical":
                out = {
                    'st_atime': int(st.st_atime),
                    'st_ctime': int(st.st_ctime),
                    'st_mtime': int(st.st_mtime),
                    'st_gid': st.st_gid,
                    'st_uid': st.st_uid,
                    'st_mode': 0o040755,
                    'st_nlink': 2,
                    'st_size': 4096,
                }
            else:
                out = {
                    'st_atime': int(st.st_atime),
                    'st_ctime': int(st.st_ctime),
                    'st_mtime': int(st.st_mtime),
                    'st_gid': st.st_gid,
                    'st_uid': st.st_uid,
                    'st_mode': 0o100444,
                    'st_nlink': 1,
                    'st_size': st.st_size,
                }
            cache_getattr(xfull_path, parent_dir, out)
            return self._dict_to_entry_attributes(out, inode)

        # Fallback to parent class
        # Handle real files/directories that aren't zips
        if isinstance(fspath, str) and os.path.exists(fspath):
            try:
                st = os.lstat(fspath)
                result = {
                    'st_atime': int(st.st_atime),
                    'st_ctime': int(st.st_ctime),
                    'st_mtime': int(st.st_mtime),
                    'st_gid': st.st_gid,
                    'st_uid': st.st_uid,
                    'st_mode': st.st_mode,
                    'st_nlink': st.st_nlink,
                    'st_size': st.st_size,
                }
                cache_getattr(xfull_path, parent_dir, result)
                logger.info(f"GETATTR: returning real file attributes for {inode}")
                return self._dict_to_entry_attributes(result, inode)
            except (OSError, FileNotFoundError) as e:
                logger.error(f"GETATTR: error getting attributes for {fspath}: {e}")
                raise FUSEError(errno.ENOENT)
        
        # Before giving up, check if this is a query map directory (virtual, no physical backing)
        # This handles cases where get_source_path returns a path that doesn't exist
        if isinstance(fspath, str) and not os.path.exists(fspath):
            from pathutils import find_map_entry, is_query_map, get_map_config
            
            rel_path = os.path.relpath(xfull_path, self.mount_path)
            rel_parts = [p for p in rel_path.split('/') if p and p != '.']
            
            # Check if this looks like a query map directory: /<client>/<category>/<system>/<map>
            # or /<client>/<system>/<map> (without category paths)
            if len(rel_parts) >= 3:
                client_name = rel_parts[0]
                client = next((c for c in self.config.get('clients', []) if c['name'] == client_name), None)
                
                if client:
                    # Determine system name and map path based on whether client uses category paths
                    has_category_paths = 'category_paths' in client
                    
                    if has_category_paths and len(rel_parts) >= 4:
                        # Format: /<client>/<category>/<system>/<map>
                        system_name = rel_parts[2]
                        map_path = '/'.join(rel_parts[3:])
                        map_parts = rel_parts[3:]
                    else:
                        # Format: /<client>/<system>/<map>
                        system_name = rel_parts[1]
                        map_path = '/'.join(rel_parts[2:])
                        map_parts = rel_parts[2:]
                    
                    system_info = next((s for s in client.get('systems', []) if s['name'] == system_name), None)
                    
                    if system_info and len(map_parts) == 1:
                        # Check if this is a query map (virtual directory)
                        map_name = map_parts[0]
                        map_entry = find_map_entry(system_info, map_name)
                        map_config = get_map_config(map_entry)
                        
                        if is_query_map(map_config):
                            # This is a virtual query map directory
                            now = int(time.time())
                            result = {
                                'st_atime': now,
                                'st_ctime': now,
                                'st_mtime': now,
                                'st_gid': 0,
                                'st_uid': 0,
                                'st_mode': 0o040755,
                                'st_nlink': 2,
                                'st_size': 4096,
                            }
                            logger.info(f"GETATTR: returning virtual directory for query map {map_name} (fallback)")
                            return self._dict_to_entry_attributes(result, inode)
        
        # If we can't handle it, raise ENOENT
        logger.error(f"GETATTR: unhandled case for inode={inode} fspath={fspath}")
        raise FUSEError(errno.ENOENT)
    
    async def open(self, inode: InodeT, flags: int, ctx):
        """Open a file (pyfuse3 async version)."""
        t_start = time.time()
        path = self._inode_to_path(inode)
        logger.info("OPEN START: inode=%s, flags=%s, path=%s", inode, flags, path)
        
        # Try database-only mode for query map files first
        trans_path = None
        map_info = None
        if not (flags & os.O_CREAT):
            # Check if this is a file within a query map directory
            map_info = self._extract_map_info(path)
            if map_info:
                logger.info("OPEN: detected query map file, trying database-only mode")
                t_db = time.time()
                trans_path = await self._open_database_only(path, map_info)
                t_db_elapsed = time.time() - t_db
                logger.info(f"OPEN: database query took {t_db_elapsed:.4f}s, result={'found' if trans_path else 'not found'}")
                if trans_path:
                    logger.info(f"OPEN: database-only mode successful, trans_path={trans_path}")
                else:
                    logger.info(f"OPEN: database-only mode failed, falling back to filesystem")
        
        # Fallback to normal source path resolution if database lookup failed or not a query map
        if trans_path is None:
            t_gsp = time.time()
            trans_path = get_source_path(logger, self.config, self.mount_path, path)
            t_gsp_elapsed = time.time() - t_gsp
            logger.info(f"OPEN: get_source_path took {t_gsp_elapsed:.4f}s")
        logger.info("OPEN: trans_path=%s", trans_path)

        if trans_path is None:
            if flags & os.O_CREAT:
                trans_path = get_source_path_for_write(logger, self.config, self.mount_path, path)
                logger.debug("DEBUG: open write trans_path=%s", trans_path)
                if trans_path is None:
                    logger.debug("DEBUG: open: no mapping for write")
                    raise FUSEError(errno.ENOENT)
            else:
                logger.debug("DEBUG: open: no mapping")
                raise FUSEError(errno.ENOENT)

        # Handle zip internal files
        if isinstance(trans_path, tuple):
            zip_path, internal_file = trans_path
            logger.debug("DEBUG: open extracting %s from %s", internal_file, zip_path)

            # --- Disc cache: reuse extracted temp file if the same game is still "inserted" ---
            disc_cache_key = None
            if map_info:
                client_name, system_name, _ = map_info
                disc_cache_key = (client_name, system_name)

            if disc_cache_key is not None:
                cached = self._disc_cache.get(disc_cache_key)
                if cached and cached['zip_path'] != zip_path:
                    # Different game loaded — evict old cached files
                    logger.info(
                        "DISC_CACHE: evicting %s for %s (new game %s)",
                        cached['zip_path'], disc_cache_key, zip_path,
                    )
                    for _inner, _tmp in cached['files'].items():
                        try:
                            os.unlink(_tmp)
                            logger.debug("DISC_CACHE: unlinked %s", _tmp)
                        except OSError:
                            pass
                    del self._disc_cache[disc_cache_key]
                    cached = None

                if cached and cached['zip_path'] == zip_path:
                    cached_path = cached['files'].get(internal_file)
                    if cached_path and os.path.exists(cached_path):
                        logger.info(
                            "DISC_CACHE HIT: reusing %s for %s/%s",
                            cached_path, disc_cache_key, internal_file,
                        )
                        try:
                            fd = os.open(cached_path, os.O_RDONLY)
                            self._register_open_handle(fd, inode, cached_path, flags, "zip-temp-cached")
                            logger.info("OPEN COMPLETE: inode=%s fh=%s kind=zip-temp-cached elapsed=%.4fs", inode, fd, time.time() - t_start)
                            return pyfuse3.FileInfo(fh=fd)
                        except OSError as e:
                            logger.warning("DISC_CACHE: failed to reopen cached file %s: %s — re-extracting", cached_path, e)
                            cached['files'].pop(internal_file, None)
            # --- End disc cache check ---

            try:
                with zippath_open_file(f"{zip_path}/{internal_file}", "rb") as f:
                    temp = tempfile.NamedTemporaryFile(mode='wb', delete=False)
                    content = f.read()
                    if isinstance(content, str):
                        content = content.encode('utf-8')

                    if str(internal_file).lower().endswith('.cue'):
                        inner_dir = os.path.dirname(str(internal_file)).replace('\\', '/').strip('/')
                        sibling_target = zip_path if not inner_dir else f"{zip_path}/{inner_dir}"
                        try:
                            sibling_names = zippath_listdir(sibling_target)
                        except Exception:
                            sibling_names = []
                        content = self._rewrite_cue_content(
                            content,
                            sibling_names,
                            f"{zip_path}/{internal_file}",
                        )

                    temp.write(content)
                    temp.close()
                    logger.debug("DEBUG: open temp file created at %s", temp.name)

                    # Store in disc cache
                    if disc_cache_key is not None:
                        slot = self._disc_cache.setdefault(disc_cache_key, {'zip_path': zip_path, 'files': {}})
                        slot['zip_path'] = zip_path
                        slot['files'][internal_file] = temp.name
                        logger.info("DISC_CACHE: cached %s for %s/%s", temp.name, disc_cache_key, internal_file)

                    fd = os.open(temp.name, flags)
                    self._register_open_handle(fd, inode, temp.name, flags, "zip-temp")
                    logger.info("OPEN COMPLETE: inode=%s fh=%s kind=zip-temp elapsed=%.4fs", inode, fd, time.time() - t_start)
                    return pyfuse3.FileInfo(fh=fd)
            except FileNotFoundError:
                logger.error("open: %s not in zip %s", internal_file, zip_path)
                raise FUSEError(errno.ENOENT)
            except Exception as e:
                logger.error("open: error extracting %s from %s: %s", internal_file, zip_path, e)
                raise FUSEError(errno.ENOENT)

        # Handle files with transformation pipelines
        if isinstance(trans_path, dict) and 'transform_pipeline' in trans_path:
            source_path = trans_path['path']
            pipeline = trans_path['transform_pipeline']
            logger.debug("DEBUG: open applying transform pipeline: %s", pipeline)
            
            if not os.path.exists(source_path):
                logger.error("open: source file %s does not exist for transformation", source_path)
                raise FUSEError(errno.ENOENT)

            # Fast-path: transforms that produce a prebuilt file (e.g. ChdTransform)
            # serve the output file directly — no need to load hundreds of MB into memory.
            if pipeline.stages and hasattr(pipeline.stages[-1], 'get_prebuilt_path'):
                try:
                    prebuilt = pipeline.stages[-1].get_prebuilt_path(source_path)
                    if prebuilt and os.path.exists(prebuilt):
                        fd = os.open(prebuilt, os.O_RDONLY)
                        self._register_open_handle(fd, inode, prebuilt, flags, "prebuilt-transform")
                        logger.info(
                            "OPEN COMPLETE: inode=%s fh=%s kind=prebuilt-transform elapsed=%.4fs path=%s",
                            inode, fd, time.time() - t_start, prebuilt,
                        )
                        return pyfuse3.FileInfo(fh=fd)
                    logger.error("open: prebuilt transform returned no path for %s", source_path)
                    raise FUSEError(errno.EIO)
                except FUSEError:
                    raise
                except Exception as exc:
                    logger.error("open: prebuilt transform error for %s: %s", source_path, exc)
                    raise FUSEError(errno.EIO)

            try:
                # Read source file and apply transformations
                with open(source_path, 'rb') as source_file:
                    # Get source file size
                    source_file.seek(0, os.SEEK_END)
                    source_size = source_file.tell()
                    source_file.seek(0)
                    
                    # Calculate output size
                    output_size = self._get_transform_output_size(pipeline, source_size)
                    logger.info(f"OPEN: transform source_size={source_size}, output_size={output_size}")
                    
                    # Read and transform all data
                    # For now, read entire file - could optimize for large files later
                    transformed_data = pipeline.apply_transforms(source_file, 0, output_size if output_size >= 0 else source_size)
                    logger.info(f"OPEN: transformed_data length={len(transformed_data)}")
                    
                    # Write to temp file
                    temp = tempfile.NamedTemporaryFile(mode='wb', delete=False)
                    temp.write(transformed_data)
                    temp.close()
                    logger.info("OPEN: created transformed temp file at %s (size: %d -> %d)", 
                                temp.name, source_size, len(transformed_data))
                    
                    # Open temp file
                    fd = os.open(temp.name, flags)
                    self._register_open_handle(fd, inode, temp.name, flags, "transform-temp")
                    logger.info("OPEN COMPLETE: inode=%s fh=%s kind=transform-temp elapsed=%.4fs", inode, fd, time.time() - t_start)
                    return pyfuse3.FileInfo(fh=fd)
            except Exception as e:
                logger.error("open: error applying transform pipeline for %s: %s", source_path, e)
                raise FUSEError(errno.EIO)

        # Handle regular files
        if isinstance(trans_path, str):
            if not os.path.exists(trans_path):
                if flags & os.O_CREAT:
                    logger.debug("open: creating new file at %s", trans_path)
                    parent_dir = os.path.dirname(trans_path)
                    try:
                        os.makedirs(parent_dir, exist_ok=True)
                        logger.debug("open: ensured directory exists: %s", parent_dir)
                    except Exception as e:
                        logger.error("open: failed to create directory %s: %s", parent_dir, e)
                        raise FUSEError(errno.EACCES)
                    try:
                        fd = os.open(trans_path, flags, 0o644)
                        self._register_open_handle(fd, inode, trans_path, flags, "create")

                        parent_path = self._normalize_to_virtual_path(os.path.dirname(path))
                        self._lookup_parent_entries_cache.pop(parent_path, None)

                        logger.info("OPEN COMPLETE: inode=%s fh=%s kind=create elapsed=%.4fs", inode, fd, time.time() - t_start)
                        return pyfuse3.FileInfo(fh=fd)
                    except Exception as e:
                        logger.error("open: failed to create file %s: %s", trans_path, e)
                        raise FUSEError(errno.EACCES)
                else:
                    logger.error("open: real file %s does not exist", trans_path)
                    raise FUSEError(errno.ENOENT)
            
            # File exists - open it directly (don't use parent class)
            logger.info("OPEN: opening existing file trans_path=%s", trans_path)
            try:
                # Always open a new file descriptor - don't reuse
                # (Reusing causes file position conflicts between multiple handles)
                fd = os.open(trans_path, flags)
                self._register_open_handle(fd, inode, trans_path, flags, "regular")
                
                # Setup memory-mapped I/O for large files if enabled
                self._setup_mmap_if_applicable(fd, trans_path)
                
                logger.info("OPEN COMPLETE: inode=%s fh=%s kind=regular elapsed=%.4fs", inode, fd, time.time() - t_start)
                return pyfuse3.FileInfo(fh=fd)
            except OSError as exc:
                logger.error("OPEN: failed to open %s: %s", trans_path, exc)
                raise FUSEError(exc.errno if exc.errno else errno.EIO)

        logger.debug("DEBUG: open: unknown mapping")
        raise FUSEError(errno.ENOENT)

    async def read(self, fh, off, size):
        """
        Read data from an open file.
        Uses trio thread offloading to avoid blocking the async event loop.
        Supports optional memory-mapped I/O for large files to avoid os.read() chunking.
        """
        t_start = time.time()
        meta = self._fd_open_meta.get(fh)
        if meta is None:
            logger.warning("READ: fh=%s off=%s size=%s with missing open metadata", fh, off, size)
        # Debug level logging to avoid log spam
        logger.debug("READ: fh=%s off=%s size=%s", fh, off, size)
        try:
            # Use trio.to_thread.run_sync to offload blocking I/O to a thread
            def _do_read():
                """
                Read 'size' bytes from file handle at offset 'off'.
                
                If mmap is enabled and available for this fd, use memory-mapped I/O
                which avoids the FUSE kernel driver's 65KB chunking limitation.
                
                Otherwise, uses a loop to handle short reads from os.read(), which can
                legally return fewer bytes than requested without causing an error.
                This is critical for large files accessed over SMB/CIFS.
                """
                # Try mmap first if available for this file descriptor
                mmap_obj = self._fd_mmap.get(fh)
                if mmap_obj is not None:
                    file_size = self._fd_file_size.get(fh, 0)
                    # Validate read bounds
                    if off >= file_size:
                        return b''  # EOF
                    read_end = min(off + size, file_size)
                    actual_size = read_end - off
                    try:
                        # Direct memory copy from mmap - fast!
                        data = mmap_obj[off:read_end]
                        return bytes(data)  # Convert memoryview to bytes
                    except Exception as e:
                        logger.warning(f"READ: mmap failed for fh={fh} off={off} size={size}: {e}, falling back to os.read()")
                        # Fall through to os.read() approach
                
                # Standard os.read() with loop to handle short reads
                os.lseek(fh, off, os.SEEK_SET)
                data = b''
                remaining = size
                read_iterations = 0
                while remaining > 0:
                    chunk = os.read(fh, remaining)
                    read_iterations += 1
                    if not chunk:  # EOF reached
                        if remaining > 0 and meta:
                            logger.warning(
                                "READ SHORT: fh=%s off=%s requested=%d got=%d (EOF after %d iterations) path=%s",
                                fh, off, size, len(data), read_iterations, meta.get("path", "")
                            )
                        break
                    if len(chunk) < remaining:
                        # Got a short read - only log at debug level to avoid log spam
                        if read_iterations == 1:  # Log first occurrence only
                            logger.debug(
                                "READ PARTIAL: fh=%s iteration=%d requested=%d got=%d remaining=%d",
                                fh, read_iterations, remaining, len(chunk), remaining - len(chunk)
                            )
                    data += chunk
                    remaining -= len(chunk)
                if read_iterations > 1:
                    logger.debug(
                        "READ COMPLETE: fh=%s off=%s size=%d completed in %d iterations",
                        fh, off, size, read_iterations
                    )
                return data

            data = await trio.to_thread.run_sync(_do_read)
            elapsed_ms = (time.time() - t_start) * 1000.0
            # Only log at debug level unless it's slow
            logger.debug("READ: fh=%s off=%s size=%s -> %d bytes (%.2fms)", fh, off, size, len(data), elapsed_ms)
            
            # Track read stats for diagnostics
            try:
                stats = self._fd_read_stats.get(fh)
                if stats is not None:
                    stats["total"] += len(data)
                    stats["reads"] += 1
                    stats["last_off"] = off
                    stats["last_size"] = size
                    stats["last_elapsed_ms"] = elapsed_ms
                    end = off + len(data)
                    if end > stats["max_end"]:
                        stats["max_end"] = end
                    path = self._fd_path_map.get(fh, "")
                    if path.endswith("/Acorn/Atom/Software/VHD/hoglet67.vhd"):
                        logger.info(
                            "READ_STATS: fh=%s total=%d max_end=%d path=%s",
                            fh, stats["total"], stats["max_end"], path
                        )
            except Exception:
                pass

            if elapsed_ms > 100:
                path = self._fd_path_map.get(fh)
                logger.warning(
                    "READ SLOW: fh=%s off=%s size=%s elapsed=%.2fms path=%s",
                    fh,
                    off,
                    size,
                    elapsed_ms,
                    path,
                )
            return data
        except OSError as exc:
            stats = self._fd_read_stats.get(fh)
            if stats is not None:
                stats["errors"] += 1
            logger.error("READ: failed fh=%s off=%s size=%s: %s", fh, off, size, exc)
            raise FUSEError(exc.errno if exc.errno else errno.EIO)

    async def write(self, fh, off, buf):
        """
        Write data to an open file.
        Uses trio thread offloading to avoid blocking the async event loop.
        """
        logger.info("WRITE: fh=%s off=%s size=%s", fh, off, len(buf))
        try:
            # Use trio.to_thread.run_sync to offload blocking I/O to a thread
            def _do_write():
                os.lseek(fh, off, os.SEEK_SET)
                return os.write(fh, buf)
            
            written = await trio.to_thread.run_sync(_do_write)
            logger.info("WRITE: fh=%s off=%s -> %d bytes written", fh, off, written)
            return written
        except OSError as exc:
            logger.error("WRITE: failed fh=%s off=%s: %s", fh, off, exc)
            raise FUSEError(exc.errno if exc.errno else errno.EIO)

    async def release(self, fh):
        """
        Close an open file.
        Uses trio thread offloading for the close operation.
        """
        logger.info("RELEASE: fh=%s", fh)
        self._log_fh_state(fh, "release-start")
        try:
            open_count = self._fd_open_count.get(fh)
            if open_count is None:
                # Idempotency guard: release can occasionally be observed after state cleanup.
                logger.warning("RELEASE: fh=%s already released (no open_count state)", fh)
                return

            if open_count > 1:
                self._fd_open_count[fh] = open_count - 1
                logger.info("RELEASE: fh=%s decremented count to %d", fh, self._fd_open_count[fh])
                self._log_fh_state(fh, "release-decrement")
                return

            self._fd_open_count.pop(fh, None)
            inode = self._fd_inode_map.pop(fh, None)
            stats = self._fd_read_stats.get(fh, {})
            meta = self._fd_open_meta.get(fh, {})

            if inode is not None:
                # Only clear inode->fd mapping if it still points at this fh.
                mapped_fh = self._inode_fd_map.get(inode)
                if mapped_fh == fh:
                    self._inode_fd_map.pop(inode, None)

            self._fd_path_map.pop(fh, None)
            self._fd_read_stats.pop(fh, None)
            self._fd_open_meta.pop(fh, None)
            
            # Cleanup memory-mapped I/O if it was used
            mmap_obj = self._fd_mmap.pop(fh, None)
            if mmap_obj is not None:
                try:
                    mmap_obj.close()
                    logger.debug("RELEASE: closed mmap for fh=%s", fh)
                except Exception as e:
                    logger.warning("RELEASE: failed to close mmap for fh=%s: %s", fh, e)
            self._fd_file_size.pop(fh, None)

            pending_times = self._pending_utime.get(inode) if inode is not None else None
            has_other_fhs_for_inode = False
            if inode is not None:
                has_other_fhs_for_inode = inode in self._fd_inode_map.values()

            if pending_times and not has_other_fhs_for_inode:
                self._pending_utime.pop(inode, None)
                atime_ns, mtime_ns = pending_times
                path = self._inode_to_path(inode)
                def _do_utime():
                    os.utime(path, None, follow_symlinks=False, ns=(atime_ns, mtime_ns))
                try:
                    with trio.move_on_after(1) as cancel_scope:
                        await trio.to_thread.run_sync(_do_utime)
                    if cancel_scope.cancelled_caught:
                        logger.warning("RELEASE: deferred utime timed out inode=%s", inode)
                    else:
                        logger.info("RELEASE: applied deferred utime inode=%s", inode)
                except OSError as exc:
                    logger.warning("RELEASE: deferred utime failed inode=%s: %s", inode, exc)
            
            # Use trio.to_thread.run_sync to offload blocking close to a thread
            def _do_close():
                os.close(fh)

            try:
                await trio.to_thread.run_sync(_do_close)
            except OSError as exc:
                if exc.errno == errno.EBADF:
                    logger.warning("RELEASE: fh=%s already closed (EBADF)", fh)
                    return
                raise

            open_age = None
            if meta.get("opened_at") is not None:
                open_age = max(0.0, time.time() - meta["opened_at"])

            logger.info(
                "RELEASE: fh=%s closed successfully (inode=%s kind=%s lifetime=%.3fs reads=%s total=%s max_end=%s errors=%s)",
                fh,
                inode,
                meta.get("source_kind"),
                open_age if open_age is not None else -1.0,
                stats.get("reads"),
                stats.get("total"),
                stats.get("max_end"),
                stats.get("errors"),
            )
            self._log_fh_state(fh, "release-closed")
        except OSError as exc:
            logger.error("RELEASE: failed fh=%s: %s", fh, exc)
            raise FUSEError(exc.errno if exc.errno else errno.EIO)

    async def flush(self, fh):
        """Flush file data to storage (FUSE flush)."""
        logger.info("FLUSH: fh=%s", fh)
        self._log_fh_state(fh, "flush-start")
        try:
            def _do_fsync():
                os.fsync(fh)

            await trio.to_thread.run_sync(_do_fsync)
            logger.info("FLUSH: fh=%s completed", fh)
        except OSError as exc:
            logger.error("FLUSH: failed fh=%s: %s", fh, exc)
            raise FUSEError(exc.errno if exc.errno else errno.EIO)

    async def fsync(self, fh, datasync):
        """Synchronize file contents to disk."""
        logger.info("FSYNC: fh=%s datasync=%s", fh, datasync)
        self._log_fh_state(fh, "fsync-start")
        try:
            def _do_fsync():
                if datasync:
                    os.fdatasync(fh)
                else:
                    os.fsync(fh)

            await trio.to_thread.run_sync(_do_fsync)
            logger.info("FSYNC: fh=%s completed", fh)
        except OSError as exc:
            logger.error("FSYNC: failed fh=%s: %s", fh, exc)
            raise FUSEError(exc.errno if exc.errno else errno.EIO)

    async def _apply_deferred_utime(self, inode: InodeT, path: str, atime_ns: int, mtime_ns: int):
        try:
            with trio.move_on_after(1) as cancel_scope:
                await trio.to_thread.run_sync(
                    lambda: os.utime(path, None, follow_symlinks=False, ns=(atime_ns, mtime_ns))
                )
            if cancel_scope.cancelled_caught:
                logger.warning("SETATTR DEFERRED TIMEOUT: inode=%s", inode)
            else:
                logger.info("SETATTR DEFERRED DONE: inode=%s", inode)
        except OSError as exc:
            logger.warning("SETATTR DEFERRED FAILED: inode=%s: %s", inode, exc)

    async def setattr(self, inode: InodeT, attr, fields, fh, ctx):
        """Set file attributes with logging."""
        path = self._inode_to_path(inode) if fh is None else f"fh={fh}"
        ops = []
        if fields.update_size:
            ops.append(f"size={attr.st_size}")
        if fields.update_mode:
            ops.append(f"mode={oct(attr.st_mode)}")
        if fields.update_uid:
            ops.append(f"uid={attr.st_uid}")
        if fields.update_gid:
            ops.append(f"gid={attr.st_gid}")
        if fields.update_atime:
            ops.append("atime")
        if fields.update_mtime:
            ops.append("mtime")
        
        logger.info("SETATTR START: inode=%s %s ops=[%s]", inode, path, ",".join(ops))
        try:
            has_times = fields.update_atime or fields.update_mtime
            has_other = fields.update_size or fields.update_mode or fields.update_uid or fields.update_gid

            async def _apply_non_time_updates_to_real_path(real_path: str):
                """Apply size/mode/ownership updates to a real backing path.

                This avoids recursive setattr calls when virtual paths are passed to
                Passthrough.setattr() with fh=None.
                """
                if fields.update_size:
                    await trio.to_thread.run_sync(lambda: os.truncate(real_path, attr.st_size))

                if fields.update_mode:
                    mode = attr.st_mode & 0o7777
                    await trio.to_thread.run_sync(lambda: os.chmod(real_path, mode))

                if fields.update_uid and fields.update_gid:
                    await trio.to_thread.run_sync(
                        lambda: os.chown(real_path, attr.st_uid, attr.st_gid, follow_symlinks=False)
                    )
                elif fields.update_uid:
                    await trio.to_thread.run_sync(
                        lambda: os.chown(real_path, attr.st_uid, -1, follow_symlinks=False)
                    )
                elif fields.update_gid:
                    await trio.to_thread.run_sync(
                        lambda: os.chown(real_path, -1, attr.st_gid, follow_symlinks=False)
                    )

            if has_times:
                atime_ns = attr.st_atime_ns
                mtime_ns = attr.st_mtime_ns
                if fh is not None:
                    self._pending_utime[inode] = (atime_ns, mtime_ns)
                    logger.info("SETATTR DEFERRED: inode=%s fh=%s", inode, fh)
                else:
                    real_path = self._inode_to_path(inode)
                    logger.info("SETATTR DEFERRED: inode=%s path=%s", inode, real_path)
                    trio.lowlevel.spawn_system_task(self._apply_deferred_utime, inode, real_path, atime_ns, mtime_ns)

                if not has_other:
                    entry_path = self._inode_to_path(inode)
                    parent_dir = os.path.dirname(entry_path)
                    cached = get_cached_getattr(entry_path, parent_dir)
                    if cached:
                        cached = dict(cached)
                        cached['st_atime'] = atime_ns / 1e9
                        cached['st_mtime'] = mtime_ns / 1e9
                        result = self._dict_to_entry_attributes(cached, inode)
                    else:
                        result = await self.getattr(inode, ctx)
                    logger.info("SETATTR DONE: inode=%s", inode)
                    return result

            if has_other:
                # Avoid passing virtual paths into Passthrough.setattr(fh=None), which can
                # recurse into FUSE and stall SMB create requests.
                if fh is None:
                    virtual_path = self._inode_to_path(inode)
                    real_path = get_source_path_for_write(logger, self.config, self.mount_path, virtual_path)
                    if not real_path:
                        real_path = get_source_path(logger, self.config, self.mount_path, virtual_path)

                    if isinstance(real_path, str):
                        await _apply_non_time_updates_to_real_path(real_path)
                        result = await self.getattr(inode, ctx)
                    else:
                        # Fallback for non-regular mappings where a direct path is unavailable.
                        result = await super().setattr(inode, attr, fields, fh, ctx)
                else:
                    # fh-based updates are safe in Passthrough (ftruncate/fchmod/fchown).
                    result = await super().setattr(inode, attr, fields, fh, ctx)
            else:
                result = await self.getattr(inode, ctx)
            logger.info("SETATTR DONE: inode=%s", inode)
            return result
        except Exception as exc:
            logger.error("SETATTR FAILED: inode=%s: %s", inode, exc)
            raise

    async def lookup(self, parent_inode: InodeT, name: bytes, ctx=None):
        """
        Look up a directory entry (pyfuse3 async version).
        Handles virtual path translation.
        """
        name_str = name.decode('utf-8') if isinstance(name, bytes) else name
        parent_path = self._inode_to_path(parent_inode)
        # Normalize to virtual path for consistency across readdir/lookup
        parent_path = self._normalize_to_virtual_path(parent_path)
        path = os.path.join(parent_path, name_str)
        logger.info(f"LOOKUP: '{name_str}' in inode {parent_inode}, parent_path={parent_path}, full_path={path}")

        # Special handling for . and ..
        if name_str == '.':
            logger.info(f"LOOKUP: returning parent inode for '.'")
            self._increment_lookup_count(parent_inode)
            return await self.getattr(parent_inode, ctx)
        if name_str == '..':
            parent_of_parent = str(Path(parent_path).parent)
            if parent_of_parent in self._inode_path_map.values():
                for inode, p in self._inode_path_map.items():
                    if p == parent_of_parent or (isinstance(p, set) and parent_of_parent in p):
                        logger.info(f"LOOKUP: returning inode {inode} for '..'")
                        self._increment_lookup_count(inode)
                        return await self.getattr(inode, ctx)
            # Fallback: use ROOT_INODE if we're at the top
            logger.info(f"LOOKUP: returning ROOT_INODE for '..'")
            self._increment_lookup_count(pyfuse3.ROOT_INODE)
            return await self.getattr(pyfuse3.ROOT_INODE, ctx)

        if self._is_hidden_root_alias_lookup(parent_inode, parent_path, name_str):
            alias_inode = self._make_synthetic_inode(path)
            self._add_path(alias_inode, path)
            logger.info("LOOKUP: treating hidden root alias '%s' as synthetic root inode=%s", name_str, alias_inode)
            self._increment_lookup_count(alias_inode)
            return await self.getattr(alias_inode, ctx)

        # Try to get source path (handles virtual translation)
        source_path = get_source_path(logger, self.config, self.mount_path, path)
        logger.info(f"LOOKUP: source_path={source_path}")

        # Generate inode for this path
        # Use consistent hash-based inode for deterministic lookups
        synthetic_inode = self._make_synthetic_inode(path)

        # Check if it's a real file/dir that exists
        if source_path and isinstance(source_path, str) and os.path.exists(source_path):
            filestore_root = self.config.get("filestore", "/mnt/filestorefs") if isinstance(self.config, dict) else "/mnt/filestorefs"
            # Avoid inode collisions for virtual client roots that map to filestore root
            if os.path.normpath(source_path) == os.path.normpath(filestore_root):
                self._add_path(synthetic_inode, path)
                logger.info(f"LOOKUP: SUCCESS - virtual root mapping, synthetic_inode={synthetic_inode}")
                self._increment_lookup_count(synthetic_inode)
                return await self.getattr(synthetic_inode, ctx)

            # CRITICAL: Use synthetic inodes for ALL directories.
            # Multiple virtual paths (e.g., MiSTer/3do and MAME/ROMS/3do) can resolve
            # to the same physical directory (same inode). Using the physical inode causes
            # the second lookup to reuse the first path's inode and readdir returns wrong
            # entries. Synthetic inodes are keyed on virtual path, so each virtual path
            # gets its own inode regardless of what's on disk.
            if os.path.isdir(source_path):
                self._add_path(synthetic_inode, path)
                logger.info(f"LOOKUP: SUCCESS - real dir (using synthetic inode), synthetic_inode={synthetic_inode}")
                self._increment_lookup_count(synthetic_inode)
                return await self.getattr(synthetic_inode, ctx)

            # Real file - use its actual inode for consistency with what the kernel has
            stat = os.lstat(source_path)
            actual_inode = stat.st_ino
            self._add_path(actual_inode, path)
            logger.info(f"LOOKUP: SUCCESS - real file, inode={actual_inode}")
            self._increment_lookup_count(actual_inode)
            return await self.getattr(actual_inode, ctx)

        # Check if it's a file in a zip
        if source_path and isinstance(source_path, tuple):
            # File in zip - use synthetic inode
            self._add_path(synthetic_inode, path)
            logger.info(f"LOOKUP: SUCCESS - zip file, synthetic_inode={synthetic_inode}")
            self._increment_lookup_count(synthetic_inode)
            return await self.getattr(synthetic_inode, ctx)

        # Check if it's a transformed file (dict with path)
        if source_path and isinstance(source_path, dict) and 'path' in source_path:
            real_path = source_path['path']
            if isinstance(real_path, str) and os.path.exists(real_path):
                self._add_path(synthetic_inode, path)
                logger.info(f"LOOKUP: SUCCESS - transformed file, synthetic_inode={synthetic_inode}")
                self._increment_lookup_count(synthetic_inode)
                return await self.getattr(synthetic_inode, ctx)

        # Database-backed fallback for query-map entries.
        # Some virtual files only exist in the metadata index and are resolved later
        # at open time (for example archive members flattened into a query map).
        map_info = self._extract_map_info(path)
        if map_info:
            stat_dict = await self._getattr_database_only(path, map_info)
            if stat_dict:
                self._add_path(synthetic_inode, path)
                logger.info(f"LOOKUP: SUCCESS - database-only query map entry, synthetic_inode={synthetic_inode}")
                self._increment_lookup_count(synthetic_inode)
                return await self.getattr(synthetic_inode, ctx)

        # Fallback for writable paths: allow lookup of physically created files
        # even when parse_trans_path caches haven't listed them yet.
        writable_path = get_source_path_for_write(logger, self.config, self.mount_path, path)
        if writable_path and os.path.exists(writable_path):
            self._add_path(synthetic_inode, path)
            logger.info(f"LOOKUP: SUCCESS - writable fallback path exists: {writable_path}")
            self._increment_lookup_count(synthetic_inode)
            return await self.getattr(synthetic_inode, ctx)

        # Check if it's a virtual directory/file by checking if it would be listed
        parent_entries = self._get_parent_entries_for_lookup(parent_path)
        logger.info("LOOKUP: parent_entries_count=%d", len(parent_entries))
        
        # First try exact match
        if name_str in parent_entries:
            # It's a virtual entry - use synthetic inode
            self._add_path(synthetic_inode, path)
            logger.info(f"LOOKUP: SUCCESS - virtual entry in parent, synthetic_inode={synthetic_inode}")
            self._increment_lookup_count(synthetic_inode)
            return await self.getattr(synthetic_inode, ctx)
        
        # Try case-insensitive match for compatibility with case-insensitive clients
        # (e.g., MiSTer looking for 'ARCHIE' when config has 'Archie')
        name_lower = name_str.lower()
        for entry in parent_entries:
            if entry.lower() == name_lower:
                # Found case-insensitive match - use the actual entry name
                actual_path = os.path.join(parent_path, entry)
                self._add_path(synthetic_inode, actual_path)
                logger.info(f"LOOKUP: SUCCESS - case-insensitive match '{name_str}' -> '{entry}', synthetic_inode={synthetic_inode}")
                self._increment_lookup_count(synthetic_inode)
                return await self.getattr(synthetic_inode, ctx)

        # Not found
        logger.info(f"LOOKUP: FAILED - not found: {name_str}")
        raise FUSEError(errno.ENOENT)

    async def create(self, parent_inode: InodeT, name: bytes, mode, flags, ctx):
        """Create and open a file."""
        name_str = name.decode('utf-8') if isinstance(name, bytes) else name
        logger.debug("CREATE: called with name=%s, mode=%s", name_str, oct(mode))
        
        parent_path = self._inode_to_path(parent_inode)
        trans_path = os.path.join(parent_path, name_str)
        real_path = get_source_path_for_write(logger, self.config, self.mount_path, trans_path)
        logger.debug("CREATE: path=%s, real_path=%s", trans_path, real_path)
        
        if real_path is None:
            logger.debug("CREATE: EROFS (no mapping)")
            raise FUSEError(errno.EROFS)
        
        real_dir = os.path.dirname(real_path)
        logger.debug("CREATE: real_dir=%s", real_dir)
        try:
            os.makedirs(real_dir, exist_ok=True)
            logger.debug("CREATE: ensured directory exists: %s", real_dir)
        except Exception as e:
            logger.debug("CREATE: failed to create directory %s: %s", real_dir, e)
            raise FUSEError(errno.EACCES)
        
        if os.path.isdir(real_path):
            logger.debug("CREATE: EISDIR (is a directory)")
            raise FUSEError(errno.EISDIR)
        
        try:
            fd = os.open(real_path, os.O_WRONLY | os.O_CREAT, mode)
            logger.debug("CREATE: success fd=%s", fd)
            
            attr = self._getattr(path=real_path)
            self._add_path(attr.st_ino, trans_path)
            self._inode_fd_map[attr.st_ino] = fd
            self._fd_inode_map[fd] = attr.st_ino
            self._fd_open_count[fd] = 1

            normalized_parent = self._normalize_to_virtual_path(parent_path)
            self._lookup_parent_entries_cache.pop(normalized_parent, None)
            return (pyfuse3.FileInfo(fh=fd), attr)
        except Exception as e:
            logger.debug("CREATE: Exception %s", e)
            raise FUSEError(errno.EACCES)

    async def mkdir(self, parent_inode: InodeT, name: bytes, mode, ctx):
        """Create a directory."""
        name_str = name.decode('utf-8') if isinstance(name, bytes) else name
        logger.debug("MKDIR: called with name=%s, mode=%s", name_str, oct(mode))
        
        parent_path = self._inode_to_path(parent_inode)
        path = os.path.join(parent_path, name_str)
        
        # Use write path mapper for mkdir operations (allows creating in mapped write paths)
        real_path = get_source_path_for_write(logger, self.config, self.mount_path, path)
        if real_path is None:
            logger.debug("MKDIR: EROFS (no write mapping)")
            raise FUSEError(errno.EROFS)
        
        os.makedirs(real_path, mode=mode, exist_ok=True)
        logger.debug("MKDIR: created directory %s", real_path)
        attr = self._getattr(path=real_path)
        self._add_path(attr.st_ino, path)
        return attr

    async def unlink(self, parent_inode: InodeT, name: bytes, ctx):
        """Delete a file."""
        name_str = name.decode('utf-8') if isinstance(name, bytes) else name
        start_time = time.time()
        logger.info(f"UNLINK START: {name_str}")
        
        parent_path = self._inode_to_path(parent_inode)
        path = os.path.join(parent_path, name_str)
        
        # Get real path first (before invalidating cache)
        t_get_path_start = time.time()
        real_path = get_source_path_for_write(logger, self.config, self.mount_path, path)
        t_get_path = time.time() - t_get_path_start
        
        logger.debug("UNLINK: path=%s, real_path=%s", path, real_path)
        
        if real_path is None or not os.path.exists(real_path):
            logger.debug("UNLINK: ENOENT")
            raise FUSEError(errno.ENOENT)
        
        try:
            t_unlink_start = time.time()
            inode = os.lstat(real_path).st_ino
            os.unlink(real_path)
            t_unlink = time.time() - t_unlink_start
            
            elapsed = time.time() - start_time
            logger.info(f"UNLINK COMPLETE: {name_str} total={elapsed:.3f}s get_path={t_get_path:.3f}s unlink={t_unlink:.3f}s")
            
            # Invalidate subdirectory query cache for parent directory
            # This ensures next READDIR sees the updated file count
            try:
                from dirlisting import _subdir_query_cache, _empty_subdir_cache
                # Convert parent path to virtual path format for cache key
                if parent_path.startswith(self.mount_path):
                    cache_key = parent_path[len(self.mount_path):].strip('/').replace('\\', '/')
                    if cache_key in _subdir_query_cache:
                        del _subdir_query_cache[cache_key]
                        logger.debug(f"UNLINK: invalidated subdir cache for {cache_key}")
                    if cache_key in _empty_subdir_cache:
                        del _empty_subdir_cache[cache_key]
            except Exception as e:
                logger.debug(f"UNLINK: cache invalidation failed: {e}")

            self._lookup_parent_entries_cache.pop(parent_path, None)
                
        except OSError as exc:
            elapsed = time.time() - start_time
            logger.info("UNLINK ERROR: %s after %.3fs (errno=%s)", name_str, elapsed, exc.errno)
            raise FUSEError(exc.errno)
        
        if inode in self._lookup_cnt:
            self._forget_path(inode, path)
    async def rmdir(self, parent_inode: InodeT, name: bytes, ctx):
        """Delete a directory."""
        name_str = name.decode('utf-8') if isinstance(name, bytes) else name
        logger.debug("RMDIR: called with name=%s", name_str)
        
        parent_path = self._inode_to_path(parent_inode)
        path = os.path.join(parent_path, name_str)
        # Use write path mapper to allow deletion in writable areas
        real_path = get_source_path_for_write(logger, self.config, self.mount_path, path)
        logger.debug("RMDIR: path=%s, real_path=%s", path, real_path)
        
        if real_path is None or not os.path.exists(real_path):
            logger.debug("RMDIR: ENOENT")
            raise FUSEError(errno.ENOENT)
        
        try:
            inode = os.lstat(real_path).st_ino
            os.rmdir(real_path)  # Will fail with ENOTEMPTY if directory not empty
            
            # Invalidate subdirectory query cache for parent directory
            try:
                from dirlisting import _subdir_query_cache, _empty_subdir_cache
                if parent_path.startswith(self.mount_path):
                    cache_key = parent_path[len(self.mount_path):].strip('/').replace('\\', '/')
                    if cache_key in _subdir_query_cache:
                        del _subdir_query_cache[cache_key]
                        logger.debug(f"RMDIR: invalidated subdir cache for {cache_key}")
                    if cache_key in _empty_subdir_cache:
                        del _empty_subdir_cache[cache_key]
            except Exception as e:
                logger.debug(f"RMDIR: cache invalidation failed: {e}")

            self._lookup_parent_entries_cache.pop(parent_path, None)
                
        except OSError as exc:
            logger.debug("RMDIR: OSError errno=%s", exc.errno)
            raise FUSEError(exc.errno)
        
        if inode in self._lookup_cnt:
            self._forget_path(inode, path)

    def getxattr(self, inode: InodeT, name: str, ctx):
        """
        Return extended attributes.
        Since we're a translation layer, we don't support xattrs.
        """
        raise FUSEError(errno.ENODATA)

    async def access(self, inode: InodeT, mode: int, ctx):
        """
        Check if operation is allowed.
        For a virtual filesystem, we allow all operations.
        """
        logger.debug("ACCESS: inode=%s mode=%s", inode, oct(mode))
        return True

    async def statfs(self, ctx):
        """Return filesystem statistics from the underlying filestore."""
        stat_ = pyfuse3.StatvfsData()
        statfs = os.statvfs('/mnt/filestorefs')

        for attr in ('f_bsize', 'f_frsize', 'f_blocks', 'f_bfree', 'f_bavail',
                     'f_files', 'f_ffree', 'f_favail', 'f_namemax'):
            setattr(stat_, attr, getattr(statfs, attr))

        return stat_


async def main_async(mount_path: str, root_path: str):
    """Async main function for pyfuse3."""
    global _fuse_instance
    
    import signal
    from config import read_app_config
    from cache_warmer import CacheWarmer
    from dirlisting import set_cache_config
    from startup_prewarm import prewarm_hotpaths, prewarm_subdirectory_cache, prewarm_recursive_indexes

    # Initialize cache configuration from app.yaml
    app_config = read_app_config()
    cache_config = app_config.get('cache', {})
    perf_config = app_config.get('performance', {})
    
    # Performance tuning settings
    use_mmap = perf_config.get('use_mmap_for_reads', False)
    mmap_threshold = perf_config.get('mmap_threshold_bytes', 10485760)  # 10MB default
    logger.info(f"Performance: use_mmap={use_mmap}, threshold={mmap_threshold / 1048576:.1f}MB")
    
    # Create TransFS instance with performance settings
    fs = TransFS(root_path, mount_path)
    fs._use_mmap = use_mmap
    fs._mmap_threshold = mmap_threshold
    set_cache_config(cache_config)
    
    # Store global reference for API access
    _fuse_instance = fs
    
    # Write FUSE process PID to a file for API access
    fuse_pid = os.getpid()
    pid_file = "/tmp/transfs_fuse.pid"
    try:
        with open(pid_file, 'w') as f:
            f.write(str(fuse_pid))
        logger.info(f"FUSE process PID {fuse_pid} written to {pid_file}")
    except Exception as e:  # pylint: disable=broad-except
        logger.warning(f"Failed to write PID file {pid_file}: {e}")
    
    # Register SIGHUP handler for config reload
    def sighup_handler(signum, frame):
        logger.info("Received SIGHUP - reloading config...")
        result = fs.reload_config_from_disk()
        if result['success']:
            logger.info(f"SIGHUP handler: {result['message']}")
        else:
            logger.error(f"SIGHUP handler failed: {result['error']}")
    
    signal.signal(signal.SIGHUP, sighup_handler)
    logger.info("SIGHUP signal handler registered for config reload")
    
    # Pre-warm hot paths BEFORE mounting filesystem
    logger.info("Pre-warming hot paths at startup...")
    try:
        prewarm_hotpaths(
            config=fs.config,
            root_path=root_path,
            mount_path=mount_path,
            data_adapter=fs.data_adapter,
            readdir_cache_dict=fs._db_readdir_cache,
            config_readdir_cache_dict=fs._config_readdir_cache,
            db_readdir_cache_ttl=fs._db_readdir_cache_ttl,
            config_readdir_cache_ttl=fs._config_readdir_cache_ttl
        )
        prewarm_subdirectory_cache(fs.config, mount_path)
        prewarm_recursive_indexes(fs.config, root_path)
    except Exception as e:
        logger.warning(f"Hot-path pre-warm failed (non-fatal): {e}")

    fuse_options = set(pyfuse3.default_options)
    fuse_options.add('fsname=transfs')
    fuse_options.add('allow_other')
    fuse_options.discard('default_permissions')
    fuse_options.discard('ro')  # Ensure read-only is not set
    
    # NOTE: pyfuse3 doesn't support direct_io, auto_cache, timeout, or max_read options via mount options
    # max_read must be set via pyfuse3.init() max_read parameter instead
    # SMB stability will rely on Samba keepalive settings instead

    logger.info(f"Mounting TransFS at {mount_path} with root {root_path}")
    logger.info(f"FUSE options: {fuse_options}")
    pyfuse3.init(fs, mount_path, fuse_options)

    # Start cache warmer
    warmer_config = app_config.get("cache_warmer", {})

    warmer = CacheWarmer(
        mount_point=mount_path,
        readdir_func=fs.readdir,
        config=warmer_config
    )
    warmer.start()

    try:
        logger.info("Starting pyfuse3 main loop")
        await pyfuse3.main()
    finally:
        logger.info("Unmounting TransFS")
        warmer.stop()
        pyfuse3.close(unmount=True)



def reload_fuse_config() -> dict:
    """Trigger config reload in the FUSE process from the API.
    
    Sends SIGHUP signal to the FUSE process which triggers the registered
    signal handler to safely reload configuration.
    
    Returns:
        Dictionary with success status and result message
    """
    import signal as signal_module
    
    # Read FUSE process PID from file
    pid_file = "/tmp/transfs_fuse.pid"
    
    try:
        try:
            with open(pid_file, 'r') as f:
                fuse_pid = int(f.read().strip())
        except (FileNotFoundError, ValueError) as e:
            logger.error(f"Failed to read FUSE PID from {pid_file}: {e}")
            return {
                "success": False,
                "error": "FUSE process PID not found - ensure FUSE process has started"
            }
        
        # Send SIGHUP to FUSE process
        logger.info(f"Sending SIGHUP to FUSE process (PID {fuse_pid})")
        os.kill(fuse_pid, signal_module.SIGHUP)
        
        return {
            "success": True,
            "message": "SIGHUP signal sent to FUSE process - configuration reload initiated",
            "fuse_pid": fuse_pid
        }
    except ProcessLookupError:
        logger.error(f"FUSE process with PID {fuse_pid} not found")
        return {
            "success": False,
            "error": f"FUSE process (PID {fuse_pid}) not found - may have crashed"
        }
    except PermissionError:
        logger.error(f"Permission denied sending signal to FUSE process (PID {fuse_pid})")
        return {
            "success": False,
            "error": "Permission denied - cannot signal FUSE process"
        }
    except Exception as e:  # pylint: disable=broad-except
        logger.error(f"Failed to signal FUSE process: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


def main(mount_path: str, root_path: str):
    """Entry point - runs async main with Trio."""
    trio.run(main_async, mount_path, root_path)


if __name__ == '__main__':
    main(mount_path="/mnt/transfs", root_path="/mnt/filestorefs")
