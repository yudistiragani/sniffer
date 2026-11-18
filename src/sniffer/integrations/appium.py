from __future__ import annotations

import json
from urllib.request import urlopen

from sniffer.runtime import require_free_port
from sniffer.settings import Device, Platform


def status(url: str) -> bool:
    try:
        with urlopen(url.rstrip("/") + "/status", timeout=3) as response:
            return json.load(response).get("value", {}).get("ready") is True
    except Exception:
        return False


def connect(device: Device, platform: Platform):
    try:
        from appium import webdriver
        from appium.options.android import UiAutomator2Options
    except ImportError as error:
        raise RuntimeError("Install automation support: uv sync --extra automation") from error
    require_free_port("127.0.0.1", device.system_port)
    options = UiAutomator2Options().load_capabilities({
        "platformName": "Android",
        "appium:automationName": "UiAutomator2",
        "appium:udid": device.adb_serial,
        "appium:appPackage": platform.package,
        "appium:noReset": True,
        "appium:fullReset": False,
        "appium:autoLaunch": False,
        "appium:forceAppLaunch": False,
        "appium:shouldTerminateApp": False,
        "appium:systemPort": device.system_port,
        "appium:newCommandTimeout": 120,
    })
    return webdriver.Remote(device.appium_url, options=options)
