from pathlib import Path
import os
import zipfile
from typing import Optional, Tuple, List, Iterable, Dict, Set
from functools import lru_cache
import io
from typing import cast
import pickle
import threading
import time
import logging  # [added]

logger = logging.getLogger(__name__)  # [added]

# [added] Simple timing decorator (logs calls taking >= 100ms)
def _timed(func):
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = time.perf_counter() - start
        if elapsed > 0.1:  # log only slow calls
            try:
                arg0 = args[0]
            except Exception:  # pylint: disable=broad-except
                arg0 = "N/A"
            logger.debug("%s took %.3fs for %s", func.__name__, elapsed, arg0)
        return result
    return wrapper

# ==========================
# Fast hierarchical ZIP index
# ==========================
class ZipIndex:
    """
    Lazy ZIP index to reduce build-time overhead for very large archives.
    Eager parent-chain construction removed; directory child lists are
    derived on-demand per prefix and cached.
    """
    __slots__ = (
        "zip_path", "mtime", "built_at",
        "_raw_entries",        # List[Tuple[str, int, bool]]
        "_file_set", "_dir_set",
        "_file_sizes",
        "_children_cache"      # Dict[str, List[str]]
    )
    def __init__(self, zip_path: str, mtime: float):
        self.zip_path = zip_path
        self.mtime = mtime
        self.built_at = time.time()
        self._raw_entries: List[Tuple[str, int, bool]] = []  # (logical_name, size, is_dir)
        self._file_set: Optional[Set[str]] = None
        self._dir_set: Optional[Set[str]] = None
        self._file_sizes: Optional[Dict[str, int]] = None
        self._children_cache: Dict[str, List[str]] = {}

    # Called during initial scan; minimal work (strip trailing slash only)
    def add_raw(self, logical_name: str, size: int, is_dir: bool):
        self._raw_entries.append((logical_name, size, is_dir))

    def _ensure_sets(self):
        if self._file_set is not None:
            return
        files: Set[str] = set()
        dirs: Set[str] = set([""])
        sizes: Dict[str, int] = {}
        for name, size, is_dir in self._raw_entries:
            if is_dir:
                dirs.add(name)
            else:
                files.add(name)
                sizes[name] = size
        # Infer directories from file paths (parents) lazily
        for fname in files:
            parts = fname.split("/")
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))
        self._file_set = files
        self._dir_set = dirs
        self._file_sizes = sizes

    def _children_for(self, prefix: str) -> List[str]:
        if prefix in self._children_cache:
            return self._children_cache[prefix]
        self._ensure_sets()
        files = self._file_set  # type: ignore
        dirs = self._dir_set    # type: ignore
        plen = len(prefix)
        prefix_slash = prefix + "/" if prefix else ""
        children: Set[str] = set()
        # From files
        for f in files:  # type: ignore
            if prefix == "":
                # Top-level: get first path component
                first = f.split("/", 1)[0]
                children.add(first)
            elif f.startswith(prefix_slash):
                # File is under the prefix directory
                rest = f[plen + 1:]
                if rest:
                    first = rest.split("/", 1)[0]
                    children.add(first)
        # From dirs
        for d in dirs:  # type: ignore
            if d == prefix or d == "":
                continue
            if prefix == "":
                first = d.split("/", 1)[0]
                children.add(first)
            else:
                if d.startswith(prefix_slash):
                    rest = d[plen + 1:]
                    if rest:
                        first = rest.split("/", 1)[0]
                        children.add(first)
        result = sorted(children)
        self._children_cache[prefix] = result
        return result

    def listdir(self, inner: str) -> List[str]:
        prefix = inner.strip("/")
        return self._children_for(prefix)

    def exists(self, inner: str) -> bool:
        key = inner.strip("/")
        if key == "":
            return True
        self._ensure_sets()
        return key in self._file_set or key in self._dir_set  # type: ignore

    def isdir(self, inner: str) -> bool:
        key = inner.strip("/")
        if key == "":
            return True
        self._ensure_sets()
        if key in self._dir_set:  # type: ignore
            return True
        # Implicit directory if any file under it
        prefix = key + "/"
        return any(f.startswith(prefix) for f in self._file_set)  # type: ignore

    def isfile(self, inner: str) -> bool:
        key = inner.strip("/")
        self._ensure_sets()
        return key in self._file_set  # type: ignore

_index_lock = threading.Lock()
_zip_index_cache: Dict[str, ZipIndex] = {}
_MAX_INDEX_AGE = 3600

# NEW: Thread-local cache to eliminate lock contention during readdir+getattr bursts
_thread_local = threading.local()

def _get_thread_cache() -> Dict[str, ZipIndex]:
    """Get thread-local index cache (no lock needed)."""
    if not hasattr(_thread_local, 'zip_cache'):
        _thread_local.zip_cache = {}
    return _thread_local.zip_cache

def _persist_index(idx: ZipIndex):
    if os.getenv("TRANSFS_PERSIST_ZIP_INDEX", "0") != "1":
        return
    idx_path = idx.zip_path + ".transfs.zipindex"
    try:
        # Security: restrictive permissions (user read/write only)
        fd = os.open(idx_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as f:
            pickle.dump(idx, f, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception:  # pylint: disable=broad-except
        pass

def _load_persisted_index(zip_path: str, mtime: float) -> Optional[ZipIndex]:
    idx_path = zip_path + ".transfs.zipindex"
    try:
        if not os.path.isfile(idx_path):
            return None
        # Security: verify file ownership and permissions
        st = os.stat(idx_path)
        # Only perform uid check on Unix-like systems
        if hasattr(os, 'getuid'):
            if st.st_uid != os.getuid() or (st.st_mode & 0o077) != 0: # type: ignore
                return None
        with open(idx_path, "rb") as f:
            obj = pickle.load(f)
        if isinstance(obj, ZipIndex) and obj.mtime == mtime:
            return obj
    except Exception:  # pylint: disable=broad-except
        return None
    return None

@_timed
def _build_index(zip_path: str, mtime: float) -> ZipIndex:
    idx = ZipIndex(zip_path, mtime)
    with zipfile.ZipFile(zip_path, 'r') as zf:
        t0 = time.perf_counter()
        infos = zf.infolist()
        logger.debug("ZipFile.infolist() took %.3fs for %s entries=%d", time.perf_counter() - t0, zip_path, len(infos))
        for info in infos:
            is_dir = info.filename.endswith('/')
            logical_name = info.filename[:-1] if is_dir else info.filename
            idx.add_raw(logical_name, info.file_size, is_dir)
    _persist_index(idx)
    return idx

def _get_index(zip_path: str) -> ZipIndex:
    """Get or build index with minimal lock contention."""
    zp = os.path.abspath(zip_path)
    
    # Fast path: check thread-local cache first (no lock)
    tc = _get_thread_cache()
    idx = tc.get(zp)
    if idx:
        try:
            mtime = os.path.getmtime(zp)
            if idx.mtime == mtime and (time.time() - idx.built_at) < _MAX_INDEX_AGE:
                return idx
        except OSError:
            pass
    
    # Get mtime for validation
    try:
        mtime = os.path.getmtime(zp)
    except OSError as exc:
        raise FileNotFoundError(zp) from exc
    
    # Check global cache without full lock (optimistic read)
    curr = _zip_index_cache.get(zp)
    if curr and curr.mtime == mtime and (time.time() - curr.built_at) < _MAX_INDEX_AGE:
        tc[zp] = curr
        return curr
    
    # Slow path: acquire lock and build/load index
    with _index_lock:
        # Double-check after acquiring lock
        curr = _zip_index_cache.get(zp)
        if curr and curr.mtime == mtime and (time.time() - curr.built_at) < _MAX_INDEX_AGE:
            tc[zp] = curr
            return curr
        
        # Try persisted index
        persisted = _load_persisted_index(zp, mtime)
        if persisted:
            _zip_index_cache[zp] = persisted
            tc[zp] = persisted
            return persisted
        
        # Build fresh
        fresh = _build_index(zp, mtime)
        _zip_index_cache[zp] = fresh
        tc[zp] = fresh
        return fresh

# ==========================
# Existing helpers (preserved)
# ==========================

def _path_parts(path: str) -> List[str]:
    p = Path(path)
    parts = list(p.parts)
    return parts

def _join_parts(parts: Iterable[str]) -> str:
    return os.path.join(*parts)

def _normalize_zip_inner(inner: str) -> str:
    if not inner:
        return ""
    return inner.replace(os.sep, "/").lstrip("/")

def _find_zip_component(path: str) -> Optional[Tuple[str, str]]:
    """
    Return (zip_path, inner_path) for the first path component that is a zip file on disk,
    walking from left->right. Prefer a real directory named *.zip over an archive file.
    """
    parts = _path_parts(path)
    if not parts:
        return None
    for i in range(1, len(parts) + 1):
        candidate = _join_parts(parts[:i])
        if os.path.isdir(candidate):
            continue
        if candidate.lower().endswith(".zip") and os.path.isfile(candidate):
            inner_parts = parts[i:]
            inner = _normalize_zip_inner(_join_parts(inner_parts)) if inner_parts else ""
            return (os.path.abspath(candidate), inner)
    return None

@lru_cache(maxsize=128)
def _zip_namelist(zip_path: str) -> List[str]:
    zip_path = os.path.abspath(zip_path)
    with zipfile.ZipFile(zip_path, "r") as zf:
        return [n for n in zf.namelist()]

# ==========================
# Public API (augmented, fallback preserved)
# ==========================

@_timed
def exists(path: str) -> bool:
    z = _find_zip_component(path)
    if z is None:
        return os.path.exists(path)
    zip_path, inner = z
    try:
        return _get_index(zip_path).exists(inner)
    except Exception:  # pylint: disable=broad-except
        # Fallback to previous behavior
        try:
            if inner == "":
                return os.path.isfile(zip_path)
            names = _zip_namelist(zip_path)
            if inner in names:
                return True
            pref = inner.rstrip("/") + "/"
            return any(n.startswith(pref) for n in names)
        except Exception:  # pylint: disable=broad-except
            return False

@_timed
def isdir(path: str) -> bool:
    z = _find_zip_component(path)
    if z is None:
        return os.path.isdir(path)
    zip_path, inner = z
    try:
        return _get_index(zip_path).isdir(inner)
    except Exception:  # pylint: disable=broad-except
        try:
            if inner == "":
                return True
            names = _zip_namelist(zip_path)
            pref = inner.rstrip("/") + "/"
            if inner in names and inner.endswith("/"):
                return True
            return any(n.startswith(pref) for n in names)
        except Exception:  # pylint: disable=broad-except
            return False

@_timed
def isfile(path: str) -> bool:
    z = _find_zip_component(path)
    if z is None:
        return os.path.isfile(path)
    zip_path, inner = z
    if inner == "":
        return False
    try:
        return _get_index(zip_path).isfile(inner)
    except Exception:  # pylint: disable=broad-except
        try:
            names = _zip_namelist(zip_path)
            return inner in names and not inner.endswith("/")
        except Exception:  # pylint: disable=broad-except
            return False

@_timed
def listdir(path: str) -> List[str]:
    """
    List immediate children of path. For zip-contained paths, use the fast index if available.
    """
    z = _find_zip_component(path)
    if z is None:
        try:
            return sorted([e for e in os.listdir(path) if not e.startswith(".")])
        except Exception:  # pylint: disable=broad-except
            return []
    zip_path, inner = z
    try:
        return _get_index(zip_path).listdir(inner)
    except Exception:  # pylint: disable=broad-except
        # Fallback to previous behavior
        try:
            names = _zip_namelist(zip_path)
            prefix = inner.rstrip("/") + "/" if inner else ""
            seen = set()
            for entry in names:
                if not entry.startswith(prefix):
                    continue
                rest = entry[len(prefix):]
                if rest == "":
                    continue
                first = rest.split("/", 1)[0]
                seen.add(first)
            return sorted(seen)
        except Exception:  # pylint: disable=broad-except
            return []

@_timed
def getinfo(path: str):
    t_start = time.perf_counter()
    z = _find_zip_component(path)
    t_find = time.perf_counter() - t_start
    
    if z is None:
        try:
            st = os.stat(path)
            return {"size": st.st_size, "is_dir": os.path.isdir(path), "mtime": int(st.st_mtime)}
        except Exception:  # pylint: disable=broad-except
            return None
    zip_path, inner = z
    t_idx_start = time.perf_counter()
    try:
        idx = _get_index(zip_path)
        t_idx = time.perf_counter() - t_idx_start
        
        if inner == "":
            return {"size": os.path.getsize(zip_path), "is_dir": True, "mtime": int(os.path.getmtime(zip_path))}
        
        t_check_start = time.perf_counter()
        if idx.isfile(inner):
            # Ensure sizes loaded
            idx._ensure_sets()  # pylint: disable=protected-access
            size = idx._file_sizes.get(inner, 0) if idx._file_sizes else 0  # pylint: disable=protected-access
            t_check = time.perf_counter() - t_check_start
            t_total = time.perf_counter() - t_start
            if t_total > 0.05:
                logger.warning("PERF: getinfo slow %.3fs (find=%.3fs, idx=%.3fs, check=%.3fs) for %s", t_total, t_find, t_idx, t_check, path)
            return {"size": size, "is_dir": False, "mtime": None}
        if idx.isdir(inner):
            t_check = time.perf_counter() - t_check_start
            t_total = time.perf_counter() - t_start
            if t_total > 0.05:
                logger.warning("PERF: getinfo slow %.3fs (find=%.3fs, idx=%.3fs, check=%.3fs) for %s", t_total, t_find, t_idx, t_check, path)
            return {"size": 0, "is_dir": True, "mtime": None}
    except Exception:  # pylint: disable=broad-except
        pass
    return None

def listdir_with_info(path: str) -> List[dict]:
    """
    List directory contents with metadata (name, size, is_dir) in one efficient call.
    This is much faster than calling listdir() then getinfo() for each entry.
    """
    z = _find_zip_component(path)
    if z is None:
        # Regular directory - use os.scandir for efficiency
        try:
            result = []
            for entry in os.scandir(path):
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    size = 0 if is_dir else entry.stat(follow_symlinks=False).st_size
                    result.append({
                        "name": entry.name,
                        "size": size,
                        "is_dir": is_dir
                    })
                except (PermissionError, OSError):
                    continue
            return result
        except Exception:  # pylint: disable=broad-except
            return []
    
    # ZIP path - use cached index for maximum efficiency
    zip_path, inner = z
    try:
        idx = _get_index(zip_path)
        idx._ensure_sets()  # pylint: disable=protected-access
        
        # Get children from index
        children = idx.listdir(inner)
        
        # Build full paths and get metadata
        result = []
        inner_prefix = inner.strip("/")
        
        # Cache references to avoid attribute lookups in loop
        file_set = idx._file_set  # type: ignore  # pylint: disable=protected-access
        dir_set = idx._dir_set  # type: ignore  # pylint: disable=protected-access
        file_sizes = idx._file_sizes  # type: ignore  # pylint: disable=protected-access
        
        # Pre-compute separator (empty string or slash)
        sep = "/" if inner_prefix else ""
        
        for name in children:
            # Build full inner path efficiently
            full_inner = f"{inner_prefix}{sep}{name}" if inner_prefix else name
            
            # Check if it's a file or directory (set lookups are O(1))
            is_file = full_inner in file_set if file_set else False
            is_dir = full_inner in dir_set if dir_set else False
            
            size = file_sizes.get(full_inner, 0) if is_file and file_sizes else 0
            
            result.append({
                "name": name,
                "size": size,
                "is_dir": is_dir
            })
        
        return result
    except Exception:  # pylint: disable=broad-except
        return []

class _ZipEntryFile:
    """
    Wrapper that keeps the ZipFile open while the returned file-like is used.
    """
    def __init__(self, zip_path: str, inner: str, mode: str = "r"):
        if "w" in mode or "a" in mode or "+" in mode:
            raise ValueError("zip entries are read-only via this API")
        self._zip_path = os.path.abspath(zip_path)
        self._inner = inner
        self._zf = zipfile.ZipFile(self._zip_path, "r")
        self._file = self._zf.open(inner, "r")
        # Cast to satisfy type checker; ZipExtFile works with BufferedReader at runtime.
        self._buffer = io.BufferedReader(cast(io.RawIOBase, self._file))

    @property
    def name(self) -> str:
        return self._inner

    @property
    def closed(self) -> bool:
        return self._buffer.closed

    def read(self, *args, **kwargs):
        return self._buffer.read(*args, **kwargs)

    def readline(self, *args, **kwargs):
        return self._buffer.readline(*args, **kwargs)

    def write(self, *args, **kwargs):
        raise io.UnsupportedOperation("not writable")

    def flush(self):
        pass

    def seekable(self) -> bool:
        return self._buffer.seekable()

    def readable(self) -> bool:
        return self._buffer.readable()

    def writable(self) -> bool:
        return False

    def truncate(self, size=None):
        raise io.UnsupportedOperation("not writable")

    def fileno(self):
        raise io.UnsupportedOperation("fileno not supported for zip entries")

    def isatty(self) -> bool:
        return False

    def close(self):
        try: self._buffer.close()
        except Exception: pass  # pylint: disable=broad-except
        try: self._file.close()
        except Exception: pass  # pylint: disable=broad-except
        try: self._zf.close()
        except Exception: pass  # pylint: disable=broad-except

    def __enter__(self):
        return self
    def __exit__(self, *a):
        self.close()

def open_file(path: str, mode: str = "rb"):
    z = _find_zip_component(path)
    if z is None:
        return open(path, mode, encoding='utf-8' if 'b' not in mode else None)
    zip_path, inner = z
    if inner == "":
        raise FileNotFoundError(path)
    handle = _ZipEntryFile(zip_path, inner, mode)
    if "b" in mode:
        return handle
    return io.TextIOWrapper(handle, encoding="utf-8")