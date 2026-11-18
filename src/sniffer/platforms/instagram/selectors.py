from __future__ import annotations

import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


def is_stale(error: Exception) -> bool:
    # Keep offline imports independent of the optional Selenium/Appium extra.
    return any(cls.__name__ == "StaleElementReferenceException" for cls in type(error).__mro__)


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
            try:
                for element in driver.find_elements(strategy, value):
                    if element.is_displayed():
                        return element
            except Exception as error:
                if not is_stale(error):
                    raise
                logger.info("IG selector=%s status=STALE_RELOOKUP", name)
        time.sleep(0.3)
    raise RuntimeError(
        f"Instagram {name} not found; verify version, language, login, and selectors."
    )


def interact(
    driver, candidates: list[tuple[str, str]], action: Callable, *,
    name: str, checkpoint: Callable[[], None], initial=None, attempts: int = 3,
):
    """Reacquire on stale only. The action must be safe to replay as a whole."""
    if attempts < 1:
        raise ValueError("Interaction attempts must be positive.")
    for attempt in range(attempts):
        checkpoint()
        element = initial if attempt == 0 and initial is not None else wait_for(
            driver, candidates, name=name, checkpoint=checkpoint,
        )
        try:
            action(element)
            checkpoint()
            return element
        except Exception as error:
            if not is_stale(error) or attempt + 1 == attempts:
                raise
            logger.warning(
                "IG step=%s status=STALE_RETRY next_attempt=%s/%s",
                name, attempt + 2, attempts,
            )
            checkpoint()
            time.sleep(0.2)
