from __future__ import annotations

import time


def wait_for(driver, candidates: list[tuple[str, str]], timeout: float = 20):
    if not candidates:
        raise ValueError("Missing selectors; configure the platform's selector candidates.")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for strategy, value in candidates:
            for element in driver.find_elements(strategy, value):
                if element.is_displayed():
                    return element
        time.sleep(0.3)
    raise RuntimeError("Instagram UI element not found; verify version, language, login, selectors.")
