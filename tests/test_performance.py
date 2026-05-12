"""Performance tests for TransFS filesystem operations.

Tests directory listings and file attribute lookups for both small and large directories.
Ensures operations complete within acceptable time limits to prevent client timeouts.
"""

import pytest
import os
import time
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Performance thresholds (in seconds)
THRESHOLDS = {
    "small_dir_readdir": 1.0,      # < 100 files
    "medium_dir_readdir": 5.0,     # 100-1000 files
    "large_dir_readdir": 45.0,     # > 1000 files (current limitation)
    "small_dir_stat": 2.0,         # stat all files in small dir
    "medium_dir_stat": 10.0,       # stat all files in medium dir
    "large_dir_stat": 60.0,        # stat all files in large dir (current limitation)
}

def measure_operation(operation_name, func, *args, **kwargs):
    """Measure and log the time taken for an operation."""
    start = time.time()
    result = func(*args, **kwargs)
    elapsed = time.time() - start
    logger.info(f"PERFORMANCE: {operation_name} took {elapsed:.3f}s")
    return result, elapsed


class TestDirectoryListingPerformance:
    """Test readdir() performance across different directory sizes."""
    
    def test_small_directory_listing(self, fuse_mount):
        """Test listing a small directory (< 100 files)."""
        path = Path(fuse_mount) / "MiSTer" / "Acorn" / "Archimedes" / "Software" / "BIOS"
        
        if not path.exists():
            pytest.skip(f"Test path not found: {path}")
        
        entries, elapsed = measure_operation(
            "readdir(small_dir)",
            lambda: list(os.listdir(path))
        )
        
        assert len(entries) < 100, "Test expects small directory"
        assert elapsed < THRESHOLDS["small_dir_readdir"], \
            f"Small directory listing took {elapsed:.3f}s, expected < {THRESHOLDS['small_dir_readdir']}s"
        
        logger.info(f"  ✓ Listed {len(entries)} files in {elapsed:.3f}s")
    
    def test_large_directory_listing(self, fuse_mount):
        """Test listing a large directory (> 1000 files) - Amstrad Tapes."""
        path = Path(fuse_mount) / "MiSTer" / "Amstrad" / "Tapes"
        
        if not path.exists():
            pytest.skip(f"Test path not found: {path}")
        
        entries, elapsed = measure_operation(
            "readdir(large_dir)",
            lambda: list(os.listdir(path))
        )
        
        assert len(entries) > 1000, f"Test expects large directory, got {len(entries)} files"
        
        # Log warning if approaching timeout
        if elapsed > THRESHOLDS["large_dir_readdir"]:
            logger.warning(f"  ⚠ Large directory listing took {elapsed:.3f}s, exceeds {THRESHOLDS['large_dir_readdir']}s threshold")
            logger.warning(f"  ⚠ SMB clients may timeout! Consider optimization.")
        else:
            logger.info(f"  ✓ Listed {len(entries)} files in {elapsed:.3f}s")
        
        assert elapsed < THRESHOLDS["large_dir_readdir"] * 1.5, \
            f"Large directory listing took {elapsed:.3f}s, way too slow (limit: {THRESHOLDS['large_dir_readdir'] * 1.5}s)"


class TestFileAttributePerformance:
    """Test getattr() performance for stat operations."""
    
    def test_small_directory_stat_all(self, fuse_mount):
        """Test stat'ing all files in a small directory."""
        path = Path(fuse_mount) / "MiSTer" / "Acorn" / "Archimedes" / "Software" / "BIOS"
        
        if not path.exists():
            pytest.skip(f"Test path not found: {path}")
        
        def stat_all():
            stats = []
            for entry in os.listdir(path):
                stats.append(os.stat(path / entry))
            return stats
        
        stats, elapsed = measure_operation(
            "stat_all(small_dir)",
            stat_all
        )
        
        assert elapsed < THRESHOLDS["small_dir_stat"], \
            f"Small directory stat took {elapsed:.3f}s, expected < {THRESHOLDS['small_dir_stat']}s"
        
        logger.info(f"  ✓ Stat'd {len(stats)} files in {elapsed:.3f}s ({elapsed/len(stats)*1000:.1f}ms per file)")
    
    def test_large_directory_stat_all(self, fuse_mount):
        """Test stat'ing all files in a large directory (simulates ls -al)."""
        path = Path(fuse_mount) / "MiSTer" / "Amstrad" / "Tapes"
        
        if not path.exists():
            pytest.skip(f"Test path not found: {path}")
        
        def stat_all():
            stats = []
            for entry in os.listdir(path):
                stats.append(os.stat(path / entry))
            return stats
        
        stats, elapsed = measure_operation(
            "stat_all(large_dir)",
            stat_all
        )
        
        per_file_ms = elapsed / len(stats) * 1000
        
        if elapsed > THRESHOLDS["large_dir_stat"]:
            logger.warning(f"  ⚠ Large directory stat took {elapsed:.3f}s ({per_file_ms:.1f}ms per file)")
            logger.warning(f"  ⚠ Exceeds {THRESHOLDS['large_dir_stat']}s threshold - clients may timeout")
        else:
            logger.info(f"  ✓ Stat'd {len(stats)} files in {elapsed:.3f}s ({per_file_ms:.1f}ms per file)")
        
        assert elapsed < THRESHOLDS["large_dir_stat"] * 1.5, \
            f"Large directory stat took {elapsed:.3f}s, way too slow (limit: {THRESHOLDS['large_dir_stat'] * 1.5}s)"


class TestCacheEffectiveness:
    """Test that caching improves subsequent access performance."""
    
    def test_cached_readdir_performance(self, fuse_mount):
        """Test that second readdir() is faster due to caching."""
        path = Path(fuse_mount) / "MiSTer" / "Amstrad" / "Tapes"
        
        if not path.exists():
            pytest.skip(f"Test path not found: {path}")
        
        # First access (may be cache miss)
        _, first_time = measure_operation(
            "readdir(first_access)",
            lambda: list(os.listdir(path))
        )
        
        # Second access (should be cached)
        _, second_time = measure_operation(
            "readdir(second_access_cached)",
            lambda: list(os.listdir(path))
        )
        
        speedup = first_time / second_time if second_time > 0 else 1.0
        
        logger.info(f"  First access:  {first_time:.3f}s")
        logger.info(f"  Second access: {second_time:.3f}s (cache)")
        logger.info(f"  Speedup: {speedup:.1f}x")
        
        # Second access should be at least as fast (may not be faster if already cached)
        assert second_time <= first_time * 1.1, \
            f"Cached access ({second_time:.3f}s) slower than first ({first_time:.3f}s)"
    
    def test_cached_stat_performance(self, fuse_mount):
        """Test that repeated stat operations benefit from caching."""
        path = Path(fuse_mount) / "MiSTer" / "Amstrad" / "Tapes"
        
        if not path.exists():
            pytest.skip(f"Test path not found: {path}")
        
        entries = list(os.listdir(path))
        if len(entries) < 100:
            pytest.skip("Need large directory for cache test")
        
        # Take first 100 files for testing
        test_files = entries[:100]
        
        def stat_files():
            return [os.stat(path / f) for f in test_files]
        
        # First stat run
        _, first_time = measure_operation(
            "stat_100_files(first)",
            stat_files
        )
        
        # Second stat run (should be cached)
        _, second_time = measure_operation(
            "stat_100_files(cached)",
            stat_files
        )
        
        speedup = first_time / second_time if second_time > 0 else 1.0
        
        logger.info(f"  First run:  {first_time:.3f}s ({first_time/100*1000:.1f}ms per file)")
        logger.info(f"  Second run: {second_time:.3f}s ({second_time/100*1000:.1f}ms per file)")
        logger.info(f"  Speedup: {speedup:.1f}x")
        
        assert second_time <= first_time * 1.1, \
            f"Cached stat ({second_time:.3f}s) slower than first ({first_time:.3f}s)"


class TestWorstCaseScenarios:
    """Test extreme cases that might cause problems."""
    
    def test_ls_minus_al_simulation(self, fuse_mount):
        """Simulate 'ls -al' command on large directory (readdir + stat all)."""
        path = Path(fuse_mount) / "MiSTer" / "Amstrad" / "Tapes"
        
        if not path.exists():
            pytest.skip(f"Test path not found: {path}")
        
        def ls_al():
            # This is what 'ls -al' does:
            entries = os.listdir(path)  # readdir()
            stats = []
            for entry in entries:
                stats.append(os.stat(path / entry))  # getattr() for each
            return entries, stats
        
        (entries, stats), elapsed = measure_operation(
            "ls_al(large_dir)",
            ls_al
        )
        
        logger.info(f"  Files: {len(entries)}")
        logger.info(f"  Total time: {elapsed:.3f}s")
        logger.info(f"  Time per file: {elapsed/len(entries)*1000:.1f}ms")
        
        # This is the critical threshold - most SMB clients timeout at 60s
        SMB_TIMEOUT = 60.0
        
        if elapsed > SMB_TIMEOUT:
            logger.error(f"  ✗ CRITICAL: Operation took {elapsed:.3f}s, exceeds typical SMB timeout ({SMB_TIMEOUT}s)")
            logger.error(f"  ✗ Clients will experience failures!")
            pytest.fail(f"ls -al simulation took {elapsed:.3f}s, exceeds SMB timeout threshold")
        elif elapsed > SMB_TIMEOUT * 0.8:
            logger.warning(f"  ⚠ Operation took {elapsed:.3f}s, close to SMB timeout ({SMB_TIMEOUT}s)")
            logger.warning(f"  ⚠ Optimization recommended")
        else:
            logger.info(f"  ✓ Within acceptable limits ({elapsed:.3f}s < {SMB_TIMEOUT}s)")


@pytest.fixture(scope="session", autouse=True)
def performance_summary(request):
    """Print performance summary at the end of test run."""
    yield
    
    logger.info("\n" + "="*80)
    logger.info("PERFORMANCE TEST SUMMARY")
    logger.info("="*80)
    logger.info("Thresholds configured:")
    for key, value in THRESHOLDS.items():
        logger.info(f"  {key}: {value}s")
    logger.info("="*80)
