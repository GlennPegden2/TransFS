"""Foundation tests - Verify basic TransFS functionality and mount availability.

These tests ensure the core infrastructure is operational:
- Volume mounts are accessible (/mnt/transfs, /mnt/filestorefs)
- Expected client mappings (MiSTer, Retrobat) exist
- Filesystem structure is clean and organized

All other tests depend on these passing.
"""

import os
import pytest
from pathlib import Path
from typing import List, Set


class TestVolumeMounts:
    """Test that required FUSE volumes are mounted and accessible."""
    
    def test_transfs_volume_mounted(self):
        """Verify /mnt/transfs is mounted and accessible."""
        assert Path("/mnt/transfs").exists(), "/mnt/transfs not found"
        assert Path("/mnt/transfs").is_dir(), "/mnt/transfs is not a directory"
        # Try to list contents to verify it's actually mounted
        contents = list(Path("/mnt/transfs").iterdir())
        assert len(contents) > 0, "/mnt/transfs is empty or not accessible"
    
    def test_filestorefs_volume_mounted(self):
        """Verify /mnt/filestorefs is mounted and accessible."""
        assert Path("/mnt/filestorefs").exists(), "/mnt/filestorefs not found"
        assert Path("/mnt/filestorefs").is_dir(), "/mnt/filestorefs is not a directory"
        # Try to list contents to verify it's actually mounted
        contents = list(Path("/mnt/filestorefs").iterdir())
        assert len(contents) > 0, "/mnt/filestorefs is empty or not accessible"


class TestClientMappings:
    """Test that client mappings (MiSTer, Retrobat, etc.) exist in TransFS mount."""
    
    def test_mister_client_exists(self):
        """Verify MiSTer client mapping exists."""
        mister_path = Path("/mnt/transfs/MiSTer")
        assert mister_path.exists(), f"MiSTer client mapping not found at {mister_path}"
        assert mister_path.is_dir(), f"MiSTer path is not a directory: {mister_path}"
    
    def test_retrobat_client_exists(self):
        """Verify Retrobat client mapping exists (if configured)."""
        retrobat_path = Path("/mnt/transfs/Retrobat")
        # Retrobat is optional, but if it exists, it should be a directory
        if retrobat_path.exists():
            assert retrobat_path.is_dir(), f"Retrobat path is not a directory: {retrobat_path}"


class TestMiSTerStructure:
    """Test MiSTer client structure and system mappings."""
    
    def test_mister_has_systems(self):
        """Verify MiSTer has at least some system mappings."""
        mister_path = Path("/mnt/transfs/MiSTer")
        systems = list(mister_path.iterdir())
        
        # Filter out hidden items and files (should only have directories)
        system_dirs = [s for s in systems if s.is_dir() and not s.name.startswith(".")]
        
        assert len(system_dirs) > 0, \
            "MiSTer client has no system mappings. Check if TransFS is running and configured correctly."


class TestFileAccessibility:
    """Test that files are accessible and readable from TransFS mount."""
    
    def test_file_readable_from_transfs(self):
        """Verify that files in TransFS can be read (not just listed)."""
        # Find a file in MiSTer/Amstrad/CPC
        cpc_path = Path("/mnt/transfs/MiSTer/Amstrad/CPC")
        
        # Try to find and read a BIOS file or similar
        boot_rom = cpc_path / "boot.rom"
        if boot_rom.exists():
            assert boot_rom.is_file(), f"boot.rom is not a file: {boot_rom}"
            assert os.access(boot_rom, os.R_OK), f"boot.rom is not readable: {boot_rom}"
            
            # Try to read a few bytes to verify it's really accessible
            try:
                with open(boot_rom, "rb") as f:
                    data = f.read(8)
                    assert len(data) == 8, f"Failed to read 8 bytes from {boot_rom}"
            except Exception as e:
                pytest.fail(f"Failed to read from {boot_rom}: {e}")
