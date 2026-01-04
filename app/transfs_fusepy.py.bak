#!/usr/bin/env python

import errno
import logging
import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Literal, Optional, cast
from dirlisting import parse_trans_path
from pathutils import (
    full_path,
    is_virtual_path,
    map_virtual_to_real,
)
from sourcepath import get_source_path, get_source_path_for_write
from zippath import open_file as zippath_open_file  # new

from fuse import FUSE, FuseOSError
from passthroughfs import Passthrough  
from logging_setup import setup_logging

setup_logging(logging.INFO)
logger = logging.getLogger("transfs")
logger.info("TransFS logging initialized")



class TransFS(Passthrough):
    """FUSE filesystem for translating virtual paths to real files, including zip logic and filetype mapping."""
    
    # Profiling stats
    _getattr_count = 0
    _getattr_total_time = 0.0
    _getattr_cache_hits = 0
    _getattr_cache_misses = 0
    _last_stats_print = time.time()

    def __init__(self, root_path: str):
        super().__init__(root_path)
        logger.debug("Starting TransFS")
        self.root = root_path
        from config import read_config
        self.config = read_config()
    
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
            return "hierarchical"  # default
        
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

    def readdir(self, path: str, fh: int):
        t_start = time.time()
        logger.debug("DEBUG: readdir(%s)", path)
        xfull_path = full_path(self.root,path)
        t_parse_start = time.time()
        dirents = ['.', '..']
        virtual_entries = set(parse_trans_path(self.config,self.root, xfull_path))
        t_parse_elapsed = time.time() - t_parse_start
        logger.debug(f"DEBUG readdir: xfull_path={xfull_path}, virtual_entries count={len(virtual_entries)} parse_time=%.4fs", t_parse_elapsed)
        
        # For ZIP-internal paths (hierarchical mode), entries from zippath are already validated
        # Skip expensive existence checks for large directories
        is_zip_internal = "//" not in xfull_path and ".zip/" in xfull_path
        
        if is_zip_internal:
            # Fast path: trust zippath results, no validation needed
            dirents.extend(virtual_entries)
        else:
            # Slow path: validate each entry exists (needed for non-ZIP virtual paths)
            for entry in virtual_entries:
                entry_full_path = os.path.join(xfull_path, entry)
                entry_source_path = get_source_path(logger, self.config, self.root, entry_full_path)
                
                # Check if the backing file/directory exists
                if entry_source_path:
                    if isinstance(entry_source_path, tuple):
                        # It's a zip file mapping - check if zip exists
                        zip_path, _ = entry_source_path
                        if os.path.exists(zip_path):
                            dirents.append(entry)
                    else:
                        if os.path.exists(entry_source_path):
                            dirents.append(entry)
                # If no source path, it's a virtual directory (like ...SoftwareArchives...)
                elif entry.startswith('...') and entry.endswith('...'):
                    dirents.append(entry)
        
        if os.path.isdir(xfull_path):
            real_entries = os.listdir(xfull_path)
            logger.debug(f"DEBUG readdir: real directory exists, real_entries={real_entries}")
            for entry in real_entries:
                if entry not in dirents:  # Avoid duplicates
                    dirents.append(entry)
        
        t_total = time.time() - t_start
        logger.info(f"READDIR PROFILE: {path} entries={len(dirents)} parse_time=%.4fs total_time=%.4fs", t_parse_elapsed, t_total)
        logger.debug(f"DEBUG readdir: final dirents count={len(dirents)}")
        for entry in dirents:
            yield entry


    def getattr(
        self,
        path: str,
        fh: Optional[int] = None
    ) -> dict[
        Literal[
            'st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime',
            'st_nlink', 'st_size', 'st_uid'
        ],
        int
    ]:
        """FUSE getattr implementation."""
        t_start = time.time()
        logger.debug("DEBUG: getattr(%s)", path)
        xfull_path = full_path(self.root, path)
        
        # Try cache first - use real filesystem path for parent dir mtime checking
        t_cache_start = time.time()
        parent_dir_virtual = str(Path(xfull_path).parent)
        # Convert /mnt/transfs -> /mnt/filestorefs for cache key matching
        parent_dir = parent_dir_virtual.replace("/mnt/transfs", "/mnt/filestorefs")
        from dirlisting import get_cached_getattr, cache_getattr
        cached_stat = get_cached_getattr(xfull_path, parent_dir)
        t_cache_elapsed = time.time() - t_cache_start
        
        if cached_stat is not None:
            t_total = time.time() - t_start
            TransFS._getattr_cache_hits += 1
            TransFS._getattr_count += 1
            TransFS._getattr_total_time += t_total
            logger.debug("GETATTR CACHE HIT: %s (cache_lookup=%.4fs, total=%.4fs)", path, t_cache_elapsed, t_total)
            self._maybe_print_stats()
            return cached_stat
        
        TransFS._getattr_cache_misses += 1
        logger.debug("GETATTR CACHE MISS: %s (cache_lookup=%.4fs)", path, t_cache_elapsed)
        t_source_start = time.time()
        fspath = get_source_path(logger, self.config, self.root, xfull_path)
        t_source_elapsed = time.time() - t_source_start
        logger.debug("GETATTR get_source_path took %.4fs for %s", t_source_elapsed, path)
        logger.debug("DEBUG: getattr full_path=%s, fspath=%s", xfull_path, fspath)

        # Determine zip_mode for this path (if applicable)
        zip_mode = self._get_zip_mode_for_path(xfull_path)
        logger.debug("DEBUG: getattr zip_mode=%s for path=%s", zip_mode, path)

        # PATCH: If mapped to a file inside a zip (unzip: true), always stat as a file
        if isinstance(fspath, tuple):
            logger.debug("DEBUG: Inside isinstance(fspath, tuple) branch: %s", fspath)
            zip_path, internal_file = fspath
            import zippath
            
            # Use zippath.getinfo() which uses cached index - much faster than opening ZipFile
            full_internal_path = os.path.join(zip_path, internal_file)
            now = int(os.path.getmtime(zip_path))
            
            info = zippath.getinfo(full_internal_path)
            if info is None:
                raise FileNotFoundError(f"Path not found in ZIP: {internal_file}")
            
            if info['is_dir']:
                # It's a directory (explicit or inferred)
                result = {
                    'st_atime': now,
                    'st_ctime': now,
                    'st_mtime': now,
                    'st_gid': 0,
                    'st_uid': 0,
                    'st_mode': 0o040555,  # directory, read-only
                    'st_nlink': 2,
                    'st_size': 0,
                }
            else:
                # It's a file - size from cached index
                result = {
                    'st_atime': now,
                    'st_ctime': now,
                    'st_mtime': now,
                    'st_gid': 0,
                    'st_uid': 0,
                    'st_mode': 0o100444,  # regular file, read-only
                    'st_nlink': 1,
                    'st_size': info['size'],
                }
            
            cache_getattr(xfull_path, parent_dir, result)
            return result

        if fspath is None:
            parent_path = str(Path(xfull_path).parent)
            entries = set(parse_trans_path(self.config,self.root, parent_path))
            name = os.path.basename(xfull_path)
            logger.debug("DEBUG getattr fallback: parent_path=%s, entries=%s, name=%s", parent_path, entries, name)

            if name in entries:
                # Retry get_source_path to find the real backing file
                retry_fspath = get_source_path(logger, self.config, self.root, xfull_path)
                logger.debug("DEBUG getattr retry_fspath: %s", retry_fspath)
                
                # If we found a real file, stat it for accurate size
                if retry_fspath and isinstance(retry_fspath, str) and os.path.exists(retry_fspath):
                    st = os.lstat(retry_fspath)
                    result = {
                        'st_atime': int(st.st_atime),
                        'st_ctime': int(st.st_ctime),
                        'st_mtime': int(st.st_mtime),
                        'st_gid': st.st_gid,
                        'st_uid': st.st_uid,
                        'st_mode': 0o100444,  # regular file, read-only
                        'st_nlink': 1,
                        'st_size': st.st_size,
                    }
                    cache_getattr(xfull_path, parent_dir, result)
                    return result
                elif retry_fspath and isinstance(retry_fspath, tuple):
                    # Handle zip internal file
                    zip_path, internal_file = retry_fspath
                    if os.path.exists(zip_path):
                        with zipfile.ZipFile(zip_path, 'r') as zf:
                            info = zf.getinfo(internal_file)
                            now = int(os.path.getmtime(zip_path))
                            result = {
                                'st_atime': now,
                                'st_ctime': now,
                                'st_mtime': now,
                                'st_gid': 0,
                                'st_uid': 0,
                                'st_mode': 0o100444,
                                'st_nlink': 1,
                                'st_size': info.file_size,
                            }
                            cache_getattr(xfull_path, parent_dir, result)
                            return result
                
                # Check if it's a virtual directory (like ...SoftwareArchives...)
                if name.startswith('...') and name.endswith('...'):
                    now = int(time.time())
                    result = {
                        'st_atime': now,
                        'st_ctime': now,
                        'st_mtime': now,
                        'st_gid': 0,
                        'st_uid': 0,
                        'st_mode': 0o040755,  # directory
                        'st_nlink': 2,
                        'st_size': 4096,
                    }
                    cache_getattr(xfull_path, parent_dir, result)
                    return result
                
                # If no backing file exists, raise ENOENT (file not found)
                logger.debug("DEBUG getattr: entry %s in map but no backing file exists", name)
            # Otherwise, fall through to ENOENT
            raise FuseOSError(errno.ENOENT)

        logger.debug("DEBUG: getattr(%s) full_path=%s fspath=%s type=%s", path, full_path, fspath, type(fspath))

        # PATCH: treat zip files based on zip_mode
        if isinstance(fspath, str) and fspath.lower().endswith('.zip'):
            st = os.lstat(fspath)
            # Hierarchical mode: ZIPs are directories
            if zip_mode == "hierarchical":
                out = {
                    'st_atime': int(st.st_atime),
                    'st_ctime': int(st.st_ctime),
                    'st_mtime': int(st.st_mtime),
                    'st_gid': st.st_gid,
                    'st_uid': st.st_uid,
                    'st_mode': 0o040755,  # directory
                    'st_nlink': 2,
                    'st_size': 4096,
                }
            else:  # file or flatten mode: ZIPs are files
                out = {
                    'st_atime': int(st.st_atime),
                    'st_ctime': int(st.st_ctime),
                    'st_mtime': int(st.st_mtime),
                    'st_gid': st.st_gid,
                    'st_uid': st.st_uid,
                    'st_mode': 0o100444,  # regular file
                    'st_nlink': 1,
                    'st_size': st.st_size,
                }
            cache_getattr(xfull_path, parent_dir, out)
            return cast(
                dict[
                    Literal[
                        'st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime',
                        'st_nlink', 'st_size', 'st_uid'
                    ],
                    int
                ],
                out
            )

        if not os.path.exists(fspath):
            # fspath doesn't exist, but maybe it's a virtual mapping to a different real file
            # Check if this is a virtual entry (i.e., listed in the parent directory)
            parent_path = str(Path(xfull_path).parent)
            t_start = time.time()
            entries = set(parse_trans_path(self.config, self.root, parent_path))
            t_elapsed = time.time() - t_start
            name = os.path.basename(xfull_path)
            if t_elapsed > 1.0:
                logger.warning(f"SLOW parse_trans_path({parent_path}) took {t_elapsed:.2f}s, returned {len(entries)} entries")
            logger.debug("DEBUG getattr fallback (real missing): parent_path=%s, entries=%s, name=%s", parent_path, entries, name)
            if name in entries:
                # Retry get_source_path to find the real backing file  
                retry_fspath = get_source_path(logger, self.config, self.root, xfull_path)
                logger.debug("DEBUG getattr retry_fspath (real missing): %s", retry_fspath)
                
                # If we found a different real file, stat it
                if retry_fspath and isinstance(retry_fspath, str) and retry_fspath != fspath and os.path.exists(retry_fspath):
                    st = os.lstat(retry_fspath)
                    result = {
                        'st_atime': int(st.st_atime),
                        'st_ctime': int(st.st_ctime),
                        'st_mtime': int(st.st_mtime),
                        'st_gid': st.st_gid,
                        'st_uid': st.st_uid,
                        'st_mode': 0o100444,  # regular file, read-only
                        'st_nlink': 1,
                        'st_size': st.st_size,
                    }
                    cache_getattr(xfull_path, parent_dir, result)
                    return result
                elif retry_fspath and isinstance(retry_fspath, tuple):
                    # Handle zip internal file
                    zip_path, internal_file = retry_fspath
                    if os.path.exists(zip_path):
                        with zipfile.ZipFile(zip_path, 'r') as zf:
                            info = zf.getinfo(internal_file)
                            now = int(os.path.getmtime(zip_path))
                            result = {
                                'st_atime': now,
                                'st_ctime': now,
                                'st_mtime': now,
                                'st_gid': 0,
                                'st_uid': 0,
                                'st_mode': 0o100444,
                                'st_nlink': 1,
                                'st_size': info.file_size,
                            }
                            cache_getattr(xfull_path, parent_dir, result)
                            return result
                
                # Check if it's a virtual directory (like ...SoftwareArchives...)
                if name.startswith('...') and name.endswith('...'):
                    now = int(time.time())
                    result = {
                        'st_atime': now,
                        'st_ctime': now,
                        'st_mtime': now,
                        'st_gid': 0,
                        'st_uid': 0,
                        'st_mode': 0o040755,  # directory
                        'st_nlink': 2,
                        'st_size': 4096,
                    }
                    cache_getattr(xfull_path, parent_dir, result)
                    return result
                
                # If no backing file exists, raise ENOENT
                logger.debug("DEBUG getattr (real missing): entry %s in map but no backing file exists", name)
            raise FuseOSError(errno.ENOENT)

        st = os.lstat(fspath)
        if os.path.isdir(fspath):
            mode = 0o040755
        elif os.path.isfile(fspath):
            mode = 0o100644
        else:
            raise FuseOSError(errno.ENOENT)

        keys = (
            'st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime',
            'st_nlink', 'st_size', 'st_uid'
        )
        out = {key: int(getattr(st, key)) for key in keys}
        out['st_mode'] = mode
        cache_getattr(xfull_path, parent_dir, out)
        
        t_total = time.time() - t_start
        TransFS._getattr_count += 1
        TransFS._getattr_total_time += t_total
        if t_total > 0.01:  # Log slow operations
            logger.info("GETATTR PROFILE: %s took %.4fs (source_path=%.4fs)", path, t_total, t_source_elapsed)
        
        self._maybe_print_stats()
        return cast(
            dict[
                Literal[
                    'st_atime', 'st_ctime', 'st_gid', 'st_mode', 'st_mtime',
                    'st_nlink', 'st_size', 'st_uid'
                ],
                int
            ],
            out
        )

    def open(self, path: str, flags: int) -> int:
        """FUSE open implementation."""
        logger.debug("DEBUG: open(%s, flags=%s)", path, flags)
        xfull_path = full_path(self.root,path)
        trans_path = get_source_path(logger, self.config, self.root, xfull_path)
        logger.debug("DEBUG: open trans_path=%s", trans_path)

        if trans_path is None:
            # Check if this is a write operation
            if flags & os.O_CREAT:
                from sourcepath import get_source_path_for_write
                trans_path = get_source_path_for_write(logger, self.config, self.root, xfull_path)
                logger.debug("DEBUG: open write trans_path=%s", trans_path)
                if trans_path is None:
                    logger.debug("DEBUG: open: no mapping for write %s", path)
                    raise FuseOSError(errno.ENOENT)
                # Create file path determined, handle below
            else:
                logger.debug("DEBUG: open: no mapping for %s", path)
                raise FuseOSError(errno.ENOENT)

        if isinstance(trans_path, tuple):
            zip_path, internal_file = trans_path
            logger.debug("DEBUG: open extracting %s from %s", internal_file, zip_path)
            # Use zippath layer to open internal file
            try:
                with zippath_open_file(f"{zip_path}/{internal_file}", "rb") as f:
                    temp = tempfile.NamedTemporaryFile(mode='wb', delete=False)
                    content = f.read()
                    if isinstance(content, str):
                        content = content.encode('utf-8')
                    temp.write(content)
                    temp.close()
                    logger.debug("DEBUG: open temp file created at %s", temp.name)
                    return os.open(temp.name, flags)
            except FileNotFoundError:
                logger.error("open: %s not in zip %s", internal_file, zip_path)
                raise FuseOSError(errno.ENOENT)
            except Exception as e:
                logger.error("open: error extracting %s from %s: %s", internal_file, zip_path, e)
                raise FuseOSError(errno.ENOENT)

        if isinstance(trans_path, str):
            if not os.path.exists(trans_path):
                # Check if O_CREAT flag is set
                if flags & os.O_CREAT:
                    logger.debug("open: creating new file at %s", trans_path)
                    # Ensure parent directory exists
                    parent_dir = os.path.dirname(trans_path)
                    try:
                        os.makedirs(parent_dir, exist_ok=True)
                        logger.debug("open: ensured directory exists: %s", parent_dir)
                    except Exception as e:
                        logger.error("open: failed to create directory %s: %s", parent_dir, e)
                        raise FuseOSError(errno.EACCES)
                    # Create and open the file
                    try:
                        return os.open(trans_path, flags, 0o644)
                    except Exception as e:
                        logger.error("open: failed to create file %s: %s", trans_path, e)
                        raise FuseOSError(errno.EACCES)
                else:
                    logger.error("open: real file %s does not exist", trans_path)
                    raise FuseOSError(errno.ENOENT)
            logger.debug("open using trans_path=%s", trans_path)
            return os.open(trans_path, flags)

        logger.debug("DEBUG: open: unknown mapping for %s", path)
        raise FuseOSError(errno.ENOENT)



    def create(self, path, mode, fi=None):
        logger.debug("CREATE: called with path=%s, mode=%s", path, oct(mode))
        trans_path = full_path(self.root, path)
        real_path = get_source_path_for_write(logger, self.config, self.root, trans_path)
        logger.debug("CREATE: path=%s, real_path=%s", path, real_path)
        if real_path is None:
            logger.debug("CREATE: EROFS (no mapping)")
            raise FuseOSError(errno.EROFS)
        real_dir = os.path.dirname(real_path)
        logger.debug("CREATE: real_dir=%s", real_dir)
        try:
            os.makedirs(real_dir, exist_ok=True)
            logger.debug("CREATE: ensured directory exists: %s", real_dir)
        except Exception as e:
            logger.debug("CREATE: failed to create directory %s: %s", real_dir, e)
            raise
        if os.path.isdir(real_path):
            logger.debug("CREATE: EISDIR (is a directory)")
            raise FuseOSError(errno.EISDIR)
        try:
            fd = os.open(real_path, os.O_WRONLY | os.O_CREAT, mode)
            logger.debug("CREATE: success fd=%s", fd)
            return fd
        except Exception as e:
            logger.debug("CREATE: Exception %s", e)
            raise

    def mkdir(self, path, mode):
        real_path = map_virtual_to_real(self.config,path)
        if real_path is None:
            raise FuseOSError(errno.EROFS)
        os.makedirs(real_path, mode=mode, exist_ok=True)
        return None

    def access(self, path, amode):
        """
        FUSE access implementation.
        Always allow access to virtual directories and files that exist in the virtual namespace.
        """
        xfull_path = full_path(self.root,path)
        fspath = get_source_path(logger, self.config, self.root, xfull_path)

        # If it's a virtual directory, allow access
        if fspath is None and is_virtual_path(self.config, self.root,xfull_path):
            return 0

        # If it's a real file or directory, check access using os.access
        if fspath and os.path.exists(fspath):
            if os.access(fspath, amode):
                return 0
            else:
                raise FuseOSError(errno.EACCES)

        # If not found, deny access
        raise FuseOSError(errno.ENOENT)

    def truncate(self, path, length, fh=None):
        logger.debug("TRUNCATE: called with path=%s, length=%s, fh=%s", path, length, fh)
        real_path = map_virtual_to_real(self.config, path)
        logger.debug("TRUNCATE: real_path=%s", real_path)
        if real_path is None or not os.path.exists(real_path):
            logger.debug("TRUNCATE: ENOENT")
            raise FuseOSError(errno.ENOENT)
        with open(real_path, 'r+b') as f:
            f.truncate(length)

    def unlink(self, path):
        logger.debug("UNLINK: called with path=%s", path)
        real_path = map_virtual_to_real(self.config, path)
        logger.debug("UNLINK: real_path=%s", real_path)
        if real_path is None or not os.path.exists(real_path):
            logger.debug("UNLINK: ENOENT")
            raise FuseOSError(errno.ENOENT)
        os.unlink(real_path)

    def getxattr(self, path: str, name: str, position: int = 0):
        """
        Return extended attributes. Since we're a translation layer,
        we don't support xattrs and return ENODATA instead of ENOTSUP
        to avoid traceback spam in logs.
        """
        # Silently indicate no extended attributes are available
        raise FuseOSError(errno.ENODATA)


def main(mount_path: str, root_path: str):
    FUSE(
        TransFS(root_path=root_path),
        mount_path,
        nothreads=True,
        foreground=True,
        debug=False,  # Set to True for FUSE protocol-level debugging
        encoding='utf-8',
        allow_other=True,
        direct_io=True  # Disable kernel caching to prevent Samba data corruption
    )


if __name__ == '__main__':
    main(mount_path="/mnt/transfs", root_path="/mnt/filestorefs")
