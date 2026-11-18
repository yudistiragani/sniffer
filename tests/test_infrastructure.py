import json
from types import SimpleNamespace

import pytest

from sniffer.device import register
from sniffer.integrations import redroid
from sniffer.settings import Device


def test_create_rejects_existing_before_docker_create(settings, monkeypatch):
    monkeypatch.setattr(redroid.platform, "system", lambda: "Linux")
    calls = []
    monkeypatch.setattr(redroid, "run", lambda args, **kwargs: calls.append(args))
    with pytest.raises(ValueError, match="existing"):
        redroid.create(settings, "android01", "custom:magisk", 5557, 8203, 8083)
    assert calls == []


def test_create_does_not_run_on_windows(settings, monkeypatch):
    monkeypatch.setattr(redroid.platform, "system", lambda: "Windows")
    with pytest.raises(RuntimeError, match="Linux"):
        redroid.create(settings, "android03", "custom:magisk", 5557, 8203, 8083)


def test_create_only_creates_with_private_adb_and_persistent_data(settings, monkeypatch):
    monkeypatch.setattr(redroid.platform, "system", lambda: "Linux")
    monkeypatch.setattr(redroid, "inspect_container", lambda _: None)
    monkeypatch.setattr(redroid, "require_free_port", lambda *_: None)
    calls = []
    def fake(args, **_):
        calls.append(args)
        return SimpleNamespace(stdout="new-id\n", returncode=0)
    monkeypatch.setattr(redroid, "run", fake)
    result = redroid.create(settings, "android03", "custom:magisk", 5557, 8203, 8083)
    command = next(c for c in calls if c[1] == "create")
    assert "127.0.0.1:5557:5555" in command
    assert "--privileged" in command and "--mount" in command
    assert "--rm" not in command and "--pull" not in command
    assert all(c[1] not in {"start", "run", "pull"} for c in calls)
    assert result["started"] is False
    assert json.loads((settings.state_dir / "devices.json").read_text())["android03"]["ownership"] == "managed"


def test_create_never_reuses_data(settings, monkeypatch):
    monkeypatch.setattr(redroid.platform, "system", lambda: "Linux")
    monkeypatch.setattr(redroid, "inspect_container", lambda _: None)
    monkeypatch.setattr(redroid, "require_free_port", lambda *_: None)
    monkeypatch.setattr(redroid, "run", lambda *_: SimpleNamespace(stdout="{}", returncode=0))
    (settings.redroid.data_dir / "android03").mkdir(parents=True)
    with pytest.raises(ValueError, match="data directory"):
        redroid.create(settings, "android03", "custom:magisk", 5557, 8203, 8083)


@pytest.mark.parametrize("operation", ["start", "stop", "destroy"])
def test_adopted_lifecycle_protected(settings, operation, monkeypatch):
    monkeypatch.setattr(redroid, "run", lambda *_: pytest.fail("must not call Docker"))
    with pytest.raises(ValueError, match="restricted"):
        redroid.lifecycle(settings, "android01", operation)


def test_destroy_managed_preserves_data(settings, monkeypatch):
    register(settings, "android03", Device(
        adb_serial="127.0.0.1:5557", container="android03", system_port=8203, proxy_port=8083
    ), ownership="managed", container_id="immutable-id")
    actual = {
        "Id": "immutable-id", "Name": "/android03", "State": {"Running": False},
        "Config": {"Labels": {redroid.LABEL: "true"}},
    }
    monkeypatch.setattr(redroid, "inspect_container", lambda _: actual)
    calls = []
    monkeypatch.setattr(redroid, "run", lambda args: calls.append(args))
    redroid.lifecycle(settings, "android03", "destroy")
    assert calls == [["docker", "rm", "immutable-id"]]
    assert json.loads((settings.state_dir / "devices.json").read_text()) == {}


def test_destroy_requires_stop_and_exact_identity(settings, monkeypatch):
    register(settings, "android03", Device(
        adb_serial="127.0.0.1:5557", container="android03", system_port=8203, proxy_port=8083
    ), ownership="managed", container_id="immutable-id")
    actual = {
        "Id": "immutable-id", "Name": "/android03", "State": {"Running": True},
        "Config": {"Labels": {redroid.LABEL: "true"}},
    }
    monkeypatch.setattr(redroid, "inspect_container", lambda _: actual)
    with pytest.raises(ValueError, match="Stop"):
        redroid.lifecycle(settings, "android03", "destroy")
    actual["Id"] = "different"
    with pytest.raises(ValueError, match="identity"):
        redroid.lifecycle(settings, "android03", "destroy")


def test_stf_start_existing_only(settings, monkeypatch):
    monkeypatch.setattr(redroid, "stf_containers", lambda _: [
        {"ID": "running", "State": "running"},
        {"ID": "stopped", "State": "exited"},
    ])
    calls = []
    monkeypatch.setattr(redroid, "run", lambda args: calls.append(args))
    assert redroid.start_stf(settings) == 1
    assert calls == [["docker", "start", "stopped"]]
