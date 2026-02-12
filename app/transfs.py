#!/usr/bin/env python3
"""
Async TransFS filesystem using pyfuse3.

This is the pyfuse3 version of TransFS with async operations and inode-based interface.
"""

import errno
import logging
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
from dirlisting import parse_trans_path, get_cached_getattr, cache_getattr
from pathutils import full_path, is_virtual_path, map_virtual_to_real
from sourcepath import get_source_path, get_source_path_for_write
from zippath import open_file as zippath_open_file
from logging_setup import setup_logging
from data_provider_init import initialize_data_provider, get_data_provider_manager
from fuse_adapter import FUSEOperationAdapter

setup_logging(logging.INFO)
logger = logging.getLogger("transfs")
logger.info("TransFS logging initialized (pyfuse3 version)")


class TransFS(Passthrough):
    """
    FUSE filesystem for translating virtual paths to real files with zip support.
    Async version using pyfuse3.
    """
    
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
        from config import read_config
        self.config = read_config()
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
    
    def _is_database_mode_enabled(self) -> bool:
        """Check if database mode is enabled and adapter is available."""
        return self.data_adapter is not None and self.data_adapter.is_database_mode()
    
    def _can_use_database(self, path: str) -> bool:
        """Check if database can be used for this path (database mode + path is suitable)."""
        if not self.data_adapter:
            return False
        # Only use database for Native paths for now
        # TODO: Expand to other paths once database is populated
        return path.startswith(os.path.join(self.mount_path, "Native"))

    def _get_zip_mode_for_path(self, xfull_path: str) -> str:
        """
        Extract zip_mode configuration for the given path.
        Returns 'hierarchical' (default), 'flatten', or 'file'.
        """
        from pathutils import get_client, get_system_info, find_software_archive_entry
        
        path = Path(xfull_path)
        root_parts = Path(self.root).parts
        rel_parts = path.parts[len(root_parts):]
        
        if len(rel_parts) < 3:
            return "hierarchical"
        
        client = get_client(self.config, rel_parts)
        if not client:
            return "hierarchical"
        
        path_template_parts = Path(client['default_target_path']).parts
        system_info = get_system_info(client, list(rel_parts), path_template_parts)
        if not system_info:
            return "hierarchical"
        
        sa_entry = find_software_archive_entry(system_info)
        if not sa_entry:
            return "hierarchical"
        
        return sa_entry["...SoftwareArchives..."].get("zip_mode", "hierarchical")

    def _get_transform_output_size(self, pipeline, source_size: int) -> int:
        """Get transform output size with optional caching."""
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
        from pathutils import get_client, get_system_info
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
            
            # Find the SoftwareArchives entry
            sa_entry = find_software_archive_entry(system_info)
            if not sa_entry:
                return {}
            
            # Get transform configuration - this maps extensions to transform specs
            transform_map = get_filetype_transforms(sa_entry)
            if not transform_map:
                return {}
            
            # Build transform pipeline for each extension that has transforms
            pipeline_map = {}
            cache_config = self.config.get("cache", {})
            
            for ext in transform_map.keys():
                # Build pipeline for this extension
                dummy_filename = f"test.{ext.lower()}"
                pipeline = get_transform_pipeline_for_file(
                    logger, 
                    system_info, 
                    dummy_filename, 
                    virtual_folder,
                    cache_config
                )
                if pipeline:
                    pipeline_map[ext.upper()] = pipeline
            
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
        """Generate a consistent synthetic inode from a path."""
        synthetic_inode = abs(hash(path)) & 0x7FFFFFFF
        if synthetic_inode == 0:
            synthetic_inode = 1
        if synthetic_inode == pyfuse3.ROOT_INODE:
            synthetic_inode += 1
        return synthetic_inode

    def _increment_lookup_count(self, inode: InodeT) -> None:
        """Increment the lookup reference count for an inode."""
        self._lookup_cnt[inode] += 1
        logger.info(f"INC_LOOKUP_CNT: inode={inode} count={self._lookup_cnt[inode]}")

    def _normalize_to_virtual_path(self, path: str) -> str:
        """Convert real filesystem path to virtual mount path for consistency."""
        # If it's already a virtual path, keep it
        if path.startswith(self.mount_path):
            return path
        # If it's a real path, convert it back to virtual
        if path.startswith("/mnt/filestorefs"):
            rel_path = os.path.relpath(path, "/mnt/filestorefs")
            if rel_path == '.':
                # If it's the root directory, return mount_path without the '.'
                return self.mount_path
            return os.path.join(self.mount_path, rel_path)
        return path

    async def readdir(self, fh: FileHandleT, start_id: int, token):
        """
        Read directory entries with FULL attributes (readdirplus support).
        Optimized to batch-resolve virtual paths and use cache efficiently.
        """
        t_start = time.time()
        path = self._inode_to_path(fh)
        # Normalize to virtual path for consistency
        path = self._normalize_to_virtual_path(path)
        logger.info("READDIR START: path=%s start_id=%d", path, start_id)
        
        # Try database mode first if enabled and path is suitable
        if self._can_use_database(path):
            try:
                logger.info(f"READDIR: using database mode for {path}")
                db_entries = self.data_adapter.readdir_entries(path)
                if db_entries:
                    sent_count = 0
                    for entry_id, (entry_name, stat_dict) in enumerate(db_entries, start=1):
                        if entry_id <= start_id:
                            continue
                        entry_path = os.path.join(path, entry_name)
                        entry_inode = self._make_synthetic_inode(entry_path)
                        self._add_path(entry_inode, entry_path)
                        entry = self._dict_to_entry_attributes(stat_dict, entry_inode)
                        if not pyfuse3.readdir_reply(token, entry_name.encode('utf-8'), entry, entry_id):
                            break
                        sent_count += 1
                    t_total = time.time() - t_start
                    logger.info(f"READDIR DATABASE: sent {sent_count} entries in {t_total:.4f}s")
                    return
            except Exception as e:
                logger.warning(f"READDIR: database mode failed, falling back to cache: {e}")
        
        xfull_path = path
        # Get the real source path for this directory (handles virtual mappings)
        parent_source = get_source_path(logger, self.config, self.mount_path, xfull_path)
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
                
                with os.scandir(parent_dir) as entries:
                    for entry in entries:
                        # Skip hidden files (starting with .) - includes cache files
                        # Skip subdirectories that are extension folders (they'll be merged)
                        if entry.name.startswith('.'):
                            continue
                        if entry.is_dir() and entry.name.isupper() and 2 <= len(entry.name) <= 4:
                            continue  # Skip extension subdirs like BIN/, ROM/, A52/
                        if direntry_cache_enabled:
                            dir_entry_cache[entry.name] = entry
                        if entry.name not in existing:
                            virtual_entries.append(entry.name)
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
                            if entry.name.startswith('.'):
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
        
        # Optimize for Native paths - skip expensive get_source_path() call
        is_native_path = parent_dir.startswith("/mnt/filestorefs/Native/")
        
        # Build system-level transform map for this directory (MAJOR OPTIMIZATION)
        # Instead of calling get_source_path() 400+ times, build the map once
        t_transform_map_start = time.time()
        system_transform_map = self._build_system_transform_map(xfull_path)
        t_transform_map = time.time() - t_transform_map_start
        
        logger.debug(f"READDIR: {len(virtual_entries)} entries parsed from {parent_dir}")
        
        # Batch get source paths for ALL entries (much faster than one-by-one)
        t_batch_start = time.time()
        source_paths = {}
        t_cache_check = 0
        t_path_resolve = 0
        t_get_source_path = 0
        get_source_path_calls = 0
        cache_checked = 0
        
        # Skip expensive cache lookups if we have DirEntry cache for all entries
        skip_cache_lookup = False
        if skip_cache_lookup_enabled and dir_entry_cache:
            missing_entries = [name for name in virtual_entries if name not in dir_entry_cache]
            if not missing_entries:
                skip_cache_lookup = True
            else:
                skip_cache_lookup = all(
                    is_virtual_path(self.config, self.mount_path, os.path.join(xfull_path, entry_name))
                    for name in missing_entries
                )
        
        fast_listing = len(virtual_entries) > fast_listing_threshold

        for entry_name in virtual_entries:
            entry_path = os.path.join(xfull_path, entry_name)
            
            # For directories with full DirEntry cache, skip the expensive cache lookup
            if skip_cache_lookup:
                # Fast path: we'll use DirEntry stat later
                # NEW: Try system transform map first before expensive get_source_path
                if system_transform_map:
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
            else:
                # Slow path: check cache first
                t_check_start = time.time()
                cached = get_cached_getattr(entry_path, parent_dir)
                t_cache_check += time.time() - t_check_start
                cache_checked += 1
                
                if cached:
                    source_paths[entry_name] = ('cached', cached)
                else:
                    # Fast path for Native: source path is just the parent_dir + entry_name
                    t_resolve_start = time.time()
                    if is_native_path:
                        fspath = os.path.join(parent_dir, entry_name)
                    else:
                        # Get source path for non-Native entries (may be expensive)
                        t_gsp = time.time()
                        fspath = get_source_path(logger, self.config, self.mount_path, entry_path)
                        t_get_source_path += time.time() - t_gsp
                        get_source_path_calls += 1
                    t_path_resolve += time.time() - t_resolve_start
                    source_paths[entry_name] = ('uncached', fspath)
        
        t_batch = time.time() - t_batch_start
        logger.info(f"READDIR BATCH: {len(virtual_entries)} entries, transform_map={len(system_transform_map)} exts, get_source_path={get_source_path_calls} calls, time={t_batch:.4f}s skip_cache={skip_cache_lookup}")
        
        # Send entries with full attributes
        sent_count = 0
        cache_hits = 0
        
        for entry_id, entry_name in enumerate(virtual_entries, start=1):
            if entry_id <= start_id:
                continue
            
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
                    elif isinstance(fspath, str) and fspath.lower().endswith('.zip'):
                        # Zip file itself
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
                        # Regular file - use cached DirEntry stat if available (avoids extra stat!)
                        # BUT: If there's a pipeline, we can't trust DirEntry cache (file may be from different source dir)
                        if not pipeline and entry_name in dir_entry_cache:
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
            
            # Send entry to client
            if not pyfuse3.readdir_reply(token, entry_name.encode('utf-8'), entry, entry_id):
                logger.info(f"READDIR: client buffer full after {sent_count} entries")
                break
            
            sent_count += 1
        
        t_total = time.time() - t_start
        hit_rate = (cache_hits / len(virtual_entries) * 100) if virtual_entries else 0
        logger.info(f"READDIR COMPLETE: {path} entries={len(virtual_entries)} sent={sent_count} "
                   f"cache_hits={cache_hits} hit_rate={hit_rate:.1f}% "
                   f"parse={t_parse:.4f}s batch={t_batch:.4f}s total={t_total:.4f}s")


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
        
        logger.info(f"GETATTR: inode={inode} path={path}")
        logger.debug("DEBUG: getattr(inode=%s) path=%s", inode, path)
        
        # Try database mode first if enabled and path is suitable
        if self._can_use_database(path):
            try:
                logger.info(f"GETATTR: using database mode for {path}")
                stat_dict = self.data_adapter.getattr_stat(path)
                if stat_dict:
                    t_total = time.time() - t_start
                    TransFS._getattr_count += 1
                    TransFS._getattr_total_time += t_total
                    logger.info(f"GETATTR DATABASE: found entry in {t_total:.4f}s")
                    return self._dict_to_entry_attributes(stat_dict, inode)
            except Exception as e:
                logger.warning(f"GETATTR: database mode failed, falling back to cache: {e}")
        
        xfull_path = path  # Already full path from inode map
        logger.info(f"GETATTR: about to compute parent_dir from {xfull_path}")
        
        # Try cache first
        t_cache_start = time.time()
        parent_path = str(Path(xfull_path).parent)
        logger.info(f"GETATTR: parent_path={parent_path}")
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
        logger.info(f"GETATTR: parent_dir={parent_dir}")
        
        cached_stat = get_cached_getattr(xfull_path, parent_dir)
        t_cache_elapsed = time.time() - t_cache_start
        
        if cached_stat is not None:
            # Check if this is a placeholder directory entry (from readdir for virtual paths)
            # These have mode=0o040755 and size=4096 - skip cache and resolve properly
            is_placeholder = (cached_stat.get('st_mode') == 0o040755 and 
                            cached_stat.get('st_size') == 4096 and
                            cached_stat.get('st_nlink') == 2)
            
            if not is_placeholder:
                t_total = time.time() - t_start
                TransFS._getattr_cache_hits += 1
                TransFS._getattr_count += 1
                TransFS._getattr_total_time += t_total
                logger.debug("GETATTR CACHE HIT: inode=%s (cache_lookup=%.4fs, total=%.4fs)", inode, t_cache_elapsed, t_total)
                self._maybe_print_stats()
                
                # Convert dict to EntryAttributes
                return self._dict_to_entry_attributes(cached_stat, inode)
            else:
                logger.debug("GETATTR: skipping placeholder cache entry for %s", xfull_path)
        
        TransFS._getattr_cache_misses += 1
        logger.debug("GETATTR CACHE MISS: inode=%s (cache_lookup=%.4fs)", inode, t_cache_elapsed)
        
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
            transformed_size = self._get_transform_output_size(pipeline, source_size)
            
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
                # Check if it's a virtual directory
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
            
            raise FUSEError(errno.ENOENT)

        # Handle zip files based on zip_mode
        if isinstance(fspath, str) and fspath.lower().endswith('.zip'):
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
        
        # If we can't handle it, raise ENOENT
        logger.error(f"GETATTR: unhandled case for inode={inode} fspath={fspath}")
        raise FUSEError(errno.ENOENT)
    
    async def open(self, inode: InodeT, flags: int, ctx):
        """Open a file (pyfuse3 async version)."""
        path = self._inode_to_path(inode)
        logger.info("OPEN: inode=%s, flags=%s, path=%s", inode, flags, path)
        
        # Path from _inode_to_path is already in mount format
        trans_path = get_source_path(logger, self.config, self.mount_path, path)
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
            try:
                with zippath_open_file(f"{zip_path}/{internal_file}", "rb") as f:
                    temp = tempfile.NamedTemporaryFile(mode='wb', delete=False)
                    content = f.read()
                    if isinstance(content, str):
                        content = content.encode('utf-8')
                    temp.write(content)
                    temp.close()
                    logger.debug("DEBUG: open temp file created at %s", temp.name)
                    fd = os.open(temp.name, flags)
                    self._fd_inode_map[fd] = inode
                    self._inode_fd_map[inode] = fd
                    self._fd_open_count[fd] = 1
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
            
            try:
                # Read source file and apply transformations
                with open(source_path, 'rb') as source_file:
                    # Get source file size
                    source_file.seek(0, os.SEEK_END)
                    source_size = source_file.tell()
                    source_file.seek(0)
                    
                    # Calculate output size
                    output_size = self._get_transform_output_size(pipeline, source_size)
                    
                    # Read and transform all data
                    # For now, read entire file - could optimize for large files later
                    transformed_data = pipeline.apply_transforms(source_file, 0, output_size if output_size >= 0 else source_size)
                    
                    # Write to temp file
                    temp = tempfile.NamedTemporaryFile(mode='wb', delete=False)
                    temp.write(transformed_data)
                    temp.close()
                    logger.debug("DEBUG: open created transformed temp file at %s (size: %d -> %d)", 
                                temp.name, source_size, len(transformed_data))
                    
                    # Open temp file
                    fd = os.open(temp.name, flags)
                    self._fd_inode_map[fd] = inode
                    self._inode_fd_map[inode] = fd
                    self._fd_open_count[fd] = 1
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
                        self._fd_inode_map[fd] = inode
                        self._inode_fd_map[inode] = fd
                        self._fd_open_count[fd] = 1
                        logger.info("OPEN: created new file, fd=%s", fd)
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
                # Check if already open
                if inode in self._inode_fd_map:
                    fd = self._inode_fd_map[inode]
                    self._fd_open_count[fd] += 1
                    logger.info("OPEN: file already open, fd=%s, count=%s", fd, self._fd_open_count[fd])
                    return pyfuse3.FileInfo(fh=fd)
                
                fd = os.open(trans_path, flags)
                self._fd_inode_map[fd] = inode
                self._inode_fd_map[inode] = fd
                self._fd_open_count[fd] = 1
                logger.info("OPEN: opened successfully, fd=%s", fd)
                return pyfuse3.FileInfo(fh=fd)
            except OSError as exc:
                logger.error("OPEN: failed to open %s: %s", trans_path, exc)
                raise FUSEError(exc.errno if exc.errno else errno.EIO)

        logger.debug("DEBUG: open: unknown mapping")
        raise FUSEError(errno.ENOENT)

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

        # Try to get source path (handles virtual translation)
        source_path = get_source_path(logger, self.config, self.root, path)
        logger.info(f"LOOKUP: source_path={source_path}")

        # Generate inode for this path
        # Use consistent hash-based inode for deterministic lookups
        synthetic_inode = self._make_synthetic_inode(path)

        # Check if it's a real file that exists
        if source_path and isinstance(source_path, str) and os.path.exists(source_path):
            filestore_root = self.config.get("filestore", "/mnt/filestorefs") if isinstance(self.config, dict) else "/mnt/filestorefs"
            # Avoid inode collisions for virtual client roots that map to filestore root
            if os.path.normpath(source_path) == os.path.normpath(filestore_root):
                self._add_path(synthetic_inode, path)
                logger.info(f"LOOKUP: SUCCESS - virtual root mapping, synthetic_inode={synthetic_inode}")
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

        # Check if it's a virtual directory/file by checking if it would be listed
        parent_entries = set(parse_trans_path(self.config, self.root, parent_path))
        logger.info(f"LOOKUP: parent_entries={parent_entries}")
        
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
            return (pyfuse3.FileInfo(fh=fd), attr)
        except Exception as e:
            logger.debug("CREATE: Exception %s", e)
            raise FUSEError(errno.EACCES)

    async def mkdir(self, parent_inode: InodeT, name: bytes, mode, ctx):
        """Create a directory."""
        name_str = name.decode('utf-8') if isinstance(name, bytes) else name
        parent_path = self._inode_to_path(parent_inode)
        path = os.path.join(parent_path, name_str)
        
        real_path = map_virtual_to_real(self.config, path)
        if real_path is None:
            raise FUSEError(errno.EROFS)
        
        os.makedirs(real_path, mode=mode, exist_ok=True)
        attr = self._getattr(path=real_path)
        self._add_path(attr.st_ino, path)
        return attr

    async def unlink(self, parent_inode: InodeT, name: bytes, ctx):
        """Delete a file."""
        name_str = name.decode('utf-8') if isinstance(name, bytes) else name
        logger.debug("UNLINK: called with name=%s", name_str)
        
        parent_path = self._inode_to_path(parent_inode)
        path = os.path.join(parent_path, name_str)
        real_path = map_virtual_to_real(self.config, path)
        logger.debug("UNLINK: real_path=%s", real_path)
        
        if real_path is None or not os.path.exists(real_path):
            logger.debug("UNLINK: ENOENT")
            raise FUSEError(errno.ENOENT)
        
        try:
            inode = os.lstat(real_path).st_ino
            os.unlink(real_path)
        except OSError as exc:
            raise FUSEError(exc.errno)
        
        if inode in self._lookup_cnt:
            self._forget_path(inode, path)

    def getxattr(self, inode: InodeT, name: str, ctx):
        """
        Return extended attributes.
        Since we're a translation layer, we don't support xattrs.
        """
        raise FUSEError(errno.ENODATA)


async def main_async(mount_path: str, root_path: str):
    """Async main function for pyfuse3."""
    from config import read_app_config
    from cache_warmer import CacheWarmer
    from dirlisting import set_cache_config

    fs = TransFS(root_path=root_path, mount_path=mount_path)

    # Initialize cache configuration from app.yaml
    app_config = read_app_config()
    cache_config = app_config.get('cache', {})
    set_cache_config(cache_config)

    fuse_options = set(pyfuse3.default_options)
    fuse_options.add('fsname=transfs')
    fuse_options.add('allow_other')
    fuse_options.discard('default_permissions')

    logger.info(f"Mounting TransFS at {mount_path} with root {root_path}")
    pyfuse3.init(fs, mount_path, fuse_options)

    # Start cache warmer (only if caching is enabled)
    warmer_config = app_config.get("cache_warmer", {})
    if not cache_config.get('dir_cache_enabled', True):
        warmer_config = {'enabled': False}

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


def main(mount_path: str, root_path: str):
    """Entry point - runs async main with Trio."""
    trio.run(main_async, mount_path, root_path)


if __name__ == '__main__':
    main(mount_path="/mnt/transfs", root_path="/mnt/filestorefs")
