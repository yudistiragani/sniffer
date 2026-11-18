from __future__ import annotations

import logging
import time
from collections.abc import Callable

from sniffer.automation.gestures import scroll_up
from sniffer.jobs import SearchJob
from sniffer.platforms.instagram.selectors import wait_for
from sniffer.settings import Platform

logger = logging.getLogger(__name__)


def search(driver, config: Platform, job: SearchJob, checkpoint: Callable[[], None]) -> dict:
    # The operator must log in beforehand. Never automate credential entry.
    def step(name, action):
        checkpoint()
        started = time.monotonic()
        logger.info("IG step=%s status=START", name)
        try:
            result = action()
            checkpoint()
        except Exception as error:
            # Do not log the keyword, field text, page source, or raw exception message.
            logger.error("IG step=%s status=FAILED error_type=%s", name, type(error).__name__)
            raise
        logger.info("IG step=%s status=END duration=%.2fs", name, time.monotonic() - started)
        return result

    tab = step("search_tab.find", lambda: wait_for(
        driver, config.selectors.get("search_tab", []),
        name="search_tab", checkpoint=checkpoint,
    ))
    step("search_tab.click", tab.click)
    field = step("search_input.find", lambda: wait_for(
        driver, config.selectors.get("search_input", []),
        name="search_input", checkpoint=checkpoint,
    ))
    step("search_input.click", field.click)
    step("search_input.clear", field.clear)
    step("search_input.type", lambda: field.send_keys(job.keyword))
    # Android ENTER: submit rather than only loading typeahead.
    step("search_input.submit", lambda: driver.press_keycode(66))
    step("search_results.find", lambda: wait_for(
        driver, config.selectors.get("results", []),
        name="search_results", checkpoint=checkpoint,
    ))
    for index in range(job.scroll_count):
        step(f"search_results.scroll.{index + 1}", lambda: scroll_up(driver))
        # Short sleeps allow capture/lease health checks during dwell.
        deadline = time.monotonic() + job.scroll_pause_ms / 1000
        while time.monotonic() < deadline:
            checkpoint()
            time.sleep(min(0.2, max(0, deadline - time.monotonic())))
    checkpoint()
    return {
        "action": "search", "scrolls": job.scroll_count,
        "result_category": "default UI results; not semantically verified",
    }
