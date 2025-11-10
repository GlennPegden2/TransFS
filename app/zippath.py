from pathlib import Path
import os
import zipfile
from typing import Optional, Tuple, List, Iterable
from functools import lru_cache
import io
from typing import cast

# Policy: prefer real directory named *.zip over treating it as an archive.
# _find_zip_component returns (zip_path, inner_path) or None if no zip component found.

def _path_parts(path: str) -> List[str]:
    p = Path(path)
    parts = list(p.parts)
    # On Windows Path.parts can include drive; keep as-is
    return parts

def _join_parts(parts: Iterable[str]) -> str:
    # Use os.path.join to create platform-appropriate path (keeps leading / if present)
    return os.path.join(*parts)

def _normalize_zip_inner(inner: str) -> str:
    # Zip entries are always posix-style, use forward slashes
    if not inner:
        return ""
    return inner.replace(os.sep, "/").lstrip("/")

def _find_zip_component(path: str) -> Optional[Tuple[str, str]]:
    """
    Return (zip_path, inner_path) for the first path component that is a zip file on disk,
    walking from left->right. If no zip component present, return None.

    Policy: if candidate is an actual directory, treat it as a directory (prefer dir over zip).
    """
    parts = _path_parts(path)
    if not parts:
        return None
    # Build incremental paths, include root if present (e.g. '/', 'C:\\')
    for i in range(1, len(parts) + 1):
        candidate = _join_parts(parts[:i])
        # If candidate is a directory, prefer it and continue scanning further components
        if os.path.isdir(candidate):
            continue
        if candidate.lower().endswith('.zip') and os.path.isfile(candidate):
            inner_parts = parts[i:]
            inner = _normalize_zip_inner(_join_parts(inner_parts)) if inner_parts else ""
            return (os.path.abspath(candidate), inner)
    return None

@lru_cache(maxsize=128)
def _zip_namelist(zip_path: str) -> List[str]:
    zip_path = os.path.abspath(zip_path)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        # Filter out directory entries that are explicit (ending with '/')
        return [n for n in zf.namelist()]

def exists(path: str) -> bool:
    z = _find_zip_component(path)
    if z is None:
        return os.path.exists(path)
    zip_path, inner = z
    try:
        if inner == "":
            # zip root exists if zip file exists
            return os.path.isfile(zip_path)
        namelist = _zip_namelist(zip_path)
        if inner in namelist:
            return True
        # directory-like: check any entry startswith inner + '/'
        inner_pref = inner.rstrip('/') + '/'
        return any(n.startswith(inner_pref) for n in namelist)
    except Exception:
        return False

def isdir(path: str) -> bool:
    z = _find_zip_component(path)
    if z is None:
        return os.path.isdir(path)
    zip_path, inner = z
    if inner == "":
        # root of the zip treated as directory
        return True
    try:
        namelist = _zip_namelist(zip_path)
        inner_pref = inner.rstrip('/') + '/'
        # If exact entry exists and ends with '/', treat as dir
        if inner in namelist and inner.endswith('/'):
            return True
        return any(n.startswith(inner_pref) for n in namelist)
    except Exception:
        return False

def isfile(path: str) -> bool:
    z = _find_zip_component(path)
    if z is None:
        return os.path.isfile(path)
    zip_path, inner = z
    if inner == "":
        return False
    try:
        namelist = _zip_namelist(zip_path)
        # Exact match (and not a directory entry)
        return inner in namelist and not inner.endswith('/')
    except Exception:
        return False

def listdir(path: str) -> List[str]:
    """
    List immediate children of path. For zip-contained paths, return entries inside the zip.
    """
    z = _find_zip_component(path)
    if z is None:
        try:
            return sorted([e for e in os.listdir(path) if not e.startswith('.')])
        except Exception:
            return []
    zip_path, inner = z
    try:
        namelist = _zip_namelist(zip_path)
        prefix = inner.rstrip('/') + '/' if inner else ''
        seen = set()
        for entry in namelist:
            if not entry.startswith(prefix):
                continue
            rest = entry[len(prefix):]
            if rest == '':
                continue
            first_component = rest.split('/', 1)[0]
            seen.add(first_component)
        return sorted(seen)
    except Exception:
        return []

def getinfo(path: str):
    """
    Return a small dict with metadata for a path (size, is_dir).
    """
    z = _find_zip_component(path)
    if z is None:
        try:
            st = os.stat(path)
            return {
                "size": st.st_size,
                "is_dir": os.path.isdir(path),
                "mtime": int(st.st_mtime),
            }
        except Exception:
            return None
    zip_path, inner = z
    try:
        with zipfile.ZipFile(zip_path, 'r') as zf:
            if inner == "":
                # zip root
                return {"size": os.path.getsize(zip_path), "is_dir": True, "mtime": int(os.path.getmtime(zip_path))}
            # zipfile raises KeyError if not present
            info = zf.getinfo(inner)
            return {"size": info.file_size, "is_dir": inner.endswith('/'), "mtime": None}
    except KeyError:
        # Could be a directory implied by entries
        try:
            namelist = _zip_namelist(zip_path)
            inner_pref = inner.rstrip('/') + '/'
            if any(n.startswith(inner_pref) for n in namelist):
                return {"size": 0, "is_dir": True, "mtime": None}
        except Exception:
            pass
    except Exception:
        pass
    return None

class _ZipEntryFile:
    """
    Wrapper that keeps the ZipFile open while the returned file-like is used.
    Delegates read/seek/tell/close to the underlying ZipExtFile.
    """
    def __init__(self, zip_path: str, inner: str, mode: str = 'r'):
        # Only support reading entries from zip
        if 'w' in mode or 'a' in mode or '+' in mode:
            raise ValueError("zip entries are read-only via this API")
        self._zip_path = os.path.abspath(zip_path)
        self._inner = inner
        self._zf = zipfile.ZipFile(self._zip_path, 'r')
        # zipfile returns a file-like in binary mode
        self._file = self._zf.open(inner, 'r')
        # Provide a buffered wrapper for .read() semantics. ZipExtFile lacks 'readinto'
        # in type stubs, so cast to RawIOBase to satisfy the type checker.
        self._buffer = io.BufferedReader(cast(io.RawIOBase, self._file))
        self._closed = False

    @property
    def name(self) -> str:
        return self._inner

    @property
    def closed(self) -> bool:
        return self._closed

    def read(self, *args, **kwargs):
        return self._buffer.read(*args, **kwargs)

    def readline(self, *args, **kwargs):
        return self._buffer.readline(*args, **kwargs)

    def readinto(self, b):
        return self._buffer.readinto(b)

    def write(self, b):
        raise OSError("zip entries are read-only")

    def flush(self):
        pass  # No-op for read-only streams

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def truncate(self, size=None):
        raise OSError("zip entries are read-only")

    def fileno(self):
        raise OSError("zip entries do not have file descriptors")

    def isatty(self) -> bool:
        return False

    def seek(self, offset, whence=io.SEEK_SET):
        # ZipExtFile does not support random access in general; emulated via read/discard if needed.
        # Provide basic support: if whence == 1 or 2 raise.
        if whence != io.SEEK_SET or offset < 0:
            raise OSError("seek not supported on zip entry")
        # Reopen and read to offset (inefficient). Caller should avoid seeking.
        self._buffer.close()
        self._file.close()
        self._zf.close()
        self._zf = zipfile.ZipFile(self._zip_path, 'r')
        self._file = self._zf.open(self._inner, 'r')
        self._buffer = io.BufferedReader(cast(io.RawIOBase, self._file))
        if offset:
            self._buffer.read(offset)
        return self.tell()

    def tell(self):
        return self._buffer.tell()

    def close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._buffer.close()
        except Exception:
            pass
        try:
            self._file.close()
        except Exception:
            pass
        try:
            self._zf.close()
        except Exception:
            pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

def open_file(path: str, mode: str = "rb"):
    """
    Return a file-like object. For files inside zips, the returned object must be closed to
    release the underlying ZipFile handle.
    """
    z = _find_zip_component(path)
    if z is None:
        return open(path, mode)
    zip_path, inner = z
    if inner == "":
        # Cannot open root of zip
        raise FileNotFoundError(path)
    # zipfile returns binary stream; our wrapper provides buffering and ensures ZipFile lifetime
    # Accept textual modes by wrapping binary object as TextIO if requested
    bin_handle = _ZipEntryFile(zip_path, inner, mode)
    if 'b' in mode:
        return bin_handle
    # text mode requested: wrap with TextIOWrapper
    return io.TextIOWrapper(bin_handle, encoding='utf-8')

# Note: If you heavily open many zip files, consider adding an LRU cache of ZipFile metadata or handles.
# This module intentionally caches namelists only (via _zip_namelist).