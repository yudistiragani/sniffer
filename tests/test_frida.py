import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from sniffer.integrations.frida import Instrumentation


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
