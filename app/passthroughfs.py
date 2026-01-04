#!/usr/bin/env python3
"""
Async passthrough filesystem using pyfuse3.

Based on pyfuse3's passthroughfs.py example with modifications for TransFS compatibility.
This serves as the base class for TransFS async operations.
"""

import errno
import logging
import os
import stat as stat_m
from collections import defaultdict
from os import fsdecode, fsencode
from typing import Dict, Set, Union

import pyfuse3
from pyfuse3 import FUSEError

log = logging.getLogger(__name__)

# Type aliases for clarity
InodeT = pyfuse3.InodeT
FileHandleT = pyfuse3.FileHandleT


class Passthrough(pyfuse3.Operations):
    """
    Async passthrough filesystem that mirrors a source directory.
    
    This class manages inode-to-path mappings and provides basic filesystem operations.
    TransFS will inherit from this and override methods for virtual path translation.
    """
    
    enable_writeback_cache = True
    
    def __init__(self, root_path: str):
        super().__init__()
        self.root = root_path
        
        # Inode management
        self._inode_path_map: Dict[InodeT, Union[str, Set[str]]] = {
            pyfuse3.ROOT_INODE: root_path
        }
        self._lookup_cnt: Dict[InodeT, int] = defaultdict(lambda: 0)
        
        # File descriptor management
        self._fd_inode_map: Dict[int, InodeT] = {}
        self._inode_fd_map: Dict[InodeT, int] = {}
        self._fd_open_count: Dict[int, int] = {}
        
        log.debug(f"Initialized Passthrough filesystem with root: {root_path}")
    
    # Inode Management Helpers
    # =========================
    
    def _inode_to_path(self, inode: InodeT) -> str:
        """Convert inode to filesystem path."""
        try:
            val = self._inode_path_map[inode]
        except KeyError:
            raise FUSEError(errno.ENOENT)
        
        if isinstance(val, set):
            # In case of hardlinks, pick any path
            val = next(iter(val))
        return val
    
    def _add_path(self, inode: InodeT, path: str) -> None:
        """Add a path to the inode map (handles hardlinks)."""
        log.debug(f"add path {path} for inode {inode}")
        
        if inode not in self._lookup_cnt:
            self._inode_path_map[inode] = path
            return
        
        val = self._inode_path_map[inode]
        if isinstance(val, set):
            val.add(path)
        elif val != path:
            self._inode_path_map[inode] = {val, path}
    
    def _forget_path(self, inode: InodeT, path: str) -> None:
        """Remove a path from the inode map."""
        log.debug(f"forget {path} for inode {inode}")
        val = self._inode_path_map[inode]
        
        if isinstance(val, set):
            val.remove(path)
            if len(val) == 1:
                self._inode_path_map[inode] = next(iter(val))
        else:
            del self._inode_path_map[inode]
    
    def _getattr(self, path: str = None, fd: int = None) -> pyfuse3.EntryAttributes:
        """
        Get file attributes from path or file descriptor.
        Returns pyfuse3.EntryAttributes object.
        """
        assert fd is None or path is None
        assert not (fd is None and path is None)
        
        try:
            if fd is None:
                assert path is not None
                stat = os.lstat(path)
            else:
                stat = os.fstat(fd)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        entry = pyfuse3.EntryAttributes()
        for attr in ('st_ino', 'st_mode', 'st_nlink', 'st_uid', 'st_gid',
                     'st_rdev', 'st_size', 'st_atime_ns', 'st_mtime_ns', 'st_ctime_ns'):
            setattr(entry, attr, getattr(stat, attr))
        
        entry.generation = 0
        entry.entry_timeout = 0
        entry.attr_timeout = 0
        entry.st_blksize = 512
        entry.st_blocks = ((entry.st_size + entry.st_blksize - 1) // entry.st_blksize)
        
        return entry
    
    # FUSE Operations
    # ===============
    
    async def forget(self, inode_list):
        """Handle inode reference count decrements."""
        for inode, nlookup in inode_list:
            if self._lookup_cnt[inode] > nlookup:
                self._lookup_cnt[inode] -= nlookup
                continue
            
            log.debug(f"forgetting about inode {inode}")
            assert inode not in self._inode_fd_map
            del self._lookup_cnt[inode]
            try:
                del self._inode_path_map[inode]
            except KeyError:
                pass  # May have been deleted
    
    async def lookup(self, parent_inode: InodeT, name: bytes, ctx=None):
        """Look up a directory entry and return its attributes."""
        name_str = fsdecode(name)
        log.debug(f"lookup for {name_str} in {parent_inode}")
        
        parent_path = self._inode_to_path(parent_inode)
        path = os.path.join(parent_path, name_str)
        attr = self._getattr(path=path)
        
        if name_str not in ('.', '..'):
            self._add_path(attr.st_ino, path)
        
        return attr
    
    async def getattr(self, inode: InodeT, ctx=None):
        """Get file attributes by inode."""
        if inode in self._inode_fd_map:
            return self._getattr(fd=self._inode_fd_map[inode])
        else:
            return self._getattr(path=self._inode_to_path(inode))
    
    async def readlink(self, inode: InodeT, ctx):
        """Read the target of a symbolic link."""
        path = self._inode_to_path(inode)
        try:
            target = os.readlink(path)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        return fsencode(target)
    
    async def opendir(self, inode: InodeT, ctx):
        """Open a directory for reading."""
        # For simplicity, we use the inode as file handle
        return inode
    
    async def readdir(self, fh: FileHandleT, start_id: int, token):
        """
        Read directory entries using token-based callback.
        
        This replaces the generator-based approach in fusepy.
        """
        path = self._inode_to_path(fh)
        log.debug(f"reading directory {path}")
        
        # Build list of entries
        entries = []
        for name in os.listdir(path):
            if name in ('.', '..'):
                continue
            try:
                attr = self._getattr(path=os.path.join(path, name))
                entries.append((attr.st_ino, name, attr))
            except OSError:
                # Skip entries we can't stat
                continue
        
        log.debug(f"read {len(entries)} entries, starting at {start_id}")
        
        # Send entries via token callback
        # This is not fully POSIX compliant for hardlinks, but works for most cases
        for ino, name, attr in sorted(entries):
            if ino <= start_id:
                continue
            if not pyfuse3.readdir_reply(token, fsencode(name), attr, ino):
                break  # Client buffer full
            self._add_path(attr.st_ino, os.path.join(path, name))
    
    async def unlink(self, parent_inode: InodeT, name: bytes, ctx):
        """Delete a file."""
        name_str = fsdecode(name)
        parent = self._inode_to_path(parent_inode)
        path = os.path.join(parent, name_str)
        
        try:
            inode = os.lstat(path).st_ino
            os.unlink(path)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        if inode in self._lookup_cnt:
            self._forget_path(inode, path)
    
    async def rmdir(self, parent_inode: InodeT, name: bytes, ctx):
        """Remove a directory."""
        name_str = fsdecode(name)
        parent = self._inode_to_path(parent_inode)
        path = os.path.join(parent, name_str)
        
        try:
            inode = os.lstat(path).st_ino
            os.rmdir(path)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        if inode in self._lookup_cnt:
            self._forget_path(inode, path)
    
    async def symlink(self, parent_inode: InodeT, name: bytes, target: bytes, ctx):
        """Create a symbolic link."""
        name_str = fsdecode(name)
        target_str = fsdecode(target)
        parent = self._inode_to_path(parent_inode)
        path = os.path.join(parent, name_str)
        
        try:
            os.symlink(target_str, path)
            os.lchown(path, ctx.uid, ctx.gid)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        stat = os.lstat(path)
        self._add_path(stat.st_ino, path)
        return await self.getattr(stat.st_ino)
    
    async def rename(self, parent_inode_old: InodeT, name_old: bytes,
                     parent_inode_new: InodeT, name_new: bytes, flags, ctx):
        """Rename/move a file or directory."""
        if flags != 0:
            raise FUSEError(errno.EINVAL)
        
        name_old_str = fsdecode(name_old)
        name_new_str = fsdecode(name_new)
        parent_old = self._inode_to_path(parent_inode_old)
        parent_new = self._inode_to_path(parent_inode_new)
        path_old = os.path.join(parent_old, name_old_str)
        path_new = os.path.join(parent_new, name_new_str)
        
        try:
            os.rename(path_old, path_new)
            inode = os.lstat(path_new).st_ino
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        if inode not in self._lookup_cnt:
            return
        
        val = self._inode_path_map[inode]
        if isinstance(val, set):
            assert len(val) > 1
            val.add(path_new)
            val.remove(path_old)
        else:
            assert val == path_old
            self._inode_path_map[inode] = path_new
    
    async def link(self, inode: InodeT, new_parent_inode: InodeT, new_name: bytes, ctx):
        """Create a hard link."""
        new_name_str = fsdecode(new_name)
        parent = self._inode_to_path(new_parent_inode)
        path = os.path.join(parent, new_name_str)
        
        try:
            os.link(self._inode_to_path(inode), path, follow_symlinks=False)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        self._add_path(inode, path)
        return await self.getattr(inode)
    
    async def setattr(self, inode: InodeT, attr, fields, fh, ctx):
        """Set file attributes."""
        try:
            if fields.update_size:
                if fh is None:
                    os.truncate(self._inode_to_path(inode), attr.st_size)
                else:
                    os.ftruncate(fh, attr.st_size)
            
            if fields.update_mode:
                # chmod always resolves symlinks
                assert not stat_m.S_ISLNK(attr.st_mode)
                if fh is None:
                    os.chmod(self._inode_to_path(inode), stat_m.S_IMODE(attr.st_mode))
                else:
                    os.fchmod(fh, stat_m.S_IMODE(attr.st_mode))
            
            if fields.update_uid and fields.update_gid:
                if fh is None:
                    os.chown(self._inode_to_path(inode), attr.st_uid, attr.st_gid,
                            follow_symlinks=False)
                else:
                    os.fchown(fh, attr.st_uid, attr.st_gid)
            elif fields.update_uid:
                if fh is None:
                    os.chown(self._inode_to_path(inode), attr.st_uid, -1,
                            follow_symlinks=False)
                else:
                    os.fchown(fh, attr.st_uid, -1)
            elif fields.update_gid:
                if fh is None:
                    os.chown(self._inode_to_path(inode), -1, attr.st_gid,
                            follow_symlinks=False)
                else:
                    os.fchown(fh, -1, attr.st_gid)
            
            if fields.update_atime and fields.update_mtime:
                if fh is None:
                    os.utime(self._inode_to_path(inode), None,
                            follow_symlinks=False,
                            ns=(attr.st_atime_ns, attr.st_mtime_ns))
                else:
                    os.utime(fh, None, ns=(attr.st_atime_ns, attr.st_mtime_ns))
            elif fields.update_atime or fields.update_mtime:
                # Need to retrieve the other value
                if fh is None:
                    path = self._inode_to_path(inode)
                    oldstat = os.stat(path, follow_symlinks=False)
                else:
                    oldstat = os.fstat(fh)
                
                if not fields.update_atime:
                    attr.st_atime_ns = oldstat.st_atime_ns
                else:
                    attr.st_mtime_ns = oldstat.st_mtime_ns
                
                if fh is None:
                    os.utime(path, None, follow_symlinks=False,
                            ns=(attr.st_atime_ns, attr.st_mtime_ns))
                else:
                    os.utime(fh, None, ns=(attr.st_atime_ns, attr.st_mtime_ns))
        
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        return await self.getattr(inode)
    
    async def mknod(self, parent_inode: InodeT, name: bytes, mode, rdev, ctx):
        """Create a special file (device node, FIFO, etc.)."""
        path = os.path.join(self._inode_to_path(parent_inode), fsdecode(name))
        try:
            os.mknod(path, mode=(mode & ~ctx.umask), device=rdev)
            os.chown(path, ctx.uid, ctx.gid)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        attr = self._getattr(path=path)
        self._add_path(attr.st_ino, path)
        return attr
    
    async def mkdir(self, parent_inode: InodeT, name: bytes, mode, ctx):
        """Create a directory."""
        path = os.path.join(self._inode_to_path(parent_inode), fsdecode(name))
        try:
            os.mkdir(path, mode=(mode & ~ctx.umask))
            os.chown(path, ctx.uid, ctx.gid)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        attr = self._getattr(path=path)
        self._add_path(attr.st_ino, path)
        return attr
    
    async def statfs(self, ctx):
        """Get filesystem statistics."""
        root = self._inode_path_map[pyfuse3.ROOT_INODE]
        stat_ = pyfuse3.StatvfsData()
        try:
            statfs = os.statvfs(root)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        for attr in ('f_bsize', 'f_frsize', 'f_blocks', 'f_bfree', 'f_bavail',
                     'f_files', 'f_ffree', 'f_favail'):
            setattr(stat_, attr, getattr(statfs, attr))
        stat_.f_namemax = statfs.f_namemax - (len(root) + 1)
        return stat_
    
    async def open(self, inode: InodeT, flags, ctx):
        """Open a file."""
        if inode in self._inode_fd_map:
            fd = self._inode_fd_map[inode]
            self._fd_open_count[fd] += 1
            return pyfuse3.FileInfo(fh=fd)
        
        assert flags & os.O_CREAT == 0
        try:
            fd = os.open(self._inode_to_path(inode), flags)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        self._inode_fd_map[inode] = fd
        self._fd_inode_map[fd] = inode
        self._fd_open_count[fd] = 1
        return pyfuse3.FileInfo(fh=fd)
    
    async def create(self, parent_inode: InodeT, name: bytes, mode, flags, ctx):
        """Create and open a file."""
        path = os.path.join(self._inode_to_path(parent_inode), fsdecode(name))
        try:
            fd = os.open(path, flags | os.O_CREAT | os.O_TRUNC)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
        
        attr = self._getattr(fd=fd)
        self._add_path(attr.st_ino, path)
        self._inode_fd_map[attr.st_ino] = fd
        self._fd_inode_map[fd] = attr.st_ino
        self._fd_open_count[fd] = 1
        return (pyfuse3.FileInfo(fh=fd), attr)
    
    async def read(self, fh, off, size):
        """Read data from an open file."""
        os.lseek(fh, off, os.SEEK_SET)
        return os.read(fh, size)
    
    async def write(self, fh, off, buf):
        """Write data to an open file."""
        os.lseek(fh, off, os.SEEK_SET)
        return os.write(fh, buf)
    
    async def release(self, fh):
        """Close an open file."""
        if self._fd_open_count[fh] > 1:
            self._fd_open_count[fh] -= 1
            return
        
        del self._fd_open_count[fh]
        inode = self._fd_inode_map[fh]
        del self._inode_fd_map[inode]
        del self._fd_inode_map[fh]
        try:
            os.close(fh)
        except OSError as exc:
            assert exc.errno is not None
            raise FUSEError(exc.errno)
