"""
Startup hot-path pre-warming for TransFS.

Pre-loads critical paths into cache during initialization to avoid
cold-start delays when emulators first access the filesystem.
"""

import logging
import time
from typing import List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


def prewarm_hotpaths(
    config: dict,
    root_path: str,
    mount_path: str,
    data_adapter,
    readdir_cache_dict: dict,
    config_readdir_cache_dict: dict,
    db_readdir_cache_ttl: float = 30.0,
    config_readdir_cache_ttl: float = 15.0
) -> None:
    """
    Pre-warm critical paths at startup to reduce cold-start latency.
    
    This function is called during filesystem initialization BEFORE the FUSE mount
    completes. It pre-populates caches with data for frequently-accessed paths
    to ensure fast first access.
    
    Args:
        config: Application configuration dict
        root_path: Filesystem root path (e.g., /mnt/filestorefs)
        mount_path: Virtual mount path (e.g., /mnt/transfs)
        data_adapter: Database adapter for querying
        readdir_cache_dict: Reference to TransFS._db_readdir_cache
        config_readdir_cache_dict: Reference to TransFS._config_readdir_cache
        db_readdir_cache_ttl: Cache TTL for database queries
        config_readdir_cache_ttl: Cache TTL for config parse results
    """
    prewarm_config = config.get("startup_prewarm", {})
    if not prewarm_config.get("enabled", True):
        logger.info("Startup prewarm: disabled in configuration")
        return
    
    hot_paths = prewarm_config.get("hot_paths", [])
    if not hot_paths:
        logger.info("Startup prewarm: no hot paths configured")
        return
    
    t_start = time.time()
    loaded_count = 0
    
    logger.info(f"Startup prewarm: loading {len(hot_paths)} hot paths...")
    
    for virtual_path in hot_paths:
        try:
            # Construct full virtual path
            if not virtual_path.startswith(mount_path):
                full_path = str(Path(mount_path) / virtual_path.lstrip('/'))
            else:
                full_path = virtual_path
            
            logger.info(f"Startup prewarm: loading {full_path}")
            
            # Pre-warm config parse cache (parse_trans_path results)
            from dirlisting import parse_trans_path
            t_parse_start = time.time()
            config_entries = list(parse_trans_path(config, root_path, full_path))
            t_parse = time.time() - t_parse_start
            config_readdir_cache_dict[full_path] = (time.time(), config_entries)
            logger.info(f"  Config cache: {len(config_entries)} entries in {t_parse:.3f}s")
            
            # Pre-warm database readdir cache if adapter is available
            if data_adapter and data_adapter.is_database_mode():
                try:
                    t_db_start = time.time()
                    db_entries = data_adapter.readdir_entries(full_path)
                    t_db = time.time() - t_db_start
                    if db_entries:
                        readdir_cache_dict[full_path] = (time.time(), db_entries)
                        logger.info(f"  DB cache: {len(db_entries)} entries in {t_db:.3f}s")
                    else:
                        logger.info(f"  DB cache: no entries found")
                except Exception as e:
                    logger.warning(f"  DB cache: error: {e}")
            
            loaded_count += 1
            
        except Exception as e:
            logger.warning(f"Startup prewarm: failed to load {virtual_path}: {e}")
    
    t_total = time.time() - t_start
    logger.info(f"Startup prewarm: complete - loaded {loaded_count}/{len(hot_paths)} paths in {t_total:.2f}s")


def prewarm_subdirectory_cache(config: dict, mount_path: str = "/mnt/transfs") -> None:
    """
    Pre-warm subdirectory discovery cache with common queries.
    
    This reduces the 1.5s+ database query latency for subdirectory listings
    by executing and caching queries during startup.
    
    Args:
        config: Application configuration dict
        mount_path: Virtual filesystem mount point
    """
    prewarm_config = config.get("startup_prewarm", {})
    if not prewarm_config.get("prewarm_subdirs", True):
        logger.info("Subdirectory cache prewarm: disabled")
        return
    
    # Get list of client roots to pre-warm
    subdir_paths = prewarm_config.get("subdirectory_paths", [])
    if not subdir_paths:
        # Default: pre-warm all client roots
        clients = config.get('clients', [])
        subdir_paths = [f"{client['name']}" for client in clients]
    
    if not subdir_paths:
        logger.info("Subdirectory cache prewarm: no paths configured")
        return
    
    t_start = time.time()
    logger.info(f"Subdirectory cache prewarm: warming {len(subdir_paths)} paths...")
    
    from dirlisting import _get_subdirectories_from_db
    
    for virtual_rel_path in subdir_paths:
        try:
            t_query_start = time.time()
            subdirs = _get_subdirectories_from_db(mount_path, virtual_rel_path)
            t_query = time.time() - t_query_start
            logger.info(f"  {virtual_rel_path}: {len(subdirs)} subdirs in {t_query:.3f}s")
        except Exception as e:
            logger.warning(f"  {virtual_rel_path}: error: {e}")
    
    t_total = time.time() - t_start
    logger.info(f"Subdirectory cache prewarm: complete in {t_total:.2f}s")


def prewarm_recursive_indexes(config: dict, filestore_root: str = None) -> None:
    """
    Pre-warm recursive filename index caches for large source directories.
    
    This eliminates 8+ second cold-start delays when first accessing files
    in flattened query maps with thousands of source files.
    
    Args:
        config: Application configuration dict
        filestore_root: Root path for file storage (defaults to config["filestore"])
    """
    if filestore_root is None:
        filestore_root = config.get("filestore", "/data/retronas")
    prewarm_config = config.get("startup_prewarm", {})
    if not prewarm_config.get("prewarm_recursive_indexes", True):
        logger.info("Recursive index prewarm: disabled")
        return
    
    # Get list of large source directories to pre-index
    index_paths = prewarm_config.get("recursive_index_paths", [])
    if not index_paths:
        logger.info("Recursive index prewarm: no paths configured")
        return
    
    t_start = time.time()
    logger.info(f"Recursive index prewarm: warming {len(index_paths)} directory indexes...")
    
    from sourcepath import _find_file_recursive_indexed
    
    for relative_path in index_paths:
        try:
            if not relative_path.startswith('/'):
                full_path = f"{filestore_root}/{relative_path}"
            else:
                full_path = relative_path
            
            t_index_start = time.time()
            # Trigger index build by looking for a dummy file
            _find_file_recursive_indexed(full_path, "__dummy_file_that_does_not_exist__.xyz")
            t_index = time.time() - t_index_start
            logger.info(f"  {relative_path}: indexed in {t_index:.2f}s")
        except Exception as e:
            logger.warning(f"  {relative_path}: error: {e}")
    
    t_total = time.time() - t_start
    logger.info(f"Recursive index prewarm: complete in {t_total:.2f}s")
