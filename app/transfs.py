#!/usr/bin/env python

import errno
import logging
import os
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Literal, Optional, cast

import yaml
from fuse import FUSE, FuseOSError
from passthroughfs import Passthrough  
from logging_setup import setup_logging

setup_logging(logging.DEBUG)
logger = logging.getLogger("transfs")
logger.debug("TEST: Logging setup works")


from dirlisting import parse_trans_path
from pathutils import (
    full_path,
    is_virtual_path,
    map_virtual_to_real,
)
from sourcepath import get_source_path


class TransFS(Passthrough):
    """FUSE filesystem for translating virtual paths to real files, including zip logic and filetype mapping."""

    def __init__(self, root_path: str):
        super().__init__(root_path)
        logger.debug("Starting TransFS")
        self.root = root_path
        with open("transfs.yaml", "r", encoding="UTF-8") as f:
            self.config = yaml.safe_load(f)

    def readdir(self, path: str, fh: int):
        logger.debug("DEBUG: readdir(%s)", path)
        xfull_path = full_path(self.root,path)
        dirents = ['.', '..']
        virtual_entries = set(parse_trans_path(self.config,self.root, xfull_path))
        dirents.extend(virtual_entries)
        if os.path.isdir(xfull_path):
            for entry in os.listdir(xfull_path):
                if entry not in virtual_entries:
                    dirents.append(entry)
        for entry in dirents:
            logger.debug("DEBUG: readdir yields %s", entry)
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
        logger.debug("DEBUG: getattr(%s)", path)
        xfull_path = full_path(self.root, path)
        fspath = get_source_path(logger, self.config, self.root, xfull_path)
        logger.debug("DEBUG: getattr full_path=%s, fspath=%s", xfull_path, fspath)

        # PATCH: If mapped to a file inside a zip (unzip: true), always stat as a file
        if isinstance(fspath, tuple):
            logger.debug("DEBUG: Inside isinstance(fspath, tuple) branch: %s", fspath)
            zip_path, internal_file = fspath
            with zipfile.ZipFile(zip_path, 'r') as zf:
                info = zf.getinfo(internal_file)
                now = int(os.path.getmtime(zip_path))
                return {
                    'st_atime': now,
                    'st_ctime': now,
                    'st_mtime': now,
                    'st_gid': 0,
                    'st_uid': 0,
                    'st_mode': 0o100444,  # regular file, read-only
                    'st_nlink': 1,
                    'st_size': info.file_size,
                }

        if fspath is None:
            # Try to stat as a virtual entry if it is in the virtual directory listing
            parent_path = str(Path(xfull_path).parent)
            entries = set(parse_trans_path(self.config,self.root, parent_path))
            name = os.path.basename(xfull_path)

            logger.debug("DEBUG getattr fallback: parent_path=%s, entries=%s, name=%s", parent_path, entries, name)

            if name in entries:
                now = int(time.time())
                # Heuristic: treat as file if it has a dot (extension), else directory
                if '.' in name:
                    mode = 0o100444  # file
                    nlink = 1
                    size = 0
                else:
                    mode = 0o040755  # directory
                    nlink = 2
                    size = 4096
                return {
                    'st_atime': now,
                    'st_ctime': now,
                    'st_mtime': now,
                    'st_gid': 0,
                    'st_uid': 0,
                    'st_mode': mode,
                    'st_nlink': nlink,
                    'st_size': size,
                }
            # Otherwise, fall through to ENOENT
            raise FuseOSError(errno.ENOENT)

        logger.debug("DEBUG: getattr(%s) full_path=%s fspath=%s type=%s", path, full_path, fspath, type(fspath))

        # PATCH: treat zip files as directories unless mapped with unzip: true
        if isinstance(fspath, str) and fspath.lower().endswith('.zip'):
            # Only treat as file if this is a mapped file with unzip: false or missing
            # Otherwise, treat as directory
            st = os.lstat(fspath)
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
            # Check if this is a virtual entry (i.e., listed in the parent directory)
            parent_path = str(Path(xfull_path).parent)
            entries = set(parse_trans_path(self.config, self.root, parent_path))
            name = os.path.basename(xfull_path)
            logger.debug("DEBUG getattr fallback (real missing): parent_path=%s, entries=%s, name=%s", parent_path, entries, name)
            if name in entries:
                now = int(time.time())
                # Heuristic: treat as file if it has a dot (extension), else directory
                if '.' in name:
                    mode = 0o100444  # file
                    nlink = 1
                    size = 0
                else:
                    mode = 0o040755  # directory
                    nlink = 2
                    size = 4096
                return {
                    'st_atime': now,
                    'st_ctime': now,
                    'st_mtime': now,
                    'st_gid': 0,
                    'st_uid': 0,
                    'st_mode': mode,
                    'st_nlink': nlink,
                    'st_size': size,
                }
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
            logger.debug("DEBUG: open: no mapping for %s", path)
            raise FuseOSError(errno.ENOENT)

        if isinstance(trans_path, tuple):
            zip_path, internal_file = trans_path
            logger.debug("DEBUG: open extracting %s from %s", internal_file, zip_path)
            if not os.path.exists(zip_path):
                logger.error("open: zip file %s does not exist", zip_path)
                raise FuseOSError(errno.ENOENT)
            with zipfile.ZipFile(zip_path, 'r') as zf:
                if internal_file not in zf.namelist():
                    logger.error("open: %s not in zip %s. Contents: %s", internal_file, zip_path, zf.namelist())
                    raise FuseOSError(errno.ENOENT)
                temp = tempfile.NamedTemporaryFile(delete=False)
                temp.write(zf.read(internal_file))
                temp.close()
                logger.debug("DEBUG: open temp file created at %s", temp.name)
                return os.open(temp.name, flags)

        if isinstance(trans_path, str):
            if not os.path.exists(trans_path):
                logger.error("open: real file %s does not exist", trans_path)
                raise FuseOSError(errno.ENOENT)
            logger.debug("open using trans_path=%s", trans_path)
            return os.open(trans_path, flags)

        logger.debug("DEBUG: open: unknown mapping for %s", path)
        raise FuseOSError(errno.ENOENT)



    def create(self, path, mode, fi=None):
        logger.debug("CREATE: called with path=%s, mode=%s", path, oct(mode))
        real_path = map_virtual_to_real(self.config, path)
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
        return None

    def unlink(self, path):
        logger.debug("UNLINK: called with path=%s", path)
        real_path = map_virtual_to_real(self.config, path)
        logger.debug("UNLINK: real_path=%s", real_path)
        if real_path is None or not os.path.exists(real_path):
            logger.debug("UNLINK: ENOENT")
            raise FuseOSError(errno.ENOENT)
        os.unlink(real_path)


def main(mount_path: str, root_path: str):
    FUSE(
        TransFS(root_path=root_path),
        mount_path,
        nothreads=True,
        foreground=True,
        debug=True,
        encoding='utf-8',
        allow_other=True
    )


if __name__ == '__main__':
    main(mount_path="/mnt/transfs", root_path="/mnt/filestorefs")
