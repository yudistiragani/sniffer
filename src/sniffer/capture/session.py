from __future__ import annotations

import time

from sniffer.device import resolve
from sniffer.executor import new_session
from sniffer.integrations.mitmproxy import ProxyCapture
from sniffer.runtime import atomic_json, lock
from sniffer.settings import Settings


def record(
    settings: Settings, device_name: str, platform: str, *, duration: int = 60, raw: bool = False
) -> dict:
    if platform not in {"instagram", "tiktok"} or platform not in settings.platforms:
        raise ValueError("Capture platform must be instagram or tiktok and have configuration.")
    device = resolve(settings, device_name)
    with lock(settings, f"device-{device_name}"):
        output = new_session(settings, platform, device_name, capture=True, raw=raw)
        try:
            with ProxyCapture(settings, device, output, raw=raw) as proxy:
                deadline = time.monotonic() + duration
                while time.monotonic() < deadline:
                    proxy.require_alive()
                    time.sleep(0.2)
        except (KeyboardInterrupt, SystemExit):
            atomic_json(output / "capture.stopped.json", {"reason": "operator_shutdown"})
            raise
        except BaseException as error:
            atomic_json(output / "failure.json", {"error_type": type(error).__name__})
            raise
        return {"output": str(output.resolve()), "duration": duration, "raw": raw}
