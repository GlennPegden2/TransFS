"""Unit tests for runtime port resolution behavior."""

from app import config as config_module


def test_resolve_runtime_ports_prefers_standard_ports_when_available(monkeypatch):
    """Preferred ports should be used when available and auto-claim is enabled."""
    monkeypatch.setattr(config_module, "_is_bind_available", lambda _host, _port: True)

    app_config = {
        "runtime": {"enable_port_auto_claim": True},
        "web_api": {"host": "0.0.0.0", "preferred_port": 8000, "fallback_ports": [8001, 8080]},
        "smb": {"preferred_port": 445, "fallback_ports": [3445, 1445]},
    }

    resolved = config_module.resolve_runtime_ports(app_config=app_config)

    assert resolved["web_api"]["allocated_port"] == 8000
    assert resolved["web_api"]["warning_nonstandard_port"] is False
    assert resolved["smb"]["allocated_port"] == 445
    assert resolved["smb"]["warning_nonstandard_port"] is False


def test_resolve_runtime_ports_falls_back_and_warns_on_conflict(monkeypatch):
    """When preferred ports are unavailable, first available fallback should be selected."""

    def fake_bind_available(_host, port):
        return port in {8001, 3445}

    monkeypatch.setattr(config_module, "_is_bind_available", fake_bind_available)

    app_config = {
        "runtime": {"enable_port_auto_claim": True},
        "web_api": {"host": "0.0.0.0", "preferred_port": 8000, "fallback_ports": [8001, 8080]},
        "smb": {"preferred_port": 445, "fallback_ports": [3445, 1445]},
    }

    resolved = config_module.resolve_runtime_ports(app_config=app_config)

    assert resolved["web_api"]["allocated_port"] == 8001
    assert resolved["web_api"]["warning_nonstandard_port"] is True
    assert resolved["web_api"]["conflicts_detected"] == [8000]

    assert resolved["smb"]["allocated_port"] == 3445
    assert resolved["smb"]["warning_nonstandard_port"] is True
    assert resolved["smb"]["conflicts_detected"] == [445]


def test_resolve_runtime_ports_respects_strict_standard_port(monkeypatch):
    """Strict mode should emit allocation error when preferred port is occupied."""
    monkeypatch.setattr(config_module, "_is_bind_available", lambda _host, _port: False)

    app_config = {
        "runtime": {"enable_port_auto_claim": True},
        "smb": {
            "preferred_port": 445,
            "fallback_ports": [3445, 1445],
            "strict_standard_port": True,
        },
    }

    resolved = config_module.resolve_runtime_ports(app_config=app_config)
    smb = resolved["smb"]

    assert smb["allocated_port"] == 445
    assert "strict_standard_port is enabled" in (smb["allocation_error"] or "")
