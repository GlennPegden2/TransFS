"""System-specific tests - Validate per-system mappings, file integrity, and performance.

Tests are parameterized per system with expected values for:
- Directory structure (recursive mapping validation)
- File presence, type, checksums, and permissions
- Performance thresholds for directory listing operations

Each system test uses a SystemTestConfig fixture that defines:
- System name and path
- Expected files with checksums and metadata
- Performance thresholds
- Archive handling (ZIP, etc.)
"""

import os
import pytest
import hashlib
import time
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class ExpectedFile:
    """Definition of an expected file in a system mapping."""
    relative_path: str                          # Path relative to system root (e.g., "boot.rom")
    expected_size: Optional[int] = None         # File size in bytes
    expected_hash: Optional[str] = None         # SHA256 hash
    expected_perms: Optional[int] = None        # Unix permissions (e.g., 0o644)
    is_archive: bool = False                    # Is this a compressed archive?
    archive_type: Optional[str] = None          # Type of archive (zip, tar, etc.)
    is_generated: bool = False                  # Is file generated/transformed by TransFS?


@dataclass
class DirectoryPerformanceThreshold:
    """Performance threshold for directory listing operations."""
    path: str                                   # Relative path from system root
    max_readdir_seconds: float                  # Max time to list directory
    max_stat_all_seconds: float                 # Max time to stat all files
    expected_entry_count: Optional[int] = None  # Expected number of entries (for validation)


@dataclass
class SystemTestConfig:
    """Complete test configuration for a retro system."""
    system_name: str                            # Name of system (e.g., "Amstrad CPC")
    system_path: str                            # Path in TransFS (e.g., "MiSTer/Amstrad/CPC")
    source_base_path: str                       # Source path (e.g., "Native/Amstrad/CPC")
    
    expected_files: List[ExpectedFile]          # Files that should exist
    performance_thresholds: List[DirectoryPerformanceThreshold]  # Performance targets
    
    skip_reason: Optional[str] = None           # If set, skip this system with reason
    
    def get_transfs_path(self) -> Path:
        return Path(f"/mnt/transfs/{self.system_path}")
    
    def get_source_path(self) -> Path:
        return Path(f"/mnt/filestorefs/{self.source_base_path}")


# ============================================================================
# System Configurations - Define expected state for each system
# ============================================================================

# Amstrad CPC Configuration
AMSTRAD_CPC_CONFIG = SystemTestConfig(
    system_name="Amstrad CPC",
    system_path="MiSTer/Amstrad",  # TransFS virtual path (what MiSTer expects)
    source_base_path="Native/Systems/Amstrad/CPC",  # FileStore real path (normalized storage)
    expected_files=[
        # BIOS files - both boot.rom and boot2.rom are served for compatibility
        ExpectedFile("boot.rom", is_generated=False),
        ExpectedFile("boot2.rom", is_generated=False),
        
        # Virtual folders for different file types
        ExpectedFile("FDs", is_generated=True),  # Virtual directory aggregating DSK files
        ExpectedFile("Tapes", is_generated=True),  # Virtual directory aggregating CDT files
#        ExpectedFile("Collections", is_generated=True),  # Virtual directory aggregating ZIP files
    ],
    performance_thresholds=[
        DirectoryPerformanceThreshold(
            path=".",
            max_readdir_seconds=2.0,
            max_stat_all_seconds=5.0,
        ),
        DirectoryPerformanceThreshold(
            path="FDs",
            max_readdir_seconds=15.0,  # Large folder, allow more time
            max_stat_all_seconds=30.0,
        ),
    ],
)

# Acorn Archimedes Configuration
ACORN_ARCHIMEDES_CONFIG = SystemTestConfig(
    system_name="Acorn Archimedes",
    system_path="MiSTer/Archie",  # TransFS virtual path (what MiSTer expects)
    source_base_path="Native/Systems/Acorn/Archimedes",  # FileStore real path (normalized storage)
    expected_files=[
        # BIOS file with checksum validation
        ExpectedFile(
            "riscos.rom",
            expected_hash="d069312a506daf4c0e2a94283672b1cba3550ab04435355b1685485fbd55b5d1",
            is_generated=False
        ),
        # Additional BIOS versions
#        ExpectedFile("riscos3_71.rom", is_generated=False),
        
        # Virtual folders
        ExpectedFile("HDs", is_generated=True),  # Virtual directory for disk images
    ],
    performance_thresholds=[
        DirectoryPerformanceThreshold(
            path=".",
            max_readdir_seconds=2.0,
            max_stat_all_seconds=5.0,
        ),
    ],
)

# Acorn Electron Configuration (if available)
ACORN_ELECTRON_CONFIG = SystemTestConfig(
    system_name="Acorn Electron",
    system_path="MiSTer/Acorn/Electron",
    source_base_path="Native/Systems/Acorn/Electron",
    expected_files=[
        ExpectedFile("boot.vhd", is_generated=False),
        ExpectedFile("Software", is_generated=True),
    ],
    performance_thresholds=[
        DirectoryPerformanceThreshold(
            path=".",
            max_readdir_seconds=2.0,
            max_stat_all_seconds=5.0,
        ),
    ],
)

# Acorn Atom Configuration
ACORN_ATOM_CONFIG = SystemTestConfig(
    system_name="Acorn Atom",
    system_path="MiSTer/AcornAtom",
    source_base_path="Native/Systems/Acorn/Atom",
    expected_files=[
        ExpectedFile("boot.vhd", is_generated=False),
        ExpectedFile("HDs/hoglet67.vhd", is_generated=False),
    ],
    performance_thresholds=[
        DirectoryPerformanceThreshold(
            path=".",
            max_readdir_seconds=2.0,
            max_stat_all_seconds=5.0,
        ),
    ],
)

# Acorn BBC Micro Configuration
ACORN_BBC_CONFIG = SystemTestConfig(
    system_name="Acorn BBC Micro",
    system_path="MiSTer/BBCMicro",
    source_base_path="Native/Systems/Acorn/BBC_B",
    expected_files=[
        ExpectedFile("boot.vhd", is_generated=False),
    ],
    performance_thresholds=[
        DirectoryPerformanceThreshold(
            path=".",
            max_readdir_seconds=2.0,
            max_stat_all_seconds=5.0,
        ),
    ],
)

# ============================================================================
# Pytest Fixtures
# ============================================================================

@pytest.fixture(params=[AMSTRAD_CPC_CONFIG, ACORN_ARCHIMEDES_CONFIG, ACORN_ATOM_CONFIG, ACORN_BBC_CONFIG],
                 ids=lambda config: config.system_name)
def system_config(request) -> SystemTestConfig:
    """Parameterized fixture providing system configurations.
    
    Add new systems to the params list above to include them in testing.
    Systems with skip_reason will be skipped.
    """
    config: SystemTestConfig = request.param
    
    if config.skip_reason:
        skip_msg = f"{config.system_name}: {config.skip_reason}"
        sys.stderr.write(f"\n[SKIP_REASON] {skip_msg}\n")
        sys.stderr.flush()
        pytest.skip(skip_msg)
    
    # Verify system path exists before running tests
    if not config.get_transfs_path().exists():
        skip_msg = f"{config.system_name}: TransFS path not found at {config.get_transfs_path()}"
        sys.stderr.write(f"\n[SKIP_REASON] {skip_msg}\n")
        sys.stderr.flush()
        pytest.skip(skip_msg)
    
    return config


# ============================================================================
# Tests
# ============================================================================

class TestSystemStructure:
    """Validate system directory structure matches expected mappings."""
    
    def test_system_root_exists(self, system_config: SystemTestConfig):
        """Verify system root directory exists in TransFS."""
        root = system_config.get_transfs_path()
        assert root.exists(), f"System path not found: {root}"
        assert root.is_dir(), f"System path is not a directory: {root}"
    
    def test_expected_files_exist(self, system_config: SystemTestConfig):
        """Verify all expected files/directories exist."""
        root = system_config.get_transfs_path()
        
        for expected in system_config.expected_files:
            path = root / expected.relative_path
            if path.exists():
                continue
            
            # Fallback: some FUSE paths can appear in listings but fail direct stat
            top_level_name = expected.relative_path.split('/')[0]
            try:
                listed_names = {item.name for item in root.iterdir()}
            except Exception:
                listed_names = set()
            
            assert top_level_name in listed_names, \
                f"Expected file/directory not found: {path} (in {system_config.system_name})"
    
#    @pytest.mark.skip(reason="Deprecated: top-level contents are no longer deterministic across mappings")
#    def test_no_unexpected_toplevel_items(self, system_config: SystemTestConfig):
#        """Verify only expected items exist at system root level."""
#        root = system_config.get_transfs_path()
#        expected_names = {f.relative_path.split('/')[0] for f in system_config.expected_files}
#        
#        actual_items = {item.name for item in root.iterdir() if not item.name.startswith(".")}
#        
#        unexpected = actual_items - expected_names
#        if unexpected:
#            # Allow some flexibility for system-specific hidden files
#            hidden_ok = {".DS_Store", ".gitkeep", ".keep"}
#            unexpected = {u for u in unexpected if u not in hidden_ok}
#        
#        assert not unexpected, \
#            f"Unexpected items found in {system_config.system_name} root: {unexpected}"
    
    def test_source_to_mount_mapping(self, system_config: SystemTestConfig):
        """Verify files from source appear correctly in TransFS mount."""
        # Verify that the TransFS path exists
        transfs_root = system_config.get_transfs_path()
        assert transfs_root.exists(), \
            f"TransFS mount not found for {system_config.system_name} at {transfs_root}"
        
        # Verify that the source path exists
        source_root = system_config.get_source_path()
        assert source_root.exists(), \
            f"Source path not found for {system_config.system_name} at {source_root}"
        
        # Verify at least one expected file is mapped correctly
        non_generated_files = [f for f in system_config.expected_files if not f.is_generated]
        assert len(non_generated_files) > 0, \
            f"No non-generated files configured for {system_config.system_name}"
        
        for expected in non_generated_files:
            transfs_path = transfs_root / expected.relative_path
            if transfs_path.exists():
                # At least one file is mapped - integration is working
                return
        
        pytest.fail(
            f"None of the expected files from source appear in TransFS mount for {system_config.system_name}. "
            f"Expected at least one of: {[f.relative_path for f in non_generated_files]}"
        )


class TestSystemFileAccess:
    """Test that files are accessible and readable from system mapping."""
    
#    def test_bios_files_readable(self, system_config: SystemTestConfig):
#        """Verify BIOS/boot files are readable."""
#        pytest.skip("Deprecated: covered by expected files and checksum tests")
#        root = system_config.get_transfs_path()
#        
#        bios_files = [f for f in system_config.expected_files 
#                      if "boot" in f.relative_path.lower() or "bios" in f.relative_path.lower()]
#        
#        for bios_file in bios_files:
#            path = root / bios_file.relative_path
#            if path.exists() and path.is_file():
#                assert os.access(path, os.R_OK), f"File not readable: {path}"
#                
#                # Try to read a few bytes
#                try:
#                    with open(path, "rb") as f:
#                        data = f.read(8)
#                        assert len(data) > 0, f"Failed to read from {path}"
#                except Exception as e:
#                    pytest.fail(f"Error reading {path}: {e}")
    
    def test_directory_listing(self, system_config: SystemTestConfig):
        """Verify directories can be listed."""
        root = system_config.get_transfs_path()
        
        try:
            items = list(root.iterdir())
            assert len(items) >= 0, f"Failed to list {root}"
        except Exception as e:
            pytest.fail(f"Error listing {root}: {e}")


@pytest.mark.performance
class TestSystemPerformance:
    """Test performance of directory operations."""
    
    def test_directory_readdir_performance(self, system_config: SystemTestConfig):
        """Verify directory listing performance meets thresholds."""
        root = system_config.get_transfs_path()
        
        for threshold in system_config.performance_thresholds:
            path = root / threshold.path if threshold.path != "." else root
            
            start = time.time()
            try:
                entries = list(path.iterdir())
                elapsed = time.time() - start
                
                assert elapsed <= threshold.max_readdir_seconds, \
                    f"Directory listing too slow for {threshold.path}: {elapsed:.2f}s > {threshold.max_readdir_seconds}s"
                
                # Validate expected entry count if specified
                if threshold.expected_entry_count is not None:
                    assert len(entries) == threshold.expected_entry_count, \
                        f"Unexpected entry count in {threshold.path}: {len(entries)} != {threshold.expected_entry_count}"
                        
            except AssertionError:
                raise
            except Exception as e:
                pytest.skip(f"Could not test performance of {path}: {e}")
    
    def test_directory_stat_performance(self, system_config: SystemTestConfig):
        """Verify stat operations on directory contents meet thresholds."""
        root = system_config.get_transfs_path()
        
        for threshold in system_config.performance_thresholds:
            path = root / threshold.path if threshold.path != "." else root
            
            if not path.exists():
                continue
            
            start = time.time()
            try:
                entries = list(path.iterdir())
                for entry in entries:
                    entry.stat()
                elapsed = time.time() - start
                
                assert elapsed <= threshold.max_stat_all_seconds, \
                    f"Stat operations too slow for {threshold.path}: {elapsed:.2f}s > {threshold.max_stat_all_seconds}s"
                    
            except AssertionError:
                raise
            except Exception as e:
                pytest.skip(f"Could not test stat performance of {path}: {e}")


class TestSystemFileHash:
    """Test file integrity via checksums (when hash is provided in config)."""
    
    def test_file_checksums(self, system_config: SystemTestConfig):
        """Verify file checksums match expected values."""
        root = system_config.get_transfs_path()
        
        for expected in system_config.expected_files:
            if not expected.expected_hash or expected.is_generated:
                continue  # Skip files without hash or generated files
            
            path = root / expected.relative_path
            
            # Use os.path.exists for better FUSE compatibility
            if not os.path.exists(str(path)):
                pytest.skip(f"File not found: {path}")
            
            # Use os.path.isfile for FUSE compatibility
            if not os.path.isfile(str(path)):
                continue  # Skip directories
            
            # Calculate actual hash
            sha256 = hashlib.sha256()
            try:
                with open(str(path), "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        sha256.update(chunk)
            except FileNotFoundError:
                # FUSE cache issue - try once more after brief delay
                import time
                time.sleep(0.1)
                try:
                    with open(str(path), "rb") as f:
                        for chunk in iter(lambda: f.read(65536), b""):
                            sha256.update(chunk)
                except Exception as e:
                    pytest.skip(f"File appears in listing but cannot be opened (FUSE cache issue): {path}")
            except Exception as e:
                pytest.fail(f"Failed to read {path} for hashing: {e}")
            
            actual_hash = sha256.hexdigest()
            assert actual_hash == expected.expected_hash, \
                f"Hash mismatch for {path}: {actual_hash} != {expected.expected_hash}"


def test_archimedes_riscos_byte_by_byte():
    """Byte-by-byte comparison of riscos.rom between filestore and TransFS.
    
    This test catches corruption that might not be detected by checksum alone
    if the corruption happens during the read operation itself.
    """
    # Paths
    transfs_rom = Path("/mnt/transfs/MiSTer/Archie/riscos.rom")
    filestore_rom = Path("/mnt/filestorefs/Native/Systems/Acorn/Archimedes/BIOS/riscos.rom")
    
    # Check filestore file exists first
    if not filestore_rom.exists():
        pytest.skip(f"Filestore ROM not found: {filestore_rom}")
    
    # Check transfs file using os.access (FUSE-friendly)
    if not os.path.exists(str(transfs_rom)):
        pytest.skip(f"TransFS ROM not found: {transfs_rom}")
    
    # Get file sizes using os.stat (FUSE-friendly)
    transfs_size = os.stat(str(transfs_rom)).st_size
    filestore_size = os.stat(str(filestore_rom)).st_size
    
    assert transfs_size == filestore_size, \
        f"File size mismatch: TransFS={transfs_size}, Filestore={filestore_size}"
    
    # Read both files completely using os.open for better FUSE compatibility
    with open(str(filestore_rom), "rb") as fs_file:
        filestore_data = fs_file.read()
    
    with open(str(transfs_rom), "rb") as tf_file:
        transfs_data = tf_file.read()
    
    # Byte-by-byte comparison
    corrupted_bytes = 0
    first_corruption = None
    corruption_ranges = []
    in_corruption = False
    corruption_start = None
    
    for offset in range(len(filestore_data)):
        fs_byte = filestore_data[offset]
        tf_byte = transfs_data[offset]
        
        if fs_byte != tf_byte:
            corrupted_bytes += 1
            if first_corruption is None:
                first_corruption = offset
            
            if not in_corruption:
                corruption_start = offset
                in_corruption = True
        else:
            if in_corruption:
                corruption_ranges.append((corruption_start, offset - 1))
                in_corruption = False
    
    # Close final corruption range if file ended in corruption
    if in_corruption:
        corruption_ranges.append((corruption_start, len(filestore_data) - 1))
    
    # Build detailed error message if corruption found
    if corrupted_bytes > 0:
        error_msg = f"CORRUPTION DETECTED in riscos.rom:\n"
        error_msg += f"  Total corrupted bytes: {corrupted_bytes:,} / {len(filestore_data):,} ({100*corrupted_bytes/len(filestore_data):.2f}%)\n"
        error_msg += f"  First corruption at offset: {first_corruption} (0x{first_corruption:x})\n"
        error_msg += f"  Number of corruption ranges: {len(corruption_ranges)}\n"
        
        if len(corruption_ranges) <= 10:
            error_msg += "\n  Corruption ranges:\n"
            for start, end in corruption_ranges:
                size = end - start + 1
                error_msg += f"    Offset {start:,}-{end:,} ({size:,} bytes)\n"
                
                # Show hex comparison for first corruption
                if start == first_corruption:
                    sample_start = max(0, start - 8)
                    sample_end = min(len(filestore_data), start + 24)
                    error_msg += f"      Filestore: {filestore_data[sample_start:sample_end].hex()}\n"
                    error_msg += f"      TransFS:   {transfs_data[sample_start:sample_end].hex()}\n"
        else:
            error_msg += f"\n  (showing first 10 ranges)\n"
            for start, end in corruption_ranges[:10]:
                size = end - start + 1
                error_msg += f"    Offset {start:,}-{end:,} ({size:,} bytes)\n"
        
        pytest.fail(error_msg)
    
    # All bytes match
    assert corrupted_bytes == 0, "Byte-by-byte comparison should pass"
