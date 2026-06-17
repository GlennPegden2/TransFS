import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import api


def _mount_entry(filestore: Path) -> dict:
    return {
        "id": "3do-nas",
        "display_name": "3DO on nas",
        "mount_type": "cifs",
        "enabled": True,
        "target_subpath": "Systems/3DO/3DO/Software/Collections/RetroRom-Collection",
        "smb_host": "192.168.95.19",
        "smb_share": "software",
        "smb_subpath": "3do/RetroRom-Collection",
        "guest": False,
        "read_only": False,
        "vers": "3.0",
        "auto_reconnect": True,
        "extra_options": [],
        "username": "glenn",
        "credentials_file": str(filestore / ".secrets" / "transfs" / "native-mounts" / "3do-nas.cred"),
        "last_error": "",
        "last_ok": 0,
        "last_checked": 0,
    }


def _patch_empty_mountinfo(monkeypatch):
    original_open = open

    def fake_open(path, *args, **kwargs):
        if path == "/proc/self/mountinfo":
            return io.StringIO("")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr("builtins.open", fake_open)


def test_browse_native_bridge_reports_failed_descendant_mount(monkeypatch, tmp_path):
    filestore = tmp_path / "filestore"
    systems_dir = filestore / "Native" / "Systems"
    (systems_dir / "3DO").mkdir(parents=True)
    mountpoint = tmp_path / "transfs"
    mountpoint.mkdir()
    app_config = {
        "filestore": str(filestore),
        "mountpoint": str(mountpoint),
        "native_external_mounts": [_mount_entry(filestore)],
    }

    monkeypatch.setattr(api, "read_app_config", lambda: app_config)
    monkeypatch.setattr(api, "get_mount_status", lambda config, entry: {"mounted": False})
    _patch_empty_mountinfo(monkeypatch)

    result = api.api_browse_directory(str(systems_dir))

    entry = next(item for item in result["entries"] if item["name"] == "3DO")
    assert entry["is_mount"] is False
    assert entry["mount_kind"] == "descendant"
    assert entry["mount_state"] == "failed"
    assert entry["mount_source"] == "//192.168.95.19/software/3do/RetroRom-Collection"
    assert "Missing credentials file" in entry["mount_error"]


def test_browse_native_bridge_reports_mounted_descendant_mount(monkeypatch, tmp_path):
    filestore = tmp_path / "filestore"
    systems_dir = filestore / "Native" / "Systems"
    (systems_dir / "3DO").mkdir(parents=True)
    mountpoint = tmp_path / "transfs"
    mountpoint.mkdir()
    app_config = {
        "filestore": str(filestore),
        "mountpoint": str(mountpoint),
        "native_external_mounts": [_mount_entry(filestore)],
    }

    monkeypatch.setattr(api, "read_app_config", lambda: app_config)
    monkeypatch.setattr(api, "get_mount_status", lambda config, entry: {"mounted": True})
    _patch_empty_mountinfo(monkeypatch)

    result = api.api_browse_directory(str(systems_dir))

    entry = next(item for item in result["entries"] if item["name"] == "3DO")
    assert entry["is_mount"] is True
    assert entry["mount_kind"] == "descendant"
    assert entry["mount_state"] == "mounted"
    assert entry["mount_source"] == "//192.168.95.19/software/3do/RetroRom-Collection"
    assert entry["mount_error"] is None