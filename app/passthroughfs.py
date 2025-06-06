#!/usr/bin/env python
from __future__ import with_statement

import os
import errno
from fuse import FUSE, FuseOSError, Operations, fuse_get_context


class Passthrough(Operations):
    def __init__(self, root_path):
        self.root = root_path

    # Helpers
    # =======

    def _full_path(self, partial):
        if partial.startswith("/"):
            partial = partial[1:]
        path = os.path.join(self.root, partial)
        return path

    # Filesystem methods
    # ==================

    def access(self, path, amode):
        full_path = self._full_path(path)
        if not os.access(full_path, amode):
            raise FuseOSError(errno.EACCES)
        return 0

    def chmod(self, path, mode): # type: ignore
        full_path = self._full_path(path)
        os.chmod(full_path, mode)
        return 0

    def chown(self, path, uid, gid):
        full_path = self._full_path(path)
        if hasattr(os, 'chown'):
            return os.chown(full_path, uid, gid) # type: ignore
        else:
            raise NotImplementedError("os.chown is not available on this platform")

    def getattr(self, path, fh=None): # type: ignore
        full_path = self._full_path(path)
        st = os.lstat(full_path)
        return dict((key, int(getattr(st, key))) for key in ('st_atime', 'st_ctime',
                                                             'st_gid', 'st_mode', 'st_mtime', 'st_nlink', 'st_size', 'st_uid'))

    def readdir(self, path, fh): # type: ignore
        full_path = self._full_path(path)

        dirents = ['.', '..']
        if os.path.isdir(full_path):
            dirents.extend(os.listdir(full_path))
        for r in dirents:
            yield r

    def readlink(self, path):
        pathname = os.readlink(self._full_path(path))
        if pathname.startswith("/"):
            # Path name is absolute, sanitize it.
            return os.path.relpath(pathname, self.root)
        else:
            return pathname

    def mknod(self, path, mode, dev):
        if hasattr(os, 'mknod'):
            return os.mknod(self._full_path(path), mode, dev) # type: ignore
        else:
            raise NotImplementedError("os.mknod is not available on this platform")

    def rmdir(self, path): # type: ignore
        full_path = self._full_path(path)
        return os.rmdir(full_path)

    def mkdir(self, path, mode): # type: ignore
        return os.mkdir(self._full_path(path), mode)

    def statfs(self, path):
        full_path = self._full_path(path)
        if hasattr(os, 'statvfs'):
            stv = os.statvfs(full_path) # type: ignore
            return dict((key, getattr(stv, key)) for key in ('f_bavail', 'f_bfree',
                                                             'f_blocks', 'f_bsize', 'f_favail', 'f_ffree', 'f_files', 'f_flag',
                                                             'f_frsize', 'f_namemax'))
        else:
            raise NotImplementedError("os.statvfs is not available on this platform")

    def unlink(self, path): # type: ignore
        return os.unlink(self._full_path(path))

    def symlink(self, name, target): # type: ignore
        return os.symlink(target, self._full_path(name))

    def rename(self, old, new): # type: ignore
        return os.rename(self._full_path(old), self._full_path(new))

    def link(self, target, name): # type: ignore
        return os.link(self._full_path(name), self._full_path(target))

    def utimens(self, path, times=None): # type: ignore
        return os.utime(self._full_path(path), times)

    # File methods
    # ============

    def open(self, path, flags): # type: ignore
        full_path = self._full_path(path)
        return os.open(full_path, flags)

    def create(self, path, mode, fi=None): # type: ignore
        uid, gid, pid = fuse_get_context()
        full_path = self._full_path(path)
        fd = os.open(full_path, os.O_WRONLY | os.O_CREAT, mode)
        try:
            os.chown(full_path, uid, gid)  # type: ignore # chown to context uid & gid 
        except AttributeError:
            os.system(f'chown {uid}:{gid} "{full_path}"')  # Fallback to system call
        return fd

    def read(self, path, length, offset, fh): # type: ignore
        os.lseek(fh, offset, os.SEEK_SET)
        return os.read(fh, length)

    def write(self, path, buf, offset, fh): # type: ignore
        os.lseek(fh, offset, os.SEEK_SET)
        return os.write(fh, buf)

    def truncate(self, path, length, fh=None): # type: ignore
        full_path = self._full_path(path)
        with open(full_path, 'r+') as f:
            f.truncate(length)

    def flush(self, path, fh): # type: ignore
        return os.fsync(fh)

    def release(self, path, fh): # type: ignore
        return os.close(fh)

    def fsync(self, path, fdatasync, fh): # type: ignore
        return self.flush(path, fh)


def main(mountpoint, root):
    FUSE(Passthrough(root_path=root), mountpoint, nothreads=True,
         foreground=True, allow_other=True)


if __name__ == '__main__':
    mountpoint = "/mnt/transfs"
    root = "/mnt/filestorefs"
    main(mountpoint, root)
