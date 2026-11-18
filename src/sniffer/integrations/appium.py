from __future__ import annotations

import json
import logging
import time
from contextlib import contextmanager
from urllib.request import urlopen

from sniffer.runtime import require_free_port
from sniffer.settings import Device, Platform

logger = logging.getLogger(__name__)


def wait_system_port(device: Device, timeout: float = 5) -> None:
    deadline = time.monotonic() + timeout
    announced = False
    while True:
        try:
            require_free_port("127.0.0.1", device.system_port, reuse_address=True)
            return
        except RuntimeError as error:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"Appium systemPort {device.system_port} remains occupied. "
                    "No process or ADB forward was removed. Inspect Appium sessions and "
                    f"'adb -s {device.adb_serial} forward --list' before retrying."
                ) from error
            if not announced:
                logger.info("Appium system_port=%s status=WAIT_RELEASE", device.system_port)
                announced = True
            time.sleep(0.2)

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
    wait_system_port(device)
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


@contextmanager
def session(device: Device, platform: Platform):
    """Close only the session created here; do not mask the primary UI error."""
    driver = connect(device, platform)
    failed = False
    try:
        yield driver
    except BaseException:
        failed = True
        raise
    finally:
        logger.info("Appium session_cleanup status=START system_port=%s", device.system_port)
        try:
            driver.quit()
        except Exception as error:
            logger.error("Appium session_cleanup status=FAILED error_type=%s", type(error).__name__)
            if not failed:
                raise RuntimeError(
                    "Appium session cleanup failed; inspect active sessions before retrying."
                ) from error
        else:
            logger.info("Appium session_cleanup status=END system_port=%s", device.system_port)
