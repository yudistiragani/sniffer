import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sniffer.device import configure, register, registry, resolve
from sniffer.jobs import SearchJob
from sniffer.runtime import atomic_json, lock
from sniffer.settings import Device, Settings, load_settings, safe_name


@pytest.mark.parametrize("value", ["../escape", ".", "", "a/b", "hello world", "-flag"])
def test_reject_unsafe_names(value):
    with pytest.raises(ValueError):
        safe_name(value)


@pytest.mark.parametrize("value", ["android01", "manual-1", "job_001.json"])
def test_accept_names(value):
    assert safe_name(value) == value


def test_load_existing_inventory():
    settings = load_settings(Path("config/example.yaml"))
    assert settings.devices["android01"].adb_serial == "127.0.0.1:5555"
    assert settings.devices["android02"].adb_serial == "127.0.0.1:5556"


def test_env_override(monkeypatch):
    monkeypatch.setenv("SNIFFER_BEANSTALK_PORT", "11400")
    assert load_settings().beanstalk.port == 11400


def test_missing_config(tmp_path):
    with pytest.raises(ValueError):
        load_settings(tmp_path / "missing.yaml")


def test_duplicate_ports_rejected():
    with pytest.raises(ValidationError):
        Settings(devices={"a": Device(adb_serial="a"), "b": Device(adb_serial="b")})


@pytest.mark.parametrize("changes", [
    {"keyword": ""}, {"scroll_count": -1}, {"scroll_count": 101},
    {"job_id": "../x"}, {"action": "shell"}, {"script": "/tmp/x"},
    {"schema_version": 2}, {"keyword": "   "},
])
def test_invalid_job(changes):
    payload = {"job_id": "job-1", "keyword": "coffee", **changes}
    with pytest.raises(ValidationError):
        SearchJob.model_validate(payload)


def test_atomic_write_and_device_registry(settings):
    register(settings, "android03", Device(
        adb_serial="127.0.0.1:5557", system_port=8203, proxy_port=8083
    ), ownership="adopted")
    assert resolve(settings, "android03").proxy_port == 8083
    with pytest.raises(ValueError):
        register(settings, "android01", Device(adb_serial="x"))
    with pytest.raises(ValueError):
        register(settings, "duplicate", Device(adb_serial="127.0.0.1:5555"))
    path = settings.state_dir / "test.json"
    atomic_json(path, {"one": 1})
    atomic_json(path, {"two": 2})
    assert json.loads(path.read_text()) == {"two": 2}


def test_device_lock_excludes_other_owner(settings):
    from filelock import Timeout
    with lock(settings, "device-android01"):
        with pytest.raises(Timeout), lock(settings, "device-android01"):
            pass


def test_configure_preserves_managed_identity(settings):
    register(settings, "android03", Device(
        adb_serial="127.0.0.1:5557", system_port=8203, proxy_port=8083
    ), ownership="managed", container_id="immutable-id")
    configure(settings, "android03", {"frida_endpoint": "127.0.0.1:27042"})
    entry = registry(settings)["android03"]
    assert entry["ownership"] == "managed" and entry["container_id"] == "immutable-id"
    assert resolve(settings, "android03").frida_endpoint == "127.0.0.1:27042"
    with pytest.raises(ValueError):
        configure(settings, "android03", {"adb_serial": "different"})
    with pytest.raises(ValueError):
        configure(settings, "android03", {"proxy_port": 8081})
    with pytest.raises(ValueError, match="YAML"):
        configure(settings, "android01", {"proxy_port": 8099})
