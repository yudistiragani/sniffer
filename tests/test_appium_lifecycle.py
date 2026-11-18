import logging
import socket
from unittest.mock import MagicMock

import pytest

from sniffer.integrations import appium
from sniffer.runtime import require_free_port


def test_system_port_tolerates_brief_cleanup_delay(settings, monkeypatch, caplog):
    probe = MagicMock(side_effect=[RuntimeError("busy"), None])
    monkeypatch.setattr(appium, "require_free_port", probe)
    monkeypatch.setattr(appium.time, "sleep", lambda _: None)
    with caplog.at_level(logging.INFO):
        appium.wait_system_port(settings.devices["android01"])
    assert probe.call_count == 2
    probe.assert_called_with("127.0.0.1", 8201, reuse_address=True)
    assert "status=WAIT_RELEASE" in caplog.text


def test_system_port_timeout_has_non_destructive_diagnostics(settings, monkeypatch):
    monkeypatch.setattr(appium, "require_free_port", MagicMock(side_effect=RuntimeError("busy")))
    with pytest.raises(RuntimeError, match="No process or ADB forward was removed") as error:
        appium.wait_system_port(settings.devices["android01"], timeout=0)
    assert "forward --list" in str(error.value) and "8201" in str(error.value)


def test_reusable_bind_still_rejects_an_active_listener():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        with pytest.raises(RuntimeError, match="unavailable"):
            require_free_port("127.0.0.1", port, reuse_address=True)


def test_session_quits_once_on_success(settings, monkeypatch, caplog):
    driver = MagicMock()
    monkeypatch.setattr(appium, "connect", lambda *_: driver)
    with caplog.at_level(logging.INFO), appium.session(
        settings.devices["android01"], settings.platforms["instagram"]
    ) as current:
        assert current is driver
    driver.quit.assert_called_once()
    assert "session_cleanup status=END" in caplog.text


def test_cleanup_failure_does_not_mask_primary_ui_error(settings, monkeypatch, caplog):
    driver = MagicMock()
    driver.quit.side_effect = RuntimeError("private cleanup detail")
    monkeypatch.setattr(appium, "connect", lambda *_: driver)
    with caplog.at_level(logging.ERROR), pytest.raises(ValueError, match="primary"):
        with appium.session(settings.devices["android01"], settings.platforms["instagram"]):
            raise ValueError("primary")
    assert "session_cleanup status=FAILED" in caplog.text
    assert "private cleanup detail" not in caplog.text


def test_cleanup_failure_does_not_mark_success(settings, monkeypatch):
    driver = MagicMock()
    driver.quit.side_effect = RuntimeError("private cleanup detail")
    monkeypatch.setattr(appium, "connect", lambda *_: driver)
    with pytest.raises(RuntimeError, match="session cleanup failed"):
        with appium.session(settings.devices["android01"], settings.platforms["instagram"]):
            pass


def test_failed_connect_does_not_quit_some_other_session(settings, monkeypatch):
    monkeypatch.setattr(appium, "connect", MagicMock(side_effect=RuntimeError("connect failed")))
    with pytest.raises(RuntimeError, match="connect failed"):
        with appium.session(settings.devices["android01"], settings.platforms["instagram"]):
            pytest.fail("must not enter")
