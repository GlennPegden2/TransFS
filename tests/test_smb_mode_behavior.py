"""Unit tests for smb.mode normalization and ownership gates."""

from app import smb_config


def test_get_smb_mode_defaults_to_transfs_managed():
    """Missing mode should preserve legacy behavior."""
    assert smb_config.get_smb_mode({}) == "transfs_managed"


def test_get_smb_mode_normalizes_invalid_to_default():
    """Unknown mode values should safely default to transfs_managed."""
    assert smb_config.get_smb_mode({"smb": {"mode": "not-real"}}) == "transfs_managed"


def test_is_samba_managed_by_transfs_for_retronas_mode():
    """RetroNAS-managed mode should not trigger Samba management by TransFS."""
    assert smb_config.is_samba_managed_by_transfs({"smb": {"mode": "retronas_managed"}}) is False


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
