"""Foundation tests - Verify basic TransFS functionality and mount availability.

These tests ensure the core infrastructure is operational:
- Volume mounts are accessible (/mnt/transfs, /mnt/filestorefs)
- Expected client mappings (MiSTer, Retrobat) exist
- No unexpected additional files/directories at top level
- Client folders show ONLY configured systems (regression test for database mode)
- Filesystem structure is clean and organized

All other tests depend on these passing.
"""

import os
import logging
import pytest
from pathlib import Path
from uuid import uuid4
import yaml


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
    
    def test_only_expected_clients_at_toplevel(self):
        """Verify only expected client directories exist at top level of /mnt/transfs."""
        # List of supported emulation clients/platforms that should be available
        # Edit this list to match your configured clients in TransFS
        expected_clients = {
            "MiSTer",      # MiSTer FPGA emulator
            "RetroBat",    # RetroBat emulator suite
            "RetroPie",    # RetroPie emulator suite
            "Mame",        # MAME arcade emulator
            "Generic",     # Generic emulators
        }
        
        transfs_root = Path("/mnt/transfs")
        actual_items = {item.name for item in transfs_root.iterdir()}
        
        # All items should either be expected clients or hidden files/dirs
        for item_name in actual_items:
            if item_name.startswith("."):
                continue  # Allow hidden files
            assert item_name in expected_clients, \
                f"Unexpected top-level item in /mnt/transfs: {item_name}\nExpected: {expected_clients}"


class TestClientSystemMappings:
    """Test that client folders show ONLY configured systems (regression test for database mode bug).

    Validates that browsing a client folder (e.g., /mnt/transfs/MiSTer)
    only shows configured system names from clients.yaml.
    """

    @staticmethod
    def _load_clients_config():
        """Load the clients.yaml configuration."""
        config_path = Path("/app/config/clients.yaml")
        if not config_path.exists():
            pytest.skip(f"clients.yaml not found at {config_path}")

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return config

    def test_client_folders_show_configured_systems_only(self):
        """Verify each client folder shows exactly its configured systems, nothing more."""
        config = self._load_clients_config()

        transfs_root = Path("/mnt/transfs")

        for client_config in config.get("clients", []):
            client_name = client_config.get("name")
            client_systems = {s.get("name") for s in client_config.get("systems", [])}

            if not client_systems:
                continue  # Skip clients with no systems configured

            client_path = transfs_root / client_name
            if not client_path.exists():
                continue  # Skip clients that aren't mounted

            actual_entries = {
                entry.name for entry in client_path.iterdir()
                if not entry.name.startswith(".")
            }

            assert actual_entries == client_systems, (
                f"Client folder '{client_name}' has mismatched entries.\n"
                f"Expected systems (from config): {sorted(client_systems)}\n"
                f"Actual entries (from filesystem): {sorted(actual_entries)}\n"
                f"Missing: {sorted(client_systems - actual_entries)}\n"
                f"Extra (should not exist): {sorted(actual_entries - client_systems)}\n"
                "This suggests database mode or implicit file listing is active at the wrong hierarchy level."
            )

    def test_mister_systems_match_config(self):
        """Regression test: MiSTer should show systems, not thousands of files."""
        config = self._load_clients_config()

        mister_config = next(
            (c for c in config.get("clients", []) if c.get("name") == "MiSTer"),
            None
        )

        if not mister_config:
            pytest.skip("MiSTer not configured")

        configured_systems = {s.get("name") for s in mister_config.get("systems", [])}

        mister_path = Path("/mnt/transfs/MiSTer")
        assert mister_path.exists(), "MiSTer path does not exist"

        actual_entries = {
            entry.name for entry in mister_path.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        }

        assert len(actual_entries) < 100, (
            f"MiSTer has too many entries ({len(actual_entries)}). "
            "This suggests it's showing files instead of systems. "
            "Database mode may be active at wrong hierarchy level."
        )

        assert len(actual_entries) > 5, (
            f"MiSTer has suspiciously few entries ({len(actual_entries)}). "
            "Check if configuration is loaded correctly."
        )

        assert actual_entries == configured_systems, (
            "MiSTer systems don't match configuration.\n"
            f"Expected: {sorted(configured_systems)}\n"
            f"Actual: {sorted(actual_entries)}"
        )


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


class TestSourcefileAvailability:
    """Test that source files in /mnt/filestorefs are available and accessible."""
    
    def test_native_systems_directory_exists(self):
        """Verify Native systems directory exists in source."""
        native_path = Path("/mnt/filestorefs/Native")
        assert native_path.exists(), f"Native systems directory not found: {native_path}"
        assert native_path.is_dir(), f"Native path is not a directory: {native_path}"
    
    def test_native_has_content(self):
        """Verify Native systems directory contains system folders."""
        native_path = Path("/mnt/filestorefs/Native")
        systems = list(native_path.iterdir())
        system_dirs = [s for s in systems if s.is_dir() and not s.name.startswith(".")]
        
        assert len(system_dirs) > 0, \
            "Native systems directory is empty. No source files available for testing."


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


class TestWriteCapabilities:
    """Test write/delete behavior in configured writable folders."""

    @staticmethod
    def _write_and_cleanup(target_dir: Path, prefix: str):
        """Create a temp file, verify contents, then remove it."""
        from config import read_config
        from sourcepath import get_source_path_for_write

        target_dir.mkdir(parents=True, exist_ok=True)
        test_file = target_dir / f"{prefix}_{uuid4().hex}.tmp"
        payload = b"transfs-foundation-write-test"
        logger = logging.getLogger(__name__)

        config = read_config()
        resolved_path = get_source_path_for_write(logger, config, "/mnt/transfs", str(test_file))
        backend_file = Path(resolved_path) if resolved_path else None

        try:
            with open(test_file, "wb") as handle:
                handle.write(payload)

            transfs_exists = test_file.exists()
            backend_exists = backend_file.exists() if backend_file else False
            assert transfs_exists or backend_exists, (
                f"Test file was not created in either location:\n"
                f"TransFS path: {test_file}\n"
                f"Backend path: {backend_file}"
            )

            read_target = test_file if transfs_exists else backend_file
            with open(read_target, "rb") as handle:
                read_back = handle.read()
            assert read_back == payload, f"Unexpected file contents for {read_target}"
        finally:
            if test_file.exists():
                test_file.unlink()
            if backend_file and backend_file.exists():
                backend_file.unlink()

        assert not test_file.exists(), f"Test file was not removed from TransFS path: {test_file}"
        if backend_file:
            assert not backend_file.exists(), f"Test file was not removed from backend path: {backend_file}"

    def test_can_write_and_cleanup_retrobat_bios_folder(self):
        """Verify write/delete in RetroBat BIOS folder."""
        candidates = [
            Path("/mnt/transfs/RetroBat/bios"),
            Path("/mnt/transfs/Retrobat/bios"),
        ]
        target_dir = next((path for path in candidates if path.exists()), None)
        if target_dir is None:
            pytest.skip("RetroBat BIOS folder not present in this environment")

        self._write_and_cleanup(target_dir, "retrobat_bios")

    def test_can_write_and_cleanup_mister_archimedes_folder(self):
        """Verify write/delete in MiSTer Archimedes folder."""
        candidates = [
            Path("/mnt/transfs/MiSTer/Archie"),
            Path("/mnt/transfs/MiSTer/Archimedes"),
        ]
        target_dir = next((path for path in candidates if path.exists()), None)
        assert target_dir is not None, "MiSTer Archimedes folder not present in TransFS mount"

        self._write_and_cleanup(target_dir, "mister_archimedes")
