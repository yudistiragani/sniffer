from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sniffer.integrations.frida_server import WorkerFridaServer


def test_uses_existing_endpoint_without_device_mutation(monkeypatch):
    device = SimpleNamespace(
        adb_serial="synthetic", frida_endpoint="127.0.0.1:27052", frida_server_path=None,
    )
    adb = MagicMock()
    monkeypatch.setattr("sniffer.integrations.frida_server.ADB", lambda *_: adb)
    server = WorkerFridaServer(device)
    monkeypatch.setattr(server, "_reachable", lambda: True)
    server.ensure_ready()
    adb.command.assert_not_called()
    server.close()
    adb.command.assert_not_called()


def test_starts_configured_server_once_and_stops_only_owned_pid(monkeypatch):
    device = SimpleNamespace(
        adb_serial="synthetic", frida_endpoint="127.0.0.1:27052",
        frida_server_path="/data/local/tmp/frida-server",
    )
    adb = MagicMock()
    adb.command.side_effect = [
        SimpleNamespace(returncode=1, stdout=""),  # pidof
        SimpleNamespace(returncode=0, stdout=""),  # executable
        SimpleNamespace(returncode=0, stdout="987\n"),  # launch PID
        SimpleNamespace(returncode=0, stdout="/data/local/tmp/frida-server --listen=127.0.0.1:27052"),
        SimpleNamespace(returncode=0, stdout=""),  # SIGTERM owned PID
        SimpleNamespace(returncode=1, stdout=""),  # process exited
    ]
    monkeypatch.setattr("sniffer.integrations.frida_server.ADB", lambda *_: adb)
    server = WorkerFridaServer(device)
    states = iter([False, True])
    monkeypatch.setattr(server, "_reachable", lambda: next(states))
    server.ensure_ready()
    assert server.started
    assert server.owned_pid == 987
    assert adb.command.call_args_list[2].args == (
        "shell",
        "'/data/local/tmp/frida-server' --listen=127.0.0.1:27052 "
        ">/dev/null 2>&1 </dev/null & echo $!",
    )
    server.close()
    assert server.owned_pid is None
    assert adb.command.call_args_list[4].args == ("shell", "kill", "987")


def test_existing_server_process_is_never_restarted(monkeypatch):
    device = SimpleNamespace(
        adb_serial="synthetic", frida_endpoint="127.0.0.1:27052",
        frida_server_path="/data/local/tmp/frida-server",
    )
    adb = MagicMock()
    adb.command.return_value = SimpleNamespace(returncode=0, stdout="111 222")
    monkeypatch.setattr("sniffer.integrations.frida_server.ADB", lambda *_: adb)
    server = WorkerFridaServer(device)
    monkeypatch.setattr(server, "_reachable", lambda: False)
    with pytest.raises(RuntimeError, match="no existing process"):
        server.ensure_ready()
    adb.command.assert_called_once_with("shell", "pidof", "frida-server", check=False)


@pytest.mark.parametrize("path", [
    None, "relative/frida-server", "/data/frida-server;pm clear",
    "/data/../tmp/frida-server",
])
def test_missing_or_unsafe_server_binary_never_starts(path, monkeypatch):
    device = SimpleNamespace(
        adb_serial="synthetic", frida_endpoint="127.0.0.1:27052",
        frida_server_path=path,
    )
    adb = MagicMock()
    adb.command.return_value = SimpleNamespace(returncode=1, stdout="")
    monkeypatch.setattr("sniffer.integrations.frida_server.ADB", lambda *_: adb)
    server = WorkerFridaServer(device)
    monkeypatch.setattr(server, "_reachable", lambda: False)
    with pytest.raises(RuntimeError):
        server.ensure_ready()
    assert all(call.args[:3] != ("shell", "sh", "-c") for call in adb.command.call_args_list)


def test_cleanup_skips_pid_if_identity_changed(monkeypatch):
    device = SimpleNamespace(
        adb_serial="synthetic", frida_endpoint="127.0.0.1:27052",
        frida_server_path="/data/local/tmp/frida-server",
    )
    adb = MagicMock()
    adb.command.return_value = SimpleNamespace(returncode=0, stdout="/system/bin/other")
    monkeypatch.setattr("sniffer.integrations.frida_server.ADB", lambda *_: adb)
    server = WorkerFridaServer(device)
    server.owned_pid = 987
    server.close()
    adb.command.assert_called_once_with("shell", "cat", "/proc/987/cmdline", check=False)


def test_cleanup_accepts_frida_process_title_with_only_executable(monkeypatch):
    device = SimpleNamespace(
        adb_serial="synthetic", frida_endpoint="127.0.0.1:27052",
        frida_server_path="/data/local/tmp/frida-server",
    )
    adb = MagicMock()
    adb.command.side_effect = [
        SimpleNamespace(returncode=0, stdout="/data/local/tmp/frida-server"),
        SimpleNamespace(returncode=0, stdout=""),
        SimpleNamespace(returncode=1, stdout=""),
    ]
    monkeypatch.setattr("sniffer.integrations.frida_server.ADB", lambda *_: adb)
    server = WorkerFridaServer(device)
    server.owned_pid = 987
    server.close()
    assert adb.command.call_args_list[1].args == ("shell", "kill", "987")
