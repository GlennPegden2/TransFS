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
from typing import Optional
import trio

import pyfuse3
from pyfuse3 import FUSEError, InodeT, FileHandleT

from passthroughfs_pyfuse3 import Passthrough
from dirlisting import parse_trans_path, get_cached_getattr, cache_getattr
from pathutils import full_path, is_virtual_path, map_virtual_to_real
from sourcepath import get_source_path, get_source_path_for_write
from zippath import open_file as zippath_open_file
from logging_setup import setup_logging

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

    def __init__(self, root_path: str):
        super().__init__(root_path)
        logger.debug("Starting TransFS (pyfuse3)")
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

    async def readdir(self, fh: FileHandleT, start_id: int, token):
        """
        Read directory entries using token-based callback (pyfuse3 style).
        This replaces the generator-based readdir from fusepy.
        """
        t_start = time.time()
        path = self._inode_to_path(fh)  # Use fh as inode (from opendir)
        logger.debug("DEBUG: readdir(inode=%s) path=%s", fh, path)
        
        xfull_path = path  # Already full path from inode map
        t_parse_start = time.time()
        
        # Get virtual entries
        virtual_entries = set(parse_trans_path(self.config, self.root, xfull_path))
        t_parse_elapsed = time.time() - t_parse_start
        logger.debug(f"DEBUG readdir: xfull_path={xfull_path}, virtual_entries count={len(virtual_entries)} parse_time=%.4fs", t_parse_elapsed)
        
        # Build entry list with (inode, name, attr) tuples
        entries = []
        entry_id = 1  # Start IDs from 1
        
        # For ZIP-internal paths, trust zippath results
        is_zip_internal = "//" not in xfull_path and ".zip/" in xfull_path
        
        if is_zip_internal:
            # Fast path: trust zippath results
            for entry_name in virtual_entries:
                entry_full_path = os.path.join(xfull_path, entry_name)
                try:
                    # Get inode for this entry (will stat it)
                    attr = await self.lookup(fh, entry_name.encode('utf-8'))
                    entries.append((attr.st_ino, entry_name, attr, entry_id))
                    entry_id += 1
                except (FUSEError, OSError):
                    continue
        else:
            # Slow path: validate each entry
            for entry_name in virtual_entries:
                entry_full_path = os.path.join(xfull_path, entry_name)
                entry_source_path = get_source_path(logger, self.config, self.root, entry_full_path)
                
                # Check if backing file exists
                if entry_source_path:
                    if isinstance(entry_source_path, tuple):
                        zip_path, _ = entry_source_path
                        if os.path.exists(zip_path):
                            try:
                                attr = await self.lookup(fh, entry_name.encode('utf-8'))
                                entries.append((attr.st_ino, entry_name, attr, entry_id))
                                entry_id += 1
                            except (FUSEError, OSError):
                                continue
                    else:
                        if os.path.exists(entry_source_path):
                            try:
                                attr = await self.lookup(fh, entry_name.encode('utf-8'))
                                entries.append((attr.st_ino, entry_name, attr, entry_id))
                                entry_id += 1
                            except (FUSEError, OSError):
                                continue
                # Virtual directories (like ...SoftwareArchives...)
                elif entry_name.startswith('...') and entry_name.endswith('...'):
                    try:
                        attr = await self.lookup(fh, entry_name.encode('utf-8'))
                        entries.append((attr.st_ino, entry_name, attr, entry_id))
                        entry_id += 1
                    except (FUSEError, OSError):
                        continue
        
        # Add real directory entries if directory exists
        if os.path.isdir(xfull_path):
            real_entries = os.listdir(xfull_path)
            logger.debug(f"DEBUG readdir: real directory exists, real_entries={real_entries}")
            existing_names = {name for _, name, _, _ in entries}
            for entry_name in real_entries:
                if entry_name not in existing_names:
                    try:
                        attr = await self.lookup(fh, entry_name.encode('utf-8'))
                        entries.append((attr.st_ino, entry_name, attr, entry_id))
                        entry_id += 1
                    except (FUSEError, OSError):
                        continue
        
        t_total = time.time() - t_start
        logger.info(f"READDIR PROFILE: {path} entries={len(entries)} parse_time=%.4fs total_time=%.4fs", t_parse_elapsed, t_total)
        logger.debug(f"DEBUG readdir: final entries count={len(entries)}")
        
        # Send entries via token callback
        for ino, name, attr, eid in entries:
            if eid <= start_id:
                continue
            if not pyfuse3.readdir_reply(token, name.encode('utf-8'), attr, eid):
                break  # Client buffer full

    async def getattr(self, inode: InodeT, ctx=None):
        """
        Get file attributes by inode (pyfuse3 async version).
        This converts the path-based fusepy version to inode-based.
        """
        t_start = time.time()
        path = self._inode_to_path(inode)
        logger.debug("DEBUG: getattr(inode=%s) path=%s", inode, path)
        
        xfull_path = path  # Already full path from inode map
        
        # Try cache first
        t_cache_start = time.time()
        parent_dir_virtual = str(Path(xfull_path).parent)
        parent_dir = parent_dir_virtual.replace("/mnt/transfs", "/mnt/filestorefs")
        
        cached_stat = get_cached_getattr(xfull_path, parent_dir)
        t_cache_elapsed = time.time() - t_cache_start
        
        if cached_stat is not None:
            t_total = time.time() - t_start
            TransFS._getattr_cache_hits += 1
            TransFS._getattr_count += 1
            TransFS._getattr_total_time += t_total
            logger.debug("GETATTR CACHE HIT: inode=%s (cache_lookup=%.4fs, total=%.4fs)", inode, t_cache_elapsed, t_total)
            self._maybe_print_stats()
            
            # Convert dict to EntryAttributes
            return self._dict_to_entry_attributes(cached_stat, inode)
        
        TransFS._getattr_cache_misses += 1
        logger.debug("GETATTR CACHE MISS: inode=%s (cache_lookup=%.4fs)", inode, t_cache_elapsed)
        
        t_source_start = time.time()
        fspath = get_source_path(logger, self.config, self.root, xfull_path)
        t_source_elapsed = time.time() - t_source_start
        logger.debug("GETATTR get_source_path took %.4fs for inode=%s", t_source_elapsed, inode)
        logger.debug("DEBUG: getattr full_path=%s, fspath=%s", xfull_path, fspath)

        # Determine zip_mode
        zip_mode = self._get_zip_mode_for_path(xfull_path)
        logger.debug("DEBUG: getattr zip_mode=%s for path=%s", zip_mode, path)

        # Handle file inside a zip
        if isinstance(fspath, tuple):
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
            
            cache_getattr(xfull_path, parent_dir, result)
            return self._dict_to_entry_attributes(result, inode)

        # Handle virtual directories
        if fspath is None:
            parent_path = str(Path(xfull_path).parent)
            entries = set(parse_trans_path(self.config, self.root, parent_path))
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
                retry_fspath = get_source_path(logger, self.config, self.root, xfull_path)
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
        return await super().getattr(inode, ctx)
    
    def _dict_to_entry_attributes(self, stat_dict: dict, inode: InodeT) -> pyfuse3.EntryAttributes:
        """Convert fusepy-style stat dict to pyfuse3 EntryAttributes."""
        entry = pyfuse3.EntryAttributes()
        entry.st_ino = inode
        entry.st_mode = stat_dict['st_mode']
        entry.st_nlink = stat_dict['st_nlink']
        entry.st_uid = stat_dict['st_uid']
        entry.st_gid = stat_dict['st_gid']
        entry.st_size = stat_dict['st_size']
        entry.st_atime_ns = stat_dict['st_atime'] * 10**9
        entry.st_mtime_ns = stat_dict['st_mtime'] * 10**9
        entry.st_ctime_ns = stat_dict['st_ctime'] * 10**9
        entry.st_rdev = 0
        entry.generation = 0
        entry.entry_timeout = 0
        entry.attr_timeout = 0
        entry.st_blksize = 512
        entry.st_blocks = (entry.st_size + entry.st_blksize - 1) // entry.st_blksize
        return entry

    async def open(self, inode: InodeT, flags: int, ctx):
        """Open a file (pyfuse3 async version)."""
        path = self._inode_to_path(inode)
        logger.debug("DEBUG: open(inode=%s, flags=%s) path=%s", inode, flags, path)
        
        xfull_path = path
        trans_path = get_source_path(logger, self.config, self.root, xfull_path)
        logger.debug("DEBUG: open trans_path=%s", trans_path)

        if trans_path is None:
            if flags & os.O_CREAT:
                trans_path = get_source_path_for_write(logger, self.config, self.root, xfull_path)
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
                        return pyfuse3.FileInfo(fh=fd)
                    except Exception as e:
                        logger.error("open: failed to create file %s: %s", trans_path, e)
                        raise FUSEError(errno.EACCES)
                else:
                    logger.error("open: real file %s does not exist", trans_path)
                    raise FUSEError(errno.ENOENT)
            
            logger.debug("open using trans_path=%s", trans_path)
            # Use parent class open logic
            return await super().open(inode, flags, ctx)

        logger.debug("DEBUG: open: unknown mapping")
        raise FUSEError(errno.ENOENT)

    async def lookup(self, parent_inode: InodeT, name: bytes, ctx=None):
        """
        Look up a directory entry (pyfuse3 async version).
        Handles virtual path translation.
        """
        name_str = name.decode('utf-8') if isinstance(name, bytes) else name
        logger.debug(f"lookup for {name_str} in inode {parent_inode}")
        
        parent_path = self._inode_to_path(parent_inode)
        path = os.path.join(parent_path, name_str)
        
        # Check if this is a virtual path
        if is_virtual_path(self.config, self.root, path):
            # Get attributes via getattr which handles virtual paths
            # First, we need to assign an inode
            # Use hash of path for synthetic inode
            synthetic_inode = abs(hash(path)) & 0x7FFFFFFF
            if synthetic_inode == 0:
                synthetic_inode = 1
            if synthetic_inode == pyfuse3.ROOT_INODE:
                synthetic_inode += 1
            
            # Add to inode map
            self._add_path(synthetic_inode, path)
            
            # Get attributes
            return await self.getattr(synthetic_inode, ctx)
        
        # Use parent class lookup for real files
        return await super().lookup(parent_inode, name, ctx)

    async def create(self, parent_inode: InodeT, name: bytes, mode, flags, ctx):
        """Create and open a file."""
        name_str = name.decode('utf-8') if isinstance(name, bytes) else name
        logger.debug("CREATE: called with name=%s, mode=%s", name_str, oct(mode))
        
        parent_path = self._inode_to_path(parent_inode)
        trans_path = os.path.join(parent_path, name_str)
        real_path = get_source_path_for_write(logger, self.config, self.root, trans_path)
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
    fs = TransFS(root_path=root_path)
    
    fuse_options = set(pyfuse3.default_options)
    fuse_options.add('fsname=transfs')
    fuse_options.add('allow_other')
    fuse_options.discard('default_permissions')
    
    logger.info(f"Mounting TransFS at {mount_path} with root {root_path}")
    pyfuse3.init(fs, mount_path, fuse_options)
    
    try:
        logger.info("Starting pyfuse3 main loop")
        await pyfuse3.main()
    finally:
        logger.info("Unmounting TransFS")
        pyfuse3.close(unmount=True)


def main(mount_path: str, root_path: str):
    """Entry point - runs async main with Trio."""
    trio.run(main_async, mount_path, root_path)


if __name__ == '__main__':
    main(mount_path="/mnt/transfs", root_path="/mnt/filestorefs")
