"""
Background cache warmer for TransFS.

Monitors system idle state and proactively warms the getattr cache
by walking virtual filesystem paths when CPU and I/O are low.
"""

import os
import time
import threading
import logging
from collections import deque
from typing import Optional, Callable

logger = logging.getLogger(__name__)

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available - cache warmer will use simplified idle detection")


class CacheWarmer:
    """Background thread that warms cache during idle periods."""

    def __init__(
        self,
        mount_point: str,
        readdir_func: Callable,
        config: Optional[dict] = None
    ):
        """
        Initialize cache warmer.

        Args:
            mount_point: Virtual filesystem mount point (e.g., /mnt/transfs)
            readdir_func: Function to call for directory listing (warms cache as side effect)
            config: Configuration dict with keys:
                - enabled: bool (default True)
                - check_interval_seconds: int (default 10)
                - cpu_threshold_percent: float (default 20.0)
                - io_threshold_percent: float (default 20.0)
                - max_depth: int (default 8)
                - batch_size: int (default 3 paths per idle check)
        """
        self.mount_point = mount_point
        self.readdir_func = readdir_func

        # Load configuration
        cfg = config or {}
        self.enabled = cfg.get("enabled", True)
        self.check_interval = cfg.get("check_interval_seconds", 10)
        self.cpu_threshold = cfg.get("cpu_threshold_percent", 20.0)
        self.io_threshold = cfg.get("io_threshold_percent", 20.0)
        self.max_depth = cfg.get("max_depth", 8)
        self.batch_size = cfg.get("batch_size", 3)

        # State tracking
        self.queue = deque()  # Paths to warm, with (path, depth) tuples
        self.warmed = set()  # Paths already warmed
        self.running = False
        self.thread = None

        # Idle detection state
        self.last_io_counters = None

    def is_system_idle(self) -> bool:
        """Check if system CPU and I/O are below thresholds."""
        if not PSUTIL_AVAILABLE:
            # Fallback: assume idle if no error
            return True

        try:
            # Check CPU usage (average over short interval)
            cpu_percent = psutil.cpu_percent(interval=0.1)
            if cpu_percent > self.cpu_threshold:
                return False

            # Check I/O activity (compare to last check)
            io_counters = psutil.disk_io_counters()
            if io_counters and self.last_io_counters:
                # Calculate bytes/sec since last check
                read_bytes = io_counters.read_bytes - self.last_io_counters.read_bytes
                write_bytes = io_counters.write_bytes - self.last_io_counters.write_bytes
                total_bytes = read_bytes + write_bytes

                # Convert to MB/s
                mb_per_sec = total_bytes / (1024 * 1024 * self.check_interval)

                # Rough heuristic: >10 MB/s = active I/O
                if mb_per_sec > 10:
                    self.last_io_counters = io_counters
                    return False

            self.last_io_counters = io_counters
            return True

        except Exception as e:
            logger.debug(f"Idle check failed: {e}")
            return False

    def populate_initial_queue(self):
        """Populate queue with client roots to start warming."""
        try:
            # List client directories at mount point root
            for entry in os.scandir(self.mount_point):
                if entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
                    path = entry.path
                    if path not in self.warmed:
                        self.queue.append((path, 1))
                        logger.info(f"Cache warmer: queued {path}")
        except Exception as e:
            logger.warning(f"Cache warmer: failed to populate initial queue: {e}")

    def warm_path(self, path: str, depth: int):
        """
        Warm cache for a single path and queue its children.
        Also pre-populates attribute cache for all files encountered.

        Args:
            path: Filesystem path to warm
            depth: Current depth (for max_depth limit)
        """
        try:
            # Mark as warmed
            self.warmed.add(path)

            # Only scandir if this is a directory
            if not os.path.isdir(path):
                logger.debug(f"Cache warmer: skipped {path} (not a directory)")
                return

            # Call readdir to warm cache (this is the actual cache warming)
            entries = list(os.scandir(path))
            logger.debug(f"Cache warmer: warmed {path} ({len(entries)} entries)")
            
            # NOTE: Attribute caching disabled in cache warmer to avoid threading conflicts
            # The readdir operation in the main FUSE loop will populate the cache when files are accessed

            # Queue child directories if not at max depth
            if depth < self.max_depth:
                for entry in entries:
                    if entry.is_dir(follow_symlinks=False):
                        child_path = entry.path
                        if child_path not in self.warmed and child_path not in [p for p, _ in self.queue]:
                            self.queue.append((child_path, depth + 1))

        except PermissionError:
            logger.debug(f"Cache warmer: permission denied for {path}")
        except FileNotFoundError:
            logger.debug(f"Cache warmer: path not found {path}")
        except Exception as e:
            logger.warning(f"Cache warmer: error warming {path}: {e}")

    def run_loop(self):
        """Main background thread loop."""
        logger.info("Cache warmer: thread started")

        # Populate initial queue
        self.populate_initial_queue()

        while self.running:
            try:
                # Sleep for check interval
                time.sleep(self.check_interval)

                # Check if system is idle
                if not self.is_system_idle():
                    logger.debug("Cache warmer: system busy, skipping")
                    continue

                # Warm a batch of paths
                warmed_count = 0
                while warmed_count < self.batch_size and self.queue:
                    path, depth = self.queue.popleft()
                    if path not in self.warmed:
                        self.warm_path(path, depth)
                        warmed_count += 1

                if warmed_count > 0:
                    logger.info(f"Cache warmer: warmed {warmed_count} paths, {len(self.queue)} remaining in queue")

            except Exception as e:
                logger.error(f"Cache warmer: error in run loop: {e}", exc_info=True)

        logger.info("Cache warmer: thread stopped")

    def start(self):
        """Start the background cache warmer thread."""
        if not self.enabled:
            logger.info("Cache warmer: disabled in configuration")
            return

        # Safety guard: avoid scanning the mounted FUSE path from inside the same process.
        # This can lead to deadlocks/hangs if the filesystem implementation re-enters itself.
        if os.getenv("TRANSFS_ALLOW_MOUNT_WARMER", "0") != "1":
            logger.warning(
                "Cache warmer disabled: mount scan is unsafe in-process. "
                "Set TRANSFS_ALLOW_MOUNT_WARMER=1 to override."
            )
            return

        if self.running:
            logger.warning("Cache warmer: already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self.run_loop, daemon=True, name="CacheWarmer")
        self.thread.start()
        logger.info("Cache warmer: started")

    def stop(self):
        """Stop the background cache warmer thread."""
        if not self.running:
            return

        logger.info("Cache warmer: stopping...")
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Cache warmer: stopped")
