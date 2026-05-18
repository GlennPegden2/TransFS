"""Unit tests for smb.mode normalization and ownership gates."""

from app import smb_config


def test_get_smb_mode_defaults_to_transfs_managed():
    """Missing mode should preserve legacy behavior."""
    assert smb_config.get_smb_mode({}) == "transfs_managed"


def test_get_smb_mode_normalizes_invalid_to_default():
    """Unknown mode values should safely default to transfs_managed."""
    assert smb_config.get_smb_mode({"smb": {"mode": "not-real"}}) == "transfs_managed"


def test_get_smb_mode_accepts_custom():
    """custom is a valid mode and should be returned as-is."""
    assert smb_config.get_smb_mode({"smb": {"mode": "custom"}}) == "custom"


def test_get_smb_conf_path_default():
    """Standard modes return the default Samba path."""
    assert smb_config.get_smb_conf_path({}) == "/etc/samba/smb.conf"
    assert smb_config.get_smb_conf_path({"smb": {"mode": "transfs_managed"}}) == "/etc/samba/smb.conf"
    assert smb_config.get_smb_conf_path({"smb": {"mode": "retronas_managed"}}) == "/etc/samba/smb.conf"


def test_get_smb_conf_path_custom_with_path():
    """custom mode returns the user-specified path."""
    cfg = {"smb": {"mode": "custom", "conf_path": "/opt/mysamba/smb.conf"}}
    assert smb_config.get_smb_conf_path(cfg) == "/opt/mysamba/smb.conf"


def test_get_smb_conf_path_custom_fallback():
    """custom mode without conf_path falls back to the default path."""
    cfg = {"smb": {"mode": "custom"}}
    assert smb_config.get_smb_conf_path(cfg) == "/etc/samba/smb.conf"


def test_is_samba_managed_by_transfs_for_retronas_mode():
    """RetroNAS-managed mode should not trigger Samba management by TransFS."""
    assert smb_config.is_samba_managed_by_transfs({"smb": {"mode": "retronas_managed"}}) is False


def test_is_samba_managed_by_transfs_for_custom_mode():
    """custom mode should be treated as TransFS-managed (TransFS owns Samba config)."""
    assert smb_config.is_samba_managed_by_transfs({"smb": {"mode": "custom"}}) is True


def test_is_samba_managed_by_transfs_for_disabled_mode():
    """disabled mode should not trigger Samba management."""
    assert smb_config.is_samba_managed_by_transfs({"smb": {"mode": "disabled"}}) is False


def test_setup_samba_from_config_noops_when_retronas_managed(monkeypatch):
    """In retronas_managed mode, setup should return success without calling Samba setup routines."""
    calls = {"configure": 0, "update_conf": 0}

    def fake_configure(_username, _password):
        calls["configure"] += 1
        return True

    def fake_update_conf(*_args, **_kwargs):
        calls["update_conf"] += 1
        return True

    monkeypatch.setattr(smb_config, "configure_samba_user", fake_configure)
    monkeypatch.setattr(smb_config, "update_smb_conf_guest_access", fake_update_conf)

    result = smb_config.setup_samba_from_config({"smb": {"mode": "retronas_managed"}})

    assert result is True
    assert calls["configure"] == 0
    assert calls["update_conf"] == 0


def test_setup_samba_from_config_uses_custom_conf_path(monkeypatch, tmp_path):
    """custom mode should call update_smb_conf_guest_access with the user-specified path."""
    custom_conf = str(tmp_path / "smb.conf")
    received_paths = []

    def fake_update_conf(allow_guest, conf_path="/etc/samba/smb.conf"):
        received_paths.append(conf_path)
        return True

    monkeypatch.setattr(smb_config, "configure_samba_user", lambda *_: True)
    monkeypatch.setattr(smb_config, "update_smb_conf_guest_access", fake_update_conf)

    cfg = {"smb": {"mode": "custom", "conf_path": custom_conf, "username": "u", "password": "p"}}
    smb_config.setup_samba_from_config(cfg)

    assert received_paths == [custom_conf]
