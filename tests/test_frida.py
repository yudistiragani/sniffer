import json
import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sniffer.integrations.frida import Instrumentation, safe_attach_detail


@pytest.fixture(autouse=True)
def mock_adb_pid(monkeypatch):
    adb = MagicMock()
    adb.command.return_value = SimpleNamespace(returncode=0, stdout="123\n")
    monkeypatch.setattr("sniffer.integrations.frida.ADB", lambda _: adb)
    return adb


def test_frida_requires_explicit_target_and_configured_scripts(settings, monkeypatch, tmp_path):
    manager = MagicMock()
    monkeypatch.setitem(sys.modules, "frida", SimpleNamespace(get_device_manager=lambda: manager))
    device = settings.devices["android01"]
    config = settings.platforms["instagram"]
    with pytest.raises(ValueError, match="no frida_scripts"):
        with Instrumentation(device, config, tmp_path):
            pass
    config.frida_scripts = ["shared/observe.js"]
    with pytest.raises(ValueError, match="explicitly"):
        with Instrumentation(device, config, tmp_path):
            pass
    manager.add_remote_device.assert_not_called()


def test_frida_attach_load_and_detach_without_killing_existing_app(settings, monkeypatch, tmp_path):
    target = MagicMock()
    target.enumerate_applications.return_value = [
        SimpleNamespace(identifier="com.instagram.android", pid=123)
    ]
    manager = MagicMock()
    manager.add_remote_device.return_value = target
    monkeypatch.setitem(sys.modules, "frida", SimpleNamespace(get_device_manager=lambda: manager))
    device = settings.devices["android01"]
    device.frida_endpoint = "127.0.0.1:27042"
    config = settings.platforms["instagram"]
    config.frida_scripts = ["shared/observe.js"]
    with Instrumentation(device, config, tmp_path):
        target.attach.assert_called_once_with(123)
        target.attach.return_value.create_script.return_value.load.assert_called_once()
    target.attach.return_value.detach.assert_called_once()
    target.kill.assert_not_called()
    target.spawn.assert_not_called()


def test_frida_script_cannot_escape_packaged_directory(settings, monkeypatch, tmp_path):
    target = MagicMock()
    target.enumerate_applications.return_value = [
        SimpleNamespace(identifier="com.instagram.android", pid=123)
    ]
    manager = MagicMock()
    manager.add_remote_device.return_value = target
    monkeypatch.setitem(sys.modules, "frida", SimpleNamespace(get_device_manager=lambda: manager))
    device = settings.devices["android01"]
    device.frida_endpoint = "127.0.0.1:27042"
    config = settings.platforms["instagram"]
    config.frida_scripts = ["../../outside.js"]
    with pytest.raises(ValueError, match="inside"):
        with Instrumentation(device, config, tmp_path):
            pass
    target.attach.return_value.detach.assert_called_once()
    target.attach.return_value.create_script.assert_not_called()


def test_script_error_and_detach_fail_health(settings, tmp_path, caplog):
    instrumentation = Instrumentation(
        settings.devices["android01"], settings.platforms["instagram"], tmp_path
    )
    with caplog.at_level("ERROR"):
        instrumentation._message({"type": "error", "description": "private detail"}, None)
    with pytest.raises(RuntimeError, match="script error"):
        instrumentation.check()
    assert "private detail" not in caplog.text
    instrumentation.failure = None
    instrumentation._detached("process-terminated")
    with pytest.raises(RuntimeError, match="detached"):
        instrumentation.check()


def test_console_logs_event_name_not_payload(settings, tmp_path, caplog):
    instrumentation = Instrumentation(
        settings.devices["android01"], settings.platforms["instagram"], tmp_path
    )
    with caplog.at_level("INFO"):
        instrumentation._message({
            "type": "send",
            "payload": {"event": "tls.call", "access_token": "private-token", "result": 1},
        }, b"binary data")
    assert "event=tls.call" in caplog.text and "private-token" not in caplog.text
    text = (tmp_path / "frida.jsonl").read_text()
    assert "private-token" not in text
    assert "binary data" not in text


def test_normal_cleanup_does_not_mark_unexpected_detach(settings, tmp_path):
    instrumentation = Instrumentation(
        settings.devices["android01"], settings.platforms["instagram"], tmp_path
    )
    instrumentation.session = MagicMock()
    instrumentation.session.detach.side_effect = lambda: instrumentation._detached("application-requested")
    instrumentation.__exit__(None, None, None)
    instrumentation.check()


def test_cleanup_error_preserves_primary_failure(settings, tmp_path):
    instrumentation = Instrumentation(
        settings.devices["android01"], settings.platforms["instagram"], tmp_path
    )
    instrumentation.session = MagicMock()
    instrumentation.session.detach.side_effect = RuntimeError("cleanup detail")
    instrumentation.__exit__(ValueError, ValueError("primary"), None)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        instrumentation.__exit__(None, None, None)


def test_persistence_failure_stops_instrumentation(settings, tmp_path, monkeypatch):
    instrumentation = Instrumentation(
        settings.devices["android01"], settings.platforms["instagram"], tmp_path
    )
    def disk_error(*_):
        raise OSError("disk unavailable")
    monkeypatch.setattr("sniffer.integrations.frida.append_json", disk_error)
    instrumentation._message({"type": "send", "payload": {"event": "tls.runtime"}}, None)
    with pytest.raises(RuntimeError, match="could not be saved"):
        instrumentation.check()


def test_ambiguous_pid_is_never_attached(settings, monkeypatch, tmp_path, mock_adb_pid):
    mock_adb_pid.command.return_value.stdout = "123 456"
    target, manager = MagicMock(), MagicMock()
    manager.add_remote_device.return_value = target
    monkeypatch.setitem(sys.modules, "frida", SimpleNamespace(get_device_manager=lambda: manager))
    settings.devices["android01"].frida_endpoint = "127.0.0.1:27052"
    settings.platforms["instagram"].frida_scripts = ["shared/tls_observer.js"]
    with pytest.raises(RuntimeError, match="ambiguous"):
        with Instrumentation(
            settings.devices["android01"], settings.platforms["instagram"], tmp_path
        ):
            pass
    target.attach.assert_not_called()
    target.spawn.assert_not_called()


def test_metadata_probe_never_spawns_if_app_not_running(settings, monkeypatch, tmp_path, mock_adb_pid):
    mock_adb_pid.command.return_value = SimpleNamespace(returncode=1, stdout="")
    target, manager = MagicMock(), MagicMock()
    manager.add_remote_device.return_value = target
    monkeypatch.setitem(sys.modules, "frida", SimpleNamespace(get_device_manager=lambda: manager))
    settings.devices["android01"].frida_endpoint = "127.0.0.1:27052"
    settings.platforms["instagram"].frida_scripts = ["shared/runtime_probe.js"]
    with pytest.raises(RuntimeError, match="not running"):
        with Instrumentation(
            settings.devices["android01"], settings.platforms["instagram"], tmp_path,
            realm="emulated", allow_spawn=False,
        ):
            pass
    target.spawn.assert_not_called()
    target.attach.assert_not_called()


def test_explicit_emulated_realm_is_forwarded(settings, monkeypatch, tmp_path):
    target, manager = MagicMock(), MagicMock()
    manager.add_remote_device.return_value = target
    monkeypatch.setitem(sys.modules, "frida", SimpleNamespace(get_device_manager=lambda: manager))
    settings.devices["android01"].frida_endpoint = "127.0.0.1:27052"
    settings.platforms["instagram"].frida_scripts = ["shared/runtime_probe.js"]
    with Instrumentation(
        settings.devices["android01"], settings.platforms["instagram"], tmp_path,
        realm="emulated", allow_spawn=False,
    ):
        pass
    target.attach.assert_called_once_with(123, realm="emulated")
    target.spawn.assert_not_called()


def test_inspect_returns_only_packaged_runtime_snapshot(settings, monkeypatch):
    import sniffer.integrations.frida as integration
    from sniffer.capture.writer import append_json
    observed = {}
    class FakeProbe:
        def __init__(self, device, config, output, **options):
            observed.update(options)
            observed["scripts"] = config.frida_scripts
            self.output = output
        def __enter__(self):
            append_json(self.output / "frida.jsonl", {
                "message": {"type": "send", "payload": {
                    "event": "tls.runtime_probe", "arch": "arm", "pointerSize": 4, "modules": [],
                }},
            })
            return self
        def check(self):
            pass
        def __exit__(self, *_):
            pass
    monkeypatch.setattr(integration, "Instrumentation", FakeProbe)
    monkeypatch.setattr(integration.time, "sleep", lambda _: None)
    result = integration.inspect_runtime(settings, "android01", "127.0.0.1:27052", "emulated", 1)
    assert result["runtime"]["arch"] == "arm"
    assert result["tls_verification_changed"] is False
    assert observed["allow_spawn"] is False
    assert observed["scripts"] == ["shared/runtime_probe.js"]
    assert settings.platforms["instagram"].frida_scripts == []


def test_inspect_rejects_invalid_realm_without_side_effects(settings):
    from sniffer.integrations.frida import inspect_runtime
    with pytest.raises(ValueError):
        inspect_runtime(settings, "android01", "127.0.0.1:27052", "auto")
    assert not settings.output_dir.exists()


def test_emulated_not_supported_has_safe_actionable_error(settings, monkeypatch, tmp_path):
    class NotSupportedError(Exception):
        pass
    target, manager = MagicMock(), MagicMock()
    manager.add_remote_device.return_value = target
    target.attach.side_effect = NotSupportedError("process is not using emulation")
    monkeypatch.setitem(sys.modules, "frida", SimpleNamespace(get_device_manager=lambda: manager))
    settings.devices["android01"].frida_endpoint = "127.0.0.1:27052"
    settings.platforms["instagram"].frida_scripts = ["shared/runtime_probe.js"]
    with pytest.raises(RuntimeError, match="could not expose the emulated realm"):
        with Instrumentation(
            settings.devices["android01"], settings.platforms["instagram"], tmp_path,
            realm="emulated", allow_spawn=False,
        ):
            pass
    target.spawn.assert_not_called()


def test_inspect_without_snapshot_is_not_success(settings, monkeypatch):
    import sniffer.integrations.frida as integration
    fake = MagicMock()
    monkeypatch.setattr(integration, "Instrumentation", fake)
    monkeypatch.setattr(integration.time, "sleep", lambda _: None)
    with pytest.raises(RuntimeError, match="no runtime snapshot"):
        integration.inspect_runtime(settings, "android01", "127.0.0.1:27052", "native", 1)
    assert list(settings.output_dir.glob("*/failure.json"))


@pytest.mark.parametrize("text,secrets", [
    ("RPC error password='private value'; token=private-token", ["private value", "private-token"]),
    ("RPC error Authorization: Bearer private-token", ["private-token"]),
    ("RPC ws://private-user:private-pass@127.0.0.1:27052", ["private-user", "private-pass"]),
    ("RPC 'client_secret': 'private-value'", ["private-value"]),
    ("RPC -----BEGIN PRIVATE KEY-----\nprivate-data\n-----END PRIVATE KEY-----", ["private-data"]),
])
def test_attach_error_detail_redacts_sensitive_values(text, secrets):
    detail = safe_attach_detail(RuntimeError(text))
    assert all(secret not in detail for secret in secrets)
    assert "[REDACTED" in detail


def test_attach_error_detail_is_bounded_and_printable():
    assert len(safe_attach_detail(RuntimeError("x" * 10000))) == 800
    assert "\n" not in safe_attach_detail(RuntimeError("RPC\nprotocol\x1b failure"))
    assert safe_attach_detail(RuntimeError("")) == "(no error detail)"


def test_protocol_error_is_actionable_without_loading_script(settings, monkeypatch, tmp_path):
    class ProtocolError(Exception):
        pass
    target, manager = MagicMock(), MagicMock()
    manager.add_remote_device.return_value = target
    target.attach.side_effect = ProtocolError("RPC channel closed while attaching")
    monkeypatch.setitem(sys.modules, "frida", SimpleNamespace(get_device_manager=lambda: manager))
    settings.devices["android01"].frida_endpoint = "127.0.0.1:27052"
    settings.platforms["instagram"].frida_scripts = ["shared/runtime_probe.js"]
    with pytest.raises(RuntimeError, match="RPC channel closed") as error:
        with Instrumentation(
            settings.devices["android01"], settings.platforms["instagram"], tmp_path,
            realm="emulated", allow_spawn=False,
        ):
            pass
    assert "ProtocolError" in str(error.value)
    recorded = json.loads((tmp_path / "frida-attach-error.json").read_text())
    assert recorded == {
        "phase": "attach", "realm": "emulated", "pid": 123,
        "error_type": "ProtocolError", "error_message": "RPC channel closed while attaching",
    }
    target.attach.assert_called_once_with(123, realm="emulated")
    target.attach.return_value.create_script.assert_not_called()
    target.spawn.assert_not_called()
