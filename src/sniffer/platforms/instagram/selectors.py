from __future__ import annotations

import time
from collections.abc import Callable


def wait_for(
    driver, candidates: list[tuple[str, str]], timeout: float = 20, *,
    name: str = "UI element", checkpoint: Callable[[], None] = lambda: None,
):
    if not candidates:
        raise ValueError(f"Missing selectors for {name}; configure the platform's candidates.")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for strategy, value in candidates:
            checkpoint()
            for element in driver.find_elements(strategy, value):
                if element.is_displayed():
                    return element
        time.sleep(0.3)
    raise RuntimeError(
        f"Instagram {name} not found; verify version, language, login, and selectors."
    )
