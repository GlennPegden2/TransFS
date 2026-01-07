import pytest
import os
import time
import logging
from pathlib import Path
from typing import Dict, Optional

# Set up logging for performance tracking
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("test_performance")

# Detect if we're running inside Docker or on the host
IS_IN_DOCKER = os.path.exists("/.dockerenv") or os.environ.get("RUNNING_IN_DOCKER") == "1"

# Docker volume paths - different depending on where tests run
if IS_IN_DOCKER:
    # Running inside container - use container paths
    FILESTORE_VOLUME = Path("/mnt/filestorefs")
    TRANSFS_VOLUME = Path("/mnt/transfs")
    logger.info("Running tests INSIDE Docker container")
    logger.info(f"  FILESTORE_VOLUME: {FILESTORE_VOLUME}")
    logger.info(f"  TRANSFS_VOLUME: {TRANSFS_VOLUME}")
else:
    # Running on host - use host paths (may not work on Windows due to FUSE limitations)
    FILESTORE_VOLUME = Path("./content")
    TRANSFS_VOLUME = Path("./transfs")
    logger.warning("Running tests ON HOST - FUSE mount may not be accessible")
    logger.warning("  For accurate testing, run: ./run_tests_in_docker.ps1")
    logger.info(f"  FILESTORE_VOLUME: {FILESTORE_VOLUME}")
    logger.info(f"  TRANSFS_VOLUME: {TRANSFS_VOLUME}")

@pytest.fixture(scope="session")
def fuse_mount():
    """Path to the TransFS FUSE mount inside the container.
    
    When running tests inside the container, use this path.
    When running tests on the host, use transfs_volume fixture instead.
    """
    return "/mnt/transfs"

@pytest.fixture(scope="session")
def filestore_volume():
    """Path to the filestore volume accessible from host.
    
    This is the original content directory that TransFS reads from.
    """
    return FILESTORE_VOLUME

@pytest.fixture(scope="session")
def transfs_volume():
    """Path to the TransFS mount accessible from host via Docker volume.
    
    This is the transformed/virtual filesystem created by TransFS.
    Note: On Windows hosts, this may not work due to FUSE limitations.
    Consider running tests inside the container instead.
    """
    return TRANSFS_VOLUME

@pytest.fixture(scope="session")
def is_running_in_docker():
    """Detect if tests are running inside Docker container."""
    return IS_IN_DOCKER

@pytest.fixture
def filesystem_walker():
    """Factory fixture for walking and capturing filesystem state."""
    
    def walk_and_capture(root_path: Path, 
                         max_depth: Optional[int] = None,
                         include_metadata: bool = False,
                         max_entries_per_dir: Optional[int] = 10,
                         exclude_paths: Optional[list] = None) -> Dict:
        """Walk a directory tree and capture its structure.
        
        Args:
            root_path: Root directory to walk
            max_depth: Maximum depth to traverse (None = unlimited)
            include_metadata: Include file sizes, types, etc.
            max_entries_per_dir: Maximum entries to sample per directory (None = unlimited)
                                Useful for directories with thousands of files/ZIPs.
                                Default is 10 for fast testing.
            exclude_paths: List of path patterns to exclude (e.g., ['Amstrad/Tapes', 'Mame'])
                          Paths are relative to root_path
            
        Returns:
            Dictionary containing directory structure and metadata
        """
        start_time = time.time()
        exclude_paths = exclude_paths or []
        logger.info(f"Starting filesystem walk of: {root_path}")
        logger.info(f"  max_depth={max_depth}, max_entries_per_dir={max_entries_per_dir}")
        if exclude_paths:
            logger.info(f"  excluding paths: {exclude_paths}")
        
        result = {
            "root": str(root_path),
            "directories": [],
            "files": [],
            "metadata": {} if include_metadata else None,
            "sampled": max_entries_per_dir is not None  # Track if sampling was used
        }
        
        if not root_path.exists():
            result["error"] = "Path does not exist"
            logger.warning(f"Path does not exist: {root_path}")
            return result
        
        dir_count = 0
        file_count = 0
        
        for dirpath, dirnames, filenames in os.walk(root_path):
            dir_start = time.time()
            current_depth = len(Path(dirpath).relative_to(root_path).parts)
            
            if max_depth is not None and current_depth >= max_depth:
                dirnames.clear()  # Don't descend further
                continue
            
            rel_dir = os.path.relpath(dirpath, root_path)
            if rel_dir == ".":
                rel_dir = ""
            
            # Check if this directory itself should be excluded (skip it entirely)
            should_exclude = False
            for exclude_pattern in exclude_paths:
                if rel_dir.startswith(exclude_pattern) or rel_dir == exclude_pattern:
                    should_exclude = True
                    break
            
            if should_exclude:
                logger.info(f"Excluding directory: {rel_dir}")
                dirnames.clear()  # Don't descend into excluded paths
                continue
            
            # Filter out child directories that match exclusion patterns
            # This prevents os.walk from descending into them
            if dirnames and exclude_paths:
                original_dirnames = list(dirnames)
                dirnames[:] = [
                    d for d in dirnames 
                    if not any(
                        (os.path.join(rel_dir, d) if rel_dir else d).startswith(excl) or
                        (os.path.join(rel_dir, d) if rel_dir else d) == excl
                        for excl in exclude_paths
                    )
                ]
                excluded = set(original_dirnames) - set(dirnames)
                if excluded:
                    logger.info(f"Filtering excluded subdirectories from {rel_dir or '(root)'}: {excluded}")
            
            # Log directory processing
            dir_entry_count = len(dirnames) + len(filenames)
            if dir_entry_count > 100 or (time.time() - dir_start) > 0.5:
                logger.info(f"Processing directory: {rel_dir or '(root)'} ({len(dirnames)} dirs, {len(filenames)} files)")
            
            # Apply sampling limit to directories
            original_dirnames = sorted(dirnames)
            if max_entries_per_dir is not None and len(dirnames) > max_entries_per_dir:
                # Sample first N directories (sorted for consistency)
                dirnames[:] = original_dirnames[:max_entries_per_dir]
                logger.info(f"  Sampled {len(dirnames)} of {len(original_dirnames)} directories")
            else:
                dirnames[:] = original_dirnames
            
            # Add directories (only the ones we'll traverse)
            for dirname in dirnames:
                dir_rel_path = os.path.join(rel_dir, dirname) if rel_dir else dirname
                result["directories"].append(dir_rel_path + "/")
                dir_count += 1
            
            # Apply sampling limit to files
            sorted_filenames = sorted(filenames)
            if max_entries_per_dir is not None:
                sampled_files = sorted_filenames[:max_entries_per_dir]
                if len(sorted_filenames) > max_entries_per_dir:
                    logger.info(f"  Sampled {len(sampled_files)} of {len(sorted_filenames)} files")
            else:
                sampled_files = sorted_filenames
            
            # Add files
            for filename in sampled_files:
                file_start = time.time()
                file_rel_path = os.path.join(rel_dir, filename) if rel_dir else filename
                result["files"].append(file_rel_path)
                file_count += 1
                
                if include_metadata and result["metadata"] is not None:
                    file_full_path = Path(dirpath) / filename
                    try:
                        stat = file_full_path.stat()
                        result["metadata"][file_rel_path] = { # pylint: disable=unsupported-assignment-operation
                            "size": stat.st_size,
                            "is_symlink": file_full_path.is_symlink(),
                            "extension": file_full_path.suffix
                        }
                    except (OSError, PermissionError) as e:
                        result["metadata"][file_rel_path] = {"error": str(e)} # pylint: disable=unsupported-assignment-operation
                
                # Log slow file operations
                file_elapsed = time.time() - file_start
                if file_elapsed > 0.1:
                    logger.warning(f"  SLOW file operation ({file_elapsed:.2f}s): {file_rel_path}")
            
            # Log slow directory operations
            dir_elapsed = time.time() - dir_start
            if dir_elapsed > 1.0:
                logger.warning(f"SLOW directory ({dir_elapsed:.2f}s): {rel_dir or '(root)'} - {len(dirnames)} dirs, {len(sampled_files)} files")
        
        total_elapsed = time.time() - start_time
        logger.info(f"Completed walk in {total_elapsed:.2f}s: {dir_count} directories, {file_count} files")
        
        return result
    
    return walk_and_capture

@pytest.fixture
def filesystem_comparator():
    """Fixture for comparing filesystem states."""
    
    def compare_states(state1: Dict, state2: Dict) -> Dict:
        """Compare two filesystem states and return differences.
        
        Returns:
            Dictionary containing differences between the two states
        """
        try:
            from deepdiff import DeepDiff
        except ImportError:
            # Fallback to simple comparison if deepdiff not installed
            return {
                "has_changes": state1 != state2,
                "differences": "Install deepdiff for detailed comparison",
                "summary": {}
            }
        
        diff = DeepDiff(state1, state2, ignore_order=False)
        
        return {
            "has_changes": bool(diff),
            "differences": diff,
            "summary": {
                "directories_added": len(diff.get("iterable_item_added", {}).get("root['directories']", [])) if "iterable_item_added" in diff else 0,
                "directories_removed": len(diff.get("iterable_item_removed", {}).get("root['directories']", [])) if "iterable_item_removed" in diff else 0,
                "files_added": len(diff.get("iterable_item_added", {}).get("root['files']", [])) if "iterable_item_added" in diff else 0,
                "files_removed": len(diff.get("iterable_item_removed", {}).get("root['files']", [])) if "iterable_item_removed" in diff else 0,
            }
        }
    
    return compare_states