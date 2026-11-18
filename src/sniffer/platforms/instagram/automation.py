from __future__ import annotations

import time
from collections.abc import Callable

from sniffer.automation.gestures import scroll_up
from sniffer.jobs import SearchJob
from sniffer.platforms.instagram.selectors import wait_for
from sniffer.settings import Platform


def search(driver, config: Platform, job: SearchJob, checkpoint: Callable[[], None]) -> dict:
    # The operator must log in beforehand. Never automate credential entry.
    checkpoint()
    wait_for(driver, config.selectors.get("search_tab", [])).click()
    field = wait_for(driver, config.selectors.get("search_input", []))
    field.click()
    field.clear()
    field.send_keys(job.keyword)
    driver.press_keycode(66)  # Android ENTER: submit rather than only loading typeahead.
    wait_for(driver, config.selectors.get("results", []))
    for _ in range(job.scroll_count):
        checkpoint()
        scroll_up(driver)
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
