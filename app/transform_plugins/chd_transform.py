"""CHD (Compressed Hunks of Data) transform plugin.

Converts CD image formats (CUE/BIN, ISO, GDI, etc.) to MAME CHD format
on demand using chdman, with persistent disk caching.

The generated CHD is cached persistently so subsequent reads are instant.
The first access blocks while chdman converts the source image.

Usage in config (transforms section of a map):
    transforms:
      CUE:
        - type: chd
"""

import hashlib
import logging
import os
import subprocess
from dataclasses import dataclass, field
from typing import BinaryIO, Optional

from transforms import Transform, TransformError

logger = logging.getLogger(__name__)

# Default cache directory — persists across container restarts on the filestore volume.
# Override with the TRANSFS_CHD_CACHE_DIR environment variable.
DEFAULT_CACHE_DIR = os.environ.get(
    "TRANSFS_CHD_CACHE_DIR",
    "/mnt/filestorefs/.cache/chd",
)


@dataclass
class ChdTransform(Transform):
    """
    Convert a CD image (CUE/BIN, ISO, GDI) to CHD format using chdman.

    The CHD is built on first access and cached persistently.  Subsequent
    accesses are served directly from the cache without any conversion cost.

    The transform reports output_extension="chd" so TransFS renames the
    virtual file (e.g., game.cue → game.chd) in directory listings.

    Implements get_prebuilt_path() so transfs.py open() can serve the CHD
    file via a direct file descriptor instead of loading it into memory —
    essential for large images (500 MB+).
    """

    cache_dir: str = field(default_factory=lambda: DEFAULT_CACHE_DIR)

    # Internal state (not part of public interface)
    _chd_path: Optional[str] = field(default=None, init=False, repr=False)
    _chd_size: Optional[int] = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------ #
    #  Cache helpers                                                       #
    # ------------------------------------------------------------------ #

    def _cache_key(self, source_path: str) -> str:
        """Stable cache key based on source path + mtime + size."""
        try:
            stat = os.stat(source_path)
            key_data = f"{source_path}:{stat.st_mtime:.0f}:{stat.st_size}"
        except OSError:
            key_data = source_path
        return hashlib.md5(key_data.encode()).hexdigest()

    def _cache_path(self, source_path: str) -> str:
        """Return the expected on-disk cache path for a given source."""
        key = self._cache_key(source_path)
        basename = os.path.splitext(os.path.basename(source_path))[0]
        return os.path.join(self.cache_dir, f"{basename}_{key}.chd")

    # ------------------------------------------------------------------ #
    #  CHD build                                                           #
    # ------------------------------------------------------------------ #

    def _build_chd(self, source_path: str, chd_path: str) -> bool:
        """
        Run chdman to build the CHD file.  Returns True on success.

        Uses a .tmp staging file so a partial conversion is never left as
        a valid cache entry.
        """
        try:
            os.makedirs(self.cache_dir, exist_ok=True)
        except OSError as exc:
            logger.error("ChdTransform: cannot create cache dir %s: %s", self.cache_dir, exc)
            return False

        tmp_path = chd_path + ".tmp"
        try:
            logger.info(
                "ChdTransform: building CHD from %s -> %s", source_path, chd_path
            )
            result = subprocess.run(  # noqa: S603
                ["chdman", "createcd", "-i", source_path, "-o", tmp_path],
                capture_output=True,
                text=True,
                timeout=600,  # 10 minutes max for very large images
            )
            if result.returncode != 0:
                logger.error(
                    "ChdTransform: chdman failed (rc=%d) for %s: %s",
                    result.returncode, source_path, result.stderr.strip(),
                )
                return False

            os.rename(tmp_path, chd_path)
            logger.info(
                "ChdTransform: CHD built successfully at %s (%.1f MB)",
                chd_path, os.path.getsize(chd_path) / 1_048_576,
            )
            return True

        except subprocess.TimeoutExpired:
            logger.error("ChdTransform: chdman timed out for %s", source_path)
            return False
        except FileNotFoundError:
            logger.error(
                "ChdTransform: chdman not found — install mame-tools "
                "(apt-get install mame-tools)"
            )
            return False
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("ChdTransform: unexpected error: %s", exc)
            return False
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    # ------------------------------------------------------------------ #
    #  Public API used by transfs.py open()                               #
    # ------------------------------------------------------------------ #

    def get_prebuilt_path(self, source_path: str) -> Optional[str]:
        """
        Return the path to the cached CHD, building it if necessary.

        Called by transfs.py open() to serve the CHD via a direct fd,
        avoiding the need to load hundreds of MB into Python memory.

        Returns None if the build fails.
        """
        # Return cached path if still valid
        if self._chd_path and os.path.exists(self._chd_path):
            return self._chd_path

        chd_path = self._cache_path(source_path)

        if not os.path.exists(chd_path):
            if not self._build_chd(source_path, chd_path):
                return None

        self._chd_path = chd_path
        self._chd_size = os.path.getsize(chd_path)
        return chd_path

    # ------------------------------------------------------------------ #
    #  Transform interface                                                 #
    # ------------------------------------------------------------------ #

    def get_output_size(self, input_size: int) -> int:
        """
        Return the CHD size if already cached, otherwise -1 (unknown).

        Checks the on-disk cache even when _chd_path is not yet set in this
        process (e.g. after a container restart where the CHD already exists
        from a previous session).  When the source path is not yet known,
        the instance-level _chd_path/size attributes are used.
        """
        if self._chd_size is not None:
            return self._chd_size
        if self._chd_path and os.path.exists(self._chd_path):
            self._chd_size = os.path.getsize(self._chd_path)
            return self._chd_size
        return -1

    def get_output_size_for_path(self, source_path: str) -> int:
        """
        Return the CHD size for a specific source path by checking the
        on-disk cache, without triggering a build.

        Called by transfs.py _get_transform_output_size_for_path() during
        getattr/readdir when the source path is known, so that directory
        listings show the correct CHD size even before the first open().
        Returns -1 if not yet cached.
        """
        chd_path = self._cache_path(source_path)
        if os.path.exists(chd_path):
            size = os.path.getsize(chd_path)
            # Populate instance cache so get_output_size() also benefits
            self._chd_path = chd_path
            self._chd_size = size
            return size
        return -1

    def get_source_offset(self, virtual_offset: int) -> int:
        """1:1 offset mapping — the CHD file is served as-is."""
        return virtual_offset

    def can_random_access(self) -> bool:
        return True

    def get_output_extension(self) -> str:
        """Virtual filename extension presented to clients."""
        return "chd"

    def transform_read(self, source_file: BinaryIO, virtual_offset: int, length: int) -> bytes:
        """
        Read bytes from the cached CHD.

        Note: transfs.py open() preferentially calls get_prebuilt_path() to
        avoid loading the full CHD into memory.  This method exists for
        compatibility with the base Transform interface and is used when
        the pipeline is applied directly (e.g., unit tests).
        """
        source_path = getattr(source_file, "name", None)
        if not source_path:
            raise TransformError(
                "ChdTransform: cannot determine source path from file handle"
            )

        chd_path = self.get_prebuilt_path(source_path)
        if not chd_path:
            raise TransformError(
                f"ChdTransform: failed to build CHD for {source_path}"
            )

        with open(chd_path, "rb") as chd_file:
            chd_file.seek(virtual_offset)
            return chd_file.read(length)

    def metadata(self) -> dict:
        return {
            "type": "ChdTransform",
            "cache_dir": self.cache_dir,
            "chd_path": self._chd_path or "(not yet built)",
        }


TRANSFORM_PLUGINS = {
    "chd": ChdTransform,
}
