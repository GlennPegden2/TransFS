"""Foundation tests - Verify basic TransFS functionality and mount availability.

These tests ensure the core infrastructure is operational:
- Volume mounts are accessible (/mnt/transfs, /mnt/filestorefs)
- Expected client mappings (MiSTer, Retrobat) exist
- Client folders show ONLY configured systems (regression test for database mode)
- Filesystem structure is clean and organized

All other tests depend on these passing.
"""

import os
import sys
import logging
import hashlib
import tempfile
import pytest
from pathlib import Path
from uuid import uuid4
import yaml

# Allow importing from the app package when running inside the container
sys.path.insert(0, "/app")


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


class TestClientSystemMappings:
    """Test that client folders show ONLY configured systems (regression test for database mode bug).

    Validates that browsing a client folder (e.g., /mnt/transfs/MiSTer)
    only shows configured system names from clients.yaml.
    """

    @staticmethod
    def _load_clients_config():
        """Load the clients configuration using the modular config structure."""
        try:
            from config import read_clients_config
        except ImportError:
            pytest.skip("config module not importable")

        config_dir = "/app/config"
        if not os.path.isdir(config_dir):
            pytest.skip(f"Config directory not found at {config_dir}")

        return read_clients_config(config_dir=config_dir)

    def test_client_folders_show_configured_systems_only(self):
        """Verify each client folder shows exactly its configured systems, nothing more."""
        config = self._load_clients_config()

        transfs_root = Path("/mnt/transfs")

        for client_config in config.get("clients", []):
            client_name = client_config.get("name")
            client_systems = {s.get("name") for s in client_config.get("systems", [])}

            if not client_systems:
                continue  # Skip clients with no systems configured

            # Clients using category_paths have a different top-level layout (e.g. ROMS/)
            # rather than individual system names, so this check doesn't apply to them.
            if client_config.get("category_paths"):
                continue

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


@pytest.mark.slow
class TestSmbFoundation:
    """Foundation tests that exercise read/write/delete through Samba.
    
    WARNING: These tests are known to hang when run as part of a larger test suite.
    When working on other tests, skip SMB tests with: pytest -m "not slow"
    """

    SMB_HOST_CANDIDATES = ("127.0.0.1", "localhost", "transfs")
    SMB_PORT = 445
    SMB_SHARE = "TransFS"
    SMB_USER = "root"
    SMB_PASSWORD = "1"
    SMB_CLIENT_NAME = "transfs-pytest"
    SMB_SERVER_NAME = "TRANSFS"

    @classmethod
    def _connect(cls):
        try:
            import smbclient
        except ImportError:
            pytest.skip("smbprotocol/smbclient not installed in test environment")

        last_error = None
        for host in cls.SMB_HOST_CANDIDATES:
            try:
                # Clean up any existing session first
                try:
                    smbclient.delete_session(host)
                except Exception:
                    pass
                
                smbclient.register_session(
                    host,
                    username=cls.SMB_USER,
                    password=cls.SMB_PASSWORD,
                    port=cls.SMB_PORT,
                )
                smbclient.listdir(f"\\\\{host}\\{cls.SMB_SHARE}")
                return smbclient, host
            except Exception as error:
                last_error = error
                # Try to clean up any partial session
                try:
                    smbclient.delete_session(host)
                except Exception:
                    pass

        pytest.fail(
            "Unable to connect to Samba for foundation tests via "
            f"{cls.SMB_HOST_CANDIDATES}: {last_error}"
        )

    @classmethod
    def _assert_remote_dir_exists(cls, smbclient_module, host: str, remote_dir: str) -> bool:
        try:
            normalized_remote_dir = remote_dir.strip('/').replace('/', '\\')
            return smbclient_module.path.isdir(
                f"\\\\{host}\\{cls.SMB_SHARE}\\{normalized_remote_dir}"
            )
        except Exception:
            return False

    @classmethod
    def _unc_path(cls, host: str, relative_path: str = "") -> str:
        normalized_relative = relative_path.strip('/').replace('/', '\\')
        if not normalized_relative:
            return f"\\\\{host}\\{cls.SMB_SHARE}"
        return f"\\\\{host}\\{cls.SMB_SHARE}\\{normalized_relative}"

    def _resolve_remote_test_dir(self, smbclient_module, host: str):
        candidates = [
            "RetroBat/bios",
            "Retrobat/bios",
            "MiSTer/Archie",
            "MiSTer/Archimedes",
        ]

        for candidate in candidates:
            if self._assert_remote_dir_exists(smbclient_module, host, candidate):
                return candidate

        root_unc = self._unc_path(host)
        if smbclient_module.path.isdir(root_unc):
            return ""

        pytest.skip("No writable SMB directory found in TransFS share")

    def test_smb_write_read_delete_roundtrip(self):
        """Verify SMB share supports write, reread, and delete through Samba."""
        smbclient_module, host = self._connect()
        try:
            remote_dir = self._resolve_remote_test_dir(smbclient_module, host)
            filename = f"smb_roundtrip_{uuid4().hex}.bin"
            remote_file_path = f"{remote_dir}/{filename}" if remote_dir else filename
            unc_remote_file_path = self._unc_path(host, remote_file_path)
            payload = b"transfs-smb-roundtrip-test"

            with tempfile.TemporaryDirectory() as temp_dir:
                local_get_path = Path(temp_dir) / "get_payload.bin"

                with smbclient_module.open_file(
                    unc_remote_file_path,
                    mode="wb",
                    share_access="rwd",
                ) as remote_handle:
                    remote_handle.write(payload)

                try:
                    with smbclient_module.open_file(
                        unc_remote_file_path,
                        mode="rb",
                        share_access="rwd",
                    ) as remote_handle:
                        local_get_path.write_bytes(remote_handle.read())

                    assert local_get_path.exists(), "SMB retrieve did not create local output file"
                    assert local_get_path.read_bytes() == payload, "SMB readback payload mismatch"
                finally:
                    smbclient_module.remove(unc_remote_file_path)

                    assert not smbclient_module.path.exists(unc_remote_file_path), (
                        f"SMB test file still exists: {remote_file_path}"
                    )
        finally:
            try:
                smbclient_module.delete_session(host)
            except Exception:
                pass

    def test_smb_can_read_large_file_over_1mb(self):
        """Verify SMB layer can transfer files larger than 1MB without truncation."""
        smbclient_module, host = self._connect()
        try:
            remote_dir = self._resolve_remote_test_dir(smbclient_module, host)
            filename = f"smb_large_{uuid4().hex}.bin"
            remote_file_path = f"{remote_dir}/{filename}" if remote_dir else filename
            unc_remote_file_path = self._unc_path(host, remote_file_path)
            payload_size_bytes = 2 * 1024 * 1024
            expected_payload = os.urandom(payload_size_bytes)
            expected_hash = hashlib.sha256(expected_payload).hexdigest()

            with tempfile.TemporaryDirectory() as temp_dir:
                local_get_path = Path(temp_dir) / "large_get.bin"

                with smbclient_module.open_file(
                    unc_remote_file_path,
                    mode="wb",
                    share_access="rwd",
                ) as remote_handle:
                    remote_handle.write(expected_payload)

                try:
                    with smbclient_module.open_file(
                        unc_remote_file_path,
                        mode="rb",
                        share_access="rwd",
                    ) as remote_handle:
                        local_get_path.write_bytes(remote_handle.read())

                    assert local_get_path.exists(), "SMB retrieve did not produce large output file"
                    actual_size = local_get_path.stat().st_size
                    assert actual_size == payload_size_bytes, (
                        f"Large SMB read returned wrong size: {actual_size} != {payload_size_bytes}"
                    )

                    actual_hash = hashlib.sha256(local_get_path.read_bytes()).hexdigest()
                    assert actual_hash == expected_hash, "Large SMB readback hash mismatch"
                finally:
                    smbclient_module.remove(unc_remote_file_path)
        finally:
            try:
                smbclient_module.delete_session(host)
            except Exception:
                pass
