"""
Snapshot tests for TransFS filesystem structure.

These tests capture the current state of the TransFS virtual filesystem
and compare it against saved snapshots. If the structure changes unexpectedly,
the tests will fail, helping catch breaking changes.

PERFORMANCE NOTE:
The filesystem_walker fixture samples only the first 20 entries per directory
by default (via max_entries_per_dir parameter). This prevents slowdowns when
testing directories containing thousands of ZIP files in hierarchical mode.
The sampling is deterministic (sorted order), so tests remain reproducible.

To test full directories without sampling, pass max_entries_per_dir=None:
    state = filesystem_walker(path, max_entries_per_dir=None)

To update snapshots when you intentionally add new features:
    pytest --snapshot-update
"""

import pytest


class TestTransFSSnapshots:
    """Test suite for capturing TransFS filesystem snapshots."""
    
    def test_transfs_root_structure(self, transfs_volume, filesystem_walker, snapshot):
        """Verify the root structure of TransFS mount hasn't changed unexpectedly.
        
        This test captures:
        - Top-level directories
        - Top-level files
        - Overall structure (without deep traversal)
        """
        if not transfs_volume.exists():
            pytest.skip("TransFS volume not mounted - ensure Docker container is running")
        
        state = filesystem_walker(transfs_volume, max_depth=2, include_metadata=False)
        
        # Use syrupy to snapshot the state
        assert state == snapshot
    
    def test_transfs_directory_counts(self, transfs_volume, filesystem_walker, snapshot):
        """Verify that directory and file counts remain stable.
        
        Catches breaking changes where files/directories are accidentally removed.
        
        NOTE: This test uses sampling (max_entries_per_dir=10) AND max_depth=4 to avoid
        performance issues with large directories containing thousands of ZIP files.
        The counts represent sampled data at limited depth. This is intentional for test speed.
        """
        if not transfs_volume.exists():
            pytest.skip("TransFS volume not mounted")
        
        # Use default sampling (10 entries per dir) and limit depth for performance
        state = filesystem_walker(transfs_volume, max_depth=4, include_metadata=False)
        
        counts = {
            "sampled": state.get("sampled", True),  # Track if sampling was used
            "total_directories": len(state["directories"]),
            "total_files": len(state["files"]),
            "directory_list": sorted(state["directories"]),
            "file_list": sorted(state["files"])
        }
        
        assert counts == snapshot
    
    @pytest.mark.parametrize("system_path", [
        "Native/Acorn/Archimedes",
        "Native/Acorn/Atom",
        "Native/Acorn/Electron",
        "Native/Amstrad/CPC",
        "Native/Amstrad/PCW",
        "Native/MITS/Altair8800",
        "Native/Tandy/MC-10",
    ])
    def test_system_specific_structure(self, transfs_volume, system_path, 
                                       filesystem_walker, snapshot):
        """Test individual system directory structures.
        
        This creates a separate snapshot for each system, making it easy to see
        which system broke when a test fails.
        
        Uses max_depth=3 to avoid deep recursion into large ZIP collections.
        """
        full_path = transfs_volume / system_path
        
        if not full_path.exists():
            pytest.skip(f"System path {system_path} not found")
        
        state = filesystem_walker(full_path, max_depth=3, include_metadata=False)
        assert state == snapshot
    
    def test_filestore_unchanged(self, filestore_volume, filesystem_walker, snapshot):
        """Verify that the source filestore content hasn't changed.
        
        This is a control test - if this fails, your source content changed,
        not TransFS behavior.
        """
        if not filestore_volume.exists():
            pytest.skip("Filestore volume not found")
        
        state = filesystem_walker(filestore_volume, max_depth=4, include_metadata=False)
        assert state == snapshot


class TestTransFSWithMetadata:
    """Tests that include file metadata for more detailed verification."""
    
    def test_virtual_file_extensions(self, transfs_volume, filesystem_walker, snapshot):
        """Verify that virtual file types/extensions remain consistent.
        
        Useful for catching changes in how files are transformed or exposed.
        """
        if not transfs_volume.exists():
            pytest.skip("TransFS volume not mounted")
        
        state = filesystem_walker(transfs_volume, include_metadata=True)
        
        # Extract just the extension information
        extensions = {}
        if state.get("metadata"):
            for file_path, metadata in state["metadata"].items():
                ext = metadata.get("extension", "")
                if ext not in extensions:
                    extensions[ext] = []
                extensions[ext].append(file_path)
        
        # Sort for consistent comparison
        for ext in extensions:
            extensions[ext] = sorted(extensions[ext])
        
        assert extensions == snapshot
    
    def test_symlink_detection(self, transfs_volume, filesystem_walker, snapshot):
        """Detect if any symlinks are created/removed in the virtual filesystem."""
        if not transfs_volume.exists():
            pytest.skip("TransFS volume not mounted")
        
        state = filesystem_walker(transfs_volume, include_metadata=True)
        
        symlinks = []
        if state.get("metadata"):
            symlinks = [
                path for path, meta in state["metadata"].items()
                if meta.get("is_symlink", False)
            ]
        
        assert sorted(symlinks) == snapshot


class TestComparativeAnalysis:
    """Tests that compare filestore vs transfs to detect transformation issues."""
    
    def test_file_count_ratio(self, filestore_volume, transfs_volume, 
                              filesystem_walker, snapshot):
        """Compare file counts between source and transformed filesystem.
        
        Large deviations might indicate issues with virtual file generation.
        """
        if not filestore_volume.exists() or not transfs_volume.exists():
            pytest.skip("Volumes not available")
        
        filestore_state = filesystem_walker(filestore_volume, include_metadata=False)
        transfs_state = filesystem_walker(transfs_volume, include_metadata=False)
        
        comparison = {
            "filestore_file_count": len(filestore_state["files"]),
            "filestore_dir_count": len(filestore_state["directories"]),
            "transfs_file_count": len(transfs_state["files"]),
            "transfs_dir_count": len(transfs_state["directories"]),
            "file_count_ratio": (
                len(transfs_state["files"]) / len(filestore_state["files"])
                if len(filestore_state["files"]) > 0 else 0
            ),
            "dir_count_ratio": (
                len(transfs_state["directories"]) / len(filestore_state["directories"])
                if len(filestore_state["directories"]) > 0 else 0
            )
        }
        
        assert comparison == snapshot


class TestRegressionDetection:
    """Tests specifically designed to catch common regression patterns."""
    
    def test_no_empty_directories_created(self, transfs_volume, filesystem_walker):
        """Ensure TransFS doesn't create unexpected empty directories."""
        if not transfs_volume.exists():
            pytest.skip("TransFS volume not mounted")
        
        state = filesystem_walker(transfs_volume, include_metadata=False)
        
        # Check for directories with no files or subdirectories
        empty_dirs = []
        for directory in state["directories"]:
            dir_path = transfs_volume / directory.rstrip("/")
            if dir_path.exists():
                contents = list(dir_path.iterdir())
                if not contents:
                    empty_dirs.append(directory)
        
        # It's OK to have some empty directories, but we should track them
        # If this list suddenly grows, something might be wrong
        assert len(empty_dirs) < 10, f"Found {len(empty_dirs)} empty directories: {empty_dirs}"
    
    def test_critical_files_present(self, transfs_volume):
        """Ensure critical configuration or system files are present.
        
        Add specific files that must always exist here.
        """
        if not transfs_volume.exists():
            pytest.skip("TransFS volume not mounted")
        
        critical_paths = [
            # Add paths to files that must always exist
            # Example: "Native/Acorn/Archimedes/Software/BIOS/riscos.rom"
        ]
        
        missing = []
        for path in critical_paths:
            if not (transfs_volume / path).exists():
                missing.append(path)
        
        assert not missing, f"Critical files missing: {missing}"
